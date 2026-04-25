# Parallel Paper — Checkpoint 40d (Style Stability & Portraits)

> **Post-step-3b caveat (added 2026-04-25)**: NAVs / drift bps /
> trade counts / specific dates cited in this memo are **pre-step-3b**.
> Post-rebuild canonical numbers for the four paper cells live in
> TD75 §0c. Specific dates here are BarStore-label dates;
> under the rebuilt store every weekday is a real ET trading day.
> See `docs/memos/20260425-data_integrity_round3_step3b_complete.md`.

**Date**: 2026-04-24
**Window**: 2024-01-02 → 2024-02-28 (first 40 real trading days of the
matched 2024-01-02 → 2024-04-01 paper window)
**Cutoff rule**: analysis strictly stops at **real trading day 40 = 2024-02-28
(Wed)**. 60d data remains untouched.

## 0. Retroactive correction to the 20d memo

The signals / target-portfolio / turnover CSVs include Saturday pad rows
(index entries with NaN signals, carried forward from Friday's positions).
The 20d memo (`docs/20260424-parallel_paper_checkpoint_20d.md`) used raw
index position 20, which landed on **2024-01-25 (Thu) = real trading day
17**, not real TD 20.

Real TD 20 is **2024-01-30 (Tue)**.

The 20d memo's findings still stand qualitatively (turnover divergence
clear, drift explainable, no candidate-specific problems). The numbers
are for ~17 real trading days of data, which does not change any
conclusion.

All subsequent checkpoints in this series use the weekday-filtered
trading-day convention. Day 40 = **2024-02-28 (Wed)**. Day 60 target
= approximately **2024-03-27 (Wed)**.

---

## 1. Focus area results (40d cutoff)

### 1.1 Turnover structure

| Metric | RCMv1 | Candidate-2 | Ratio |
|--------|------:|------------:|------:|
| Active turnover days | 15 / 40 | 32 / 40 | 2.1× |
| Mean turnover on active days | 0.31 | 0.60 | 1.9× |
| Median / std | 0.30 / 0.13 | 0.60 / 0.21 | — |
| Max single-day turnover | 0.70 | 0.90 | — |
| Cumulative turnover (40d) | 4.60 | **19.20** | **4.2×** |
| Mean gap between active days | 2.93 d | 1.52 d | — |
| Unique symbols ever held | 22 | 52 | 2.4× |
| Mean holding spell | 5.85 d | 1.67 d | — |
| Median holding spell | 1 d | 1 d | — |
| Max holding spell | **31 d** | 7 d | — |

Turnover structure is now **clearly bimodal**, not just quantitatively
different:

- RCMv1 has **core holdings**: `VICI` (31d), `TSN` (31d), `ED` (30d),
  `DG` (30d), `GIS` (30d) — all held continuously since day 10. The
  remaining portfolio churns around these.
- Candidate-2 has **no equivalent core**: top holdings are `TSLA` (18d),
  `SOXL` (18d), `NVDA` (16d), `TQQQ` (13d), `TRGP` (12d) — each held for
  less than half the window. Median holding is 1 day.

Both candidates have filled 100% of their `40_days × 10_slots = 400` slot
budget (no empty slots post-warmup), so the slot-churn difference is
purely about how many unique names cycle through.

### 1.2 Behavior / exposure concentration

| Metric | RCMv1 | Candidate-2 |
|--------|------:|------------:|
| Top-5-symbols share of cumulative weight-days | 49.0% | 24.1% |
| Top-10-symbols share | 85.2% | 41.6% |
| Individual stocks share of weight-days | 80.3% | **99.1%** |
| Sector ETFs share | 6.1% | 0.9% |
| Factor ETFs share | 9.4% | 0.0% |
| Cross-asset share | 4.2% | 0.0% |

**This is the first checkpoint where the two candidates diverge on
something other than activity level.** Exposure signatures are
economically distinct:

- **RCMv1** allocates ~20% of weight-days to non-equity-single-name
  instruments: XLRE (real estate), MTUM + QUAL (factor ETFs), SLV
  (silver). This is what a defensive / regime-aware composite is
  expected to do — it uses ETFs as a bucket for when its factor signals
  point at themes rather than at individual names.
- **Candidate-2** is 99.1% individual stocks. Among those, 52 different
  tickers each get some weight. The top-10 share (41.6%) is under
  half — this is a broadly distributed, high-rotation book.

Weight-day concentration (top 5 / top 10) confirms RCMv1 is structurally
**more concentrated on a small set of names** (49% / 85%) while
Candidate-2 **diffuses across many names** (24% / 42%).

