"""PEAD Path 1 — SUE-based signal smoke backtest.

PRD: docs/prd/20260514-pead_bundle_phase1_prd.md §3 Path 1
Lineage: pead-bundle-2026-05-14
Cost: 30bp slip + 2bp commission (cycle11+ baseline)

9 trials: (SUE_threshold × max_hold × top_n) representative grid.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJ = Path("/home/zibo/Documents/projects/pqs")
if str(PROJ) not in sys.path:
    sys.path.insert(0, str(PROJ))

import numpy as np
import pandas as pd

from core.backtest.signal_driven_runner import SignalDrivenBacktest
from core.data.edgar_provider import EdgarProvider
from core.execution.cost_model import CostModel
from core.config.schemas.cost_model import CostModelConfig, CostTierConfig

from core.research.pead.earnings_dates import extract_earnings_dates_panel
from core.research.pead.sue_calculator import compute_sue_panel, build_sue_signal_panel

from dev.scripts.pead._pead_smoke_common import (
    load_universe, build_panels, spy_baseline, trial_metrics,
)


def _run_one_trial(
    sue_panel,
    close_df,
    open_df,
    cost,
    sue_threshold: float,
    max_hold: int,
    top_n: int,
    universe: list,
) -> dict:
    """One SUE-PEAD trial."""
    entry = build_sue_signal_panel(
        sue_panel,
        sue_threshold=sue_threshold,
        price_index=close_df.index,
        universe=universe,
    )
    # Exit signal = entry shifted by max_hold (forced exit)
    exit_ = entry.shift(max_hold).fillna(False).astype(bool)

    n_signals = int(entry.values.sum())
    years = (close_df.index[-1] - close_df.index[0]).days / 365.25
    n_per_year = n_signals / max(years, 1.0)

    if n_signals == 0:
        return {"sharpe": 0.0, "cagr": 0.0, "max_dd": 0.0, "n_trades": 0,
                "final_equity": 10_000.0, "n_signals_total": 0,
                "n_signals_avg_per_year": 0.0}

    try:
        bt = SignalDrivenBacktest(
            entry_signals=entry,
            exit_signals=exit_,
            price_df=close_df,
            ttl_bars=0,
            top_n=top_n,
            cost_model=cost,
            initial_capital=10_000.0,
            execution_delay_bars=1,
            open_df=open_df,
        )
        result = bt.run()
    except Exception as e:
        return {"sharpe": 0.0, "cagr": 0.0, "max_dd": 0.0, "n_trades": 0,
                "final_equity": 10_000.0, "n_signals_total": n_signals,
                "n_signals_avg_per_year": n_per_year, "error": str(e)[:120]}

    m = trial_metrics(result, top_n_signals_avg=n_per_year)
    m["n_signals_total"] = n_signals
    return m


def main():
    print("=== PEAD Path 1 (SUE) smoke @ 30bp ===")

    universe = load_universe()
    print(f"Universe: {len(universe)} stocks (EDGAR-covered)")

    close_df, open_df = build_panels(universe, add_benchmark=False)
    print(f"Panels: close={close_df.shape}, open={open_df.shape}, "
          f"range {close_df.index.min().date()} → {close_df.index.max().date()}")

    # Extract earnings dates + SUE
    edgar = EdgarProvider()
    print("Extracting earnings dates from EDGAR cache...")
    earn = extract_earnings_dates_panel(universe, edgar_provider=edgar)
    print(f"Earnings events: {len(earn)} rows; tickers covered: {earn['ticker'].nunique()}")

    print("Computing SUE...")
    sue = compute_sue_panel(earn)
    non_na = sue["sue"].notna().sum()
    print(f"SUE: {non_na}/{len(sue)} non-NaN; "
          f"distribution: mean={sue['sue'].mean():.3f}, "
          f"std={sue['sue'].std():.3f}, "
          f"≥1σ count={int((sue['sue']>=1.0).sum())}, "
          f"≥1.5σ count={int((sue['sue']>=1.5).sum())}, "
          f"≥2σ count={int((sue['sue']>=2.0).sum())}")

    cost = CostModel(CostModelConfig(
        tiers={"default": CostTierConfig(
            symbols=[], commission_bps=2.0,
            slippage_interday_bps=30.0, slippage_intraday_bps=60.0,
        )}
    ))

    # 9-trial grid
    grid = [
        # (sue_threshold, max_hold, top_n)
        (1.0,  21, 10),
        (1.5,  21, 10),
        (2.0,  21, 10),
        (1.0,  42, 10),
        (1.5,  42, 10),
        (2.0,  42, 10),
        (1.5,  60, 10),
        (1.5,  21, 5),
        (1.5,  21, 20),
    ]

    print(f"\nRunning {len(grid)} trials...")
    trials = []
    for i, (thr, hold, top_n) in enumerate(grid):
        m = _run_one_trial(sue, close_df, open_df, cost, thr, hold, top_n, universe)
        m.update({"trial_id": i, "sue_threshold": thr,
                  "max_hold": hold, "top_n": top_n})
        trials.append(m)
        err = f" [ERR: {m.get('error', '')}]" if "error" in m else ""
        print(f"  trial {i:2d}: SUE≥{thr:.1f}σ hold={hold:3d} top_n={top_n:2d} "
              f"→ Sharpe={m['sharpe']:+.3f} CAGR={m['cagr']*100:+.2f}% "
              f"MaxDD={m['max_dd']*100:+.2f}% trades={m['n_trades']:5d} "
              f"signals/yr≈{m['n_signals_avg_per_year']:.1f}{err}")

    # SPY baseline
    spy = spy_baseline()
    print(f"\n=== SPY baseline ===")
    print(f"  Sharpe={spy['sharpe']:+.3f} CAGR={spy['cagr']*100:+.2f}%")

    # Top by Sharpe
    valid = [t for t in trials if "error" not in t and t["sharpe"] > 0]
    top = sorted(valid, key=lambda x: -x["sharpe"])[:5]
    print(f"\n=== Top 5 by Sharpe ===")
    for t in top:
        beat = "✓" if t["sharpe"] > spy["sharpe"] else "✗"
        print(f"  {beat} trial {t['trial_id']:2d}: SUE≥{t['sue_threshold']:.1f}σ "
              f"hold={t['max_hold']:3d} top_n={t['top_n']:2d} → "
              f"Sharpe={t['sharpe']:+.3f} CAGR={t['cagr']*100:+.2f}%")

    # Save
    out = PROJ / "data/audit/pead_path1_sue_smoke.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "lineage": "pead-bundle-2026-05-14",
        "path": "path1_sue",
        "cost_bps": 30,
        "universe_size": len(universe),
        "earnings_events_total": int(len(earn)),
        "sue_non_nan": int(non_na),
        "n_trials": len(trials),
        "spy_baseline": spy,
        "trials": trials,
        "top_5_by_sharpe": top,
    }
    out.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\nSaved: {out}")

    if top and top[0]["sharpe"] > spy["sharpe"]:
        print(f"\nVERDICT: ≥1 trial beat SPY Sharpe. Track A acceptance eligible.")
    else:
        print(f"\nVERDICT: 0 trials beat SPY Sharpe. PEAD Path 1 informative null.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
