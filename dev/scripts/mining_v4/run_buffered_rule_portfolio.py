#!/usr/bin/env python3
"""Run the preregistered rank-buffered rule portfolio on exact cash data."""

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
from core.research.mining_v4_portfolio import (  # noqa: E402
    build_buffered_membership_weights,
    expand_decision_signals,
)
from core.research.trial_ledger import AppendOnlyTrialLedger  # noqa: E402
from dev.scripts.mining_v4.run_numeric_rank_mining import (  # noqa: E402
    EXACT_CASH_PRICE_BASIS,
    _atomic_json,
    _flat_cost_model,
    _git_commit,
    _hash_price_inputs,
    _load_exact_cash_panel,
    _portfolio_trial_intent,
    _rolling_excess_fraction,
    _sha256_file,
    _sha256_json,
    _validate_snapshot_manifest,
)

CONSTRUCTION_ID = "spy35_active65_equal_top10_buffer15_membership_only"
LOCKED_CONSTRUCTION = {
    "top_k": 10,
    "exit_rank": 15,
    "spy_weight": 0.35,
    "active_target": 0.65,
    "active_single_name_cap": 0.10,
    "rebalance": "membership_change_only",
}
LOCKED_COSTS_BPS = [30.0, 60.0, 90.0]


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


def _annual_traded_notional(result: Any) -> float:
    if result.equity_curve.empty:
        return 0.0
    years = max(
        (result.equity_curve.index[-1] - result.equity_curve.index[0]).days
        / 365.25,
        1.0 / 252.0,
    )
    traded = float(sum(fill.notional_usd for fill in result.trades))
    return traded / max(float(result.equity_curve.mean()), 1e-12) / years


