"""130/30 long-short configuration — Priority 4 (2026-05-14).

Allows per-cycle relaxation of the CLAUDE.md "long-only, no-short"
invariant. User explicit-go 2026-05-14 (priority sequence include
priority 4).

When enabled, the harness selector may produce SHORT weights up to
``max_short_pct`` (default 0.30 = 30% gross short notional). The
companion long_pct is implicit: long_pct = 1.0 + max_short_pct
(default 1.30 = 130% gross long), so gross exposure = 160% but net
exposure stays = 100%.

Borrow cost model: borrow_cost_annual default 1.0% (industry baseline
for most US large-cap stocks); per-symbol overrides available for
hard-to-borrow names. Sector overrides cover concentrated industries
(e.g., biotech / small-cap energy historically tighter borrow).

Sector + symbol short caps prevent concentrated short risk that could
amplify drawdowns past CLAUDE.md MaxDD ceilings.

This MVP ships the CONFIG SCHEMA only. Wiring into the cap_aware
selector (allowing negative weights) + daily borrow cost accrual
in BacktestEngine is deferred to the first 130/30 mining cycle when
authorized.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class LongShortConfig:
    """Per-cycle config for 130/30 long-short construction.

    enabled=False (default) → behaves as long-only (current invariant).
    enabled=True → harness selector may produce negative weights subject
    to all caps below.
    """
    enabled: bool = False

    # Gross short notional cap (fraction of NAV). 0.30 = 30% short.
    # Long notional = 1.0 + max_short_pct (so 130% long when 30% short).
    # Net exposure = 100% always.
    max_short_pct: float = 0.30

    # Per-symbol short cap (fraction of NAV). 0.05 = 5% short per stock.
    # Set lower than long cap (0.10) because concentrated short risk
    # is asymmetric (short losses are uncapped).
    per_symbol_short_cap: float = 0.05

    # Per-sector short cap (fraction of NAV gross sector short).
    # Default 0.15 = 15% short any single GICS sector.
    per_sector_short_cap: float = 0.15

    # Annual borrow cost (fraction of short notional / year).
    # Default 1.0% baseline; daily accrual = annual / 252.
    borrow_cost_annual_default: float = 0.01

    # Per-symbol borrow cost overrides (annual). Keys = symbols;
    # values = annual rate. Empty default = use default for all.
    borrow_cost_annual_per_symbol: Dict[str, float] = field(default_factory=dict)

    # Per-sector borrow cost overrides (annual). Keys = GICS sector names.
    borrow_cost_annual_per_sector: Dict[str, float] = field(default_factory=dict)

    # Symbols explicitly banned from shorting (e.g., ETFs that can't be
    # shorted by retail, or names with regulatory short-sale restrictions).
    short_blacklist: tuple[str, ...] = ()

    def __post_init__(self):
        if not 0.0 <= self.max_short_pct <= 1.0:
            raise ValueError(
                f"max_short_pct {self.max_short_pct} must be in [0, 1]"
            )
        if not 0.0 <= self.per_symbol_short_cap <= self.max_short_pct:
            raise ValueError(
                f"per_symbol_short_cap {self.per_symbol_short_cap} must be "
                f"in [0, max_short_pct={self.max_short_pct}]"
            )
        if not 0.0 <= self.per_sector_short_cap <= self.max_short_pct:
            raise ValueError(
                f"per_sector_short_cap {self.per_sector_short_cap} must be "
                f"in [0, max_short_pct={self.max_short_pct}]"
            )
        if self.borrow_cost_annual_default < 0:
            raise ValueError(
                f"borrow_cost_annual_default {self.borrow_cost_annual_default} "
                "must be non-negative"
            )
        # Sanity: if enabled=False, the other params should not be used at
        # runtime. We still allow them to be set (e.g., yaml dispatch logic
        # writes default values regardless of enabled flag).

    def daily_borrow_cost(self, symbol: str, sector: Optional[str] = None) -> float:
        """Daily borrow cost for a single short position (1 unit notional).

        Priority order: per-symbol override → per-sector override → default.
        Returns daily fraction = annual / 252.
        """
        if symbol in self.borrow_cost_annual_per_symbol:
            annual = self.borrow_cost_annual_per_symbol[symbol]
        elif sector and sector in self.borrow_cost_annual_per_sector:
            annual = self.borrow_cost_annual_per_sector[sector]
        else:
            annual = self.borrow_cost_annual_default
        return annual / 252.0

    def can_short(self, symbol: str) -> bool:
        """Check whether `symbol` may be shorted under this config."""
        if not self.enabled:
            return False
        return symbol not in self.short_blacklist


def long_only_default() -> LongShortConfig:
    """Return the long-only default (enabled=False, current invariant)."""
    return LongShortConfig(enabled=False)


def conservative_130_30() -> LongShortConfig:
    """Conservative 130/30 preset with stricter per-symbol/sector caps.

    Use for FIRST 130/30 mining cycle. Tighter caps reduce risk of
    learning structurally large short positions that violate the
    "MaxDD ≤ 20%" invariant.
    """
    return LongShortConfig(
        enabled=True,
        max_short_pct=0.30,
        per_symbol_short_cap=0.03,  # tighter: 3% (vs 5% default)
        per_sector_short_cap=0.10,  # tighter: 10% (vs 15% default)
        borrow_cost_annual_default=0.01,
        # Hard-to-borrow sector overrides
        borrow_cost_annual_per_sector={
            "Health Care": 0.015,  # biotech often tight borrow
            "Energy": 0.012,
            "Information Technology": 0.008,  # generally easier
        },
        # SQQQ/TQQQ already in main universe blacklist; here we block
        # SHORTING of inverse ETFs (which would be a long bull bet).
        short_blacklist=("SH", "PSQ", "DOG", "SQQQ", "TQQQ", "SOXL"),
    )
