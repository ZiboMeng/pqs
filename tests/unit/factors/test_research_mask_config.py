"""Phase E-post R5 (E-post-2): unified research mask config invariants.

Hard invariants locked by this file (PRD §4.2 + §10.2):
  1. Loader reads the right keys from config/research_mask.yaml
  2. Loader falls back to historical defaults when yaml is absent
  3. research_mask_default() equals research_mask(price, vol, 5.0, 20e6, 20)
     bit-for-bit on synthetic panels AND on real data
  4. The yaml values equal the historical hardcoded defaults
     (so the refactor does not silently change eligibility)
  5. No script still hardcodes the `{5.0, 20e6, 20}` triple

These tests are the enforcement layer of the §10.2 invariant:
  "Unified mask 在 post-2026-04-24-rcm-v1-lag1 lineage 窗口上产出的
   eligibility set 必须与 RCMv1 现有口径 bit-for-bit identical"
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from core.factors.base_masks import (
    _HISTORICAL_DEFAULTS,
    load_research_mask_params,
    research_mask,
    research_mask_default,
)


REPO_ROOT = Path(__file__).resolve().parents[3]


# ── Config loader ───────────────────────────────────────────────────────────


def test_default_config_exists():
    """The canonical config file must ship in the repo."""
    assert (REPO_ROOT / "config" / "research_mask.yaml").exists()


def test_loader_returns_historical_defaults_from_default_path():
    """Reading the default config must yield exactly the historical
    defaults — the bit-identical invariant."""
    params = load_research_mask_params(
        REPO_ROOT / "config" / "research_mask.yaml"
    )
    assert params["min_price"] == _HISTORICAL_DEFAULTS["min_price"]
    assert params["min_usd"] == _HISTORICAL_DEFAULTS["min_usd"]
    assert params["window"] == _HISTORICAL_DEFAULTS["window"]


def test_loader_falls_back_when_file_missing(tmp_path):
    """A missing yaml must return the frozen historical defaults
    (fresh-clone / CI safety)."""
    missing = tmp_path / "nonexistent.yaml"
    params = load_research_mask_params(missing)
    assert params == _HISTORICAL_DEFAULTS


def test_loader_partial_yaml_fills_gaps_with_defaults(tmp_path):
    """A partial yaml (only min_price set) must use defaults for the
    unset keys — prevents silent surprise if a reviewer drops a key."""
    partial = tmp_path / "partial.yaml"
    partial.write_text("research_mask:\n  min_price: 7.5\n")
    params = load_research_mask_params(partial)
    assert params["min_price"] == 7.5
    assert params["min_usd"] == _HISTORICAL_DEFAULTS["min_usd"]
    assert params["window"] == _HISTORICAL_DEFAULTS["window"]


def test_yaml_values_equal_historical_defaults():
    """Direct yaml parse (no loader) — the values in the shipped yaml
    file must literally match the historical hardcoded defaults."""
    path = REPO_ROOT / "config" / "research_mask.yaml"
    doc = yaml.safe_load(path.read_text())
    section = doc["research_mask"]
    assert float(section["min_price"]) == _HISTORICAL_DEFAULTS["min_price"]
    assert float(section["min_usd"]) == _HISTORICAL_DEFAULTS["min_usd"]
    assert int(section["window"]) == _HISTORICAL_DEFAULTS["window"]


# ── Bit-for-bit equivalence on synthetic panels ─────────────────────────────


def _build_synthetic_panel(seed: int = 42, n_days: int = 60, n_syms: int = 8):
    """Panel with realistic price/volume distribution for mask testing."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n_days, freq="B")
    syms = [f"SYM{i:02d}" for i in range(n_syms)]
    # Prices mostly above $5 but sprinkle some below to exercise price floor
    base_price = rng.uniform(3.0, 80.0, size=n_syms)
    daily_ret = rng.normal(0, 0.02, size=(n_days, n_syms))
    prices = base_price * np.cumprod(1 + daily_ret, axis=0)
    # Volumes: uniform 10k–5M shares — dollar volume crosses the 20M gate
    volumes = rng.uniform(10_000, 5_000_000, size=(n_days, n_syms))
    close_df = pd.DataFrame(prices, index=dates, columns=syms)
    vol_df = pd.DataFrame(volumes, index=dates, columns=syms)
    return close_df, vol_df


