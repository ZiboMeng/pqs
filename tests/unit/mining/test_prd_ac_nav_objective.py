"""Unit tests for PRD-AC v1.1 (NAV-based mining objective + execution_policy
hyperparameter). Covers Phase 1 deliverables:

  - CompositeMetrics: 4 new nav_* fields (default NaN), to_dict round-trip
  - ObjectiveWeights: 4 new w_nav_* fields (default 0.0), is_nav_based()
  - compute_objective: v1_legacy bit-identical to legacy; v2_nav_based math
    matches PRD §4.4; NaN-safe on missing NAV metrics
  - RCMArchive: schema migration adds 4 NAV cols; insert_trial persists
    correctly (NULL for v1_legacy, real for v2); record_study stamps
    objective_version + 4 new w_nav_* in objective_weights_json blob

Phase 1c PRD §5.1 backward-compat regression (top-20 Spearman > 0.95 vs
cycle04 archive) is acceptance-pack territory and lives in Phase 4 smoke
runs, not unit tests.
"""

from __future__ import annotations

import json
import math
import sqlite3
import tempfile
from pathlib import Path

from core.mining.rcm_archive import RCMArchive
from core.mining.research_miner import (
    CompositeMetrics,
    ObjectiveWeights,
    ResearchCompositeSpec,
    TrialResult,
    compute_objective,
)


# ── CompositeMetrics: 4 new nav_* fields ─────────────────────────────────────


def test_composite_metrics_defaults_nan_for_nav_fields():
    """Constructing CompositeMetrics without NAV kwargs leaves them NaN."""
    m = CompositeMetrics(
        n_features=3, n_families=2, n_dates=100,
        ic_mean=0.05, ic_std=0.1, ic_ir=2.5,
        turnover_proxy=0.3, corr_concentration=0.4,
    )
    assert math.isnan(m.nav_sharpe)
    assert math.isnan(m.nav_max_dd)
    assert math.isnan(m.nav_correlation_vs_anchor_pooled_raw)
    assert math.isnan(m.nav_vs_qqq_excess_full_period)


def test_composite_metrics_to_dict_includes_nav_keys():
    """to_dict round-trip surfaces all 4 new keys (NaN included)."""
    m = CompositeMetrics(
        n_features=3, n_families=2, n_dates=100,
        ic_mean=0.05, ic_std=0.1, ic_ir=2.5,
        turnover_proxy=0.3, corr_concentration=0.4,
        nav_sharpe=1.2, nav_max_dd=-0.18,
        nav_correlation_vs_anchor_pooled_raw=0.65,
        nav_vs_qqq_excess_full_period=0.05,
    )
    d = m.to_dict()
    assert d["nav_sharpe"] == 1.2
    assert d["nav_max_dd"] == -0.18
    assert d["nav_correlation_vs_anchor_pooled_raw"] == 0.65
    assert d["nav_vs_qqq_excess_full_period"] == 0.05
    # All 13 keys (9 legacy + 4 new) round-tripped
    assert set(d.keys()) == {
        "n_features", "n_families", "n_dates",
        "ic_mean", "ic_std", "ic_ir",
        "turnover_proxy", "corr_concentration", "horizon",
        "nav_sharpe", "nav_max_dd",
        "nav_correlation_vs_anchor_pooled_raw",
        "nav_vs_qqq_excess_full_period",
    }


# ── ObjectiveWeights: 4 new w_nav_* fields + is_nav_based() ─────────────────


def test_objective_weights_defaults_zero_for_nav_weights():
    """ObjectiveWeights() with no kwargs leaves all w_nav_* at 0.0."""
    w = ObjectiveWeights()
    assert w.w_nav_sharpe == 0.0
    assert w.w_nav_max_dd_penalty == 0.0
    assert w.w_nav_orthogonality == 0.0
    assert w.w_vs_qqq_excess == 0.0


def test_objective_weights_is_nav_based_legacy():
    """v1_legacy weights → is_nav_based()=False."""
    w = ObjectiveWeights()
    assert w.is_nav_based() is False
    # Modifying only legacy weights still legacy
    w2 = ObjectiveWeights(w_ir=2.0, w_turnover=0.1)
    assert w2.is_nav_based() is False


def test_objective_weights_is_nav_based_each_nav_weight():
    """Any single non-zero w_nav_* → is_nav_based()=True."""
    for kw in (
        {"w_nav_sharpe": 0.15},
        {"w_nav_max_dd_penalty": 0.05},
        {"w_nav_orthogonality": 1.0},
        {"w_vs_qqq_excess": 0.5},
    ):
        w = ObjectiveWeights(**kw)
        assert w.is_nav_based() is True, f"failed for kw={kw}"


def test_objective_weights_kwargs_construction():
    """Dict-spread construction (yaml-driven) works for both v1 and v2."""
    w_legacy = ObjectiveWeights(**{"w_ir": 0.7, "w_turnover": 0.1})
    assert w_legacy.is_nav_based() is False
    w_v2 = ObjectiveWeights(**{
        "w_ir": 0.7, "w_nav_sharpe": 0.15, "w_nav_max_dd_penalty": 0.05,
    })
    assert w_v2.is_nav_based() is True
    assert w_v2.w_nav_sharpe == 0.15


