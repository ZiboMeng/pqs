"""Path E: synthetic wheel backtest on SPY (CSP → assignment → CC → repeat).

Tests whether the covered-call arm of the wheel UNLOCKS the V-shaped
recovery alpha that pure CSP loses by going to cash on assignment.

Wheel state machine (per "unit" of capital):
  STATE_CASH        → sell next CSP at 5pct OTM
  STATE_SHORT_PUT   → wait for expiry; if SPY < strike → assigned →
                      receive shares at strike, transition to STATE_LONG_SHARES
  STATE_LONG_SHARES → sell next CC at 5pct OTM above current spot OR
                      basis (whichever higher to avoid locking in loss)
  STATE_SHORT_CALL  → wait for expiry; if SPY > strike → called away
                      → receive cash, transition to STATE_CASH

Defended-loss policy: CC strike >= max(spot * 1.05, basis * 1.02)
                      to avoid being called away at a loss.

Sizing: full notional deployment (1.0 frac) since wheel tracks one
position at a time, NOT a notional-fraction CSP. Account collateral
= strike * 100 per contract; assignment takes that collateral to
buy shares.

Apples-to-apples comparison vs Phase 1.3 / 1.5 results: same SPY 33yr
panel, same VIX-as-IV (with skew options), same PRD §2 overlay
(time stops, VIX>40 halt) adapted to wheel state machine.

Per-leg IV: use realistic asymmetric skew from yfinance validation:
  put leg: VIX * 1.11 (5pct OTM)
  call leg: VIX * 0.69 (5pct OTM, but call leg less impacted in wheel
            since CC strike is OFTEN above spot, deeper OTM at high vol)

Output:
  data/options/backtest/wheel_nav.parquet   (gitignored)
  data/options/analysis/wheel_backtest_summary.json
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

from core.options.pricing.black_scholes import BSInputs, put_price, call_price  # noqa: E402

SNAP_DIR = PROJ / "data" / "options" / "snapshots"
ANAL_DIR = PROJ / "data" / "options" / "analysis"
BT_DIR = PROJ / "data" / "options" / "backtest"

INITIAL_NAV = 10_000.0
DTE_OPEN_DAYS = 21
PUT_OTM_PCT = 0.05
CC_OTM_PCT = 0.05
RISK_FREE_RATE = 0.045
IV_HAIRCUT_VOL_PTS = 0.10
PUT_SKEW = 1.11
CALL_SKEW = 0.69
DEFEND_BASIS_MULT = 1.02         # CC strike must be >= basis * this
VIX_HALT_HARD = 40.0
DD_HALT_PCT = 0.10
DD_HALT_WINDOW = 21


STATE_CASH = "cash"
STATE_SHORT_PUT = "short_put"
STATE_LONG_SHARES = "long_shares"
STATE_SHORT_CALL = "short_call"


@dataclass
class WheelPosition:
    state: str = STATE_CASH
    short_strike: float | None = None
    short_credit: float = 0.0       # per share
    short_open_date: pd.Timestamp | None = None
    short_expiry_date: pd.Timestamp | None = None
    short_iv_at_open: float | None = None
    shares_held: int = 0            # multiple of 100 (per contract)
    basis_per_share: float = 0.0    # cost per share when assigned
    contracts: int = 0              # number of put/call contracts active


@dataclass
class WheelState:
    nav: float = INITIAL_NAV
    cash: float = INITIAL_NAV
    pos: WheelPosition = field(default_factory=WheelPosition)
    history: list[dict] = field(default_factory=list)
    cycle_log: list[dict] = field(default_factory=list)


def _load_data() -> pd.DataFrame:
    vix = pd.read_parquet(SNAP_DIR / "vix_history.parquet")["close"].rename("vix")
    spy = pd.read_parquet(SNAP_DIR / "spy_history.parquet")["close"].rename("spy")
    df = pd.concat([vix, spy], axis=1, join="inner").dropna()
    iv_atm = ((df["vix"] - IV_HAIRCUT_VOL_PTS) / 100.0).clip(lower=0.05)
    df["iv_put"] = (iv_atm * PUT_SKEW).clip(lower=0.05)
    df["iv_call"] = (iv_atm * CALL_SKEW).clip(lower=0.05)
    return df


def _is_last_bday_of_month(idx: pd.DatetimeIndex, i: int) -> bool:
    if i + 1 >= len(idx): return True
    return idx[i].month != idx[i + 1].month


def _bs_put(spot, strike, t, iv, r=RISK_FREE_RATE):
    return put_price(BSInputs(spot=spot, strike=strike, t_years=t, sigma=iv, r=r))


def _bs_call(spot, strike, t, iv, r=RISK_FREE_RATE):
    return call_price(BSInputs(spot=spot, strike=strike, t_years=t, sigma=iv, r=r))


def run_wheel(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    state = WheelState()
    panel_index = df.index
    nav_window: list[float] = []

    for i, today in enumerate(panel_index):
        spot = float(df["spy"].iat[i])
        vix = float(df["vix"].iat[i])
        iv_put = float(df["iv_put"].iat[i])
        iv_call = float(df["iv_call"].iat[i])

        pos = state.pos

        # 1) Mark current state to NAV + check expiry
        unrealized = 0.0
        if pos.state == STATE_SHORT_PUT:
            dte = (pos.short_expiry_date - today).days
            if dte <= 0:
                # Expiry handling
                intrinsic_per_share = max(pos.short_strike - spot, 0.0)
                if intrinsic_per_share > 0:
                    # Assignment: buy shares at strike
                    pos.shares_held = pos.contracts * 100
                    pos.basis_per_share = pos.short_strike
                    state.cash -= pos.short_strike * pos.shares_held  # collateral becomes shares
                    pnl = (pos.short_credit - intrinsic_per_share) * pos.shares_held
                    state.cycle_log.append({"date": today, "event": "csp_assigned",
                                            "strike": pos.short_strike, "spot": spot,
                                            "credit": pos.short_credit, "intrinsic": intrinsic_per_share,
                                            "pnl_realized": pnl})
                    pos.state = STATE_LONG_SHARES
                    pos.short_strike = None
                else:
                    # Expire worthless
                    state.cycle_log.append({"date": today, "event": "csp_expired_worthless",
                                            "strike": pos.short_strike, "spot": spot,
                                            "credit": pos.short_credit,
                                            "pnl_realized": pos.short_credit * pos.contracts * 100})
                    pos.state = STATE_CASH
                    pos.short_strike = None
                    pos.contracts = 0
            else:
                # MtM
                t = max(dte / 365.0, 1e-6)
                mtm = _bs_put(spot, pos.short_strike, t, iv_put)
                unrealized = (pos.short_credit - mtm) * pos.contracts * 100

        elif pos.state == STATE_SHORT_CALL:
            dte = (pos.short_expiry_date - today).days
            if dte <= 0:
                intrinsic_per_share = max(spot - pos.short_strike, 0.0)
                if intrinsic_per_share > 0:
                    # Called away: sell shares at strike
                    sale_proceeds = pos.short_strike * pos.shares_held
                    pnl_shares = (pos.short_strike - pos.basis_per_share) * pos.shares_held
                    pnl_call = (pos.short_credit - intrinsic_per_share) * pos.shares_held
                    state.cash += sale_proceeds
                    state.cycle_log.append({"date": today, "event": "cc_called_away",
                                            "strike": pos.short_strike, "spot": spot,
                                            "basis": pos.basis_per_share,
                                            "credit": pos.short_credit, "intrinsic": intrinsic_per_share,
                                            "pnl_shares": pnl_shares, "pnl_call": pnl_call})
                    pos.shares_held = 0
                    pos.basis_per_share = 0
                    pos.contracts = 0
                    pos.state = STATE_CASH
                    pos.short_strike = None
                else:
                    state.cycle_log.append({"date": today, "event": "cc_expired_worthless",
                                            "strike": pos.short_strike, "spot": spot,
                                            "credit": pos.short_credit,
                                            "pnl_call": pos.short_credit * pos.shares_held})
                    pos.state = STATE_LONG_SHARES
                    pos.short_strike = None
            else:
                t = max(dte / 365.0, 1e-6)
                mtm = _bs_call(spot, pos.short_strike, t, iv_call)
                unrealized = (pos.short_credit - mtm) * pos.shares_held

        # 2) NAV mark
        share_value = pos.shares_held * spot if pos.shares_held > 0 else 0
        nav_today = state.cash + share_value + unrealized
        state.nav = nav_today
        nav_window.append(nav_today)
        if len(nav_window) > DD_HALT_WINDOW: nav_window.pop(0)
        rolling_dd = (max(nav_window) - nav_today) / max(nav_window)

        # 3) Decide entry (only on last bday of month)
        new_action = ""
        if _is_last_bday_of_month(panel_index, i):
            if pos.state == STATE_CASH:
                # Open new CSP if vol regime allows
                if vix < VIX_HALT_HARD and rolling_dd <= DD_HALT_PCT:
                    expiry_loc = min(i + DTE_OPEN_DAYS, len(panel_index) - 1)
                    expiry_date = panel_index[expiry_loc]
                    t_years = (expiry_date - today).days / 365.0
                    if t_years > 0:
                        strike = round(spot * (1 - PUT_OTM_PCT), 0)
                        contracts_target = int(state.nav / (strike * 100))
                        if contracts_target >= 1:
                            credit = _bs_put(spot, strike, t_years, iv_put)
                            collateral = strike * 100 * contracts_target
                            if collateral <= state.cash:
                                state.cash += credit * 100 * contracts_target
                                pos.state = STATE_SHORT_PUT
                                pos.short_strike = strike
                                pos.short_credit = credit
                                pos.short_open_date = today
                                pos.short_expiry_date = expiry_date
                                pos.short_iv_at_open = iv_put
                                pos.contracts = contracts_target
                                new_action = "open_csp"
            elif pos.state == STATE_LONG_SHARES:
                # Open new CC: strike >= max(spot * 1.05, basis * 1.02)
                expiry_loc = min(i + DTE_OPEN_DAYS, len(panel_index) - 1)
                expiry_date = panel_index[expiry_loc]
                t_years = (expiry_date - today).days / 365.0
                if t_years > 0:
                    strike = round(max(spot * (1 + CC_OTM_PCT),
                                       pos.basis_per_share * DEFEND_BASIS_MULT), 0)
                    credit = _bs_call(spot, strike, t_years, iv_call)
                    if credit > 0:
                        state.cash += credit * pos.shares_held
                        pos.state = STATE_SHORT_CALL
                        pos.short_strike = strike
                        pos.short_credit = credit
                        pos.short_open_date = today
                        pos.short_expiry_date = expiry_date
                        pos.short_iv_at_open = iv_call
                        pos.contracts = pos.shares_held // 100
                        new_action = f"open_cc_at_{strike}"

        state.history.append({
            "date": today, "nav": nav_today, "spot": spot, "vix": vix,
            "state": pos.state, "shares": pos.shares_held,
            "basis": pos.basis_per_share, "rolling_dd": rolling_dd,
            "action": new_action,
        })

    nav_df = pd.DataFrame(state.history).set_index("date")
    return nav_df, state.cycle_log


def _max_dd(nav: pd.Series) -> float:
    rmax = nav.cummax()
    return float(((nav - rmax) / rmax).min())


def main() -> int:
    BT_DIR.mkdir(parents=True, exist_ok=True)
    ANAL_DIR.mkdir(parents=True, exist_ok=True)

    df = _load_data()
    print(f"[wheel] panel {df.index.min().date()} → {df.index.max().date()} "
          f"({len(df)} rows)")
    nav_df, cycles = run_wheel(df)
    nav_df.to_parquet(BT_DIR / "wheel_nav.parquet")
    print(f"[wheel] cycle events: {len(cycles)}")

    nav = nav_df["nav"]
    daily_ret = nav.pct_change().dropna()
    n_years = len(nav) / 252.0
    cum = nav.iloc[-1] / nav.iloc[0] - 1.0
    cagr = (nav.iloc[-1] / nav.iloc[0]) ** (1 / n_years) - 1.0
    sharpe = float(daily_ret.mean() / daily_ret.std() * np.sqrt(252)) if daily_ret.std() > 0 else 0.0
    max_dd = _max_dd(nav)

    by_event = pd.Series([c["event"] for c in cycles]).value_counts().to_dict()

    spy = df["spy"]
    spy_n = len(spy) / 252.0
    spy_cagr = (spy.iloc[-1] / spy.iloc[0]) ** (1 / spy_n) - 1.0
    spy_ret = spy.pct_change().dropna()
    spy_sharpe = float(spy_ret.mean() / spy_ret.std() * np.sqrt(252))
    spy_dd = _max_dd(spy)

    summary = {
        "params": {"initial_nav": INITIAL_NAV, "dte_open_days": DTE_OPEN_DAYS,
                   "put_otm_pct": PUT_OTM_PCT, "cc_otm_pct": CC_OTM_PCT,
                   "put_skew": PUT_SKEW, "call_skew": CALL_SKEW,
                   "defend_basis_mult": DEFEND_BASIS_MULT,
                   "vix_halt_hard": VIX_HALT_HARD, "dd_halt_pct": DD_HALT_PCT},
        "headline": {"nav_initial": float(nav.iloc[0]),
                     "nav_final": float(nav.iloc[-1]),
                     "cum_return": float(cum), "cagr": float(cagr),
                     "sharpe": sharpe, "max_dd": max_dd,
                     "n_years": n_years},
        "spy_buy_hold": {"cagr": float(spy_cagr), "sharpe": float(spy_sharpe), "max_dd": spy_dd},
        "cycle_events": by_event,
    }
    out = ANAL_DIR / "wheel_backtest_summary.json"
    out.write_text(json.dumps(summary, indent=2, default=str))
    print(f"[wheel] wrote {out}\n")

    print("# Synthetic wheel backtest — SPY 33y, realistic asymmetric skew")
    print()
    print(f"Window: {nav.index.min().date()} → {nav.index.max().date()} "
          f"({n_years:.1f} years)")
    print()
    print(f"| Strategy            | CAGR     | Sharpe | MaxDD   | Final NAV  |")
    print(f"|---------------------|----------|--------|---------|------------|")
    print(f"| wheel (CSP→CC)      | {cagr*100:+.2f}%  | {sharpe:.2f}   | {max_dd*100:+.2f}% | ${nav.iloc[-1]:>10,.0f} |")
    print(f"| SPY buy-and-hold    | {spy_cagr*100:+.2f}% | {spy_sharpe:.2f}   | {spy_dd*100:+.2f}% | (ref)      |")
    print()
    print(f"Cycle events: {by_event}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
