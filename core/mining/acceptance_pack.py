"""Acceptance pack — validation checks required before promote_strategy.py
upgrades `config/production_strategy.yaml::status` to `active`.

PRD: docs/20260421-prd_framework_completion.md §M2

A spec_id from the mining archive is considered promotable only if it passes
ALL gates below. Each gate is a boolean with supporting diagnostic values;
the aggregate verdict (`overall_passed`) is `all(gate.passed for gate in ...)`.

**Pack v3 (2026-07-21)** — history: v1 trusted archive row as
authoritative evidence, but a real promote attempt revealed that archive's
`quick_cagr` / `qqq_full_period_excess` fields come from the **quick 70%
data fraction**, not a full-period backtest. A spec that looked great in
the quick window can underperform QQQ on full period.

v3 re-runs MultiFactorStrategy on split-adjusted execution prices plus an
exact cash-distribution ledger, compares after-cost performance with a costed
SPY buy-and-hold portfolio, treats QQQ as diagnostic, and requires a bound
lookahead/overfit/paper-alignment artifact for automatic promotion.

Set `run_fresh_backtest=False` only for diagnostic/unit-test packs; automatic
promotion treats it as a failure.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class GateResult:
    name: str
    passed: bool
    values: Dict[str, Any] = field(default_factory=dict)
    threshold: Dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    binding: bool = True

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AcceptancePackResult:
    spec_id: str
    strategy_type: str
    lineage_tag: str
    params: Dict[str, Any]
    gates: List[GateResult]
    overall_passed: bool
    evaluated_at: str
    archive_evidence_only: bool = True
    promotion_evidence_path: str = ""
    promotion_evidence_sha256: str = ""
    notes: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "spec_id": self.spec_id,
            "strategy_type": self.strategy_type,
            "lineage_tag": self.lineage_tag,
            "params": self.params,
            "gates": [g.as_dict() for g in self.gates],
            "overall_passed": self.overall_passed,
            "evaluated_at": self.evaluated_at,
            "archive_evidence_only": self.archive_evidence_only,
            "promotion_evidence_path": self.promotion_evidence_path,
            "promotion_evidence_sha256": self.promotion_evidence_sha256,
            "notes": self.notes,
        }

    def summary_line(self) -> str:
        binding = [gate for gate in self.gates if gate.binding]
        n_pass = sum(1 for gate in binding if gate.passed)
        return (
            f"AcceptancePack {self.spec_id[:12]} ({self.strategy_type}, "
            f"{self.lineage_tag}): {n_pass}/{len(binding)} binding gates passed, "
            f"overall={'PASS' if self.overall_passed else 'FAIL'}"
        )


class AcceptancePackError(RuntimeError):
    """Raised when the pack cannot be built (missing spec_id, bad archive)."""


# ---------------------------------------------------------------------------
# Gate thresholds (mirror config/backtest.yaml::mining but hardcoded here so
# the pack has a stable contract independent of config drift).
#
# Freeze contract (codex round-13 §"Decision 3", 2026-04-28):
#   _THRESHOLDS does NOT auto-sync from AcceptanceThresholds
#   (`config/acceptance.yaml` / `core/config/schemas/acceptance.py`).
#   Future divergence is allowed; only an explicit versioned
#   recalibration PRD with (a) version bump, (b) contract migration
#   rationale, (c) backward-compat stance, and (d) changelog entry is
#   permitted to update _THRESHOLDS. The acceptance pack is the
#   stable promotion contract for already-promoted artifacts; its
#   numbers are a separate governance surface from the live Tier D /
#   walk-forward / factor-tier knobs in `cfg.acceptance`. See
#   `docs/prd/20260428-acceptance_threshold_unification_prd.md` v1.1
#   §4.5 for the full rule.
# ---------------------------------------------------------------------------


_THRESHOLDS = {
    "quick_min_sharpe": 0.30,
    "quick_max_drawdown": 0.40,
    "oos_min_pass_rate": 0.55,
    "oos_min_ir_vs_benchmark": 0.20,
    "oos_min_excess_return": 0.02,
    "maxdd_abs_floor": -0.25,              # strategy MaxDD must be >= -25%
    "maxdd_rel_multiplier": 1.5,           # strategy MaxDD <= 1.5× SPY
    "qqq_min_full_excess": 0.0,
    "qqq_min_holdout_excess": 0.0,
    "qqq_min_oos_avg_excess": 0.0,
    "min_holdout_ir": 0.0,
}


# ---------------------------------------------------------------------------
# Pack builder
# ---------------------------------------------------------------------------


def _coerce_numeric(v: Any) -> Any:
    """Best-effort numeric coercion; leave strings/None as-is if not convertible."""
    if v is None:
        return None
    if isinstance(v, (int, float, bool)):
        return v
    if isinstance(v, str):
        try:
            f = float(v)
            # Preserve bool-like 0/1 as int for cleaner JSON
            if f.is_integer():
                return int(f)
            return f
        except ValueError:
            return v
    return v


_NUMERIC_FIELDS = {
    "quick_sharpe", "quick_max_dd", "quick_cagr",
    "oos_ir", "oos_pass_rate", "oos_sharpe", "oos_excess_return",
    "diversity_corr",
    "holdout_ir", "holdout_excess_return", "holdout_max_dd",
    "qqq_full_period_excess", "qqq_holdout_excess", "qqq_oos_avg_excess",
}
_BOOL_FIELDS = {
    "passed_quick", "passed_oos",
    "regime_robust", "cost_robust", "param_robust", "stress_passed",
    "passed_diversity", "passed_holdout", "passed_qqq_gate",
}


def _normalize_row(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce sqlite row values to expected types."""
    out = dict(raw)
    for f in _NUMERIC_FIELDS:
        if f in out:
            out[f] = _coerce_numeric(out[f])
    for f in _BOOL_FIELDS:
        if f in out and out[f] is not None:
            v = _coerce_numeric(out[f])
            out[f] = bool(v) if v is not None else None
    return out


