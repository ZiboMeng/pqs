# Invariant Revision Checkpoint — 2026-05-02

**Type**: Formal invariant change record (per CLAUDE.md "Invariant
Constraints" governance — changes require explicit user approval).

**Authority**: User explicit-go 2026-05-02 (resident-quant 3-round
audit recommendation accepted).

**Branch**: `invariant-revision-2026-05-02` → merged to main on
`<merge-commit>`.

**Decision memo**: `docs/memos/20260502-qqq_benchmark_deprecation.md`
(8-angle analysis + change table + reversibility clause).

---

## Invariant table — diff vs pre-2026-05-02 state

| Invariant | Pre-2026-05-02 | Post-2026-05-02 | Change Type |
|---|---|---|---|
| Long-only no-margin no-short | HARD | **HARD (unchanged)** | — |
| SQQQ blacklist | HARD | **HARD (unchanged)** | — |
| TQQQ/SOXL stricter risk | HARD | **HARD (unchanged)** | — |
| Backtest-execution consistency | HARD | **HARD (unchanged)** | — |
| Long-term outperform SPY | HARD | **HARD (unchanged)** | — |
| **Long-term outperform QQQ** | **HARD** | **🔴 DIAGNOSTIC** | DEPRECATED |
| **2025 holdout vs QQQ** | **HARD** | **🔴 DIAGNOSTIC** + **vs_spy HARD added** | DEPRECATED + REPLACED |
| **OOS walk-forward window-mean vs QQQ** | **HARD (waived for diversifier)** | **🔴 DIAGNOSTIC (all roles)** | DEPRECATED |
| MaxDD 15-20% target | HARD | **HARD (unchanged)** | — |
| **Black swan resilience** | aspiration (vague) | **🟡 2008-style scenario MaxDD ≤ 25% (testable)** | QUANTIFIED |
| **Capital scale aspiration** | $10K → $1M+ | **🟡 $10K → $100K (10x in 5-10y)** | REVISED |
| Chinese reporting English code | convention | convention (unchanged) | — |
| Initial capital ~$10K | factual | factual (unchanged) | — |

**Summary**: 3 RED (deprecation) + 2 YELLOW (refinement). 9 invariants
unchanged.

---

## Why these specific changes

Full rationale in `docs/memos/20260502-qqq_benchmark_deprecation.md`.
Condensed:

1. **QQQ benchmark mathematical infeasibility**: long-only beat-QQQ
   requires beta>1 → MaxDD>QQQ → violates risk constraint. 5 cycles'
   sibling-by-NAV convergence root-caused by this infeasibility.
2. **QQQ long-term ≈ SPY (1999-2025: +0.5%)**: 2009-2021 outperformance
   was zero-rate cherry-pick. Hard gate = bet on regime continuation.
3. **Industry norm**: long-only US large-cap → S&P 500/Russell 1000
   benchmark, NOT QQQ.
4. **Diversifier exception precedent**: setup property not
   role property; extends to core_alpha logically.
5. **$1M+ scale unrealistic for individual + AI single operator** in
   reasonable timeline. $100K (10x) is realistic compound.
6. **Black swan "resilient" was un-testable**; quantified to 2008-style
   MaxDD ≤ 25% per stress slice.

---

## Operational consequences

### Mining acceptance pipeline
- `core/research/temporal_split_acceptance.py` gate type change for
  vs_qqq cells (core role): hard → diagnostic
- Cycle #04/#05 archived trials re-evaluated under new gate (Phase 3
  of branch); some previously rejected trials may now pass

### Diversifier Role Exception simplification
- "Waived rule cell" line becomes empty (the cell is now diagnostic
  for all roles)
- Diversifier-specific STRICTER rules (NAV correlation, factor overlap,
  cross-asset utilization, per-year MaxDD) are KEPT
- Section renamed "Diversifier Role Additional Constraints" (not
  "Exception" since there's nothing to except from anymore)

### Master report
- vs_qqq column kept (diagnostic)
- vs_spy column promoted to primary outperformance display
- Flag "fails QQQ diagnostic" added (info only, not gate)

### Trial 9 status
- Trial 9 currently `diversifier` role (D10c soft-warn flag)
- Under new gate, Trial 9 could potentially be re-classified to
  `core_alpha` (passes new gate)
- **Decision deferred to Phase 3 re-evaluation memo**: do NOT
  auto-mutate Trial 9 manifest; operator decides after re-eval data
  available
- Forward observation continues unchanged on main (Trial 9 manifest
  not touched on this branch)

---

## Reversibility

Mirror Diversifier Role Exception revocation pattern (CLAUDE.md
already documents this convention):

1. User explicit-go required
2. Draft `docs/memos/YYYY-MM-DD-qqq_hard_criteria_restoration_memo.md`
3. Revert CLAUDE.md edits + this checkpoint
4. Revert `temporal_split_acceptance.py` gate type change
5. Re-evaluate active candidates under restored gate
6. Inform operator (memo + chat)

Anti-pattern: silent CLAUDE.md edit without memo / checkpoint update.

---

## Files touched on branch

| File | Phase | Type |
|---|---|---|
| `docs/memos/20260502-qqq_benchmark_deprecation.md` | 1 | NEW |
| `docs/checkpoints/20260502-invariant_revision.md` | 1 | NEW (this) |
| `CLAUDE.md` | 1 | EDIT (System Identity + Invariants + QQQ Rule + Diversifier section) |
| `core/research/temporal_split_acceptance.py` | 2 | EDIT (gate type) |
| `config/temporal_split.yaml` | 2 | EDIT (vs_qqq gate type if specified) |
| `config/temporal_split_v2.yaml` | 2 | EDIT (vs_qqq gate type if specified) |
| `tests/unit/research/test_temporal_split_acceptance.py` | 2 | EDIT (test updates) |
| `docs/memos/20260502-cycle04_05_re_evaluation.md` | 3 | NEW |

---

## Trial 9 / forward observation isolation

**HARD constraint on this branch**: do NOT touch any of
- `data/research_candidates/trial9_diversifier_001.yaml`
- `data/research_candidates/trial9_diversifier_001_forward_manifest.json`
- `core/research/forward/runner.py` (forward observe code)
- `core/research/forward/manifest_schema.py` (forward schema; bridge
  function from 2026-05-02 self-audit ship is already on main)
- Anything that would change `config_snapshot.universe_hash` or
  `risk_config_hash` or `factor_registry_hash` or `system_config_hash`

Trial 9 forward observation continues on main during the entire branch
lifetime. Daily ritual unaffected.

Post-merge: Trial 9 forward observation MUST still work without any
config drift halt. Verified in Phase 4.
