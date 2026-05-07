#!/bin/bash
# Start the Cycle 07 -> Fleet master ralph-loop.
#
# Purpose: execute PRD docs/prd/20260506-cycle07_to_fleet_master_prd.md
# v1.1 across Phase A (cycle07a reweight + RSI/KDJ/MACD IC screen),
# Phase B (factor pool expansion + SR defer mining integration),
# Phase C (regime-conditional cycle08 mining), and Phase D (fleet
# allocator PRD writing; impl gated on Trial9 TD60 GREEN ~2026-07-30).
#
# Each execution round embeds a 4-layer self-audit (R1 factual /
# R2 logical / R3 actually-run / R4 boundary). Final 3 rounds are
# dedicated full-codebase audit re-engaging every prior round's
# PASS claim per memory feedback_self_audit_methodology.md.
#
# Reference PRD: docs/prd/20260506-cycle07_to_fleet_master_prd.md
# Predecessor PRDs:
#   - docs/prd/20260505-mining_objective_nav_based_plus_execution_policy_prd.md (PRD-AC v1.1)
#   - docs/prd/20260505-taa_regime_allocation_framework_prd.md (PRD-E v1.1)
#   - docs/prd/20260501-two_stage_allocation_architecture_prd.md (Phase C-PRD-1 trial9 diversifier)
#
# Lineage tag:        cycle07-to-fleet-master-2026-05-06 (all rounds share)
# Target rounds:      13 (10 execution + 3 final audit)
# Max iterations:     14 (13 + 1 retry buffer)
# Completion promise: CYCLE07TOFLEETDONE
#
# USAGE:
#   bash dev/scripts/loop/start_cycle07_to_fleet_loop.sh
#
# WARNING: keep the prompt SINGLE-LINE with ASCII-only characters per
# prior lesson (Chinese punctuation + multi-line prompts break argparse).
#
# Note: NO `set -e` here. The launcher's only contract is to print the
# slash command. Pre-flight is informational; nothing in pre-flight may
# abort before the slash command reaches stdout.

PRD_PATH="docs/prd/20260506-cycle07_to_fleet_master_prd.md"
PRD_AC_PATH="docs/prd/20260505-mining_objective_nav_based_plus_execution_policy_prd.md"
PRD_E_PATH="docs/prd/20260505-taa_regime_allocation_framework_prd.md"
PRD_C1_PATH="docs/prd/20260501-two_stage_allocation_architecture_prd.md"

