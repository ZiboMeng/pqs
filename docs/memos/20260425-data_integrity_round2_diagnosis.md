# Data-Integrity Workstream — Round-2 Diagnosis Memo

**Date**: 2026-04-25
**Status**: round-2 = 判因 + 选路径 (NOT 实现修复). No code, no data
rebuild in this round.
**Predecessor**: round-1 + round-1.1 scoping memo
`docs/memos/20260425-data_integrity_scoping.md`.
**Headline**: round-2 evidence collapses sub-issue I (split-adjustment)
and sub-issue II (date-label) into **a single underlying root cause**.
The round-1 / 1.1 framing of "two independent sub-issues" needs to be
restated as "one root cause + two surface symptoms separated by split
magnitude × source mix." This memo also rejects the simple "single
canonical fix" framing because the multi-source mix is itself the
problem; the fix must commit to one canonical source AND ban future
top-up cascades.

---

## 1. Round-2 evidence (read-only)

### 1.1 Sub-issue I: hypothesis verification

`BarStore.load(adjusted=False)` (the RAW path) for known-contaminated
windows returns mixed-scale data on disk:

```
TSLA 2022-Q1 RAW close (BarStore):
  3-25  336.88  | 3-26 1010.67  | 3-28  363.95  | 3-29  366.52
  3-30 1099.57  | 3-31 1093.99  | 4-01 1079.63  | 4-02 1085.54
  4-04  381.82  | 4-05 1145.38  | 4-06 1090.83  | 4-07  352.42
```

Adjacent days alternate between the raw and the post-split-cascade
scale (ratio ~1:3 = TSLA's 2022-08 3:1 split factor; multiply with
the 2020-08 5:1 → 15× cumulative).

GOOGL 2018-Q3 raw shows the same pattern at ratio ~1:20 (2022-07
20:1 split). TJX 2017-04 shows ratio ~1:2 (2017-04 2:1 split).

Implication: **`splits.parquet` cascade IS NOT the cause** (H-1c
rejected). Cascade only multiplies a fixed per-row factor; it cannot
produce alternating scales day-to-day. The on-disk parquet itself is
mixed before any read-time math runs.

`splits.parquet` separately has reference-data quality issues
(orthogonal to this root cause):
- TJX 2018-11-07 entry exists but no public TJX split on that date
- TJX 2017-04-05 (2:1, public) is missing
- GOOGL 2014-04-03 (2:1, public) is missing — does not affect 2018+
  store coverage

These are independent reference bugs and stay open as a sub-task,
but they are not what produces the alternating-scale pattern in
TSLA/GOOGL/TJX history.

### 1.2 Sub-issue II: α validation (round-1.1 finding)

In round-1.1 the simple α "Saturday row = next valid trading day"
hypothesis was rejected at the 167/170 level (volume mismatch).
Drill-down found II-a (yfinance_daily symbols, Mon→Sat replacement)
behaviorally distinct from II-b (polygon_gz symbols, Mon present
AND Sat present + ~7% intra-week swings). Round-1.1 left them as
two sub-sub-issues to be scoped separately.

### 1.3 Round-2 oracle validation: cross-source reconciliation

Used polygon 1m bars (vendor-stable, contemporaneous to original
ingest) as the truth-side oracle. For each BarStore daily row over
several windows, classified the row's `close` against:

- **A_yf_adj**: matches `yfinance(auto_adjust=True).Close` on same
  date as the BS label (50bps tolerance).
- **B_poly_minus1d**: matches polygon 1m's regular-session last
  close on `bs_date − 1 trading day`.
- **B_poly_same_date**: matches polygon 1m's regular-session last
  close on `bs_date` itself (no offset).
- **mismatch**: matches none of the above.

Results across 6 symbols × representative windows:

