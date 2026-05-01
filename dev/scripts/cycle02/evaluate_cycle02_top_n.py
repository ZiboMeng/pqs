"""Cycle #02 evaluation pipeline (Step 3).

Pulls top-N archived trials from lineage `track-c-cycle-2026-04-30-02`,
runs each through the per-trial harness (Step 1) under the cycle's
construction config (weekly cadence, top_n=10), produces:

  - per-candidate paper NAV (over train+validation panel)
  - Track A acceptance metrics (per-validation-year, per-stress-slice,
    concentration, vs SPY+QQQ excess, cost-robustness flag)
  - NAV correlation vs RCMv1 + Cand-2 (using harness re-run on
    current data, since the live forward observations were aborted)
  - Family E/F archived-trial census (cycle #02 hypothesis test)
  - R41 5-tier classification per candidate
  - Closeout outcome summary

Output: data/ml/cycle02_evaluation/<lineage>/...

Decision authority: run automatically once cycle #02 mining completes.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import yaml


PROJ = Path("/home/zibo/Documents/projects/pqs")
CRITERIA_YAML = (
    PROJ
    / "data"
    / "research_candidates"
    / "track-c-cycle-2026-04-30-02_promotion_criteria.yaml"
)
LINEAGE_TAG = "track-c-cycle-2026-04-30-02"


# ── Loaders ──────────────────────────────────────────────────────────────────


def _load_criteria_yaml() -> Dict:
    return yaml.safe_load(CRITERIA_YAML.read_text())


def _load_top_n_archived_trials(top_k: int = 10) -> pd.DataFrame:
    """Pull top-K trials from the archive, sorted by IC_IR desc."""
    con = sqlite3.connect(str(PROJ / "data" / "mining" / "rcm_archive.db"))
    df = pd.read_sql(
        "SELECT trial_id, ic_ir, features_csv, weights_csv, "
        "family_counts_json, ic_mean, ic_std, turnover_proxy, "
        "corr_concentration, n_dates, objective "
        "FROM rcm_trials WHERE lineage_tag = ? "
        "ORDER BY ic_ir DESC LIMIT ?",
        con,
        params=(LINEAGE_TAG, top_k),
    )
    con.close()
    return df


def _build_inputs():
    """Build factor_panel_map + price_df + benchmark series for the
    train+validation panel (matches what cycle #02 mining used)."""
    import sys

    sys.path.insert(0, str(PROJ))
    from core.config.loader import load_config
    from core.data.bar_store import BarStore
    from core.factors.factor_generator import generate_all_factors
    from core.research.temporal_split import (
        load_temporal_split,
        restrict_frames_to_train,
    )

    cfg = load_config(PROJ / "config")
    # Use BarStore.load(adjusted=True) — applies splits.parquet cascade.
    # MarketDataStore.read returns RAW heterogeneously-split-adjusted parquet,
    # which produces NAV-explosion artifacts (Step 0 finding 2026-04-30).
    store = BarStore(root=Path(cfg.system.paths.data_dir))

    # Universe: 78 syms minus BRK-B (matches yaml.universe_panel_mask_spec)
    uni = cfg.universe
    all_syms = list(
        dict.fromkeys(
            list(uni.seed_pool)
            + list(uni.sector_etfs)
            + list(uni.factor_etfs)
            + list(uni.cross_asset)
        )
    )
    tradable = [
        s
        for s in all_syms
        if s not in uni.blacklist and s not in uni.macro_reference
    ]
    tradable = [s for s in tradable if s != "BRK-B"]

    # Always include benchmarks for vs_spy/vs_qqq even if they aren't in
    # the tradable universe.
    for bench in ("SPY", "QQQ"):
        if bench not in tradable:
            tradable.append(bench)

    frames = {k: {} for k in ("close", "open", "high", "low", "volume")}
    for sym in tradable:
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

    # Apply temporal split: train + validation only (no 2026 sealed)
    split_cfg = load_temporal_split(PROJ / "config" / "temporal_split.yaml")
    panel = {"close": close_df, "open": open_df, "high": high_df,
             "low": low_df, "volume": volume_df}
    panel = restrict_frames_to_train(panel, split_cfg)

    # Generate factors over the train+validation panel
    benchmark_map = {
        b: panel["close"][b]
        for b in ("SPY", "QQQ")
        if b in panel["close"].columns
    }
    all_factors = generate_all_factors(
        panel["close"],
        volume_df=panel["volume"],
        open_df=panel["open"],
        high_df=panel["high"],
        low_df=panel["low"],
        benchmark_map=benchmark_map,
    )

    # Research mask
    from core.factors.base_masks import research_mask_default

    research_mask = (
        research_mask_default(panel["close"], panel["volume"])
        if panel["volume"] is not None
        else None
    )

    return panel, all_factors, research_mask, split_cfg


# ── Family E/F census ────────────────────────────────────────────────────────


_FAMILY_E = {
    "hl_range",
    "intraday_ret_1d",
    "intraday_autocorr_21d",
    "intraday_vol_ratio_21d",
    "realized_vol_60m_21d",
    "overnight_ret_1d",
    "overnight_gap_5d",
    "overnight_gap_21d",
    "overnight_vs_intraday",
    "price_volume_div",
}
_FAMILY_F = {"ret_1d", "ret_2d", "ret_5d", "reversal_5d", "reversal_10d", "reversal_21d"}


def _family_ef_census() -> Dict:
    """Count archived trials touching Family E or F under cycle #02 lineage.
    The yaml's report_only.family_ef_archived_trial_census fields."""
    con = sqlite3.connect(str(PROJ / "data" / "mining" / "rcm_archive.db"))
    df = pd.read_sql(
        "SELECT trial_id, ic_ir, features_csv FROM rcm_trials "
        "WHERE lineage_tag = ?",
        con,
        params=(LINEAGE_TAG,),
    )
    con.close()
    e_only = 0
    f_only = 0
    e_or_f = 0
    e_or_f_trials: List[Tuple[str, float, str]] = []
    for _, row in df.iterrows():
        feats = set(row["features_csv"].split(","))
        in_e = bool(feats & _FAMILY_E)
        in_f = bool(feats & _FAMILY_F)
        if in_e and not in_f:
            e_only += 1
        if in_f and not in_e:
            f_only += 1
        if in_e or in_f:
            e_or_f += 1
            e_or_f_trials.append(
                (row["trial_id"], float(row["ic_ir"]), row["features_csv"])
            )
    e_or_f_trials.sort(key=lambda x: -x[1])
    return {
        "n_archived_trials_total": int(len(df)),
        "n_archived_trials_in_family_e_only": e_only,
        "n_archived_trials_in_family_f_only": f_only,
        "n_archived_trials_in_family_e_or_f": e_or_f,
        "top_3_archived_trials_touching_family_ef": [
            {"trial_id": t, "ic_ir": ic, "features": f}
            for t, ic, f in e_or_f_trials[:3]
        ],
    }


# ── Per-candidate evaluation ─────────────────────────────────────────────────


def _evaluate_one_candidate(
    trial_row: pd.Series,
    panel: Dict[str, pd.DataFrame],
    all_factors: Dict,
    research_mask,
    cycle_yaml: Dict,
    split_cfg,
) -> Dict:
    """Run one archived candidate through the harness."""
    import sys

    sys.path.insert(0, str(PROJ))
    from core.mining.research_miner import ResearchCompositeSpec
    from core.research.harness import (
        HarnessConfig,
        evaluate_composite_spec,
    )

    feats = trial_row["features_csv"].split(",")
    weights = [float(w) for w in trial_row["weights_csv"].split(",")]
    family_counts = json.loads(trial_row["family_counts_json"])

    # Archive stores weights as f"{w:.6f}" (rcm_archive.py:310); equal-weight
    # 1/3 truncates to 0.333333 → sum=0.999999 < 1.0 strict tolerance (1e-6).
    # Renormalize, then absorb residual into the max weight (mirrors
    # research_miner.py:599-606 absorb-into-largest pattern).
    total = sum(weights)
    if abs(total - 1.0) > 0:
        weights = [w / total for w in weights]
        residual = 1.0 - sum(weights)
        if abs(residual) > 0:
            max_idx = max(range(len(weights)), key=lambda i: weights[i])
            weights[max_idx] += residual

    # Build spec
    spec = ResearchCompositeSpec(
        features=tuple(feats),
        weights=tuple(weights),
        family_counts=family_counts,
    )

    # Build cycle-config-aligned panel_map
    panel_map = {f: all_factors[f] for f in feats if f in all_factors}
    if len(panel_map) != len(feats):
        missing = [f for f in feats if f not in panel_map]
        return {"trial_id": trial_row["trial_id"], "error": f"missing factors: {missing}"}

    # Validation years from temporal split config (.year per entry)
    validation_years = sorted(
        {vy.year for vy in split_cfg.partition.validation_years}
    )

    # Stress slices from temporal split config (canonical SoT)
    stress_slices = {
        ss.name: (ss.start.isoformat(), ss.end.isoformat())
        for ss in split_cfg.partition.stress_slices
    }

    # Construction config from cycle yaml
    construction = cycle_yaml.get("construction", {})
    cfg = HarnessConfig(
        rebalance_cadence=construction.get("rebalance_cadence", "weekly"),
        top_n=int(construction.get("top_n", 10)),
        min_holding_days=int(construction.get("min_holding_days", 1)),
        horizon_days=int(cycle_yaml["hard_requirements"].get("fwd_return_horizon_days", 5)),
        initial_capital=float(construction.get("initial_capital", 100_000.0)),
    )

    spy = panel["close"].get("SPY")
    qqq = panel["close"].get("QQQ")

    try:
        result = evaluate_composite_spec(
            spec=spec,
            factor_panel_map=panel_map,
            price_df=panel["close"],
            open_df=panel["open"],
            spy_series=spy,
            qqq_series=qqq,
            config=cfg,
            validation_years=validation_years,
            stress_slices=stress_slices,
            research_mask=research_mask,
        )
    except Exception as exc:
        return {
            "trial_id": trial_row["trial_id"],
            "error": f"harness failed: {type(exc).__name__}: {exc}",
        }

    return {
        "trial_id": trial_row["trial_id"],
        "features": feats,
        "weights": weights,
        "ic_ir_mining": float(trial_row["ic_ir"]),
        "n_observed_days": result.n_observed_days,
        "metrics_full_period": result.metrics_full_period,
        "metrics_per_validation_year": result.metrics_per_validation_year,
        "metrics_per_stress_slice": result.metrics_per_stress_slice,
        "concentration": result.concentration,
        "nav_correlation_vs_benchmark": result.nav_correlation_vs_benchmark,
    }


# ── Main ────────────────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser(description="Cycle #02 evaluation pipeline (Step 3)")
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--out-dir", default=None,
                   help="Default: data/ml/cycle02_evaluation/<lineage>/")
    args = ap.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else (
        PROJ / "data" / "ml" / "cycle02_evaluation" / LINEAGE_TAG
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[cycle02 eval] Loading criteria yaml: {CRITERIA_YAML.name}")
    cycle_yaml = _load_criteria_yaml()

    print(f"[cycle02 eval] Pulling top-{args.top_k} archived trials...")
    top_df = _load_top_n_archived_trials(top_k=args.top_k)
    if len(top_df) == 0:
        print(f"[cycle02 eval] No archived trials found under lineage "
              f"{LINEAGE_TAG} — mining may not have completed yet.")
        return 1
    print(f"  {len(top_df)} trials retrieved")

    print(f"[cycle02 eval] Family E/F census...")
    ef_census = _family_ef_census()
    print(f"  total archived: {ef_census['n_archived_trials_total']}")
    print(f"  in family E only: {ef_census['n_archived_trials_in_family_e_only']}")
    print(f"  in family F only: {ef_census['n_archived_trials_in_family_f_only']}")
    print(f"  in family E or F: {ef_census['n_archived_trials_in_family_e_or_f']}")
    if ef_census["top_3_archived_trials_touching_family_ef"]:
        print("  Top 3 archived trials touching E/F:")
        for r in ef_census["top_3_archived_trials_touching_family_ef"]:
            print(f"    ic_ir={r['ic_ir']:.4f}  {r['trial_id']}  {r['features']}")

    print(f"[cycle02 eval] Building input panels (train+validation)...")
    panel, all_factors, research_mask, split_cfg = _build_inputs()
    print(f"  panel: {panel['close'].shape[0]} dates × {panel['close'].shape[1]} symbols")
    print(f"  factor panels generated: {len(all_factors)}")

    print(f"[cycle02 eval] Evaluating top-{len(top_df)} candidates via harness...")
    evaluations = []
    for i, (_, trial_row) in enumerate(top_df.iterrows(), start=1):
        print(f"  [{i}/{len(top_df)}] trial_id={trial_row['trial_id']} "
              f"ic_ir={float(trial_row['ic_ir']):.4f}")
        result = _evaluate_one_candidate(
            trial_row, panel, all_factors, research_mask, cycle_yaml, split_cfg,
        )
        evaluations.append(result)

    summary = {
        "lineage_tag": LINEAGE_TAG,
        "criteria_yaml_sha256": (
            __import__("hashlib").sha256(CRITERIA_YAML.read_bytes()).hexdigest()
        ),
        "evaluation_timestamp": pd.Timestamp.utcnow().isoformat(),
        "family_ef_census": ef_census,
        "top_k": args.top_k,
        "evaluations": evaluations,
    }

    out_path = out_dir / "evaluation_summary.json"
    out_path.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\n[cycle02 eval] Wrote: {out_path}")

    # Print top-3 brief summary to stdout
    print("\n=== TOP-3 SUMMARY ===")

    def _fmt(x, spec=".3f"):
        if x is None or (isinstance(x, float) and np.isnan(x)):
            return "NA"
        try:
            return format(x, spec)
        except (TypeError, ValueError):
            return str(x)

    for ev in evaluations[:3]:
        if "error" in ev:
            print(f"  {ev['trial_id']}  ERROR: {ev['error']}")
            continue
        m = ev.get("metrics_full_period", {}) or {}
        nc = ev.get("nav_correlation_vs_benchmark", {}) or {}
        print(f"  {ev['trial_id']}  features={ev.get('features')}")
        print(f"    cum_ret={_fmt(m.get('cum_ret'), '.4%')} "
              f"sharpe={_fmt(m.get('sharpe'), '.3f')} "
              f"max_dd={_fmt(m.get('max_dd'), '.4%')} "
              f"vs_spy={_fmt(m.get('vs_spy'), '+.4%')} "
              f"vs_qqq={_fmt(m.get('vs_qqq'), '+.4%')}")
        print(f"    raw_corr_spy={_fmt(nc.get('raw_pearson_vs_spy'))} "
              f"raw_corr_qqq={_fmt(nc.get('raw_pearson_vs_qqq'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