# Single-line ASCII-only prompt. AUTONOMOUS MODE per PRD section 9.
PROMPT='Execute one round per docs/prd/20260506-cycle07_to_fleet_master_prd.md v1.1 section 4 phase architecture. lineage_tag=cycle07-to-fleet-master-2026-05-06 for all artifacts. Execution order is 2->3->4->1 per PRD section 4 header. Round 1 = Phase A.2 RSI KDJ MACD IC screening on partition_for_role role=miner panel; dev/scripts/factor_screening/run_rsi_kdj_macd_ic_screen.py inline 3 factors plus IC plus 3-by-67 cor matrix plus per-factor verdict ELIGIBLE if max-cor under 0.6 or CONDITIONAL if 0.6 to 0.7 or REJECT if over 0.7; output JSON; closeout memo docs/memos/20260507-phase_a2_ic_screening_close.md. Round 2 = Phase A.1 cycle07a yaml authoring inheriting cycle06 verbatim except objective_weights per PRD section 4.1 plus smoke_n_trials override 8 to 16 per Issue I plus lineage_tag track-c-cycle-2026-05-07-01 plus yaml sha256 commit; 200-trial mining background run via scripts/run_research_miner.py with role=miner; Track A acceptance evaluation on top-3 archived trials via dev/scripts/cycle07a/cycle07a_track_a_eval.py mirroring cycle06 evaluator; closeout memo docs/memos/20260507-cycle07a_closeout.md with H1 Spearman plus H2 COMPLETE-state cells plus H3 Pareto plus Track A plus R41 verdicts plus branch decision per PRD section 4.2 B.3 table. Round 3 = Phase B.1 promote ELIGIBLE factors per Round 1 verdict to core/factors/factor_registry.py RESEARCH_FACTORS plus FAMILIES_V2 per PRD Issue J classification RSI to Family C and KDJ to Family B and MACD to Family D plus per-factor unit tests plus update test_aplusplus_families_v2_union_equals_research_factors count from 67; SKIP this round if 0 ELIGIBLE. Round 4 = Phase B.2 PRD-AC Phase 3 round 2 SR defer FULL mining integration per PRD-AC section 1.3 user explicit-go; ResearchMiner constructor loads 60m bars at instantiation; sampler enable_sr_defer_choices=False True no longer forced; evaluate_composite NAV path runs second BacktestEngine on filtered_weights when SR defer fires; I6 prefilter activation rate under 5 percent forces False; tests for SR defer applied plus integration plus cycle04 cycle05 cycle06 archive replay regression unchanged. Round 5 = Phase B.3 branch decision summary; if Round 2 cycle07a Track A produced nominee then forward init the candidate via dev/scripts/forward/init_<id>.py script using core/research/forward/runner.py init API mirroring trial9 pattern; else mark for fleet integration only; commit phase B closeout. Round 6 = Phase C.1 regime-conditional mining objective v3 design plus implementation; ObjectiveWeightsV3 dataclass with per-regime IR and NAV weights per PRD section 4.3 C.1 default; compute_objective dispatch via isinstance ObjectiveWeightsV3 per Issue N; evaluate_composite_regime_conditional new function consuming daily_regime_labels from core/research/taa/regime_label_generator.py; Issue D fallback rule when regime n_days under 200 on miner panel; tests for v3 objective plus regime stratification plus fallback. Round 7 = Phase C.2 cycle08 yaml plus 200-trial mining; cycle08 yaml inherits cycle07a verbatim except objective_version v3_regime_conditional plus enable_sr_defer_choices=False True if Round 4 landed plus factor_registry_pool RESEARCH_FACTORS post-Round 3 plus R41 anchor pool dynamic enumerate per Issue L including RCMv1 plus Cand-2 plus Trial9 plus cycle07a-nominee if Round 2 produced one; mining wall-clock 95 to 130 min. Round 8 = Phase C.3 cycle08 acceptance plus R41 sibling check plus G3 orthogonality check on top-3 trials; G3 anchor REPLAYED NAV via harness pattern per Issue C; G3 N-floor SKIP if joint TDs under 30 per Issue H; G3 PASS if at least 1 trial raw NAV cor under 0.70 vs RCMv1 plus Cand-2 plus Trial9 blend AND residual under 0.50. Round 9 = Phase C.4 closeout memo docs/memos/20260520-cycle08_closeout.md with G2 evidence BEAR-IC over 1.5x BULL-IC plus G3 verdict plus Track A verdict plus regime-conditional outcomes plus next-phase decision. Round 10 = Phase D.0 gate prerequisite check plus Phase D.1 fleet allocator PRD draft docs/prd/2026XXXX-fleet_allocator_prd.md; D.2 to D.4 implementation HARD GATED on both (a) at least 1 nominee passing Track A from Round 2 or Round 8 AND (b) Trial9 forward TD60 GREEN per CLAUDE.md ~2026-07-30 calendar; if either gate not met by ralph-loop end then D.1 PRD writing only and emit completion promise without D.2-D.4 code. Round 11 = AUDIT FINAL 1 full re-engagement on Phase A plus Phase B; read every prior round memo R1 to R5 and append cross-round meta-check section listing each prior PASS claim re-engaged with outcome CONFIRMED or CHALLENGED or ELEVATED; live e2e execution at least 3 commands not just pytest; reverse-validation of every Phase A B fix; doc-vs-code reconciliation; commit memo docs/audit/20260506-cycle07_fleet_audit_final_1.md. Round 12 = AUDIT FINAL 2 full re-engagement on Phase C; read R6 to R9 memos plus mining objective v3 code plus cycle08 archive; verify regime-conditional IC fallback fired correctly per Issue D plus G3 N-floor handled per Issue H plus R41 dynamic anchor pool per Issue L; live e2e execution; reverse-validation; doc-vs-code reconciliation; commit memo docs/audit/20260506-cycle07_fleet_audit_final_2.md. Round 13 = AUDIT FINAL 3 meta-audit plus Phase D plus G1 G2 G3 G4 success metrics verification per PRD section 5.2 plus cross-cycle sibling drift check vs cycle04 cycle05 cycle06 archives; verify the three cycle04-style sibling failure modes did NOT recur in cycle07a or cycle08 outputs; emit CYCLE07TOFLEETDONE at top level of assistant reply only when (all simultaneously true) all 13 rounds committed AND full unit test suite green AND README plus CLAUDE.md plus docs/INDEX.md updated AND data/baseline/latest.json regenerated AND PRD G1 G2 G3 G4 each have explicit verdict (met or partial or unmet with explanation) AND R11 R12 R13 audits all confirm zero unexplained pytest drift AND fleet allocator code only landed if D.0 gate (a) AND (b) both true; commit final synthesis docs/memos/20260506-cycle07_to_fleet_final_synthesis.md. PER-ROUND AUDIT EMBEDDED: every round R1 through R13 closes with a 4-layer self-audit before commit per memory feedback_self_audit_methodology.md - R1 factual is the numbers I claim grep-able; R2 logical do the conclusions follow from numbers and predecessor evidence; R3 actually-run did I execute the code path or am I reading test scaffolding; R4 boundary what edge cases would break this. Per-round audit findings appended to round memo as Self-Audit section. AUTONOMOUS MODE per PRD section 9 ralph-loop checkpoints: tactical decisions auto-advance per memory feedback_decision_authority_operator_audit_split.md; directional decisions pause for user (Phase B.3 branch decision if 0 nominee; Phase C anchor controversy; Phase D gate (a) (b) both not met; G3 anchor controversy raised in PRD section 2.3 G3 note on CLAUDE.md invariant). HARD INVARIANTS per PRD section 8 reversibility: do NOT modify PRD-AC v1.1 archives cycle04 cycle05 cycle06; do NOT modify PRD-E TAA modules dormant; do NOT consume sealed 2026 panel via partition_for_role role=sealed_test_runner; do NOT modify CLAUDE.md invariants long-only no-margin no-short fleet 2-candidate gate; do NOT modify PRODUCTION_FACTORS or config/production_strategy.yaml; do NOT auto-promote cycle07a or cycle08 nominee to fleet without R41 plus NAV pair correlation check; do NOT auto-promote Trial9 to fleet before TD60 GREEN. PYTEST DRIFT RULE: record pytest tuple (passed, skipped, xfailed) at start AND end of every round; any drift not explained by regression tests added this round MUST halt loop. PER-ROUND COMMIT MESSAGE FORMAT: cycle07-fleet R<N>: <phase>: <summary>. PER-ROUND CHINESE REPORT: append 11-part report to docs/20260420-ralph_loop_log.md as R-cycle07-to-fleet-2026-05-06-round-NN per existing convention. HALT CONDITIONS: (1) any HARD invariant violated; (2) same round retried twice without progress; (3) pytest drift not explained by this round regression tests; (4) single round runtime over 4 hours wall-clock excluding background mining; (5) sealed 2026 panel access detected; (6) RCMv1 or Cand-2 archive mutation detected; (7) cycle07a or cycle08 yaml sha256 mutation post-commit; (8) CYCLE07TOFLEETDONE successfully emitted (clean exit). Memos must include lineage_tag in YAML frontmatter or first line. R13 reply must emit literal CYCLE07TOFLEETDONE token at top level (not only inside committed markdown).'

