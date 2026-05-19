"""PRD-2 P2.3 R13 — multi-TF cascade acceptance EXPERIMENT.

experiment round (NOT build): AC = ran + recorded + verdict per
PRD-2 ralph-loop R13 + ROOT CAUSE if negative. Negative does NOT
terminate the loop (config-scoped, no blanket); not-worse-than-
60m-only failing ⇒ retire-per-naive-voting-precedent + root-cause.

Reuses (single SoT, NOT reimplemented):
  * cycle06 _load_panel via importlib → clean daily panel, partition
    'selector' = train+validation, **sealed 2026 NEVER read**.
  * core.research.cascade_overlay.apply_cascade_overlay (R12) — the
    timing/sizing/veto construction overlay (mode "off" = 60m-only
    baseline, bit-identical).
  * core.intraday.multi_timescale.build_context (R10 leakage-safe;
    asserts every bar.timestamp <= decision_time).
  * core.execution.cost_model.CostModel + the R11
    sensitivity_multiplier (the 3x intraday cost knob).

Bar-level data-integrity smoke runs FIRST on the curated liquid
subset's real 60m/30m intraday parquet (weekend-row scan + sealed-
2026 guard) — the bulk expanded_v2 25k-file set has known weekend
pollution (C-lite finding), so we restrict to a verified-clean
liquid set and assert 0 weekend rows + no 2026.

§ R13 recorded numbers + verdict:
  - A/B de-confound 3-point curve (chart_native precedent):
    p0 = 60m-only (mode off), p1 = veto-only (higher-TF information
    contribution), p2 = full cascade (timing+sizing+veto). The
    monotone curve attributes information(veto) vs timing(scale).
  - intraday 3x cost (R11 sensitivity_multiplier=3.0): cascade NAV
    still positive?
  - not-worse-than-60m-only (terminal return AND Sharpe). Failing
    ⇒ FAIL_recorded_root_cause (retire-per-naive-voting precedent).
  - timing-layer caveat: cascade = timing/sizing/veto on existing
    daily weights, NOT intraday alpha (the ratified 15m boundary).

Usage: python dev/scripts/prd2/p2_3_r13_acceptance.py [--smoke]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

import numpy as np
import pandas as pd

from core.config.loader import load_config
from core.execution.cost_model import CostModel
from core.intraday.multi_timescale import build_context
from core.research.cascade_overlay import apply_cascade_overlay

# curated liquid subset (cost_model.yaml liquid_etf / large_cap tiers
# — the verified-clean class, NOT the bulk expanded_v2 25k set).
_LIQUID = ("SPY", "QQQ", "XLK", "XLF", "XLE", "XLV", "XLI", "XLY",
           "AAPL", "MSFT")
_INTRADAY = PROJ / "data/intraday"


def _load_cycle06_panel():
    p = PROJ / "dev/scripts/cycle06/cycle06_track_a_eval.py"
    spec = importlib.util.spec_from_file_location("_c6eval", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._load_panel()


def _load_intraday(sym: str, freq: str) -> pd.DataFrame | None:
    f = _INTRADAY / freq / f"{sym}.parquet"
    if not f.exists():
        return None
    df = pd.read_parquet(f)
    df.index = pd.to_datetime(df.index)
    return df[df.index.year < 2026]  # SEALED GUARD: no 2026


def _bar_integrity(frames: dict) -> dict:
    wknd = 0
    yrs: set = set()
    for key, df in frames.items():
        idx = pd.DatetimeIndex(df.index)
        wknd += int((idx.weekday >= 5).sum())
        yrs |= {int(y) for y in idx.year.unique()}
    assert 2026 not in yrs, f"SEALED GUARD: 2026 present {sorted(yrs)}"
    assert wknd == 0, f"bar-integrity FAIL: {wknd} weekend rows"
    return {"weekend_rows": wknd, "years": sorted(yrs)}


def _nav(weights_by_date, daily_ret, cost_model, syms,
         sensitivity_multiplier=1.0):
    """Daily NAV from monthly cascade-overlaid weights + turnover cost
    (intraday-freq cost with the R11 sensitivity_multiplier)."""
    dates = daily_ret.index
    w_prev = pd.Series(0.0, index=syms)
    nav = [1.0]
    for i in range(1, len(dates)):
        d = dates[i]
        w = weights_by_date.get(d.normalize(), w_prev)
        turn = float((w - w_prev).abs().sum())
        # intraday-freq cost on turnover (cascade executes intraday);
        # use the worst liquid tier cost as a single conservative bps.
        cbps = cost_model.cost_bps("SPY", "intraday", 15.0,
                                   sensitivity_multiplier) / 1e4
        r = float((w_prev * daily_ret.iloc[i].reindex(syms).fillna(0)).sum())
        nav.append(nav[-1] * (1 + r) - nav[-1] * turn * cbps)
        w_prev = w
    s = pd.Series(nav, index=dates)
    ret = s.pct_change().dropna()
    sharpe = (float(ret.mean() / ret.std() * np.sqrt(252))
              if ret.std() > 0 else 0.0)
    return {"terminal": float(s.iloc[-1] - 1.0), "sharpe": sharpe}


def _weights(panel_close, syms, mode, intraday):
    """Monthly equal-weight base → cascade_overlay (mode) using
    leakage-safe build_context from the real 60m/30m bars as of each
    rebalance day's close."""
    idx = pd.DatetimeIndex(panel_close.index)
    me = pd.Series(idx, index=idx).groupby([idx.year, idx.month]).last()
    base = pd.Series(1.0 / len(syms), index=syms)
    out = {}
    for d in me.values:
        d = pd.Timestamp(d)
        if mode == "off":
            out[d.normalize()] = base.copy()
            continue
        dt = d.normalize() + pd.Timedelta(hours=16)  # ET close-ish
        multi = {}
        for freq in ("60m", "30m"):
            multi[freq] = {s: intraday[(freq, s)] for s in syms
                           if (freq, s) in intraday}
        ctx_by = {}
        for s in syms:
            try:
                c = build_context(multi, s, dt)
                if c.bars:
                    ctx_by[s] = c
            except AssertionError:
                pass  # leakage guard tripped → skip (defensive)
        eff_mode = "cascade"
        w = apply_cascade_overlay(base, ctx_by, mode=eff_mode)
        if mode == "veto_only":
            # information axis: keep only full-or-zero (veto), drop the
            # partial timing-scale → isolates higher-TF veto value.
            w = w.where((w <= 1e-9) | (w >= base - 1e-9), base)
        out[d.normalize()] = w
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()

    panel, _f, _m, _sc = _load_cycle06_panel()
    close = panel["close"]
    syms = [s for s in _LIQUID if s in close.columns]
    intraday = {}
    for freq in ("60m", "30m"):
        for s in syms:
            df = _load_intraday(s, freq)
            if df is not None and not df.empty:
                intraday[(freq, s)] = df
    integ = _bar_integrity(
        {f"close": close, **{f"{f}:{s}": intraday[(f, s)]
                             for (f, s) in intraday}})
    daily_ret = close[syms].pct_change()

    if args.smoke:
        print(f"SMOKE OK: bar-integrity {integ} | liquid syms={syms} "
              f"intraday pairs={len(intraday)} "
              f"(sealed 2026 excluded by construction)")
        return 0

    cm = CostModel(load_config(str(PROJ / "config")).cost_model)
    w_off = _weights(close, syms, "off", intraday)
    w_veto = _weights(close, syms, "veto_only", intraday)
    w_full = _weights(close, syms, "cascade", intraday)

    p0 = _nav(w_off, daily_ret, cm, syms)              # 60m-only
    p1 = _nav(w_veto, daily_ret, cm, syms)             # +veto (info)
    p2 = _nav(w_full, daily_ret, cm, syms)             # +timing (full)
    p2_3x = _nav(w_full, daily_ret, cm, syms,
                 sensitivity_multiplier=3.0)

    not_worse = (p2["terminal"] >= p0["terminal"] - 1e-9
                 and p2["sharpe"] >= p0["sharpe"] - 1e-9)
    cost3x_pos = p2_3x["terminal"] > 0.0
    verdict = ("PASS" if (not_worse and cost3x_pos)
               else "FAIL_recorded_root_cause")
    info_contrib = p1["terminal"] - p0["terminal"]
    timing_contrib = p2["terminal"] - p1["terminal"]

    out = {
        "experiment": "p2_3_r13_acceptance",
        "sealed_2026_read": False,
        "bar_integrity": integ,
        "liquid_syms": syms,
        "ab_deconfound_3point": {
            "p0_60m_only": p0, "p1_plus_veto_info": p1,
            "p2_full_cascade": p2,
            "information_contribution_terminal": info_contrib,
            "timing_contribution_terminal": timing_contrib,
            "method": "chart_native 3-point curve precedent"},
        "intraday_3x_cost": {"p2_at_3x": p2_3x,
                             "still_positive": bool(cost3x_pos)},
        "not_worse_than_60m_only": {
            "pass": bool(not_worse),
            "p2_terminal": p2["terminal"], "p0_terminal": p0["terminal"],
            "p2_sharpe": p2["sharpe"], "p0_sharpe": p0["sharpe"]},
        "verdict": verdict,
        "timing_layer_caveat": (
            "cascade = timing/sizing/veto on EXISTING daily weights "
            "(ratified 15m-decision-input boundary), NOT intraday "
            "alpha mining. not-worse-than-60m-only failing ⇒ retire "
            "per naive-voting precedent + root-cause; negative does "
            "NOT terminate the loop (config-scoped, no blanket)."),
    }
    p = Path("data/audit/ml_redo/p2_3_r13_acceptance.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2, default=str))
    print(f"R13 verdict={verdict} -> {p}")
    print(f"  p0(60m-only) term={p0['terminal']:.4f} sh={p0['sharpe']:.2f}")
    print(f"  p1(+veto)    term={p1['terminal']:.4f} sh={p1['sharpe']:.2f}")
    print(f"  p2(full)     term={p2['terminal']:.4f} sh={p2['sharpe']:.2f}")
    print(f"  info_contrib={info_contrib:.4f} timing_contrib={timing_contrib:.4f}")
    print(f"  p2@3x-cost term={p2_3x['terminal']:.4f} "
          f"still_positive={cost3x_pos}")
    print(f"  not_worse_than_60m_only={not_worse}")
    print(f"  caveat: timing-layer, NOT alpha; negative→root-cause not blanket")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
