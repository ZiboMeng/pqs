"""Factor cluster decomposition — find disguised duplicates.

PRD-driven 2026-05-12 (Round Z1).

For 162 factors, compute pairwise correlation across the panel and
identify clusters of factors that look distinct by name but ARE
correlated > τ (default 0.7). Mining can use this to penalize
within-cluster co-sampling.
"""

from __future__ import annotations

import logging
from typing import Dict, List

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_factor_clusters(
    factor_panel_map: Dict[str, pd.DataFrame],
    correlation_threshold: float = 0.70,
    sample_dates: int = 200,
) -> pd.DataFrame:
    """Find pairwise high-correlation factor pairs.

    Computation strategy: stack each factor's panel (date × symbol) into
    a single flat vector (length = n_dates × n_syms), then compute
    pairwise Pearson correlation across factors. Sample `sample_dates`
    dates for tractability (162 × 162 correlations on full panel is
    expensive otherwise).

    Returns:
        DataFrame with rows = pairs above threshold; columns:
          factor_a, factor_b, abs_corr, signed_corr
        Sorted descending by abs_corr.
    """
    if not factor_panel_map:
        return pd.DataFrame(columns=["factor_a", "factor_b", "abs_corr", "signed_corr"])

    # Sample dates to keep computation tractable
    first = next(iter(factor_panel_map.values()))
    if first is None or first.empty:
        return pd.DataFrame(columns=["factor_a", "factor_b", "abs_corr", "signed_corr"])
    dates = first.index
    if len(dates) > sample_dates:
        step = len(dates) // sample_dates
        dates = dates[::step]

    # Build a flat vector per factor: stack rows of (panel.loc[dates])
    flat_vectors = {}
    for name, df in factor_panel_map.items():
        if df is None or df.empty:
            continue
        try:
            sub = df.reindex(index=dates)
        except KeyError:
            continue
        # Flatten to 1D array
        vec = sub.values.flatten()
        if np.nansum(np.isfinite(vec)) < 50:
            # Too sparse to compute correlation
            continue
        flat_vectors[name] = vec

    names = list(flat_vectors.keys())
    n = len(names)
    if n < 2:
        return pd.DataFrame(columns=["factor_a", "factor_b", "abs_corr", "signed_corr"])

    # Pairwise Pearson via NaN-aware impl
    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            v1, v2 = flat_vectors[names[i]], flat_vectors[names[j]]
            mask = np.isfinite(v1) & np.isfinite(v2)
            if mask.sum() < 30:
                continue
            x = v1[mask]; y = v2[mask]
            # Handle near-constant vectors
            if x.std() < 1e-12 or y.std() < 1e-12:
                continue
            c = float(np.corrcoef(x, y)[0, 1])
            if not np.isfinite(c):
                continue
            if abs(c) >= correlation_threshold:
                pairs.append({
                    "factor_a": names[i],
                    "factor_b": names[j],
                    "abs_corr": abs(c),
                    "signed_corr": c,
                })

    if not pairs:
        return pd.DataFrame(columns=["factor_a", "factor_b", "abs_corr", "signed_corr"])
    return pd.DataFrame(pairs).sort_values("abs_corr", ascending=False).reset_index(drop=True)
