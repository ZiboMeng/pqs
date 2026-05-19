# ⚠ chart_native_s1_evidence_v1 — LEAKAGE CAVEAT (read before any forward judgment)

**2026-05-18.** This candidate's original Track-A 17/17 PASS (the
forward-init basis) is **leakage-inflated**. Leakage-correct re-eval
(López de Prado average-uniqueness weighting + purge/embargo of train
rows whose 21d label reaches a validation year) → Track-A **FAIL**
(`validation_aggregate_excess_vs_spy` + 2025 vs_spy); IC-on-59
0.0146 → 0.0110 (−25%).

- Decision = **A: KEEP as evidence_only_observation + documented
  caveat** (NOT retire; NOT fleet; no capital). Forward soak is the
  real-time test of whether this leakage-correct-FAIL weak signal
  holds out-of-sample.
- frozen β is **NOT refit** (sha256-pinned frozen-probe contract;
  refit = new candidate, contradicts A). Caveat applies to the
  existing frozen candidate as-is.
- **Every forward judgment / TD60 verdict (~2026-08-13) MUST cite
  this caveat.** Do NOT use the original 17/17 PASS as a health
  baseline.

Full: `docs/memos/20260518-chart_native_s1_evidence_leakage_caveat_decision.md`
Source: `docs/memos/20260518-l3_deconfound_correctness_verdict.md` §5.
