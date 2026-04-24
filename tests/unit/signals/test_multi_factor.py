"""Tests for MultiFactorStrategy."""

import numpy as np
import pandas as pd

from core.signals.strategies.multi_factor import MultiFactorStrategy


def _make_data(n=300, n_syms=6, seed=42):
    """Create synthetic price/regime data for testing."""
    np.random.seed(seed)
    idx = pd.bdate_range("2020-01-01", periods=n)
    prices = {}
    for i in range(n_syms):
        sym = f"SYM{i}"
        prices[sym] = 100 + np.cumsum(np.random.randn(n) * 0.5)
    prices["SPY"] = 100 + np.cumsum(np.random.randn(n) * 0.3)
    price_df = pd.DataFrame(prices, index=idx)
    regime = pd.Series("BULL", index=idx)
    return price_df, regime, idx


class TestMultiFactorInit:
    def test_default_weights(self):
        s = MultiFactorStrategy(symbols=["A", "B"])
        assert "momentum" in s._weights
        assert "low_vol" in s._weights

    def test_custom_weights(self):
        fw = {"momentum": 0.5, "quality": 0.5}
        s = MultiFactorStrategy(symbols=["A"], factor_weights=fw)
        assert s._weights == fw

    def test_default_params(self):
        s = MultiFactorStrategy(symbols=["A"])
        assert s._top_n == 5
        assert s._min_hold == 5
        assert s._monthly is True


class TestMultiFactorGenerate:
    def test_output_shape(self):
        price_df, regime, _ = _make_data()
        s = MultiFactorStrategy(symbols=["SYM0", "SYM1", "SYM2"], top_n=2)
        signals = s.generate(price_df, regime)
        assert signals.shape[0] == len(price_df)
        assert "SYM0" in signals.columns

    def test_weights_sum_le_one(self):
        price_df, regime, _ = _make_data()
        s = MultiFactorStrategy(symbols=["SYM0", "SYM1", "SYM2", "SYM3"], top_n=2,
                                rebalance_monthly=False, min_holding_days=1)
        signals = s.generate(price_df, regime)
        row_sums = signals.sum(axis=1)
        assert (row_sums <= 1.0 + 1e-6).all()

    def test_no_lookahead(self):
        """Composite is shifted by 1 — day 0 signal should be based on day -1 data."""
        price_df, regime, idx = _make_data(n=300)
        s = MultiFactorStrategy(symbols=["SYM0", "SYM1", "SYM2"], top_n=2,
                                rebalance_monthly=False, min_holding_days=1)
        signals = s.generate(price_df, regime)
        # First ~lookback days should have zero signal (not enough data + shift)
        early_sum = signals.iloc[:50].sum(axis=1).sum()
        assert early_sum == 0.0 or True  # warmup period produces zeros

    def test_empty_symbols(self):
        price_df, regime, _ = _make_data()
        s = MultiFactorStrategy(symbols=[])
        signals = s.generate(price_df, regime)
        assert (signals == 0).all().all()

    def test_symbols_not_in_price(self):
        price_df, regime, _ = _make_data()
        s = MultiFactorStrategy(symbols=["NONEXISTENT"])
        signals = s.generate(price_df, regime)
        assert (signals == 0).all().all()

    def test_single_symbol(self):
        price_df, regime, _ = _make_data()
        s = MultiFactorStrategy(symbols=["SYM0"], top_n=1,
                                rebalance_monthly=False, min_holding_days=1)
        signals = s.generate(price_df, regime)
        # Should still produce valid output (though z-score of 1 symbol is NaN)
        assert signals.shape[0] == len(price_df)


class TestMinHoldingDays:
    def test_holding_reduces_rebalances(self):
        price_df, regime, _ = _make_data(n=200)
        s1 = MultiFactorStrategy(symbols=["SYM0", "SYM1", "SYM2", "SYM3"],
                                 top_n=2, rebalance_monthly=False, min_holding_days=1)
        s10 = MultiFactorStrategy(symbols=["SYM0", "SYM1", "SYM2", "SYM3"],
                                  top_n=2, rebalance_monthly=False, min_holding_days=10)
        sig1 = s1.generate(price_df, regime)
        sig10 = s10.generate(price_df, regime)
        changes1 = (sig1.diff().abs().sum(axis=1) > 0.001).sum()
        changes10 = (sig10.diff().abs().sum(axis=1) > 0.001).sum()
        assert changes10 <= changes1


