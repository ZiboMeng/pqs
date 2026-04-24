"""Declarative cross-ticker rule engine (PRD M4).

Rules compose on top of strategy output (weight dict per bar) to express
cross-ticker conditional logic without writing a new strategy class.

Three rule types:
  1. benchmark_trigger    — driver symbol condition gates target symbols
  2. regime_basket        — regime-conditioned basket preference
  3. multi_tf_confirmation — timing multiplier when confirmations agree

Long-only invariant: all outputs are clipped to >= 0 and re-normalized.
Expression parser is whitelist-only (no Python eval).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

import pandas as pd
import yaml

from core.logging_setup import get_logger

logger = get_logger(__name__)


class RuleType(str, Enum):
    BENCHMARK_TRIGGER = "benchmark_trigger"
    REGIME_BASKET = "regime_basket"
    MULTI_TF_CONFIRMATION = "multi_tf_confirmation"


class CrossTickerRuleError(ValueError):
    """Raised on invalid rule config."""


# ---------------------------------------------------------------------------
# Rule dataclasses
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkTriggerRule:
    name: str
    driver: str
    condition: str          # DSL expression, e.g. "sma(close, 5) > sma(close, 200)"
    targets: List[str]
    action: Literal["allow_overweight", "block", "allow_only"] = "allow_overweight"
    weight_multiplier: float = 1.0
    regime_scope: List[str] = field(default_factory=list)  # empty = all regimes
    priority: int = 100


@dataclass
class RegimeBasketRule:
    name: str
    regime: List[str]
    basket_weights: Dict[str, float]
    override_strategy: bool = False   # False = blend with base, True = replace
    # Optional fast-exit / recovery trigger. When set, the rule is SKIPPED (no
    # blend / no override) if the driver's last bar satisfies `condition`.
    # Shape: {"driver": "SPY", "condition": "sma(close, 5) > sma(close, 20)"}
    # Motivation: R25 deep-mining crisis stress test — V-recovery was hurt by
    # keeping the defensive blend active after the market had already turned.
    suppress_if: Optional[Dict[str, str]] = None
    priority: int = 100


@dataclass
class MultiTFConfirmationRule:
    name: str
    target: str
    primary_condition: str
    confirmations: List[Dict[str, Any]]  # each: {symbol, timeframe, condition}
    action: Dict[str, Any] = field(default_factory=dict)
    priority: int = 100


Rule = BenchmarkTriggerRule | RegimeBasketRule | MultiTFConfirmationRule


# ---------------------------------------------------------------------------
# Safe expression evaluator — whitelist-only
# ---------------------------------------------------------------------------


_FUNCTION_WHITELIST = {"sma", "ema", "ref_high", "ref_low", "rsi"}
_FIELD_WHITELIST = {"open", "high", "low", "close", "volume"}
_OPERATOR_PATTERN = re.compile(r"^[\d\.\s\+\-\*\/\(\)\,\w<>=!&|]+$")


def _validate_expression(expr: str) -> None:
    """Refuse expressions with unexpected characters or unknown funcs."""
    if not _OPERATOR_PATTERN.match(expr):
        raise CrossTickerRuleError(
            f"Expression contains disallowed characters: {expr!r}"
        )
    # Check function names
    for fn_match in re.finditer(r"(\w+)\s*\(", expr):
        fn = fn_match.group(1)
        if fn not in _FUNCTION_WHITELIST:
            raise CrossTickerRuleError(
                f"Unknown function {fn!r} in expression (allowed: {sorted(_FUNCTION_WHITELIST)})"
            )
    # Check field names (standalone identifiers that aren't functions or numbers)
    for ident_match in re.finditer(r"\b([a-zA-Z_]\w*)\b", expr):
        ident = ident_match.group(1)
        if ident in _FUNCTION_WHITELIST or ident in _FIELD_WHITELIST:
            continue
        # Allow 'and', 'or', 'not'
        if ident in ("and", "or", "not", "True", "False"):
            continue
        raise CrossTickerRuleError(
            f"Unknown identifier {ident!r} in expression (allowed fields: "
            f"{sorted(_FIELD_WHITELIST)}; functions: {sorted(_FUNCTION_WHITELIST)})"
        )


def _eval_expression(expr: str, ohlcv: pd.DataFrame) -> bool:
    """Evaluate a whitelisted expression against an OHLCV DataFrame.

    Returns the boolean outcome at the LAST row of ohlcv.
    Supports: sma(col, N), ema(col, N), ref_high(N), ref_low(N), rsi(col, N).
    """
    _validate_expression(expr)

    def sma(col: pd.Series, n: int) -> float:
        if len(col) < n:
            return float("nan")
        return float(col.tail(n).mean())

    def ema(col: pd.Series, n: int) -> float:
        if len(col) < n:
            return float("nan")
        return float(col.ewm(span=n, adjust=False).mean().iloc[-1])

    def ref_high(n: int) -> float:
        if "high" not in ohlcv.columns or len(ohlcv) < n:
            return float("nan")
        return float(ohlcv["high"].tail(n).max())

    def ref_low(n: int) -> float:
        if "low" not in ohlcv.columns or len(ohlcv) < n:
            return float("nan")
        return float(ohlcv["low"].tail(n).min())

    def rsi(col: pd.Series, n: int) -> float:
        if len(col) < n + 1:
            return float("nan")
        delta = col.diff().tail(n + 1)
        gain = delta.where(delta > 0, 0).mean()
        loss = (-delta.where(delta < 0, 0)).mean()
        if loss == 0:
            return 100.0
        rs = gain / loss
        return float(100 - (100 / (1 + rs)))

    # Build eval namespace with safe primitives
    ns: Dict[str, Any] = {
        "sma": sma, "ema": ema, "ref_high": ref_high, "ref_low": ref_low, "rsi": rsi,
    }
    for field_name in _FIELD_WHITELIST:
        if field_name in ohlcv.columns:
            ns[field_name] = ohlcv[field_name]
    # Safe eval: builtins blocked
    result = eval(expr, {"__builtins__": {}}, ns)  # noqa: S307 (whitelist checked)
    if isinstance(result, pd.Series):
        result = result.iloc[-1]
    return bool(result)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _parse_rule(raw: Dict[str, Any]) -> Rule:
    name = raw.get("name", "unnamed")
    rtype = raw.get("type")
    if rtype == RuleType.BENCHMARK_TRIGGER.value:
        return BenchmarkTriggerRule(
            name=name,
            driver=raw["driver"],
            condition=raw["condition"],
            targets=list(raw["targets"]),
            action=raw.get("action", "allow_overweight"),
            weight_multiplier=float(raw.get("weight_multiplier", 1.0)),
            regime_scope=list(raw.get("regime_scope", [])),
            priority=int(raw.get("priority", 100)),
        )
    if rtype == RuleType.REGIME_BASKET.value:
        suppress_raw = raw.get("suppress_if")
        suppress_if: Optional[Dict[str, str]] = None
        if suppress_raw is not None:
            if not isinstance(suppress_raw, dict) or \
                    "driver" not in suppress_raw or "condition" not in suppress_raw:
                raise CrossTickerRuleError(
                    f"Rule {name!r}: suppress_if must be dict with 'driver' and "
                    f"'condition' keys; got {suppress_raw!r}"
                )
            # Validate expression shape now (fail fast); runtime eval still checks.
            _validate_expression(str(suppress_raw["condition"]))
            suppress_if = {
                "driver": str(suppress_raw["driver"]),
                "condition": str(suppress_raw["condition"]),
            }
        return RegimeBasketRule(
            name=name,
            regime=list(raw["regime"]),
            basket_weights=dict(raw["basket_weights"]),
            override_strategy=bool(raw.get("override_strategy", False)),
            suppress_if=suppress_if,
            priority=int(raw.get("priority", 100)),
        )
    if rtype == RuleType.MULTI_TF_CONFIRMATION.value:
        return MultiTFConfirmationRule(
            name=name,
            target=raw["target"],
            primary_condition=raw["primary_condition"],
            confirmations=list(raw.get("confirmations", [])),
            action=dict(raw.get("action", {})),
            priority=int(raw.get("priority", 100)),
        )
    raise CrossTickerRuleError(
        f"Unknown rule type {rtype!r} for rule {name!r}. "
        f"Valid types: {[t.value for t in RuleType]}"
    )


def load_rules(path: str | Path = "config/cross_ticker_rules.yaml") -> Tuple[bool, List[Rule]]:
    """Load rule config. Returns (enabled, rules_sorted_by_priority).

    Invariants:
      - Unknown rule type → CrossTickerRuleError
      - Invalid condition expression → CrossTickerRuleError
    """
    p = Path(path)
    if not p.exists():
        return (False, [])
    cfg = yaml.safe_load(p.read_text()) or {}
    enabled = bool(cfg.get("enabled", False))
    raw_rules = cfg.get("rules") or []
    rules: List[Rule] = []
    for raw in raw_rules:
        rule = _parse_rule(raw)
        # Validate conditions at load time
        if isinstance(rule, BenchmarkTriggerRule):
            _validate_expression(rule.condition)
        elif isinstance(rule, MultiTFConfirmationRule):
            _validate_expression(rule.primary_condition)
            for c in rule.confirmations:
                _validate_expression(c["condition"])
        rules.append(rule)
    rules.sort(key=lambda r: r.priority)
    return (enabled, rules)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------


@dataclass
class RuleContext:
    """Per-bar context passed to apply_rules()."""
    bar_timestamp: Any
    regime: str = "NEUTRAL"
    # Dict[symbol -> OHLCV DataFrame up to current bar]
    ohlcv: Dict[str, pd.DataFrame] = field(default_factory=dict)
    timing_scale: float = 1.0


def _apply_benchmark_trigger(
    weights: Dict[str, float],
    rule: BenchmarkTriggerRule,
    ctx: RuleContext,
) -> Dict[str, float]:
    # Regime check
    if rule.regime_scope and ctx.regime not in rule.regime_scope:
        return weights
    # Driver ohlcv
    driver_df = ctx.ohlcv.get(rule.driver)
    if driver_df is None or driver_df.empty:
        return weights
    try:
        condition_met = _eval_expression(rule.condition, driver_df)
    except Exception as exc:
        logger.warning("Rule %s expression failed: %s", rule.name, exc)
        return weights
    if not condition_met:
        if rule.action == "block":
            out = dict(weights)
            for t in rule.targets:
                out[t] = 0.0
            return out
        return weights
    # Condition met → apply
    out = dict(weights)
    if rule.action == "allow_overweight":
        for t in rule.targets:
            if t in out:
                out[t] = max(0.0, out[t] * rule.weight_multiplier)
    elif rule.action == "allow_only":
        out = {k: (v if k in rule.targets else 0.0) for k, v in out.items()}
    return out


def _apply_regime_basket(
    weights: Dict[str, float],
    rule: RegimeBasketRule,
    ctx: RuleContext,
) -> Dict[str, float]:
    if ctx.regime not in rule.regime:
        return weights
    # Fast-exit check: if suppress_if set and driver satisfies condition, skip rule.
    if rule.suppress_if is not None:
        driver = rule.suppress_if["driver"]
        driver_df = ctx.ohlcv.get(driver)
        if driver_df is not None and not driver_df.empty:
            try:
                if _eval_expression(rule.suppress_if["condition"], driver_df):
                    return weights
            except Exception as exc:
                logger.warning(
                    "Rule %s suppress_if eval failed (driver=%s): %s — continuing to apply rule",
                    rule.name, driver, exc,
                )
    if rule.override_strategy:
        # Ensure basket weights are >= 0 (long-only) and normalize
        basket = {k: max(0.0, v) for k, v in rule.basket_weights.items()}
        total = sum(basket.values())
        if total <= 0:
            return weights
        return {k: v / total for k, v in basket.items()}
    # Blend: 50/50 with existing weights (simple default)
    out = dict(weights)
    for sym, w in rule.basket_weights.items():
        out[sym] = 0.5 * out.get(sym, 0.0) + 0.5 * max(0.0, w)
    total = sum(out.values())
    if total > 0:
        out = {k: v / total for k, v in out.items()}
    return out


def _apply_multi_tf_confirmation(
    weights: Dict[str, float],
    rule: MultiTFConfirmationRule,
    ctx: RuleContext,
) -> Dict[str, float]:
    target_df = ctx.ohlcv.get(rule.target)
    if target_df is None or target_df.empty:
        return weights
    # Check primary
    try:
        primary_ok = _eval_expression(rule.primary_condition, target_df)
    except Exception as exc:
        logger.warning("Rule %s primary failed: %s", rule.name, exc)
        return weights
    if not primary_ok:
        return weights
    # All confirmations must agree
    for c in rule.confirmations:
        sym = c["symbol"]
        df = ctx.ohlcv.get(sym)
        if df is None or df.empty:
            return weights  # missing data → fail-safe no-op
        try:
            if not _eval_expression(c["condition"], df):
                return weights
        except Exception:
            return weights
    # All confirmed → apply scale multiplier
    scale = float(rule.action.get("timing_scale_multiplier", 1.0))
    out = dict(weights)
    if rule.target in out:
        out[rule.target] = max(0.0, out[rule.target] * scale)
    return out


def apply_rules(
    weights: Dict[str, float],
    ctx: RuleContext,
    rules: List[Rule],
) -> Dict[str, float]:
    """Apply rules in priority order. Enforces long-only invariant."""
    out = dict(weights)
    for rule in rules:
        if isinstance(rule, BenchmarkTriggerRule):
            out = _apply_benchmark_trigger(out, rule, ctx)
        elif isinstance(rule, RegimeBasketRule):
            out = _apply_regime_basket(out, rule, ctx)
        elif isinstance(rule, MultiTFConfirmationRule):
            out = _apply_multi_tf_confirmation(out, rule, ctx)
        # Long-only invariant after every step
        for sym, w in list(out.items()):
            if w < 0:
                logger.warning(
                    "Rule %s produced negative weight for %s (%s) — clipped to 0",
                    rule.name, sym, w,
                )
                out[sym] = 0.0
    return out
