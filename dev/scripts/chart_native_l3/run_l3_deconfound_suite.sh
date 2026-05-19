#!/usr/bin/env bash
# L3 de-confound + correctness suite (2026-05-18, user "两个一起跑").
# Serial (single GPU; feedback_heavy_training_serial_wsl). All runs
# keep the canonical executable Track-A bit-identical on gates (new
# behavior is env-flagged; IC-on-59 is additive-only).
#   run2 = 79-train/59-trade  (default, no flags) → canonical + IC-on-59
#   run1 = 59-train/59-trade  (CHART_L3_PROBE_FIT_CLUSTERMAP_ONLY=1)
#   run4 = (a) correctness    (CHART_L3_SAMPLE_UNIQ=1 + CHART_L3_PURGE_EMBARGO=1)
#   run3 = 1k-train/59-trade  (CHART_L3_UNIVERSE=expanded_v2)
set -u
PY=/home/zibo/miniconda3/envs/pqs/bin/python
S=dev/scripts/chart_native_l3/run_chart_native_l3_track_a.py
L=data/audit/ml_redo
cd /home/zibo/Documents/projects/pqs

echo "=== run2: 79-train/59-trade (default, canonical bit-identical + IC-on-59) ==="
$PY $S > $L/l3_dc_run2_79.log 2>&1
$PY - <<'EOF'
import json
a=json.load(open('/tmp/l3_canonical_preDiag.json'))
b=json.load(open('data/audit/chart_native_l3_track_a.json'))
K=['track_a_overall_passed','track_a_failed_gates','metrics_full_period','metrics_per_year','metrics_per_stress','cpcv_gate','overfit_diagnostics','no_leakage']
d=[k for k in K if json.dumps(a.get(k),sort_keys=True,default=str)!=json.dumps(b.get(k),sort_keys=True,default=str)]
print("BIT-IDENTICAL CHECK (run2 gates vs canonical):", "PASS — NONE differ" if not d else f"FAIL — {d}")
print(" run2 oos_rank_ic:", b.get('oos_rank_ic'))
EOF

echo "=== run1: 59-train/59-trade (fit clustermap-only) ==="
CHART_L3_PROBE_FIT_CLUSTERMAP_ONLY=1 $PY $S > $L/l3_dc_run1_59.log 2>&1

echo "=== run4: correctness (sample-uniqueness + purge/embargo) on 79 ==="
CHART_L3_SAMPLE_UNIQ=1 CHART_L3_PURGE_EMBARGO=1 $PY $S > $L/l3_dc_run4_corr.log 2>&1

echo "=== run3: 1k-train/59-trade (expanded_v2) ==="
CHART_L3_UNIVERSE=expanded_v2 $PY $S > $L/l3_dc_run3_1k.log 2>&1

echo "=== SUITE SUMMARY ==="
$PY - <<'EOF'
import json, glob
files={
 'run1_59train': 'data/audit/chart_native_l3_track_a_fitcmap59.json',
 'run2_79train': 'data/audit/chart_native_l3_track_a.json',
 'run4_79_corr': 'data/audit/chart_native_l3_track_a_suniq_purge.json',
 'run3_1ktrain': 'data/audit/chart_native_l3_track_a_expanded_v2.json',
}
for tag,f in files.items():
    try:
        d=json.load(open(f))
        mp=d.get('metrics_full_period',{})
        print(f"{tag}: {'PASS' if d.get('track_a_overall_passed') else 'FAIL'} "
              f"| failed={d.get('track_a_failed_gates')} "
              f"| oos_ic={d.get('oos_rank_ic')} "
              f"| cum_ret={mp.get('cum_ret'):.3f} vs_spy={mp.get('vs_spy'):.3f} "
              f"max_dd={mp.get('max_dd'):.4f} "
              f"| n_fit={d.get('no_leakage',{}).get('probe_fit_train_rows')} "
              f"| flags={d.get('diagnostic_flags')}")
    except Exception as e:
        print(f"{tag}: ERR {e!r} ({f})")
EOF
echo "=== DONE ==="
