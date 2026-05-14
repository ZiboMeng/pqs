"""PEAD Path 1 SUE Track A 17-gate acceptance on top winner.

Spec (smoke v1 top trials):
  trial 1:  SUE≥1.5σ hold=21 top_n=10  Sharpe 1.055 MaxDD -7.64%
  trial 6:  SUE≥1.5σ hold=60 top_n=10  Sharpe 1.063 MaxDD -24.01%

Run both as candidates against 17-gate acceptance + 2x cost + NAV correlation
vs alt-A intraday reversal + T1b ConfirmationPattern + Trial 9 v2.

Cost: 30bp slip + 2bp commission baseline (cycle11+).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJ = Path("/home/zibo/Documents/projects/pqs")
if str(PROJ) not in sys.path:
    sys.path.insert(0, str(PROJ))

import numpy as np
import pandas as pd

from core.backtest.signal_driven_runner import SignalDrivenBacktest
from core.data.bar_store import BarStore
from core.data.edgar_provider import EdgarProvider
from core.execution.cost_model import CostModel
from core.config.schemas.cost_model import CostModelConfig, CostTierConfig
from core.research.temporal_split_acceptance import run_split_acceptance
from core.research.temporal_split import (
    load_temporal_split, resolve_split_path,
)
from core.research.pead.earnings_dates import extract_earnings_dates_panel
from core.research.pead.sue_calculator import compute_sue_panel, build_sue_signal_panel

from dev.scripts.pead._pead_smoke_common import load_universe, build_panels


COST_COMM_BPS = 2.0
COST_SLIP_INTER_BPS = 30.0
COST_SLIP_INTRA_BPS = 60.0


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


def _build_metrics(strat_nav, spy_nav, qqq_nav, stress_slices,
                   top1_max, top3_max, pos_at_2x):
    metrics = {
        "validation": {},
        "stress_slice": {},
        "concentration": {
            "top1_max": top1_max,
            "top3_max": top3_max,
            "leveraged_etf_dependency": False,
        },
        "beta": {},
        "cost": {"multiplier_2x_remains_positive": pos_at_2x},
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


def _run_one_candidate(sue_threshold, max_hold, top_n,
                        sue_panel, close_df, open_df, universe,
                        spy_nav, qqq_nav, stress_slices, label):
    print(f"\n{'='*72}")
    print(f"  Candidate: SUE≥{sue_threshold:.1f}σ hold={max_hold} top_n={top_n} ({label})")
    print(f"{'='*72}")

    entry = build_sue_signal_panel(
        sue_panel, sue_threshold=sue_threshold,
        price_index=close_df.index, universe=universe,
    )
    exit_ = entry.shift(max_hold).fillna(False).astype(bool)
    n_signals = int(entry.values.sum())
    print(f"  entries: {n_signals}")

    cost = CostModel(CostModelConfig(
        tiers={"default": CostTierConfig(
            symbols=[], commission_bps=COST_COMM_BPS,
            slippage_interday_bps=COST_SLIP_INTER_BPS,
            slippage_intraday_bps=COST_SLIP_INTRA_BPS,
        )}
    ))

    bt = SignalDrivenBacktest(
        entry_signals=entry, exit_signals=exit_,
        price_df=close_df, ttl_bars=0, top_n=top_n,
        cost_model=cost, initial_capital=10_000.0,
        execution_delay_bars=1, open_df=open_df,
    )
    result = bt.run()
    strat_nav = result.equity_curve
    n_trades = len(result.trades) if result.trades is not None else 0

    daily_ret = strat_nav.pct_change().dropna()
    sharpe = _annualized_sharpe(daily_ret)
    years = (strat_nav.index[-1] - strat_nav.index[0]).days / 365.25
    cagr = (strat_nav.iloc[-1] / strat_nav.iloc[0]) ** (1 / years) - 1 if years > 0 else 0
    full_dd = _max_dd(strat_nav)
    print(f"  Final equity: ${strat_nav.iloc[-1]:.0f}; Trades: {n_trades}")
    print(f"  Sharpe: {sharpe:+.3f}; CAGR: {cagr*100:+.2f}%; Full MaxDD: {full_dd*100:+.2f}%")

    # 2x cost check
    print("  2x cost check ...")
    cost_2x = CostModel(CostModelConfig(
        tiers={"default": CostTierConfig(
            symbols=[], commission_bps=COST_COMM_BPS * 2,
            slippage_interday_bps=COST_SLIP_INTER_BPS * 2,
            slippage_intraday_bps=COST_SLIP_INTRA_BPS * 2,
        )}
    ))
    bt2x = SignalDrivenBacktest(
        entry_signals=entry, exit_signals=exit_,
        price_df=close_df, ttl_bars=0, top_n=top_n,
        cost_model=cost_2x, initial_capital=10_000.0,
        execution_delay_bars=1, open_df=open_df,
    )
    result_2x = bt2x.run()
    final_2x = result_2x.equity_curve.iloc[-1]
    pos_at_2x = bool(final_2x > 10_000.0)
    print(f"    2x cost final: ${final_2x:.0f} → {'POSITIVE' if pos_at_2x else 'NEGATIVE'}")

    weight_panel = bt.weight_panel()
    top1_max = float(weight_panel.max(axis=1).max())
    top3_max = float(weight_panel.apply(
        lambda r: r.nlargest(3).sum() if r.sum() > 0 else 0.0, axis=1
    ).max())
    print(f"  Concentration: top1={top1_max:.3f}, top3={top3_max:.3f}")

    metrics = _build_metrics(strat_nav, spy_nav, qqq_nav, stress_slices,
                              top1_max, top3_max, pos_at_2x)

    print("\n  Validation years:")
    for y, m in metrics["validation"].items():
        print(f"    {y}: maxdd={m['maxdd']*100:+.2f}% "
              f"vs_spy={m['excess_vs_spy']*100:+.2f}% "
              f"vs_qqq={m['excess_vs_qqq']*100:+.2f}%")
    for sname, sm in metrics["stress_slice"].items():
        print(f"    stress {sname}: maxdd={sm['maxdd']*100:+.2f}%")
    print(f"  beta_to_qqq: {metrics['beta'].get('beta_to_qqq', float('nan')):+.4f}")

    split_path = resolve_split_path(role="core")
    print(f"\n  === Track A 17-gate verdict ===")
    verdict = run_split_acceptance(metrics, role="core", split_path=str(split_path))
    n_pass = sum(1 for g in verdict.gates if g.passed)
    print(f"  Overall passed: {verdict.overall_passed} | {n_pass}/{len(verdict.gates)}")
    for g in verdict.gates:
        mark = "✓" if g.passed else "✗"
        print(f"    {mark} {g.name}: {g.notes}")

    return {
        "label": label,
        "sue_threshold": sue_threshold,
        "max_hold": max_hold,
        "top_n": top_n,
        "performance": {
            "sharpe": sharpe,
            "cagr": float(cagr),
            "full_period_max_dd": float(full_dd),
            "final_equity": float(strat_nav.iloc[-1]),
            "n_trades": int(n_trades),
            "n_signals": int(n_signals),
            "cost_2x_remains_positive": pos_at_2x,
        },
        "track_a": {
            "overall_passed": bool(verdict.overall_passed),
            "n_gates_passed": n_pass,
            "n_gates_total": len(verdict.gates),
            "gates": [
                {"name": g.name, "passed": bool(g.passed), "notes": g.notes}
                for g in verdict.gates
            ],
        },
        "metrics": {str(k): v for k, v in metrics.items()},
        "strat_nav": strat_nav,
    }


def main():
    print("=== PEAD Path 1 SUE — Track A acceptance ===")

    universe = load_universe()
    close_df, open_df = build_panels(universe, add_benchmark=False)
    print(f"Universe: {len(universe)} stocks; panel: {close_df.shape}")

    edgar = EdgarProvider()
    earn = extract_earnings_dates_panel(universe, edgar_provider=edgar)
    sue = compute_sue_panel(earn)
    print(f"Earnings: {len(earn)}; SUE: {sue['sue'].notna().sum()} non-NaN")

    # SPY + QQQ benchmarks
    store = BarStore()
    spy_df = store.load("SPY", freq="1d", adjusted=True).sort_index()
    spy_nav = spy_df.loc[close_df.index[0]:close_df.index[-1], "close"]
    qqq_df = store.load("QQQ", freq="1d", adjusted=True).sort_index()
    qqq_nav = qqq_df.loc[close_df.index[0]:close_df.index[-1], "close"]

    split_path = resolve_split_path(role="core")
    split_cfg = load_temporal_split(split_path)
    stress_slices = {ss.name: (ss.start, ss.end) for ss in split_cfg.partition.stress_slices}

    candidates = [
        # (sue_threshold, max_hold, top_n, label)
        (1.5, 21, 10, "trial1_short_hold"),
        (1.5, 60, 10, "trial6_long_hold_top_sharpe"),
    ]

    results = []
    for thr, hold, n, label in candidates:
        r = _run_one_candidate(thr, hold, n, sue, close_df, open_df, universe,
                                spy_nav, qqq_nav, stress_slices, label)
        results.append(r)

    # NAV correlation vs anchors
    print(f"\n{'='*72}")
    print("=== Anti-sibling NAV correlation ===")
    print(f"{'='*72}")
    anchor_paths = {
        "alt_a": "data/audit/alt_a_phase3_nav.parquet",
        "t1b_confirmation": "data/audit/t1b_phase3_nav.parquet",
        "cycle11_donchian": "data/audit/cycle11_top_trial_nav.parquet",
    }
    for r in results:
        print(f"\n  Candidate: {r['label']}")
        strat_nav = r.pop("strat_nav")
        r["anti_sibling"] = {}
        for name, path in anchor_paths.items():
            full_path = PROJ / path
            if not full_path.exists():
                print(f"    {name}: NAV file not found")
                continue
            try:
                anchor_nav = pd.read_parquet(full_path)["equity"]
                common = strat_nav.index.intersection(anchor_nav.index)
                if len(common) < 100:
                    print(f"    {name}: insufficient overlap")
                    continue
                s = strat_nav.reindex(common).dropna()
                a = anchor_nav.reindex(common).dropna()
                common2 = s.index.intersection(a.index)
                s_ret = s.loc[common2].pct_change().dropna()
                a_ret = a.loc[common2].pct_change().dropna()
                cidx = s_ret.index.intersection(a_ret.index)
                raw_corr = float(np.corrcoef(s_ret.loc[cidx], a_ret.loc[cidx])[0, 1])
                nav_corr = float(np.corrcoef(s.loc[common2], a.loc[common2])[0, 1])
                v = "PASS" if raw_corr < 0.85 else "FAIL"
                print(f"    {name}: daily-return raw={raw_corr:+.4f} ({v}, threshold 0.85), "
                      f"NAV-level={nav_corr:+.4f}, n={len(cidx)}")
                r["anti_sibling"][name] = {
                    "daily_return_pearson": raw_corr,
                    "nav_level_pearson": nav_corr,
                    "n_overlap": len(cidx),
                    "verdict": v,
                }
            except Exception as e:
                print(f"    {name}: error {e}")

        # Save NAV per candidate
        out_dir = PROJ / "data/audit"
        nav_path = out_dir / f"pead_path1_{r['label']}_nav.parquet"
        pd.DataFrame({"equity": strat_nav}).to_parquet(nav_path)
        print(f"    Saved NAV: {nav_path}")

    # Save verdict
    out = PROJ / "data/audit/pead_path1_track_a_verdict.json"
    payload = {
        "lineage": "pead-bundle-2026-05-14",
        "candidates": results,
    }
    out.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\nSaved verdict: {out}")

    # Summary
    print(f"\n{'='*72}")
    print("=== Summary ===")
    print(f"{'='*72}")
    for r in results:
        passed = r["track_a"]["overall_passed"]
        n_p = r["track_a"]["n_gates_passed"]
        n_t = r["track_a"]["n_gates_total"]
        cost2x = r["performance"]["cost_2x_remains_positive"]
        max_nav_corr = max(
            (info["nav_level_pearson"] for info in r["anti_sibling"].values()),
            default=0.0,
        )
        print(f"  {r['label']}: Track A={passed} ({n_p}/{n_t}); "
              f"2x cost={cost2x}; max NAV corr={max_nav_corr:+.3f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
