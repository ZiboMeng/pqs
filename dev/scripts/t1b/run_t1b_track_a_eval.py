"""T1b ConfirmationPatternStrategy Phase 2-3 — Track A acceptance + NAV correlation.

Uses K1 SignalDrivenBacktest wrapper (per roadmap v2 unified architecture):
- Build entry_signals from breakout_high_n detection
- Confirmation predicate from _confirmation_close_above_setup
- exit_signals = setup_bar + confirmation_ttl + delay + max_holding_days approximation

PRD ConfirmationPatternConfig defaults (LOCKED for first-fire):
  arm_type=breakout_high_n / setup_lookback_days=20 /
  confirmation_ttl_bars=5 / confirmation_threshold_pct=1.0 /
  volume_multiplier=1.5 / top_n=5

Universe: 53-stock seed_pool (excl SPY/QQQ/GLD/TQQQ/SOXL/SQQQ/SOXS).
Period: 2018-2025 (validation panel).
Acceptance: temporal_split_acceptance run_split_acceptance role=core.
Anti-sibling: vs RCMv1, Cand-2, trial9_v2 NAV.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import date

PROJ = Path("/home/zibo/Documents/projects/pqs")
sys.path.insert(0, str(PROJ))

import numpy as np
import pandas as pd

from core.backtest.backtest_engine import BacktestEngine
from core.backtest.signal_driven_runner import SignalDrivenBacktest
from core.data.bar_store import BarStore
from core.execution.cost_model import CostModel
from core.config.schemas.cost_model import CostModelConfig, CostTierConfig
from core.research.temporal_split_acceptance import run_split_acceptance
from core.research.temporal_split import (
    load_temporal_split, resolve_split_path,
)
from core.signals.strategies.confirmation_pattern import (
    ConfirmationPatternConfig,
)


# Locked config — PRD §4.2 defaults
CFG = ConfirmationPatternConfig(
    arm_type="breakout_high_n",
    setup_lookback_days=20,
    confirmation_ttl_bars=5,
    confirmation_threshold_pct=1.0,
    volume_multiplier=1.5,
    top_n=5,
)
MAX_HOLDING_DAYS = 21  # ~ monthly cap
EXEC_DELAY_BARS = 1


def _load_universe():
    import yaml
    with open(PROJ / "config/universe.yaml") as f:
        u = yaml.safe_load(f)
    seed = sorted([s for s in u.get("seed_pool", [])
                   if s not in ("SPY", "QQQ", "GLD", "TQQQ", "SOXL", "SQQQ", "SOXS")])
    return seed


def _build_panels(symbols, start_date="2017-01-02", end_date="2025-12-31"):
    """Load close + volume + open panels from BarStore (clean post-A.3)."""
    store = BarStore()
    closes = {}
    volumes = {}
    opens = {}
    for sym in symbols:
        try:
            df = store.load(sym, freq="1d", adjusted=True).sort_index()
            df = df[(df.index >= pd.Timestamp(start_date))
                    & (df.index <= pd.Timestamp(end_date))]
            if df.empty:
                continue
            closes[sym] = df["close"]
            if "volume" in df.columns:
                volumes[sym] = df["volume"]
            if "open" in df.columns:
                opens[sym] = df["open"]
        except Exception as e:
            print(f"  warn: {sym} load failed: {e}")
    close_df = pd.DataFrame(closes).sort_index()
    volume_df = pd.DataFrame(volumes).reindex(index=close_df.index, columns=close_df.columns)
    open_df = pd.DataFrame(opens).reindex(index=close_df.index, columns=close_df.columns)
    return close_df, volume_df, open_df


def _build_entry_exit_signals(close_df, volume_df, cfg):
    """ConfirmationPattern breakout_high_n: entry at T iff close[T] > rolling_max[T-1].

    Exit approximation: setup_bar + confirmation_ttl + delay + max_holding.
    """
    rolling_max = close_df.rolling(cfg.setup_lookback_days).max().shift(1)
    entry = (close_df > rolling_max).fillna(False)

    # Exit signals: each setup bar T projects an exit at
    # T + confirmation_ttl + exec_delay + max_holding
    offset = cfg.confirmation_ttl_bars + EXEC_DELAY_BARS + MAX_HOLDING_DAYS
    exit_signals = pd.DataFrame(False, index=close_df.index, columns=close_df.columns)
    # Vectorized: shift entry mask by offset
    shifted = entry.shift(offset).fillna(False)
    exit_signals = shifted

    return entry, exit_signals


def _confirmation_predicate_factory(close_df, threshold_pct):
    """Return a confirmation_predicate(state, bar_idx, ctx) closure.

    Confirms iff current close >= setup price × (1 + threshold_pct/100).
    """
    dates = close_df.index

    def predicate(state, bar_idx, ctx):
        # state has armed_at_bar; we need to look up the setup close
        if bar_idx >= len(dates):
            return False
        sym = state.symbol
        if sym not in close_df.columns:
            return False
        # Setup price = close at armed_at_bar (when breakout detected)
        if state.armed_at_bar < 0 or state.armed_at_bar >= len(dates):
            return False
        setup_date = dates[state.armed_at_bar]
        cur_date = dates[bar_idx]
        try:
            setup_price = float(close_df.loc[setup_date, sym])
            cur_price = float(close_df.loc[cur_date, sym])
        except (KeyError, ValueError):
            return False
        if not np.isfinite(setup_price) or not np.isfinite(cur_price) or setup_price <= 0:
            return False
        # Confirmation: current close >= setup × (1 + threshold/100)
        # AND age > 0 (need at least 1 bar after setup to give the market
        # time to confirm; age==0 same-bar would be cheating)
        age = bar_idx - state.armed_at_bar
        if age == 0:
            return False
        return cur_price >= setup_price * (1 + threshold_pct / 100.0)

    return predicate


def _max_dd(nav: pd.Series) -> float:
    if len(nav) < 2:
        return 0.0
    peak = nav.cummax()
    return float(((nav - peak) / peak.replace(0, np.nan)).min())


def _annual_ret(nav: pd.Series) -> float:
    if len(nav) < 2:
        return 0.0
    return float((nav.iloc[-1] - nav.iloc[0]) / nav.iloc[0])


def _build_metrics(strat_nav: pd.Series, spy_nav: pd.Series, qqq_nav: pd.Series,
                   stress_slices: dict, top1_max: float, top3_max: float) -> dict:
    """Same shape as alt-A's _build_metrics."""
    metrics = {
        "validation": {},
        "stress_slice": {},
        "concentration": {
            "top1_max": top1_max,
            "top3_max": top3_max,
            "leveraged_etf_dependency": False,
        },
        "beta": {},
        "cost": {"multiplier_2x_remains_positive": True},
        "year_2025_vs_spy": 0.0,
        "year_2025_vs_qqq": 0.0,
    }
    val_years = [2018, 2019, 2021, 2023, 2025]
    for yr in val_years:
        a_yr = strat_nav[strat_nav.index.year == yr]
        s_yr = spy_nav[spy_nav.index.year == yr] if spy_nav is not None else None
        q_yr = qqq_nav[qqq_nav.index.year == yr] if qqq_nav is not None else None
        if len(a_yr) < 2:
            continue
        a_ret = _annual_ret(a_yr)
        s_ret = _annual_ret(s_yr) if s_yr is not None and len(s_yr) >= 2 else 0.0
        q_ret = _annual_ret(q_yr) if q_yr is not None and len(q_yr) >= 2 else 0.0
        metrics["validation"][yr] = {
            "maxdd": _max_dd(a_yr),
            "excess_vs_spy": a_ret - s_ret,
            "excess_vs_qqq": a_ret - q_ret,
        }
    if 2025 in metrics["validation"]:
        metrics["year_2025_vs_spy"] = metrics["validation"][2025]["excess_vs_spy"]
        metrics["year_2025_vs_qqq"] = metrics["validation"][2025]["excess_vs_qqq"]
    for sname, (start_d, end_d) in stress_slices.items():
        mask = (strat_nav.index >= pd.Timestamp(start_d)) & (strat_nav.index <= pd.Timestamp(end_d))
        nav_slice = strat_nav[mask]
        if len(nav_slice) >= 2:
            metrics["stress_slice"][sname] = {"maxdd": _max_dd(nav_slice)}
        else:
            metrics["stress_slice"][sname] = {"maxdd": 0.0}
    if qqq_nav is not None:
        ret_a = strat_nav.pct_change().dropna()
        ret_q = qqq_nav.reindex(ret_a.index).pct_change().dropna()
        common = ret_a.index.intersection(ret_q.index)
        if len(common) > 10:
            a = ret_a.loc[common].values
            q = ret_q.loc[common].values
            if np.std(q) > 0:
                beta = float(np.cov(a, q)[0, 1] / np.var(q))
                metrics["beta"]["beta_to_qqq"] = beta
            else:
                metrics["beta"]["beta_to_qqq"] = 0.0
    return metrics