def test_default_equals_inline_call_synthetic():
    """research_mask_default(close, vol) must equal
    research_mask(close, vol, 5.0, 20e6, 20) elementwise — the full
    post-refactor invariant."""
    close, vol = _build_synthetic_panel()
    m_old = research_mask(close, vol, min_price=5.0, min_usd=20e6, window=20)
    m_new = research_mask_default(
        close, vol,
        config_path=REPO_ROOT / "config" / "research_mask.yaml",
    )
    # Shape / index / columns exactly match
    assert m_old.shape == m_new.shape
    assert list(m_old.index) == list(m_new.index)
    assert list(m_old.columns) == list(m_new.columns)
    # Bit-for-bit values match
    pd.testing.assert_frame_equal(m_old, m_new, check_dtype=True)


def test_default_equals_inline_call_multiple_seeds():
    """Run the invariant over 5 synthetic panels to prove it's not a
    single-seed coincidence."""
    cfg = REPO_ROOT / "config" / "research_mask.yaml"
    for seed in (1, 7, 99, 123, 2024):
        close, vol = _build_synthetic_panel(seed=seed)
        m_old = research_mask(close, vol,
                              min_price=5.0, min_usd=20e6, window=20)
        m_new = research_mask_default(close, vol, config_path=cfg)
        pd.testing.assert_frame_equal(m_old, m_new, check_dtype=True)


def test_default_uses_overridden_config(tmp_path):
    """Passing a non-default config_path must change behavior — proves
    the path is plumbed through."""
    close, vol = _build_synthetic_panel()
    override = tmp_path / "override.yaml"
    override.write_text(
        "research_mask:\n  min_price: 50.0\n  min_usd: 20000000\n  window: 20\n"
    )
    m_ovr = research_mask_default(close, vol, config_path=override)
    m_def = research_mask_default(
        close, vol,
        config_path=REPO_ROOT / "config" / "research_mask.yaml",
    )
    # With min_price=50, many more cells must be masked out
    assert m_ovr.sum().sum() < m_def.sum().sum()


# ── Migration coverage — no script may hardcode the triple ──────────────────


_HARDCODE_PATTERN = re.compile(
    r"research_mask\s*\(\s*\w+\s*,\s*\w+\s*,\s*min_price\s*="
)


def test_no_script_hardcodes_the_triple():
    """After R5 migration, no script should call
    `research_mask(X, Y, min_price=..., min_usd=..., window=...)` —
    they must all go through `research_mask_default`."""
    scripts_dir = REPO_ROOT / "scripts"
    offenders = []
    for py in scripts_dir.glob("*.py"):
        text = py.read_text()
        if _HARDCODE_PATTERN.search(text):
            offenders.append(py.name)
    assert offenders == [], (
        f"{len(offenders)} scripts still hardcode the research_mask triple: "
        f"{offenders}. Migrate them to research_mask_default(close, vol)."
    )


# ── Real-data invariant check (skipped if data absent) ──────────────────────


def test_bit_identical_on_real_universe_panel():
    """Run both paths on a real tradable universe panel. Must diff to
    zero — this is the §10.2 invariant in its operational form.

    Skips if the data directory is unavailable (CI / fresh clone)."""
    try:
        from core.config.loader import load_config
        from core.data.factory import create_default_store
    except ImportError:
        pytest.skip("config/data factory unavailable")

    cfg = load_config(REPO_ROOT / "config")
    store = create_default_store(cfg)
    uni = cfg.universe
    syms = [s for s in dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs)
        + list(uni.factor_etfs) + list(uni.cross_asset)
    ) if s not in uni.blacklist and s not in uni.macro_reference]

    # Build a close + volume panel
    close_frames = {}
    vol_frames = {}
    for sym in syms[:20]:  # top 20 for test-speed; invariant is panel-wide
        df = store.read(sym, "1d")
        if df is None or df.empty or "close" not in df.columns:
            continue
        close_frames[sym] = df["close"]
        if "volume" in df.columns:
            vol_frames[sym] = df["volume"]
    if len(close_frames) < 5:
        pytest.skip("not enough real-data symbols (<5)")
    close = pd.DataFrame(close_frames).sort_index()
    vol = pd.DataFrame(vol_frames).reindex_like(close)
    # Use the RCMv1 lag1 window (post-2026-04-24 lineage)
    close = close.loc[close.index >= "2015-01-01"]
    vol = vol.loc[vol.index >= "2015-01-01"]

    m_old = research_mask(close, vol, min_price=5.0, min_usd=20e6, window=20)
    m_new = research_mask_default(
        close, vol,
        config_path=REPO_ROOT / "config" / "research_mask.yaml",
    )
    pd.testing.assert_frame_equal(m_old, m_new, check_dtype=True)
    # Diff count is exactly zero — this is the bit-identical guarantee
    assert int((m_old != m_new).sum().sum()) == 0