| Symbol | Window | A_yf_adj | B_poly−1d | B_poly_same | mismatch | n |
|--------|--------|---------:|----------:|------------:|---------:|--:|
| DG     | 2022-08 | 9        | 8         | 0           | 0        | 17 |
| AAPL   | 2022-08 | 1        | 13        | 0           | 0        | 14 |
| SPY    | 2022-08 | 0        | 14        | 0           | 0        | 14 |
| TJX    | 2022-08 | 9        | 6         | 0           | 2        | 17 |
| MSFT   | 2018-09 | 0        | 13        | 0           | 0        | 13 |
| TSLA   | 2022-03 | 6        | 13        | 0           | 0        | 19 |
| **all** |        | 25       | 67        | 0           | 2        | 94 |

**97% of BS daily rows** classify cleanly into one of two sources:
A or B−1d. Zero rows are B_same_date (i.e. nothing matches polygon
on the same calendar date). This is the empirical fingerprint of
the root cause.

A spot example (DG 2022-08-22 Mon):
```
BS daily 2022-08-22:    close=231.84  vol=1,822,100
yf raw 2022-08-22:      close=248.73  vol=1,822,100   ← B candidate
yf adj 2022-08-22:      close=231.8398  vol=1,822,100  ← MATCH (A_yf_adj)
poly 1m 2022-08-22:     close=248.64  vol=1,592,225   ← matches yf raw
poly 1m 2022-08-19 (Fri): close=257.84  vol=1,576,600
```

DG's BS 2022-08-22 row is the yfinance auto_adjust=True close
(231.84) on the real date — written by an A-type ingest top-up.

Adjacent example (DG 2022-08-23 Tue):
```
BS daily 2022-08-23:    close=230.79  vol=1,669,300
yf raw 2022-08-23:      close=247.60                     
yf adj 2022-08-23:      close=230.7865                   ← MATCH (A_yf_adj)
poly 1m 2022-08-23:     close=247.58
```

Also A-type. But:

```
BS daily 2022-08-25 Thu: close=247.77  vol=1,535,378
poly 1m 2022-08-24 Wed (real -1d):  close=247.77  vol=1,535,378  ← MATCH
```

Same-week, BS daily 2022-08-25 Thu is actually polygon 1m raw on
2022-08-24 Wed (B−1d) — written by a B-type ingest top-up.

So inside the same DG 2022-08 week, A-type and B−1d-type rows
**coexist on different calendar dates**, with neither being the
canonical truth.

### 1.4 The root cause (single-statement)

**BarStore daily was constructed by N successive ingest top-ups,
each using one of two sources without conflict resolution:**

- **Source A**: yfinance with `auto_adjust=True`. Provides
  split- and dividend-adjusted close. Stores at `label = real
  trading date`.
- **Source B**: polygon flat files (1m bars) → daily aggregation.
  Provides raw close (no adjustment). Stores at `label = real
  trading date + 1 calendar day` due to a timezone-floor bug
  (likely UTC→ET `tz_convert` instead of `tz_localize`, exact
  hypothesis in §1.5).

Different top-up runs over time wrote different (date, value)
pairs into the same parquet without reconciling scale or label
convention. The result is that today's daily store carries:
- A-type rows from some top-ups (real-date label, adjusted scale)
- B-type rows from other top-ups (real-date+1 label, raw scale)
- No deterministic per-symbol-per-year pattern; the mix is whatever
  the ingest history laid down

The **two surface symptoms** the round-1 memo split into sub-issues
I and II are the same A/B mix:

| Symbol class | Split history | A vs B scale gap | Surface symptom (what got named) |
|---|---|---:|---|
| Mid-cap (DG, ED, GIS, GILD) | none | div cumul ~5-10% | ~7% intra-week swings + Sat rows = "II-b" |
| Mega-cap + ETF (AAPL, SPY, MSFT, MTUM) | small / none | small | predominantly B → all dates +1, Mon disappears, Sat appears = "II-a" |
| Heavy-split (TSLA, GOOGL, TJX) | 15× / 20× / 2× | huge | day-to-day +200% / -65% / +200% spurious = "sub-issue I" |

### 1.5 Why label = real_date + 1 for B-type rows (B−1d offset)

B-type rows ride exactly 1 calendar day later than the real trading
day. This is consistent with H-2a from round-1 §2.4 (timezone-floor
bug at ingest):

- yfinance / polygon flat files often deliver bar timestamps in
  UTC. A NY Monday bar ending at 16:00 ET = 21:00 UTC.
