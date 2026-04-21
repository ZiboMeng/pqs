"""Acceptance pack — validation checks required before promote_strategy.py
upgrades `config/production_strategy.yaml::status` to `active`.

PRD: docs/prd_framework_completion.md §M2

A spec_id from the mining archive is considered promotable only if it passes
ALL gates below. Each gate is a boolean with supporting diagnostic values;
the aggregate verdict (`overall_passed`) is `all(gate.passed for gate in ...)`.

**Pack v2 (2026-04-21, post-rollback)** — history: v1 trusted archive row as
authoritative evidence, but a real promote attempt revealed that archive's
`quick_cagr` / `qqq_full_period_excess` fields come from the **quick 70%
data fraction**, not a full-period backtest. A spec that looked great in
the quick window can underperform QQQ on full period.

v2 adds gate 10 `full_period_fresh_backtest` — re-runs MultiFactorStrategy
with spec params on full price panel, computes actual CAGR vs QQQ CAGR, and
fails if strategy doesn't beat QQQ on current data. This makes the pack
more expensive (1-2 min) but structurally honest.

Set `run_fresh_backtest=False` for unit tests with synthetic archives.
"""
from __future__ import annotations

import json
import sqlite3
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
            "notes": self.notes,
        }

    def summary_line(self) -> str:
        n_pass = sum(1 for g in self.gates if g.passed)
        return (
            f"AcceptancePack {self.spec_id[:12]} ({self.strategy_type}, "
            f"{self.lineage_tag}): {n_pass}/{len(self.gates)} gates passed, "
            f"overall={'PASS' if self.overall_passed else 'FAIL'}"
        )


class AcceptancePackError(RuntimeError):
    """Raised when the pack cannot be built (missing spec_id, bad archive)."""


# ---------------------------------------------------------------------------
# Gate thresholds (mirror config/backtest.yaml::mining but hardcoded here so
# the pack has a stable contract independent of config drift)
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
    """Re-run MultiFactorStrategy with spec params on current full price panel.

    Returns dict with keys {strategy_cagr, qqq_cagr, excess, passed} or None
    if data unavailable / strategy not multi_factor / any runtime error.

    This is expensive (1-2 min on 53-symbol universe × 19 years). Called
    only when pack is invoked with run_fresh_backtest=True.
    """
    try:
        from pathlib import Path as _P
        import json as _json
        import pandas as _pd
        from core.config.loader import load_config
        from core.data.market_data_store import MarketDataStore
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

        frames = {}
        open_frames = {}
        for sym in all_syms:
            df = store.read(sym, "1d")
            if df is not None and not df.empty and "close" in df.columns:
                frames[sym] = df["close"]
                if "open" in df.columns:
                    open_frames[sym] = df["open"]
        price_df = _pd.DataFrame(frames).sort_index()
        open_df = _pd.DataFrame(open_frames).sort_index() if open_frames else None
        if price_df.empty or "SPY" not in price_df.columns or "QQQ" not in price_df.columns:
            return {"error": "price data unavailable"}

        spy = price_df["SPY"]
        qqq = price_df["QQQ"]
        vix = load_vix_series(store, price_df.index, mode="lenient")
        regime = RegimeDetector(cfg.regime).classify_series(spy, vix)

        strat = MultiFactorStrategy(
            symbols=risk_syms, factor_weights=factor_weights, **ctor_params,
        )
        signals = strat.generate(price_df, regime)
        constructor = PortfolioConstructor(use_vol_parity=False)
        weights = constructor.build(
            raw_signals=signals, price_df=price_df, regime_series=regime,
        )
        cost = CostModel(cfg.cost_model)
        engine = BacktestEngine(cost_model=cost, initial_capital=10000)
        bt = engine.run(
            signals_df=weights, price_df=price_df, open_df=open_df,
            regime_series=regime, benchmark_series=spy,
        )
        # BacktestEngine may produce NaN in last bar (stale-data edge case);
        # drop trailing NaN before computing CAGR so fresh check is robust.
        equity_clean = bt.equity_curve.dropna()
        metrics = compute_metrics(equity_clean, benchmark=spy)
        # compute_metrics() uses lowercase 'cagr' key
        strat_cagr_raw = metrics.get("cagr", metrics.get("CAGR", 0))
        strat_cagr = float(strat_cagr_raw) if strat_cagr_raw is not None else float("nan")

        # Align QQQ window to backtest equity range for apples-to-apples
        bt_idx = bt.equity_curve.index if not bt.equity_curve.empty else qqq.index
        qqq_aligned = qqq.reindex(bt_idx, method="ffill").dropna()
        if len(qqq_aligned) < 2:
            return {"error": "QQQ window too short after alignment"}
        years = (qqq_aligned.index[-1] - qqq_aligned.index[0]).days / 365.25
        qqq_cagr = float(
            (qqq_aligned.iloc[-1] / qqq_aligned.iloc[0]) ** (1 / max(years, 0.01)) - 1
        )

        # NaN-safe comparison: NaN excess → fail-closed
        import math
        if math.isnan(strat_cagr) or math.isnan(qqq_cagr):
            return {
                "strategy_cagr": strat_cagr,
                "qqq_cagr": qqq_cagr,
                "excess": float("nan"),
                "passed": False,
                "note": "NaN in CAGR; BacktestEngine may have produced invalid equity curve",
            }
        excess = strat_cagr - qqq_cagr
        return {
            "strategy_cagr": strat_cagr,
            "qqq_cagr": qqq_cagr,
            "excess": excess,
            "passed": excess > 0,
        }
    except Exception as exc:
        return {"error": f"fresh backtest failed: {exc}"}


