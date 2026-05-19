#!/usr/bin/env bash
# Verify the leakage-correct-DEFAULT flip (2026-05-18, user go):
#  - default run (no env) = NEW honest canonical (leakage-correct)
#  - CHART_L3_LEGACY_NO_LEAKAGE_CORR=1 = reproduce the OLD leakage-naive
#    canonical, must be bit-identical to /tmp/l3_canonical_preDiag.json
#    (proves the legacy escape hatch is exact + isolates the delta).
# Serial (single GPU; feedback_heavy_training_serial_wsl).
set -u
PY=/home/zibo/miniconda3/envs/pqs/bin/python
S=dev/scripts/chart_native_l3/run_chart_native_l3_track_a.py
L=data/audit/ml_redo
cd /home/zibo/Documents/projects/pqs

echo "=== run L: legacy (reproduce old leakage-naive canonical) ==="
CHART_L3_LEGACY_NO_LEAKAGE_CORR=1 $PY $S > $L/l3_lc_legacy.log 2>&1
$PY - <<'EOF'
import json
a=json.load(open('/tmp/l3_canonical_preDiag.json'))
b=json.load(open('data/audit/chart_native_l3_track_a_legacyNoCorr.json'))
K=['track_a_overall_passed','track_a_failed_gates','metrics_full_period','metrics_per_year','metrics_per_stress','cpcv_gate','overfit_diagnostics','no_leakage']
d=[k for k in K if json.dumps(a.get(k),sort_keys=True,default=str)!=json.dumps(b.get(k),sort_keys=True,default=str)]
print("LEGACY BIT-IDENTICAL vs old canonical:", "PASS — NONE differ" if not d else f"FAIL — {d}")
EOF

echo "=== run D: default = NEW leakage-correct canonical ==="
$PY $S > $L/l3_lc_default.log 2>&1
$PY - <<'EOF'
import json
d=json.load(open('data/audit/chart_native_l3_track_a.json'))
print("NEW canonical (leakage-correct default):",
      "PASS" if d.get('track_a_overall_passed') else "FAIL",
      "| failed=", d.get('track_a_failed_gates'),
      "| oos_ic=", d.get('oos_rank_ic'),
      "| leakage_correct_default=", d.get('leakage_correct_default'),
      "| flags=", d.get('diagnostic_flags'))
EOF
echo "=== DONE ==="
