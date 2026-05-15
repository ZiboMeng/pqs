"""Priority 5.2: inverse ETF cap grid search.

Strategy: cycle08_8ac6bccbeed1 spec (max_dd_126d + mom_252d + reversal_21d,
weekly cadence). Universe: 81 main + 10 blue chips + 3 inverse ETFs (94).
Construction: cap_aware_cross_asset with new "inverse_equity" cluster +
"inverse_equities" asset_class.

Grid: inverse_equities asset_class_cap ∈ {0.05, 0.075, 0.10, 0.125, 0.15}.

Output: full-period Sharpe + MaxDD + 2025 vs SPY + 2018 + stress slices.
Decision rule: pick cap maximizing Sharpe subject to MaxDD ≤ 20% AND
stress slice MaxDD ≤ 25% (CLAUDE.md). Tie-break: prefer LOWER cap.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd

PROJ = Path("/home/zibo/Documents/projects/pqs")
sys.path.insert(0, str(PROJ))
sys.path.insert(0, str(PROJ / "dev" / "scripts" / "cycle06"))


# Blue-chip cluster mapping (priority-5 extensions)
BLUE_CHIP_CLUSTERS = {
    "JPM":  "money_center_finance",
    "V":    "money_center_finance",
    "XOM":  "energy_oilgas",
    "HD":   "disc_premium",
    "ABBV": "mega_pharma",
    "NFLX": "mega_cap_internet_consumer",
    "KO":   "staples_defensive",
    "CRM":  "mega_cap_platform",
    "ORCL": "mega_cap_platform",
    "PEP":  "staples_defensive",
}

# Inverse ETFs → new "inverse_equity" cluster
INVERSE_ETF_CLUSTERS = {
    "SH":  "inverse_equity",
    "PSQ": "inverse_equity",
    "DOG": "inverse_equity",
}

# cycle08_8ac6bccbeed1 spec
SPEC_FEATURES = ("max_dd_126d", "mom_252d", "reversal_21d")
SPEC_WEIGHTS = (1/3, 1/3, 1/3)
SPEC_CADENCE = "weekly"

GRID_CAPS = [0.05, 0.075, 0.10, 0.125, 0.15]


def main():
    from core.config.loader import load_config
    from core.data.bar_store import BarStore
    from core.factors.base_masks import research_mask_default
    from core.factors.factor_generator import generate_all_factors
    from core.mining.research_miner import ResearchCompositeSpec
    from core.research.harness import HarnessConfig, evaluate_composite_spec
    from core.research.risk_cluster_map import (
        ASSET_CLASS_BY_CLUSTER,
        CROSS_ASSET_RISK_CLUSTER_MAP,
        make_unified_cluster_map,
    )
    from core.research.temporal_split import load_temporal_split, partition_for_role

    cfg = load_config(PROJ / "config")
    store = BarStore(root=Path(cfg.system.paths.data_dir))
    uni = cfg.universe
    main_syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs)
        + list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    drop = {"BRK-B", "USO", "SLV"}  # cycle08 drop list
    main_syms = [s for s in main_syms if s not in uni.blacklist
                 and s not in uni.macro_reference and s not in drop]
    extension_syms = list(BLUE_CHIP_CLUSTERS) + list(INVERSE_ETF_CLUSTERS)
    syms = main_syms + extension_syms
    for b in ("SPY", "QQQ"):
        if b not in syms:
            syms.append(b)
    print(f"Loading {len(syms)} symbols (main {len(main_syms)} + ext {len(extension_syms)})...")

    cross_asset_set = set(CROSS_ASSET_RISK_CLUSTER_MAP.keys())
    frames = {k: {} for k in ("close", "open", "high", "low", "volume")}
    for sym in syms:
        atr = sym in cross_asset_set
        df = store.load(sym, freq="1d", adjusted=True,
                        adjusted_total_return=atr, fallback="local")
        if df is None or df.empty or "close" not in df.columns:
            print(f"  ✗ {sym} missing")
            continue
        frames["close"][sym] = df["close"]
        for col in ("open", "high", "low", "volume"):
            if col in df.columns:
                frames[col][sym] = df[col]
    panel = {"close": pd.DataFrame(frames["close"]).sort_index()}
    panel["open"] = pd.DataFrame(frames["open"]).reindex_like(panel["close"])
    panel["high"] = pd.DataFrame(frames["high"]).reindex_like(panel["close"])
    panel["low"] = pd.DataFrame(frames["low"]).reindex_like(panel["close"])
    panel["volume"] = pd.DataFrame(frames["volume"]).reindex_like(panel["close"])

    split_cfg = load_temporal_split(PROJ / "config" / "temporal_split.yaml")
    panel = partition_for_role(panel, split_cfg, role="selector")
    print(f"  panel: {panel['close'].shape}")

    bench = {b: panel["close"][b] for b in ("SPY", "QQQ") if b in panel["close"].columns}
    factors = generate_all_factors(
        panel["close"], volume_df=panel["volume"],
        open_df=panel["open"], high_df=panel["high"], low_df=panel["low"],
        benchmark_map=bench,
    )
    mask = research_mask_default(panel["close"], panel["volume"])

    # Build extended cluster_map + asset_class_map
    base_cluster_map = make_unified_cluster_map(include_cross_asset=True)
    cluster_map = dict(base_cluster_map)
    cluster_map.update(BLUE_CHIP_CLUSTERS)
    cluster_map.update(INVERSE_ETF_CLUSTERS)

    asset_class_map = {}
    for sym in panel["close"].columns:
        if sym in cluster_map:
            clu = cluster_map[sym]
            if clu == "inverse_equity":
                asset_class_map[sym] = "inverse_equities"
            elif clu in ASSET_CLASS_BY_CLUSTER:
                asset_class_map[sym] = ASSET_CLASS_BY_CLUSTER[clu]
            else:
                asset_class_map[sym] = "equities"

    spec = ResearchCompositeSpec(
        features=SPEC_FEATURES, weights=SPEC_WEIGHTS,
        family_counts={"X": 3}, holding_freq=SPEC_CADENCE,
    )
    panel_map = {f: factors[f] for f in SPEC_FEATURES if f in factors}
    if len(panel_map) != len(SPEC_FEATURES):
        missing = set(SPEC_FEATURES) - set(panel_map)
        print(f"FATAL: missing factors {missing}")
        return 1

    validation_years = sorted({vy.year for vy in split_cfg.partition.validation_years})
    stress_slices = {
        ss.name: (ss.start.isoformat(), ss.end.isoformat())
        for ss in split_cfg.partition.stress_slices
    }
    spy = panel["close"].get("SPY")
    qqq = panel["close"].get("QQQ")

    print(f"\nGrid search: inverse_equities cap ∈ {GRID_CAPS}")
    print(f"{'cap%':>6} {'sharpe':>7} {'maxdd':>8} {'2025_vs_spy':>11} {'2018_maxdd':>10} {'covid_md':>10} {'rate_md':>10} {'cum_ret':>10}")
    print("-" * 90)
    results = []
    for cap in GRID_CAPS:
        hc = HarnessConfig(
            rebalance_cadence=SPEC_CADENCE,
            construction_mode="cap_aware_cross_asset",
            top_n=10, cluster_cap=0.20, max_single_weight=0.10,
            cluster_map=cluster_map, asset_class_map=asset_class_map,
            asset_class_caps={
                "equities":         0.70,
                "bonds":            0.40,
                "commodities":      0.20,
                "cash_anchor":      0.30,
                "inverse_equities": cap,  # ← grid variable
            },
        )
        r = evaluate_composite_spec(
            spec=spec, factor_panel_map=panel_map,
            price_df=panel["close"], open_df=panel["open"],
            spy_series=spy, qqq_series=qqq, config=hc,
            validation_years=validation_years, stress_slices=stress_slices,
            research_mask=mask,
        )
        sh = float(r.metrics_full_period.get("sharpe", 0))
        md = float(r.metrics_full_period.get("max_dd", 0))
        cum = float(r.metrics_full_period.get("cum_ret", 0))
        y2025 = r.metrics_per_validation_year.get(2025, {})
        vs_spy_25 = float(y2025.get("vs_spy", 0))
        y2018 = r.metrics_per_validation_year.get(2018, {})
        md2018 = float(y2018.get("max_dd", 0))
        covid_md = float(r.metrics_per_stress_slice.get("covid_flash", {}).get("max_dd", 0))
        rate_md = float(r.metrics_per_stress_slice.get("rate_hike_2022", {}).get("max_dd", 0))
        print(f"{cap*100:>6.1f} {sh:>7.3f} {md:>8.2%} {vs_spy_25:>11.2%} {md2018:>10.2%} {covid_md:>10.2%} {rate_md:>10.2%} {cum:>10.2%}")
        results.append({
            "cap_pct": cap * 100,
            "sharpe": sh, "max_dd": md, "cum_ret": cum,
            "y2025_vs_spy": vs_spy_25, "y2018_maxdd": md2018,
            "covid_flash_maxdd": covid_md, "rate_hike_2022_maxdd": rate_md,
            "concentration": dict(r.concentration),
        })

    # Decision rule
    print("\n=== DECISION (max Sharpe, MaxDD ≤ 20%, stress ≤ 25%) ===")
    eligible = [r for r in results
                if abs(r["max_dd"]) <= 0.20
                and abs(r["covid_flash_maxdd"]) <= 0.25
                and abs(r["rate_hike_2022_maxdd"]) <= 0.25]
    if eligible:
        best = max(eligible, key=lambda r: r["sharpe"])
        tied = [r for r in eligible if r["sharpe"] == best["sharpe"]]
        if len(tied) > 1:
            best = min(tied, key=lambda r: r["cap_pct"])  # prefer lower cap
        print(f"  WINNER: cap = {best['cap_pct']:.1f}% (sharpe {best['sharpe']:.3f}, maxdd {best['max_dd']:.2%})")
    else:
        print("  NO ELIGIBLE cap — all violate MaxDD ≤ 20% OR stress ≤ 25%")
        best = max(results, key=lambda r: r["sharpe"])
        print(f"  Best Sharpe (NOT eligible): cap = {best['cap_pct']:.1f}% (sharpe {best['sharpe']:.3f}, maxdd {best['max_dd']:.2%})")

    out = {
        "spec": {
            "features": list(SPEC_FEATURES), "weights": list(SPEC_WEIGHTS),
            "cadence": SPEC_CADENCE, "source": "cycle08_8ac6bccbeed1",
        },
        "universe_size": len(panel["close"].columns),
        "grid_caps_pct": [c * 100 for c in GRID_CAPS],
        "results": results,
        "winner_cap_pct": best["cap_pct"] if eligible else None,
        "winner_sharpe": best["sharpe"] if eligible else None,
        "all_eligible": eligible is not None and len(eligible) > 0,
    }
    out_path = PROJ / "data/audit/p5_inverse_etf_cap_grid.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nWrote: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
