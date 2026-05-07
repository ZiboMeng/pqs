---
lineage_tag: cycle07-to-fleet-master-2026-05-06
phase: B.3
round: R5
status: NO FORWARD INIT — cycle07a 0 nominee
date: 2026-05-07
operator: zibomeng (Claude Opus 4.7)
---

# Phase B.3 closeout — Branch decision (NO forward init for cycle07a)

## TL;DR

Per master PRD `docs/prd/20260506-cycle07_to_fleet_master_prd.md` v1.1
§4.2 Phase B.3 branch table:

> If Round 2 cycle07a Track A produced nominee then forward init the
> candidate via dev/scripts/forward/init_<id>.py; ELSE mark for fleet
> integration only.

R2 closeout (`docs/memos/20260507-cycle07a_closeout.md`): cycle07a
**0 strict Track A nominee**. Best near-miss `1e771580f486` (drawup +
mom_63d + ret_1d, monthly) fails 2 gates (vs_qqq aggregate + beta_to_qqq).

→ **NO forward init**. cycle07a archive preserved per yaml immutability
contract for future re-evaluation if framework changes.

## What R5 would have done (had cycle07a produced a nominee)

1. Author `dev/scripts/forward/init_cycle07a_<id>.py` mirroring
   `init_trial9_diversifier.py` pattern
2. Build `FrozenStrategySpec` from cycle07a archive trial:
   - `composite_factor_weights` from `weights_csv` + `features_csv`
   - `harness_config` from cycle06-inherited yaml (cap_aware_cross_asset
     + monthly + cluster_cap=0.20 + max_single=0.10 + asset_class_caps)
   - `execution_policy` = {"enable_sr_defer": false} (cycle07a yaml had
     enable_sr_defer_choices=[false] only; round 2 stub)
3. Stamp `candidate_role`: per CLAUDE.md, role would depend on absolute
   alpha vs diversifier intent. Trial 3's 2018+2025 vs_qqq positive +
   2019/2021/2023 negative → likely **diversifier** role (similar pattern
   to Trial9)
4. Initialize `data/research_candidates/cycle07a_<id>_forward_manifest.json`
   via `core.research.forward.runner.init` API
5. First TD entry on next NYSE trading day post-freeze
6. Commit + push

NONE of the above ran for cycle07a because the precondition (Track A
PASS) was not met.

## Why no fleet integration either (yet)

R5 PRD §4.2 says "ELSE mark for fleet integration only". This is a
documentation status, not a code action. cycle07a archive is preserved
+ tagged in this memo. Whether to USE cycle07a in future fleet:

- If R7+R8 cycle08 produces a nominee, fleet would have at most 2
  candidates: Trial9 (diversifier role, currently in forward observation)
  + cycle08-nominee. cycle07a would NOT enter fleet (failed Track A).
- If cycle08 also 0 nominee, fleet remains 1-candidate (Trial9 only).
  Per CLAUDE.md "Track B Step 6+ HARD PAUSED until ≥2 candidates exist
  that BOTH pass Track A acceptance", fleet allocator stays paused.
  cycle07a's near-miss (Trial 3) does NOT bypass this gate.

## Strategic finding

cycle07a is the **first cycle since cycle04/05/06 to demonstrate
materially different mining outcomes** (per H1 Spearman -0.17 vs cycle06's
0.89). The single-axis NAV-side reweight is mechanistically working. But
strict Track A gates expose the **2023 BULL year + beta_to_qqq pattern**:
broad long-only equal-weight cannot match QQQ in narrow sector rallies
(2023 = NVDA-led tech), pulling aggregate vs_qqq negative.

This pattern crosses cycle04/05/06 + cycle07a + Trial9 — same binding
constraint. Resolution requires either:
1. **Anchor swap** (cycle08 dynamic anchor pool: master PRD G3 / Issue L)
2. **Regime-conditional mining** (cycle08 v3 objective: master PRD §4.3 C.1)
3. **Universe expansion** (Phase E options per PRD §6 risk row)
4. **Loosen vs_qqq aggregate** (CLAUDE.md QQQ deprecation reading; user
   directional decision needed)

Master PRD §4.3 cycle08 attempts (1) + (2). Phase E (3) not yet
authorized. (4) is a CLAUDE.md invariant change requiring user
explicit-go.

## Phase B summary (R3 + R4 + R5 bundled)

| Phase B sub-round | Status | Commit |
|---|---|---|
| B.1 (R3) factor promotion | SKIP — R1 0/3 ELIGIBLE | `5ddc5f4` |
| B.2 (R4) SR defer mining integration | SHIPPED — 6/6 tests | `7512bae` |
| B.3 (R5) branch decision | NO FORWARD INIT (this memo) | (this commit) |

**Phase B disposition**: G1 (factor pool expansion) evidence path now
relies entirely on R4's SR defer mining integration. Cycle08 yaml will
test enable_sr_defer=True actually shifts NAV ranking under v3 objective.

## Self-Audit (R1/R2/R3/R4)

### R1 — factual

- cycle07a Track A 0/3 PASS verified by `data/audit/cycle07a_track_a_eval_track-c-cycle-2026-05-07-01.json`
  → `n_passed: 0, n_evaluated: 3`
- R3 SKIP commit `5ddc5f4` (verified `git log --oneline | grep R3`)
- R4 SHIPPED commit `7512bae` (verified `git log --oneline | grep R4`)
- Trial9 forward observation status (CLAUDE.md): in_progress, TD003 +8.02%,
  status not yet TD60 GREEN

### R2 — logical

- "no forward init for cycle07a" follows from PRD §4.2 B.3 verbatim
- "fleet integration only" status is documentation, not code action
- 1-candidate fleet (Trial9 only) doesn't bypass Track B Step 6+ pause
- Decision is Pareto-stable: even if R7 cycle08 produces a nominee,
  cycle07a still doesn't enter fleet because cycle07a failed Track A

### R3 — actually-run

- This is a doc-only round (no new code)
- R3 (already SKIPPED) + R4 (already shipped) verified by git log
- No new pytest required (Phase B closeout is doc-level)

### R4 — boundary

- **What if user says "loosen vs_qqq gate"?** cycle07a Trial 3 might
  promote to nominee status. But this requires CLAUDE.md invariant
  change + user explicit-go. Out of scope for this round.
- **What if Trial9 reaches TD60 GREEN by week 12 + cycle07a reactivates?**
  cycle07a archive is preserved; future re-evaluation under updated gates
  is reversible.
- **What if cycle08 also 0 nominee?** Fleet stays 1-candidate; per CLAUDE.md
  Track B Step 6+ paused. PRD §4.4 D.0 gate (a) NOT MET → D.2-D.4 paused;
  D.1 fleet PRD writing only (R10).

### Self-audit verdict

PASS. R5 branch decision = NO FORWARD INIT is correct outcome per PRD
§4.2 B.3 + R2 evidence (0 Track A nominee).

## Reversibility

This memo is doc-only. No code change. No data destruction. Future
revocation = revert this commit; R3+R4 outcomes preserved.

## Lineage

`cycle07-to-fleet-master-2026-05-06` round 5 of 13. Next round: R7
(Phase C.2 cycle08 yaml + 200-trial mining; depends on cycle08 yaml
authoring + ResearchMiner.run_trial v3 dispatch wire).
