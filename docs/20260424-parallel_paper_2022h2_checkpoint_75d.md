# Parallel Paper — TD75 Cross-Regime Comparison Memo

**Date**: 2026-04-24
**Scope**: terminal cross-regime memo. Side-by-side comparison of the
**2024-01-02 → 2024-04-17** up-tape window and the
**2022-08-26 → 2022-12-09** bear+recovery window, both truncated to
**TD75** real trading days, on the same frozen pair `rcm_v1_defensive_composite_01`
+ `candidate_2_orthogonal_01`, the same 79-symbol universe, the same
pipeline.

This is the first memo in the parallel-paper exercise where universe
extension / new mining / new data tier / Candidate-3 may legitimately
be discussed (PRD §8 + user direction at TD60). Both windows have
been observed in full; both candidates have been stress-tested in
two distinct regimes.

---

## 0b. Post-M11 refresh (added 2026-04-24, supersedes §0a)

The drift contamination flagged in §0a has been **fully attributed and
fixed** under the M11 batch
(`docs/memos/20260424-m11_paper_engine_parity_fix.md`). Post-M11
paper-vs-replay drift is **literal zero** across all 4 cells × 91-95
days each. The "drift confounds the ranking" caveat in §0a is no
longer in force; the cross-regime pair comparison is now internally
consistent and reproducible.

### 0b.1 Canonical post-M11 baselines (replaces §0 headline numbers)

The numbers in §0 (and downstream §1.x sections) were generated
pre-M11 with hash-randomized `_generate_orders` iteration order, so
exact fills and final NAVs are **not reproducible** under the
post-M11 codebase. The post-M11 baselines are the canonical
comparison surface for any future TD80+ work.

| Cell | Pre-M11 paper cum ret (legacy §0) | Post-M11 paper cum ret | Pre-M11 excess vs SPY | Post-M11 excess vs SPY | Post-M11 excess vs QQQ |
|------|----------------------------------:|-----------------------:|----------------------:|-----------------------:|-----------------------:|
| 2024 up-tape RCMv1  | +16.64% | +9.83%  | +1017 bps | +409 bps  | +465 bps  |
| 2024 up-tape Cand-2 | +36.30% | +35.27% | +2983 bps | +2953 bps | +3009 bps |
| 2022 bear  RCMv1    | +18.57% | +23.67% | +2408 bps | +2834 bps | +3430 bps |
| 2022 bear  Cand-2   | +52.63% | +74.57% | +5814 bps | +7924 bps | +8520 bps |

Drift: was 3.63 / 23.07 / 0.00 / 100.12 bps mean abs (legacy §0);
**now 0.00 bps in all four cells**.

Trade counts: 95/675/84/685 (legacy §0); now 126/764/149/883 post-M11.
The post-M11 count is the deterministic baseline.

### 0b.2 Which §0a / §1.x conclusions to retain, revise, or drop

**Retained (still defensible, possibly stronger after refresh):**
- "Both candidates beat SPY in both regimes" — confirmed; the
  excess vs SPY in every cell is well outside any reasonable
  drift-uncertainty (now zero anyway).
- Orthogonality construction (§1.1) — not affected by drift; turnover
  ratio + Top-5 weight-day share + signal-correlation 0.385 / 0.225
  hold.
- "Position-set diff = 0/75 across all 4 cells" (signal layer is
  bit-stable) — strengthened: now both signal AND fill paths are
  bit-stable post-M11.
- §1.4 "RCMv1 has zero drift cross-regime" — was **always** zero
  in 2022 (legacy reading; this was actually masked NaN-curtain +
  hash-randomization noise, post-M11 is genuinely zero).
- §1.5 "Both candidates' daily excess std nearly doubles in bear" —
  not drift-sensitive, still holds.

**Revised (rephrase with post-M11 numbers; conclusion direction
unchanged):**
- §0 headline table → use the post-M11 numbers in §0b.1 above.
- §1.2 "Cand-2 dominates excess vs SPY in BOTH regimes" — now
  defensible under zero-drift; the magnitude in 2022 is **even
  larger** post-M11 (+7924 vs +5814 bps). The auditor's §0a
  rejection of this framing was correct given the pre-M11 data;
  post-M11 the framing recovers.
