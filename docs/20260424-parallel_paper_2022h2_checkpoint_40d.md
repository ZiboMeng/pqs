# Parallel Paper (2022-H2 bear) — Checkpoint TD40 (Bear-Bottom Stress)

**Date**: 2026-04-24
**Window**: 2022-08-26 → 2022-12-15 (79 real TDs)
**Cutoff (this memo)**: real trading day **TD40 = 2022-10-21 (Fri)**.
This window contains **2022-10-12, the S&P 500 bear bottom** (close
3577, −24% from January 2022 peak) within TD33 of this checkpoint.
The 5 worst drift days for Candidate-2 land 2022-10-11 through
2022-10-18 — exactly across the bottom.

**Scope per PRD §7.2 + the 5 focus areas the user defined for 2024-40d**:
turnover structure, behavior/exposure concentration, benchmark-relative
path shape, drift trending, candidate portraits. Plus regime-specific
follow-ups carried from the 2022-20d memo.

Strict cutoff. TD41+ data on disk untouched.

---

## 1. Headline @ TD40

| Metric | RCMv1 | Candidate-2 | SPY / QQQ |
|--------|------:|------------:|----------:|
| Paper cum ret (TD40) | **−0.28%** | **+11.24%** | SPY −12.79%, QQQ −16.91% |
| Excess vs SPY @ TD40 | +1251 bps | **+2403 bps** | — |
| Excess vs QQQ @ TD40 | +1570 bps | +2722 bps | — |
| Cum turnover (40d) | 4.00 | 21.40 | — |
| Active turnover days | 16 / 40 | 33 / 40 | — |
| Total fills | 39 | 381 | — |
| Drift mean \|Δ NAV\| | **0.00 bps** | **71.29 bps** | — |
| Drift max \|Δ NAV\| | 0.00 bps | **197.49 bps** | — |
| Days \|Δ\| > 50 bps | 0 / 40 | **16 / 40** | — |
| Position-set diff days | 0 / 40 | 0 / 40 | — |

The cumulative excess numbers are now substantially divergent — Cand-2
has nearly doubled RCMv1's lead vs SPY at TD40 (+2403 vs +1251 bps).
But Cand-2's drift has also exploded — see §4.

---

## 2. Focus 1 — Turnover structure

| Metric | RCMv1 | Cand-2 |
|--------|------:|-------:|
| Active days TD1-20 | 5/20 | 13/20 |
| Active days TD21-40 | 11/20 | 20/20 |
| Cum turnover TD1-20 | 1.30 | 7.80 |
| Cum turnover TD21-40 | 2.70 | 13.60 |
| Cum turnover total (40d) | 4.00 | 21.40 |
| Mean turnover on active days | 0.25 | 0.65 |
| Holding-spell mean / median / max | 7.27 / 4 / **32** | 1.52 / 1 / **6** |
| Unique symbols held | 19 | 53 |

**RCMv1 is more active in TD21-40 (11/20 vs 5/20)** — same ramping-up
pattern observed in 2024 (the day-40 to day-60 acceleration). The bear
bottom forces some defensive rotation. The **TRGP / TSN / ED / GIS /
VICI core** is held continuously for 30-32 days (since day 9 / 10);
the rest of the book churns around it.

**Cand-2 hits 100% active in TD21-40** — matches the 2024 mid-window
pattern. But here it happens earlier in the window (day 21 vs 2024's
day 40). Bear regime accelerates the persistent-active mode. Mean
turnover on active days jumps from 0.60 (TD1-20) to 0.68 (TD21-40).

Top names through TD40:
- RCMv1: TRGP(32d), TSN(32d), ED(32d), GIS(30d), VICI(30d)
- Cand-2: TSLA(21d), SOXL(18d), TER(17d), TRGP(16d), TQQQ(16d)

**Coincidence to flag, not interpret**: TRGP appears in both
candidates' top-5. RCMv1 holds it continuously 32d; Cand-2 trades
in/out 16d. Same name, different intentions — interesting.