# Print the slash command FIRST so it's always visible no matter what
# the pre-flight or terminal does.
cat <<EOF
================================================================================
Cycle 07 -> Fleet Master 13-Round Ralph-Loop Setup
================================================================================

PRD:                 $PRD_PATH
PRD-AC predecessor:  $PRD_AC_PATH
PRD-E predecessor:   $PRD_E_PATH
PRD-C1 predecessor:  $PRD_C1_PATH
Lineage tag:         cycle07-to-fleet-master-2026-05-06
Target rounds:       13 (10 execution + 3 final audit)
Max iterations:      14 (13 + 1 retry buffer)
Completion promise:  CYCLE07TOFLEETDONE

ROUND PLAN (one focus per round; per-round 4-layer audit embedded;
            execution order = 2 -> 3 -> 4 -> 1 per PRD section 4):

  R1  -- Phase A.2  RSI/KDJ/MACD IC screening on miner panel
                    dev/scripts/factor_screening/run_rsi_kdj_macd_ic_screen.py
                    Per-factor verdict ELIGIBLE / CONDITIONAL / REJECT
                    Closeout: docs/memos/20260507-phase_a2_ic_screening_close.md

  R2  -- Phase A.1  cycle07a yaml inherit + 200-trial mining (~65 min bg)
                    Track A on top-3 + H1+H2+H3+R41 verdicts
                    Branch decision per PRD section 4.2 B.3 table
                    Closeout: docs/memos/20260507-cycle07a_closeout.md

  R3  -- Phase B.1  Promote ELIGIBLE factors per R1 verdict to
                    RESEARCH_FACTORS + FAMILIES_V2 per Issue J
                    (RSI->C / KDJ->B / MACD->D; no Family G branching)
                    SKIP if 0 ELIGIBLE

  R4  -- Phase B.2  SR defer mining FULL integration (PRD-AC sec 1.3)
                    60m bar loading + second BacktestEngine path +
                    I6 prefilter (under 5 pct activation -> False)
                    Cycle04/05/06 replay regression unchanged

  R5  -- Phase B.3  Branch decision summary; if R2 cycle07a nominee
                    produced -> forward init via runner.init pattern
                    Else mark for fleet integration only

  R6  -- Phase C.1  Regime-conditional mining objective v3 design + impl
                    ObjectiveWeightsV3 + isinstance dispatch (Issue N)
                    Issue D fallback when regime n_days under 200 on miner
                    Reuse core/research/taa/regime_label_generator.py

  R7  -- Phase C.2  cycle08 yaml + 200-trial mining (~95-130 min bg)
                    R41 anchor pool dynamic enumerate per Issue L
                    Single-axis diff vs cycle07a = regime-conditional obj

  R8  -- Phase C.3  cycle08 acceptance + R41 + G3 orthogonality
                    G3 REPLAYED NAV per Issue C
                    G3 N-floor SKIP if joint TDs < 30 per Issue H
                    G3 PASS if 1+ trial raw < 0.70 AND residual < 0.50

  R9  -- Phase C.4  cycle08 closeout memo + branch decision
                    Phase D.0 prerequisite assessment

  R10 -- Phase D.0  Gate (a) at least 1 nominee passing Track A
                    Gate (b) Trial9 forward TD60 GREEN (~2026-07-30)
        Phase D.1   Fleet allocator PRD draft writing
                    D.2-D.4 impl HARD GATED on (a) AND (b) both true

  R11 -- AUDIT FINAL 1   Phase A + Phase B full re-engagement
                         Read R1-R5 memos; append cross-round meta-check
                         Each prior PASS claim re-engaged with verdict
                         CONFIRMED / CHALLENGED / ELEVATED
                         Live e2e execution >=3 commands; reverse-validate
                         Memo: docs/audit/20260506-cycle07_fleet_audit_final_1.md

  R12 -- AUDIT FINAL 2   Phase C full re-engagement
                         Read R6-R9 memos; verify Issue D fallback
                         + Issue H N-floor + Issue L dynamic anchor
                         Memo: docs/audit/20260506-cycle07_fleet_audit_final_2.md

  R13 -- AUDIT FINAL 3   Meta-audit + Phase D + G1-G4 verdicts
                         Cross-cycle sibling drift check vs cycle04/05/06
                         Verify cycle04-style sibling failure modes
                         did NOT recur
                         Final synthesis:
                           docs/memos/20260506-cycle07_to_fleet_final_synthesis.md
                         Emit CYCLE07TOFLEETDONE at top level of reply

