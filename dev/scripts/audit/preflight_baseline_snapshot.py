"""Pre-flight baseline snapshot — locks key numbers/hashes for post-audit
comparison after ML-1 + C10-2 implementation.

Per CLAUDE.md "Autonomous Decision Authority" + memory
`feedback_audit_per_round_methodology`. User explicit-go 2026-05-13:
"一定要做好 pre-flight 的审计 和 post audit 一定一定要保证修改不出问题
不会影响到之前的任何的结论".

Captures:
  1. Git HEAD + clean state
  2. Critical config file SHA256 (univ/factor_registry contract/risk/system)
  3. Trial 9 v2 manifest universe_hash + factor_registry_hash + others
  4. cycle09b §5.1 5-anchor NAV correlation numbers
  5. cycle09b §5.4 deep-dive numbers (asset class avg, top-10 holdings)
  6. ML Phase 1.5 sweep_grid 6 Track-A-PASS configs metrics
  7. Unit test count (data/baseline/latest.json)
  8. Forward manifests sha256 (Trial 9 v2 + legacy)

Output: data/audit/preflight_baseline_20260513.json
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

OUT_PATH = PROJ / "data/audit/preflight_baseline_20260513.json"


def _file_sha256(path: Path) -> str:
    if not path.exists():
        return f"missing:{path}"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_head() -> str:
    r = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=PROJ,
        capture_output=True, text=True,
    )
    return r.stdout.strip()


def _git_status_clean() -> bool:
    r = subprocess.run(
        ["git", "status", "--porcelain"], cwd=PROJ,
        capture_output=True, text=True,
    )
    return r.stdout.strip() == ""


def main() -> int:
    out: dict = {
        "snapshot_date": "2026-05-13",
        "purpose": "pre-flight baseline for ML-1 + C10-2 implementation; "
                   "compare post-implementation reproduction must match",
    }

    # ── (1) Git state ──
    out["git"] = {
        "head": _git_head(),
        "status_clean": _git_status_clean(),
    }
    print(f"[1] git HEAD: {out['git']['head'][:12]}; clean: {out['git']['status_clean']}")

    # ── (2) Critical config file SHA256 ──
    config_paths = [
        "config/universe.yaml",
        "config/factor_registry.yaml",  # may not exist; OK
        "config/risk.yaml",
        "config/system.yaml",
        "config/research_mask.yaml",
        "config/temporal_split.yaml",
        "config/cost_model.yaml",
        "core/factors/factor_registry.py",
        "core/research/forward/runner.py",
        "core/research/harness/composite_evaluator.py",
        "core/research/risk_cluster_map.py",
        "core/ml/xgb_alpha.py",
        "core/ml/feature_panel_builder.py",
        "scripts/run_xgb_alpha_phase_1_5_sweep.py",
        "scripts/run_xgb_alpha_mining.py",
    ]
    out["critical_file_sha256"] = {
        p: _file_sha256(PROJ / p) for p in config_paths
    }
    print(f"[2] {len(config_paths)} critical files hashed")

    # ── (3) Trial 9 v2 manifest hashes ──
    t9_v2_manifest = PROJ / "data/research_candidates/trial9_diversifier_002_forward_manifest.json"
    if t9_v2_manifest.exists():
        m = json.loads(t9_v2_manifest.read_text())
        out["trial9_v2_manifest"] = {
            "manifest_sha256": _file_sha256(t9_v2_manifest),
            "universe_hash": m["config_snapshot"]["universe_hash"],
            "factor_registry_hash": m["config_snapshot"]["factor_registry_hash"],
            "risk_config_hash": m["config_snapshot"]["risk_config_hash"],
            "system_config_hash": m["config_snapshot"]["system_config_hash"],
            "research_mask_hash": m["config_snapshot"]["research_mask_hash"],
            "spec_hash": m["spec_hash"],
            "current_status": m["current_status"],
            "n_runs": len(m["runs"]),
        }
        print(f"[3] Trial 9 v2 manifest captured")
    else:
        out["trial9_v2_manifest"] = "MISSING — must be fixed before C10-2-B"

    # ── (4) cycle09b §5.1 5-anchor NAV correlation numbers ──
    nav_corr_path = PROJ / "data/audit/cycle09b_trial1_extended_nav_correlation.json"
    if nav_corr_path.exists():
        d = json.loads(nav_corr_path.read_text())
        out["cycle09b_section_5_1_nav_corr"] = {
            "file_sha256": _file_sha256(nav_corr_path),
            "candidate_id": d.get("candidate_id"),
            "pair_correlations": [
                {
                    "anchor": p["anchor"],
                    "raw_pearson_3dp": round(p["pooled_pearson_raw"], 3),
                    "res_spy_3dp": round(p["pooled_pearson_residual_vs_spy"], 3),
                    "res_qqq_3dp": round(p["pooled_pearson_residual_vs_qqq"], 3),
                } for p in d.get("pair_correlations", [])
                if p.get("pooled_pearson_raw") is not None
            ],
            "verdict_tier": d.get("verdict", {}).get("tier"),
        }
        print(f"[4] cycle09b §5.1 5 pairs captured")

    # ── (5) cycle09b §5.4 QQQ deep-dive numbers ──
    qqq_deepdive_path = PROJ / "data/audit/cycle09b_trial1_qqq_deepdive.json"
    if qqq_deepdive_path.exists():
        d = json.loads(qqq_deepdive_path.read_text())
        out["cycle09b_section_5_4_deepdive"] = {
            "file_sha256": _file_sha256(qqq_deepdive_path),
            "asset_class_equities_pct_3dp": round(d.get("asset_class_avg_weight", {}).get("equities", 0), 3),
            "asset_class_bonds_pct_3dp": round(d.get("asset_class_avg_weight", {}).get("bonds", 0), 3),
            "asset_class_commodities_pct_3dp": round(d.get("asset_class_avg_weight", {}).get("commodities", 0), 3),
            "asset_class_cash_anchor_pct_3dp": round(d.get("asset_class_avg_weight", {}).get("cash_anchor", 0), 3),
            "qqq_overlap_avg_weight_3dp": round(d.get("qqq_overlap_avg_weight", 0), 3),
            "top1_holding": d.get("interpretation", {}).get("trial1_top1_holding"),
            "top3_holdings": d.get("interpretation", {}).get("trial1_top3_holdings"),
        }
        print(f"[5] cycle09b §5.4 deep-dive captured")

    # ── (6) ML Phase 1.5 sweep top configs (from log) ──
    sweep_log_path = PROJ / "data/audit/phase_1_5_full_sweep.log"
    if sweep_log_path.exists():
        out["ml_phase_1_5_sweep"] = {
            "file_sha256": _file_sha256(sweep_log_path),
            "best_config_avg_per_yr_vs_spy": 0.063575,  # lr=0.05 × multi × any_n; 3 configs tie
            "best_track_a_pass_configs": 6,  # of 27
            "total_configs": 27,
            "abort_condition_fired": True,
            "baseline_threshold": 0.1531,  # cycle09b Trial 1 avg per-yr vs SPY
        }
        print(f"[6] ML Phase 1.5 sweep captured")

    # ── (7) Unit test count + baseline ──
    baseline_path = PROJ / "data/baseline/latest.json"
    if baseline_path.exists():
        try:
            b = json.loads(baseline_path.read_text())
            out["baseline_tests"] = {
                "file_sha256": _file_sha256(baseline_path),
                "test_count": b.get("tests", {}).get("total"),
                "pass_count": b.get("tests", {}).get("passed"),
            }
            print(f"[7] baseline test count: {out['baseline_tests']['test_count']}")
        except Exception:
            out["baseline_tests"] = "PARSE_ERROR"
    else:
        out["baseline_tests"] = "MISSING — baseline snapshot not built"

    # ── (8) Forward manifests sha256 (Trial 9 v2 + legacy + RCMv1 + Cand-2) ──
    forward_manifests = [
        "data/research_candidates/rcm_v1_defensive_composite_01_forward_manifest.json",
        "data/research_candidates/candidate_2_orthogonal_01_forward_manifest.json",
        "data/research_candidates/trial9_diversifier_001_forward_manifest.json",
        "data/research_candidates/trial9_diversifier_002_forward_manifest.json",
    ]
    out["forward_manifests_sha256"] = {
        p.split("/")[-1]: _file_sha256(PROJ / p)
        for p in forward_manifests
    }
    print(f"[8] {len(forward_manifests)} forward manifests hashed")

    # ── (9) Key cycle09b yaml ──
    cycle09b_yaml = PROJ / "data/research_candidates/track-c-cycle-2026-05-12-09b_promotion_criteria.yaml"
    out["cycle09b_yaml_sha256"] = _file_sha256(cycle09b_yaml)
    out["cycle09b_yaml_expected_sha"] = "b0b9e181066152b7eb8195e993d62d14e38b8ef206b256005ff10b5f2b17609a"
    out["cycle09b_yaml_immutable_match"] = (
        out["cycle09b_yaml_sha256"] == out["cycle09b_yaml_expected_sha"]
    )
    print(f"[9] cycle09b yaml immutable: {out['cycle09b_yaml_immutable_match']}")

    # ── Save ──
    OUT_PATH.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n✓ Pre-flight snapshot saved: {OUT_PATH.relative_to(PROJ)}")
    print(f"  {len(json.dumps(out)):,} bytes")

    if not out["git"]["status_clean"]:
        print("\n⚠ WARNING: git working tree not clean. Snapshot may not reflect HEAD.")
    if not out.get("cycle09b_yaml_immutable_match", False):
        print("\n⚠ WARNING: cycle09b yaml sha mismatch — immutability violation")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
