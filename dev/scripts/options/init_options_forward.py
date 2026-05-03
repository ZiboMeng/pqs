"""Bootstrap an options forward paper-trading run.

Usage:
  python dev/scripts/options/init_options_forward.py \
    --candidate-id spy_8otm_bull_put_v1 \
    --strategy-type bull_put_spread \
    --short-otm 0.08 --long-otm 0.10 \
    --start-date 2026-05-04 \
    [--initial-nav 10000]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

from core.options.paper.spec import (  # noqa: E402
    StrategySpec, OverlayParams, VolRegimeFilterParams, PricingParams,
)
from core.options.paper.runner import init_run, PAPER_DIR_DEFAULT  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate-id", required=True)
    ap.add_argument("--strategy-type", default="bull_put_spread",
                    choices=["bull_put_spread", "iron_condor"])
    ap.add_argument("--underlying", default="SPY")
    ap.add_argument("--short-otm", type=float, default=0.08)
    ap.add_argument("--long-otm", type=float, default=0.10)
    ap.add_argument("--dte", type=int, default=30)
    ap.add_argument("--risk-pct", type=float, default=0.02)
    ap.add_argument("--initial-nav", type=float, default=10000.0)
    ap.add_argument("--start-date", default=None,
                    help="YYYY-MM-DD (default = today)")
    # Overlay
    ap.add_argument("--stop-loss-frac", type=float, default=0.80)
    ap.add_argument("--early-tp-frac", type=float, default=0.50)
    ap.add_argument("--time-stop-dte", type=int, default=7)
    ap.add_argument("--vix-halt", type=float, default=40.0)
    ap.add_argument("--dd-halt-pct", type=float, default=0.10)
    # Vol regime
    ap.add_argument("--no-vol-filter", action="store_true",
                    help="Disable vol_regime_filter (mechanical monthly entry)")
    ap.add_argument("--vix-min", type=float, default=12.0)
    ap.add_argument("--vix-max", type=float, default=25.0)
    # Pricing
    ap.add_argument("--put-skew", type=float, default=1.30)
    ap.add_argument("--call-skew", type=float, default=0.75)

    args = ap.parse_args()

    spec = StrategySpec(
        candidate_id=args.candidate_id,
        strategy_type=args.strategy_type,
        underlying=args.underlying,
        short_otm_pct=args.short_otm,
        long_otm_pct=args.long_otm,
        dte_open_days=args.dte,
        risk_per_trade_pct=args.risk_pct,
        initial_nav=args.initial_nav,
        created_at=datetime.now().strftime("%Y-%m-%d"),
        overlay=OverlayParams(
            stop_loss_frac=args.stop_loss_frac,
            early_tp_frac=args.early_tp_frac,
            time_stop_dte=args.time_stop_dte,
            vix_halt_hard=args.vix_halt,
            dd_halt_pct=args.dd_halt_pct,
        ),
        vol_regime_filter=VolRegimeFilterParams(
            enabled=not args.no_vol_filter,
            vix_min=args.vix_min,
            vix_max=args.vix_max,
        ),
        pricing=PricingParams(
            put_skew_factor=args.put_skew,
            call_skew_factor=args.call_skew,
        ),
    )

    state = init_run(spec, base_dir=PAPER_DIR_DEFAULT, start_date=args.start_date)
    print(f"\nRun initialized:")
    print(f"  candidate_id: {state.candidate_id}")
    print(f"  spec_hash:    {state.spec_hash}")
    print(f"  start_date:   {state.start_date}")
    print(f"  initial_nav:  ${state.nav_initial:,.2f}")
    print(f"  output dir:   {PAPER_DIR_DEFAULT / state.candidate_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
