"""PRD-X v2 Phase X2 §5.3.1 — NoTradeBandCalculator.

Vol/regime-conditional no-trade band widths per Leland 1999 key
insight: **"no-trade region should be LARGE when volatility is
HIGH"** (cited in PRD §0 external dependency, R3-verified
one-handed source). PRD v1 lacked this mechanic; v2 §5.3.1
explicitly added.

Pure calculator: reads ctx (realized_vol + regime state) only.
Zero panel/bar-store imports at module level (schema-purity
discipline same as decision schema X1).

API:
    calc = NoTradeBandCalculator(base_band=0.02)
    bands = calc.compute(symbol, ctx)
    # bands.enter / bands.add / bands.trim / bands.exit (all > 0)

Formula (PRD §5.3.1):
    band = base_band × vol_multiplier(realized_vol)
                     × regime_multiplier(regime)

  - vol_multiplier: monotone-increasing in realized_vol (high vol
    → wider band → less churn). Anchored at vol_anchor (~0.15
    typical S&P 500 annualized).
  - regime_multiplier: ≥ 1 always; RISK_OFF / CAUTIOUS bump band
    wider; BULL / RISK_ON / NEUTRAL are 1.0 (no penalty).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from core.regime.regime_detector import RegimeState

__all__ = ["Bands", "NoTradeBandCalculator"]


# ── dataclass ────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Bands:
    """4 per-symbol band widths for the Decision-layer no-trade region.

    All bands are non-negative widths (PRD §5.3 — "证据落在 band 内
    保持 HOLD,不生成订单"). Negative widths are meaningless and
    raise at construction.
    """
    enter: float
    add: float
    trim: float
    exit: float

    def __post_init__(self) -> None:
        for name in ("enter", "add", "trim", "exit"):
            v = getattr(self, name)
            if v < 0:
                raise ValueError(
                    f"Bands.{name}={v} — band widths must be "
                    f"non-negative")


# ── regime multipliers (PRD §5.3.1 + regime_detector RegimeState) ───
# BULL/RISK_ON/NEUTRAL = 1.0 (no widening); CAUTIOUS/RISK_OFF wider.
# Calibrated conservatively; X2 acceptance experiment may refine.
_REGIME_MULTIPLIER: Dict[RegimeState, float] = {
    RegimeState.BULL: 1.0,
    RegimeState.RISK_ON: 1.0,
    RegimeState.NEUTRAL: 1.0,
    RegimeState.CAUTIOUS: 1.5,
    RegimeState.RISK_OFF: 2.0,
}

# vol anchor: ~ S&P 500 long-run realized vol annualized
_VOL_ANCHOR = 0.15


def _vol_multiplier(realized_vol: float) -> float:
    """Linear-in-vol multiplier anchored at _VOL_ANCHOR.

    realized_vol = 0       → 1.0 (graceful)
    realized_vol = anchor  → 1.0
    realized_vol = 2×anchor → 2.0
    realized_vol = 0.5×anchor → 0.83 (still ≥ floor of 0.5)

    Monotone-increasing per Leland 1999.
    """
    v = max(0.0, float(realized_vol))
    mult = 1.0 + (v - _VOL_ANCHOR) / _VOL_ANCHOR
    return max(0.5, mult)  # floor at 0.5 to avoid band collapse


# ── calculator ───────────────────────────────────────────────────────
class NoTradeBandCalculator:
    """Compute (enter/add/trim/exit) band widths per-symbol per-bar.

    Parameters
    ----------
    base_band : float
        Baseline band width (e.g. 0.02 = 2% weight delta tolerance).
        Strictly > 0; raises otherwise.
    enter_band_mult, add_band_mult, trim_band_mult, exit_band_mult :
        Optional per-action shape multipliers (default 1.0 each).
    """

    def __init__(
        self,
        base_band: float = 0.02,
        enter_band_mult: float = 1.0,
        add_band_mult: float = 0.5,
        trim_band_mult: float = 0.5,
        exit_band_mult: float = 1.0,
    ) -> None:
        if base_band <= 0:
            raise ValueError(
                f"base_band={base_band} must be > 0 (band width)")
        self._base = float(base_band)
        self._enter_m = float(enter_band_mult)
        self._add_m = float(add_band_mult)
        self._trim_m = float(trim_band_mult)
        self._exit_m = float(exit_band_mult)

    def compute(self, symbol: str, ctx: Dict[str, Any]) -> Bands:
        """Per-symbol band widths from ctx (realized_vol + regime).

        **R18 (auditor F5 closure)**: lookup precedence for
        realized_vol — per-symbol map FIRST, then scalar fallback:

          1. ctx['realized_vol_by_symbol'][symbol] (per-symbol)
          2. ctx['realized_vol'] (scalar, was the only path pre-R18)
          3. _VOL_ANCHOR (0.15, conservative default)

        This is backward-compatible (legacy ctx with just
        'realized_vol' scalar still works) but enables overlay
        callers to thread per-symbol vol so the Leland 1999
        mechanic actually engages instead of collapsing to 1.0 at
        the anchor.
        """
        ctx = ctx or {}
        by_sym = ctx.get("realized_vol_by_symbol") or {}
        if symbol in by_sym and by_sym[symbol] is not None:
            realized_vol = by_sym[symbol]
        else:
            realized_vol = ctx.get("realized_vol", _VOL_ANCHOR)
        regime: Optional[RegimeState] = ctx.get("regime")
        if regime is None:
            regime = RegimeState.NEUTRAL

        vol_mult = _vol_multiplier(realized_vol)
        reg_mult = _REGIME_MULTIPLIER.get(regime, 1.0)
        # any out-of-set regime → conservative widen
        if regime not in _REGIME_MULTIPLIER:
            reg_mult = 1.5

        w = self._base * vol_mult * reg_mult
        return Bands(
            enter=w * self._enter_m,
            add=w * self._add_m,
            trim=w * self._trim_m,
            exit=w * self._exit_m,
        )
