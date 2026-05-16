"""Subsequence transforms — MiniROCKET-style bridge representation layer.

Per `docs/prd/20260515-chart_structure_input_representation_prd.md` §4.3
(Phase 2B-0 bridge baseline) and the ralph-loop execution PRD §6 round
P2B·R1. Execution PRD §3 q6: implemented as a ~self-contained numpy
transform — no `sktime` / `pyts` dependency added to PQS.

What this is
------------
MiniROCKET (Dempster, Schmidt & Webb 2021, "MINIROCKET: A Very Fast
(Almost) Deterministic Transform for Time Series Classification",
arXiv:2012.08791) turns a time series into a fixed feature vector via a
small set of FIXED dilated convolutional kernels + PPV (proportion of
positive values) pooling. It is the "(almost) deterministic" successor
to ROCKET — the kernels are not random, only the PPV bias thresholds
have a data-dependent component.

This module implements a faithful, scaled-down MiniROCKET-style transform:
  - 84 fixed length-9 kernels: weights in {-1, 2}, exactly three +2
    positions (C(9,3) = 84). Each kernel sums to 3*2 + 6*(-1) = 0.
  - a configurable exponential dilation set.
  - PPV pooling at configurable per-series quantile biases.
Output feature count = 84 * n_dilations * n_quantile_biases.

It is a *bridge* layer (PRD §4.3): more expressive than a single hand-
crafted scalar, far cheaper / more sample-efficient than a deep CNN.
Whether the features carry incremental alpha is decided by the PQS IC /
Track A / sealed funnel — this module only produces the representation.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import numpy as np

_KERNEL_LEN = 9
_N_PLUS = 3  # number of +2 weights per kernel; C(9,3) = 84 kernels


def _build_kernels() -> np.ndarray:
    """The 84 fixed MiniROCKET kernels: length-9, weights {-1, 2}, exactly
    three +2 positions, each kernel mean-zero."""
    kernels = np.full((84, _KERNEL_LEN), -1.0, dtype=np.float64)
    for ki, plus_pos in enumerate(itertools.combinations(range(_KERNEL_LEN), _N_PLUS)):
        kernels[ki, list(plus_pos)] = 2.0
    return kernels


_KERNELS = _build_kernels()


@dataclass(frozen=True)
class MiniRocketConfig:
    """Config for the MiniROCKET-style transform.

    dilations         : dilation factors applied to every kernel.
    quantile_biases   : per-series conv-output quantiles used as PPV bias
                        thresholds (the data-dependent part).
    """

    dilations: tuple[int, ...] = (1, 2, 4, 8)
    quantile_biases: tuple[float, ...] = (0.25, 0.5, 0.75)

    @property
    def n_features(self) -> int:
        return 84 * len(self.dilations) * len(self.quantile_biases)


def _dilated_conv(x: np.ndarray, kernel: np.ndarray, dilation: int) -> np.ndarray:
    """Valid dilated 1-D convolution of series ``x`` with ``kernel``.

    Returns the convolution output (length = len(x) - (K-1)*dilation), or
    an empty array if the series is shorter than the dilated kernel."""
    eff = (_KERNEL_LEN - 1) * dilation + 1
    n_out = len(x) - eff + 1
    if n_out <= 0:
        return np.empty(0, dtype=np.float64)
    # build the (n_out, K) strided view of dilated taps
    idx = np.arange(n_out)[:, None] + np.arange(_KERNEL_LEN)[None, :] * dilation
    return (x[idx] * kernel[None, :]).sum(axis=1)


def minirocket_features(series: np.ndarray,
                        cfg: MiniRocketConfig | None = None) -> np.ndarray:
    """Transform a single 1-D series into a MiniROCKET-style feature vector.

    Returns a length-``cfg.n_features`` vector of PPV values in [0, 1].
    NaN-only or too-short series yield an all-NaN vector (caller masks)."""
    if cfg is None:
        cfg = MiniRocketConfig()
    x = np.asarray(series, dtype=np.float64)
    out = np.full(cfg.n_features, np.nan, dtype=np.float64)
    finite = x[np.isfinite(x)]
    if finite.size < _KERNEL_LEN + 1:
        return out
    # work on the finite tail (gaps in the middle would break dilation
    # geometry; the caller passes contiguous windows)
    x = finite
    fi = 0
    for dil in cfg.dilations:
        for ki in range(84):
            conv = _dilated_conv(x, _KERNELS[ki], dil)
            if conv.size == 0:
                fi += len(cfg.quantile_biases)
                continue
            biases = np.quantile(conv, cfg.quantile_biases)
            for b in biases:
                out[fi] = float(np.mean(conv > b))
                fi += 1
    return out


def minirocket_transform(panel: np.ndarray,
                         cfg: MiniRocketConfig | None = None) -> np.ndarray:
    """Transform a stack of series ``panel`` (n_series, series_len) into a
    feature matrix (n_series, n_features)."""
    if cfg is None:
        cfg = MiniRocketConfig()
    panel = np.asarray(panel, dtype=np.float64)
    if panel.ndim != 2:
        raise ValueError(f"panel must be 2-D (n_series, len); got {panel.shape}")
    return np.vstack([minirocket_features(panel[i], cfg) for i in range(panel.shape[0])])


def rolling_minirocket_ppv_mean(close: np.ndarray, window: int,
                                cfg: MiniRocketConfig | None = None) -> np.ndarray:
    """Causal rolling bridge feature for a single symbol's close series.

    For each bar t, applies the MiniROCKET transform to the trailing
    ``window`` log-returns ending at t and returns the MEAN PPV across all
    kernels — a single scalar bridge feature per bar (a compact summary of
    "how does the recent subsequence shape score across the kernel bank").
    Bars with insufficient history get NaN. Strictly causal: bar t uses
    only returns up to t.

    A compact 1-feature summary is intentional for the bridge baseline; the
    full ``minirocket_features`` vector is available for callers that want
    the high-dimensional representation.
    """
    if cfg is None:
        cfg = MiniRocketConfig()
    close = np.asarray(close, dtype=np.float64)
    n = len(close)
    out = np.full(n, np.nan, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        logret = np.diff(np.log(close))
    for t in range(n):
        # returns available as of bar t: logret indices [0 .. t-1]
        avail = logret[max(0, t - window):t]
        if len(avail) < _KERNEL_LEN + 1:
            continue
        feats = minirocket_features(avail, cfg)
        finite = feats[np.isfinite(feats)]
        if finite.size:
            out[t] = float(finite.mean())
    return out
