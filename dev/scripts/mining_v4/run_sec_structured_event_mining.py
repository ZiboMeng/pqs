#!/usr/bin/env python3
"""Run governed structured SEC-event rank baselines without filing text."""

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
    build_structured_event_panel,
    event_eligibility_from_previous_close,
    make_event_open_to_close_residual_rank_labels,
)
from core.research.trial_ledger import AppendOnlyTrialLedger  # noqa: E402
from dev.scripts.mining_v4.run_numeric_rank_mining import (  # noqa: E402
    EXACT_CASH_PRICE_BASIS,
    _atomic_json,
    _atomic_parquet,
    _git_commit,
    _hash_price_inputs,
    _load_exact_cash_panel,
    _load_panel,
    _portfolio_trial_intent,
    _sha256_file,
    _sha256_json,
    _validate_snapshot_manifest,
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


def _validate_corpus(
    corpus_root: Path,
    *,
    pool_hash: str,
    expected_ciks: set[int],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    manifest_path = corpus_root / "manifest.json"
    metadata_path = corpus_root / "filing_metadata.parquet"
    provenance_path = corpus_root / "response_provenance.parquet"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("pool_artifact_sha256") != pool_hash:
        raise RuntimeError("SEC corpus pool hash differs from frozen pool")
    if _sha256_file(metadata_path) != manifest.get("metadata_sha256"):
        raise RuntimeError("SEC filing metadata hash differs from manifest")
    if _sha256_file(provenance_path) != manifest.get(
        "response_provenance_sha256"
    ):
        raise RuntimeError("SEC response provenance hash differs from manifest")
    provenance = pd.read_parquet(provenance_path)
    if set(provenance["cik"].astype(int)) != expected_ciks:
        raise RuntimeError("SEC response CIK set differs from frozen pool")
    if not provenance["http_status"].eq(200).all():
        raise RuntimeError("SEC corpus contains a non-200 response")
    for row in provenance.itertuples(index=False):
        raw_relative_path = getattr(row, "raw_relative_path", None)
        raw = (
            corpus_root / str(raw_relative_path)
            if raw_relative_path
            else corpus_root / "raw_submissions" / f"CIK{int(row.cik):010d}.json"
        )
        if _sha256_file(raw) != row.response_sha256:
            raise RuntimeError(f"SEC raw response hash mismatch for CIK {row.cik}")
    metadata = pd.read_parquet(metadata_path)
    return metadata, {
        "corpus_id": manifest.get("corpus_id"),
        "manifest_sha256": _sha256_file(manifest_path),
        "metadata_sha256": manifest.get("metadata_sha256"),
        "response_provenance_sha256": manifest.get(
            "response_provenance_sha256"),
        "raw_responses_verified": len(provenance),
        "selected_filings_raw": len(metadata),
        "builder_commit": manifest.get("builder_commit"),
        "evidence_scope": manifest.get("evidence_scope"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument(
        "--pool", default="research/universes/semantic_ml_company_pool_v1.json")
    parser.add_argument("--config", default="config/strategy_mining_v4.yaml")
    parser.add_argument("--report", required=True)
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--ledger", required=True)
    args = parser.parse_args()

    data_root = Path(args.data_root).resolve()
    corpus_root = Path(args.corpus_root).resolve()
    pool_path = (PROJ / args.pool).resolve()
    config_path = (PROJ / args.config).resolve()
    pool = json.loads(pool_path.read_text())
    config = yaml.safe_load(config_path.read_text())
    pool_candidates = [row["ticker"] for row in pool["selected"]]
    snapshot_manifest = json.loads((data_root / "manifest.json").read_text())
    excluded_candidates = sorted(snapshot_manifest.get("excluded_symbols", []))
    candidates = [
        symbol for symbol in pool_candidates if symbol not in excluded_candidates
    ]
    all_symbols = candidates + ["SPY"]
    development_start_year = 2015
    development_end_year = int(config["models"]["development_end_year"])
    load_end = f"{development_end_year}-12-31"
    holding_sessions = 5
    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ledger = AppendOnlyTrialLedger(Path(args.ledger).resolve())

    print("[1/5] validating raw price snapshot and SEC response hash chain")
    exact_cash = snapshot_manifest.get("price_basis") == EXACT_CASH_PRICE_BASIS
    if exact_cash:
        panel_all, missing = _load_exact_cash_panel(
            data_root,
            all_symbols,
            start="2007-01-01",
            end=load_end,
        )
    else:
        panel_all, missing = _load_panel(
            data_root,
            all_symbols,
            start="2007-01-01",
            end=load_end,
            total_return=False,
        )
    if missing:
        raise RuntimeError(f"price snapshot missing symbols: {missing}")
    snapshot_evidence = _validate_snapshot_manifest(
        data_root,
        pool_hash=pool["artifact_sha256"],
        symbols=all_symbols,
        through=load_end,
    )
    metadata, corpus_evidence = _validate_corpus(
        corpus_root,
        pool_hash=pool["artifact_sha256"],
        expected_ciks={int(row["cik"]) for row in pool["selected"]},
    )

    print("[2/5] building acceptance-time features and next-open event labels")
    candidate_panel = {
        name: frame.loc[:, candidates] for name, frame in panel_all.items()
    }
    eligibility_doc = config["dynamic_eligibility"]
    daily_eligibility = build_dynamic_eligibility_mask(
        candidate_panel["close"],
        candidate_panel["volume"],
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
        metadata,
        panel_all["close"].index,
        candidates,
        development_start=f"{development_start_year}-01-01",
        development_end=load_end,
    )
    labels = make_event_open_to_close_residual_rank_labels(
        candidate_panel["open"],
        candidate_panel["close"],
        panel_all["open"]["SPY"],
        panel_all["close"]["SPY"],
        structured.event_mask,
        holding_sessions=holding_sessions,
        beta_window_sessions=int(config["models"]["beta_window_sessions"]),
        cash_distributions=candidate_panel.get("cash_distribution"),
        market_cash_distributions=(
            panel_all["cash_distribution"]["SPY"] if exact_cash else None),
        total_return_close_prices=candidate_panel.get("total_return_close"),
        market_total_return_close=(
            panel_all["total_return_close"]["SPY"] if exact_cash else None),
    )
    eligibility = event_eligibility_from_previous_close(
        daily_eligibility, structured.event_mask)
    eligibility &= labels.notna()
    cohort_ok = eligibility.sum(axis=1) >= 3
    dates = eligibility.index[cohort_ok]
    eligibility = eligibility.loc[dates]
    labels = labels.loc[dates].where(eligibility)
    features = {
        name: frame.loc[dates] for name, frame in structured.features.items()
    }
    cohort_cells = int(eligibility.to_numpy().sum())
    if cohort_cells < 1000 or len(dates) < 250:
        raise RuntimeError(
            f"insufficient governed event cohorts: dates={len(dates)} cells={cohort_cells}")
    print(f"  cohort_dates={len(dates)} cohort_cells={cohort_cells}")

    print("[3/5] running validation-only structured linear/XGB folds")
    walk_config = WalkForwardConfig(
        start_year=development_start_year,
        end_year=development_end_year,
        train_window_years=int(config["models"]["train_window_years"]),
        val_window_years=int(config["models"]["validation_window_years"]),
        step_years=int(config["models"]["step_years"]),
        embargo_days=holding_sessions,
    )
    factories: dict[str, Callable] = {
        "structured_linear_rank": LinearBaselineRankModel,
        "structured_xgb_rank_ndcg": lambda: XGBRankerRankModel(
            n_estimators=100,
            max_depth=3,
            learning_rate=0.05,
            objective="rank:ndcg",
            random_state=int(config["models"]["seed"]),
        ),
    }
    price_hash, files_hashed = _hash_price_inputs(data_root, all_symbols)
    data_hash = _sha256_json({
        "price_input_sha256": price_hash,
        "sec_manifest_sha256": corpus_evidence["manifest_sha256"],
    })
    commit = _git_commit()
    config_hash = _sha256_file(config_path)
    feature_id = _sha256_json(sorted(features))
    intent_common = {
        "universe_hash": pool["artifact_sha256"],
        "data_hash": data_hash,
        "config_hash": config_hash,
        "code_commit": commit,
        "feature_id": feature_id,
        "start": f"{development_start_year}-01-01",
        "end": load_end,
        "observed_through": str(config["observed_through"]),
        "seed": int(config["models"]["seed"]),
    }
    model_reports: dict[str, Any] = {}
    predictions: dict[str, pd.DataFrame] = {}
    for model_name, factory in factories.items():
        trial_id = f"{run_stamp}-{model_name}-signal"
        registration = ledger.register_intent(_portfolio_trial_intent(
            trial_id=trial_id,
            model_name=model_name,
            construction="structured_event_signal_rank_only",
            cost_bps=0.0,
            hypothesis_family="sec_structured_event_rank_signal",
            execution_id="next_session_open_after_sec_acceptance",
            label_id="open_to_fifth_session_close_market_residual_rank",
            **intent_common,
        ))
        result = run_oof_rank_mining(
            factory,
            walk_config,
            features,
            labels,
            eligibility,
            daily_trading_index=panel_all["close"].index,
            cluster_features=True,
            correlation_threshold=float(
                config["models"]["feature_correlation_threshold"]),
            sealed_years=(2025, 2026),
        )
        successful = [fold for fold in result.folds if fold.error is None]
        summary = {
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
            f"  {model_name}: folds={result.successful_folds}/"
            f"{len(result.folds)} mean_ic={summary['mean_rank_ic']}")

    print("[4/5] publishing non-null validation predictions")
    prediction_long = pd.concat({
        model: frame.stack().dropna().rename("score")
        for model, frame in predictions.items()
    }, names=["model", "date", "symbol"]).reset_index()
    predictions_path = Path(args.predictions).resolve()
    _atomic_parquet(prediction_long, predictions_path)

    print("[5/5] publishing structured-event diagnostic report")
    metadata_tickers = set(metadata["ticker"])
    report = {
        "schema_version": 1,
        "run_id": f"governed-sec-structured-{run_stamp}",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "code_commit": commit,
        "evidence_scope": "DEVELOPMENT_ONLY",
        "automatic_promotion_eligible": False,
        "historical_oos_claim_allowed": False,
        "text_or_llm_used": False,
        "stage": "STRUCTURED_METADATA_BASELINE",
        "snapshot_evidence": snapshot_evidence,
        "corpus_evidence": corpus_evidence,
        "pricing": {
            "feature_availability": "SEC acceptanceDateTime",
            "execution_contract": "strictly next exchange session open",
            "label": "open_to_fifth_session_close_market_residual_rank",
            "basis": (
                "exact_cash_open_to_close_account_return"
                if exact_cash else "split_adjusted_price_return"
            ),
            "portfolio_evaluation": "NOT_RUN_SIGNAL_DIAGNOSTIC_STAGE",
        },
        "coverage": {
            "frozen_pool_companies": len(pool_candidates),
            "corporate_action_excluded_companies": excluded_candidates,
            "pool_companies": len(candidates),
            "companies_with_governed_forms": len(metadata_tickers),
            "unsupported_or_zero_governed_form_tickers": sorted(
                set(candidates) - metadata_tickers),
            "raw_selected_filings": len(metadata),
            "development_event_records": len(structured.event_records),
            "cohort_dates_at_least_three": len(dates),
            "cohort_cells": cohort_cells,
            "cohort_cells_by_year": {
                str(year): int(
                    eligibility.loc[eligibility.index.year == year]
                    .to_numpy().sum())
                for year in sorted(set(eligibility.index.year))
            },
            "feature_names": sorted(features),
        },
        "models": model_reports,
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
                "sec_structured_event_rank_signal"),
            "incomplete_trial_ids": ledger.incomplete_trial_ids(),
        },
        "disposition": "STRUCTURED_SIGNAL_DIAGNOSTIC_ONLY",
    }
    _atomic_json(_finite(report), Path(args.report).resolve())
    print(f"report={Path(args.report).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
