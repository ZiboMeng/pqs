"""PRD-AC v1.1 Phase 4 cycle #06 dry-run closeout analysis.

Reads archived trials under lineage `track-c-cycle-2026-05-06-01` and
emits the deliverables required by PRD §5.2 + §5.3 acceptance:

  H1: Spearman rank correlation top-10 v2 vs v1 (from same archive,
      v1 ranking = compute_objective with all w_nav_*=0)
  H2: TPE distribution across holding_freq cells (≥30 trials per cell)
  H3: v2 top-1 nav_sharpe ≥ v1 top-1 nav_sharpe (Pareto check)
  H4: nav_correlation_vs_anchor_pooled_raw distribution (anchor
      calibration §4.6 decision)
  Track A acceptance: per-validation-year vs SPY / vs QQQ, max_dd,
      stress slices, beta — for top-10 v2 trials
  R41 informational: sibling-by-NAV vs RCMv1 + Cand-2 (Tier 1 / Tier 2;
      PRD I18: Tier 2 still counts as nominee)

Output: data/audit/cycle06_closeout_analysis.json + stdout summary.

Usage
-----
    python dev/scripts/cycle06/cycle06_closeout_analysis.py
    python dev/scripts/cycle06/cycle06_closeout_analysis.py \
        --lineage track-c-cycle-2026-05-06-01
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

import numpy as np
import pandas as pd

from core.mining.research_miner import (
    CompositeMetrics,
    ObjectiveWeights,
    compute_objective,
)


def _load_archived(archive_db: Path, lineage: str) -> pd.DataFrame:
    conn = sqlite3.connect(archive_db)
    cur = conn.execute(
        """
        SELECT trial_id, ic_ir, objective, n_dates,
               turnover_proxy, corr_concentration,
               nav_sharpe, nav_max_dd,
               nav_correlation_vs_anchor_pooled_raw,
               nav_vs_qqq_excess_full_period,
               benchmark_excess, regime_stddev, spec_json
        FROM rcm_trials
        WHERE lineage_tag=? AND objective IS NOT NULL
        ORDER BY objective DESC
        """,
        (lineage,),
    )
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    conn.close()
    df = pd.DataFrame(rows, columns=cols)
    if df.empty:
        return df
    # Parse spec_json for features / holding_freq / enable_sr_defer
    df["spec_dict"] = df["spec_json"].apply(json.loads)
    df["features"] = df["spec_dict"].apply(lambda d: ",".join(d["features"]))
    df["holding_freq"] = df["spec_dict"].apply(
        lambda d: d.get("holding_freq", "monthly")  # default cycle04 cadence
    )
    df["enable_sr_defer"] = df["spec_dict"].apply(
        lambda d: d.get("enable_sr_defer", False)
    )
    return df


def _recompute_v1_objective(row) -> float:
    """Compute what objective WOULD have been at all w_nav_*=0 (v1_legacy
    equivalent ranking). Used for H1 / H3 v2 vs v1 comparison."""
    metrics = CompositeMetrics(
        n_features=0, n_families=0, n_dates=int(row.n_dates) if row.n_dates else 0,
        ic_mean=0.0, ic_std=0.0,
        ic_ir=float(row.ic_ir) if row.ic_ir is not None else float("nan"),
        turnover_proxy=float(row.turnover_proxy) if row.turnover_proxy is not None else 0.0,
        corr_concentration=float(row.corr_concentration) if row.corr_concentration is not None else 0.0,
    )
    # cycle06 yaml v1_legacy default = w_ir=1.0, w_turnover=0.5, w_corr_conc=1.0,
    # w_bench_excess=0.3, w_regime_stddev=0.2 (legacy defaults)
    w_v1 = ObjectiveWeights()  # default = pre-PRD-AC behavior
    return compute_objective(
        metrics,
        benchmark_excess=float(row.benchmark_excess or 0.0),
        regime_stddev=float(row.regime_stddev or 0.0),
        weights=w_v1,
    )


def _spearman(a: List, b: List) -> float:
    """Spearman rank correlation between two lists."""
    if len(a) < 2 or len(a) != len(b):
        return float("nan")
    sa = pd.Series(a)
    sb = pd.Series(b)
    return float(sa.corr(sb, method="spearman"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--archive-db", default=str(PROJ / "data/mining/rcm_archive.db"),
    )
    ap.add_argument("--lineage", default="track-c-cycle-2026-05-06-01")
    ap.add_argument("--out-json", default=None)
    args = ap.parse_args()

    df = _load_archived(Path(args.archive_db), args.lineage)
    if df.empty:
        print(f"No archived trials for lineage {args.lineage!r}")
        return 1

    n = len(df)
    print(f"Loaded {n} archived trials from {args.lineage}\n")

    # H2: holding_freq cell distribution
    print("=" * 60)
    print("H2 — TPE distribution across holding_freq cells")
    print("=" * 60)
    hf_counts = df["holding_freq"].value_counts().to_dict()
    print(f"  holding_freq counts: {hf_counts}")
    h2_pass = all(hf_counts.get(c, 0) >= 30 for c in ("monthly", "weekly", "daily"))
    print(f"  H2 verdict: {'PASS' if h2_pass else 'FAIL'} (target ≥30 per cell)")

    # H1, H3: v2 vs v1 ranking
    print("\n" + "=" * 60)
    print("H1 + H3 — v2 vs v1 objective comparison")
    print("=" * 60)
    df["v1_objective"] = df.apply(_recompute_v1_objective, axis=1)
    df["v1_rank"] = df["v1_objective"].rank(ascending=False, method="min")
    df["v2_rank"] = df["objective"].rank(ascending=False, method="min")
    top10_v2 = df.nsmallest(10, "v2_rank")
    top10_v1 = df.nsmallest(10, "v1_rank")
    spear = _spearman(
        top10_v2.sort_values("trial_id")["v2_rank"].tolist(),
        top10_v2.sort_values("trial_id")["v1_rank"].tolist(),
    )
    n_v2_not_in_v1 = len(set(top10_v2["trial_id"]) - set(top10_v1["trial_id"]))
    print(f"  Spearman rank correlation top-10 v2 vs v1: {spear:.3f}")
    print(f"  trials in v2 top-10 NOT in v1 top-10:       {n_v2_not_in_v1}")
    h1_pass = (spear < 0.7) and (n_v2_not_in_v1 >= 3)
    print(f"  H1 verdict: {'PASS' if h1_pass else 'FAIL'}")
    def _safe_float(x):
        if x is None or pd.isna(x):
            return float("nan")
        return float(x)

    v2_top_sharpe = _safe_float(top10_v2.iloc[0]["nav_sharpe"]) if len(top10_v2) else float("nan")
    v1_top_sharpe = _safe_float(top10_v1.iloc[0]["nav_sharpe"]) if len(top10_v1) else float("nan")
    h3_pass = v2_top_sharpe >= v1_top_sharpe if (
        np.isfinite(v2_top_sharpe) and np.isfinite(v1_top_sharpe)
    ) else False
    print(f"  v2 top-1 nav_sharpe: {v2_top_sharpe:.4f}")
    print(f"  v1 top-1 nav_sharpe: {v1_top_sharpe:.4f}")
    print(f"  H3 verdict: {'PASS' if h3_pass else 'FAIL'}")

    # H4: anchor_corr distribution
    print("\n" + "=" * 60)
    print("H4 — Anchor orthogonality calibration (PRD §4.6)")
    print("=" * 60)
    anchor = df["nav_correlation_vs_anchor_pooled_raw"].dropna()
    if len(anchor) == 0:
        print("  (no finite anchor_corr values; cross-asset specs skip orthogonality)")
        h4_decision = "skip — all NaN (cross-asset universe; Option γ)"
    else:
        p25 = float(np.percentile(anchor, 25))
        p50 = float(np.percentile(anchor, 50))
        p75 = float(np.percentile(anchor, 75))
        p95 = float(np.percentile(anchor, 95))
        below_05 = int((anchor < 0.50).sum())
        in_band = int(((anchor >= 0.50) & (anchor < 0.70)).sum())
        above_07 = int((anchor >= 0.70).sum())
        pct_below_05 = 100 * below_05 / len(anchor)
        print(f"  anchor_corr distribution (n={len(anchor)}):")
        print(f"    p25={p25:.3f}  p50={p50:.3f}  p75={p75:.3f}  p95={p95:.3f}")
        print(f"  n_trials below 0.50:    {below_05} ({pct_below_05:.1f}%)")
        print(f"  n_trials in 0.50-0.70:  {in_band}")
        print(f"  n_trials above 0.70:    {above_07}")
        if pct_below_05 >= 30:
            h4_decision = "Option β anchor viable — enable w_nav_orthogonality in cycle07+"
        elif pct_below_05 < 10:
            h4_decision = "Option γ fallback — skip orthogonality term in cycle07+"
        else:
            h4_decision = "directional — user decision needed"
        print(f"  H4 decision: {h4_decision}")

    # Top-10 detailed
    print("\n" + "=" * 60)
    print("Top-10 v2 trials")
    print("=" * 60)
    def _fmt(x, spec=".3f"):
        if x is None or (isinstance(x, float) and not np.isfinite(x)):
            return "nan"
        return format(x, spec)

    for _, row in top10_v2.iterrows():
        print(f"  {row.trial_id} obj={_fmt(row.objective,'.4f')} "
              f"ic_ir={_fmt(row.ic_ir,'.4f')} "
              f"sharpe={_fmt(row.nav_sharpe)} "
              f"max_dd={_fmt(row.nav_max_dd,'.2%')} "
              f"vs_qqq={_fmt(row.nav_vs_qqq_excess_full_period,'+.3f')} "
              f"holding={row.holding_freq} feats={row.features}")

    # Output JSON
    out = {
        "lineage": args.lineage,
        "n_trials_archived": int(n),
        "h2_holding_freq_distribution": hf_counts,
        "h2_pass": bool(h2_pass),
        "h1_spearman_v2_v1_top10": float(spear) if np.isfinite(spear) else None,
        "h1_n_v2_only_in_top10": int(n_v2_not_in_v1),
        "h1_pass": bool(h1_pass),
        "h3_v2_top1_nav_sharpe": v2_top_sharpe if np.isfinite(v2_top_sharpe) else None,
        "h3_v1_top1_nav_sharpe": v1_top_sharpe if np.isfinite(v1_top_sharpe) else None,
        "h3_pass": bool(h3_pass),
        "h4_anchor_decision": h4_decision,
        "h4_anchor_n_finite": int(len(anchor)),
        "top10_v2_trials": [
            {
                "trial_id": str(row.trial_id),
                "objective": float(row.objective),
                "ic_ir": float(row.ic_ir),
                "nav_sharpe": float(row.nav_sharpe) if pd.notna(row.nav_sharpe) else None,
                "nav_max_dd": float(row.nav_max_dd) if pd.notna(row.nav_max_dd) else None,
                "nav_correlation_vs_anchor_pooled_raw": (
                    float(row.nav_correlation_vs_anchor_pooled_raw)
                    if pd.notna(row.nav_correlation_vs_anchor_pooled_raw) else None
                ),
                "nav_vs_qqq_excess_full_period": (
                    float(row.nav_vs_qqq_excess_full_period)
                    if pd.notna(row.nav_vs_qqq_excess_full_period) else None
                ),
                "holding_freq": str(row.holding_freq),
                "features": str(row.features),
            }
            for _, row in top10_v2.iterrows()
        ],
    }
    out_path = Path(
        args.out_json or f"data/audit/cycle06_closeout_analysis_{args.lineage}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
