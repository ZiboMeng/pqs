"""Forward paper-trading runner for options strategies.

State machine analogous to `core/research/forward/runner.py` but
simpler — options strategies are deterministic from (VIX, SPY, spec)
so no factor input hashing required.

Two CLI entry points:
  init    — bootstrap a paper run with strategy spec + initial state
  observe — daily ritual: pull live VIX/SPY → mark → apply overlay → maybe open

Outputs per candidate (under data/options/paper_runs/<id>/):
  spec.yaml                      — frozen strategy spec (sha256 anchored)
  manifest.json                  — run metadata + position state
  daily_nav.csv                  — date / nav / spot / vix / iv / state / pnl_realized / pnl_unrealized
  trade_log.csv                  — per-trade open/close events
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from core.options.pricing.black_scholes import BSInputs, put_price, call_price
from core.options.strategies.spreads import (
    BullPutSpread, IronCondor,
    bull_put_spread_metrics, iron_condor_metrics,
    bull_put_spread_mtm, iron_condor_mtm,
    bull_put_spread_expiry_payoff, iron_condor_expiry_payoff,
)
from core.options.paper.spec import StrategySpec, load_spec, write_spec


PAPER_DIR_DEFAULT = Path("data/options/paper_runs")


# -- Data structures --------------------------------------------------------

@dataclass
class OpenPosition:
    structure: str                   # bull_put / iron_condor
    open_date: str                   # YYYY-MM-DD
    expiry_date: str                 # YYYY-MM-DD
    spot_at_open: float
    iv_at_open_put: float
    iv_at_open_call: float
    credit_per_share: float
    max_loss_per_share: float
    width_per_share: float
    contracts: int
    cash_collateral: float
    # Strikes (only relevant ones populated):
    k_short_put: float | None = None
    k_long_put: float | None = None
    k_short_call: float | None = None
    k_long_call: float | None = None


@dataclass
class RunState:
    candidate_id: str
    spec_hash: str
    spec_path: str
    start_date: str
    cash: float
    nav_initial: float
    nav_current: float
    nav_high_water: float
    open_positions: list[OpenPosition] = field(default_factory=list)
    n_observe_days: int = 0
    last_observe_date: str | None = None
    last_observe_at_utc: str | None = None
    rolling_nav_window: list[float] = field(default_factory=list)
    rolling_window_max: int = 21
    closed_positions_count: int = 0
    realized_pnl_cumulative: float = 0.0


# -- Helpers ----------------------------------------------------------------

def _spec_iv_per_leg(spec: StrategySpec, vix: float) -> tuple[float, float]:
    """Return (iv_put, iv_call) annualized decimal under per-leg skew."""
    iv_atm = max((vix - spec.pricing.iv_haircut_vol_pts) / 100.0, 0.05)
    iv_put = max(iv_atm * spec.pricing.put_skew_factor, 0.05)
    iv_call = max(iv_atm * spec.pricing.call_skew_factor, 0.05)
    return iv_put, iv_call


def _is_last_bday_of_month(d: datetime) -> bool:
    """True if d is the last NYSE trading day of its month (approx via
    Mon-Fri + skip if next Mon-Fri is in the same month)."""
    # Iterate to next weekday after d; if same month, d is not last bday
    cur = d
    while True:
        cur = cur + timedelta(days=1)
        if cur.weekday() < 5:  # Mon-Fri
            return cur.month != d.month


def _vol_regime_go(spec: StrategySpec, vix: float, spy_history_close: pd.Series) -> bool:
    f = spec.vol_regime_filter
    if not f.enabled:
        return True
    if not (f.vix_min <= vix <= f.vix_max):
        return False
    if f.require_positive_vrp and len(spy_history_close) > f.rv_window:
        log_ret = np.log(spy_history_close / spy_history_close.shift(1)).dropna()
        rv = log_ret.iloc[-f.rv_window:].std() * math.sqrt(252) * 100.0
        vrp = vix - rv
        if vrp <= 0:
            return False
    return True


def _open_position(spec: StrategySpec, today: datetime, spot: float,
                   vix: float, iv_put: float, iv_call: float,
                   nav: float, available_cash: float) -> OpenPosition | None:
    """Open new position per spec strategy_type. Returns None if not opened."""
    expiry = today + timedelta(days=spec.dte_open_days)
    t_years = (expiry - today).days / 365.0
    if t_years <= 0:
        return None
    width = spot * (spec.long_otm_pct - spec.short_otm_pct)

    if spec.strategy_type == "bull_put_spread":
        k_short = round(spot * (1.0 - spec.short_otm_pct), 0)
        k_long = round(k_short - width, 0)
        if k_long >= k_short:  # safety: ensure long < short
            k_long = k_short - 1.0
        bp = BullPutSpread(spot_at_open=spot, k_short_put=k_short, k_long_put=k_long,
                           t_years=t_years, sigma=iv_put, r=spec.pricing.risk_free_rate)
        m = bull_put_spread_metrics(bp)
        ks = dict(k_short_put=k_short, k_long_put=k_long,
                  k_short_call=None, k_long_call=None)
    elif spec.strategy_type == "iron_condor":
        k_short_put = round(spot * (1.0 - spec.short_otm_pct), 0)
        k_long_put = round(k_short_put - width, 0)
        k_short_call = round(spot * (1.0 + spec.short_otm_pct), 0)
        k_long_call = round(k_short_call + width, 0)
        # Use put-leg pricing for short put + call-leg for short call
        # (asymmetric IV); compose net credit + max_loss manually
        bp = BullPutSpread(spot_at_open=spot, k_short_put=k_short_put,
                           k_long_put=k_long_put, t_years=t_years,
                           sigma=iv_put, r=spec.pricing.risk_free_rate)
        bp_m = bull_put_spread_metrics(bp)
        # For call leg use bear_call metrics with iv_call
        from core.options.strategies.spreads import BearCallSpread, bear_call_spread_metrics, SpreadMetrics
        bc = BearCallSpread(spot_at_open=spot, k_short_call=k_short_call,
                            k_long_call=k_long_call, t_years=t_years,
                            sigma=iv_call, r=spec.pricing.risk_free_rate)
        bc_m = bear_call_spread_metrics(bc)
        net_credit = bp_m.net_credit_per_share + bc_m.net_credit_per_share
        width_max = max(bp_m.width_per_share, bc_m.width_per_share)
        max_loss = max(width_max - net_credit, 0.0)
        m = SpreadMetrics(
            net_credit_per_share=net_credit, max_loss_per_share=max_loss,
            max_profit_per_share=net_credit,
            breakeven_low=k_short_put - net_credit,
            breakeven_high=k_short_call + net_credit,
            width_per_share=width_max,
        )
        ks = dict(k_short_put=k_short_put, k_long_put=k_long_put,
                  k_short_call=k_short_call, k_long_call=k_long_call)
    else:
        raise ValueError(f"unknown strategy_type: {spec.strategy_type}")

    if m.max_loss_per_share <= 0:
        return None
    risk_dollars = nav * spec.risk_per_trade_pct
    contracts_target = int(risk_dollars / (m.max_loss_per_share * 100.0))
    if contracts_target < 1:
        return None
    cash_coll = contracts_target * m.max_loss_per_share * 100.0
    if cash_coll > available_cash:
        return None

    return OpenPosition(
        structure=spec.strategy_type, open_date=today.strftime("%Y-%m-%d"),
        expiry_date=expiry.strftime("%Y-%m-%d"),
        spot_at_open=spot,
        iv_at_open_put=iv_put, iv_at_open_call=iv_call,
        credit_per_share=m.net_credit_per_share,
        max_loss_per_share=m.max_loss_per_share,
        width_per_share=m.width_per_share,
        contracts=contracts_target, cash_collateral=cash_coll, **ks,
    )


def _mtm_per_share(spec: StrategySpec, pos: OpenPosition,
                   spot: float, iv_put: float, iv_call: float,
                   today: datetime) -> float:
    expiry = datetime.strptime(pos.expiry_date, "%Y-%m-%d")
    t_years = max((expiry - today).days / 365.0, 1e-6)
    if pos.structure == "bull_put_spread":
        bp = BullPutSpread(spot_at_open=pos.spot_at_open, k_short_put=pos.k_short_put,
                           k_long_put=pos.k_long_put, t_years=t_years,
                           sigma=iv_put, r=spec.pricing.risk_free_rate)
        return bull_put_spread_mtm(bp, spot, iv_put, t_years, spec.pricing.risk_free_rate)
    elif pos.structure == "iron_condor":
        from core.options.strategies.spreads import BearCallSpread, bear_call_spread_mtm
        bp = BullPutSpread(spot_at_open=pos.spot_at_open, k_short_put=pos.k_short_put,
                           k_long_put=pos.k_long_put, t_years=t_years,
                           sigma=iv_put, r=spec.pricing.risk_free_rate)
        bc = BearCallSpread(spot_at_open=pos.spot_at_open, k_short_call=pos.k_short_call,
                            k_long_call=pos.k_long_call, t_years=t_years,
                            sigma=iv_call, r=spec.pricing.risk_free_rate)
        return (bull_put_spread_mtm(bp, spot, iv_put, t_years, spec.pricing.risk_free_rate)
                + bear_call_spread_mtm(bc, spot, iv_call, t_years, spec.pricing.risk_free_rate))
    raise ValueError(pos.structure)


def _expiry_payoff_per_share(pos: OpenPosition, spot_expiry: float) -> float:
    if pos.structure == "bull_put_spread":
        return bull_put_spread_expiry_payoff(pos.k_short_put, pos.k_long_put, spot_expiry)
    if pos.structure == "iron_condor":
        return iron_condor_expiry_payoff(
            pos.k_long_put, pos.k_short_put, pos.k_short_call, pos.k_long_call, spot_expiry,
        )
    raise ValueError(pos.structure)


# -- Public API: init / observe ---------------------------------------------

def init_run(spec: StrategySpec, base_dir: Path = PAPER_DIR_DEFAULT,
             start_date: str | None = None) -> RunState:
    """Bootstrap a fresh paper run. Idempotent — reuses existing if found."""
    run_dir = base_dir / spec.candidate_id
    spec_path = run_dir / "spec.yaml"
    manifest_path = run_dir / "manifest.json"

    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text())
        if existing.get("spec_hash") != spec.spec_hash():
            raise RuntimeError(
                f"Run {spec.candidate_id} exists with DIFFERENT spec_hash:\n"
                f"  existing: {existing.get('spec_hash')}\n"
                f"  current:  {spec.spec_hash()}\n"
                f"Use a different candidate_id or delete the run dir."
            )
        return _state_from_manifest(existing)

    run_dir.mkdir(parents=True, exist_ok=True)
    sh = write_spec(spec, spec_path)
    start = start_date or datetime.now().strftime("%Y-%m-%d")
    state = RunState(
        candidate_id=spec.candidate_id, spec_hash=sh, spec_path=str(spec_path),
        start_date=start, cash=spec.initial_nav, nav_initial=spec.initial_nav,
        nav_current=spec.initial_nav, nav_high_water=spec.initial_nav,
        rolling_window_max=spec.overlay.dd_halt_window,
    )
    _persist(state, run_dir)
    print(f"[init] {spec.candidate_id} created at {run_dir}")
    print(f"[init] spec_hash: {sh}")
    print(f"[init] start_date: {start} | initial NAV: ${spec.initial_nav:,.2f}")
    return state


def _state_from_manifest(d: dict) -> RunState:
    positions = [OpenPosition(**p) for p in d.get("open_positions", [])]
    state = RunState(
        candidate_id=d["candidate_id"], spec_hash=d["spec_hash"],
        spec_path=d["spec_path"], start_date=d["start_date"],
        cash=d["cash"], nav_initial=d["nav_initial"],
        nav_current=d["nav_current"], nav_high_water=d["nav_high_water"],
        open_positions=positions,
        n_observe_days=d.get("n_observe_days", 0),
        last_observe_date=d.get("last_observe_date"),
        last_observe_at_utc=d.get("last_observe_at_utc"),
        rolling_nav_window=d.get("rolling_nav_window", []),
        rolling_window_max=d.get("rolling_window_max", 21),
        closed_positions_count=d.get("closed_positions_count", 0),
        realized_pnl_cumulative=d.get("realized_pnl_cumulative", 0.0),
    )
    return state


def _persist(state: RunState, run_dir: Path) -> None:
    manifest = {
        **{k: v for k, v in asdict(state).items() if k != "open_positions"},
        "open_positions": [asdict(p) for p in state.open_positions],
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))


def _append_csv(path: Path, row: dict) -> None:
    new_file = not path.exists()
    df = pd.DataFrame([row])
    if new_file:
        df.to_csv(path, index=False)
    else:
        df.to_csv(path, mode="a", header=False, index=False)


def observe(spec: StrategySpec, today_dt: datetime, spot: float, vix: float,
            spy_history_close: pd.Series,
            base_dir: Path = PAPER_DIR_DEFAULT) -> dict:
    """Run one daily observation. Returns dict with summary."""
    run_dir = base_dir / spec.candidate_id
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise RuntimeError(f"Run {spec.candidate_id} not initialized. Run init_run() first.")
    state = _state_from_manifest(json.loads(manifest_path.read_text()))
    today_str = today_dt.strftime("%Y-%m-%d")
    if state.last_observe_date == today_str:
        print(f"[observe] {spec.candidate_id} already observed today ({today_str}); skipping.")
        return {"status": "skipped_already_today"}

    iv_put, iv_call = _spec_iv_per_leg(spec, vix)
    events: list[str] = []

    # 1) Process expirations + overlay closes
    still_open: list[OpenPosition] = []
    for pos in state.open_positions:
        expiry_dt = datetime.strptime(pos.expiry_date, "%Y-%m-%d")
        dte = (expiry_dt - today_dt).days
        if dte <= 0:
            payoff = _expiry_payoff_per_share(pos, spot)
            pnl_per_share = pos.credit_per_share - payoff
            pnl_total = pnl_per_share * 100.0 * pos.contracts
            state.cash -= payoff * 100.0 * pos.contracts
            state.cash += pos.cash_collateral
            state.realized_pnl_cumulative += pnl_total
            state.closed_positions_count += 1
            reason = ("expiry_full_loss" if payoff >= pos.width_per_share - 1e-6
                      else "expiry_partial_loss" if payoff > 0 else "expiry_worthless")
            _append_csv(run_dir / "trade_log.csv", {
                "date": today_str, "event": "close", "structure": pos.structure,
                "reason": reason, "contracts": pos.contracts,
                "credit_per_share": pos.credit_per_share, "close_value": payoff,
                "pnl_total": pnl_total,
            })
            events.append(f"closed:{reason}:${pnl_total:+.2f}")
            continue

        mtm = _mtm_per_share(spec, pos, spot, iv_put, iv_call, today_dt)
        unrealized_pnl_per_share = pos.credit_per_share - mtm
        # Stop loss
        if unrealized_pnl_per_share <= -spec.overlay.stop_loss_frac * pos.max_loss_per_share:
            pnl = unrealized_pnl_per_share * 100.0 * pos.contracts
            state.cash -= mtm * 100.0 * pos.contracts
            state.cash += pos.cash_collateral
            state.realized_pnl_cumulative += pnl
            state.closed_positions_count += 1
            _append_csv(run_dir / "trade_log.csv", {
                "date": today_str, "event": "close", "structure": pos.structure,
                "reason": "stop_loss", "contracts": pos.contracts,
                "credit_per_share": pos.credit_per_share, "close_value": mtm,
                "pnl_total": pnl,
            })
            events.append(f"closed:stop_loss:${pnl:+.2f}")
            continue
        # Profit target
        if unrealized_pnl_per_share >= spec.overlay.early_tp_frac * pos.credit_per_share:
            pnl = unrealized_pnl_per_share * 100.0 * pos.contracts
            state.cash -= mtm * 100.0 * pos.contracts
            state.cash += pos.cash_collateral
            state.realized_pnl_cumulative += pnl
            state.closed_positions_count += 1
            _append_csv(run_dir / "trade_log.csv", {
                "date": today_str, "event": "close", "structure": pos.structure,
                "reason": "early_tp", "contracts": pos.contracts,
                "credit_per_share": pos.credit_per_share, "close_value": mtm,
                "pnl_total": pnl,
            })
            events.append(f"closed:early_tp:${pnl:+.2f}")
            continue
        # Time stop
        if dte <= spec.overlay.time_stop_dte:
            pnl = unrealized_pnl_per_share * 100.0 * pos.contracts
            state.cash -= mtm * 100.0 * pos.contracts
            state.cash += pos.cash_collateral
            state.realized_pnl_cumulative += pnl
            state.closed_positions_count += 1
            _append_csv(run_dir / "trade_log.csv", {
                "date": today_str, "event": "close", "structure": pos.structure,
                "reason": "time_stop", "contracts": pos.contracts,
                "credit_per_share": pos.credit_per_share, "close_value": mtm,
                "pnl_total": pnl,
            })
            events.append(f"closed:time_stop:${pnl:+.2f}")
            continue
        still_open.append(pos)
    state.open_positions = still_open

    # 2) NAV mark-to-market
    unrealized = 0.0
    collateral = sum(p.cash_collateral for p in state.open_positions)
    for pos in state.open_positions:
        mtm = _mtm_per_share(spec, pos, spot, iv_put, iv_call, today_dt)
        unrealized += (pos.credit_per_share - mtm) * 100.0 * pos.contracts
    nav_today = state.cash + collateral + unrealized
    state.nav_current = nav_today
    state.nav_high_water = max(state.nav_high_water, nav_today)
    state.rolling_nav_window.append(nav_today)
    if len(state.rolling_nav_window) > state.rolling_window_max:
        state.rolling_nav_window.pop(0)
    rolling_dd = (max(state.rolling_nav_window) - nav_today) / max(state.rolling_nav_window)

    # 3) Decide entry
    opened = False
    if _is_last_bday_of_month(today_dt) and not state.open_positions:
        if vix < spec.overlay.vix_halt_hard and rolling_dd <= spec.overlay.dd_halt_pct:
            if _vol_regime_go(spec, vix, spy_history_close):
                pos = _open_position(spec, today_dt, spot, vix, iv_put, iv_call,
                                     nav_today, state.cash)
                if pos is not None:
                    state.cash -= pos.cash_collateral
                    state.cash += pos.credit_per_share * 100.0 * pos.contracts
                    state.open_positions.append(pos)
                    opened = True
                    _append_csv(run_dir / "trade_log.csv", {
                        "date": today_str, "event": "open", "structure": pos.structure,
                        "reason": "monthly_entry", "contracts": pos.contracts,
                        "credit_per_share": pos.credit_per_share, "close_value": None,
                        "pnl_total": None,
                    })
                    events.append(f"opened:{pos.structure}:credit=${pos.credit_per_share:.2f}/sh×{pos.contracts}")

    # 4) Persist
    state.n_observe_days += 1
    state.last_observe_date = today_str
    state.last_observe_at_utc = datetime.utcnow().isoformat() + "Z"

    _append_csv(run_dir / "daily_nav.csv", {
        "date": today_str, "nav": nav_today, "spot": spot, "vix": vix,
        "iv_put": iv_put, "iv_call": iv_call, "cash": state.cash,
        "collateral": collateral, "unrealized_pnl": unrealized,
        "rolling_dd": rolling_dd, "n_open": len(state.open_positions),
        "opened_today": opened, "events": "|".join(events) if events else "",
    })
    _persist(state, run_dir)

    return {
        "status": "observed", "candidate_id": spec.candidate_id,
        "as_of_date": today_str, "n_observe_days": state.n_observe_days,
        "nav": nav_today, "rolling_dd": rolling_dd,
        "open_positions": len(state.open_positions),
        "cum_pnl": state.realized_pnl_cumulative + unrealized,
        "events": events,
    }