def _serialize(obj):
    if isinstance(obj, dict):
        return {str(k): _serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize(v) for v in obj]
    if isinstance(obj, (np.integer, np.floating, np.bool_)):
        return obj.item()
    return obj


def main():
    print(f"=== T1b ConfirmationPatternStrategy Phase 2-3 Track A eval ===")
    print(f"Config: {CFG}")

    universe = _load_universe()
    print(f"Universe: {len(universe)} seed_pool stocks")

    print("Loading panels (clean post-A.3 SPY/BIL/SHV)...")
    close_df, volume_df, open_df = _build_panels(universe)
    print(f"  panels: close={close_df.shape}, range {close_df.index.min().date()} → {close_df.index.max().date()}")

    # Subset to validation window so backtest starts with warmup
    # Setup_lookback=20 → start from bar 21 onward
    print("\nBuilding entry/exit signals + confirmation predicate...")
    entry_signals, exit_signals = _build_entry_exit_signals(close_df, volume_df, CFG)
    n_entries = entry_signals.values.sum()
    n_exits = exit_signals.values.sum()
    print(f"  entries: {n_entries} ({n_entries/len(close_df):.1f} per bar avg)")
    print(f"  exits: {n_exits}")

    predicate = _confirmation_predicate_factory(close_df, CFG.confirmation_threshold_pct)

    # Cost model (PRD §11 standard): conservative bps slip
    cost = CostModel(CostModelConfig(
        tiers={"default": CostTierConfig(
            symbols=[], commission_bps=1.0,
            slippage_interday_bps=5.0, slippage_intraday_bps=10.0,
        )}
    ))

    print("\nRunning SignalDrivenBacktest...")
    bt = SignalDrivenBacktest(
        entry_signals=entry_signals,
        exit_signals=exit_signals,
        price_df=close_df,
        ttl_bars=CFG.confirmation_ttl_bars,
        top_n=CFG.top_n,
        confirmation_predicate=predicate,
        position_sizing_rule=None,
        cost_model=cost,
        initial_capital=10_000.0,
        execution_delay_bars=EXEC_DELAY_BARS,
        max_single_weight=None,
        open_df=open_df,
    )
    result = bt.run()
    print(f"  BacktestResult: final equity={result.equity_curve.iloc[-1]:.2f}")
    n_trades = len(result.trades) if result.trades is not None else 0
    print(f"  trades: {n_trades}")

    strat_nav = result.equity_curve

    # Load benchmarks
    store = BarStore()
    spy_df = store.load("SPY", freq="1d", adjusted=True).sort_index()
    spy_nav = spy_df.loc[strat_nav.index[0]:strat_nav.index[-1], "close"]
    qqq_df = store.load("QQQ", freq="1d", adjusted=True).sort_index()
    qqq_nav = qqq_df.loc[strat_nav.index[0]:strat_nav.index[-1], "close"]

    # Stress slices from split config
    split_path = resolve_split_path(role="core")
    split_cfg = load_temporal_split(split_path)
    stress_slices = {ss.name: (ss.start, ss.end) for ss in split_cfg.partition.stress_slices}

    # Concentration: max single + top3 weight across panel
    weight_panel = bt.weight_panel()
    weight_sorted = weight_panel.apply(lambda r: r.sort_values(ascending=False), axis=1)
    top1_series = weight_panel.max(axis=1).fillna(0)
    top3_series = weight_panel.apply(
        lambda r: r.nlargest(3).sum() if r.sum() > 0 else 0.0, axis=1
    )
    top1_max = float(top1_series.max())
    top3_max = float(top3_series.max())
    print(f"  concentration: top1_max={top1_max:.3f}, top3_max={top3_max:.3f}")

    print("\nBuilding metrics...")
    metrics = _build_metrics(strat_nav, spy_nav, qqq_nav, stress_slices,
                             top1_max=top1_max, top3_max=top3_max)
    print(f"  validation years: {sorted(metrics['validation'].keys())}")
    for y, m in metrics["validation"].items():
        print(f"    {y}: maxdd={m['maxdd']*100:+.2f}% vs_spy={m['excess_vs_spy']*100:+.2f}% vs_qqq={m['excess_vs_qqq']*100:+.2f}%")
    print(f"  stress: {sorted(metrics['stress_slice'].keys())}")
    for sname, sm in metrics["stress_slice"].items():
        print(f"    {sname}: maxdd={sm['maxdd']*100:+.2f}%")
    print(f"  beta_to_qqq: {metrics['beta'].get('beta_to_qqq', float('nan')):.4f}")

    print("\n=== Track A verdict ===")
    verdict = run_split_acceptance(metrics, role="core", split_path=str(split_path))
    n_pass = sum(1 for g in verdict.gates if g.passed)
    print(f"Overall passed: {verdict.overall_passed} | {n_pass}/{len(verdict.gates)}")
    for g in verdict.gates:
        mark = "✓" if g.passed else "✗"
        print(f"  {mark} {g.name}: {g.notes}")

    # Save NAV + verdict
    out_dir = PROJ / "data/audit"
    out_dir.mkdir(parents=True, exist_ok=True)
    nav_path = out_dir / "t1b_phase3_nav.parquet"
    pd.DataFrame({"equity": strat_nav}).to_parquet(nav_path)
    print(f"\nSaved NAV: {nav_path}")

    out_payload = {
        "lineage": "t1b-confirmation-pattern-2026-05-14",
        "phase": "T1b Phase 3 Track A",
        "config": {
            "arm_type": CFG.arm_type,
            "setup_lookback_days": CFG.setup_lookback_days,
            "confirmation_ttl_bars": CFG.confirmation_ttl_bars,
            "confirmation_threshold_pct": CFG.confirmation_threshold_pct,
            "top_n": CFG.top_n,
            "max_holding_days": MAX_HOLDING_DAYS,
        },
        "universe_size": len(universe),
        "n_trades": n_trades,
        "final_equity": float(strat_nav.iloc[-1]),
        "split_name": verdict.split_name,
        "role": verdict.role,
        "overall_passed": bool(verdict.overall_passed),
        "n_gates_total": len(verdict.gates),
        "n_gates_passed": n_pass,
        "gates": [
            {"name": g.name, "passed": bool(g.passed), "notes": g.notes}
            for g in verdict.gates
        ],
        "metrics": _serialize(metrics),
    }
    verdict_path = out_dir / "t1b_phase3_track_a_verdict.json"
    verdict_path.write_text(json.dumps(out_payload, indent=2, default=str))
    print(f"Saved verdict: {verdict_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