PER-ROUND 4-LAYER AUDIT EMBEDDED (memory feedback_self_audit_methodology.md):
  R1 factual    -- numbers I claim are grep-able / dataset-verifiable
  R2 logical    -- conclusions follow from numbers + predecessor evidence
  R3 run        -- I executed the code path, not just read scaffolding
  R4 boundary   -- edge cases that would break this finding
  Findings appended to round memo as "Self-Audit" section before commit.

HARD INVARIANTS (violation halts loop, per PRD section 8):
  - no edits to RCMv1 / Cand-2 / cycle04/05/06 archives or yamls
  - no edits to PRD-E TAA modules (preserved dormant per PRD-E close)
  - no consumption of sealed 2026 panel (sealed_test_runner role banned)
  - no edits to CLAUDE.md invariants (long-only / no-margin / no-short /
    fleet 2-candidate gate / sealed single-shot)
  - no edits to PRODUCTION_FACTORS or config/production_strategy.yaml
  - no auto-promote cycle07a/cycle08 nominee to fleet without R41
    + NAV pair correlation check
  - no auto-promote Trial9 to fleet before TD60 GREEN
  - no cycle07a/cycle08 yaml sha256 mutation post-commit (immutability)

PYTEST DRIFT RULE:
  Every round logs pre/post pytest tuple (passed, skipped, xfailed).
  Allowed drift: +N for new regression tests added this round only.
  Unexpected drift -> HALT and surface to user.