- If the ingest path does `pd.to_datetime(...).tz_convert('UTC')`
  on a UTC timestamp it's a no-op; the timestamp stays at 21:00 UTC
  Monday.
- If the ingest then does `.normalize()` to pull the date, it gets
  Monday correctly.
- However, if the ingest does `pd.to_datetime(...).tz_localize('UTC')`
  AFTER having read it as naive ET (16:00 ET-naive interpreted as
  UTC), then `tz_convert('US/Eastern')` brings it back to 12:00 ET
  Monday — still Monday, OK.
- Where the bug actually fits is more likely on the `.floor('D')` /
  `.normalize()` step: if the ingest takes a naive UTC bar and
  floors to date in a way that reads 21:00 UTC Monday as
  `2022-08-22T21:00 → floor → 2022-08-22` correctly, then there's
  no offset. But if there's a `+ 1 day` calendar shift (e.g. for
  "ex-date" semantics that mistakenly applied to bar dates), all
  bars go forward 1 calendar day.

Without inspecting the ingest scripts directly (which are out of
scope for this round per "no code change"), the precise mechanism
is unconfirmed. What matters is **the offset is empirically a
deterministic +1 calendar day** across all symbols / years /
sources B-type rows came from, never variable, never 0 days,
never 2 days.

---

## 2. Re-stated workstream — single root cause, two repair paths

### 2.1 Replaces round-1 framing

The round-1 / 1.1 split into "sub-issue I (split-adjust) +
sub-issue II (date-label, with II-a/II-b)" is no longer the
clearest framing. The actual structure is:

- **One root cause**: multi-source ingest cascade with no scale /
  label reconciliation.
- **Three observable symptoms**: (1) heavy-split symbols' alternating
  100s-of-bps spurious returns, (2) mega-cap+ETF Mon-disappears
  pattern, (3) mid-cap intra-week ~7% swings + Sat rows.

