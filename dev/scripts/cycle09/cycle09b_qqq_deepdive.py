"""cycle09b §5.4 — NAV vs QQQ 0.851 deep-dive.

Closeout memo hypothesis: `rd_intensity_ttm` selects tech-heavy names
(NVDA / AAPL / MSFT / GOOGL / AMD / AVGO etc.) which are QQQ-weighted,
producing raw_pearson_vs_qqq = 0.851 on the cycle09b selector panel.

Diagnostics:
  1. Asset-class breakdown over time (equities / bonds / commodities /
     cash_anchor sum-of-weights time series + average exposure).
  2. Top-N holdings by total holding-days (count of dates where the
     name carries > 0 weight, sum-weight cumulative).
  3. Sector breakdown via config/sector_map.yaml (tech / communication /
     consumer_discretionary / etc.) — averaged weight by sector.
  4. QQQ overlap heuristic: portfolio weight share of names with
     sector ∈ {technology, communication, consumer_discretionary}
     (typical QQQ tech-heavy buckets).

Output: data/audit/cycle09b_trial1_qqq_deepdive.json
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Dict

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

import pandas as pd
import yaml

from core.mining.research_miner import ResearchCompositeSpec
from core.research.harness import HarnessConfig, evaluate_composite_spec
from core.research.risk_cluster_map import (
    ASSET_CLASS_BY_CLUSTER,
    make_unified_cluster_map,
)

from dev.scripts.cycle09.cycle09b_track_a_eval import _load_panel


SECTOR_MAP_PATH = PROJ / "config" / "sector_map.yaml"
OUT_PATH = PROJ / "data" / "audit" / "cycle09b_trial1_qqq_deepdive.json"

QQQ_SECTORS = {"technology", "communication", "consumer_discretionary"}


def _load_sector_map() -> Dict[str, str]:
    cfg = yaml.safe_load(SECTOR_MAP_PATH.read_text())
    smap = cfg.get("sector_map", {})
    return {sym: row["sector"] for sym, row in smap.items() if isinstance(row, dict)}


def main() -> int:
    print("[§5.4] Loading panel + factors...")
    t0 = time.time()
    panel, factors, mask, split_cfg = _load_panel()
    print(f"  panel: {panel['close'].shape}, factors={len(factors)} ({time.time()-t0:.1f}s)")

    spy = panel["close"].get("SPY")
    qqq = panel["close"].get("QQQ")

    print("\n[§5.4] Evaluating cycle09b Trial 1 to get daily weights...")
    cluster_map = make_unified_cluster_map(include_cross_asset=True)
    asset_class_map = {
        sym: ASSET_CLASS_BY_CLUSTER[cluster_map[sym]]
        for sym in panel["close"].columns if sym in cluster_map
    }
    cfg = HarnessConfig(
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
    feats = ["rs_vs_spy_63d", "cpi_yoy_pct", "rd_intensity_ttm"]
    panel_map = {f: factors[f] for f in feats}
    spec = ResearchCompositeSpec(
        features=tuple(feats), weights=(1/3, 1/3, 1/3),
        family_counts={"A": 1, "P": 1, "N": 1}, holding_freq="monthly",
    )
    t0 = time.time()
    r = evaluate_composite_spec(
        spec=spec, factor_panel_map=panel_map, price_df=panel["close"],
        open_df=panel["open"], spy_series=spy, qqq_series=qqq,
        config=cfg, research_mask=mask,
    )
    weights = r.weights  # date × symbol
    print(f"  weights: {weights.shape}  total_weight_per_date_max={weights.sum(axis=1).max():.4f}  ({time.time()-t0:.1f}s)")

    # ── 1. Asset-class breakdown ─────────────────────────────────────
    print("\n[§5.4] Asset-class breakdown over time...")
    ac_series = pd.DataFrame(index=weights.index)
    for ac in ("equities", "bonds", "commodities", "cash_anchor"):
        syms_in_ac = [s for s in weights.columns if asset_class_map.get(s) == ac]
        if syms_in_ac:
            ac_series[ac] = weights[syms_in_ac].sum(axis=1)
        else:
            ac_series[ac] = 0.0
    ac_series["other"] = weights.sum(axis=1) - ac_series.sum(axis=1)

    # Only consider dates where the portfolio actually holds something
    held_mask = weights.sum(axis=1) > 0.01
    ac_held = ac_series.loc[held_mask]
    ac_mean = {col: float(ac_held[col].mean()) for col in ac_held.columns}
    ac_max = {col: float(ac_held[col].max()) for col in ac_held.columns}
    print(f"  n_held_dates: {int(held_mask.sum())} / {len(weights)}")
    for col, m in ac_mean.items():
        print(f"  {col:14s}  mean={m:.4f}  max={ac_max[col]:.4f}")

    # ── 2. Top-N holdings ────────────────────────────────────────────
    print("\n[§5.4] Top-10 holdings by total weight-day product...")
    weight_days = weights.sum(axis=0).sort_values(ascending=False)
    n_held_days = (weights > 0).sum(axis=0).sort_values(ascending=False)
    top10 = []
    for sym in weight_days.head(15).index:
        top10.append({
            "symbol": sym,
            "weight_days_total": float(weight_days[sym]),
            "n_held_days": int(n_held_days[sym]),
            "fraction_of_held_dates": float(n_held_days[sym]) / max(int(held_mask.sum()), 1),
            "avg_weight_when_held": float(weight_days[sym]) / max(int(n_held_days[sym]), 1),
        })
    for h in top10[:10]:
        print(f"  {h['symbol']:6s}  weight_days={h['weight_days_total']:7.2f}  "
              f"n_days={h['n_held_days']:4d}  "
              f"frac_held={h['fraction_of_held_dates']:.3f}  "
              f"avg_w={h['avg_weight_when_held']:.4f}")

    # ── 3. Sector breakdown ──────────────────────────────────────────
    print("\n[§5.4] Sector breakdown via config/sector_map.yaml...")
    sector_map = _load_sector_map()
    sectors_in_universe = set(sector_map.get(s, "unknown") for s in weights.columns)
    sector_series = pd.DataFrame(index=weights.index)
    for sec in sectors_in_universe:
        syms_in_sec = [s for s in weights.columns if sector_map.get(s) == sec]
        if syms_in_sec:
            sector_series[sec] = weights[syms_in_sec].sum(axis=1)
    sec_held = sector_series.loc[held_mask]
    sec_mean = sec_held.mean().sort_values(ascending=False).to_dict()
    print("  Avg weight per sector (held dates only):")
    for sec, m in sec_mean.items():
        print(f"  {sec:30s}  {m:.4f}")

    # ── 4. QQQ-overlap heuristic ─────────────────────────────────────
    qqq_overlap_syms = [
        s for s in weights.columns
        if sector_map.get(s, "") in QQQ_SECTORS
    ]
    qqq_overlap_series = weights[qqq_overlap_syms].sum(axis=1)
    qqq_overlap_mean = float(qqq_overlap_series.loc[held_mask].mean())
    print(f"\n[§5.4] QQQ-sector overlap (technology + communication + consumer_disc):")
    print(f"  avg weight in QQQ-style sectors: {qqq_overlap_mean:.4f}")
    print(f"  n_qqq_overlap_syms in universe: {len(qqq_overlap_syms)}")

    out = {
        "cycle": "track-c-cycle-2026-05-12-09b",
        "audit_section": "§5.4 NAV vs QQQ 0.851 deep-dive",
        "candidate_id": "cycle09b_trial1_5a99868072e6",
        "n_held_dates": int(held_mask.sum()),
        "n_total_dates": int(len(weights)),
        "asset_class_avg_weight": ac_mean,
        "asset_class_max_weight": ac_max,
        "top10_holdings": top10[:10],
        "top15_holdings": top10,
        "sector_avg_weight": sec_mean,
        "qqq_overlap_avg_weight": qqq_overlap_mean,
        "qqq_overlap_symbols": sorted(qqq_overlap_syms),
        "qqq_sectors_def": sorted(QQQ_SECTORS),
        "interpretation": {
            "trial1_is_equity_heavy": ac_mean["equities"] > 0.50,
            "trial1_qqq_sector_overlap_pct": qqq_overlap_mean,
            "trial1_top1_holding": top10[0]["symbol"] if top10 else None,
            "trial1_top3_holdings": [h["symbol"] for h in top10[:3]],
        },
    }
    OUT_PATH.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n[§5.4] Output: {OUT_PATH.relative_to(PROJ)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
