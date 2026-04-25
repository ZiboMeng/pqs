# Round-3 Step 3a Audit Summary (READ-ONLY DRY RUN)

**Date**: 2026-04-25
**Status**: dry-run audit completed; **no parquet writes**. This is
the gate before step 3b (actual daily parquet rebuild).
**Universe**: 59 symbols from `config/universe.yaml::seed_pool`.
**Range**: 2015-01-02 .. 2026-04-16 (full 1m parquet coverage).
**Aggregator contract**: per round-3 implementation note §2 + §3.
**N_min threshold**: 350 (~90% of full 390-min session).

**TL;DR — multiple stop signals, NOT yet ready to write.** 9.84%
of records quarantined (15,535 of 157,856), with structural
concerns on BRK-B / TKO / BKNG / SOXL and on the canonical 2024
window. Recommend N_min recalibration + per-symbol exception list
before step 3b. See §9 for the punch list.

---

## G1 Overall

|  | count | % |
|---|---:|---:|
| Total `(symbol, day)` records | 157,856 | 100.00% |
| **complete**     | 141,090 | **89.38%** |
| **partial** (NYSE half-session whitelist) | 1,231 | 0.78% |
| **quarantined**  | 15,535  | **9.84%** |

Quarantined breakdown:
- `q_low_bars` (n_bars < 350 on a full-session day): 12,081 (78% of quarantined, 7.65% of total)
- `q_no_open` (missing 09:30 ET 1m bar): 3,435 (2.18% of total)
- `q_no_close` (missing 15:59 ET 1m bar): 4,412 (2.79% of total)

The `q_low_bars` bucket dominates. **Median n_bars in this bucket is
in the 319-349 range** (just below threshold) — this is N_min
calibration territory, not pathological data.

---

## G2 Per-symbol distribution

### G2.1 Top-10 dirtiest

| symbol | type | complete | partial | quarantined | q_pct |
|--------|------|---------:|--------:|------------:|------:|
| **BKNG** | eq | 181  | 18 | **1847** | **90.27%** |
| **TKO**  | eq | 205  |  6 | **440**  | **67.59%** |
| **CMG**  | eq | 936  | 17 | **1886** | **66.43%** |
| **ISRG** | eq | 1337 | 23 | 1479     | 52.10% |
| **SOXL** | ETF| 1768 | 22 | **1048** | **36.93%** |
| ACGL     | eq | 1801 | 23 | 1015     | 35.75% |
| MCK      | eq | 1827 | 22 | 990      | 34.87% |
| TT       | eq | 1000 |  8 | 532      | 34.55% |
| APD      | eq | 1976 | 22 | 841      | 29.62% |
| KLAC     | eq | 2098 | 23 | 718      | 25.29% |

### G2.2 Cleanest 10 (mostly 0% quarantine)

SPY / QQQ / GLD / AAPL / MSFT / AMZN / GILD / NVDA / MU all sit at
**~2816 complete + 23 partial + 0 quarantined** = clean.

**BRK-B is BUG-FLAG**: complete=0 / partial=0 / quarantined=0.
**No 1m data at all** for BRK-B in the parquet store. Aggregator
silently emits empty for it.

---

## G3 Per-year distribution

| year | complete | partial | quarantined | total | q_pct |
|------|---------:|--------:|------------:|------:|------:|
| 2015 | 11,713 | 104 | 1,539 | 13,356 | 11.52% |
| 2016 | 12,162 |  53 | 1,141 | 13,356 |  8.54% |
| 2017 | 11,975 | 104 | 1,224 | 13,303 |  9.20% |
| 2018 | 12,233 | 156 | 1,357 | 13,746 |  9.87% |
| 2019 | 12,361 | 159 | 1,340 | 13,860 |  9.67% |
| 2020 | 13,054 | 110 |   964 | 14,128 |  6.82% |
| 2021 | 12,727 |  57 | 1,457 | 14,241 | 10.23% |
| 2022 | 13,253 |  55 |   909 | 14,217 |  6.39% |
| 2023 | 12,538 | 111 | 1,678 | 14,327 | 11.71% |
| **2024** | 12,219 | 174 | **2,223** | 14,616 | **15.21%** |
| 2025 | 12,847 | 148 | 1,482 | 14,477 | 10.24% |
| 2026 |  4,008 |   0 |   221 |  4,229 |  5.23% |

