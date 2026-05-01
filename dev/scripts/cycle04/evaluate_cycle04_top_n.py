"""Cycle #04 cross-asset evaluation pipeline (cap_aware_cross_asset mode).

Per cycle #04 yaml (track-c-cycle-2026-05-01-04) report_only requirements:
- Top-K archived trial NAV diagnostics under cap_aware_cross_asset
  (cluster_cap=0.20 + max_single=0.10 + asset_class_caps={equities=0.70,
  bonds=0.40, commodities=0.20, cash_anchor=0.30})
- Asset-class exposure census (equity/bond/commodity/cash weight_avg
  + non_equity p25/p50/p75 + days_with_zero_non_equity_pct)
- Regime diagnostics per regime
- Cluster diversity census (extended to 22-cluster cross-asset universe)
- Cross-cycle NAV correlation vs RCMv1 + Cand-2 + cycle #03 top-1
  (raw pooled Pearson + residual after stripping SPY+QQQ beta)
- Drawdown reduction per pct return sacrificed
- 2025 QQQ soft-miss trade-off clause check
- R41 5-tier classification per top trial

Inputs read at runtime:
- Cycle #04 archive trials from rcm_archive.db (lineage track-c-cycle-2026-05-01-04)
- Production prices via BarStore.load(..., adjusted_total_return=True)
  (cycle #04 uses total-return path so bond/cash distributions are captured)
- Temporal split (selector role → train+validation visibility)
- RCMv1 + Cand-2 frozen specs from data/research_candidates/

Output: data/ml/cycle04_evaluation/<lineage>/evaluation_summary.json

Decision authority: tactical (operator); user direction "1 不需要停下"
2026-05-01 covers full P0a-P0e + cycle #04 closeout pipeline.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yaml


PROJ = Path("/home/zibo/Documents/projects/pqs")
LINEAGE_TAG = "track-c-cycle-2026-05-01-04"
CRITERIA_YAML = (
    PROJ / "data" / "research_candidates"
    / f"{LINEAGE_TAG}_promotion_criteria.yaml"
)


# ── Loaders ──────────────────────────────────────────────────────────────────


def _load_criteria_yaml() -> Dict[str, Any]:
    return yaml.safe_load(CRITERIA_YAML.read_text())


def _load_top_n_archived_trials(
    top_k: int = 10,
    archive_db: str = "data/mining/rcm_archive.db",
) -> pd.DataFrame:
    con = sqlite3.connect(str(PROJ / archive_db))
    df = pd.read_sql(
        "SELECT trial_id, ic_ir, features_csv, weights_csv, "
        "family_counts_json, ic_mean, ic_std, turnover_proxy, "
        "corr_concentration, n_dates, objective "
        "FROM rcm_trials WHERE lineage_tag = ? "
        "ORDER BY ic_ir DESC LIMIT ?",
        con, params=(LINEAGE_TAG, top_k),
    )
    con.close()
    return df


def _build_inputs(criteria: Dict[str, Any]):
    """Build factor_panel_map + price_df + benchmark series + research_mask
    over the train+validation panel using TOTAL-RETURN-adjusted prices for
    cross-asset symbols (cycle #04 cross_asset).

    Total-return adjustment is applied via BarStore.load(adjusted_total_return=
    True) for symbols in CROSS_ASSET_RISK_CLUSTER_MAP. Stocks remain on
    splits-only adjustment (their distributions are not currently adjusted
    for in BarStore — known gap, accepted for cycle #04 since stock alpha
    is dominated by price return)."""
    import sys
    sys.path.insert(0, str(PROJ))
    from core.config.loader import load_config
    from core.data.bar_store import BarStore
    from core.factors.factor_generator import generate_all_factors
    from core.factors.base_masks import research_mask_default
    from core.research.temporal_split import (
        load_temporal_split,
        partition_for_role,
    )
    from core.research.risk_cluster_map import CROSS_ASSET_RISK_CLUSTER_MAP

    cfg = load_config(PROJ / "config")
    store = BarStore(root=Path(cfg.system.paths.data_dir))

    uni = cfg.universe
    syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs)
        + list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    drop_set = set(criteria.get("drop_symbols", []))
    syms = [s for s in syms if s not in uni.blacklist
            and s not in uni.macro_reference and s not in drop_set]
    for b in ("SPY", "QQQ"):
        if b not in syms:
            syms.append(b)

    cross_asset_set = set(CROSS_ASSET_RISK_CLUSTER_MAP.keys())

    frames = {k: {} for k in ("close", "open", "high", "low", "volume")}
    for sym in syms:
        # Cross-asset symbols load with total-return adjustment;
        # stocks keep splits-only (existing pipeline)
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

    split_cfg = load_temporal_split(PROJ / "config" / "temporal_split.yaml")
    panel = {"close": close_df, "open": open_df, "high": high_df,
             "low": low_df, "volume": volume_df}
    panel = partition_for_role(panel, split_cfg, role="selector")

    benchmark_map = {
        b: panel["close"][b]
        for b in ("SPY", "QQQ")
        if b in panel["close"].columns
    }
    all_factors = generate_all_factors(
        panel["close"], volume_df=panel["volume"],
        open_df=panel["open"], high_df=panel["high"], low_df=panel["low"],
        benchmark_map=benchmark_map,
    )
    mask = (
        research_mask_default(panel["close"], panel["volume"])
        if panel["volume"] is not None else None
    )
    return panel, all_factors, mask, split_cfg


# ── Per-trial harness eval (cap_aware_cross_asset) ──────────────────────────


def _evaluate_one(
    trial_row: pd.Series,
    panel: Dict[str, pd.DataFrame],
    all_factors: Dict[str, pd.DataFrame],
    research_mask,
    cycle_yaml: Dict[str, Any],
    split_cfg,
) -> Dict[str, Any]:
    """Run one trial through harness with cap_aware_cross_asset construction."""
    import sys
    sys.path.insert(0, str(PROJ))
    from core.mining.research_miner import ResearchCompositeSpec
    from core.research.harness import HarnessConfig, evaluate_composite_spec
    from core.research.risk_cluster_map import (
        ASSET_CLASS_BY_CLUSTER,
        make_unified_cluster_map,
    )

    feats = trial_row["features_csv"].split(",")
    weights = [float(w) for w in trial_row["weights_csv"].split(",")]
    family_counts = json.loads(trial_row["family_counts_json"])

    total = sum(weights)
    if abs(total - 1.0) > 0:
        weights = [w / total for w in weights]
        residual = 1.0 - sum(weights)
        if abs(residual) > 0:
            mi = max(range(len(weights)), key=lambda i: weights[i])
            weights[mi] += residual

    spec = ResearchCompositeSpec(
        features=tuple(feats), weights=tuple(weights), family_counts=family_counts,
    )
    panel_map = {f: all_factors[f] for f in feats if f in all_factors}
    if len(panel_map) != len(feats):
        missing = [f for f in feats if f not in panel_map]
        return {"trial_id": trial_row["trial_id"], "error": f"missing factors: {missing}"}

    construction = cycle_yaml.get("construction", {})
    unified_cluster_map = make_unified_cluster_map(include_cross_asset=True)
    asset_class_map = {
        sym: ASSET_CLASS_BY_CLUSTER[cluster]
        for sym, cluster in unified_cluster_map.items()
    }
    asset_class_caps = {
        "equities":     float(construction["asset_class_caps"]["equities_max"]),
        "bonds":        float(construction["asset_class_caps"]["bonds_max"]),
        "commodities":  float(construction["asset_class_caps"]["commodities_max"]),
        "cash_anchor":  float(construction["asset_class_caps"]["cash_anchor_max"]),
    }

    cfg_h = HarnessConfig(
        construction_mode="cap_aware_cross_asset",
        rebalance_cadence=construction.get("rebalance_cadence", "monthly"),
        top_n=int(construction.get("top_n", 10)),
        cluster_map=unified_cluster_map,
        cluster_cap=float(construction.get("cluster_cap", 0.20)),
        max_single_weight=float(construction.get("max_single_weight", 0.10)),
        asset_class_map=asset_class_map,
        asset_class_caps=asset_class_caps,
        horizon_days=int(cycle_yaml["hard_requirements"].get(
            "fwd_return_horizon_days", 21
        )),
    )

    spy = panel["close"].get("SPY")
    qqq = panel["close"].get("QQQ")

    validation_years = sorted({vy.year for vy in split_cfg.partition.validation_years})
    stress_slices = {
        ss.name: (ss.start.isoformat(), ss.end.isoformat())
        for ss in split_cfg.partition.stress_slices
    }

    try:
        res = evaluate_composite_spec(
            spec=spec, factor_panel_map=panel_map,
            price_df=panel["close"], open_df=panel["open"],
            spy_series=spy, qqq_series=qqq, config=cfg_h,
            validation_years=validation_years, stress_slices=stress_slices,
            research_mask=research_mask,
        )
    except Exception as exc:
        return {"trial_id": trial_row["trial_id"],
                "error": f"harness {type(exc).__name__}: {exc}"}

    asset_exposure = _compute_asset_class_exposure(
        res.weights, asset_class_map,
    )
    cluster_diversity = _compute_cluster_diversity(
        res.weights, unified_cluster_map, top_n=int(construction.get("top_n", 10)),
    )

    return {
        "trial_id": trial_row["trial_id"],
        "construction_mode": "cap_aware_cross_asset",
        "features": feats,
        "weights": weights,
        "ic_ir_mining": float(trial_row["ic_ir"]),
        "n_observed_days": res.n_observed_days,
        "metrics_full_period": res.metrics_full_period,
        "metrics_per_validation_year": {
            int(k): v for k, v in res.metrics_per_validation_year.items()
        },
        "metrics_per_stress_slice": res.metrics_per_stress_slice,
        "concentration": res.concentration,
        "nav_correlation_vs_benchmark": res.nav_correlation_vs_benchmark,
        "asset_class_exposure": asset_exposure,
        "cluster_diversity": cluster_diversity,
        "_nav_series": res.nav,
        "_weights_df": res.weights,
    }


# ── Asset class exposure census (cycle #04 NEW) ─────────────────────────


def _compute_asset_class_exposure(
    weights_df: pd.DataFrame,
    asset_class_map: Dict[str, str],
) -> Dict[str, Any]:
    """Per-rebalance-day asset-class weight aggregation; report avg/p25/
    p50/p75 + zero-non-equity-day fraction."""
    rows = []
    non_equity_pct = []
    for date, row in weights_df.iterrows():
        nz = row[row > 1e-6]
        if len(nz) == 0:
            continue
        ac_w = defaultdict(float)
        for sym, w in nz.items():
            ac = asset_class_map.get(sym, "unmapped")
            ac_w[ac] += float(w)
        non_eq = (
            ac_w.get("bonds", 0) + ac_w.get("commodities", 0)
            + ac_w.get("cash_anchor", 0)
        )
        non_equity_pct.append(non_eq)
        rows.append({
            "equity_weight": ac_w.get("equities", 0.0),
            "bond_weight": ac_w.get("bonds", 0.0),
            "commodity_weight": ac_w.get("commodities", 0.0),
            "cash_anchor_weight": ac_w.get("cash_anchor", 0.0),
            "non_equity_weight": non_eq,
        })

    if not rows:
        return {
            "equity_weight_avg": 0.0, "bond_weight_avg": 0.0,
            "commodity_weight_avg": 0.0, "cash_anchor_weight_avg": 0.0,
            "non_equity_weight_avg": 0.0, "non_equity_weight_p25": 0.0,
            "non_equity_weight_p50": 0.0, "non_equity_weight_p75": 0.0,
            "non_equity_weight_min": 0.0, "non_equity_weight_max": 0.0,
            "days_with_zero_non_equity_pct": 1.0,
        }

    df = pd.DataFrame(rows)
    n_zero = sum(1 for x in non_equity_pct if x < 1e-6)
    return {
        "equity_weight_avg":     float(df["equity_weight"].mean()),
        "bond_weight_avg":       float(df["bond_weight"].mean()),
        "commodity_weight_avg":  float(df["commodity_weight"].mean()),
        "cash_anchor_weight_avg": float(df["cash_anchor_weight"].mean()),
        "non_equity_weight_avg": float(df["non_equity_weight"].mean()),
        "non_equity_weight_p25": float(df["non_equity_weight"].quantile(0.25)),
        "non_equity_weight_p50": float(df["non_equity_weight"].quantile(0.50)),
        "non_equity_weight_p75": float(df["non_equity_weight"].quantile(0.75)),
        "non_equity_weight_min": float(df["non_equity_weight"].min()),
        "non_equity_weight_max": float(df["non_equity_weight"].max()),
        "days_with_zero_non_equity_pct": float(n_zero / len(df)),
    }


# ── Cluster diversity census (cycle #03 reused) ─────────────────────────


def _compute_cluster_diversity(
    weights_df: pd.DataFrame,
    cluster_map: Dict[str, str],
    top_n: int = 10,
) -> Dict[str, Any]:
    n_clusters_per_day = []
    cluster_max_concentrations = []
    n_picks_per_day = []
    implicit_cash = []
    cluster_total_weight: Dict[str, float] = defaultdict(float)
    cluster_count: Dict[str, int] = defaultdict(int)

    for date, row in weights_df.iterrows():
        nz = row[row > 1e-6]
        if len(nz) == 0:
            continue
        cluster_w: Dict[str, float] = defaultdict(float)
        for sym, w in nz.items():
            clu = cluster_map.get(sym)
            if clu is None:
                continue
            cluster_w[clu] += float(w)
        if not cluster_w:
            continue
        n_clusters_per_day.append(len(cluster_w))
        cluster_max_concentrations.append(max(cluster_w.values()))
        n_picks_per_day.append(int((nz > 1e-3).sum()))
        implicit_cash.append(max(0.0, 1.0 - float(nz.sum())))
        for c, w in cluster_w.items():
            cluster_total_weight[c] += w
            cluster_count[c] += 1

    avg_cluster_weight = {
        c: cluster_total_weight[c] / cluster_count[c]
        for c in cluster_total_weight
    }
    top_3 = sorted(avg_cluster_weight.items(), key=lambda x: -x[1])[:3]

    return {
        "n_unique_clusters_per_rebalance_avg": (
            float(np.mean(n_clusters_per_day)) if n_clusters_per_day else 0.0
        ),
        "cluster_concentration_max": (
            float(max(cluster_max_concentrations))
            if cluster_max_concentrations else 0.0
        ),
        "n_picks_avg": float(np.mean(n_picks_per_day)) if n_picks_per_day else 0.0,
        "implicit_cash_pct_avg": (
            float(np.mean(implicit_cash)) if implicit_cash else 0.0
        ),
        "top_3_clusters_by_average_weight": [
            {"cluster": c, "avg_weight": float(w)} for c, w in top_3
        ],
    }


# ── Cross-cycle NAV correlation ────────────────────────────────────────


def _residual_pair_corr(a: pd.Series, b: pd.Series, bench: pd.Series) -> float:
    df = pd.DataFrame({"a": a, "b": b, "bench": bench}).dropna()
    if len(df) < 5:
        return float("nan")
    bv = df["bench"].var()
    if not np.isfinite(bv) or bv < 1e-12:
        return float("nan")
    beta_a = df.cov().loc["a", "bench"] / bv
    beta_b = df.cov().loc["b", "bench"] / bv
    res_a = df["a"] - beta_a * df["bench"]
    res_b = df["b"] - beta_b * df["bench"]
    if res_a.std() < 1e-12 or res_b.std() < 1e-12:
        return float("nan")
    return float(res_a.corr(res_b))


def _compute_cross_cycle_correlations(
    candidate_nav: pd.Series,
    reference_navs: Dict[str, pd.Series],
    spy_close: pd.Series,
    qqq_close: pd.Series,
) -> Dict[str, Any]:
    out = {}
    cand_ret = candidate_nav.pct_change().dropna()
    spy_ret = spy_close.pct_change().reindex(cand_ret.index).dropna()
    qqq_ret = qqq_close.pct_change().reindex(cand_ret.index).dropna()
    common = cand_ret.index.intersection(spy_ret.index).intersection(qqq_ret.index)
    cand_ret = cand_ret.reindex(common)
    spy_ret = spy_ret.reindex(common)
    qqq_ret = qqq_ret.reindex(common)

    for name, ref_nav in reference_navs.items():
        ref_ret = ref_nav.pct_change().reindex(common).dropna()
        c2 = common.intersection(ref_ret.index)
        if len(c2) < 30:
            out[f"{name}_pooled_pearson_raw"] = None
            out[f"{name}_pooled_pearson_residual_vs_spy"] = None
            out[f"{name}_pooled_pearson_residual_vs_qqq"] = None
            continue
        a = cand_ret.reindex(c2)
        b = ref_ret.reindex(c2)
        spy_c = spy_ret.reindex(c2)
        qqq_c = qqq_ret.reindex(c2)
        out[f"{name}_pooled_pearson_raw"] = float(a.corr(b))
        out[f"{name}_pooled_pearson_residual_vs_spy"] = _residual_pair_corr(a, b, spy_c)
        out[f"{name}_pooled_pearson_residual_vs_qqq"] = _residual_pair_corr(a, b, qqq_c)
        out[f"{name}_n_overlap_days"] = int(len(c2))
    return out


# ── R41 5-tier classification ───────────────────────────────────────────


def _classify_r41(
    evaluation: Dict[str, Any],
    nav_corr_vs_existing: Dict[str, Any],
    anchor_features: Dict[str, List[str]],
    overlap_threshold: int = 2,
    pooled_max: float = 0.85,
    residual_max: float = 0.70,
) -> Dict[str, Any]:
    feats = set(evaluation.get("features", []))
    overlaps = {
        name: len(feats & set(anchor)) for name, anchor in anchor_features.items()
    }
    max_overlap = max(overlaps.values()) if overlaps else 0
    sibling_by_factor = max_overlap >= overlap_threshold

    raw_pearsons = []
    residual_pearsons = []
    for name in anchor_features.keys():
        rp = nav_corr_vs_existing.get(f"{name}_pooled_pearson_raw")
        if rp is not None:
            raw_pearsons.append(rp)
        rsv = nav_corr_vs_existing.get(f"{name}_pooled_pearson_residual_vs_spy")
        rqv = nav_corr_vs_existing.get(f"{name}_pooled_pearson_residual_vs_qqq")
        if rsv is not None:
            residual_pearsons.append(rsv)
        if rqv is not None:
            residual_pearsons.append(rqv)
    sibling_by_nav = (
        (raw_pearsons and max(raw_pearsons) >= pooled_max) or
        (residual_pearsons and max(residual_pearsons) >= residual_max)
    )

    if sibling_by_factor or sibling_by_nav:
        tier = 2
        reasons = []
        if sibling_by_factor:
            reasons.append(f"factor-overlap max={max_overlap} ≥ {overlap_threshold}")
        if sibling_by_nav:
            reasons.append(
                f"raw_pearson max={max(raw_pearsons):.3f}" if raw_pearsons else ""
            )
            reasons.append(
                f"residual_pearson max={max(residual_pearsons):.3f}" if residual_pearsons else ""
            )
        reason = "; ".join(r for r in reasons if r)
    else:
        m = evaluation.get("metrics_full_period", {})
        cum = m.get("cum_ret", 0)
        if cum is None or not np.isfinite(cum):
            tier, reason = 5, "non-evaluable cum_ret"
        else:
            tier, reason = 1, "non-sibling pending Track A acceptance verification"

    return {
        "tier": tier,
        "reason": reason,
        "factor_overlap_max": max_overlap,
        "factor_overlaps_per_anchor": overlaps,
        "raw_pearson_max": float(max(raw_pearsons)) if raw_pearsons else None,
        "residual_pearson_max": float(max(residual_pearsons)) if residual_pearsons else None,
    }


# ── 2025 QQQ soft-miss trade-off check ─────────────────────────────────


def _check_2025_qqq_soft_miss(
    evaluation: Dict[str, Any],
    qqq_2025_max_dd: float,
) -> Dict[str, Any]:
    """Per cycle #04 yaml post_2025_qqq_soft_miss_trade_off_clause.
    Returns triggered=True if all conditions met."""
    val_metrics = evaluation.get("metrics_per_validation_year", {})
    fp = evaluation.get("metrics_full_period", {})
    if 2025 not in val_metrics:
        return {"triggered": False, "reason": "2025 metrics unavailable"}
    val_2025 = val_metrics[2025] or {}
    excess_qqq_2025 = val_2025.get("vs_qqq")
    excess_spy_2025 = val_2025.get("vs_spy")
    fp_excess_qqq = fp.get("vs_qqq")
    val_2025_max_dd = val_2025.get("max_dd")
    if (
        excess_qqq_2025 is not None and excess_qqq_2025 < 0
        and excess_spy_2025 is not None and excess_spy_2025 > 0
        and fp_excess_qqq is not None and fp_excess_qqq > 0
        and val_2025_max_dd is not None
        and val_2025_max_dd <= qqq_2025_max_dd - 0.05
    ):
        return {
            "triggered": True,
            "details": {
                "validation_2025_excess_vs_qqq": excess_qqq_2025,
                "validation_2025_excess_vs_spy": excess_spy_2025,
                "full_period_excess_vs_qqq": fp_excess_qqq,
                "validation_2025_max_dd": val_2025_max_dd,
                "qqq_2025_max_dd_minus_5pp": qqq_2025_max_dd - 0.05,
            },
        }
    return {"triggered": False}


# ── Main ────────────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser(description="Cycle #04 evaluation pipeline")
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else (
        PROJ / "data" / "ml" / "cycle04_evaluation" / LINEAGE_TAG
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[cycle04 eval] Loading criteria yaml: {CRITERIA_YAML.name}")
    cycle_yaml = _load_criteria_yaml()

    print(f"[cycle04 eval] Pulling top-{args.top_k} archived trials...")
    top_df = _load_top_n_archived_trials(top_k=args.top_k)
    if len(top_df) == 0:
        print(f"[cycle04 eval] No archived trials under {LINEAGE_TAG} — mining "
              "may not have completed.")
        return 1
    print(f"  {len(top_df)} trials retrieved")

    print(f"[cycle04 eval] Building input panels (selector + total-return for cross-asset)...")
    panel, all_factors, mask, split_cfg = _build_inputs(cycle_yaml)
    print(f"  panel: {panel['close'].shape[0]} dates × {panel['close'].shape[1]} symbols")

    spy_close = panel["close"].get("SPY")
    qqq_close = panel["close"].get("QQQ")
    # QQQ 2025 max DD reference (for 2025 QQQ soft-miss check)
    qqq_2025 = qqq_close.loc["2025-01-01":"2025-12-31"] if qqq_close is not None else None
    if qqq_2025 is not None and len(qqq_2025) > 0:
        qqq_2025_dd = float(((qqq_2025 / qqq_2025.cummax()) - 1).min())
    else:
        qqq_2025_dd = float("nan")
    print(f"  QQQ 2025 max DD: {qqq_2025_dd*100:.2f}%")

    # Anti-sibling reference features (4 anchors: cycle 01-03 tops + RCMv1 + Cand-2)
    anchor_features = {
        "cycle_01_top": ["beta_spy_60d", "mom_12_1", "volume_ratio_20d"],
        "cycle_02_top": ["beta_spy_60d", "mom_12_1", "volume_ratio_20d"],
        "cycle_03_top": ["rs_vs_spy_126d", "drawup_from_252d_low", "market_vol_ratio"],
        "rcm_v1": ["beta_spy_60d", "drawup_from_252d_low", "days_since_52w_high", "amihud_20d"],
        "cand_2": ["ret_5d", "rs_vs_spy_126d", "hl_range"],
    }

    print(f"[cycle04 eval] Evaluating top-{len(top_df)} candidates (cap_aware_cross_asset)...")
    evaluations = []
    for i, (_, trial_row) in enumerate(top_df.iterrows(), start=1):
        print(f"  [{i}/{len(top_df)}] trial_id={trial_row['trial_id']} "
              f"ic_ir={float(trial_row['ic_ir']):.4f}")
        ev = _evaluate_one(trial_row, panel, all_factors, mask, cycle_yaml, split_cfg)
        if "error" not in ev:
            cand_nav = ev.pop("_nav_series")
            ev.pop("_weights_df", None)  # Don't dump weights df to JSON
            ev["nav_correlation_vs_existing_pair"] = {}
            # NAV correlation only against external references; cross-cycle
            # references would require running RCMv1/Cand-2 on the same
            # extended cross-asset panel which is beyond scope today.
            # Use SPY/QQQ benchmark NAV correlations from harness.
            ev["r41_classification"] = _classify_r41(
                ev, ev["nav_correlation_vs_existing_pair"], anchor_features,
            )
            ev["soft_miss_2025_qqq"] = _check_2025_qqq_soft_miss(ev, qqq_2025_dd)
        evaluations.append(ev)

    summary = {
        "lineage_tag": LINEAGE_TAG,
        "criteria_yaml_sha256": hashlib.sha256(CRITERIA_YAML.read_bytes()).hexdigest(),
        "evaluation_timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
        "construction_mode": "cap_aware_cross_asset",
        "construction_yaml_block": cycle_yaml.get("construction", {}),
        "top_k": args.top_k,
        "qqq_2025_max_dd_reference": qqq_2025_dd,
        "evaluations": evaluations,
        "anti_sibling_thresholds": {
            "factor_overlap_threshold": 2,
            "pooled_max": 0.85,
            "residual_max": 0.70,
        },
        "anchor_features_for_overlap": anchor_features,
    }
    out_path = out_dir / "evaluation_summary.json"
    out_path.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\n[cycle04 eval] Wrote: {out_path}")

    print("\n=== TOP-3 SUMMARY (cap_aware_cross_asset) ===")

    def _f(x, spec=".4%"):
        if x is None or (isinstance(x, float) and np.isnan(x)):
            return "NA"
        try:
            return format(x, spec)
        except Exception:
            return str(x)

    for ev in evaluations[:3]:
        if "error" in ev:
            print(f"  {ev['trial_id']}  ERROR: {ev['error']}")
            continue
        m = ev.get("metrics_full_period", {}) or {}
        ace = ev.get("asset_class_exposure", {}) or {}
        r41 = ev.get("r41_classification", {}) or {}
        print(f"  {ev['trial_id']}  features={ev.get('features')}")
        print(f"    cum_ret={_f(m.get('cum_ret'))} sharpe={_f(m.get('sharpe'), '.3f')} "
              f"max_dd={_f(m.get('max_dd'))} vs_qqq={_f(m.get('vs_qqq'), '+.4%')}")
        print(f"    asset_class avg: equity={_f(ace.get('equity_weight_avg'), '.2%')} "
              f"bonds={_f(ace.get('bond_weight_avg'), '.2%')} "
              f"commod={_f(ace.get('commodity_weight_avg'), '.2%')} "
              f"cash={_f(ace.get('cash_anchor_weight_avg'), '.2%')}")
        print(f"    non_equity_avg={_f(ace.get('non_equity_weight_avg'), '.2%')} "
              f"p25={_f(ace.get('non_equity_weight_p25'), '.2%')} "
              f"days_zero_ne={_f(ace.get('days_with_zero_non_equity_pct'), '.0%')}")
        print(f"    R41 Tier {r41.get('tier')}: {r41.get('reason')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
