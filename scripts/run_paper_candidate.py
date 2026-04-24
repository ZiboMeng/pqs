#!/usr/bin/env python
"""Manual paper run for a frozen research candidate (Phase E-2 R8).

MVP paper runner per charter §6.1 "只做手动 daily run + frozen
candidate 验证, 不做 scheduler / daemon / live feed". Given a frozen
candidate at S1 or S2, replay its feature_set + weights as a composite
signal over a user-specified date range, simulate fills, and write
paper artifacts under `data/paper_runs/<candidate_id>/<run_date>/`.

Hard invariants (tested):
  - DOES NOT read config/production_strategy.yaml
  - DOES NOT use scripts/promote_strategy.py
  - Refuses if candidate status is not S1_research_candidate or
    S2_paper_candidate (i.e. candidate must already be promoted past
    S0 prototype)

Usage:
    # Happy path (on the real RCMv1 candidate, 60 days)
    python scripts/run_paper_candidate.py \
        --candidate-id rcm_v1_defensive_composite_01 \
        --start-date 2024-01-01 \
        --end-date 2024-03-01

    # Custom output dir
    python scripts/run_paper_candidate.py \
        --candidate-id my_cand \
        --start-date 2024-01-01 --end-date 2024-04-01 \
        --out-dir data/paper_runs/my_cand/2024-04-01

Portfolio construction (MVP):
  - Composite signal = sum(w_i * zscore_cs(feature_i))
  - Top-N ranking by composite value per date (N configurable,
    default 10)
  - Equal-weight among top-N, rest zero
  - Simulates T+1 open execution via BacktestEngine.run()

Artifacts written (all CSV, one row per date):
  - signals_daily.csv            composite signal values (date × symbol)
  - target_portfolio_daily.csv   target weights (date × symbol)
  - pnl_daily.csv                equity_curve + cash_curve + ret
  - fills.csv                    simulated fills from BacktestEngine

PRDs:
  docs/20260424-prd_phase_e_execution.md §2 E2-R8
  docs/20260424-prd_phase_e_governance_and_paper.md §E-2
  docs/20260424-prd_research_to_paper_promote_standard.md §11
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

from core.config.loader import load_config
from core.data.market_data_store import MarketDataStore
from core.execution.cost_model import CostModel
from core.factors.base_masks import apply_research_mask, research_mask
from core.factors.factor_generator import generate_all_factors
from core.logging_setup import get_logger, setup_logging
from core.mining.research_miner import zscore_cs
from core.research.candidate_registry import (
    CandidateRegistry,
    CandidateStatus,
)
from core.research.frozen_spec import FrozenStrategySpec

setup_logging()
logger = get_logger("run_paper_candidate")


_DEFAULT_REGISTRY_DB = "data/research_candidates/registry.db"
_DEFAULT_OUT_ROOT = Path("data/paper_runs")

def _load_candidate(
    registry_db: str, candidate_id: str,
) -> tuple[FrozenStrategySpec, CandidateStatus, str]:
    """Load candidate from registry. Returns (spec, status, frozen_path)."""
    registry = CandidateRegistry(registry_db)
    rec = registry.get(candidate_id)
    if rec.status not in (CandidateStatus.S1_CANDIDATE,
                          CandidateStatus.S2_PAPER):
        raise ValueError(
            f"Candidate {candidate_id} at {rec.status.value}; paper run "
            "requires S1_research_candidate or S2_paper_candidate"
        )
    if not rec.frozen_spec_path:
        raise ValueError(
            f"Candidate {candidate_id} has no frozen_spec_path"
        )
    spec = FrozenStrategySpec.from_yaml_file(rec.frozen_spec_path)
    return spec, rec.status, rec.frozen_spec_path


def _load_panel(
    cfg, store: MarketDataStore, start: pd.Timestamp, end: pd.Timestamp,
) -> dict[str, pd.DataFrame]:
    """Build an OHLCV panel + benchmark_map over [start, end] for the
    tradable universe. Mirrors run_research_miner._load_price_volume."""
    uni = cfg.universe
    syms = [s for s in dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs)
        + list(uni.factor_etfs) + list(uni.cross_asset)
    ) if s not in uni.blacklist and s not in uni.macro_reference]

    frames: dict[str, dict] = {k: {} for k in
                                ("close", "open", "high", "low", "volume")}
    for sym in syms:
        df = store.read(sym, "1d")
        if df is None or df.empty or "close" not in df.columns:
            continue
        frames["close"][sym] = df["close"]
        for col in ("open", "high", "low", "volume"):
            if col in df.columns:
                frames[col][sym] = df[col]
    close = pd.DataFrame(frames["close"]).sort_index()
    close = close[(close.index >= start) & (close.index <= end)]

    def _df(col: str) -> Optional[pd.DataFrame]:
        if not frames[col]:
            return None
        return pd.DataFrame(frames[col]).reindex_like(close)

    return {
        "close": close,
        "open": _df("open"),
        "high": _df("high"),
        "low": _df("low"),
        "volume": _df("volume"),
    }


def _compute_composite_signal(
    spec: FrozenStrategySpec, frames: dict,
) -> pd.DataFrame:
    """Compute composite z-score signal over the panel using spec's
    feature_set + weights."""
    close = frames["close"]
    volume = frames["volume"]
    benchmark_map = {b: close[b] for b in ("SPY", "QQQ") if b in close.columns}
    all_factors = generate_all_factors(
        close, volume_df=volume,
        open_df=frames["open"], high_df=frames["high"], low_df=frames["low"],
        benchmark_map=benchmark_map,
    )
    # Extract + z-score each feature
    # Normalize weights (spec weights may sum to <1 due to float rounding)
    total_w = sum(
        (f.weight or 0.0) for f in spec.feature_set
    ) or 1.0

    composite = None
    for feat in spec.feature_set:
        panel = all_factors.get(feat.name)
        if panel is None:
            raise RuntimeError(
                f"Feature {feat.name!r} not produced by factor_generator "
                f"on current panel (available: {list(all_factors)[:5]}...)"
            )
        z = zscore_cs(panel, min_periods=5)
        w = (feat.weight or 0.0) / total_w
        component = z * w
        composite = component if composite is None else composite.add(
            component, fill_value=0.0,
        )
    if composite is None:
        raise RuntimeError("Empty feature_set produced no composite")
    # Apply research mask
    if volume is not None:
        mask = research_mask(close, volume, min_price=5.0,
                             min_usd=20e6, window=20)
        composite = apply_research_mask(composite, mask)
    return composite


def _composite_to_target_weights(
    composite: pd.DataFrame, top_n: int,
) -> pd.DataFrame:
    """Select top-N by composite per date; equal-weight among selected.
    Returns DataFrame same shape as composite with target weights."""
    n_dates, n_symbols = composite.shape
    targets = pd.DataFrame(0.0, index=composite.index, columns=composite.columns)
    for i, date in enumerate(composite.index):
        row = composite.loc[date].dropna()
        if len(row) < top_n:
            continue  # not enough valid data on this date
        top = row.nlargest(top_n).index
        w = 1.0 / top_n
        for sym in top:
            targets.loc[date, sym] = w
    return targets


def _simulate(
    cfg, frames: dict, target_wts: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run BacktestEngine with the target weights as signals.

    Returns (pnl_df, fills_df):
      pnl_df: date × [equity_curve, cash_curve, ret]
      fills_df: trade ledger
    """
    from core.backtest.backtest_engine import BacktestEngine
    cm = CostModel(cfg.cost_model)
    be = BacktestEngine(cost_model=cm, initial_capital=100_000.0)
    result = be.run(
        signals_df=target_wts,
        price_df=frames["close"],
        open_df=frames["open"],
    )
    # Build pnl_df
    eq = result.equity_curve
    cash = result.cash_curve
    ret = eq.pct_change().fillna(0.0)
    pnl_df = pd.DataFrame({
        "equity_curve": eq,
        "cash_curve": cash,
        "ret": ret,
    })
    # result.trades is List[Fill]; flatten into a DataFrame for
    # artifact output
    if result.trades:
        fills_df = pd.DataFrame([
            {
                "date": f.fill_date,
                "symbol": f.order.symbol,
                "side": f.order.side.value if hasattr(f.order.side, "value")
                    else str(f.order.side),
                "quantity": f.executed_qty,
                "price": f.executed_price,
                "commission": f.cost_breakdown.commission_usd,
                "slippage": f.cost_breakdown.slippage_usd
                    if hasattr(f.cost_breakdown, "slippage_usd") else 0.0,
                "cash_delta": f.cash_delta,
            }
            for f in result.trades
        ])
    else:
        fills_df = pd.DataFrame(columns=[
            "date", "symbol", "side", "quantity", "price",
            "commission", "slippage", "cash_delta",
        ])
    return pnl_df, fills_df


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Manual paper run for a frozen research candidate "
                    "(Phase E-2 R8)",
    )
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--start-date", required=True,
                        help="ISO date (e.g. 2024-01-01)")
    parser.add_argument("--end-date", required=True,
                        help="ISO date (inclusive)")
    parser.add_argument("--top-n", type=int, default=10,
                        help="Top-N symbols to hold by composite rank "
                             "(equal-weight). Default 10")
    parser.add_argument("--registry-db", default=_DEFAULT_REGISTRY_DB)
    parser.add_argument("--out-dir", default=None,
                        help="Output directory; default "
                             "data/paper_runs/<candidate-id>/<YYYYMMDD>/")
    parser.add_argument("--config-dir", default="config")
    args = parser.parse_args()

    # Load candidate + frozen spec
    try:
        spec, status, frozen_path = _load_candidate(
            args.registry_db, args.candidate_id,
        )
    except ValueError as e:
        logger.error("%s", e)
        return 1
    except Exception as e:
        logger.error("Candidate load failed: %s", e)
        return 1
    logger.info("Candidate %s loaded at status %s (frozen_spec=%s)",
                args.candidate_id, status.value, frozen_path)
    logger.info("Feature set (%d): %s",
                len(spec.feature_set),
                [f.name for f in spec.feature_set])

    # Resolve output dir
    if args.out_dir:
        out_dir = Path(args.out_dir)
    else:
        run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = _DEFAULT_OUT_ROOT / args.candidate_id / run_stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load config + panel
    cfg = load_config(Path(args.config_dir))
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))
    start = pd.Timestamp(args.start_date)
    end = pd.Timestamp(args.end_date)
    frames = _load_panel(cfg, store, start, end)
    if frames["close"].empty:
        logger.error("No price data in requested range %s to %s",
                     args.start_date, args.end_date)
        return 1
    logger.info("Panel: %d dates × %d symbols",
                frames["close"].shape[0], frames["close"].shape[1])

    # Compute composite signal
    try:
        composite = _compute_composite_signal(spec, frames)
    except RuntimeError as e:
        logger.error("Composite signal failed: %s", e)
        return 1
    logger.info("Composite shape: %s, %d cells non-null",
                composite.shape, int(composite.notna().sum().sum()))

    # Target weights
    targets = _composite_to_target_weights(composite, args.top_n)
    n_active_rows = int((targets.sum(axis=1) > 0).sum())
    logger.info("Target weights: %d active rows (of %d)",
                n_active_rows, len(targets))

    # Simulate
    pnl_df, fills_df = _simulate(cfg, frames, targets)
    logger.info("Simulation: final equity=%.2f, trades=%d",
                pnl_df["equity_curve"].iloc[-1]
                if len(pnl_df) else float("nan"),
                len(fills_df))

    # Write core artifacts
    composite.to_csv(out_dir / "signals_daily.csv")
    targets.to_csv(out_dir / "target_portfolio_daily.csv")
    pnl_df.to_csv(out_dir / "pnl_daily.csv")
    fills_df.to_csv(out_dir / "fills.csv", index=False)

    # R9: extended paper artifacts (live-like + benchmark-relative + turnover)
    from core.research.paper_artifacts import (
        write_live_like_pnl,
        write_benchmark_relative_paper,
        write_turnover_log,
    )
    initial_capital = 100_000.0  # matches BacktestEngine default in _simulate
    if len(pnl_df):
        write_live_like_pnl(
            equity_curve=pnl_df["equity_curve"],
            cash_curve=pnl_df["cash_curve"],
            initial_capital=initial_capital,
            out_path=out_dir / "live_like_pnl.csv",
        )
        # Benchmark-relative using SPY + QQQ closes already on panel
        bench_closes = {
            sym: frames["close"][sym]
            for sym in ("SPY", "QQQ")
            if sym in frames["close"].columns
        }
        if bench_closes:
            write_benchmark_relative_paper(
                equity_curve=pnl_df["equity_curve"],
                benchmark_closes=bench_closes,
                initial_capital=initial_capital,
                out_path=out_dir / "benchmark_relative_paper.csv",
            )
    write_turnover_log(targets, out_dir / "turnover_log.csv")

    # Meta JSON (self-documenting for drift report consumers)
    import json
    (out_dir / "run_meta.json").write_text(json.dumps({
        "candidate_id": args.candidate_id,
        "status_at_run": status.value,
        "frozen_spec_path": str(frozen_path),
        "start_date": args.start_date,
        "end_date": args.end_date,
        "top_n": args.top_n,
        "n_dates": int(len(frames["close"])),
        "n_symbols": int(frames["close"].shape[1]),
        "n_active_rows": n_active_rows,
        "final_equity": float(pnl_df["equity_curve"].iloc[-1])
            if len(pnl_df) else None,
        "n_trades": int(len(fills_df)),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }, indent=2, default=str))

    print("=" * 70)
    print(f"Paper run complete: {args.candidate_id}")
    print("=" * 70)
    print(f"  Status          : {status.value}")
    print(f"  Date range      : {args.start_date} → {args.end_date}")
    print(f"  Panel           : {frames['close'].shape[0]} days × "
          f"{frames['close'].shape[1]} symbols")
    print(f"  Features        : {len(spec.feature_set)}")
    print(f"  Top-N           : {args.top_n}")
    print(f"  Final equity    : {pnl_df['equity_curve'].iloc[-1]:,.2f}"
          if len(pnl_df) else "  Final equity    : nan")
    print(f"  Trades          : {len(fills_df)}")
    print(f"  Artifacts       : {out_dir}")
    print(f"\n  Next: run scripts/paper_drift_report.py after >=5 days of "
          f"paper runs (R10).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
