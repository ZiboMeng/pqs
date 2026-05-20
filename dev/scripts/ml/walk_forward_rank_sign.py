#!/usr/bin/env python
"""PRD #4 P4.4 sub-step 3b — real-data walk-forward driver for rank models.

Loads the cycle06-style 113-factor research panel (executable universe by
default) + builds forward-return labels at the canonical candidate horizon
(weekly = 5 bday default, matching cycle06_31af04cf2ff9 holding_freq).
Runs strict-chronological rolling-window walk-forward for LinearBaseline
and XGBRanker, optionally producing pooled vs on-tradeable-mask rank-IC
side-by-side per PRD #4 P4.1 AC binding constraint.

Discipline (mandatory):
  - assert_bar_integrity (CLAUDE.md hard requirement before heavy ML)
  - assert_no_sealed_year (data-level last-line-of-defense for 2026)
  - WalkForwardConfig sealed_years guard (config-level backstop)
  - strict-chronological (Track-A R1 leakage discipline)
  - per-fold transparency + non-blanket fold failures

Output:
  - per-fold metric tables printed to stdout (human-readable verdict)
  - artifacts saved to data/ml/<lineage_tag>.{pkl,json}
  - summary JSON written to data/ml/<universe>_<horizon>_summary.json

Usage:
  python dev/scripts/ml/walk_forward_rank_sign.py
  python dev/scripts/ml/walk_forward_rank_sign.py --universe executable \
      --horizon-days 5 --model both
  python dev/scripts/ml/walk_forward_rank_sign.py --train-window 5 \
      --start-year 2010 --end-year 2017
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Tuple

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from core.config.loader import load_config  # noqa: E402
from core.data.bar_store import BarStore  # noqa: E402
from core.factors.base_masks import research_mask_default  # noqa: E402
from core.factors.factor_generator import generate_all_factors  # noqa: E402
from core.research.ml.artifact import (  # noqa: E402
    ModelArtifact,
    make_artifact_metadata,
    save_artifact,
)
from core.research.ml.labels import (  # noqa: E402
    apply_tradeable_mask,
    assert_bar_integrity,
    assert_no_sealed_year,
    make_forward_return_labels,
)
from core.research.ml.pipeline import (  # noqa: E402
    DEFAULT_SEALED_YEARS,
    WalkForwardConfig,
    WalkForwardResult,
    run_walk_forward,
)
from core.research.ml.rank_model import LinearBaselineRankModel  # noqa: E402


def _load_panel(
    universe_name: str = "executable",
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, pd.DataFrame], pd.DataFrame]:
    """Load price panel + factors + tradeable mask (cycle06 pattern).

    Returns (panel, factors, mask) where panel has keys close/open/high/
    low/volume, factors is the 113-factor research dict, mask is the
    research-default boolean tradeability mask.
    """
    cfg = load_config(PROJ / "config")
    store = BarStore(root=Path(cfg.system.paths.data_dir))
    uni = cfg.universe
    syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs)
        + list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    # cycle06 yaml drop_symbols
    drop = {"BRK-B", "USO", "SLV"}
    syms = [s for s in syms if s not in uni.blacklist
            and s not in uni.macro_reference and s not in drop]
    for b in ("SPY", "QQQ"):
        if b not in syms:
            syms.append(b)

    frames: Dict[str, Dict[str, pd.Series]] = {
        k: {} for k in ("close", "open", "high", "low", "volume")}
    for sym in syms:
        # PRD-X v2 Phase X0: atr=True universally (TR cascade)
        df = store.load(sym, freq="1d", adjusted=True,
                        adjusted_total_return=True, fallback="local")
        if df is None or df.empty or "close" not in df.columns:
            continue
        frames["close"][sym] = df["close"]
        for col in ("open", "high", "low", "volume"):
            if col in df.columns:
                frames[col][sym] = df[col]

    close = pd.DataFrame(frames["close"]).sort_index()
    panel = {
        "close": close,
        "open": pd.DataFrame(frames["open"]).reindex_like(close),
        "high": pd.DataFrame(frames["high"]).reindex_like(close),
        "low": pd.DataFrame(frames["low"]).reindex_like(close),
        "volume": pd.DataFrame(frames["volume"]).reindex_like(close),
    }
    bench = {b: close[b] for b in ("SPY", "QQQ") if b in close.columns}
    factors = generate_all_factors(
        close, volume_df=panel["volume"],
        open_df=panel["open"], high_df=panel["high"], low_df=panel["low"],
        benchmark_map=bench,
    )
    mask = (research_mask_default(close, panel["volume"])
            if panel["volume"] is not None else None)
    return panel, factors, mask


def _slice_to_year_range(
    panel: Dict[str, pd.DataFrame],
    factors: Dict[str, pd.DataFrame],
    mask: pd.DataFrame | None,
    start_year: int,
    end_year: int,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, pd.DataFrame], pd.DataFrame | None]:
    """Inclusive year-range slice for all data."""
    start = pd.Timestamp(f"{start_year}-01-01")
    end = pd.Timestamp(f"{end_year}-12-31")
    sliced_panel = {
        k: v.loc[(v.index >= start) & (v.index <= end)]
        for k, v in panel.items()
    }
    sliced_factors = {
        k: v.loc[(v.index >= start) & (v.index <= end)]
        for k, v in factors.items()
    }
    sliced_mask = (mask.loc[(mask.index >= start) & (mask.index <= end)]
                   if mask is not None else None)
    return sliced_panel, sliced_factors, sliced_mask


def _print_per_fold_table(name: str, result: WalkForwardResult) -> None:
    print(f"\n  {name} per-fold:")
    print(f"  {'fold':<5} {'train':<25} {'val':<25} "
          f"{'rank_ic':>10} {'rank_ir':>10} {'val_n':>8} {'err':<20}")
    for fm in result.per_fold:
        train_str = f"{fm.fold.train_start.date()}..{fm.fold.train_end.date()}"
        val_str = f"{fm.fold.val_start.date()}..{fm.fold.val_end.date()}"
        err_str = (fm.error[:18] + "..") if fm.error else "-"
        print(f"  {fm.fold.fold_idx:<5} {train_str:<25} {val_str:<25} "
              f"{fm.rank_ic:>10.4f} {fm.rank_ir:>10.4f} "
              f"{fm.val_n_obs:>8} {err_str:<20}")
    print(f"  → mean rank-IC = {result.mean_rank_ic:.4f}  "
          f"mean rank-IR = {result.mean_rank_ir:.4f}  "
          f"({result.n_successful_folds}/{len(result.per_fold)} folds OK)")


def _filter_factors_to_panel(
    factors: Dict[str, pd.DataFrame],
) -> Dict[str, pd.DataFrame]:
    """Drop factors with empty / all-NaN panels (per-fold safety)."""
    out = {}
    for name, panel in factors.items():
        if panel.empty:
            continue
        if panel.notna().sum().sum() == 0:
            continue
        out[name] = panel
    return out


def _build_xgb_factory(seed: int = 42) -> Callable:
    """Lazy import to avoid xgboost dep at module load."""
    from core.research.ml.xgb_rank_model import XGBRankerRankModel

    def _factory() -> XGBRankerRankModel:
        # Tight tree budget — keep walk-forward fold under ~5s
        return XGBRankerRankModel(
            n_estimators=50, max_depth=4, learning_rate=0.1,
            random_state=seed,
        )
    return _factory


def main() -> int:
    parser = argparse.ArgumentParser(
        description="PRD #4 P4.4 sub-step 3b: real-data walk-forward driver",
    )
    parser.add_argument("--universe", default="executable",
                        choices=["executable", "expanded_v2"],
                        help="universe yaml choice (executable=config/universe.yaml)")
    parser.add_argument("--horizon-days", type=int, default=5,
                        help="forward-return label horizon in business days "
                             "(default 5 = weekly per cycle06_31af04cf2ff9 spec)")
    parser.add_argument("--start-year", type=int, default=2010)
    parser.add_argument("--end-year", type=int, default=2024,
                        help="must be < 2026 (sealed-year guard)")
    parser.add_argument("--train-window", type=int, default=5,
                        help="train window in years (default 5)")
    parser.add_argument("--val-window", type=int, default=1,
                        help="val window in years (default 1)")
    parser.add_argument("--step", type=int, default=1,
                        help="walk-forward step in years (default 1)")
    parser.add_argument("--model", default="both",
                        choices=["linear", "xgb", "both"])
    parser.add_argument("--features", default="cycle06",
                        choices=["cycle06", "all"],
                        help="cycle06 = 3-factor composite (drawup_from_252d_low + "
                             "trend_tstat_20d + ret_2d); all = full 113-factor panel")
    parser.add_argument("--save-dir", default="data/ml")
    parser.add_argument("--no-save", action="store_true",
                        help="Skip artifact saving (smoke / dry-run)")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if args.universe != "executable":
        print(f"NOTE: universe={args.universe!r} not yet wired in this driver; "
              f"only 'executable' is supported in sub-step 3b. "
              f"expanded_v2 follows in P4.5 acceptance.",
              file=sys.stderr)
        return 2

    print(f"=== PRD #4 P4.4 sub-step 3b walk-forward driver ===")
    print(f"universe={args.universe} horizon_days={args.horizon_days} "
          f"train_window={args.train_window}y val_window={args.val_window}y "
          f"step={args.step}y range={args.start_year}-{args.end_year}")
    print(f"features={args.features} model={args.model}")

    print(f"\n[1/5] Loading panel + factors + mask via cycle06 pattern...")
    panel, factors, mask = _load_panel(args.universe)
    print(f"  close: {panel['close'].shape} ({len(panel['close'].columns)} symbols)")
    print(f"  factors: {len(factors)} computed")
    if mask is not None:
        print(f"  tradeable mask: {mask.shape} "
              f"({100 * mask.sum().sum() / mask.size:.1f}% cells tradeable)")

    print(f"\n[2/5] Slicing to year range {args.start_year}-{args.end_year}...")
    panel, factors, mask = _slice_to_year_range(
        panel, factors, mask, args.start_year, args.end_year)
    factors = _filter_factors_to_panel(factors)
    print(f"  close: {panel['close'].shape}  factors: {len(factors)} non-empty")

    print(f"\n[3/5] Bar-integrity + sealed-year smoke...")
    try:
        assert_bar_integrity(panel["close"], name="panel.close")
        assert_no_sealed_year(panel["close"], DEFAULT_SEALED_YEARS,
                              name="panel.close")
    except ValueError as exc:
        print(f"  ❌ SMOKE FAIL: {exc}", file=sys.stderr)
        return 3
    print(f"  ✅ bar-integrity OK")
    print(f"  ✅ no sealed-year ({DEFAULT_SEALED_YEARS}) overlap")

    print(f"\n[4/5] Building forward-return labels (horizon={args.horizon_days})...")
    labels_raw = make_forward_return_labels(panel["close"], args.horizon_days)
    labels_pooled = labels_raw
    labels_tradeable = apply_tradeable_mask(labels_raw, mask)
    pooled_n = int(labels_pooled.notna().sum().sum())
    tradeable_n = int(labels_tradeable.notna().sum().sum())
    print(f"  pooled labels: {pooled_n} non-NaN cells")
    print(f"  tradeable labels: {tradeable_n} non-NaN cells "
          f"({100 * tradeable_n / max(pooled_n, 1):.1f}% of pooled)")

    # Pick feature set
    if args.features == "cycle06":
        cycle06_feats = ("drawup_from_252d_low", "trend_tstat_20d", "ret_2d")
        missing = [f for f in cycle06_feats if f not in factors]
        if missing:
            print(f"  ❌ cycle06 features missing from factor panel: {missing}",
                  file=sys.stderr)
            return 4
        train_features = {f: factors[f] for f in cycle06_feats}
    else:
        train_features = factors

    feature_names = tuple(sorted(train_features.keys()))
    print(f"  features used: {len(feature_names)}")

    print(f"\n[5/5] Walk-forward training + held-out eval...")
    cfg = WalkForwardConfig(
        start_year=args.start_year, end_year=args.end_year,
        train_window_years=args.train_window,
        val_window_years=args.val_window,
        step_years=args.step,
    )

    # Pick models
    factories: List[Tuple[str, Callable, Dict]] = []
    if args.model in ("linear", "both"):
        factories.append((
            "LinearBaselineRankModel", LinearBaselineRankModel, {},
        ))
    if args.model in ("xgb", "both"):
        factories.append((
            "XGBRankerRankModel", _build_xgb_factory(args.seed),
            {"n_estimators": 50, "max_depth": 4, "learning_rate": 0.1,
             "random_state": args.seed},
        ))

    save_dir = PROJ / args.save_dir
    if not args.no_save:
        save_dir.mkdir(parents=True, exist_ok=True)
    summary: Dict[str, Dict] = {}
    trained_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    for model_name, factory, hyperparams in factories:
        print(f"\n--- {model_name} ---")
        for variant_name, variant_labels in (
            ("pooled", labels_pooled),
            ("tradeable", labels_tradeable),
        ):
            result = run_walk_forward(
                model_factory=factory, config=cfg,
                features=train_features, labels=variant_labels,
                sealed_years=DEFAULT_SEALED_YEARS,
            )
            _print_per_fold_table(f"{model_name}/{variant_name}", result)
            summary.setdefault(model_name, {})[variant_name] = {
                "mean_rank_ic": result.mean_rank_ic,
                "mean_rank_ir": result.mean_rank_ir,
                "n_successful_folds": result.n_successful_folds,
                "n_failed_folds": result.n_failed_folds,
            }

            if not args.no_save:
                # Train a final model on the LAST fold's train slice for
                # the persisted artifact (sub-step 3b: walk-forward
                # transparency + last-fold artifact for inference reuse;
                # full retrain on train+val is a separate sub-step).
                if result.n_successful_folds > 0:
                    last_train_fold = next(
                        (f for f in reversed(result.per_fold) if f.error is None),
                        None,
                    )
                    if last_train_fold is not None:
                        final_model = factory()
                        train_slice_feats = {
                            n: p.loc[(p.index >= last_train_fold.fold.train_start)
                                     & (p.index <= last_train_fold.fold.train_end)]
                            for n, p in train_features.items()
                        }
                        train_slice_labels = variant_labels.loc[
                            (variant_labels.index >= last_train_fold.fold.train_start)
                            & (variant_labels.index <= last_train_fold.fold.train_end)
                        ]
                        try:
                            final_model.fit(train_slice_feats, train_slice_labels)
                            metadata = make_artifact_metadata(
                                result=result, model_class_name=model_name,
                                hyperparams=hyperparams,
                                feature_columns=feature_names,
                                trained_at_utc=trained_at,
                            )
                            artifact = ModelArtifact(
                                model=final_model, metadata=metadata)
                            base = (save_dir
                                    / f"{model_name}_{variant_name}_"
                                      f"{args.start_year}-{args.end_year}_"
                                      f"{trained_at}")
                            paths = save_artifact(artifact, base)
                            print(f"  saved → {paths.pkl_path.name} + "
                                  f"{paths.json_path.name}")
                        except Exception as exc:
                            print(f"  ⚠ final-model fit failed: {exc}",
                                  file=sys.stderr)

    print(f"\n=== Summary ===")
    print(json.dumps(summary, indent=2))
    if not args.no_save:
        summary_path = (save_dir
                        / f"summary_{args.universe}_h{args.horizon_days}_"
                          f"{trained_at}.json")
        summary_path.write_text(json.dumps({
            "args": vars(args), "summary": summary,
            "trained_at_utc": trained_at,
        }, indent=2))
        print(f"summary → {summary_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
