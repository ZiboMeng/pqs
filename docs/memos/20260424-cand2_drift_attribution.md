# Cand-2 Drift Attribution — M14 NaN, NOT Execution Noise

**Date**: 2026-04-24
**Trigger**: auditor correction on TD75 cross-regime memo — the
"Cand-2 dominates RCMv1 in both regimes" claim was contaminated by
~100 bps mean drift in 2022 bear, with 42/75 days breaching the 50bps
informational threshold. The auditor required structural attribution
of this drift before any further work.

This memo overturns the previous "Cand-2 has structural execution-
layer stress" interpretation. The drift is, with high confidence,
**caused by M14** (BacktestEngine ghost-cleanup + NaN last-bar
interaction), and is **not** a Cand-2-specific execution-noise signal.

---

## Status update (2026-04-25, post-step-3b)

This memo's specific dates and "next-day-after-NaN" lists below are
**BarStore-label dates from the pre-step-3b daily store**. The
underlying root cause has now been fully traced and fixed across
M14 → M11 → round-3 data-integrity workstream:

- **M14 fix (2026-04-24)**: `backtest_engine.py` `last_valid_close`
  fallback — eliminated NaN-equity rows even when held symbols had
  NaN close on a given panel date.
- **M11 fix (2026-04-24)**: hash-determinism + run_day_daily semantics
  — collapsed paper-vs-replay drift to literal zero on the pre-fix
  data store.
- **Round-3 data-integrity workstream (2026-04-25)**: rebuilt
  `data/daily/<sym>.parquet` from polygon 1m as single canonical
  source — eliminated +1d label offset, mixed-scale alternation,
  and Sat/Sun pad rows universe-wide.

Under the rebuilt store:
- All four canonical paper cells re-run with drift = 0 bps.
- The "NaN-Monday" days enumerated in §2.2 below (e.g. 2022-10-17,
  2022-12-12, etc.) are BarStore-label-date references from the
  pre-step-3b era. Under the rebuilt store, every weekday is a real
  ET trading day with the correct label, and the Saturday pad rows
  that used to follow each Friday are gone — so the "NaN day +
  next day jump" pattern documented below cannot recur.

The substantive conclusion of this memo (drift was M14-driven, not
Cand-2-execution-driven) was correct and remains historically
important. The numerical specifics are post-step-3b stale.

For canonical NAV / drift numbers see TD75 §0c
(`docs/20260424-parallel_paper_2022h2_checkpoint_75d.md` §0c).

---

## 1. Headline finding

The Cand-2 paper-vs-replay drift in both windows is dominated by a
**M14 NaN-bridge artifact**. The mechanism:

1. Cand-2's high-turnover trading creates intermediate cash + position
   state that, at certain calendar boundaries (mostly Mondays after
   weekends), triggers BacktestEngine's ghost-cleanup-with-NaN
   path and produces a `NaN` equity row in the paper run's
   `pnl_daily.csv`.
2. The drift-report replay starts from a fresh state. Its
   intermediate state at the same calendar boundary may NOT trigger
   the same NaN.
3. Result: paper has NaN at, e.g., 2022-10-17 (Monday); replay has a
   real value. The drift skips that day (`delta_bps = 0` because
   `paper_nav` is NaN). The day AFTER the NaN, paper rebuilds equity
   from a different starting point than replay → drift jumps to
   ~150-200 bps and stays there for the rest of the cycle.

This is NOT execution-fill variance. It is a **reproducibility bug**
in BacktestEngine's NaN handling.

---

## 2. Evidence

### 2.1 Drift is strongly signed (one-direction bias)

| Window | + days (replay > paper) | − days (paper > replay) | zero days |
|--------|------------------------:|------------------------:|----------:|
| 2024 up-tape | 39 | 14 | 22 |
| 2022 bear | **49** | **3** | 23 |

Both windows show replay > paper systematically. If this were
random execution noise (fill-price slippage, cost timing) the sign
would be roughly balanced. The 49/3 split in 2022 is essentially
one-directional — replay's NAV is consistently higher than paper's.

Mean signed drift: +19.7 bps (2024) and **+100.0 bps (2022)**.
Absolute mean drift: +23.1 bps and +100.1 bps. The ratio of
|signed mean| / |abs mean| is 0.85 (2024) and **1.00 (2022)** —
in 2022, the drift is ~100% directional.

### 2.2 NaN days in paper coincide exactly with drift jumps

Paper `pnl_daily.csv` has NaN equity rows at specific calendar
boundaries:

| Window | NaN equity days | Pattern |
|--------|----------------:|---------|
| 2024 up-tape | 13 | Mostly Mondays |
| 2022 bear | 16 | Mostly Mondays + 2 Thanksgiving-week days |