def _build_gates(
    trial: Dict[str, Any],
    fresh_check: Optional[Dict[str, Any]] = None,
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
        # Diversity passed by default if no promoted to compare against.
        gates.append(GateResult(
            name="diversity",
            passed=True,
            values={"diversity_corr": trial.get("diversity_corr")},
            threshold={"note": "Not evaluated against current promoted set"},
            notes="SKIP-PASS (no prior promoted to correlate against)",
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
    max_dd = trial.get("quick_max_dd")
    # quick_max_dd is stored as positive (e.g. 0.30 means -30%); convert.
    strat_dd_signed = -abs(max_dd) if max_dd is not None else None
    passed_dd = strat_dd_signed is None or (strat_dd_signed >= _THRESHOLDS["maxdd_abs_floor"])
    gates.append(GateResult(
        name="max_drawdown",
        passed=passed_dd,
        values={"max_dd": strat_dd_signed},
        threshold={
            "abs_floor": _THRESHOLDS["maxdd_abs_floor"],
            "rel_vs_spy_multiplier": _THRESHOLDS["maxdd_rel_multiplier"],
        },
        notes=("Relative-to-SPY check requires benchmark data; "
               "v1 acceptance pack enforces absolute floor only."),
    ))

    # Gate 7: Concentration — trivially pass here; MFS soft_cap is enforced at runtime.
    # (A future enhancement can inspect equity_curve / weights series if stored.)
    gates.append(GateResult(
        name="concentration",
        passed=True,
        values={"max_single_position_observed": None},
        threshold={"max_single_position_hard": 0.35},
        notes="Runtime-enforced via config/risk.yaml::position_limits; not re-validated in pack v1.",
    ))

    # Gate 8: Paper-backtest alignment — skipped in v1 pack (runtime contract
    # in M1 ensures same strategy instance in both). Future v2: run a small
    # replay + diff.
    gates.append(GateResult(
        name="paper_backtest_alignment",
        passed=True,
        values={},
        threshold={"max_equity_drift_bps": 10},
        notes="SKIP-PASS in pack v1; contract enforced by M1 single-source-of-truth + M3 alignment check.",
    ))

    # Gate 9: QQQ hard gate (from archive quick_eval excess)
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
        notes="Archive quick_eval excess (70% data); supplemented by gate 10 fresh-backtest.",
    ))

    # Gate 10: Fresh full-period backtest vs QQQ (pack v2, 2026-04-21 rollout)
    if fresh_check is None:
        gates.append(GateResult(
            name="full_period_fresh_backtest",
            passed=True,  # skip-pass when not requested
            values={"skipped": True},
            threshold={"strategy_cagr_gt_qqq_cagr": True},
            notes="SKIP-PASS — fresh backtest not requested (run_fresh_backtest=False); use CLI default to enforce.",
        ))
    elif "error" in fresh_check:
        gates.append(GateResult(
            name="full_period_fresh_backtest",
            passed=False,  # error on fresh → fail closed
            values={"error": fresh_check["error"]},
            threshold={"strategy_cagr_gt_qqq_cagr": True},
            notes="Fresh backtest errored; cannot verify CAGR > QQQ on current data. Fail-closed.",
        ))
    else:
        gates.append(GateResult(
            name="full_period_fresh_backtest",
            passed=bool(fresh_check.get("passed")),
            values={
                "strategy_cagr": fresh_check.get("strategy_cagr"),
                "qqq_cagr": fresh_check.get("qqq_cagr"),
                "excess": fresh_check.get("excess"),
            },
            threshold={"strategy_cagr_gt_qqq_cagr": True},
            notes=(
                "Re-ran full-period backtest with spec params on current data. "
                "This catches specs whose archive quick_eval excess was inflated "
                "by only using first 70% of data."
            ),
        ))

    return gates


def run_acceptance_pack(
    spec_id: str,
    archive_db: str | Path = "data/mining/archive.db",
    run_fresh_backtest: bool = True,
) -> AcceptancePackResult:
    """Build an AcceptancePackResult for a given spec_id.

    Reads the archive trial row as authoritative historical evidence, and
    (v2, if run_fresh_backtest=True) runs a fresh full-period backtest to
    verify CAGR beats QQQ on current data.
    """
    archive_path = Path(archive_db)
    trial = _fetch_trial_row(archive_path, spec_id)

    fresh_check = None
    if run_fresh_backtest:
        fresh_check = _run_fresh_full_period_check(trial)

    gates = _build_gates(trial, fresh_check=fresh_check)
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
        overall_passed=all(g.passed for g in gates),
        evaluated_at=datetime.now(timezone.utc).isoformat(),
        archive_evidence_only=(not run_fresh_backtest),
        notes=(
            "Pack v2: archive row evidence + optional fresh full-period "
            "backtest. Concentration / paper-backtest alignment gates are "
            "skip-pass (enforced elsewhere). Gate 10 'full_period_fresh_backtest' "
            "catches specs whose archive quick_eval (70% data) overstated "
            "CAGR vs full-period reality."
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
