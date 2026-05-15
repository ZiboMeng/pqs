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

# Schema-bypass guard contract (see
# tests/unit/research/test_forward_manifest_schema.py::
# test_forward_runner_writes_go_through_schema_validation):
# any forward-package module that mentions manifests must import
# ForwardRunManifest so the schema validator stays reachable.
from .manifest_schema import ForwardRunManifest as _ForwardRunManifest  # noqa: F401


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
    # Trial 9 features (diversifier role, Phase C-PRD-1)
    "max_dd_126d": FactorInputContract(
        factor_name="max_dd_126d",
        # Chains rolling(252).max → drawdown → rolling(126).min: earliest
        # bar whose change feeds today's value is t-251-125=t-376. Use
        # 378 for safety. See core.factors.factor_generator._quality_factors.
        attributes=("close",),
        lookback_days=378,
        cross_sectional=False,
    ),
    "ret_1d": FactorInputContract(
        factor_name="ret_1d",
        attributes=("close",),
        lookback_days=1,
        cross_sectional=False,
    ),
    # cycle06 + cycle08 evidence candidate features (2026-05-15 forward-init)
    "xsection_rank_63d": FactorInputContract(
        factor_name="xsection_rank_63d",
        # price_df.pct_change(63).rank(axis=1, pct=True) — cross-sectional
        # RANK across the universe; ranks only within the panel symbols,
        # needs NO external benchmark → cross_sectional=False.
        attributes=("close",),
        lookback_days=63,
        cross_sectional=False,
    ),
    "trend_tstat_20d": FactorInputContract(
        factor_name="trend_tstat_20d",
        # OLS slope t-stat of log(close) on a rolling 20d window.
        attributes=("close",),
        lookback_days=20,
        cross_sectional=False,
    ),
    "ret_2d": FactorInputContract(
        factor_name="ret_2d",
        attributes=("close",),
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


def _resolve_lookback_window_start(
    panel: dict,
    as_of_date: date,
    lookback: int,
) -> date:
    """Resolve ``window_start`` to the actual ``lookback``-th prior
    trading row in the panel calendar.

    Codex Round-10 Blocker 1: ``pd.tseries.offsets.BDay(lookback)`` is
    a calendar-weekday offset (Mon-Fri only) and ignores US market
    holidays, so for a daily NYSE-trading-calendar panel ``BDay(252)``
    lands ~9 trading rows short of the true 252nd prior trading day.
    Factor engines (``factor_generator.py``) compute on rolling row
    windows — they read those omitted rows even when the hash misses
    them, producing a false-negative coverage hole where revisions on
    the omitted rows fail to flip ``signal_input_hash``.

    Algorithm: take the canonical ``close`` panel's sorted DatetimeIndex,
    keep rows at-or-before ``as_of_date``, step back ``lookback`` rows.
    Returns the panel's earliest available date when fewer than
    ``lookback`` rows are available (early-history candidates / new
    factors with longer lookback than the panel itself).
    """
    close_panel = panel.get("close")
    if close_panel is None or close_panel.empty:
        # Pure fallback for degenerate test fixtures with no close
        # panel; production runs always carry close. BDay is wrong but
        # at least deterministic.
        return (pd.Timestamp(as_of_date) - pd.tseries.offsets.BDay(lookback)).date()
    idx = close_panel.index
    as_of_ts = pd.Timestamp(as_of_date)
    valid = idx[idx <= as_of_ts]
    if len(valid) == 0:
        return (pd.Timestamp(as_of_date) - pd.tseries.offsets.BDay(lookback)).date()
    if len(valid) < lookback:
        return valid[0].date()
    # Inclusive of as_of (valid[-1]); valid[-lookback] gives `lookback`
    # rows ending at as_of.
    return valid[-lookback].date()


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


# ── per-scope hashers ──────────────────────────────────────────────


# Default bar_revision pin used for the canonical polygon-derived
# daily store. Re-exported here so callers don't need to import from
# robustness/runner; v2.1 forward hashers use this as the bar_revision
# value on PerScopeHashInputs unless overridden.
from core.research.robustness.runner import DAILY_STORE_REBUILD_COMMIT  # noqa: E402

DEFAULT_BAR_REVISION = f"polygon_canonical_rebuild_{DAILY_STORE_REBUILD_COMMIT}"


def compute_signal_input_hash(
    *,
    spec: FrozenStrategySpec,
    universe: Iterable[str],
    panel: dict,
    as_of_date: date,
    bar_revision: str = DEFAULT_BAR_REVISION,
    track_per_cell: bool = False,
) -> tuple[str, "PerScopeHashInputs"]:
    """Hash the raw bars feeding the candidate's composite signal at
    ``as_of_date``. Window = ``[as_of - max_lookback, as_of]`` resolved
    via ``resolve_factor_input_contract``. Attributes = union of factor
    input attributes; benchmark symbols (e.g. SPY) for cross_sectional
    factors are folded into the symbol list.

    ``track_per_cell`` (default ``False``): when False, ``per_cell_digest``
    stays empty. The rolling hash alone covers ~80 syms × 252 days × 2
    attrs (~40K cells); storing per-cell 8-char digests adds ~2 MB per
    TD which would balloon the manifest to >100 MB by TD60. This
    storage is **dead weight for materiality** because revalidate only
    needs per-cell granularity for cells in the execution_nav scope
    (the held / traded subset over [start_date..as_of]) — those cells
    are tracked by ``compute_execution_nav_hash`` already. Any
    signal-only revision (revision outside execution_nav scope) fails-
    closed to bound_only per §4.4 regardless of per-cell granularity.
    Set ``track_per_cell=True`` only for tests that need to assert
    per-cell digest content directly.

    Returns ``(hash_hex_24, PerScopeHashInputs)``.
    """
    from .manifest_schema import PerScopeHashInputs

    contracts = resolve_factor_input_contract(spec)
    attrs = sorted(union_attributes(contracts))
    lookback = max_lookback(contracts)
    benchmarks = union_benchmark_symbols(contracts)

    syms = sorted(set(universe) | benchmarks)
    window_start = _resolve_lookback_window_start(panel, as_of_date, lookback)
    window_end   = as_of_date

    rolling_h = hashlib.sha256()
    rolling_h.update(f"signal_input|rev={bar_revision}|attrs={','.join(attrs)}".encode())
    cells_merged: dict = {}
    for attr in attrs:
        attr_panel = panel.get(attr)
        if attr_panel is None:
            # missing attribute panel — fold sentinel; signal will fail
            # downstream, but the hash stays deterministic.
            rolling_h.update(f"|<panel_missing:{attr}>|".encode())
            continue
        partial_hex, partial_cells = _hash_panel(
            panel=attr_panel,
            symbols=syms,
            attribute=attr,
            window_start=window_start,
            window_end=window_end,
        )
        rolling_h.update(f"|{attr}={partial_hex}".encode())
        if track_per_cell:
            cells_merged = _merge_cell_digests(cells_merged, partial_cells)

    inputs = PerScopeHashInputs(
        scope="signal_input",
        symbols=syms,
        bar_attributes=attrs,
        window_start=window_start,
        window_end=window_end,
        bar_revision=bar_revision,
        per_cell_digest=cells_merged,  # empty unless track_per_cell=True
        # Anchor values are NOT captured for signal_input — non-held
        # universe revisions fail-closed per §4.4 (bound_only); held
        # symbols' anchors are captured by execution_nav scope.
        materiality_anchor_values={},
    )
    return rolling_h.hexdigest()[:24], inputs


def compute_execution_nav_hash(
    *,
    held_or_traded_symbols: Iterable[str],
    panel: dict,
    start_date: date,
    as_of_date: date,
    bar_revision: str = DEFAULT_BAR_REVISION,
    anchor_ring_days: int = 10,
) -> tuple[str, "PerScopeHashInputs"]:
    """Hash open + close bars used by BacktestEngine from
    ``start_date`` through ``as_of_date`` over the held-or-traded set.

    Anchored at ``manifest.start_date`` (NOT ``as_of_date``) per PRD
    v2.1 §G6 so the cumulative-return denominator is included.

    Captures observation-time close+open numerics for the held-or-
    traded set on the last ``anchor_ring_days`` trading days
    at-or-before ``as_of_date`` — used by revalidate to compute
    deterministic NAV-impact bps for in-ring revisions.
    """
    from .manifest_schema import PerScopeHashInputs

    attrs = ("close", "open")
    syms = sorted(set(held_or_traded_symbols))

    rolling_h = hashlib.sha256()
    rolling_h.update(f"execution_nav|rev={bar_revision}|attrs={','.join(attrs)}".encode())
    cells_merged: dict = {}
    for attr in attrs:
        attr_panel = panel.get(attr)
        if attr_panel is None:
            rolling_h.update(f"|<panel_missing:{attr}>|".encode())
            continue
        partial_hex, partial_cells = _hash_panel(
            panel=attr_panel,
            symbols=syms,
            attribute=attr,
            window_start=start_date,
            window_end=as_of_date,
        )
        rolling_h.update(f"|{attr}={partial_hex}".encode())
        cells_merged = _merge_cell_digests(cells_merged, partial_cells)

    anchor_values = _capture_anchor_values(
        panel=panel.get("close"),
        open_panel=panel.get("open"),
        held_or_traded=syms,
        as_of_date=as_of_date,
        ring_days=anchor_ring_days,
    )

    inputs = PerScopeHashInputs(
        scope="execution_nav",
        symbols=syms,
        bar_attributes=list(attrs),
        window_start=start_date,
        window_end=as_of_date,
        bar_revision=bar_revision,
        per_cell_digest=cells_merged,
        materiality_anchor_values=anchor_values,
    )
    return rolling_h.hexdigest()[:24], inputs


def compute_benchmark_hash(
    *,
    benchmark_symbols: Iterable[str],
    panel: dict,
    start_date: date,
    as_of_date: date,
    bar_revision: str = DEFAULT_BAR_REVISION,
    anchor_ring_days: int = 10,
) -> tuple[str, "PerScopeHashInputs"]:
    """Hash SPY (and QQQ if secondary) closes from ``start_date``
    through ``as_of_date``. Drives ``vs_spy`` / ``vs_qqq``.

    Anchor values for benchmarks are captured for the close attribute
    only; revalidate's vs_spy / vs_qqq drift calc reads the anchor
    closes as the "old benchmark NAV path."
    """
    from .manifest_schema import PerScopeHashInputs

    attrs = ("close",)
    syms = sorted(set(benchmark_symbols))

    rolling_h = hashlib.sha256()
    rolling_h.update(f"benchmark|rev={bar_revision}|attrs={','.join(attrs)}".encode())
    cells_merged: dict = {}
    close_panel = panel.get("close")
    if close_panel is None:
        rolling_h.update(b"|<panel_missing:close>|")
    else:
        partial_hex, partial_cells = _hash_panel(
            panel=close_panel,
            symbols=syms,
            attribute="close",
            window_start=start_date,
            window_end=as_of_date,
        )
        rolling_h.update(f"|close={partial_hex}".encode())
        cells_merged = _merge_cell_digests(cells_merged, partial_cells)

    anchor_values = _capture_anchor_values(
        panel=close_panel,
        open_panel=None,
        held_or_traded=syms,
        as_of_date=as_of_date,
        ring_days=anchor_ring_days,
    )

    inputs = PerScopeHashInputs(
        scope="benchmark",
        symbols=syms,
        bar_attributes=list(attrs),
        window_start=start_date,
        window_end=as_of_date,
        bar_revision=bar_revision,
        per_cell_digest=cells_merged,
        materiality_anchor_values=anchor_values,
    )
    return rolling_h.hexdigest()[:24], inputs


def compute_bar_hash_rollup(
    signal_input_hash: str,
    execution_nav_hash: str,
    benchmark_hash: str,
) -> str:
    """Roll-up = sha256(s||e||b)[:24]. Top-level cheap diff."""
    h = hashlib.sha256()
    h.update(signal_input_hash.encode())
    h.update(b"|")
    h.update(execution_nav_hash.encode())
    h.update(b"|")
    h.update(benchmark_hash.encode())
    return h.hexdigest()[:24]


# ── observation-time evidence capture ──────────────────────────────


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
