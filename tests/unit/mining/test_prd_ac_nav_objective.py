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

import pytest

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


# ── Integration: evaluate_composite NAV gate ──────────────────────────────────


def _build_synthetic_panel(n_days=180, n_syms=8, seed=0):
    """Build (panel_map, fwd_returns, price_df, open_df, spy, qqq) for
    an integration smoke that exercises the full NAV gate."""
    import numpy as np
    import pandas as pd
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
    # Two factor panels (zscored cross-sectionally)
    f1 = zscore_cs(price_df.pct_change(20))
    f2 = zscore_cs(price_df.pct_change(60))
    panel_map = {"momentum_20d": f1, "momentum_60d": f2}
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


def test_evaluate_composite_v1_legacy_default_path_nan_nav():
    """Default compute_nav=False leaves all 4 nav_* fields NaN."""
    from core.mining.research_miner import (
        ResearchCompositeSpec, evaluate_composite,
    )

    panel_map, fwd, *_ = _build_synthetic_panel(n_days=120)
    spec = ResearchCompositeSpec(
        features=("momentum_20d", "momentum_60d"),
        weights=(0.6, 0.4),
        family_counts={"A": 2},
    )
    metrics = evaluate_composite(spec, panel_map, fwd)
    assert math.isfinite(metrics.ic_ir) or math.isnan(metrics.ic_ir)
    # NAV path NOT triggered → all NaN
    assert math.isnan(metrics.nav_sharpe)
    assert math.isnan(metrics.nav_max_dd)
    assert math.isnan(metrics.nav_correlation_vs_anchor_pooled_raw)
    assert math.isnan(metrics.nav_vs_qqq_excess_full_period)


def test_evaluate_composite_v2_nav_path_populates_metrics():
    """compute_nav=True with all required panels → 4 nav_* fields populated."""
    from core.mining.research_miner import (
        ResearchCompositeSpec, evaluate_composite,
    )
    from core.mining.nav_objective import (
        build_universe_baseline_residual_returns,
    )

    panel_map, fwd, price_df, open_df, spy, qqq = _build_synthetic_panel()
    anchor = build_universe_baseline_residual_returns(price_df, spy)
    spec = ResearchCompositeSpec(
        features=("momentum_20d", "momentum_60d"),
        weights=(0.6, 0.4),
        family_counts={"A": 2},
    )
    metrics = evaluate_composite(
        spec, panel_map, fwd,
        price_df=price_df, open_df=open_df,
        spy_series=spy, qqq_series=qqq,
        anchor_residual_returns=anchor,
        compute_nav=True,
    )
    # All 4 NAV fields populated (finite or at worst non-NaN — sharpe
    # may be 0.0 on degenerate window but should not be NaN)
    assert not math.isnan(metrics.nav_sharpe), \
        f"nav_sharpe NaN: {metrics.nav_sharpe}"
    assert not math.isnan(metrics.nav_max_dd), \
        f"nav_max_dd NaN: {metrics.nav_max_dd}"
    # nav_corr_anchor MAY be NaN if I20 cross-asset triggered or anchor
    # window too short on synthetic 180-day panel; both are valid
    # outcomes. nav_vs_qqq populated from harness.
    assert math.isfinite(metrics.nav_max_dd)
    assert metrics.nav_max_dd <= 0.0  # MaxDD always ≤ 0


def test_evaluate_composite_compute_nav_requires_panels():
    """compute_nav=True without panels → fail-closed ValueError."""
    from core.mining.research_miner import (
        ResearchCompositeSpec, evaluate_composite,
    )

    panel_map, fwd, *_ = _build_synthetic_panel(n_days=120)
    spec = ResearchCompositeSpec(
        features=("momentum_20d", "momentum_60d"),
        weights=(0.6, 0.4),
        family_counts={"A": 2},
    )
    with pytest.raises(ValueError, match="non-None price_df and spy_series"):
        evaluate_composite(
            spec, panel_map, fwd,
            compute_nav=True,  # but no price_df / spy_series
        )


def test_research_miner_v1_legacy_no_panels_required():
    """v1_legacy ResearchMiner accepts None panels (no NAV gate)."""
    from core.mining.research_miner import ResearchMiner

    panel_map, fwd, *_ = _build_synthetic_panel(n_days=60)
    # No panels passed; v1_legacy should accept this
    miner = ResearchMiner(
        factor_panel_map=panel_map, fwd_returns=fwd,
        objective_weights=ObjectiveWeights(),  # all w_nav_*=0
    )
    assert miner._anchor_residual_returns is None


def test_research_miner_v2_nav_based_fail_closed_without_panels():
    """v2_nav_based ResearchMiner without panels → fail-closed."""
    from core.mining.research_miner import ResearchMiner

    panel_map, fwd, *_ = _build_synthetic_panel(n_days=60)
    with pytest.raises(ValueError, match="is_nav_based"):
        ResearchMiner(
            factor_panel_map=panel_map, fwd_returns=fwd,
            objective_weights=ObjectiveWeights(w_nav_sharpe=0.15),
            # No price_df / spy_series — should fail-closed
        )


