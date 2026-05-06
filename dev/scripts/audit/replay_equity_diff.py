#!/usr/bin/env python
"""M11 paper-BT consistency replay tool (M11 pack v3 ad-hoc CLI).

Standalone diagnostic that re-runs a frozen candidate spec under
BacktestEngine and compares the resulting equity curve against a
stored NAV parquet. Reports per-bar drift in bps + summary stats
(max abs drift, last-bar drift, overall return drift).

This is NOT yet wired into ``core/mining/acceptance_pack.py``. M11
"pack v3 gate" remains DEFERRED per
``docs/memos/20260505-m11_paper_bt_consistency_v3_deferred.md``.
This CLI exists so that operators (or audit reviewers) can manually
run the consistency check on any candidate without acceptance pack
re-architecture.

Usage::

    python dev/scripts/audit/replay_equity_diff.py \\
        --candidate-spec-yaml data/research_candidates/trial9_diversifier_001.yaml \\
        --stored-nav-parquet data/sr_validation/trial9_arm_A_baseline_nav.parquet \\
        --start 2018-01-01 --end 2025-12-31 \\
        --top-n 10 --initial-capital 10000

Exit codes::

    0  drift within threshold (default 10 bps max abs)
    1  drift exceeds threshold
    2  input error / missing file / replay failure
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from core.backtest.backtest_engine import BacktestEngine
from core.config.loader import load_config
from core.data.factory import create_default_store
from core.execution.cost_model import CostModel
from core.research.frozen_spec import FrozenStrategySpec
from core.research.robustness.runner import (
    _composite_to_target_weights,
    _compute_composite,
    _load_panel,
)


def _replay_equity(
    spec: FrozenStrategySpec,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    top_n: int,
    initial_capital: float,
) -> pd.Series:
    """Re-run backtest engine on the spec and return the equity curve."""
    cfg = load_config()
    store = create_default_store(cfg)
    panel = _load_panel(cfg, store, start=start, end=end)
    composite, _ = _compute_composite(spec, panel)
    target_wts = _composite_to_target_weights(composite, top_n=top_n)
    cm = CostModel(cfg.cost_model)
    engine = BacktestEngine(cost_model=cm, initial_capital=initial_capital)
    result = engine.run(
        signals_df=target_wts,
        price_df=panel["close"],
        open_df=panel["open"],
    )
    eq = result.equity_curve
    return eq


def _compute_drift_stats(
    replay_eq: pd.Series, stored_eq: pd.Series,
) -> dict:
    """Per-bar drift in bps + summary stats."""
    aligned = pd.concat({"replay": replay_eq, "stored": stored_eq}, axis=1)
    aligned = aligned.dropna()
    if aligned.empty:
        return {"error": "no overlapping bars between replay and stored NAV"}
    # bps drift = (replay - stored) / stored * 10_000
    drift_bps = (aligned["replay"] - aligned["stored"]) / aligned["stored"] * 10_000.0
    abs_drift = drift_bps.abs()
    last_bar_drift = float(drift_bps.iloc[-1])
    return {
        "n_bars_overlap": int(len(aligned)),
        "first_overlap_date": str(aligned.index[0].date()),
        "last_overlap_date": str(aligned.index[-1].date()),
        "max_abs_drift_bps": float(abs_drift.max()),
        "max_abs_drift_at": str(abs_drift.idxmax().date()),
        "mean_abs_drift_bps": float(abs_drift.mean()),
        "last_bar_drift_bps": last_bar_drift,
        "replay_total_return_pct": float(
            replay_eq.iloc[-1] / replay_eq.iloc[0] - 1.0
        ),
        "stored_total_return_pct": float(
            stored_eq.iloc[-1] / stored_eq.iloc[0] - 1.0
        ),
        "total_return_drift_pp": float(
            (replay_eq.iloc[-1] / replay_eq.iloc[0])
            - (stored_eq.iloc[-1] / stored_eq.iloc[0])
        ) * 100.0,
    }


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--candidate-spec-yaml", required=True,
                    help="Path to FrozenStrategySpec yaml")
    ap.add_argument("--stored-nav-parquet", required=True,
                    help="Path to stored NAV parquet (single 'equity' column or single-column)")
    ap.add_argument("--start", required=True,
                    help="Replay start date (YYYY-MM-DD)")
    ap.add_argument("--end", required=True,
                    help="Replay end date (YYYY-MM-DD)")
    ap.add_argument("--top-n", type=int, default=10)
    ap.add_argument("--initial-capital", type=float, default=10000.0)
    ap.add_argument("--max-drift-bps", type=float, default=10.0,
                    help="Threshold (bps) for max abs drift before failing")
    ap.add_argument("--output-json", default=None,
                    help="Optional path to write the drift report as JSON")
    args = ap.parse_args(argv)

    spec_path = Path(args.candidate_spec_yaml)
    if not spec_path.exists():
        print(f"[err] spec yaml not found: {spec_path}", file=sys.stderr)
        return 2
    nav_path = Path(args.stored_nav_parquet)
    if not nav_path.exists():
        print(f"[err] stored NAV parquet not found: {nav_path}", file=sys.stderr)
        return 2

    spec = FrozenStrategySpec.from_yaml_file(spec_path)

    stored_df = pd.read_parquet(nav_path)
    if stored_df.shape[1] == 1:
        stored_eq = stored_df.iloc[:, 0]
    elif "equity" in stored_df.columns:
        stored_eq = stored_df["equity"]
    else:
        print(f"[err] stored NAV has multiple cols and no 'equity' col: "
              f"{list(stored_df.columns)}", file=sys.stderr)
        return 2

    print(f"[replay] spec={spec.candidate_id} range=[{args.start}, {args.end}] "
          f"top_n={args.top_n}")
    try:
        replay_eq = _replay_equity(
            spec,
            start=pd.Timestamp(args.start),
            end=pd.Timestamp(args.end),
            top_n=args.top_n,
            initial_capital=args.initial_capital,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[err] replay failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    if replay_eq.empty:
        print("[err] replay produced empty equity curve", file=sys.stderr)
        return 2

    stats = _compute_drift_stats(replay_eq, stored_eq)
    if "error" in stats:
        print(f"[err] {stats['error']}", file=sys.stderr)
        return 2

    print(f"\n=== drift report ===")
    print(f"  n_bars overlap:      {stats['n_bars_overlap']}")
    print(f"  date range:          {stats['first_overlap_date']} → {stats['last_overlap_date']}")
    print(f"  max abs drift:       {stats['max_abs_drift_bps']:.4f} bps "
          f"(at {stats['max_abs_drift_at']})")
    print(f"  mean abs drift:      {stats['mean_abs_drift_bps']:.4f} bps")
    print(f"  last-bar drift:      {stats['last_bar_drift_bps']:.4f} bps")
    print(f"  replay total return: {100*stats['replay_total_return_pct']:.2f}%")
    print(f"  stored total return: {100*stats['stored_total_return_pct']:.2f}%")
    print(f"  total-return drift:  {stats['total_return_drift_pp']:.4f} pp")

    threshold = args.max_drift_bps
    passed = stats["max_abs_drift_bps"] <= threshold
    verdict = "PASS" if passed else "FAIL"
    print(f"\n  threshold={threshold:.2f} bps → {verdict}")

    if args.output_json:
        out = {
            "spec_id": spec.candidate_id,
            "stored_nav_path": str(nav_path),
            "replay_range": [args.start, args.end],
            "top_n": args.top_n,
            "initial_capital": args.initial_capital,
            "threshold_bps": threshold,
            "verdict": verdict,
            "passed": passed,
            **stats,
            "computed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        Path(args.output_json).write_text(json.dumps(out, indent=2, default=str))
        print(f"\n  wrote: {args.output_json}")

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
