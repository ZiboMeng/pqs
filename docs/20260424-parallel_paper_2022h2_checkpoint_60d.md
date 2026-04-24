# Parallel Paper (2022-H2 bear) — Checkpoint TD60 (Decision Readiness)

**Date**: 2026-04-24
**Window**: 2022-08-26 → 2022-12-15 (79 real TDs)
**Cutoff (this memo)**: real trading day **TD60 = 2022-11-18 (Fri)**.
**Scope per PRD §7.2 + §8**: full 60-day comparison; decision readiness
on universe extension / new mining / new data tier; cross-regime
synthesis with the 2024 TD60 checkpoint where the two regimes meet.
**TD61+ data on disk untouched** — TD75 cross-regime memo remains
the next checkpoint.

The 2022 window context @ TD60: SPY recovered from the Oct 12 bottom
(−12.79% at our TD40) to **−5.94% at TD60**. The CPI-cool rally on
2022-11-10 (+5.5% SPY single day) is inside the window. So TD60 spans
the full bear → bottom → ~7-point recovery cycle, not just the
drawdown.

---

## 1. Headline @ TD60

| Metric | RCMv1 | Candidate-2 | SPY / QQQ |
|--------|------:|------------:|----------:|
| Paper cum ret (TD60) | +15.49% | **+47.36%** | SPY −5.94%, QQQ −9.87% |
| Excess vs SPY @ TD60 | +2142 bps | **+5330 bps** | — |
| Excess vs QQQ @ TD60 | +2658 bps | +5845 bps | — |
| Cum turnover (60d) | 8.80 | 34.00 | 3.9× |
| Active turnover days | 29 / 60 | 53 / 60 | — |
| Total fills (60d) | 73 | 572 | 7.8× |
| Drift mean \|Δ NAV\| | **0.00 bps** | **94.39 bps** | — |
| Drift max \|Δ NAV\| | 0.00 bps | 197.49 bps | — |
| Days \|Δ\| > 50 bps | **0 / 60** | **32 / 60** | 53% breach |
| Position-set diff days | 0 / 60 | 0 / 60 | — |

The numbers are dramatic. Cand-2 is up **+47%** in 60 trading days
in a window where SPY closed −5.9%. That outperformance is real on
the signal layer (position-set diff = 0/60), but contaminated on the
execution layer by an average 94 bps of drift per day. Net replay-
adjusted excess vs SPY is in the +4400 to +5300 bps range — still
huge but with non-trivial uncertainty.

---

## 2. Focus 1 — Turnover shape stability across 3 buckets

| Bucket | RCMv1 active | RCMv1 cum | Cand-2 active | Cand-2 cum |
|--------|-------------:|----------:|--------------:|-----------:|
| TD1-20 | 5 / 20 | 1.30 | 13 / 20 | 7.80 |
| TD21-40 | 11 / 20 | 2.70 | 20 / 20 | 13.60 |
| TD41-60 | **13 / 20** | **4.80** | 20 / 20 | 12.60 |
| **60d total** | **29 / 60** | **8.80** | **53 / 60** | **34.00** |

Burst characteristics:

| | RCMv1 | Cand-2 |
|---|------:|-------:|
| Top-3 turnover days share | 22.7% | 8.5% |
| Top-5 turnover days share | 36.4% | 13.8% |
| Active-day lag-1 AC | 0.15 | **0.92** |

Two stable signatures preserved cross-regime:

- **Cand-2 = persistent high activity** (lag-1 AC 0.92, top-5 days
  only 14% of cum) — same as 2024 60d (AC 0.93, top-5 14%). Steady
  state confirmed in bear too.
