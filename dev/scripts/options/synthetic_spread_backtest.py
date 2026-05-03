"""Synthetic spread backtest: baseline (mechanical) vs signal-driven on SPY.

Phase 1.5b + Phase 2.1 of `pqs-options-v1-2026-05-02`. Two backtests:

(1) BASELINE — mechanical monthly entry, no market-state signal:
    - 3 separate runs, one per spread structure (bull put / bear call / iron condor)
    - Each run sells the SAME structure every month, regardless of trend
    - This isolates "pure VRP harvest with defined risk" baseline

(2) SIGNAL-DRIVEN — trend-filter selects structure each month:
    - Stock signal: SPY 200d MA + 20d momentum
    - Mapping:
        bull regime  (SPY > 200d MA AND 20d mom > 0) → bull put spread
        bear regime  (SPY < 200d MA AND 20d mom < 0) → bear call spread
        mixed/range  (signals disagree)              → iron condor
        VIX >= 40                                    → no trade
    - Same overlay (PRD §2 spread-adapted) on all entries

Reports headline metrics + tail-period segments for each run.

Outputs:
  data/options/backtest/spread_baseline_<structure>_nav.parquet (gitignored)
  data/options/backtest/spread_signal_driven_nav.parquet         (gitignored)
  data/options/analysis/spread_backtest_summary.json             (committable)
  stdout: markdown digest
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

from core.options.strategies.spreads import (  # noqa: E402
    BullPutSpread, BearCallSpread, IronCondor,
    bull_put_spread_metrics, bear_call_spread_metrics, iron_condor_metrics,
    bull_put_spread_mtm, bear_call_spread_mtm, iron_condor_mtm,
    bull_put_spread_expiry_payoff, bear_call_spread_expiry_payoff,
    iron_condor_expiry_payoff,
)

SNAP_DIR = PROJ / "data" / "options" / "snapshots"
ANAL_DIR = PROJ / "data" / "options" / "analysis"
BT_DIR = PROJ / "data" / "options" / "backtest"

# --- Strategy constants ---
INITIAL_NAV = 10_000.0
DTE_OPEN_DAYS = 21               # trading days ≈ 30 calendar days
SHORT_OTM_PCT = 0.05             # short leg 5% OTM
WIDTH_PCT = 0.01                 # spread width = 1% of spot
RISK_FREE_RATE = 0.045
IV_HAIRCUT_VOL_PTS = 0.10
RISK_PER_TRADE_PCT = 0.02        # max loss per trade ≤ 2% of NAV

# Tail-risk overlay (PRD §2 spread-adapted)
VIX_HALT_HARD = 40.0
EARLY_TP_FRAC = 0.50             # close at 50% of max profit
STOP_LOSS_FRAC = 0.80            # close at 80% of max loss
TIME_STOP_DTE = 7
DD_HALT_PCT = 0.10
DD_HALT_WINDOW = 21

# Signal params
TREND_MA_DAYS = 200
MOMENTUM_DAYS = 20


@dataclass
class SpreadPosition:
    structure: str                # "bull_put" | "bear_call" | "iron_condor"
    open_date: pd.Timestamp
    expiry_date: pd.Timestamp
    spot_at_open: float
    iv_at_open: float
    credit_per_share: float
    max_loss_per_share: float
    width_per_share: float
    contracts: float              # fractional bookkeeping
    cash_collateral: float        # contracts * max_loss * 100
    # Strike storage (set per structure):
    k_short_put: float | None = None
    k_long_put: float | None = None
    k_short_call: float | None = None
    k_long_call: float | None = None
    # Exit:
    is_open: bool = True
    close_date: pd.Timestamp | None = None
    close_pnl: float = 0.0
    close_reason: str = ""


@dataclass
class State:
    nav: float = INITIAL_NAV
    cash: float = INITIAL_NAV
    collateral: float = 0.0
    positions: list[SpreadPosition] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)


def _load_data() -> pd.DataFrame:
    if not (SNAP_DIR / "vix_history.parquet").exists():
        raise FileNotFoundError("Run vix_rv_gap_analysis.py first")
    vix = pd.read_parquet(SNAP_DIR / "vix_history.parquet")["close"].rename("vix")
    spy = pd.read_parquet(SNAP_DIR / "spy_history.parquet")["close"].rename("spy")
    df = pd.concat([vix, spy], axis=1, join="inner").dropna()
    df["iv"] = ((df["vix"] - IV_HAIRCUT_VOL_PTS) / 100.0).clip(lower=0.05)
    df["spy_ma200"] = df["spy"].rolling(TREND_MA_DAYS, min_periods=TREND_MA_DAYS).mean()
    df["spy_mom20"] = df["spy"].pct_change(MOMENTUM_DAYS)
    df["regime"] = "warmup"
    bull = (df["spy"] > df["spy_ma200"]) & (df["spy_mom20"] > 0)
    bear = (df["spy"] < df["spy_ma200"]) & (df["spy_mom20"] < 0)
    df.loc[bull, "regime"] = "bull"
    df.loc[bear, "regime"] = "bear"
    df.loc[~(bull | bear) & df["spy_ma200"].notna(), "regime"] = "mixed"
    return df


def _is_last_bday_of_month(idx: pd.DatetimeIndex, i: int) -> bool:
    if i + 1 >= len(idx):
        return True
    return idx[i].month != idx[i + 1].month


def _open_spread(
    state: State, structure: str,
    today: pd.Timestamp, spot: float, iv: float,
    panel_index: pd.DatetimeIndex, today_loc: int,
) -> SpreadPosition | None:
    expiry_loc = min(today_loc + DTE_OPEN_DAYS, len(panel_index) - 1)
    expiry_date = panel_index[expiry_loc]
    t_years = (expiry_date - today).days / 365.0
    if t_years <= 0:
        return None
    width = spot * WIDTH_PCT

    if structure == "bull_put":
        k_short_put = spot * (1.0 - SHORT_OTM_PCT)
        k_long_put = k_short_put - width
        spread = BullPutSpread(
            spot_at_open=spot, k_short_put=k_short_put, k_long_put=k_long_put,
            t_years=t_years, sigma=iv, r=RISK_FREE_RATE,
        )
        m = bull_put_spread_metrics(spread)
        ks = dict(k_short_put=k_short_put, k_long_put=k_long_put)
    elif structure == "bear_call":
        k_short_call = spot * (1.0 + SHORT_OTM_PCT)
        k_long_call = k_short_call + width
        spread = BearCallSpread(
            spot_at_open=spot, k_short_call=k_short_call, k_long_call=k_long_call,
            t_years=t_years, sigma=iv, r=RISK_FREE_RATE,
        )
        m = bear_call_spread_metrics(spread)
        ks = dict(k_short_call=k_short_call, k_long_call=k_long_call)
    elif structure == "iron_condor":
        k_short_put = spot * (1.0 - SHORT_OTM_PCT)
        k_long_put = k_short_put - width
        k_short_call = spot * (1.0 + SHORT_OTM_PCT)
        k_long_call = k_short_call + width
        spread = IronCondor(
            spot_at_open=spot, k_long_put=k_long_put, k_short_put=k_short_put,
            k_short_call=k_short_call, k_long_call=k_long_call,
            t_years=t_years, sigma=iv, r=RISK_FREE_RATE,
        )
        m = iron_condor_metrics(spread)
        ks = dict(k_short_put=k_short_put, k_long_put=k_long_put,
                  k_short_call=k_short_call, k_long_call=k_long_call)
    else:
        raise ValueError(f"unknown structure: {structure}")

    if m.max_loss_per_share <= 0:
        return None
    risk_dollars = state.nav * RISK_PER_TRADE_PCT
    contracts = risk_dollars / (m.max_loss_per_share * 100.0)
    if contracts < 1e-6:
        return None
    cash_coll = contracts * m.max_loss_per_share * 100.0
    if cash_coll > state.cash:
        return None

    state.cash -= cash_coll
    state.collateral += cash_coll
    state.cash += m.net_credit_per_share * 100.0 * contracts

    return SpreadPosition(
        structure=structure, open_date=today, expiry_date=expiry_date,
        spot_at_open=spot, iv_at_open=iv,
        credit_per_share=m.net_credit_per_share,
        max_loss_per_share=m.max_loss_per_share,
        width_per_share=m.width_per_share,
        contracts=contracts, cash_collateral=cash_coll, **ks,
    )


def _mtm_per_share(pos: SpreadPosition, spot: float, iv: float, t_years: float) -> float:
    if pos.structure == "bull_put":
        s = BullPutSpread(spot_at_open=pos.spot_at_open, k_short_put=pos.k_short_put,
                          k_long_put=pos.k_long_put, t_years=pos.expiry_date.day,
                          sigma=pos.iv_at_open, r=RISK_FREE_RATE)
        return bull_put_spread_mtm(s, spot, iv, t_years, RISK_FREE_RATE)
    if pos.structure == "bear_call":
        s = BearCallSpread(spot_at_open=pos.spot_at_open, k_short_call=pos.k_short_call,
                           k_long_call=pos.k_long_call, t_years=pos.expiry_date.day,
                           sigma=pos.iv_at_open, r=RISK_FREE_RATE)
        return bear_call_spread_mtm(s, spot, iv, t_years, RISK_FREE_RATE)
    if pos.structure == "iron_condor":
        s = IronCondor(spot_at_open=pos.spot_at_open,
                       k_long_put=pos.k_long_put, k_short_put=pos.k_short_put,
                       k_short_call=pos.k_short_call, k_long_call=pos.k_long_call,
                       t_years=pos.expiry_date.day, sigma=pos.iv_at_open, r=RISK_FREE_RATE)
        return iron_condor_mtm(s, spot, iv, t_years, RISK_FREE_RATE)
    raise ValueError(pos.structure)


def _expiry_payoff_per_share(pos: SpreadPosition, spot_expiry: float) -> float:
    if pos.structure == "bull_put":
        return bull_put_spread_expiry_payoff(pos.k_short_put, pos.k_long_put, spot_expiry)
    if pos.structure == "bear_call":
        return bear_call_spread_expiry_payoff(pos.k_short_call, pos.k_long_call, spot_expiry)
    if pos.structure == "iron_condor":
        return iron_condor_expiry_payoff(
            pos.k_long_put, pos.k_short_put, pos.k_short_call, pos.k_long_call, spot_expiry,
        )
    raise ValueError(pos.structure)


def _close_position(state: State, pos: SpreadPosition, today: pd.Timestamp,
                    cost_to_close_per_share: float, reason: str) -> None:
    pnl_per_share = pos.credit_per_share - cost_to_close_per_share
    pnl_total = pnl_per_share * 100.0 * pos.contracts
    state.cash -= cost_to_close_per_share * 100.0 * pos.contracts
    state.cash += pos.cash_collateral
    state.collateral -= pos.cash_collateral
    pos.is_open = False
    pos.close_date = today
    pos.close_pnl = pnl_total
    pos.close_reason = reason


def _expire_position(state: State, pos: SpreadPosition,
                     today: pd.Timestamp, spot_expiry: float) -> None:
    payoff = _expiry_payoff_per_share(pos, spot_expiry)
    pnl_per_share = pos.credit_per_share - payoff
    pnl_total = pnl_per_share * 100.0 * pos.contracts
    state.cash -= payoff * 100.0 * pos.contracts
    state.cash += pos.cash_collateral
    state.collateral -= pos.cash_collateral
    pos.is_open = False
    pos.close_date = today
    pos.close_pnl = pnl_total
    pos.close_reason = (
        "expiry_full_loss" if payoff >= pos.width_per_share - 1e-6
        else "expiry_partial_loss" if payoff > 0
        else "expiry_worthless"
    )


def run_backtest(df: pd.DataFrame, *, mode: str) -> tuple[pd.DataFrame, list[SpreadPosition]]:
    """mode ∈ {'baseline:bull_put', 'baseline:bear_call', 'baseline:iron_condor',
              'signal_driven'}."""
    state = State()
    panel_index = df.index
    nav_window: list[float] = []

    for i, today in enumerate(panel_index):
        spot = float(df["spy"].iat[i])
        vix = float(df["vix"].iat[i])
        iv = float(df["iv"].iat[i])
        regime = str(df["regime"].iat[i])

        # 1) Mark + manage open positions
        for pos in state.positions:
            if not pos.is_open:
                continue
            dte = (pos.expiry_date - today).days
            if dte <= 0:
                _expire_position(state, pos, today, spot)
                continue
            t_years = max(dte / 365.0, 1e-6)
            mtm = _mtm_per_share(pos, spot, iv, t_years)
            unrealized_pnl = pos.credit_per_share - mtm  # per share
            # Stop loss (close at 80% of max loss = -0.8 * max_loss in P&L)
            if unrealized_pnl <= -STOP_LOSS_FRAC * pos.max_loss_per_share:
                _close_position(state, pos, today, mtm, "stop_loss")
                continue
            # Profit target (50% of max profit = 50% of credit)
            if unrealized_pnl >= EARLY_TP_FRAC * pos.credit_per_share:
                _close_position(state, pos, today, mtm, "early_tp")
                continue
            # Time stop
            if dte <= TIME_STOP_DTE:
                _close_position(state, pos, today, mtm, "time_stop")
                continue

        # 2) NAV mark
        unrealized = 0.0
        for pos in state.positions:
            if pos.is_open:
                dte = (pos.expiry_date - today).days
                t_years = max(dte / 365.0, 1e-6)
                mtm = _mtm_per_share(pos, spot, iv, t_years)
                unrealized += (pos.credit_per_share - mtm) * 100.0 * pos.contracts
        nav_today = state.cash + state.collateral + unrealized
        state.nav = nav_today
        nav_window.append(nav_today)
        if len(nav_window) > DD_HALT_WINDOW:
            nav_window.pop(0)
        rolling_dd = (max(nav_window) - nav_today) / max(nav_window)

        # 3) Decide entry
        opened = False
        chosen_struct = None
        if _is_last_bday_of_month(panel_index, i):
            already_open = any(p.is_open for p in state.positions)
            if not already_open and vix < VIX_HALT_HARD and rolling_dd <= DD_HALT_PCT:
                if mode.startswith("baseline:"):
                    chosen_struct = mode.split(":", 1)[1]
                elif mode == "signal_driven":
                    if regime == "bull":
                        chosen_struct = "bull_put"
                    elif regime == "bear":
                        chosen_struct = "bear_call"
                    elif regime == "mixed":
                        chosen_struct = "iron_condor"
                    else:
                        chosen_struct = None  # warmup
                if chosen_struct is not None:
                    pos = _open_spread(state, chosen_struct, today, spot, iv,
                                       panel_index, i)
                    if pos is not None:
                        state.positions.append(pos)
                        opened = True

        state.history.append({
            "date": today, "nav": nav_today, "spy": spot, "vix": vix,
            "regime": regime, "rolling_dd": rolling_dd,
            "opened_today": opened, "chosen_struct": chosen_struct or "",
        })

    return pd.DataFrame(state.history).set_index("date"), state.positions


def _segment(nav: pd.Series, start: str, end: str) -> dict:
    sub = nav.loc[start:end]
    if sub.empty:
        return {"window": [start, end], "n": 0}
    cum = sub.iloc[-1] / sub.iloc[0] - 1.0
    rmax = sub.cummax()
    dd = (sub - rmax) / rmax
    return {"window": [start, end], "n": int(len(sub)),
            "cum_return": float(cum), "max_dd": float(dd.min())}


def _summarize(nav_df: pd.DataFrame, positions: list[SpreadPosition], label: str) -> dict:
    nav = nav_df["nav"]
    daily_ret = nav.pct_change().dropna()
    n_years = len(nav) / 252.0
    cum = nav.iloc[-1] / nav.iloc[0] - 1.0
    cagr = (nav.iloc[-1] / nav.iloc[0]) ** (1 / n_years) - 1.0 if n_years > 0 else 0.0
    sharpe = float(daily_ret.mean() / daily_ret.std() * np.sqrt(252)) if daily_ret.std() > 0 else 0.0
    rmax = nav.cummax()
    max_dd = float(((nav - rmax) / rmax).min())
    closed = [p for p in positions if not p.is_open]
    pnl_total = float(sum(p.close_pnl for p in closed))
    by_reason = pd.Series([p.close_reason for p in closed]).value_counts().to_dict()
    by_struct = pd.Series([p.structure for p in closed]).value_counts().to_dict()
    win_rate = sum(1 for p in closed if p.close_pnl > 0) / max(len(closed), 1)

    tails = {
        "gfc_2008":         _segment(nav, "2008-09-01", "2009-03-31"),
        "volmageddon_2018": _segment(nav, "2018-02-01", "2018-02-28"),
        "q4_2018":          _segment(nav, "2018-10-01", "2018-12-31"),
        "covid_2020":       _segment(nav, "2020-02-15", "2020-04-30"),
        "rate_hike_2022":   _segment(nav, "2022-01-01", "2022-12-31"),
    }
    return {
        "label": label,
        "window": {"start": str(nav.index.min().date()),
                   "end": str(nav.index.max().date()),
                   "n_days": int(len(nav)), "n_years": float(n_years)},
        "headline": {"nav_initial": float(nav.iloc[0]),
                     "nav_final": float(nav.iloc[-1]),
                     "cum_return": float(cum), "cagr": float(cagr),
                     "sharpe": sharpe, "max_dd": max_dd},
        "trades": {"n_closed": len(closed), "n_open": sum(1 for p in positions if p.is_open),
                   "total_pnl": pnl_total, "win_rate": float(win_rate),
                   "close_reasons": by_reason, "by_structure": by_struct},
        "tails": tails,
    }


def render_md(summaries: list[dict], buy_hold: dict) -> str:
    lines = [
        "# Synthetic spread backtest — baseline (3 cells) + signal-driven, SPY",
        "",
        f"Window: {summaries[0]['window']['start']} → "
        f"{summaries[0]['window']['end']} ({summaries[0]['window']['n_years']:.1f} years)",
        "",
        "## Headline metrics",
        "",
        "| Strategy | CAGR | Sharpe | MaxDD | Final NAV | Closed | Win% |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in summaries:
        h = s["headline"]
        t = s["trades"]
        lines.append(
            f"| {s['label']} | {h['cagr']*100:+.2f}% | {h['sharpe']:.2f} | "
            f"{h['max_dd']*100:+.2f}% | ${h['nav_final']:,.0f} | "
            f"{t['n_closed']} | {t['win_rate']*100:.1f}% |"
        )
    h = buy_hold
    lines.append(
        f"| spy_buy_hold | {h['cagr']*100:+.2f}% | {h['sharpe']:.2f} | "
        f"{h['max_dd']*100:+.2f}% | (ref) | — | — |"
    )
    lines += ["", "## Tail period DD (overlay validates)", "",
              "| Window | " + " | ".join(s['label'] for s in summaries) + " |",
              "|---|" + "---|" * len(summaries)]
    for tail in summaries[0]["tails"]:
        if summaries[0]["tails"][tail].get("n", 0) == 0:
            continue
        cells = []
        for s in summaries:
            t = s["tails"][tail]
            cells.append(f"{t['cum_return']*100:+.2f}% / {t['max_dd']*100:+.2f}%")
        lines.append(f"| {tail} | " + " | ".join(cells) + " |")

    lines += ["", "## Signal-driven structure mix (from close_reasons + by_structure)", ""]
    sig = next((s for s in summaries if s['label'] == 'signal_driven'), None)
    if sig:
        lines.append(f"- Total closed: {sig['trades']['n_closed']}")
        lines.append(f"- By structure: {sig['trades']['by_structure']}")
        lines.append(f"- Close reasons: {sig['trades']['close_reasons']}")
    return "\n".join(lines)


def _buy_hold(df: pd.DataFrame) -> dict:
    spy = df["spy"]
    n_years = len(spy) / 252.0
    cum = spy.iloc[-1] / spy.iloc[0] - 1.0
    cagr = (spy.iloc[-1] / spy.iloc[0]) ** (1 / n_years) - 1.0 if n_years > 0 else 0.0
    daily_ret = spy.pct_change().dropna()
    sharpe = float(daily_ret.mean() / daily_ret.std() * np.sqrt(252)) if daily_ret.std() > 0 else 0.0
    rmax = spy.cummax()
    max_dd = float(((spy - rmax) / rmax).min())
    return {"label": "spy_buy_hold", "cum_return": float(cum), "cagr": float(cagr),
            "sharpe": sharpe, "max_dd": max_dd}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    args = ap.parse_args()

    BT_DIR.mkdir(parents=True, exist_ok=True)
    ANAL_DIR.mkdir(parents=True, exist_ok=True)

    df = _load_data()
    if args.start: df = df.loc[args.start:]
    if args.end:   df = df.loc[:args.end]
    print(f"[bt] panel {df.index.min().date()} → {df.index.max().date()} ({len(df)} rows)")

    summaries = []
    for mode_label, mode in [
        ("baseline_bull_put",   "baseline:bull_put"),
        ("baseline_bear_call",  "baseline:bear_call"),
        ("baseline_iron_condor","baseline:iron_condor"),
        ("signal_driven",       "signal_driven"),
    ]:
        print(f"[bt] running {mode_label} ...")
        nav, pos = run_backtest(df, mode=mode)
        nav.to_parquet(BT_DIR / f"spread_{mode_label}_nav.parquet")
        summaries.append(_summarize(nav, pos, mode_label))

    bh = _buy_hold(df)
    summary = {
        "params": {
            "initial_nav": INITIAL_NAV, "dte_open_days": DTE_OPEN_DAYS,
            "short_otm_pct": SHORT_OTM_PCT, "width_pct": WIDTH_PCT,
            "risk_per_trade_pct": RISK_PER_TRADE_PCT,
            "vix_halt_hard": VIX_HALT_HARD, "early_tp_frac": EARLY_TP_FRAC,
            "stop_loss_frac": STOP_LOSS_FRAC, "time_stop_dte": TIME_STOP_DTE,
            "dd_halt_pct": DD_HALT_PCT, "trend_ma_days": TREND_MA_DAYS,
            "momentum_days": MOMENTUM_DAYS,
        },
        "runs": {s["label"]: s for s in summaries},
        "buy_hold_spy": bh,
    }
    out = ANAL_DIR / "spread_backtest_summary.json"
    out.write_text(json.dumps(summary, indent=2, default=str))
    print(f"[bt] wrote {out}")
    print()
    print(render_md(summaries, bh))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
