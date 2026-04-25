# M14 NaN-Equity Fix — Root Cause + Pre/Post Comparison + Residual

**Date**: 2026-04-24
**Trigger**: drift attribution memo
`docs/memos/20260424-cand2_drift_attribution.md` promoted M14 from a
conditional P2 to first-priority blocker. User directive: investigate,
fix, document root-cause path / NaN-equity days before-vs-after / 4
drift cells before-vs-after / residual that needs separate attribution.

This memo closes that loop.

---

## Status update (2026-04-25, post-step-3b)

The data-integrity workstream round-3 step 3b
(`docs/memos/20260425-data_integrity_round3_step3b_complete.md`)
rebuilt `data/daily/<sym>.parquet` from polygon 1m as the single
canonical source. Under the rebuilt store:

- **There are no Sat/Sun-labeled rows** (the +1d offset bug that
  produced "NaN-equity days at Saturdays" is gone)
- **NaN-equity day patterns documented in §1 / §3 below no longer
  exist** under the new store. The "13 / 16 NaN days per cell"
  enumerations were a vocabulary artifact of the bug.
- **Specific dates cited below (e.g. "2022-10-17 Monday NaN day",
  "2022-08-29 missing Mon") are BarStore-label dates from the
  pre-step-3b era**. Under the rebuilt store every real ET trading
  day exists with the correct label and the corresponding "Sat
  pad row" does not exist.

The M14 fix code (`backtest_engine.py` `last_valid_close` fallback)
is still in place and still load-bearing — under the rebuilt store
some symbols (BKNG / CMG / SOXL / etc.) have legitimate quarantine
days where `price_row[sym]` is NaN; the M14 fallback prevents those
from poisoning portfolio_value. The fix is no longer the *primary*
defense (the data is now clean enough that NaN closes are rare),
but it remains a defense-in-depth backstop.

For canonical NAV / drift numbers post-step-3b, see TD75 §0c
(`docs/20260424-parallel_paper_2022h2_checkpoint_75d.md` §0c) and
the step 4 memo
(`docs/memos/20260425-data_integrity_round3_step4_complete.md`).

The §1-§5 narrative below is preserved as the historical
investigation record. Read it as "what we learned in the M14 round
that fed into the data-integrity workstream", not "current state."

---

## 1. Root cause — exact path

**File**: `core/backtest/backtest_engine.py`
**Line range pre-fix**: 262-265
**Code pre-fix**:

```python
portfolio_value = cash + sum(
    shares.get(sym, 0) * price_row.get(sym, 0)
    for sym in shares
)
```

**Bug semantics**: `dict.get(sym, 0)` returns the default `0` ONLY when
the key is **missing** from the dict. When `price_row` is a Pandas
`Series` row (cross-section of the price panel for a single date) that
**has** the column for `sym` but the value is `NaN` (e.g. a held symbol
whose close is missing on that date because the BarStore panel
union-merges symbols with non-aligned calendars), `price_row.get(sym, 0)`
returns the **NaN value**, not the `0` default. The multiplication
`qty * NaN = NaN` propagates to `portfolio_value`, which writes NaN
into `equity_curve` for that day.

**Why it surfaces**: BarStore stores RAW per-symbol parquet, then the
backtest pipeline unions them into a daily panel. Coverage is not 100%
identical across symbols — a few symbols periodically miss specific
dates (often Mondays after off-hours data gaps; some symbols also have
late starts). Any held position in a "missing on this date" symbol
trips the bug.

Verified directly via the BarStore for 2022-10-03 (a Monday hit by all
four 2022 cells): NVDA / TQQQ / SOXL / MU / LRCX absent from the panel
index that date, while GILD / TJX / VICI present. With Cand-2 holding
~10 names and RCMv1 holding ~12 names, the chance of at least one held
name being missing on a given Monday is high — which matches the
observed NaN-equity day counts (12-14 per 95-day window).