def _fetch_trial_row(archive_db: Path, spec_id: str) -> Dict[str, Any]:
    if not archive_db.exists():
        raise AcceptancePackError(f"Archive DB not found: {archive_db}")
    conn = sqlite3.connect(archive_db)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM trials WHERE spec_id = ?", (spec_id,)
        ).fetchone()
        if row is None:
            # Prefix match (no order-by — table may not have evaluated_at column
            # in synthetic test fixtures)
            row = conn.execute(
                "SELECT * FROM trials WHERE spec_id LIKE ? LIMIT 1",
                (spec_id + "%",),
            ).fetchone()
        if row is None:
            raise AcceptancePackError(f"spec_id {spec_id!r} not found in {archive_db}")
        return _normalize_row(dict(row))
    finally:
        conn.close()


def _run_fresh_full_period_check(trial: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Re-run on split-adjusted execution prices plus exact cash ledgers.

    Signals consume an exact total-return close recurrence, while portfolio
    execution consumes as-traded split-adjusted OHLC and credits per-share
    cash only to eligible overnight holders. SPY is a costed buy-and-hold
    portfolio on the same dates and data basis; QQQ is diagnostic only.
    """
    try:
        from pathlib import Path as _P
        import json as _json
        import pandas as _pd
        from core.config.loader import load_config
        from core.data.market_data_store import MarketDataStore
        from core.data.price_access import load_adjusted_panel
        from core.data.cash_distribution_access import (
            build_total_return_close_panel,
            load_cash_distribution_panel,
        )
        from core.regime.regime_detector import RegimeDetector
        from core.data.vix_loader import load_vix_series
        from core.signals.strategies.multi_factor import MultiFactorStrategy
        from core.portfolio.constructor import PortfolioConstructor
        from core.backtest.backtest_engine import BacktestEngine, compute_metrics
        from core.execution.cost_model import CostModel
    except Exception as exc:
        return {"error": f"import failed: {exc}"}

    strategy_type = trial.get("strategy_type")
    if strategy_type != "multi_factor":
        return {"error": f"fresh check only supports multi_factor (got {strategy_type})"}

    try:
        params = _json.loads(trial.get("params_json") or "{}")
    except Exception:
        return {"error": "params_json parse failed"}

    # Extract weights (w_<name> prefix) + ctor params
    factor_weights = {k[2:]: v for k, v in params.items() if k.startswith("w_")}
    if not factor_weights:
        factor_weights = params.get("factor_weights") or params.get("weights")
    if not factor_weights:
        return {"error": "no factor_weights in archive params"}

    ctor_keys = {"top_n", "rebalance_monthly", "score_weighted", "min_holding_days",
                 "lookback_mom", "lookback_quality", "lookback_vol", "apply_extra_shift"}
    ctor_params = {k: params[k] for k in ctor_keys if k in params}
    ctor_params.setdefault("apply_extra_shift", False)

    try:
        cfg = load_config(_P("config"))
        store = MarketDataStore(data_dir=_P(cfg.system.paths.data_dir))
        uni = cfg.universe
        all_syms = list(dict.fromkeys(
            list(uni.seed_pool) + list(uni.sector_etfs)
            + list(uni.factor_etfs) + list(uni.cross_asset)
        ))
        def_syms = [s for s in ["TLT", "IEF", "GLD", "SHY"] if s in all_syms]
        risk_syms = [s for s in all_syms if s not in def_syms
                     and s not in ["TQQQ", "SOXL"] and s not in uni.blacklist]

        panel = load_adjusted_panel(
            all_syms,
            store.data_dir,
            "1d",
            adjusted_total_return=False,
            fallback="local",
        )
        execution_close = panel["close"]
        open_df = panel["open"]
        if (
            execution_close.empty
            or open_df is None
            or "SPY" not in execution_close.columns
            or "QQQ" not in execution_close.columns
        ):
            return {"error": "price data unavailable"}
        open_df = open_df.reindex(
            index=execution_close.index, columns=execution_close.columns)
        cash = load_cash_distribution_panel(
            store.data_dir,
            list(execution_close.columns),
            execution_close.index,
            validate_coverage=True,
        )
        total_return_close = build_total_return_close_panel(execution_close, cash)
        risk_syms = [symbol for symbol in risk_syms if symbol in total_return_close]
        if not risk_syms:
            return {"error": "no risk-universe symbols on certified price basis"}
        spy_total_return = total_return_close["SPY"]
        vix = load_vix_series(store, execution_close.index, mode="lenient")
        regime = RegimeDetector(cfg.regime).classify_series(spy_total_return, vix)

        strat = MultiFactorStrategy(
            symbols=risk_syms, factor_weights=factor_weights, **ctor_params,
        )
        signals = strat.generate(total_return_close, regime)
        constructor = PortfolioConstructor(use_vol_parity=False)
        weights = constructor.build(
            raw_signals=signals,
            price_df=total_return_close,
            regime_series=regime,
        )
        cost = CostModel(cfg.cost_model)
        engine = BacktestEngine(cost_model=cost, initial_capital=10000)
        bt = engine.run(
            signals_df=weights,
            price_df=execution_close,
            open_df=open_df,
            regime_series=regime,
            cash_distributions_df=cash,
        )
        if engine._skipped_missing_open:
            return {
                "error": (
                    "fresh backtest attempted orders with missing execution opens: "
                    f"{engine._skipped_missing_open}"
                )
            }

        def _buy_and_hold(symbol: str):
            decision = _pd.DataFrame(
                {symbol: [1.0]},
                index=_pd.DatetimeIndex([execution_close.index[0]]),
            )
            target = decision.reindex(execution_close.index).ffill()
            benchmark_engine = BacktestEngine(
                cost_model=cost,
                initial_capital=10000,
                min_trade_usd=0.0,
                rebalance_threshold=0.0,
            )
            result = benchmark_engine.run(
                signals_df=target,
                price_df=execution_close[[symbol]],
                open_df=open_df[[symbol]],
                rebalance_dates=[execution_close.index[0]],
                cash_distributions_df=cash[[symbol]],
            )
            if benchmark_engine._skipped_missing_open:
                raise RuntimeError(f"{symbol} benchmark has missing execution open")
            return result

        spy_result = _buy_and_hold("SPY")
        qqq_result = _buy_and_hold("QQQ")
        equity_clean = bt.equity_curve.dropna()
        spy_equity = spy_result.equity_curve.reindex(equity_clean.index)
        metrics = compute_metrics(equity_clean, benchmark=spy_equity)
        strat_cagr_raw = metrics.get("cagr", metrics.get("CAGR", 0))
        strat_cagr = float(strat_cagr_raw) if strat_cagr_raw is not None else float("nan")
        spy_cagr = float(spy_result.metrics.get("cagr", float("nan")))
        qqq_cagr = float(qqq_result.metrics.get("cagr", float("nan")))

        # NaN-safe comparison: NaN excess → fail-closed
        import math
        if math.isnan(strat_cagr) or math.isnan(spy_cagr):
            return {
                "strategy_cagr": strat_cagr,
                "spy_cagr": spy_cagr,
                "qqq_cagr": qqq_cagr,
                "excess": float("nan"),
                "passed": False,
                "note": "NaN in strategy/SPY CAGR; fail-closed",
            }
        excess = strat_cagr - spy_cagr
        # M12 concentration metrics from the freshly-computed weight matrix.
        # These pass through verbatim from BacktestResult.metrics
        # (populated by core.backtest.concentration_metrics during run()).
        m12_top1 = bt.metrics.get("m12_top1_weight_max")
        m12_top3 = bt.metrics.get("m12_top3_weight_max")
        return {
            "strategy_cagr": strat_cagr,
            "spy_cagr": spy_cagr,
            "qqq_cagr": qqq_cagr,
            "excess": excess,
            "passed": excess > 0,
            "strategy_max_drawdown": metrics.get("max_drawdown"),
            "spy_max_drawdown": spy_result.metrics.get("max_drawdown"),
            "m12_top1_weight_max": m12_top1,
            "m12_top3_weight_max": m12_top3,
            "price_basis": "split_adjusted_execution_plus_exact_cash_ledger",
            "benchmark_symbol": "SPY",
            "strategy_costs_included": True,
        }
    except Exception as exc:
        return {"error": f"fresh backtest failed: {exc}"}


def _build_gates(
    trial: Dict[str, Any],
    fresh_check: Optional[Dict[str, Any]] = None,
    *,
    promotion_evidence: Any = None,
    automatic_promotion: bool = False,
) -> List[GateResult]:
    """Construct the gates from a trial row (and optional fresh check)."""
    gates: List[GateResult] = []

    # Gate 1: Quick evaluation
    qs, qdd, qcagr = trial.get("quick_sharpe"), trial.get("quick_max_dd"), trial.get("quick_cagr")
    passed_quick = bool(trial.get("passed_quick"))
    gates.append(GateResult(
        name="quick",
        passed=passed_quick,
        values={"sharpe": qs, "max_dd": qdd, "cagr": qcagr},
        threshold={
            "min_sharpe": _THRESHOLDS["quick_min_sharpe"],
            "max_drawdown": _THRESHOLDS["quick_max_drawdown"],
        },
        notes="Full-period backtest passes min Sharpe / CAGR / MaxDD" if passed_quick
              else "Failed quick gate (see mining evaluator stage 1)",
    ))

    # Gate 2: OOS walk-forward
    oos_ir, oos_pr, oos_ex = trial.get("oos_ir"), trial.get("oos_pass_rate"), trial.get("oos_excess_return")
    passed_oos = bool(trial.get("passed_oos"))
    gates.append(GateResult(
        name="oos_walk_forward",
        passed=passed_oos,
        values={"oos_ir": oos_ir, "pass_rate": oos_pr, "excess_return": oos_ex},
        threshold={
            "min_ir": _THRESHOLDS["oos_min_ir_vs_benchmark"],
            "min_pass_rate": _THRESHOLDS["oos_min_pass_rate"],
            "min_excess": _THRESHOLDS["oos_min_excess_return"],
        },
    ))

    # Gate 3: Robustness (regime + cost + param + stress)
    reg, cost, par, stress = (
        bool(trial.get("regime_robust")), bool(trial.get("cost_robust")),
        bool(trial.get("param_robust")), bool(trial.get("stress_passed")),
    )
    gates.append(GateResult(
        name="robustness",
        passed=(reg and cost and par and stress),
        values={"regime_robust": reg, "cost_robust": cost,
                "param_robust": par, "stress_passed": stress},
        threshold={"all_four_required": True},
    ))

    # Gate 4: Diversity (correlation with existing promoted)
    # Archive row may not always have this (legacy trials); treat None as skipped.
    div = trial.get("passed_diversity")
    if div is None:
        gates.append(GateResult(
            name="diversity",
            passed=not automatic_promotion,
            values={"diversity_corr": trial.get("diversity_corr")},
            threshold={"note": "Not evaluated against current promoted set"},
            notes=(
                "FAIL — automatic promotion requires measured diversity"
                if automatic_promotion
                else "DIAGNOSTIC SKIP — no prior promoted strategy to compare"
            ),
            binding=automatic_promotion,
        ))
    else:
        gates.append(GateResult(
            name="diversity",
            passed=bool(div),
            values={"diversity_corr": trial.get("diversity_corr")},
            threshold={"max_corr": 0.70},
        ))

    # Gate 5: Holdout (last 252d)
    passed_hold = bool(trial.get("passed_holdout"))
    gates.append(GateResult(
        name="holdout",
        passed=passed_hold,
        values={
            "holdout_ir": trial.get("holdout_ir"),
            "holdout_excess": trial.get("holdout_excess_return"),
            "holdout_max_dd": trial.get("holdout_max_dd"),
        },
        threshold={"min_ir": _THRESHOLDS["min_holdout_ir"]},
    ))

    # Gate 6: MaxDD absolute + relative
    max_dd = (
        fresh_check.get("strategy_max_drawdown")
        if fresh_check and "strategy_max_drawdown" in fresh_check
        else trial.get("quick_max_dd")
    )
    strat_dd_signed = -abs(max_dd) if max_dd is not None else None
    spy_dd = fresh_check.get("spy_max_drawdown") if fresh_check else None
    relative_ratio = None
    if strat_dd_signed is not None and spy_dd not in (None, 0):
        relative_ratio = abs(float(strat_dd_signed)) / abs(float(spy_dd))
    absolute_passed = (
        strat_dd_signed is not None
        and strat_dd_signed >= _THRESHOLDS["maxdd_abs_floor"]
    )
    passed_dd = absolute_passed and (
        not automatic_promotion
        or (
            relative_ratio is not None
            and relative_ratio <= _THRESHOLDS["maxdd_rel_multiplier"]
        )
    )
    gates.append(GateResult(
        name="max_drawdown",
        passed=passed_dd,
        values={
            "max_dd": strat_dd_signed,
            "spy_max_dd": spy_dd,
            "relative_ratio": relative_ratio,
        },
        threshold={
            "abs_floor": _THRESHOLDS["maxdd_abs_floor"],
            "rel_vs_spy_multiplier": _THRESHOLDS["maxdd_rel_multiplier"],
        },
        notes=(
            "Absolute and relative-to-SPY drawdown checks are both binding."
            if automatic_promotion
            else "Diagnostic pack enforces the historical absolute drawdown floor."
        ),
    ))

    # Gate 7: M12 concentration enforcement (codex Round-5).
    # When a fresh backtest is available, use the per-date top-1 / top-3
    # weight maxima to enforce the hard ceilings (40% / 70%). When no
    # fresh backtest is available, report an explicit non-binding diagnostic
    # gap. Automatic promotion treats the same missing evidence as a failure.
    from core.backtest.concentration_metrics import (
        DEFAULT_TOP1_CEILING,
        DEFAULT_TOP3_CEILING,
        validate_concentration,
    )
    if fresh_check and "m12_top1_weight_max" in fresh_check:
        m12_top1 = fresh_check.get("m12_top1_weight_max")
        m12_top3 = fresh_check.get("m12_top3_weight_max")
        if m12_top1 is None or m12_top3 is None:
            gates.append(GateResult(
                name="concentration",
                passed=False,
                values={
                    "m12_top1_weight_max": m12_top1,
                    "m12_top3_weight_max": m12_top3,
                },
                threshold={
                    "top1_ceiling": DEFAULT_TOP1_CEILING,
                    "top3_ceiling": DEFAULT_TOP3_CEILING,
                },
                notes=(
                    "FAIL — fresh backtest returned no concentration metrics; "
                    "treat as fail-closed (cannot certify concentration "
                    "without observed weights)."
                ),
            ))
        else:
            passed, breaches = validate_concentration(
                top1_observed=float(m12_top1),
                top3_observed=float(m12_top3),
            )
            gates.append(GateResult(
                name="concentration",
                passed=passed,
                values={
                    "m12_top1_weight_max": float(m12_top1),
                    "m12_top3_weight_max": float(m12_top3),
                    "breaches": breaches,
                },
                threshold={
                    "top1_ceiling": DEFAULT_TOP1_CEILING,
                    "top3_ceiling": DEFAULT_TOP3_CEILING,
                },
                notes=(
                    "PASS — observed top-1 / top-3 within ceilings."
                    if passed else
                    "FAIL — observed concentration breaches ceiling; "
                    "candidate is a concentrated bet, not a diversified "
                    "systematic strategy."
                ),
            ))
    else:
        gates.append(GateResult(
            name="concentration",
            passed=not automatic_promotion,
            values={"m12_top1_weight_max": None, "m12_top3_weight_max": None},
            threshold={
                "top1_ceiling": DEFAULT_TOP1_CEILING,
                "top3_ceiling": DEFAULT_TOP3_CEILING,
            },
            notes=(
                "FAIL — automatic promotion requires fresh concentration evidence"
                if automatic_promotion
                else "DIAGNOSTIC SKIP — fresh concentration evidence unavailable"
            ),
            binding=automatic_promotion,
        ))

    evidence_failures = (
        tuple(promotion_evidence.failed_checks)
        if promotion_evidence is not None
        else ("promotion_evidence_missing",)
    )
    evidence_payload = (
        promotion_evidence.payload
        if promotion_evidence is not None
        else {}
    )
    lookahead_passed = bool(evidence_payload.get("lookahead")) and not any(
        item.startswith("lookahead_") for item in evidence_failures
    )
    overfit_passed = bool(evidence_payload.get("overfit")) and not any(
        item.startswith("overfit_") for item in evidence_failures
    )
    gates.append(GateResult(
        name="lookahead_evidence",
        passed=lookahead_passed,
        values={"failed_checks": list(evidence_failures)},
        threshold={"candidate_bound_test_artifact": True},
        notes="Candidate-bound test evidence; a boolean attestation is insufficient.",
        binding=automatic_promotion,
    ))
    gates.append(GateResult(
        name="overfit_evidence",
        passed=overfit_passed,
        values={"failed_checks": list(evidence_failures)},
        threshold={"dsr_pbo_minbtl_cpcv": "all required"},
        notes="Prospective automatic promotion only; legacy absence is not a pass.",
        binding=automatic_promotion,
    ))

    alignment_passed = bool(evidence_payload.get("paper_backtest_alignment")) and not any(
        item.startswith("paper_backtest_alignment_") for item in evidence_failures
    )
    gates.append(GateResult(
        name="paper_backtest_alignment",
        passed=alignment_passed,
        values={"failed_checks": list(evidence_failures)},
        threshold={"max_equity_drift_bps": 10},
        notes="Requires a hashed candidate-specific replay/diff artifact.",
        binding=automatic_promotion,
    ))
    gates.append(GateResult(
        name="bound_promotion_evidence",
        passed=bool(promotion_evidence is not None and promotion_evidence.passed),
        values={"failed_checks": list(evidence_failures)},
        threshold={"all_evidence_controls_pass": True},
        notes="Missing or stale evidence routes to REVIEW_HOLD.",
        binding=automatic_promotion,
    ))

    # Gate 9: legacy QQQ diagnostic (from archive quick_eval excess)
    passed_qqq = bool(trial.get("passed_qqq_gate"))
    gates.append(GateResult(
        name="qqq_hard_gate_archive",
        passed=passed_qqq,
        values={
            "full_period_excess": trial.get("qqq_full_period_excess"),
            "holdout_excess": trial.get("qqq_holdout_excess"),
            "oos_avg_excess": trial.get("qqq_oos_avg_excess"),
        },
        threshold={
            "min_full_period": _THRESHOLDS["qqq_min_full_excess"],
            "min_holdout": _THRESHOLDS["qqq_min_holdout_excess"],
            "min_oos_avg": _THRESHOLDS["qqq_min_oos_avg_excess"],
        },
        notes="Diagnostic only under active SPY-primary governance.",
        binding=False,
    ))

    # Gate 10: fresh full-period exact-cash strategy vs costed SPY buy-and-hold.
    if fresh_check is None:
        gates.append(GateResult(
            name="full_period_fresh_backtest",
            passed=False,
            values={"skipped": True},
            threshold={"strategy_cagr_gt_spy_cagr": True},
            notes="Fresh backtest is mandatory for automatic promotion.",
            binding=automatic_promotion,
        ))
    elif "error" in fresh_check:
        gates.append(GateResult(
            name="full_period_fresh_backtest",
            passed=False,  # error on fresh → fail closed
            values={"error": fresh_check["error"]},
            threshold={"strategy_cagr_gt_spy_cagr": True},
            notes="Fresh backtest errored; cannot verify CAGR > SPY on current data. Fail-closed.",
        ))
    else:
        gates.append(GateResult(
            name="full_period_fresh_backtest",
            passed=bool(fresh_check.get("passed")),
            values={
                "strategy_cagr": fresh_check.get("strategy_cagr"),
                "spy_cagr": fresh_check.get("spy_cagr"),
                "qqq_cagr": fresh_check.get("qqq_cagr"),
                "excess": fresh_check.get("excess"),
                "price_basis": fresh_check.get("price_basis"),
            },
            threshold={"strategy_cagr_gt_spy_cagr": True},
            notes=(
                "Exact-cash, split-adjusted execution comparison against a "
                "costed SPY buy-and-hold portfolio."
            ),
        ))

    return gates


def run_acceptance_pack(
    spec_id: str,
    archive_db: str | Path = "data/mining/archive.db",
    run_fresh_backtest: bool = True,
    *,
    automatic_promotion: bool = False,
    promotion_evidence_path: str | Path | None = None,
    repo_root: str | Path | None = None,
) -> AcceptancePackResult:
    """Build an AcceptancePackResult for a given spec_id.

    Reads the archive trial row as authoritative historical evidence, and
    A diagnostic pack may omit expensive or prospective evidence. Automatic
    promotion mode never treats omission as a pass.
    """
    archive_path = Path(archive_db)
    trial = _fetch_trial_row(archive_path, spec_id)

    fresh_check = None
    if run_fresh_backtest:
        fresh_check = _run_fresh_full_period_check(trial)

    root = (
        Path(repo_root).resolve()
        if repo_root is not None
        else Path(__file__).resolve().parents[2]
    )
    promotion_evidence = None
    if promotion_evidence_path is not None or automatic_promotion:
        from core.research.promotion.evidence import validate_promotion_evidence

        try:
            commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True,
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            commit = None
        promotion_evidence = validate_promotion_evidence(
            promotion_evidence_path,
            expected_candidate_id=trial["spec_id"],
            repo_root=root,
            expected_code_commit=commit,
        )

    gates = _build_gates(
        trial,
        fresh_check=fresh_check,
        promotion_evidence=promotion_evidence,
        automatic_promotion=automatic_promotion,
    )
    try:
        params = json.loads(trial.get("params_json") or "{}")
    except Exception:
        params = {}

    return AcceptancePackResult(
        spec_id=trial["spec_id"],
        strategy_type=trial.get("strategy_type", "unknown"),
        lineage_tag=trial.get("lineage_tag", ""),
        params=params,
        gates=gates,
        overall_passed=all(g.passed for g in gates if g.binding),
        evaluated_at=datetime.now(timezone.utc).isoformat(),
        archive_evidence_only=(not run_fresh_backtest),
        promotion_evidence_path=(
            promotion_evidence.artifact_path if promotion_evidence else ""
        ),
        promotion_evidence_sha256=(
            promotion_evidence.artifact_sha256 if promotion_evidence else ""
        ),
        notes=(
            "Pack v3: QQQ is diagnostic; automatic promotion requires an "
            "exact-cash fresh SPY comparison plus bound lookahead, overfit, "
            "and paper/backtest-alignment evidence. Missing evidence routes "
            "to REVIEW_HOLD and is never a skip-pass."
        ),
    )


def write_acceptance_artifact(
    result: AcceptancePackResult,
    out_path: str | Path,
) -> Path:
    """Write pack result to JSON (pretty-printed)."""
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(result.as_dict(), indent=2, ensure_ascii=False))
    return p