Per the user's request, "by-construction" top-1 / top-3 equal-weight
metrics (both still 0.10 / 0.30) are no longer informative. This
behavior / exposure concentration view replaces them from 40d onward.

### 1.3 Benchmark-relative path shape

| Metric | RCMv1 | Candidate-2 |
|--------|------:|------------:|
| Daily excess vs SPY: mean | +5.5 bps | +23.2 bps |
| Daily excess vs SPY: std | 149.7 | 131.5 |
| p10 / p25 / med / p75 / p90 | −166 / −76 / −7 / +57 / +194 | −123 / −35 / +12 / +104 / +150 |
| min / max | −278 / +360 | −308 / +384 |
| Top-3 days share of \|cumulative excess\| | 32.9% | 35.6% |
| Top-5 days share | 46.6% | 49.2% |
| Cumulative @ cutoff: paper ret / SPY / QQQ | +7.92% / +7.27% / +8.65% | +17.52% / +7.27% / +8.65% |
| Excess vs SPY / QQQ @ cutoff | +65 bps / −73 bps | **+1025 bps** / **+887 bps** |

Both candidates have bursty, NOT smooth, excess-return paths: ~33-35%
of cumulative \|excess\| comes from the top 3 days. This pattern matches
how active cross-sectional strategies typically behave on a short
horizon (long tails).

RCMv1's excess vs SPY has higher *daily volatility* (std 150 bps vs
132 bps) but its *cumulative* excess collapsed from +243 bps at day-20
to +65 bps at day-40 — it gave back the day-20 lead against SPY.
Against QQQ it's now −73 bps.

Candidate-2's cumulative excess kept accumulating: vs SPY +490 → +1025
bps, vs QQQ +183 → +887 bps. The window 2024-01-02 → 2024-02-28 was
a strong up-tape led by mega-cap tech (QQQ +8.65% vs SPY +7.27%);
Cand-2's tech/momentum overweight captured that cleanly.

**Cautious interpretation (per user direction: no優劣 conclusions at 40d)**:
RCMv1 looks like it's struggling to keep up with QQQ in a tech-led
market. Cand-2 looks like it's riding the tech rally hard. **But this
is 40 trading days on a single up-tape regime.** Both candidates need
to be seen on a drawdown window before the shape interpretation is
credible.

### 1.4 Drift trending

| Metric | RCMv1 | Candidate-2 |
|--------|------:|------------:|
| Mean \|Δ NAV\| (40d) | 0.67 bps | 11.48 bps |
| Max \|Δ NAV\| | 3.15 bps | **51.77 bps** |
| Days with \|Δ\| > 50 bps | 0 / 40 | **1 / 40** |
| First-half (day 1-20) mean \|Δ\| | 0.33 | 3.62 |
| Second-half (day 21-40) mean \|Δ\| | 1.01 | 19.35 |
| Second-half / first-half ratio | 3.1× | 5.3× |
| Fills cumulative (40d) | 33 | 320 |
| Per-trade drift | 0.81 bps-days/trade | 1.44 bps-days/trade |
| Position-set diff days | **0 / 40** | **0 / 40** |
| weight_l1_diff mean / max | 0.0000 / 0.0000 | 0.0000 / 0.0000 |

**Drift IS trending up for both candidates**. RCMv1's second-half mean
is 3.1× the first-half; Cand-2's is 5.3×. Candidate-2 crossed the 50 bps
informational threshold on day 40 itself (51.77 bps on 2024-02-28). One
day at threshold, not a pattern yet.

Key safety fact: **position-set diff remains 0 / 40 for both**. The
target weights that the paper run recorded match bit-exactly with a
fresh replay on every single day — there is no signal-layer
reproducibility problem. All drift is execution-layer.

Per-trade drift is still within the same order of magnitude:
0.81 vs 1.44 bps-days/trade — consistent with Cand-2's higher turnover
amplifying aggregate drift. The fact that per-trade drift has grown
from 0.21 / 0.36 (day 20) to 0.81 / 1.44 (day 40) is a ~3.5-4× scale-up
for both, suggesting the growth is about cumulative compound effect,
not a divergent pipeline bug.

**Not a blocker at 40d, but watch at 60d**:
- Is Candidate-2 crossing 50 bps more frequently?
- Is the per-trade drift continuing to climb or stabilizing?
- Does position-set diff stay at zero?

### 1.5 Candidate portraits

Based on the 40d evidence, the two candidates now have clearly
different live signatures:

**RCMv1 — defensive / slow / concentrated / ETF-hybrid**

- 22 unique symbols ever held; **5 names held continuously since day 10**
  (VICI, TSN, ED, DG, GIS — REIT / utility / staples / restaurants /
  packaged food). Defensive sector tilt visible.
- 20% of weight-days in sector / factor / cross-asset ETFs
  (XLRE + MTUM + QUAL + SLV). Acts like it's using ETFs as a risk
  overlay.
- 4.6 cumulative turnover over 40d — trades on 38% of days with mean
  0.31 per active day.
- Drift metrics tiny: mean 0.67 bps, max 3.15 bps.
- Daily excess vs SPY is volatile but low-biased; cumulative went
  +243 → +65 bps over days 21-40 (gave back in an up-tape).
- **Fits "steady defensive baseline" archetype**. Expected to lag in
  strong bull QQQ-led runs. Will need a drawdown window to see its
  downside-protection thesis play out.

**Candidate-2 — active / diffuse / stock-heavy / momentum-riding**

- 52 unique symbols ever held; no continuous-since-day-10 core. Top
  holdings TSLA / SOXL / NVDA / TQQQ / TRGP rotate in and out with
  ~1-day median holding.
- 99.1% individual stocks, 0.9% one sector ETF (XLE), zero factor /
  cross-asset ETFs.
- 19.2 cumulative turnover (4.2× RCMv1) — trades on 80% of days with
  mean 0.60.
- Drift metrics higher: mean 11.48 bps, max 51.77 bps (one 50-bps day).
- Daily excess vs SPY: lower daily std than RCMv1 (132 vs 150 bps) but
  upward-biased; cumulative went +490 → +1025 bps — kept extending in
  the up-tape.
- **Fits "high-activity tactical momentum" archetype**. Riding the
  tech-led rally visible in QQQ +8.65%. Will likely experience the
  opposite dynamic on a tech-led drawdown.

The **portrait divergence is real and on-design**. Neither candidate
shows any sign of its live behavior contradicting its frozen spec
(`data/research_candidates/*.yaml`). Both are behaving as their factor
families predicted.

---

## 2. PRD §7.2 continuation answers

- **Q1 (turnover / concentration diverging?)**: Turnover — 4.2×
  divergence, even more pronounced than 20d. Concentration — equal-
  weight top-1/top-3 still by-construction identical, but
  **behavior/exposure concentration is clearly different** (RCMv1 49%
  top-5 share vs Cand-2 24%; RCMv1 20% ETF allocation vs Cand-2 1%).
- **Q2 (drift explainable?)**: Drift is trending up for both, roughly
  in proportion to their fills ratio. Per-trade drift still same order
  (0.81 vs 1.44). Position-set diff still 0 / 40 on both. One 50-bps
  day on Cand-2; not a pattern. Explainable, but needs 60d to see if
  the trend continues or stabilizes.
- **Q3 (candidate-specific problem?)**: None at 40d. The known M14
  `final_equity = NaN` continues to surface on both runs (framework-
  wide, not candidate-specific).

---

## 3. What deliberately not done at 40d

Per user direction:

- No "RCMv1 vs Candidate-2 is better / worse" call. At 40d both are
  behaving exactly as their construction intended, and the window
  (2024-01 → 2024-02) is a single-regime up-tape. Judgment on which
  style survives drawdown requires different data.
- No universe extension / new mining / new data tier discussion.
  Nothing observed at 40d triggers an exception to that freeze.
- No peek at day 41-60 data; that remains the 60d checkpoint's job.

---

## 4. Registry + code state

Both candidates remain at `S2_paper_candidate`. No revoke, demote, or
production-config change. pytest unchanged at 1566 / 1 / 1. No code
or schema edits.

A refreshed phase-state snapshot (`docs/20260424-phase_state_snapshot.md`)
accompanies this memo.

---

## 5. Next checkpoint (60d)

Target cutoff **2024-03-27 (Wed)** = real trading day 60. Focus will be
(per PRD §7.3 60-day scope):

- Full-window comparison of the two candidates on matched metrics
  assembled across 10d / 20d / 40d / 60d.
- Decision-readiness for "next research path" question (PRD §8.1 / §8.2
  / §8.3): is the paper feedback now sufficient to answer whether
  universe extension / new mining / new data tier is warranted?
- Whether either candidate's drift breach count (days > 50 bps) or the
  trending shape crosses a judgment threshold requiring revoke /
  demote.

No extra data collection needed for 60d — `data/paper_runs/*` already
contains it.
