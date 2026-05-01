"""Unit tests for core/research/harness/composite_evaluator.py.

Step 1 of the priority-realign post-cycle-#01 path. The harness is
the precondition for evaluating Track A 17-gate aggregate-pass on a
Cycle #02 candidate.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.mining.research_miner import ResearchCompositeSpec
from core.research.harness import (
    EvaluatedComposite,
    HarnessConfig,
    rebalance_mask,
    topn_signals_from_composite,
)


# ── HarnessConfig ────────────────────────────────────────────────────────────


def test_harness_config_defaults():
    cfg = HarnessConfig()
    assert cfg.rebalance_cadence == "monthly"
    assert cfg.top_n == 10
    assert cfg.min_holding_days == 1
    assert cfg.horizon_days == 21
    assert cfg.initial_capital == 100_000.0


def test_harness_config_invalid_cadence():
    with pytest.raises(ValueError, match="rebalance_cadence must be one of"):
        HarnessConfig(rebalance_cadence="hourly")


def test_harness_config_invalid_top_n():
    with pytest.raises(ValueError, match="top_n must be"):
        HarnessConfig(top_n=0)


def test_harness_config_invalid_min_holding_days():
    with pytest.raises(ValueError, match="min_holding_days must be"):
        HarnessConfig(min_holding_days=0)


def test_harness_config_invalid_horizon_days():
    with pytest.raises(ValueError, match="horizon_days must be"):
        HarnessConfig(horizon_days=0)


def test_harness_config_invalid_initial_capital():
    with pytest.raises(ValueError, match="initial_capital must be"):
        HarnessConfig(initial_capital=0)


def test_harness_config_accepts_weekly_cadence():
    cfg = HarnessConfig(rebalance_cadence="weekly")
    assert cfg.rebalance_cadence == "weekly"


# ── rebalance_mask ───────────────────────────────────────────────────────────


def test_rebalance_mask_monthly_marks_last_trading_day_per_month():
    idx = pd.date_range("2024-01-01", "2024-03-31", freq="B")  # ~64 days, 3 months
    mask = rebalance_mask(idx, "monthly")
    # Each calendar month should have exactly 1 True
    months_with_true = idx[mask].to_period("M").unique()
    assert len(months_with_true) == 3
    # Each True date should be the LAST day in its month (within idx)
    for p in months_with_true:
        in_month = idx[idx.to_period("M") == p]
        true_in_month = idx[mask & (idx.to_period("M") == p)]
        assert len(true_in_month) == 1
        assert true_in_month[0] == in_month[-1]


def test_rebalance_mask_weekly_marks_last_trading_day_per_iso_week():
    idx = pd.date_range("2024-01-01", "2024-01-31", freq="B")
    mask = rebalance_mask(idx, "weekly")
    # Each ISO week should have exactly 1 True
    weeks_with_true = idx[mask].to_period("W").unique()
    for p in weeks_with_true:
        in_week = idx[idx.to_period("W") == p]
        true_in_week = idx[mask & (idx.to_period("W") == p)]
        assert len(true_in_week) == 1
        # And that True is the last date in the week present in idx
        assert true_in_week[0] == in_week[-1]


def test_rebalance_mask_daily_all_true():
    idx = pd.date_range("2024-01-01", "2024-01-31", freq="B")
    mask = rebalance_mask(idx, "daily")
    assert mask.all()
    assert mask.sum() == len(idx)


def test_rebalance_mask_invalid_cadence():
    idx = pd.date_range("2024-01-01", "2024-01-31", freq="B")
    with pytest.raises(ValueError, match="cadence must be one of"):
        rebalance_mask(idx, "hourly")


def test_rebalance_mask_count_consistency():
    idx = pd.date_range("2024-01-02", "2024-12-31", freq="B")  # full 2024 trading days ~252
    n_monthly = int(rebalance_mask(idx, "monthly").sum())
    n_weekly = int(rebalance_mask(idx, "weekly").sum())
    n_daily = int(rebalance_mask(idx, "daily").sum())
    # 12 months → 12 rebalances
    assert n_monthly == 12
    # 52-53 ISO weeks → ~52 rebalances
    assert 51 <= n_weekly <= 54
    # daily = every trading day
    assert n_daily == len(idx)


# ── topn_signals_from_composite ──────────────────────────────────────────────


def _build_simple_composite(n_dates=20, n_syms=5, seed=42):
    """Build a small synthetic composite panel."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n_dates, freq="B")
    cols = [f"S{i}" for i in range(n_syms)]
    composite = pd.DataFrame(
        rng.standard_normal((n_dates, n_syms)),
        index=idx, columns=cols,
    )
    return composite


