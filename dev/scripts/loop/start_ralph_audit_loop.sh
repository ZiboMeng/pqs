#!/bin/bash
# Start the 10-round ralph-loop audit (forward evidence v2.1.3 + codebase-wide).
#
# Reference PRD: docs/prd/20260428-ralph_audit_loop_prd.md
# Lineage tag:        ralph-audit-2026-04-28
# Max iterations:     10 (3 deep + 7 codebase-wide)
# Completion promise: RALPHAUDIT10DONE
#
# USAGE: bash dev/scripts/loop/start_ralph_audit_loop.sh
#
# WARNING: keep the prompt SINGLE-LINE with ASCII-only characters per
# prior lesson (Chinese punctuation + multi-line prompts break argparse).
#
# Note: NO `set -e` here. The launcher's only contract is to print the
# slash command. Pre-flight is informational; nothing in pre-flight may
# abort before the slash command reaches stdout.

PRD_PATH="docs/prd/20260428-ralph_audit_loop_prd.md"

# ASCII-only single-line prompt for /ralph-loop:ralph-loop
PROMPT='Execute one round per docs/prd/20260428-ralph_audit_loop_prd.md section 4 round briefs. lineage_tag=ralph-audit-2026-04-28. Phase A is 3 deep rounds on forward evidence v2.1.3 (R1=A1 module + contract + reverse-validate v2.1.3 fixes; R2=A2 adversarial scenarios; R3=A3 forward documentation sync). Phase B is 7 cumulative-pass full-codebase rounds, NOT divide-and-conquer slices: each Phase B round audits the ENTIRE codebase under a different lens, and each subsequent round explicitly re-engages prior rounds PASS claims. R4=B1 static and contract lens. R5=B2 live e2e execution lens. R6=B3 adversarial corner-case lens with at least 30 scenarios. R7=B4 cross-cutting invariant lens. R8=B5 determinism and reproducibility lens. R9=B6 documentation truth lens with README changelog removal. R10=B7 meta-audit and final consolidation. Hard rules section 3 apply every round: live e2e execution at least 3 commands not just pytest, reverse-validation required for every fix, real-data fixtures only no bdate_range for trading-calendar tests, findings classified blocker non-blocker docs-only cosmetic, doc-vs-code reconciliation per round, README must contain zero update log or changelog content, memo at docs/audit/20260428-ralph_audit_round_NN.md with frontmatter status PASS or FIX_LANDED or BLOCKERS_OPEN, 11-part Chinese summary in docs/20260420-ralph_loop_log.md as R-ralph-audit-2026-04-28-round-NN, AND for Phase B every round after the first must read every prior B-round memo and append a cross-round meta-check section listing each prior PASS claim re-engaged with outcome CONFIRMED or CHALLENGED or ELEVATED. AUTONOMOUS MODE: section 6 Authorized autonomously rules; pause to surface per section 6 Pause for user. Halt per section 5 conditions. Push memo to review/claude-collab end of every round; code and doc fixes to main. Emit RALPHAUDIT10DONE only after all 10 rounds complete with status PASS or FIX_LANDED, full unit suite green, README clean of changelog, baseline refreshed, CLAUDE.md plus docs/INDEX.md reconciled, and R10 meta-audit confirms the three failure modes from PRD section 1 did NOT recur in any round.'

# Print the slash command FIRST so it's always visible no matter what
# the pre-flight or terminal does.
cat <<EOF
============== Paste this into Claude Code (single line below) =================

/ralph-loop:ralph-loop "$PROMPT" --max-iterations 10 --completion-promise RALPHAUDIT10DONE

================================================================================

PRD:        $PRD_PATH
Lineage:    ralph-audit-2026-04-28
Iterations: 10 (Phase A: 3 deep on forward v2.1.3 / Phase B: 7 cumulative-pass codebase)
Promise:    RALPHAUDIT10DONE

(Round briefs + hard rules + authority + halt conditions live in the PRD.)
EOF

# Pre-flight checks (informational; never abort). Run after the slash
# command so the user's primary deliverable is already on stdout.
echo
echo "Pre-flight (informational):"

# PRD presence
if [[ -f "$PRD_PATH" ]]; then
    echo "  [OK]   PRD: $PRD_PATH"
else
    echo "  [WARN] PRD missing: $PRD_PATH (commit it before launching the loop)"
fi

# Working tree
if git diff --quiet 2>/dev/null && git diff --cached --quiet 2>/dev/null; then
    echo "  [OK]   working tree clean"
else
    echo "  [WARN] working tree has uncommitted changes"
fi

# Project venv python
PQS_PYTHON="${PQS_PYTHON:-/home/zibo/miniconda3/envs/pqs/bin/python}"
if [[ -x "$PQS_PYTHON" ]]; then
    if "$PQS_PYTHON" -c "from core.research.forward import compute_signal_input_hash" >/dev/null 2>&1; then
        echo "  [OK]   forward module imports ($PQS_PYTHON)"
    else
        echo "  [WARN] forward module import failed under $PQS_PYTHON"
    fi
else
    echo "  [WARN] PQS python not found at $PQS_PYTHON (set PQS_PYTHON env var)"
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
    echo "  [WARN] data/baseline/latest.json missing (Round 3 will rebuild)"
fi

# Disk
disk_gb=$(df -BG --output=avail . 2>/dev/null | tail -1 | tr -dc '0-9')
if [[ ${disk_gb:-0} -ge 10 ]]; then
    echo "  [OK]   disk free ${disk_gb}G"
elif [[ -n "$disk_gb" ]]; then
    echo "  [WARN] disk free ${disk_gb}G < 10G (halt-condition risk)"
fi
