"""Regime auto-classifier for the Track A temporal split.

PRD: docs/prd/20260429-temporal_split_holdout_discipline_prd.md (v1.1)
Step A.8 — wraps ``core.regime.regime_detector.RegimeDetector`` to
produce a single dominant-class label per calendar year. Output fills
``partition.validation_years[].auto_classifier_tag`` in the split YAML.

Disagreement policy (M9 tiered, codex R20 Q4):
  - 0-1 year mismatch  → reconciliation memo per year
  - ≥2 year mismatch   → user explicit-go required before split lock
  - All 5 disagree     → hard error; either detector or manual is wrong

This module exposes the classifier; the orchestration script (lives
under ``dev/scripts/research/``) does data loading + write-back.

Public API
----------
- ``classify_year_dominant(year, spy, vix, tnx, regime_cfg)`` →
  RegimeState string ("BULL", "RISK_ON", ...). Computes daily regime
  states across the year, returns the modal class.
- ``compare_manual_vs_auto(cfg, dominant_by_year)`` → ReconciliationReport
  with disagreement count + tier classification + per-year diffs.
- ``ReconciliationReport``: dataclass with ``tier`` ∈ {"memo_only",
  "user_explicit_go_required", "hard_error"} and ``disagreements`` list.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from core.regime.regime_detector import RegimeDetector, RegimeState
from core.research.temporal_split import TemporalSplitConfig


# ---------------------------------------------------------------------------
# Year-level classification
# ---------------------------------------------------------------------------


def classify_year_dominant(
    year: int,
    spy: pd.Series,
    vix: pd.Series,
    tnx: Optional[pd.Series],
    regime_detector: RegimeDetector,
) -> str:
    """Return the modal RegimeState string across all classified days in ``year``.

    Daily classifications come from RegimeDetector.classify_series. Ties
    are broken by max-defensive (CRISIS > RISK_OFF > CAUTIOUS > NEUTRAL >
    RISK_ON > BULL) so misclassifying a year as MORE defensive is the
    conservative direction.
    """
    daily = regime_detector.classify_series(spy=spy, vix=vix, tnx=tnx)
    if len(daily) == 0:
        raise ValueError(f"no SPY/VIX overlap for year {year}; cannot classify")
    daily_in_year = daily[daily.index.year == year]
    if len(daily_in_year) == 0:
        raise ValueError(f"no daily regime classifications for year {year}")
    counts = Counter(daily_in_year)
    max_count = max(counts.values())
    tied = [s for s, c in counts.items() if c == max_count]
    if len(tied) == 1:
        return tied[0]
    # Conservative tie-break: most defensive wins
    rank = {
        RegimeState.BULL.value:     0,
        RegimeState.RISK_ON.value:  1,
        RegimeState.NEUTRAL.value:  2,
        RegimeState.CAUTIOUS.value: 3,
        RegimeState.RISK_OFF.value: 4,
        RegimeState.CRISIS.value:   5,
    }
    return max(tied, key=lambda s: rank.get(s, -1))


# ---------------------------------------------------------------------------
# Reconciliation report (M9 tiered policy)
# ---------------------------------------------------------------------------


@dataclass
class YearDisagreement:
    year: int
    manual_tag: str
    auto_tag: str


@dataclass
class ReconciliationReport:
    """Outcome of comparing manual_regime_tag vs auto_classifier_tag.

    ``tier`` field encodes the M9 policy: ``memo_only`` (0-1 mismatch),
    ``user_explicit_go_required`` (2-4 mismatch), ``hard_error`` (all
    5 mismatch). Caller decides what to do based on tier.
    """

    tier: str  # "memo_only" | "user_explicit_go_required" | "hard_error"
    n_validation_years: int
    n_disagreements: int
    disagreements: List[YearDisagreement] = field(default_factory=list)
    per_year: Dict[int, Dict[str, str]] = field(default_factory=dict)

    @property
    def needs_user_approval(self) -> bool:
        return self.tier in ("user_explicit_go_required", "hard_error")

    def summary_line(self) -> str:
        return (
            f"Regime reconciliation: {self.n_disagreements}/"
            f"{self.n_validation_years} disagree → tier={self.tier}"
        )


def compare_manual_vs_auto(
    cfg: TemporalSplitConfig,
    dominant_by_year: Dict[int, str],
) -> ReconciliationReport:
    """Build M9 reconciliation report.

    ``dominant_by_year`` maps each validation year (and optionally sealed
    year) to the auto-classified RegimeState string. The function only
    compares against ``cfg.partition.validation_years[].manual_regime_tag``.

    Manual tags use narrative labels (``rate_hike_bear``, ``ai_narrow``,
    ``current_market``, etc.); auto tags use RegimeState enum values
    (``BULL``, ``RISK_OFF``, ...). The two namespaces do not overlap;
    therefore "match" is defined by an explicit semantic mapping (below).
    The mapping is conservative: when uncertain, mark as DISAGREE.
    """
    # Semantic mapping: manual narrative tag → expected auto regime class.
    # Multi-mapping list: any auto match counts as agreement.
    _MANUAL_TO_AUTO_EXPECTED = {
        "rate_hike_bear":     {"CAUTIOUS", "RISK_OFF"},
        "rate_hike_bear_full":{"CAUTIOUS", "RISK_OFF", "CRISIS"},
        "normal_bull":        {"BULL", "RISK_ON"},
        "liquidity_mania":    {"BULL", "RISK_ON"},
        "ai_narrow":          {"BULL", "RISK_ON", "NEUTRAL"},
        "current_market":     {"BULL", "RISK_ON", "NEUTRAL"},
        "covid_v_recovery":   {"CRISIS", "RISK_OFF", "BULL"},
        "financial_crisis":   {"CRISIS", "RISK_OFF"},
        "ai_continuation":    {"BULL", "RISK_ON"},
    }

    disagreements: List[YearDisagreement] = []
    per_year: Dict[int, Dict[str, str]] = {}
    for vy in cfg.partition.validation_years:
        manual = vy.manual_regime_tag
        auto = dominant_by_year.get(vy.year)
        per_year[vy.year] = {"manual": manual, "auto": (auto or "missing")}
        if auto is None:
            disagreements.append(YearDisagreement(year=vy.year, manual_tag=manual,
                                                  auto_tag="missing"))
            continue
        expected = _MANUAL_TO_AUTO_EXPECTED.get(manual, set())
        if auto not in expected:
            disagreements.append(YearDisagreement(year=vy.year, manual_tag=manual,
                                                  auto_tag=auto))

    n_val = len(cfg.partition.validation_years)
    n_dis = len(disagreements)
    if n_val == 0:
        tier = "memo_only"
    elif n_dis == n_val:
        tier = "hard_error"
    elif n_dis >= 2:
        tier = "user_explicit_go_required"
    else:
        tier = "memo_only"

    return ReconciliationReport(
        tier=tier,
        n_validation_years=n_val,
        n_disagreements=n_dis,
        disagreements=disagreements,
        per_year=per_year,
    )
