"""Priority 7: PEAD Path 1 cost-sensitivity re-eval (2026-05-14).

PEAD baseline cost: 2bp commission + 30bp interday slippage.
Stress cost: 2bp commission + 60bp interday slippage (≈ 2x).

CLAUDE.md acceptance Track A: cost_robustness.multiplier_2x_remains_positive.
If PEAD Sharpe drops below 0 at 2x cost, signal is not cost-robust.

Trial 1 = active forward candidate (SUE>=1.5σ h21 n10).
Trial 6 = best hold=60 (Sharpe 1.06 baseline).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJ = Path("/home/zibo/Documents/projects/pqs")
sys.path.insert(0, str(PROJ))

from core.config.schemas.cost_model import CostModelConfig, CostTierConfig
from core.data.edgar_provider import EdgarProvider
from core.execution.cost_model import CostModel
from core.research.pead.earnings_dates import extract_earnings_dates_panel
from core.research.pead.sue_calculator import compute_sue_panel
from dev.scripts.pead._pead_smoke_common import load_universe, build_panels
from dev.scripts.pead.run_path1_sue_smoke import _run_one_trial


def main():
    print("=== Priority 7: PEAD Path 1 cost sensitivity ===")
    universe = load_universe()
    close_df, open_df = build_panels(universe, add_benchmark=False)
    print(f"Universe: {len(universe)}, panel range "
          f"{close_df.index.min().date()} → {close_df.index.max().date()}")

    edgar = EdgarProvider()
    earn = extract_earnings_dates_panel(universe, edgar_provider=edgar)
    sue = compute_sue_panel(earn)

    grid = [(1.5, 21, 10), (1.5, 60, 10)]  # trial 1 + trial 6

    cost_30 = CostModel(CostModelConfig(
        tiers={"default": CostTierConfig(
            symbols=[], commission_bps=2.0,
            slippage_interday_bps=30.0, slippage_intraday_bps=60.0,
        )}
    ))
    cost_60 = CostModel(CostModelConfig(
        tiers={"default": CostTierConfig(
            symbols=[], commission_bps=2.0,
            slippage_interday_bps=60.0, slippage_intraday_bps=120.0,
        )}
    ))

    print(f"\n{'spec':<25} {'sharpe@30bp':>13} {'sharpe@60bp':>13} {'maxdd@60bp':>12} {'verdict':>11}")
    print("-" * 80)
    out_records = []
    for thresh, hold, top_n in grid:
        spec = f"SUE>={thresh:.1f} h={hold} n={top_n}"
        r30 = _run_one_trial(sue, close_df, open_df, cost_30, thresh, hold, top_n, universe)
        r60 = _run_one_trial(sue, close_df, open_df, cost_60, thresh, hold, top_n, universe)
        sh30, sh60, md60 = r30["sharpe"], r60["sharpe"], r60["max_dd"]
        verdict = (
            "ROBUST" if sh60 >= 0.6 and abs(md60) <= 0.15 else
            "MARGINAL" if sh60 >= 0.3 else "FRAGILE"
        )
        print(f"{spec:<25} {sh30:>13.3f} {sh60:>13.3f} {md60:>12.2%} {verdict:>11}")
        out_records.append({
            "spec": spec, "30bp": {"sharpe": sh30, "cagr": r30["cagr"], "max_dd": r30["max_dd"]},
            "60bp": {"sharpe": sh60, "cagr": r60["cagr"], "max_dd": md60},
            "verdict": verdict,
        })

    out_path = PROJ / "data/audit/p7_pead_cost_sensitivity.json"
    out_path.write_text(json.dumps({
        "method": "PEAD Path 1 baseline 30bp vs stress 60bp slippage",
        "results": out_records,
    }, indent=2))
    print(f"\nWrote: {out_path}")


if __name__ == "__main__":
    main()