- §1.3 "Cand-2's drift signature is structural" — **drop entirely**
  for the live data; what was observed pre-M11 was 100%
  PYTHONHASHSEED-induced, not a Cand-2-specific structural property.

**Dropped:**
- §0a's deferral on "strategic ranking between RCMv1 and Cand-2".
  The M11 fix removed the contamination that motivated the
  deferral. Ranking by paper cum ret post-M11 is now a clean
  comparison; Cand-2 outperforms RCMv1 by ~10 percentage points in
  2024 and ~50 percentage points in 2022.
- §0a's "Cand-2 execution-layer investigation" workstream — closed
  by the M11 batch.

### 0b.3 Caveats that DO survive M11

- **"M11 passed" is a 4-cell-cohort claim, not a permanent system
  guarantee.** Two engines, two windows, two candidates, 91-95 days
  each. New candidates / new code paths / longer windows should
  re-run the parity tests
  (`tests/unit/paper_trading/test_paper_engine_parity_gap_open.py`,
  `tests/unit/backtest/test_hash_determinism.py`,
  `tests/unit/paper_trading/test_run_paper_candidate_immediate_rerun.py`)
  and reproduce zero drift before any new headline claim is made.
- **The 2022 BarStore Saturday-row data integrity issue is
  independent of M11 and unresolved.** The numbers above are
  internally consistent (paper and replay use the same misdated
  panel), but cross-references to specific 2022 calendar dates
  (Mondays mislabeled as Saturdays) carry a label-vs-real-exchange
  caveat. See M11 memo §5 for details. This is a deferred
  data-integrity workstream item; it does NOT invalidate any
  M11-level NAV comparison or pair-orthogonality claim.

### 0b.4 Forward direction (cadence pause + workstream switch)

- TD75 cadence is closed; no TD80 / TD100 unless a new question
  motivates it.
- Per-user direction at M11 closeout (2026-04-24): main-line
  technical-debt focus switches off the M14/M11 stack and onto the
  **data-integrity workstream** (split-adjustment + date-label
  integrity, of which the 2022 Saturday-row finding is one
  observation). When that work lands, re-run the 4 paper cells to
  verify post-data-fix drift remains zero.
- Universe extension / new mining / new data tier / Candidate-3 /
  retroactive RCMv1 spec change: **all still frozen**.

---

## 0a. Auditor correction (added 2026-04-24, after initial commit)

The "Cand-2 dominates RCMv1 in both regimes" framing in the original
TD75 draft (sections 1.2, 4, and sundry) was too strong. It is a
**paper-cumulative-return** statement, but Cand-2's paper-cum is
materially polluted by execution-layer drift in the 2022 bear window:
mean 100 bps, max 197 bps, **42/75 days breaching 50 bps (56%)**. That
contamination is large enough to affect any economic ranking
conclusion.

What can be claimed at TD75:
- The pair's structural orthogonality holds cross-regime
  (corr 0.39 / 0.23, drawdown timing asynchronous).
- The baseline-vs-tactical character allocation holds cross-regime.
- Both candidates beat SPY in both regimes — this is robust under
  any reasonable drift-replay-adjustment.

What canNOT be claimed at TD75:
- Strategic ranking between RCMv1 and Cand-2. The +5814 bps Cand-2
  excess vs SPY in 2022 includes ~7500 bps-day of cumulative drift
  noise. The replay-adjusted excess is meaningfully smaller; the
  dispersion around the headline is large enough that "Cand-2 leads
  by 2.4×" is not a sound conclusion.

Decisions deferred until after Cand-2 execution-layer investigation:
- All §3 "Candidate-3" assessment is unchanged (still NOT START), but
  for a sharper reason: we do not yet know how much of the existing
  pair's apparent diversification benefit is real signal vs
  execution-layer noise on Cand-2.
- The §1.2 mechanism narrative for RCMv1's regime-dependent factor
  selection (QUAL / MTUM in up-tape vs VLUE in bear) is still useful
  as observation, but should not motivate spec-redesign discussion
  until the drift question is resolved.