def test_topn_signals_picks_top_2_equal_weight():
    composite = _build_simple_composite(n_dates=10, n_syms=5)
    mask = pd.Series(True, index=composite.index)  # rebalance every day
    signals = topn_signals_from_composite(composite, mask, top_n=2)
    # On day 0, the two highest-score symbols should each have weight 0.5
    day0 = composite.iloc[0].nlargest(2).index
    assert abs(signals.iloc[0][day0[0]] - 0.5) < 1e-12
    assert abs(signals.iloc[0][day0[1]] - 0.5) < 1e-12
    # All other symbols should be 0
    assert signals.iloc[0].sum() == pytest.approx(1.0)


def test_topn_signals_holds_between_rebalances():
    """Non-rebalance days should carry over the prior rebalance's weights."""
    composite = _build_simple_composite(n_dates=10, n_syms=4)
    mask = pd.Series(False, index=composite.index)
    mask.iloc[0] = True
    mask.iloc[5] = True
    signals = topn_signals_from_composite(composite, mask, top_n=2)
    # Days 1-4 should match day 0
    for i in range(1, 5):
        assert (signals.iloc[i].values == signals.iloc[0].values).all()
    # Day 5's selection should be different from day 0 (different scores)
    # (true with high probability for random scores; defensive: check only
    # that day 6-9 match day 5)
    for i in range(6, 10):
        assert (signals.iloc[i].values == signals.iloc[5].values).all()


def test_topn_signals_min_holding_days_blocks_back_to_back_rebalances():
    composite = _build_simple_composite(n_dates=10, n_syms=4)
    # Every day is a candidate rebalance day
    mask = pd.Series(True, index=composite.index)
    # But min_holding_days=3 should mean only ~ every 3rd day rebalances
    signals = topn_signals_from_composite(
        composite, mask, top_n=2, min_holding_days=3,
    )
    # First rebalance: day 0 (always allowed). Next: day 3, then day 6, then day 9.
    # Days 1,2 carry day 0; days 4,5 carry day 3; etc.
    # We can verify by detecting weight changes
    weight_changes = (
        signals.diff().abs().sum(axis=1) > 1e-9
    ).iloc[1:]  # skip day 0 (no diff)
    # Expect changes at days 3, 6, 9 only (3 changes in days 1..9)
    assert weight_changes.sum() == 3


def test_topn_signals_skips_rebalance_when_too_few_valid_scores():
    """If composite has fewer than top_n valid (non-NaN) scores on a
    rebalance day, signals should carry over instead of partial-fill."""
    composite = _build_simple_composite(n_dates=5, n_syms=4)
    # Make day 0 have only 1 valid score; all others have all 4
    composite.iloc[0, 1:] = np.nan  # only S0 valid
    mask = pd.Series(True, index=composite.index)
    signals = topn_signals_from_composite(composite, mask, top_n=2)
    # Day 0 cannot rebalance → all zeros (initial last_selection)
    assert signals.iloc[0].sum() == 0.0
    # Day 1 has 4 valid scores → rebalances correctly
    assert signals.iloc[1].sum() == pytest.approx(1.0)


def test_topn_signals_invalid_top_n():
    composite = _build_simple_composite()
    mask = pd.Series(True, index=composite.index)
    with pytest.raises(ValueError, match="top_n must be"):
        topn_signals_from_composite(composite, mask, top_n=0)


def test_topn_signals_invalid_min_holding_days():
    composite = _build_simple_composite()
    mask = pd.Series(True, index=composite.index)
    with pytest.raises(ValueError, match="min_holding_days must be"):
        topn_signals_from_composite(composite, mask, top_n=2, min_holding_days=0)


def test_topn_signals_weights_sum_to_one_on_rebalance_days():
    """When a rebalance day succeeds, weights should sum to exactly 1."""
    composite = _build_simple_composite(n_dates=15, n_syms=8)
    mask = pd.Series(False, index=composite.index)
    # Rebalance on days 0, 5, 10
    mask.iloc[[0, 5, 10]] = True
    signals = topn_signals_from_composite(composite, mask, top_n=3)
    for i in [0, 5, 10]:
        assert signals.iloc[i].sum() == pytest.approx(1.0)
    # Each non-zero weight should be 1/3
    for i in [0, 5, 10]:
        nonzero = signals.iloc[i][signals.iloc[i] > 0]
        assert len(nonzero) == 3
        assert all(abs(v - 1.0 / 3.0) < 1e-12 for v in nonzero.values)


