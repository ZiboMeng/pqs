# Robustness eval — candidate_2_orthogonal_01

**evidence_class**: `pseudo_oos_robustness` (NOT deployable OOS — see PRD v3 §1.1)
**window**: 2025-04-16 → 2026-04-17 (252 TD / target 252)

## Metrics

- cum_ret: +191.57%
- sharpe (annualized): +3.740
- max_dd: -11.32%
- vs SPY: +158.13%
- vs QQQ: +147.41%
- turnover (daily mean): 0.3520
- fill_count: 1872
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
- generated_at_utc: 2026-04-26T01:39:02.544434+00:00
