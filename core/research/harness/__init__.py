"""Per-trial composite-spec → paper-NAV harness (Cycle #02 prep).

Step 1 of the priority-realign post-cycle-#01 path. Provides
``evaluate_composite_spec`` which takes a ResearchCompositeSpec
(produced by the research miner) plus already-built factor panels
plus price + benchmark data, and returns:

  - NAV history (daily) under the spec's composite signal interpreted
    as a top-N equal-weight portfolio
  - daily weight history (post-construction)
  - per-validation-year metrics (cum_ret, sharpe, max_dd, vs_spy, vs_qqq)
  - per-stress-slice metrics (covid_flash, rate_hike_2022)
  - concentration metrics (top1_max, top3_max, watchlist_share, etc.)
  - raw + residual NAV correlation diagnostics vs SPY+QQQ benchmarks

Critical design notes:
  - The harness REUSES BacktestEngine for the return computation
    path. This is mandated by the Step 0 finding that raw daily
    parquet files have heterogeneous split adjustment which
    BarStore.load(adjusted=True) cannot fully normalize; the paper
    engine + BacktestEngine path correctly handles this.
  - rebalance_cadence is configurable: 'monthly' | 'weekly' | 'daily'.
    Required because Cycle #02's primary axis is C-1 weekly cadence
    (per docs/memos/20260430-step0_retro_c1_pivot.md).
  - The composite signal is interpreted as a cross-sectional ranking
    of stocks; the harness picks top_n at each rebalance, equal-
    weights, and holds between rebalances. This matches the legacy
    MultiFactorStrategy construction so that any difference in
    realized NAV between the harness output and a hypothetical MFS
    run is purely due to the composite scoring (not construction).

Cycle #02 prep status: this module is the precondition for
evaluating Track A 17-gate aggregate-pass on a Cycle #02 candidate
that doesn't trivially fail anti-sibling discipline at the feature
level.
"""

from .composite_evaluator import (
    EvaluatedComposite,
    HarnessConfig,
    evaluate_composite_spec,
    rebalance_mask,
    topn_signals_from_composite,
)

__all__ = [
    "EvaluatedComposite",
    "HarnessConfig",
    "evaluate_composite_spec",
    "rebalance_mask",
    "topn_signals_from_composite",
]
