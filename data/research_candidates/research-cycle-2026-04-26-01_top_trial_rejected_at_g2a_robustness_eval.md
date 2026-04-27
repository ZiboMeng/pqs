# Robustness eval — research-cycle-2026-04-26-01_top_trial_rejected_at_g2a

**evidence_class**: `pseudo_oos_robustness` (NOT deployable OOS — see PRD v3 §1.1)
**window**: 2024-01-01 → 2024-12-31 (252 TD / target 252)

## Metrics

- cum_ret: +28.01%
- sharpe (annualized): +0.889
- max_dd: -28.84%
- vs SPY: +4.01%
- vs QQQ: +1.02%
- turnover (daily mean): 0.0937
- fill_count: 400
- n_dates: 252

## Caveats

- This is **pseudo-OOS robustness**, not deployable OOS evidence.
  The window predates frozen-date and was reachable during candidate
  construction. Treating these numbers as out-of-sample would re-create
  the chronic trap PRD v3 §1.3 warns about.
- Real OOS validation requires forward observation (post-frozen-date)
  per the forward manifest schema (PRD v3 §B).

## Data integrity snapshot

- daily_store_rebuild_commit: `f170b0c00000`
- baseline_snapshot_path: `data/baseline/latest.json`
- generated_at_utc: 2026-04-26T19:11:01.878087+00:00
