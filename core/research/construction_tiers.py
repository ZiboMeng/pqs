"""PRD-2 P2.1 — construction-tier weight construction (T1 hedge).

T1 = invariant-PRESERVING 1x inverse-ETF hedge sleeve. You BUY a 1x
inverse ETF (SH / PSQ / DOG) — it is itself a LONG position, so
no-short / no-margin / long-only invariants are NOT broken:
  - every output weight stays >= 0
  - output sum == input sum (no leverage / no margin added)

This is mechanistically DISTINCT from
``core/research/long_short_config.py`` (true short / negative weights
= T2 territory, PRD-2 §6 PERMANENTLY GATED, needs user explicit-go).
T1 must NOT be routed through that schema (would conflate an
invariant-preserving hedge with an invariant-breaking short).

CLAUDE.md invariant: SQQQ permanently blacklisted; any LEVERAGED
inverse (-2x/-3x: SQQQ/SPXU/SDS/SPXS/SOXS…) is rejected. Only the
three 1x inverse ETFs the project already vetted in
``config/universe_priority5.yaml`` are allowed.

(P2.1 R2: pure construction function + config + invariant guards;
fully unit-testable in isolation, zero core-path change. Routing
``HarnessConfig.construction_tier == 'T1'`` through this — i.e.
flipping the R1 NotImplementedError — is the next step P2.1 R2-cont
with a T0 bit-identical regression on composite_evaluator.)
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

# Only the 1x inverse ETFs vetted in config/universe_priority5.yaml.
# SQQQ + every leveraged inverse stay permanently blacklisted.
_VALID_1X_INVERSE = ("SH", "PSQ", "DOG")
_EPS = 1e-12


def _check_hedge_etf(etf: str) -> None:
    if etf not in _VALID_1X_INVERSE:
        raise ValueError(
            f"hedge_etf={etf!r} not allowed. T1 permits ONLY 1x inverse "
            f"ETFs {_VALID_1X_INVERSE!r}; SQQQ + all leveraged inverse "
            f"(-2x/-3x) are permanently blacklisted (CLAUDE.md invariant)."
        )


@dataclass
class T1HedgeConfig:
    """1x inverse-ETF hedge config. Defaults = no hedge (== T0)."""

    hedge_etf: str = "SH"
    hedge_frac: float = 0.0
    max_hedge_frac: float = 0.30

    def __post_init__(self) -> None:
        _check_hedge_etf(self.hedge_etf)
        if not (0.0 < self.max_hedge_frac <= 0.5):
            raise ValueError(
                f"max_hedge_frac {self.max_hedge_frac} must be in (0, 0.5]"
            )
        if not (0.0 <= self.hedge_frac <= self.max_hedge_frac):
            raise ValueError(
                f"hedge_frac {self.hedge_frac} must be in "
                f"[0, max_hedge_frac={self.max_hedge_frac}]"
            )


def apply_t1_inverse_hedge(
    long_weights: pd.Series,
    hedge_etf: str,
    hedge_frac: float,
) -> pd.Series:
    """Overlay a 1x inverse-ETF hedge sleeve on a long-only weight
    vector. Long sleeve scaled to ``(1 - hedge_frac)``; ``hedge_frac``
    added (combined, not overwritten) into ``hedge_etf``.

    Invariant-preserving: refuses if any input weight is negative
    (that is already T2/true-short territory, not T1); output stays
    all->=0 and sum-preserving (no margin).
    """
    _check_hedge_etf(hedge_etf)
    if not (0.0 <= hedge_frac <= 1.0):
        raise ValueError(f"hedge_frac {hedge_frac} must be in [0, 1]")
    if (long_weights < -_EPS).any():
        raise ValueError(
            "apply_t1_inverse_hedge received a NEGATIVE input weight — "
            "T1 is invariant-preserving and only overlays a long hedge; "
            "negative weights are T2/true-short territory (PRD-2 §6 "
            "permanently gated)."
        )
    if hedge_frac == 0.0:
        return long_weights.copy()
    out = (long_weights * (1.0 - hedge_frac)).copy()
    out.loc[hedge_etf] = out.get(hedge_etf, 0.0) + hedge_frac
    return out


def inverse_etf_decay_return(
    index_daily_returns,
    expense_annual: float = 0.0090,
):
    """PRD-2 P2.1 R3 — 1x inverse-ETF daily-reset cost model.

    A -1x daily-reset ETF held over multiple days does NOT return
    -(cumulative index move): it compounds each day's inverse, so
    volatility / path introduces drift ("beta slippage" / volatility
    decay). Returns ``(modeled, naive_optimistic)`` so callers MUST
    report BOTH (PRD-2 §7 P2.1(c): never report only the optimistic
    leg).

    modeled = ∏(1 - r_t - expense_daily) - 1   (daily-reset compounding)
    naive   = -(∏(1 + r_t) - 1)                (pretend exact -cum move)

    decay = modeled - naive is PATH-DEPENDENT (a drag in oscillating
    markets, can be positive on a monotone trend). 1x only — leverage
    is out of scope (SQQQ/-2x/-3x permanently blacklisted).
    """
    import numpy as _np
    r = _np.asarray(list(index_daily_returns), dtype=float)
    if r.size == 0:
        return 0.0, 0.0
    exp_d = expense_annual / 252.0
    modeled = float(_np.prod(1.0 - r - exp_d) - 1.0)
    naive = float(-(_np.prod(1.0 + r) - 1.0))
    return modeled, naive


def apply_tier_overlay(
    signals: "pd.DataFrame",
    construction_tier: str,
    hedge_etf: str,
    hedge_frac: float,
) -> "pd.DataFrame":
    """Single hook evaluate_composite_spec calls after signals are
    built. T0 = IDENTITY (returns signals unchanged → bit-identical to
    the pre-tier path). T1 = overlay the 1x inverse-ETF hedge per
    rebalance (non-zero) row. T2 = permanently gated (PRD-2 §6).
    """
    if construction_tier == "T0":
        return signals
    if construction_tier == "T2":
        raise ValueError(
            "construction_tier='T2' (true short) is PERMANENTLY GATED "
            "(PRD-2 §6 / P2.4): never auto; needs user explicit-go."
        )
    if construction_tier != "T1":
        raise ValueError(
            f"unknown construction_tier {construction_tier!r}; "
            f"expected one of {_VALID_1X_INVERSE and ('T0','T1','T2')}"
        )
    # T1
    if hedge_frac == 0.0:
        return signals                       # == T0 effect (no hedge)
    _check_hedge_etf(hedge_etf)
    out = signals.copy()
    if hedge_etf not in out.columns:
        out[hedge_etf] = 0.0
    cols = out.columns

    def _row(r):
        nz = r[r != 0.0]
        if nz.empty:
            return r                          # no-trade row untouched
        h = apply_t1_inverse_hedge(nz, hedge_etf, hedge_frac)
        return h.reindex(cols).fillna(0.0)

    return out.apply(_row, axis=1)
