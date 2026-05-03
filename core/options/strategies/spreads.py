"""Multi-leg spread combinations for synthetic option backtests.

Layered on top of `core.options.pricing.black_scholes` (single-leg
pricing primitives). This module handles:
  - Net credit / debit assembly across legs
  - Max loss / max profit / breakeven computation
  - Cash collateral required (defined-risk = max_loss; naked = strike*100)
  - At-expiry payoff under arbitrary spot

All prices are PER 1 SHARE. Multiply by 100 for per-contract dollars.
All sizes are PER 1 CONTRACT (= 100 shares of underlying exposure).

Conventions:
  - Short legs are SOLD (we collect premium), Long legs are BOUGHT.
  - Net credit > 0 means we received premium upfront (credit spread).
  - For credit spreads, max_loss = (strike_width - net_credit), max_profit = net_credit.
  - At-expiry P&L vs current MtM: P&L is realized when position closes;
    MtM is the running value of legs marked to current model price.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.options.pricing.black_scholes import BSInputs, put_price, call_price


# -- Single-spread descriptors ------------------------------------------------

@dataclass(frozen=True)
class BullPutSpread:
    """SHORT put @ k_short_put + LONG put @ k_long_put (k_long < k_short)."""
    spot_at_open: float
    k_short_put: float
    k_long_put: float
    t_years: float
    sigma: float
    r: float = 0.045


@dataclass(frozen=True)
class BearCallSpread:
    """SHORT call @ k_short_call + LONG call @ k_long_call (k_long > k_short)."""
    spot_at_open: float
    k_short_call: float
    k_long_call: float
    t_years: float
    sigma: float
    r: float = 0.045


@dataclass(frozen=True)
class IronCondor:
    """Bull put spread + bear call spread on same underlying / expiration."""
    spot_at_open: float
    k_short_put: float
    k_long_put: float
    k_short_call: float
    k_long_call: float
    t_years: float
    sigma: float
    r: float = 0.045


# -- Spread metrics at open (entry credit + max loss + max profit) -----------

@dataclass(frozen=True)
class SpreadMetrics:
    net_credit_per_share: float       # collected per share at open (>0 for credit spread)
    max_loss_per_share: float         # worst-case loss per share at expiry
    max_profit_per_share: float       # best-case profit per share at expiry (= net credit for credit)
    breakeven_low: float | None       # below this, the put side is ITM enough to lose money
    breakeven_high: float | None      # above this, the call side loses
    width_per_share: float            # strike width (defines collateral)


def _put(spot: float, k: float, t: float, sigma: float, r: float) -> float:
    return put_price(BSInputs(spot=spot, strike=k, t_years=t, sigma=sigma, r=r))


def _call(spot: float, k: float, t: float, sigma: float, r: float) -> float:
    return call_price(BSInputs(spot=spot, strike=k, t_years=t, sigma=sigma, r=r))


def bull_put_spread_metrics(s: BullPutSpread) -> SpreadMetrics:
    if s.k_long_put >= s.k_short_put:
        raise ValueError(f"BullPutSpread: long put strike ({s.k_long_put}) "
                         f"must be below short put strike ({s.k_short_put})")
    short_p = _put(s.spot_at_open, s.k_short_put, s.t_years, s.sigma, s.r)
    long_p  = _put(s.spot_at_open, s.k_long_put,  s.t_years, s.sigma, s.r)
    net_credit = short_p - long_p
    width = s.k_short_put - s.k_long_put
    max_loss = max(width - net_credit, 0.0)
    return SpreadMetrics(
        net_credit_per_share=net_credit,
        max_loss_per_share=max_loss,
        max_profit_per_share=net_credit,
        breakeven_low=s.k_short_put - net_credit,
        breakeven_high=None,
        width_per_share=width,
    )


def bear_call_spread_metrics(s: BearCallSpread) -> SpreadMetrics:
    if s.k_long_call <= s.k_short_call:
        raise ValueError(f"BearCallSpread: long call strike ({s.k_long_call}) "
                         f"must be above short call strike ({s.k_short_call})")
    short_c = _call(s.spot_at_open, s.k_short_call, s.t_years, s.sigma, s.r)
    long_c  = _call(s.spot_at_open, s.k_long_call,  s.t_years, s.sigma, s.r)
    net_credit = short_c - long_c
    width = s.k_long_call - s.k_short_call
    max_loss = max(width - net_credit, 0.0)
    return SpreadMetrics(
        net_credit_per_share=net_credit,
        max_loss_per_share=max_loss,
        max_profit_per_share=net_credit,
        breakeven_low=None,
        breakeven_high=s.k_short_call + net_credit,
        width_per_share=width,
    )


def iron_condor_metrics(s: IronCondor) -> SpreadMetrics:
    if not (s.k_long_put < s.k_short_put < s.k_short_call < s.k_long_call):
        raise ValueError(
            "IronCondor: strikes must be ordered "
            "k_long_put < k_short_put < k_short_call < k_long_call; "
            f"got {s.k_long_put}/{s.k_short_put}/{s.k_short_call}/{s.k_long_call}"
        )
    bull = bull_put_spread_metrics(BullPutSpread(
        spot_at_open=s.spot_at_open, k_short_put=s.k_short_put,
        k_long_put=s.k_long_put, t_years=s.t_years, sigma=s.sigma, r=s.r,
    ))
    bear = bear_call_spread_metrics(BearCallSpread(
        spot_at_open=s.spot_at_open, k_short_call=s.k_short_call,
        k_long_call=s.k_long_call, t_years=s.t_years, sigma=s.sigma, r=s.r,
    ))
    net_credit = bull.net_credit_per_share + bear.net_credit_per_share
    # Iron condor: at expiry only ONE side can be ITM (spot can't be both
    # below put strikes and above call strikes simultaneously). So max
    # loss = max(put_side_max_loss, call_side_max_loss) using NET credit
    # (not per-side credit). Equivalently: max(width_put, width_call) - net_credit.
    width = max(bull.width_per_share, bear.width_per_share)
    max_loss = max(width - net_credit, 0.0)
    return SpreadMetrics(
        net_credit_per_share=net_credit,
        max_loss_per_share=max_loss,
        max_profit_per_share=net_credit,
        breakeven_low=s.k_short_put - net_credit,
        breakeven_high=s.k_short_call + net_credit,
        width_per_share=width,
    )


# -- Mark-to-market (current value of spread, given current spot/iv/dte) ------

def bull_put_spread_mtm(s: BullPutSpread, spot_now: float, sigma_now: float,
                        t_now: float, r_now: float | None = None) -> float:
    """Cost-to-close per share = MtM(short)*-1 + MtM(long)*+1, but for
    a credit spread we owe MtM(short_p) - MtM(long_p). At expiry this
    equals max(K_short - spot, 0) - max(K_long - spot, 0)."""
    r = r_now if r_now is not None else s.r
    short_p = _put(spot_now, s.k_short_put, t_now, sigma_now, r)
    long_p  = _put(spot_now, s.k_long_put,  t_now, sigma_now, r)
    return short_p - long_p


def bear_call_spread_mtm(s: BearCallSpread, spot_now: float, sigma_now: float,
                         t_now: float, r_now: float | None = None) -> float:
    r = r_now if r_now is not None else s.r
    short_c = _call(spot_now, s.k_short_call, t_now, sigma_now, r)
    long_c  = _call(spot_now, s.k_long_call,  t_now, sigma_now, r)
    return short_c - long_c


def iron_condor_mtm(s: IronCondor, spot_now: float, sigma_now: float,
                    t_now: float, r_now: float | None = None) -> float:
    r = r_now if r_now is not None else s.r
    bull = BullPutSpread(spot_at_open=s.spot_at_open, k_short_put=s.k_short_put,
                         k_long_put=s.k_long_put, t_years=s.t_years, sigma=s.sigma, r=s.r)
    bear = BearCallSpread(spot_at_open=s.spot_at_open, k_short_call=s.k_short_call,
                          k_long_call=s.k_long_call, t_years=s.t_years, sigma=s.sigma, r=s.r)
    return bull_put_spread_mtm(bull, spot_now, sigma_now, t_now, r) \
         + bear_call_spread_mtm(bear, spot_now, sigma_now, t_now, r)


# -- At-expiry payoff (deterministic, no model) ------------------------------

def bull_put_spread_expiry_payoff(k_short: float, k_long: float, spot_at_expiry: float) -> float:
    """At expiry, value of the SHORT side of the spread (positive = we owe).
    P&L = net_credit - this_value."""
    short_p_value = max(k_short - spot_at_expiry, 0.0)
    long_p_value = max(k_long - spot_at_expiry, 0.0)
    return short_p_value - long_p_value


def bear_call_spread_expiry_payoff(k_short: float, k_long: float, spot_at_expiry: float) -> float:
    short_c_value = max(spot_at_expiry - k_short, 0.0)
    long_c_value = max(spot_at_expiry - k_long, 0.0)
    return short_c_value - long_c_value


def iron_condor_expiry_payoff(
    k_long_put: float, k_short_put: float,
    k_short_call: float, k_long_call: float,
    spot_at_expiry: float,
) -> float:
    return (bull_put_spread_expiry_payoff(k_short_put, k_long_put, spot_at_expiry)
            + bear_call_spread_expiry_payoff(k_short_call, k_long_call, spot_at_expiry))
