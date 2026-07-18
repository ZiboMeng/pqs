# Phase-two strategy registry

Authoritative machine record: `research/registry/strategy_registry.json`.

## Approved PAPER strategy

### `dual_index_growth_v1` — `PAPER_APPROVED`

- Role: unlevered growth engine; it is not a stable-core substitute.
- Assets: SPY, QQQ, IEF, GLD, BIL and SHY.
- Signal: month-end QQQ slow trend plus positive 126-session return and SPY
  200-session trend; fixed 21-session cooldown after exit.
- Execution: signal at session close, first legal fill at next tradable open.
- Risk-on allocation: 35% QQQ, 35% SPY, 15% GLD, residual BIL/SHY.
- Risk-off allocation: 30% IEF, 30% GLD, 20% BIL and 20% SHY.
- Aggregate constraints: gross <=100%, position <=35%, cash >=5%, annual
  turnover gate <=8x, no leverage, no shorting, no TQQQ.
- Kill/degrade: 17.5% drawdown degrades; 25% halts; broker mismatch,
  UNKNOWN/low-confidence regime data, stale/missing data and manual pauses fail closed.
- Invalidating conditions: rolling 60-session Sharpe below -0.5, drawdown at
  25%, data provenance change, timing/cost drift, or reconciliation failure.
- Default configuration: enabled only in `config/strategies.paper.yaml`.
- LIVE: `false` in every phase-two config and registry record.

Evidence:

- Development: `research/results/phase2/development/selection_d2r5.json`
- Validation: `research/results/phase2/validation/summary_d2r5.json`
- Final holdout: `research/results/phase2/holdout/summary_d2r5.json`
- PAPER acceptance: `research/results/phase2/paper/operational_acceptance.json`
- Promotion decision: `research/registry/promotion_registry.json`

## Non-approved candidates

| Candidate | Final disposition |
|---|---|
| adaptive_core_v1 | final holdout fail; no retune |
| controlled_growth_v1 | development fail; stop v1 |
| sector_rotation_v1 | validation execution invariant fail |
| sector_rotation_v2 | final holdout fail; no retune |
| etf_reversion_v1 | development fail; stop v1 |
| risk_balanced_core_v1 | development fail; stop v1 |
| defensive_growth_v1 | development fail; stop v1 |
| multi_asset_trend_v1 | development fail; stop v1 |
| crash_buffer_core_v1 | D2R6 development fail; terminal family stopped |

There is no second approved strategy. Complementarity gates cannot be claimed
with a single member and remain not applicable, not passed by assumption.