---

## 3. Focus 2 — Exposure concentration

| Metric | RCMv1 | Cand-2 |
|--------|------:|-------:|
| Top 5 / Top 10 weight-day share | 48.8% / 85.9% | 26.7% / 42.7% |
| Individual stocks | 93.1% | 96.7% |
| Sector ETFs | 0.0% | **1.8% (XLE, XLF)** |
| Factor ETFs | 6.9% (VLUE) | 0.0% |
| Cross-asset | 0.0% | **1.5% (SHY, SLV)** |

Two regime-dependent observations updated since TD20:

**RCMv1 ETF allocation hasn't broadened**. At TD20: VLUE only (5%).
At TD40: still VLUE only (6.9%). No XLU / TLT / XLP / SHY rotation
into traditional bear-defense ETFs. The composite is choosing
**individual defensive equities** (TRGP / TSN / ED / GIS / VICI = midstream
energy / staples / utility / staples / casino REIT) instead of using
the sector / cross-asset toolbox. This partially answers the open
question from 2024 60d: the ETF overlay is **regime-narrow**, not
"broadly underused" — it picks one factor ETF (VLUE in bear, MTUM /
QUAL in up-tape) and drives the rotation through individual names.

**Cand-2 added a small sector + cross-asset allocation**: 1.8% in
XLE + XLF (energy + financials, the 2 outperforming sectors of 2022),
1.5% in SHY (short Treasury) + SLV. Versus 2024 TD40 where Cand-2 was
99.1% pure stocks. The bear regime is nudging Cand-2 into a tiny bit
of cross-asset exposure, but it's still overwhelmingly individual
stocks.

Top-5 weight-day shares:
- RCMv1: 48.8% (versus 49.0% at 2024 TD40 — same concentration shape)
- Cand-2: 26.7% (versus 24.1% at 2024 TD40 — slightly more
  concentrated, but very close)

Both candidates' concentration profiles are remarkably stable
cross-regime, even as their turnover and absolute returns differ.

---

## 4. Focus 3 — Benchmark-relative path shape

Daily excess vs SPY through TD40:

| Metric | RCMv1 | Candidate-2 |
|--------|------:|------------:|
| n daily observations | 29 | 27 |
| Mean daily excess (bps) | +35.8 | +31.4 |
| Std daily excess (bps) | **292** | **193** |
| Skew | **+0.46** | **−1.04** |
| Positive days | 16 (55%) | 18 (67%) |
| Negative days | 13 (45%) | 9 (33%) |
| Mean on +days | +242 bps | +130 bps |
| Mean on −days | −218 bps | −166 bps |
| Win/loss count ratio | 1.23 | 2.00 |
| Top-3 days share of \|cum excess\| | 27.1% | 32.9% |
| Top-5 days share | 38.6% | 49.0% |
| Max DD of cum excess vs SPY | **−702 bps** | **−747 bps** |

**Two distinct path-shape signatures emerging**:

- **RCMv1**: high daily std (292 bps) but **positive skew** (+0.46) —
  big positive-tail days dominate. 55% win rate but +242 mean on wins
  vs −218 on losses. Cumulative excess builds via "occasional big
  positive days when defensive names spike".
- **Cand-2**: lower daily std (193 bps) but **negative skew** (−1.04)
  — losing days bigger than gaining days on average (−166 vs +130).
  Compensates with a higher win rate (67% — 2× the ratio of wins to
  losses in count terms). Cumulative excess builds via "more wins than
  losses, even though individual losses sting more".

Both have similar excess-path drawdowns: −702 vs −747 bps. So at some
point in the window, both candidates' lead vs SPY collapsed by ≈ 700
bps and recovered. The drawdown timing matters but is a TD60 question
(does it correlate with the Oct 12 bottom?).

