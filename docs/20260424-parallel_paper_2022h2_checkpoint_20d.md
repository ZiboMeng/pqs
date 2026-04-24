# Parallel Paper (2022-H2 bear) — Checkpoint TD20 (Early Behavior)

**Date**: 2026-04-24
**Window**: 2022-08-26 → 2022-12-15 (79 real TDs)
**Cutoff (this memo)**: real trading day **TD20 = 2022-09-23 (Fri)**.
**Scope**: early behavior characterization per PRD §7.2. Turnover /
concentration starting to diverge; drift trending vs explainability;
candidate-specific issues. Strict cutoff at TD20 — TD21+ data on disk
remains untouched.

---

## 1. Headline @ TD20

| Metric | RCMv1 | Candidate-2 | SPY / QQQ baseline |
|--------|------:|------------:|-------------------:|
| Paper cum ret (TD20) | −0.36% | +1.58% | SPY −10.78%, QQQ −12.65% |
| Excess vs SPY | **+1043 bps** | **+1236 bps** | — |
| Excess vs QQQ | +1229 bps | +1423 bps | — |
| Cum turnover | 1.30 | 7.80 | — |
| Active turnover days | 5 / 20 | 13 / 20 | — |
| Total fills | 19 | 135 | — |
| Drift mean \|Δ NAV\| | **0.00 bps** | 6.61 bps | — |
| Drift max \|Δ NAV\| | 0.00 bps | 25.90 bps | — |
| Days \|Δ\| > 50 bps | 0 / 20 | 0 / 20 | — |
| Position-set diff days | 0 / 20 | 0 / 20 | — |

**Important regime context**: SPY is **−10.78%** over the first 20 TDs.
Both candidates are essentially flat-to-slightly-positive while broad
indices drop 10-12%. That's not a small thing — but at TD20 it's
"both candidates avoid the drawdown" rather than "either is winning".
Per PRD §7.2: the magnitude of excess-vs-SPY at TD20 is **reportable
but not interpreted** for ranking. It's a 20-day count.

---

## 2. Turnover divergence — sharper than 2024

| Metric (TD20) | RCMv1 | Cand-2 | Ratio | 2024 TD20 ratio |
|---------------|------:|-------:|------:|-----------------:|
| Active days | 5 | 13 | 2.6× | 1.8× (6/20 vs 11/20) |
| Cumulative turnover | 1.30 | 7.80 | **6.0×** | 3.8× (1.60 vs 6.10) |
| Mean active turnover | 0.26 | 0.60 | 2.3× | 2.0× |

The orthogonality-by-construction ratio is **larger** in the bear
regime than in 2024. RCMv1 is even more passive in bear (5 active days
out of 20, vs 6 in 2024 — same magnitude); Cand-2 is more active
(13/20 vs 11/20). The relative gap widens to 6× cumulative. This
matches the design hypothesis: defensive composite goes quieter in
risk-off; tactical composite cycles harder.

Day-by-day texture:

```
  RCMv1 active days:  TD9, TD14, TD16, TD17, TD18    (initial buy + 1 reshuffle + 3-day burst)
  Cand-2 active days: TD8, TD9, TD10, TD11, TD12, TD13, TD14, TD15, TD16, TD17, TD18, TD19, TD20
                      (consecutive every day from TD8 onward — same persistent-active
                       pattern observed in 2024 days 21+)
```