def _gate_evaluation(
    strategy: dict[str, float],
    benchmark: dict[str, float],
    rolling_fraction: float | None,
    gate: dict[str, Any],
) -> dict[str, Any]:
    cagr_excess = float(strategy["cagr"] - benchmark["cagr"])
    benchmark_drawdown = abs(float(benchmark["max_drawdown"]))
    drawdown_ratio = (
        abs(float(strategy["max_drawdown"])) / benchmark_drawdown
        if benchmark_drawdown > 0 else None
    )
    checks = {
        "after_cost_cagr_excess_vs_spy": (
            cagr_excess >= float(gate["min_after_cost_excess_vs_spy"])),
        "positive_252d_rolling_excess_fraction": (
            rolling_fraction is not None
            and rolling_fraction >= float(
                gate["min_positive_rolling_window_fraction"])),
        "max_drawdown_vs_spy_multiplier": (
            drawdown_ratio is not None
            and drawdown_ratio <= float(
                gate["max_drawdown_vs_spy_multiplier"])),
    }
    return {
        "checks": checks,
        "all_primary_gates_pass": all(checks.values()),
        "max_drawdown_vs_spy_ratio": drawdown_ratio,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--numeric-report", required=True)
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--preregistration", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument(
        "--pool", default="research/universes/semantic_ml_company_pool_v1.json")
    parser.add_argument("--config", default="config/strategy_mining_v4.yaml")
    args = parser.parse_args()

    data_root = Path(args.data_root).resolve()
    numeric_report_path = Path(args.numeric_report).resolve()
    predictions_path = Path(args.predictions).resolve()
    preregistration_path = Path(args.preregistration).resolve()
    pool_path = (PROJ / args.pool).resolve()
    config_path = (PROJ / args.config).resolve()
    manifest_path = data_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    numeric_report = json.loads(numeric_report_path.read_text())
    preregistration = yaml.safe_load(preregistration_path.read_text())
    pool = json.loads(pool_path.read_text())
    config = yaml.safe_load(config_path.read_text())

    if manifest.get("price_basis") != EXACT_CASH_PRICE_BASIS:
        raise RuntimeError("buffered research requires exact cash-ledger prices")
    if preregistration.get("status") != "LOCKED_BEFORE_OUTCOME":
        raise RuntimeError("preregistration is not locked before outcome")
    if preregistration.get("construction") != LOCKED_CONSTRUCTION:
        raise RuntimeError("preregistered construction differs from locked code")
    if [float(value) for value in preregistration.get("costs_bps", [])] != (
        LOCKED_COSTS_BPS
    ):
        raise RuntimeError("preregistered cost grid differs from locked code")
    evidence = preregistration.get("evidence", {})
    expected_hashes = {
        "snapshot_manifest_sha256": _sha256_file(manifest_path),
        "source_numeric_report_sha256": _sha256_file(numeric_report_path),
        "source_predictions_sha256": _sha256_file(predictions_path),
        "implementation_driver_sha256": _sha256_file(Path(__file__).resolve()),
        "portfolio_module_sha256": _sha256_file(
            PROJ / "core/research/mining_v4_portfolio.py"),
    }
    for name, actual in expected_hashes.items():
        if evidence.get(name) != actual:
            raise RuntimeError(f"preregistration {name} differs from input")
    if numeric_report.get("predictions", {}).get("sha256") != (
        expected_hashes["source_predictions_sha256"]
    ):
        raise RuntimeError("numeric report prediction hash differs from artifact")
    if numeric_report.get("snapshot_evidence", {}).get("sha256") != (
        expected_hashes["snapshot_manifest_sha256"]
    ):
        raise RuntimeError("numeric report points to a different snapshot")

    excluded = set(manifest.get("excluded_symbols", []))
    candidates = [
        row["ticker"] for row in pool["selected"]
        if row["ticker"] not in excluded
    ]
    symbols = candidates + ["SPY"]
    snapshot_evidence = _validate_snapshot_manifest(
        data_root,
        pool_hash=pool["artifact_sha256"],
        symbols=symbols,
        through="2024-12-31",
    )
    prediction_long = pd.read_parquet(predictions_path)
    rule_rows = prediction_long[prediction_long["model"].eq("rule_rank")].copy()
    if rule_rows.empty:
        raise RuntimeError("source predictions contain no rule_rank rows")
    scores = rule_rows.pivot(
        index="date", columns="symbol", values="score").reindex(
            columns=candidates)
    scores.index = pd.DatetimeIndex(scores.index)
    scores = scores.sort_index()
    buffered = build_buffered_membership_weights(
        scores,
        top_k=10,
        exit_rank=15,
        spy_weight=0.35,
        active_single_name_cap=0.10,
    )
    first_decision = scores.index.min()
    panel, missing = _load_exact_cash_panel(
        data_root,
        symbols,
        start=str(first_decision.date()),
        end="2024-12-31",
    )
    if missing:
        raise RuntimeError(f"exact cash panel missing symbols: {missing}")
    daily_index = panel["close"].index
    signals = expand_decision_signals(
        buffered.decision_weights, daily_index)
    spy_decision = pd.DataFrame(
        {"SPY": [1.0]}, index=pd.DatetimeIndex([first_decision]))
    spy_signals = expand_decision_signals(spy_decision, daily_index)

    ledger = AppendOnlyTrialLedger(Path(args.ledger).resolve())
    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    price_hash, _ = _hash_price_inputs(data_root, symbols)
    data_hash = _sha256_json({
        "prices": price_hash,
        "source_numeric_report": expected_hashes[
            "source_numeric_report_sha256"],
        "source_predictions": expected_hashes["source_predictions_sha256"],
        "preregistration": _sha256_file(preregistration_path),
    })
    common_intent = {
        "universe_hash": pool["artifact_sha256"],
        "data_hash": data_hash,
        "config_hash": _sha256_file(preregistration_path),
        "code_commit": _git_commit(),
        "feature_id": numeric_report["panel"]["label"],
        "start": str(first_decision.date()),
        "end": "2024-12-31",
        "observed_through": str(config["observed_through"]),
        "seed": int(config["models"]["seed"]),
        "hypothesis_family": "numeric_rank_buffered_portfolio",
    }
    results: dict[str, Any] = {}
    for cost_bps in LOCKED_COSTS_BPS:
        trial_id = f"{run_stamp}-rule-rank-buffer15-{cost_bps:g}bps"
        registration = ledger.register_intent(_portfolio_trial_intent(
            trial_id=trial_id,
            model_name="rule_rank",
            construction=CONSTRUCTION_ID,
            cost_bps=cost_bps,
            **common_intent,
        ))
        cost_model = _flat_cost_model(cost_bps)
        strategy = BacktestEngine(
            cost_model,
            initial_capital=100_000.0,
            min_trade_usd=0.0,
            rebalance_threshold=0.0,
        ).run(
            signals,
            panel["close"],
            open_df=panel["open"],
            benchmark_series=panel["total_return_close"]["SPY"],
            rebalance_dates=buffered.decision_weights.index,
            cash_distributions_df=panel["cash_distribution"],
        )
        benchmark = BacktestEngine(
            cost_model,
            initial_capital=100_000.0,
            min_trade_usd=0.0,
            rebalance_threshold=0.0,
        ).run(
            spy_signals,
            panel["close"][["SPY"]],
            open_df=panel["open"][["SPY"]],
            rebalance_dates=[first_decision],
            cash_distributions_df=panel["cash_distribution"][["SPY"]],
        )
        rolling = _rolling_excess_fraction(
            strategy.equity_curve, benchmark.equity_curve)
        cagr_excess = float(
            strategy.metrics["cagr"] - benchmark.metrics["cagr"])
        baseline_key = (
            "rule_rank/spy35_active65_equal_top10/"
            f"{cost_bps:g}bps")
        baseline = numeric_report["portfolio_results"][baseline_key]
        outcome = {
            "cost_bps": cost_bps,
            "independent_trial": registration.independent_trial,
            "strategy": _finite(strategy.metrics),
            "spy_buy_hold": _finite(benchmark.metrics),
            "cagr_excess_vs_spy": cagr_excess,
            "total_return_excess_vs_spy": float(
                strategy.metrics["total_return"]
                - benchmark.metrics["total_return"]),
            "positive_252d_rolling_excess_fraction": rolling,
            "annual_gross_traded_notional_over_average_nav": (
                _annual_traded_notional(strategy)),
            "n_trades": strategy.n_trades,
            "total_slippage_usd": strategy.total_slippage_usd,
            "cash_distributions_usd": strategy.metrics.get(
                "cash_distributions_usd", 0.0),
            "source_monthly_equal_top10_baseline": baseline,
            "trade_count_reduction_vs_source_baseline": (
                1.0 - strategy.n_trades / max(int(baseline["n_trades"]), 1)),
            "slippage_reduction_vs_source_baseline": (
                1.0
                - strategy.total_slippage_usd
                / max(float(baseline["total_slippage_usd"]), 1e-12)
            ),
        }
        outcome["gate_evaluation"] = _gate_evaluation(
            strategy.metrics,
            benchmark.metrics,
            rolling,
            config["forward_freeze_gate"],
        )
        results[f"{cost_bps:g}bps"] = _finite(outcome)
        ledger.record_outcome(trial_id, _finite(outcome))
        print(
            f"{cost_bps:g}bps: excess={cagr_excess:.6f} "
            f"rolling={rolling} trades={strategy.n_trades}",
            flush=True,
        )

    primary = results["30bps"]
    report = {
        "schema_version": 1,
        "run_id": f"governed-buffered-rule-{run_stamp}",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "code_commit": _git_commit(),
        "evidence_scope": "DEVELOPMENT_ONLY_POST_SELECTION",
        "automatic_promotion_eligible": False,
        "historical_oos_claim_allowed": False,
        "post_selection_disclosure": (
            "The rule family and SPY-anchored equal-weight baseline were "
            "selected after observing 2015-2024 development results. This "
            "single buffered construction is preregistered only to constrain "
            "additional researcher degrees of freedom; future data is still "
            "required for independent confirmation."),
        "preregistration": {
            "path": str(preregistration_path),
            "sha256": _sha256_file(preregistration_path),
            "status": preregistration["status"],
        },
        "snapshot_evidence": snapshot_evidence,
        "source_numeric_report_sha256": expected_hashes[
            "source_numeric_report_sha256"],
        "source_predictions_sha256": expected_hashes[
            "source_predictions_sha256"],
        "construction": {
            "id": CONSTRUCTION_ID,
            **LOCKED_CONSTRUCTION,
            "evaluated_month_end_dates": buffered.evaluated_decision_dates,
            "emitted_membership_change_targets": (
                buffered.membership_change_dates),
        },
        "pricing": (
            "split-adjusted raw OHLC plus exact per-share cash account credit"),
        "costs_bps": LOCKED_COSTS_BPS,
        "gate_policy": {
            "primary_cost_bps": 30.0,
            "thresholds": config["forward_freeze_gate"],
            "automatic_drop_on_failure": False,
        },
        "results": results,
        "disposition": (
            "DEVELOPMENT_GATE_PASS_REQUIRES_FUTURE_CONFIRMATION"
            if primary["gate_evaluation"]["all_primary_gates_pass"]
            else "DEVELOPMENT_GATE_FAIL_RETAIN_FOR_REVIEW"),
        "trial_ledger": {
            "path": str(Path(args.ledger).resolve()),
            "independent_trials": ledger.independent_trial_count(
                "numeric_rank_buffered_portfolio"),
            "incomplete_trial_ids": ledger.incomplete_trial_ids(),
        },
    }
    _atomic_json(_finite(report), Path(args.report).resolve())
    print(f"report={Path(args.report).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