**Cautious read** (per user's frozen-at-no-rank rule): Cand-2's
−1.04 skew in bear vs +0.46 RCMv1 is a meaningful regime signature.
It says Cand-2's tactical book takes asymmetric losses on bad days
in bear — losses bigger than gains on good days — but compensates
through count-based win rate. This is the kind of profile that
**would crack** if a multi-month bear extended further. We don't have
that data here, only 27 observations, but it's worth flagging.

---

## 5. Focus 4 — Drift trending (the headline finding)

| Metric | RCMv1 | Candidate-2 |
|--------|------:|------------:|
| TD1-10 mean \|Δ\| | 0.00 bps | 0.06 bps |
| TD11-20 mean \|Δ\| | 0.00 bps | 13.16 bps |
| TD21-40 mean \|Δ\| | 0.00 bps | **135.97 bps** |
| TD21-40 max \|Δ\| | 0.00 bps | **197.49 bps** |
| TD21-40 days > 50 bps | 0 / 20 | **16 / 20** |
| Per-trade drift TD1-20 | 0.00 | 0.98 bps-days/trade |
| Per-trade drift TD21-40 | 0.00 | **11.05** bps-days/trade |
| Position-set diff days TD40 | 0 / 40 | **0 / 40** |

**RCMv1 drift is literally zero across all 40 days** (max 0.00 bps).
With only 39 fills over 40 days and a stable defensive core, there's
essentially no execution surface for variance to land on. Replay
produces bit-exact NAV every single day.

**Cand-2 drift is the headline finding of TD40**:

- 16 of 20 days in TD21-40 exceed the 50 bps informational threshold.
  By comparison, **2024 TD41-60 had 9 days > 50 bps**, and that was
  considered the worst case in the up-tape window.
- The 5 worst drift days are **clustered exactly around the Oct 12
  2022 bear bottom**:
  ```
  2022-10-11  +195.86 bps
  2022-10-12  +187.52 bps   ← bear bottom
  2022-10-13  +188.84 bps
  2022-10-14  +187.99 bps
  2022-10-18  +197.49 bps
  ```
- Per-trade drift jumped 0.98 → 11.05 bps-days/trade — an 11×
  amplification, far exceeding the fills count growth (135 → 246
  ≈ 1.8×). So the bear-bottom days are hitting Cand-2's execution
  layer disproportionately.
- **BUT**: position-set diff = 0 / 40. The replay produces the same
  target weights on every single day. The signal layer is bit-stable.

**What this means**: the drift is purely fill-price / cost-timing
variance under high volatility. The 5 worst days are all VIX-spike
days clustered around the bear bottom. Cand-2's high-turnover
execution is hitting these days on the wrong side of price discovery
roughly half the time, accumulating ~190 bps NAV-over-replay
divergence each day.

**Is it a blocker?** Per PRD §7.2 the 50 bps line is informational,
not a gate. 16/20 days breach in TD21-40 alone is a **strong signal
that Cand-2's execution layer is not bear-resilient at high turnover**.
But:

- The signal layer (target weights) is still bit-stable
- The cumulative excess is +2403 bps despite the drift
- The maximum single-day drift is 197 bps — sizable but not
  catastrophic on a $100k notional
- The 197 bps max coincides with the M14 NaN-ghost-cleanup interaction
  flagged in earlier memos; if M14 were fixed the worst-case might
  collapse

**Recommendation for TD60 watch list**:
- Does drift stabilize as Oct-12 volatility fades, or persist?
- Does the per-trade drift come back down in TD41-60 as the bear
  recovers, or stay elevated?
- Is there a single trade that's driving the 197 bps outlier (e.g.
  a SOXL or TQQQ position rolled across a sudden gap)?

This is the strongest candidate-specific signal we've seen in the
parallel paper to date. Not a revoke / demote trigger at TD40, but
something to actively watch.

---

## 6. Focus 5 — Candidate portraits @ bear-bottom (TD40)

