# Round-3 Step 3b — Daily Parquet Rebuild Complete

**Date**: 2026-04-25
**Status**: full universe daily store rebuilt from polygon 1m via the
step-1 aggregator. Three sidecars persisted. Step 4 (baseline + 4
paper cells re-run) now unblocked.

---

## Run summary

```
[rebuild_daily] 59 symbols, mode = APPLY (writes parquet)
all 59 processed in 279.6s

Symbols processed:    59
Symbols actually written: 58  (apply mode)
Symbols dropped:      1  ['no_1m_parquet']  → BRK-B
Total new rows:       149,069
  of which thin_data:    6,748 (4.53%)
  of which partial:      1,231 (0.83%)
Quarantined rows:     8,787
Old rows (cur store): 170,584
Net delta:            -21,515
Watch sidecar:        18 symbols flagged
```

The −21,515 row delta is dominated by:
- 31,675 Sat/Sun-labeled rows correctly removed (old +1d offset bug
  artifact)
- 8,787 newly quarantined rows (low-bar-count or missing endpoints,
  per the user-pinned two-tier policy)
- ~+19,000 net new clean Mondays recovered (no longer shifted to Sat)

---

## Sidecars persisted

All gitignored under `data/ref/`:

1. **`data/ref/daily_rebuild_manifest.parquet`** — 59 rows, one per
   universe symbol:
   ```
   symbol  old_rows  new_rows  thin_data_count  partial_count  quarantine_count  written  drop_reason
   ```

2. **`data/ref/incomplete_days.parquet`** — 8,787 rows, one per
   `(symbol, date)` quarantined day:
   ```
   reason / n_bars / first_bar_ts / last_bar_ts / partial_day_whitelisted
   ```
   Reasons distribution: `low_bar_count<300` ≫ `missing_1559_close` ≫
   `missing_0930_open`.

3. **`data/ref/data_quality_watch.parquet`** — 18 symbols flagged:
   ```
   sym     thin_pct%  quar_pct%  written  reasons
   BRK-B    0.00      0.00       FALSE    dropped:no_1m_parquet | hardcoded_watch
   BKNG    58.28     76.69       TRUE     hardcoded | thin>5% | quar>10%
   CMG     30.18     51.92       TRUE     hardcoded | thin>5% | quar>10%
   TKO     54.13     29.34       TRUE     hardcoded | thin>5% | quar>10%
   ISRG    33.69     27.76       TRUE     thin>5% | quar>10%
   SOXL    19.55     21.60       TRUE     hardcoded | thin>5% | quar>10%
   TT      18.12     20.06       TRUE     hardcoded | thin>5% | quar>10%
   MCK     21.08     17.47       TRUE     thin>5% | quar>10%
   ACGL    22.38     17.22       TRUE     thin>5% | quar>10%
   LLY      0.00     13.70       TRUE     quar>10%
   ABT      0.00     11.38       TRUE     quar>10%
   KLAC    20.29      6.27       TRUE     thin>5%
   APD     25.03      6.13       TRUE     thin>5%
   TMO      7.43      5.57       TRUE     thin>5%
   PWR     17.48      3.84       TRUE     thin>5%
   CLX     14.02      2.50       TRUE     thin>5%
   TRV      9.17      2.36       TRUE     thin>5%
   LRCX     7.11      1.37       TRUE     thin>5%
   ```

---

## Sanity verification

### Schema + label

`data/daily/AAPL.parquet` (post-rebuild):
```
cols: [open, high, low, close, volume, amount, partial_day, thin_data]
rows: 2839
date range: 2015-01-02 → 2026-04-17
Sat/Sun rows: 0  ← matches R-1 contract
partial_day count: 23  ← NYSE half-day whitelist matches
thin_data count: 0  ← AAPL has no thin days
```

### +1d offset bug eliminated

`data/daily/SPY.parquet` 2022-08-22..09-02 spot-check:
```
2022-08-22 Mon close=413.46  ← was missing pre-rebuild
2022-08-23 Tue close=412.33
2022-08-24 Wed close=413.63
2022-08-25 Thu close=419.51
2022-08-26 Fri close=405.32
2022-08-29 Mon close=402.63  ← was missing pre-rebuild
2022-08-30 Tue close=398.18
...
```
All real ET trading dates present; **no 2022-08-27 Sat row anywhere**.
The Mon→Sat date-label offset is gone.

---