**Fix** (lines 262-289 post-fix): walk `shares` explicitly, fall back to
`last_valid_close[sym]` (the same dict the ghost-cleanup logic at
lines 202-206 already maintains) when `price_row[sym]` is NaN or missing
or non-positive. If the symbol never had a valid close (held-but-
never-priced edge case — e.g. position opened on a halt/no-trade day),
treat as `0` — consistent with the ghost-cleanup write-off branch.

```python
portfolio_value = cash
for sym, qty in shares.items():
    p = price_row.get(sym, None)
    p_f = float(p) if p is not None else float("nan")
    if not np.isfinite(p_f) or p_f <= 0:
        p_f = float(last_valid_close.get(sym, 0.0))
    portfolio_value += qty * p_f
```

This fallback mirrors the M14 PRD recommendation in CLAUDE.md
("Forward-fill last-valid price for positions held into a NaN bar").

**Regression tests**: `tests/unit/backtest/test_m14_nan_equity.py` (5
tests). 4/5 fail pre-fix; all 5 pass post-fix. Tests cover headline
NaN-day case, last-valid-close fallback semantics, recovery on next
valid bar, write-off semantics for never-priced positions, and the
production multi-symbol partial-NaN panel pattern.

---

## 2. NaN equity days — pre-fix vs post-fix (4 cells)

| Cell                | NaN-equity days pre | NaN-equity days post |
|---------------------|--------------------:|---------------------:|
| 2024 up-tape RCMv1  | 15 / 91             | **0 / 91**           |
| 2024 up-tape Cand-2 | 13 / 91             | **0 / 91**           |
| 2022 bear  RCMv1    | 28 / 95             | **0 / 95**           |
| 2022 bear  Cand-2   | 25 / 95             | **0 / 95**           |

**Day-of-week pattern of pre-fix NaN days**: dominated by Mondays in
all four cells (the 2024 cells were 11-12/13-15 Mondays; the 2022
cells additionally included Saturday pad rows — see §5 caveat). This
is consistent with weekend/Monday data gaps in the BarStore panel.

**Post-fix**: zero NaN-equity rows in any of the four cells. Mechanism
proven: the headline M14 NaN-bridge artifact is gone.

---

## 3. Drift cells — pre-fix vs post-fix

Drift is the per-day `(paper_NAV - replay_NAV)` in bps, computed by
`scripts/paper_drift_report.py`.

| Cell                | Pre-fix mean abs drift | Pre-fix max | Post-fix mean abs | Post-fix max | NaN→fix net change |
|---------------------|-----------------------:|------------:|------------------:|-------------:|-------------------:|
| 2024 up-tape RCMv1  | 3.60 bps               | 26.02       | 4.43              | 20.86        | + 0.83 bps         |
| 2024 up-tape Cand-2 | 24.08 bps              | 174.89      | **59.77**         | 172.02       | +35.69 bps         |
| 2022 bear  RCMv1    | 2.69 bps               | 7.23        | **18.55**         | 51.84        | +15.86 bps         |
| 2022 bear  Cand-2   | 88.68 bps              | 197.49      | 65.36             | 157.12       | −23.32 bps         |

**Surprising result**: drift went UP in 3/4 cells. The naive expectation
"M14 fix should make all drift collapse to zero" was wrong. See §4 for
why.

**Trade counts pre→post**: every cell got MORE trades post-fix.

| Cell                | Fills pre | Fills post | Δ      |
|---------------------|----------:|-----------:|-------:|
| 2024 up-tape RCMv1  | 99        | 133        | +34 (+34%) |
| 2024 up-tape Cand-2 | 707       | 788        | +81 (+11%) |
| 2022 bear  RCMv1    | 115       | 148        | +33 (+29%) |
| 2022 bear  Cand-2   | 778       | 883        | +105 (+13%) |

**Final equity pre→post**: NAV materially changes in three cells.

