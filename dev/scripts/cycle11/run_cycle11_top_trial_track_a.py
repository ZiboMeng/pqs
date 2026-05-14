"""cycle11 Donchian-20 hold=21 spot-check — Track A 17-gate + NAV correlation.

Reuses pattern from dev/scripts/t1b/run_t1b_track_a_eval.py but with
Donchian-20 hold=21 entry/exit logic (the cycle11 smoke v2 top winner).

Cost: 30bp slippage + 2bp commission baseline (cost gate 6x revision).
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

from core.backtest.backtest_engine import BacktestResult
from core.backtest.signal_driven_runner import SignalDrivenBacktest
from core.data.bar_store import BarStore
from core.execution.cost_model import CostModel
from core.config.schemas.cost_model import CostModelConfig, CostTierConfig
from core.research.temporal_split_acceptance import run_split_acceptance
from core.research.temporal_split import (
    load_temporal_split, resolve_split_path,
)


# Spec: Donchian-20 hold=21 (smoke v2 #1)
LOOKBACK = 20
MAX_HOLD = 21
TOP_N = 5
EXEC_DELAY = 1
COST_COMM_BPS = 2.0
COST_SLIP_INTER_BPS = 30.0
COST_SLIP_INTRA_BPS = 60.0


def _load_universe():
    import yaml
    with open(PROJ / "config/universe.yaml") as f:
        u = yaml.safe_load(f)
    return sorted([s for s in u.get("seed_pool", [])
                   if s not in ("SPY", "QQQ", "GLD", "TQQQ", "SOXL", "SQQQ", "SOXS")])


def _build_panel(symbols, start="2017-01-02", end="2025-12-31"):
    store = BarStore()
    closes = {}
    opens = {}
    for sym in symbols:
        try:
            df = store.load(sym, freq="1d", adjusted=True).sort_index()
            df = df[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))]
            if not df.empty:
                closes[sym] = df["close"]
                if "open" in df.columns:
                    opens[sym] = df["open"]
        except Exception:
            continue
    close_df = pd.DataFrame(closes).sort_index()
    open_df = pd.DataFrame(opens).reindex(index=close_df.index, columns=close_df.columns)
    return close_df, open_df


def _max_dd(nav: pd.Series) -> float:
    if len(nav) < 2:
        return 0.0
    peak = nav.cummax()
    return float(((nav - peak) / peak.replace(0, np.nan)).min())


def _annual_ret(nav: pd.Series) -> float:
    if len(nav) < 2:
        return 0.0
    return float((nav.iloc[-1] - nav.iloc[0]) / nav.iloc[0])


def _annualized_sharpe(returns: pd.Series) -> float:
    if returns.std() == 0 or len(returns) < 2:
        return 0.0
    return float(returns.mean() / returns.std() * np.sqrt(252))


def _build_metrics(strat_nav, spy_nav, qqq_nav, stress_slices, top1_max, top3_max, n_held):
    metrics = {
        "validation": {},
        "stress_slice": {},
        "concentration": {
            "top1_max": top1_max,
            "top3_max": top3_max,
            "leveraged_etf_dependency": False,
        },
        "beta": {},
        "cost": {"multiplier_2x_remains_positive": True},  # placeholder, will verify
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
    for sname, (sd, ed) in stress_slices.items():
        mask = (strat_nav.index >= pd.Timestamp(sd)) & (strat_nav.index <= pd.Timestamp(ed))
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
                metrics["beta"]["beta_to_qqq"] = float(np.cov(a, q)[0, 1] / np.var(q))
            else:
                metrics["beta"]["beta_to_qqq"] = 0.0
    return metrics


def main():
    print(f"=== cycle11 Donchian-{LOOKBACK} hold={MAX_HOLD} Track A spot-check ===")
    print(f"Cost: {COST_COMM_BPS}bp commission + {COST_SLIP_INTER_BPS}bp slippage (interday)")

    universe = _load_universe()
    print(f"Universe: {len(universe)} stocks")

    close_df, open_df = _build_panel(universe)
    print(f"Panel: {close_df.shape}, range {close_df.index.min().date()} → {close_df.index.max().date()}")

    # Donchian-20 breakout signal
    rolling_max = close_df.rolling(LOOKBACK, min_periods=LOOKBACK).max().shift(1)
    entry = (close_df > rolling_max).fillna(False)
    exit_ = entry.shift(MAX_HOLD).fillna(False)
    print(f"  entries: {int(entry.values.sum())}")

    cost = CostModel(CostModelConfig(
        tiers={"default": CostTierConfig(
            symbols=[], commission_bps=COST_COMM_BPS,
            slippage_interday_bps=COST_SLIP_INTER_BPS,
            slippage_intraday_bps=COST_SLIP_INTRA_BPS,
        )}
    ))

    print("\nRunning SignalDrivenBacktest...")
    bt = SignalDrivenBacktest(
        entry_signals=entry, exit_signals=exit_,
        price_df=close_df, ttl_bars=0, top_n=TOP_N,
        cost_model=cost, initial_capital=10_000.0,
        execution_delay_bars=EXEC_DELAY,
        open_df=open_df,
    )
    result = bt.run()
    strat_nav = result.equity_curve
    n_trades = len(result.trades) if result.trades is not None else 0
    print(f"  Final equity: ${strat_nav.iloc[-1]:.0f}")
    print(f"  Trades: {n_trades}")

    daily_ret = strat_nav.pct_change().dropna()
    sharpe = _annualized_sharpe(daily_ret)
    years = (strat_nav.index[-1] - strat_nav.index[0]).days / 365.25
    cagr = (strat_nav.iloc[-1] / strat_nav.iloc[0]) ** (1/years) - 1 if years > 0 else 0
    full_dd = _max_dd(strat_nav)
    print(f"  Sharpe: {sharpe:+.3f}")
    print(f"  CAGR: {cagr*100:+.2f}%")
    print(f"  Full-period MaxDD: {full_dd*100:+.2f}%")

    # Verify cost robustness 2x
    print("\nCost robustness 2x check...")
    cost_2x = CostModel(CostModelConfig(
        tiers={"default": CostTierConfig(
            symbols=[], commission_bps=COST_COMM_BPS * 2,
            slippage_interday_bps=COST_SLIP_INTER_BPS * 2,
            slippage_intraday_bps=COST_SLIP_INTRA_BPS * 2,
        )}
    ))
    bt2x = SignalDrivenBacktest(
        entry_signals=entry, exit_signals=exit_,
        price_df=close_df, ttl_bars=0, top_n=TOP_N,
        cost_model=cost_2x, initial_capital=10_000.0,
        execution_delay_bars=EXEC_DELAY,
        open_df=open_df,
    )
    result_2x = bt2x.run()
    final_2x = result_2x.equity_curve.iloc[-1]
    pos_at_2x = final_2x > 10_000.0
    print(f"  2x cost final equity: ${final_2x:.0f} -> {'POSITIVE' if pos_at_2x else 'NEGATIVE'}")

    # Benchmarks
    store = BarStore()
    spy_df = store.load("SPY", freq="1d", adjusted=True).sort_index()
    spy_nav = spy_df.loc[strat_nav.index[0]:strat_nav.index[-1], "close"]
    qqq_df = store.load("QQQ", freq="1d", adjusted=True).sort_index()
    qqq_nav = qqq_df.loc[strat_nav.index[0]:strat_nav.index[-1], "close"]

    split_path = resolve_split_path(role="core")
    split_cfg = load_temporal_split(split_path)
    stress_slices = {ss.name: (ss.start, ss.end) for ss in split_cfg.partition.stress_slices}

    weight_panel = bt.weight_panel()
    top1_max = float(weight_panel.max(axis=1).max())
    top3_max = float(weight_panel.apply(
        lambda r: r.nlargest(3).sum() if r.sum() > 0 else 0.0, axis=1
    ).max())
    print(f"\n  concentration: top1={top1_max:.3f}, top3={top3_max:.3f}")

    metrics = _build_metrics(
        strat_nav, spy_nav, qqq_nav, stress_slices,
        top1_max, top3_max, n_held=TOP_N,
    )
    metrics["cost"]["multiplier_2x_remains_positive"] = bool(pos_at_2x)

    print(f"\n  Validation years:")
    for y, m in metrics["validation"].items():
        print(f"    {y}: maxdd={m['maxdd']*100:+.2f}% vs_spy={m['excess_vs_spy']*100:+.2f}% vs_qqq={m['excess_vs_qqq']*100:+.2f}%")
    for sname, sm in metrics["stress_slice"].items():
        print(f"    stress {sname}: maxdd={sm['maxdd']*100:+.2f}%")
    print(f"  beta_to_qqq: {metrics['beta'].get('beta_to_qqq', float('nan')):+.4f}")

    print(f"\n=== Track A 17-gate verdict ===")
    verdict = run_split_acceptance(metrics, role="core", split_path=str(split_path))
    n_pass = sum(1 for g in verdict.gates if g.passed)
    print(f"Overall passed: {verdict.overall_passed} | {n_pass}/{len(verdict.gates)}")
    for g in verdict.gates:
        mark = "✓" if g.passed else "✗"
        print(f"  {mark} {g.name}: {g.notes}")

    # Anti-sibling NAV correlation
    print(f"\n=== Anti-sibling NAV correlation ===")
    anti_sib_results = {}
    anchor_paths = {
        "alt_a": "data/audit/alt_a_phase3_nav.parquet",
        "t1b_confirmation": "data/audit/t1b_phase3_nav.parquet",
    }
    for name, path in anchor_paths.items():
        try:
            anchor_nav = pd.read_parquet(PROJ / path)["equity"]
            common = strat_nav.index.intersection(anchor_nav.index)
            if len(common) < 100:
                print(f"  {name}: insufficient overlap ({len(common)} bars), skipping")
                continue
            s = strat_nav.reindex(common).dropna()
            a = anchor_nav.reindex(common).dropna()
            common2 = s.index.intersection(a.index)
            s_ret = s.loc[common2].pct_change().dropna()
            a_ret = a.loc[common2].pct_change().dropna()
            cidx = s_ret.index.intersection(a_ret.index)
            raw_corr = float(np.corrcoef(s_ret.loc[cidx], a_ret.loc[cidx])[0, 1])
            nav_corr = float(np.corrcoef(s.loc[common2], a.loc[common2])[0, 1])
            verdict_ok = "PASS" if raw_corr < 0.85 else "FAIL"
            print(f"  {name}: daily-return raw={raw_corr:+.4f} ({verdict_ok}, threshold 0.85)")
            print(f"  {name}: NAV-level raw={nav_corr:+.4f}")
            anti_sib_results[name] = {
                "daily_return_pearson": raw_corr,
                "nav_level_pearson": nav_corr,
                "n_overlap": len(cidx),
                "verdict": verdict_ok,
            }
        except FileNotFoundError:
            print(f"  {name}: NAV file not found ({path})")

    # Save artifacts
    out_dir = PROJ / "data/audit"
    nav_path = out_dir / "cycle11_top_trial_nav.parquet"
    pd.DataFrame({"equity": strat_nav}).to_parquet(nav_path)
    print(f"\nSaved NAV: {nav_path}")

    payload = {
        "lineage": "track-c-cycle-2026-05-14-11-signal-driven-top-trial",
        "spec": {
            "seed": "donchian",
            "lookback": LOOKBACK,
            "max_hold": MAX_HOLD,
            "top_n": TOP_N,
            "execution_delay_bars": EXEC_DELAY,
            "cost_commission_bps": COST_COMM_BPS,
            "cost_slippage_interday_bps": COST_SLIP_INTER_BPS,
        },
        "performance": {
            "sharpe": sharpe,
            "cagr": float(cagr),
            "full_period_max_dd": float(full_dd),
            "final_equity": float(strat_nav.iloc[-1]),
            "n_trades": n_trades,
            "cost_2x_remains_positive": bool(pos_at_2x),
        },
        "track_a": {
            "split_name": verdict.split_name,
            "role": verdict.role,
            "overall_passed": bool(verdict.overall_passed),
            "n_gates_total": len(verdict.gates),
            "n_gates_passed": n_pass,
            "gates": [
                {"name": g.name, "passed": bool(g.passed), "notes": g.notes}
                for g in verdict.gates
            ],
        },
        "anti_sibling": anti_sib_results,
        "metrics": {str(k): v for k, v in metrics.items()},
    }
    verdict_path = out_dir / "cycle11_top_trial_track_a_verdict.json"
    verdict_path.write_text(json.dumps(payload, indent=2, default=str))
    print(f"Saved verdict: {verdict_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
