# Robustness eval — rcm_v1_defensive_composite_01

**evidence_class**: `pseudo_oos_robustness` (NOT deployable OOS — see PRD v3 §1.1)
**window**: 2025-04-16 → 2026-04-17 (252 TD / target 252)

## Metrics

- cum_ret: +62.76%
- sharpe (annualized): +1.879
- max_dd: -16.57%
- vs SPY: +29.31%
- vs QQQ: +18.60%
- turnover (daily mean): 0.0821
- fill_count: 336
- n_dates: 252

## Caveats

- This is **pseudo-OOS robustness**, not deployable OOS evidence.
  The window predates frozen-date and was reachable during candidate
  construction. Treating these numbers as out-of-sample would re-create
  the chronic trap PRD v3 §1.3 warns about.
- Real OOS validation requires forward observation (post-frozen-date)
  per the forward manifest schema (PRD v3 §B).

## Data integrity snapshot

- daily_store_rebuild_commit: `9fa4118b497a4c01abcb7c3d13939be29ba2ff61`
- baseline_snapshot_path: `data/baseline/latest.json`
- generated_at_utc: 2026-04-25T23:47:53.191417+00:00
