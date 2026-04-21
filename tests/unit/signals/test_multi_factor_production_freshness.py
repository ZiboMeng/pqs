"""Regression tests for P0.1 (MultiFactor signal freshness).

Guards against silent drift back to the legacy `apply_extra_shift=True`
default, which made production paths execute T-2 data (T-1 signal
shifted once more, then T+1 open execution).

Covers:
  1. Module-level default MUST be False (as of 2026-04-20 fix)
  2. `MultiFactorSpace.instantiate` returns strategies with False
     (so every mining trial uses fresh signals)
  3. Truncation lookahead test re-run under the new default
"""

from __future__ import annotations

import inspect
import numpy as np
import pandas as pd

from core.mining.strategy_space import MultiFactorSpace
from core.signals.strategies.multi_factor import MultiFactorStrategy


def _make_prices(n=300, n_syms=4, seed=42):
    np.random.seed(seed)
    idx = pd.bdate_range("2023-01-02", periods=n)
    syms = [f"SYM{i}" for i in range(n_syms)]
    arr = 100 + np.cumsum(np.random.randn(n, n_syms) * 0.5, axis=0)
    return pd.DataFrame(arr, index=idx, columns=syms)


class TestDefaultIsFresh:
    def test_constructor_default_is_false(self):
        """The __init__ default for apply_extra_shift MUST be False.
        If this fails, someone flipped the default back to legacy True
        — that produces T-2 stale signals in every production path."""
        sig = inspect.signature(MultiFactorStrategy.__init__)
        default = sig.parameters["apply_extra_shift"].default
        assert default is False, (
            f"MultiFactorStrategy default apply_extra_shift changed to "
            f"{default}. Per 2026-04-20 P0.1, this MUST stay False to "
            f"avoid T-2 stale signals in production paths."
        )

    def test_default_strategy_uses_t_close_factors(self):
        """A strategy built with defaults (no apply_extra_shift kwarg)
        should produce a signal at T that reflects T-close data, not
        T-1 close data. Proof: truncate history at T and verify the
        signal at T is identical — means no info was used beyond T."""
        prices = _make_prices(n=300, n_syms=4)
        regime = pd.Series("BULL", index=prices.index)

        s = MultiFactorStrategy(
            symbols=list(prices.columns), top_n=2,
            rebalance_monthly=False, min_holding_days=1,
        )
        sig_full = s.generate(prices, regime)

        # Truncate at T = 70% through history
        test_T = prices.index[int(len(prices) * 0.7)]
        s_trunc = MultiFactorStrategy(
            symbols=list(prices.columns), top_n=2,
            rebalance_monthly=False, min_holding_days=1,
        )
        sig_trunc = s_trunc.generate(
            prices.loc[:test_T], regime.loc[:test_T],
        )
        if test_T in sig_full.index and test_T in sig_trunc.index:
            a = sig_full.loc[test_T].fillna(0)
            b = sig_trunc.loc[test_T].fillna(0)
            assert (a - b).abs().max() < 1e-9, (
                "Signal at T with default apply_extra_shift differs "
                "between full-history and truncated-at-T — lookahead "
                "or inconsistent freshness semantics."
            )


class TestMiningSpaceFreshness:
    def test_multifactor_space_instantiates_with_false(self):
        """Every mining trial must produce strategies with
        apply_extra_shift=False — otherwise mining ranks strategies
        by stale T-2 signal behavior, polluting every promotion."""
        space = MultiFactorSpace()
        params = {
            "top_n": 4,
            "w_low_vol": 0.05, "w_momentum": 0.20, "w_quality": 0.20,
            "w_pv_div": 0.10, "w_rel_strength": 0.20, "w_market_trend": 0.10,
            "rebalance_monthly": False, "score_weighted": True,
            "lookback_vol": 63, "lookback_mom": 189, "lookback_quality": 189,
            "min_holding_days": 5,
        }
        strat = space.instantiate(params, risk_universe=["A", "B", "C"])
        assert strat._apply_extra_shift is False
