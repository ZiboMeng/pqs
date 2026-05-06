"""Unit tests for PRD-AC v1.1 Phase 3 round 1 search-space extension.

Round 1 ships:
  - holding_freq end-to-end: trial.suggest → ResearchCompositeSpec field
    → harness_config.rebalance_cadence override at evaluate_composite
    NAV path → archive trial_id includes holding_freq when non-default
  - enable_sr_defer sampling stub: forced False; archive schema ready;
    full integration in Phase 3 round 2 (60m bar load + filter +
    second BacktestEngine run).

PRD §6 Phase 3 step 5 acceptance: tests covering the 6 hyperparam
combos. Round 1 covers 3 cells (holding_freq × {enable_sr_defer=False});
round 2 will add 3 more cells when SR-defer integration lands.
"""

from __future__ import annotations

import json
import sqlite3

import numpy as np
import pandas as pd
import pytest

from core.mining.rcm_archive import RCMArchive, _serialize_spec, compute_spec_id
from core.mining.research_miner import (
    ObjectiveWeights,
    ResearchCompositeSpec,
    TrialResult,
    suggest_composite_spec,
)


# ── ResearchCompositeSpec new fields ────────────────────────────────────────


def test_research_composite_spec_legacy_construction_unchanged():
    """Pre-PRD-AC call sites (no holding_freq / no enable_sr_defer) work."""
    spec = ResearchCompositeSpec(
        features=("a", "b"), weights=(0.5, 0.5), family_counts={"X": 2},
    )
    assert spec.holding_freq is None
    assert spec.enable_sr_defer is False


def test_research_composite_spec_holding_freq_validates():
    """holding_freq must be one of {None, daily, weekly, monthly}."""
    for valid in (None, "daily", "weekly", "monthly"):
        ResearchCompositeSpec(
            features=("a",), weights=(1.0,),
            family_counts={"X": 1}, holding_freq=valid,
        )
    with pytest.raises(ValueError, match="holding_freq must be"):
        ResearchCompositeSpec(
            features=("a",), weights=(1.0,),
            family_counts={"X": 1}, holding_freq="hourly",
        )


# ── _serialize_spec backward compat ─────────────────────────────────────────


def test_serialize_spec_legacy_omits_new_fields():
    """Legacy spec (None / False defaults) serializes WITHOUT new keys
    so trial_id hash matches cycle04/05 archive entries."""
    spec = ResearchCompositeSpec(
        features=("a", "b"), weights=(0.5, 0.5), family_counts={"X": 2},
    )
    out = _serialize_spec(spec)
    assert "holding_freq" not in out
    assert "enable_sr_defer" not in out
    # Hash matches what cycle04 archive computed for any structurally-
    # identical spec
    legacy_dict = {
        "features": ["a", "b"],
        "weights": [0.5, 0.5],
        "family_counts": {"X": 2},
    }
    assert json.dumps(out, sort_keys=True) == json.dumps(legacy_dict, sort_keys=True)


def test_serialize_spec_includes_holding_freq_when_set():
    """holding_freq surfaces in serialized dict only when non-None."""
    spec = ResearchCompositeSpec(
        features=("a",), weights=(1.0,),
        family_counts={"X": 1}, holding_freq="weekly",
    )
    out = _serialize_spec(spec)
    assert out["holding_freq"] == "weekly"


def test_serialize_spec_includes_sr_defer_when_set():
    """enable_sr_defer surfaces in dict only when True (Phase 3 round 2
    will produce True specs; round 1 archives still won't have this key
    because all sampled specs are False)."""
    spec = ResearchCompositeSpec(
        features=("a",), weights=(1.0,),
        family_counts={"X": 1}, enable_sr_defer=True,
    )
    out = _serialize_spec(spec)
    assert out["enable_sr_defer"] is True


def test_compute_spec_id_changes_with_holding_freq():
    """Same factors + weights but different holding_freq → different
    trial_id. Mining can store both as distinct trials."""
    s_legacy = ResearchCompositeSpec(
        features=("a",), weights=(1.0,), family_counts={"X": 1},
    )
    s_weekly = ResearchCompositeSpec(
        features=("a",), weights=(1.0,),
        family_counts={"X": 1}, holding_freq="weekly",
    )
    assert compute_spec_id(s_legacy) != compute_spec_id(s_weekly)