The TD75 cross-regime cadence (10/20/40/60/75 × 2 windows) is still
COMPLETE as a cadence; the next-step workstream switches off
checkpoint cadence and onto Cand-2 drift attribution. See
`docs/20260424-cand2_drift_attribution.md` (separate doc).

---

## 0. Headline (one table)

| Metric @ TD75 | 2024 up-tape RCMv1 | 2024 Cand-2 | 2022 bear RCMv1 | 2022 Cand-2 |
|---------------|-------------------:|------------:|----------------:|------------:|
| Paper cum ret | +16.64% | **+36.30%** | +18.57% | **+52.63%** |
| SPY cum ret | +6.47% | (shared) | -5.41% | (shared) |
| QQQ cum ret | +7.04% | (shared) | -8.86% | (shared) |
| Excess vs SPY | +1017 bps | **+2983 bps** | +2408 bps | **+5814 bps** |
| Excess vs QQQ | +960 bps | +2926 bps | +2998 bps | +6405 bps |
| Cum turnover | 16.80 | 41.30 | 15.20 | 44.80 |
| Active days | 38 / 75 | 67 / 75 | 40 / 75 | 68 / 75 |
| Total fills | (~95) | (~675) | 84 | 685 |
| Drift mean \|Δ\| | 3.63 bps | 23.07 bps | **0.00 bps** | **100.12 bps** |
| Drift max \|Δ\| | 26.02 | 174.89 | 0.00 | 197.49 |
| Days \|Δ\| > 50bps | 0 / 75 | **9 / 75** | 0 / 75 | **42 / 75** |
| Position-set diff days | 0 / 75 | 0 / 75 | 0 / 75 | 0 / 75 |
| Unique syms held | 31 | 58 | 33 | 62 |
| Top-5 weight-day share | 34.4% | 25.1% | 38.8% | 26.5% |

**TL;DR for the table**: Both candidates beat SPY in both regimes,
Cand-2 by a much larger margin in both. RCMv1 has zero drift cross-
regime; Cand-2 has structurally elevated drift that gets sharply
worse in the bear regime (12% breach → 56% breach). The signal layer
of both is bit-stable across all 4 runs (position-set diff = 0/75 in
every cell).

---

## 1. Cross-regime synthesis — 5 key findings

### 1.1 The orthogonality construction holds, in two senses

**Construction sense** (what we designed for at Phase E-post R6):
composite-correlation < 0.5; turnover relative diff ≥ 20%. Holds
loudly cross-regime:

| | 2024 | 2022 |
|---|---:|---:|
| Cum turnover ratio (Cand-2 / RCMv1) | 2.5× | 2.9× |
| Top-5 weight-days share | 34% / 25% | 39% / 27% |

**Live-data sense** (what we found at TD75): the daily excess vs SPY
series of the two candidates are weakly correlated in both regimes:

| Window | corr(daily excess RCMv1, daily excess Cand-2) | n |
|---|------:|--:|
| 2024 up-tape | **+0.385** | 46 |
| 2022 bear+recovery | **+0.225** | 46 |

Both well under 0.5. The candidates are MORE independent in bear
(0.225) than in up-tape (0.385) — they share less common drivers
under risk-off conditions. This is a positive finding: in the regime
that matters most for portfolio diversification, the pair has the
LEAST overlap.

Drawdown timing overlap (>100 bps DD of cum excess from peak):

| Window | both DD | RCMv1 only | Cand-2 only | neither |
|---|---:|---:|---:|---:|
| 2024 | 22 days | 18 | 3 | 32 |
| 2022 | 12 days | 17 | 6 | 40 |

Their excess paths drawdown asynchronously in both regimes. RCMv1 is
in DD more often "alone" than synchronized — the defensive composite
takes hits at moments different from when the tactical book does.

### 1.2 Cand-2 dominates excess vs SPY in BOTH regimes

This was a 2024-window-only suspicion at TD60; TD75 of the bear
window confirms it cross-regime:

