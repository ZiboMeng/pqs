# Diversifier Role Decision Memo

**Date**: 2026-05-01
**Authority**: User explicit-go (zibo, 2026-05-01: "按照你的建议走")
**PRD**: `docs/prd/20260501-two_stage_allocation_architecture_prd.md`
**Implementing Phase**: C-PRD-1 (lightweight role tag + Trial 9 forward init)
**Affects**: CLAUDE.md QQQ Outperformance Rule, `config/temporal_split.yaml`, forward manifest schema, candidate registry schema, Trial 9 candidate

## TL;DR

Adds `diversifier` candidate role to PQS with role-specific acceptance gates:

- **Window-mean vs QQQ rule WAIVED for diversifier role only** (1 specific rule cell);
- **All other CLAUDE.md QQQ Rule cells UNCHANGED** (full-period vs QQQ, holdout 2025 vs QQQ, drawdown, stress, concentration, long-only/no-short/no-margin invariants);
- **Diversifier-specific gates STRICTER on NAV correlation, factor overlap, non-equity exposure** (these are what distinguish a diversifier from a core);
- **D10c compromise: 18% per-validation-year max_dd is "soft warn" + 20% is "hard fail" + TD60 self-clearing condition** (60-day rolling max_dd ≤ 15% required to clear warning, else TD60 yellow→red).

Trial 9 (`6c745c601a47` from track-c-cycle-2026-05-01-05) is the first concrete diversifier candidate. Trial 9's 2025 max_dd = -18.16% triggers the soft-warn but passes the hard-fail. Forward TD60 will determine whether the warning clears.

## D1-D10 user decisions recorded

| D | Question | User decision |
|---|----------|--------------|
| D1 | Diversifier waiver scope (only OOS walk-forward window-mean rule)? | YES |
| D2 | Trial 9 enters forward observation as diversifier? | YES |
| D3 | core_alpha QQQ Rule unchanged? | YES |
| D4 | Only Phase C-PRD-1 authorized; 2/3/4 deferred until forward triggers? | YES |
| D5 | Defer D3b regime-aware mining objective; absorb into Stage 1 PRD? | YES |
| D6 | This PRD absorbs Track B Step 6+ scope? | YES |
| D7 | CLAUDE.md edit: pre-commit review by user? | YES |
| D8 | §5.1.4 default allocation weights authorized as starting values (subject to §6.4 acceptance)? | YES (deferred to Phase C-PRD-3) |
| D9 | §10.8 max-3 diversifier population cap initial? | YES (deferred to Phase C-PRD-2) |
| D10a | Correlation threshold = PRD's NAV-level 0.70 raw / 0.50 residual? | YES |
| D10b | 2025 vs_qqq slack = strict > 0 (no -0.05 slack)? | YES |
| **D10c** | **2025 max_dd: soft-warn at 18% + hard-fail at 20% + TD60 self-clearing** | **YES (compromise path)** |

## Implementation deliverables (Phase C-PRD-1)

1. **CLAUDE.md QQQ Outperformance Rule** — add diversifier role exception clause citing this PRD. Pre-commit review by user before push.

2. **`config/temporal_split.yaml`** — replace existing speculative diversifier section with PRD §6.2 thresholds:
   - eligibility_constraint: NAV-level (was factor-IC-level 0.40)
   - validation_gates: 2025 vs_qqq strict > 0 (was -0.05 slack), 2025 max_dd soft-warn 18% + hard-fail 20%

3. **`core/research/forward/manifest_schema.py`** — add `CandidateRole` enum + `ForwardRunManifest.candidate_role` Optional field (lazy migration default = `legacy_decay_verification`).

4. **`core/research/candidate_registry.py`** — add `role` field to `CandidateRecord` + idempotent ALTER TABLE migration (default existing rows to `legacy_decay_verification`).

5. **Trial 9 frozen spec** — `data/research_candidates/trial9_diversifier_001.yaml`, immutable, contains spec extracted from rcm_archive cycle05 trial `6c745c601a47`.

