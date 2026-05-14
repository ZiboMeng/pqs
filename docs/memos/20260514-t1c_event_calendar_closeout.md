# T1c Event-Calendar Closeout — FOMC Dead, PEAD Deferred

**Date**: 2026-05-14
**Lineage**: `t1c-event-calendar-2026-05-14` (FOMC smoke only)
**Status**: PARTIAL — FOMC informative null; PEAD deferred (per-symbol earnings dates ingest needed)
**Authors**: operator (zibomeng@) + Claude Code assist
**PRD scope**: per roadmap v2 Q2 LOCKED = PEAD + FOMC bundle (3-4 weeks full eng)

---

## §1 Quick verdict

**FOMC pre-announcement drift smoke (2017-2025, 72 FOMC dates)**:
- Mean 24h pre-FOMC SPY return: **+8.8 bps** (Lucca-Moench 2015 J.Finance claim was +49 bps)
- Median 24h: +5.3 bps
- Hit rate 24h > 0: 59.7%
- Compound 9-year return holding SPY only on pre-FOMC windows: **+5.81%**
- Implied CAGR: **+0.64%**

**Verdict**: pre-FOMC drift is **degraded** post-2015 to ~1/5 of original strength. Confirms FRL 2021 follow-up finding (Lucca-Moench's drift "disappeared after 2015"). At 8.8 bps mean with bid-ask spread + commission, signal is net-negative after transaction costs.

**PEAD (post-earnings drift)**: not tested. Requires per-symbol earnings dates which PQS has in SEC EDGAR cache (~210 MB) but not in active factor pipeline. Building proper PEAD signal needs:
- Earnings date extraction from EDGAR cache per symbol
- SUE (standardized unexpected earnings) compute
- 60-day post-announcement holding window
- Sector-neutral cross-sectional ranking

Estimated PEAD-only eng: ~1-2 weeks. **Deferred to user explicit-go.**

---

## §2 Per-year breakdown (FOMC 24h drift)

| Year | n FOMC | Mean (bps) | Median (bps) |
|---|---|---|---|
| 2017 | 8 | +35.3 | +16.6 |
| 2018 | 8 | +17.4 | -59.2 |
| 2019 | 8 | -19.2 | +10.6 |
| 2020 | 8 | -21.6 | +5.1 |
| 2021 | 8 | **-46.3** | +5.8 |
| 2022 | 8 | +72.5 | -16.6 |
| 2023 | 8 | -18.0 | -1.6 |
| 2024 | 8 | +19.6 | +11.7 |
| 2025 | 8 | +39.6 | +44.1 |

Pattern: dispersion >> mean. The 2022 +72 bps mean (Fed hiking shock) and 2025 +40 bps (recent quasi-revival) inflate the period mean. Median is +5.3 bps — basically noise after costs.

**The 2017-2025 distribution does NOT support a tradable signal.** Per-year mean ranges from -46 to +72 bps; this is high variance with no consistent positive bias.

---

## §3 T1c verdict + path forward

**FOMC sleeve**: NOT VIABLE. Don't build out to Track A acceptance — would fail aggregate excess vs SPY hard, and per-bar holdings are too brief for the framework. Skip Track A run.

**PEAD sleeve**: viable per academic literature (Bernard-Thomas 1989; Lan et al. 2024 IRFA) but requires per-symbol earnings ingest work (~1-2 weeks). Per roadmap v2 §9 stop-rule, do NOT auto-fire next cycle without user explicit-go.

**Roadmap v2 §9 path adjustment**: T1c "PEAD+FOMC bundle" → "PEAD only (later)". FOMC drop early per dead-signal evidence.

Strategic implication: of 3 T1 sleeves planned (alt-A intraday reversal / T1b confirmation pattern / T1c event calendar):
- alt-A: NAV-orthogonal but CAGR 2.9% (too thin)
- T1b: CAGR 20.3% but Track A FAIL on year-by-year consistency
- T1c: FOMC dead; PEAD deferred

**No Track-A-passing nominee from T1 sleeves**. Per roadmap v2 §9 informative-null discipline, this is the expected outcome that triggers T2 (cycle11 signal-driven mining) as the next attack vector.

---

## §4 Files

- Smoke: `dev/scripts/t1c/run_t1c_fomc_smoke.py`
- Closeout: this file

No NAV file saved (smoke didn't produce a strategy run). No Track A verdict (gated on FOMC alpha being live).

---

## §5 Asks for user

Nothing required. T1c closes with FOMC = informative null, PEAD = deferred to user explicit-go.

Proceed to T2a (cycle11 signal-driven mining PRD) per roadmap v2 §9.
