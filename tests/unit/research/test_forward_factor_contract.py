"""Factor input-contract resolver tests (PRD v2.1 §4.3.0).

Pin the live frozen specs (RCMv1 + Cand-2) so an accidental contract
change for any of their factors fails CI. Also pin fail-closed
behavior on unknown factors.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.research.forward import (
    ContractResolutionError,
    max_lookback,
    resolve_factor_input_contract,
    union_attributes,
    union_benchmark_symbols,
)
from core.research.frozen_spec import FrozenStrategySpec, FeatureEntry


CAND_DIR = Path("data/research_candidates")


def test_resolve_factor_input_contract_rcm_v1():
    spec = FrozenStrategySpec.from_yaml_file(
        CAND_DIR / "rcm_v1_defensive_composite_01.yaml",
    )
    c = resolve_factor_input_contract(spec)
    assert set(c.keys()) == {
        "beta_spy_60d", "drawup_from_252d_low",
        "days_since_52w_high", "amihud_20d",
    }
    assert union_attributes(c) == {"close", "volume"}
    assert max_lookback(c) == 252
    assert union_benchmark_symbols(c) == {"SPY"}
    # beta_spy_60d is the only cross_sectional factor in this spec
    assert c["beta_spy_60d"].cross_sectional is True
    assert c["amihud_20d"].cross_sectional is False


def test_resolve_factor_input_contract_cand_2():
    spec = FrozenStrategySpec.from_yaml_file(
        CAND_DIR / "candidate_2_orthogonal_01.yaml",
    )
    c = resolve_factor_input_contract(spec)
    assert set(c.keys()) == {"ret_5d", "rs_vs_spy_126d", "hl_range"}
    assert union_attributes(c) == {"close", "high", "low"}
    assert max_lookback(c) == 126
    assert union_benchmark_symbols(c) == {"SPY"}
    # rs_vs_spy_126d is the only cross_sectional factor in this spec
    assert c["rs_vs_spy_126d"].cross_sectional is True
    assert c["hl_range"].cross_sectional is False


def test_resolve_factor_input_contract_unknown_factor_fails_closed():
    """Synthetic spec with an unknown factor must raise, NOT silently
    default to close-only. Silent under-hashing is worse than no hash.
    """
    # Build a minimal in-memory FrozenStrategySpec with an unregistered
    # factor name. We bypass yaml round-trip to keep the test focused on
    # the resolver contract.
    spec = FrozenStrategySpec(
        candidate_id="test_unknown_factor",
        strategy_version="test-1",
        source_trial_id="t000",
        feature_set=[
            FeatureEntry(name="beta_spy_60d", weight=0.5),
            FeatureEntry(name="some_factor_we_have_not_registered_yet", weight=0.5),
        ],
        benchmark_relative_summary="placeholder",
        oos_holdout_summary="placeholder",
        robustness_summary="placeholder",
        decision_memo="docs/test.md",
        labels={"fwd_return_horizon_days": 21, "fwd_return_mode": "cc"},
        panel_contract={"universe": "test"},
        composite_rule={"method": "weighted_sum"},
        transforms={"standardization": "zscore_cross_sectional"},
    )
    with pytest.raises(ContractResolutionError) as exc_info:
        resolve_factor_input_contract(spec)
    assert "some_factor_we_have_not_registered_yet" in str(exc_info.value)