HALT CONDITIONS:
  1. Any HARD invariant violated
  2. Same round retried twice without progress
  3. Pytest drift not explained by this round regression tests
  4. Single round runtime > 4 hours wall-clock (excluding bg mining)
  5. Sealed 2026 panel access detected
  6. RCMv1 / Cand-2 / cycle04-06 archive mutation detected
  7. Cycle07a / cycle08 yaml sha256 mutation post-commit
  8. CYCLE07TOFLEETDONE successfully emitted (clean exit)

DIRECTIONAL DECISIONS THAT PAUSE FOR USER:
  - Phase B.3 branch decision if cycle07a 0 nominee + 0 ELIGIBLE
  - Phase C anchor controversy (RCMv1+Cand-2+Trial9 anchor as
    objective term vs hard gate; PRD section 2.3 G3 note)
  - Phase D gate (a) AND (b) both not met at R10 (whether to ship
    D.1 PRD only and end loop, or extend to wait for Trial9 TD60)
  - G3 anchor invariant interpretation if user disputes term/gate
    distinction (PRD section 2.3 G3 note)

PRE-FLIGHT CHECKLIST (run before pasting the command below):

1. Git working tree clean:
       git status
2. Pre-loop pytest baseline (record this tuple -- R1 must preserve
   or justify every delta via regression tests added this round):
       /home/zibo/miniconda3/envs/pqs/bin/python -m pytest tests/ -q --tb=no | tail -3
3. Baseline snapshot readable:
       jq '.tests' data/baseline/latest.json
4. Core import smoke (TAA + research_miner + forward runner):
       /home/zibo/miniconda3/envs/pqs/bin/python -c "from core.research.taa.regime_label_generator import daily_regime_labels; from core.mining.research_miner import ResearchMiner, ObjectiveWeights; from core.research.forward.runner import ForwardRunner; print('core OK')"
5. Cycle06 archive readable (anchor for v1 vs v2 Spearman in R2):
       /home/zibo/miniconda3/envs/pqs/bin/python -c "
       import sqlite3
       c = sqlite3.connect('data/ml/research_miner/track-c-cycle-2026-05-06-01/rcm_archive.db').cursor()
       n = c.execute('SELECT COUNT(*) FROM rcm_trials').fetchone()[0]
       assert n > 0, 'cycle06 archive empty'
       print(f'cycle06 archive trials: {n}')
       "
6. Trial9 forward manifest readable (Phase D.0 gate (b) status):
       test -f data/research_candidates/trial9_diversifier_001_forward_manifest.json && echo 'trial9 manifest OK'
7. PRD readable + sha256 stable:
       test -f $PRD_PATH && sha256sum $PRD_PATH | head -c 12 && echo "..."
8. Disk check (need >= 20 GB; mining + bg processes):
       df -h .

--------------------------------------------------------------------------------
PASTE THIS INTO CLAUDE CODE (single line, starts with /ralph-loop:ralph-loop):
--------------------------------------------------------------------------------

/ralph-loop:ralph-loop "\$PROMPT" --max-iterations 14 --completion-promise CYCLE07TOFLEETDONE

EOF

# Print the slash command WITH the prompt expanded so user can copy in one shot.
echo "--------------------------------------------------------------------------------"
echo "Or expanded version (copy this whole line):"
echo "--------------------------------------------------------------------------------"
echo
echo "/ralph-loop:ralph-loop \"$PROMPT\" --max-iterations 14 --completion-promise CYCLE07TOFLEETDONE"
echo
cat <<EOF
--------------------------------------------------------------------------------
During the loop (informational):
--------------------------------------------------------------------------------

- Per-round commit + 11-part Chinese report appended to
  docs/20260420-ralph_loop_log.md
  (section header: "R-cycle07-to-fleet-2026-05-06-round-NN")

- Round commit message convention:
       cycle07-fleet R1: phase-A.2: RSI/KDJ/MACD IC screening
       cycle07-fleet R2: phase-A.1: cycle07a mining + Track A verdict
       cycle07-fleet R7: phase-C.2: cycle08 regime-conditional mining
       cycle07-fleet R11: audit-final-1: Phase A+B re-engagement
       cycle07-fleet R13: audit-final-3: meta-audit + CYCLE07TOFLEETDONE

- To halt mid-loop:
       rm .claude/ralph-loop.local.md
  Or use /ralph-loop:cancel-ralph

