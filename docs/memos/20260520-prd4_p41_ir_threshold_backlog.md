# PRD #4 P4.1 rank-IR < 0.30 threshold — operator backlog (option B + C)

**Status**: backlog (recorded post-Round-25, deferred per user directive
2026-05-20 "走完整个流程之前不要旁逸斜出 先走 A")
**Triggered by**: Round 25 ledger entry P4.1 AC partial PASS finding —
rank-IC PASS 4/4 configs but rank-IR FAIL 4/4(0.10-0.14 vs 0.30 AC threshold)

---

## Findings to address (post P4.2-P4.5 cycle)

Per Round 25 verdict, on cycle06 3-feature × horizon=5 × 10-fold 2010-2024:

| Config | rank-IC > 0.02 AC | rank-IR > 0.30 AC | Notes |
|---|---|---|---|
| Linear / pooled | 0.0411 ✅ | 0.1394 ❌ | Best IC config |
| Linear / tradeable | 0.0371 ✅ | 0.1258 ❌ | |
| XGB / pooled | 0.0275 ✅ | 0.1262 ❌ | |
| XGB / tradeable | 0.0244 ✅ | 0.1095 ❌ | |

## Option B (deferred) — engineer toward IR ≥ 0.30

Three improvement levers, in order of expected ROI:

1. **XGB hyperparam search** (highest ROI hypothesis)
   - Current: `n_estimators=50, max_depth=4, learning_rate=0.1` (hand-pick)
   - Search space: n_estimators ∈ {30, 100, 300}, max_depth ∈ {3, 5, 8},
     learning_rate ∈ {0.01, 0.05, 0.1}, optionally reg_lambda ∈ {0, 1, 10}
   - Per Round 25 finding "Linear > XGB on 3-feature small panel" =
     XGB overfit noise. Tighter regularization / fewer trees might fix.
   - Driver hook: extend `walk_forward_rank_sign.py` with
     `--hyperparam-search` flag using strict-chronological CV inside each
     fold's train slice (NOT cross-fold, that's leakage).

2. **`--drop-high-nan` preprocessing** (closes the 113-factor scope FAIL)
   - Add `--drop-high-nan {0.5,0.7,0.9}` flag; drop features whose
     non-NaN coverage on the training window < threshold
   - Re-enables 113-factor training (currently blocked by strict-AND
     row filter in LinearBaseline.fit on full 113 panel)
   - Expected to lift IC because broader feature set is available;
     IR effect ambiguous (more features → more noise too)

3. **Monthly horizon retest** (alignment with classical ML literature)
   - Currently `horizon=5` matching cycle06_31af04cf2ff9 weekly cadence
   - Gu-Kelly-Xiu uses 21-day forward — different signal structure
   - Cheap test: `--horizon-days 21` rerun on cycle06 3-feature panel

4. **Multi-TF context features** (PRD #4 P4.3)
   - Daily regime state, 60m/30m intraday signals, overnight gap
   - Could improve both IC AND IR by giving the rank model context
     beyond pure cross-sectional cycle06 factors
   - **NOTE**: P4.3 is in PRD #4 scope; doing it as part of P4.5
     acceptance experiment is the natural path (instead of as a B option)

## Option C (directional, user gate required) — revise IR AC threshold

**Rationale to consider**:
- 0.30 IR is fund-grade benchmark (Grinold-Kahn for ranking)
- Single-strategy individual trader scale ($10K → $100K target per
  CLAUDE.md) may not need 0.30 IR
- Empirical (Gu-Kelly-Xiu, learning-to-rank literature) typical
  cross-sectional ML rank-IR on monthly forward returns:
  - All firms pooled: 0.15-0.25
  - Top-decile only: 0.30-0.50
- A 0.15-0.20 IR threshold would align with academic norms while
  preserving the meaningful-signal-vs-noise guard

**Counter (why keep 0.30)**:
- §6.4 invariants are aggressive (15-20% MaxDD, beat SPY hard)
- Lower IR threshold weakens the ML overlay's contribution to
  fleet-level Sharpe
- Promotion threshold should be HARD lest the bar drifts down

**Resolution**:
- After P4.2-P4.5 results are in, the IR numbers (with hyperparam +
  multi-TF + drop-high-nan) will inform whether 0.30 is achievable
- IF P4.5 acceptance shows R-ML-B/C/D beat R-ML-A on Sharpe AND MaxDD
  (the P4.5 AC), the IR threshold may be redundant to the binding
  test (Sharpe + MaxDD) anyway
- **Directional decision deferred to post-P4.5 user review**

## What this memo does NOT do

- Does NOT change PRD #4 P4.1 AC text (rank-IR > 0.30 stays binding
  until explicitly revised by user)
- Does NOT block P4.2 or P4.5 (Round 26+ proceeds with current AC text
  and reports the same IR honestly — Option B levers may be applied
  inside P4.5)

## When to revisit

After P4.5 acceptance experiments (R-ML-A/B/C/D) complete. At that
point the operator+user discuss:
1. Did any ML-driven path beat R-ML-A heuristic baseline on Sharpe AND
   MaxDD? (P4.5 binding AC)
2. What's the IR delta after hyperparam search + multi-TF?
3. Is the 0.30 IR threshold still warranted given the §6.4 binding
   tests already constrain MaxDD?

---

**References**:
- Round 25 ledger entry: `docs/memos/20260519-prdx_execution_ledger.md`
- PRD #4 P4.1 AC: `docs/prd/20260520-prd_rank_first_ml_pipeline.md`
- Decision discipline: `feedback_no_blanket_failure_verdict`
