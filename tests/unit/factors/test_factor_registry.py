"""Tests for the factor registry contract (约束 2).

Enforces:
  - PRODUCTION_FACTORS == MultiFactorSpace._TUNED_FACTORS
  - Every research→production mapping target is in PRODUCTION_FACTORS
  - factor_generator output names all appear in RESEARCH_FACTORS
    (drift detection — catches new factor families silently added to
    factor_generator without registry update)
  - MultiFactorStrategy drops unregistered factor names and logs a
    warning
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from core.factors.factor_generator import generate_all_factors
from core.factors.factor_registry import (
    PRODUCTION_FACTORS,
    RESEARCH_FACTORS,
    RESEARCH_TO_PRODUCTION_MAP,
    check_execution_factor_names,
    production_factor_names,
    research_only_factors,
)
from core.mining.strategy_space import MultiFactorSpace
from core.signals.strategies.multi_factor import MultiFactorStrategy


class TestRegistryIntegrity:
    def test_production_factors_matches_mining_space(self):
        assert MultiFactorSpace._TUNED_FACTORS == PRODUCTION_FACTORS

    def test_production_factors_not_empty(self):
        assert len(PRODUCTION_FACTORS) > 0

    def test_ordered_names_roundtrip(self):
        names = production_factor_names()
        assert set(names) == PRODUCTION_FACTORS
        assert len(names) == len(PRODUCTION_FACTORS)  # no dupes

    def test_research_to_production_map_targets_exist(self):
        for research_name, prod_name in RESEARCH_TO_PRODUCTION_MAP.items():
            assert research_name in RESEARCH_FACTORS, (
                f"mapping key {research_name} not in RESEARCH_FACTORS"
            )
            assert prod_name in PRODUCTION_FACTORS, (
                f"mapping target {prod_name} not in PRODUCTION_FACTORS"
            )

    def test_research_only_factors_exist(self):
        ro = research_only_factors()
        # Research-only = research factors with no production mapping
        assert ro == RESEARCH_FACTORS - set(RESEARCH_TO_PRODUCTION_MAP.keys())


class TestFactorGeneratorAlignsWithRegistry:
    """factor_generator output names must all appear in RESEARCH_FACTORS.
    Drift test — forces updating the registry when new factor families
    are added to factor_generator."""

    def test_all_generator_outputs_registered(self):
        np.random.seed(42)
        idx = pd.bdate_range("2024-01-01", periods=400)
        # QQQ added for PRD 20260424 Family A features (rel_qqq_20d etc.)
        syms = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA"]
        price = pd.DataFrame(
            100 + np.cumsum(np.random.randn(400, len(syms)) * 0.5, axis=0),
            index=idx, columns=syms,
        )
        volume = pd.DataFrame(
            np.random.uniform(1e6, 1e8, (400, len(syms))),
            index=idx, columns=syms,
        )
        open_df = price.shift(1).bfill()
        # Synthetic high / low panels so hl_range (PRD 20260423 R02)
        # participates in the drift check. Simple ±0.5% envelope around
        # close — enough to produce a finite H-L each bar.
        high_df = price * 1.005
        low_df = price * 0.995
        # Synthetic 60m RTH bars so intraday factor family (Round 5
        # Topic F, 2026-04-20) participates in the drift check.
        intraday_bars_60m = {}
        bar_times = []
        for d in idx[:120]:  # 4 months of intraday bars is enough
            for h, m in [(10, 30), (11, 30), (12, 30), (13, 30),
                         (14, 30), (15, 30), (16, 0)]:
                bar_times.append(d.replace(hour=h, minute=m))
        bar_idx = pd.DatetimeIndex(bar_times)
        for sym in syms:
            ret = np.random.normal(0, 0.004, len(bar_idx))
            close = 100 * np.exp(np.cumsum(ret))
            intraday_bars_60m[sym] = pd.DataFrame({
                "open":  close * 0.999,
                "high":  close * 1.001,
                "low":   close * 0.999,
                "close": close,
                "volume": np.random.randint(1e4, 1e5, len(bar_idx)),
            }, index=bar_idx)

        factors = generate_all_factors(
            price, volume, open_df=open_df,
            high_df=high_df, low_df=low_df,
            intraday_bars_60m=intraday_bars_60m,
        )

        produced = set(factors.keys())
        missing_from_registry = produced - RESEARCH_FACTORS
        missing_from_generator = RESEARCH_FACTORS - produced
        assert not missing_from_registry, (
            f"factor_generator produces {missing_from_registry} but "
            f"they are not in RESEARCH_FACTORS. Update the registry."
        )
        assert not missing_from_generator, (
            f"RESEARCH_FACTORS lists {missing_from_generator} but "
            f"factor_generator does not produce them. Remove stale names."
        )


class TestExecutionGate:
    """MultiFactorStrategy must drop unregistered factor names."""

    def test_unknown_factor_name_dropped_with_warning(self, caplog):
        with caplog.at_level(logging.WARNING):
            strat = MultiFactorStrategy(
                symbols=["SPY", "AAPL"],
                factor_weights={
                    "momentum": 0.5,
                    "price_volume_div": 0.5,  # research name, NOT production
                    "nonsense_factor": 0.3,    # typo
                },
            )
        # Only 'momentum' should survive
        assert set(strat._weights.keys()) == {"momentum"}
        # Warning must mention the offending names
        msgs = "\n".join(r.message for r in caplog.records)
        assert "price_volume_div" in msgs
        assert "nonsense_factor" in msgs

    def test_all_production_factors_accepted(self):
        weights = {name: 1.0 / len(PRODUCTION_FACTORS) for name in PRODUCTION_FACTORS}
        strat = MultiFactorStrategy(
            symbols=["SPY", "AAPL"],
            factor_weights=weights,
        )
        assert set(strat._weights.keys()) == PRODUCTION_FACTORS

    def test_check_execution_factor_names_empty_when_clean(self):
        good = {"momentum": 0.5, "quality": 0.5}
        assert check_execution_factor_names(good) == []

    def test_check_execution_factor_names_flags_unknowns(self):
        mixed = {"momentum": 0.5, "foo": 0.3, "bar": 0.2}
        flagged = check_execution_factor_names(mixed)
        assert set(flagged) == {"foo", "bar"}