- R13 must:
  * Emit CYCLE07TOFLEETDONE at TOP LEVEL of assistant reply
    (not only inside committed markdown)
  * Commit final synthesis memo +
    CLAUDE.md TODO update + docs/INDEX.md update +
    data/baseline/latest.json regen
  * Verify G1-G4 each have explicit verdict (met / partial / unmet)
  * Verify zero unexplained pytest drift across all 13 rounds
  * Verify zero sealed 2026 panel access in any round
  * Verify R11/R12/R13 cross-round meta-checks all CONFIRMED
  * Verify fleet allocator code only landed if D.0 gate (a)+(b)
    both true (else PRD writing only)

EOF

# Pre-flight checks (informational; never abort). Run after the slash
# command so the user's primary deliverable is already on stdout.
echo
echo "Pre-flight (informational):"

# PRD presence
for prd in "$PRD_PATH" "$PRD_AC_PATH" "$PRD_E_PATH" "$PRD_C1_PATH"; do
    if [[ -f "$prd" ]]; then
        echo "  [OK]   PRD: $prd"
    else
        echo "  [WARN] PRD missing: $prd"
    fi
done

# Working tree
if git diff --quiet 2>/dev/null && git diff --cached --quiet 2>/dev/null; then
    echo "  [OK]   working tree clean"
else
    echo "  [WARN] working tree has uncommitted changes"
fi

# Project venv python
PQS_PYTHON="${PQS_PYTHON:-/home/zibo/miniconda3/envs/pqs/bin/python}"
if [[ -x "$PQS_PYTHON" ]]; then
    if "$PQS_PYTHON" -c "from core.research.taa.regime_label_generator import daily_regime_labels; from core.mining.research_miner import ResearchMiner; from core.research.forward.runner import ForwardRunner" >/dev/null 2>&1; then
        echo "  [OK]   core imports (TAA + research_miner + forward) OK ($PQS_PYTHON)"
    else
        echo "  [WARN] core imports failed under $PQS_PYTHON (TAA / research_miner / forward)"
    fi
else
    echo "  [WARN] PQS python not found at $PQS_PYTHON (set PQS_PYTHON env var)"
fi

# Cycle06 archive (R2 anchor for v1 vs v2 Spearman comparison)
if [[ -f data/ml/research_miner/track-c-cycle-2026-05-06-01/rcm_archive.db ]]; then
    echo "  [OK]   cycle06 archive present (R2 v1 vs v2 Spearman anchor)"
else
    echo "  [WARN] cycle06 archive missing -- R2 H1 Spearman comparison will skip"
fi

# Trial9 forward manifest (Phase D.0 gate (b) status check)
if [[ -f data/research_candidates/trial9_diversifier_001_forward_manifest.json ]]; then
    n_runs=$("$PQS_PYTHON" -c "
import json
m = json.load(open('data/research_candidates/trial9_diversifier_001_forward_manifest.json'))
print(len(m.get('runs', [])))
" 2>/dev/null)
    echo "  [OK]   Trial9 forward manifest present (n_runs=$n_runs; TD60 gate at >=60)"
else
    echo "  [WARN] Trial9 forward manifest missing -- Phase D.0 gate (b) cannot be evaluated"
fi

# PRD sha256 (PRD immutability check)
if [[ -f "$PRD_PATH" ]]; then
    PRD_SHA=$(sha256sum "$PRD_PATH" | cut -c1-12)
    echo "  [OK]   PRD sha256 (first 12): $PRD_SHA"
fi

# Baseline test count
if [[ -f data/baseline/latest.json ]]; then
    baseline_tests=$(jq -r '.tests.passed // .tests.collected // empty' data/baseline/latest.json 2>/dev/null)
    if [[ -n "$baseline_tests" ]]; then
        echo "  [OK]   baseline tests passed: $baseline_tests"
    else
        echo "  [WARN] data/baseline/latest.json schema unexpected"
    fi
else
    echo "  [WARN] data/baseline/latest.json missing (R13 will rebuild)"
fi

# Disk
disk_gb=$(df -BG --output=avail . 2>/dev/null | tail -1 | tr -dc '0-9')
if [[ ${disk_gb:-0} -ge 20 ]]; then
    echo "  [OK]   disk free ${disk_gb}G"
elif [[ -n "$disk_gb" ]]; then
    echo "  [WARN] disk free ${disk_gb}G < 20G (mining + bg processes need headroom)"
fi
