#!/usr/bin/env python3
"""LLM-Round 25 tool: Layer 3 priority bucket assignment.

Reads universe_risk_labels output (Layer 2) and applies v2.2 §4
bucket rules. Outputs a candidate list partitioned by bucket.

Per v2.2 §4, 4 primary buckets + Unscored:
  - Alpha Core (4.1)
  - Diversifiers (4.2) — with R23 coverage-test relaxation
  - Tactical High-Beta Alpha (4.3)
  - Proxy / Redundant (4.4)
  - Unscored (4.5, fails all bucket criteria)

SYMBOL-INTRINSIC CRITERIA implemented now (what Layer 2 provides):
  - alpha_positive_rate
  - alpha_t_stat
  - alpha_subperiod_consistency
  - r2_max
  - beta_spy, beta_qqq
  - tail_correlation_to_spy

PORTFOLIO-RELATIVE CRITERIA DEFERRED (require chicken-and-egg iteration):
  - corr_to_portfolio
  - marginal_drawdown_contribution
  - marginal_sharpe_contribution

Layer 3 "provisional" bucket assignment: uses intrinsic metrics only;
marks symbols as "PROVISIONAL_<bucket>" when they depend on
portfolio-relative metrics. Final bucket finalization requires a
second-pass portfolio-aware run.

v2.2 coverage-test relaxation (R23 item 2):
  - If final Diversifier count < `min_diversifier_count`:
    relax corr_to_portfolio max 0.50 → 0.60 OR tail_correlation max
    0.50 → 0.60
  - NEVER relax marginal_dd_contribution or the semantic core

Does NOT modify config. Produces candidate bucket CSV for user review.

Usage
-----
    python scripts/universe_bucket_assign.py \\
        --labels-csv data/ml/universe_risk_labels_r22_test.csv \\
        --out-tag r22_test_buckets
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from core.logging_setup import get_logger, setup_logging

setup_logging()
logger = get_logger("universe_bucket_assign")


def _safe_lt(val, threshold, strict=True):
    """val < threshold, safe for None/NaN (returns False)."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return False
    return val < threshold if strict else val <= threshold


def _safe_gt(val, threshold, strict=True):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return False
    return val > threshold if strict else val >= threshold