| | 2024 TD75 | 2022 TD75 |
|---|---:|---:|
| RCMv1 excess vs SPY | +1017 bps | +2408 bps |
| Cand-2 excess vs SPY | **+2983 bps** | **+5814 bps** |
| Cand-2 / RCMv1 ratio | 2.9× | 2.4× |

Cand-2 captures more excess in both directions of market movement.
That's not what a textbook "tactical momentum vs defensive baseline"
pair is supposed to do — defensives normally have their moment when
the benchmark drops. Why doesn't RCMv1 catch up in the bear?

The 2024 TD60 ETF analysis flipped at 2022 TD60: in 2024 RCMv1's
ETF-day excess (+29 bps) > no-ETF excess (+1 bps); in 2022 it was
inverted (no-ETF +32 bps > has-ETF −11 bps). The mechanism:

- 2024 ETF mix: QUAL + MTUM + XLRE + SLV (~16% of weight-days in 2024
  TD75) — quality/momentum/REIT/silver, all participating in the
  tech-led rally
- 2022 ETF mix: VLUE only (~6% of weight-days in 2022 TD75) — value
  factor, lagged growth in the November 2022 rebound

So RCMv1's defensive thesis exists, but its **factor-selection
sub-decision** (VLUE > MTUM > QUAL > nothing-else) was wrong-footed
by the bear+recovery dynamics. The composite isn't broken; it's just
making a regime call that didn't play out optimally in this specific
2-month bear-recovery sequence.

This is a meaningful **finding for future RCMv1 spec design** but
NOT a revoke trigger.

### 1.3 Cand-2's drift signature is structural, not transient

| | 2024 TD75 | 2022 TD75 |
|---|---:|---:|
| Drift mean \|Δ\| | 23.07 bps | **100.12 bps** |
| Drift max \|Δ\| | 174.89 bps | 197.49 bps |
| Days > 50 bps | 9 / 75 (12%) | **42 / 75 (56%)** |

Per-bucket detail (TD25 / TD50 / TD75):

| 2024 Cand-2 | TD1-25 | TD26-50 | TD51-75 |
|---|---:|---:|---:|
| Mean \|Δ\| | 4.04 | 22.67 | 42.50 |
| Days > 50 | 0 | 1 | 8 |

| 2022 Cand-2 | TD1-25 | TD26-50 | TD51-75 |
|---|---:|---:|---:|
| Mean \|Δ\| | 29.22 | **142.36** | **128.78** |
| Days > 50 | 4 | 20 | 18 |

**Cand-2's drift is structurally amplified in bear by 4-5×**, and it
does NOT decay back even after the bear bottom passes. TD51-75 mean
of 128.78 bps in bear is comparable to TD26-50 mean of 142.36, which
covered the Oct 12 bottom region.

**But position-set diff = 0/75 cross all 4 cells**. The signal layer
is bit-stable. The drift is purely execution variance — fill prices
and cost timing diverge from the replay under sustained high turnover
+ high market volatility.

This is the strongest **candidate-specific** signal in the parallel-
paper exercise. It is NOT a revoke trigger (the signal layer is
reproducible, and the cumulative excess is +5814 bps even after
absorbing 100 bps mean drift). It is a strong call to:

- **Investigate the Cand-2 execution-layer model**. Is the fill-price
  approximation good enough at top-N=10 with 0.6 average daily
  turnover? Top-of-book vs VWAP vs T+1 open assumptions might need
  re-examination for high-vol days.
- **Elevate M14 NaN fix priority**. The 197 bps max in 2022 (and 175
  bps max in 2024) both correlate with high-vol days where M14's
  ghost-cleanup interaction may bias the equity calculation. A clean
  M14 fix may mechanically reduce the worst tails.

### 1.4 RCMv1's "zero drift" cross-regime is itself a finding

| | 2024 TD75 | 2022 TD75 |
|---|---:|---:|
| Drift mean \|Δ\| | 3.63 bps | **0.00 bps** |
| Days > 50 bps | 0 | 0 |

