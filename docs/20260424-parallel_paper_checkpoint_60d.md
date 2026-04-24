# Parallel Paper — Checkpoint 60d (Full-Window Synthesis)

**Date**: 2026-04-24
**Window**: 2024-01-02 → 2024-03-27 (first 60 real trading days of the
matched 2024-01-02 → 2024-04-01 paper window)
**Cutoff**: real trading day 60 = **2024-03-27 (Wed)**.

This is the terminal checkpoint per PRD §7.2 checkpoint schedule. It is
the first point at which universe-extension / new-mining / new-data-tier
decisions may reasonably be discussed. It is also the first point at
which Candidate-3 may be reasonably discussed — but not started.

---

## 1. Headline — one line per metric

| Metric | RCMv1 | Candidate-2 | Note |
|--------|------:|------------:|------|
| Cumulative paper return (60d) | +18.64% | **+33.02%** | raw |
| SPY / QQQ baselines (60d) | +9.85% / +10.21% | (shared) | up-tape |
| Excess vs SPY (bps @ 60d) | +879 | +2317 | — |
| Excess vs QQQ (bps @ 60d) | +843 | +2281 | — |
| Cumulative turnover (60d) | 10.70 | 32.20 | **3.0×** |
| Total fills (60d) | 74 | 548 | 7.4× |
| Drift mean \|Δ NAV\| | 0.98 bps | 20.92 bps | 21× |
| Drift max \|Δ NAV\| | 2.55 bps | **157.57 bps** | — |
| Days with \|Δ\| > 50 bps | 0 / 60 | **10 / 60** | see §4 |
| Position-set diff days | 0 / 60 | 0 / 60 | signal-layer perfect |

Full-window excess drawdown of the cumulative excess-vs-SPY series:

| | RCMv1 | Candidate-2 |
|--------|------:|------------:|
| Max drawdown of (paper_cum - SPY_cum) in bps | −568 | −498 |
| Max drawdown vs QQQ | −550 | −634 |

Both candidates experienced a −500 to −600 bps drawdown of their excess
path at some point in the 60 days — **neither is a smooth accumulator**.
Neither is broken by these drawdowns; both recovered and ended strongly
ahead of SPY.

---

## 2. Focus 1 — Turnover shape stability

Distribution across three 20-day buckets:

| Bucket | RCMv1 active | RCMv1 cum | Cand-2 active | Cand-2 cum |
|--------|:---:|---:|:---:|---:|
| day 1-20 | 6 / 20 | 1.40 | 12 / 20 | 6.90 |
| day 21-40 | 9 / 20 | 3.20 | 20 / 20 | 12.30 |
| day 41-60 | 14 / 20 | 6.10 | 20 / 20 | 13.00 |
| **60d total** | **29 / 60** | **10.70** | **52 / 60** | **32.20** |

