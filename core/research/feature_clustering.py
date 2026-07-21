"""Train-fold-only unsupervised clustering of redundant numeric features."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class FeatureClusterFit:
    representatives: tuple[str, ...]
    clusters: tuple[tuple[str, ...], ...]
    n_observations: int


def fit_feature_correlation_clusters(
    features: Mapping[str, pd.DataFrame],
    mask: pd.DataFrame,
    train_dates: Sequence[pd.Timestamp] | pd.DatetimeIndex,
    *,
    absolute_correlation_threshold: float = 0.85,
    min_pair_observations: int = 100,
) -> FeatureClusterFit:
    """Fit correlation components and choose their deterministic medoids."""

    if not 0 < absolute_correlation_threshold <= 1:
        raise ValueError("absolute_correlation_threshold must be in (0, 1]")
    names = sorted(features)
    if not names:
        raise ValueError("at least one feature is required")
    dates = pd.DatetimeIndex(train_dates)
    if len(dates) == 0:
        raise ValueError("train_dates cannot be empty")
    missing = dates.difference(mask.index)
    if len(missing):
        raise KeyError(f"train dates missing from mask: {list(missing[:5])}")
    series = {}
    train_mask = mask.loc[dates]
    for name in names:
        frame = features[name].reindex(index=dates, columns=train_mask.columns)
        series[name] = frame.where(train_mask).stack()
    long = pd.concat(series, axis=1)
    correlation = long.corr(min_periods=min_pair_observations).abs()

    adjacency: dict[str, set[str]] = {name: set() for name in names}
    for left_position, left in enumerate(names):
        for right in names[left_position + 1:]:
            value = correlation.at[left, right]
            if pd.notna(value) and value >= absolute_correlation_threshold:
                adjacency[left].add(right)
                adjacency[right].add(left)

    remaining = set(names)
    clusters: list[tuple[str, ...]] = []
    representatives: list[str] = []
    while remaining:
        seed = min(remaining)
        component: set[str] = set()
        stack = [seed]
        while stack:
            name = stack.pop()
            if name in component:
                continue
            component.add(name)
            stack.extend(sorted(adjacency[name] - component, reverse=True))
        remaining -= component
        cluster = tuple(sorted(component))
        clusters.append(cluster)
        if len(cluster) == 1:
            representatives.append(cluster[0])
            continue
        centrality: dict[str, float] = {}
        for name in cluster:
            peers = [peer for peer in cluster if peer != name]
            values = correlation.loc[name, peers].dropna()
            centrality[name] = float(values.mean()) if len(values) else -np.inf
        representatives.append(sorted(
            cluster, key=lambda name: (-centrality[name], name))[0])

    paired = sorted(zip(representatives, clusters), key=lambda item: item[0])
    return FeatureClusterFit(
        representatives=tuple(item[0] for item in paired),
        clusters=tuple(item[1] for item in paired),
        n_observations=int(len(long)),
    )


__all__ = ["FeatureClusterFit", "fit_feature_correlation_clusters"]