Drift on each NaN day = 0 bps (because paper_nav is NaN, the
comparison short-circuits). Drift the **next trading day** is where
the gap shows up:

```
2022 bear — top 10 day-over-day drift jumps:
  2022-10-18 (Tue): +0.0 → +197.5 bps   [prev day = NaN Monday]
  2022-10-11 (Tue): +0.0 → +195.9 bps   [prev day = NaN Monday]
  2022-10-17 (Mon): +188.0 → +0.0 bps   [is NaN day itself]
  2022-12-13 (Tue): +0.0 → +186.7 bps   [prev day = NaN Monday]
  2022-12-12 (Mon): +186.3 → +0.0 bps   [is NaN day itself]
  ...
```

Every drift jump > ~150 bps is a "next day after a NaN day". And
every drift collapse to 0 is a "NaN day itself". The pattern is
deterministic across all 16 NaN days in 2022 and all 13 in 2024.

### 2.3 Drift is NOT correlated with turnover or volatility

| Window | corr(\|drift\|, turnover) | corr(\|drift\|, \|SPY ret\|) |
|--------|--------------------------:|----------------------------:|
| 2024 up-tape | 0.076 | −0.031 |
| 2022 bear | 0.181 | 0.046 |

Both correlations are essentially zero. The TD60/TD75 hypothesis
("bear-bottom volatility amplifies execution variance via Cand-2's
high turnover") is **wrong**. The drift is independent of how much
trading occurs that day or how volatile the market is.

### 2.4 The worst drift day has zero fills

| Window | Worst drift day | Drift bps | Fills on that day |
|--------|-----------------|----------:|------------------:|
| 2024 | 2024-03-26 | +174.89 | **0** |
| 2022 | 2022-10-18 | +197.49 | **0** |

If drift were execution-fill noise, the worst drift days would be
high-trade days. Instead they're the day AFTER a NaN-Monday with
zero same-day fills. The drift comes from **mark-to-market valuation
of held positions** under different starting states between paper
and replay, NOT from per-trade execution variance.

### 2.5 RCMv1 has zero drift because it has near-zero NaN days

RCMv1 paper `pnl_daily.csv` has very few NaN equity rows in either
window — checked but not enumerated here. Its low-turnover defensive
core doesn't generate the intermediate state that triggers M14
ghost-cleanup. With no NaN days, there's no NaN-bridge gap, so drift
remains effectively zero.

This explains the cross-candidate drift-magnitude difference cleanly:

```
   Candidate    NaN days  Drift mean (bps)
   RCMv1        ~0         0.0
   Cand-2       13-16     23-100
```

The drift is a function of NaN-bridge incidence, not candidate-
intrinsic execution behavior.

---

## 3. What this overturns

### 3.1 TD60 and TD75 narratives that need revision

- "**Cand-2's drift escalation is bear-amplified execution variance**" —
  WRONG. The drift is M14 NaN-bridge, and the 2022 vs 2024 difference
  is just NaN-day count (16 vs 13) plus larger per-NaN-bridge gap
  (because Cand-2 is up more in 2022, 1 day's compounding worth
  more bps).
- "**Bear regime amplifies Cand-2's execution-layer sensitivity**" —
  WRONG. Bear regime amplifies the NaN-bridge gap because
  high-volatility days that follow NaN Mondays have larger
  one-day moves, which compound into the drift more.
- "**Per-trade drift growing 0.98 → 11.05 → 14.72 bps-days/trade**" —
  This metric was constructed by dividing aggregate drift by fill
  count. Since drift is NOT actually per-trade, the metric was
  meaningless. Higher drift in later buckets is just NaN-bridge
  density × position-MTM spread.
- "**Cand-2 execution layer is bear-vulnerable**" — UNCONFIRMED. We
  can't measure Cand-2's actual execution layer until M14 is out of
  the way.

### 3.2 What still holds

- **Position-set diff = 0/75 across all 4 cells**: signal layer is
  bit-stable. Both candidates' target-weight outputs are 100%
  reproducible. This was always the strongest claim, and it survives.
- **Orthogonality construction**: composite correlation 0.385 (2024)
  and 0.225 (2022). These are independent of NaN-bridge artifact —
  they're computed on the published cumulative excess, but day-over-
  day correlation is a sign-and-direction property, not a magnitude
  one.
- **Both candidates beat SPY in both regimes**: directionally
  unchanged. Even at 100 bps mean drift, the +2400 bps and +5800 bps
  excess vs SPY are not within drift-uncertainty of zero.
- **Both candidates' portrait classes** (defensive ETF-hybrid vs
  high-activity tactical): unchanged. These are turnover / unique-
  symbol / asset-class properties, not NAV-drift-sensitive.

### 3.3 What is now ambiguous

