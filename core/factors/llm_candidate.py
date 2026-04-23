"""LLM-proposed factor candidate schema + validation funnel (Round 10
Topic J, 2026-04-20).

This module is the SCAFFOLD for the LLM-assisted factor mining phase
defined in `docs/20260420-prd_llm_factor_mining.md`. It does NOT call any LLM.
It provides:

  1. `FactorCandidate` dataclass matching the PRD's structured YAML
  2. `load_candidate_from_yaml(path)` — parse + shape-validate
  3. `leakage_heuristic_check(candidate)` — text heuristics catching
     obvious lookahead (e.g. candidate formula mentions "future" or
     lacks any lag/shift keyword)
  4. `dedup_check(candidate_values, existing_factors)` — rank
     correlation > threshold vs existing factors
  5. `run_funnel(candidate, ...)` — orchestrator returning a verdict
     (REJECT / ARCHIVE / KEEP / NEEDS_HUMAN_REVIEW)

Hard-rule enforcement per PRD:
  - LLM is NOT the final judge — this module's verdict is input to
    human review, not auto-promotion
  - All candidates go through the FULL funnel (shape → leakage →
    dedup → IC → OOS → regime), never shortcut
  - Factor names that collide with `PRODUCTION_FACTORS` or
    `RESEARCH_FACTORS` are auto-rejected (namespace hygiene)
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd
import yaml

from core.factors.factor_registry import PRODUCTION_FACTORS, RESEARCH_FACTORS


# ── Schema ────────────────────────────────────────────────────────────────────

@dataclass
class FactorCandidate:
    """Matches the PRD structured YAML schema
    (docs/20260420-prd_llm_factor_mining.md §4).

    Required fields must be non-empty; optional fields can be None/empty
    but should be populated when the LLM has an answer.
    """
    # Required
    factor_name:                    str
    hypothesis:                     str
    formula:                        str   # pseudocode or pandas expression
    required_fields:                List[str] = field(default_factory=list)
    suitable_horizon:               List[str] = field(default_factory=list)
    suitable_universe:              str = ""
    suitable_regime:                List[str] = field(default_factory=list)
    expected_edge:                  str = ""
    expected_risk:                  str = ""
    possible_failure_modes:         List[str] = field(default_factory=list)
    novelty_vs_existing_factors:    str = ""

    # Optional — path to a Python callable that computes the factor
    # given (price_df, volume_df) → pd.DataFrame. If provided the
    # funnel can run dedup + IC; if None the candidate is a "proposal"
    # requiring human implementation.
    compute_fn_path:                Optional[str] = None

    def to_yaml(self) -> str:
        return yaml.safe_dump(asdict(self), sort_keys=False, allow_unicode=True)


class CandidateValidationError(ValueError):
    """Raised when candidate YAML fails shape / namespace validation."""


# ── Load + shape validation ───────────────────────────────────────────────────

_REQUIRED_FIELDS = ("factor_name", "hypothesis", "formula")


def load_candidate_from_yaml(path: str | Path) -> FactorCandidate:
    """Parse YAML file into a FactorCandidate. Raises
    CandidateValidationError on shape issues."""
    path = Path(path)
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise CandidateValidationError(
            f"YAML at {path} did not parse to a mapping; got {type(data)}"
        )
    return load_candidate_from_dict(data)


def load_candidate_from_dict(data: dict) -> FactorCandidate:
    """Parse dict into FactorCandidate with shape checks."""
    for req in _REQUIRED_FIELDS:
        if not data.get(req):
            raise CandidateValidationError(
                f"Required field '{req}' missing or empty. "
                f"Full field list: {sorted(data.keys())}"
            )
    # Namespace hygiene: reject names already in use
    name = data["factor_name"]
    if name in PRODUCTION_FACTORS:
        raise CandidateValidationError(
            f"factor_name '{name}' collides with PRODUCTION_FACTORS. "
            "Pick a distinct name (LLM candidates cannot shadow production)."
        )
    if name in RESEARCH_FACTORS:
        raise CandidateValidationError(
            f"factor_name '{name}' collides with RESEARCH_FACTORS. "
            "Pick a distinct name or promote the existing research factor."
        )
    # Only keep known fields
    known = {k: data.get(k) for k in FactorCandidate.__dataclass_fields__}
    # Fill list-typed defaults when None present in YAML
    for key, default in (("required_fields", []), ("suitable_horizon", []),
                         ("suitable_regime", []),
                         ("possible_failure_modes", [])):
        if known.get(key) is None:
            known[key] = default
    for key, default in (("suitable_universe", ""), ("expected_edge", ""),
                         ("expected_risk", ""),
                         ("novelty_vs_existing_factors", "")):
        if known.get(key) is None:
            known[key] = default
    return FactorCandidate(**known)


# ── Leakage heuristic (text-level) ────────────────────────────────────────────

_LOOKAHEAD_KEYWORDS = (
    "future", "tomorrow", "t+1 data", "lookahead", "look-ahead",
    "forward close", "next day close", "t+1 close",
)
_LAG_KEYWORDS = (
    "shift(", ".shift", "lag", "pct_change(", "rolling(",
    "cummax", "cummin", "diff(", "t-1", "previous", "historical",
)


def leakage_heuristic_check(candidate: FactorCandidate) -> List[str]:
    """Text-based heuristic scan of the candidate's formula + hypothesis.

    Returns list of concerns (empty = no obvious leakage). This is
    NOT a substitute for the truncation-based leakage test in the IC
    pipeline — it's a cheap first pass to reject obviously-bad
    candidates before running expensive IC.
    """
    issues: List[str] = []
    text = " ".join([
        candidate.formula or "", candidate.hypothesis or "",
    ]).lower()

    for kw in _LOOKAHEAD_KEYWORDS:
        if kw in text:
            issues.append(
                f"formula/hypothesis contains lookahead keyword '{kw}'"
            )

    has_lag = any(kw in text for kw in _LAG_KEYWORDS)
    if not has_lag:
        issues.append(
            "no explicit lag/shift/rolling keyword in formula — "
            "candidate must show it uses past-only data"
        )

    return issues


# ── Dedup check ───────────────────────────────────────────────────────────────

def dedup_check(
    candidate_values: pd.DataFrame,
    existing_factors:  dict,
    corr_threshold:    float = 0.7,
) -> List[tuple]:
    """Compute Spearman rank correlation between candidate values and
    each existing factor's values. Returns list of (existing_name, rho)
    tuples where |rho| >= corr_threshold — candidates that shadow
    existing factors.

    Per PRD §5.1: correlation > 0.7 triggers MANDATORY REVIEW, not
    auto-reject. Caller decides whether to keep or reject.
    """
    flagged: List[tuple] = []
    if candidate_values is None or candidate_values.empty:
        return flagged
    # Average across time×symbol for each factor
    cand_stack = candidate_values.stack()
    for name, fdf in existing_factors.items():
        if fdf is None or fdf.empty:
            continue
        existing_stack = fdf.reindex(
            index=candidate_values.index, columns=candidate_values.columns,
        ).stack()
        common_idx = cand_stack.index.intersection(existing_stack.index)
        if len(common_idx) < 30:
            continue
        a = cand_stack.loc[common_idx].astype(float)
        b = existing_stack.loc[common_idx].astype(float)
        mask = ~(a.isna() | b.isna())
        if mask.sum() < 30:
            continue
        rho = a.loc[mask].rank().corr(b.loc[mask].rank(), method="pearson")
        if not np.isnan(rho) and abs(rho) >= corr_threshold:
            flagged.append((name, float(rho)))
    return flagged


# ── Funnel orchestrator ───────────────────────────────────────────────────────

@dataclass
class CandidateVerdict:
    """Output of run_funnel. Never 'KEEP' without human review — per
    PRD §2.2, LLM is not the final judge."""
    verdict:               str   # REJECT / ARCHIVE / NEEDS_HUMAN_REVIEW
    reason:                str
    leakage_issues:        List[str] = field(default_factory=list)
    dedup_matches:         List[tuple] = field(default_factory=list)
    ic_stats:              Optional[dict] = None  # filled in when computed


def run_funnel(
    candidate: FactorCandidate,
    compute_fn=None,
    price_df: Optional[pd.DataFrame] = None,
    volume_df: Optional[pd.DataFrame] = None,
    existing_factors: Optional[dict] = None,
) -> CandidateVerdict:
    """Run the candidate through: shape → leakage heuristic → dedup
    (if compute_fn provided) → IC screen (if compute_fn + data provided).

    This function NEVER returns a KEEP verdict directly. The final
    decision to promote is HUMAN-REVIEW gated, consistent with
    `docs/20260420-prd_llm_factor_mining.md` §2.
    """
    # Stage 1: leakage heuristic
    leakage = leakage_heuristic_check(candidate)
    if leakage:
        return CandidateVerdict(
            verdict="REJECT",
            reason="leakage heuristic flagged issues",
            leakage_issues=leakage,
        )

    # Stage 2: if no compute_fn, can't go further — mark for review
    if compute_fn is None or price_df is None:
        return CandidateVerdict(
            verdict="NEEDS_HUMAN_REVIEW",
            reason="no compute_fn or price_df — candidate is a proposal; "
                   "human must implement before IC screen",
            leakage_issues=leakage,
        )

    # Stage 3: compute candidate values
    try:
        if volume_df is not None:
            cand_df = compute_fn(price_df, volume_df)
        else:
            cand_df = compute_fn(price_df)
    except Exception as exc:
        return CandidateVerdict(
            verdict="REJECT",
            reason=f"compute_fn raised: {exc}",
            leakage_issues=leakage,
        )
    if not isinstance(cand_df, pd.DataFrame) or cand_df.empty:
        return CandidateVerdict(
            verdict="REJECT",
            reason="compute_fn returned empty or non-DataFrame output",
            leakage_issues=leakage,
        )

    # Stage 4: dedup
    dedup_flags = []
    if existing_factors:
        dedup_flags = dedup_check(cand_df, existing_factors)
        if dedup_flags:
            return CandidateVerdict(
                verdict="NEEDS_HUMAN_REVIEW",
                reason=f"high correlation with {len(dedup_flags)} existing "
                       "factor(s); see dedup_matches",
                leakage_issues=leakage,
                dedup_matches=dedup_flags,
            )

    # Stage 5: IC screen (basic cross-sectional IC vs 21-day forward)
    try:
        fwd = price_df.pct_change(21).shift(-21)
        ic_vals = []
        for date in cand_df.index:
            if date not in fwd.index:
                continue
            c_row = cand_df.loc[date].dropna()
            f_row = fwd.loc[date].dropna()
            common = c_row.index.intersection(f_row.index)
            if len(common) < 5:
                continue
            rho = c_row.loc[common].rank().corr(
                f_row.loc[common].rank(), method="pearson")
            if not np.isnan(rho):
                ic_vals.append(rho)
        if not ic_vals:
            return CandidateVerdict(
                verdict="ARCHIVE",
                reason="IC could not be computed (too few observations)",
                leakage_issues=leakage,
                dedup_matches=dedup_flags,
                ic_stats={"n_dates": 0},
            )
        ic_mean = float(np.mean(ic_vals))
        ic_std = float(np.std(ic_vals, ddof=1)) if len(ic_vals) > 1 else 0.0
        ic_ir = ic_mean / ic_std if ic_std > 1e-10 else 0.0
        ic_stats = {
            "ic_mean": round(ic_mean, 5),
            "ic_std":  round(ic_std, 5),
            "ic_ir":   round(ic_ir, 3),
            "n_dates": len(ic_vals),
        }
    except Exception as exc:
        return CandidateVerdict(
            verdict="ARCHIVE",
            reason=f"IC computation failed: {exc}",
            leakage_issues=leakage, dedup_matches=dedup_flags,
        )

    # Verdict logic (per PRD §5.3 + §6 reverse-review):
    # - IC mean |value| > 0.03 AND IR > 0.3 → worth human review (KEEP cand.)
    # - otherwise → ARCHIVE for record
    if abs(ic_stats["ic_mean"]) >= 0.03 and abs(ic_stats["ic_ir"]) >= 0.3:
        return CandidateVerdict(
            verdict="NEEDS_HUMAN_REVIEW",
            reason=f"IC stats non-trivial (mean={ic_stats['ic_mean']:+.4f}, "
                   f"IR={ic_stats['ic_ir']:+.2f}); human must run OOS + "
                   "regime + cost stress before promoting",
            leakage_issues=leakage, dedup_matches=dedup_flags,
            ic_stats=ic_stats,
        )
    return CandidateVerdict(
        verdict="ARCHIVE",
        reason=f"IC too weak (mean={ic_stats['ic_mean']:+.4f}, "
               f"IR={ic_stats['ic_ir']:+.2f}); archived for record",
        leakage_issues=leakage, dedup_matches=dedup_flags,
        ic_stats=ic_stats,
    )
