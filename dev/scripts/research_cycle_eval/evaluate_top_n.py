"""Generic research-cycle evaluation pipeline.

Replaces cycle04-specific `dev/scripts/cycle04/evaluate_cycle04_top_n.py` +
post-eval `cross_cycle_nav_correlation.py` with a single yaml-driven script.

Reads any cycle yaml (--yaml-path), dispatches construction mode based on
``cycle_yaml.construction.mode`` (cap_aware_cross_asset / cap_aware /
global_top_n), folds cross-cycle NAV correlation INLINE into main flow,
calls ``anti_sibling_policy.classify`` for R41 v2 verdict in one step.

Output: single ``evaluation_summary.json`` with populated
``nav_correlation_vs_existing_pair`` + ``r41_classification`` per trial.

Cycle history pipeline lessons folded:
- Cycle #04 v1: nav_correlation_vs_existing_pair was empty + R41 v1 reported
  5 false-positive Tier 1; required post-eval patch via cross_cycle_nav_
  correlation.py. This script removes that gap.
- Cycle #04 v2: post-eval R41 was binary (1/2/5) factor-overlap-only.
  This script replaces with anti_sibling_policy.classify (5-tier including
  Tier 1-conditional with PRE-REGISTERED 4-condition gate).

Usage:
    python dev/scripts/research_cycle_eval/evaluate_top_n.py \\
        --yaml-path data/research_candidates/<lineage>_promotion_criteria.yaml \\
        [--top-k 10] [--out-dir <dir>]

Anchor features (built-in defaults; can be overridden via yaml):
- cycle_01_top, cycle_02_top, cycle_03_top: prior-cycle top-1 specs
- rcm_v1: legacy RCMv1
- cand_2: legacy Cand-2

Anchor MaxDD lookup (for conditional review c3):
- Computed inline by running each anchor spec via global_top_n harness
  on the same panel (apples-to-apples).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import numpy as np
import pandas as pd
import yaml


PROJ = Path("/home/zibo/Documents/projects/pqs")
sys.path.insert(0, str(PROJ))


# ── Anchor specs (single source of truth for cross-cycle reference NAVs) ──


ANCHOR_SPECS: Dict[str, Dict[str, Any]] = {
    "rcm_v1": {
        "features": ("beta_spy_60d", "drawup_from_252d_low",
                     "days_since_52w_high", "amihud_20d"),
        "weights": (0.186, 0.302, 0.395, 0.117),
        "family_counts": {"A": 1, "B": 2, "C": 1},
    },
    "cand_2": {
        "features": ("ret_5d", "rs_vs_spy_126d", "hl_range"),
        "weights": (1 / 3, 1 / 3, 1 / 3),
        "family_counts": {"E": 1, "F": 1, "D": 1},
    },
    "cycle_03_top": {
        "features": ("rs_vs_spy_126d", "drawup_from_252d_low",
                     "market_vol_ratio"),
        "weights": (1 / 3, 1 / 3, 1 / 3),
        "family_counts": {"E": 1, "B": 1, "C": 1},
    },
    # cycle_01_top + cycle_02_top share the same composite (verified 2026-04-30)
    "cycle_01_top": {
        "features": ("beta_spy_60d", "mom_12_1", "volume_ratio_20d"),
        "weights": (1 / 3, 1 / 3, 1 / 3),
        "family_counts": {"A": 1, "B": 1, "C": 1},
    },
    "cycle_02_top": {
        "features": ("beta_spy_60d", "mom_12_1", "volume_ratio_20d"),
        "weights": (1 / 3, 1 / 3, 1 / 3),
        "family_counts": {"A": 1, "B": 1, "C": 1},
    },
}


def _normalize_weights(weights: Tuple[float, ...]) -> Tuple[float, ...]:
    s = sum(weights)
    if s <= 0:
        return weights
    return tuple(w / s for w in weights)


# ── Yaml-driven loaders ─────────────────────────────────────────────────


def _load_yaml(yaml_path: Path) -> Dict[str, Any]:
    return yaml.safe_load(yaml_path.read_text())


def _yaml_lineage_tag(cycle_yaml: Dict[str, Any]) -> str:
    tag = cycle_yaml.get("lineage_tag")
    if not tag:
        raise ValueError("yaml missing required field: lineage_tag")
    return str(tag)


def _yaml_construction_mode(cycle_yaml: Dict[str, Any]) -> str:
    mode = cycle_yaml.get("construction", {}).get("mode")
    if not mode:
        raise ValueError("yaml missing required field: construction.mode")
    if mode not in ("global_top_n", "cap_aware", "cap_aware_cross_asset"):
        raise ValueError(f"unsupported construction.mode={mode!r}")
    return str(mode)


def _yaml_top_k(cycle_yaml: Dict[str, Any], cli_top_k: int) -> int:
    return int(cli_top_k)


def _load_top_n_archived_trials(
    lineage_tag: str, top_k: int = 10,
    archive_db: str = "data/mining/rcm_archive.db",
) -> pd.DataFrame:
    con = sqlite3.connect(str(PROJ / archive_db))
    df = pd.read_sql(
        "SELECT trial_id, ic_ir, features_csv, weights_csv, "
        "family_counts_json, ic_mean, ic_std, turnover_proxy, "
        "corr_concentration, n_dates, objective "
        "FROM rcm_trials WHERE lineage_tag = ? "
        "ORDER BY ic_ir DESC LIMIT ?",
        con, params=(lineage_tag, top_k),
    )
    con.close()
    return df


# ── Panel builder (handles total-return for cross-asset symbols) ────────


def _build_inputs(cycle_yaml: Dict[str, Any]):
    from core.config.loader import load_config
    from core.data.bar_store import BarStore
    from core.factors.factor_generator import generate_all_factors
    from core.factors.base_masks import research_mask_default
    from core.research.temporal_split import (
        load_temporal_split, partition_for_role,
    )
    from core.research.risk_cluster_map import CROSS_ASSET_RISK_CLUSTER_MAP

    cfg = load_config(PROJ / "config")
    store = BarStore(root=Path(cfg.system.paths.data_dir))

    uni = cfg.universe
    syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs)
        + list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    drop_set = set(cycle_yaml.get("drop_symbols", []))
    syms = [s for s in syms if s not in uni.blacklist
            and s not in uni.macro_reference and s not in drop_set]
    for b in ("SPY", "QQQ"):
        if b not in syms:
            syms.append(b)

    cross_asset_set = set(CROSS_ASSET_RISK_CLUSTER_MAP.keys())
    construction_mode = _yaml_construction_mode(cycle_yaml)
    use_total_return = construction_mode == "cap_aware_cross_asset"

    frames = {k: {} for k in ("close", "open", "high", "low", "volume")}
    for sym in syms:
        atr = use_total_return and (sym in cross_asset_set)
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
        b: panel["close"][b] for b in ("SPY", "QQQ")
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


# ── Harness config dispatch (yaml.construction.mode aware) ──────────────


def _build_harness_config_for_cycle(
    cycle_yaml: Dict[str, Any], horizon_days: int,
):
    from core.research.harness import HarnessConfig
    from core.research.risk_cluster_map import (
        ASSET_CLASS_BY_CLUSTER, STOCK_RISK_CLUSTER_MAP, make_unified_cluster_map,
    )

    construction = cycle_yaml.get("construction", {})
    mode = _yaml_construction_mode(cycle_yaml)
    top_n = int(construction.get("top_n", 10))
    cadence = construction.get("rebalance_cadence", "monthly")

    base = dict(
        construction_mode=mode,
        rebalance_cadence=cadence,
        top_n=top_n,
        horizon_days=horizon_days,
    )

    if mode == "global_top_n":
        return HarnessConfig(**base)

    if mode == "cap_aware":
        return HarnessConfig(
            **base,
            cluster_map=dict(STOCK_RISK_CLUSTER_MAP),
            cluster_cap=float(construction.get("cluster_cap", 0.20)),
            max_single_weight=float(construction.get("max_single_weight", 0.10)),
        )

    if mode == "cap_aware_cross_asset":
        unified_cluster_map = make_unified_cluster_map(include_cross_asset=True)
        asset_class_map = {
            sym: ASSET_CLASS_BY_CLUSTER[cluster]
            for sym, cluster in unified_cluster_map.items()
        }
        caps = construction.get("asset_class_caps", {})
        asset_class_caps = {
            "equities":     float(caps.get("equities_max", 0.70)),
            "bonds":        float(caps.get("bonds_max", 0.40)),
            "commodities":  float(caps.get("commodities_max", 0.20)),
            "cash_anchor":  float(caps.get("cash_anchor_max", 0.30)),
        }
        return HarnessConfig(
            **base,
            cluster_map=unified_cluster_map,
            cluster_cap=float(construction.get("cluster_cap", 0.20)),
            max_single_weight=float(construction.get("max_single_weight", 0.10)),
            asset_class_map=asset_class_map,
            asset_class_caps=asset_class_caps,
        )

    raise ValueError(f"unhandled mode: {mode}")


# ── Per-trial evaluation ────────────────────────────────────────────────


def _evaluate_one(
    trial_row: pd.Series,
    panel: Dict[str, pd.DataFrame],
    all_factors: Dict[str, pd.DataFrame],
    research_mask,
    cycle_yaml: Dict[str, Any],
    split_cfg,
) -> Dict[str, Any]:
    from core.mining.research_miner import ResearchCompositeSpec
    from core.research.harness import evaluate_composite_spec

    feats = trial_row["features_csv"].split(",")
    weights = [float(w) for w in trial_row["weights_csv"].split(",")]
    family_counts = json.loads(trial_row["family_counts_json"])

    weights = list(_normalize_weights(tuple(weights)))
    residual = 1.0 - sum(weights)
    if abs(residual) > 1e-12:
        mi = max(range(len(weights)), key=lambda i: weights[i])
        weights[mi] += residual

    spec = ResearchCompositeSpec(
        features=tuple(feats), weights=tuple(weights),
        family_counts=family_counts,
    )
    panel_map = {f: all_factors[f] for f in feats if f in all_factors}
    if len(panel_map) != len(feats):
        missing = [f for f in feats if f not in panel_map]
        return {"trial_id": trial_row["trial_id"],
                "error": f"missing factors: {missing}"}

    horizon_days = int(cycle_yaml.get("hard_requirements", {}).get(
        "fwd_return_horizon_days", 21,
    ))
    cfg_h = _build_harness_config_for_cycle(cycle_yaml, horizon_days)

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

    out: Dict[str, Any] = {
        "trial_id": trial_row["trial_id"],
        "construction_mode": cfg_h.construction_mode,
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
        "_nav_series": res.nav,
        "_weights_df": res.weights,
    }

    # Mode-specific diagnostics
    if cfg_h.construction_mode in ("cap_aware", "cap_aware_cross_asset"):
        out["cluster_diversity"] = _compute_cluster_diversity(
            res.weights, cfg_h.cluster_map, top_n=cfg_h.top_n,
        )
    if cfg_h.construction_mode == "cap_aware_cross_asset":
        out["asset_class_exposure"] = _compute_asset_class_exposure(
            res.weights, cfg_h.asset_class_map,
        )

    return out


# ── Diagnostics (cap_aware_cross_asset specific) ────────────────────────


def _compute_asset_class_exposure(
    weights_df: pd.DataFrame, asset_class_map: Dict[str, str],
) -> Dict[str, Any]:
    rows = []
    non_equity_pct = []
    for date, row in weights_df.iterrows():
        nz = row[row > 1e-6]
        if len(nz) == 0:
            continue
        ac_w = defaultdict(float)
        for sym, w in nz.items():
            ac_w[asset_class_map.get(sym, "unmapped")] += float(w)
        non_eq = (ac_w.get("bonds", 0) + ac_w.get("commodities", 0)
                  + ac_w.get("cash_anchor", 0))
        non_equity_pct.append(non_eq)
        rows.append({
            "equity_weight": ac_w.get("equities", 0.0),
            "bond_weight": ac_w.get("bonds", 0.0),
            "commodity_weight": ac_w.get("commodities", 0.0),
            "cash_anchor_weight": ac_w.get("cash_anchor", 0.0),
            "non_equity_weight": non_eq,
        })

    if not rows:
        return {k: 0.0 for k in (
            "equity_weight_avg", "bond_weight_avg", "commodity_weight_avg",
            "cash_anchor_weight_avg", "non_equity_weight_avg",
            "non_equity_weight_p25", "non_equity_weight_p50",
            "non_equity_weight_p75", "non_equity_weight_min",
            "non_equity_weight_max", "days_with_zero_non_equity_pct",
        )}

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


def _compute_cluster_diversity(
    weights_df: pd.DataFrame, cluster_map: Dict[str, str], top_n: int = 10,
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
        c: cluster_total_weight[c] / cluster_count[c] for c in cluster_total_weight
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


# ── Reference NAV builder (for cross-cycle correlation) ─────────────────


def _build_reference_nav(
    spec_name: str, panel: Dict[str, pd.DataFrame],
    all_factors: Dict[str, pd.DataFrame], research_mask, horizon_days: int,
) -> Tuple[Optional[pd.Series], Optional[float]]:
    """Build NAV + max_dd for an anchor spec via global_top_n harness on
    the SAME panel. Returns (nav, max_dd) or (None, None) if any anchor
    factor is missing from the panel."""
    from core.mining.research_miner import ResearchCompositeSpec
    from core.research.harness import HarnessConfig, evaluate_composite_spec

    spec_def = ANCHOR_SPECS.get(spec_name)
    if spec_def is None:
        return None, None
    feats = spec_def["features"]
    weights = _normalize_weights(spec_def["weights"])
    family_counts = spec_def["family_counts"]

    panel_map = {f: all_factors[f] for f in feats if f in all_factors}
    if len(panel_map) != len(feats):
        return None, None

    cfg_g = HarnessConfig(
        construction_mode="global_top_n", rebalance_cadence="monthly",
        top_n=10, horizon_days=horizon_days,
    )
    spy = panel["close"].get("SPY")
    qqq = panel["close"].get("QQQ")
    try:
        r = evaluate_composite_spec(
            spec=ResearchCompositeSpec(
                features=tuple(feats), weights=tuple(weights),
                family_counts=family_counts,
            ),
            factor_panel_map=panel_map, price_df=panel["close"],
            open_df=panel["open"], spy_series=spy, qqq_series=qqq,
            config=cfg_g, research_mask=research_mask,
        )
    except Exception as exc:
        print(f"  ✗ {spec_name} NAV failed: {exc}")
        return None, None

    max_dd = None
    if r.metrics_full_period and "max_dd" in r.metrics_full_period:
        max_dd = float(r.metrics_full_period["max_dd"])
    return r.nav, max_dd


# ── Cross-cycle correlation ─────────────────────────────────────────────


def _residual_pair_corr(
    a: pd.Series, b: pd.Series, bench: pd.Series,
) -> float:
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
    spy_close: pd.Series, qqq_close: pd.Series,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    cand_ret = candidate_nav.pct_change().dropna()
    spy_ret = spy_close.pct_change().reindex(cand_ret.index).dropna()
    qqq_ret = qqq_close.pct_change().reindex(cand_ret.index).dropna()
    common = cand_ret.index.intersection(spy_ret.index).intersection(qqq_ret.index)
    cand_ret = cand_ret.reindex(common)
    spy_ret = spy_ret.reindex(common)
    qqq_ret = qqq_ret.reindex(common)

    for name, ref_nav in reference_navs.items():
        if ref_nav is None:
            for suffix in ("raw", "residual_vs_spy", "residual_vs_qqq"):
                out[f"{name}_pooled_pearson_{suffix}"] = None
            out[f"{name}_n_overlap_days"] = 0
            continue
        ref_ret = ref_nav.pct_change().reindex(common).dropna()
        c2 = common.intersection(ref_ret.index)
        if len(c2) < 30:
            for suffix in ("raw", "residual_vs_spy", "residual_vs_qqq"):
                out[f"{name}_pooled_pearson_{suffix}"] = None
            out[f"{name}_n_overlap_days"] = int(len(c2))
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


# ── 2025 QQQ soft-miss check (preserved from cycle04) ───────────────────


def _check_2025_qqq_soft_miss(
    evaluation: Dict[str, Any], qqq_2025_max_dd: float,
) -> Dict[str, Any]:
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


# ── Anchor features registry ────────────────────────────────────────────


def _anchor_features_for_classifier() -> Dict[str, List[str]]:
    """Return {anchor_name: [factor_names]} for R41 factor-overlap check.
    Single source of truth from ANCHOR_SPECS."""
    return {name: list(spec["features"]) for name, spec in ANCHOR_SPECS.items()}


# ── Main ────────────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser(
        description="Generic research-cycle evaluation pipeline",
    )
    ap.add_argument("--yaml-path", required=True,
                    help="path to <lineage>_promotion_criteria.yaml")
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--out-dir", default=None,
                    help="default: data/ml/research_cycle_eval/<lineage>/")
    ap.add_argument("--lineage-override", default=None,
                    help="Override yaml.lineage_tag for archive query. Use for "
                         "smoke runs where mining lineage differs from yaml "
                         "(e.g. <lineage>-smoke). Construction + thresholds "
                         "still come from yaml.")
    args = ap.parse_args()

    yaml_path = Path(args.yaml_path)
    if not yaml_path.is_absolute():
        yaml_path = (Path.cwd() / yaml_path).resolve()
    if not yaml_path.exists():
        raise SystemExit(f"yaml not found: {yaml_path}")

    print(f"[eval] Loading yaml: {yaml_path.name}")
    cycle_yaml = _load_yaml(yaml_path)
    lineage_tag = _yaml_lineage_tag(cycle_yaml)
    construction_mode = _yaml_construction_mode(cycle_yaml)
    print(f"  lineage_tag = {lineage_tag}")
    print(f"  construction_mode = {construction_mode}")

    # Anti-sibling policy version gating (cycle #05+ yamls declare it;
    # cycle #04 doesn't — emit informational note instead of raising)
    from core.research.anti_sibling_policy import (
        POLICY_VERSION, assert_policy_version_matches, classify,
    )
    yaml_policy_version = cycle_yaml.get("anti_sibling_policy_version")
    if yaml_policy_version:
        assert_policy_version_matches(yaml_policy_version)
        print(f"  anti_sibling_policy_version = {yaml_policy_version} (matches module)")
    else:
        print(f"  [info] yaml lacks anti_sibling_policy_version field; using "
              f"module POLICY_VERSION={POLICY_VERSION} (cycle #04 backwards-compat)")

    out_dir = Path(args.out_dir) if args.out_dir else (
        PROJ / "data" / "ml" / "research_cycle_eval" / lineage_tag
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[eval] Pulling top-{args.top_k} archived trials for {lineage_tag}...")
    top_df = _load_top_n_archived_trials(lineage_tag=lineage_tag, top_k=args.top_k)
    if len(top_df) == 0:
        print(f"  no archived trials under {lineage_tag} — mining may not have "
              "completed.")
        return 1
    print(f"  {len(top_df)} trials retrieved")

    print(f"[eval] Building input panels (selector role)...")
    panel, all_factors, mask, split_cfg = _build_inputs(cycle_yaml)
    print(f"  panel: {panel['close'].shape[0]} dates × "
          f"{panel['close'].shape[1]} symbols")

    spy_close = panel["close"].get("SPY")
    qqq_close = panel["close"].get("QQQ")
    qqq_2025 = (qqq_close.loc["2025-01-01":"2025-12-31"]
                if qqq_close is not None else None)
    if qqq_2025 is not None and len(qqq_2025) > 0:
        qqq_2025_dd = float(((qqq_2025 / qqq_2025.cummax()) - 1).min())
    else:
        qqq_2025_dd = float("nan")
    print(f"  QQQ 2025 max DD = {qqq_2025_dd*100:.2f}%")

    horizon_days = int(cycle_yaml.get("hard_requirements", {}).get(
        "fwd_return_horizon_days", 21,
    ))

    # ── Step 1: build reference NAVs (anchor specs on same panel) ──
    print(f"[eval] Building reference anchor NAVs (global_top_n) "
          f"on {len(panel['close'].columns)}-symbol panel...")
    reference_navs: Dict[str, pd.Series] = {}
    anchor_max_dd_lookup: Dict[str, float] = {}
    for anchor_name in ANCHOR_SPECS.keys():
        nav, mdd = _build_reference_nav(
            anchor_name, panel, all_factors, mask, horizon_days,
        )
        if nav is not None:
            reference_navs[anchor_name] = nav
            if mdd is not None:
                anchor_max_dd_lookup[anchor_name] = mdd
                print(f"  ✓ {anchor_name} NAV (n={len(nav)}, max_dd={mdd*100:.2f}%)")
            else:
                print(f"  ✓ {anchor_name} NAV (max_dd missing)")
        else:
            print(f"  - {anchor_name} skipped (factor missing or harness failed)")

    anchor_features = _anchor_features_for_classifier()

    # ── Step 2: evaluate top trials + cross-cycle correlation + R41 ──
    print(f"[eval] Evaluating top-{len(top_df)} trials "
          f"(construction_mode={construction_mode})...")
    evaluations: List[Dict[str, Any]] = []
    for i, (_, trial_row) in enumerate(top_df.iterrows(), start=1):
        print(f"  [{i}/{len(top_df)}] trial_id={trial_row['trial_id']} "
              f"ic_ir={float(trial_row['ic_ir']):.4f}")
        ev = _evaluate_one(trial_row, panel, all_factors, mask, cycle_yaml, split_cfg)
        if "error" in ev:
            evaluations.append(ev)
            continue

        cand_nav = ev.pop("_nav_series")
        ev.pop("_weights_df", None)

        # FOLD: cross-cycle NAV correlation inline
        nc = _compute_cross_cycle_correlations(
            cand_nav, reference_navs, spy_close, qqq_close,
        )
        ev["nav_correlation_vs_existing_pair"] = nc

        # R41 v2 verdict via anti_sibling_policy module
        metrics_2025 = ev.get("metrics_per_validation_year", {}).get(2025)
        r41 = classify(
            candidate_features=ev.get("features", []),
            anchor_features=anchor_features,
            nav_correlation=nc,
            candidate_metrics_full_period=ev.get("metrics_full_period", {}),
            candidate_metrics_2025=metrics_2025,
            anchor_max_dd_lookup=anchor_max_dd_lookup,
        )
        ev["r41_classification"] = r41.to_dict()

        # 2025 QQQ soft-miss
        ev["soft_miss_2025_qqq"] = _check_2025_qqq_soft_miss(ev, qqq_2025_dd)
        evaluations.append(ev)

    # ── Output ──
    summary = {
        "lineage_tag": lineage_tag,
        "yaml_path": str(yaml_path),
        "yaml_sha256": hashlib.sha256(yaml_path.read_bytes()).hexdigest(),
        "evaluation_timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
        "construction_mode": construction_mode,
        "construction_yaml_block": cycle_yaml.get("construction", {}),
        "anti_sibling_policy_version": POLICY_VERSION,
        "anchor_features_for_overlap": anchor_features,
        "anchor_max_dd_lookup": anchor_max_dd_lookup,
        "top_k": args.top_k,
        "qqq_2025_max_dd_reference": qqq_2025_dd,
        "evaluations": evaluations,
    }
    out_path = out_dir / "evaluation_summary.json"
    out_path.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\n[eval] Wrote: {out_path}")

    # ── Top-3 console summary ──
    print("\n=== TOP-3 SUMMARY ===")

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
        r41 = ev.get("r41_classification", {}) or {}
        print(f"  {ev['trial_id']}  features={ev.get('features')}")
        print(f"    cum_ret={_f(m.get('cum_ret'))} sharpe={_f(m.get('sharpe'), '.3f')} "
              f"max_dd={_f(m.get('max_dd'))} vs_qqq={_f(m.get('vs_qqq'), '+.4%')}")
        print(f"    R41 Tier {r41.get('tier')}: {r41.get('reason')}")

    # Tier distribution
    tiers: Dict[str, int] = {}
    for ev in evaluations:
        if "error" in ev:
            tiers["error"] = tiers.get("error", 0) + 1
        else:
            t = str(ev.get("r41_classification", {}).get("tier", "?"))
            tiers[t] = tiers.get(t, 0) + 1
    print(f"\nTier distribution: {sorted(tiers.items())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