Cand-2 hit **persistent daily activity** earlier in the bear (from
TD8) than it did in 2024 (didn't reach 100% active until day 21+).
The bear regime is forcing it into "always-on" mode immediately.

---

## 3. Concentration: behavior / exposure (not by-construction top-N)

Top-N is by construction equal-weight 1/10 / 3/10 — uninformative.
Behavior-level concentration:

| Metric (TD20) | RCMv1 | Candidate-2 |
|---------------|------:|------------:|
| Unique symbols ever held | 13 | 41 |
| Top 5 most-held names | TSN(12), TRGP(12), VICI(12), TRV(12), GIS(12) | TSLA(10), SOXL(8), TRGP(8), TQQQ(6), TT(6) |
| Individual stocks share | 95.0% | 98.5% |
| Sector ETFs share | 0.0% | 0.0% |
| Factor ETFs share | **5.0% (VLUE only)** | 0.0% |
| Cross-asset share | 0.0% | **1.5% (SLV only)** |

**Two regime-dependent observations**:

- **RCMv1's ETF allocation at this TD20 is different from 2024**.
  At 2024 TD60, RCMv1 used QUAL / MTUM / XLRE / SLV (~20% weight-days
  in the up-tape). At 2022 TD20 (bear), it has chosen **VLUE only**
  (5% weight-days). The composite is responding to the regime: from
  growth/quality/REITs in up-tape to value-factor in bear. This is
  on-thesis for "defensive_composite", but also tells us **the toolbox
  the spec actually uses depends on what the regime calls for**, not
  on the ETF list being "underused" as flagged at 2024 TD60. Wait for
  TD40 / TD60 to see whether broader rotation kicks in.
- **Cand-2 unchanged in shape**: 41 unique symbols, ~99% stocks, top
  names dominated by leveraged ETFs (SOXL, TQQQ) and momentum names
  (TSLA). Same portrait as 2024, just executing it harder.

---

## 4. Drift trending — RCMv1 essentially zero, Cand-2 ramping fast

| Metric | RCMv1 | Candidate-2 |
|--------|------:|------------:|
| Mean \|Δ NAV\| TD1-10 | 0.00 bps | 0.06 bps |
| Mean \|Δ NAV\| TD11-20 | 0.00 bps | **13.16 bps** |
| Scale-up factor | 1.0× | **219×** |
| Per-trade drift (TD20) | 0.00 | 0.98 bps-days/trade |
| Days \|Δ\| > 50 bps | 0 | 0 |

**RCMv1's drift is not just small — it's identically zero through TD20**
(maximum |Δ NAV| over 20 days is 0.00 bps). The replay produces
bit-identical NAV every day. With only 5 active days and small turnover,
there's barely any execution surface for variance to accumulate.

**Cand-2's drift is escalating sharply in TD11-20**: mean grew from
0.06 to 13.16 bps — a 219× scale-up. Compare to 2024 TD20 (3.62 bps
mean) — 2022 bear's 13.16 bps mean over the same 20 TDs is **~3.6×
higher**. This is the bear-regime amplification of execution variance
predicted at 2024-60d: high-vol days widen fills' price-discovery cost.

**Still explainable**:
- Position-set diff = 0/20 BOTH → signal layer remains bit-stable
- Drift is purely execution-layer
- Days > 50 bps = 0/20 (informational threshold not yet breached)

**Watch list for TD40**:
- If Cand-2's TD21-40 mean climbs above ~30-40 bps and crosses 50-bps
  threshold on multiple days, that warrants a candidate-specific note
- The 2024 TD60 already showed 9 days > 50 bps in TD41-60 — bear
  regime may produce that pattern earlier

---

## 5. Path quality (early)

Daily excess vs SPY distribution through TD20:

| | RCMv1 | Candidate-2 |
|---|------:|------------:|
| n daily observations | 17 | 15 |
| Mean daily excess | +74.5 bps | +23.1 bps |
| Std daily excess | 275 bps | 210 bps |
| Positive days / negative days | 10 / 7 | 9 / 6 |
| Mean on +days | +234.6 bps | +142.5 bps |
| Mean on −days | −154.1 bps | −156.0 bps |

RCMv1 is **more aggressive on the upside** in the bear (mean +days
+234.6 bps) and similar on downside (−154.1 vs −156.0). Higher daily
std (275 vs 210) — RCMv1's defensive overlay is producing larger swings
day-to-day, not steady protection.

In 2024 TD20 the daily-excess shape was reversed: Cand-2 had lower
std (132 vs 150) and higher mean (Cand-2 led on cumulative). At 2022
TD20 it's flipped — RCMv1 has higher std AND higher mean.

**Cautious read**: this is consistent with regime-dependent factor
families. Defensive composite expressed via VLUE / staples / REITs
gets bigger relative-to-market days when the market is dropping (the
bench drops, the defensive doesn't, excess widens). Tactical composite
on TSLA / SOXL / TQQQ has equity-like volatility regardless of regime.

But again — 17 / 15 daily observations is a tiny sample. The cumulative
+1043 / +1236 bps figures are **early bear protection signals**, not
yet alpha claims.

---

## 6. PRD §7.2 TD20 questions answered

- **Turnover diverging?** Yes — 6× cumulative ratio (sharper than
  2024's 4×). Cand-2 in persistent-active mode from TD8.
- **Concentration diverging?** Yes — RCMv1 13 unique syms vs Cand-2
  41; RCMv1 has factor-ETF (VLUE) allocation, Cand-2 has cross-asset
  (SLV) allocation, but the asset-class profiles are clearly distinct.
- **Drift explainable?** Yes for RCMv1 (literally zero). Yes for
  Cand-2 (3.6× higher than 2024 TD20 mean, but per-trade drift only
  0.98 vs 2024's 0.36 — not a regime-change-of-pipeline-character,
  just bear-amplification of the same execution sensitivity).
- **Candidate-specific problem?** None. Position-set diff = 0/20 on
  both. No NaN, no crash, no dead signal day.

---

## 7. Deliberate non-claims at TD20

Per user direction:

- **No "RCMv1 wins / Cand-2 wins in bear"**. 20 TDs is too short.
- **No "ETF overlay works"**. The VLUE-only allocation at TD20 differs
  from the 2024 portrait, but it's also early. Wait for TD40 / TD60.
- **No "Cand-2 tactical thesis surviving"**. It's holding TSLA /
  SOXL / TQQQ in a bear, which is intentional for momentum/rel-strength,
  but whether that style breaks down requires more TDs.
- **No comparison-of-windows synthesis** — that's the TD75 cross-regime
  memo's job.
- **No universe extension / new mining / Candidate-3 discussion** —
  frozen until TD60 of this rerun.

---

## 8. Status

- Both candidates remain at `S2_paper_candidate`.
- pytest 1566/1/1 (no code change this round).
- No registry / config / schema / dependency changes.
- No new paper run needed for TD40 / TD60 / TD75 — data on disk.

Next checkpoint: **TD40 = 2022-10-21 (Fri)**. That date contains the
**Oct 12, 2022 bear bottom**, so TD40 will read across the most
adversarial period in the window.