- **Cand-2's true excess vs SPY** in either window. The headline
  +2983 bps (2024) and +5814 bps (2022) include accumulated
  NaN-bridge bias. Replay-adjusted excess is the more reliable
  number, but we don't have a clean "no-M14 replay" baseline yet.
  Cand-2 still wins vs SPY directionally, but by how much is
  uncertain by ~100-200 bps in 2022.
- **Whether Cand-2 "leads" RCMv1**. Auditor was correct that this
  was unfounded; now we know the drift contamination is even
  larger and more directional than initially thought.
- **All TD60 §8 decision-readiness reasoning that depended on
  drift-as-execution-stress** needs to be re-read with the
  understanding that M14 was the actual driver.

---

## 4. Implications for next steps

### 4.1 M14 NaN fix is now first-priority

Per user's earlier ranking (Cand-2 execution investigation first,
M14 second). After this attribution, the order should flip:

- **M14 fix is now THE first-priority blocker.** Without it, we
  literally cannot measure Cand-2's actual execution layer. The
  attribution cannot proceed further.
- The "Cand-2 execution-layer investigation" that user asked for
  has, in this memo, **completed its diagnostic phase**. The
  conclusion is that there is no Cand-2-specific execution-layer
  stress signal we can verify until M14 is fixed.
- After M14 fix, re-run the parallel-paper drift reports for both
  candidates in both windows. If RCMv1 stays at near-zero drift
  AND Cand-2 collapses to near-zero drift, the M14 hypothesis is
  fully confirmed and there's no remaining Cand-2 issue. If Cand-2
  retains some non-zero drift after M14 is removed, that residual
  is the real execution-layer signal that we then characterize.

### 4.2 Recommended sequence

1. **M14 root-cause** in BacktestEngine. Identify where the NaN
   ghost-cleanup is triggered. Likely in `core/backtest/backtest_engine.py`
   or `core/backtest/intraday_engine.py` around end-of-day cleanup
   when the engine processes a position with a NaN last-known-price
   (e.g. a delisted symbol or an end-of-window edge).
2. **Fix candidates**:
   - Skip ghost-liquidation when last_close is NaN
   - Forward-fill last-valid price for positions held into a
     NaN bar
   - Detect the no-data condition and emit a clean log + skip the
     equity-aggregation rather than write NaN
3. **Verify** by re-running both paper runs and checking:
   - paper_pnl_daily has no NaN equity rows
   - paper_drift_report mean drift drops to near zero for both
     candidates in both windows
4. **Then**: continue any candidate-specific execution-layer
   investigation if the post-fix data still suggests one. If
   Cand-2's drift stays near zero, we've conclusively answered
   that the original concern was M14, not Cand-2.

### 4.3 Data integrity / split adjustment workstream

User direction: parallel but not main line. With M14 elevated to
first-priority, the data-integrity item drops to second-priority.
Order:

1. M14 fix (this commit's recommendation: jump to top of queue)
2. Data-integrity scope/root-cause memo (after M14)
3. RCMv1 factor-selection sub-decision post-mortem (after data
   integrity)

### 4.4 Things still NOT to do per current freeze

- No universe extension
- No new mining round
- No new data tier
- No Candidate-3 work
- No retroactive RCMv1 spec change

These remain frozen until the M14 fix lands and we can re-examine
clean drift numbers.

---

## 5. Status & artifact pointers

- Both candidates remain at `S2_paper_candidate`. No registry
  change.
- pytest 1566/1/1 (no code change in this attribution work; only
  analysis + this memo).
- Underlying data:
  - `data/paper_runs/candidate_2_orthogonal_01/20260424T212809Z/`
    (2024 TD75 paper run + drift)
  - `data/paper_runs/candidate_2_orthogonal_01/20260424T214644Z/`
    (2022 TD75 paper run + drift)
  - `data/paper_runs/rcm_v1_defensive_composite_01/20260424T212806Z/`
    + `20260424T214642Z/` (matched RCMv1 runs)
- Cross-references:
  - TD75 memo: `docs/20260424-parallel_paper_2022h2_checkpoint_75d.md`
    §0a (audit correction with this memo's lookback)
  - M14 origin: CLAUDE.md "Phase E history" archive references it
    as "BacktestEngine ghost-cleanup + NaN last-bar (P2 conditional)"
  - This is the first concrete evidence that promotes M14 from
    "conditional P2" to "first-priority blocker" status.

---

## 6. Recommendation in one sentence

**Do not start any further Cand-2 / RCMv1 / Candidate-3 work until
M14 is root-caused and fixed**, because the parallel-paper
reproducibility evidence to date is dominated by M14, and any
post-M14 conclusions will likely look meaningfully different from
the pre-M14 ones.