def _assign_bucket(row: pd.Series, thresholds: Dict) -> Dict:
    """Apply v2.2 §4 rules. Returns dict with bucket + reasoning."""
    t = thresholds

    # Extract metrics (with None safety)
    # Per v2.2 spec §3.3: alpha_positive_rate_rolling is PRIMARY metric.
    # Fallback to legacy name for old CSVs.
    alpha_pos = row.get("alpha_positive_rate_rolling",
                        row.get("alpha_positive_rate"))
    # Spec §4.1 Alpha Core requires alpha_t_stat_504d; fall back to 252
    # if 504 not available (old CSV or risk_estimation_stable=False).
    alpha_t_504 = row.get("alpha_t_stat_504d")
    alpha_t_252 = row.get("alpha_t_stat_252d", row.get("alpha_t_stat_252"))
    alpha_t = (alpha_t_504 if alpha_t_504 is not None
               and not (isinstance(alpha_t_504, float) and np.isnan(alpha_t_504))
               else alpha_t_252)

    # Subperiod consistency — support ALL-agree (legacy) OR
    # positive_fraction ≥ threshold (R25 relaxation).
    consistency_mode = t.get("consistency_mode", "all_same_sign")
    if consistency_mode == "all_same_sign":
        alpha_sub = bool(row.get("alpha_subperiod_all_same_sign",
                                  row.get("alpha_subperiod_consistent", False)))
    else:
        # fraction-based: consistency_min = fraction of subperiods with
        # alpha same sign as majority (or just positive)
        frac = row.get("alpha_subperiod_positive_frac")
        if frac is None or (isinstance(frac, float) and np.isnan(frac)):
            alpha_sub = False
        else:
            # "majority sign fraction" — take max of positive_frac and
            # (1 - positive_frac), since symmetric stable factors count too
            majority_frac = max(float(frac), 1.0 - float(frac))
            alpha_sub = majority_frac >= float(t.get("consistency_min", 0.75))

    r2_max = row.get("r2_max")
    beta_spy = row.get("beta_spy_252d")
    beta_qqq = row.get("beta_qqq_252d")
    # Per v2.2 spec §3.4 field name is tail_correlation_to_spy.
    tail_corr = row.get("tail_correlation_to_spy",
                        row.get("tail_correlation_spy"))
    alpha_annual = row.get("alpha_annual_spy_252")

    notes = []

    # ── 4.1 Alpha Core (symbol-intrinsic portion) ─────────────────────────
    alpha_core_conditions = {
        "alpha_positive_rate":      _safe_gt(alpha_pos, t["alpha_core"]["alpha_positive_rate_min"]),
        "alpha_t_stat":             _safe_gt(alpha_t, t["alpha_core"]["alpha_t_stat_min"]),
        "alpha_subperiod_consistent": alpha_sub,
        "r2_max":                   _safe_lt(r2_max, t["alpha_core"]["r2_max"]),
    }
    # cost_adjusted_residual_return + corr_to_portfolio deferred
    alpha_core_intrinsic_pass = all(alpha_core_conditions.values())

    # ── 4.2 Diversifier (symbol-intrinsic portion) ────────────────────────
    diversifier_conditions = {
        "beta_spy":       _safe_lt(beta_spy, t["diversifier"]["beta_spy_max"]),
        "beta_qqq":       _safe_lt(beta_qqq, t["diversifier"]["beta_qqq_max"]),
        "tail_correlation": _safe_lt(tail_corr, t["diversifier"]["tail_correlation_max"]),
        # corr_to_portfolio, marginal_dd, marginal_sharpe deferred
        # alpha_non_negative: alpha >= 0 OR tail_correlation < 0.30
        "alpha_or_tail_diversifier":
            _safe_gt(alpha_annual, -1e-9, strict=False) or _safe_lt(tail_corr, 0.30),
    }
    diversifier_intrinsic_pass = all(diversifier_conditions.values())

    # ── 4.3 Tactical High-Beta Alpha ──────────────────────────────────────
    tactical_conditions = {
        "beta_spy_or_qqq_gt_1_3": (
            _safe_gt(beta_spy, t["tactical"]["beta_spy_or_qqq_min"])
            or _safe_gt(beta_qqq, t["tactical"]["beta_spy_or_qqq_min"])
        ),
        "alpha_positive_rate_gt_0_55": _safe_gt(alpha_pos, t["tactical"]["alpha_positive_rate_min"]),
        "alpha_t_stat_gt_1_0": _safe_gt(alpha_t, t["tactical"]["alpha_t_stat_min"]),
    }
    tactical_pass = all(tactical_conditions.values())

    # ── 4.4 Proxy / Redundant ─────────────────────────────────────────────
    proxy_conditions = {
        "r2_max_ge_0_75": _safe_gt(r2_max, t["proxy"]["r2_min"], strict=False),
        "alpha_positive_rate_lt_0_55": _safe_lt(alpha_pos, t["proxy"]["alpha_positive_rate_max"]),
    }
    proxy_pass = all(proxy_conditions.values())

    # ── Assignment priority ──────────────────────────────────────────────
    # Alpha Core > Diversifier > Tactical > Proxy > Unscored
    # v2.2 "PROVISIONAL_" prefix when relies on portfolio-relative
    # metrics (which this tool cannot evaluate).
    if alpha_core_intrinsic_pass:
        bucket = "PROVISIONAL_ALPHA_CORE"
        notes.append("needs: cost_adjusted_return>0, corr_to_portfolio<0.80")
    elif diversifier_intrinsic_pass:
        bucket = "PROVISIONAL_DIVERSIFIER"
        notes.append("needs: corr_to_portfolio<0.50, marginal_dd≤0, marginal_sharpe≥0")
    elif tactical_pass:
        bucket = "TACTICAL_HIGH_BETA_ALPHA"
    elif proxy_pass:
        bucket = "PROXY_REDUNDANT"
    else:
        bucket = "UNSCORED"
        # Capture leading reason for rejection
        if alpha_pos is None or (isinstance(alpha_pos, float) and np.isnan(alpha_pos)):
            notes.append("alpha_positive_rate missing")
        elif alpha_pos < 0.55:
            notes.append(f"alpha_positive_rate_low({alpha_pos:.2f})")
        elif alpha_t is None or alpha_t < 1.0:
            notes.append(f"alpha_t_stat_low")
        if r2_max is not None and r2_max >= 0.75 and alpha_pos is not None and alpha_pos >= 0.55:
            notes.append("high_r2_with_mid_alpha")

    return {
        "bucket":                 bucket,
        "alpha_core_intrinsic":   alpha_core_intrinsic_pass,
        "diversifier_intrinsic":  diversifier_intrinsic_pass,
        "tactical":               tactical_pass,
        "proxy":                  proxy_pass,
        "notes":                  "; ".join(notes) if notes else "",
    }