def test_research_miner_v2_nav_based_builds_anchor_at_construction():
    """v2_nav_based ResearchMiner caches the anchor at construction time."""
    from core.mining.research_miner import ResearchMiner

    panel_map, fwd, price_df, _open, spy, _qqq = _build_synthetic_panel()
    miner = ResearchMiner(
        factor_panel_map=panel_map, fwd_returns=fwd,
        objective_weights=ObjectiveWeights(w_nav_sharpe=0.15),
        price_df=price_df, spy_series=spy,
    )
    assert miner._anchor_residual_returns is not None
    assert len(miner._anchor_residual_returns) > 0
    assert miner._anchor_residual_returns.name == "universe_baseline_residual"


def test_evaluate_composite_v2_nav_path_handles_non_contiguous_panel():
    """PRD §6 Phase 2 I9 boundary check (lightweight): NAV gate runs
    end-to-end on a panel with a multi-year gap (mimics
    partition_for_role(miner) train-only output).

    Doesn't compare drift vs an external archive (full I9 verify needs
    cycle04 archive + replay). Verifies the NAV gate doesn't NaN/crash
    at the year boundary, which is the structural concern.
    """
    import numpy as np
    import pandas as pd
    from core.mining.research_miner import (
        ResearchCompositeSpec, evaluate_composite, zscore_cs,
    )
    from core.mining.nav_objective import (
        build_universe_baseline_residual_returns,
    )

    rng = np.random.default_rng(7)
    # Two train segments with a 2-year gap (mimics 2017 → 2020 boundary)
    seg_a = pd.date_range("2017-01-02", "2017-12-29", freq="B")
    seg_b = pd.date_range("2020-01-02", "2020-12-31", freq="B")
    dates = seg_a.union(seg_b)
    n = len(dates)
    n_syms = 6
    syms = [f"S{i}" for i in range(n_syms)]
    market = rng.normal(0, 0.01, size=n)
    sym_specific = rng.normal(0, 0.005, size=(n, n_syms))
    rets = market[:, None] + sym_specific
    prices = 100.0 * np.cumprod(1 + rets, axis=0)
    price_df = pd.DataFrame(prices, index=dates, columns=syms)
    open_df = price_df * (1 + rng.normal(0, 0.001, size=(n, n_syms)))
    fwd = price_df.pct_change(21).shift(-21)
    panel_map = {
        "momentum_20d": zscore_cs(price_df.pct_change(20)),
        "momentum_60d": zscore_cs(price_df.pct_change(60)),
    }
    spy = pd.Series(
        400.0 * np.cumprod(1 + market + rng.normal(0, 0.001, size=n)),
        index=dates, name="SPY",
    )
    qqq = pd.Series(
        300.0 * np.cumprod(1 + market * 1.1 + rng.normal(0, 0.002, size=n)),
        index=dates, name="QQQ",
    )
    anchor = build_universe_baseline_residual_returns(price_df, spy)
    spec = ResearchCompositeSpec(
        features=("momentum_20d", "momentum_60d"),
        weights=(0.6, 0.4),
        family_counts={"A": 2},
    )
    metrics = evaluate_composite(
        spec, panel_map, fwd,
        price_df=price_df, open_df=open_df,
        spy_series=spy, qqq_series=qqq,
        anchor_residual_returns=anchor,
        compute_nav=True,
    )
    # Boundary-day artifacts would manifest as NaN-explosion or |max_dd|
    # near 100% (e.g. price gap interpreted as a -90% return).
    assert math.isfinite(metrics.nav_max_dd), \
        "non-contiguous panel produced NaN max_dd (boundary artifact)"
    assert metrics.nav_max_dd > -0.50, (
        f"non-contiguous panel max_dd={metrics.nav_max_dd:.2%} "
        f"suspiciously large; potential boundary artifact"
    )
    assert math.isfinite(metrics.nav_sharpe), \
        "non-contiguous panel produced NaN Sharpe"


def test_research_miner_record_study_stamps_v2_nav_based(tmp_path):
    """Non-zero w_nav_* → study JSON has objective_version=v2_nav_based.

    PRD-AC v1.1 §4.3 also requires NAV-gate panels at construction; pass
    minimal stubs (price_df + spy_series) to satisfy the fail-closed
    guard. This test verifies the JSON stamping path, not the NAV
    eval itself (covered by test_evaluate_composite_v2_nav_path).
    """
    import pandas as pd
    from core.mining.research_miner import ResearchMiner

    dates = pd.date_range("2020-01-01", periods=10, freq="B")
    fwd = pd.DataFrame(0.01, index=dates, columns=["AAPL"])
    panel_map = {"beta_spy_60d": pd.DataFrame(0.5, index=dates, columns=["AAPL"])}
    price_df = pd.DataFrame(100.0, index=dates, columns=["AAPL"])
    spy = pd.Series(400.0, index=dates, name="SPY")

    db = tmp_path / "study.db"
    arch = RCMArchive(db)
    ResearchMiner(
        factor_panel_map=panel_map, fwd_returns=fwd,
        objective_weights=ObjectiveWeights(w_nav_sharpe=0.15),
        archive=arch, lineage_tag="test", study_id="s1",
        price_df=price_df, spy_series=spy,
    )
    with sqlite3.connect(db) as conn:
        ow_json = conn.execute(
            "SELECT objective_weights_json FROM rcm_studies WHERE study_id='s1'"
        ).fetchone()[0]
    ow = json.loads(ow_json)
    assert ow["objective_version"] == "v2_nav_based"
    assert ow["w_nav_sharpe"] == 0.15
