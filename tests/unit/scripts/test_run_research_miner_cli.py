"""Unit tests for `scripts/run_research_miner.py` CLI args added during
research-cycle 2026-04-26-01:

  - ``--end-date``: enforces the criteria yaml's panel cutoff (G4).
  - ``--drop-symbols``: enforces the criteria yaml's drop_symbols list
    without mutating the frozen ``config/universe.yaml``.

These two flags carry the cycle's pre-registration discipline. If
either silently regresses, a future cycle could mine on data past
the criteria cutoff or include symbols the criteria excluded — both
would silently violate the criteria's immutability contract.

Tests target the CLI's panel-loading helper (`_load_price_volume`)
directly. Going through subprocess would also work but is slower
and adds noise.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[3]


def _load_runner_module():
    """Import scripts/run_research_miner.py as a module under a stable
    name so we can call ``_load_price_volume`` directly.
    """
    spec = importlib.util.spec_from_file_location(
        "run_research_miner_test_import",
        ROOT / "scripts" / "run_research_miner.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class _FakeStore:
    """Minimal MarketDataStore stand-in returning per-symbol daily frames.

    Each frame has columns close/open/high/low/volume indexed by a
    datetime index spanning 2020-01-01 → 2025-12-31 (1500+ trading days
    is overkill but tests don't care about exact length).
    """

    def __init__(self, symbols, start="2020-01-01", end="2025-12-31"):
        idx = pd.date_range(start, end, freq="B")
        self._frames = {
            sym: pd.DataFrame(
                {
                    "close": 100.0,
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "volume": 1_000_000,
                },
                index=idx,
            )
            for sym in symbols
        }

    def read(self, sym, freq):
        if freq != "1d":
            return None
        return self._frames.get(sym)


@pytest.fixture(autouse=True)
def _patch_adjusted_panel(monkeypatch):
    """P0-A (grand-audit, commit 7850b98) made `_load_price_volume`
    load split-adjusted data from disk via
    `core.data.price_access.load_adjusted_panel` and STOP using the
    injected `store` (intentional: the raw MarketDataStore.read path
    bypassed the split cascade — that was the whole P0-A bug). These
    CLI tests exercise the --end-date / --drop-symbols PLUMBING, not
    price adjustment, so we patch the disk loader with a synthetic
    builder spanning the same window the old `_FakeStore` used
    (2020-01-01 → 2025-12-31). Without this, post-P0-A the tests
    would hit real parquet (slow / environment-coupled) and the stub
    cfg would AttributeError on `cfg.system.paths.data_dir`.
    """
    def _fake_load_adjusted_panel(symbols, root, freq="1d", **kw):
        idx = pd.date_range("2020-01-01", "2025-12-31", freq="B")
        close = pd.DataFrame({s: 100.0 for s in symbols}, index=idx)
        return {
            "close": close,
            "open": close.copy(),
            "high": close.copy() + 1.0,
            "low": close.copy() - 1.0,
            "volume": pd.DataFrame({s: 1_000_000 for s in symbols},
                                   index=idx),
        }

    monkeypatch.setattr(
        "core.data.price_access.load_adjusted_panel",
        _fake_load_adjusted_panel,
    )


def _fake_cfg(seed_pool, sector_etfs=None, factor_etfs=None,
              cross_asset=None, blacklist=None, macro_reference=None,
              start_date="2020-01-01"):
    universe = SimpleNamespace(
        seed_pool=list(seed_pool),
        sector_etfs=list(sector_etfs or []),
        factor_etfs=list(factor_etfs or []),
        cross_asset=list(cross_asset or []),
        blacklist=list(blacklist or []),
        macro_reference=list(macro_reference or []),
    )
    backtest = SimpleNamespace(start_date=start_date)
    # P0-A: _load_price_volume resolves the data root via
    # cfg.system.paths.data_dir (the patched loader ignores it, but
    # the attribute must exist — production cfg always has it).
    system = SimpleNamespace(
        paths=SimpleNamespace(data_dir=str(ROOT / "data")))
    return SimpleNamespace(universe=universe, backtest=backtest,
                           system=system)


# ── --end-date ──────────────────────────────────────────────────────


def test_end_date_truncates_panel_to_at_or_before_cutoff():
    """Panel must end at-or-before the cutoff. No 2024+ rows allowed
    when cutoff=2023-12-31 (the actual G4 cutoff for cycle
    2026-04-26-01)."""
    mod = _load_runner_module()
    syms = ["AAA", "BBB", "SPY", "QQQ"]
    cfg = _fake_cfg(seed_pool=syms, start_date="2020-01-01")
    store = _FakeStore(syms)

    out, tradable = mod._load_price_volume(
        cfg, store, end_date="2023-12-31",
    )

    assert out["close"].index.max() <= pd.Timestamp("2023-12-31"), (
        "panel must not contain dates after G4 cutoff"
    )
    # Sanity: panel still has multi-year coverage
    assert out["close"].index.min() <= pd.Timestamp("2020-01-31")


def test_end_date_none_keeps_full_panel():
    """When --end-date is omitted, panel runs to last available bar
    (no silent truncation)."""
    mod = _load_runner_module()
    syms = ["AAA", "SPY"]
    cfg = _fake_cfg(seed_pool=syms, start_date="2020-01-01")
    store = _FakeStore(syms, end="2025-12-31")

    out, _ = mod._load_price_volume(cfg, store, end_date=None)

    assert out["close"].index.max() >= pd.Timestamp("2025-12-30")


def test_end_date_filters_open_high_low_volume_too():
    """All OHLCV frames must agree with the close index after cutoff.
    A frame mismatch would corrupt downstream factor generation."""
    mod = _load_runner_module()
    syms = ["AAA", "SPY"]
    cfg = _fake_cfg(seed_pool=syms, start_date="2020-01-01")
    store = _FakeStore(syms)

    out, _ = mod._load_price_volume(cfg, store, end_date="2022-06-30")

    cutoff = pd.Timestamp("2022-06-30")
    assert out["close"].index.max() <= cutoff
    for col in ("open", "high", "low", "volume"):
        assert out[col] is not None
        assert out[col].index.equals(out["close"].index), (
            f"{col} frame index diverged from close after end_date filter"
        )


# ── --drop-symbols ──────────────────────────────────────────────────


def test_drop_symbols_excludes_named_tickers_from_tradable():
    """BRK-B is the post-round-3-step-3b drop. The criteria yaml's
    drop_symbols list MUST be honored without mutating universe.yaml."""
    mod = _load_runner_module()
    syms = ["AAA", "BRK-B", "BBB", "SPY"]
    cfg = _fake_cfg(seed_pool=syms, start_date="2020-01-01")
    store = _FakeStore(syms)

    out, tradable = mod._load_price_volume(
        cfg, store, drop_symbols=["BRK-B"],
    )

    assert "BRK-B" not in tradable
    assert "BRK-B" not in out["close"].columns
    assert {"AAA", "BBB", "SPY"}.issubset(set(out["close"].columns))


def test_drop_symbols_none_keeps_all():
    """When --drop-symbols is omitted, every universe symbol stays."""
    mod = _load_runner_module()
    syms = ["AAA", "BRK-B", "SPY"]
    cfg = _fake_cfg(seed_pool=syms, start_date="2020-01-01")
    store = _FakeStore(syms)

    out, tradable = mod._load_price_volume(cfg, store, drop_symbols=None)

    assert set(tradable) == {"AAA", "BRK-B", "SPY"}
    assert "BRK-B" in out["close"].columns


def test_drop_symbols_does_not_mutate_universe_config_object():
    """Calling _load_price_volume must not mutate the cfg.universe
    seed_pool list — that's the whole point of having drop_symbols
    as a runtime arg instead of a config edit."""
    mod = _load_runner_module()
    seed = ["AAA", "BRK-B", "SPY"]
    cfg = _fake_cfg(seed_pool=seed, start_date="2020-01-01")
    store = _FakeStore(seed)

    mod._load_price_volume(cfg, store, drop_symbols=["BRK-B"])

    assert cfg.universe.seed_pool == seed, (
        "drop_symbols leaked into config — universe.yaml integrity broken"
    )


# ── combined ────────────────────────────────────────────────────────


def test_end_date_and_drop_symbols_compose():
    """Both flags must apply together. Real cycle uses both:
    end_date=2023-12-31 + drop_symbols=[BRK-B]."""
    mod = _load_runner_module()
    syms = ["AAA", "BRK-B", "SPY", "QQQ"]
    cfg = _fake_cfg(seed_pool=syms, start_date="2020-01-01")
    store = _FakeStore(syms)

    out, tradable = mod._load_price_volume(
        cfg, store,
        end_date="2023-12-31",
        drop_symbols=["BRK-B"],
    )

    assert "BRK-B" not in out["close"].columns
    assert out["close"].index.max() <= pd.Timestamp("2023-12-31")


# ── purge_labels_at_boundary integration (cycle #02 audit fix 2026-04-30) ──


def _build_split_cfg_for_purge_test():
    """Mini split config matching the audit-fix scenario: train years
    2009-2017+2020+2022+2024 with validation 2018/2019/2021/2023/2025
    (alternating regime). Forces non-contiguous train segments so
    fwd_returns near segment boundaries fall across calendar gaps.
    """
    from core.research.temporal_split import load_temporal_split
    return load_temporal_split(ROOT / "config" / "temporal_split.yaml")


def test_build_factor_panel_map_purges_cross_boundary_fwd_returns():
    """When split_cfg is provided and train years are non-contiguous
    (2009-2017+2020+2022+2024), forward-return labels at the LAST DAY
    of a train segment must be NaN'd out by purge_labels_at_boundary.

    Pre-fix (cycle #02 audit): the miner script never invoked
    purge_labels_at_boundary, so e.g. row 2017-12-29 carried a
    non-NaN fwd_return that spanned the 2018-2019 validation gap to
    a 2020-01-08 close.

    Post-fix: that row's fwd_return is NaN, signaling no IC contribution
    from gap-spanning labels.
    """
    mod = _load_runner_module()
    syms = ["AAA", "BBB", "SPY", "QQQ"]
    # Use only train years for the synthetic panel to mimic
    # post-restrict_frames_to_train state.
    train_dates = pd.bdate_range("2009-01-02", "2017-12-29").union(
        pd.bdate_range("2020-01-02", "2020-12-31")
    ).union(pd.bdate_range("2022-01-03", "2022-12-30")).union(
        pd.bdate_range("2024-01-02", "2024-12-31"))

    rng = pd.RangeIndex(len(train_dates))
    df = pd.DataFrame(
        {sym: 100.0 + rng for sym in syms},
        index=train_dates,
    )
    frames = {
        "close": df, "open": df, "high": df * 1.01,
        "low": df * 0.99, "volume": pd.DataFrame(
            {sym: 1_000_000 for sym in syms}, index=train_dates,
        ),
    }
    split_cfg = _build_split_cfg_for_purge_test()
    panel_map, fwd_h, mask, _ = mod._build_factor_panel_map(
        frames, syms, horizon=5, split_cfg=split_cfg,
    )

    # Last day of 2017 train segment: forward window crosses into
    # validation 2018 → row should be NaN-purged
    last_2017 = pd.Timestamp("2017-12-29")
    assert last_2017 in fwd_h.index
    assert fwd_h.loc[last_2017].isna().all(), (
        f"fwd_h at {last_2017} must be NaN (window crosses validation 2018) "
        f"but got {fwd_h.loc[last_2017].tolist()}"
    )

    # Mid-2015 deep in train → forward window stays in train → not purged
    mid_2015 = pd.Timestamp("2015-06-15")
    if mid_2015 in fwd_h.index:
        assert not fwd_h.loc[mid_2015].isna().all(), (
            f"fwd_h at {mid_2015} should NOT be all-NaN (deep in train)"
        )


def test_build_factor_panel_map_no_purge_when_split_cfg_none():
    """When split_cfg is None (no temporal-split mode), purge is a
    no-op — fwd_h matches pre-fix behavior so legacy non-split runs
    are unchanged."""
    mod = _load_runner_module()
    syms = ["AAA", "SPY"]
    idx = pd.bdate_range("2020-01-02", "2024-12-31")
    df = pd.DataFrame({sym: 100.0 + pd.RangeIndex(len(idx)) for sym in syms},
                       index=idx)
    frames = {
        "close": df, "open": df, "high": df * 1.01,
        "low": df * 0.99, "volume": pd.DataFrame(
            {sym: 1_000_000 for sym in syms}, index=idx),
    }
    panel_map, fwd_h, mask, _ = mod._build_factor_panel_map(
        frames, syms, horizon=5, split_cfg=None,
    )
    # Standard fwd_h: only the LAST 5 rows should be NaN (no future bars)
    last_5 = fwd_h.tail(5)
    earlier = fwd_h.iloc[:-10]
    assert last_5.isna().all().all(), "tail rows should be NaN (no future)"
    # Some earlier rows should be finite (no purge applied)
    assert earlier.notna().any().any(), (
        "without split_cfg, mid-panel fwd_returns should be finite"
    )
