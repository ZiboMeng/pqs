"""Provider-neutral option contract, quote, and chain domain models."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Protocol, runtime_checkable


class OptionRight(StrEnum):
    CALL = "CALL"
    PUT = "PUT"


class ExerciseStyle(StrEnum):
    AMERICAN = "AMERICAN"
    EUROPEAN = "EUROPEAN"


class QuoteQualityError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class OptionContract:
    contract_id: str
    occ_symbol: str
    underlying: str
    expiry: date
    strike: float
    right: OptionRight
    multiplier: int = 100
    exercise_style: ExerciseStyle = ExerciseStyle.AMERICAN
    settlement: str = "PHYSICAL"

    def __post_init__(self) -> None:
        if not self.contract_id.strip() or not self.occ_symbol.strip():
            raise ValueError("contract_id and occ_symbol are required")
        object.__setattr__(self, "underlying", self.underlying.strip().upper())
        if not self.underlying:
            raise ValueError("underlying is required")
        if not math.isfinite(self.strike) or self.strike <= 0:
            raise ValueError("strike must be finite and positive")
        if self.multiplier <= 0:
            raise ValueError("multiplier must be positive")


@dataclass(frozen=True, slots=True)
class OptionQuote:
    contract: OptionContract
    bid: float
    ask: float
    bid_size: int
    ask_size: int
    quote_time: datetime
    received_time: datetime
    underlying_price: float
    implied_volatility: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    open_interest: int | None = None
    volume: int | None = None

    def __post_init__(self) -> None:
        for name in ("bid", "ask", "underlying_price"):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        if self.underlying_price <= 0:
            raise ValueError("underlying_price must be positive")
        if self.bid_size < 0 or self.ask_size < 0:
            raise ValueError("quote sizes must be non-negative")
        for name in ("quote_time", "received_time"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware UTC")
            if value.utcoffset() != timedelta(0):
                raise ValueError(f"{name} must be normalized to UTC")
        if self.received_time < self.quote_time:
            raise ValueError("received_time cannot precede quote_time")

    @property
    def midpoint(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    def quality_reasons(
        self,
        *,
        now_utc: datetime,
        max_age: timedelta,
        max_relative_spread: float = 0.50,
    ) -> tuple[str, ...]:
        if now_utc.tzinfo is None or now_utc.utcoffset() != timedelta(0):
            raise ValueError("now_utc must be timezone-aware UTC")
        reasons: list[str] = []
        if self.ask < self.bid:
            reasons.append("CROSSED_MARKET")
        if self.bid <= 0 or self.ask <= 0:
            reasons.append("NON_POSITIVE_TWO_SIDED_MARKET")
        if self.bid_size == 0 or self.ask_size == 0:
            reasons.append("ZERO_DISPLAYED_SIZE")
        if now_utc - self.quote_time > max_age:
            reasons.append("STALE_QUOTE")
        if self.quote_time > now_utc:
            reasons.append("FUTURE_QUOTE_TIME")
        if self.midpoint > 0 and self.spread / self.midpoint > max_relative_spread:
            reasons.append("WIDE_MARKET")
        if self.contract.expiry < now_utc.date():
            reasons.append("EXPIRED_CONTRACT")
        return tuple(reasons)

    def require_tradeable(
        self,
        *,
        now_utc: datetime,
        max_age: timedelta,
        max_relative_spread: float = 0.50,
    ) -> None:
        reasons = self.quality_reasons(
            now_utc=now_utc,
            max_age=max_age,
            max_relative_spread=max_relative_spread,
        )
        if reasons:
            raise QuoteQualityError(",".join(reasons))


@dataclass(frozen=True, slots=True)
class OptionChain:
    underlying: str
    provider: str
    as_of: datetime
    received_at: datetime
    quotes: tuple[OptionQuote, ...]
    is_synthetic: bool = False

    def __post_init__(self) -> None:
        normalized = self.underlying.strip().upper()
        object.__setattr__(self, "underlying", normalized)
        if not normalized or not self.provider.strip():
            raise ValueError("underlying and provider are required")
        for timestamp in (self.as_of, self.received_at):
            if timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0):
                raise ValueError("chain timestamps must be normalized to UTC")
        if self.received_at < self.as_of:
            raise ValueError("received_at cannot precede as_of")
        if any(quote.contract.underlying != normalized for quote in self.quotes):
            raise ValueError("every quote must belong to the chain underlying")

    def tradeable_quotes(
        self,
        *,
        now_utc: datetime | None = None,
        max_age: timedelta = timedelta(seconds=30),
        max_relative_spread: float = 0.50,
    ) -> tuple[OptionQuote, ...]:
        now = datetime.now(UTC) if now_utc is None else now_utc
        return tuple(
            quote
            for quote in self.quotes
            if not quote.quality_reasons(
                now_utc=now,
                max_age=max_age,
                max_relative_spread=max_relative_spread,
            )
        )


@runtime_checkable
class OptionsDataProvider(Protocol):
    """A real provider must preserve event time and local receive time."""

    @property
    def provider_name(self) -> str: ...

    def get_chain(self, underlying: str, *, as_of: datetime) -> OptionChain: ...
