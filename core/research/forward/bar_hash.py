"""Forward-evidence input-scope hashing (PRD v2.1 §4.3).

Three per-scope hashers fingerprint the bars actually used to compute
a forward TD's metrics:

  - ``compute_signal_input_hash``: full pre-top_n universe over the
    candidate spec's factor lookback window — close + volume + high +
    low as needed (resolved via ``resolve_factor_input_contract``).
  - ``compute_execution_nav_hash``: held-or-traded set over
    ``[start_date .. as_of_date]`` — open + close (open drives fills;
    close drives EOD MTM).
  - ``compute_benchmark_hash``: SPY (and QQQ if secondary) closes
    over ``[start_date .. as_of_date]``.

Each hasher returns ``(hex_hash, PerScopeHashInputs)`` where
``PerScopeHashInputs`` carries enough evidence (per_cell_digest +
materiality_anchor_values) to detect revisions and compute NAV-impact
bps deterministically inside the 10-day anchor ring.

Determinism contract:
  - All inputs serialized in lexicographic order (sym → date → attr).
  - Floats formatted via ``f"{value:.10g}"`` to avoid Python repr
    drift across versions / platforms.
  - NaN serialized as the literal ``"NaN"`` so delisting-in-flight or
    pre-IPO bars produce deterministic hashes.
  - Truncation: 24 hex chars (96 bits). Random collision negligible
    at our scale (≤60 TDs × 3 scopes).
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Optional

import numpy as np
import pandas as pd

from core.research.frozen_spec import FrozenStrategySpec


# ── factor input contract resolver ─────────────────────────────────


class ContractResolutionError(KeyError):
    """Raised when a factor in a frozen spec has no input contract.

    Fail-closed: silent under-hashing creates false confidence and is
    worse than no hash at all. Operators must add a contract entry
    before forward observation can resume.
    """


@dataclass(frozen=True)
class FactorInputContract:
    """Per-factor raw-data dependency contract.

    ``cross_sectional=True`` factors read ``benchmark_symbols`` (e.g.
    SPY) in addition to per-symbol bars; the resolver's union calls
    fold those benchmarks into the signal-input universe so the hash
    covers them.
    """

    factor_name: str
    attributes: tuple[str, ...]
    lookback_days: int
    cross_sectional: bool
    benchmark_symbols: tuple[str, ...] = field(default_factory=tuple)


# Static registry of factor input contracts. Adding a factor here is a
# deliberate act — RCMv1 / Cand-2 contracts are pinned by tests so an
# accidental change to one of these rows fails CI. New factors used by
# future candidates must add their entry here OR the resolver
# fail-closes.
_FACTOR_REGISTRY: dict[str, FactorInputContract] = {
    # RCMv1 features
    "beta_spy_60d": FactorInputContract(
        factor_name="beta_spy_60d",
        attributes=("close",),
        lookback_days=60,
        cross_sectional=True,
        benchmark_symbols=("SPY",),
    ),
    "drawup_from_252d_low": FactorInputContract(
        factor_name="drawup_from_252d_low",
        attributes=("close",),
        lookback_days=252,
        cross_sectional=False,
    ),
    "days_since_52w_high": FactorInputContract(
        factor_name="days_since_52w_high",
        attributes=("close",),
        lookback_days=252,
        cross_sectional=False,
    ),
    "amihud_20d": FactorInputContract(
        factor_name="amihud_20d",
        attributes=("close", "volume"),
        lookback_days=20,
        cross_sectional=False,
    ),
    # Cand-2 features
    "ret_5d": FactorInputContract(
        factor_name="ret_5d",
        attributes=("close",),
        lookback_days=5,
        cross_sectional=False,
    ),
    "rs_vs_spy_126d": FactorInputContract(
        factor_name="rs_vs_spy_126d",
        attributes=("close",),
        lookback_days=126,
        cross_sectional=True,
        benchmark_symbols=("SPY",),
    ),
    "hl_range": FactorInputContract(
        factor_name="hl_range",
        # hl_range = (high - low) / prev_close — needs high, low, and
        # prev close. Lookback=2 to safely include prev_close.
        attributes=("close", "high", "low"),
        lookback_days=2,
        cross_sectional=False,
    ),
}


def resolve_factor_input_contract(
    spec: FrozenStrategySpec,
) -> dict[str, FactorInputContract]:
    """Resolve every factor in ``spec.feature_set`` to its input contract.

    Fail-closed on any factor not present in ``_FACTOR_REGISTRY`` —
    raises ``ContractResolutionError`` so the operator must explicitly
    add the contract before v2.1 hash creation can proceed.
    """
    resolved: dict[str, FactorInputContract] = {}
    missing: list[str] = []
    for f in spec.feature_set:
        c = _FACTOR_REGISTRY.get(f.name)
        if c is None:
            missing.append(f.name)
            continue
        resolved[f.name] = c
    if missing:
        raise ContractResolutionError(
            f"factor(s) {missing!r} have no FactorInputContract entry in "
            f"core.research.forward.bar_hash._FACTOR_REGISTRY; v2.1 "
            f"signal-input hashing refuses to proceed silently. Add a "
            f"contract entry before forward observation can resume."
        )
    return resolved


def union_attributes(
    contracts: dict[str, FactorInputContract],
) -> set[str]:
    """Union of raw bar attributes read by the spec's factors."""
    out: set[str] = set()
    for c in contracts.values():
        out.update(c.attributes)
    return out


