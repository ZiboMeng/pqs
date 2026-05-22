"""P3 — score-to-weight mapping (PRD 20260521 §4.8).

Maps a per-bar cross-sectional score (rank ∈ [0, 1], the §9.0-compliant
output of a rank model) into LONG-ONLY target weights, under the
mapping modes + caps declared in `config/ml_allocation.yaml`.

LONG-ONLY GUARDRAIL (PRD §4.8 AUDIT-2026-05-21): every output weight is
≥ 0. There is no short leg. The single-name cap is enforced (and cannot
be silently bypassed — P3 §12.3 gate); when caps bind, the residual is
left as cash rather than forced onto a name.
"""
from __future__ import annotations

import pandas as pd

__all__ = ["score_to_weight", "score_panel_to_weights", "MAPPING_MODES"]

MAPPING_MODES = (
    "top_k_capped",
    "score_proportional_clipped",
    "score_vol_scaled",
)


def _apply_single_name_cap(w: pd.Series, cap: float) -> pd.Series:
    """Cap each weight at `cap`, redistributing the excess pro-rata to
    the uncapped names; iterate to a fixed point. If every name is
    capped the weights sum to < 1 — the residual stays as cash (a risk
    cap is never silently bypassed)."""
    if cap >= 1.0:
        return w
    w = w.copy()
    for _ in range(100):
        over = w[w > cap + 1e-12]
        if over.empty:
            break
        excess = float((over - cap).sum())
        w[over.index] = cap
        room = w[w < cap - 1e-12]
        if room.empty or room.sum() <= 0:
            break  # everyone at cap → residual is cash
        w[room.index] = room + excess * (room / room.sum())
    return w.clip(upper=cap)


def score_to_weight(
    score: pd.Series,
    mode: str = "top_k_capped",
    top_k: int = 10,
    max_single_weight: float = 0.40,
    vol: pd.Series | None = None,
    clip_quantile: float = 0.95,
) -> pd.Series:
    """One bar: cross-sectional score → long-only target weights.

    Args:
        score: index=symbol, value=rank score ∈ [0, 1] (NaN allowed)
        mode: one of MAPPING_MODES
        top_k: number of names to hold (the long top-k)
        max_single_weight: hard per-name cap
        vol: per-symbol realized vol (required for score_vol_scaled)
        clip_quantile: winsorize quantile for score_proportional_clipped

    Returns:
        Series index=score.index, weights ≥ 0, sum ≤ 1 (residual = cash).
    """
    if mode not in MAPPING_MODES:
        raise ValueError(f"unknown mapping mode {mode!r}; "
                         f"expected one of {MAPPING_MODES}")
    out = pd.Series(0.0, index=score.index)
    s = score.dropna()
    if s.empty or top_k < 1:
        return out  # cash / no-trade
    top = s.nlargest(min(top_k, len(s)))

    if mode == "top_k_capped":
        raw = pd.Series(1.0, index=top.index)
    elif mode == "score_proportional_clipped":
        raw = top.clip(upper=float(top.quantile(clip_quantile)))
    else:  # score_vol_scaled
        if vol is None:
            raise ValueError("score_vol_scaled requires `vol`")
        v = vol.reindex(top.index).astype(float).clip(lower=1e-6)
        raw = top / v

    raw = raw.clip(lower=0.0)  # long-only invariant
    total = float(raw.sum())
    if total <= 0:
        return out  # cash
    w = _apply_single_name_cap(raw / total, max_single_weight)
    out.loc[w.index] = w.to_numpy()
    return out


def score_panel_to_weights(
    score_df: pd.DataFrame,
    mode: str = "top_k_capped",
    top_k: int = 10,
    max_single_weight: float = 0.40,
    vol_df: pd.DataFrame | None = None,
    clip_quantile: float = 0.95,
) -> pd.DataFrame:
    """Apply `score_to_weight` per bar over a (date × symbol) score panel."""
    rows = {}
    for date, score_row in score_df.iterrows():
        vol_row = (vol_df.loc[date]
                   if vol_df is not None and date in vol_df.index else None)
        rows[date] = score_to_weight(
            score_row, mode=mode, top_k=top_k,
            max_single_weight=max_single_weight,
            vol=vol_row, clip_quantile=clip_quantile)
    return pd.DataFrame(rows).T.reindex(columns=score_df.columns).fillna(0.0)
