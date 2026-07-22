#!/usr/bin/env python3
"""Execute the preregistered 30-round diverse strategy mining campaign."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, cast

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.backtest.backtest_engine import BacktestEngine  # noqa: E402
from core.research.diverse_mining_campaign import (  # noqa: E402
    cross_sectional_rule_score,
    load_campaign,
    select_formal_candidates,
    synthetic_market_neutral_returns,
)
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
    build_buffered_membership_weights,
    build_decision_weights,
    expand_decision_signals,
)
from core.research.qualification_v2 import (  # noqa: E402
    build_qualification_artifact,
    sha256_file,
    validate_qualification_artifact,
)
from core.research.sec_event_portfolio import (  # noqa: E402
    build_event_overlay_weights,
)
from core.research.trial_ledger import (  # noqa: E402
    AppendOnlyTrialLedger,
    TrialIntent,
)
from dev.scripts.mining_v4.run_numeric_rank_mining import (  # noqa: E402
    _flat_cost_model,
    _load_exact_cash_panel,
    _validate_snapshot_manifest,
)


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _sha_json(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _finite(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _finite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(item) for item in value]
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    os.close(descriptor)
    temporary = Path(name)
    try:
        frame.to_parquet(temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _assert_input_hash(path: Path, expected: str, label: str) -> None:
    actual = sha256_file(path)
    if actual != expected:
        raise RuntimeError(f"{label} hash mismatch expected={expected} actual={actual}")


def _prefix_and_mutation_audit(
    panel: Mapping[str, pd.DataFrame],
    market: pd.Series,
    full_features: Mapping[str, pd.DataFrame],
    eligibility: pd.DataFrame,
    eligibility_config: DynamicEligibilityConfig,
) -> dict[str, Any]:
    prefix_end = pd.Timestamp("2023-12-29")
    prefix_panel = {
        name: frame.loc[frame.index <= prefix_end].copy()
        for name, frame in panel.items()
    }
    prefix_market = market.loc[market.index <= prefix_end]
    prefix_features = build_causal_numeric_features(prefix_panel, prefix_market)
    prefix_eligibility = build_dynamic_eligibility_mask(
        prefix_panel["close"], prefix_panel["volume"], eligibility_config
    )
    feature_prefix_pass = all(
        np.allclose(
            prefix_features[name].to_numpy(),
            full_features[name].loc[prefix_features[name].index].to_numpy(),
            equal_nan=True,
        )
        for name in prefix_features
    )
    eligibility_prefix_pass = prefix_eligibility.equals(
        eligibility.loc[prefix_eligibility.index]
    )

    mutation_date = panel["close"].index[-1]
    mutated = {name: frame.copy() for name, frame in panel.items()}
    for name in ("open", "high", "low", "close", "total_return_close"):
        if name in mutated:
            mutated[name].loc[mutation_date] *= 1.10
    mutated_market = market.copy()
    mutated_features = build_causal_numeric_features(mutated, mutated_market)
    prior = panel["close"].index[-2]
    mutation_pass = all(
        np.allclose(
            mutated_features[name].loc[:prior].to_numpy(),
            full_features[name].loc[:prior].to_numpy(),
            equal_nan=True,
        )
        for name in full_features
    )
    return {
        "prefix_end": str(prefix_end.date()),
        "feature_prefix_invariance_passed": feature_prefix_pass,
        "eligibility_prefix_invariance_passed": eligibility_prefix_pass,
        "future_mutation_date": str(mutation_date.date()),
        "future_mutation_passed": mutation_pass,
    }


def _prediction_scores(
    path: Path,
    model: str,
    decisions: pd.DatetimeIndex,
    candidates: list[str],
    eligibility: pd.DataFrame,
) -> pd.DataFrame:
    long = pd.read_parquet(path, filters=[("model", "==", model)])
    if long.empty:
        raise RuntimeError(f"prediction artifact has no model {model!r}")
    pivot = long.pivot(index="date", columns="symbol", values="score")
    pivot.index = pd.DatetimeIndex(pivot.index)
    return pivot.reindex(index=decisions, columns=candidates).where(eligibility)


def _targets_from_score(
    score: pd.DataFrame,
    volatility: pd.DataFrame,
    construction: str,
    *,
    market: pd.Series,
) -> pd.DataFrame:
    if construction == "active":
        return build_decision_weights(
            score, volatility, cast(Construction, "active_top10_control")
        )
    if construction == "hybrid":
        return build_decision_weights(
            score, volatility,
            cast(Construction, "spy35_active65_equal_top10"),
        )
    if construction == "rank_vol":
        return build_decision_weights(
            score, volatility,
            cast(Construction, "spy35_active65_rank_vol_top10"),
        )
    if construction == "buffer15":
        return build_buffered_membership_weights(
            score, top_k=10, exit_rank=15
        ).decision_weights
    if construction in {"dual_momentum", "vol_regime"}:
        weights = build_decision_weights(
            score, volatility,
            cast(Construction, "spy35_active65_equal_top10"),
        )
        active_columns = [column for column in weights if column != "SPY"]
        if construction == "dual_momentum":
            market_momentum = market.div(market.shift(252)).sub(1.0).reindex(weights.index)
            inactive = market_momentum <= 0.0
            weights.loc[inactive, active_columns] = 0.0
            weights.loc[inactive, "SPY"] = 1.0
        else:
            market_volatility = (
                market.pct_change(fill_method=None)
                .rolling(63, min_periods=63).std(ddof=1)
                .mul(math.sqrt(252.0)).reindex(weights.index)
            )
            multiplier = (0.15 / market_volatility).clip(lower=0.25, upper=1.0)
            weights.loc[:, active_columns] = weights.loc[:, active_columns].mul(
                multiplier, axis=0
            )
            weights.loc[:, "SPY"] = 1.0 - weights.loc[:, active_columns].sum(axis=1)
        return weights
    raise RuntimeError(f"unsupported construction {construction!r}")


def _run_backtest(
    targets: pd.DataFrame,
    panel: Mapping[str, pd.DataFrame],
    *,
    cost_bps: float,
) -> tuple[Any, bool]:
    signals = expand_decision_signals(targets, panel["close"].index)
    result = BacktestEngine(
        _flat_cost_model(cost_bps),
        initial_capital=100_000.0,
        min_trade_usd=0.0,
        rebalance_threshold=0.0,
    ).run(
        signals,
        panel["close"],
        open_df=panel["open"],
        benchmark_series=panel["total_return_close"]["SPY"],
        rebalance_dates=targets.index,
        cash_distributions_df=panel["cash_distribution"],
    )
    timing_passed = bool(result.trades) and all(
        pd.Timestamp(fill.fill_date) > pd.Timestamp(fill.signal_date)
        for fill in result.trades
    )
    return result, timing_passed


def _spy_backtest(
    first_decision: pd.Timestamp,
    panel: Mapping[str, pd.DataFrame],
    cost_bps: float,
) -> Any:
    targets = pd.DataFrame(
        {"SPY": [1.0]}, index=pd.DatetimeIndex([first_decision])
    )
    return _run_backtest(targets, panel, cost_bps=cost_bps)[0]


def _metric_summary(result: Any, spy: Any) -> dict[str, Any]:
    common = result.equity_curve.index.intersection(spy.equity_curve.index)
    strategy = result.equity_curve.loc[common]
    benchmark = spy.equity_curve.loc[common]
    window = 252
    rolling_fraction = None
    if len(common) > window:
        strategy_window = strategy.div(strategy.shift(window)).sub(1.0)
        benchmark_window = benchmark.div(benchmark.shift(window)).sub(1.0)
        valid = pd.concat([strategy_window, benchmark_window], axis=1).dropna()
        rolling_fraction = float((valid.iloc[:, 0] > valid.iloc[:, 1]).mean())
    spy_drawdown = abs(float(spy.metrics["max_drawdown"]))
    return {
        "candidate_metrics": _finite(result.metrics),
        "spy_metrics": _finite(spy.metrics),
        "cagr_excess_vs_spy": float(result.metrics["cagr"] - spy.metrics["cagr"]),
        "rolling_252d_excess_fraction": rolling_fraction,
        "max_drawdown_vs_spy_ratio": (
            abs(float(result.metrics["max_drawdown"])) / spy_drawdown
            if spy_drawdown > 0 else None
        ),
        "trades": result.n_trades,
        "commission_usd": result.total_commission_usd,
        "slippage_usd": result.total_slippage_usd,
    }


def _trial_intent(
    spec: Mapping[str, Any],
    *,
    code_commit: str,
    universe_hash: str,
    data_hash: str,
    config_hash: str,
) -> TrialIntent:
    return TrialIntent(
        trial_id=f"diverse-mining-v1-r{int(spec['round']):02d}-{spec['id']}",
        hypothesis_family=str(spec["family"]),
        mechanism_id=str(spec["kind"]),
        universe_hash=universe_hash,
        data_hash=data_hash,
        config_hash=config_hash,
        code_commit=code_commit,
        feature_id=_sha_json(spec.get("features", spec.get("models", spec.get("model", "none")))),
        model_id=str(spec.get("model", spec["kind"])),
        label_id="after_cost_total_return_vs_spy",
        construction_id=str(spec["construction"]),
        cost_id="fixed_30_60_90_bps_stress_bundle",
        execution_id=(
            "next_session_open_exact_cash"
            if spec["kind"] not in {"synthetic_short", "blocked_feasibility"}
            else "research_diagnostic_not_formal_execution"
        ),
        seed=42,
        period_start="2015-01-01",
        period_end="2024-12-31",
        observed_through="2026-07-17",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preregistration",
        default="research/preregistrations/20260721-diverse-mining-campaign-v1.yaml",
    )
    parser.add_argument(
        "--snapshot-root",
        default=(
            "/home/zibo/Documents/projects/pqs/data/research/mining_v4/"
            "yahoo_exact_cash_ledger_2007_2024_v6"
        ),
    )
    parser.add_argument(
        "--numeric-predictions",
        default=(
            "/home/zibo/Documents/projects/pqs/data/research/mining_v4/"
            "numeric_rank_exact_cash_v6.parquet"
        ),
    )
    parser.add_argument(
        "--semantic-predictions",
        default=(
            "/home/zibo/Documents/projects/pqs/data/research/mining_v4/"
            "sec_8k_lexical_exact_cash_v6.parquet"
        ),
    )
    parser.add_argument(
        "--output-dir",
        default="research/results/mining_campaign_20260721_v1",
    )
    args = parser.parse_args()

    prereg_path = (ROOT / args.preregistration).resolve()
    snapshot_root = Path(args.snapshot_root).resolve()
    numeric_path = Path(args.numeric_predictions).resolve()
    semantic_path = Path(args.semantic_predictions).resolve()
    output_dir = (ROOT / args.output_dir).resolve()
    campaign = load_campaign(prereg_path)
    if _git("status", "--porcelain", "--untracked-files=no"):
        raise RuntimeError("tracked worktree must be clean before campaign execution")
    _git("ls-files", "--error-unmatch", str(prereg_path.relative_to(ROOT)))
    commit = _git("rev-parse", "HEAD")
    config_hash = sha256_file(prereg_path)
    data_doc = campaign["data"]
    pool_path = ROOT / data_doc["pool_path"]
    _assert_input_hash(
        snapshot_root / "manifest.json",
        data_doc["snapshot_manifest_sha256"],
        "exact-cash snapshot",
    )
    _assert_input_hash(pool_path, data_doc["pool_file_sha256"], "company pool")
    _assert_input_hash(numeric_path, data_doc["numeric_oof_sha256"], "numeric OOF")
    _assert_input_hash(semantic_path, data_doc["semantic_oof_sha256"], "semantic OOF")
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger = AppendOnlyTrialLedger(output_dir / "trial_ledger.jsonl")
    if ledger.verified_events():
        raise RuntimeError("campaign output ledger already exists and is non-empty")

    pool = json.loads(pool_path.read_text(encoding="utf-8"))
    snapshot_manifest = json.loads(
        (snapshot_root / "manifest.json").read_text(encoding="utf-8")
    )
    eligible_snapshot = set(snapshot_manifest["eligible_symbols"])
    pool_candidates = [row["ticker"] for row in pool["selected"]]
    candidates = [symbol for symbol in pool_candidates if symbol in eligible_snapshot]
    symbols = candidates + ["SPY"]
    print(f"[preflight] commit={commit} candidates={len(candidates)}", flush=True)
    snapshot_evidence = _validate_snapshot_manifest(
        snapshot_root,
        pool_hash=pool["artifact_sha256"],
        symbols=symbols,
        through="2024-12-31",
    )
    panel, missing = _load_exact_cash_panel(
        snapshot_root, symbols, start="2007-01-01", end="2024-12-31"
    )
    if missing:
        raise RuntimeError(f"exact-cash panel missing {missing}")
    candidate_panel = {
        name: frame.loc[:, candidates] for name, frame in panel.items()
    }
    market = panel["total_return_close"]["SPY"]
    eligibility_config = DynamicEligibilityConfig()
    eligibility_daily = build_dynamic_eligibility_mask(
        candidate_panel["close"], candidate_panel["volume"], eligibility_config
    )
    features_daily = build_causal_numeric_features(candidate_panel, market)
    timing_audit = _prefix_and_mutation_audit(
        candidate_panel,
        market,
        features_daily,
        eligibility_daily,
        eligibility_config,
    )
    decisions = month_end_decision_dates(panel["close"].index, market)
    decisions = decisions[(decisions >= "2015-01-01") & (decisions <= "2024-12-31")]
    eligibility = eligibility_daily.loc[decisions]
    features = {name: frame.loc[decisions] for name, frame in features_daily.items()}
    volatility = features["vol_63"]
    print(
        f"[preflight] sessions={len(panel['close'])} decisions={len(decisions)} "
        f"timing={timing_audit}",
        flush=True,
    )

    result_rows: list[dict[str, Any]] = []
    candidate_returns: dict[str, dict[str, pd.Series]] = {}
    spy_returns: dict[str, pd.Series] = {}
    family_by_candidate: dict[str, str] = {}
    trial_id_by_candidate: dict[str, str] = {}
    targets_by_candidate: dict[str, pd.DataFrame] = {}
    scores_by_rule_id: dict[str, pd.DataFrame] = {}
    prediction_cache: dict[str, pd.DataFrame] = {}

    for spec in campaign["rounds"]:
        round_number = int(spec["round"])
        candidate_id = str(spec["id"])
        intent = _trial_intent(
            spec,
            code_commit=commit,
            universe_hash=pool["artifact_sha256"],
            data_hash=data_doc["snapshot_manifest_sha256"],
            config_hash=config_hash,
        )
        trial_id_by_candidate[candidate_id] = intent.trial_id
        ledger.register_intent(intent)
        print(f"[round {round_number:02d}/30] {candidate_id}", flush=True)
        if spec["kind"] == "blocked_feasibility":
            ledger.record_failed(
                intent.trial_id,
                error_type="PreRegisteredFeasibilityBlocker",
                message=str(spec["blocker"]),
            )
            result_rows.append({
                "round": round_number,
                "candidate_id": candidate_id,
                "family": spec["family"],
                "status": "FAILED_COUNTED",
                "reason": spec["blocker"],
                "formal_candidate_eligible": False,
            })
            continue
        ledger.record_started(intent.trial_id)
        try:
            if spec["kind"] in {"rule", "synthetic_short"}:
                score = cross_sectional_rule_score(
                    features, eligibility, spec["features"]
                )
                scores_by_rule_id[candidate_id] = score
            elif spec["kind"] == "pretrained_prediction":
                model = str(spec["model"])
                if model not in prediction_cache:
                    prediction_cache[model] = _prediction_scores(
                        numeric_path, model, decisions, candidates, eligibility
                    )
                score = prediction_cache[model]
            elif spec["kind"] == "prediction_ensemble":
                components = []
                for model in spec["models"]:
                    if model not in prediction_cache:
                        prediction_cache[model] = _prediction_scores(
                            numeric_path, model, decisions, candidates, eligibility
                        )
                    components.append(
                        prediction_cache[model].rank(axis=1, pct=True)
                    )
                score = sum(components) / len(components)
            elif spec["kind"] == "semantic_event":
                semantic_long = pd.read_parquet(
                    semantic_path, filters=[("model", "==", spec["model"])]
                )
                semantic_score = semantic_long.pivot(
                    index="date", columns="symbol", values="score"
                ).reindex(columns=candidates)
                semantic_score.index = pd.DatetimeIndex(semantic_score.index)
                overlay = build_event_overlay_weights(
                    semantic_score, panel["close"].index
                )
                targets = overlay.decision_weights
                score = semantic_score
            else:
                raise RuntimeError(f"unsupported round kind {spec['kind']!r}")

            if spec["kind"] == "synthetic_short":
                asset_returns = (
                    candidate_panel["total_return_close"]
                    .pct_change(fill_method=None)
                )
                stress_returns = {
                    str(cost): synthetic_market_neutral_returns(
                        score,
                        asset_returns,
                        cost_bps=float(cost),
                        annual_borrow_fee=0.03,
                    )
                    for cost in (30, 60, 90)
                }
                base = stress_returns["30"]
                candidate_returns[candidate_id] = stress_returns
                spy_returns[candidate_id] = market.pct_change(fill_method=None).reindex(base.index)
                outcome = {
                    "status": "RESEARCH_INCOMPLETE",
                    "reason": "NO_POINT_IN_TIME_BORROW_LOCATE_FEE_RECALL_HISTORY",
                    "synthetic_diagnostic": {
                        cost: {
                            "cumulative_return": float((1.0 + values.fillna(0.0)).prod() - 1.0),
                            "annualized_mean": float(values.mean() * 252.0),
                        }
                        for cost, values in stress_returns.items()
                    },
                    "formal_candidate_eligible": False,
                }
            else:
                if spec["kind"] != "semantic_event":
                    targets = _targets_from_score(
                        score,
                        volatility.reindex(score.index),
                        str(spec["construction"]),
                        market=market,
                    )
                    if spec["kind"] == "rule":
                        replay = _targets_from_score(
                            score,
                            volatility.reindex(score.index),
                            str(spec["construction"]),
                            market=market,
                        )
                        if not targets.equals(replay):
                            raise RuntimeError("deterministic target replay mismatch")
                targets_by_candidate[candidate_id] = targets
                stress_metrics: dict[str, Any] = {}
                returns_by_cost: dict[str, pd.Series] = {}
                timing_passed = True
                spy_base: pd.Series | None = None
                for cost in (30.0, 60.0, 90.0):
                    result, execution_timing = _run_backtest(
                        targets, panel, cost_bps=cost
                    )
                    spy = _spy_backtest(targets.index[0], panel, cost)
                    stress_metrics[f"{cost:g}"] = _metric_summary(result, spy)
                    returns_by_cost[f"{cost:g}"] = result.equity_curve.pct_change(
                        fill_method=None
                    )
                    if cost == 30.0:
                        spy_base = spy.equity_curve.pct_change(fill_method=None)
                    timing_passed = timing_passed and execution_timing
                    del result, spy
                    gc.collect()
                assert spy_base is not None
                candidate_returns[candidate_id] = returns_by_cost
                spy_returns[candidate_id] = spy_base
                family_by_candidate[candidate_id] = str(spec["family"])
                is_candidate_specific = spec["kind"] == "rule"
                outcome = {
                    "status": "COMPLETED_DEVELOPMENT_ONLY",
                    "stress_metrics": stress_metrics,
                    "candidate_specific_timing": {
                        "prefix_invariance_passed": bool(
                            is_candidate_specific
                            and timing_audit["feature_prefix_invariance_passed"]
                            and timing_audit["eligibility_prefix_invariance_passed"]
                        ),
                        "next_session_execution_passed": timing_passed,
                        "deterministic_replay_passed": is_candidate_specific,
                        "future_mutation_passed": bool(
                            is_candidate_specific
                            and timing_audit["future_mutation_passed"]
                        ),
                    },
                    "formal_candidate_eligible": is_candidate_specific,
                }
            ledger.record_outcome(intent.trial_id, _finite(outcome))
            round_artifact = output_dir / "rounds" / f"{round_number:02d}-{candidate_id}.json"
            _atomic_json(round_artifact, _finite({
                "schema_version": 1,
                "campaign_id": campaign["campaign_id"],
                "trial_id": intent.trial_id,
                "round_spec": spec,
                "outcome": outcome,
            }))
            ledger.bind_artifact(
                intent.trial_id,
                path=str(round_artifact.relative_to(ROOT)),
                sha256=sha256_file(round_artifact),
                artifact_type="MINING_ROUND_RESULT",
            )
            result_rows.append({
                "round": round_number,
                "candidate_id": candidate_id,
                "family": spec["family"],
                **_finite(outcome),
            })
        except Exception as exc:
            ledger.record_failed(
                intent.trial_id,
                error_type=type(exc).__name__,
                message=str(exc),
            )
            result_rows.append({
                "round": round_number,
                "candidate_id": candidate_id,
                "family": spec["family"],
                "status": "FAILED_COUNTED",
                "reason": f"{type(exc).__name__}: {exc}",
                "formal_candidate_eligible": False,
            })

    ledger_snapshot = ledger.snapshot()
    if ledger_snapshot["raw_independent_n"] != 30:
        raise RuntimeError(f"ledger raw N is not 30: {ledger_snapshot}")
    if ledger_snapshot["incomplete_trial_ids"]:
        raise RuntimeError("campaign ledger has incomplete trials")

    successful_long = [
        row["candidate_id"] for row in result_rows
        if row.get("status") == "COMPLETED_DEVELOPMENT_ONLY"
        and row["candidate_id"] in family_by_candidate
    ]
    common_start = pd.Timestamp(data_doc["common_qualification_start"])
    common_index: pd.DatetimeIndex | None = None
    for candidate_id in successful_long:
        index = candidate_returns[candidate_id]["30"].dropna().index
        index = index[index >= common_start]
        common_index = index if common_index is None else common_index.intersection(index)
    if common_index is None or len(common_index) < 252:
        raise RuntimeError("insufficient common qualification return history")
    common_index = common_index.sort_values()
    matrix = np.column_stack([
        candidate_returns[candidate_id]["30"].reindex(common_index).to_numpy()
        for candidate_id in successful_long
    ])
    if not np.isfinite(matrix).all():
        raise RuntimeError("trial performance matrix contains NaN/inf")

    returns_frame = pd.DataFrame(index=common_index)
    qualification_rows: list[dict[str, Any]] = []
    for candidate_id in successful_long:
        returns_frame[f"{candidate_id}__30"] = candidate_returns[candidate_id]["30"].reindex(common_index)
        returns_frame[f"{candidate_id}__60"] = candidate_returns[candidate_id]["60"].reindex(common_index)
        returns_frame[f"{candidate_id}__90"] = candidate_returns[candidate_id]["90"].reindex(common_index)
    benchmark_common = spy_returns[successful_long[0]].reindex(common_index)
    returns_frame["SPY__30"] = benchmark_common
    _atomic_parquet(output_dir / "daily_net_returns.parquet", returns_frame)

    for candidate_id in successful_long:
        row = next(item for item in result_rows if item["candidate_id"] == candidate_id)
        timing = row["candidate_specific_timing"]
        input_bundle = {
            "schema_version": 1,
            "candidate_id": candidate_id,
            "observed_through": campaign["observed_through"],
            "dates": [str(date.date()) for date in common_index],
            "candidate_net_returns": candidate_returns[candidate_id]["30"].reindex(
                common_index
            ).tolist(),
            "benchmark_total_returns": benchmark_common.tolist(),
            "trial_ids": [trial_id_by_candidate[item] for item in successful_long],
            "trial_period_returns": matrix.tolist(),
            "cost_stress_returns": {
                "base_30bps": candidate_returns[candidate_id]["30"].reindex(
                    common_index
                ).tolist(),
                "double_60bps": candidate_returns[candidate_id]["60"].reindex(
                    common_index
                ).tolist(),
                "triple_90bps": candidate_returns[candidate_id]["90"].reindex(
                    common_index
                ).tolist(),
            },
            "cpcv": {
                "n_groups": 6,
                "k_test": 2,
                "horizon": 21,
                "embargo_frac": 0.01,
            },
            "candidate_specific_timing": timing,
            "freeze_thresholds": {
                "min_positive_rolling_fraction": 0.60,
                "max_drawdown_vs_spy_multiplier": 1.25,
            },
        }
        input_path = output_dir / "qualification_inputs" / f"{candidate_id}.json"
        _atomic_json(input_path, _finite(input_bundle))
        artifact = build_qualification_artifact(
            input_bundle_path=input_path,
            ledger_path=output_dir / "trial_ledger.jsonl",
            repo_root=ROOT,
            code_commit=commit,
        )
        artifact_path = output_dir / "qualifications" / f"{candidate_id}.json"
        _atomic_json(artifact_path, _finite(artifact))
        validation = validate_qualification_artifact(
            artifact_path,
            expected_candidate_id=candidate_id,
            expected_code_commit=commit,
            repo_root=ROOT,
        )
        computed = artifact["computed"]
        qualification_rows.append({
            "candidate_id": candidate_id,
            "family": family_by_candidate[candidate_id],
            "qualification_passed": validation.passed,
            "failed_checks": list(validation.failed_checks),
            "active_cagr_excess": computed["active"]["cagr_excess_vs_spy"],
            "active_sharpe": computed["active"]["annualized_sharpe"],
            "qualification_path": str(artifact_path.relative_to(ROOT)),
            "qualification_sha256": sha256_file(artifact_path),
            "canonical_gates": computed["gates"],
        })

    qualification_rows.sort(
        key=lambda row: float(row["active_cagr_excess"]), reverse=True
    )
    base_return_map = {
        candidate_id: candidate_returns[candidate_id]["30"].reindex(common_index)
        for candidate_id in successful_long
    }
    selected, selection_rejections = select_formal_candidates(
        qualification_rows,
        base_return_map,
        maximum=5,
        max_correlation=0.70,
    )
    frozen: list[dict[str, Any]] = []
    for candidate in selected:
        candidate_id = candidate["candidate_id"]
        freeze = {
            "schema_version": 1,
            "candidate_id": candidate_id,
            "status": "FROZEN_FORWARD_CANDIDATE",
            "evidence_scope": "DEVELOPMENT_ONLY",
            "automatic_promotion_eligible": False,
            "code_commit": commit,
            "preregistration": {
                "path": str(prereg_path.relative_to(ROOT)),
                "sha256": config_hash,
            },
            "qualification": {
                "path": candidate["qualification_path"],
                "sha256": candidate["qualification_sha256"],
            },
            "trial_ledger": ledger.snapshot(),
            "snapshot_manifest_sha256": data_doc["snapshot_manifest_sha256"],
            "pool_artifact_sha256": pool["artifact_sha256"],
            "source_batch_bridge_ready": False,
            "paper_readiness": "NOT_READY_UNTIL_TRUSTED_FUTURE_SOURCE_BATCH",
            "forward_start": "SAME_FUTURE_SESSION_FOR_ALL_FROZEN_CANDIDATES",
            "no_feedback_to_miner": True,
        }
        freeze_path = output_dir / "frozen_candidates" / f"{candidate_id}.json"
        _atomic_json(freeze_path, freeze)
        frozen.append({
            "candidate_id": candidate_id,
            "family": candidate["family"],
            "freeze_path": str(freeze_path.relative_to(ROOT)),
            "freeze_sha256": sha256_file(freeze_path),
        })

    report = {
        "schema_version": 1,
        "campaign_id": campaign["campaign_id"],
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "code_commit": commit,
        "evidence_scope": "DEVELOPMENT_ONLY",
        "automatic_promotion_eligible": False,
        "observed_through": campaign["observed_through"],
        "historical_oos_claim_allowed": False,
        "survivorship_boundary": "PROSPECTIVE_CURRENT_COMPANY_POOL_USED_FOR_DEVELOPMENT",
        "snapshot_evidence": snapshot_evidence,
        "timing_audit": timing_audit,
        "ledger": ledger.snapshot(),
        "rounds_executed": 30,
        "round_results": result_rows,
        "qualification_common_period": {
            "start": str(common_index[0].date()),
            "end": str(common_index[-1].date()),
            "sessions": len(common_index),
            "successful_long_trials_in_matrix": len(successful_long),
        },
        "qualifications": qualification_rows,
        "formal_frozen_candidates": frozen,
        "formal_candidate_count": len(frozen),
        "selection_rejections": selection_rejections,
        "exit": {
            "condition": (
                "FIVE_FORMAL_CANDIDATES"
                if len(frozen) >= 5 else "MAXIMUM_30_ROUNDS"
            ),
            "target_formal_candidates": 5,
            "maximum_rounds": 30,
            "completed": True,
        },
        "short_disposition": "RESEARCH_INCOMPLETE_NO_PIT_BORROW_HISTORY",
        "llm_disposition": "FAILED_COUNTED_NO_FROZEN_RESPONSE_CORPUS",
    }
    report_path = output_dir / "campaign_report.json"
    _atomic_json(report_path, _finite(report))
    print(f"report={report_path}")
    print(f"rounds_executed=30 formal_candidates={len(frozen)}")
    print(f"exit={report['exit']['condition']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
