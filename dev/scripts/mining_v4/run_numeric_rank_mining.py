#!/usr/bin/env python3
"""Run governed rule/linear/XGB rank mining on the frozen company pool."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, cast

import numpy as np
import pandas as pd
import yaml

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

from core.backtest.backtest_engine import BacktestEngine  # noqa: E402
from core.config.schemas.cost_model import (  # noqa: E402
    CostModelConfig,
    CostTierConfig,
)
from core.data.bar_store import BarStore  # noqa: E402
from core.data.price_basis import (  # noqa: E402
    PriceBasisError,
    validate_total_return_coverage,
)
from core.execution.cost_model import CostModel  # noqa: E402
from core.research.dynamic_universe import (  # noqa: E402
    DynamicEligibilityConfig,
    build_dynamic_eligibility_mask,
)
from core.research.mining_v4_features import (  # noqa: E402
    build_causal_numeric_features,
    month_end_decision_dates,
)
from core.research.mining_v4_portfolio import (  # noqa: E402
    Construction,
    build_decision_weights,
    expand_decision_signals,
)
from core.research.ml.labels import make_residualized_rank_labels  # noqa: E402
from core.research.ml.pipeline import WalkForwardConfig  # noqa: E402
from core.research.ml.rank_model import LinearBaselineRankModel  # noqa: E402
from core.research.ml.xgb_rank_model import XGBRankerRankModel  # noqa: E402
from core.research.oof_rank_mining import (  # noqa: E402
    RuleRankModel,
    run_oof_rank_mining,
)
from core.research.trial_ledger import (  # noqa: E402
    AppendOnlyTrialLedger,
    TrialIntent,
)

RULE_ORIENTATIONS = {
    "drawdown_126": 1.0,
    "mom_126": 1.0,
    "mom_252": 1.0,
    "rs_spy_63": 1.0,
    "trend_efficiency_63": 1.0,
    "vol_63": -1.0,
}


def _git_commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=PROJ, text=True).strip()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_symbol(symbol: str) -> str:
    return symbol.replace("^", "_").replace("-", "_")


def _hash_price_inputs(data_root: Path, symbols: list[str]) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    for symbol in sorted(set(symbols)):
        path = data_root / "daily" / f"{_safe_symbol(symbol)}.parquet"
        if not path.exists():
            continue
        digest.update(symbol.encode("utf-8"))
        digest.update(bytes.fromhex(_sha256_file(path)))
        count += 1
    manifest_path = data_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("price_basis") == "RAW_OHLCV_WITH_SPLITS_APPLIED_AT_READ_TIME":
        split_path = data_root / "ref" / "splits.parquet"
        digest.update(b"splits.parquet")
        digest.update(bytes.fromhex(_sha256_file(split_path)))
    else:
        digest.update(b"manifest.json")
        digest.update(bytes.fromhex(_sha256_file(manifest_path)))
    return digest.hexdigest(), count


def _validate_snapshot_manifest(
    data_root: Path,
    *,
    pool_hash: str,
    symbols: list[str],
    through: str,
) -> dict[str, Any]:
    path = data_root / "manifest.json"
    if not path.exists():
        raise RuntimeError(
            f"governed numeric mining requires snapshot manifest: {path}")
    manifest = json.loads(path.read_text())
    if manifest.get("pool_artifact_sha256") != pool_hash:
        raise RuntimeError("snapshot pool hash differs from frozen company pool")
    if manifest.get("through") != through:
        raise RuntimeError(
            f"snapshot through={manifest.get('through')} does not equal {through}")
    allowed_bases = {
        "RAW_OHLCV_WITH_SPLITS_APPLIED_AT_READ_TIME",
        "YAHOO_SPLIT_ADJUSTED_OHLC_PLUS_CASH_EVENT_TOTAL_RETURN_V1",
    }
    if manifest.get("price_basis") not in allowed_bases:
        raise RuntimeError("snapshot price basis is not governed")
    rows = manifest.get("symbols")
    if not isinstance(rows, list):
        raise RuntimeError("snapshot manifest lacks per-symbol evidence rows")
    by_symbol = {row.get("symbol"): row for row in rows}
    if not set(symbols).issubset(by_symbol):
        raise RuntimeError("snapshot manifest lacks requested pool symbols")
    for symbol in by_symbol:
        daily_path = data_root / "daily" / f"{_safe_symbol(symbol)}.parquet"
        if not daily_path.exists():
            raise RuntimeError(f"snapshot daily file is missing for {symbol}")
        actual = _sha256_file(daily_path)
        if actual != by_symbol[symbol].get("output_sha256"):
            raise RuntimeError(f"snapshot daily hash mismatch for {symbol}")
    if manifest.get("price_basis") == "RAW_OHLCV_WITH_SPLITS_APPLIED_AT_READ_TIME":
        splits_path = data_root / "ref" / "splits.parquet"
        if _sha256_file(splits_path) != manifest.get("splits_sha256"):
            raise RuntimeError("snapshot splits hash differs from manifest")
    return {
        "path": "manifest.json",
        "sha256": _sha256_file(path),
        "snapshot_id": manifest.get("snapshot_id"),
        "builder_commit": manifest.get("builder_commit"),
        "builder_script_sha256": manifest.get("builder_script_sha256"),
        "repair_module_sha256": manifest.get("repair_module_sha256"),
        "adjustment_module_sha256": manifest.get("adjustment_module_sha256"),
        "price_basis": manifest.get("price_basis"),
        "through": manifest.get("through"),
        "symbols_verified": len(symbols),
        "manifest_files_verified": len(by_symbol),
        "excluded_symbols": manifest.get("excluded_symbols", []),
    }


def _atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        frame.to_parquet(temporary, index=False)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _finite(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _finite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(item) for item in value]
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def _load_panel(
    data_root: Path,
    symbols: list[str],
    *,
    start: str,
    end: str,
    total_return: bool,
) -> tuple[dict[str, pd.DataFrame], list[str]]:
    manifest = json.loads((data_root / "manifest.json").read_text())
    embedded = manifest.get("price_basis") == (
        "YAHOO_SPLIT_ADJUSTED_OHLC_PLUS_CASH_EVENT_TOTAL_RETURN_V1"
    )
    store = BarStore(root=data_root)
    frames: dict[str, dict[str, pd.Series]] = {
        name: {} for name in ("open", "high", "low", "close", "volume")
    }
    missing: list[str] = []
    cutoff = pd.Timestamp(end)
    for position, symbol in enumerate(symbols, start=1):
        if position % 50 == 0 or position == len(symbols):
            print(f"  loading bars {position}/{len(symbols)}", flush=True)
        if embedded:
            daily_path = data_root / "daily" / f"{_safe_symbol(symbol)}.parquet"
            if not daily_path.exists():
                frame = pd.DataFrame()
            else:
                stored = pd.read_parquet(daily_path)
                stored = stored[
                    (stored.index >= pd.Timestamp(start))
                    & (stored.index <= cutoff)
                ]
                if total_return:
                    frame = pd.DataFrame({
                        name: stored[f"total_return_{name}"]
                        for name in ("open", "high", "low", "close")
                    }, index=stored.index)
                    frame["volume"] = stored["volume"]
                else:
                    frame = stored[["open", "high", "low", "close", "volume"]]
        else:
            frame = store.load(
                symbol,
                freq="1d",
                adjusted=True,
                adjusted_total_return=total_return,
                start=start,
                end=end,
                as_of=cutoff,
                fallback="local",
            )
        if frame.empty or "close" not in frame:
            missing.append(symbol)
            continue
        frames["close"][symbol] = frame["close"]
        for name in ("open", "high", "low", "volume"):
            if name in frame:
                frames[name][symbol] = frame[name]
    close = pd.DataFrame(frames["close"]).sort_index()
    loaded = [symbol for symbol in symbols if symbol in close]
    panel = {"close": close.loc[:, loaded]}
    for name in ("open", "high", "low", "volume"):
        panel[name] = pd.DataFrame(frames[name]).reindex(
            index=close.index, columns=loaded)
    return panel, missing


def _embedded_total_return_evidence(
    data_root: Path,
    symbols: list[str],
    *,
    from_date: pd.Timestamp,
    through: str,
) -> dict[str, Any] | None:
    manifest_path = data_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("price_basis") != (
        "YAHOO_SPLIT_ADJUSTED_OHLC_PLUS_CASH_EVENT_TOTAL_RETURN_V1"
    ):
        return None
    eligible = set(manifest.get("eligible_symbols", []))
    missing = sorted(set(symbols) - eligible)
    if missing:
        raise PriceBasisError(
            f"embedded total-return snapshot excludes requested symbols: {missing}"
        )
    if manifest.get("through") != through:
        raise PriceBasisError("embedded total-return cutoff differs from request")
    required = {
        "total_return_open", "total_return_high", "total_return_low",
        "total_return_close",
    }
    if set(manifest.get("total_return_columns", [])) != required:
        raise PriceBasisError("embedded total-return columns are incomplete")
    return {
        "basis": manifest["price_basis"],
        "symbols": symbols,
        "coverage_start": str(from_date.date()),
        "coverage_end": through,
        "source_snapshot_manifest_sha256": manifest.get(
            "source_snapshot_manifest_sha256"),
        "cash_distribution_events_applied": manifest.get(
            "cash_distribution_events_applied"),
        "cash_distribution_events_skipped_pre_history": manifest.get(
            "cash_distribution_events_skipped_pre_history"),
        "excluded_symbols": manifest.get("excluded_symbols", []),
        "manifest_sha256": _sha256_file(manifest_path),
    }


def _flat_cost_model(cost_bps: float) -> CostModel:
    config = CostModelConfig(tiers={
        "default": CostTierConfig(
            symbols=[],
            commission_bps=0.0,
            slippage_interday_bps=cost_bps,
            slippage_intraday_bps=cost_bps,
        ),
    })
    return CostModel(config)


def _rolling_excess_fraction(
    strategy_nav: pd.Series,
    spy_nav: pd.Series,
    window: int = 252,
) -> float | None:
    common = strategy_nav.index.intersection(spy_nav.index)
    if len(common) <= window:
        return None
    strategy_return = strategy_nav.loc[common].div(
        strategy_nav.loc[common].shift(window)) - 1.0
    spy_return = spy_nav.loc[common].div(spy_nav.loc[common].shift(window)) - 1.0
    excess = (strategy_return - spy_return).dropna()
    return float((excess > 0).mean()) if len(excess) else None


def _portfolio_trial_intent(
    *,
    trial_id: str,
    model_name: str,
    construction: str,
    cost_bps: float,
    universe_hash: str,
    data_hash: str,
    config_hash: str,
    code_commit: str,
    feature_id: str,
    start: str,
    end: str,
    observed_through: str,
    seed: int,
    hypothesis_family: str = "numeric_rank_portfolio",
    execution_id: str = "month_end_close_to_next_session_open",
    label_id: str = "market_residual_rank_21d",
) -> TrialIntent:
    return TrialIntent(
        trial_id=trial_id,
        hypothesis_family=hypothesis_family,
        mechanism_id=model_name,
        universe_hash=universe_hash,
        data_hash=data_hash,
        config_hash=config_hash,
        code_commit=code_commit,
        feature_id=feature_id,
        model_id=model_name,
        label_id=label_id,
        construction_id=construction,
        cost_id=f"flat_one_way_{cost_bps:g}bps",
        execution_id=execution_id,
        seed=seed,
        period_start=start,
        period_end=end,
        observed_through=observed_through,
    )


def _run_portfolios(
    *,
    data_root: Path,
    candidates: list[str],
    predictions: dict[str, pd.DataFrame],
    volatility: pd.DataFrame,
    first_date: pd.Timestamp,
    end_date: pd.Timestamp,
    ledger: AppendOnlyTrialLedger,
    run_stamp: str,
    intent_common: dict[str, Any],
    constructions: list[str],
) -> dict[str, Any]:
    symbols = candidates + ["SPY"]
    panel, missing = _load_panel(
        data_root,
        symbols,
        start=str(first_date.date()),
        end=str(end_date.date()),
        total_return=True,
    )
    if missing:
        raise RuntimeError(f"total-return panel missing symbols: {missing}")
    daily_index = panel["close"].index
    results: dict[str, Any] = {}
    for cost_bps in (30.0, 60.0, 90.0):
        cost_model = _flat_cost_model(cost_bps)
        spy_decision = pd.DataFrame(
            {"SPY": [1.0]}, index=pd.DatetimeIndex([first_date]))
        spy_signals = expand_decision_signals(spy_decision, daily_index)
        spy_result = BacktestEngine(
            cost_model,
            initial_capital=100_000.0,
            min_trade_usd=0.0,
            rebalance_threshold=0.0,
        ).run(
            spy_signals,
            panel["close"],
            open_df=panel["open"],
            rebalance_dates=[first_date],
        )
        for model_name, score in predictions.items():
            usable = score.loc[score.index >= first_date].dropna(how="all")
            for construction in constructions:
                trial_id = (
                    f"{run_stamp}-{model_name}-{construction}-{cost_bps:g}bps")
                intent = _portfolio_trial_intent(
                    trial_id=trial_id,
                    model_name=model_name,
                    construction=construction,
                    cost_bps=cost_bps,
                    **intent_common,
                )
                registration = ledger.register_intent(intent)
                decision_weights = build_decision_weights(
                    usable,
                    volatility.reindex(usable.index),
                    cast(Construction, construction),
                )
                signals = expand_decision_signals(decision_weights, daily_index)
                result = BacktestEngine(
                    cost_model,
                    initial_capital=100_000.0,
                    min_trade_usd=0.0,
                    rebalance_threshold=0.0,
                ).run(
                    signals,
                    panel["close"],
                    open_df=panel["open"],
                    benchmark_series=panel["close"]["SPY"],
                    rebalance_dates=decision_weights.index,
                )
                key = f"{model_name}/{construction}/{cost_bps:g}bps"
                metrics = {
                    "strategy": _finite(result.metrics),
                    "spy_buy_hold": _finite(spy_result.metrics),
                    "total_return_excess_vs_spy": float(
                        result.metrics["total_return"]
                        - spy_result.metrics["total_return"]),
                    "cagr_excess_vs_spy": float(
                        result.metrics["cagr"] - spy_result.metrics["cagr"]),
                    "positive_252d_rolling_excess_fraction": (
                        _rolling_excess_fraction(
                            result.equity_curve, spy_result.equity_curve)),
                    "n_trades": result.n_trades,
                    "total_commission_usd": result.total_commission_usd,
                    "total_slippage_usd": result.total_slippage_usd,
                    "independent_trial": registration.independent_trial,
                }
                results[key] = _finite(metrics)
                ledger.record_outcome(trial_id, _finite(metrics))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", default=str(PROJ / "data"))
    parser.add_argument(
        "--pool", default="research/universes/semantic_ml_company_pool_v1.json")
    parser.add_argument("--config", default="config/strategy_mining_v4.yaml")
    parser.add_argument("--report", default=None)
    parser.add_argument("--predictions", default=None)
    parser.add_argument("--ledger", default=None)
    parser.add_argument(
        "--models", nargs="+", default=["rule_rank", "linear_rank", "xgb_rank_ndcg"],
        choices=["rule_rank", "linear_rank", "xgb_rank_ndcg"],
    )
    args = parser.parse_args()

    data_root = Path(args.data_root).resolve()
    pool_path = (PROJ / args.pool).resolve()
    config_path = (PROJ / args.config).resolve()
    pool = json.loads(pool_path.read_text())
    config = yaml.safe_load(config_path.read_text())
    model_config = config["models"]
    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = (
        Path(args.report).resolve()
        if args.report
        else data_root / "research" / "mining_v4" / f"numeric_rank_{run_stamp}.json"
    )
    predictions_path = (
        Path(args.predictions).resolve()
        if args.predictions
        else data_root / "research" / "mining_v4" / f"numeric_rank_{run_stamp}.parquet"
    )
    ledger_path = (
        Path(args.ledger).resolve()
        if args.ledger
        else data_root / "research" / "mining_v4" / "trial_ledger.jsonl"
    )
    ledger = AppendOnlyTrialLedger(ledger_path)

    pool_candidates = [row["ticker"] for row in pool["selected"]]
    snapshot_manifest = json.loads((data_root / "manifest.json").read_text())
    snapshot_excluded = set(snapshot_manifest.get("excluded_symbols", []))
    candidates = [
        symbol for symbol in pool_candidates if symbol not in snapshot_excluded
    ]
    excluded_candidates = sorted(set(pool_candidates) - set(candidates))
    all_symbols = candidates + ["SPY"]
    start_year = int(model_config["development_start_year"])
    end_year = int(model_config["development_end_year"])
    load_start = "2007-01-01"
    load_end = f"{end_year}-12-31"
    print(f"[1/6] loading {len(all_symbols)} split-adjusted price series")
    panel_all, missing = _load_panel(
        data_root,
        all_symbols,
        start=load_start,
        end=load_end,
        total_return=False,
    )
    if "SPY" in missing or "SPY" not in panel_all["close"]:
        raise RuntimeError("SPY is unavailable from the governed local source")
    loaded_candidates = [
        symbol for symbol in candidates if symbol in panel_all["close"].columns]
    if len(loaded_candidates) < 250:
        raise RuntimeError(
            f"only {len(loaded_candidates)} / {len(candidates)} company bars loaded")
    candidate_panel = {
        name: frame.loc[:, loaded_candidates]
        for name, frame in panel_all.items()
    }
    market = panel_all["close"]["SPY"]
    print(f"  loaded candidates={len(loaded_candidates)} missing={len(missing)}")

    print("  verifying immutable snapshot manifest and per-file hashes")
    snapshot_evidence = _validate_snapshot_manifest(
        data_root,
        pool_hash=pool["artifact_sha256"],
        symbols=all_symbols,
        through=load_end,
    )

    print("[2/6] building causal eligibility, features, and 21-session labels")
    eligibility_doc = config["dynamic_eligibility"]
    eligibility_config = DynamicEligibilityConfig(
        min_history_sessions=int(eligibility_doc["min_history_sessions"]),
        lookback_sessions=int(eligibility_doc["lookback_sessions"]),
        min_observation_density=float(eligibility_doc["min_observation_density"]),
        min_price=float(eligibility_doc["min_price"]),
        min_median_dollar_volume=float(
            eligibility_doc["min_median_dollar_volume"]),
    )
    eligibility_daily = build_dynamic_eligibility_mask(
        candidate_panel["close"], candidate_panel["volume"], eligibility_config)
    features_daily = build_causal_numeric_features(candidate_panel, market)
    labels_daily = make_residualized_rank_labels(
        candidate_panel["close"],
        int(model_config["label_horizon_sessions"]),
        market,
        beta_window=int(model_config["beta_window_sessions"]),
    )
    decisions = month_end_decision_dates(panel_all["close"].index, market)
    decisions = decisions[
        (decisions.year >= start_year) & (decisions.year <= end_year)]
    eligibility = eligibility_daily.loc[decisions]
    features = {name: frame.loc[decisions] for name, frame in features_daily.items()}
    labels = labels_daily.loc[decisions].where(eligibility)
    data_hash, files_hashed = _hash_price_inputs(data_root, all_symbols)
    universe_hash = pool["artifact_sha256"]
    config_hash = _sha256_file(config_path)
    feature_id = _sha256_json(sorted(features))
    commit = _git_commit()
    print(
        f"  decisions={len(decisions)} features={len(features)} "
        f"eligible_cells={int(eligibility.sum().sum())}")

    print("[3/6] running validation-only rule/linear/XGB folds")
    walk_config = WalkForwardConfig(
        start_year=start_year,
        end_year=end_year,
        train_window_years=int(model_config["train_window_years"]),
        val_window_years=int(model_config["validation_window_years"]),
        step_years=int(model_config["step_years"]),
        embargo_days=int(model_config["label_horizon_sessions"]),
    )
    factories: dict[str, tuple[Callable, dict[str, pd.DataFrame], bool]] = {
        "rule_rank": (
            lambda: RuleRankModel(RULE_ORIENTATIONS),
            {name: features[name] for name in RULE_ORIENTATIONS},
            False,
        ),
        "linear_rank": (LinearBaselineRankModel, features, True),
        "xgb_rank_ndcg": (
            lambda: XGBRankerRankModel(
                n_estimators=100,
                max_depth=3,
                learning_rate=0.05,
                objective="rank:ndcg",
                random_state=int(model_config["seed"]),
            ),
            features,
            True,
        ),
    }
    model_reports: dict[str, Any] = {}
    predictions: dict[str, pd.DataFrame] = {}
    intent_common = {
        "universe_hash": universe_hash,
        "data_hash": data_hash,
        "config_hash": config_hash,
        "code_commit": commit,
        "feature_id": feature_id,
        "start": f"{start_year}-01-01",
        "end": load_end,
        "observed_through": str(config["observed_through"]),
        "seed": int(model_config["seed"]),
    }
    for model_name in args.models:
        factory, model_features, cluster = factories[model_name]
        trial_id = f"{run_stamp}-{model_name}-signal"
        signal_intent = _portfolio_trial_intent(
            trial_id=trial_id,
            model_name=model_name,
            construction="signal_rank_only",
            cost_bps=0.0,
            hypothesis_family="numeric_rank_signal",
            execution_id="validation_rank_ic_no_portfolio_execution",
            **intent_common,
        )
        registration = ledger.register_intent(signal_intent)
        result = run_oof_rank_mining(
            factory,
            walk_config,
            model_features,
            labels,
            eligibility,
            daily_trading_index=panel_all["close"].index,
            cluster_features=cluster,
            correlation_threshold=float(
                model_config["feature_correlation_threshold"]),
            sealed_years=(2025, 2026),
        )
        folds = [asdict(fold) for fold in result.folds]
        successful = [fold for fold in result.folds if fold.error is None]
        summary = {
            "independent_trial": registration.independent_trial,
            "successful_folds": result.successful_folds,
            "mean_rank_ic": float(np.mean([fold.rank_ic for fold in successful]))
            if successful else None,
            "mean_rank_ir": float(np.mean([fold.rank_ir for fold in successful]))
            if successful else None,
            "positive_rank_ic_fold_fraction": (
                float(np.mean([fold.rank_ic > 0 for fold in successful]))
                if successful else None),
            "folds": folds,
        }
        model_reports[model_name] = _finite(summary)
        predictions[model_name] = result.predictions
        ledger.record_outcome(trial_id, _finite(summary))
        print(
            f"  {model_name}: folds={result.successful_folds}/{len(result.folds)} "
            f"mean_ic={summary['mean_rank_ic']}")

    print("[4/6] publishing OOF predictions")
    prediction_long = pd.concat(
        {
            model: frame.stack().dropna().rename("score")
            for model, frame in predictions.items()
        },
        names=["model", "date", "symbol"],
    ).reset_index()
    _atomic_parquet(prediction_long, predictions_path)

    print("[5/6] enforcing total-return portfolio preflight")
    first_validation_year = start_year + int(model_config["train_window_years"])
    first_validation_dates = decisions[decisions.year >= first_validation_year]
    if len(first_validation_dates) == 0:
        raise RuntimeError("no validation decision dates were generated")
    first_validation_date = first_validation_dates[0]
    try:
        embedded_evidence = _embedded_total_return_evidence(
            data_root,
            loaded_candidates + ["SPY"],
            from_date=first_validation_date,
            through=load_end,
        )
        evidence = (
            embedded_evidence
            if embedded_evidence is not None
            else asdict(validate_total_return_coverage(
                data_root,
                loaded_candidates + ["SPY"],
                from_date=first_validation_date,
                through=load_end,
            ))
        )
        portfolio_preflight: dict[str, Any] = {
            "status": "PASS",
            "evidence": _finite(evidence),
        }
    except PriceBasisError as exc:
        portfolio_preflight = {
            "status": "BLOCKED_FAIL_CLOSED",
            "reason": str(exc),
        }

    portfolio_results: dict[str, Any] = {}
    if portfolio_preflight["status"] == "PASS":
        portfolio_results = _run_portfolios(
            data_root=data_root,
            candidates=loaded_candidates,
            predictions=predictions,
            volatility=features["vol_63"],
            first_date=first_validation_date,
            end_date=pd.Timestamp(load_end),
            ledger=ledger,
            run_stamp=run_stamp,
            intent_common=intent_common,
            constructions=list(config["constructions"]),
        )
    else:
        print(f"  portfolio blocked: {portfolio_preflight['reason']}")

    print("[6/6] publishing governed report")
    try:
        predictions_location = str(predictions_path.relative_to(data_root))
    except ValueError:
        predictions_location = predictions_path.name
    try:
        ledger_location = str(ledger_path.relative_to(data_root))
    except ValueError:
        ledger_location = ledger_path.name
    report = {
        "schema_version": 1,
        "run_id": f"governed-numeric-rank-{run_stamp}",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "code_commit": commit,
        "evidence_scope": "DEVELOPMENT_ONLY",
        "automatic_promotion_eligible": False,
        "historical_oos_claim_allowed": False,
        "survivorship_note": (
            "current 2026 company snapshot used for historical development; "
            "validation folds are model-held-out but not point-in-time-universe OOS"),
        "pool_id": pool["pool_id"],
        "pool_artifact_sha256": universe_hash,
        "config_sha256": config_hash,
        "data_input_sha256": data_hash,
        "data_files_hashed": files_hashed,
        "snapshot_evidence": snapshot_evidence,
        "pricing": {
            "signal_and_label_basis": "split_adjusted_price_return",
            "portfolio_required_basis": "split_and_distribution_adjusted_total_return",
            "portfolio_preflight": portfolio_preflight,
        },
        "panel": {
            "frozen_pool_companies": len(pool_candidates),
            "requested_companies": len(candidates),
            "corporate_action_excluded_companies": excluded_candidates,
            "loaded_companies": len(loaded_candidates),
            "missing_symbols": missing,
            "first_date": str(panel_all["close"].index.min().date()),
            "last_date": str(panel_all["close"].index.max().date()),
            "decision_dates": len(decisions),
            "eligible_cells": int(eligibility.sum().sum()),
            "eligible_cells_by_year": {
                str(year): int(
                    eligibility.loc[eligibility.index.year == year]
                    .to_numpy().sum())
                for year in sorted(set(eligibility.index.year))
            },
            "feature_count": len(features),
            "feature_names": sorted(features),
            "label": "market_residual_rank_21d",
        },
        "models": model_reports,
        "predictions": {
            "data_root_relative_path": predictions_location,
            "sha256": _sha256_file(predictions_path),
            "rows": len(prediction_long),
        },
        "portfolio_results": portfolio_results,
        "trial_ledger": {
            "data_root_relative_path": ledger_location,
            "independent_signal_trials": ledger.independent_trial_count(
                "numeric_rank_signal"),
            "independent_portfolio_trials": ledger.independent_trial_count(
                "numeric_rank_portfolio"),
            "incomplete_trial_ids": ledger.incomplete_trial_ids(),
        },
        "disposition": (
            "SIGNAL_DIAGNOSTIC_ONLY"
            if portfolio_preflight["status"] != "PASS"
            else "PORTFOLIO_DEVELOPMENT_EVALUATED_NOT_PROMOTED"
        ),
    }
    _atomic_json(_finite(report), report_path)
    print(f"report={report_path}")
    print(f"predictions={predictions_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
