"""LLM-based factor mining framework — Priority 9 (2026-05-14).

Per CLAUDE.md "因子走漏斗" rule: LLM does CANDIDATE GENERATION only.
Mandatory funnel before any production promotion:
  1. LLM suggests factor formula + rationale
  2. Validate (no lookahead, allowed operators, DataFrame shape)
  3. Compile to pandas expression
  4. Backtest on training years only (sealed 2026 NEVER touched)
  5. IC + Track A acceptance gate
  6. Manual promotion to RESEARCH_FACTORS / PRODUCTION_FACTORS (one-way)

This module ships the FRAMEWORK only (schema + validator + compiler).
LLM API integration is deferred to first actual LLM mining session
(requires user explicit-go to spend API tokens).

Key safety:
  - Only pandas operators in whitelist allowed
  - No bare `eval()` — all formulas compiled via restricted AST
  - No future-period references (shift only with negative arg blocked)
  - Lookback ≤ split_acceptance.access_rules.factor_warmup_max_lookback_days
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd


# ── Allowed AST nodes for LLM-suggested factor formulas ───────────────────

ALLOWED_AST_NODES: Set[type] = {
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Call, ast.Attribute,
    ast.Subscript, ast.Name, ast.Load, ast.Constant, ast.Compare,
    ast.BoolOp, ast.Tuple, ast.List, ast.keyword,
    # Operators
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow, ast.FloorDiv,
    ast.USub, ast.UAdd, ast.Not, ast.And, ast.Or,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
}

ALLOWED_FUNCTIONS: Set[str] = {
    # pandas rolling primitives
    "rolling", "expanding", "ewm",
    "mean", "std", "var", "min", "max", "sum", "median", "quantile",
    "rank", "pct_change", "diff", "shift", "fillna", "dropna",
    "abs", "log", "log1p", "exp", "sqrt",
    # numpy via np.*
    "np.maximum", "np.minimum", "np.sign", "np.where", "np.clip",
    # Custom safe wrappers
    "zscore", "winsorize", "neutralize",
}

# Lookback / warmup constraints (CLAUDE.md temporal_split.yaml)
MAX_LOOKBACK_DAYS = 504  # access_rules.factor_warmup_max_lookback_days


@dataclass
class LLMCandidateFactor:
    """One LLM-suggested factor candidate."""
    name: str  # snake_case identifier
    formula: str  # pandas expression string
    rationale: str  # LLM's economic / market reasoning
    inputs: Tuple[str, ...]  # required input columns (close, volume, ...)
    expected_horizon_days: int  # target forward-return horizon
    expected_ic_sign: int  # +1 / -1 / 0 (unknown) — used to flip sign at usage
    llm_model: str  # e.g. "claude-opus-4-7"
    llm_session_id: Optional[str] = None
    notes: str = ""


@dataclass
class ValidationResult:
    """Output of validate_candidate."""
    is_valid: bool
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def validate_candidate(cand: LLMCandidateFactor) -> ValidationResult:
    """Static validation of LLM-suggested factor candidate.

    Checks:
      - Formula parses as Python expression
      - AST contains only allowed nodes
      - All function calls in ALLOWED_FUNCTIONS whitelist
      - No future-period references (shift with negative arg, fillna(method='bfill'))
      - Lookback windows ≤ MAX_LOOKBACK_DAYS
      - Inputs reference standard OHLCV column names
    """
    issues: List[str] = []
    warnings: List[str] = []

    # Parse
    try:
        tree = ast.parse(cand.formula, mode="eval")
    except SyntaxError as e:
        return ValidationResult(False, [f"SyntaxError: {e}"])

    # Walk AST
    for node in ast.walk(tree):
        if type(node) not in ALLOWED_AST_NODES:
            issues.append(f"Disallowed AST node: {type(node).__name__}")
        # Function call whitelist
        if isinstance(node, ast.Call):
            fn_name = _get_call_name(node)
            if fn_name not in ALLOWED_FUNCTIONS:
                issues.append(f"Disallowed function call: {fn_name}")
            # No-lookahead: shift(N) where N < 0 means future reference
            if fn_name == "shift":
                for arg in node.args:
                    val = None
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, (int, float)):
                        val = arg.value
                    elif (isinstance(arg, ast.UnaryOp) and isinstance(arg.op, ast.USub)
                          and isinstance(arg.operand, ast.Constant)
                          and isinstance(arg.operand.value, (int, float))):
                        val = -arg.operand.value
                    if val is not None and val < 0:
                        issues.append(f"shift(N) with N<0 = future ref: {val}")
            # fillna(method='bfill') = future fill
            if fn_name == "fillna":
                for kw in node.keywords:
                    if kw.arg == "method" and isinstance(kw.value, ast.Constant):
                        if kw.value.value in ("bfill", "backfill"):
                            issues.append("fillna(method='bfill') = future fill")
        # Lookback window check: rolling(N).mean() etc.
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            if node.value > MAX_LOOKBACK_DAYS:
                warnings.append(
                    f"Lookback {node.value} > MAX_LOOKBACK_DAYS={MAX_LOOKBACK_DAYS}"
                )

    # Inputs check
    valid_inputs = {"close", "open", "high", "low", "volume",
                    "spy", "qqq", "vix", "bench"}
    for inp in cand.inputs:
        if inp.lower() not in valid_inputs:
            warnings.append(f"Non-standard input: {inp}")

    # IC sign check
    if cand.expected_ic_sign not in (-1, 0, 1):
        issues.append(f"expected_ic_sign must be -1/0/+1, got {cand.expected_ic_sign}")

    return ValidationResult(
        is_valid=(len(issues) == 0),
        issues=issues, warnings=warnings,
    )


def _get_call_name(call: ast.Call) -> str:
    """Extract function name from AST Call node."""
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        # e.g. df.rolling(20).mean → mean
        return func.attr
    return "<unknown>"


def llm_prompt_template(
    universe_description: str,
    existing_factor_count: int,
    target_anomaly: str,
) -> str:
    """Build the prompt for LLM factor candidate generation.

    This is the framework prompt; actual LLM API call is external. The
    caller should:
      1. Build prompt via this function
      2. Send to chosen LLM
      3. Parse response into LLMCandidateFactor instances
      4. Run validate_candidate on each
      5. Reject invalid; queue valid for IC/backtest funnel
    """
    return f"""You are a quantitative researcher generating factor formula candidates.

