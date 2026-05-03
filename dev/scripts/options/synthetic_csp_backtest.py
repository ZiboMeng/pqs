"""Synthetic cash-secured put backtest on SPY (1993-2026) with tail-risk overlay.

Phase 1.3 of `pqs-options-v1-2026-05-02`. Simulates monthly 5%-OTM
30-DTE cash-secured puts on SPY using Black-Scholes priced with VIX
as IV proxy. Mandatory tail-risk overlay encoded per PRD §2.

Two backtests run side-by-side:
  (1) NAIVE: write monthly puts, hold to expiration always (NO overlay).
      This is the "control" — measures pure VRP harvest minus tail
      blowups. EXPECTED to fail in 2008 / 2020 if VRP harvest were
      free money.
  (2) WITH_OVERLAY: PRD §2 discipline:
        - Halt new entries if VIX > 40 (VRP coin-flip regime per Phase 1.2)
        - Stop loss: close at 200% of credit (loss = 1x credit)
        - Early TP: close at 50% of max profit (1x credit + 50% gain)
        - Time stop: close at <=7 DTE (gamma risk surge near expiration)
        - Account-level halt: pause new entries if rolling 21d DD > 5%
        - VIX-tier position sizing: full size when VIX 12-25, half when
          25-40, ZERO when >=40

Sizing convention:
  - "Notional" = strike * 100 (per contract). Cash-secured means we
    set aside that notional from NAV.
  - We sell 1 "unit position" per month. Premium and P&L scale linearly.
  - Position sized as TARGET_NOTIONAL_FRAC (default 50%) of NAV — i.e.,
    a $10K account writes the equivalent of 1 contract on a $20K
    notional underlying. With SPY at $400, that means strike ~ $380
    and we set aside 50% of NAV ($5K equivalent — fractional bookkeeping).
  - This is fractional-contract bookkeeping; real implementation rounds
    DOWN to integer contracts, but for VRP-magnitude validation the
    fractional simulation is the right tool.

Outputs:
  data/options/backtest/csp_naive_nav.parquet         (gitignored)
  data/options/backtest/csp_overlay_nav.parquet       (gitignored)
  data/options/analysis/csp_backtest_summary.json     (committable)
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

from core.options.pricing.black_scholes import BSInputs, put_greeks  # noqa: E402

SNAP_DIR = PROJ / "data" / "options" / "snapshots"
ANAL_DIR = PROJ / "data" / "options" / "analysis"
BT_DIR = PROJ / "data" / "options" / "backtest"

VIX_PARQUET = SNAP_DIR / "vix_history.parquet"
SPY_PARQUET = SNAP_DIR / "spy_history.parquet"

# --- Strategy constants (PRD §6 + §2) ---
INITIAL_NAV = 10_000.0
TARGET_NOTIONAL_FRAC = 0.50      # half of NAV deployed per cycle
DTE_OPEN_DAYS = 21               # trading days ≈ 30 calendar days; allows monthly cycles
OTM_PCT = 0.05                   # 5% OTM puts
RISK_FREE_RATE = 0.045           # constant proxy; FRED swap-in is Phase 2
IV_HAIRCUT_VOL_PTS = 0.10        # subtract 10 vol-pt from VIX (skew + b/a haircut)

# Tail-risk overlay (PRD §2)
VIX_HALT_HARD = 40.0             # do not open new positions
VIX_DOWNSIZE = 25.0              # half size between 25 and 40
DD_HALT_PCT = 0.10               # account-level: halt new entries if 21d rolling DD > 10%
DD_HALT_WINDOW = 21              # rolling window for DD measurement (trading days)
EARLY_TP_FRAC = 0.50             # close at 50% of max profit
STOP_LOSS_MULT = 2.0             # close if MtM loss = 2x credit (i.e., -1x credit P&L)
TIME_STOP_DTE = 7                # close at <=7 DTE


@dataclass
class Position:
    open_date: pd.Timestamp
    expiry_date: pd.Timestamp
    strike: float
    spot_at_open: float
    iv_at_open: float
    credit: float                 # premium received per unit notional
    notional: float               # strike * 100 (per "unit contract")
    contracts: float              # fractional units; equity NAV * frac / notional
    cash_collateral: float        # contracts * notional (cash set aside)
    is_open: bool = True
    close_date: pd.Timestamp | None = None
    close_pnl: float = 0.0
    close_reason: str = ""


@dataclass
class BacktestState:
    nav: float = INITIAL_NAV
    cash: float = INITIAL_NAV
    collateral: float = 0.0
    positions: list[Position] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)


def _load_data() -> pd.DataFrame:
    if not VIX_PARQUET.exists() or not SPY_PARQUET.exists():
        raise FileNotFoundError(
            "Run dev/scripts/options/vix_rv_gap_analysis.py first to populate "
            f"{SNAP_DIR}"
        )
    vix = pd.read_parquet(VIX_PARQUET)["close"].rename("vix")
    spy = pd.read_parquet(SPY_PARQUET)["close"].rename("spy")
    df = pd.concat([vix, spy], axis=1, join="inner").dropna()
    df["iv"] = (df["vix"] - IV_HAIRCUT_VOL_PTS) / 100.0
    df["iv"] = df["iv"].clip(lower=0.05)
    return df


def _is_last_bday_of_month(idx: pd.DatetimeIndex, i: int) -> bool:
    if i + 1 >= len(idx):
        return True
    return idx[i].month != idx[i + 1].month


def _open_position(
    state: BacktestState,
    today: pd.Timestamp,
    spot: float,
    iv: float,
    notional_frac: float,
    panel_index: pd.DatetimeIndex,
    today_loc: int,
) -> Position | None:
    if notional_frac <= 0:
        return None
    strike = spot * (1.0 - OTM_PCT)
    notional = strike * 100.0
    target_cash = state.nav * notional_frac
    contracts = target_cash / notional
    if contracts < 1e-6:
        return None
    expiry_loc = min(today_loc + DTE_OPEN_DAYS, len(panel_index) - 1)
    expiry_date = panel_index[expiry_loc]
    t_years = (expiry_date - today).days / 365.0
    if t_years <= 0:
        return None
    inputs = BSInputs(spot=spot, strike=strike, t_years=t_years, sigma=iv, r=RISK_FREE_RATE)
    greeks = put_greeks(inputs)
    credit_per_unit = max(greeks.price, 0.0) * 100.0  # per contract
    cash_collateral = contracts * notional
    if cash_collateral > state.cash:
        return None
    state.cash -= cash_collateral
    state.collateral += cash_collateral
    state.cash += credit_per_unit * contracts
    return Position(
        open_date=today, expiry_date=expiry_date, strike=strike,
        spot_at_open=spot, iv_at_open=iv, credit=credit_per_unit,
        notional=notional, contracts=contracts, cash_collateral=cash_collateral,
    )


def _mark_position(pos: Position, today: pd.Timestamp, spot: float, iv: float) -> float:
    """Per-contract put MtM today."""
    t_years = max((pos.expiry_date - today).days / 365.0, 1e-6)
    inputs = BSInputs(spot=spot, strike=pos.strike, t_years=t_years, sigma=iv, r=RISK_FREE_RATE)
    return put_greeks(inputs).price * 100.0


def _close_position(
    state: BacktestState, pos: Position, today: pd.Timestamp,
    mtm_per_unit: float, reason: str,
) -> None:
    pnl_per_unit = pos.credit - mtm_per_unit  # short put: credit collected - cost to close
    pnl_total = pnl_per_unit * pos.contracts
    # Return collateral, deduct buy-back cost
    state.cash -= mtm_per_unit * pos.contracts  # pay to close
    state.cash += pos.cash_collateral
    state.collateral -= pos.cash_collateral
    pos.is_open = False
    pos.close_date = today
    pos.close_pnl = pnl_total
    pos.close_reason = reason


def _expire_position(
    state: BacktestState, pos: Position, today: pd.Timestamp, spot: float,
) -> None:
    intrinsic = max(pos.strike - spot, 0.0) * 100.0  # per-contract
    pnl_per_unit = pos.credit - intrinsic
    pnl_total = pnl_per_unit * pos.contracts
    state.cash -= intrinsic * pos.contracts
    state.cash += pos.cash_collateral
    state.collateral -= pos.cash_collateral
    pos.is_open = False
    pos.close_date = today
    pos.close_pnl = pnl_total
    pos.close_reason = "expiry_assigned" if intrinsic > 0 else "expiry_worthless"


def run_backtest(df: pd.DataFrame, *, with_overlay: bool) -> tuple[pd.DataFrame, list[Position]]:
    state = BacktestState()
    panel_index = df.index
    nav_window: list[float] = []  # 21d rolling NAV (for proper rolling DD)

    for i, today in enumerate(panel_index):
        spot = float(df["spy"].iat[i])
        vix = float(df["vix"].iat[i])
        iv = float(df["iv"].iat[i])

        # 1) Mark all open positions and check exits
        for pos in state.positions:
            if not pos.is_open:
                continue
            dte = (pos.expiry_date - today).days
            if dte <= 0:
                _expire_position(state, pos, today, spot)
                continue
            mtm_per_unit = _mark_position(pos, today, spot, iv)
            unrealized_pnl_per_unit = pos.credit - mtm_per_unit
            if with_overlay:
                # Stop loss: MtM loss exceeds 1x credit (i.e., MtM > 2x credit)
                if mtm_per_unit >= STOP_LOSS_MULT * pos.credit:
                    _close_position(state, pos, today, mtm_per_unit, "stop_loss")
                    continue
                # Early TP at 50% of max profit
                if unrealized_pnl_per_unit >= EARLY_TP_FRAC * pos.credit:
                    _close_position(state, pos, today, mtm_per_unit, "early_tp")
                    continue
                # Time stop
                if dte <= TIME_STOP_DTE:
                    _close_position(state, pos, today, mtm_per_unit, "time_stop")
                    continue

        # 2) Compute NAV mark-to-market
        unrealized = 0.0
        for pos in state.positions:
            if pos.is_open:
                mtm = _mark_position(pos, today, spot, iv)
                unrealized += (pos.credit - mtm) * pos.contracts
        nav_today = state.cash + state.collateral + unrealized
        state.nav = nav_today
        nav_window.append(nav_today)
        if len(nav_window) > DD_HALT_WINDOW:
            nav_window.pop(0)
        rolling_max_window = max(nav_window)
        rolling_dd = (rolling_max_window - nav_today) / rolling_max_window

        # 3) Decide whether to open a new monthly position
        opened = False
        if _is_last_bday_of_month(panel_index, i):
            already_open = any(p.is_open for p in state.positions)
            if not already_open:
                if not with_overlay:
                    notional_frac = TARGET_NOTIONAL_FRAC
                else:
                    notional_frac = TARGET_NOTIONAL_FRAC
                    if vix >= VIX_HALT_HARD:
                        notional_frac = 0.0
                    elif vix >= VIX_DOWNSIZE:
                        notional_frac *= 0.5
                    if rolling_dd > DD_HALT_PCT:
                        notional_frac = 0.0
                if notional_frac > 0:
                    pos = _open_position(state, today, spot, iv, notional_frac, panel_index, i)
                    if pos is not None:
                        state.positions.append(pos)
                        opened = True

        state.history.append({
            "date": today, "nav": nav_today, "spy": spot, "vix": vix, "iv": iv,
            "cash": state.cash, "collateral": state.collateral,
            "unrealized_pnl": unrealized, "rolling_dd": rolling_dd,
            "opened_today": opened,
            "open_positions": sum(1 for p in state.positions if p.is_open),
        })

    nav_df = pd.DataFrame(state.history).set_index("date")
    return nav_df, state.positions


def _segment_metric(nav: pd.Series, start: str, end: str) -> dict:
    sub = nav.loc[start:end]
    if sub.empty:
        return {"window": [start, end], "n": 0}
    cum = sub.iloc[-1] / sub.iloc[0] - 1.0
    rolling_max = sub.cummax()
    dd = (sub - rolling_max) / rolling_max
    return {
        "window": [start, end], "n": int(len(sub)),
        "cum_return": float(cum),
        "max_dd": float(dd.min()),
        "nav_start": float(sub.iloc[0]),
        "nav_end": float(sub.iloc[-1]),
    }


def _summarize(nav_df: pd.DataFrame, positions: list[Position], label: str) -> dict:
    nav = nav_df["nav"]
    daily_ret = nav.pct_change().dropna()
    n_years = len(nav) / 252.0
    cum = nav.iloc[-1] / nav.iloc[0] - 1.0
    cagr = (nav.iloc[-1] / nav.iloc[0]) ** (1 / n_years) - 1.0 if n_years > 0 else 0.0
    sharpe = float(daily_ret.mean() / daily_ret.std() * np.sqrt(252)) if daily_ret.std() > 0 else 0.0
    rolling_max = nav.cummax()
    dd = (nav - rolling_max) / rolling_max
    max_dd = float(dd.min())
    closed_pos = [p for p in positions if not p.is_open]
    open_pos = [p for p in positions if p.is_open]
    pnl_total = float(sum(p.close_pnl for p in closed_pos))
    win_rate = (
        float(sum(1 for p in closed_pos if p.close_pnl > 0) / max(len(closed_pos), 1))
    )
    reasons = pd.Series([p.close_reason for p in closed_pos]).value_counts().to_dict()

    tails = {
        "gfc_2008":          _segment_metric(nav, "2008-09-01", "2009-03-31"),
        "volmageddon_2018":  _segment_metric(nav, "2018-02-01", "2018-02-28"),
        "q4_2018":           _segment_metric(nav, "2018-10-01", "2018-12-31"),
        "covid_2020":        _segment_metric(nav, "2020-02-15", "2020-04-30"),
        "rate_hike_2022":    _segment_metric(nav, "2022-01-01", "2022-12-31"),
    }

    return {
        "label": label,
        "window": {
            "start": str(nav.index.min().date()),
            "end": str(nav.index.max().date()),
            "n_days": int(len(nav)), "n_years": float(n_years),
        },
        "headline": {
            "nav_initial": float(nav.iloc[0]), "nav_final": float(nav.iloc[-1]),
            "cum_return": float(cum), "cagr": float(cagr),
            "sharpe": sharpe, "max_dd": max_dd,
        },
        "trades": {
            "n_closed": len(closed_pos), "n_open": len(open_pos),
            "total_pnl": pnl_total, "win_rate": win_rate,
            "close_reasons": reasons,
        },
        "tails": tails,
    }


def _compare_buy_hold(df: pd.DataFrame) -> dict:
    spy = df["spy"]
    n_years = len(spy) / 252.0
    cum = spy.iloc[-1] / spy.iloc[0] - 1.0
    cagr = (spy.iloc[-1] / spy.iloc[0]) ** (1 / n_years) - 1.0 if n_years > 0 else 0.0
    daily_ret = spy.pct_change().dropna()
    sharpe = float(daily_ret.mean() / daily_ret.std() * np.sqrt(252)) if daily_ret.std() > 0 else 0.0
    rolling_max = spy.cummax()
    max_dd = float(((spy - rolling_max) / rolling_max).min())
    return {"label": "spy_buy_hold", "cum_return": float(cum), "cagr": float(cagr),
            "sharpe": sharpe, "max_dd": max_dd}


def render_md(naive: dict, overlay: dict, buy_hold: dict) -> str:
    lines = [
        "# Synthetic CSP backtest — naive vs tail-risk overlay vs SPY buy-hold",
        "",
        f"Window: {naive['window']['start']} → {naive['window']['end']} "
        f"({naive['window']['n_years']:.1f} years)",
        "",
        "## Headline",
        "",
        "| Strategy | CAGR | Sharpe | MaxDD | Final NAV |",
        "|---|---|---|---|---|",
    ]
    for s in [naive, overlay]:
        h = s["headline"]
        lines.append(
            f"| {s['label']} | {h['cagr']*100:+.2f}% | {h['sharpe']:.2f} | "
            f"{h['max_dd']*100:+.2f}% | ${h['nav_final']:,.0f} |"
        )
    lines.append(
        f"| {buy_hold['label']} | {buy_hold['cagr']*100:+.2f}% | "
        f"{buy_hold['sharpe']:.2f} | {buy_hold['max_dd']*100:+.2f}% | "
        f"(unscaled SPY %) |"
    )
    lines += [
        "",
        "## Tail period segment returns",
        "",
        "| Window | Naive cum_ret | Naive max_dd | Overlay cum_ret | Overlay max_dd |",
        "|---|---|---|---|---|",
    ]
    for label in naive["tails"]:
        n = naive["tails"][label]
        o = overlay["tails"][label]
        if n.get("n", 0) == 0:
            continue
        lines.append(
            f"| {label} ({n['window'][0]}…{n['window'][1]}) | "
            f"{n['cum_return']*100:+.2f}% | {n['max_dd']*100:+.2f}% | "
            f"{o['cum_return']*100:+.2f}% | {o['max_dd']*100:+.2f}% |"
        )
    lines += [
        "",
        "## Close reasons (overlay)",
        "",
    ]
    for reason, count in overlay["trades"]["close_reasons"].items():
        lines.append(f"- {reason}: {count}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=None, help="Override start date (YYYY-MM-DD)")
    ap.add_argument("--end", default=None, help="Override end date (YYYY-MM-DD)")
    args = ap.parse_args()

    BT_DIR.mkdir(parents=True, exist_ok=True)
    ANAL_DIR.mkdir(parents=True, exist_ok=True)

    df = _load_data()
    if args.start:
        df = df.loc[args.start:]
    if args.end:
        df = df.loc[:args.end]
    print(f"[bt] panel {df.index.min().date()} → {df.index.max().date()} "
          f"({len(df)} rows)")

    print("[bt] running NAIVE (no overlay) ...")
    naive_nav, naive_pos = run_backtest(df, with_overlay=False)
    naive_nav.to_parquet(BT_DIR / "csp_naive_nav.parquet")
    naive_summary = _summarize(naive_nav, naive_pos, "csp_naive_no_overlay")

    print("[bt] running WITH_OVERLAY (PRD §2) ...")
    overlay_nav, overlay_pos = run_backtest(df, with_overlay=True)
    overlay_nav.to_parquet(BT_DIR / "csp_overlay_nav.parquet")
    overlay_summary = _summarize(overlay_nav, overlay_pos, "csp_with_tail_risk_overlay")

    buy_hold = _compare_buy_hold(df)

    summary = {
        "params": {
            "initial_nav": INITIAL_NAV,
            "target_notional_frac": TARGET_NOTIONAL_FRAC,
            "dte_open_days": DTE_OPEN_DAYS,
            "otm_pct": OTM_PCT,
            "risk_free_rate": RISK_FREE_RATE,
            "iv_haircut_vol_pts": IV_HAIRCUT_VOL_PTS,
            "vix_halt_hard": VIX_HALT_HARD,
            "vix_downsize": VIX_DOWNSIZE,
            "dd_halt_pct": DD_HALT_PCT,
            "early_tp_frac": EARLY_TP_FRAC,
            "stop_loss_mult": STOP_LOSS_MULT,
            "time_stop_dte": TIME_STOP_DTE,
        },
        "naive": naive_summary,
        "overlay": overlay_summary,
        "buy_hold_spy": buy_hold,
    }
    out_path = ANAL_DIR / "csp_backtest_summary.json"
    out_path.write_text(json.dumps(summary, indent=2, default=str))
    print(f"[bt] wrote {out_path}")

    print()
    print(render_md(naive_summary, overlay_summary, buy_hold))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