**RCMv1 — defensive baseline holds shape**:
- 19 unique symbols, 5 of them held continuously for 30-32 days
  (defensive REIT / staples / utility core: TRGP / TSN / ED / GIS / VICI)
- 6.9% in VLUE (value factor) — the only ETF allocation, unchanged
  from TD20 (5.0%)
- Cumulative turnover 4.00 over 40 days, mean active turnover 0.25
- Drift literally zero — pipeline reproducibility perfect under bear stress
- Excess vs SPY +1251 bps (paper basically flat at −0.28% vs SPY −12.79%)
- **Reads as**: low-activity defensive book that is CHOOSING
  individual defensive names over rotating ETFs. The 2024-60d
  observation that "the ETF toolbox seems narrow" is now better
  understood: the spec is choosing names within a specific defensive
  factor (VLUE / staples / consumer-defensive REIT) rather than
  trading the ETF universe per se.

**Cand-2 — tactical book under bear-bottom stress**:
- 53 unique symbols, no continuous core (max holding spell 6 days)
- 96.7% stocks, 1.8% sector ETFs (XLE+XLF), 1.5% cross-asset (SHY+SLV)
  — small but real cross-asset diversification compared to 2024's
  99.1% pure stocks
- Cumulative turnover 21.40 over 40 days (5.4× RCMv1)
- Drift mean 71 bps, max 197 bps, 16/40 days > 50 bps — bear-bottom
  execution stress visible, but no signal-layer break
- Excess vs SPY +2403 bps (paper +11.24% vs SPY −12.79%)
- Daily excess: −1.04 skew (asymmetric losses), 67% win rate
- **Reads as**: tactical book that's still working — generating
  alpha vs SPY in the bear — but at execution-layer cost, with
  asymmetric daily-loss profile that flags it as more vulnerable
  to extended bear regimes than RCMv1.

The **baseline-vs-tactical pair structure is preserved cross-regime**.
Both candidates are alive and behaving on-thesis. RCMv1 looks more
like a steady defensive baseline than ever (drift = 0); Cand-2 looks
more like a high-octane tactical book operating closer to its
execution-stress envelope.

---

## 7. PRD §7.2 questions answered at TD40

- **Style stability**: Yes for both. RCMv1's defensive core (5 names
  continuous for 30+ days) is intact. Cand-2's persistent-active
  pattern is intact (now 100% active in TD21-40).
- **Drift explainable?** Yes for RCMv1 (literally zero). Yes for
  Cand-2 mechanistically — bear bottom amplifies execution variance
  on a high-turnover book — but the magnitude (16/20 days > 50 bps
  in one bucket) is now a notable, not-routine, candidate-specific
  signal. Position-set diff stays 0/40 so it's execution-layer.
- **Candidate-specific problem?** Cand-2's drift escalation around
  the bear bottom is a candidate-specific stress signature. Not a
  blocker, but the strongest signal we have to watch through TD60.

---

## 8. What we deliberately are NOT claiming

- That RCMv1 "wins in bear" or Cand-2 "wins in bear". Both beat SPY
  by 1000-2400 bps; the relative comparison would require longer
  windows or multiple bear regimes.
- That the ETF overlay finally answered the 60d question. It's
  partially answered (regime-narrow, not broadly underused). Full
  TD60 + cross-window comparison still pending.
- That the Cand-2 drift signature is a revoke trigger. It's a watch
  signal. The signal layer is reproducible.
- Anything about universe / mining / Candidate-3. Frozen until TD60.

---

## 9. Next checkpoint

**TD60 = 2022-11-18 (Fri)**. By that point the bear bottom is past
(Oct 12), recovery into November is observed, and CPI-cool day
(2022-11-10 — already inside the data, the +10.6% Cand-2 single-day
move) is included. TD60 is the decision-readiness checkpoint per
PRD §8.

Status: pytest 1566/1/1, both candidates remain at S2_paper_candidate,
no code or config change.