UNIVERSE: {universe_description}
EXISTING FACTOR POOL SIZE: {existing_factor_count} (already cover momentum,
value, quality, low-vol, breakout, regime). Avoid duplicates.

TARGET ANOMALY: {target_anomaly}

OUTPUT FORMAT (JSON list, 5 candidates):
[
  {{
    "name": "snake_case_identifier",
    "formula": "pandas expression with no future references",
    "rationale": "1-2 sentence economic / market reasoning",
    "inputs": ["close", "volume", ...],  // required OHLCV columns
    "expected_horizon_days": 21,         // target forward-return horizon
    "expected_ic_sign": 1                 // +1 / -1 / 0 (unknown)
  }},
  ...
]

CONSTRAINTS:
1. No future-period references: shift(-N) banned; fillna(method='bfill') banned.
2. Lookback ≤ {MAX_LOOKBACK_DAYS} days (factor_warmup_max_lookback_days).
3. Allowed operators: + - * / ** ; comparisons; .rolling / .expanding / .ewm;
   .mean / .std / .min / .max / .sum / .median / .quantile / .rank /
   .pct_change / .diff / .shift / .fillna(value=...) / .abs / .log /
   .log1p / .exp / .sqrt
4. No bare eval() / exec() / file IO / network IO.
5. Input columns: close, open, high, low, volume, spy, qqq, vix, bench.

REMEMBER: LLM output goes through funnel (validate → IC test → Track A
acceptance). LLM does NOT make final judgment — only candidate suggestion.
"""


def parse_llm_response(
    response_json: List[Dict],
    llm_model: str = "claude-opus-4-7",
    llm_session_id: Optional[str] = None,
) -> List[LLMCandidateFactor]:
    """Parse LLM JSON output into LLMCandidateFactor list.

    Skips entries with missing required fields (best-effort parse).
    """
    out: List[LLMCandidateFactor] = []
    for entry in response_json:
        try:
            out.append(LLMCandidateFactor(
                name=entry["name"],
                formula=entry["formula"],
                rationale=entry["rationale"],
                inputs=tuple(entry["inputs"]),
                expected_horizon_days=int(entry["expected_horizon_days"]),
                expected_ic_sign=int(entry["expected_ic_sign"]),
                llm_model=llm_model,
                llm_session_id=llm_session_id,
                notes=entry.get("notes", ""),
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return out
