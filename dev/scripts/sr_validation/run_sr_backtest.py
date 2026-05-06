#!/usr/bin/env python
"""S/R alpha-first plan — Step 5 backtest harness (PRD 20260505).

Runs a candidate FrozenStrategySpec under daily T+1 open execution
(matches forward observe path), optionally with a S/R defer filter
that zeros out target_wts cells where T-day's 60m close is hugging
swing-based resistance. Path A of the Step 5b retest after Step 5b
v1 (intraday + decide_timing modulation) was found to destroy daily-
holding-period strategies (NAV -91%, MaxDD -100% on trial9).

Two-arm comparison (run separately, compare offline):
  A) --enable-sr-defer  (Path A: T+1 open + 60m S/R defer-day filter)
  B) (no flag)          (baseline: pure T+1 open via BacktestEngine)

Path A Mechanism:
  For each (T_date, symbol) cell in target_wts where weight > 0:
    1. Look up the symbol's 60m bars on T_date (T-day's intraday bars)
    2. Take the LAST 60m bar of T-day (i.e., closest to T-day close
       at 16:00 ET)
    3. Compute swing-based nearest support/resistance via
       core.intraday.sr_swing.compute_nearest_sr (n=5, lookback=20)
    4. If close is within sr_near_resistance_pct of resistance
       → set target_wts[T_date, symbol] = 0
  Effect: skip NEW entries on days where symbol is hugging
  resistance. Existing positions also re-targeted to 0 if they're
  hugging R (this drains positions chasing R, conservative behavior).
  Preserves T+1 open execution semantics throughout.

CLAUDE.md sealed-window discipline: default end=2025-12-31. The
S/R computation is past-only (compute_sr_levels_at truncates at as_of).

NOTE: Step 3's intraday + decide_timing path (--execution-mode intraday)
is preserved for completeness but Step 5b v1 demonstrated it is
structurally destructive for ~21d holding strategies. NOT recommended.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from core.backtest.backtest_engine import BacktestEngine, compute_metrics
from core.backtest.intraday_engine import IntradayBacktestEngine
from core.config.loader import load_config
from core.data.factory import create_default_store
from core.execution.cost_model import CostModel
from core.intraday.multi_timescale import (
    TimingThresholds,
    build_context,
    decide_timing,
    load_multi_timescale_bars,
)
from core.research.frozen_spec import FrozenStrategySpec
from core.research.robustness.runner import (
    _composite_to_target_weights,
    _compute_composite,
    _load_panel,
)


def _build_label(args: argparse.Namespace, spec_id: str) -> str:
    parts = [spec_id, args.execution_mode]
    if args.enable_sr_defer:
        parts.append("sr_defer")
    if args.enable_sr_timing:
        parts.append("sr_timing")
    parts.append(f"top{args.top_n}")
    return "_".join(parts)


def _apply_sr_defer_filter(
    target_wts: pd.DataFrame,
    multi_bars: dict,
    thresholds: TimingThresholds,
    start: Optional[pd.Timestamp] = None,
    end: Optional[pd.Timestamp] = None,
) -> tuple[pd.DataFrame, int, int]:
    """Path A defer filter — zero out target_wts cells where T-day's
    60m close is hugging swing-based resistance.

    Returns
    -------
    (modified_target_wts, n_defers, n_evaluated)
        n_defers     : number of cells zeroed by the filter
        n_evaluated  : number of cells evaluated (defined target weight
                       AND symbol has 60m coverage AND has bars on T_date)

    Implementation note (perf): pre-computes ``compute_nearest_sr`` ONCE
    per symbol on the full 60m series, plus a per-date last-bar timestamp
    map. Per-cell lookup is then O(1). Earlier naive per-cell call to
    ``compute_sr_levels_at`` was O(L*lookback) per query × 162k cells
    ≈ multi-billion-op trap; killed at 11 min mark before 1st spec
    finished.
    """
    from core.intraday.sr_swing import compute_nearest_sr

    if "60m" not in multi_bars or not multi_bars["60m"]:
        return target_wts, 0, 0

    out = target_wts.copy()
    n_defers = 0
    n_evaluated = 0

    # Pre-compute per-symbol SR DataFrame + last-bar-of-day map.
    sym_sr_cache: dict[str, pd.DataFrame] = {}
    sym_close_cache: dict[str, pd.Series] = {}
    sym_last_bar_by_date: dict[str, dict] = {}

    for sym, sym_60 in multi_bars["60m"].items():
        if sym_60 is None or sym_60.empty:
            continue
        # Restrict to <= end_date so SR computation cannot peek into
        # the sealed window (CLAUDE.md discipline).
        sym_60_used = sym_60
        if end is not None:
            sym_60_used = sym_60[sym_60.index <= end]
            if sym_60_used.empty:
                continue
        sr_full = compute_nearest_sr(
            sym_60_used,
            n=thresholds.sr_swing_n,
            lookback=thresholds.sr_lookback_bars,
        )
        sym_sr_cache[sym] = sr_full
        sym_close_cache[sym] = sym_60_used["close"]
        last_idx_by_date: dict = {}
        for ts in sym_60_used.index:
            last_idx_by_date[ts.date()] = ts
        sym_last_bar_by_date[sym] = last_idx_by_date

    for date in target_wts.index:
        if start is not None and date < start:
            continue
        if end is not None and date > end:
            continue
        row = target_wts.loc[date]
        for sym, w in row.items():
            if w <= 0:
                continue
            sr_full = sym_sr_cache.get(sym)
            if sr_full is None:
                continue
            last_bar_ts = sym_last_bar_by_date[sym].get(date.date())
            if last_bar_ts is None:
                continue
            if last_bar_ts not in sr_full.index:
                continue
            n_evaluated += 1
            R = sr_full.at[last_bar_ts, "resistance"]
            if pd.isna(R):
                continue
            close = float(sym_close_cache[sym].at[last_bar_ts])
            if close <= 0 or R <= close:
                continue
            gap_frac = (R - close) / close
            if 0 < gap_frac <= thresholds.sr_near_resistance_pct:
                out.at[date, sym] = 0.0
                n_defers += 1

    return out, n_defers, n_evaluated


def _run_daily_arm(
    target_wts: pd.DataFrame,
    panel: dict,
    initial_capital: float,
    cost_cfg,
) -> tuple[pd.Series, dict]:
    """Daily T+1 open execution via BacktestEngine. Mirrors forward observe."""
    cm = CostModel(cost_cfg)
    engine = BacktestEngine(cost_model=cm, initial_capital=initial_capital)
    result = engine.run(
        signals_df=target_wts,
        price_df=panel["close"],
        open_df=panel["open"],
    )
    eq = result.equity_curve
    n_trades = len(result.trades or [])
    return eq, {"n_trades": n_trades, "n_bars": len(eq)}


def _run_intraday_arm(
    target_wts: pd.DataFrame,
    panel: dict,
    multi_bars: dict,
    initial_capital: float,
    cost_cfg,
    thresholds: TimingThresholds,
    start_date: Optional[pd.Timestamp] = None,
    end_date: Optional[pd.Timestamp] = None,
) -> tuple[pd.Series, dict]:
    """Intraday execution via IntradayBacktestEngine + decide_timing.

    ``start_date`` / ``end_date`` (inclusive) bound the iteration range
    so the harness respects CLAUDE.md sealed-window discipline (default
    end=2025-12-31). Without these bounds the loop iterates every date
    present in the loaded 60m bars (which go further back / forward than
    the panel and may include the sealed 2026 window).
    """
    cm = CostModel(cost_cfg)
    engine = IntradayBacktestEngine(
        cost_model=cm, initial_capital=initial_capital, eod_force_close=False,
    )

    cash = float(initial_capital)
    positions: dict[str, float] = {}
    eq_records: list[tuple] = []

    n_trades = 0
    n_vetoes = 0
    n_sr_fires = 0

    # Iterate trading dates that have BOTH a target weight row and 60m bar coverage
    target_dates = set(target_wts.index)
    if "60m" not in multi_bars or not multi_bars["60m"]:
        raise RuntimeError("intraday mode requires 60m bars; none available")
    sample_sym = next(iter(multi_bars["60m"]))
    intraday_dates = sorted({d.date() for d in multi_bars["60m"][sample_sym].index})

    # Bound to caller's [start, end] window. Critical for CLAUDE.md
    # sealed-window discipline (default end=2025-12-31). 60m bar files
    # extend further back/forward than the panel; without this filter
    # we'd silently read the sealed 2026 panel.
    if start_date is not None:
        start_d = pd.Timestamp(start_date).date()
        intraday_dates = [d for d in intraday_dates if d >= start_d]
    if end_date is not None:
        end_d = pd.Timestamp(end_date).date()
        intraday_dates = [d for d in intraday_dates if d <= end_d]

    for date in intraday_dates:
        date_ts = pd.Timestamp(date)
        if date_ts not in target_dates:
            eq_records.append((date_ts, cash + sum(
                qty * panel["close"].at[date_ts, sym] if (sym in panel["close"].columns
                    and date_ts in panel["close"].index
                    and pd.notna(panel["close"].at[date_ts, sym]))
                else 0
                for sym, qty in positions.items()
            )))
            continue

        day_wts = target_wts.loc[date_ts]
        base_targets = {s: float(v) for s, v in day_wts.items() if v > 1e-6}
        if not base_targets:
            eq_records.append((date_ts, cash))
            continue

        # Build day-level intraday bars per symbol (held + targeted set)
        day_bars: dict[str, pd.DataFrame] = {}
        for sym in set(list(base_targets) + list(positions)):
            sym_60 = (multi_bars.get("60m") or {}).get(sym)
            if sym_60 is None:
                continue
            mask = sym_60.index.date == date
            if mask.any():
                day_bars[sym] = sym_60[mask]
        if not day_bars:
            eq_records.append((date_ts, cash))
            continue

        # Compute timing decisions at mid-day reference bar
        ref_bars = next(iter(day_bars.values()))
        mid_bar_ts = ref_bars.index[len(ref_bars) // 2]
        adjusted_targets: dict[str, float] = {}

        # SR levels per (sym, freq=60m) at mid-day reference
        sr_levels_per_sym: dict[str, dict] = {}
        if thresholds.enable_sr_timing:
            from core.intraday.multi_timescale import compute_sr_levels_at
            for sym in base_targets:
                sym_60 = (multi_bars.get("60m") or {}).get(sym)
                if sym_60 is None:
                    continue
                sr = compute_sr_levels_at(
                    sym_60, mid_bar_ts, freq="60m",
                    n=thresholds.sr_swing_n,
                    lookback=thresholds.sr_lookback_bars,
                )
                if sr is not None:
                    sr_levels_per_sym[sym] = {"60m": sr}

        for sym, bw in base_targets.items():
            ctx = build_context(multi_bars, sym, mid_bar_ts)
            decision = decide_timing(
                ctx, sym, base_weight=float(bw), daily_side=1,
                thresholds=thresholds,
                sr_levels=sr_levels_per_sym.get(sym),
            )
            if not decision.execute:
                n_vetoes += 1
                continue
            if decision.higher_tf_vote.get("sr_60m") == "near_resistance":
                n_sr_fires += 1
            adjusted_targets[sym] = decision.effective_weight

        result = engine.run_multi_day(
            date=date_ts, day_bars=day_bars, target_wts=adjusted_targets,
            positions=positions, cash=cash,
        )
        positions = result.eod_positions
        cash = result.eod_cash
        n_trades += result.n_trades

        eod_equity = cash
        for sym, qty in positions.items():
            if sym in day_bars and len(day_bars[sym]) > 0:
                eod_equity += qty * float(day_bars[sym]["close"].iloc[-1])
        eq_records.append((date_ts, eod_equity))

    eq = pd.Series(
        [v for (_d, v) in eq_records],
        index=pd.DatetimeIndex([d for (d, _v) in eq_records]),
    )
    return eq, {
        "n_trades": int(n_trades),
        "n_vetoes": int(n_vetoes),
        "n_sr_fires": int(n_sr_fires),
        "n_bars": len(eq),
    }


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidate-spec-yaml", required=True,
                    help="Path to FrozenStrategySpec yaml")
    ap.add_argument("--execution-mode", choices=["daily", "intraday"],
                    default="daily")
    ap.add_argument("--enable-sr-timing", action="store_true",
                    help="(Step 3 path) Activate S/R-aware timing modifier "
                         "in decide_timing. Intraday mode only. Step 5b v1 "
                         "found this destructive for daily-holding strategies "
                         "— prefer --enable-sr-defer (Path A) instead.")
    ap.add_argument("--enable-sr-defer", action="store_true",
                    help="(Path A) Apply S/R defer filter to target_wts: "
                         "zero out cells where T-day's 60m close is hugging "
                         "swing-based resistance. Daily mode only; preserves "
                         "T+1 open execution semantics.")
    ap.add_argument("--top-n", type=int, default=10)
    ap.add_argument("--start", default="2018-01-01",
                    help="Backtest start (default 2018-01-01)")
    ap.add_argument("--end", default="2025-12-31",
                    help="Backtest end (default 2025-12-31; sealed-window discipline)")
    ap.add_argument("--initial-capital", type=float, default=10000.0)
    ap.add_argument("--output-dir", default="data/sr_validation")
    ap.add_argument("--label", default=None,
                    help="Output label (default = auto-derived)")
    args = ap.parse_args(argv)

    if args.enable_sr_timing and args.execution_mode != "intraday":
        print("[warn] --enable-sr-timing requires --execution-mode intraday; "
              "flag will have no effect in daily mode.",
              file=sys.stderr)
    if args.enable_sr_defer and args.execution_mode != "daily":
        ap.error("--enable-sr-defer is only meaningful with "
                 "--execution-mode daily (Path A semantics)")

    spec_path = Path(args.candidate_spec_yaml)
    spec = FrozenStrategySpec.from_yaml_file(spec_path)
    spec_id = spec.candidate_id

    label = args.label or _build_label(args, spec_id)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = load_config()
    store = create_default_store(cfg)

    print(f"[harness] spec={spec_id}  mode={args.execution_mode}  "
          f"sr_timing={args.enable_sr_timing}  range=[{args.start}, {args.end}]")
    print(f"[harness] loading panel...")
    panel = _load_panel(
        cfg, store,
        start=pd.Timestamp(args.start),
        end=pd.Timestamp(args.end),
    )
    print(f"[harness] panel shape: close={panel['close'].shape}")

    print(f"[harness] computing composite + targets (top_n={args.top_n})...")
    composite, _factors = _compute_composite(spec, panel)
    target_wts = _composite_to_target_weights(composite, top_n=args.top_n)
    print(f"[harness] target_wts shape: {target_wts.shape}, "
          f"non-zero rows: {(target_wts.sum(axis=1) > 0).sum()}")

    if args.execution_mode == "daily":
        defer_stats = {"n_sr_defers": 0, "n_sr_evaluated": 0}
        if args.enable_sr_defer:
            target_syms = [s for s in target_wts.columns
                           if (target_wts[s] > 0).any()]
            print(f"[harness] loading 60m bars for SR defer filter "
                  f"({len(target_syms)} target syms)...")
            multi_bars = load_multi_timescale_bars(
                store, target_syms, freqs=["60m"],
            )
            thresholds = TimingThresholds.from_config(cfg.risk.intraday_timing)
            print(f"[harness] applying SR defer filter "
                  f"(near_R_pct={thresholds.sr_near_resistance_pct})...")
            target_wts, n_defers, n_eval = _apply_sr_defer_filter(
                target_wts, multi_bars, thresholds,
                start=pd.Timestamp(args.start),
                end=pd.Timestamp(args.end),
            )
            defer_stats = {"n_sr_defers": n_defers, "n_sr_evaluated": n_eval}
            defer_pct = (n_defers / n_eval * 100) if n_eval > 0 else 0
            print(f"[harness] SR defer fired: {n_defers}/{n_eval} cells "
                  f"({defer_pct:.2f}%)")
        eq, run_stats = _run_daily_arm(
            target_wts, panel, args.initial_capital, cfg.cost_model,
        )
        run_stats.update(defer_stats)
    else:
        thresholds_cfg = cfg.risk.intraday_timing
        thresholds = TimingThresholds.from_config(thresholds_cfg)
        # Override enable_sr_timing per CLI flag (allows running both arms
        # without modifying yaml).
        thresholds = TimingThresholds(
            **{**thresholds.__dict__,
               "enable_sr_timing": bool(args.enable_sr_timing)},
        )
        target_syms = [s for s in target_wts.columns
                       if (target_wts[s] > 0).any()]
        print(f"[harness] loading 60m + 30m bars for {len(target_syms)} target syms...")
        multi_bars = load_multi_timescale_bars(
            store, target_syms, freqs=["60m", "30m"],
        )
        eq, run_stats = _run_intraday_arm(
            target_wts, panel, multi_bars,
            args.initial_capital, cfg.cost_model, thresholds,
            start_date=pd.Timestamp(args.start),
            end_date=pd.Timestamp(args.end),
        )

    if eq.empty or len(eq) < 2:
        print(f"[harness] insufficient equity points ({len(eq)}); aborting",
              file=sys.stderr)
        return 1

    metrics = compute_metrics(eq, initial_capital=args.initial_capital)
    spy = panel["close"].get("SPY")
    qqq = panel["close"].get("QQQ")
    spy_excess = (
        float(eq.iloc[-1] / eq.iloc[0] - 1.0) - float(
            spy.loc[eq.index[0]:eq.index[-1]].iloc[-1]
            / spy.loc[eq.index[0]:eq.index[-1]].iloc[0] - 1.0)
        if spy is not None else None
    )
    qqq_excess = (
        float(eq.iloc[-1] / eq.iloc[0] - 1.0) - float(
            qqq.loc[eq.index[0]:eq.index[-1]].iloc[-1]
            / qqq.loc[eq.index[0]:eq.index[-1]].iloc[0] - 1.0)
        if qqq is not None else None
    )

    out_metrics = {
        "label": label,
        "spec_id": spec_id,
        "execution_mode": args.execution_mode,
        "enable_sr_timing": bool(args.enable_sr_timing),
        "top_n": args.top_n,
        "start": str(eq.index[0].date()),
        "end": str(eq.index[-1].date()),
        "n_bars": int(len(eq)),
        "initial_capital": args.initial_capital,
        "final_nav": float(eq.iloc[-1]),
        "cum_ret": float(eq.iloc[-1] / eq.iloc[0] - 1.0),
        "cagr": float(metrics.get("cagr", 0.0)),
        "sharpe": float(metrics.get("sharpe", 0.0)),
        "max_drawdown": float(metrics.get("max_drawdown", 0.0)),
        "win_rate": float(metrics.get("win_rate", 0.0)),
        "vs_spy_full": spy_excess,
        "vs_qqq_full": qqq_excess,
        **run_stats,
        "computed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    nav_path = out_dir / f"{label}_nav.parquet"
    metrics_path = out_dir / f"{label}_metrics.json"
    eq.to_frame("equity").to_parquet(nav_path)
    with metrics_path.open("w") as f:
        json.dump(out_metrics, f, indent=2)

    print()
    print(f"=== {label} ===")
    print(f"  Range:    {out_metrics['start']} ~ {out_metrics['end']} ({out_metrics['n_bars']} bars)")
    print(f"  Final NAV: ${out_metrics['final_nav']:,.2f}")
    print(f"  cum_ret:  {out_metrics['cum_ret']*100:+.2f}%")
    print(f"  CAGR:     {out_metrics['cagr']*100:+.2f}%")
    print(f"  Sharpe:   {out_metrics['sharpe']:.2f}")
    print(f"  MaxDD:    {out_metrics['max_drawdown']*100:.2f}%")
    if spy_excess is not None:
        print(f"  vs SPY:   {spy_excess*100:+.2f}%")
    if qqq_excess is not None:
        print(f"  vs QQQ:   {qqq_excess*100:+.2f}%")
    print(f"  Run stats: {run_stats}")
    print(f"  Outputs:")
    print(f"    {nav_path}")
    print(f"    {metrics_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