## Known issue surfaced during sanity: TJX split-crossing in polygon 1m

`data/intraday/1m/TJX.parquet` close around the 2017-04-05 (2:1)
split:
```
2017-03-31 Fri close = 79.07
2017-04-03 Mon close = 78.34
2017-04-04 Tue close = 76.70  ← pre-split last day
2017-04-05 Wed close = 75.91  ← split-effective day; ratio 0.99 vs 4-04
2017-04-06 Thu close = 76.80
```

Expected behavior on a 2:1 split: 4-05 close ≈ 4-04 close × 0.5 ≈
$38. Observed: 4-05 ≈ 4-04 (no halving). **Polygon 1m's TJX data
across 2017-04-05 is missing one split-adjustment**. The cascade at
read time then yields an adjusted curve with a 2x discontinuity at
the split day:

```
TJX adjusted=True via BarStore.load post-rebuild:
  2017-04-04 adjusted = 76.70 × 0.5 = 38.35  (correct)
  2017-04-05 adjusted = 75.91 × 1.0 = 75.91  (WRONG, should ≈ 38)
  2017-04-06 adjusted = 76.80 × 1.0 = 76.80  (WRONG, should ≈ 38)
```

The 5 other split crossings spot-checked (TSLA 2020-08-31 5:1, GOOGL
2022-07-18 20:1, NVDA 2024-06-10 10:1, AAPL 2020-08-31 4:1, LRCX
2024-10-03 10:1) all show polygon 1m correctly at contemporaneous
raw scale. **Only TJX exhibits this pattern.** Round-2 §2.4.1 did
not include TJX in the sample, so this was first surfaced here.

Hypothesis: TJX has the most splits in the universe (1998 / 2000 /
2002 / 2012 / 2015 / 2017 = 6 splits), and polygon's flat-file
generation may have an edge case in cumulative split application.

### Disposition (per user no-fallback rule)

- **Not a step 3b blocker.** Daily rebuild is otherwise correct.
- TJX adjusted-close discontinuity at 2017-04-05 is a known issue
  documented here. **Add TJX to watch sidecar manually as a
  follow-up** (see §"Open follow-ups" below).
- TJX is not a Cand-2 / RCMv1 frozen-spec holding, so step 4 paper
  drift cells over 2022-H2 + 2024 should not be materially affected.
- Per user "no fallback" rule, we do NOT patch TJX with yfinance. A
  proper fix is upstream (re-pull polygon 1m TJX with explicit
  split-cascade, OR re-derive TJX 1m from a different source).
  Belongs to a future "polygon 1m hygiene audit" workstream, not
  in scope here.

---

## Open follow-ups (NOT step 3b blockers)

1. **Split-crossing scale health check.** Programmatic audit: for
   every (symbol, splits.parquet entry), compare `polygon_1m_close`
   on `split_date − 1` vs `split_date` against the expected
   `split_factor`. Flag any symbol with ratio ≠ split_factor at any
   split crossing. TJX is the known offender; this audit checks
   universe-wide. ~30-line script; out of scope for step 3b.

2. **TJX added to data_quality_watch.parquet manually.** Either via
   a one-line patch to the watch sidecar at this commit, or via the
   future split-crossing audit (item 1) which would auto-flag it.

3. **Universe hardcode → config sweep.** Parking-lot item per user
   request earlier this round.

---

## What this unblocks

Step 4 (baseline + 4 paper cells re-run) is the immediate next item.
Expected:
- `data/baseline/latest.json` rebuilds with new test counts and
  pinned daily store hash.
- 4 paper drift cells (2024 + 2022-H2 × RCMv1 + Cand-2) re-run
  via `scripts/run_paper_candidate.py` + `paper_drift_report.py`.
- Drift expected = 0 bps (M11 parity holds; aggregator is
  deterministic).
- Final NAVs WILL move because: (a) +1d offset rows now align to
  real dates, (b) thin_data days enter cross-sectional rebalance
  panel that previously had different scale, (c) some watch-list
  names lose ~50%+ of their daily rows.

---

## Artifacts

**Code**: `dev/scripts/data_integrity/rebuild_daily.py` (this commit).
**Data sidecars**: gitignored at `data/ref/*.parquet` (3 files).
**Daily parquet**: gitignored at `data/daily/*.parquet` (58 written).
**Tests**: 27/27 daily-aggregator tests pass; full pytest pending
verification post-step-4 (some tests pin specific daily values
that may shift).
