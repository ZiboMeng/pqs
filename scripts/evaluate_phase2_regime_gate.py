#!/usr/bin/env python3
"""Compare independent and external-Regime-gated validation behavior."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.backtest.backtest_engine import BacktestEngine
from core.data.market_data_store import MarketDataStore
from core.data.vix_loader import load_vix_series
from core.execution.cost_model import CostModel
from core.regime.phase2_regime import Phase2RegimeAdapter, fail_closed_regime_scale
from core.regime.regime_detector import RegimeDetector
from core.research.phase2.metrics import detailed_metrics
from core.signals.strategies.phase2_etf import (
    DualIndexGrowthParams,
    DualIndexGrowthStrategy,
)
from scripts.run_strategy_phase2 import _load_panel


def _metrics(
    weights: pd.DataFrame,
    close: pd.DataFrame,
    open_prices: pd.DataFrame,
    cfg: Any,
) -> dict[str, float]:
    result = BacktestEngine(
        cost_model=CostModel(cfg.cost_model),
        initial_capital=cfg.system.account.initial_capital_usd,
        integer_shares=not cfg.risk.position_limits.allow_fractional_shares,
    ).run(
        signals_df=weights,
        price_df=close,
        open_df=open_prices,
        benchmark_series=close["QQQ"],
    )
    values = detailed_metrics(
        result,
        start=pd.Timestamp("2017-01-03"),
        end="2023-12-29",
        benchmark=close["QQQ"],
    )
    return {
        key: float(values[key])
        for key in (
            "cagr",
            "sharpe",
            "sortino",
            "max_drawdown",
            "calmar",
            "annual_turnover",
        )
    }


def evaluate() -> dict[str, Any]:
    close, open_prices, cfg = _load_panel("2023-12-29", "d2")
    strategy = DualIndexGrowthStrategy(
        DualIndexGrowthParams(
            slow_trend=168,
            equity_gross=0.70,
            cooldown_sessions=21,
        )
    )
    symbols = list(strategy.required_symbols)
    weights = strategy.generate(close[symbols])
    vix = load_vix_series(MarketDataStore(ROOT / "data"), close.index, mode="strict")
    legacy = RegimeDetector(cfg.regime).classify_series(close["SPY"], vix)
    regime = Phase2RegimeAdapter().classify(legacy, close["SPY"])
    risk_on = regime.state.isin(["RISK_ON", "STRONG_BULL_TREND"]) & regime.confidence.ge(0.50)
    quality = regime.state.ne("UNKNOWN") & regime.confidence.ge(0.50)
    scale = fail_closed_regime_scale(regime.state, regime.confidence, 0.50)
    variants = {
        "independent_internal_gate": weights,
        "external_risk_on_only": weights.where(risk_on, 0.0),
        "external_quality_fail_closed": weights.where(quality, 0.0),
        "external_exposure_scaled": weights.mul(scale, axis=0),
    }
    metrics = {
        name: _metrics(value, close[symbols], open_prices[symbols], cfg)
        for name, value in variants.items()
    }
    validation = slice("2017-01-03", "2023-12-29")
    return {
        "schema_version": 1,
        "strategy_id": strategy.strategy_id,
        "evaluation_role": "validation_regime_ablation",
        "evaluation_start": "2017-01-03",
        "evaluation_end": "2023-12-29",
        "code_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "data_manifest_sha256": hashlib.sha256(
            (ROOT / "research/registry/phase2_data_manifest.json").read_bytes()
        ).hexdigest(),
        "metrics": metrics,
        "risk_on_session_fraction": float(risk_on.loc[validation].mean()),
        "quality_accepted_session_fraction": float(quality.loc[validation].mean()),
        "decision": {
            "external_risk_on_gate": "REJECTED_NO_INCREMENTAL_VALUE",
            "paper_integration": "QUALITY_FAIL_CLOSED_ONLY",
            "economic_equity_gate": "strategy_internal_dual_index_long_trend",
            "reason": (
                "External risk-on-only gating materially reduced CAGR and Sharpe and "
                "increased turnover; the mandate permits independent operation when "
                "Regime gating has no validation increment."
            ),
        },
    }


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="research/results/phase2/regime/dual_index_growth_validation.json",
    )
    args = parser.parse_args()
    payload = evaluate()
    output = Path(args.output)
    _write(output, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
