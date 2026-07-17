"""Portfolio option Greeks aggregation and independent risk veto."""

from __future__ import annotations

import math
from dataclasses import dataclass

from core.options.data import OptionContract


@dataclass(frozen=True, slots=True)
class PositionGreeks:
    contract: OptionContract
    signed_contracts: int
    underlying_price: float
    delta: float
    gamma: float
    vega: float
    theta: float
    defined_max_loss: float

    def __post_init__(self) -> None:
        values = (
            self.underlying_price,
            self.delta,
            self.gamma,
            self.vega,
            self.theta,
            self.defined_max_loss,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("all position risk values must be finite")
        if self.underlying_price <= 0 or self.defined_max_loss < 0:
            raise ValueError("underlying must be positive and max loss non-negative")


@dataclass(frozen=True, slots=True)
class PortfolioGreeks:
    dollar_delta: float
    dollar_gamma: float
    vega: float
    theta: float
    defined_max_loss: float


def aggregate_greeks(positions: tuple[PositionGreeks, ...]) -> PortfolioGreeks:
    dollar_delta = dollar_gamma = vega = theta = max_loss = 0.0
    for position in positions:
        scale = position.signed_contracts * position.contract.multiplier
        dollar_delta += position.delta * position.underlying_price * scale
        dollar_gamma += (
            position.gamma * position.underlying_price**2 * scale / 100.0
        )
        vega += position.vega * scale
        theta += position.theta * scale
        max_loss += position.defined_max_loss
    return PortfolioGreeks(dollar_delta, dollar_gamma, vega, theta, max_loss)


@dataclass(frozen=True, slots=True)
class OptionsRiskLimits:
    max_abs_dollar_delta_fraction: float = 0.20
    max_abs_dollar_gamma_fraction: float = 0.10
    max_abs_vega_fraction: float = 0.10
    max_daily_theta_loss_fraction: float = 0.01
    max_defined_loss_fraction: float = 0.05


@dataclass(frozen=True, slots=True)
class OptionsRiskDecision:
    approved: bool
    reason_codes: tuple[str, ...]
    aggregate: PortfolioGreeks


def evaluate_options_risk(
    positions: tuple[PositionGreeks, ...],
    *,
    equity: float,
    limits: OptionsRiskLimits,
) -> OptionsRiskDecision:
    if not math.isfinite(equity) or equity <= 0:
        raise ValueError("equity must be finite and positive")
    aggregate = aggregate_greeks(positions)
    reasons: list[str] = []
    if abs(aggregate.dollar_delta) > equity * limits.max_abs_dollar_delta_fraction:
        reasons.append("OPTIONS_DELTA_LIMIT")
    if abs(aggregate.dollar_gamma) > equity * limits.max_abs_dollar_gamma_fraction:
        reasons.append("OPTIONS_GAMMA_LIMIT")
    if abs(aggregate.vega) > equity * limits.max_abs_vega_fraction:
        reasons.append("OPTIONS_VEGA_LIMIT")
    if aggregate.theta < -equity * limits.max_daily_theta_loss_fraction:
        reasons.append("OPTIONS_THETA_LIMIT")
    if aggregate.defined_max_loss > equity * limits.max_defined_loss_fraction:
        reasons.append("OPTIONS_MAX_LOSS_LIMIT")
    return OptionsRiskDecision(not reasons, tuple(reasons), aggregate)
