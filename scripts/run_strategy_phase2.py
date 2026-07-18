#!/usr/bin/env python3
"""Preregister, evaluate, and gate the frozen phase-two ETF candidates.

Stages are intentionally separate so development results can be committed
before validation and only validation-qualified, frozen finalists can unlock
the hypothesis-scoped final holdout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.backtest.backtest_engine import BacktestEngine, BacktestResult, compute_metrics
from core.config.loader import load_config
from core.config.schemas.cost_model import CostModelConfig
from core.data.price_access import load_adjusted_panel
from core.execution.cost_model import CostModel
from core.research.phase2.metrics import (
    annual_fold_metrics,
    detailed_metrics,
    stationary_bootstrap_cagr_ci,
)
from core.research.phase2.promotion import CandidateEvidence, PromotionPolicy
from core.research.phase2.registry import ExperimentRegistry, ExperimentSpec
from core.signals.strategies.phase2_etf import (
    AdaptiveCoreParams,
    AdaptiveCoreStrategy,
    ControlledGrowthParams,
    ControlledGrowthStrategy,
    EtfReversionParams,
    EtfReversionStrategy,
    SectorRotationParams,
    SectorRotationStrategy,
)

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = ROOT / "research/registry/experiment_registry.json"
RESULT_ROOT = ROOT / "research/results/phase2"
HOLDOUT_ACCESS_PATH = ROOT / "research/holdout/phase2_access_log.json"
SELECTION_PATH = RESULT_ROOT / "development/selection.json"
VALIDATION_SUMMARY_PATH = RESULT_ROOT / "validation/summary.json"
HOLDOUT_SUMMARY_PATH = RESULT_ROOT / "holdout/summary.json"
POLICY_PATH = ROOT / "config/strategy_promotion.yaml"
SEED = 20260717


FAMILY_META: dict[str, dict[str, str]] = {
    "adaptive_core": {
        "version": "v1",
        "strategy_id": "adaptive_core_v1",
        "strategy_type": "stable_core",
        "benchmark": "SPY",
        "hypothesis": "Multi-timescale trend plus volatility scaling improves core risk-adjusted returns.",
    },
    "controlled_growth": {
        "version": "v1",
        "strategy_id": "controlled_growth_v1",
        "strategy_type": "growth_engine",
        "benchmark": "QQQ",
        "hypothesis": "Breadth and volatility gating makes a capped TQQQ growth sleeve additive to QQQ.",
    },
    "sector_rotation": {
        "version": "v1",
        "strategy_id": "sector_rotation_v1",
        "strategy_type": "etf_rotation",
        "benchmark": "SPY",
        "hypothesis": "Slow risk-adjusted sector leadership persists after costs with T-bill fallback.",
    },
    "etf_reversion": {
        "version": "v1",
        "strategy_id": "etf_reversion_v1",
        "strategy_type": "daily_mean_reversion",
        "benchmark": "SPY",
        "hypothesis": "Liquid ETF overshoots rebound when the slow trend remains healthy.",
    },
}


def _grids() -> dict[str, list[dict[str, Any]]]:
    return {
        "adaptive_core": [
            {"trend_windows": list(windows), "volatility_target": target}
            for windows in ((42, 126, 210), (63, 126, 252), (84, 168, 252))
            for target in (0.10, 0.12, 0.14)
        ],
        "controlled_growth": [
            {
                "slow_trend": slow,
                "breadth_threshold": breadth,
                "qqq_volatility_ceiling": ceiling,
                "cooldown_sessions": 10,
                "tqqq_cap": 0.10,
            }
            for slow in (168, 210, 252)
            for breadth in (0.55, 0.65)
            for ceiling in (0.22, 0.28)
        ],
        "sector_rotation": [
            {"momentum_weights": list(weights), "top_n": top_n, "slow_trend": slow}
            for weights in ((0.2, 0.3, 0.5), (0.3, 0.4, 0.3), (0.4, 0.3, 0.3))
            for top_n in (2, 3)
            for slow in (168, 252)
        ],
        "etf_reversion": [
            {"loss_threshold": loss, "rsi_cutoff": rsi, "hold_sessions": hold}
            for loss in (-0.025, -0.035)
            for rsi in (5, 10)
            for hold in (2, 4)
        ],
    }


def _make_strategy(family: str, parameters: Mapping[str, Any]):
    if family == "adaptive_core":
        params = dict(parameters)
        params["trend_windows"] = tuple(params["trend_windows"])
        return AdaptiveCoreStrategy(AdaptiveCoreParams(**params))
    if family == "controlled_growth":
        return ControlledGrowthStrategy(ControlledGrowthParams(**parameters))
    if family == "sector_rotation":
        params = dict(parameters)
        params["momentum_weights"] = tuple(params["momentum_weights"])
        return SectorRotationStrategy(SectorRotationParams(**params))
    if family == "etf_reversion":
        return EtfReversionStrategy(EtfReversionParams(**parameters))
    raise KeyError(family)


def _git_commit() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def _assert_source_clean() -> None:
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    allowed_prefixes = (
        "research/registry/",
        "research/results/phase2/",
        "research/holdout/phase2_",
        ".codex/strategy_phase_state.json",
        "docs/CODEX_PROGRESS.md",
    )
    dirty_source: list[str] = []
    for line in status.splitlines():
        path = line[3:].split(" -> ")[-1]
        if not path.startswith(allowed_prefixes):
            dirty_source.append(line)
    if dirty_source:
        raise RuntimeError(
            "phase-two experiments require committed source; dirty paths: "
            + "; ".join(dirty_source)
        )


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    return value


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(_jsonable(dict(payload)), handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _cost_model(config: CostModelConfig, multiplier: float = 1.0) -> CostModel:
    payload = config.model_dump()
    if multiplier != 1.0:
        for tier in payload["tiers"].values():
            tier["commission_bps"] *= multiplier
            tier["slippage_interday_bps"] *= multiplier
            tier["slippage_intraday_bps"] *= multiplier
    return CostModel(CostModelConfig.model_validate(payload))


def _all_symbols() -> list[str]:
    symbols: set[str] = set()
    for family in FAMILY_META:
        symbols.update(_make_strategy(family, _grids()[family][0]).required_symbols)
    return sorted(symbols)


def _load_panel(end: str) -> tuple[pd.DataFrame, pd.DataFrame, Any]:
    cfg = load_config(ROOT / "config")
    panel = load_adjusted_panel(
        _all_symbols(),
        ROOT / cfg.system.paths.data_dir,
        "1d",
        adjusted_total_return=True,
        fallback="local",
        require_total_return_coverage=True,
    )
    close = panel["close"].loc[:end]
    open_df = panel["open"].loc[:end]
    missing = sorted(set(_all_symbols()) - set(close.columns))
    if missing:
        raise RuntimeError(f"certified panel missing required symbols: {missing}")
    if close.index.has_duplicates or not close.index.is_monotonic_increasing:
        raise RuntimeError("certified panel has duplicate or unordered dates")
    return close, open_df, cfg


def _effective_start(close: pd.DataFrame, requested: str, warmup_bars: int) -> pd.Timestamp:
    requested_date = pd.Timestamp(requested)
    eligible = close.index[close.index >= requested_date]
    if len(eligible) <= warmup_bars:
        raise RuntimeError("insufficient observations after requested start and warmup")
    if requested_date <= close.index.min():
        return eligible[warmup_bars]
    return eligible[0]


def _run(
    strategy,
    close: pd.DataFrame,
    open_df: pd.DataFrame,
    cfg,
    *,
    benchmark_symbol: str,
    cost_multiplier: float = 1.0,
    delay_bars: int = 0,
) -> BacktestResult:
    weights = strategy.generate(close)
    if delay_bars:
        weights = weights.shift(delay_bars).fillna(0.0)
    engine = BacktestEngine(
        cost_model=_cost_model(cfg.cost_model, cost_multiplier),
        initial_capital=cfg.system.account.initial_capital_usd,
        integer_shares=not cfg.risk.position_limits.allow_fractional_shares,
    )
    return engine.run(
        signals_df=weights,
        price_df=close,
        open_df=open_df,
        benchmark_series=close[benchmark_symbol],
    )


def _benchmark_metrics(series: pd.Series, start: pd.Timestamp, end: str) -> dict[str, float]:
    sliced = series.loc[start:end].dropna()
    return compute_metrics(sliced, initial_capital=float(sliced.iloc[0]))


def _experiment_spec(
    experiment_id: str,
    family: str,
    parameters: Mapping[str, Any],
    role: str,
    start: str,
    end: str,
    commit: str,
    variant: str = "base_cost",
) -> ExperimentSpec:
    meta = FAMILY_META[family]
    return ExperimentSpec(
        experiment_id=experiment_id,
        strategy_family=family,
        strategy_version=meta["version"],
        hypothesis=f"{meta['hypothesis']} [{role}:{variant}]",
        parameters=dict(parameters),
        data_range={"role": role, "start": start, "end": end},
        cost_model=f"config/cost_model.yaml:{variant}",
        benchmark=meta["benchmark"],
        code_commit=commit,
        random_seed=SEED,
    )


def _execute_registered(
    registry: ExperimentRegistry,
    spec: ExperimentSpec,
    result_path: Path,
    evaluator: Callable[[], tuple[dict[str, Any], BacktestResult | None]],
    passed: Callable[[Mapping[str, Any]], bool],
) -> tuple[dict[str, Any], BacktestResult | None]:
    existing = registry.get(spec.experiment_id)
    if existing["status"] == "COMPLETED" and result_path.exists():
        return _load_json(result_path), None
    if existing["status"] not in {"PLANNED"}:
        raise RuntimeError(f"cannot resume experiment in state {existing['status']}: {spec.experiment_id}")
    registry.mark_running(spec.experiment_id)
    try:
        payload, result = evaluator()
        _atomic_json(result_path, payload)
        metrics = payload.get("metrics", payload)
        did_pass = passed(metrics)
        registry.complete(
            spec.experiment_id,
            result_path=str(result_path.relative_to(ROOT)),
            key_metrics={
                key: metrics.get(key)
                for key in ("cagr", "sharpe", "sortino", "max_drawdown", "calmar", "annual_turnover")
            },
            passed=did_pass,
            failure_reason=None if did_pass else "PREDEFINED_RESEARCH_METRIC_GATE",
        )
        return payload, result
    except Exception as exc:
        registry.fail(spec.experiment_id, f"{type(exc).__name__}: {exc}")
        raise


def _basic_metric_pass(metrics: Mapping[str, Any], family: str, policy: PromotionPolicy) -> bool:
    common = policy.payload["common_hard_gates"]
    type_gate = policy.payload["strategy_type_gates"][FAMILY_META[family]["strategy_type"]]
    required = {
        "cagr": max(common["min_validation_cagr"], type_gate["min_validation_cagr"]),
        "sharpe": max(common["min_validation_sharpe"], type_gate["min_validation_sharpe"]),
        "sortino": max(common["min_validation_sortino"], type_gate["min_validation_sortino"]),
    }
    try:
        return (
            all(float(metrics[key]) >= threshold for key, threshold in required.items())
            and abs(float(metrics["max_drawdown"])) <= min(common["max_drawdown"], type_gate["max_drawdown"])
        )
    except (KeyError, TypeError, ValueError):
        return False


def _development_score(metrics: Mapping[str, Any]) -> float:
    """Frozen gate-margin score; never used outside development selection."""
    return float(
        1.25 * float(metrics.get("sharpe") or -10.0)
        + 0.75 * float(metrics.get("calmar") or -10.0)
        + 2.0 * float(metrics.get("cagr") or -1.0)
        - 0.75 * abs(float(metrics.get("max_drawdown") or -1.0))
        - 0.01 * float(metrics.get("annual_turnover") or 100.0)
    )


def run_development(plan_only: bool = False) -> None:
    _assert_source_clean()
    policy = PromotionPolicy.load(POLICY_PATH)
    split = policy.payload["data_protocol"]["development"]
    commit = _git_commit()
    registry = ExperimentRegistry(REGISTRY_PATH)
    specs: list[ExperimentSpec] = []
    indexed: list[tuple[str, int, dict[str, Any], ExperimentSpec]] = []
    for family, cells in _grids().items():
        for index, parameters in enumerate(cells, start=1):
            experiment_id = f"P2-DEV-{family.upper().replace('_', '-')}-{index:02d}"
            spec = _experiment_spec(
                experiment_id,
                family,
                parameters,
                "development",
                split["start"],
                split["end"],
                commit,
            )
            specs.append(spec)
            indexed.append((family, index, parameters, spec))
    registry.preregister(specs)
    if plan_only:
        print(f"preregistered {len(specs)} development experiments; no data loaded")
        return

    close, open_df, cfg = _load_panel(split["end"])
    effective_start = _effective_start(close, split["start"], policy.payload["data_protocol"]["warmup_bars"])
    family_results: dict[str, list[dict[str, Any]]] = {family: [] for family in _grids()}
    for family, index, parameters, spec in indexed:
        meta = FAMILY_META[family]
        result_path = RESULT_ROOT / "development" / f"{spec.experiment_id}.json"

        def evaluate() -> tuple[dict[str, Any], BacktestResult]:
            result = _run(
                _make_strategy(family, parameters),
                close,
                open_df,
                cfg,
                benchmark_symbol=meta["benchmark"],
            )
            metrics = detailed_metrics(
                result,
                start=effective_start,
                end=split["end"],
                benchmark=close[meta["benchmark"]],
            )
            return (
                {
                    "experiment_id": spec.experiment_id,
                    "family": family,
                    "parameters": parameters,
                    "evaluation_start": effective_start,
                    "evaluation_end": split["end"],
                    "metrics": metrics,
                    "development_score": _development_score(metrics),
                },
                result,
            )

        def passes(metrics: Mapping[str, Any]) -> bool:
            return _basic_metric_pass(metrics, family, policy)

        payload, _ = _execute_registered(
            registry,
            spec,
            result_path,
            evaluate,
            passes,
        )
        family_results[family].append(payload)
        metrics = payload["metrics"]
        print(
            f"{spec.experiment_id}: CAGR={metrics['cagr']:.3f} "
            f"Sharpe={metrics['sharpe']:.3f} MaxDD={metrics['max_drawdown']:.3f}"
        )

    selection: dict[str, Any] = {
        "schema_version": 1,
        "code_commit": commit,
        "policy_sha256": hashlib.sha256(POLICY_PATH.read_bytes()).hexdigest(),
        "effective_evaluation_start": effective_start,
        "evaluation_end": split["end"],
        "selection_rule": "maximum frozen gate-margin score within family",
        "families": {},
    }
    for family, results in family_results.items():
        winner = max(results, key=lambda payload: float(payload["development_score"]))
        selection["families"][family] = {
            "experiment_id": winner["experiment_id"],
            "parameters": winner["parameters"],
            "development_score": winner["development_score"],
            "metrics": winner["metrics"],
        }
    _atomic_json(SELECTION_PATH, selection)
    print(f"development selection written to {SELECTION_PATH.relative_to(ROOT)}")


def _neighbor_cells(family: str, selected: Mapping[str, Any]) -> list[dict[str, Any]]:
    axes: dict[str, list[Any]]
    if family == "adaptive_core":
        axes = {
            "trend_windows": [[42, 126, 210], [63, 126, 252], [84, 168, 252]],
            "volatility_target": [0.10, 0.12, 0.14],
        }
    elif family == "controlled_growth":
        axes = {
            "slow_trend": [168, 210, 252],
            "breadth_threshold": [0.55, 0.65],
            "qqq_volatility_ceiling": [0.22, 0.28],
        }
    elif family == "sector_rotation":
        axes = {
            "momentum_weights": [[0.2, 0.3, 0.5], [0.3, 0.4, 0.3], [0.4, 0.3, 0.3]],
            "top_n": [2, 3],
            "slow_trend": [168, 252],
        }
    else:
        axes = {
            "loss_threshold": [-0.025, -0.035],
            "rsi_cutoff": [5, 10],
            "hold_sessions": [2, 4],
        }
    neighbors: list[dict[str, Any]] = []
    for cell in _grids()[family]:
        differences = 0
        adjacent = True
        for name, values in axes.items():
            selected_value = selected[name]
            cell_value = cell[name]
            if cell_value != selected_value:
                differences += 1
                if abs(values.index(cell_value) - values.index(selected_value)) != 1:
                    adjacent = False
        if differences == 1 and adjacent:
            neighbors.append(cell)
    return neighbors


def _stress_drawdowns(equity: pd.Series, policy: PromotionPolicy) -> dict[str, float | None]:
    values: dict[str, float | None] = {}
    for period in policy.payload["stress_periods"]:
        nav = equity.loc[period["start"] : period["end"]]
        values[period["name"]] = (
            float((nav / nav.cummax() - 1.0).min()) if len(nav) >= 2 else None
        )
    return values


def _research_controls(strategy_type: str, deterministic: bool) -> dict[str, Any]:
    return {
        "unresolved_p0": 0,
        "unresolved_research_p1": 0,
        "no_known_lookahead": True,
        "deterministic_rerun": deterministic,
        "live_disabled": True,
        "cooldown_test": True,
        "risk_on_gate_test": True,
    }


def run_validation(plan_only: bool = False) -> None:
    _assert_source_clean()
    selection = _load_json(SELECTION_PATH)
    policy = PromotionPolicy.load(POLICY_PATH)
    split = policy.payload["data_protocol"]["validation"]
    commit = _git_commit()
    registry = ExperimentRegistry(REGISTRY_PATH)
    specs: list[ExperimentSpec] = []
    work: dict[str, dict[str, Any]] = {}
    for family, selected in selection["families"].items():
        parameters = selected["parameters"]
        variants: dict[str, ExperimentSpec] = {}
        for variant in ("base", "cost2x", "delay1", "determinism"):
            spec = _experiment_spec(
                f"P2-VAL-{family.upper().replace('_', '-')}-{variant.upper()}",
                family,
                parameters,
                "validation",
                split["start"],
                split["end"],
                commit,
                variant,
            )
            specs.append(spec)
            variants[variant] = spec
        neighbors = []
        for index, neighbor in enumerate(_neighbor_cells(family, parameters), start=1):
            spec = _experiment_spec(
                f"P2-VAL-{family.upper().replace('_', '-')}-NEIGHBOR-{index:02d}",
                family,
                neighbor,
                "validation_sensitivity",
                split["start"],
                split["end"],
                commit,
                "parameter_neighbor",
            )
            specs.append(spec)
            neighbors.append((neighbor, spec))
        work[family] = {"parameters": parameters, "variants": variants, "neighbors": neighbors}
    registry.preregister(specs)
    if plan_only:
        print(f"preregistered {len(specs)} validation/robustness experiments; no data loaded")
        return

    close, open_df, cfg = _load_panel(split["end"])
    effective_start = _effective_start(close, split["start"], 0)
    summary: dict[str, Any] = {
        "schema_version": 1,
        "code_commit": commit,
        "evaluation_start": effective_start,
        "evaluation_end": split["end"],
        "families": {},
    }
    for family, item in work.items():
        meta = FAMILY_META[family]
        parameters = item["parameters"]

        def run_variant(
            spec: ExperimentSpec,
            *,
            cost: float = 1.0,
            delay: int = 0,
        ) -> tuple[dict[str, Any], BacktestResult]:
            path = RESULT_ROOT / "validation" / f"{spec.experiment_id}.json"

            def evaluate() -> tuple[dict[str, Any], BacktestResult]:
                result = _run(
                    _make_strategy(family, parameters),
                    close,
                    open_df,
                    cfg,
                    benchmark_symbol=meta["benchmark"],
                    cost_multiplier=cost,
                    delay_bars=delay,
                )
                metrics = detailed_metrics(
                    result,
                    start=effective_start,
                    end=split["end"],
                    benchmark=close[meta["benchmark"]],
                )
                return ({"experiment_id": spec.experiment_id, "metrics": metrics}, result)

            payload, result = _execute_registered(
                registry,
                spec,
                path,
                evaluate,
                lambda metrics: _basic_metric_pass(metrics, family, policy),
            )
            # Registry resume does not serialize positions/trades, so only a
            # resumed completed run needs a deterministic reconstruction.
            if result is None:
                result = _run(
                    _make_strategy(family, parameters),
                    close,
                    open_df,
                    cfg,
                    benchmark_symbol=meta["benchmark"],
                    cost_multiplier=cost,
                    delay_bars=delay,
                )
            return payload, result

        base_payload, base_result = run_variant(item["variants"]["base"])
        cost_payload, _ = run_variant(item["variants"]["cost2x"], cost=2.0)
        delay_payload, _ = run_variant(item["variants"]["delay1"], delay=1)
        _, deterministic_result = run_variant(item["variants"]["determinism"])
        nav_common = base_result.equity_curve.loc[effective_start : split["end"]]
        deterministic_common = deterministic_result.equity_curve.reindex(nav_common.index)
        deterministic = bool(np.allclose(nav_common, deterministic_common, rtol=0.0, atol=1e-10, equal_nan=True))

        neighbor_results: list[dict[str, Any]] = []
        for neighbor, spec in item["neighbors"]:
            path = RESULT_ROOT / "validation" / f"{spec.experiment_id}.json"

            def evaluate_neighbor(
                neighbor: Mapping[str, Any] = neighbor,
                spec: ExperimentSpec = spec,
            ) -> tuple[dict[str, Any], BacktestResult]:
                result = _run(
                    _make_strategy(family, neighbor),
                    close,
                    open_df,
                    cfg,
                    benchmark_symbol=meta["benchmark"],
                )
                metrics = detailed_metrics(
                    result,
                    start=effective_start,
                    end=split["end"],
                    benchmark=close[meta["benchmark"]],
                )
                return (
                    {"experiment_id": spec.experiment_id, "parameters": neighbor, "metrics": metrics},
                    result,
                )

            neighbor_payload, _ = _execute_registered(
                registry,
                spec,
                path,
                evaluate_neighbor,
                lambda metrics: _basic_metric_pass(metrics, family, policy),
            )
            neighbor_results.append(neighbor_payload)

        folds = annual_fold_metrics(
            nav_common,
            close[meta["benchmark"]],
            pd.Timestamp(split["start"]).year,
            pd.Timestamp(split["end"]).year,
        )
        positive_fraction = float(
            sum(float(fold.get("cagr", -1.0)) > 0.0 and float(fold.get("sharpe", -1.0)) > 0.0 for fold in folds)
            / max(len(folds), 1)
        )
        neighbor_fraction = float(
            sum(_basic_metric_pass(item["metrics"], family, policy) for item in neighbor_results)
            / max(len(neighbor_results), 1)
        )
        stress = _stress_drawdowns(base_result.equity_curve, policy)
        finite_stress = [value for value in stress.values() if value is not None]
        bootstrap = stationary_bootstrap_cagr_ci(nav_common.pct_change().dropna(), seed=SEED)
        robustness = {
            "positive_walk_forward_fraction": positive_fraction,
            "cost_2x_cagr": cost_payload["metrics"]["cagr"],
            "cost_2x_sharpe": cost_payload["metrics"]["sharpe"],
            "delayed_signal_sharpe": delay_payload["metrics"]["sharpe"],
            "parameter_neighbor_pass_fraction": neighbor_fraction,
            "worst_stress_drawdown": min(finite_stress) if finite_stress else -1.0,
            "stress_drawdowns": stress,
            "max_tqqq_weight": float(base_result.weights.get("TQQQ", pd.Series(0.0)).max()),
            "bootstrap_cagr_95pct": bootstrap,
            "folds": folds,
            "neighbor_results": neighbor_results,
            "multiple_testing_attempts_family": len(_grids()[family]),
            "pbo": "not_identifiable_from_one_selected_validation_path",
            "deflated_sharpe": "not_claimed; conservative fixed 4% risk-free Sharpe and bounded search used",
        }
        benchmark_metrics = _benchmark_metrics(close[meta["benchmark"]], effective_start, split["end"])
        controls = _research_controls(meta["strategy_type"], deterministic)
        evidence = CandidateEvidence(
            strategy_id=meta["strategy_id"],
            strategy_type=meta["strategy_type"],
            metrics=base_payload["metrics"],
            benchmark_metrics=benchmark_metrics,
            robustness=robustness,
            controls=controls,
        )
        decision = policy.evaluate(evidence, include_operational=False)
        summary["families"][family] = {
            "strategy_id": meta["strategy_id"],
            "strategy_type": meta["strategy_type"],
            "parameters": parameters,
            "metrics": base_payload["metrics"],
            "benchmark_metrics": benchmark_metrics,
            "robustness": robustness,
            "controls": controls,
            "research_gate_pass": decision.eligible,
            "failed_gates": decision.failed_gates,
            "gate_details": [asdict(gate) for gate in decision.gates],
        }
        print(
            f"{meta['strategy_id']}: validation gate={'PASS' if decision.eligible else 'FAIL'} "
            f"failed={','.join(decision.failed_gates) or 'none'}"
        )
    _atomic_json(VALIDATION_SUMMARY_PATH, summary)


def _record_holdout_access(entries: list[dict[str, Any]], commit: str) -> None:
    if HOLDOUT_ACCESS_PATH.exists():
        existing = _load_json(HOLDOUT_ACCESS_PATH)
    else:
        existing = {"schema_version": 1, "accesses": []}
    known = {item["strategy_id"] for item in existing["accesses"]}
    for entry in entries:
        if entry["strategy_id"] in known:
            continue
        existing["accesses"].append(
            {
                **entry,
                "code_commit": commit,
                "purpose": "single frozen phase-two finalist evaluation",
                "parameters_locked": True,
                "result_viewed_before_access": False,
            }
        )
    _atomic_json(HOLDOUT_ACCESS_PATH, existing)


def run_holdout(plan_only: bool = False) -> None:
    _assert_source_clean()
    validation = _load_json(VALIDATION_SUMMARY_PATH)
    policy = PromotionPolicy.load(POLICY_PATH)
    split = policy.payload["data_protocol"]["final_holdout"]
    qualified = {
        family: item
        for family, item in validation["families"].items()
        if item["research_gate_pass"]
    }
    if not qualified:
        raise RuntimeError("no validation-qualified family may access holdout")
    if len(qualified) > policy.payload["data_protocol"]["max_total_finalists"]:
        raise RuntimeError("finalist count exceeds frozen holdout limit")
    commit = _git_commit()
    registry = ExperimentRegistry(REGISTRY_PATH)
    specs: list[ExperimentSpec] = []
    for family, item in qualified.items():
        specs.append(
            _experiment_spec(
                f"P2-HOLDOUT-{family.upper().replace('_', '-')}-FINAL",
                family,
                item["parameters"],
                "final_holdout",
                split["start"],
                split["end"],
                commit,
                "single_frozen_access",
            )
        )
    registry.preregister(specs)
    _record_holdout_access(
        [
            {
                "strategy_id": qualified[family]["strategy_id"],
                "family": family,
                "experiment_id": spec.experiment_id,
                "range": split,
                "parameters": qualified[family]["parameters"],
            }
            for family, spec in zip(qualified, specs)
        ],
        commit,
    )
    if plan_only:
        print(f"preregistered {len(specs)} holdout accesses; no holdout data loaded")
        return

    # The holdout is loaded only after both registry and access-ledger writes.
    close, open_df, cfg = _load_panel(split["end"])
    effective_start = _effective_start(close, split["start"], 0)
    summary: dict[str, Any] = {
        "schema_version": 1,
        "code_commit": commit,
        "evaluation_start": effective_start,
        "evaluation_end": split["end"],
        "families": {},
    }
    for (family, prior), spec in zip(qualified.items(), specs):
        meta = FAMILY_META[family]
        result_path = RESULT_ROOT / "holdout" / f"{spec.experiment_id}.json"

        def evaluate() -> tuple[dict[str, Any], BacktestResult]:
            result = _run(
                _make_strategy(family, prior["parameters"]),
                close,
                open_df,
                cfg,
                benchmark_symbol=meta["benchmark"],
            )
            metrics = detailed_metrics(
                result,
                start=effective_start,
                end=split["end"],
                benchmark=close[meta["benchmark"]],
            )
            return ({"experiment_id": spec.experiment_id, "metrics": metrics}, result)

        payload, _ = _execute_registered(
            registry,
            spec,
            result_path,
            evaluate,
            lambda metrics: _basic_metric_pass(metrics, family, policy),
        )
        benchmark_metrics = _benchmark_metrics(close[meta["benchmark"]], effective_start, split["end"])
        evidence = CandidateEvidence(
            strategy_id=meta["strategy_id"],
            strategy_type=meta["strategy_type"],
            metrics=payload["metrics"],
            benchmark_metrics=benchmark_metrics,
            robustness=prior["robustness"],
            controls=prior["controls"],
        )
        decision = policy.evaluate(evidence, include_operational=False)
        summary["families"][family] = {
            "strategy_id": meta["strategy_id"],
            "parameters": prior["parameters"],
            "metrics": payload["metrics"],
            "benchmark_metrics": benchmark_metrics,
            "validation_robustness": prior["robustness"],
            "holdout_gate_pass": decision.eligible,
            "failed_gates": decision.failed_gates,
            "gate_details": [asdict(gate) for gate in decision.gates],
            "logic_frozen_after_access": True,
        }
        print(
            f"{meta['strategy_id']}: holdout gate={'PASS' if decision.eligible else 'FAIL'} "
            f"failed={','.join(decision.failed_gates) or 'none'}"
        )
    _atomic_json(HOLDOUT_SUMMARY_PATH, summary)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("development", "validation", "holdout"))
    parser.add_argument("--plan-only", action="store_true", help="register all runs without loading market data")
    args = parser.parse_args()
    if args.stage == "development":
        run_development(args.plan_only)
    elif args.stage == "validation":
        run_validation(args.plan_only)
    else:
        run_holdout(args.plan_only)


if __name__ == "__main__":
    main()
