#!/usr/bin/env python3
"""Compare structured, lexical, combined and shuffled SEC event features."""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
import yaml

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

from core.research.dynamic_universe import (  # noqa: E402
    DynamicEligibilityConfig,
    build_dynamic_eligibility_mask,
)
from core.research.ml.pipeline import WalkForwardConfig  # noqa: E402
from core.research.ml.rank_model import LinearBaselineRankModel  # noqa: E402
from core.research.ml.xgb_rank_model import XGBRankerRankModel  # noqa: E402
from core.research.oof_rank_mining import run_oof_rank_mining  # noqa: E402
from core.research.sec_event_features import (  # noqa: E402
    build_lexical_event_panel,
    build_structured_event_panel,
    event_eligibility_from_previous_close,
    make_event_open_to_close_residual_rank_labels,
)
from core.research.trial_ledger import AppendOnlyTrialLedger  # noqa: E402
from dev.scripts.mining_v4.run_numeric_rank_mining import (  # noqa: E402
    _atomic_json,
    _atomic_parquet,
    _git_commit,
    _hash_price_inputs,
    _load_panel,
    _portfolio_trial_intent,
    _sha256_file,
    _sha256_json,
    _validate_snapshot_manifest,
)
from dev.scripts.mining_v4.run_sec_structured_event_mining import (  # noqa: E402
    _validate_corpus,
)


