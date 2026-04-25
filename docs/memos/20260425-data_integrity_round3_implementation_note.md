# Data-Integrity Round-3 — Implementation Note

**Date**: 2026-04-25
**Status**: contract for round-3 execution. Path = E (re-aggregate
daily from polygon 1m). Contracts pinned below; no long argumentation
— see round-2 diagnosis memo for evidence.

---

## 1. Canonical source

- **`data/intraday/1m/<SYMBOL>.parquet`** is the single canonical
  raw source for daily.
- yfinance daily / yfinance auto_adjust=True / current daily parquet
  are NOT canonical and will be REPLACED.
- No further top-up cascade into the daily store after E ships.
  Daily store is only ever rebuilt from 1m, never partially patched.

## 2. Daily aggregation contract

- **Label** = real ET trading day (`bar.timestamp.date()` where bar
  timestamps are ET-naive in 1m parquet, verified round-2 §2.4.2).
- **Close convention**: **15:59 ET 1m bar's close**.
  - Use the bar whose timestamp's HH:MM == 15:59. If absent, mark
    the day as incomplete (see §3).
  - Do NOT use 16:00, 16:05, after-hours-last, or any other tie-break.
- **Open**: 09:30 ET 1m bar's open. If absent → incomplete.
- **High**: max over 09:30 ≤ HH:MM ≤ 15:59 ET 1m bars.
- **Low**:  min over 09:30 ≤ HH:MM ≤ 15:59 ET 1m bars.
- **Volume**: sum over 09:30 ≤ HH:MM ≤ 15:59 ET 1m bars (regular
  session only; pre/post excluded by default).
- **Adjustment**: daily parquet stores RAW (no cascade). Cascade
  applied at READ time by `BarStore.load(adjusted=True)` against
  `data/ref/splits.parquet`. This matches the documented design.

## 3. Incomplete-1m day policy

- A day is "complete" iff both 09:30 and 15:59 ET 1m bars are present
  AND total regular-session bar count ≥ N_min (TBD; suggest 350 as
  starting threshold ≈ 90% of full session).
- Incomplete days:
  - On the **partial-day whitelist** (NYSE half-sessions: day-after-
    Thanksgiving, Christmas Eve, July 3 etc. when applicable):
    accept what 1m has; record `partial_day=True` in a sidecar.
  - **NOT on the whitelist**: **flag and quarantine, do NOT silently
    fall back** to yfinance / any other source. Quarantined days
    appear in a `data/ref/incomplete_days.parquet` audit log; daily
    parquet has no row for that (symbol, date).
- The audit log is shipped alongside E so future debugging knows
  exactly which days were dropped vs accepted-as-partial.

## 4. ETF 2024+ trades_backfill re-confirmation

- Before E ships: re-confirm `trades_backfill` 1m bars for the 8
  universe ETFs (SPY/QQQ/SOXL/TQQQ/MTUM/QUAL/SLV/XLRE) over 2024-01
  through 2026-04 produce sane regular-session bar counts (§2.4.3
  showed 200-1400 bars/day, but per-day audit before reuse).
- Audit lives in the same incomplete-days log (§3).

## 5. `splits.parquet` reference sub-tasks (ship in same commit)

- **TJX**: add `2017-04-05` (2:1 split, public record); remove the
  `2018-11-07` entry (no public TJX split that date).
- **GOOGL**: add `2014-04-03` (2:1 split, public record). Does not
  affect current paper cells but cleans the reference.
- No other reference changes in this batch.

## 6. Post-fix rerun / refresh list

After E + splits.parquet sub-tasks ship:

- `data/baseline/latest.json` → rebuild via
  `dev/scripts/baseline/build_research_baseline_snapshot.py
  --run-tests`.
- 4 paper drift cells (2024 + 2022-H2 × RCMv1 + Cand-2): re-run
  `scripts/run_paper_candidate.py` + `scripts/paper_drift_report.py`;
  expected drift = 0 bps (M11 still holds), final NAVs WILL move.
- **Headline-4 docs full refresh**:
  - `docs/20260424-parallel_paper_2022h2_checkpoint_75d.md` §0b
  - `docs/memos/20260424-m11_paper_engine_parity_fix.md` §5
  - `docs/memos/20260424-m14_nan_equity_fix.md` §1
  - `docs/memos/20260424-cand2_drift_attribution.md` §2.2
- **All-repo date-reference caveat sweep**: identify every memo /
  PRD / readme that cites a specific BS-label date (e.g.
  "2022-08-27", "2022-10-17 NaN day"). For each:
  - if the date materially backs a numerical claim that this batch
    invalidates → refresh inline,
  - otherwise append a one-line caveat noting that the date was a
    BS-label and post-E it has shifted to the real-exchange date.
- **Mining lineage**: `data/mining/*.db` STAYS quarantined per
  round-1.1. Do not refresh.

## 7. Three regression assertions (added under tests/)

- **R-1**: `no Saturday/Sunday rows` in `BarStore.load(symbol, '1d')`
  for any universe symbol.
- **R-2**: `daily row close ≈ polygon 1m regular-session last close
  on the same real date` (50 bps tolerance) for any universe symbol
  × representative dates. This is E's core contract.
- **R-3**: `no adjacent-day raw-close ratio outside [0.5, 2.0]` on
  `BarStore.load(symbol, '1d', adjusted=False)`, **except on dates
  in the splits.parquet known-splits whitelist** (post-§5 cleanup).
  Whitelist drives explicit allow-list; do NOT relax to "ratio
  outside 0.4-2.5" or other knob loosening when partial days fail.

## 8. Standing freeze (continues through round-3)

- No universe extension
- No new mining round
- No new data tier
- No Candidate-3 work
- No retroactive RCMv1 / Cand-2 frozen-spec change
- No new factor in PRODUCTION_FACTORS
- **No OOS-framework work** until E + rerun + headline-4 refresh
  + sweep all complete

---

## 9. Round-3 commit-flow shape (suggested, not contractual)

1. E aggregator + +1d offset fix + 3 regression assertions →
   one commit.
2. splits.parquet sub-tasks → one commit (same batch).
3. Daily parquet rebuild + incomplete-days audit log → one commit.
4. Baseline + 4 paper cells re-run → one commit.
5. Headline-4 docs refresh → one commit (or 4 small).
6. All-repo date-reference sweep → one commit.

(One bigger or one smaller is fine; the structure exists so each
step can be reviewed without unwrapping the rest.)

---

This note is the round-3 contract. Implementation begins in the next
turn against this contract.
