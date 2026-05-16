"""Inject chart-structure representations into the ML factor panel — P2B·R4.

Per chart-structure ralph-loop execution PRD §6 round P2B·R4 (P2-d5).

The chart-structure representations (P2B·R1 MiniROCKET bridge, P2B·R2
TS2Vec embedding) are turned into ordinary ``{name: date×symbol frame}``
factor dicts so the EXISTING ``build_ml_panel`` consumes them unchanged
— no edit to ``build_ml_panel`` itself, which makes the post-injection
regression (AC P2-A6) hold by construction.

``inject_chart_structure_factors`` merges representation factor dicts
into a base factor dict with a name-collision guard; injecting nothing
returns the base dict untouched, so the default ML panel is bit-for-bit
unaffected by the existence of this module.
"""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

from core.ml.subsequence_transforms import MiniRocketConfig, rolling_minirocket_ppv_mean

CS_PREFIX = "cs_"  # namespace for every injected chart-structure factor


def rolling_minirocket_factor_frame(
    close_panel: pd.DataFrame,
    window: int = 80,
    cfg: MiniRocketConfig | None = None,
    factor_name: str = "cs_minirocket_ppv_mean",
) -> Dict[str, pd.DataFrame]:
    """Bridge-layer factor: per (symbol, date) trailing-window mean PPV.

    ``close_panel`` is a date×symbol close frame. For each symbol the
    causal ``rolling_minirocket_ppv_mean`` is evaluated; the result is a
    single date×symbol factor frame returned as a one-entry dict (the
    shape ``build_ml_panel`` expects).
    """
    cfg = cfg or MiniRocketConfig()
    out = {}
    for sym in close_panel.columns:
        series = close_panel[sym].to_numpy(dtype=float)
        out[sym] = rolling_minirocket_ppv_mean(series, window=window, cfg=cfg)
    frame = pd.DataFrame(out, index=close_panel.index)
    if not factor_name.startswith(CS_PREFIX):
        raise ValueError(f"chart-structure factor name must start {CS_PREFIX!r}")
    return {factor_name: frame}


def embedding_factor_frames(
    embeddings: Dict[str, pd.DataFrame],
    dims: int,
    prefix: str = "cs_emb",
) -> Dict[str, pd.DataFrame]:
    """Turn per-symbol window embeddings into per-dimension factor frames.

    ``embeddings`` maps symbol → (date × embedding_dim) frame (e.g. from
    ``TS2VecEncoder.encode_last`` evaluated on a rolling window). Output
    is ``embedding_dim`` factor frames ``{prefix}_{d}``, each date×symbol.
    """
    if not embeddings:
        return {}
    dates = sorted(set().union(*[e.index for e in embeddings.values()]))
    syms = sorted(embeddings.keys())
    frames: Dict[str, pd.DataFrame] = {}
    for d in range(dims):
        col = {s: embeddings[s].iloc[:, d].reindex(dates) for s in syms}
        frames[f"{prefix}_{d}"] = pd.DataFrame(col, index=dates)
    return frames


def inject_chart_structure_factors(
    base_factors: Dict[str, pd.DataFrame],
    *repr_factor_dicts: Dict[str, pd.DataFrame],
) -> Dict[str, pd.DataFrame]:
    """Merge chart-structure representation factors into a base factor
    dict. Raises on a name collision. Injecting nothing returns ``dict
    (base_factors)`` — the default ML panel is unaffected.
    """
    merged = dict(base_factors)
    for rd in repr_factor_dicts:
        for name, frame in rd.items():
            if name in merged:
                raise ValueError(
                    f"chart-structure factor {name!r} collides with an "
                    f"existing factor — injection refused")
            merged[name] = frame
    return merged
