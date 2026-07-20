#!/usr/bin/env python3
"""Isolated fixed-schema metric worker for sealed artifact-return batches."""

from __future__ import annotations

import json
import math
import statistics
import sys
from datetime import date
from pathlib import Path


def _finite(value, label: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"non-finite {label}")
    return number


def _metrics(payload: dict) -> dict:
    if set(payload) != {"schema_version", "artifact_root_sha256", "rows", "policy"}:
        raise ValueError("worker input schema mismatch")
    if payload["schema_version"] != 1:
        raise ValueError("worker input version mismatch")
    rows = payload["rows"]
    if not isinstance(rows, list) or not rows:
        raise ValueError("sealed evaluator requires at least one row")
    expected_root = payload["artifact_root_sha256"]
    sessions: set[str] = set()
    previous_session: date | None = None
    strategy_returns: list[float] = []
    benchmark_returns: list[float] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "session",
            "artifact_root_sha256",
            "strategy_return",
            "benchmark_return",
        }:
            raise ValueError("sealed row schema mismatch")
        session = str(row["session"])
        parsed_session = date.fromisoformat(session)
        if session in sessions:
            raise ValueError("duplicate sealed return session")
        if previous_session is not None and parsed_session <= previous_session:
            raise ValueError("sealed return sessions must be strictly increasing")
        sessions.add(session)
        previous_session = parsed_session
        if row["artifact_root_sha256"] != expected_root:
            raise ValueError("sealed return row is bound to another artifact")
        strategy_return = _finite(row["strategy_return"], "strategy return")
        benchmark_return = _finite(row["benchmark_return"], "benchmark return")
        if strategy_return <= -1 or benchmark_return <= -1:
            raise ValueError("sealed return cannot be less than or equal to -100%")
        strategy_returns.append(strategy_return)
        benchmark_returns.append(benchmark_return)

    policy = payload["policy"]
    if not isinstance(policy, dict) or set(policy) != {
        "annualization_sessions",
        "minimum_sessions",
        "maximum_drawdown_abs",
        "minimum_sharpe",
        "maximum_beta",
        "maximum_annualized_volatility",
    }:
        raise ValueError("metric policy schema mismatch")
    annualization = int(policy["annualization_sessions"])
    minimum_sessions = int(policy["minimum_sessions"])
    if annualization <= 0 or minimum_sessions <= 0:
        raise ValueError("metric policy session counts must be positive")

    n_sessions = len(strategy_returns)
    compounded = 1.0
    curve = [1.0]
    for value in strategy_returns:
        compounded *= 1.0 + value
        curve.append(compounded)
    total_return = compounded - 1.0
    annualized_return = (
        (1.0 + total_return) ** (annualization / n_sessions) - 1.0
        if total_return > -1
        else -1.0
    )
    if n_sessions >= 2:
        volatility = statistics.stdev(strategy_returns) * math.sqrt(annualization)
        mean_return = statistics.fmean(strategy_returns)
        sharpe = (
            mean_return / statistics.stdev(strategy_returns) * math.sqrt(annualization)
            if statistics.stdev(strategy_returns) > 1e-15
            else None
        )
        benchmark_variance = statistics.variance(benchmark_returns)
        if benchmark_variance > 1e-18:
            strategy_mean = statistics.fmean(strategy_returns)
            benchmark_mean = statistics.fmean(benchmark_returns)
            covariance = sum(
                (strategy - strategy_mean) * (benchmark - benchmark_mean)
                for strategy, benchmark in zip(strategy_returns, benchmark_returns)
            ) / (n_sessions - 1)
            beta = covariance / benchmark_variance
        else:
            beta = None
    else:
        volatility = None
        sharpe = None
        beta = None
    peak = curve[0]
    max_drawdown = 0.0
    for value in curve:
        peak = max(peak, value)
        max_drawdown = min(max_drawdown, value / peak - 1.0)

    gates = {
        "minimum_sessions": n_sessions >= minimum_sessions,
        "maximum_drawdown": abs(max_drawdown)
        <= _finite(policy["maximum_drawdown_abs"], "maximum drawdown policy"),
        "minimum_sharpe": sharpe is not None
        and sharpe >= _finite(policy["minimum_sharpe"], "minimum Sharpe policy"),
        "maximum_beta": beta is not None
        and beta <= _finite(policy["maximum_beta"], "maximum beta policy"),
        "maximum_annualized_volatility": volatility is not None
        and volatility
        <= _finite(
            policy["maximum_annualized_volatility"],
            "maximum volatility policy",
        ),
    }
    return {
        "schema_version": 1,
        "n_sessions": n_sessions,
        "metrics": {
            "total_return": total_return,
            "annualized_return": annualized_return,
            "annualized_volatility": volatility,
            "max_drawdown": max_drawdown,
            "sharpe": sharpe,
            "beta_to_benchmark": beta,
        },
        "gates": gates,
        "passed": all(gates.values()),
    }


def main() -> int:
    if len(sys.argv) != 3:
        return 2
    source = Path(sys.argv[1])
    target = Path(sys.argv[2])
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
        result = _metrics(payload)
        target.write_text(
            json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        return 0
    except Exception:
        # Raw rows and exception details must not cross the subprocess boundary.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