def max_lookback(
    contracts: dict[str, FactorInputContract],
) -> int:
    """Max factor lookback over the spec — drives signal_input window."""
    return max((c.lookback_days for c in contracts.values()), default=0)


def union_benchmark_symbols(
    contracts: dict[str, FactorInputContract],
) -> set[str]:
    """SPY/QQQ/etc. pulled in by cross_sectional factors."""
    out: set[str] = set()
    for c in contracts.values():
        if c.cross_sectional:
            out.update(c.benchmark_symbols)
    return out


# ── hashing helpers ────────────────────────────────────────────────


def _fmt_value(v) -> str:
    """Deterministic float-to-string: NaN → "NaN", else f"{v:.10g}".

    Plain Python repr of float64 differs across NumPy versions; using
    %.10g avoids that drift. Integer values pass through losslessly
    because :.10g on an int prints without exponent up to 10 digits.
    """
    if v is None:
        return "None"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if math.isnan(f):
        return "NaN"
    return f"{f:.10g}"


def _digest8(value: str) -> str:
    """8-char prefix of sha256(value-string). Used per-cell."""
    return hashlib.sha256(value.encode()).hexdigest()[:8]


def _hash_panel(
    *,
    panel: pd.DataFrame,
    symbols: Iterable[str],
    attribute: str,
    window_start: date,
    window_end: date,
) -> tuple[str, dict]:
    """Hash one (symbols, attribute, window) slice deterministically.

    Returns (sha256_hex, per_cell_digest) where per_cell_digest is
    ``{ sym: { iso_date: { attribute: digest8 } } }`` for the cells
    in the slice.

    ``panel`` is expected to be a DataFrame indexed by date with
    columns of symbols (the standard PQS panel shape after
    ``_load_panel``). Missing symbols / dates yield NaN cells which
    serialize deterministically as "NaN".
    """
    symbols = sorted(symbols)
    h = hashlib.sha256()
    cells: dict = {}
    if panel is None or panel.empty:
        h.update(b"|empty|")
        return h.hexdigest()[:24], cells

    ws = pd.Timestamp(window_start)
    we = pd.Timestamp(window_end)
    window = panel[(panel.index >= ws) & (panel.index <= we)]
    if window.empty:
        h.update(b"|empty|")
        return h.hexdigest()[:24], cells

    for sym in symbols:
        if sym not in window.columns:
            # Symbol fully absent over window — fold a sentinel marker
            # so a future presence change is detectable.
            h.update(f"{sym}|{attribute}|<missing>".encode())
            continue
        col = window[sym]
        sym_cells: dict = {}
        # Iterate in date order; window.index is already ascending
        # because pandas keeps DatetimeIndex sorted on slice.
        for ts, val in col.items():
            iso = pd.Timestamp(ts).date().isoformat()
            s = _fmt_value(val)
            payload = f"{sym}|{iso}|{attribute}|{s}".encode()
            h.update(payload)
            h.update(b"\n")
            sym_cells.setdefault(iso, {})[attribute] = _digest8(s)
        if sym_cells:
            cells[sym] = sym_cells
    return h.hexdigest()[:24], cells


def _merge_cell_digests(*partials: dict) -> dict:
    """Deep-merge per-attribute per_cell_digests for the same scope."""
    out: dict = {}
    for p in partials:
        for sym, by_date in p.items():
            d_out = out.setdefault(sym, {})
            for iso, attrs in by_date.items():
                a_out = d_out.setdefault(iso, {})
                a_out.update(attrs)
    return out


def _capture_anchor_values(
    *,
    panel: pd.DataFrame,
    open_panel: Optional[pd.DataFrame],
    held_or_traded: Iterable[str],
    as_of_date: date,
    ring_days: int = 10,
) -> dict:
    """Snapshot close+open numerics for the held/traded set on the
    last ``ring_days`` trading days at-or-before ``as_of_date``.

    Captured at observation time. Lets revalidate compute deterministic
    NAV-impact bps for revisions that fall inside the ring; revisions
    outside the ring fail-closed to bound_only per §4.4.

    Layout: ``{ sym: { iso_date: { 'close': float|NaN, 'open': float|NaN } } }``.
    NaN is preserved (not stripped) so a later "we observed NaN here"
    state is reproducible.
    """
    out: dict = {}
    if panel is None or panel.empty:
        return out
    available = panel.index[panel.index <= pd.Timestamp(as_of_date)]
    if len(available) == 0:
        return out
    ring = available[-ring_days:]
    syms = sorted(set(held_or_traded))
    for sym in syms:
        sym_out: dict = {}
        for ts in ring:
            iso = pd.Timestamp(ts).date().isoformat()
            close_val: Optional[float]
            open_val:  Optional[float]
            if sym in panel.columns:
                v = panel[sym].get(ts, np.nan)
                close_val = None if pd.isna(v) else float(v)
            else:
                close_val = None
            if open_panel is not None and sym in open_panel.columns:
                v = open_panel[sym].get(ts, np.nan)
                open_val = None if pd.isna(v) else float(v)
            else:
                open_val = None
            sym_out[iso] = {"close": close_val, "open": open_val}
        if sym_out:
            out[sym] = sym_out
    return out