**2024 is the dirtiest year (15.21% q_pct)** — coincides with the
stocks_csv source switch boundary (2024-01-01). Worth a closer look.

---

## G4 ETF subset (5 symbols)

| ETF | complete | partial | quarantined | q_pct | first | last |
|-----|---------:|--------:|------------:|------:|-------|------|
| SPY  | 2,815 | 23 |    0 |  0.0% | 2015-01-02 | 2026-04-16 |
| QQQ  | 2,815 | 23 |    0 |  0.0% | 2015-01-02 | 2026-04-16 |
| GLD  | 2,815 | 23 |    0 |  0.0% | 2015-01-02 | 2026-04-16 |
| TQQQ | 2,805 | 23 |   10 |  0.4% | 2015-01-02 | 2026-04-16 |
| **SOXL** | 1,768 | 22 | **1,048** | **36.93%** | 2015-01-02 | 2026-04-16 |

**SOXL anomaly**: round-2 §2.4.3 sampled SOXL at 200-1400 bars/day
across years and concluded ETF coverage was sufficient. Per-day
audit reveals SOXL has 1,048 quarantined days — likely lower-volume
days with sparse 1m bars. **This contradicts the round-2 "ETF
coverage sufficient" assertion** and needs explicit handling before
step 3b.

(Note: round-3 implementation note §1 ETF list included MTUM / QUAL
/ SLV / XLRE, but `config/universe.yaml::seed_pool` does NOT contain
them. The aggregator audit only covered the 5 ETFs in seed_pool.
The other 4 ETFs are referenced elsewhere in the codebase via factor
families. **Not a blocker for step 3b**, but worth checking before
the universe-config-cleanup follow-up.)

---

## G5 Canonical paper windows

### 2022-H2 bear (2022-08-26 .. 2022-12-15)

| bucket | count |
|--------|------:|
| complete    | 4,066 |
| partial     |    55 |
| quarantined |   325 |

Top quarantined symbols: BKNG (77), CMG (77), MCK (33), PWR (32),
TT (21), APD (20), LLY (14), CLX (10).

**~7.4% of `(symbol, day)` records in this window are quarantined.**

### 2024 up-tape (2024-01-02 .. 2024-04-19)

| bucket | count |
|--------|------:|
| complete    | 3,819 |
| partial     |     0 |
| quarantined |   589 |

Top quarantined symbols: BKNG (76), CMG (76), MCK (71), KLAC (59),
LRCX (52), TT (52), PWR (47), TKO (38).

**~13.3% of `(symbol, day)` records in this window are quarantined.**

This is **a meaningful drop in available cross-sectional coverage**
on the canonical paper windows. Cand-2 + RCMv1 paper runs do NOT
materially hold BKNG / CMG / MCK / TKO etc. as far as we know
(top-10 holdings tend to be SPY / QQQ / mega-cap). The drift cells'
final NAVs are therefore unlikely to swing dramatically, but
**universe-wide cross-sectional factor metrics WILL change** — IC
calculations on the 2024 window currently exclude no rows; after
step 3b they will exclude ~13%.

---

## G6 Incomplete-day examples

### Quarantined (q_low_bars) — n_bars near threshold

```
GOOGL 2016-12-23  q_low_bars  n_bars=319
GOOGL 2017-11-22  q_low_bars  n_bars=346  (NYE-1, low volume)
GOOGL 2017-12-29  q_low_bars  n_bars=346  (year-end, low volume)
GOOGL 2019-05-22  q_low_bars  n_bars=348
GOOGL 2019-08-20  q_low_bars  n_bars=322
GOOGL 2019-08-21  q_low_bars  n_bars=331
GOOGL 2019-08-22  q_low_bars  n_bars=343
GOOGL 2019-08-28  q_low_bars  n_bars=349
```

