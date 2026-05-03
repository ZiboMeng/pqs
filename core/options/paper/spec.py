"""Frozen strategy spec for options forward paper trading.

Analogous to `core/research/forward/manifest_schema.py` but simpler:
options strategies are deterministic given (VIX, SPY, spec params),
so no factor-input hashing is needed. Only the yaml spec hash anchors
reproducibility.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class OverlayParams:
    stop_loss_frac: float = 0.80     # close when MtM loss >= this × max_loss
    early_tp_frac: float = 0.50      # close when MtM profit >= this × max_profit
    time_stop_dte: int = 7
    vix_halt_hard: float = 40.0
    dd_halt_pct: float = 0.10
    dd_halt_window: int = 21


@dataclass(frozen=True)
class VolRegimeFilterParams:
    enabled: bool = True
    vix_min: float = 12.0
    vix_max: float = 25.0
    require_positive_vrp: bool = True
    rv_window: int = 21              # SPY 21d realized vol for VRP gap


@dataclass(frozen=True)
class PricingParams:
    put_skew_factor: float = 1.30    # put IV / VIX (8% OTM empirical)
    call_skew_factor: float = 0.75   # call IV / VIX (8% OTM empirical)
    risk_free_rate: float = 0.045
    iv_haircut_vol_pts: float = 0.10


@dataclass(frozen=True)
class StrategySpec:
    candidate_id: str
    strategy_type: str               # "bull_put_spread" | "iron_condor"
    underlying: str                  # "SPY"
    short_otm_pct: float             # 0.08
    long_otm_pct: float              # 0.10
    dte_open_days: int               # 30 calendar days
    risk_per_trade_pct: float        # 0.02 (2% NAV)
    overlay: OverlayParams
    vol_regime_filter: VolRegimeFilterParams
    pricing: PricingParams
    initial_nav: float
    created_at: str                  # YYYY-MM-DD

    def to_canonical_yaml(self) -> str:
        """Deterministic yaml dump for hashing."""
        d = self.to_dict()
        return yaml.dump(d, sort_keys=True, default_flow_style=False, indent=2)

    def spec_hash(self) -> str:
        return hashlib.sha256(self.to_canonical_yaml().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "strategy_type": self.strategy_type,
            "underlying": self.underlying,
            "short_otm_pct": self.short_otm_pct,
            "long_otm_pct": self.long_otm_pct,
            "dte_open_days": self.dte_open_days,
            "risk_per_trade_pct": self.risk_per_trade_pct,
            "initial_nav": self.initial_nav,
            "created_at": self.created_at,
            "overlay": {
                "stop_loss_frac": self.overlay.stop_loss_frac,
                "early_tp_frac": self.overlay.early_tp_frac,
                "time_stop_dte": self.overlay.time_stop_dte,
                "vix_halt_hard": self.overlay.vix_halt_hard,
                "dd_halt_pct": self.overlay.dd_halt_pct,
                "dd_halt_window": self.overlay.dd_halt_window,
            },
            "vol_regime_filter": {
                "enabled": self.vol_regime_filter.enabled,
                "vix_min": self.vol_regime_filter.vix_min,
                "vix_max": self.vol_regime_filter.vix_max,
                "require_positive_vrp": self.vol_regime_filter.require_positive_vrp,
                "rv_window": self.vol_regime_filter.rv_window,
            },
            "pricing": {
                "put_skew_factor": self.pricing.put_skew_factor,
                "call_skew_factor": self.pricing.call_skew_factor,
                "risk_free_rate": self.pricing.risk_free_rate,
                "iv_haircut_vol_pts": self.pricing.iv_haircut_vol_pts,
            },
        }


def load_spec(yaml_path: Path) -> StrategySpec:
    raw = yaml.safe_load(yaml_path.read_text())
    return StrategySpec(
        candidate_id=raw["candidate_id"],
        strategy_type=raw["strategy_type"],
        underlying=raw["underlying"],
        short_otm_pct=float(raw["short_otm_pct"]),
        long_otm_pct=float(raw["long_otm_pct"]),
        dte_open_days=int(raw["dte_open_days"]),
        risk_per_trade_pct=float(raw["risk_per_trade_pct"]),
        initial_nav=float(raw["initial_nav"]),
        created_at=str(raw["created_at"]),
        overlay=OverlayParams(**raw.get("overlay", {})),
        vol_regime_filter=VolRegimeFilterParams(**raw.get("vol_regime_filter", {})),
        pricing=PricingParams(**raw.get("pricing", {})),
    )


def write_spec(spec: StrategySpec, yaml_path: Path) -> str:
    """Write spec yaml + return its canonical sha256 hash."""
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text(spec.to_canonical_yaml())
    return spec.spec_hash()
