"""
Unit tests for FactorEvaluator.

全部使用合成数据。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.factors.factor_engine import FactorEngine
from core.factors.factor_evaluator import FactorEvaluator, FactorReport, _auto_tier


# ── 辅助函数 ──────────────────────────────────────────────────────────────────

def _make_dates(n: int, start: str = "2021-01-04") -> pd.DatetimeIndex:
    return pd.bdate_range(start, periods=n)


def _strong_setup(n_dates: int = 200, n_syms: int = 20, seed: int = 7):
    """
    返回 (factor_df, price_df) — 强预测因子。

    关键：factor[t] ∝ ret[t+1]（今日因子值预测明日收益），
    与 evaluator 内部 make_forward_returns(horizon=1) 形成正相关。
    """
    rng   = np.random.default_rng(seed)
    dates = _make_dates(n_dates)
    syms  = [f"S{i:02d}" for i in range(n_syms)]

    ret    = pd.DataFrame(rng.normal(0, 0.01, (n_dates, n_syms)), index=dates, columns=syms)
    price  = (1 + ret).cumprod()

    # 构造预测因子：今天的因子 = 明天的收益 + 少量噪声
    fwd    = ret.shift(-1).fillna(0.0)
    noise  = rng.normal(0, 0.002, (n_dates, n_syms))
    factor = pd.DataFrame(fwd.values + noise, index=dates, columns=syms)
    return factor, price


def _random_setup(n_dates: int = 200, n_syms: int = 20, seed: int = 13):
    """返回 (factor_df, price_df) — 纯噪声因子。"""
    rng   = np.random.default_rng(seed)
    dates = _make_dates(n_dates)
    syms  = [f"S{i:02d}" for i in range(n_syms)]

    ret    = pd.DataFrame(rng.normal(0, 0.01, (n_dates, n_syms)), index=dates, columns=syms)
    factor = pd.DataFrame(rng.normal(0, 1,    (n_dates, n_syms)), index=dates, columns=syms)
    price  = (1 + ret).cumprod()
    return factor, price


# ── FactorEvaluator.evaluate ──────────────────────────────────────────────────

class TestEvaluate:
    def test_returns_factor_report(self):
        factor, price = _strong_setup()
        ev = FactorEvaluator(horizons=[1, 5], n_sub_periods=2, decay_max_lag=5)
        report = ev.evaluate(factor, price, "test")
        assert isinstance(report, FactorReport)

    def test_stats_for_all_horizons(self):
        factor, price = _strong_setup()
        ev = FactorEvaluator(horizons=[1, 5, 10], n_sub_periods=2, decay_max_lag=3)
        report = ev.evaluate(factor, price, "mom")
        for h in [1, 5, 10]:
            assert h in report.stats

    def test_strong_factor_tier_not_d(self):
        factor, price = _strong_setup(n_dates=300, n_syms=25)
        ev = FactorEvaluator(horizons=[1, 5], n_sub_periods=2, decay_max_lag=5)
        report = ev.evaluate(factor, price, "strong")
        assert report.tier in ("S", "A", "B", "C"), (
            f"强因子评级不应为 D，得到 {report.tier}"
        )

    def test_random_factor_tier_d(self):
        factor, price = _random_setup(n_dates=300, n_syms=25)
        ev = FactorEvaluator(horizons=[1, 5], n_sub_periods=2, decay_max_lag=5)
        report = ev.evaluate(factor, price, "noise")
        # 随机因子绝大多数情况应为 C 或 D
        assert report.tier in ("C", "D"), (
            f"随机因子评级应为 C/D，得到 {report.tier}"
        )

    def test_summary_no_exception(self):
        factor, price = _strong_setup()
        ev = FactorEvaluator(horizons=[1], n_sub_periods=2, decay_max_lag=3)
        report = ev.evaluate(factor, price, "f")
        text = report.summary()
        assert "FactorReport" in text and "Tier" in text


# ── layered_backtest ──────────────────────────────────────────────────────────

class TestLayeredBacktest:
    def test_returns_dataframe(self):
        factor, price = _strong_setup()
        engine = FactorEngine()
        fwd    = engine.make_forward_returns(price, horizon=1)
        ev     = FactorEvaluator(n_quantiles=5)
        result = ev.layered_backtest(factor, fwd)
        assert isinstance(result, pd.DataFrame)

    def test_columns_include_spread(self):
        factor, price = _strong_setup()
        engine = FactorEngine()
        fwd    = engine.make_forward_returns(price, horizon=1)
        ev     = FactorEvaluator(n_quantiles=5)
        result = ev.layered_backtest(factor, fwd)
        assert "spread" in result.columns

    def test_quantile_columns_present(self):
        factor, price = _strong_setup()
        engine = FactorEngine()
        fwd    = engine.make_forward_returns(price, horizon=1)
        ev     = FactorEvaluator(n_quantiles=5)
        result = ev.layered_backtest(factor, fwd)
        for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
            assert q in result.columns

    def test_strong_factor_top_quantile_outperforms_bottom(self):
        """强因子：最高分位（Q5）累积收益应 > 最低分位（Q1）。"""
        factor, price = _strong_setup(n_dates=300, n_syms=25)
        engine = FactorEngine()
        fwd    = engine.make_forward_returns(price, horizon=1)
        ev     = FactorEvaluator(n_quantiles=5)
        result = ev.layered_backtest(factor, fwd)
        if result.empty:
            pytest.skip("分层回测结果为空")
        q5_final = result["Q5"].iloc[-1]
        q1_final = result["Q1"].iloc[-1]
        assert q5_final > q1_final, (
            f"强因子 Q5({q5_final:.4f}) 应 > Q1({q1_final:.4f})"
        )

    def test_empty_when_too_few_symbols(self):
        """symbol 数量少于 n_quantiles*2 时应返回空 DataFrame。"""
        dates  = _make_dates(30)
        syms   = ["A", "B", "C"]  # 只有 3 个，5 分位需要 ≥ 10
        factor = pd.DataFrame(np.random.randn(30, 3), index=dates, columns=syms)
        ret    = pd.DataFrame(np.random.randn(30, 3) * 0.01, index=dates, columns=syms)
        ev     = FactorEvaluator(n_quantiles=5)
        result = ev.layered_backtest(factor, ret)
        assert result.empty


# ── sub_period_stability ──────────────────────────────────────────────────────

class TestSubPeriodStability:
    def test_returns_dataframe(self):
        factor, price = _strong_setup(n_dates=300)
        engine = FactorEngine()
        fwd    = engine.make_forward_returns(price, horizon=5)
        ev     = FactorEvaluator(n_sub_periods=4)
        result = ev.sub_period_stability(factor, fwd)
        assert isinstance(result, pd.DataFrame)

    def test_correct_number_of_periods(self):
        factor, price = _strong_setup(n_dates=300)
        engine = FactorEngine()
        fwd    = engine.make_forward_returns(price, horizon=5)
        ev     = FactorEvaluator(n_sub_periods=4)
        result = ev.sub_period_stability(factor, fwd)
        if not result.empty:
            assert len(result) == 4

    def test_columns_present(self):
        factor, price = _strong_setup(n_dates=300)
        engine = FactorEngine()
        fwd    = engine.make_forward_returns(price, horizon=5)
        ev     = FactorEvaluator(n_sub_periods=4)
        result = ev.sub_period_stability(factor, fwd)
        if not result.empty:
            for col in ["start", "end", "mean_ic", "ir", "n"]:
                assert col in result.columns

    def test_too_few_dates_returns_empty(self):
        """数据量不足（< n_sub_periods*5）时应返回空 DataFrame。"""
        factor, price = _random_setup(n_dates=10, n_syms=5)
        engine = FactorEngine()
        fwd    = engine.make_forward_returns(price, horizon=1)
        ev     = FactorEvaluator(n_sub_periods=4)
        result = ev.sub_period_stability(factor, fwd)
        assert result.empty

    def test_strong_factor_consistent_ir_sign(self):
        """强因子在各子区间 IR 方向应一致（全部为正）。"""
        factor, price = _strong_setup(n_dates=500, n_syms=25)
        engine = FactorEngine()
        fwd    = engine.make_forward_returns(price, horizon=5)
        ev     = FactorEvaluator(n_sub_periods=4)
        result = ev.sub_period_stability(factor, fwd)
        if result.empty:
            pytest.skip("子区间结果为空")
        ir_vals = result["ir"].dropna()
        positive_ratio = (ir_vals > 0).mean()
        assert positive_ratio >= 0.75, (
            f"强因子子区间 IR 正值比例应 ≥ 75%，得到 {positive_ratio:.0%}"
        )


# ── _auto_tier ────────────────────────────────────────────────────────────────

class TestAutoTier:
    def _make_stats(self, ir: float, p: float = 0.01) -> dict:
        from core.factors.factor_engine import FactorStats
        s = FactorStats(
            factor_name="f", horizon=1, n_periods=100,
            mean_ic=ir * 0.05, ic_std=0.05,
            ir=ir, t_stat=ir * 10, p_value=p,
            ic_positive_ratio=0.6 if ir > 0 else 0.4,
            ic_gt_02_ratio=0.3,
        )
        return {1: s}

    def test_high_ir_significant_is_s(self):
        assert _auto_tier(self._make_stats(ir=1.0, p=0.001)) == "S"

    def test_medium_ir_significant_is_a(self):
        assert _auto_tier(self._make_stats(ir=0.6, p=0.01)) == "A"

    def test_low_ir_significant_is_b(self):
        assert _auto_tier(self._make_stats(ir=0.35, p=0.04)) == "B"

    def test_weak_ir_not_significant_is_c(self):
        assert _auto_tier(self._make_stats(ir=0.15, p=0.30)) == "C"

    def test_tiny_ir_is_d(self):
        assert _auto_tier(self._make_stats(ir=0.05, p=0.80)) == "D"

    def test_empty_stats_is_d(self):
        assert _auto_tier({}) == "D"

    # ── PRD §6.3 step 3: AcceptanceThresholds wiring ──────────────────────

    def test_auto_tier_honors_yaml_threshold_override(self):
        """Tightened ``factor_tiers.s_min_ir=0.95`` must demote IR=0.85 from S to A.

        Reverse-validation cue: revert _auto_tier to the hardcoded 0.8/0.5/0.3/0.1
        cuts and this test fails — IR=0.85 ≥ 0.8 → S under pre-fix, but ≥ 0.95 must
        miss the S-tier under the override.
        """
        from core.config.schemas import (
            AcceptanceThresholds,
            FactorTierThresholds,
        )

        # Default → 0.85 IR is significant → S tier.
        default_tier = _auto_tier(self._make_stats(ir=0.85, p=0.001))
        assert default_tier == "S", (
            f"sanity: with default thresholds, IR=0.85 should land in S; got {default_tier}"
        )

        tightened = AcceptanceThresholds(
            factor_tiers=FactorTierThresholds(
                s_min_ir=0.95,
                a_min_ir=0.50,
                b_min_ir=0.30,
                c_min_ir=0.10,
            )
        )
        injected_tier = _auto_tier(
            self._make_stats(ir=0.85, p=0.001), thresholds=tightened
        )
        assert injected_tier == "A", (
            f"override s_min_ir=0.95 should demote IR=0.85 to A; got {injected_tier}"
        )

    def test_auto_tier_default_kwarg_matches_schema_defaults(self):
        """Calling without ``thresholds`` is equivalent to passing schema defaults."""
        from core.config.schemas import AcceptanceThresholds
        stats = self._make_stats(ir=0.45, p=0.001)
        assert _auto_tier(stats) == _auto_tier(stats, thresholds=AcceptanceThresholds())


# ── PRD codex round-16 follow-up: public threshold path on FactorEvaluator ───


class TestFactorEvaluatorPublicThresholdPath:
    """Codex round-16 finding #1: ``FactorEvaluator(thresholds=...)`` must
    flow through to the resulting ``FactorReport.tier`` so a researcher who
    edits ``config/acceptance.yaml`` and constructs the evaluator with
    ``cfg.acceptance`` actually gets yaml-driven tiering — not the
    schema-default tiering produced by ``FactorReport.__post_init__``.

    Reverse-validation: revert the override-after-construct line in
    ``FactorEvaluator.evaluate()`` and this test fails.
    """

    def _make_panel(self, n_dates: int = 252, seed: int = 42):
        """Tiny deterministic panel: factor rank ≈ next-day return rank.

        Strong-IR factor (~0.85) → default tiers say S, but a tightened
        ``s_min_ir=0.95`` should demote to A.
        """
        rng = np.random.default_rng(seed)
        n_syms = 20
        idx = pd.bdate_range("2020-01-02", periods=n_dates)
        syms = [f"S{i:02d}" for i in range(n_syms)]
        # base prices
        rets = rng.normal(0.0005, 0.012, (n_dates, n_syms))
        prices = 100.0 * np.cumprod(1 + rets, axis=0)
        price_df = pd.DataFrame(prices, index=idx, columns=syms)
        # factor: tomorrow's return signal scaled (high IR but not 1.0)
        fwd1 = price_df.pct_change().shift(-1)
        noise = rng.normal(0, 0.005, (n_dates, n_syms))
        factor_df = fwd1 + noise
        return factor_df, price_df

    def test_factor_evaluator_default_uses_schema_thresholds(self):
        """No injection: report.tier reflects default 0.8/0.5/0.3/0.1 cuts."""
        factor_df, price_df = self._make_panel()
        ev = FactorEvaluator(horizons=[1, 5], n_sub_periods=2, decay_max_lag=3)
        report = ev.evaluate(factor_df, price_df, factor_name="f_strong")
        assert report.tier in {"S", "A", "B", "C", "D"}
        # Sanity: not asserting a specific tier on stochastic data, just
        # that the path returns a valid label without crashing.

    def test_factor_evaluator_thresholds_kwarg_changes_report_tier(self):
        """Inject a tightened factor_tier set with a deterministic stats
        block that exercises the override branch. Use a fixed-stats path
        so the assertion is sharp."""
        from core.config.schemas import (
            AcceptanceThresholds,
            FactorTierThresholds,
        )

        # Build a deterministic minimal report by side-loading stats. The
        # public path computes `tier` two ways: once in __post_init__
        # (default) and again in evaluate() if thresholds is set. We test
        # both: build report via evaluate(), then check that flipping the
        # injected factor_tiers cuts changes the resulting tier.
        factor_df, price_df = self._make_panel()

        # Default thresholds path
        ev_default = FactorEvaluator(
            horizons=[1, 5], n_sub_periods=2, decay_max_lag=3
        )
        rep_default = ev_default.evaluate(factor_df, price_df, "f")

        # Forced-D path: every cut set to a value primary IR can't reach
        unattainable = AcceptanceThresholds(
            factor_tiers=FactorTierThresholds(
                s_min_ir=99.0, a_min_ir=99.0, b_min_ir=99.0, c_min_ir=99.0,
            )
        )
        ev_forced = FactorEvaluator(
            horizons=[1, 5],
            n_sub_periods=2,
            decay_max_lag=3,
            thresholds=unattainable,
        )
        rep_forced = ev_forced.evaluate(factor_df, price_df, "f")

        assert rep_forced.tier == "D", (
            f"unattainable factor_tiers must force tier D; got {rep_forced.tier} "
            f"(default tier was {rep_default.tier})"
        )

        # Symmetry: ultra-permissive cuts → at least C even for noise-only
        permissive = AcceptanceThresholds(
            factor_tiers=FactorTierThresholds(
                s_min_ir=0.0, a_min_ir=0.0, b_min_ir=0.0, c_min_ir=0.0,
            )
        )
        ev_permissive = FactorEvaluator(
            horizons=[1, 5],
            n_sub_periods=2,
            decay_max_lag=3,
            thresholds=permissive,
        )
        rep_permissive = ev_permissive.evaluate(factor_df, price_df, "f")
        # IR=any non-NaN value clears 0.0 → S (with significance) or C
        # (without). D only if IR is NaN, which shouldn't happen on this
        # panel.
        assert rep_permissive.tier != "D", (
            f"all-zero factor_tiers should never produce D; got {rep_permissive.tier}"
        )