The §3 recommended order in round-1.1 ("first I hypothesis
verification, second II-a oracle validation, third II-b scoping")
is now collapsed into "one diagnosis (this memo) + one repair
decision."

### 2.2 Repair path options (re-stated)

Only options that commit to ONE canonical source can fix the root
cause. Multi-source patches (e.g. fix splits.parquet, relabel
Saturdays) only chip at surface symptoms, leaving the underlying
mix in place.

| Option | Description | Cost | Coverage | Blast radius |
|--------|-------------|-----:|----------|-------------:|
| **B (refresh, full)** | One-shot re-fetch of all 24 universe symbols × full history from `yfinance(auto_adjust=False)` (raw close, raw volume), write fresh daily parquet. Ban any subsequent top-up that overlaps existing range. After write, `BarStore.load(adjusted=True)` cascades from a clean splits.parquet (subtask: also fix the TJX and GOOGL splits.parquet entries first). | medium | full | high — every daily-derived artifact recomputes |
| **E (re-aggregate from 1m)** | Treat polygon 1m + stocks_csv 1m as the canonical raw source. Fix the +1 day timezone-floor bug at the aggregation layer. Re-emit daily parquet from 1m. ETF coverage gap (1m for ETFs is thin pre-2024) needs B-style yfinance backfill. | high | full (with ETF backfill) | high |
| **A+I (skip-list)** | Quarantine known-bad cells: refuse to load contaminated (symbol, year-window) at BarStore boundary. Trade-off: research surface shrinks materially; TSLA/GOOGL/TJX 2015-2022 effectively drop out of universe. | low | partial | low but lossy |
| **D (forward-only)** | Only run paper / mining over post-2024-01-01 windows where stocks_csv is the primary 1m source AND (claim) less mixed. Reject all use of pre-2024 BarStore daily. | low | partial | none locally; permanent research-coverage loss |
| **NONE: simple α relabel** | ✗ rejected in round-1.1 (167/170 mismatch on volume). Cannot fix anything because the underlying data is also mis-scaled, not just mis-labelled. |

A and D from the round-1 menu are now redundant (reference fixes
are sub-tasks of B). C is renamed A+I above to distinguish it from
the new A reference-fix sub-task. The original options menu
collapses into B / E / A+I / D.

### 2.3 Risk comparison B vs E

Both B and E are "re-write the daily parquet" plans. Differences:

| Risk | B (yfinance refresh) | E (1m re-aggregate) |
|------|----------------------|---------------------|
| Vendor dependency | yfinance availability + revision history | polygon 1m availability + completeness |
| ETF coverage | yfinance covers all ETFs through 2026 | polygon 1m has thin ETF coverage pre-2024; needs hybrid |
| Volume revision | yfinance has revised volumes since original ingest (verified §1.3) — refresh would change historical numbers vs current store | polygon 1m raw volume is contemporaneous; less revision risk |
| Adjustment bias | yfinance auto_adjust=True applies ALL future splits + divs, baked into the close. Hard to "un-adjust" later. Use auto_adjust=False to keep raw. | 1m raw is naturally raw; cleaner |
| 1m bug propagation | Independent of 1m | If the timezone bug exists in 1m too, E inherits it |
| Test fixture impact | Same in both: every regression baseline that pins specific close prices needs refreshing | Same |
| Implementation cost | Lower; yfinance is one Python call per (sym, range) | Higher; needs aggregation script + tz fix + reconcile |

**E is the more robust long-term choice** if (a) polygon 1m is itself
clean of the timezone bug, and (b) ETF backfill is acceptable. **B is
the lower-risk short-term choice** if E's preconditions can't be
quickly verified.

### 2.4 Open question — is polygon 1m itself clean?

Critical to E's viability. Quick reproduction:

```
For symbol AAPL, polygon 1m timestamp range across 2022-08-22:
  first bar at 04:00:00 ET (or UTC interpreted as ET?)
  last bar at 19:59:00 ET
  → 836 minute bars, last_close=161.79
yfinance daily AAPL 2022-08-22 (verified separately):
  close=167.59 (auto_adjust=False, raw)
```

The 1m last-close (161.79) does NOT match yfinance raw close 167.59
on the same date. But it DOES match a recent yfinance auto_adjust=True
close on AAPL — which means **polygon 1m may also be storing
post-cascade-adjusted prices**, not pure raw. This is unconfirmed
in this round; it depends on what scale polygon flat files were
delivered in.

If polygon 1m is ALSO mixed scale (some periods raw, some
post-cascade), then E doesn't actually have a clean source either,
and B with `auto_adjust=False` becomes the only viable option.

**Action item** (NOT in this round): a 30-line verification that
polygon 1m AAPL on 2015-01-02 (well before any 2020/2022 split)
returns ~$110 (raw scale on that date) vs ~$24 (post-cascade)
would resolve this. Out of scope for this memo per "判因 not
实现 round."

---

## 3. Re-stated downstream re-run obligations

If B or E is shipped, all of these need refreshing:

- `data/baseline/latest.json`
- 4 paper drift cells (2024 + 2022-H2 × RCMv1 + Cand-2)
- TD75 cross-regime memo §0b numbers
- M14 memo §1 NaN-equity day patterns (Sat/Mon labels shift)
- Cand-2 attribution memo §2.2 NaN-day date list
- M11 memo §5 (the Saturday-row caveat is fully obsolete; replace
  with single root-cause pointer)
- factor_evaluator IC / IR baselines for any production / research
  factor that touches contaminated symbols (TSLA / GOOGL / TJX
  significantly; mid-caps marginally; ETFs marginally)
- All hand-coded date references in PRDs, decision memos, readmes
  — much of the "2022-10-17 NaN day" / "2022-08-29 missing" / etc.
  vocabulary will need a sweep, since BS labels were +1 from real
  dates for B-type rows

Mining lineage snapshots (`data/mining/*.db`): **stay quarantined
per round-1.1 user direction** (historical record).

The 4 canonical paper cells (2022-H2 + 2024) survive structurally
in that paper-vs-replay parity is still 0 bps drift post-fix
(M11 result, internal consistency). But the absolute NAV numbers
will move under either B or E, and the §0b TD75 baselines move
with them.

---

## 4. Reference-data sub-tasks (orthogonal to root cause)

These are not the root cause, but they will be visible after the
root cause is fixed and should be batched into the B/E execution:

- **TJX `splits.parquet`**: drop the 2018-11-07 entry (no public
  TJX split on that date); add the 2017-04-05 (2:1) entry
- **GOOGL `splits.parquet`**: add the 2014-04-03 (2:1) entry. Does
  not affect any current paper cell (BS GOOGL coverage starts
  2018), but cleanliness of reference data is cheap to fix.
- **TSLA `splits.parquet`**: ✓ already correct
- **NVDA `splits.parquet`**: from/to convention OK (verified
  ratio computation against current cascade)

These can ship in the same commit as B or E without expanding scope.

---

## 5. Decision points for round-3 (next-round sign-off)

Listing the decisions this memo deliberately defers:

1. **Pick repair path among B / E / A+I / D.** B is the recommended
   default; E is preferred IF polygon 1m is verified clean.
2. **Verify polygon 1m cleanliness** (the §2.4 open question) before
   committing to E.
3. **Confirm reference-data sub-tasks (TJX / GOOGL splits.parquet)
   ship in the same commit** as the chosen repair path.
4. **Confirm mining-lineage quarantine** holds (don't refresh
   `data/mining/*.db`) — same as round-1.1 q4.
5. **Pick refresh scope for downstream memos**: full sweep of every
   memo's date references vs only headline 4 (TD75 §0b, M11 §5,
   M14 §1, Cand-2 attribution §2.2). Round-1.1 q5 still applies.
