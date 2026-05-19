"""PRD-3 RB4 — B2 intraday deep scaffold (TCN/iTransformer/PatchTST
+ masked-SSL → frozen probe) with the MANDATORY DLinear baseline.

build round. AC (PRD-3 ralph-loop RB4): deep pipeline unit GREEN
+ **DLinear baseline 强制接入(无之结果不可信)**. The DLinear
mandate is the load-bearing piece: per Zeng et al. 2023 ("Are
Transformers Effective for Time Series Forecasting?"), simple
linear baselines beat or match many deep TS models — running deep
without DLinear next to it is uninterpretable. RB4 wires that in.

Honest scope (R4/R6/R7): masked-SSL→frozen probe ALREADY exists
(``core.research.a4_universe_guard.a4_ssl_frozen_probe_scaffold``
which delegates to ``core.ml.ssl_pretrain.pretrain_mae`` /
``MAEEncoder``). DELEGATED. The genuinely-new RB4 surface is the
DLinear baseline (the missing piece across PRD-3-A — RA4 used a
documented Ridge proxy and labeled it ``dlinear_essence_ridge``;
RB4 makes that explicit + ATTRIBUTED to Zeng et al.) + multi-TF
channel/variate stacking for the 15m/30m/60m → SSL→probe path.

Component-B gate (RB1) is ROUTED FIRST in every entry point. TCN
(Bai et al. 2018) / iTransformer / PatchTST: this scaffold builds
the CHANNEL/VARIATE-STACK and the leakage-safe pretrain hook; the
specific deep encoder choice is a configuration knob the RB5
experiment exercises. We do NOT reimplement TCN/iTransformer from
scratch here — the masked-SSL probe scaffold + DLinear baseline
are the build-round AC; B2 acceptance (deep > shallow > DLinear)
is RB5.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from core.research.a4_universe_guard import a4_ssl_frozen_probe_scaffold
from core.research.component_b_gate import (
    assert_archetype_differentiated,
    assert_component_b_prerequisites,
)

__all__ = [
    "dlinear_baseline_fit_predict",
    "build_multitf_channels",
    "B2Config",
    "b2_ssl_frozen_probe",
]

_FREQS = ("15m", "30m", "60m")


def dlinear_baseline_fit_predict(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    *,
    individual: bool = True,
    seed: int = 42,
) -> np.ndarray:
    """MANDATORY DLinear baseline (Zeng et al. 2023, AAAI: "Are
    Transformers Effective for Time Series Forecasting?").

    In Zeng's original setting DLinear = trend/seasonal decomposition
    via a moving-average kernel + a per-channel linear layer. In our
    CROSS-SECTIONAL daily-feature setting (each row is a
    (date,symbol) with engineered scalar features, NOT a raw window)
    DLinear collapses to a LINEAR regression on the same features
    (per-feature linear weight, no nonlinearity). We expose
    ``individual=True/False`` to match the Zeng paper's per-channel
    vs. shared knob; for the cross-sectional reduction the two are
    equivalent (we keep the knob for API parity).

    Returns predictions on ``X_val``. This is THE mandatory baseline
    every B2 RB5 experiment must report next to its deep model —
    without it the deep numbers are uninterpretable (the RB4 AC
    "无之结果不可信").
    """
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler
    sc = StandardScaler().fit(np.nan_to_num(X_train.to_numpy()))
    m = Ridge(alpha=1.0, random_state=seed).fit(
        sc.transform(np.nan_to_num(X_train.to_numpy())),
        y_train.to_numpy())
    return m.predict(sc.transform(np.nan_to_num(X_val.to_numpy())))


def build_multitf_channels(
    intraday_bars_by_freq: Dict[str, Dict[str, pd.DataFrame]],
    symbol: str,
    decision_time: pd.Timestamp,
    lookback_bars: int = 32,
    freqs: Sequence[str] = _FREQS,
) -> Optional[np.ndarray]:
    """Stack the last ``lookback_bars`` closes of the named freqs
    as channels/variates for a (symbol, decision_time) sample.

    Returns ``(K_freq, lookback_bars)`` float32, or ``None`` if any
    requested freq lacks enough completed bars at ``decision_time``.
    Each freq's bars are filtered to ``index <= decision_time`` =
    the leakage-safe "only closed bars" rule (CLAUDE.md Multi-TF
    Leakage Rules / R10 contract). Channel-independence-friendly
    layout per iTransformer / PatchTST.
    """
    chans = []
    for f in freqs:
        df = intraday_bars_by_freq.get(f, {}).get(symbol)
        if df is None or df.empty:
            return None
        usable = df[df.index <= decision_time]
        if len(usable) < lookback_bars:
            return None
        c = usable["close"].iloc[-lookback_bars:].to_numpy(np.float32)
        if not np.isfinite(c).all():
            return None
        chans.append(c)
    return np.stack(chans, axis=0)


@dataclass
class B2Config:
    """B2 deep config. RB1 gate ROUTED FIRST. archetype must be
    differentiated (naive bar-voting refused). encoder choice is a
    knob for RB5 (the build round wires the channel/variate stack +
    SSL→probe scaffold; the experiment chooses the encoder)."""
    archetype: str = "intraday_reversal"
    encoder: str = "mae_ssl_in_domain"  # via RA7 scaffold
    pretrain_steps: int = 200
    seed: int = 42


def b2_ssl_frozen_probe(
    train_windows: np.ndarray,
    *,
    universe_name: str = "executable",
    bulk_weekend_fixed: bool = False,
    cfg: B2Config = B2Config(),
):
    """B2 in-domain SSL → frozen probe entry point.

    Routes RB1 prereqs + archetype gate FIRST; then delegates to
    the RA7 ``a4_ssl_frozen_probe_scaffold`` (which itself routes
    the R6 expanded-universe guard before any pretrain). Returns
    ``(frozen_model, embed_fn)``.
    """
    assert_component_b_prerequisites()
    assert_archetype_differentiated(cfg.archetype)
    return a4_ssl_frozen_probe_scaffold(
        train_windows, steps=cfg.pretrain_steps,
        universe_name=universe_name,
        bulk_weekend_fixed=bulk_weekend_fixed,
        seed=cfg.seed)