# ── compute_objective: v1_legacy bit-identical, v2 math, NaN-safety ──────────


def _legacy_metrics(ic_ir: float = 2.5) -> CompositeMetrics:
    return CompositeMetrics(
        n_features=3, n_families=2, n_dates=100,
        ic_mean=0.05, ic_std=0.1, ic_ir=ic_ir,
        turnover_proxy=0.3, corr_concentration=0.4,
    )


def test_compute_objective_v1_legacy_bit_identical():
    """Default ObjectiveWeights() reproduces pre-PRD-AC math exactly."""
    m = _legacy_metrics()
    o = compute_objective(m, benchmark_excess=0.02, regime_stddev=0.05)
    # Manual: 1.0*2.5 - 0.5*0.3 - 1.0*0.4 + 0.3*0.02 - 0.2*0.05
    expected = 1.0 * 2.5 - 0.5 * 0.3 - 1.0 * 0.4 + 0.3 * 0.02 - 0.2 * 0.05
    assert abs(o - expected) < 1e-9


def test_compute_objective_v2_nav_full_math():
    """v2_nav_based math matches PRD §4.4 example."""
    m = CompositeMetrics(
        n_features=3, n_families=2, n_dates=100,
        ic_mean=0.05, ic_std=0.1, ic_ir=2.5,
        turnover_proxy=0.3, corr_concentration=0.4,
        nav_sharpe=1.2, nav_max_dd=-0.18,
        nav_correlation_vs_anchor_pooled_raw=0.65,
        nav_vs_qqq_excess_full_period=0.05,
    )
    w = ObjectiveWeights(
        w_nav_sharpe=0.15, w_nav_max_dd_penalty=0.05,
        w_nav_orthogonality=1.0, w_vs_qqq_excess=0.5,
    )
    o = compute_objective(m, weights=w)
    legacy = 1.0 * 2.5 - 0.5 * 0.3 - 1.0 * 0.4
    nav = 0.15 * 1.2 - 0.05 * 0.18 - 1.0 * (0.65 - 0.5) + 0.5 * 0.05
    expected = legacy + nav
    assert abs(o - expected) < 1e-9


def test_compute_objective_v2_orthogonality_no_penalty_below_threshold():
    """Orthogonality term: max(0, raw_corr - 0.5) → corr<0.5 = no penalty."""
    m = CompositeMetrics(
        n_features=3, n_families=2, n_dates=100,
        ic_mean=0.05, ic_std=0.1, ic_ir=2.5,
        turnover_proxy=0.3, corr_concentration=0.4,
        nav_correlation_vs_anchor_pooled_raw=0.30,  # below 0.5 threshold
    )
    w = ObjectiveWeights(w_nav_orthogonality=1.0)
    o = compute_objective(m, weights=w)
    expected = 1.0 * 2.5 - 0.5 * 0.3 - 1.0 * 0.4  # legacy only, no orth penalty
    assert abs(o - expected) < 1e-9


def test_compute_objective_v2_weights_with_nan_metrics_falls_back_to_legacy():
    """v2 weights enabled but NAV metrics NaN → NAV terms contribute 0."""
    m = _legacy_metrics()  # all nav_* default NaN
    w = ObjectiveWeights(
        w_nav_sharpe=0.15, w_nav_max_dd_penalty=0.05,
        w_nav_orthogonality=1.0, w_vs_qqq_excess=0.5,
    )
    o = compute_objective(m, weights=w)
    # With all nav_* = NaN, NAV terms collapse to 0; legacy terms unchanged
    expected = 1.0 * 2.5 - 0.5 * 0.3 - 1.0 * 0.4
    assert abs(o - expected) < 1e-9


def test_compute_objective_returns_neginf_on_nan_ic_ir():
    """Pre-existing invariant: NaN IC_IR returns -inf (no signal)."""
    m = CompositeMetrics(
        n_features=3, n_families=2, n_dates=100,
        ic_mean=float("nan"), ic_std=0.1, ic_ir=float("nan"),
        turnover_proxy=0.3, corr_concentration=0.4,
        nav_sharpe=1.2,  # NAV present but should not save the trial
    )
    w = ObjectiveWeights(w_nav_sharpe=0.15)
    o = compute_objective(m, weights=w)
    assert o == float("-inf")


# ── RCMArchive: schema migration + insert_trial persistence ──────────────────


def _make_trial(metrics: CompositeMetrics, objective: float = 1.5) -> TrialResult:
    spec = ResearchCompositeSpec(
        features=("beta_spy_60d",), weights=(1.0,), family_counts={"A": 1},
    )
    return TrialResult(spec=spec, metrics=metrics, objective=objective)