RCMv1 has **literally zero drift across all 75 days in the bear** —
mean 0.00, max 0.00, 0 days breaching threshold. With only 84 fills
over 75 days (vs Cand-2's 685) and 5+ symbols held continuously for
50+ days, there's effectively no execution surface for variance to
materialize.

In 2024 (slightly higher activity, 95 fills) RCMv1's drift mean was
3.63 bps and max 26 bps — also entirely under threshold but
non-zero. So RCMv1 is "always near zero drift", and the bear regime
**reduces** its drift further (because the composite goes more
defensive, holds positions longer, trades less).

This is an unintended feature of the defensive composite worth
documenting: **low turnover → near-perfect replay reproducibility**
regardless of regime. A baseline candidate should have this
property.

### 1.5 Both candidates' daily excess std nearly doubles in bear

| Window | RCMv1 daily excess std | Cand-2 daily excess std |
|---|---:|---:|
| 2024 up-tape | 153 bps | 132 bps |
| 2022 bear | **260 bps** | **237 bps** |
| Bear / up-tape ratio | 1.7× | 1.8× |

When the benchmark moves more, daily portfolio-vs-benchmark
deviation widens. This is mechanical, not character-changing. The
mean daily excess actually slightly INCREASES in bear for both
(RCMv1 +27 → +29 bps; Cand-2 +39 → +57 bps), so the std-up isn't
just losses widening but wins widening too.

**Skew flips for RCMv1**: +0.14 (2024) → +0.71 (2022). Strong
positive tail in bear — defensive holdings have outsized days when
SPY is dropping, while losses are smaller. This is on-thesis for
defensive composite.

**Cand-2 skew shifts from −0.12 (2024) to +0.26 (2022)**: improved
slightly, less negative tail in bear than 2024. Cand-2's bear-
recovery captures (TSLA / SOXL / TQQQ) provided some right-tail
days in November 2022.

---

## 2. PRD §8 decision-readiness — FINAL with both windows

### 2.1 Universe extension — **NOT YET**

- Cand-2: 58 unique syms in 2024, 62 in 2022. Both ~75% of the
  79-symbol universe. Not at saturation.
- RCMv1: 31 / 33 unique. Way under saturation; the defensive
  composite has small "core+rotation" pattern.
- Neither has shown signal failures or coverage-gap symptoms.
- Cross-regime confirmation: same shape in both windows.
- **No saturation signal. No universe-extension trigger.** Defer.

### 2.2 New mining round — **NOT YET**

- Both candidates produce alpha vs SPY and vs QQQ in BOTH regimes.
- The factor-selection sub-decision in RCMv1 (VLUE in bear vs
  QUAL/MTUM in up-tape) was sub-optimal in bear — this could
  motivate a refined RCMv2 spec, not a new mining round per se.
- No factor-space exhaustion. The composites are still pulling
  signal.
- **No new-mining trigger.** Defer.

### 2.3 New data tier — **NOT YET**

- All Cand-2 drift is execution-layer (position-set diff = 0/75).
- Data-integrity issue (BarStore split-adjustment, separately logged)
  is a fix-existing-tier matter, not new-tier.
- No data-tier starvation symptoms.
- **No new-data-tier trigger.** Defer.

---

## 3. Candidate-3 — final assessment at TD75

At 2024 TD60 and 2022 TD60 I recommended NOT starting Candidate-3.
TD75 cross-regime data lets me make a sharper call.

### 3.1 Arguments FOR starting Candidate-3

- **Cand-2 dominates in both regimes**. RCMv1's defensive thesis was
  expected to shine more in bear and didn't. A more pure-defensive
  C-3 (e.g. low-volatility USMV-driven, or a long-duration
  TLT-anchored) might fill that gap.
- **Both candidates are bursty**. Top-3 days = 24-26% of cum excess
  for both, in both regimes. A non-bursty (smooth-accumulator)
  candidate would fill a path-shape gap.
- **Cross-correlation is low**, but a 3rd candidate could make it
  even lower if chosen orthogonally to BOTH existing.

### 3.2 Arguments AGAINST starting Candidate-3 now

- **The current pair still works**. Both beat SPY decisively in
  both regimes. Replacing or augmenting them isn't urgent.
- **Cand-2's drift signature is the more pressing item**. 56% of
  bear days breach 50 bps. Investigating that (M14 fix? execution
  model review?) returns more value per unit effort than starting
  C-3 work, which would just put a third candidate on the same
  drift-amplifying execution surface.
- **2 regimes is still narrow**. Up-tape and bear+recovery are 2
  market characters; we haven't observed sideways-low-vol,
  capitulation, FOMC-day shocks, or extended grinding bear (multi-
  month). A C-3 chosen on this 2-window basis might overfit to
  these specific regimes' missing features.
- **3-cand attribution complexity**. Adding a candidate increases
  the parallel-paper analysis surface and dilutes drift / pair-
  comparison clarity. Premature given current open issues.

### 3.3 Trigger conditions (formalized)

I'd recommend opening Candidate-3 work only if **any** of:

1. **Cand-2 gets revoked** (its drift signature crosses some hard
   threshold or the M14 investigation reveals real bias). Then
   parallel-paper drops to 1 candidate, which is worse than 2 even
   with a placeholder.
2. **A 3rd market regime is observed and reveals a coverage gap**
   that neither RCMv1 nor Cand-2 addresses. Specifically:
   sideways-low-vol with no decisive direction; or extended grinding
   bear (multi-month).
3. **Specific economic theme gap is identified by analysis**.
   E.g. mean-reversion factors not present in either candidate's
   spec, or pure-low-volatility book missing.

**My TD75 recommendation: still NOT start.** Resolve Cand-2 drift
investigation first; collect a 3rd regime sample if/when it
naturally arrives in the data; revisit C-3 scope at that point.

---

## 4. The pair, in one paragraph

After 75 trading days × 2 regimes = 150 observations, the
baseline-vs-tactical pair is **structurally validated**: both
candidates produce alpha vs SPY in both an up-tape and a
bear+recovery; their daily-excess series are weakly correlated
(0.39 / 0.23) in both regimes; their drawdowns of cum excess are
asynchronous; their drift signatures are distinct (RCMv1 essentially
zero, Cand-2 high and bear-amplified); their portrait classes
(defensive ETF-hybrid baseline vs high-activity tactical momentum)
are confirmed cross-regime. **Two open items**: Cand-2's structural
drift, and RCMv1's regime-dependent factor-selection sub-decision.
Neither requires Candidate-3 to investigate; both are within the
existing pair's scope.

---

## 5. Status & next steps

- Both candidates remain at `S2_paper_candidate`. No revoke, no
  demote.
- pytest 1566/1/1. No code, config, schema, dependency, or registry
  changes anywhere in this exercise.
- 4 paper run dirs are gitignored; all metadata + analysis lives in
  `docs/`. The state snapshot
  (`docs/20260424-phase_state_snapshot.md`) reflects the post-TD75
  state.
- Data-integrity issue (BarStore split-adjustment for pre-2022-Aug
  windows) remains parked at
  `docs/20260424-data_integrity_2022_split_adjustment.md`. Not on
  the parallel-paper main line.

### 5.1 Open items flagged for user (not auto-actioned)

1. **Cand-2 drift investigation**. Recommend a focused look at the
   ExecutionSimulator fill-price model for high-vol days. Likely
   1-2 days work.
2. **M14 (BacktestEngine NaN / ghost-cleanup) elevation**. Fixing
   would likely collapse the 175-200 bps single-day Cand-2 drift
   tails. Already in the framework completion PRD as P2.
3. **RCMv1 factor-selection sub-decision review**. The QUAL→VLUE
   regime swap was internally consistent but VLUE was wrong-footed
   in November 2022. A clean post-mortem on the regime-detector +
   factor-selection logic might be valuable. ~0.5-1 day.
4. **Candidate-3 scope discussion** (when triggered per §3.3). Not
   now.

### 5.2 What NOT to do per current freeze

- No universe extension
- No new mining round
- No new data tier
- No Candidate-3 work
- No retroactive RCMv1 spec change without explicit user direction
  (frozen spec is a contract)

The parallel-paper cadence (10 / 20 / 40 / 60 / 75 across two
windows) is now COMPLETE. Next direction is up to user — the four
items in §5.1 are options, not auto-decisions.
