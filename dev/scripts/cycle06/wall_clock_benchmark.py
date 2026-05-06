"""PRD-AC v1.1 §6 Phase 2 step 5: per-trial wall-clock benchmark.

Loads partition_for_role(role='miner') panel ONCE, then runs
evaluate_composite NAV path N times on different archived specs to
measure per-trial wall-clock distribution.

Acceptance: median per-trial NAV-path elapsed ≤ 20s (PRD §6 Phase 2
target; R3-AC-1 measured ~15s on a single trial). Used to size the
Phase 4 200-trial smoke run timeline (200 trials × median = mining
wall-clock estimate).

Usage
-----
    python dev/scripts/cycle06/wall_clock_benchmark.py
    python dev/scripts/cycle06/wall_clock_benchmark.py --n-trials 5
    python dev/scripts/cycle06/wall_clock_benchmark.py \
        --lineage track-c-cycle-2026-05-01-04 --n-trials 10
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import List

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

import numpy as np
import pandas as pd

# Reuse shared panel-load helpers from i9_boundary_verify
from dev.scripts.cycle06.i9_boundary_verify import _load_train_panel  # type: ignore

from core.factors.factor_generator import compute_forward_returns
from core.mining.nav_objective import (
    build_universe_baseline_residual_returns,
)
from core.mining.research_miner import (
    ResearchCompositeSpec,
    evaluate_composite,
)
from core.research.harness import HarnessConfig
from core.research.risk_cluster_map import (
    ASSET_CLASS_BY_CLUSTER,
    make_unified_cluster_map,
)


def _load_top_n_trials(
    archive_db: Path, lineage: str, n: int,
) -> List[dict]:
    conn = sqlite3.connect(archive_db)
    cur = conn.execute(
        "SELECT trial_id, ic_ir, objective, features_csv, weights_csv "
        "FROM rcm_trials WHERE lineage_tag = ? AND objective IS NOT NULL "
        "ORDER BY objective DESC LIMIT ?",
        (lineage, n),
    )
    rows = cur.fetchall()
    conn.close()
    return [
        {
            "trial_id": r[0],
            "ic_ir": r[1],
            "objective": r[2],
            "features": r[3].split(","),
            "weights": [float(w) for w in r[4].split(",")],
        }
        for r in rows
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--archive-db", default=str(PROJ / "data/mining/rcm_archive.db"),
    )
    ap.add_argument(
        "--lineage", default="track-c-cycle-2026-05-01-04",
    )
    ap.add_argument(
        "--n-trials", type=int, default=5,
        help="number of archived top trials to time (default 5)",
    )
    ap.add_argument(
        "--target-seconds", type=float, default=20.0,
        help="median target per-trial NAV-path elapsed (default 20s)",
    )
    ap.add_argument("--out-json", default=None)
    args = ap.parse_args()

    print(f"Loading panel + factors (partition_for_role role='miner')...")
    t0 = time.time()
    panel, factors, mask, split_cfg = _load_train_panel()
    panel_load_seconds = time.time() - t0
    print(f"  panel n_dates={panel['close'].shape[0]} "
          f"n_syms={panel['close'].shape[1]} ({panel_load_seconds:.1f}s)")

    spy = panel["close"]["SPY"] if "SPY" in panel["close"].columns else None
    qqq = panel["close"]["QQQ"] if "QQQ" in panel["close"].columns else None
    price_df = panel["close"].drop(columns=["SPY", "QQQ"], errors="ignore")
    open_df = panel["open"].drop(columns=["SPY", "QQQ"], errors="ignore")
    if spy is None:
        raise SystemExit("SPY not found in panel")

    anchor = build_universe_baseline_residual_returns(price_df, spy)
    fwd = compute_forward_returns(panel["close"], horizons=[21], mode="cc")[21]

    cluster_map = make_unified_cluster_map(include_cross_asset=True)
    asset_class_map = {
        sym: ASSET_CLASS_BY_CLUSTER[cluster_map[sym]]
        for sym in price_df.columns if sym in cluster_map
    }
    hc = HarnessConfig(
        rebalance_cadence="monthly",
        construction_mode="cap_aware_cross_asset",
        top_n=10, cluster_cap=0.20, max_single_weight=0.10,
        cluster_map=cluster_map,
        asset_class_map=asset_class_map,
        asset_class_caps={
            "equities": 0.70, "bonds": 0.40,
            "commodities": 0.20, "cash_anchor": 0.30,
        },
    )

    trials = _load_top_n_trials(Path(args.archive_db), args.lineage, args.n_trials)
    print(f"\nTiming {len(trials)} archived trials from {args.lineage}:")
    elapsed_per_trial = []
    for i, t in enumerate(trials, 1):
        # Renormalize weights (archive stores 6-decimal CSV; sum can be 0.999999)
        total = sum(t["weights"])
        weights_norm = tuple(w / total for w in t["weights"])
        spec = ResearchCompositeSpec(
            features=tuple(t["features"]),
            weights=weights_norm,
            family_counts={"X": len(t["features"])},
        )
        # Filter panels to features actually in factors dict
        panel_map = {f: factors[f] for f in t["features"] if f in factors}
        if len(panel_map) != len(t["features"]):
            print(f"  trial {i}/{len(trials)} {t['trial_id']}: "
                  f"SKIP (missing factor panels)")
            continue
        t_start = time.time()
        metrics = evaluate_composite(
            spec, panel_map, fwd, mask=mask,
            price_df=price_df, open_df=open_df,
            spy_series=spy, qqq_series=qqq,
            anchor_residual_returns=anchor,
            harness_config=hc, compute_nav=True,
        )
        elapsed = time.time() - t_start
        elapsed_per_trial.append(elapsed)
        print(f"  trial {i}/{len(trials)} {t['trial_id']}: {elapsed:.1f}s "
              f"sharpe={metrics.nav_sharpe:.3f} max_dd={metrics.nav_max_dd:.2%}")

    if not elapsed_per_trial:
        print("No timing samples collected (all trials skipped)")
        return 1

    e = np.array(elapsed_per_trial)
    print(f"\nWall-clock distribution (n={len(e)} samples):")
    print(f"  min        : {e.min():.2f}s")
    print(f"  median     : {float(np.median(e)):.2f}s")
    print(f"  mean       : {e.mean():.2f}s")
    print(f"  p95        : {float(np.percentile(e, 95)):.2f}s")
    print(f"  max        : {e.max():.2f}s")

    median = float(np.median(e))
    verdict = "PASS" if median <= args.target_seconds else "FAIL"
    print(f"\nVerdict: {verdict} (median {median:.2f}s "
          f"vs target ≤ {args.target_seconds:.2f}s)")
    print(f"Phase 4 200-trial smoke estimate: "
          f"{200 * median / 60:.1f} min mining wall-clock")

    out = {
        "lineage": args.lineage,
        "panel_load_seconds": panel_load_seconds,
        "n_samples": len(e),
        "elapsed_per_trial_seconds": elapsed_per_trial,
        "stats": {
            "min": float(e.min()),
            "median": median,
            "mean": float(e.mean()),
            "p95": float(np.percentile(e, 95)),
            "max": float(e.max()),
        },
        "target_seconds": args.target_seconds,
        "verdict": verdict,
        "estimated_200_trial_smoke_minutes": 200 * median / 60,
    }
    out_path = Path(
        args.out_json or
        f"data/audit/wall_clock_benchmark_{args.lineage}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nWrote {out_path}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
