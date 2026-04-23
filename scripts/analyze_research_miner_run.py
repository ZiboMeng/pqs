#!/usr/bin/env python
"""Diagnostic analyzer for a Research Composite Miner run (R14).

Reads rcm_archive.db for a given lineage_tag (and optionally study_id),
computes:

  1. Feature frequency in top-K specs
  2. Per-family histogram in top-K
  3. Turnover / correlation-concentration distribution
  4. Univariate per-feature IC (raw, not composite-embedded) — compares
     PRD's 12 new features against existing RESEARCH_FACTORS so we can
     see whether under-representation in composite top-K comes from
     weak raw signal or from sampler coverage.
  5. Pairwise Spearman correlation matrix for the top-K-appearing
     features + all 12 PRD features (research orthogonality check)

Writes JSON + parquet to `data/ml/research_miner/<study>/diagnostics/`.

Usage:
  python scripts/analyze_research_miner_run.py \
      --study rcm-v1-run-01 --lineage post-2026-04-24-rcm-v1 --top-k 10
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.config.loader import load_config
from core.data.market_data_store import MarketDataStore
from core.factors.base_masks import research_mask
from core.factors.factor_generator import (
    compute_forward_returns,
    generate_all_factors,
)
from core.factors.factor_registry import RESEARCH_FACTORS
from core.logging_setup import get_logger, setup_logging
from core.mining.rcm_archive import RCMArchive
from core.mining.research_miner import FAMILIES_V1, family_of_factor

setup_logging()
logger = get_logger("rcm_analyzer")


# 12 PRD-new orthogonal features (PRD 20260424 §5.2)
PRD_NEW_FEATURES = [
    # Family A — Benchmark-relative / Residual / Risk Exposure
    "rel_spy_20d", "rel_qqq_20d", "beta_spy_60d", "residual_mom_spy_20d",
    # Family B — Position / Breakout / Path Shape
    "range_pos_252d", "days_since_52w_high", "breakout_20d_strength",
    "dist_from_new_high_252",
    # Family C — Liquidity / Cost Proxy / Risk State
    "amihud_20d", "downside_vol_20d", "vol_ratio_5_20",
    # Family D — Trend Quality
    "trend_tstat_20d",
]


def _load_top_k(archive: RCMArchive, lineage: str, k: int, study_id: str | None):
    df = archive.top_k(k=k, lineage_tag=lineage)
    if study_id:
        df = df[df["study_id"] == study_id].reset_index(drop=True)
    return df


def _feature_frequency(top_df: pd.DataFrame) -> pd.DataFrame:
    """Count how many top-K specs include each feature."""
    cnt = Counter()
    for row in top_df.itertuples():
        for f in row.features_csv.split(","):
            cnt[f.strip()] += 1
    rows = []
    for f, n in cnt.most_common():
        fam = family_of_factor(f, FAMILIES_V1)
        rows.append({
            "feature": f,
            "top_k_appearances": n,
            "family": fam if fam else "?",
            "is_prd_new": f in PRD_NEW_FEATURES,
        })
    return pd.DataFrame(rows)


def _family_histogram(top_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate family_counts across top-K."""
    totals: Counter[str] = Counter()
    for row in top_df.itertuples():
        fam_counts = json.loads(row.family_counts_json)
        for fam, n in fam_counts.items():
            totals[fam] += int(n)
    rows = [{"family": fam, "total_slot_count_in_top_k": totals[fam]}
            for fam in sorted(totals)]
    return pd.DataFrame(rows)


def _load_panel(cfg, store, horizon: int):
    """Re-build the panel the miner ran on (same contract as CLI)."""
    uni = cfg.universe
    all_syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs)
        + list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    tradable = [s for s in all_syms
                if s not in uni.blacklist and s not in uni.macro_reference]
    frames = {k: {} for k in ("close", "open", "high", "low", "volume")}
    for sym in tradable:
        df = store.read(sym, "1d")
        if df is None or df.empty or "close" not in df.columns:
            continue
        frames["close"][sym] = df["close"]
        for col in ("open", "high", "low", "volume"):
            if col in df.columns:
                frames[col][sym] = df[col]
    close = pd.DataFrame(frames["close"]).sort_index()
    start = cfg.backtest.start_date or "2007-01-02"
    close = close[close.index >= pd.Timestamp(start)]

    def _df(col):
        if not frames[col]:
            return None
        d = pd.DataFrame(frames[col]).reindex_like(close)
        return d

    volume = _df("volume")
    open_df = _df("open")
    high_df = _df("high")
    low_df = _df("low")

    benchmark_map = {b: close[b] for b in ("SPY", "QQQ") if b in close.columns}
    factors = generate_all_factors(
        close, volume_df=volume,
        open_df=open_df, high_df=high_df, low_df=low_df,
        benchmark_map=benchmark_map,
    )
    panel_map = {name: fdf for name, fdf in factors.items()
                 if name in RESEARCH_FACTORS}
    mask = (
        research_mask(close, volume, min_price=5.0, min_usd=20e6, window=20)
        if volume is not None else None
    )
    fwd = compute_forward_returns(close, horizons=[horizon], mode="cc")[horizon]
    return panel_map, fwd, mask