def _build_default_thresholds(
    consistency_mode: str = "fraction",
    consistency_min: float = 0.75,
) -> Dict:
    """Default v2.2 §4 thresholds. Mirrors v2.2 spec YAML.

    consistency_mode:
        "all_same_sign"  - strict v2.2 original (boolean all-agree)
        "fraction"       - ≥ consistency_min of subperiods same-sign
                           (default 0.75 per R25 user decision pending)
    """
    return {
        "consistency_mode": consistency_mode,
        "consistency_min":  consistency_min,
        "alpha_core": {
            "alpha_positive_rate_min": 0.60,
            "alpha_t_stat_min":        1.5,
            "r2_max":                  0.75,
            # cost_adjusted, corr_to_portfolio: deferred
        },
        "diversifier": {
            "beta_spy_max":            0.70,
            "beta_qqq_max":            0.70,
            "tail_correlation_max":    0.50,
            # corr_to_portfolio, marginal_*: deferred
        },
        "tactical": {
            "beta_spy_or_qqq_min":     1.30,
            "alpha_positive_rate_min": 0.55,
            "alpha_t_stat_min":        1.0,
        },
        "proxy": {
            "r2_min":                  0.75,
            "alpha_positive_rate_max": 0.55,
        },
    }


def _diversifier_coverage_check(
    df_assigned: pd.DataFrame, min_count: int = 5,
) -> Dict:
    """Per R23 item 2: if Diversifier candidate count too small, signal
    for threshold relaxation. Does NOT automatically relax — just reports."""
    div_count = int((df_assigned["bucket"] == "PROVISIONAL_DIVERSIFIER").sum())
    if div_count >= min_count:
        return {"action": "none", "div_count": div_count,
                "message": f"Diversifier coverage OK: {div_count} ≥ {min_count}"}
    return {
        "action": "relax_recommended",
        "div_count": div_count,
        "message": (
            f"Diversifier coverage TOO SMALL: {div_count} < {min_count}. "
            "Consider relaxing corr_to_portfolio_max → 0.60 OR "
            "tail_correlation_max → 0.60 (per v2.2 R23 note). "
            "NEVER relax marginal_dd_contribution_max (semantic core)."
        ),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels-csv", required=True,
                        help="CSV from universe_risk_labels.py")
    parser.add_argument("--out-tag", default="buckets")
    parser.add_argument("--min-diversifier-count", type=int, default=5,
                        help="Minimum Diversifier candidates to avoid relaxation signal")
    parser.add_argument("--consistency-mode", choices=["all_same_sign", "fraction"],
                        default="fraction",
                        help="Alpha Core consistency rule. 'all_same_sign' is "
                             "strict v2.2 original; 'fraction' requires "
                             "majority-sign-frac ≥ consistency-min.")
    parser.add_argument("--consistency-min", type=float, default=0.75,
                        help="For 'fraction' mode: min majority-sign fraction")
    parser.add_argument("--out-dir", default="data/ml")
    args = parser.parse_args()

    labels_path = Path(args.labels_csv)
    if not labels_path.exists():
        logger.error("Labels CSV not found: %s", labels_path)
        sys.exit(2)
    df = pd.read_csv(labels_path)
    logger.info("Loaded %d labeled symbols", len(df))

    # Filter to risk_estimation_ready symbols (Layer 2 gate)
    if "risk_estimation_ready" in df.columns:
        ready_df = df[df["risk_estimation_ready"] == True].copy()  # noqa: E712
        unready_df = df[df["risk_estimation_ready"] != True].copy()  # noqa: E712
    else:
        ready_df = df
        unready_df = pd.DataFrame()
    logger.info("risk_estimation_ready: %d / %d", len(ready_df), len(df))

    thresholds = _build_default_thresholds(
        consistency_mode=args.consistency_mode,
        consistency_min=args.consistency_min,
    )

    # Apply bucket logic
    assignments = ready_df.apply(_assign_bucket, axis=1, thresholds=thresholds)
    assigned_df = pd.DataFrame(list(assignments))
    merged = pd.concat(
        [ready_df.reset_index(drop=True), assigned_df.reset_index(drop=True)],
        axis=1,
    )

    # Unready symbols get UNSCORED_PENDING_RISK
    if not unready_df.empty:
        unready_df = unready_df.copy()
        unready_df["bucket"] = "UNSCORED_PENDING_RISK"
        unready_df["notes"] = "risk_estimation_ready=false"
        for col in ["alpha_core_intrinsic", "diversifier_intrinsic",
                    "tactical", "proxy"]:
            unready_df[col] = False
        merged = pd.concat([merged, unready_df], axis=0, ignore_index=True)

    # Coverage check
    coverage = _diversifier_coverage_check(merged, args.min_diversifier_count)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"universe_buckets_{args.out_tag}.csv"
    merged.to_csv(csv_path, index=False)

    bucket_counts = merged["bucket"].value_counts().to_dict()
    summary = {
        "source_csv":       str(labels_path),
        "n_symbols":        len(merged),
        "bucket_counts":    bucket_counts,
        "coverage_check":   coverage,
        "defaults_used":    thresholds,
        "deferred_criteria_note":
            "corr_to_portfolio, marginal_drawdown_contribution, "
            "marginal_sharpe_contribution, cost_adjusted_residual_return: "
            "require portfolio-aware second pass to finalize.",
    }
    (out_dir / f"universe_buckets_{args.out_tag}_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False)
    )

    # Print
    print()
    print("=" * 90)
    print(f"Universe Bucket Assignment (Layer 3) — {args.out_tag}")
    print(f"  Source: {labels_path.name}  | N={len(merged)}")
    print("=" * 90)
    print(f"Bucket counts: {bucket_counts}")
    print()
    for bucket in ["PROVISIONAL_ALPHA_CORE", "PROVISIONAL_DIVERSIFIER",
                   "TACTICAL_HIGH_BETA_ALPHA", "PROXY_REDUNDANT",
                   "UNSCORED", "UNSCORED_PENDING_RISK"]:
        syms = merged.loc[merged["bucket"] == bucket, "symbol"].tolist()
        if syms:
            disp = syms[:15]
            suffix = f" ...+{len(syms)-15}" if len(syms) > 15 else ""
            print(f"{bucket} ({len(syms)}): {disp}{suffix}")
    print()
    print(f"Coverage: {coverage['action']}  — {coverage['message']}")
    print()
    print("Deferred criteria (need portfolio-aware 2nd pass):")
    print("  - corr_to_portfolio")
    print("  - marginal_drawdown_contribution")
    print("  - marginal_sharpe_contribution")
    print("  - cost_adjusted_residual_return")
    print("=" * 90)
    print(f"Artifacts: {csv_path}")


if __name__ == "__main__":
    main()