| Cell                | Final NAV pre | Final NAV post | Δ          |
|---------------------|--------------:|---------------:|-----------:|
| 2024 up-tape RCMv1  | 109,519       | 109,215        | −0.28%     |
| 2024 up-tape Cand-2 | 136,574       | 137,159        | +0.43%     |
| 2022 bear  RCMv1    | 122,941       | 125,507        | **+2.09%** |
| 2022 bear  Cand-2   | 156,891       | 171,967        | **+9.61%** |

So M14 had a SECOND-DIMENSION effect beyond writing NaN to equity rows:
NaN `portfolio_value` was silently **suppressing rebalance orders**
downstream (rebalance triggers compare current weights to targets;
NaN portfolio_value ⇒ NaN current weights ⇒ rebalance condition
short-circuits ⇒ order skipped). The fix unblocks ~10-30% more
rebalance activity, which materially changes the strategy's actual
realized P&L — most dramatically for high-turnover Cand-2 in 2022
(+9.61% on final NAV).

This means the previous TD75 cross-regime memo's headline equity
numbers (Cand-2 +5814 bps vs SPY in 2022, +2983 bps in 2024) were
**under-reported** for both candidates — the M14-suppressed rebalances
were depressing Cand-2's realized return. Post-fix Cand-2 realized
return in 2022 is meaningfully higher.

---

## 4. Why drift went UP in 3/4 cells — residual attribution

This is the part that requires careful framing.

### 4.1 The pre-fix "low drift" was an illusion

For every NaN-equity day in paper, the drift report short-circuited:
`paper_NAV = NaN ⇒ delta_bps = NaN ⇒ counted as 0`. Verified directly:

| Cell                | Pre-fix NaN paper days | Pre-fix `\|delta\|≤0.5` days | Overlap |
|---------------------|-----------------------:|----------------------------:|--------:|
| 2024 up-tape RCMv1  | 15                     | 60                          | 15      |
| 2024 up-tape Cand-2 | 13                     | 28                          | 13      |
| 2022 bear  RCMv1    | 28                     | 45                          | 28      |
| 2022 bear  Cand-2   | 25                     | 37                          | 25      |

100% of the NaN paper days appeared as "zero drift" days in the report.
On the 2022 RCMv1 cell, that was 28 of 45 reported zero-drift days —
NEARLY HALF of the apparent reproducibility was a NaN-curtain artifact.

When the fix removes the NaN curtain, those days become real
comparisons. So the post-fix mean |drift| can legitimately be HIGHER
than the pre-fix mean even though each individual day's comparison is
now correct rather than masked.

### 4.2 Two distinct components in the post-fix drift

For each post-fix cell, the post-fix drift is

  post_mean = (real-drift days unmasked) + (drift on previously-NaN days now visible)

The 2022 Cand-2 cell shows the cleanest reduction (88.68 → 65.36 bps
i.e. −26%) because pre-fix it had genuine large NaN-bridge gaps + huge
"day after NaN" drift jumps (the Cand2 attribution memo §2.2 itemized
these — ~190-200 bps "day after NaN Monday" jumps, gone now). The fix
removed those.

The 2022 RCMv1 cell shows the largest INCREASE (2.69 → 18.55 bps) for
the opposite reason — pre-fix it was almost entirely NaN-curtain
zero-drift (28 of 45 zero days were NaN). The remaining 17 zero days
were genuine matches. Once the curtain lifted, the underlying paper-
vs-replay drift became visible.

### 4.3 What is the underlying drift in the 2022 RCMv1 cell?

This is the residual that needs explaining.

Post-fix sign distribution: **78+ / 0− / 17 zero**. This is monotonic:
paper is ALWAYS ≥ replay (within a tolerance), never less. Mean signed
drift +18.54 bps = mean abs drift 18.55 bps; ratio = 1.00.

This is NOT noise. Noise would give roughly balanced signs. A 78/0
split rejects the null hypothesis of random execution variance at any
reasonable significance threshold.

**Hypothesis** (not yet confirmed): the residual is paper-vs-replay
**execution-state divergence**, separate from M14. Mechanism candidates:

a) **Order-generation path divergence**. Paper iterates day-by-day
   producing fills/positions and persisting state. Replay reconstructs
   the same period in one pass, computing positions from the persisted
   `signals_daily.csv` rather than from scratch. If `_generate_orders`
   has any state that depends on multi-day accumulated context (e.g.
   ghost-cleanup carry-over, stale-days counter, last_valid_close),
   paper and replay can diverge whenever the carry-over differs.

b) **Cost-accounting timing**. `ExecutionSimulator.simulate_fill` shifts
   execution price by `cost_bps` (slippage) and applies `commission_usd`
   to cash. The 1.3 PRD-known-bug section flagged that `cost_bps` may
   represent total cost (commission + slippage) and double-count
   commission. If paper and replay traverse the same code path but
   accumulate state in slightly different orders (e.g. cash residuals
   from integer-share rounding), the doubled commission compounds
   asymmetrically.

c) **Integer-shares rounding asymmetry**. Both paths use integer shares
   in non-strict mode. If the order-generation logic chooses to round
   the same target weight differently between paper (which sees
   yesterday's actual cash) and replay (which sees a freshly-computed
   cash trajectory), small per-day rounding deltas compound.

The 78+/0- bias suggests (b) or (c) is more likely than (a) — those
asymmetries are systematic; (a) would more likely produce mixed-sign
drift.

This residual is **out of scope for the M14 fix**. It deserves its own
investigation under the existing "M11 paper-BT consistency gate"
PRD item, which is now upgraded from skip-PASS to active.

### 4.4 What about the 2024 RCMv1 cell — why is it ~unchanged?

2024 RCMv1 had only 15 NaN-paper days (vs 28 in 2022 RCMv1) and only
modest underlying drift on those days (low-turnover defensive
strategy). Pre-fix mean 3.60 bps, post-fix 4.43 bps — within the
~1 bps execution-state envelope. This cell has the cleanest "M14 was
the only meaningful drift driver, and it's now removed" story.

### 4.5 What about 2024 Cand-2 — why did it go UP if 2022 Cand-2 went DOWN?

2024 Cand-2: 24.08 → 59.77 bps (+35.69 bps)
2022 Cand-2: 88.68 → 65.36 bps (−23.32 bps)

The 2024 cell is the symmetric counterpart to 2022 RCMv1: pre-fix had
13 NaN days that hid drift-curtain zero-bps in the report. Post-fix
those days surface as real comparisons. Combined with Cand-2's
high-turnover sensitivity to the same execution-state divergence in
§4.3, post-fix drift is higher.

The 2022 Cand-2 case is different: pre-fix the M14 NaN-bridge "day
after Monday" jumps were dominant (~190 bps × 16 days), and those got
removed by the fix. The execution-state residual remains but is
smaller than the M14 contribution that was eliminated.

So the four cells reflect a 2-by-2 of (high vs low turnover) × (high
vs low NaN-bridge gap magnitude). Fixing M14 removes the latter; the
former leaves a residual proportional to turnover.

---

## 5. Caveats and known limitations

### 5.1 Saturday pad rows in 2022 cells

The pre-fix NaN-paper-day breakdowns for 2022 cells include Saturday
rows ("Saturday: 13" for 2022 RCMv1; "Saturday: 9" for 2022 Cand-2).
Saturdays are non-trading; their presence is a `pd.bdate_range` /
panel-construction artifact (`bdate_range` excludes weekends, so the
Saturday rows are coming in via signals_daily.csv being indexed off a
panel that includes pad rows). These rows have NaN equity pre-fix
because the price panel is empty on weekends, but they don't
correspond to real trading days — they're padding.

Post-fix, those Saturday rows still exist in pnl_daily.csv but with
finite equity (last-valid-close fallback). They don't introduce real
drift because both paper and replay produce the same pad-row equity
deterministically. The drift report's date alignment handles them
correctly.

### 5.2 Single-period observation