def _univariate_ic(
    panel_map: dict, fwd: pd.DataFrame, mask, horizon: int,
    feature_list: list[str],
) -> pd.DataFrame:
    """Per-feature per-date Spearman IC, averaged over time.

    Also returns horizon-aware IR. Reuses `_spearman_ic_per_date` from
    research_miner to stay consistent.
    """
    from core.mining.research_miner import _spearman_ic_per_date
    from core.factors.base_masks import apply_research_mask
    rows = []
    for f in feature_list:
        if f not in panel_map:
            rows.append({
                "feature": f, "ic_mean": np.nan, "ic_std": np.nan,
                "ic_ir": np.nan, "n_dates": 0,
                "is_prd_new": f in PRD_NEW_FEATURES,
            })
            continue
        panel = panel_map[f]
        if mask is not None:
            panel = apply_research_mask(panel, mask)
        ic_series = _spearman_ic_per_date(panel, fwd)
        if len(ic_series) == 0:
            ic_mean = ic_std = ic_ir = np.nan
        else:
            ic_mean = float(ic_series.mean())
            ic_std = float(ic_series.std()) if len(ic_series) > 1 else np.nan
            if ic_std and np.isfinite(ic_std) and ic_std > 0:
                ic_ir = float(ic_mean / ic_std * np.sqrt(252 / horizon))
            else:
                ic_ir = np.nan
        rows.append({
            "feature": f,
            "ic_mean": ic_mean, "ic_std": ic_std, "ic_ir": ic_ir,
            "n_dates": int(len(ic_series)),
            "family": family_of_factor(f, FAMILIES_V1) or "?",
            "is_prd_new": f in PRD_NEW_FEATURES,
        })
    df = pd.DataFrame(rows).sort_values("ic_ir", ascending=False, na_position="last")
    return df.reset_index(drop=True)