**Most are 320-349 bars vs threshold 350.** Looks like upstream 1m
data dropped 30-70 bars on these days, but the days are otherwise
real trading days. Lowering N_min to ~300 would recover most of
these — but then we accept somewhat-thinner 1m days as "complete".

### Partial (NYSE half-session whitelist)

```
SPY 2015-11-27  partial  n_bars=210  (Black Friday)
SPY 2015-12-24  partial  n_bars=210  (Christmas Eve)
SPY 2016-11-25  partial  n_bars=210  (Black Friday)
SPY 2017-07-03  partial  n_bars=210  (July 3)
```

**Half-day whitelist works correctly** (210 bars = 09:30 + 12:59 = 210 minutes).

---

## G7 Bar-count distribution (complete days only)

```
Total complete (sym, day): 141,090
n_bars: min=350  median=390  mean=386  max=390
        10th pct=375  25th=386  75th=390  90th=390
```

Most complete days have the full 390 bars or close to it. The
distribution is heavily concentrated near 390.

`q_low_bars` n_bars range: **[28, 349]** — low end (28) is
genuine "data essentially missing" days; high end (349) is just
below the threshold.

---

## G8 Write-impact estimate

| Metric | Value |
|--------|------:|
| Symbols to (re-)write daily parquet | 58 / 59 (BRK-B has zero) |
| Total rows in fresh daily store | 142,321 |
| Quarantined rows excluded | 15,535 |
| Current daily-store total rows | 173,428 |
| Current Sat/Sun rows (will disappear) | 31,675 |
| **Net row delta (new − current)** | **−31,107** |

The −31,107 row delta is dominated by:
- **31,675 Sat/Sun rows correctly removed** (the +1d offset bug
  artifact).
- **15,535 newly quarantined rows** (real trading days the audit
  would NOT keep).
- **+~16,000 net new clean Mondays** that recover (no longer being
  shifted to Sat).

The net effect: the new store has **fewer rows but cleaner
semantics** — Sat/Sun pollution gone, +1d offset fixed, but ~10%
real-day records dropped to quarantine pending exception handling.

### Per-symbol impact

**Biggest +%delta** (all near zero — the clean group):
```
AAPL / AMZN / SPY / GLD / QQQ / MSFT / NVDA / MU:
  cur=2843, new=2838, delta=-5 (-0.2%)
```
Only −5 rows each — those are the +1d offset rows (Saturdays after
real Fridays at the end of the data range).

**Biggest −%delta** (the worry list):
```
BRK-B : cur=2844 new=    0  delta=-2844  (-100.0%)  ← lost entirely
TKO   : cur=2702 new=  211  delta=-2491   (-92.2%)
BKNG  : cur=2051 new=  199  delta=-1852   (-90.3%)
CMG   : cur=2844 new=  953  delta=-1891   (-66.5%)
TT    : cur=2890 new= 1008  delta=-1882   (-65.1%)
ISRG  : cur=2844 new= 1360  delta=-1484   (-52.2%)
SOXL  : cur=2843 new= 1790  delta=-1053   (-37.0%)
ACGL  : cur=2844 new= 1824  delta=-1020   (-35.9%)
```

These 8 symbols lose 35-100% of their daily rows. Most are because
their 1m data is structurally sparse (high-priced low-volume single
stocks where many minutes have no trades).

---

## 9. Stop signals — punch list before step 3b

These are the items I'd want resolved before writing any daily
parquet:

### 9.1 BRK-B has zero 1m data
**Severity: HIGH**. Can't aggregate something that doesn't exist.
Options:
- (a) Drop BRK-B from the universe (effectively unreachable post-step-3b
  anyway).
- (b) Fall back to yfinance daily for BRK-B as an explicit, single-
  symbol exception (deviates from "no silent fallback" — would be a
  documented per-symbol policy, not silent).