- **RCMv1 = ramping with bursts** (lag-1 AC 0.15, top-5 days 36% —
  more bursty than 2024's 38%). Activity ramps from 5 → 11 → 13
  active days per 20-day bucket. The bear bottom triggered some
  rotation in TD21-40, and the recovery triggered more in TD41-60.

---

## 3. Focus 2 — Benchmark-relative path quality

Daily excess vs SPY through 60 days:

| Metric | RCMv1 | Candidate-2 |
|--------|------:|------------:|
| n daily observations | 41 | 39 |
| Mean daily excess (bps) | +31.3 | **+56.0** |
| Std daily excess (bps) | 272 | 240 |
| Skew | **+0.72** | **+0.26** |
| Positive days | 20 (49%) | 27 (69%) |
| Negative days | 21 | 12 |
| Mean on +days (bps) | +244 | +167 |
| Mean on −days (bps) | −172 | −194 |
| Win/loss count ratio | 0.95 | **2.25** |
| Top-3 days share \|cum excess\| | 24.2% | 25.8% |
| Top-5 days share | 33.9% | 37.0% |
| Max DD of cum excess vs SPY | **−702 bps** | **−747 bps** |
| Max DD of cum excess vs QQQ | −706 bps | −592 bps |

Both candidates have similar excess-path drawdowns (~700 bps);
neither is a smooth accumulator. Cand-2 has 2.25 win/loss count ratio
(the strongest in any checkpoint we've measured) — its tactical book
in the bear+recovery generates lots of small wins relative to fewer
larger losses.

**Notable cross-regime path-shape comparison**:

| | 2024 TD60 (up-tape) | 2022 TD60 (bear+recovery) |
|---|--------------------:|-------------------------:|
| RCMv1 daily excess mean | +24.3 bps | +31.3 bps |
| RCMv1 daily excess std | 142.6 bps | **272.1 bps** |
| RCMv1 skew | +0.37 | +0.72 |
| Cand-2 daily excess mean | +31.5 bps | **+56.0 bps** |
| Cand-2 daily excess std | 124.7 bps | 240.2 bps |
| Cand-2 skew | +0.01 | +0.26 |

RCMv1's daily-excess std nearly **doubled** in bear (142 → 272 bps).
Cand-2's std also doubled (125 → 240). Both candidates have higher
daily excess volatility in the bear regime, which makes sense — the
benchmark is moving faster, so any portfolio deviation from it
fluctuates more.

Cumulative excess @ TD60 evolution:

| | TD10 | TD20 | TD40 | TD60 |
|---|----:|----:|----:|----:|
| RCMv1 vs SPY (bps) | +481 | +1043 | +1251 | **+2142** |
| Cand-2 vs SPY (bps) | +557 | +1236 | +2403 | **+5330** |

Both candidates have **monotonically growing excess vs SPY** through
the entire 2022 window. In the 2024 window, RCMv1 was V-shaped
(+243 → +65 → +879 vs SPY), giving back its lead at TD40. In bear it
never gives back. That's a regime-dependent property of defensive
composites: they're more reliably above the benchmark when the
benchmark is dropping.

Cand-2's TD41-60 excess gain is **+2927 bps** (+2403 → +5330) — by
far the largest 20-day gain in any checkpoint. The recovery from the
Oct 12 bottom is where Cand-2's high-beta book (TSLA / SOXL / TQQQ /
NVDA — all up 25-50% in November 2022) generated most of its alpha.

---

## 4. Focus 3 — Drift trending (the standout finding)

| Metric | RCMv1 | Candidate-2 |
|--------|------:|------------:|
| Mean \|Δ\| TD1-20 | 0.00 bps | 6.61 bps |
| Mean \|Δ\| TD21-40 | 0.00 bps | **135.97 bps** |
| Mean \|Δ\| TD41-60 | 0.00 bps | **140.59 bps** |
| Per-trade drift TD1-20 | 0.00 | 0.98 |
| Per-trade drift TD21-40 | 0.00 | 11.05 |
| Per-trade drift TD41-60 | 0.00 | **14.72** |
| Days > 50 bps TD1-20 | 0 | 0 |
| Days > 50 bps TD21-40 | 0 | 16 |
| Days > 50 bps TD41-60 | 0 | **16** |
| Position-set diff TD60 | **0 / 60** | **0 / 60** |

**Cand-2 drift did NOT decay after bear bottom**. The 5 worst days
are still 2022-10-11 to 2022-10-18 (cluster around Oct 12). But:
- TD21-40 mean: 135.97 bps  
- TD41-60 mean: 140.59 bps (slightly HIGHER)
- Per-trade drift: 11.05 → 14.72 (elevated, not stabilizing)

So drift is now **structural**, not just bear-bottom-induced. 32/60
days breach the 50 bps informational threshold — over half the
days. This is a candidate-specific stress signature that **persists
even as market volatility normalizes from the Oct 12 peak**.

Compared to 2024 TD60: 9/60 days breach (15%). 2022 TD60: 32/60
breach (53%). **3.5× higher breach rate cross-regime**.

But — position-set diff = 0/60. Signal layer is bit-stable. Replay
target weights match exactly. The drift is purely fill-price /
cost-timing variance under sustained high turnover.

**Candidate-specific watch list updated**:
- Drift is structural in bear, not bottom-only
- Per-trade drift growing across buckets (11 → 14.7), not stabilizing
- Sample of pre-revoke-trigger? PRD §7.2 50bps is informational, not
  a gate. But 53% of days breaching is the strongest stress signal we
  have. If a future window (or live forward run) shows this pattern,
  the M14 NaN fix or a dedicated execution-layer review for Cand-2
  would be warranted.

**RCMv1 drift remains literally zero**. 5 worst days all show 0.00
bps. With only 73 fills over 60 days and a stable defensive core
(TRGP / TSN / ED / VICI continuously held 50-52 days), there's
essentially no execution surface.

---

## 5. Focus 4 — RCMv1 ETF overlay in bear (the open question from 2024-60d)

The 2024 60d memo found that on days RCMv1 holds ETFs, daily excess
vs SPY averaged +29 bps; on no-ETF days, +1 bps. The interpretation
was that the ETF overlay was a real driver of RCMv1's alpha. The
2022 bear window now provides the cross-regime test:

| Metric | 2024 TD60 | 2022 TD60 |
|--------|----------:|----------:|
| Active days | 51 | 52 |
| No-ETF days | 14 | 22 |
| Has-ETF days | 37 | 30 |
| ETFs ever held | QUAL, MTUM, XLRE, SLV (4) | **VLUE, QUAL** (2; QUAL only 1 day) |
| No-ETF mean excess vs SPY | +1.3 bps | **+32.3 bps** |
| Has-ETF mean excess vs SPY | **+29.1 bps** | **−10.8 bps** |
| **Sign of effect** | **+** | **−** |

**The finding flips**. In the 2024 up-tape, RCMv1 generated alpha on
days it had ETF exposure (+29 vs +1 bps). In the 2022 bear+recovery,
RCMv1 generated alpha on **no-ETF days** (+32 bps), while ETF-days
underperformed by 11 bps.

Mechanism: in 2024, RCMv1 held QUAL + MTUM + XLRE + SLV — quality /
momentum / real-estate / silver, all of which performed in the
tech-led up-tape. In 2022 bear, RCMv1 held essentially only **VLUE
(value factor)** for 30 days. November 2022 was a growth-led recovery
from the bear bottom; value lagged growth that month. So VLUE was a
**drag**, not a help.

**Revised reading of the cross-regime ETF picture**:

- The composite IS adapting its toolbox to regime (QUAL/MTUM/XLRE/SLV
  in up-tape → VLUE in bear). Confirmed.
- But the toolbox-pick in the 2022 bear-recovery wasn't the right
  one. VLUE underperformed growth in the November rally.
- "ETF overlay adds alpha" was a 2024-specific finding, not a
  cross-regime property.
- The conditional-alpha analysis at 2024 60d **was correct for that
  window**, but I shouldn't have implied a generalizable thesis.

This finding is fully on the parallel-paper table — it does NOT
require a Candidate-3 / new-mining decision to be valuable. It tells
us:

- RCMv1's ETF allocation IS regime-aware (different toolboxes per
  regime)