def test_rcm_archive_fresh_db_has_nav_columns(tmp_path):
    """Fresh DB after _init_schema includes 4 new NAV cols on rcm_trials."""
    db = tmp_path / "fresh.db"
    RCMArchive(db)  # triggers _init_schema
    with sqlite3.connect(db) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(rcm_trials)").fetchall()]
    for col in (
        "nav_sharpe", "nav_max_dd",
        "nav_correlation_vs_anchor_pooled_raw",
        "nav_vs_qqq_excess_full_period",
    ):
        assert col in cols, f"fresh DB missing {col}; got {cols}"


def test_rcm_archive_insert_trial_v1_legacy_persists_null(tmp_path):
    """v1_legacy trial with NaN nav_* → SQLite NULL in archive."""
    db = tmp_path / "v1.db"
    arch = RCMArchive(db)
    arch.record_study(study_id="s1", lineage_tag="test")
    m = _legacy_metrics()
    arch.insert_trial(_make_trial(m), lineage_tag="test", study_id="s1")
    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT nav_sharpe, nav_max_dd, "
            "nav_correlation_vs_anchor_pooled_raw, "
            "nav_vs_qqq_excess_full_period FROM rcm_trials"
        ).fetchone()
    assert row == (None, None, None, None)


def test_rcm_archive_insert_trial_v2_persists_values(tmp_path):
    """v2 trial with real nav_* → archive stores numeric values."""
    db = tmp_path / "v2.db"
    arch = RCMArchive(db)
    arch.record_study(study_id="s1", lineage_tag="test")
    m = CompositeMetrics(
        n_features=1, n_families=1, n_dates=100,
        ic_mean=0.05, ic_std=0.1, ic_ir=2.0,
        turnover_proxy=0.3, corr_concentration=0.4,
        nav_sharpe=1.2, nav_max_dd=-0.18,
        nav_correlation_vs_anchor_pooled_raw=0.65,
        nav_vs_qqq_excess_full_period=0.05,
    )
    arch.insert_trial(_make_trial(m), lineage_tag="test", study_id="s1")
    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT nav_sharpe, nav_max_dd, "
            "nav_correlation_vs_anchor_pooled_raw, "
            "nav_vs_qqq_excess_full_period FROM rcm_trials"
        ).fetchone()
    assert row == (1.2, -0.18, 0.65, 0.05)


# ── ResearchMiner.record_study: stamps objective_version + new weights ───────


def test_research_miner_record_study_stamps_v1_legacy(tmp_path):
    """Default ObjectiveWeights() → study JSON has objective_version=v1_legacy
    and all w_nav_*=0."""
    import pandas as pd
    from core.mining.research_miner import ResearchMiner

    # Minimal panel (won't run trials, just need miner construction to record study)
    dates = pd.date_range("2020-01-01", periods=10, freq="B")
    fwd = pd.DataFrame(0.01, index=dates, columns=["AAPL"])
    panel_map = {"beta_spy_60d": pd.DataFrame(0.5, index=dates, columns=["AAPL"])}

    db = tmp_path / "study.db"
    arch = RCMArchive(db)
    ResearchMiner(
        factor_panel_map=panel_map, fwd_returns=fwd,
        objective_weights=ObjectiveWeights(),  # default = v1_legacy
        archive=arch, lineage_tag="test", study_id="s1",
    )
    with sqlite3.connect(db) as conn:
        ow_json = conn.execute(
            "SELECT objective_weights_json FROM rcm_studies WHERE study_id='s1'"
        ).fetchone()[0]
    ow = json.loads(ow_json)
    assert ow["objective_version"] == "v1_legacy"
    assert ow["w_nav_sharpe"] == 0.0
    assert ow["w_nav_max_dd_penalty"] == 0.0
    assert ow["w_nav_orthogonality"] == 0.0
    assert ow["w_vs_qqq_excess"] == 0.0


def test_research_miner_record_study_stamps_v2_nav_based(tmp_path):
    """Non-zero w_nav_* → study JSON has objective_version=v2_nav_based."""
    import pandas as pd
    from core.mining.research_miner import ResearchMiner

    dates = pd.date_range("2020-01-01", periods=10, freq="B")
    fwd = pd.DataFrame(0.01, index=dates, columns=["AAPL"])
    panel_map = {"beta_spy_60d": pd.DataFrame(0.5, index=dates, columns=["AAPL"])}

    db = tmp_path / "study.db"
    arch = RCMArchive(db)
    ResearchMiner(
        factor_panel_map=panel_map, fwd_returns=fwd,
        objective_weights=ObjectiveWeights(w_nav_sharpe=0.15),
        archive=arch, lineage_tag="test", study_id="s1",
    )
    with sqlite3.connect(db) as conn:
        ow_json = conn.execute(
            "SELECT objective_weights_json FROM rcm_studies WHERE study_id='s1'"
        ).fetchone()[0]
    ow = json.loads(ow_json)
    assert ow["objective_version"] == "v2_nav_based"
    assert ow["w_nav_sharpe"] == 0.15
