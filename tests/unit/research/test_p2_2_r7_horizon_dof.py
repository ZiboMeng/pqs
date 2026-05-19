"""PRD-2 P2.2 R7 — non-intraday horizon DOF (TDD).

Grounded re-scope (honest, same pattern as R4/R6): the non-intraday
holding-horizon DOF is ALREADY wired = ``min_holding_days`` (enforced
in BOTH topn_signals_from_composite AND topn_signals_with_caps via
``days_since_rebal < min_holding_days → continue``; validated ≥1;
partly tested on the non-caps path). ``horizon_days`` is documented
"mining forward-return horizon (NOT used by harness)" — a label
horizon, NOT a holding control. The genuinely-NEW R7 surface is
min_holding_days as a HORIZON DOF on the cap_aware path at
non-trivial horizons (5d / 63d) + monotonicity + a structural guard
that horizon_days does NOT drive harness holding.
"""
import inspect

import numpy as np
import pandas as pd
import pytest

import core.research.harness.composite_evaluator as ce
from core.research.harness.composite_evaluator import (
    HarnessConfig, topn_signals_with_caps,
)


def _composite(n_dates: int, n_syms: int = 6) -> pd.DataFrame:
    idx = pd.bdate_range("2015-01-01", periods=n_dates)
    rng = np.random.default_rng(7)
    return pd.DataFrame(
        rng.standard_normal((n_dates, n_syms)),
        index=idx, columns=[f"S{i}" for i in range(n_syms)])


_CMAP = {f"S{i}": f"clu{i}" for i in range(6)}  # 1 sym per cluster


def _n_rebalances(comp, min_hold):
    sig = topn_signals_with_caps(
        comp, pd.Series(True, index=comp.index),
        target_n_picks=3, cluster_map=_CMAP,
        cluster_cap=1.0, max_single_weight=1.0,  # loose: isolate horizon
        min_holding_days=min_hold)
    return int((sig.diff().abs().sum(axis=1) > 1e-9).iloc[1:].sum())


class TestHorizonDOF:
    def test_min_holding_days_is_horizon_dof_on_cap_aware_path(self):
        comp = _composite(130)               # > 63 so 63d horizon binds
        n1 = _n_rebalances(comp, 1)
        n5 = _n_rebalances(comp, 5)
        n63 = _n_rebalances(comp, 63)
        # horizon DOF: longer hold → strictly fewer rebalances
        assert n1 > n5 > n63 >= 1
        # spacing sanity: 63d horizon over 130 bdays → ~ a couple holds
        assert n63 <= 130 // 63 + 1

    def test_default_min_holding_days_1_unchanged(self):
        comp = _composite(40)
        n_default = _n_rebalances(comp, 1)
        # min=1 + all-True mask → rebalance (nearly) every day
        assert n_default >= 35

    @pytest.mark.parametrize("h", [5, 21, 63])
    def test_spacing_respects_horizon(self, h):
        comp = _composite(200)
        sig = topn_signals_with_caps(
            comp, pd.Series(True, index=comp.index),
            target_n_picks=3, cluster_map=_CMAP,
            cluster_cap=1.0, max_single_weight=1.0, min_holding_days=h)
        chg = np.flatnonzero(
            (sig.diff().abs().sum(axis=1) > 1e-9).to_numpy())
        if len(chg) >= 2:
            assert np.diff(chg).min() >= h   # never closer than horizon

    def test_horizon_days_is_NOT_a_harness_holding_control(self):
        # semantics guard: horizon_days is mining-label only; it must
        # NOT be referenced by the signal-construction functions.
        for fn in (ce.topn_signals_from_composite,
                   ce.topn_signals_with_caps):
            assert "horizon_days" not in inspect.getsource(fn), (
                f"{fn.__name__} references horizon_days — it is a "
                f"mining-label horizon, NOT a harness holding control")
        # and HarnessConfig accepts it but it does not gate holding
        assert HarnessConfig(horizon_days=63).horizon_days == 63
