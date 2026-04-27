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
    return SimpleNamespace(universe=universe, backtest=backtest)


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
