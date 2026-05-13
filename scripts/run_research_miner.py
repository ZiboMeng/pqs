#!/usr/bin/env python
"""Research Composite Miner v1 runner (PRD 20260424 §15 Step 6, R13).

Runs N Optuna trials of family-aware research composite sampling on the
79-symbol universe with 12 PRD features + existing RESEARCH_FACTORS.
Persists every trial to rcm_archive.db + Optuna state to rcm_optuna.db.
Writes top-K JSON + lineage summary to data/ml/research_miner/.

This runner is research-only: it does NOT promote to PRODUCTION_FACTORS,
does NOT touch config/production_strategy.yaml, does NOT mix with the
production mining archive.

Usage:
  python scripts/run_research_miner.py --trials 50 --study rcm-v1-run-01
  python scripts/run_research_miner.py --trials 200 --study rcm-v1-run-02 \
      --lineage post-2026-04-24-rcm-v1 --resume
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Optional
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.config.loader import load_config
from core.data.market_data_store import MarketDataStore
from core.factors.base_masks import research_mask_default
from core.factors.factor_generator import (
    compute_forward_returns,
    generate_all_factors,
)
from core.factors.factor_registry import RESEARCH_FACTORS
from core.logging_setup import get_logger, setup_logging
from core.mining.rcm_archive import RCMArchive
from core.research.temporal_split import (
    compute_panel_max_date,
    compute_split_sha256,
    ensure_role_assigned,
    load_temporal_split,
    purge_labels_at_boundary,
    restrict_frames_to_train,
    validate_no_holdout_leakage,
)
from core.mining.research_miner import (
    FAMILIES_V1,
    FAMILIES_V2,
    ObjectiveWeights,
    ResearchMiner,
    all_family_factors,
    assert_reachability_matches_pool,
    families_for_pool,
)

setup_logging()
logger = get_logger("research_miner_cli")


def _load_price_volume(
    cfg, store, end_date: Optional[str] = None,
    drop_symbols: Optional[list] = None,
) -> dict[str, pd.DataFrame]:
    """Return {close, open, high, low, volume} DataFrames for the tradable
    universe + SPY/QQQ benchmarks.

    ``end_date`` (post-2026-04-26 audit, research-cycle pre-registration):
    if provided, filters the panel to dates ≤ end_date. Used by mining
    cycles that pre-register a panel cutoff per
    ``docs/memos/20260426-research_layer_partial_unfreeze.md`` §G4.

    ``drop_symbols`` (same audit): symbols to exclude from the panel
    even if present in universe.yaml. Used to honor a research-cycle
    criteria's ``drop_symbols`` declaration without modifying
    universe.yaml itself (which remains frozen under the partial
    unfreeze).
    """
    uni = cfg.universe
    all_syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs)
        + list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    # Include SPY & QQQ whether or not blacklisted (always needed as benchmarks)
    tradable = [s for s in all_syms
                if s not in uni.blacklist and s not in uni.macro_reference]
    if drop_symbols:
        drop_set = set(drop_symbols)
        tradable = [s for s in tradable if s not in drop_set]
    frames = {k: {} for k in ("close", "open", "high", "low", "volume")}
    for sym in tradable:
        df = store.read(sym, "1d")
        if df is None or df.empty or "close" not in df.columns:
            continue
        frames["close"][sym] = df["close"]
        for col in ("open", "high", "low", "volume"):
            if col in df.columns:
                frames[col][sym] = df[col]
    out = {}
    out["close"] = pd.DataFrame(frames["close"]).sort_index()
    for col in ("open", "high", "low", "volume"):
        if frames[col]:
            out[col] = pd.DataFrame(frames[col]).reindex_like(out["close"])
        else:
            out[col] = None
    # Start date
    start = cfg.backtest.start_date or "2007-01-02"
    mask = out["close"].index >= pd.Timestamp(start)
    if end_date is not None:
        mask = mask & (out["close"].index <= pd.Timestamp(end_date))
    out["close"] = out["close"][mask]
    for col in ("open", "high", "low", "volume"):
        if out[col] is not None:
            out[col] = out[col].reindex(out["close"].index)
    return out, tradable


def _build_factor_panel_map(
    frames: dict, tradable: list[str], horizon: int = 21,
    split_cfg=None,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, pd.DataFrame, int]:
    """Generate factor panels + forward returns + research mask.

    When ``split_cfg`` is provided, forward-return labels whose horizon
    window crosses a partition boundary (train ↔ validation ↔ sealed)
    are set to NaN via ``purge_labels_at_boundary`` (M4, financial-ML
    purging rule). This is required for non-contiguous train panels:
    e.g. with train_years = 2009-2017+2020+2022+2024, the row 2017-12-29
    in a train-restricted panel would otherwise carry a fwd_return
    computed across the 2018+2019 validation gap to 2020-01-08, which
    is methodologically meaningless for IC purposes (no leak — both
    endpoints are train data — but the value matches a 2-year-and-10-day
    return to a 5-day-horizon position label).

    Returns (factor_panel_map, fwd_returns_<horizon>d, mask, n_masked_out)
    """
    close = frames["close"]
    volume = frames["volume"]

    # Research mask (PRD §7): shared sample definition
    mask = (
        research_mask_default(close, volume)
        if volume is not None else None
    )

    # Build benchmark_map from SPY + QQQ (columns of close)
    benchmark_map = {}
    for bench in ("SPY", "QQQ"):
        if bench in close.columns:
            benchmark_map[bench] = close[bench]

    factors = generate_all_factors(
        close,
        volume_df=volume,
        open_df=frames["open"], high_df=frames["high"], low_df=frames["low"],
        benchmark_map=benchmark_map,
    )
    # Restrict to RESEARCH_FACTORS set (the miner uses FAMILIES_V1 which is
    # a subset, but having the full RESEARCH_FACTORS available means users
    # can experiment with extending families)
    panel_map = {
        name: fdf for name, fdf in factors.items()
        if name in RESEARCH_FACTORS
    }

    # PRD 20260512: merge fundamental / sector / macro factor compute
    # paths. These come from separate compute_* functions because
    # they have different input signatures (EDGAR cache / sector_map /
    # FRED CSV) than generate_all_factors. Each is wrapped in try/except
    # so missing-cache scenarios degrade gracefully (mining proceeds
    # with OHLCV + whatever non-OHLCV path succeeded). Logs the
    # outcome for ops audit.
    tickers = list(close.columns)
    daily_idx = close.index

    try:
        from core.factors.fundamental_factors import (
            compute_fundamental_factors_full,
        )
        from core.data.fundamentals_store import FundamentalsStore
        fstore = FundamentalsStore()
        fund_factors = compute_fundamental_factors_full(
            daily_idx, tickers, store=fstore, price_df=close,
        )
        added = 0
        for name, fdf in fund_factors.items():
            if name in RESEARCH_FACTORS:
                panel_map[name] = fdf
                added += 1
        logger.info("Fundamental factors merged: %d", added)
    except Exception as e:
        logger.warning(
            "Fundamental factor compute failed: %s. Mining will proceed "
            "without Bucket B factors.", e,
        )

    try:
        from core.factors.sector_factors import compute_sector_factors
        sec_factors = compute_sector_factors(close)
        added = 0
        for name, sdf in sec_factors.items():
            if name in RESEARCH_FACTORS:
                panel_map[name] = sdf
                added += 1
        logger.info("Sector factors merged: %d", added)
    except Exception as e:
        logger.warning("Sector factor compute failed: %s", e)

    try:
        from core.factors.macro_factors import compute_macro_factors
        macro_factors = compute_macro_factors(daily_idx, tickers)
        added = 0
        for name, mdf in macro_factors.items():
            if name in RESEARCH_FACTORS:
                panel_map[name] = mdf
                added += 1
        logger.info("Macro factors merged: %d", added)
    except Exception as e:
        logger.warning("Macro factor compute failed: %s", e)

    # Round D event window factors (pre-FOMC / CPI / NFP)
    try:
        from core.factors.event_window_factors import (
            compute_event_window_factors,
        )
        event_factors = compute_event_window_factors(daily_idx, tickers)
        added = 0
        for name, edf in event_factors.items():
            if name in RESEARCH_FACTORS:
                panel_map[name] = edf
                added += 1
        logger.info("Event window factors merged: %d", added)
    except Exception as e:
        logger.warning("Event window factor compute failed: %s", e)

    # Round F signal-confirmation multi-bar factors
    try:
        from core.factors.signal_confirmation_factors import (
            compute_signal_confirmation_factors,
        )
        sc_factors = compute_signal_confirmation_factors(close, volume)
        added = 0
        for name, sdf in sc_factors.items():
            if name in RESEARCH_FACTORS:
                panel_map[name] = sdf
                added += 1
        logger.info("Signal-confirmation factors merged: %d", added)
    except Exception as e:
        logger.warning("Signal-confirmation factor compute failed: %s", e)

    # Forward returns: `horizon`-day CC return (default 21d = medium-term)
    fwd_all = compute_forward_returns(close, horizons=[horizon], mode="cc")
    fwd_h = fwd_all[horizon]

    # M4 (cycle #02 audit fix 2026-04-30): purge cross-boundary labels.
    # config/temporal_split.yaml has purge_at_split_boundary=true, but
    # pre-fix the miner script never invoked the function. See
    # docs/memos/20260430-cycle02_data_isolation_audit.md §1B-9.
    if split_cfg is not None:
        fwd_h = purge_labels_at_boundary(fwd_h, split_cfg)

    n_masked_out = None
    if mask is not None:
        try:
            n_masked_out = int((~mask).sum().sum())
        except Exception:
            n_masked_out = None
    return panel_map, fwd_h, mask, n_masked_out


def _write_artifacts(
    out_dir: Path,
    study_id: str,
    lineage_tag: str,
    results,
    archive: RCMArchive,
    config_snapshot: dict,
    temporal_split_metadata: Optional[dict] = None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()

    # top-K from archive (authoritative — includes persisted rows)
    top_df = archive.top_k(k=20, lineage_tag=lineage_tag)
    if len(top_df):
        top_df.to_parquet(out_dir / "top_20.parquet")
        top_df.to_csv(out_dir / "top_20.csv", index=False)

    lineage_df = archive.lineage_summary()
    lineage_df.to_csv(out_dir / "lineage_summary.csv", index=False)

    # Summary JSON
    summary = {
        "timestamp": ts,
        "lineage_tag": lineage_tag,
        "study_id": study_id,
        "config": config_snapshot,
        "archive_n_trials_for_lineage": archive.n_trials(lineage_tag=lineage_tag),
        "miner_in_memory_completed": len(results),
        "top_3_preview": (
            top_df.head(3).to_dict(orient="records") if len(top_df) else []
        ),
    }
    if temporal_split_metadata is not None:
        # Track A audit fields: split_sha256 + split_name + role + panel_max_date.
        # Trial-level archive metadata wiring is Step A.4; here we capture
        # them at run-summary level as authoritative provenance.
        summary["temporal_split"] = temporal_split_metadata
    (out_dir / "run_summary.json").write_text(
        json.dumps(summary, indent=2, default=str)
    )
    logger.info("Artifacts written to %s", out_dir)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Research Composite Miner v1 (PRD 20260424)",
    )
    parser.add_argument("--trials", type=int, default=50,
                        help="Optuna trial count")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--study", default=None,
                        help="Optuna study_name (and miner study_id); "
                             "default = timestamped rcm-v1-run-<utc>")
    parser.add_argument("--lineage", default="post-2026-04-24-rcm-v1")
    parser.add_argument("--archive-db",
                        default="data/mining/rcm_archive.db")
    parser.add_argument("--optuna-db",
                        default="data/mining/rcm_optuna.db")
    parser.add_argument("--out-dir",
                        default="data/ml/research_miner")
    parser.add_argument("--resume", action="store_true",
                        help="Pass load_if_exists=True to Optuna")
    parser.add_argument("--min-families", type=int, default=3)
    parser.add_argument("--max-features-per-family", type=int, default=2)
    parser.add_argument("--horizon", type=int, default=21,
                        help="Forecast horizon in trading days (also used "
                             "for IC_IR annualization factor sqrt(252/h))")
    parser.add_argument("--sampler", default="tpe",
                        choices=["tpe", "random"],
                        help="Optuna sampler (R19: random for baseline check)")
    parser.add_argument("--lag", type=int, default=1,
                        help="Bars to shift composite before IC (R15: "
                             "1 prevents shared-close leakage; 0 allows "
                             "contemporaneous IC for benchmarking)")
    parser.add_argument("--config-dir", default="config")
    parser.add_argument(
        "--end-date", default=None,
        help="ISO date upper bound on panel data (e.g. 2023-12-31). "
             "Used by mining cycles that pre-register a panel cutoff per "
             "docs/memos/20260426-research_layer_partial_unfreeze.md §G4.",
    )
    parser.add_argument(
        "--drop-symbols", nargs="*", default=None,
        help="Symbols to exclude from the panel (e.g. BRK-B). Used to "
             "honor research-cycle criteria's drop_symbols list without "
             "modifying universe.yaml (which is frozen under the "
             "partial unfreeze).",
    )
    parser.add_argument(
        "--temporal-split", default=None,
        help="Path to temporal_split.yaml (Track A v1). When provided, "
             "the panel is restricted to train_years and "
             "validate_no_holdout_leakage is enforced. --role becomes "
             "REQUIRED. Mutually compatible with --end-date (split "
             "takes precedence; end-date acts as additional cap).",
    )
    parser.add_argument(
        "--role", default=None,
        help="Candidate role under the temporal split (e.g. core, "
             "diversifier). REQUIRED when --temporal-split is given. "
             "Audit guard fail_closed_if_role_unspecified_at_mining_start "
             "+ M6 C1+C2 (pre-mining lock; no post-hoc reclassification).",
    )
    # ── A+ patch 2026-04-30: pre-registered criteria yaml as source of
    # truth ─────────────────────────────────────────────────────────────
    # When --criteria-yaml is provided, the mining_config block of that
    # yaml IS the source of truth for: composite_weighting,
    # composite_cardinality, n_trials, seed, sampler, panel_end_date,
    # drop_symbols, min_families, max_features_per_family, lineage_tag.
    # Any explicit CLI flag that conflicts with the yaml value FAILS
    # CLOSED (raises SystemExit). This prevents the gap that pre-flight
    # 2026-04-30 caught: yaml asserted equal_weight + cardinality=3 but
    # miner code didn't honor those fields, so they were silently
    # decorative.
    parser.add_argument(
        "--criteria-yaml", default=None,
        help="Path to pre-registered cycle criteria yaml. When provided, "
             "yaml.mining_config is the source of truth for "
             "composite_weighting / composite_cardinality / n_trials / "
             "seed / sampler / panel_end_date / drop_symbols / "
             "min_families / max_features_per_family / lineage_tag. "
             "Any conflicting CLI flag fails closed.",
    )
    parser.add_argument(
        "--composite-weighting", default=None,
        choices=["tpe_normalized", "equal_weight"],
        help="Composite weighting scheme. Default tpe_normalized (legacy). "
             "When --criteria-yaml is provided this CLI flag must match "
             "yaml.mining_config.composite_weighting or be omitted.",
    )
    parser.add_argument(
        "--composite-cardinality", type=int, default=None,
        help="Exact post-dedup feature count. None = no enforcement. "
             "When --criteria-yaml is provided this CLI flag must match "
             "yaml.mining_config.composite_cardinality or be omitted.",
    )
    # ── A++ patch 2026-04-30: factor_registry_pool reachability contract ──
    # When --criteria-yaml asserts mining_config.factor_registry_pool ==
    # 'RESEARCH_FACTORS', the runner MUST pick FAMILIES_V2 (the only
    # family list whose union covers all 64 RESEARCH_FACTORS) and run
    # assert_reachability_matches_pool BEFORE any mining trial. This
    # closes the pre-A++ gap where FAMILIES_V1 (33 factors) silently
    # restricted the mining search space below the pre-registered pool
    # (Cand-2's anchors `ret_5d` and `hl_range` were unreachable).
    parser.add_argument(
        "--factor-registry-pool", default=None,
        choices=["RESEARCH_FACTORS", "FAMILIES_V1", "FAMILIES_V2"],
        help="Factor registry pool the sampler must cover. None = legacy "
             "FAMILIES_V1. When --criteria-yaml is provided this CLI flag "
             "must match yaml.mining_config.factor_registry_pool or be "
             "omitted (yaml is source of truth).",
    )
    # explicit_exclusions are typically expressed in the criteria yaml
    # (under mining_config.explicit_exclusions) rather than CLI; this
    # CLI flag exists for ad-hoc/testing flows. When --criteria-yaml is
    # provided, the runner reads yaml.mining_config.explicit_exclusions.
    parser.add_argument(
        "--explicit-exclusion", action="append", default=None,
        help="Factor name to exclude from the reachability + panel-"
             "availability contract (repeatable). Typically declared in "
             "criteria yaml; CLI form is for ad-hoc/testing flows.",
    )
    args = parser.parse_args()
    # Normalize explicit_exclusions: yaml is source of truth; CLI fills only
    # when yaml absent / silent.
    if args.explicit_exclusion is None:
        args.explicit_exclusions: list = []
    else:
        args.explicit_exclusions = list(args.explicit_exclusion)

    # ── Apply criteria yaml as source of truth (fail-closed mismatch) ──
    if args.criteria_yaml is not None:
        import yaml as _yaml
        crit_path = Path(args.criteria_yaml)
        if not crit_path.exists():
            raise SystemExit(
                f"--criteria-yaml path not found: {crit_path}"
            )
        crit_doc = _yaml.safe_load(crit_path.read_text())
        mc = crit_doc.get("mining_config") or {}
        cy_lineage = crit_doc.get("lineage_tag")

        # Field map: yaml key → (CLI attr, CLI cli-flag-display-name)
        # CLI default sentinel detection: argparse default values listed
        # explicitly so we can distinguish "user passed default" from
        # "user did not pass". For numeric/string defaults we do a value
        # compare; for None-default flags (composite_weighting,
        # composite_cardinality, end_date, drop_symbols) None means
        # "unspecified".
        _yaml_to_cli = [
            # (yaml_key,                      cli_attr,                   default_marker, friendly_flag_name)
            ("composite_weighting",           "composite_weighting",       None,          "--composite-weighting"),
            ("composite_cardinality",         "composite_cardinality",     None,          "--composite-cardinality"),
            ("n_trials",                      "trials",                    50,            "--trials"),
            ("seed",                          "seed",                      42,            "--seed"),
            ("sampler",                       "sampler",                   "tpe",         "--sampler"),
            ("panel_end_date",                "end_date",                  None,          "--end-date"),
            ("min_families",                  "min_families",              3,             "--min-families"),
            ("max_features_per_family",       "max_features_per_family",   2,             "--max-features-per-family"),
            # A++ patch 2026-04-30: factor_registry_pool reachability contract
            ("factor_registry_pool",          "factor_registry_pool",      None,          "--factor-registry-pool"),
        ]
        mismatches: list[str] = []
        for yaml_key, cli_attr, default, flag_name in _yaml_to_cli:
            yaml_val = mc.get(yaml_key)
            cli_val = getattr(args, cli_attr)
            if yaml_val is None:
                continue  # yaml didn't specify this field
            # CLI explicitly set (non-default) AND non-equal → mismatch
            if cli_val != default and cli_val != yaml_val:
                mismatches.append(
                    f"  {flag_name}={cli_val!r} conflicts with "
                    f"yaml.mining_config.{yaml_key}={yaml_val!r}"
                )
            # Override default with yaml value
            if cli_val == default or cli_val is None:
                setattr(args, cli_attr, yaml_val)

        # PRD-AC v1.1 §4.7: objective_version + objective_weights from yaml.
        # `objective_version` is informational (recorded in archive +
        # closeout memo); `objective_weights` is the actual ObjectiveWeights
        # dict consumed by ResearchMiner. Default = v1_legacy + empty dict
        # → ObjectiveWeights() default constructor → cycle04/05 backward
        # compat preserved bit-for-bit.
        yaml_obj_version = mc.get("objective_version") or "v1_legacy"
        yaml_obj_weights = mc.get("objective_weights")
        if yaml_obj_weights is not None and not isinstance(yaml_obj_weights, dict):
            mismatches.append(
                f"  yaml.mining_config.objective_weights must be a dict, got "
                f"{type(yaml_obj_weights).__name__}"
            )
            yaml_obj_weights = None
        if yaml_obj_weights is None:
            yaml_obj_weights = {}
        # Cross-check: v2_nav_based version must have at least one
        # w_nav_* > 0; v1_legacy must have all w_nav_* == 0 (or absent).
        nav_weight_keys = (
            "w_nav_sharpe", "w_nav_max_dd_penalty",
            "w_nav_orthogonality", "w_vs_qqq_excess",
        )
        any_nav_nonzero = any(
            float(yaml_obj_weights.get(k, 0.0)) != 0.0 for k in nav_weight_keys
        )
        if yaml_obj_version == "v2_nav_based" and not any_nav_nonzero:
            mismatches.append(
                "  yaml.mining_config.objective_version='v2_nav_based' "
                "requires at least one of "
                f"{nav_weight_keys} to be non-zero"
            )
        if yaml_obj_version == "v1_legacy" and any_nav_nonzero:
            mismatches.append(
                "  yaml.mining_config.objective_version='v1_legacy' "
                "requires all w_nav_* weights to be 0 (or absent); "
                "found non-zero NAV weights — set objective_version="
                "'v2_nav_based' to opt into NAV objective"
            )
        # PRD-AC v1.1 §4.5 Phase 3 round 1 search-space yaml fields:
        # - holding_freq_choices: list[str] subset of {daily, weekly, monthly}
        # - enable_sr_defer_choices: list[bool] (round 1 only [false])
        # Both default None / [false] preserves cycle04/05 legacy 2-dim
        # search behavior bit-for-bit.
        yaml_holding_choices = mc.get("holding_freq_choices")
        if yaml_holding_choices is not None:
            if not isinstance(yaml_holding_choices, list) or any(
                v not in ("daily", "weekly", "monthly")
                for v in yaml_holding_choices
            ):
                mismatches.append(
                    "  yaml.mining_config.holding_freq_choices must be a list "
                    "of {'daily','weekly','monthly'} subsets, got "
                    f"{yaml_holding_choices!r}"
                )
                yaml_holding_choices = None
        yaml_sr_choices = mc.get("enable_sr_defer_choices")
        if yaml_sr_choices is not None:
            if (
                not isinstance(yaml_sr_choices, list)
                or any(not isinstance(v, bool) for v in yaml_sr_choices)
            ):
                # Master PRD §4.2 Phase B.2 (R4 ship 2026-05-07): True is
                # now a legal choice. ResearchMiner constructor enforces
                # the contract that intraday_bars_60m must be supplied
                # when True is sampled. The CLI ban on True (Phase 3
                # round 1 stub) was lifted with the R4 commit.
                mismatches.append(
                    "  yaml.mining_config.enable_sr_defer_choices must be a "
                    f"list of bools, got {yaml_sr_choices!r}"
                )
                yaml_sr_choices = None
        # Stash for later use after mismatches block
        args._objective_version = yaml_obj_version
        args._objective_weights_dict = yaml_obj_weights
        args._holding_freq_choices = yaml_holding_choices
        args._enable_sr_defer_choices = yaml_sr_choices or [False]

        # explicit_exclusions: yaml mining_config.explicit_exclusions list.
        # When yaml lists exclusions and CLI ALSO lists exclusions, fail-
        # closed unless they match exactly (yaml is source of truth).
        yaml_excl = mc.get("explicit_exclusions") if isinstance(mc.get("explicit_exclusions"), list) else None
        if yaml_excl is not None:
            if args.explicit_exclusions and set(args.explicit_exclusions) != set(yaml_excl):
                mismatches.append(
                    f"  --explicit-exclusion={sorted(args.explicit_exclusions)!r} conflicts with "
                    f"yaml.mining_config.explicit_exclusions={sorted(yaml_excl)!r}"
                )
            args.explicit_exclusions = list(yaml_excl)

        # drop_symbols: yaml is a list; CLI default is None
        yaml_drop = mc.get("drop_symbols") if isinstance(mc.get("drop_symbols"), list) else None
        # Fall back to universe_panel_mask_spec.drop_symbols (cycle #01 yaml schema)
        if yaml_drop is None:
            ums = (crit_doc.get("hard_requirements") or {}).get("universe_panel_mask_spec") or {}
            ymd = ums.get("drop_symbols")
            if isinstance(ymd, list):
                yaml_drop = ymd
        if yaml_drop is not None:
            if args.drop_symbols is not None and args.drop_symbols != yaml_drop:
                mismatches.append(
                    f"  --drop-symbols={args.drop_symbols!r} conflicts with "
                    f"yaml.drop_symbols={yaml_drop!r}"
                )
            if args.drop_symbols is None:
                args.drop_symbols = yaml_drop

        # lineage_tag: yaml is source of truth for naming
        if cy_lineage is not None:
            if args.lineage != "post-2026-04-24-rcm-v1" and args.lineage != cy_lineage:
                mismatches.append(
                    f"  --lineage={args.lineage!r} conflicts with "
                    f"yaml.lineage_tag={cy_lineage!r}"
                )
            if args.lineage == "post-2026-04-24-rcm-v1":
                args.lineage = cy_lineage

        if mismatches:
            raise SystemExit(
                "criteria-yaml / CLI mismatch (fail-closed per A+ patch "
                "2026-04-30):\n" + "\n".join(mismatches) + "\n"
                "Resolution: omit the conflicting CLI flag (yaml is "
                "source of truth) OR use a different yaml."
            )

        logger.info(
            "Criteria yaml loaded as source of truth: lineage=%s "
            "composite_weighting=%s composite_cardinality=%s trials=%d "
            "seed=%d sampler=%s end_date=%s drop_symbols=%s",
            cy_lineage, args.composite_weighting, args.composite_cardinality,
            args.trials, args.seed, args.sampler, args.end_date,
            args.drop_symbols,
        )

    # CLI defaults stay for non-yaml mining (legacy flow): if
    # composite_weighting still None after potential yaml override,
    # default to legacy tpe_normalized.
    if args.composite_weighting is None:
        args.composite_weighting = "tpe_normalized"

    study_id = args.study or (
        "rcm-v1-run-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    )
    logger.info("Study: %s  Lineage: %s  Trials: %d  Seed: %d",
                study_id, args.lineage, args.trials, args.seed)

    cfg = load_config(Path(args.config_dir))
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))

    # Track A: temporal split discipline. Mutually exclusive precondition:
    # --temporal-split requires --role; --role without --temporal-split
    # is silently ignored (legacy mining flow).
    split_cfg = None
    split_sha256 = None
    if args.temporal_split:
        split_cfg = load_temporal_split(Path(args.temporal_split))
        split_sha256 = compute_split_sha256(Path(args.temporal_split))
        # M6 C1+C2 + audit guard fail_closed_if_role_unspecified_at_mining_start
        ensure_role_assigned(args.role, split_cfg)
        logger.info(
            "Temporal split active: %s (sha256=%s) role=%s",
            split_cfg.split_name, split_sha256[:16], args.role,
        )

    logger.info("Loading price/volume frames...")
    if args.end_date:
        logger.info("Panel end_date cap: %s (G4 cutoff)", args.end_date)
    if args.drop_symbols:
        logger.info("Drop symbols: %s (criteria yaml drop_symbols)",
                    args.drop_symbols)
    frames, tradable = _load_price_volume(
        cfg, store,
        end_date=args.end_date,
        drop_symbols=args.drop_symbols,
    )

    # Track A: restrict panel to train years + validate no holdout leakage
    panel_max_date = None
    if split_cfg is not None:
        n_pre = frames["close"].shape[0]
        frames = restrict_frames_to_train(frames, split_cfg)
        validate_no_holdout_leakage(frames, split_cfg)
        n_post = frames["close"].shape[0]
        logger.info(
            "Temporal split filter: %d → %d rows (dropped %d holdout-year rows)",
            n_pre, n_post, n_pre - n_post,
        )
        pmd = compute_panel_max_date(frames)
        panel_max_date = pmd.isoformat() if pmd is not None else None
        logger.info("Panel max date (post-split): %s", panel_max_date)

    n_syms = frames["close"].shape[1]
    n_dates = frames["close"].shape[0]
    logger.info("Panel: %d dates × %d symbols (%d tradable)",
                n_dates, n_syms, len(tradable))

    logger.info("Generating factors (this takes 1-2 min)...")
    panel_map, fwd_h, mask, n_masked = _build_factor_panel_map(
        frames, tradable, horizon=args.horizon, split_cfg=split_cfg,
    )
    if split_cfg is not None:
        logger.info(
            "purge_labels_at_boundary: applied (split=%s, horizon_max=%dd)",
            split_cfg.split_name,
            split_cfg.acceptance.purge_rules.label_horizon_days_max,
        )
    # A++ patch 2026-04-30: select family list per factor_registry_pool
    # contract. None → FAMILIES_V1 (legacy, 33 factors). Cycle 2026-04-30
    # #01 yaml asserts RESEARCH_FACTORS → FAMILIES_V2 (64 factors).
    if args.factor_registry_pool is None:
        active_families = FAMILIES_V1
        active_pool_label = "FAMILIES_V1 (legacy, no pool contract)"
    else:
        active_families = families_for_pool(args.factor_registry_pool)
        active_pool_label = args.factor_registry_pool
        # Pre-flight reachability assert (fail-closed on contract mismatch).
        # explicit_exclusions are factors the criteria yaml acknowledges
        # are unreachable (e.g., data-dependency not yet wired) — they're
        # subtracted from the expected pool for the assertion.
        assert_reachability_matches_pool(
            pool_name=args.factor_registry_pool,
            families=active_families,
            explicit_exclusions=args.explicit_exclusions or None,
        )
        logger.info(
            "factor_registry_pool=%s reachability preflight PASS (%d factors "
            "reachable across %d families; %d explicit_exclusions)",
            args.factor_registry_pool,
            len(all_family_factors(active_families)),
            len(active_families),
            len(args.explicit_exclusions or []),
        )
        if args.explicit_exclusions:
            logger.info(
                "explicit_exclusions: %s (data-dependency not satisfied "
                "in this pipeline)",
                sorted(args.explicit_exclusions),
            )
    family_factor_names = all_family_factors(active_families)
    # A++ patch 2026-04-30: panel-availability assertion. The reachability
    # preflight above only checks sampler→family→factor coverage. It does
    # NOT check that each reachable factor actually has a generated panel
    # in `panel_map`. R3 audit caught the case where 3 intraday-dependent
    # factors are in RESEARCH_FACTORS + FAMILIES_V2 but the daily-mining
    # panel pipeline doesn't compute their panels — every TPE trial that
    # picks one of those factors fails KeyError downstream. Fail-closed
    # here so the operator notices BEFORE the mining run rather than
    # after 200 pruned trials.
    if args.factor_registry_pool is not None:
        excl_set = set(args.explicit_exclusions or ())
        expected_in_panel = family_factor_names - excl_set
        unavailable = sorted(expected_in_panel - set(panel_map))
        if unavailable:
            raise SystemExit(
                "Panel-availability contract violation (A++ patch 2026-04-30):\n"
                f"  factor_registry_pool={args.factor_registry_pool}\n"
                f"  Sampler can reach: {len(family_factor_names)} factors\n"
                f"  Panel pipeline produced: {len(panel_map)} factors\n"
                f"  Unreachable due to missing panel ({len(unavailable)}): "
                f"{unavailable}\n"
                "Resolution: either (a) wire the factor pipeline to "
                "produce these panels, or (b) declare them under criteria "
                "yaml mining_config.explicit_exclusions with a documented "
                "data-dependency reason."
            )
    missing = family_factor_names - set(panel_map)
    if missing:
        logger.warning(
            "Family factors not present in panel_map — sampler will still "
            "generate but evaluate will raise KeyError on those: %s",
            sorted(missing),
        )
    panel_feature_count = len(panel_map)
    logger.info(
        "factor_panel_map: %d factors; 12 PRD features in catalog: %s",
        panel_feature_count,
        all(f in panel_map for f in [
            "rel_spy_20d", "rel_qqq_20d", "beta_spy_60d",
            "residual_mom_spy_20d", "range_pos_252d", "days_since_52w_high",
            "breakout_20d_strength", "dist_from_new_high_252",
            "amihud_20d", "downside_vol_20d", "vol_ratio_5_20",
            "trend_tstat_20d",
        ]),
    )
    if n_masked is not None:
        logger.info("Research mask: %d bar-symbol cells masked out", n_masked)

    logger.info("Opening archive: %s", args.archive_db)
    archive = RCMArchive(args.archive_db)

    # Master PRD §4.2 Phase B.2 (R4 ship 2026-05-07): SR defer mining
    # integration. When the yaml's enable_sr_defer_choices contains True,
    # load 60m bars for the tradable universe via BarStore so the filter
    # has a per-symbol panel to evaluate. CLI flow only — direct
    # ResearchMiner construction must supply intraday_bars_60m on its own.
    intraday_bars_60m: dict[str, "pd.DataFrame"] | None = None
    sr_defer_choices = getattr(args, "_enable_sr_defer_choices", [False])
    if True in tuple(sr_defer_choices):
        logger.info(
            "Loading 60m bars for SR defer mining (yaml "
            "enable_sr_defer_choices contains True)..."
        )
        from core.data.bar_store import BarStore
        bar_store = BarStore(root=Path(cfg.system.paths.data_dir))
        intraday_bars_60m = {}
        bar_load_syms = list(frames["close"].columns)
        for sym in bar_load_syms:
            try:
                df = bar_store.load(sym, freq="60m")
            except Exception:  # noqa: BLE001
                df = None
            if df is None or len(df) == 0:
                continue
            intraday_bars_60m[sym] = df
        logger.info(
            "60m bars loaded for %d / %d symbols (missing symbols pass "
            "through unchanged inside apply_sr_defer_filter as "
            "n_skipped_no_60m_coverage)",
            len(intraday_bars_60m), len(bar_load_syms),
        )

    logger.info("Building ResearchMiner with %s...", active_pool_label)
    miner = ResearchMiner(
        factor_panel_map=panel_map,
        fwd_returns=fwd_h,
        mask=mask,
        families=active_families,
        objective_weights=ObjectiveWeights(
            **getattr(args, "_objective_weights_dict", {})
        ),
        # PRD-AC v1.1 §4.3 NAV gate panels. Required when objective_version=
        # v2_nav_based (any w_nav_* > 0). Constructor validates and fails
        # closed if v2_nav_based + missing panels (cycle04/05 v1_legacy
        # mining unaffected: ObjectiveWeights() defaults all w_nav_*=0).
        # SPY / QQQ are extracted from frames["close"]; the universe panel
        # excludes them so the equal-weight anchor baseline is computed on
        # the tradable universe only.
        price_df=frames["close"].drop(
            columns=["SPY", "QQQ"], errors="ignore",
        ),
        open_df=(
            frames["open"].drop(columns=["SPY", "QQQ"], errors="ignore")
            if frames["open"] is not None else None
        ),
        spy_series=(
            frames["close"]["SPY"] if "SPY" in frames["close"].columns else None
        ),
        qqq_series=(
            frames["close"]["QQQ"] if "QQQ" in frames["close"].columns else None
        ),
        # PRD-AC v1.1 §4.5 Phase 3 round 1: search-space dims from yaml.
        # Default None / (False,) preserves cycle04/05 legacy behavior.
        holding_freq_choices=getattr(args, "_holding_freq_choices", None),
        enable_sr_defer_choices=tuple(
            getattr(args, "_enable_sr_defer_choices", [False])
        ),
        # Master PRD §4.2 Phase B.2 (R4 ship 2026-05-07): 60m bar dict
        # required when SR defer choices contains True.
        intraday_bars_60m=intraday_bars_60m,
        min_families=args.min_families,
        max_features_per_family=args.max_features_per_family,
        composite_weighting=args.composite_weighting,
        target_n_features=args.composite_cardinality,
        horizon=args.horizon,
        lag=args.lag,
        archive=archive,
        lineage_tag=args.lineage,
        study_id=study_id,
        # Track A v1 fingerprint threading (None when --temporal-split absent)
        split_name=(split_cfg.split_name if split_cfg is not None else None),
        split_sha256=split_sha256,
        panel_max_date=panel_max_date,
        role=(args.role if split_cfg is not None else None),
        max_factor_lookback_days=(
            split_cfg.access_rules.factor_warmup_max_lookback_days
            if split_cfg is not None else None
        ),
        # A++ patch 2026-04-30: pool contract carried into miner for
        # archive provenance + a redundant constructor-level reachability
        # assert (defense-in-depth vs caller bypassing the runner).
        factor_registry_pool=args.factor_registry_pool,
        explicit_exclusions=(args.explicit_exclusions or None),
    )

    logger.info(
        "Starting mining (Optuna storage: sqlite:///%s, study=%s, resume=%s)",
        args.optuna_db, study_id, args.resume,
    )
    optuna_storage = f"sqlite:///{args.optuna_db}"
    Path(args.optuna_db).parent.mkdir(parents=True, exist_ok=True)

    results = miner.mine(
        n_trials=args.trials, seed=args.seed,
        sampler=args.sampler,
        optuna_storage=optuna_storage, study_name=study_id,
        load_if_exists=args.resume,
    )
    logger.info("Completed: %d finite-objective trials (of %d attempted)",
                len(results), args.trials)

    # Report top-3 in-memory for immediate feedback
    for i, r in enumerate(results[:3], start=1):
        logger.info(
            "  #%d obj=%+.4f  IR=%+.3f  corr=%.3f  turn=%.3f  n_feat=%d  families=%s",
            i, r.objective, r.metrics.ic_ir,
            r.metrics.corr_concentration, r.metrics.turnover_proxy,
            r.spec.n_features, dict(r.spec.family_counts),
        )

    # Write artifacts
    out_root = Path(args.out_dir) / study_id
    temporal_split_metadata = None
    if split_cfg is not None:
        temporal_split_metadata = {
            "split_name": split_cfg.split_name,
            "split_sha256": split_sha256,
            "split_yaml_path": str(args.temporal_split),
            "role": args.role,
            "panel_max_date": panel_max_date,
            "train_year_count": len(
                [y for y in range(2007, 2027)
                 if y in {x for entry in split_cfg.partition.train_years
                          for x in (range(entry.range[0], entry.range[1] + 1)
                                    if hasattr(entry, "range") else [entry.year])}]
            ),
        }
    _write_artifacts(
        out_root, study_id, args.lineage, results, archive,
        config_snapshot={
            "trials": args.trials, "seed": args.seed,
            "min_families": args.min_families,
            "max_features_per_family": args.max_features_per_family,
            "n_syms": int(n_syms), "n_dates": int(n_dates),
            "n_factors_in_panel": panel_feature_count,
            "fwd_return_horizon_days": int(args.horizon),
            "fwd_return_mode": "cc",
            "composite_lag_bars": int(args.lag),
            # A++ patch 2026-04-30: factor_registry_pool provenance for
            # any consumer of the run_summary.json artifact.
            "factor_registry_pool": args.factor_registry_pool,
            "n_families_active": len(active_families),
            "n_factors_reachable_via_families": len(family_factor_names),
            "explicit_exclusions": list(args.explicit_exclusions or []),
        },
        temporal_split_metadata=temporal_split_metadata,
    )

    print("=" * 70)
    print(f"Research Composite Miner v1 — {study_id}")
    print(f"Lineage: {args.lineage}  Trials: {args.trials}")
    print("=" * 70)
    if results:
        print(f"Best objective: {results[0].objective:+.4f}")
        print(f"Best IC_IR:     {max(r.metrics.ic_ir for r in results):+.4f}")
        print(f"Archive rows under lineage: "
              f"{archive.n_trials(lineage_tag=args.lineage)}")
    else:
        print("No finite-objective trials (all pruned or failed).")
    print(f"\nArtifacts: {out_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