6. **Forward init script** — `dev/scripts/forward/init_trial9_diversifier.py` wrapping `runner.init()` with role + start_date.

7. **Tests** — ~15-20 tests across:
   - role enum dispatch
   - diversifier acceptance gate (each gate individually)
   - core_alpha acceptance regression (unchanged behavior)
   - manifest backwards-compat migration
   - registry backwards-compat migration
   - Trial 9 spec hash matches archive

8. **Backfill** — opt-in script setting role=`legacy_decay_verification` on RCMv1 + Cand-2 manifests + registry rows.

9. **First forward observe** — runs `forward observe trial9_diversifier_001` once after init produces TD001.

## TD60 self-clearing condition (D10c compromise)

Trial 9 enters forward with `soft_warn_2025_max_dd_18pct` flag. TD60 (60 trading days from start_date) MUST report:

```yaml
td60_self_clearing_check:
  required: 60_day_rolling_max_dd_le_15pct_in_observation_window
  if_passed: clear_soft_warn_flag; advance_per_normal_TD60_dispatch
  if_failed: TD60_yellow_promoted_to_red; halt_forward_observation;
             escalate_to_user_decision_per_§7_1
```

This converts the borderline backtest finding (18.16% > 18% by 0.16pp) into a forward-evidence-gated continuation: trial 9 must prove in forward that its drawdown is NOT systematically near the diversifier ceiling.

## Trial 9 forward observation setup

- candidate_id: `trial9_diversifier_001`
- source_trial_id: `6c745c601a47`
- source_lineage_tag: `track-c-cycle-2026-05-01-05`
- role: `diversifier`
- spec_hash: derived from frozen yaml content
- start_date: 2026-05-XX (first trading day post-Phase-C-PRD-1 ship)
- benchmark: SPY (primary), QQQ (secondary)
- cost_model: existing config/cost_model.yaml
- soft_warn_flags: `[soft_warn_2025_max_dd_18pct]`
- TD60 self-clearing: 60-day rolling max_dd ≤ 15%

## Governance protections (audit trail)

1. **Diversifier waiver scope is exactly 1 rule cell** — verified by unit test enforcing other QQQ rule cells remain HARD for diversifier
2. **Diversifier acceptance is STRICTER than core on NAV/factor/exposure** — verified by unit test on each gate
3. **Role tag is immutable post-init** — verified by unit test on registry mutation
4. **Trial 9 entry does NOT relax core_alpha acceptance** — verified by regression test
5. **CLAUDE.md edit cites this memo + PRD** — verified manually + audit test
6. **Yaml threshold change is logged + reviewable** — git blame preserves authorship
7. **No 2026 sealed panel access** — sealed_ledger.py guard unchanged

## What this memo does NOT decide

- Phase C-PRD-2 sleeve abstraction (deferred until TD60 GREEN)
- Phase C-PRD-3 allocation prototype (deferred)
- Phase C-PRD-4 full integration (deferred)
- Cycle #06 single-stage mining (NOT authorized)
- D3b regime-aware mining objective (deferred + absorbed into Phase C-PRD-3)
- Track B Step 6+ resumption (absorbed into Phase C-PRD-3/4)
- Adding new diversifier candidates beyond Trial 9 (no policy yet; population cap D9 deferred to Phase C-PRD-2)

## Reversal protocol

If forward observation produces evidence that the diversifier role is being abused or the waiver is creating problems:

1. Operator drafts a `docs/memos/YYYY-MM-DD-diversifier_role_revoke_memo.md`
2. User explicit-go required for revocation
3. Active diversifier candidates revert to `legacy_decay_verification` role (forward observation continues; promotion suspended)
4. CLAUDE.md edit reverted
5. yaml diversifier section restored to pre-Phase-C-PRD-1 state
6. PRD updated with reversal note

This is symmetric with the introduction: directional decision + audit trail + reversibility.