- The composite's choice of which factor to bet on (quality vs value)
  is itself a tactical call
- That call was profitable in 2024 (+29 bps conditional alpha) and
  unprofitable in 2022 (−11 bps conditional drag)
- A revised RCMv1 spec might want to explicitly check the regime-vs-
  factor-correctness, not just regime-vs-factor-shift

Note for follow-up — but **not action at TD60**. We have 2 windows of
data; that's not enough to redesign the RCMv1 frozen spec. Leave as
observation, defer redesign discussion.

---

## 6. Focus 5 — Candidate portraits @ TD60 cross-regime

**RCMv1 — defensive baseline confirmed cross-regime**:
- 29 unique syms (vs 22 at 2024 TD60) — slightly broader in bear
- Top 5 most-held: TSN(52d), TRGP(51d), VICI(50d), ED(45d), TRV(32d) —
  defensive consumer / midstream / REIT / utility / insurance
- 6.0% factor ETF (VLUE only); 0% sector / 0% cross-asset
- Cum turnover 8.80 (vs 10.70 at 2024 TD60) — slightly less active
- Drift literally zero — pipeline reproducibility perfect under bear stress
- Cum excess vs SPY +2142 bps; vs QQQ +2658 bps
- Daily excess mean +31 bps (vs +24 at 2024 TD60), std 272 (vs 143)
- **Reads as**: low-activity defensive book that holds individual
  defensive equities for the full window, with regime-aware factor
  selection (VLUE in bear, QUAL/MTUM/XLRE/SLV in up-tape) but with
  no broader sector / cross-asset rotation. The 2024-60d "narrow
  toolbox" finding now reads as "**deliberately narrow per regime**".