- (c) Backfill BRK-B 1m via trades_backfill / polygon flat files
  (deferred work).

### 9.2 N_min = 350 may be too strict
**Severity: MEDIUM**. The dominant quarantine reason is `q_low_bars`
where the bar count is 320-349 — within 30 bars of threshold.
Lowering N_min to e.g. 300 would re-classify ~70-80% of these as
"complete". Tradeoff: those days have genuinely thinner 1m coverage
and the close at 15:59 is still present.

Options:
- (a) Keep N_min=350, accept ~10% quarantine rate.
- (b) Lower to N_min=300 (~70% of full session). Recovers most
  q_low_bars; still rejects truly-broken days (n_bars < 100).
- (c) Two-tier: accept 300-349 as "complete with thin_data=True"
  flag (sidecar column), keep <300 as quarantine.

### 9.3 BKNG / CMG / TKO / TT chronically sparse
**Severity: MEDIUM**. These four symbols lose 65-100% of rows
regardless of N_min calibration. Likely a structural property of
their 1m parquet (high-priced, less-traded names with persistent
minute gaps).

Options:
- (a) Quarantine and accept reduced coverage.
- (b) Backfill from trades_backfill or yfinance daily for these
  specific symbols (per-symbol exception).
- (c) Re-evaluate whether these should remain in `seed_pool` given
  their structural data thinness.

### 9.4 SOXL anomaly contradicts round-2 §2.4.3
**Severity: MEDIUM**. round-2 §2.4.3 said ETF coverage was
sufficient based on representative-day samples. Full audit shows
SOXL at 36.9% q_pct. Need to revisit the round-2 conclusion.

Options:
- (a) Same N_min calibration as in §9.2 — SOXL's q_low_bars likely
  near threshold too.
- (b) Backfill SOXL from polygon trades or yfinance.

### 9.5 2024 window quarantine = 13.3% of paper-cell records
**Severity: MEDIUM-HIGH**. This window is the canonical 2024 paper
cell. ~13% of `(symbol, day)` records will be excluded from the
post-step-3b store. Drift cells' NAV reproducibility may shift
even if M11 parity still holds.

Options:
- (a) Accept; note in TD75 §0b that 2024 NAV will change post-fix.
- (b) Pause step 3b until §9.2 N_min is decided (because most of
  that 13% is near-threshold q_low_bars).

### 9.6 partial_day count is suspiciously low (1,231 / 158k)
**Severity: LOW**. Expected ~5-10 NYSE half-days per year × 12
years × 59 symbols = ~3,500-7,000 partial rows. Got 1,231. Likely
because many half-days fall before some symbols' 1m data start
date. Verifiable but not blocking.

---

## 10. Recommendation

**Do NOT proceed to step 3b until §9.1 (BRK-B) and §9.2 (N_min) are
decided.** §9.3–§9.5 are also material but can ride on those two
decisions (e.g. if §9.2 lowers N_min, §9.3 / §9.4 / §9.5 numbers
move).

Suggested next-round form:
- 30-line decision memo from user on §9.1 + §9.2 (and indirectly
  §9.3–§9.5).
- After decision, re-run audit-only with adjusted policy (10 min)
  to confirm new numbers.
- THEN step 3b writes daily parquet.

If §9.1 = drop BRK-B + §9.2 = lower N_min to 300, expected post-
adjustment numbers (rough):
- complete: ~155k (was 141k)
- partial:  ~1.2k (unchanged)
- quarantined: ~2k (was 15.5k) ← order-of-magnitude reduction
- BKNG / CMG / TKO / TT may still lose 50%+ — separate decision

---

## 11. Artifacts

- `/tmp/audit_step3a.pkl` — full per-day records (7.4 MB pickle)
- `/tmp/audit_summary.txt` — text version of this memo's stats
- `/tmp/audit_aggregator_v2.py` — audit script (vectorized version)
- No parquet writes; no commits to `data/intraday/`; no commits to
  `data/ref/`.

This memo is the round-3 step 3a deliverable. Step 3b is gated on
user sign-off.
