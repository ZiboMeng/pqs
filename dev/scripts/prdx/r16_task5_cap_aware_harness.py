"""PRD-X v2 — Task 5: cycle06 cap_aware_cross_asset harness replication.

Runs cycle06's exact spec (drawup_from_252d_low + trend_tstat_20d
+ ret_2d, eq-weighted, weekly) through the real
`evaluate_composite_spec` harness with construction_mode=
`cap_aware_cross_asset`, top_n=10, cluster_cap=0.20,
max_single_weight=0.10 — the SAME harness cycle06 used to produce
its metrics_full_period.sharpe = 1.37.

Compares to R12 Path A (cycle06 composite + simple normalized-rank
top-N + monthly): Sharpe 0.5792 / MaxDD -0.1732.

§12.0 strict-baseline gap finding: does the cap_aware harness close
the Sharpe gap from R12 0.58 toward cycle06's reported 1.37?
Or is the 1.37 driven primarily by the 2007-2017 pre-window
(R12 uses 2018-2024 only)?
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

from core.config.schemas.cost_model import (  # noqa: E402
    CostModelConfig, CostTierConfig,
)
from core.execution.cost_model import CostModel  # noqa: E402
from core.mining.research_miner import (  # noqa: E402
    ResearchCompositeSpec,
)
from core.research.harness import (  # noqa: E402
    HarnessConfig, evaluate_composite_spec,
)
from core.research.risk_cluster_map import (  # noqa: E402
    make_unified_cluster_map, CROSS_ASSET_RISK_CLUSTER_MAP,
    ASSET_CLASS_BY_CLUSTER,
)

OUT_PATH = (PROJ / "data" / "audit"
            / "prdx_r16_task5_cap_aware_harness.json")
LOG_PATH = (PROJ / "data" / "audit"
            / "prdx_r16_task5_cap_aware_harness.log")


def _import_cycle06_loader():
    spec = importlib.util.spec_from_file_location(
        "cycle06_track_a_eval",
        PROJ / "dev" / "scripts" / "cycle06" / "cycle06_track_a_eval.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._load_panel


def _zero_cost():
    return CostModel(CostModelConfig(tiers={
        "default": CostTierConfig(
            symbols=[], commission_bps=0.0,
            slippage_interday_bps=0.0, slippage_intraday_bps=0.0)
    }))


def main():
    log_lines = []
    def _log(msg):
        line = f"[{datetime.utcnow().isoformat()}Z] {msg}"
        print(line, flush=True)
        log_lines.append(line)

    _log("R16 Task 5 — cap_aware_cross_asset harness replication")
    load_panel = _import_cycle06_loader()
    panel, factors, mask, split_cfg = load_panel()
    _log(f"panel close {panel['close'].shape} factors {len(factors)}")

    # cycle06 spec (weights sum exactly to 1.0)
    third = 1.0 / 3
    spec = ResearchCompositeSpec(
        features=("drawup_from_252d_low", "trend_tstat_20d", "ret_2d"),
        weights=(third, third, 1.0 - 2 * third),
        family_counts={"X": 3},
        holding_freq="weekly",
    )
    _log(f"spec: features={spec.features} holding_freq={spec.holding_freq}")

    factor_panel_map = {
        name: factors[name] for name in spec.features
        if name in factors
    }
    _log(f"factor_panel_map keys = {list(factor_panel_map.keys())}")

    cluster_map = make_unified_cluster_map(include_cross_asset=True)
    asset_class_map = {
        sym: ASSET_CLASS_BY_CLUSTER[cluster_map[sym]]
        for sym in panel["close"].columns if sym in cluster_map
    }

    # 3 harness configs, ascending complexity:
    #   A: cycle06's actual setup (weekly + cap_aware top_n=10
    #      cluster_cap=0.20 max_single_weight=0.10)
    #   B: simple monthly top_n=10 cap_aware (sanity vs R12 path)
    #   C: NO cap_aware — flat top_n equal-weight (closer to R12's
    #      hand-rolled normalized-rank construction)

    train_start = pd.Timestamp("2018-01-01")
    train_end = pd.Timestamp("2024-12-31")
    close = panel["close"].sort_index()
    close_train = close.loc[(close.index >= train_start)
                            & (close.index <= train_end)]
    open_train = panel["open"].reindex_like(close_train)
    spy_series = (close_train["SPY"] if "SPY" in close_train.columns
                  else None)
    qqq_series = (close_train["QQQ"] if "QQQ" in close_train.columns
                  else None)

    def run_config(name, hc):
        _log(f"=== {name} ===")
        result = evaluate_composite_spec(
            spec=spec, factor_panel_map=factor_panel_map,
            price_df=close_train, open_df=open_train,
            spy_series=spy_series, qqq_series=qqq_series,
            cost_model=_zero_cost(), config=hc,
            research_mask=(mask.reindex_like(close_train)
                           if mask is not None else None))
        mfp = (result.metrics_full_period
               if hasattr(result, "metrics_full_period") else {})
        _log(f"  metrics_full_period: cum={mfp.get('cum_ret')} "
             f"sharpe={mfp.get('sharpe')} max_dd={mfp.get('max_dd')} "
             f"vs_spy={mfp.get('vs_spy')}")
        return {
            "name": name, "metrics_full_period": dict(mfp) if mfp else {},
            "construction_mode": hc.construction_mode,
            "rebalance_cadence": hc.rebalance_cadence,
            "top_n": hc.top_n, "cluster_cap": hc.cluster_cap,
            "max_single_weight": hc.max_single_weight,
        }

    # cycle06's actual setup
    hc_a = HarnessConfig(
        rebalance_cadence="weekly",
        construction_mode="cap_aware_cross_asset",
        top_n=10, cluster_cap=0.20, max_single_weight=0.10,
        cluster_map=cluster_map,
        asset_class_map=asset_class_map,
        asset_class_caps={
            "equities": 0.70, "bonds": 0.40,
            "commodities": 0.20, "cash_anchor": 0.30,
        },
    )
    res_a = run_config("A_cycle06_actual_weekly_cap_aware", hc_a)

    # monthly + cap_aware
    hc_b = HarnessConfig(
        rebalance_cadence="monthly",
        construction_mode="cap_aware_cross_asset",
        top_n=10, cluster_cap=0.20, max_single_weight=0.10,
        cluster_map=cluster_map, asset_class_map=asset_class_map,
        asset_class_caps={
            "equities": 0.70, "bonds": 0.40,
            "commodities": 0.20, "cash_anchor": 0.30,
        },
    )
    res_b = run_config("B_monthly_cap_aware", hc_b)

    # global top_n (no cap_aware) — closer to R12 Path A construction
    hc_c = HarnessConfig(
        rebalance_cadence="monthly",
        construction_mode="global_top_n",
        top_n=10, max_single_weight=0.10,
    )
    res_c = run_config("C_monthly_global_top_n", hc_c)

    # cycle06 reference numbers
    cycle06_ref = {
        "spec_nav_sharpe": 0.5654,            # apples-to-apples
        "full_period_sharpe": 1.3663,         # 2007-2025 pre-X0
        "full_period_max_dd": -0.1960,
        "caveat": "full_period uses 18yr 2007-2025 + pre-X0 panel; "
                  "R16 uses 7yr 2018-2024 + post-X0 TR panel — "
                  "windows NOT directly comparable",
    }

    summary = {
        "cycle06_reference": cycle06_ref,
        "R12_path_A_normalized_rank": {
            "construction": "simple normalized-rank top-N monthly",
            "sharpe": 0.5792, "max_dd": -0.1732, "cum_ret": 0.4557,
        },
        "configs": [res_a, res_b, res_c],
        "tolerances": {"sharpe": 0.2, "maxdd": 0.05},
        "verdict": {},
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }

    # Verdict per config (vs cycle06 nav_sharpe apples-to-apples)
    for r in [res_a, res_b, res_c]:
        mfp = r.get("metrics_full_period", {})
        s = mfp.get("sharpe")
        d = mfp.get("max_dd")
        if s is None or d is None:
            continue
        s = float(s); d = float(d)
        summary["verdict"][r["name"]] = {
            "sharpe_vs_a_nav_sharpe_pass": s >= (cycle06_ref["spec_nav_sharpe"]
                                                  - 0.2),
            "sharpe_vs_b_full_period_pass": s >= (cycle06_ref["full_period_sharpe"]
                                                   - 0.2),
            "maxdd_pass": d >= (cycle06_ref["full_period_max_dd"]
                                 - 0.05),
            "sharpe_value": s,
            "maxdd_value": d,
        }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(summary, indent=2, default=str))
    LOG_PATH.write_text("\n".join(log_lines))
    _log(f"written {OUT_PATH}")
    _log("VERDICT TABLE:")
    for name, v in summary["verdict"].items():
        _log(f"  {name}: sharpe={v['sharpe_value']:.4f} "
             f"(vs nav_sharpe 0.5654 pass={v['sharpe_vs_a_nav_sharpe_pass']}, "
             f"vs full-period 1.37 pass={v['sharpe_vs_b_full_period_pass']}), "
             f"maxdd={v['maxdd_value']:.4f} pass={v['maxdd_pass']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