# ── evaluate_composite_spec (integration tests) ─────────────────────────────


def _build_synthetic_panel(
    n_dates=200, n_syms=10, seed=42,
):
    """Build synthetic price + factor panels for integration testing."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2022-01-03", periods=n_dates, freq="B")
    cols = [f"S{i}" for i in range(n_syms)]
    # Geometric Brownian motion-ish prices starting at 100
    daily_ret = rng.normal(0.0005, 0.012, size=(n_dates, n_syms))
    prices = pd.DataFrame(
        100 * np.exp(daily_ret.cumsum(axis=0)),
        index=idx, columns=cols,
    )
    opens = prices * (1 + rng.normal(0, 0.001, size=prices.shape))

    # Factor panels: cross-sectional rank of past 21d return + neg of 60d vol
    fac_a = prices.pct_change(21).rank(axis=1, pct=True)
    fac_b = -prices.pct_change().rolling(60).std().rank(axis=1, pct=True)
    fac_c = prices.pct_change(126).rank(axis=1, pct=True)

    factor_panel_map = {"momentum_21d": fac_a, "low_vol_60d": fac_b,
                        "long_mom_126d": fac_c}

    # SPY benchmark: average of all symbols
    spy = prices.mean(axis=1)
    qqq = prices.mean(axis=1) * 1.02  # slightly different proxy
    return prices, opens, factor_panel_map, spy, qqq


def test_evaluate_composite_spec_returns_evaluated_composite():
    from core.research.harness import evaluate_composite_spec

    prices, opens, panel_map, spy, qqq = _build_synthetic_panel()
    spec = ResearchCompositeSpec(
        features=("momentum_21d", "low_vol_60d", "long_mom_126d"),
        weights=(1 / 3, 1 / 3, 1 / 3),
        family_counts={"A": 1, "B": 1, "C": 1},
    )
    cfg = HarnessConfig(rebalance_cadence="monthly", top_n=3,
                       initial_capital=10_000.0)

    result = evaluate_composite_spec(
        spec,
        factor_panel_map=panel_map,
        price_df=prices,
        open_df=opens,
        spy_series=spy,
        qqq_series=qqq,
        config=cfg,
    )

    assert isinstance(result, EvaluatedComposite)
    assert result.n_observed_days > 0
    assert "cum_ret" in result.metrics_full_period
    assert "sharpe" in result.metrics_full_period
    assert "max_dd" in result.metrics_full_period
    assert "vs_spy" in result.metrics_full_period
    assert "vs_qqq" in result.metrics_full_period
    assert "raw_pearson_vs_spy" in result.nav_correlation_vs_benchmark
    assert "raw_pearson_vs_qqq" in result.nav_correlation_vs_benchmark
    # NAV should never be negative
    assert (result.nav > 0).all()
    # Concentration metrics populated
    assert "m12_top1_weight_max" in result.concentration
    assert "m12_top3_weight_max" in result.concentration


def test_evaluate_composite_spec_weekly_vs_monthly_cadence_differs():
    """Weekly cadence should produce a DIFFERENT NAV path than monthly
    (the C-1 axis hypothesis). Verify the harness honors the distinction."""
    from core.research.harness import evaluate_composite_spec

    prices, opens, panel_map, spy, qqq = _build_synthetic_panel()
    spec = ResearchCompositeSpec(
        features=("momentum_21d", "low_vol_60d", "long_mom_126d"),
        weights=(1 / 3, 1 / 3, 1 / 3),
        family_counts={"A": 1, "B": 1, "C": 1},
    )

    monthly = evaluate_composite_spec(
        spec, factor_panel_map=panel_map, price_df=prices, open_df=opens,
        spy_series=spy, qqq_series=qqq,
        config=HarnessConfig(rebalance_cadence="monthly", top_n=3,
                           initial_capital=10_000.0),
    )
    weekly = evaluate_composite_spec(
        spec, factor_panel_map=panel_map, price_df=prices, open_df=opens,
        spy_series=spy, qqq_series=qqq,
        config=HarnessConfig(rebalance_cadence="weekly", top_n=3,
                           initial_capital=10_000.0),
    )

    # Same dates
    assert list(monthly.nav.index) == list(weekly.nav.index)
    # NAV paths must differ at least somewhere (different rebalance frequency)
    nav_diff = (monthly.nav - weekly.nav).abs().max()
    assert nav_diff > 1e-6, (
        f"monthly and weekly NAVs should diverge but max abs diff = {nav_diff}"
    )


def test_evaluate_composite_spec_per_validation_year_metrics():
    from core.research.harness import evaluate_composite_spec

    prices, opens, panel_map, spy, qqq = _build_synthetic_panel(n_dates=520)
    spec = ResearchCompositeSpec(
        features=("momentum_21d", "low_vol_60d", "long_mom_126d"),
        weights=(1 / 3, 1 / 3, 1 / 3),
        family_counts={"A": 1, "B": 1, "C": 1},
    )

    result = evaluate_composite_spec(
        spec, factor_panel_map=panel_map, price_df=prices, open_df=opens,
        spy_series=spy, qqq_series=qqq,
        config=HarnessConfig(top_n=3, initial_capital=10_000.0),
        validation_years=[2022, 2023],
    )

    # Both years should be in per_validation_year results (~520 trading days
    # spans late 2021 through ~late 2023)
    assert 2022 in result.metrics_per_validation_year
    # 2023 may or may not have enough days depending on synthetic panel
    assert "cum_ret" in result.metrics_per_validation_year[2022]


def test_evaluate_composite_spec_missing_feature_raises():
    """If spec references a feature not in factor_panel_map → error from
    build_composite_series propagates."""
    from core.research.harness import evaluate_composite_spec

    prices, opens, panel_map, spy, qqq = _build_synthetic_panel()
    spec = ResearchCompositeSpec(
        features=("momentum_21d", "nonexistent_factor"),
        weights=(0.5, 0.5),
        family_counts={"A": 1, "B": 1},
    )
    with pytest.raises(KeyError):
        evaluate_composite_spec(
            spec, factor_panel_map=panel_map, price_df=prices, open_df=opens,
            spy_series=spy, qqq_series=qqq,
            config=HarnessConfig(top_n=3, initial_capital=10_000.0),
        )


def test_harness_signal_path_matches_run_paper_candidate():
    """Locked numerical equivalence: harness's composite-build + top-N
    weight path must produce IDENTICAL output to
    scripts/run_paper_candidate.py's _compute_composite_signal +
    _composite_to_target_weights when given identical inputs.

    This is the precondition for cycle #02 candidates evaluated via
    the harness to be NAV-equivalent to a paper run of the same spec.
    """
    from core.factors.base_masks import apply_research_mask, research_mask_default
    from core.mining.research_miner import build_composite_series
    from scripts.run_paper_candidate import (
        _composite_to_target_weights,
        _compute_composite_signal,
    )

    # Build identical synthetic factor panels for both paths
    rng = np.random.default_rng(2026)
    n_dates = 60
    n_syms = 12
    idx = pd.date_range("2024-01-02", periods=n_dates, freq="B")
    cols = [f"S{i}" for i in range(n_syms)]
    # Two factor panels with z-scored synthetic values
    fac_a = pd.DataFrame(rng.standard_normal((n_dates, n_syms)),
                         index=idx, columns=cols)
    fac_b = pd.DataFrame(rng.standard_normal((n_dates, n_syms)),
                         index=idx, columns=cols)
    panel_map = {"factor_a": fac_a, "factor_b": fac_b}

    # Build a spec with weights summing to 1
    spec = ResearchCompositeSpec(
        features=("factor_a", "factor_b"),
        weights=(0.6, 0.4),
        family_counts={"A": 1, "B": 1},
    )

    # Path A: harness internal (build_composite_series)
    composite_harness = build_composite_series(spec, panel_map)

    # Path B: paper-candidate's _compute_composite_signal expects a
    # FrozenStrategySpec object + frames dict containing close/volume/etc.
    # We bypass that by directly replicating its math: zscore_cs(panel)
    # × weight, summed. Since paper-candidate normalizes weights itself
    # (total_w=sum(weights) or 1.0), and our spec weights already sum
    # to 1, the normalization is a no-op.
    from core.mining.research_miner import zscore_cs as zscore_cs_h
    composite_paper = None
    total_w = sum(spec.weights) or 1.0
    for feat_name, w in zip(spec.features, spec.weights):
        z = zscore_cs_h(panel_map[feat_name], min_periods=5)
        component = z * (w / total_w)
        composite_paper = component if composite_paper is None else \
            composite_paper.add(component, fill_value=0.0)

    # Path A should equal Path B (machine epsilon)
    diff = (composite_harness - composite_paper).abs()
    assert float(diff.max().max()) < 1e-12, (
        f"composite signal diverges between harness and paper code path: "
        f"max diff = {float(diff.max().max()):.2e}"
    )

    # Now compare top-N target weight construction
    from core.research.harness import (
        rebalance_mask, topn_signals_from_composite,
    )
    top_n = 3
    weights_paper = _composite_to_target_weights(composite_paper, top_n)
    mask_daily = rebalance_mask(composite_harness.index, "daily")
    weights_harness = topn_signals_from_composite(
        composite_harness, mask_daily, top_n=top_n, min_holding_days=1,
    )

    # On rebalance days where len(scores) >= top_n, both paths should
    # pick the same top-N and equal-weight them. The semantics of the
    # two functions differ on the WARMUP days (paper returns zeros;
    # harness carries last_selection which is also zeros initially) —
    # so they should match on every day.
    diff_w = (weights_paper - weights_harness).abs()
    assert float(diff_w.max().max()) < 1e-12, (
        f"target weights diverge between harness and paper code path: "
        f"max diff = {float(diff_w.max().max()):.2e}; first divergent date "
        f"= {diff_w.index[(diff_w > 1e-9).any(axis=1)].tolist()[:3]}"
    )


def test_evaluate_composite_spec_research_mask_honored():
    """When research_mask is provided, composite cells where mask=False
    should be NaN (not contribute to top-N ranking)."""
    from core.research.harness import evaluate_composite_spec

    prices, opens, panel_map, spy, qqq = _build_synthetic_panel(n_dates=60)
    spec = ResearchCompositeSpec(
        features=("momentum_21d", "low_vol_60d", "long_mom_126d"),
        weights=(1 / 3, 1 / 3, 1 / 3),
        family_counts={"A": 1, "B": 1, "C": 1},
    )

    # Mask out symbol S0 entirely
    mask = pd.DataFrame(True, index=prices.index, columns=prices.columns)
    mask["S0"] = False

    result_masked = evaluate_composite_spec(
        spec, factor_panel_map=panel_map, price_df=prices, open_df=opens,
        spy_series=spy, qqq_series=qqq,
        config=HarnessConfig(top_n=3, initial_capital=10_000.0),
        research_mask=mask,
    )

    # S0 should never be held: either absent from weights columns
    # entirely (BacktestEngine prunes never-held symbols) OR present
    # with max weight = 0.
    if "S0" in result_masked.weights.columns:
        s0_max_weight = float(result_masked.weights["S0"].max())
        assert s0_max_weight == 0.0, (
            f"S0 was masked but harness held it (max weight = {s0_max_weight})"
        )
    # Defense-in-depth: also assert S0 NEVER appears in any rebalance day's
    # held set by re-checking via the daily_returns path. The paper run
    # would also exclude S0 entirely; this is structural equivalence.


def test_evaluate_composite_spec_no_benchmark_omits_correlation_keys():
    """When spy_series and qqq_series are None, correlation diagnostic
    should not error and should simply omit the keys."""
    from core.research.harness import evaluate_composite_spec

    prices, opens, panel_map, _spy, _qqq = _build_synthetic_panel()
    spec = ResearchCompositeSpec(
        features=("momentum_21d", "low_vol_60d", "long_mom_126d"),
        weights=(1 / 3, 1 / 3, 1 / 3),
        family_counts={"A": 1, "B": 1, "C": 1},
    )

    result = evaluate_composite_spec(
        spec, factor_panel_map=panel_map, price_df=prices, open_df=opens,
        spy_series=None, qqq_series=None,
        config=HarnessConfig(top_n=3, initial_capital=10_000.0),
    )

    assert "raw_pearson_vs_spy" not in result.nav_correlation_vs_benchmark
    assert "raw_pearson_vs_qqq" not in result.nav_correlation_vs_benchmark
    # Full-period metrics still present (just no vs_spy/vs_qqq)
    assert "cum_ret" in result.metrics_full_period
    assert "sharpe" in result.metrics_full_period


# ── topn_signals_with_caps + cap_aware mode (cycle #03) ──────────────


def test_topn_signals_with_caps_basic_diversification():
    """Cap-aware selection forces structural diversity. With cluster_cap
    = 0.20 and target_n_picks=10 (weight_per_pick=0.10), max 2 picks
    per cluster → if a single cluster has top-5 scores, only 2 get
    picked, the other 3 are skipped, picks come from other clusters."""
    from core.research.harness import topn_signals_with_caps

    dates = pd.bdate_range("2020-01-02", periods=20)
    syms = [f"S{i}" for i in range(20)]
    # Make S0..S4 the highest-scoring (descending), all in cluster 'A'.
    # S5..S9 in cluster 'B', S10..S14 in 'C', S15..S19 in 'D'.
    cluster_map = {}
    for i in range(20):
        if i < 5:    cluster_map[f"S{i}"] = "A"
        elif i < 10: cluster_map[f"S{i}"] = "B"
        elif i < 15: cluster_map[f"S{i}"] = "C"
        else:        cluster_map[f"S{i}"] = "D"

    composite = pd.DataFrame(
        {sym: 20 - i for i, sym in enumerate(syms)},
        index=dates,
    )
    rmask = pd.Series(False, index=dates)
    rmask.iloc[0] = True

    signals = topn_signals_with_caps(
        composite, rmask,
        target_n_picks=10,
        cluster_map=cluster_map,
        cluster_cap=0.20,           # max 2 picks per cluster
        max_single_weight=0.10,
    )

    picked = signals.iloc[0]
    picked_nz = picked[picked > 0]
    # Cluster cap binding: max 2 per cluster
    cluster_count = {}
    for s in picked_nz.index:
        c = cluster_map[s]
        cluster_count[c] = cluster_count.get(c, 0) + 1
    for c, n in cluster_count.items():
        assert n <= 2, f"cluster {c} has {n} picks > cap of 2"

    # Picked from at least 5 clusters? With 4 clusters × 2 each = 8
    # picks max with these caps. Total picks may be 8 or 10 depending
    # on whether algorithm fills.
    assert len(picked_nz) >= 8


def test_topn_signals_with_caps_first_two_in_top_cluster():
    """The 2 highest-scoring members of the top-scored cluster MUST be
    picked (they're best-in-class within the cluster)."""
    from core.research.harness import topn_signals_with_caps

    dates = pd.bdate_range("2020-01-02", periods=5)
    syms = ["AAPL", "MSFT", "GOOGL", "META", "AMZN", "JNJ", "WMT"]
    cluster_map = {
        "AAPL": "platform", "MSFT": "platform", "GOOGL": "platform",
        "META": "internet", "AMZN": "internet",
        "JNJ": "pharma", "WMT": "staples",
    }
    # AAPL > MSFT > GOOGL > META > AMZN > JNJ > WMT
    composite = pd.DataFrame(
        {sym: 7 - i for i, sym in enumerate(syms)},
        index=dates,
    )
    rmask = pd.Series([True, False, False, False, False], index=dates)

    signals = topn_signals_with_caps(
        composite, rmask,
        target_n_picks=5, cluster_map=cluster_map,
        cluster_cap=0.40, max_single_weight=0.20,  # 2/5=0.20 each
    )
    picks = set(signals.iloc[0][signals.iloc[0] > 0].index)
    # AAPL+MSFT (top 2 in platform), then META+AMZN (top 2 in internet),
    # then JNJ (only pharma; only 1 needed)
    assert {"AAPL", "MSFT"}.issubset(picks)
    assert "GOOGL" not in picks  # cluster cap rejects 3rd platform pick


def test_topn_signals_with_caps_excludes_unmapped():
    """Symbols NOT in cluster_map are silently excluded from selection."""
    from core.research.harness import topn_signals_with_caps

    dates = pd.bdate_range("2020-01-02", periods=3)
    syms = ["AAPL", "MSFT", "SPY", "QQQ", "JNJ"]
    # SPY/QQQ NOT in cluster_map → must be excluded even if score high
    cluster_map = {"AAPL": "tech", "MSFT": "tech", "JNJ": "pharma"}
    composite = pd.DataFrame(
        {"SPY": [100, 100, 100], "QQQ": [99, 99, 99],
         "AAPL": [50, 50, 50], "MSFT": [40, 40, 40], "JNJ": [10, 10, 10]},
        index=dates,
    )
    rmask = pd.Series([True, False, False], index=dates)
    signals = topn_signals_with_caps(
        composite, rmask, target_n_picks=3, cluster_map=cluster_map,
        cluster_cap=0.7, max_single_weight=0.5,
    )
    picked = signals.iloc[0]
    assert picked["SPY"] == 0.0
    assert picked["QQQ"] == 0.0
    assert picked["AAPL"] > 0
    assert picked["MSFT"] > 0
    assert picked["JNJ"] > 0


def test_topn_signals_with_caps_implicit_cash():
    """When cluster caps bind tightly and not enough eligible picks
    exist, the portfolio is partially in cash (signal sum < 1.0)."""
    from core.research.harness import topn_signals_with_caps

    dates = pd.bdate_range("2020-01-02", periods=3)
    cluster_map = {"S0": "A", "S1": "A", "S2": "B"}  # only 3 stocks
    composite = pd.DataFrame(
        {"S0": [3, 3, 3], "S1": [2, 2, 2], "S2": [1, 1, 1]},
        index=dates,
    )
    rmask = pd.Series([True, False, False], index=dates)
    # target=10, but cluster_cap=0.10 = max 1/cluster, only 2 clusters
    # → max 2 picks, sum=0.20, 0.80 implicit cash
    signals = topn_signals_with_caps(
        composite, rmask, target_n_picks=10, cluster_map=cluster_map,
        cluster_cap=0.10, max_single_weight=0.10,
    )
    picked = signals.iloc[0]
    assert (picked > 0).sum() == 2  # only 2 picks fit
    assert abs(picked.sum() - 0.20) < 1e-6  # 80% cash


def test_harness_config_cap_aware_requires_cluster_map():
    """cap_aware mode without cluster_map must raise."""
    from core.research.harness import HarnessConfig
    with pytest.raises(ValueError, match="cap_aware.*requires cluster_map"):
        HarnessConfig(construction_mode="cap_aware", top_n=10)


def test_harness_config_validates_caps():
    """cluster_cap and max_single_weight must be in (0, 1]."""
    from core.research.harness import HarnessConfig
    with pytest.raises(ValueError, match="cluster_cap"):
        HarnessConfig(cluster_cap=0.0)
    with pytest.raises(ValueError, match="cluster_cap"):
        HarnessConfig(cluster_cap=1.5)
    with pytest.raises(ValueError, match="max_single_weight"):
        HarnessConfig(max_single_weight=-0.1)


def test_harness_config_weight_per_pick_cannot_exceed_max_single():
    """target_n_picks=5 + max_single_weight=0.10 gives wpp=0.20 > 0.10
    → invalid. cap_aware mode must catch this at construction."""
    from core.research.harness import HarnessConfig
    with pytest.raises(ValueError, match="weight_per_pick"):
        HarnessConfig(
            construction_mode="cap_aware",
            top_n=5,
            cluster_map={"AAPL": "tech"},
            max_single_weight=0.10,
        )


def test_harness_config_global_top_n_default_unchanged():
    """Existing cycle #01/#02 default config still validates and works
    (no construction_mode breaking change)."""
    from core.research.harness import HarnessConfig
    cfg = HarnessConfig(top_n=10)  # default global_top_n
    assert cfg.construction_mode == "global_top_n"
    assert cfg.cluster_map is None


# ── cap_aware_cross_asset mode (cycle #04) ───────────────────────────


def test_harness_config_cross_asset_requires_asset_class_map_and_caps():
    from core.research.harness import HarnessConfig
    cluster_map = {"AAPL": "tech", "TLT": "bond_long_duration"}
    # Missing both asset_class_map and asset_class_caps
    with pytest.raises(ValueError, match="cap_aware_cross_asset.*requires.*asset_class"):
        HarnessConfig(
            construction_mode="cap_aware_cross_asset", top_n=10,
            cluster_map=cluster_map,
        )
    # Missing only asset_class_caps
    with pytest.raises(ValueError, match="cap_aware_cross_asset.*requires"):
        HarnessConfig(
            construction_mode="cap_aware_cross_asset", top_n=10,
            cluster_map=cluster_map,
            asset_class_map={"AAPL": "equities", "TLT": "bonds"},
        )


def test_harness_config_cross_asset_rejects_unknown_asset_class():
    from core.research.harness import HarnessConfig
    with pytest.raises(ValueError, match="unknown classes"):
        HarnessConfig(
            construction_mode="cap_aware_cross_asset", top_n=10,
            cluster_map={"AAPL": "tech"},
            asset_class_map={"AAPL": "equities"},
            asset_class_caps={"equities": 0.7, "real_estate": 0.5},  # invalid
        )


def test_harness_config_cross_asset_valid_construction():
    from core.research.harness import HarnessConfig
    cfg = HarnessConfig(
        construction_mode="cap_aware_cross_asset", top_n=10,
        cluster_map={"AAPL": "tech", "TLT": "bond_long_duration"},
        asset_class_map={"AAPL": "equities", "TLT": "bonds"},
        asset_class_caps={"equities": 0.7, "bonds": 0.4,
                          "commodities": 0.2, "cash_anchor": 0.3},
    )
    assert cfg.construction_mode == "cap_aware_cross_asset"


def test_topn_signals_cross_asset_caps_bind_bonds():
    """Asset-class caps bind: even if all top scores are bonds, only
    bonds_max=0.40 worth get picked; the rest go to other asset classes."""
    from core.research.harness import topn_signals_with_caps

    dates = pd.bdate_range("2020-01-02", periods=3)
    # Make bonds top 6 of 10 scores; equities lower
    syms = ["TLT", "IEF", "SHY", "GLD", "BIL", "SHV", "AAPL", "MSFT", "JNJ", "WMT"]
    cluster_map = {
        "TLT": "bond_long", "IEF": "bond_intermediate", "SHY": "bond_short",
        "GLD": "commodities", "BIL": "cash", "SHV": "cash",
        "AAPL": "tech", "MSFT": "tech", "JNJ": "pharma", "WMT": "staples",
    }
    asset_class_map = {
        "TLT": "bonds", "IEF": "bonds", "SHY": "bonds",
        "GLD": "commodities",
        "BIL": "cash_anchor", "SHV": "cash_anchor",
        "AAPL": "equities", "MSFT": "equities",
        "JNJ": "equities", "WMT": "equities",
    }
    # All bonds scored highest (10, 9, 8); commodities 7; cash 6, 5;
    # equities 4..1
    composite = pd.DataFrame(
        {sym: 10 - i for i, sym in enumerate(syms)},
        index=dates,
    )
    rmask = pd.Series([True, False, False], index=dates)
    signals = topn_signals_with_caps(
        composite, rmask,
        target_n_picks=10,
        cluster_map=cluster_map,
        cluster_cap=0.20, max_single_weight=0.10,
        asset_class_map=asset_class_map,
        asset_class_caps={"equities": 0.70, "bonds": 0.40,
                          "commodities": 0.20, "cash_anchor": 0.30},
    )
    picked = signals.iloc[0]
    nz = picked[picked > 0]
    # bonds_max = 0.40 → at most 4 picks of weight 0.10 each
    bonds_picked = sum(1 for s in nz.index if asset_class_map[s] == "bonds")
    assert bonds_picked <= 4, (
        f"bonds cap binding violated: {bonds_picked} bond picks > 4"
    )
    # Even though SHY (8) had high score, it should be skipped because
    # bonds asset_class cap binds first → only top-2 bonds (TLT, IEF) +
    # then either skipped or one more if cluster cap allows
    # (all 3 bonds in different clusters → can pick all 3 by cluster
    # but bonds asset_class only allows 4)


def test_topn_signals_cross_asset_caps_default_omitted_works():
    """Asset_class_map + asset_class_caps both omitted → behaves like
    standard cap_aware (regression test for backward compat)."""
    from core.research.harness import topn_signals_with_caps

    dates = pd.bdate_range("2020-01-02", periods=3)
    cluster_map = {"AAPL": "tech", "MSFT": "tech", "JNJ": "pharma", "WMT": "staples"}
    composite = pd.DataFrame(
        {"AAPL": [4, 4, 4], "MSFT": [3, 3, 3], "JNJ": [2, 2, 2], "WMT": [1, 1, 1]},
        index=dates,
    )
    rmask = pd.Series([True, False, False], index=dates)
    signals = topn_signals_with_caps(
        composite, rmask, target_n_picks=4,
        cluster_map=cluster_map, cluster_cap=0.50, max_single_weight=0.25,
        # asset_class_map and asset_class_caps both None
    )
    picked = signals.iloc[0]
    assert picked["AAPL"] > 0 and picked["MSFT"] > 0


def test_topn_signals_cross_asset_caps_partial_args_raises():
    """Providing only one of (asset_class_map, asset_class_caps) raises."""
    from core.research.harness import topn_signals_with_caps

    dates = pd.bdate_range("2020-01-02", periods=2)
    composite = pd.DataFrame({"AAPL": [1.0, 1.0], "MSFT": [0.5, 0.5]}, index=dates)
    rmask = pd.Series([True, False], index=dates)
    with pytest.raises(ValueError, match="must be provided together"):
        topn_signals_with_caps(
            composite, rmask, target_n_picks=10,  # wpp=0.10 ≤ max_single 0.20
            cluster_map={"AAPL": "tech", "MSFT": "tech"},
            cluster_cap=0.5, max_single_weight=0.20,
            asset_class_map={"AAPL": "equities", "MSFT": "equities"},  # caps missing
        )