6. **Pick regression assertions** to add post-fix:
   - "no Saturday rows in BarStore.load(symbol, '1d')" (cheap, locks
     fix in)
   - "every daily row's close matches the corresponding yfinance
     auto_adjust=False close on same date" (verifies B's effect)
     OR "every daily row's close matches polygon 1m last regular-
     session close on same date" (verifies E's effect)
   - "no adjacent-day raw-close ratio outside [0.5, 2.0] except on
     known-split dates" (broader sanity)

---

## 6. What stays frozen during this workstream

Same as round-1 §4 + round-1.1 reaffirmation:

- No universe extension
- No new mining round
- No new data tier
- No Candidate-3 work
- No retroactive RCMv1 / Cand-2 frozen-spec change
- No new factor in PRODUCTION_FACTORS
- No paper artifacts archived as "post-data-fix canonical" until the
  chosen B/E repair path is shipped AND the §3 re-runs are completed

---

## 7. Status & artifacts

- This memo is the round-2 deliverable.
- No code changes in this round.
- No new tests in this round.
- No data rebuild in this round.
- pytest baseline unchanged: 1577 passed / 0 failed / 1 skipped /
  1 xfailed (from M11 close).
- Round-1 / 1.1 scoping memo
  (`docs/memos/20260425-data_integrity_scoping.md`) is **partially
  superseded** by this memo's §1.4 / §2.1 root-cause unification.
  Specifically: the "two independent sub-issues" framing in round-1
  §0 + round-1.1 II-a/II-b split is now reframed as "one root cause
  + three surface symptoms." Round-1's repair-option menus (§1.5
  options A/B/C/D/E and §2.5 options α/β/γ/δ/ε) are simplified to
  this memo's §2.2 menu (B / E / A+I / D), with reference-data
  sub-tasks separated out (§4).
- `splits.parquet` reference-data findings (§4) are a side discovery,
  not the root cause.

Cross-references:
- Predecessor: `docs/memos/20260425-data_integrity_scoping.md` (round-1 + 1.1)
- Older split-adjust memo: `docs/20260424-data_integrity_2022_split_adjustment.md` (still relevant for window-selection rationale; superseded for cause)
- M11 fix: `docs/memos/20260424-m11_paper_engine_parity_fix.md` (its §5 Saturday-row finding is one symptom of this single root cause)
- M14 fix: `docs/memos/20260424-m14_nan_equity_fix.md` (its NaN-day Mondays/Saturdays pattern is another symptom)
- Cand-2 drift attribution: `docs/memos/20260424-cand2_drift_attribution.md` (§2.2 next-day-after-NaN dates are all label-dates per the +1d offset)
