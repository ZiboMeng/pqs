"""Per-scope hasher tests (PRD v2.1 §4.3 + §6 acceptance gates 2-4).

Determinism, NaN-safety, start-date anchoring, scope independence.
Uses synthetic panels so the tests don't depend on the live store.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from core.research.forward import (
    DEFAULT_BAR_REVISION,
    compute_bar_hash_rollup,
    compute_benchmark_hash,
    compute_execution_nav_hash,
    compute_signal_input_hash,
)
from core.research.frozen_spec import FrozenStrategySpec


# ── synthetic panel fixtures ──────────────────────────────────────


def _bday_index(start: str, end: str) -> pd.DatetimeIndex:
    return pd.bdate_range(start, end)


def _panel(symbols: list[str], start: str, end: str, seed: int = 0) -> dict:
    """Build a deterministic OHLCV panel for testing."""
    rng = np.random.default_rng(seed)
    idx = _bday_index(start, end)
    out: dict = {}
    for col, base in [("close", 100.0), ("open", 99.5), ("high", 101.0),
                       ("low", 99.0), ("volume", 1_000_000.0)]:
        df = pd.DataFrame(
            base + rng.standard_normal((len(idx), len(symbols))).cumsum(axis=0) * 0.1,
            index=idx, columns=symbols,
        )
        out[col] = df
    return out


def _spec(yaml_path: str) -> FrozenStrategySpec:
    return FrozenStrategySpec.from_yaml_file(yaml_path)


CAND_DIR = "data/research_candidates"


# ── determinism ───────────────────────────────────────────────────


def test_signal_input_hash_deterministic_across_two_runs():
    spec = _spec(f"{CAND_DIR}/rcm_v1_defensive_composite_01.yaml")
    universe = ["AAPL", "MSFT", "NVDA", "SPY"]
    panel = _panel(universe + ["QQQ"], "2026-01-02", "2026-04-28")
    h1, _ = compute_signal_input_hash(
        spec=spec, universe=universe, panel=panel, as_of_date=date(2026, 4, 27),
    )
    h2, _ = compute_signal_input_hash(
        spec=spec, universe=universe, panel=panel, as_of_date=date(2026, 4, 27),
    )
    assert h1 == h2 and len(h1) == 24


def test_execution_nav_hash_deterministic():
    panel = _panel(["AAPL", "MSFT"], "2026-04-20", "2026-04-28")
    h1, _ = compute_execution_nav_hash(
        held_or_traded_symbols=["AAPL", "MSFT"],
        panel=panel,
        start_date=date(2026, 4, 24),
        as_of_date=date(2026, 4, 28),
    )
    h2, _ = compute_execution_nav_hash(
        held_or_traded_symbols=["MSFT", "AAPL"],   # input order shouldn't matter
        panel=panel,
        start_date=date(2026, 4, 24),
        as_of_date=date(2026, 4, 28),
    )
    assert h1 == h2 and len(h1) == 24


def test_benchmark_hash_deterministic():
    panel = _panel(["SPY", "QQQ"], "2026-04-20", "2026-04-28")
    h1, _ = compute_benchmark_hash(
        benchmark_symbols=["SPY", "QQQ"], panel=panel,
        start_date=date(2026, 4, 24), as_of_date=date(2026, 4, 28),
    )
    h2, _ = compute_benchmark_hash(
        benchmark_symbols=["SPY", "QQQ"], panel=panel,
        start_date=date(2026, 4, 24), as_of_date=date(2026, 4, 28),
    )
    assert h1 == h2 and len(h1) == 24


def test_rollup_combines_three_hashes_deterministically():
    r1 = compute_bar_hash_rollup("a" * 24, "b" * 24, "c" * 24)
    r2 = compute_bar_hash_rollup("a" * 24, "b" * 24, "c" * 24)
    r3 = compute_bar_hash_rollup("a" * 24, "b" * 24, "d" * 24)
    assert r1 == r2 and r1 != r3


# ── NaN safety ────────────────────────────────────────────────────


def test_signal_input_hash_handles_nan_bars():
    """Symbols with NaN bars (delisting in flight, pre-IPO) must
    produce deterministic hashes, not crash or non-determinism."""
    spec = _spec(f"{CAND_DIR}/rcm_v1_defensive_composite_01.yaml")
    universe = ["AAPL", "MSFT", "SPY"]
    panel = _panel(universe + ["QQQ"], "2026-01-02", "2026-04-28")
    # Inject NaN into AAPL close on a few dates
    panel["close"].loc[pd.Timestamp("2026-04-20"), "AAPL"] = np.nan
    panel["close"].loc[pd.Timestamp("2026-04-21"), "AAPL"] = np.nan
    # track_per_cell=True so the NaN-cell digest entry is captured
    # for the assertion below; production runner uses default
    # track_per_cell=False (rolling hash alone is sufficient + 100x
    # smaller manifest).
    h1, inputs1 = compute_signal_input_hash(
        spec=spec, universe=universe, panel=panel, as_of_date=date(2026, 4, 27),
        track_per_cell=True,
    )
    h2, inputs2 = compute_signal_input_hash(
        spec=spec, universe=universe, panel=panel, as_of_date=date(2026, 4, 27),
        track_per_cell=True,
    )
    assert h1 == h2
    # NaN must surface in per_cell_digest under a deterministic key
    digest_aapl = inputs1.per_cell_digest.get("AAPL", {})
    assert digest_aapl  # cells captured
    assert all(isinstance(v, dict) for v in digest_aapl.values())


def test_signal_input_hash_per_cell_digest_empty_by_default():
    """Storage guard (post-audit fix): the rolling hash alone is
    sufficient for revision detection on signal_input scope, and
    storing the full ~80×252×2 cell grid would balloon the manifest
    to >100 MB by TD60. Default must be empty per_cell_digest."""
    spec = _spec(f"{CAND_DIR}/rcm_v1_defensive_composite_01.yaml")
    universe = ["AAPL", "MSFT", "SPY"]
    panel = _panel(universe + ["QQQ"], "2026-01-02", "2026-04-28")
    _, inputs = compute_signal_input_hash(
        spec=spec, universe=universe, panel=panel, as_of_date=date(2026, 4, 27),
    )
    assert inputs.per_cell_digest == {}, (
        "signal_input.per_cell_digest must default to empty to keep "
        "manifest size bounded; pass track_per_cell=True to opt in."
    )
    # And track_per_cell=True still works for tests that need fine
    # cell-level attribution.
    _, inputs_tracked = compute_signal_input_hash(
        spec=spec, universe=universe, panel=panel, as_of_date=date(2026, 4, 27),
        track_per_cell=True,
    )
    assert inputs_tracked.per_cell_digest != {}


def test_execution_nav_hash_handles_nan_open():
    panel = _panel(["AAPL"], "2026-04-20", "2026-04-28")
    panel["open"].loc[pd.Timestamp("2026-04-24"), "AAPL"] = np.nan
    h1, inputs = compute_execution_nav_hash(
        held_or_traded_symbols=["AAPL"], panel=panel,
        start_date=date(2026, 4, 24), as_of_date=date(2026, 4, 28),
    )
    assert len(h1) == 24
    # anchor_values stores None for NaN cells (deterministic JSON)
    aapl_anchor = inputs.materiality_anchor_values.get("AAPL", {})
    assert aapl_anchor.get("2026-04-24", {}).get("open") is None


# ── start-date anchoring (PRD v2.1 §G6) ───────────────────────────


def test_execution_nav_hash_anchored_at_start_date_not_as_of():
    """TD002 / TD003 / TD004 anchored at the same start_date must
    share the start_date contribution; only the trailing window
    extends."""
    panel = _panel(["AAPL", "MSFT"], "2026-04-20", "2026-05-05")
    syms = ["AAPL", "MSFT"]
    start = date(2026, 4, 24)
    h_td2, in_td2 = compute_execution_nav_hash(
        held_or_traded_symbols=syms, panel=panel,
        start_date=start, as_of_date=date(2026, 4, 27),
    )
    h_td3, in_td3 = compute_execution_nav_hash(
        held_or_traded_symbols=syms, panel=panel,
        start_date=start, as_of_date=date(2026, 4, 28),
    )
    h_td4, in_td4 = compute_execution_nav_hash(
        held_or_traded_symbols=syms, panel=panel,
        start_date=start, as_of_date=date(2026, 4, 29),
    )
    # All three TDs MUST share the same window_start
    assert in_td2.window_start == start == in_td3.window_start == in_td4.window_start
    # And the start-date close cell must appear identically in all 3
    for inputs in (in_td2, in_td3, in_td4):
        cell = inputs.per_cell_digest.get("AAPL", {}).get("2026-04-24", {})
        assert "close" in cell
        cell_msft = inputs.per_cell_digest.get("MSFT", {}).get("2026-04-24", {})
        assert "close" in cell_msft
    # start-date AAPL close digest is identical across TDs
    aapl_start_td2 = in_td2.per_cell_digest["AAPL"]["2026-04-24"]["close"]
    aapl_start_td3 = in_td3.per_cell_digest["AAPL"]["2026-04-24"]["close"]
    aapl_start_td4 = in_td4.per_cell_digest["AAPL"]["2026-04-24"]["close"]
    assert aapl_start_td2 == aapl_start_td3 == aapl_start_td4
    # But the rolling top-level hash differs because the window grows
    assert len({h_td2, h_td3, h_td4}) == 3


def test_execution_nav_hash_revision_to_start_date_propagates():
    """Mutating the start_date OHLC must change execution_nav_hash on
    EVERY TD anchored from that start_date (PRD v2.1 acceptance gate 4).
    """
    panel_a = _panel(["AAPL"], "2026-04-20", "2026-04-30", seed=0)
    panel_b_dict = {k: v.copy() for k, v in panel_a.items()}
    # Revise the start-date close
    panel_b_dict["close"].loc[pd.Timestamp("2026-04-24"), "AAPL"] += 5.0

    syms = ["AAPL"]
    start = date(2026, 4, 24)

    pre_td2,  _ = compute_execution_nav_hash(
        held_or_traded_symbols=syms, panel=panel_a,
        start_date=start, as_of_date=date(2026, 4, 27),
    )
    pre_td3,  _ = compute_execution_nav_hash(
        held_or_traded_symbols=syms, panel=panel_a,
        start_date=start, as_of_date=date(2026, 4, 28),
    )
    post_td2, _ = compute_execution_nav_hash(
        held_or_traded_symbols=syms, panel=panel_b_dict,
        start_date=start, as_of_date=date(2026, 4, 27),
    )
    post_td3, _ = compute_execution_nav_hash(
        held_or_traded_symbols=syms, panel=panel_b_dict,
        start_date=start, as_of_date=date(2026, 4, 28),
    )
    # Both TDs must change because both anchor at start_date
    assert pre_td2 != post_td2
    assert pre_td3 != post_td3


# ── scope independence ────────────────────────────────────────────


def test_revising_signal_only_does_not_change_execution_nav_hash():
    """A revision to a non-held universe symbol's signal-input cell
    changes signal_input_hash but NOT execution_nav_hash (held set
    only contains AAPL)."""
    spec = _spec(f"{CAND_DIR}/rcm_v1_defensive_composite_01.yaml")
    universe = ["AAPL", "MSFT", "NVDA", "SPY"]
    panel_a = _panel(universe + ["QQQ"], "2026-01-02", "2026-04-28", seed=0)
    panel_b = {k: v.copy() for k, v in panel_a.items()}
    # Revise NVDA volume on a recent date — affects amihud_20d signal
    panel_b["volume"].loc[pd.Timestamp("2026-04-22"), "NVDA"] *= 1.5

    pre_sig,  _ = compute_signal_input_hash(
        spec=spec, universe=universe, panel=panel_a, as_of_date=date(2026, 4, 27),
    )
    post_sig, _ = compute_signal_input_hash(
        spec=spec, universe=universe, panel=panel_b, as_of_date=date(2026, 4, 27),
    )
    assert pre_sig != post_sig

    # Held-or-traded set only includes AAPL — execution_nav must NOT change
    pre_exec,  _ = compute_execution_nav_hash(
        held_or_traded_symbols=["AAPL"], panel=panel_a,
        start_date=date(2026, 4, 24), as_of_date=date(2026, 4, 27),
    )
    post_exec, _ = compute_execution_nav_hash(
        held_or_traded_symbols=["AAPL"], panel=panel_b,
        start_date=date(2026, 4, 24), as_of_date=date(2026, 4, 27),
    )
    assert pre_exec == post_exec


# ── anchor ring + bar_revision pin ────────────────────────────────


def test_execution_nav_anchor_ring_default_10_days():
    panel = _panel(["AAPL"], "2026-04-01", "2026-04-28")
    _, inputs = compute_execution_nav_hash(
        held_or_traded_symbols=["AAPL"], panel=panel,
        start_date=date(2026, 4, 24), as_of_date=date(2026, 4, 28),
    )
    aapl_anchor = inputs.materiality_anchor_values.get("AAPL", {})
    # 10 trading days at-or-before 2026-04-28
    assert 0 < len(aapl_anchor) <= 10


# ── codex Round-10 Blocker 1: lookback uses real trading-day rows ──


def _real_panel_from_store(symbols: list[str], end: str = "2026-04-27") -> dict:
    """Load a panel from the real BarStore (NYSE trading calendar incl.
    holidays) so the BDay-vs-trading-day gap exposed by the production
    daily store can be tested.
    """
    from core.data.bar_store import BarStore
    store = BarStore()
    end_ts = pd.Timestamp(end)
    panels: dict = {}
    for attr in ("close", "open", "high", "low", "volume"):
        cols = {}
        for sym in symbols:
            try:
                df = store.load(sym, freq="daily", adjusted=True).sort_index()
            except Exception:
                continue
            df = df[df.index <= end_ts]
            if attr in df.columns:
                cols[sym] = df[attr]
        if cols:
            panels[attr] = pd.concat(cols, axis=1)
    return panels


def test_signal_input_hash_window_uses_actual_trading_day_rows():
    """Codex Round-10 Blocker 1 regression: ``compute_signal_input_hash``
    MUST resolve the lookback window from the panel's actual sorted
    DatetimeIndex (real trading rows), not from
    ``pd.tseries.offsets.BDay(lookback)``. ``BDay`` is a calendar-
    weekday offset that ignores US market holidays, so on the
    production daily store BDay(252) lands ~9 trading rows short of
    the true 252nd prior trading day. A revision on one of those
    omitted rows must still flip ``signal_input_hash``.
    """
    spec = _spec(f"{CAND_DIR}/rcm_v1_defensive_composite_01.yaml")
    universe = ["AAPL", "MSFT", "SPY"]
    panel = _real_panel_from_store(universe + ["QQQ"], end="2026-04-27")
    if not panel or "close" not in panel:
        pytest.skip("real store panel unavailable")
    as_of = date(2026, 4, 27)

    close_idx = panel["close"].index
    valid = close_idx[close_idx <= pd.Timestamp(as_of)]
    if len(valid) < 252:
        pytest.skip(f"panel has only {len(valid)} rows ≤ as_of; need ≥252")
    true_252nd_prior = valid[-252]

    # Sanity: the production store must expose the BDay-vs-trading-day
    # gap (NYSE holidays). If this fails, the test fixture isn't real.
    bday_start = (pd.Timestamp(as_of) - pd.tseries.offsets.BDay(252)).date()
    assert pd.Timestamp(bday_start) > true_252nd_prior, (
        f"production store should expose BDay-vs-trading-day gap "
        f"(BDay(252)={bday_start} vs true 252nd prior={true_252nd_prior.date()})"
    )

    h_pre, _ = compute_signal_input_hash(
        spec=spec, universe=universe, panel=panel, as_of_date=as_of,
    )

    panel_b = {k: v.copy() for k, v in panel.items()}
    panel_b["close"].loc[true_252nd_prior, "AAPL"] = (
        float(panel["close"].loc[true_252nd_prior, "AAPL"]) + 1.0
    )

    h_post, _ = compute_signal_input_hash(
        spec=spec, universe=universe, panel=panel_b, as_of_date=as_of,
    )

    assert h_post != h_pre, (
        "signal_input_hash must include the true 252nd prior trading "
        "row; revision on that row must flip the hash (Blocker 1 fix)"
    )


def test_signal_input_hash_window_covers_60d_and_126d_horizons():
    """Same Blocker-1 regression at the 126d horizon (Cand-2's
    rs_vs_spy_126d). BDay(126) is ~5 trading days short on a typical
    NYSE calendar slice spanning a Thanksgiving + Christmas window.
    """
    panel = _real_panel_from_store(["AAPL", "SPY"], end="2026-04-27")
    if not panel or "close" not in panel:
        pytest.skip("real store panel unavailable")
    as_of = date(2026, 4, 27)
    close_idx = panel["close"].index
    valid = close_idx[close_idx <= pd.Timestamp(as_of)]
    if len(valid) < 126:
        pytest.skip(f"panel has only {len(valid)} rows; need ≥126")

    spec_cand2 = _spec(f"{CAND_DIR}/candidate_2_orthogonal_01.yaml")
    universe = ["AAPL", "SPY"]

    true_126th = valid[-126]
    bday126 = (pd.Timestamp(as_of) - pd.tseries.offsets.BDay(126)).date()
    assert pd.Timestamp(bday126) > true_126th, (
        f"production store should expose 126d gap "
        f"(BDay(126)={bday126} vs true 126th prior={true_126th.date()})"
    )

    h_pre, _ = compute_signal_input_hash(
        spec=spec_cand2, universe=universe, panel=panel, as_of_date=as_of,
    )
    panel_b = {k: v.copy() for k, v in panel.items()}
    panel_b["close"].loc[true_126th, "AAPL"] = (
        float(panel["close"].loc[true_126th, "AAPL"]) + 1.0
    )
    h_post, _ = compute_signal_input_hash(
        spec=spec_cand2, universe=universe, panel=panel_b, as_of_date=as_of,
    )
    assert h_post != h_pre, (
        "126d window must reach true 126th prior trading row"
    )


def test_default_bar_revision_pinned():
    """Default bar_revision must reference the canonical store rebuild
    commit so mismatched stores (pre-rebuild vs post-rebuild) produce
    different hashes even on identical raw bars."""
    assert DEFAULT_BAR_REVISION.startswith("polygon_canonical_rebuild_")
    panel = _panel(["AAPL"], "2026-04-20", "2026-04-28")
    h1, _ = compute_execution_nav_hash(
        held_or_traded_symbols=["AAPL"], panel=panel,
        start_date=date(2026, 4, 24), as_of_date=date(2026, 4, 28),
    )
    h2, _ = compute_execution_nav_hash(
        held_or_traded_symbols=["AAPL"], panel=panel,
        start_date=date(2026, 4, 24), as_of_date=date(2026, 4, 28),
        bar_revision="some_other_revision_string",
    )
    assert h1 != h2
