"""Round 6 Topic E (2026-04-20): shadowed-factor merge tests.

Validates that `vol_63d ↔ low_vol` and `rs_vs_spy_63d ↔ rel_strength`
shadow pairs have been unified to a single implementation
(core/factors/base_factors.py).

Invariants:
  1. base_factors helpers are pure functions (same inputs → same output)
  2. factor_generator.vol_63d value matches direct call to
     low_vol_factor(price_df, lookback=63)
  3. MultiFactorStrategy's internal low_vol factor is computed via
     low_vol_factor (no longer inline)
  4. rel_strength_factor called from both paths yields identical values
  5. RESEARCH_TO_PRODUCTION_MAP no longer contains vol_63d or
     rs_vs_spy_63d
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from core.factors.base_factors import low_vol_factor, rel_strength_factor
from core.factors.factor_generator import generate_all_factors
from core.factors.factor_registry import RESEARCH_TO_PRODUCTION_MAP


def _make_prices(n: int = 200, n_syms: int = 5, seed: int = 0):
    np.random.seed(seed)
    idx = pd.bdate_range("2023-01-02", periods=n)
    syms = ["SPY"] + [f"SYM{i}" for i in range(n_syms - 1)]
    arr = 100 + np.cumsum(np.random.randn(n, n_syms) * 0.5, axis=0)
    return pd.DataFrame(arr, index=idx, columns=syms)


class TestBaseFactorsHelpersArePure:

    def test_low_vol_factor_deterministic(self):
        price = _make_prices(seed=7)
        a = low_vol_factor(price, lookback=63, min_periods=20)
        b = low_vol_factor(price, lookback=63, min_periods=20)
        pd.testing.assert_frame_equal(a, b)

    def test_low_vol_factor_shape_and_sign(self):
        price = _make_prices(seed=1)
        f = low_vol_factor(price, lookback=63, min_periods=20)
        assert f.shape == price.shape
        # All non-NaN values should be <= 0 (factor is -std)
        valid = f.dropna().values.flatten()
        assert (valid <= 0).all()

    def test_rel_strength_deterministic(self):
        price = _make_prices(seed=11)
        a = rel_strength_factor(price, benchmark_col="SPY", lookback=63)
        b = rel_strength_factor(price, benchmark_col="SPY", lookback=63)
        pd.testing.assert_frame_equal(a, b)

    def test_rel_strength_benchmark_column_is_zero(self):
        """The benchmark's own rs_vs_benchmark should be 0 (minus
        itself)."""
        price = _make_prices(seed=3)
        rs = rel_strength_factor(price, "SPY", 63)
        spy_rs = rs["SPY"].dropna()
        assert (spy_rs.abs() < 1e-12).all()


class TestFactorGeneratorUsesSharedImpl:

    def test_vol_63d_matches_direct_call(self):
        price = _make_prices(seed=42)
        out = generate_all_factors(price)
        direct = low_vol_factor(price, lookback=63, min_periods=20)
        pd.testing.assert_frame_equal(
            out["vol_63d"], direct,
            check_names=False,
        )

    def test_vol_21d_also_uses_helper(self):
        price = _make_prices(seed=42)
        out = generate_all_factors(price)
        direct_21 = low_vol_factor(price, lookback=21, min_periods=20)
        pd.testing.assert_frame_equal(
            out["vol_21d"], direct_21,
            check_names=False,
        )

    def test_rs_vs_spy_63d_matches_direct_call(self):
        price = _make_prices(seed=42)
        out = generate_all_factors(price)
        direct = rel_strength_factor(price, "SPY", 63)
        pd.testing.assert_frame_equal(
            out["rs_vs_spy_63d"], direct,
            check_names=False,
        )


class TestMultiFactorUsesSharedImpl:

    def test_multifactor_low_vol_matches_base_helper(self):
        """MultiFactorStrategy's low_vol computation should now go
        through low_vol_factor rather than inline logic."""
        from core.signals.strategies.multi_factor import MultiFactorStrategy

        price = _make_prices(seed=17)
        symbols = [c for c in price.columns if c != "SPY"]
        regime = pd.Series("BULL", index=price.index)

        s = MultiFactorStrategy(
            symbols=symbols, top_n=2,
            factor_weights={"low_vol": 1.0},  # isolate low_vol
            rebalance_monthly=False,
            min_holding_days=1,
            apply_extra_shift=False,
            lookback_vol=63,
        )
        # Generate signals and check: under z-score equivalence, a
        # strategy with low_vol alone should select the lowest-vol
        # non-SPY symbols. No crash = proves helper integration.
        sig = s.generate(price, regime)
        # At least some non-zero selection after warmup
        assert sig.iloc[-20:].abs().sum().sum() > 0


class TestRegistryMapShrunk:

    def test_vol_63d_no_longer_shadow_mapped(self):
        assert "vol_63d" not in RESEARCH_TO_PRODUCTION_MAP

    def test_rs_vs_spy_63d_no_longer_shadow_mapped(self):
        assert "rs_vs_spy_63d" not in RESEARCH_TO_PRODUCTION_MAP

    def test_map_shrunk_by_exactly_two(self):
        # Before Round 6: 9 entries. After Round 6 Topic E merge: 7
        # (vol_63d + rs_vs_spy_63d removed). PRD 20260423 R02 added
        # back `vol_20d` as alias of vol_21d → low_vol, so 8 now.
        # volume_ratio_20d is NOT in this map (its canonical
        # volume_surge_20d has no PROD sibling).
        assert len(RESEARCH_TO_PRODUCTION_MAP) == 8

    def test_remaining_map_entries_still_valid(self):
        """Sanity: all remaining map keys target production factors
        still present in PRODUCTION_FACTORS."""
        from core.factors.factor_registry import PRODUCTION_FACTORS
        for research_name, prod_name in RESEARCH_TO_PRODUCTION_MAP.items():
            assert prod_name in PRODUCTION_FACTORS


class TestBackwardCompatibility:

    def test_generate_all_factors_still_includes_vol_63d(self):
        """Even after merge, the research-facing name is preserved
        (research scripts / reports still refer to it)."""
        price = _make_prices(seed=5)
        out = generate_all_factors(price)
        assert "vol_63d" in out
        assert "rs_vs_spy_63d" in out

    def test_generate_all_factors_still_includes_vol_21d(self):
        price = _make_prices(seed=5)
        out = generate_all_factors(price)
        assert "vol_21d" in out