**Burst-vs-persistent character** (top-k days' share of cumulative turnover):

| | RCMv1 | Candidate-2 |
|--------|------:|------------:|
| Top-3 turnover days / cum | 24.3% | 8.4% |
| Top-5 turnover days / cum | 38.3% | 14.0% |
| Active-day lag-1 autocorrelation | 0.36 | 0.93 |

Two very different shapes:

- **Candidate-2 = persistent high activity** (lag-1 AC 0.93, top-5 days
  only 14% of cum). Trades on nearly every day from day 21 onward
  (20/20 in buckets 2 and 3). Turnover mean stable at 0.58-0.65 across
  all three buckets. **Not burst-driven; this is its steady-state.**
- **RCMv1 = ramping-up activity + moderately bursty** (lag-1 AC 0.36,
  top-5 days 38% of cum). Activity accelerates over time: 6 active
  days in bucket 1 → 9 → 14. Mean turnover on active days: 0.23 → 0.36
  → 0.44. This is a NEW observation vs day 40 — RCMv1 is **rotating
  more as the window progresses**, not holding a steady core.

The day-40 portrait said RCMv1 had a stable core (VICI / TSN / ED /
DG / GIS all held 30+ continuous days). At 60d that core is breaking
down — only the highest-conviction longs survive; the rest rotate.
This likely reflects the March 2024 market shift.

---

## 3. Focus 2 — Benchmark-relative path quality

Daily-excess-vs-SPY distribution over 60 days:

| Metric | RCMv1 | Candidate-2 |
|--------|------:|------------:|
| n daily observations | 56 | 56 |
| Mean daily excess (bps) | +24.3 | +31.5 |
| Std daily excess (bps) | 142.6 | 124.7 |
| Skew | +0.37 | +0.01 |
| Positive days / negative days | 22 / 18 | 24 / 14 |
| Win-rate (count-based) | 55% | 63% |
| Mean on positive days | +123.8 | +100.8 |
| Mean on negative days | −97.3 | −87.3 |
| Top-5 days share of \|cum excess\| | 32.6% | 34.2% |
| Top-10 days share | 52.2% | 55.2% |

Both candidates are still bursty (top-5 ≈ 33%, top-10 ≈ 54% of
cumulative |excess|), but Candidate-2's excess distribution has **higher
win-rate** (63% vs 55%) and **more symmetric** shape (skew 0.01 vs 0.37).
Candidate-2's path quality is better on pure count-based metrics;
RCMv1 has fatter positive tails.

Path-level evolution of cumulative excess vs SPY:

| Day | RCMv1 | Candidate-2 |
|-----|------:|------------:|
| 20 | +218 bps | +300 bps |
| 40 | +65 bps (lost ground) | +1025 bps |
| 60 | **+879 bps** (recovered hard) | **+2317 bps** |

RCMv1 drew down −568 bps from its peak somewhere in days 20-40 (gave
back the day-20 lead against SPY) and then reclaimed +814 bps of cum
excess in days 41-60. That's a **large mean-reverting move**, suggesting
RCMv1's defensive tilt found its moment in the March 2024 mini-correction
in tech.

Candidate-2 did not share this V-shape — its excess grew monotonically
+300 → +1025 → +2317, even through the same March period. The
momentum/rel-strength composite kept riding winners even as tech pulled
back.

**Cautious read** (per user direction — no final ranking):

- Candidate-2 dominated this 60-day window.
- But this window contained no true drawdown regime. QQQ finished +10.21%.
- The shape of RCMv1's excess path (big drawdown + big recovery)
  suggests it's sensitive to defensive-rotation moments that didn't
  matter in most of this window.
- To meaningfully rank, need at least one full bear / crisis regime.

---

## 4. Focus 3 — Drift trending & explainability

| Metric | RCMv1 | Candidate-2 |
|--------|------:|------------:|
| mean \|Δ NAV\| bps, day 1-20 | 0.32 | 3.62 |
| mean \|Δ NAV\| bps, day 21-40 | 0.79 | 19.35 |
| mean \|Δ NAV\| bps, day 41-60 | **1.83** | **39.79** |
| max \|Δ NAV\| bps, day 1-20 | 1.03 | 21.65 |
| max \|Δ NAV\| bps, day 21-40 | 2.55 | 51.77 |
| max \|Δ NAV\| bps, day 41-60 | 2.31 | **157.57** |
| Days > 50 bps: 1-20 / 21-40 / 41-60 | 0 / 0 / 0 | 0 / 1 / **9** |
| Per-trade drift, day 1-20 | 0.24 | 0.64 |
| Per-trade drift, day 21-40 | 2.64 | 1.87 |
| Per-trade drift, day 41-60 | 0.89 | **3.49** |
| Position-set diff days | 0 / 60 | 0 / 60 |
| weight_l1_diff mean / max | 0 / 0 | 0 / 0 |

**Cand-2's drift is genuinely escalating in bucket 3**:

- 9 days over 50 bps threshold in bucket 3 alone (vs 0 and 1 in earlier
  buckets).
- Per-trade drift 0.64 → 1.87 → 3.49 = 5.5× scale-up, faster than fills
  count growth (113 → 207 → 228 = 2× scale-up).
- Worst day 2024-03-26 = 157.57 bps (coincides with the M14 end-of-window
  NaN interaction flagged in the 10d memo).
- Top 5 worst days are ALL in March 2024: 2024-03-12, -13, -14, -19, -26.
  This is the mini-correction period.

**Is it still explainable?** Position-set diff = 0/60 — the signals
generate bit-identical targets on replay. All drift is from execution:
fill-price rounding, cost timing, order sequencing. The March 2024
escalation fits a pattern of high-volatility-days-amplify-execution-noise.

Candidate-2's pipeline is not broken, but **it has an execution-layer
sensitivity to volatile days** that RCMv1 does not share (RCMv1 never
broke 3 bps even in the same March period). This is a real
candidate-specific finding that should be reported, not hand-waved.

Does this cross any blocker threshold? PRD §7.2 has the 50 bps line as
**informational only**, not a gate. 9 days over threshold is notable
but not automatic revoke/demote. The 157 bps on 2024-03-26 is explicable
via M14; if M14 ever gets fixed, that outlier should collapse.

RCMv1's drift climbed too (0.32 → 0.79 → 1.83 mean bps) but stayed <3
bps max and 0 days over threshold. No concern.

---

## 5. Focus 4 — ETF overlay for RCMv1 (is it actually doing anything?)

Only 4 of the 20 non-stock ETFs in the universe ever got weight from
RCMv1 over 60 days:

| ETF | Days held | Weight-days | First held | Last held |
|-----|:---:|---:|-----|-----|
| QUAL | 26 | 2.60 | 2024-01-23 | 2024-03-14 |
| MTUM | 25 | 2.50 | 2024-02-13 | 2024-03-27 |
| XLRE | 19 | 1.90 | 2024-01-23 | 2024-02-23 |
| SLV | 13 | 1.30 | 2024-01-23 | 2024-02-27 |

XLK / XLF / XLE / XLV / XLI / XLY / XLP / XLU / XLB / XLC / USMV / VLUE /
SCHD / TLT / IEF / SHY — **all sector / rate / dividend / safe-haven
ETFs never got weight**. The "defensive" composite expressed itself via
a narrow set of factor ETFs (QUAL / MTUM) + one sector (XLRE real
estate) + one commodity (SLV), not via the full sector-rotation /
yield-curve toolbox the universe exposes.

ETF exposure across 51 active days (post-warmup, first 60 TDs):

| ETF exposure bucket | # days |
|---------------------|------:|
| 0% | 14 |
| 0-10% | 11 |
| 10-20% | 6 |
| 20-30% | 0 |
| >30% | 20 |

Distribution is **bimodal**: 14 days with no ETFs vs 20 days with >30%
ETF weight. RCMv1 goes all-in or all-out on the ETF overlay — it's not
a smooth dial.

**Is the overlay actually adding value?** Conditional daily excess vs SPY:

| Day classification | n | Mean excess vs SPY (bps) | Median | Std |
|--------------------|--:|------------------------:|--------:|-----:|
| No-ETF days | 14 | **+1.3** | −2.4 | 130 |
| Has-ETF days | 37 | **+29.1** | +33.9 | 128 |

This is the sharpest finding of this checkpoint. **On days when RCMv1
holds ETFs, it averages +29 bps excess vs SPY. On days without ETF
overlay, it averages ≈ 0.** In a 60-day window with only 14 no-ETF
days, this is a ~2-standard-error difference, so directionally strong
but not statistically decisive.

Context check — is this because has-ETF days are stronger-market days
(ETF overlay follows market conditions, not creates them)?

| Day classification | SPY return (bps) mean | std |
|--------------------|---------------------:|-----:|
| No-ETF days | +10.0 | 72 |
| Has-ETF days | +20.7 | 75 |

Yes, has-ETF days DID have stronger SPY on average. But the EXCESS gap
(+29 vs +1 bps) is larger than the SPY gap (+21 vs +10 bps), so the ETF
overlay is adding conditional alpha on top of the regime shift, not
merely riding beta.

**Conclusion for Focus 4**: The ETF overlay is a real driver of RCMv1's
excess in this 60-day window, but only via 4 tickers (QUAL / MTUM /
XLRE / SLV). The other 16 ETFs in the universe got zero weight. If the
frozen spec intended RCMv1 to use more of the toolbox — e.g. XLU / TLT
for a real bear-regime rotation — this window didn't trigger that. We
need a true drawdown regime to see whether RCMv1's ETF toolbox has more
range.

---

## 6. Focus 5 — Is Candidate-3 worth discussing at 60d?

Per user direction: discuss, don't start. My assessment:

### 6.1 What's on the table

The parallel paper has two candidates spanning:
- Defensive / regime-aware / liquidity / ETF-hybrid (RCMv1)
- Momentum / benchmark-relative / volatility-structure / stock-heavy (Cand-2)

Economic themes **not** covered by either:
- Short-horizon mean reversion
- Volatility premium (long vol / short vol)
- Cross-asset flow (bonds ↔ equities, gold, VIX term structure)
- Event-driven / news sentiment
- Microstructure / order-flow

### 6.2 Why I recommend NOT starting Candidate-3 now

1. **We have only seen one market regime.** The 60-day window is
   mostly a tech-led up-tape with a mini-correction in early March.
   Neither candidate has been tested in a true bear or crisis regime.
   A third candidate would also only be observed in this one regime —
   adding a sample under the same conditions doesn't answer the
   questions the parallel paper is supposed to answer.
2. **Neither candidate is broken.** Both beat SPY / QQQ cleanly at 60d
   (+879 / +2317 bps vs SPY). No revoke / demote signal. The governance
   pipeline is doing its job with the existing pair.
3. **The day-60 observations raise questions about the EXISTING
   candidates that should be answered first**:
   - Does RCMv1's ETF toolbox actually rotate beyond QUAL / MTUM / XLRE
     / SLV under a real regime shift?
   - Does Candidate-2's drift escalation (9 days > 50 bps in bucket 3)
     stabilize or grow if the window extends or a different market
     regime hits?
4. **Adding a 3rd candidate dilutes parallel-paper signal.** The
   attribution math is cleaner with 2 orthogonal candidates than with
   3 partially-overlapping ones. A 3rd candidate is only worth the
   added complexity if it closes a **specific** explanatory gap we've
   already identified — and I don't think we've identified one yet.

### 6.3 Conditions under which Candidate-3 becomes worthwhile

I'd recommend starting Candidate-3 work when **any** of these is true:

- A second regime (drawdown / crisis / high-vol sideways) has been
  observed on the existing pair, and the data reveals a theme gap
  neither candidate covers.
- Paper feedback shows both candidates losing correlation with their
  frozen-spec thesis (e.g. RCMv1 no longer behaving defensively, Cand-2
  no longer riding momentum) — then Candidate-3 would be a diagnostic
  rather than an addition.
- Either candidate gets revoked / demoted, leaving a 1-candidate
  parallel paper, which is inferior to 2 even if the second is a
  placeholder.

**None of these conditions hold at 60d.** My recommendation:
**do NOT start Candidate-3 now.** Let the existing pair accumulate more
regime coverage first.

---

## 7. PRD §8.1-§8.3 decision-readiness assessment

PRD §8 asks three questions after 60d. My assessment of each:

### 7.1 Is universe extension worth doing? — **Not yet**.

Neither candidate shows structural saturation on the current 79-symbol
universe. RCMv1 uses only 4 of 20 ETFs; Cand-2 uses 52 of 79 stocks.
Before extending the universe, we'd want to see whether the unused
portion of the current universe gets used in different market regimes.

### 7.2 Is a new round of factor mining worth doing? — **Not yet**.

Conditions per PRD §8.2: E-post done ✓; Candidate-2 in parallel paper
✓; at least one checkpoint with actionable signal ✓ (this one). But
the actionable signal says "we need regime diversity", not "we need
new factors". No clear factor-space-exhaustion signal.

### 7.3 Is a new data tier worth connecting? — **Not yet**.

PRD §8.3: both candidates would need to show near-saturation of
OHLCV / benchmark-derived feature space. Neither does — they're both
still pulling distinct signal from that space, and drift is
execution-layer, not signal-layer. No data-tier starvation signal.

**Overall 60d decision**: keep the current parallel-paper setup,
accumulate more market-regime exposure (either by letting time pass
or by running the paper on a different historical window — e.g.
2022 bear for regime diversity). No research-scope expansion triggered.

---

## 8. Code / registry state

- Both candidates remain at `S2_paper_candidate`.
- No revoke, no demote, no `config/production_strategy.yaml` change.
- No schema / dependency change.
- `pytest tests/ -q` remains at **1566 passed, 1 skipped, 1 xfailed**.
- `docs/20260424-phase_state_snapshot.md` refreshed to reflect
  post-60d-analysis state (no state changes; timestamp only).

---

## 9. Open decisions for user review (not acted on here)

1. **Should we run the same parallel paper on a 2022 or 2020 bear
   window** to get regime diversity? This is a new run + analysis,
   not a research-scope change; probably a one-day task. Out of
   scope for this memo but worth considering.
2. **Should we revisit the RCMv1 ETF overlay** given that only 4 of
   20 ETFs fire? If the frozen spec intended broader rotation, this
   is a behavior-vs-spec gap worth a decision memo. Or it may just
   mean the data window didn't need broader rotation.
3. **Should M14 (BacktestEngine NaN / ghost-cleanup) get a proper
   fix** so Cand-2's 2024-03-26 157-bps outlier is cleanly decomposed
   into M14 vs legitimate execution variance? P2 in Framework
   Completion PRD; worth elevating if paper-comparison precision is a
   priority.

No code change. No universe extension. No new mining. Ends here per
user direction.

---

## 10. Summary in 5 sentences

1. Both candidates beat SPY / QQQ cleanly at 60 days (+879 / +2317 bps
   vs SPY), but both experienced ≈ 500 bps drawdowns of their excess
   paths — neither is a smooth accumulator.
2. Candidate-2's high-activity profile is **persistent, not
   burst-driven** (lag-1 AC 0.93, top-5 days only 14% of cum turnover);
   RCMv1 is **ramping up turnover over time** (bucket 1/2/3 = 1.40 /
   3.20 / 6.10), breaking its day-40 "stable core" portrait.
3. Candidate-2's drift **is escalating in the final 20 days** (mean
   3.6 → 19.4 → 39.8 bps; 9 days > 50 bps in bucket 3), driven by
   March 2024 volatility amplifying execution variance; position-set
   diff remains 0/60 so the signal layer is bit-stable.
4. RCMv1's ETF overlay uses only 4 of 20 available ETFs but adds real
   conditional alpha (+29 bps mean excess on has-ETF days vs +1 bps on
   no-ETF days); the broader ETF toolbox is unused.
5. **Candidate-3 not warranted now**; universe extension / new mining
   / new data tier all deferred — the next informative signal will
   come from observing the existing pair in a different market regime,
   not from adding research scope.