**Candidate-2 — tactical book confirmed cross-regime, with stress signature**:
- 56 unique syms (vs 52 at 2024 TD60) — same magnitude
- Top 5: TSLA(33d), SOXL(32d), TER(29d), TQQQ(28d), NVDA(21d) —
  same momentum / leveraged-ETF / tech names from 2024
- 1.1% sector ETFs (XLE+XLF) + 1.3% cross-asset (SHY+SLV) vs 2024's
  0.9% sector only — slightly more diversified in bear
- Cum turnover 34.00 (vs 32.20 at 2024 TD60) — same shape, persistent
- Drift mean 94 bps, max 197, **53% of days breach 50bps** — this is
  the stress signature
- Cum excess vs SPY +5330 bps; vs QQQ +5845 bps
- Daily excess mean +56 bps (vs +32 at 2024 TD60), 2.25 win/loss
  count ratio
- **Reads as**: high-activity tactical momentum book that captured
  the recovery from Oct 12 bear bottom hard via TSLA / SOXL / TQQQ /
  NVDA. Generated more excess in bear+recovery than in up-tape, but
  with persistent execution-layer drift that doesn't decay.

The **baseline-vs-tactical pair structure is intact cross-regime**:
- Both candidates beat SPY in BOTH regimes
- Cand-2 beats by larger margin in BOTH (not just up-tape)
- Cand-2 has higher drift in BOTH (3.5× higher breach rate in bear)
- RCMv1 has zero drift in BOTH — its low-activity profile insulates it
- Neither has drifted off-thesis or shown signal-layer breakage

---

## 7. PRD §8 decision readiness

Both candidates have now been observed in 2 distinct market regimes
with cross-regime data. PRD §8 questions can be revisited:

### 7.1 Universe extension — **NOT YET**

- Cand-2 hit 56 unique symbols in 2022, 52 in 2024. With 79 tradable
  the ceiling is ~70%; not at saturation.
- RCMv1 hit 29 unique in 2022, 22 in 2024. Way under saturation.
- Neither candidate's signal generation broke or showed coverage-gap
  symptoms in either window.
- **No saturation signal.** Defer.

### 7.2 New mining round — **NOT YET**

- Both candidates still generate distinct alpha sources. Neither has
  shown factor-space-exhaustion.
