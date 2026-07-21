#!/usr/bin/env python3
"""Backtest governed SEC structured OOF predictions as a sparse event overlay."""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

from core.backtest.backtest_engine import BacktestEngine  # noqa: E402
from core.research.mining_v4_portfolio import expand_decision_signals  # noqa: E402
from core.research.sec_event_portfolio import (  # noqa: E402
    build_event_overlay_weights,
)
from core.research.trial_ledger import AppendOnlyTrialLedger  # noqa: E402
from dev.scripts.mining_v4.run_numeric_rank_mining import (  # noqa: E402
    _atomic_json,
    _flat_cost_model,
    _git_commit,
    _hash_price_inputs,
    _load_panel,
    _portfolio_trial_intent,
    _rolling_excess_fraction,
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


def _gate_checks(
    *,
    strategy_metrics: dict[str, float],
    spy_metrics: dict[str, float],
    cagr_excess: float,
    rolling_excess_fraction: float | None,
    gate_config: dict[str, Any],
) -> dict[str, Any]:
    spy_drawdown = abs(float(spy_metrics["max_drawdown"]))
    drawdown_ratio = (
        abs(float(strategy_metrics["max_drawdown"])) / spy_drawdown
        if spy_drawdown > 0 else None
    )
    checks = {
        "after_cost_cagr_excess_vs_spy": (
            cagr_excess >= float(gate_config["min_after_cost_excess_vs_spy"])),
        "positive_252d_rolling_excess_fraction": (
            rolling_excess_fraction is not None
            and rolling_excess_fraction >= float(
                gate_config["min_positive_rolling_window_fraction"])),
        "max_drawdown_vs_spy_multiplier": (
            drawdown_ratio is not None
            and drawdown_ratio <= float(
                gate_config["max_drawdown_vs_spy_multiplier"])),
    }
    return {
        "checks": checks,
        "all_primary_gates_pass": all(checks.values()),
        "max_drawdown_vs_spy_ratio": drawdown_ratio,
        # A near miss is retained for human review; it is never promoted by
        # this flag and a negative value is never silently treated as PASS.
        "near_miss_review_eligible": (
            not all(checks.values())
            and cagr_excess >= float(
                gate_config["near_miss_min_annualized_excess"])),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--structured-report", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--pool", default="research/universes/semantic_ml_company_pool_v1.json")
    parser.add_argument("--config", default="config/strategy_mining_v4.yaml")
    args = parser.parse_args()
    data_root = Path(args.data_root).resolve()
    structured_report_path = Path(args.structured_report).resolve()
    pool_path = (PROJ / args.pool).resolve()
    config_path = (PROJ / args.config).resolve()
    pool = json.loads(pool_path.read_text())
    config = yaml.safe_load(config_path.read_text())
    gate_config = config["forward_freeze_gate"]
    structured_report = json.loads(structured_report_path.read_text())
    predictions_path = Path(structured_report["predictions"]["path"])
    if _sha256_file(predictions_path) != structured_report["predictions"]["sha256"]:
        raise RuntimeError("structured SEC predictions hash differs from report")
    snapshot_manifest = json.loads((data_root / "manifest.json").read_text())
    if _sha256_file(data_root / "manifest.json") != structured_report[
        "snapshot_evidence"
    ]["sha256"]:
        raise RuntimeError("structured SEC report points to a different price snapshot")
    excluded = set(snapshot_manifest.get("excluded_symbols", []))
    candidates = [
        row["ticker"] for row in pool["selected"] if row["ticker"] not in excluded
    ]
    all_symbols = candidates + ["SPY"]
    snapshot_evidence = _validate_snapshot_manifest(
        data_root,
        pool_hash=pool["artifact_sha256"],
        symbols=all_symbols,
        through="2024-12-31",
    )
    panel, missing = _load_panel(
        data_root, all_symbols, start="2019-01-01", end="2024-12-31",
        total_return=True,
    )
    if missing:
        raise RuntimeError(f"event portfolio total-return panel missing: {missing}")
    prediction_long = pd.read_parquet(predictions_path)
    required = {"model", "date", "symbol", "score"}
    if not required.issubset(prediction_long):
        raise RuntimeError("structured prediction artifact schema is invalid")
    prediction_long["date"] = pd.to_datetime(prediction_long["date"])
    prediction_long = prediction_long[
        prediction_long["symbol"].isin(candidates)
    ]
    model_names = sorted(prediction_long["model"].unique())
    if model_names != ["structured_linear_rank", "structured_xgb_rank_ndcg"]:
        raise RuntimeError(f"unexpected structured model set: {model_names}")

    ledger = AppendOnlyTrialLedger(Path(args.ledger).resolve())
    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    data_hash, _ = _hash_price_inputs(data_root, all_symbols)
    data_hash = _sha256_json({
        "prices": data_hash,
        "structured_report": _sha256_file(structured_report_path),
        "predictions": _sha256_file(predictions_path),
    })
    commit = _git_commit()
    config_hash = _sha256_file(config_path)
    construction = "spy_anchor_sparse_event_score80_hold5_cap10"
    results: dict[str, Any] = {}
    for model_name in model_names:
        model_rows = prediction_long[prediction_long["model"].eq(model_name)]
        predictions = model_rows.pivot(
            index="date", columns="symbol", values="score",
        ).reindex(columns=candidates)
        overlay = build_event_overlay_weights(
            predictions,
            panel["close"].index,
            holding_sessions=5,
            score_threshold=0.8,
            active_target=0.65,
            single_name_cap=0.10,
        )
        first_decision = overlay.decision_weights.index.min()
        last_execution = overlay.execution_dates.max()
        daily_index = panel["close"].index[
            (panel["close"].index >= first_decision)
            & (panel["close"].index <= last_execution)
        ]
        close = panel["close"].loc[daily_index]
        open_ = panel["open"].loc[daily_index]
        decisions = overlay.decision_weights.loc[
            overlay.decision_weights.index.intersection(daily_index)
        ]
        signals = expand_decision_signals(decisions, daily_index)
        spy_decision = pd.DataFrame(
            {"SPY": [1.0]}, index=pd.DatetimeIndex([first_decision]),
        )
        spy_signals = expand_decision_signals(spy_decision, daily_index)
        for cost_bps in (30.0, 60.0, 90.0):
            trial_id = f"{run_stamp}-{model_name}-event-overlay-{cost_bps:g}bps"
            registration = ledger.register_intent(_portfolio_trial_intent(
                trial_id=trial_id,
                model_name=model_name,
                construction=construction,
                cost_bps=cost_bps,
                universe_hash=pool["artifact_sha256"],
                data_hash=data_hash,
                config_hash=config_hash,
                code_commit=commit,
                feature_id=_sha256_json({
                    "structured_report": structured_report["data_input_sha256"],
                    "score_threshold": 0.8,
                    "holding_sessions": 5,
                    "active_target": 0.65,
                    "single_name_cap": 0.10,
                }),
                start=str(overlay.execution_dates.min().date()),
                end=str(last_execution.date()),
                observed_through=str(config["observed_through"]),
                seed=int(config["models"]["seed"]),
                hypothesis_family="sec_structured_event_portfolio",
                execution_id="sec_acceptance_to_next_session_open_hold5",
                label_id="open_to_fifth_session_close_market_residual_rank",
            ))
            cost_model = _flat_cost_model(cost_bps)
            strategy = BacktestEngine(
                cost_model, initial_capital=100_000.0,
                min_trade_usd=0.0, rebalance_threshold=0.0,
            ).run(
                signals, close, open_df=open_, benchmark_series=close["SPY"],
                rebalance_dates=decisions.index,
            )
            benchmark = BacktestEngine(
                cost_model, initial_capital=100_000.0,
                min_trade_usd=0.0, rebalance_threshold=0.0,
            ).run(
                spy_signals, close[["SPY"]], open_df=open_[["SPY"]],
                rebalance_dates=[first_decision],
            )
            outcome = {
                "model": model_name,
                "construction": construction,
                "cost_bps": cost_bps,
                "independent_trial": registration.independent_trial,
                "event_prediction_rows": len(model_rows),
                "active_signal_cells_across_targets": overlay.active_signal_cells,
                "complete_event_dates": (
                    len(predictions.index)
                    - len(overlay.dropped_incomplete_round_trip_dates)),
                "dropped_incomplete_round_trip_dates": list(
                    overlay.dropped_incomplete_round_trip_dates),
                "decision_days": len(decisions),
                "strategy": _finite(strategy.metrics),
                "spy_buy_hold": _finite(benchmark.metrics),
                "cagr_excess_vs_spy": float(
                    strategy.metrics["cagr"] - benchmark.metrics["cagr"]),
                "total_return_excess_vs_spy": float(
                    strategy.metrics["total_return"]
                    - benchmark.metrics["total_return"]),
                "positive_252d_rolling_excess_fraction": (
                    _rolling_excess_fraction(
                        strategy.equity_curve, benchmark.equity_curve)),
                "n_trades": strategy.n_trades,
                "total_commission_usd": strategy.total_commission_usd,
                "total_slippage_usd": strategy.total_slippage_usd,
            }
            outcome["gate_evaluation"] = _gate_checks(
                strategy_metrics=strategy.metrics,
                spy_metrics=benchmark.metrics,
                cagr_excess=outcome["cagr_excess_vs_spy"],
                rolling_excess_fraction=outcome[
                    "positive_252d_rolling_excess_fraction"],
                gate_config=gate_config,
            )
            key = f"{model_name}/{cost_bps:g}bps"
            results[key] = _finite(outcome)
            ledger.record_outcome(trial_id, _finite(outcome))
            print(
                f"{key}: cagr_excess={outcome['cagr_excess_vs_spy']:.6f} "
                f"rolling={outcome['positive_252d_rolling_excess_fraction']}",
                flush=True,
            )
    primary_cost_passes = sorted(
        key for key, value in results.items()
        if key.endswith("/30bps")
        and value["gate_evaluation"]["all_primary_gates_pass"]
    )
    report = {
        "schema_version": 1,
        "run_id": f"governed-sec-event-portfolio-{run_stamp}",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "code_commit": commit,
        "evidence_scope": "DEVELOPMENT_ONLY",
        "automatic_promotion_eligible": False,
        "historical_oos_claim_allowed": False,
        "source_structured_report_sha256": _sha256_file(structured_report_path),
        "source_predictions_sha256": _sha256_file(predictions_path),
        "config_sha256": config_hash,
        "pool_artifact_sha256": pool["artifact_sha256"],
        "snapshot_evidence": snapshot_evidence,
        "construction": {
            "id": construction,
            "execution": "strict next open after SEC acceptance",
            "engine_routing_adapter": (
                "target for execution session T is stored on T-1 solely to "
                "satisfy BacktestEngine's T-to-T+1 fill index; the underlying "
                "event is required to be accepted before execution open"),
            "holding_sessions": 5,
            "exit": "next session open after fifth holding-session close",
            "score_threshold": 0.8,
            "active_target": 0.65,
            "single_name_cap": 0.10,
            "unallocated_active_weight": "SPY",
        },
        "gate_policy": {
            "primary_cost_bps": 30.0,
            "thresholds": gate_config,
            "primary_cost_passes": primary_cost_passes,
            "automatic_drop_on_failure": False,
            "interpretation": (
                "gate failures remain recorded for review, but cannot freeze "
                "or promote without an explicit governed decision"),
        },
        "results": results,
        "trial_ledger": {
            "path": str(Path(args.ledger).resolve()),
            "independent_trials": ledger.independent_trial_count(
                "sec_structured_event_portfolio"),
            "incomplete_trial_ids": ledger.incomplete_trial_ids(),
        },
        "disposition": (
            "EVENT_PORTFOLIO_DEVELOPMENT_GATE_PASS_NOT_PROMOTABLE"
            if primary_cost_passes
            else "EVENT_PORTFOLIO_DEVELOPMENT_EVALUATED_NOT_PROMOTED"),
    }
    _atomic_json(_finite(report), Path(args.report).resolve())
    print(f"report={Path(args.report).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