def _feature_pair_correlation(
    panel_map: dict, mask, feature_list: list[str],
) -> pd.DataFrame:
    """Pairwise Spearman correlation matrix across the feature list.

    Flattens each factor panel to a (date, symbol) series and computes
    Spearman on the overlapping samples (post-mask). Useful for
    orthogonality audit: PRD promised "orthogonal" subset — verify.
    """
    from core.factors.base_masks import apply_research_mask
    # Flatten each feature to a long series
    flats = {}
    for f in feature_list:
        if f not in panel_map:
            continue
        p = panel_map[f]
        if mask is not None:
            p = apply_research_mask(p, mask)
        flats[f] = p.stack().rename(f)
    if not flats:
        return pd.DataFrame()
    aligned = pd.concat(flats.values(), axis=1, join="inner")
    aligned = aligned.dropna()
    if len(aligned) < 50:
        return pd.DataFrame()
    return aligned.rank().corr(method="pearson")  # rank-corr = Spearman on ranks


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Research Composite Miner run diagnostics (R14)",
    )
    parser.add_argument("--study", required=True,
                        help="study_id (e.g. rcm-v1-run-01)")
    parser.add_argument("--lineage", default="post-2026-04-24-rcm-v1")
    parser.add_argument("--archive-db", default="data/mining/rcm_archive.db")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--horizon", type=int, default=21)
    parser.add_argument("--out-dir",
                        default="data/ml/research_miner")
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--skip-univariate", action="store_true",
                        help="Skip per-feature univariate IC (expensive)")
    args = parser.parse_args()

    out_root = Path(args.out_dir) / args.study / "diagnostics"
    out_root.mkdir(parents=True, exist_ok=True)
    logger.info("Study=%s Lineage=%s Top-K=%d",
                args.study, args.lineage, args.top_k)

    archive = RCMArchive(args.archive_db)
    top_df = _load_top_k(archive, args.lineage, args.top_k, args.study)
    logger.info("Loaded top-%d from archive: %d rows", args.top_k, len(top_df))
    if len(top_df) == 0:
        logger.error("No trials under this lineage+study; abort.")
        return 1

    # Feature frequency + family histogram
    freq = _feature_frequency(top_df)
    fam_hist = _family_histogram(top_df)
    freq.to_csv(out_root / "feature_frequency_top_k.csv", index=False)
    fam_hist.to_csv(out_root / "family_histogram_top_k.csv", index=False)

    # Univariate IC
    univariate_df = None
    pair_corr = None
    if not args.skip_univariate:
        logger.info("Rebuilding panel for univariate IC...")
        cfg = load_config(Path(args.config_dir))
        store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))
        panel_map, fwd, mask = _load_panel(cfg, store, args.horizon)

        # Compute univariate IC for all feature_registry-RESEARCH_FACTORS
        all_features = sorted(panel_map.keys())
        logger.info("Univariate IC on %d features...", len(all_features))
        univariate_df = _univariate_ic(
            panel_map, fwd, mask, args.horizon, all_features,
        )
        univariate_df.to_csv(out_root / "univariate_ic.csv", index=False)

        # Pair correlation: top-10 appearing + 12 PRD features
        top_appearing = freq["feature"].head(10).tolist()
        audit_set = sorted(set(top_appearing + PRD_NEW_FEATURES))
        logger.info("Pair correlation over %d features...", len(audit_set))
        pair_corr = _feature_pair_correlation(panel_map, mask, audit_set)
        if len(pair_corr):
            pair_corr.to_csv(out_root / "feature_pair_correlation.csv")

    summary = {
        "study": args.study,
        "lineage": args.lineage,
        "top_k": int(args.top_k),
        "horizon": int(args.horizon),
        "top_k_row_count": int(len(top_df)),
        "ic_ir_range_in_top_k": [
            float(top_df["ic_ir"].min()),
            float(top_df["ic_ir"].max()),
        ],
        "objective_range_in_top_k": [
            float(top_df["objective"].min()),
            float(top_df["objective"].max()),
        ],
        "prd_new_feature_appearances_in_top_k": int(
            freq[freq["is_prd_new"]]["top_k_appearances"].sum()
        ),
        "existing_feature_appearances_in_top_k": int(
            freq[~freq["is_prd_new"]]["top_k_appearances"].sum()
        ),
        "family_totals_in_top_k": {
            row["family"]: int(row["total_slot_count_in_top_k"])
            for row in fam_hist.to_dict(orient="records")
        },
    }
    if univariate_df is not None:
        top5 = univariate_df.head(5).to_dict(orient="records")
        prd_section = (
            univariate_df[univariate_df["is_prd_new"]]
            .sort_values("ic_ir", ascending=False)
            .to_dict(orient="records")
        )
        summary["top_5_features_by_ic_ir"] = top5
        summary["prd_new_features_ic_ir_ranking"] = prd_section

    (out_root / "diagnostics_summary.json").write_text(
        json.dumps(summary, indent=2, default=str)
    )
    logger.info("Artifacts: %s", out_root)

    print("=" * 70)
    print(f"RCM diagnostics — {args.study} (horizon={args.horizon})")
    print("=" * 70)
    print(f"\nTop-{args.top_k} IC_IR range: "
          f"[{summary['ic_ir_range_in_top_k'][0]:+.3f}, "
          f"{summary['ic_ir_range_in_top_k'][1]:+.3f}]")
    print(f"PRD-new feature appearances in top-{args.top_k}: "
          f"{summary['prd_new_feature_appearances_in_top_k']}")
    print(f"Existing-feature appearances in top-{args.top_k}: "
          f"{summary['existing_feature_appearances_in_top_k']}")
    print("\nFamily distribution in top-K (total slots):")
    for fam, n in summary["family_totals_in_top_k"].items():
        print(f"  {fam}: {n}")
    if univariate_df is not None:
        print("\nTop-10 features by univariate IC_IR (horizon-aware):")
        print(univariate_df.head(10)[[
            "feature", "family", "is_prd_new", "ic_mean", "ic_ir", "n_dates",
        ]].to_string(index=False))
        print("\nPRD 12 new features — univariate IC_IR ranking:")
        prd_df = univariate_df[univariate_df["is_prd_new"]].sort_values(
            "ic_ir", ascending=False,
        )
        print(prd_df[[
            "feature", "family", "ic_mean", "ic_ir", "n_dates",
        ]].to_string(index=False))
    print(f"\nArtifacts: {out_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