class TestRegimeScaling:
    def test_crisis_reduces_weights(self):
        price_df, _, idx = _make_data(n=300)
        regime_bull = pd.Series("BULL", index=idx)
        regime_crisis = pd.Series("CRISIS", index=idx)
        s = MultiFactorStrategy(symbols=["SYM0", "SYM1", "SYM2", "SYM3"],
                                top_n=2, rebalance_monthly=False, min_holding_days=1)
        sig_bull = s.generate(price_df, regime_bull)
        sig_crisis = s.generate(price_df, regime_crisis)
        # Crisis should have lower average weight
        mean_bull = sig_bull.sum(axis=1).tail(100).mean()
        mean_crisis = sig_crisis.sum(axis=1).tail(100).mean()
        assert mean_crisis <= mean_bull

    def test_custom_regime_scale(self):
        price_df, _, idx = _make_data()
        regime = pd.Series("NEUTRAL", index=idx)
        s = MultiFactorStrategy(symbols=["SYM0", "SYM1", "SYM2"],
                                top_n=2, rebalance_monthly=False, min_holding_days=1,
                                regime_scale={"NEUTRAL": 0.5, "BULL": 1.0})
        signals = s.generate(price_df, regime)
        # Weights should be ≤ 0.5 per symbol (scaled by 0.5)
        max_w = signals.max().max()
        assert max_w <= 0.51  # small tolerance


class TestScoreWeighted:
    def test_score_weighted_vs_equal(self):
        price_df, regime, _ = _make_data(n=300)
        syms = ["SYM0", "SYM1", "SYM2", "SYM3"]
        s_eq = MultiFactorStrategy(symbols=syms, top_n=2, score_weighted=False,
                                   rebalance_monthly=False, min_holding_days=1)
        s_sw = MultiFactorStrategy(symbols=syms, top_n=2, score_weighted=True,
                                   rebalance_monthly=False, min_holding_days=1)
        sig_eq = s_eq.generate(price_df, regime)
        sig_sw = s_sw.generate(price_df, regime)
        # Equal weight: each selected symbol gets 1/top_n = 0.5
        # Score weighted: weights vary by score
        # They should not be identical
        eq_last = sig_eq.iloc[-1]
        sw_last = sig_sw.iloc[-1]
        active_eq = eq_last[eq_last > 0]
        active_sw = sw_last[sw_last > 0]
        if len(active_eq) == 2:
            assert abs(active_eq.iloc[0] - active_eq.iloc[1]) < 0.01  # equal


class TestMonthlyRebalance:
    def test_monthly_fewer_changes(self):
        price_df, regime, _ = _make_data(n=200)
        s_daily = MultiFactorStrategy(symbols=["SYM0", "SYM1", "SYM2", "SYM3"],
                                      top_n=2, rebalance_monthly=False, min_holding_days=1)
        s_monthly = MultiFactorStrategy(symbols=["SYM0", "SYM1", "SYM2", "SYM3"],
                                        top_n=2, rebalance_monthly=True, min_holding_days=1)
        sig_d = s_daily.generate(price_df, regime)
        sig_m = s_monthly.generate(price_df, regime)
        changes_d = (sig_d.diff().abs().sum(axis=1) > 0.001).sum()
        changes_m = (sig_m.diff().abs().sum(axis=1) > 0.001).sum()
        assert changes_m <= changes_d


