"""Black-Scholes pricing primitives for synthetic option backtests.

Phase 1 free-path: option chain data is paid; we synthesize prices from
SPY spot + VIX (as IV proxy) + risk-free rate + DTE. This is a
well-established proxy in academic literature for pre-paid-data
prototyping. Production switchover to real chain (CBOE / Polygon) is a
Phase 2 decision after Phase 1.4 viability memo.

Key approximations vs real chain:
- IV term structure (VIX = 30d at-the-money implied vol) is flat across
  strikes/expirations — IGNORES the volatility skew (puts trade higher
  IV than calls; deep-OTM higher than ATM). Skew adjustments are a
  Phase 2+ refinement; for VRP magnitude the flat-IV assumption is
  conservative on the put side (real put IV > VIX => real premium >
  synthetic).
- No bid-ask spread or fill slippage modeled here. Production will
  haircut. For Phase 1 we apply a flat 0.10 vol-point haircut
  separately.
- No early-exercise premium for American options (immaterial for
  short-DTE puts on a non-dividend ETF; SPY div is small enough to
  ignore in Phase 1).
"""
from __future__ import annotations

from dataclasses import dataclass
import math


# Standard normal CDF via erf (no scipy dep needed for this primitive)
def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


@dataclass(frozen=True)
class BSInputs:
    spot: float        # underlying price S
    strike: float      # strike K
    t_years: float     # time to expiration in years (e.g., 30/365)
    sigma: float       # annualized volatility (e.g., 0.20 for 20%)
    r: float           # risk-free rate (e.g., 0.045 for 4.5%)
    q: float = 0.0     # dividend yield (default 0)


@dataclass(frozen=True)
class BSGreeks:
    price: float
    delta: float
    gamma: float
    vega: float        # per 1.00 change in sigma; divide by 100 for per-vol-point
    theta_per_day: float


def _d1_d2(inp: BSInputs) -> tuple[float, float]:
    if inp.t_years <= 0 or inp.sigma <= 0 or inp.spot <= 0 or inp.strike <= 0:
        raise ValueError(f"BS inputs degenerate: {inp}")
    vol_t = inp.sigma * math.sqrt(inp.t_years)
    d1 = (math.log(inp.spot / inp.strike) + (inp.r - inp.q + 0.5 * inp.sigma ** 2) * inp.t_years) / vol_t
    d2 = d1 - vol_t
    return d1, d2


def put_price(inp: BSInputs) -> float:
    """European put price (no early-exercise premium)."""
    d1, d2 = _d1_d2(inp)
    return (inp.strike * math.exp(-inp.r * inp.t_years) * _norm_cdf(-d2)
            - inp.spot * math.exp(-inp.q * inp.t_years) * _norm_cdf(-d1))


def call_price(inp: BSInputs) -> float:
    d1, d2 = _d1_d2(inp)
    return (inp.spot * math.exp(-inp.q * inp.t_years) * _norm_cdf(d1)
            - inp.strike * math.exp(-inp.r * inp.t_years) * _norm_cdf(d2))


def put_greeks(inp: BSInputs) -> BSGreeks:
    """Price + delta/gamma/vega/theta. Sign convention: short put => collect premium,
    delta of LONG put is negative; SHORT put delta is positive."""
    d1, d2 = _d1_d2(inp)
    sqrt_t = math.sqrt(inp.t_years)
    pdf_d1 = math.exp(-0.5 * d1 ** 2) / math.sqrt(2 * math.pi)

    price = put_price(inp)
    delta_long_put = math.exp(-inp.q * inp.t_years) * (_norm_cdf(d1) - 1.0)
    gamma = math.exp(-inp.q * inp.t_years) * pdf_d1 / (inp.spot * inp.sigma * sqrt_t)
    vega = inp.spot * math.exp(-inp.q * inp.t_years) * pdf_d1 * sqrt_t  # per 1.00 sigma
    # Theta (long put), per year. Convert to per-day by /365.
    theta_per_year = (
        -(inp.spot * pdf_d1 * inp.sigma * math.exp(-inp.q * inp.t_years)) / (2 * sqrt_t)
        + inp.r * inp.strike * math.exp(-inp.r * inp.t_years) * _norm_cdf(-d2)
        - inp.q * inp.spot * math.exp(-inp.q * inp.t_years) * _norm_cdf(-d1)
    )
    return BSGreeks(
        price=price,
        delta=delta_long_put,
        gamma=gamma,
        vega=vega,
        theta_per_day=theta_per_year / 365.0,
    )