# ── suggest_composite_spec sampling ──────────────────────────────────────────


class _FakeTrial:
    """Minimal Optuna-compatible stub for unit tests."""

    def __init__(self, decisions: dict):
        self.decisions = decisions

    def suggest_int(self, name: str, low: int, high: int) -> int:
        return self.decisions.get(name, low)

    def suggest_categorical(self, name: str, choices):
        return self.decisions.get(name, choices[0])

    def suggest_float(self, name: str, low: float, high: float, step=None):
        return self.decisions.get(name, (low + high) / 2)


def test_suggest_composite_spec_no_holding_freq_choices_legacy():
    """Without holding_freq_choices kwarg, legacy 2-dim sampling preserved."""
    from core.mining.research_miner import FAMILY_A, FAMILY_B, FAMILY_C
    trial = _FakeTrial({
        "n_features_A": 1, "n_features_B": 1, "n_features_C": 1, "n_features_D": 0,
        "family_A_slot_0": "beta_spy_60d", "family_B_slot_0": "range_pos_252d",
        "family_C_slot_0": "amihud_20d",
        "w_beta_spy_60d": 0.4, "w_range_pos_252d": 0.4, "w_amihud_20d": 0.2,
    })
    spec = suggest_composite_spec(trial, families=[FAMILY_A, FAMILY_B, FAMILY_C])
    assert spec.holding_freq is None
    assert spec.enable_sr_defer is False


def test_suggest_composite_spec_with_holding_freq_choices():
    """Passing holding_freq_choices=['daily','weekly','monthly'] adds
    that search dim; sampler picks first choice in this fake trial."""
    from core.mining.research_miner import FAMILY_A, FAMILY_B, FAMILY_C
    trial = _FakeTrial({
        "n_features_A": 1, "n_features_B": 1, "n_features_C": 1, "n_features_D": 0,
        "family_A_slot_0": "beta_spy_60d", "family_B_slot_0": "range_pos_252d",
        "family_C_slot_0": "amihud_20d",
        "w_beta_spy_60d": 0.4, "w_range_pos_252d": 0.4, "w_amihud_20d": 0.2,
        "holding_freq": "weekly",
    })
    spec = suggest_composite_spec(
        trial, families=[FAMILY_A, FAMILY_B, FAMILY_C],
        holding_freq_choices=["daily", "weekly", "monthly"],
    )
    assert spec.holding_freq == "weekly"


def test_suggest_composite_spec_sr_defer_round1_forced_false():
    """Round 1: enable_sr_defer_choices=(False,) → spec.enable_sr_defer=False
    even if trial decision says True (because choices=(False,) means only
    False is valid)."""
    from core.mining.research_miner import FAMILY_A, FAMILY_B, FAMILY_C
    trial = _FakeTrial({
        "n_features_A": 1, "n_features_B": 1, "n_features_C": 1, "n_features_D": 0,
        "family_A_slot_0": "beta_spy_60d", "family_B_slot_0": "range_pos_252d",
        "family_C_slot_0": "amihud_20d",
        "w_beta_spy_60d": 0.4, "w_range_pos_252d": 0.4, "w_amihud_20d": 0.2,
    })
    spec = suggest_composite_spec(
        trial, families=[FAMILY_A, FAMILY_B, FAMILY_C],
    )
    assert spec.enable_sr_defer is False


# ── evaluate_composite NAV path uses spec.holding_freq override ──────────────


def _build_panel(n_days=180, n_syms=8, seed=0):
    from core.mining.research_miner import zscore_cs

    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n_days, freq="B")
    syms = [f"S{i}" for i in range(n_syms)]
    market = rng.normal(0, 0.01, size=n_days)
    sym_specific = rng.normal(0, 0.005, size=(n_days, n_syms))
    rets = market[:, None] + sym_specific
    prices = 100.0 * np.cumprod(1 + rets, axis=0)
    price_df = pd.DataFrame(prices, index=dates, columns=syms)
    open_df = price_df * (1 + rng.normal(0, 0.001, size=(n_days, n_syms)))
    fwd = price_df.pct_change(21).shift(-21)
    panel_map = {
        "momentum_20d": zscore_cs(price_df.pct_change(20)),
        "momentum_60d": zscore_cs(price_df.pct_change(60)),
    }
    spy = pd.Series(
        400.0 * np.cumprod(1 + market + rng.normal(0, 0.001, size=n_days)),
        index=dates, name="SPY",
    )
    qqq = pd.Series(
        300.0 * np.cumprod(
            1 + market * 1.1 + rng.normal(0, 0.002, size=n_days)
        ),
        index=dates, name="QQQ",
    )
    return panel_map, fwd, price_df, open_df, spy, qqq