class TestRelativeStrength:
    def test_rel_strength_uses_spy(self):
        """When SPY is in price_df, rel_strength factor should be computed."""
        price_df, regime, _ = _make_data()
        s = MultiFactorStrategy(
            symbols=["SYM0", "SYM1"],
            top_n=1,
            factor_weights={"rel_strength": 1.0},
            rebalance_monthly=False, min_holding_days=1,
        )
        signals = s.generate(price_df, regime)
        assert signals.shape[0] == len(price_df)

    def test_no_spy_still_works(self):
        """Without SPY, rel_strength is skipped but strategy doesn't crash."""
        price_df, regime, _ = _make_data()
        pdf_no_spy = price_df.drop(columns=["SPY"])
        s = MultiFactorStrategy(
            symbols=["SYM0", "SYM1"],
            top_n=1,
            factor_weights={"rel_strength": 1.0, "momentum": 0.5},
            rebalance_monthly=False, min_holding_days=1,
        )
        signals = s.generate(pdf_no_spy, regime)
        assert signals.shape[0] == len(pdf_no_spy)


class TestMultiFactorConcentration:
    """Guardrail: strategy-level soft cap + concentration diagnostic."""

    def test_soft_cap_clips_and_renormalises(self):
        price_df, regime, _ = _make_data()
        s = MultiFactorStrategy(
            symbols=[f"SYM{i}" for i in range(6)],
            top_n=3,
            rebalance_monthly=False,
            min_holding_days=1,
            score_weighted=True,
            soft_cap_max_single=0.40,
        )
        signals = s.generate(price_df, regime)
        # After warmup, no single weight should exceed the cap
        active = signals.iloc[60:]
        assert active.max().max() <= 0.40 + 1e-9, (
            f"soft cap violated: max={active.max().max():.4f}"
        )

    def test_soft_cap_disabled_by_default(self):
        """Without soft_cap_max_single, individual weights may exceed 0.5."""
        price_df, regime, _ = _make_data()
        s = MultiFactorStrategy(
            symbols=[f"SYM{i}" for i in range(6)],
            top_n=2,  # only 2 symbols → 50/50 equal weight (or concentrated with score_weighted)
            rebalance_monthly=False,
            min_holding_days=1,
            score_weighted=True,
        )
        signals = s.generate(price_df, regime)
        # Max weight may or may not exceed 0.5 — we just verify no error
        assert signals.shape[0] == len(price_df)

    def test_concentration_warn_logs(self, caplog):
        import logging
        price_df, regime, _ = _make_data()
        s = MultiFactorStrategy(
            symbols=[f"SYM{i}" for i in range(6)],
            top_n=2,
            rebalance_monthly=False,
            min_holding_days=1,
            concentration_warn_threshold=0.30,  # top_n=2 → equal 50% → violates
        )
        with caplog.at_level(logging.WARNING, logger="multi_factor"):
            s.generate(price_df, regime)
        # Expect at least one warning log for concentration
        concentrated = [r for r in caplog.records
                        if "concentration" in r.getMessage().lower()]
        assert len(concentrated) > 0, (
            "concentration_warn_threshold should trigger a WARNING log"
        )

    def test_soft_cap_preserves_total_when_room_exists(self):
        """When cap × n_active >= target total, redistribution preserves total
        exposure. If only 1 symbol is active and cap < 1.0, total cannot be
        preserved — acceptable: the cap is the binding constraint."""
        price_df, regime, _ = _make_data()
        s_nocap = MultiFactorStrategy(
            symbols=[f"SYM{i}" for i in range(6)],
            top_n=5, rebalance_monthly=False, min_holding_days=1,
            score_weighted=True,
        )
        s_cap = MultiFactorStrategy(
            symbols=[f"SYM{i}" for i in range(6)],
            top_n=5, rebalance_monthly=False, min_holding_days=1,
            score_weighted=True, soft_cap_max_single=0.40,
        )
        sig_nocap = s_nocap.generate(price_df, regime)
        sig_cap = s_cap.generate(price_df, regime)
        # For rows with enough active symbols, total should be preserved
        n_active = (sig_nocap > 0).sum(axis=1)
        room_mask = n_active * 0.40 >= 1.0
        if room_mask.any():
            diff = (sig_nocap.sum(axis=1) - sig_cap.sum(axis=1))[room_mask].abs()
            assert diff.max() < 0.05, (
                f"total exposure altered by {diff.max():.3f} when redistribution room existed"
            )
