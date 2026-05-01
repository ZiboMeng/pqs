"""Cycle #03 evaluation pipeline.

Per cycle #03 yaml (track-c-cycle-2026-05-01-02) report_only requirements:
- Top-K archived trial NAV diagnostics under cap-aware construction
- Cluster diversity census (n_clusters_per_rebal_avg, cluster_concentration_max,
  implicit_cash_pct_avg, top-3 clusters by avg weight)
- Cross-cycle NAV correlation vs RCMv1 + Cand-2 (raw pooled Pearson +
  residual after stripping SPY+QQQ beta)
- R41 5-tier classification per top trial

Inputs read at runtime:
- Cycle #03 archive trials from rcm_archive.db (lineage track-c-cycle-2026-05-01-02)
- Production prices via BarStore (post-canonical-rebuild data)
- Temporal split (selector role → train+validation visibility)
- RCMv1 + Cand-2 frozen specs from data/research_candidates/

Output: data/ml/cycle03_evaluation/<lineage>/evaluation_summary.json

Decision authority: tactical (operator); user direction "根据你的经验选最优路径
然后开工" 2026-05-01 covers cycle #03 closeout pipeline.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yaml


PROJ = Path("/home/zibo/Documents/projects/pqs")
LINEAGE_TAG = "track-c-cycle-2026-05-01-02"
CRITERIA_YAML = (
    PROJ / "data" / "research_candidates"
    / f"{LINEAGE_TAG}_promotion_criteria.yaml"
)


# ── Loaders ──────────────────────────────────────────────────────────────────


def _load_criteria_yaml() -> Dict[str, Any]:
    return yaml.safe_load(CRITERIA_YAML.read_text())


def _load_top_n_archived_trials(top_k: int = 10) -> pd.DataFrame:
    con = sqlite3.connect(str(PROJ / "data" / "mining" / "rcm_archive.db"))
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


def _build_inputs():
    """Build factor_panel_map + price_df + benchmark series + research_mask
    over the train+validation panel (selector role visibility per
    PRD-isolation audit fix 2026-05-01)."""
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

    cfg = load_config(PROJ / "config")
    store = BarStore(root=Path(cfg.system.paths.data_dir))

    uni = cfg.universe
    syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs)
        + list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    syms = [s for s in syms if s not in uni.blacklist
            and s not in uni.macro_reference and s != "BRK-B"]
    for b in ("SPY", "QQQ"):
        if b not in syms:
            syms.append(b)

    frames = {k: {} for k in ("close", "open", "high", "low", "volume")}
    for sym in syms:
        df = store.load(sym, freq="1d", adjusted=True, fallback="local")
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
    # SELECTOR role: train + validation visible. Sealed (2026) NEVER read.
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


# ── Per-trial harness eval (cap_aware mode) ──────────────────────────────────


def _evaluate_one(
    trial_row: pd.Series,
    panel: Dict[str, pd.DataFrame],
    all_factors: Dict[str, pd.DataFrame],
    research_mask,
    cycle_yaml: Dict[str, Any],
    split_cfg,
    construction_mode: str = "cap_aware",
) -> Dict[str, Any]:
    """Run one trial through harness with cap_aware construction."""
    import sys
    sys.path.insert(0, str(PROJ))
    from core.mining.research_miner import ResearchCompositeSpec
    from core.research.harness import HarnessConfig, evaluate_composite_spec
    from core.research.risk_cluster_map import STOCK_RISK_CLUSTER_MAP

    feats = trial_row["features_csv"].split(",")
    weights = [float(w) for w in trial_row["weights_csv"].split(",")]
    family_counts = json.loads(trial_row["family_counts_json"])

    # Renormalize for archive 6-decimal precision (1/3 → 0.333333 → sum=0.999999)
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
    if construction_mode == "cap_aware":
        cfg_h = HarnessConfig(
            construction_mode="cap_aware",
            rebalance_cadence=construction.get("rebalance_cadence", "monthly"),
            top_n=int(construction.get("top_n", 10)),
            cluster_map=STOCK_RISK_CLUSTER_MAP,
            cluster_cap=float(construction.get("cluster_cap", 0.20)),
            max_single_weight=float(construction.get("max_single_weight", 0.10)),
            horizon_days=int(cycle_yaml["hard_requirements"].get("fwd_return_horizon_days", 21)),
        )
    else:
        cfg_h = HarnessConfig(
            construction_mode="global_top_n",
            rebalance_cadence=construction.get("rebalance_cadence", "monthly"),
            top_n=int(construction.get("top_n", 10)),
            horizon_days=int(cycle_yaml["hard_requirements"].get("fwd_return_horizon_days", 21)),
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

    # Cluster diversity census
    cluster_diversity = _compute_cluster_diversity(
        res.weights, STOCK_RISK_CLUSTER_MAP, top_n=int(construction.get("top_n", 10)),
    )

    return {
        "trial_id": trial_row["trial_id"],
        "construction_mode": construction_mode,
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
        "cluster_diversity": cluster_diversity,
        "_nav_series": res.nav,  # internal — will be popped before json dump
    }


# ── Cluster diversity census ─────────────────────────────────────────────────


def _compute_cluster_diversity(
    weights_df: pd.DataFrame,
    cluster_map: Dict[str, str],
    top_n: int = 10,
) -> Dict[str, Any]:
    """Census per yaml report_only.cluster_diversity."""
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
        # Aggregate to cluster
        cluster_w = defaultdict(float)
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


# ── Cross-cycle NAV correlation (vs RCMv1 + Cand-2) ──────────────────────────


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


def _build_reference_navs(
    panel: Dict[str, pd.DataFrame],
    all_factors: Dict[str, pd.DataFrame],
    research_mask,
    split_cfg,
) -> Dict[str, pd.Series]:
    """Run RCMv1 + Cand-2 specs through harness on canonical post-rebuild
    data. Construction = global_top_n top_n=10 (their original config)."""
    import sys
    sys.path.insert(0, str(PROJ))
    from core.mining.research_miner import ResearchCompositeSpec
    from core.research.harness import HarnessConfig, evaluate_composite_spec

    refs = {}

    # RCMv1: 4 factors, weighted (per data/research_candidates/rcm_v1...)
    rcm_feats = ["beta_spy_60d", "drawup_from_252d_low", "days_since_52w_high", "amihud_20d"]
    rcm_weights = (0.186, 0.302, 0.395, 0.117)
    # Renormalize floor-noise
    s = sum(rcm_weights); rcm_weights = tuple(w / s for w in rcm_weights)
    res_floor = 1.0 - sum(rcm_weights)
    if abs(res_floor) > 0:
        ws = list(rcm_weights)
        ws[max(range(len(ws)), key=lambda i: ws[i])] += res_floor
        rcm_weights = tuple(ws)
    rcm_spec = ResearchCompositeSpec(
        features=tuple(rcm_feats), weights=rcm_weights,
        family_counts={"A": 1, "B": 2, "C": 1},
    )
    rcm_panel = {f: all_factors[f] for f in rcm_feats if f in all_factors}
    if len(rcm_panel) == len(rcm_feats):
        cfg_g = HarnessConfig(
            construction_mode="global_top_n", rebalance_cadence="monthly",
            top_n=10, horizon_days=21,
        )
        try:
            r = evaluate_composite_spec(
                spec=rcm_spec, factor_panel_map=rcm_panel,
                price_df=panel["close"], open_df=panel["open"],
                spy_series=panel["close"].get("SPY"), qqq_series=panel["close"].get("QQQ"),
                config=cfg_g, research_mask=research_mask,
            )
            refs["rcm_v1"] = r.nav
        except Exception as exc:
            print(f"  WARN: RCMv1 reference NAV failed: {exc}")

    # Cand-2: 3 factors equal-weight (per data/research_candidates/candidate_2...)
    c2_feats = ["ret_5d", "rs_vs_spy_126d", "hl_range"]
    c2_weights = (1/3, 1/3, 1/3)
    s = sum(c2_weights); c2_weights = tuple(w / s for w in c2_weights)
    res_floor = 1.0 - sum(c2_weights)
    if abs(res_floor) > 0:
        ws = list(c2_weights)
        ws[max(range(len(ws)), key=lambda i: ws[i])] += res_floor
        c2_weights = tuple(ws)
    c2_spec = ResearchCompositeSpec(
        features=tuple(c2_feats), weights=c2_weights,
        family_counts={"E": 1, "F": 1, "D": 1},
    )
    c2_panel = {f: all_factors[f] for f in c2_feats if f in all_factors}
    if len(c2_panel) == len(c2_feats):
        cfg_g = HarnessConfig(
            construction_mode="global_top_n", rebalance_cadence="monthly",
            top_n=10, horizon_days=21,
        )
        try:
            r = evaluate_composite_spec(
                spec=c2_spec, factor_panel_map=c2_panel,
                price_df=panel["close"], open_df=panel["open"],
                spy_series=panel["close"].get("SPY"), qqq_series=panel["close"].get("QQQ"),
                config=cfg_g, research_mask=research_mask,
            )
            refs["cand_2"] = r.nav
        except Exception as exc:
            print(f"  WARN: Cand-2 reference NAV failed: {exc}")

    return refs


def _compute_cross_cycle_correlations(
    candidate_nav: pd.Series,
    reference_navs: Dict[str, pd.Series],
    spy_close: pd.Series,
    qqq_close: pd.Series,
) -> Dict[str, Any]:
    """Pooled raw Pearson + residual Pearson (vs SPY+QQQ) for one
    candidate against each reference NAV."""
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


# ── R41 5-tier classification ───────────────────────────────────────────────


def _classify_r41(
    evaluation: Dict[str, Any],
    nav_corr_vs_existing: Dict[str, Any],
    cycle_01_top_features: List[str],
    cycle_02_top_features: List[str],
    rcm_v1_features: List[str],
    cand_2_features: List[str],
    overlap_threshold: int = 2,
    pooled_max: float = 0.85,
    residual_max: float = 0.70,
) -> Dict[str, Any]:
    """R41 5-tier classification:
    Tier 0: not run / aborted
    Tier 1: non-sibling nominee, all gates pass
    Tier 2: factor-level sibling (overlap ≥ threshold) OR construction-collapse
    Tier 3: passes IC but fails Track A acceptance
    Tier 4: classified failure (e.g., G2.A concentration)
    Tier 5: non-evaluable (data quality)"""
    feats = set(evaluation.get("features", []))
    overlaps = {
        "cycle_01_top": len(feats & set(cycle_01_top_features)),
        "cycle_02_top": len(feats & set(cycle_02_top_features)),
        "rcm_v1": len(feats & set(rcm_v1_features)),
        "cand_2": len(feats & set(cand_2_features)),
    }
    max_overlap = max(overlaps.values())
    sibling_by_factor = max_overlap >= overlap_threshold

    # NAV correlation tier
    raw_pearsons = []
    residual_pearsons = []
    for name in ("rcm_v1", "cand_2"):
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
        # Not sibling. Check track-A gate readiness.
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


# ── Main ────────────────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser(description="Cycle #03 evaluation pipeline")
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else (
        PROJ / "data" / "ml" / "cycle03_evaluation" / LINEAGE_TAG
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[cycle03 eval] Loading criteria yaml: {CRITERIA_YAML.name}")
    cycle_yaml = _load_criteria_yaml()

    print(f"[cycle03 eval] Pulling top-{args.top_k} archived trials...")
    top_df = _load_top_n_archived_trials(top_k=args.top_k)
    if len(top_df) == 0:
        print(f"[cycle03 eval] No archived trials under {LINEAGE_TAG} — mining "
              "may not have completed.")
        return 1
    print(f"  {len(top_df)} trials retrieved")

    print(f"[cycle03 eval] Building input panels (selector role: train+val)...")
    panel, all_factors, mask, split_cfg = _build_inputs()
    print(f"  panel: {panel['close'].shape[0]} dates × {panel['close'].shape[1]} symbols")

    print(f"[cycle03 eval] Building RCMv1 + Cand-2 reference NAVs (global_top_n)...")
    reference_navs = _build_reference_navs(panel, all_factors, mask, split_cfg)
    print(f"  reference NAVs available: {list(reference_navs.keys())}")

    spy_close = panel["close"].get("SPY")
    qqq_close = panel["close"].get("QQQ")

    # Anti-sibling references
    cycle_01_top_features = ["beta_spy_60d", "mom_12_1", "volume_ratio_20d"]  # cycle #01 top
    cycle_02_top_features = ["beta_spy_60d", "mom_12_1", "volume_ratio_20d"]  # cycle #02 top (identical)
    rcm_v1_features = ["beta_spy_60d", "drawup_from_252d_low", "days_since_52w_high", "amihud_20d"]
    cand_2_features = ["ret_5d", "rs_vs_spy_126d", "hl_range"]

    print(f"[cycle03 eval] Evaluating top-{len(top_df)} candidates (cap_aware)...")
    evaluations = []
    for i, (_, trial_row) in enumerate(top_df.iterrows(), start=1):
        print(f"  [{i}/{len(top_df)}] trial_id={trial_row['trial_id']} "
              f"ic_ir={float(trial_row['ic_ir']):.4f}")
        ev = _evaluate_one(trial_row, panel, all_factors, mask, cycle_yaml, split_cfg,
                            construction_mode="cap_aware")
        if "error" not in ev:
            cand_nav = ev.pop("_nav_series")
            ev["nav_correlation_vs_existing_pair"] = _compute_cross_cycle_correlations(
                cand_nav, reference_navs, spy_close, qqq_close,
            )
            ev["r41_classification"] = _classify_r41(
                ev, ev["nav_correlation_vs_existing_pair"],
                cycle_01_top_features, cycle_02_top_features,
                rcm_v1_features, cand_2_features,
            )
        evaluations.append(ev)

    summary = {
        "lineage_tag": LINEAGE_TAG,
        "criteria_yaml_sha256": __import__("hashlib").sha256(
            CRITERIA_YAML.read_bytes()
        ).hexdigest(),
        "evaluation_timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
        "construction_mode": "cap_aware",
        "construction_yaml_block": cycle_yaml.get("construction", {}),
        "top_k": args.top_k,
        "evaluations": evaluations,
        "anti_sibling_thresholds": {
            "factor_overlap_threshold": 2,
            "pooled_max": 0.85,
            "residual_max": 0.70,
        },
        "anchor_features_for_overlap": {
            "cycle_01_top": cycle_01_top_features,
            "cycle_02_top": cycle_02_top_features,
            "rcm_v1": rcm_v1_features,
            "cand_2": cand_2_features,
        },
    }
    out_path = out_dir / "evaluation_summary.json"
    out_path.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\n[cycle03 eval] Wrote: {out_path}")

    # Top-3 brief summary
    print("\n=== TOP-3 SUMMARY (cap_aware) ===")

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
        cd = ev.get("cluster_diversity", {}) or {}
        nc = ev.get("nav_correlation_vs_existing_pair", {}) or {}
        r41 = ev.get("r41_classification", {}) or {}
        print(f"  {ev['trial_id']}  features={ev.get('features')}")
        print(f"    cum_ret={_f(m.get('cum_ret'))} "
              f"sharpe={_f(m.get('sharpe'), '.3f')} "
              f"max_dd={_f(m.get('max_dd'))} "
              f"vs_qqq={_f(m.get('vs_qqq'), '+.4%')}")
        print(f"    n_clusters_avg={_f(cd.get('n_unique_clusters_per_rebalance_avg'), '.2f')} "
              f"cluster_max={_f(cd.get('cluster_concentration_max'), '.3f')} "
              f"cash_avg={_f(cd.get('implicit_cash_pct_avg'), '.3f')}")
        print(f"    raw_corr vs RCMv1={_f(nc.get('rcm_v1_pooled_pearson_raw'), '.3f')} "
              f"vs Cand-2={_f(nc.get('cand_2_pooled_pearson_raw'), '.3f')}")
        print(f"    R41 Tier {r41.get('tier')}: {r41.get('reason')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