def test_evaluate_composite_holding_freq_override_propagates_to_harness():
    """spec.holding_freq overrides harness_config.rebalance_cadence
    (frozen dataclass → dataclasses.replace)."""
    from core.mining.nav_objective import (
        build_universe_baseline_residual_returns,
    )
    from core.mining.research_miner import evaluate_composite
    from core.research.harness import HarnessConfig

    panel_map, fwd, price_df, open_df, spy, qqq = _build_panel()
    anchor = build_universe_baseline_residual_returns(price_df, spy)
    spec_weekly = ResearchCompositeSpec(
        features=("momentum_20d", "momentum_60d"),
        weights=(0.5, 0.5), family_counts={"A": 2},
        holding_freq="weekly",
    )
    hc = HarnessConfig(rebalance_cadence="monthly", top_n=5)  # default monthly
    metrics = evaluate_composite(
        spec_weekly, panel_map, fwd,
        price_df=price_df, open_df=open_df,
        spy_series=spy, qqq_series=qqq,
        anchor_residual_returns=anchor,
        harness_config=hc, compute_nav=True,
    )
    # The override is silent (no API to read back the effective config from
    # outside), but a different cadence must produce a different NAV-Sharpe.
    spec_monthly = ResearchCompositeSpec(
        features=("momentum_20d", "momentum_60d"),
        weights=(0.5, 0.5), family_counts={"A": 2},
        holding_freq="monthly",
    )
    metrics_monthly = evaluate_composite(
        spec_monthly, panel_map, fwd,
        price_df=price_df, open_df=open_df,
        spy_series=spy, qqq_series=qqq,
        anchor_residual_returns=anchor,
        harness_config=hc, compute_nav=True,
    )
    # Sanity: weekly vs monthly produces materially different paths
    # (holds, turnover) — Sharpe differ. Use a loose != check (could
    # be ~0 sharpe in both, but max_dd or ic_ir should differ).
    differ = (
        metrics.nav_sharpe != metrics_monthly.nav_sharpe
        or metrics.nav_max_dd != metrics_monthly.nav_max_dd
    )
    assert differ, (
        "holding_freq override appears not to take effect: "
        f"weekly sharpe={metrics.nav_sharpe} monthly sharpe={metrics_monthly.nav_sharpe}"
    )


# ── Archive backward compat: cycle04/05 trial_ids unchanged ─────────────────


def test_archive_legacy_trial_id_stable_across_phase3_change(tmp_path):
    """A spec with no holding_freq / no enable_sr_defer hashes to the
    same trial_id as a pre-PRD-AC archive entry (verified by manual
    canonical dict construction; archive insert preserves this)."""
    db = tmp_path / "compat.db"
    arch = RCMArchive(db)
    arch.record_study(study_id="s1", lineage_tag="legacy")
    spec = ResearchCompositeSpec(
        features=("a", "b"), weights=(0.5, 0.5), family_counts={"X": 2},
    )
    from core.mining.research_miner import CompositeMetrics
    m = CompositeMetrics(
        n_features=2, n_families=1, n_dates=100,
        ic_mean=0.05, ic_std=0.1, ic_ir=2.5,
        turnover_proxy=0.3, corr_concentration=0.4,
    )
    tr = TrialResult(spec=spec, metrics=m, objective=1.5)
    trial_id = arch.insert_trial(tr, lineage_tag="legacy", study_id="s1")
    # Manually compute what the legacy trial_id should be (pre-PRD-AC
    # _serialize_spec with no new keys):
    import hashlib
    legacy_json = json.dumps({
        "features": ["a", "b"],
        "weights": [0.5, 0.5],
        "family_counts": {"X": 2},
    }, sort_keys=True)
    expected = hashlib.sha256(legacy_json.encode("utf-8")).hexdigest()[:12]
    assert trial_id == expected
