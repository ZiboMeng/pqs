"""Immutable Forward PAPER tracking policy, observations, and control report."""

from __future__ import annotations

import json
import math
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import fmean
from typing import Any, Mapping

import numpy as np

from core.runtime.strategy_artifact import canonical_json, sha256_bytes


class ForwardTrackingError(RuntimeError):
    """Raised on policy drift, conflicting observations, or corrupt metrics."""


@dataclass(frozen=True, slots=True)
class ForwardTrackingPolicy:
    policy_id: str
    benchmark: str
    annualization_sessions: int
    minimum_performance_sessions: int
    minimum_promotion_sessions: int
    max_drawdown_abs: float
    max_annualized_volatility: float
    max_tracking_error: float
    max_reconciliation_failures: int
    max_missing_rate: float
    max_reject_rate: float

    def __post_init__(self) -> None:
        if not self.policy_id.strip() or not self.benchmark.strip():
            raise ValueError("tracking policy identity and benchmark are required")
        if self.annualization_sessions <= 0:
            raise ValueError("tracking annualization must be positive")
        if not (
            2 <= self.minimum_performance_sessions <= self.minimum_promotion_sessions
        ):
            raise ValueError("tracking session thresholds are inconsistent")
        for name in (
            "max_drawdown_abs",
            "max_annualized_volatility",
            "max_tracking_error",
            "max_missing_rate",
            "max_reject_rate",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"tracking control {name} must be finite and non-negative")
        if self.max_drawdown_abs > 1 or self.max_missing_rate > 1 or self.max_reject_rate > 1:
            raise ValueError("tracking fraction controls cannot exceed one")
        if self.max_reconciliation_failures < 0:
            raise ValueError("reconciliation failure limit cannot be negative")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> ForwardTrackingPolicy:
        controls = payload.get("controls")
        if not isinstance(controls, Mapping):
            raise ValueError("tracking controls must be a mapping")
        return cls(
            policy_id=str(payload["control_policy_version"]),
            benchmark=str(payload["benchmark"]).upper(),
            annualization_sessions=int(payload["annualization_sessions"]),
            minimum_performance_sessions=int(payload["minimum_performance_sessions"]),
            minimum_promotion_sessions=int(payload["minimum_promotion_sessions"]),
            max_drawdown_abs=float(controls["max_drawdown_abs"]),
            max_annualized_volatility=float(controls["max_annualized_volatility"]),
            max_tracking_error=float(controls["max_tracking_error"]),
            max_reconciliation_failures=int(controls["max_reconciliation_failures"]),
            max_missing_rate=float(controls["max_missing_rate"]),
            max_reject_rate=float(controls["max_reject_rate"]),
        )

    def payload(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "benchmark": self.benchmark,
            "annualization_sessions": self.annualization_sessions,
            "minimum_performance_sessions": self.minimum_performance_sessions,
            "minimum_promotion_sessions": self.minimum_promotion_sessions,
            "controls": {
                "max_drawdown_abs": self.max_drawdown_abs,
                "max_annualized_volatility": self.max_annualized_volatility,
                "max_tracking_error": self.max_tracking_error,
                "max_reconciliation_failures": self.max_reconciliation_failures,
                "max_missing_rate": self.max_missing_rate,
                "max_reject_rate": self.max_reject_rate,
            },
        }

    @property
    def sha256(self) -> str:
        return sha256_bytes(canonical_json(self.payload()))


