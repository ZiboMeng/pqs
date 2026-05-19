"""PRD-2 P2.1 R4 — cadence × construction_tier interaction (TDD).

Grounded re-scope (honest, like P1.2 / R2-a): PRD-2 ralph-loop R4
said "wire K1 signal_driven_runner.rebalance_mask into harness" — but
K1 has NO rebalance_mask; cadence is ALREADY canonically implemented
+ wired in composite_evaluator (rebalance_mask + cfg.rebalance_cadence,
all 3 cadences validated & used by evaluate_composite_spec, and
thoroughly tested in test_harness_composite_evaluator.py). There is
no K1 consolidation to do. The genuinely-NEW untested surface after
R2-b is the cadence × construction_tier INTERACTION: the tier overlay
must hedge correctly on every rebalance row regardless of how many
rows the cadence produced (monthly = few rows, weekly/daily = more).
apply_tier_overlay is per-row, so correctness is cadence-independent
BY CONSTRUCTION — this proves it.
"""
import inspect

import numpy as np
import pandas as pd
import pytest

import core.research.harness.composite_evaluator as ce
from core.research.construction_tiers import apply_tier_overlay


def _signals(n_rebalance_rows: int) -> pd.DataFrame:
    """Simulate signals a cadence would produce: n non-zero rebalance
    rows (weekly/daily -> larger n; monthly -> small n) interleaved
    with all-zero no-trade rows."""
    idx = pd.bdate_range("2020-01-01", periods=n_rebalance_rows * 2)
    rows = []
    for i in range(len(idx)):
        if i % 2 == 0:
            rows.append({"AAA": 0.6, "BBB": 0.4})   # rebalance row
        else:
            rows.append({"AAA": 0.0, "BBB": 0.0})   # no-trade row
    return pd.DataFrame(rows, index=idx)


class TestCadenceTierInteraction:
    @pytest.mark.parametrize("n", [2, 6, 24])  # monthly~ / weekly~ / daily~
    def test_T1_hedges_every_rebalance_row_regardless_of_cadence(self, n):
        s = _signals(n)
        out = apply_tier_overlay(s, "T1", "SH", 0.20)
        reb = out[(out[["AAA", "BBB"]] != 0.0).any(axis=1)]
        # every rebalance row hedged: SH=0.20, sum=1, all >=0.
        # (element-wise approx via np.allclose — `Series ==
        # pytest.approx(scalar)` does NOT broadcast per-element.)
        assert np.allclose(reb["SH"].to_numpy(), 0.20, atol=2e-7)
        assert np.allclose(reb.sum(axis=1).to_numpy(), 1.0, atol=2e-7)
        assert (out.values >= -1e-12).all()
        # no-trade rows untouched (no phantom hedge injected)
        notrade = out[(out[["AAA", "BBB"]] == 0.0).all(axis=1)]
        assert np.allclose(notrade.abs().sum(axis=1).to_numpy(), 0.0,
                           atol=2e-7)

    @pytest.mark.parametrize("n", [2, 6, 24])
    def test_T0_identity_under_any_cadence(self, n):
        s = _signals(n)
        pd.testing.assert_frame_equal(apply_tier_overlay(s, "T0", "SH", 0.0), s)

    def test_more_cadence_rows_more_hedged_rows(self):
        # weekly-like (more rebalances) hedges strictly more rows than
        # monthly-like — the interaction is linear in #rebalance rows.
        mo = apply_tier_overlay(_signals(2), "T1", "PSQ", 0.15)
        wk = apply_tier_overlay(_signals(12), "T1", "PSQ", 0.15)
        assert int((wk["PSQ"] > 0).sum()) > int((mo["PSQ"] > 0).sum())

    def test_overlay_applied_after_cadence_mask_in_evaluate(self):
        # structural: evaluate_composite_spec must call apply_tier_overlay
        # AFTER rebalance_mask (so the overlay is cadence-agnostic — it
        # acts on whatever rows the cadence produced, not before).
        src = inspect.getsource(ce.evaluate_composite_spec)
        i_mask = src.index("rebalance_mask(")
        i_overlay = src.index("apply_tier_overlay(")
        assert i_mask < i_overlay, (
            "apply_tier_overlay must run AFTER rebalance_mask so the "
            "tier overlay is cadence-agnostic (acts on cadence's rows)")
