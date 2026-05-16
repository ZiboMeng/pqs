"""Swing-segment structure features (family T) — chart-structure input layer.

Per `docs/prd/20260515-chart_structure_input_representation_prd.md` Phase 1
and its ralph-loop execution PRD
(`docs/prd/20260515-chart_structure_ralph_loop_execution_prd.md`).

Shipped: P1·R1 (causal swing core) + P1·R2 (12 structure features).

Causality contract (PRD §3.4 / §2.2)
------------------------------------
`detect_swing_extrema` uses a ``[i-n, i+n]`` window, so a swing at bar ``i``
is only confirmable at bar ``i+n``. Each swing carries
``confirmation_idx = i + swing_n``.

The alternating-collapse (§B-B2: of two consecutive same-kind extrema keep
the more extreme) MUST run AFTER the as-of-t confirmation filter, not
before — collapse-then-filter is non-causal (a future swing could decide
which past swing is dropped). Hence **filter-then-collapse**:
  - ``detect_raw_swings`` runs ``detect_swing_extrema`` ONCE, returns raw
    (un-collapsed) extrema; raw extrema depend only on the ``[i-n,i+n]``
    window so are causal.
  - ``confirmed_swings_asof(raw, t)`` filters to ``confirmation_idx <= t``
    then collapses.

Feature-definition note (P1·R2, 2026-05-15)
-------------------------------------------
A confirmed swing sequence is STRICTLY alternating HIGH/LOW, so consecutive
segments always alternate direction and always share an endpoint. The
PRD-v2 §3.3 draft formulas for ``impulse_score`` / ``corrective_score`` /
``trend_maturity`` were degenerate under that fact (consecutive-segment
same-direction is never true; consecutive-segment overlap is always true).
They were corrected to compare segments / swings TWO apart (same kind /
same direction) — the Elliott "progression vs overlap" primitive is a
non-adjacent comparison (wave 3 vs wave 1, wave 4 vs wave 1). The original
``seg_count_up`` / ``seg_count_down`` were near-constant (alternating
sequence => counts differ by <=1) and were replaced with informative
features. Full rationale in the loop log
(`docs/memos/20260515-chart_structure_loop_log.md`, P1·R2) and PRD §3.3.

K / tol / maturity_cap are PLACEHOLDER values (PRD §C) — no evidence
basis, to be calibrated in Phase 2A.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from core.intraday.sr_swing import detect_swing_extrema

HIGH = "HIGH"
LOW = "LOW"

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "swing_structure.yaml"


# ---------------------------------------------------------------------------
# P1·R1 — causal swing core
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SwingPoint:
    """A swing extremum in a single symbol's bar sequence.

    idx               positional index into the bar sequence (0-based).
    price             swing price.
    kind              ``HIGH`` or ``LOW``.
    confirmation_idx  ``idx + swing_n`` — first bar index at which this
                      swing is causally confirmable (PRD §3.4).
    """

    idx: int
    price: float
    kind: str
    confirmation_idx: int


@dataclass(frozen=True)
class SwingStructureConfig:
    """family T config.

    ``swing_n`` is a FACT default (= ``detect_swing_extrema`` ``n=5``).
    ``K`` / ``tol`` / ``maturity_cap`` are PLACEHOLDER values per PRD §C —
    no evidence basis, calibrated in Phase 2A. Real runs load these from
    ``config/swing_structure.yaml`` via ``load_swing_structure_config``.
    """

    swing_n: int = 5
    K: int = 8
    tol: float = 0.15
    maturity_cap: int = 5


def detect_raw_swings(
    bars: pd.DataFrame, cfg: SwingStructureConfig
) -> list[SwingPoint]:
    """Raw (un-collapsed) swing extrema for one symbol, idx-ascending.

    Runs ``detect_swing_extrema`` ONCE (compute-once, execution PRD §B-B1).
    A bar flagged BOTH swing-high and swing-low is dropped (degenerate).
    """
    ext = detect_swing_extrema(bars, n=cfg.swing_n)
    is_high = ext["is_swing_high"].to_numpy()
    is_low = ext["is_swing_low"].to_numpy()
    high = bars["high"].to_numpy()
    low = bars["low"].to_numpy()

    out: list[SwingPoint] = []
    for i in range(len(bars)):
        h = bool(is_high[i])
        ll = bool(is_low[i])
        if h and ll:
            continue
        if h:
            out.append(SwingPoint(i, float(high[i]), HIGH, i + cfg.swing_n))
        elif ll:
            out.append(SwingPoint(i, float(low[i]), LOW, i + cfg.swing_n))
    return out


def _fold_swing(out: list[SwingPoint], s: SwingPoint) -> None:
    """One step of the alternating collapse (execution PRD §B-B2): fold
    swing ``s`` into ``out`` in place. Consecutive same-kind keeps the more
    extreme (higher for HIGH, lower for LOW); ties keep the earlier point.

    The collapse is a left-fold, so folding swings one-at-a-time as they
    are confirmed produces the SAME result as batch-collapsing the whole
    confirmed set — this is what makes the incremental computation in
    ``compute_swing_structure_factors`` exact."""
    if not out:
        out.append(s)
        return
    last = out[-1]
    if s.kind != last.kind:
        out.append(s)
        return
    more_extreme = (
        s.price > last.price if s.kind == HIGH else s.price < last.price
    )
    if more_extreme:
        out[-1] = s


def _collapse_alternating(raw_swings: list[SwingPoint]) -> list[SwingPoint]:
    """Collapse an idx-ordered extrema list into a STRICTLY alternating
    HIGH/LOW sequence (left-fold of ``_fold_swing``)."""
    out: list[SwingPoint] = []
    for s in raw_swings:
        _fold_swing(out, s)
    return out


def confirmed_swings_asof(
    raw_swings: list[SwingPoint], t_idx: int
) -> list[SwingPoint]:
    """Strictly-alternating swing sequence causally confirmed as of bar
    ``t_idx`` (filter-then-collapse — see module docstring)."""
    confirmed = [s for s in raw_swings if s.confirmation_idx <= t_idx]
    return _collapse_alternating(confirmed)


# ---------------------------------------------------------------------------
# P1·R2 — 12 swing-structure features
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _Seg:
    """A segment between two consecutive swings of one symbol."""

    start_idx: int
    end_idx: int
    start_price: float
    end_price: float

    @property
    def length(self) -> float:
        return abs(self.end_price - self.start_price)

    @property
    def dur(self) -> int:
        return self.end_idx - self.start_idx

    @property
    def direction(self) -> int:
        if self.end_price > self.start_price:
            return 1
        if self.end_price < self.start_price:
            return -1
        return 0

    @property
    def slope(self) -> float:
        return (self.end_price - self.start_price) / self.dur if self.dur else np.nan

    @property
    def lo(self) -> float:
        return min(self.start_price, self.end_price)

    @property
    def hi(self) -> float:
        return max(self.start_price, self.end_price)


def _segments(window: list[SwingPoint]) -> list[_Seg]:
    return [
        _Seg(window[j].idx, window[j + 1].idx,
             window[j].price, window[j + 1].price)
        for j in range(len(window) - 1)
    ]


@dataclass(frozen=True)
class _Ctx:
    """Per-(symbol, date) feature-computation context."""

    window: list[SwingPoint]   # last <=K confirmed swings, alternating
    segs: list[_Seg]           # len(window) - 1 segments
    t_idx: int
    cfg: SwingStructureConfig


# --- 12 feature operators -- each returns a float (np.nan when undefined) --
def _feat_last_up_seg_len_pct(c: _Ctx) -> float:
    """Most recent up-segment length as a fraction of its start price."""
    for seg in reversed(c.segs):
        if seg.direction == 1 and seg.start_price > 0:
            return seg.length / seg.start_price
    return np.nan


def _feat_net_drift_k(c: _Ctx) -> float:
    """Signed net price displacement across the K-swing window."""
    if len(c.window) < 2 or c.window[0].price <= 0:
        return np.nan
    return (c.window[-1].price - c.window[0].price) / c.window[0].price


def _feat_last_seg_len_ratio(c: _Ctx) -> float:
    """len(latest segment) / len(prior segment)."""
    m = len(c.segs)
    if m < 2 or c.segs[m - 2].length == 0:
        return np.nan
    return c.segs[m - 1].length / c.segs[m - 2].length


def _feat_last_seg_slope_ratio(c: _Ctx) -> float:
    """|slope(latest)| / |slope(prior)|."""
    m = len(c.segs)
    if m < 2:
        return np.nan
    s_prev = abs(c.segs[m - 2].slope)
    if not np.isfinite(s_prev) or s_prev == 0:
        return np.nan
    s_last = abs(c.segs[m - 1].slope)
    return s_last / s_prev if np.isfinite(s_last) else np.nan


def _retrace_ratio(c: _Ctx) -> float:
    """r = len(latest segment) / len(prior segment) — the retracement
    ratio. (In an alternating sequence the latest and prior segments are
    always opposite-direction, so the PRD-draft 'if opposite' guard is
    always true and dropped.)"""
    m = len(c.segs)
    if m < 2 or c.segs[m - 2].length == 0:
        return np.nan
    return c.segs[m - 1].length / c.segs[m - 2].length


def _feat_fib_retrace_fit_382(c: _Ctx) -> float:
    r = _retrace_ratio(c)
    if not np.isfinite(r):
        return np.nan
    return max(0.0, 1.0 - abs(r - 0.382) / c.cfg.tol)


def _feat_fib_retrace_fit_618(c: _Ctx) -> float:
    r = _retrace_ratio(c)
    if not np.isfinite(r):
        return np.nan
    return max(0.0, 1.0 - abs(r - 0.618) / c.cfg.tol)


def _same_kind_pair_signs(window: list[SwingPoint]) -> list[int]:
    """For each same-kind swing pair (S[i], S[i-2]), i>=2: +1 if S[i] is a
    higher extreme, -1 if lower, 0 if equal. i and i-2 are same kind
    because the sequence strictly alternates."""
    signs: list[int] = []
    for i in range(2, len(window)):
        d = window[i].price - window[i - 2].price
        signs.append(1 if d > 0 else (-1 if d < 0 else 0))
    return signs


def _feat_impulse_score(c: _Ctx) -> float:
    """Directional progression: |#up - #down| / #pairs over same-kind
    swing pairs. 1 = every same-kind swing extends one direction (clean
    impulse); ~0 = balanced (choppy). Corrected P1·R2 — see module doc."""
    signs = _same_kind_pair_signs(c.window)
    nu = sum(1 for s in signs if s == 1)
    nd = sum(1 for s in signs if s == -1)
    npair = nu + nd
    if npair == 0:
        return np.nan
    return abs(nu - nd) / npair


def _feat_corrective_score(c: _Ctx) -> float:
    """Fraction of segment pairs (seg[j], seg[j-2]) — same direction,
    2 apart — whose price ranges overlap. High = corrective/choppy.
    Corrected P1·R2 — adjacent-segment overlap is degenerate (shared
    endpoint => always overlaps)."""
    m = len(c.segs)
    if m < 3:
        return np.nan
    n_pair = 0
    n_overlap = 0
    for j in range(2, m):
        a, b = c.segs[j], c.segs[j - 2]
        n_pair += 1
        if max(a.lo, b.lo) <= min(a.hi, b.hi):
            n_overlap += 1
    return n_overlap / n_pair if n_pair else np.nan


def _feat_trend_maturity(c: _Ctx) -> float:
    """Run length of consecutive most-recent same-direction same-kind
    swing pairs, normalised by maturity_cap and clipped to [0,1].
    Corrected P1·R2."""
    signs = _same_kind_pair_signs(c.window)
    if not signs:
        return np.nan
    d_last = signs[-1]
    if d_last == 0:
        return np.nan
    run = 0
    for s in reversed(signs):
        if s == d_last:
            run += 1
        else:
            break
    cap = c.cfg.maturity_cap
    return min(1.0, run / cap) if cap > 0 else np.nan


def _feat_high_low_overlap_pct(c: _Ctx) -> float:
    """Wave-4-overlaps-wave-1 proxy: price-range overlap of the latest
    segment and the segment 2 before it (same direction), as a fraction
    of the latest segment length."""
    m = len(c.segs)
    if m < 3:
        return np.nan
    a, b = c.segs[m - 1], c.segs[m - 3]
    if a.length == 0:
        return np.nan
    overlap = max(0.0, min(a.hi, b.hi) - max(a.lo, b.lo))
    return min(1.0, overlap / a.length)


def _feat_seg_len_dispersion(c: _Ctx) -> float:
    """Coefficient of variation of segment lengths over the window."""
    if len(c.segs) < 2:
        return np.nan
    lens = np.array([s.length for s in c.segs], dtype=float)
    mean = lens.mean()
    if mean == 0:
        return np.nan
    return float(lens.std() / mean)


def _feat_since_last_swing_bars(c: _Ctx) -> float:
    """Bars since the most recent confirmed swing."""
    if not c.window:
        return np.nan
    return float(c.t_idx - c.window[-1].idx)


# Fixed feature order (PRD §3.3, P1·R2-corrected). FEATURE_REGISTRY is the
# D4 extension hook: add a new (name, operator) entry to extend family T.
FEATURE_REGISTRY: dict[str, callable] = {
    "swing_last_up_seg_len_pct": _feat_last_up_seg_len_pct,
    "swing_net_drift_k": _feat_net_drift_k,
    "swing_last_seg_len_ratio": _feat_last_seg_len_ratio,
    "swing_last_seg_slope_ratio": _feat_last_seg_slope_ratio,
    "swing_fib_retrace_fit_382": _feat_fib_retrace_fit_382,
    "swing_fib_retrace_fit_618": _feat_fib_retrace_fit_618,
    "swing_impulse_score": _feat_impulse_score,
    "swing_corrective_score": _feat_corrective_score,
    "swing_trend_maturity": _feat_trend_maturity,
    "swing_high_low_overlap_pct": _feat_high_low_overlap_pct,
    "swing_seg_len_dispersion": _feat_seg_len_dispersion,
    "swing_since_last_swing_bars": _feat_since_last_swing_bars,
}
SWING_STRUCTURE_FEATURES: tuple[str, ...] = tuple(FEATURE_REGISTRY.keys())


def load_swing_structure_config(path: Path | str | None = None) -> SwingStructureConfig:
    """Load family-T config from ``config/swing_structure.yaml`` (PRD §3.3:
    thresholds must come from config, never hardcoded)."""
    p = Path(path) if path is not None else _CONFIG_PATH
    with open(p, "r") as fh:
        raw = yaml.safe_load(fh) or {}
    return SwingStructureConfig(
        swing_n=int(raw["swing_n"]),
        K=int(raw["K"]),
        tol=float(raw["tol"]),
        maturity_cap=int(raw["maturity_cap"]),
    )


def _features_from_window(window: list[SwingPoint], t_idx: int,
                          cfg: SwingStructureConfig) -> dict[str, float]:
    """Compute all 12 features from an already-windowed swing sequence."""
    ctx = _Ctx(window=window, segs=_segments(window), t_idx=t_idx, cfg=cfg)
    return {name: op(ctx) for name, op in FEATURE_REGISTRY.items()}


def _features_at(raw: list[SwingPoint], t_idx: int,
                 cfg: SwingStructureConfig) -> dict[str, float]:
    """Reference (non-incremental) per-date feature computation — recollapses
    the full confirmed set every call. Kept for the equivalence test against
    the incremental path in ``compute_swing_structure_factors``."""
    conf = confirmed_swings_asof(raw, t_idx)
    window = conf[-cfg.K:] if len(conf) > cfg.K else conf
    return _features_from_window(window, t_idx, cfg)


def compute_swing_structure_factors(
    price_df: pd.DataFrame,
    high_df: pd.DataFrame | None = None,
    low_df: pd.DataFrame | None = None,
    cfg: SwingStructureConfig | None = None,
) -> dict[str, pd.DataFrame]:
    """Family-T swing-structure factors (PRD §3, §A.4 family pattern).

    Swings are detected on the **close** series (PRD §3.2: "对 adjusted
    close 序列"); ``high_df`` / ``low_df`` are accepted for signature
    consistency with the factor-generator family contract but unused.
    Returns ``{factor_name: wide DataFrame}`` sharing ``price_df``'s
    index / columns.

    Performance (execution PRD §B-B1 / §B-B7): ``detect_swing_extrema``
    runs once per symbol; the alternating collapse is folded
    INCREMENTALLY as each swing's ``confirmation_idx`` is reached, so the
    whole pass is O(T + E) per symbol, not O(T·E). Output is bit-identical
    to the reference ``_features_at`` path (guarded by an equivalence
    unit test).
    """
    if cfg is None:
        cfg = load_swing_structure_config()

    n_rows = len(price_df)
    out: dict[str, pd.DataFrame] = {
        name: pd.DataFrame(np.nan, index=price_df.index, columns=price_df.columns)
        for name in SWING_STRUCTURE_FEATURES
    }
    col_loc = {sym: price_df.columns.get_loc(sym) for sym in price_df.columns}

    for sym in price_df.columns:
        close = price_df[sym]
        bars = pd.DataFrame(
            {"high": close.to_numpy(), "low": close.to_numpy(),
             "close": close.to_numpy()},
            index=close.index,
        )
        raw = detect_raw_swings(bars, cfg)  # idx-ascending => conf-idx-ascending
        collapsed: list[SwingPoint] = []
        p = 0
        cj = col_loc[sym]
        for ti in range(n_rows):
            # fold in every swing confirmed as of bar ti
            while p < len(raw) and raw[p].confirmation_idx <= ti:
                _fold_swing(collapsed, raw[p])
                p += 1
            window = collapsed[-cfg.K:] if len(collapsed) > cfg.K else collapsed
            feats = _features_from_window(window, ti, cfg)
            for name, val in feats.items():
                out[name].iat[ti, cj] = val
    return out