def _finite(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _finite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(item) for item in value]
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def _load_lexical_artifact(root: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    manifest_path = root / "manifest.json"
    features_path = root / "lexical_features.parquet"
    manifest = json.loads(manifest_path.read_text())
    if _sha256_file(features_path) != manifest.get("features_sha256"):
        raise RuntimeError("lexical features hash differs from manifest")
    features = pd.read_parquet(features_path)
    feature_names = list(manifest.get("feature_names", []))
    if not feature_names or not set(feature_names).issubset(features.columns):
        raise RuntimeError("lexical manifest feature list is invalid")
    return features, {
        "artifact_id": manifest.get("artifact_id"),
        "manifest_sha256": _sha256_file(manifest_path),
        "features_sha256": manifest.get("features_sha256"),
        "document_manifest_sha256": manifest.get("document_manifest_sha256"),
        "filing_manifest_sha256": manifest.get("filing_manifest_sha256"),
        "documents": manifest.get("documents"),
        "parse_pass": manifest.get("parse_pass"),
        "parse_missing": manifest.get("parse_missing"),
        "parse_pass_fraction": manifest.get("parse_pass_fraction"),
        "parser_module_sha256": manifest.get("parser_module_sha256"),
        "feature_names": feature_names,
    }


def _prefixed(
    prefix: str,
    features: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    return {f"{prefix}{name}": frame for name, frame in features.items()}


def _shuffle_feature_bundles(
    features: dict[str, pd.DataFrame],
    eligibility: pd.DataFrame,
    *,
    seed: int,
) -> dict[str, pd.DataFrame]:
    """Shuffle entire text bundles within each event cohort, never across time."""

    output = {name: frame.copy() for name, frame in features.items()}
    rng = np.random.default_rng(seed)
    for date in eligibility.index:
        symbols = eligibility.columns[eligibility.loc[date].to_numpy()]
        if len(symbols) < 2:
            continue
        permutation = rng.permutation(len(symbols))
        for name, frame in features.items():
            values = frame.loc[date, symbols].to_numpy(copy=True)
            output[name].loc[date, symbols] = values[permutation]
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--filing-corpus-root", required=True)
    parser.add_argument("--lexical-artifact-root", required=True)
    parser.add_argument(
        "--pool", default="research/universes/semantic_ml_company_pool_v1.json")
    parser.add_argument("--config", default="config/strategy_mining_v4.yaml")
    parser.add_argument("--report", required=True)
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--ledger", required=True)
    args = parser.parse_args()

    data_root = Path(args.data_root).resolve()
    filing_root = Path(args.filing_corpus_root).resolve()
    lexical_root = Path(args.lexical_artifact_root).resolve()
    pool = json.loads((PROJ / args.pool).read_text())
    config_path = (PROJ / args.config).resolve()
    config = yaml.safe_load(config_path.read_text())
    candidates = [row["ticker"] for row in pool["selected"]]
    all_symbols = candidates + ["SPY"]
    start_year = 2015
    end_year = int(config["models"]["development_end_year"])
    load_end = f"{end_year}-12-31"
    holding_sessions = 5
    seed = int(config["models"]["seed"])
    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ledger = AppendOnlyTrialLedger(Path(args.ledger).resolve())

    print("[1/5] validating price, SEC metadata, and lexical hash chains")
    panel_all, missing = _load_panel(
        data_root, all_symbols, start="2007-01-01", end=load_end,
        total_return=False)
    if missing:
        raise RuntimeError(f"price snapshot missing symbols: {missing}")
    snapshot_evidence = _validate_snapshot_manifest(
        data_root,
        pool_hash=pool["artifact_sha256"],
        symbols=all_symbols,
        through=load_end,
    )
    metadata, corpus_evidence = _validate_corpus(
        filing_root,
        pool_hash=pool["artifact_sha256"],
        expected_ciks={int(row["cik"]) for row in pool["selected"]},
    )
    lexical_rows, lexical_evidence = _load_lexical_artifact(lexical_root)
    if lexical_evidence["filing_manifest_sha256"] != corpus_evidence[
        "manifest_sha256"
    ]:
        raise RuntimeError(
            "lexical document chain points to a different SEC filing corpus")

    print("[2/5] building same-cohort structured/text/shuffled panels")
    candidate_panel = {
        name: frame.loc[:, candidates] for name, frame in panel_all.items()
    }
    eligibility_doc = config["dynamic_eligibility"]
    daily_eligibility = build_dynamic_eligibility_mask(
        candidate_panel["close"], candidate_panel["volume"],
        DynamicEligibilityConfig(
            min_history_sessions=int(eligibility_doc["min_history_sessions"]),
            lookback_sessions=int(eligibility_doc["lookback_sessions"]),
            min_observation_density=float(
                eligibility_doc["min_observation_density"]),
            min_price=float(eligibility_doc["min_price"]),
            min_median_dollar_volume=float(
                eligibility_doc["min_median_dollar_volume"]),
        ),
    )
    structured = build_structured_event_panel(
        metadata, panel_all["close"].index, candidates,
        development_start=f"{start_year}-01-01", development_end=load_end)
    lexical = build_lexical_event_panel(
        structured,
        lexical_rows,
        candidates,
        lexical_feature_names=lexical_evidence["feature_names"],
    )
    labels_all = make_event_open_to_close_residual_rank_labels(
        candidate_panel["open"], candidate_panel["close"],
        panel_all["open"]["SPY"], panel_all["close"]["SPY"],
        structured.event_mask,
        holding_sessions=holding_sessions,
        beta_window_sessions=int(config["models"]["beta_window_sessions"]),
    )
    eligibility = event_eligibility_from_previous_close(
        daily_eligibility, lexical.event_mask)
    labels = labels_all.reindex(eligibility.index).where(eligibility)
    eligibility &= labels.notna()
    cohort_ok = eligibility.sum(axis=1) >= 3
    dates = eligibility.index[cohort_ok]
    eligibility = eligibility.loc[dates]
    labels = labels.loc[dates].where(eligibility)
    structured_features = {
        name: frame.reindex(index=dates, columns=candidates)
        for name, frame in structured.features.items()
    }
    lexical_features = {
        name: frame.reindex(index=dates, columns=candidates)
        for name, frame in lexical.features.items()
    }
    shuffled = _shuffle_feature_bundles(
        lexical_features, eligibility, seed=seed)
    feature_sets = {
        "structured_same_8k_cohort": _prefixed(
            "structured__", structured_features),
        "lexical_only": _prefixed("lexical__", lexical_features),
        "structured_plus_lexical": {
            **_prefixed("structured__", structured_features),
            **_prefixed("lexical__", lexical_features),
        },
        "structured_plus_shuffled_lexical": {
            **_prefixed("structured__", structured_features),
            **_prefixed("shuffled_lexical__", shuffled),
        },
    }
    cohort_cells = int(eligibility.to_numpy().sum())
    if cohort_cells < 1000 or len(dates) < 250:
        raise RuntimeError(
            f"insufficient lexical cohorts: dates={len(dates)} cells={cohort_cells}")
    print(
        f"  lexical_docs_joined={lexical.joined_filing_records} "
        f"cohort_dates={len(dates)} cohort_cells={cohort_cells}")

    print("[3/5] running OOF ablations")
    walk_config = WalkForwardConfig(
        start_year=start_year,
        end_year=end_year,
        train_window_years=int(config["models"]["train_window_years"]),
        val_window_years=int(config["models"]["validation_window_years"]),
        step_years=int(config["models"]["step_years"]),
        embargo_days=holding_sessions,
    )
    model_factories: dict[str, Callable] = {
        "linear_rank": LinearBaselineRankModel,
        "xgb_rank_ndcg": lambda: XGBRankerRankModel(
            n_estimators=100, max_depth=3, learning_rate=0.05,
            objective="rank:ndcg", random_state=seed),
    }
    price_hash, files_hashed = _hash_price_inputs(data_root, all_symbols)
    data_hash = _sha256_json({
        "price": price_hash,
        "filings": corpus_evidence["manifest_sha256"],
        "lexical": lexical_evidence["manifest_sha256"],
    })
    commit = _git_commit()
    config_hash = _sha256_file(config_path)
    model_reports: dict[str, Any] = {}
    predictions: dict[str, pd.DataFrame] = {}
    for feature_set_name, model_features in feature_sets.items():
        for model_type, factory in model_factories.items():
            model_name = f"{feature_set_name}__{model_type}"
            trial_id = f"{run_stamp}-{model_name}-signal"
            feature_id = _sha256_json(sorted(model_features))
            registration = ledger.register_intent(_portfolio_trial_intent(
                trial_id=trial_id,
                model_name=model_name,
                construction="sec_8k_lexical_ablation_rank_only",
                cost_bps=0.0,
                universe_hash=pool["artifact_sha256"],
                data_hash=data_hash,
                config_hash=config_hash,
                code_commit=commit,
                feature_id=feature_id,
                start=f"{start_year}-01-01",
                end=load_end,
                observed_through=str(config["observed_through"]),
                seed=seed,
                hypothesis_family="sec_8k_lexical_event_rank_signal",
                execution_id="next_session_open_after_sec_acceptance",
            ))
            result = run_oof_rank_mining(
                factory, walk_config, model_features, labels, eligibility,
                daily_trading_index=panel_all["close"].index,
                cluster_features=True,
                correlation_threshold=float(
                    config["models"]["feature_correlation_threshold"]),
                sealed_years=(2025, 2026),
            )
            successful = [fold for fold in result.folds if fold.error is None]
            summary = {
                "feature_set": feature_set_name,
                "model_type": model_type,
                "independent_trial": registration.independent_trial,
                "successful_folds": result.successful_folds,
                "mean_rank_ic": (
                    float(np.mean([fold.rank_ic for fold in successful]))
                    if successful else None),
                "mean_rank_ir": (
                    float(np.mean([fold.rank_ir for fold in successful]))
                    if successful else None),
                "positive_rank_ic_fold_fraction": (
                    float(np.mean([fold.rank_ic > 0 for fold in successful]))
                    if successful else None),
                "folds": [asdict(fold) for fold in result.folds],
            }
            model_reports[model_name] = _finite(summary)
            predictions[model_name] = result.predictions
            ledger.record_outcome(trial_id, _finite(summary))
            print(
                f"  {model_name}: {result.successful_folds}/"
                f"{len(result.folds)} mean_ic={summary['mean_rank_ic']}")

    print("[4/5] publishing non-null OOF predictions")
    prediction_long = pd.concat({
        model: frame.stack().dropna().rename("score")
        for model, frame in predictions.items()
    }, names=["model", "date", "symbol"]).reset_index()
    predictions_path = Path(args.predictions).resolve()
    _atomic_parquet(prediction_long, predictions_path)

    print("[5/5] publishing lexical ablation report")
    report = {
        "schema_version": 1,
        "run_id": f"governed-sec-lexical-{run_stamp}",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "code_commit": commit,
        "evidence_scope": "DEVELOPMENT_ONLY",
        "automatic_promotion_eligible": False,
        "historical_oos_claim_allowed": False,
        "llm_or_frozen_encoder_used": False,
        "stage": "LEXICAL_8K_ABLATION",
        "snapshot_evidence": snapshot_evidence,
        "corpus_evidence": corpus_evidence,
        "lexical_evidence": lexical_evidence,
        "pricing": {
            "feature_availability": "SEC acceptanceDateTime",
            "execution_contract": "strictly next exchange session open",
            "label": "open_to_fifth_session_close_market_residual_rank",
            "basis": "split_adjusted_price_return",
            "portfolio_evaluation": "NOT_RUN_TOTAL_RETURN_COVERAGE_BLOCKED",
        },
        "coverage": {
            "lexical_filing_records_joined": lexical.joined_filing_records,
            "cohort_dates_at_least_three": len(dates),
            "cohort_cells": cohort_cells,
            "cohort_cells_by_year": {
                str(year): int(
                    eligibility.loc[eligibility.index.year == year]
                    .to_numpy().sum())
                for year in sorted(set(eligibility.index.year))
            },
        },
        "ablation_models": model_reports,
        "predictions": {
            "path": str(predictions_path),
            "sha256": _sha256_file(predictions_path),
            "rows": len(prediction_long),
        },
        "data_input_sha256": data_hash,
        "data_files_hashed": files_hashed,
        "trial_ledger": {
            "path": str(Path(args.ledger).resolve()),
            "independent_trials": ledger.independent_trial_count(
                "sec_8k_lexical_event_rank_signal"),
            "incomplete_trial_ids": ledger.incomplete_trial_ids(),
        },
        "disposition": "LEXICAL_SIGNAL_DIAGNOSTIC_ONLY",
    }
    _atomic_json(_finite(report), Path(args.report).resolve())
    print(f"report={Path(args.report).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
