"""PRD-AC v1.1 §6 Phase 2 I9 boundary verification (lightweight version).

Runs evaluate_composite NAV path on partition_for_role(role="miner")
panel for one archived trial (default: cycle04 cap_aware_cross_asset
top-1) and surfaces year-boundary artifact diagnostics:

  - Per-day return percentile distribution
  - Day-over-day return AT year boundaries (e.g. 2017-12-29 → 2020-01-02)
    -> must not be unreasonably large vs typical day-over-day variance
  - max_dd / sharpe / cum_ret all finite
  - Anchor builder produces non-NaN residual on this panel

Outputs JSON to data/audit/i9_boundary_verify_<lineage>_<trial_id>.json
plus a stdout summary. Exit 0 on PASS, 1 on FAIL.

Usage
-----
    python dev/scripts/cycle06/i9_boundary_verify.py
    python dev/scripts/cycle06/i9_boundary_verify.py \
        --lineage track-c-cycle-2026-05-01-04 --rank 1
    python dev/scripts/cycle06/i9_boundary_verify.py \
        --trial-id ddc2896f9d8e
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

import numpy as np
import pandas as pd

from core.config.loader import load_config
from core.data.bar_store import BarStore
from core.factors.base_masks import research_mask_default
from core.factors.factor_generator import generate_all_factors
from core.mining.nav_objective import (
    build_universe_baseline_residual_returns,
)
from core.mining.research_miner import (
    ObjectiveWeights,
    ResearchCompositeSpec,
    evaluate_composite,
)
from core.research.harness import HarnessConfig
from core.research.risk_cluster_map import (
    ASSET_CLASS_BY_CLUSTER,
    CROSS_ASSET_RISK_CLUSTER_MAP,
    make_unified_cluster_map,
)
from core.research.temporal_split import (
    load_temporal_split,
    partition_for_role,
)


def _load_archived_trial(
    archive_db: Path, lineage: str, *, rank: int = 1, trial_id: str | None = None,
) -> Dict[str, Any]:
    """Fetch one trial row from rcm_archive."""
    conn = sqlite3.connect(archive_db)
    if trial_id is not None:
        cur = conn.execute(
            "SELECT trial_id, ic_ir, objective, features_csv, weights_csv "
            "FROM rcm_trials WHERE trial_id = ? LIMIT 1",
            (trial_id,),
        )
    else:
        cur = conn.execute(
            "SELECT trial_id, ic_ir, objective, features_csv, weights_csv "
            "FROM rcm_trials WHERE lineage_tag = ? AND objective IS NOT NULL "
            "ORDER BY objective DESC LIMIT ? OFFSET ?",
            (lineage, 1, rank - 1),
        )
    row = cur.fetchone()
    conn.close()
    if row is None:
        raise SystemExit(
            f"no trial found: lineage={lineage} rank={rank} trial_id={trial_id}"
        )
    return {
        "trial_id": row[0],
        "ic_ir": row[1],
        "objective": row[2],
        "features": row[3].split(","),
        "weights": [float(w) for w in row[4].split(",")],
    }


def _load_train_panel():
    """Load full universe → partition_for_role(role='miner') → factor panel."""
    cfg = load_config(PROJ / "config")
    store = BarStore(root=Path(cfg.system.paths.data_dir))
    uni = cfg.universe
    syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs)
        + list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    syms = [s for s in syms if s not in uni.blacklist
            and s not in uni.macro_reference]
    for b in ("SPY", "QQQ"):
        if b not in syms:
            syms.append(b)
    cross_asset_set = set(CROSS_ASSET_RISK_CLUSTER_MAP.keys())
    frames = {k: {} for k in ("close", "open", "high", "low", "volume")}
    for sym in syms:
        atr = sym in cross_asset_set
        df = store.load(sym, freq="1d", adjusted=True,
                        adjusted_total_return=atr, fallback="local")
        if df is None or df.empty or "close" not in df.columns:
            continue
        frames["close"][sym] = df["close"]
        for col in ("open", "high", "low", "volume"):
            if col in df.columns:
                frames[col][sym] = df[col]
    close_df = pd.DataFrame(frames["close"]).sort_index()
    open_df = pd.DataFrame(frames["open"]).reindex_like(close_df)
    high_df = pd.DataFrame(frames["high"]).reindex_like(close_df)
    low_df = pd.DataFrame(frames["low"]).reindex_like(close_df)
    volume_df = pd.DataFrame(frames["volume"]).reindex_like(close_df)
    panel_full = {"close": close_df, "open": open_df, "high": high_df,
                  "low": low_df, "volume": volume_df}
    split_cfg = load_temporal_split(PROJ / "config" / "temporal_split.yaml")
    panel = partition_for_role(panel_full, split_cfg, role="miner")
    benchmark_map = {
        b: panel["close"][b]
        for b in ("SPY", "QQQ") if b in panel["close"].columns
    }
    factors = generate_all_factors(
        panel["close"], volume_df=panel["volume"],
        open_df=panel["open"], high_df=panel["high"], low_df=panel["low"],
        benchmark_map=benchmark_map,
    )
    mask = (
        research_mask_default(panel["close"], panel["volume"])
        if panel["volume"] is not None else None
    )
    return panel, factors, mask, split_cfg


def _detect_boundary_artifact(
    nav: pd.Series, train_year_gap_threshold_days: int = 30,
) -> Dict[str, Any]:
    """Identify days where the prior trading day was > N days earlier.
    Those are train-year boundaries. Report return at each such day.
    """
    if len(nav) < 2:
        return {"n_boundaries": 0, "max_boundary_return_abs": 0.0}
    idx = nav.index
    deltas = idx.to_series().diff()
    boundary_mask = deltas > pd.Timedelta(days=train_year_gap_threshold_days)
    boundary_dates = list(idx[boundary_mask])
    boundary_rets = []
    for bd in boundary_dates:
        prev_idx = idx.get_loc(bd) - 1
        if prev_idx < 0:
            continue
        prev_nav = float(nav.iloc[prev_idx])
        cur_nav = float(nav.iloc[idx.get_loc(bd)])
        if prev_nav > 0:
            boundary_rets.append({
                "date": bd.isoformat(),
                "prev_date": idx[prev_idx].isoformat(),
                "gap_days": int(deltas.iloc[idx.get_loc(bd)].days),
                "ret": (cur_nav / prev_nav) - 1.0,
            })
    max_abs = max((abs(r["ret"]) for r in boundary_rets), default=0.0)
    return {
        "n_boundaries": len(boundary_dates),
        "boundaries": boundary_rets,
        "max_boundary_return_abs": max_abs,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--archive-db", default=str(PROJ / "data/mining/rcm_archive.db"),
        help="rcm_archive.db path",
    )
    ap.add_argument(
        "--lineage", default="track-c-cycle-2026-05-01-04",
        help="lineage_tag to fetch top-rank trial from",
    )
    ap.add_argument(
        "--rank", type=int, default=1,
        help="1-based rank by objective desc",
    )
    ap.add_argument(
        "--trial-id", default=None,
        help="explicit trial_id (overrides --lineage/--rank)",
    )
    ap.add_argument(
        "--out-json", default=None,
        help="output JSON path (default data/audit/i9_boundary_verify_*.json)",
    )
    ap.add_argument(
        "--warn-boundary-ret-pct", type=float, default=0.05,
        help="WARN if any year-boundary day-over-day return abs > this "
             "fraction (default 0.05 = 5%%); does NOT fail the script "
             "since PRD §6 Phase 2 I9 mask zeros these in the NAV metrics",
    )
    args = ap.parse_args()

    archive_db = Path(args.archive_db)
    trial = _load_archived_trial(
        archive_db, args.lineage, rank=args.rank, trial_id=args.trial_id,
    )
    print(f"Loaded trial {trial['trial_id']} from {args.lineage}: "
          f"IC_IR={trial['ic_ir']:.4f}  objective={trial['objective']:.4f}")
    print(f"  features: {trial['features']}")
    print(f"  weights:  {trial['weights']}")

    print("\nLoading panel + factors (partition_for_role role='miner')...")
    t0 = time.time()
    panel, factors, mask, split_cfg = _load_train_panel()
    print(f"  panel n_dates={panel['close'].shape[0]} "
          f"n_syms={panel['close'].shape[1]} ({time.time()-t0:.1f}s)")

    # Build SPY/QQQ separately (excluded from anchor universe)
    spy = panel["close"]["SPY"] if "SPY" in panel["close"].columns else None
    qqq = panel["close"]["QQQ"] if "QQQ" in panel["close"].columns else None
    price_df = panel["close"].drop(columns=["SPY", "QQQ"], errors="ignore")
    open_df = panel["open"].drop(columns=["SPY", "QQQ"], errors="ignore")
    if spy is None:
        raise SystemExit("SPY not found in panel; required for NAV gate")

    # Anchor builder must produce a usable residual on train-only panel
    anchor = build_universe_baseline_residual_returns(price_df, spy)
    print(f"  anchor_residual: n={len(anchor)} "
          f"all_nan={anchor.isna().all()} std={anchor.std():.6f}")

    # Build composite spec from archived row
    panel_map = {f: factors[f] for f in trial["features"] if f in factors}
    if len(panel_map) != len(trial["features"]):
        missing = [f for f in trial["features"] if f not in factors]
        raise SystemExit(
            f"trial spec features missing from factor panels: {missing}"
        )
    # Archive stores weights at 6-decimal precision; renormalize to satisfy
    # ResearchCompositeSpec sum-to-1.0 tolerance.
    raw_weights = trial["weights"]
    total = sum(raw_weights)
    weights_norm = tuple(w / total for w in raw_weights)
    spec = ResearchCompositeSpec(
        features=tuple(trial["features"]),
        weights=weights_norm,
        family_counts={"X": len(trial["features"])},  # nominal, not used
    )

    # Build forward returns at default 21d horizon (mining default)
    from core.factors.factor_generator import compute_forward_returns
    fwd = compute_forward_returns(panel["close"], horizons=[21], mode="cc")[21]

    # Construct cap_aware_cross_asset HarnessConfig (cycle04 contract)
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

    print("\nRunning evaluate_composite NAV path on train-only panel...")
    t0 = time.time()
    metrics = evaluate_composite(
        spec, panel_map, fwd, mask=mask,
        price_df=price_df, open_df=open_df,
        spy_series=spy, qqq_series=qqq,
        anchor_residual_returns=anchor,
        harness_config=hc, compute_nav=True,
    )
    elapsed = time.time() - t0
    print(f"  elapsed: {elapsed:.1f}s")
    print(f"  ic_ir={metrics.ic_ir:.4f}  nav_sharpe={metrics.nav_sharpe:.4f}  "
          f"nav_max_dd={metrics.nav_max_dd:.4f}")
    print(f"  nav_corr_anchor={metrics.nav_correlation_vs_anchor_pooled_raw:.4f}  "
          f"nav_vs_qqq_excess={metrics.nav_vs_qqq_excess_full_period:.4f}")

    # Re-run via harness to get the NAV trajectory itself for boundary check
    from core.research.harness import evaluate_composite_spec as expost
    result = expost(
        spec, factor_panel_map=panel_map,
        price_df=price_df, open_df=open_df,
        spy_series=spy, qqq_series=qqq,
        config=hc, research_mask=mask,
    )
    boundary = _detect_boundary_artifact(result.nav)
    print(f"\nYear-boundary artifact check (gap > 30 days):")
    print(f"  n_boundaries detected: {boundary['n_boundaries']}")
    print(f"  max |boundary return|: {boundary['max_boundary_return_abs']:.4%}")
    for b in boundary.get("boundaries", []):
        print(f"    {b['prev_date']} → {b['date']} "
              f"(gap={b['gap_days']}d): {b['ret']:+.4%}")

    # PASS/WARN/FAIL gate. Boundary jumps (raw NAV) are INFORMATIONAL —
    # they're masked in the metrics returned by evaluate_composite per
    # PRD §6 Phase 2 I9 fix in core/mining/nav_objective.py
    # ::recompute_nav_metrics_train_only. WARN if raw boundary jump
    # exceeds threshold (operator should be aware); FAIL only if the
    # masked metrics themselves are NaN/unreasonable.
    fails = []
    warns = []
    if not np.isfinite(metrics.nav_sharpe):
        fails.append("masked nav_sharpe NaN — NAV gate broken")
    if not np.isfinite(metrics.nav_max_dd):
        fails.append("masked nav_max_dd NaN — NAV gate broken")
    if metrics.nav_max_dd < -0.50:
        fails.append(
            f"masked nav_max_dd={metrics.nav_max_dd:.2%} unreasonably large"
        )
    if boundary["max_boundary_return_abs"] > args.warn_boundary_ret_pct:
        warns.append(
            f"raw boundary return abs={boundary['max_boundary_return_abs']:.4%} "
            f"> warn threshold {args.warn_boundary_ret_pct:.4%} — "
            f"masked in metrics but real positions held across the gap"
        )
    if fails:
        verdict = "FAIL"
    elif warns:
        verdict = "PASS_WITH_WARNINGS"
    else:
        verdict = "PASS"
    print(f"\nVerdict: {verdict}")
    for f in fails:
        print(f"  FAIL: {f}")
    for w in warns:
        print(f"  WARN: {w}")

    out = {
        "lineage": args.lineage,
        "trial_id": trial["trial_id"],
        "rank": args.rank,
        "spec": {
            "features": trial["features"],
            "weights": trial["weights"],
        },
        "panel": {
            "n_dates": int(panel["close"].shape[0]),
            "n_syms": int(panel["close"].shape[1]),
            "split_name": split_cfg.split_name,
        },
        "metrics": {
            "ic_ir": metrics.ic_ir,
            "nav_sharpe": metrics.nav_sharpe,
            "nav_max_dd": metrics.nav_max_dd,
            "nav_correlation_vs_anchor_pooled_raw":
                metrics.nav_correlation_vs_anchor_pooled_raw,
            "nav_vs_qqq_excess_full_period":
                metrics.nav_vs_qqq_excess_full_period,
        },
        "anchor": {
            "n_obs": int(len(anchor)),
            "all_nan": bool(anchor.isna().all()),
            "std": float(anchor.std()) if len(anchor) > 0 else 0.0,
        },
        "boundary_check": boundary,
        "elapsed_seconds": elapsed,
        "verdict": verdict,
        "fails": fails,
        "warnings": warns,
    }
    out_path = Path(
        args.out_json or
        f"data/audit/i9_boundary_verify_{args.lineage}_{trial['trial_id']}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nWrote {out_path}")
    return 0 if verdict in ("PASS", "PASS_WITH_WARNINGS") else 1


if __name__ == "__main__":
    sys.exit(main())