These results are from one paper run × one replay × four cells. The
residual analysis in §4 is hypothesis-grade, not confirmed via
controlled experiment. A separate workstream should
- pin paper / replay state-divergence sources via instrumentation, and
- re-run the four cells with a debug build to confirm or reject the
  three candidate mechanisms.

### 5.3 No production_strategy.yaml impact

This fix touches `core/backtest/backtest_engine.py` only — the
production single-source-of-truth is unchanged. RCMv1 frozen spec
unchanged. Cand-2 frozen spec unchanged. Both candidates remain at
`S2_paper_candidate` registry status.

---

## 6. Test status

- `tests/unit/backtest/test_m14_nan_equity.py`: **5/5 pass** (new).
- Full pytest baseline pre-fix: 1566 passed.
- Full pytest post-fix: **1571 passed** (= 1566 + 5 new). 0 regressions.
- `data/baseline/latest.json` will be refreshed in the commit so the
  test count is the recorded SoT.

---

## 7. What changes after this fix

### 7.1 In CLAUDE.md "Current TODO"
- M14 status: `conditional P2` → **shipped** (this commit).
- M11 paper-BT consistency gate: still open. Promoted from
  "skip-PASS, M1 covers it" to "active — new evidence of execution-
  state residual drift in 2022 RCMv1 (78+/0− signed drift bias) needs
  diagnosis." See §4.3 above.

### 7.2 In TD75 cross-regime memo
The "Cand-2 dominates RCMv1" framing is still suspect, but for a
cleaner reason now:
- Cand-2 final NAV in 2022 is ~9.6% higher than previously reported.
- RCMv1 final NAV in 2022 is ~2.1% higher than previously reported.
- Both gaps come from previously-suppressed rebalances post-fix; both
  candidates' realized excess vs SPY in 2022 grows.
- The relative ordering (Cand-2 vs RCMv1) is preserved directionally
  but the magnitude difference is no longer "Cand-2 dominates by 100s
  of bps unambiguously" — it must be re-stated against the residual
  paper-replay execution-state envelope (~18-65 bps depending on cell).

### 7.3 What still NOT to do
- No universe extension
- No new mining round
- No new data tier
- No Candidate-3 work
- No retroactive RCMv1 spec change
- No frozen-spec changes for either candidate

These remain frozen until the M11 residual is also addressed.

---

## 8. Artifacts

**Code change**: `core/backtest/backtest_engine.py` lines 262-289.
**New tests**: `tests/unit/backtest/test_m14_nan_equity.py` (5 tests).
**Pre-fix paper runs**:
- `data/paper_runs/rcm_v1_defensive_composite_01/20260424T212806Z/`
- `data/paper_runs/rcm_v1_defensive_composite_01/20260424T214642Z/`
- `data/paper_runs/candidate_2_orthogonal_01/20260424T212809Z/`
- `data/paper_runs/candidate_2_orthogonal_01/20260424T214644Z/`

**Post-fix paper runs**:
- `data/paper_runs/rcm_v1_defensive_composite_01/20260424T224049Z/`
- `data/paper_runs/rcm_v1_defensive_composite_01/20260424T224054Z/`
- `data/paper_runs/candidate_2_orthogonal_01/20260424T224051Z/`
- `data/paper_runs/candidate_2_orthogonal_01/20260424T224056Z/`

**Cross-references**:
- Drift attribution memo: `docs/memos/20260424-cand2_drift_attribution.md`
- TD75 cross-regime memo: `docs/20260424-parallel_paper_2022h2_checkpoint_75d.md`
- M14 PRD item: CLAUDE.md "Current TODO Checklist" → M14 line.

---

## 9. One-sentence summary

M14 was a single-line `dict.get` default-vs-NaN bug in
`backtest_engine.py` portfolio valuation; the fix eliminates all
NaN-equity rows across 4 paper cells and unblocks ~10-30% suppressed
rebalance activity (raising 2022 Cand-2 realized NAV by +9.6%), but
exposes a previously-masked paper-vs-replay execution-state residual
drift of 18-65 bps that requires a separate M11-level investigation.