@dataclass(frozen=True, slots=True)
class ForwardTrackingObservation:
    session: date
    decision_id: str
    starting_equity: float
    ending_equity: float
    benchmark_return: float
    turnover_usd: float
    order_count: int
    fill_count: int
    rejected_order_count: int
    partial_fill_count: int
    total_cost_usd: float
    slippage_usd: float
    event_latency_seconds: float
    missing_data_count: int
    downtime_seconds: float
    reconciliation_passed: bool
    regime: str
    gross_target: float
    positions: Mapping[str, float]
    backtest_reference_return: float | None = None

    def __post_init__(self) -> None:
        if not self.decision_id.strip() or not self.regime.strip():
            raise ValueError("tracking decision and regime identities are required")
        finite_values = (
            self.starting_equity,
            self.ending_equity,
            self.benchmark_return,
            self.turnover_usd,
            self.total_cost_usd,
            self.slippage_usd,
            self.event_latency_seconds,
            self.downtime_seconds,
            self.gross_target,
        )
        if not all(math.isfinite(float(value)) for value in finite_values):
            raise ValueError("tracking observation contains non-finite values")
        if self.starting_equity <= 0 or self.ending_equity <= 0:
            raise ValueError("tracking equities must be positive")
        if min(
            self.turnover_usd,
            self.total_cost_usd,
            self.slippage_usd,
            self.event_latency_seconds,
            self.downtime_seconds,
            self.gross_target,
        ) < 0:
            raise ValueError("tracking counts and magnitudes cannot be negative")
        counts = (
            self.order_count,
            self.fill_count,
            self.rejected_order_count,
            self.partial_fill_count,
            self.missing_data_count,
        )
        if any(value < 0 for value in counts):
            raise ValueError("tracking counters cannot be negative")
        if self.rejected_order_count > self.order_count:
            raise ValueError("rejected orders cannot exceed total orders")
        if self.partial_fill_count > self.fill_count:
            raise ValueError("partial fills cannot exceed fills")
        if self.backtest_reference_return is not None and not math.isfinite(
            float(self.backtest_reference_return)
        ):
            raise ValueError("backtest reference return must be finite when present")
        if any(
            not str(symbol).strip()
            or not math.isfinite(float(quantity))
            or float(quantity) < 0
            for symbol, quantity in self.positions.items()
        ):
            raise ValueError("tracking positions must be finite and long-only")

    @property
    def actual_return(self) -> float:
        return self.ending_equity / self.starting_equity - 1.0

    def payload(self) -> dict[str, Any]:
        return {
            "session": self.session.isoformat(),
            "decision_id": self.decision_id,
            "starting_equity": self.starting_equity,
            "ending_equity": self.ending_equity,
            "actual_return": self.actual_return,
            "benchmark_return": self.benchmark_return,
            "turnover_usd": self.turnover_usd,
            "order_count": self.order_count,
            "fill_count": self.fill_count,
            "rejected_order_count": self.rejected_order_count,
            "partial_fill_count": self.partial_fill_count,
            "total_cost_usd": self.total_cost_usd,
            "slippage_usd": self.slippage_usd,
            "event_latency_seconds": self.event_latency_seconds,
            "missing_data_count": self.missing_data_count,
            "downtime_seconds": self.downtime_seconds,
            "reconciliation_passed": self.reconciliation_passed,
            "regime": self.regime,
            "gross_target": self.gross_target,
            "positions": {
                str(symbol): float(quantity)
                for symbol, quantity in sorted(self.positions.items())
            },
            "backtest_reference_return": self.backtest_reference_return,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ForwardTrackingObservation:
        return cls(
            session=date.fromisoformat(str(payload["session"])),
            decision_id=str(payload["decision_id"]),
            starting_equity=float(payload["starting_equity"]),
            ending_equity=float(payload["ending_equity"]),
            benchmark_return=float(payload["benchmark_return"]),
            turnover_usd=float(payload["turnover_usd"]),
            order_count=int(payload["order_count"]),
            fill_count=int(payload["fill_count"]),
            rejected_order_count=int(payload["rejected_order_count"]),
            partial_fill_count=int(payload["partial_fill_count"]),
            total_cost_usd=float(payload["total_cost_usd"]),
            slippage_usd=float(payload["slippage_usd"]),
            event_latency_seconds=float(payload["event_latency_seconds"]),
            missing_data_count=int(payload["missing_data_count"]),
            downtime_seconds=float(payload["downtime_seconds"]),
            reconciliation_passed=bool(payload["reconciliation_passed"]),
            regime=str(payload["regime"]),
            gross_target=float(payload["gross_target"]),
            positions={
                str(symbol): float(quantity)
                for symbol, quantity in payload["positions"].items()
            },
            backtest_reference_return=(
                None
                if payload.get("backtest_reference_return") is None
                else float(payload["backtest_reference_return"])
            ),
        )


class ForwardTrackingStore:
    def __init__(self, db_path: str | Path, policy: ForwardTrackingPolicy) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.policy = policy
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS forward_tracking_policy (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    policy_sha256 TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forward_tracking_observations (
                    session TEXT PRIMARY KEY,
                    decision_id TEXT NOT NULL UNIQUE,
                    content_sha256 TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                """
            )
        self.freeze_policy()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def freeze_policy(self) -> None:
        payload_json = canonical_json(self.policy.payload()).decode("utf-8")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT policy_sha256, payload_json FROM forward_tracking_policy WHERE id = 1"
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO forward_tracking_policy (
                        id, policy_sha256, payload_json
                    ) VALUES (1, ?, ?)
                    """,
                    (self.policy.sha256, payload_json),
                )
            elif row["policy_sha256"] != self.policy.sha256 or row["payload_json"] != payload_json:
                raise ForwardTrackingError(
                    "forward tracking policy drift; create a new isolated version"
                )

    def record(self, observation: ForwardTrackingObservation) -> bool:
        self.freeze_policy()
        payload = observation.payload()
        payload_json = canonical_json(payload).decode("utf-8")
        content_sha = sha256_bytes(payload_json.encode("utf-8"))
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT content_sha256 FROM forward_tracking_observations WHERE session = ?",
                (observation.session.isoformat(),),
            ).fetchone()
            if row is not None:
                if row["content_sha256"] != content_sha:
                    raise ForwardTrackingError(
                        f"conflicting tracking observation: {observation.session}"
                    )
                return True
            conn.execute(
                """
                INSERT INTO forward_tracking_observations (
                    session, decision_id, content_sha256, payload_json
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    observation.session.isoformat(),
                    observation.decision_id,
                    content_sha,
                    payload_json,
                ),
            )
        return False

    def observations(self) -> list[ForwardTrackingObservation]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM forward_tracking_observations ORDER BY session"
            ).fetchall()
        return [
            ForwardTrackingObservation.from_payload(json.loads(row["payload_json"]))
            for row in rows
        ]

    @staticmethod
    def _finite_or_none(value: float) -> float | None:
        return float(value) if math.isfinite(float(value)) else None

    def report(self) -> dict[str, Any]:
        observations = self.observations()
        actual = np.array([item.actual_return for item in observations], dtype=float)
        benchmark = np.array([item.benchmark_return for item in observations], dtype=float)
        n_sessions = len(observations)
        annualization = self.policy.annualization_sessions
        cumulative = np.cumprod(1.0 + actual) if n_sessions else np.array([], dtype=float)
        total_return = float(cumulative[-1] - 1.0) if n_sessions else 0.0
        annualized_return = (
            float((1.0 + total_return) ** (annualization / n_sessions) - 1.0)
            if n_sessions and total_return > -1.0
            else None
        )
        annualized_volatility = (
            float(np.std(actual, ddof=1) * math.sqrt(annualization))
            if n_sessions >= 2
            else None
        )
        if n_sessions:
            peaks = np.maximum.accumulate(np.concatenate(([1.0], cumulative)))
            values = np.concatenate(([1.0], cumulative))
            max_drawdown = float(np.min(values / peaks - 1.0))
        else:
            max_drawdown = 0.0
        benchmark_variance = float(np.var(benchmark, ddof=1)) if n_sessions >= 2 else 0.0
        beta = (
            float(np.cov(actual, benchmark, ddof=1)[0, 1] / benchmark_variance)
            if n_sessions >= 2 and benchmark_variance > 1e-18
            else None
        )
        references = [
            (item.actual_return, item.backtest_reference_return)
            for item in observations
            if item.backtest_reference_return is not None
        ]
        tracking_error = None
        if len(references) >= 2:
            differences = np.array(
                [actual_return - float(reference) for actual_return, reference in references]
            )
            tracking_error = float(np.std(differences, ddof=1) * math.sqrt(annualization))

        total_orders = sum(item.order_count for item in observations)
        total_fills = sum(item.fill_count for item in observations)
        rejected = sum(item.rejected_order_count for item in observations)
        partial = sum(item.partial_fill_count for item in observations)
        missing = sum(item.missing_data_count for item in observations)
        reconciliation_failures = sum(
            not item.reconciliation_passed for item in observations
        )
        reject_rate = rejected / total_orders if total_orders else 0.0
        partial_rate = partial / total_fills if total_fills else 0.0
        missing_rate = missing / n_sessions if n_sessions else 0.0

        current_holding_streaks: dict[str, int] = {}
        if observations:
            current_symbols = {
                symbol
                for symbol, quantity in observations[-1].positions.items()
                if quantity > 1e-6
            }
            for symbol in current_symbols:
                streak = 0
                for item in reversed(observations):
                    if item.positions.get(symbol, 0.0) <= 1e-6:
                        break
                    streak += 1
                current_holding_streaks[symbol] = streak

        performance_ready = n_sessions >= self.policy.minimum_performance_sessions
        breaches: list[dict[str, str]] = []
        if reconciliation_failures > self.policy.max_reconciliation_failures:
            breaches.append(
                {"category": "ENGINEERING", "control": "reconciliation_failures"}
            )
        if missing_rate > self.policy.max_missing_rate:
            breaches.append({"category": "ENGINEERING", "control": "missing_rate"})
        if reject_rate > self.policy.max_reject_rate:
            breaches.append({"category": "EXECUTION_MODEL", "control": "reject_rate"})
        if performance_ready and abs(max_drawdown) > self.policy.max_drawdown_abs:
            breaches.append({"category": "MARKET_PERFORMANCE", "control": "max_drawdown"})
        if (
            performance_ready
            and annualized_volatility is not None
            and annualized_volatility > self.policy.max_annualized_volatility
        ):
            breaches.append(
                {"category": "MARKET_PERFORMANCE", "control": "annualized_volatility"}
            )
        if (
            performance_ready
            and tracking_error is not None
            and tracking_error > self.policy.max_tracking_error
        ):
            breaches.append(
                {"category": "EXECUTION_MODEL", "control": "tracking_error"}
            )

        latencies = [item.event_latency_seconds for item in observations]
        holding_average = (
            fmean(current_holding_streaks.values()) if current_holding_streaks else None
        )
        return {
            "schema_version": 1,
            "policy_id": self.policy.policy_id,
            "policy_sha256": self.policy.sha256,
            "benchmark": self.policy.benchmark,
            "n_forward_sessions": n_sessions,
            "sample_status": "PERFORMANCE_READY" if performance_ready else "INSUFFICIENT",
            "performance": {
                "total_return": total_return,
                "annualized_return": annualized_return,
                "annualized_volatility": annualized_volatility,
                "max_drawdown": max_drawdown,
                "beta_to_benchmark": beta,
            },
            "execution_model": {
                "turnover_fraction_total": sum(
                    item.turnover_usd / item.starting_equity for item in observations
                ),
                "cost_usd_total": sum(item.total_cost_usd for item in observations),
                "slippage_usd_total": sum(item.slippage_usd for item in observations),
                "orders": total_orders,
                "fills": total_fills,
                "reject_rate": reject_rate,
                "partial_fill_rate": partial_rate,
                "backtest_reference_sessions": len(references),
                "backtest_to_forward_tracking_error": tracking_error,
                "tracking_error_status": (
                    "AVAILABLE" if tracking_error is not None else "INSUFFICIENT_REFERENCE"
                ),
            },
            "engineering": {
                "reconciliation_failures": reconciliation_failures,
                "missing_rate": missing_rate,
                "downtime_seconds_total": sum(
                    item.downtime_seconds for item in observations
                ),
                "event_latency_seconds_mean": fmean(latencies) if latencies else None,
                "event_latency_seconds_max": max(latencies) if latencies else None,
            },
            "exposure": {
                "regime_distribution": dict(
                    sorted(Counter(item.regime for item in observations).items())
                ),
                "average_gross_target": (
                    fmean(item.gross_target for item in observations)
                    if observations
                    else None
                ),
                "current_holding_period_sessions": current_holding_streaks,
                "current_holding_period_sessions_average": holding_average,
            },
            "control_breaches": breaches,
            "review_required": bool(breaches),
            "promotion": {
                "automatic_promotion_enabled": False,
                "eligible": False,
                "minimum_sessions": self.policy.minimum_promotion_sessions,
                "reason": (
                    "insufficient_forward_sessions"
                    if n_sessions < self.policy.minimum_promotion_sessions
                    else "manual_independent_review_required"
                ),
            },
        }