- The conditional-alpha cross-regime picture for RCMv1's ETF overlay
  is informative but doesn't say "we need new factors" — it says
  "the existing factor selection is regime-dependent and can be
  wrong on occasion".
- **No factor-space exhaustion signal.** Defer.

### 7.3 New data tier — **NOT YET**

- All drift is execution-layer; signal layer is bit-stable. No
  data-tier starvation.
- The 2022 split-adjustment data-integrity issue is logged separately
  (`docs/20260424-data_integrity_2022_split_adjustment.md`); that's
  a fix-existing-tier issue, not a new-tier issue.
- **No data-tier starvation signal.** Defer.

---

## 8. Candidate-3 discussion — first time on the table

At 2024 TD60 I recommended **not** discussing Candidate-3 because we
only had one regime. Now we have two. So the question is on the
table.

### 8.1 Why a 3rd candidate is now warranted to discuss

Cross-regime data shows:
- Cand-2 is the dominant excess-generator in both regimes
- RCMv1 is the lower-vol / lower-drift complement
- In 2022 bear+recovery, **both candidates relied on similar
  tail-end days** (top-3 days = 24-26% of cum excess for both). They
  share burst-driven path shape.
- The cross-correlation of their daily excess series (not computed
  here — would need a focused analysis) would tell us whether their
  drawdowns of cum excess (−702 / −747 bps) overlap in time.

If both candidates **drew down their excess on the same days**, then
they're not as orthogonal as the original construction suggested.
Specifically the Oct 12 bottom region could have been a shared
stress moment for both.

A 3rd candidate that's **not** burst-driven — e.g. a slow-moving
mean-reversion or pure low-volatility (USMV-style) book — would
fill the path-shape gap.

### 8.2 Why I still recommend NOT starting it now

1. **The current pair still works**. Both candidates beat SPY
   handsomely in both regimes. Pair structure preserved.
2. **The most pressing item is Cand-2's drift signature**, not
   coverage gap. 53% of days breaching 50 bps in the bear is the
   strongest signal we have. Adding a 3rd candidate doesn't help
   that.
3. **Two windows, two regimes — but limited coverage**. Up-tape
   January-April 2024 + bear-recovery Aug-Nov 2022. We don't have
   sideways-low-volatility, multi-month grinding bear, capitulation
   selloff, or risk-on-into-FOMC days. 3rd candidate sample size is
   still tiny.
4. **3-candidate parallel-paper attribution gets harder**. Adding
   complexity before resolving Cand-2's drift signature is premature.
5. **Per user direction**: discuss, don't start. So I'll surface
   Candidate-3 as **on the table for the next planning round**, not
   committed work.

### 8.3 Conditions for opening Candidate-3 work

- A third regime observation (sideways / capitulation / different
  bear shape) is added to the cross-regime set, OR
- Cand-2 gets revoked (drift signature crosses some threshold), OR
- Specific economic theme gap is identified by cross-correlation
  analysis of the existing pair's daily excess series

Until then: 2-candidate parallel paper, eyes on Cand-2 drift, no
research-scope expansion.

---

## 9. Status

- Both candidates remain at `S2_paper_candidate`.
- pytest 1566/1/1 (no code change this round).
- No registry / config / schema / dependency / universe changes.
- Snapshot `docs/20260424-phase_state_snapshot.md` will be refreshed
  at this commit.

## 10. Next checkpoint

**TD75 = 2022-12-09 (Fri)**. The terminal cross-regime memo. Per the
user's earlier 2024 TD75 framing this should be the **cross-regime
comparison memo** — comparing 2022 bear+recovery vs 2024 up-tape
side-by-side on matched metrics.

Open question for TD75:
- The cross-correlation of daily excess between RCMv1 and Cand-2 in
  bear (skipped here for brevity)
- Final verdict on the baseline-vs-tactical pair as a parallel
  paper structure
- Updated answer to the §8 decision-readiness questions with both
  windows fully analyzed

Data already on disk; no new paper run needed.
