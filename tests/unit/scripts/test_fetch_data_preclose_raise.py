"""Unit tests for `scripts/fetch_data.py` pre-close RAISE guard
(2026-05-12 strengthening of 2026-04-29 WARN-and-cap behavior).

Before 2026-05-12:
  - CLI called pre-close → logger.warning("Pre-close fetch refused...")
  - Then proceeded to fetch through yesterday (capped) and exited 0.
  - Operator could miss the warning + assume fetch succeeded normally.

After 2026-05-12:
  - CLI called pre-close → raises SystemExit (non-zero status).
  - --allow-pre-close-today emergency override bypasses the raise.
  - The download_daily / download_intraday functions themselves retain
    the WARN-and-cap branch as defense-in-depth for programmatic callers
    that bypass main().

These tests target main() directly with monkey-patched
_today_session_status to simulate pre-close / post-close / non-trading
day scenarios.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[3]


def _load_fetch_data_module():
    """Import scripts/fetch_data.py as a module so we can patch internals."""
    if "fetch_data_test_import" in sys.modules:
        return sys.modules["fetch_data_test_import"]
    spec = importlib.util.spec_from_file_location(
        "fetch_data_test_import",
        ROOT / "scripts" / "fetch_data.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ── §1 pre-close path raises SystemExit ────────────────────────────────


def test_preclose_call_raises_systemexit(monkeypatch):
    """Pre-close call with no override → CLI raises SystemExit."""
    mod = _load_fetch_data_module()
    today_et = pd.Timestamp("2026-05-12")
    fake_status = (today_et, pd.Timestamp("2026-05-12 20:00", tz="UTC"), False)

    monkeypatch.setattr(mod, "_today_session_status", lambda: fake_status)
    monkeypatch.setattr(sys, "argv", ["fetch_data.py"])

    with pytest.raises(SystemExit) as ei:
        mod.main()
    assert "REFUSED" in str(ei.value)
    assert "pre-close" in str(ei.value)
    assert "--allow-pre-close-today" in str(ei.value)


def test_preclose_call_with_override_does_not_raise(monkeypatch):
    """--allow-pre-close-today bypasses the pre-close guard; downstream
    is not exercised (we mock load_config to raise once we know the guard
    cleared)."""
    mod = _load_fetch_data_module()
    today_et = pd.Timestamp("2026-05-12")
    fake_status = (today_et, pd.Timestamp("2026-05-12 20:00", tz="UTC"), False)

    monkeypatch.setattr(mod, "_today_session_status", lambda: fake_status)
    # Sentinel: once we pass the guard, load_config gets called → use it
    # as the test marker that we got past the raise without hitting it.
    sentinel_called = {"value": False}
    def _sentinel(*a, **kw):
        sentinel_called["value"] = True
        raise RuntimeError("sentinel — guard passed")
    monkeypatch.setattr(mod, "load_config", _sentinel)
    monkeypatch.setattr(sys, "argv", ["fetch_data.py", "--allow-pre-close-today"])

    with pytest.raises(RuntimeError, match="sentinel"):
        mod.main()
    assert sentinel_called["value"] is True


# ── §2 post-close path does NOT raise ──────────────────────────────────


def test_postclose_call_does_not_raise(monkeypatch):
    """Post-close call proceeds past guard into normal flow."""
    mod = _load_fetch_data_module()
    today_et = pd.Timestamp("2026-05-12")
    fake_status = (today_et, pd.Timestamp("2026-05-12 20:00", tz="UTC"), True)

    monkeypatch.setattr(mod, "_today_session_status", lambda: fake_status)
    sentinel_called = {"value": False}
    def _sentinel(*a, **kw):
        sentinel_called["value"] = True
        raise RuntimeError("sentinel — guard passed")
    monkeypatch.setattr(mod, "load_config", _sentinel)
    monkeypatch.setattr(sys, "argv", ["fetch_data.py"])

    with pytest.raises(RuntimeError, match="sentinel"):
        mod.main()
    assert sentinel_called["value"] is True


# ── §3 non-trading-day path does NOT raise (session_complete=True) ─────


def test_non_trading_day_does_not_raise(monkeypatch):
    """Weekend / holiday: _today_session_status returns
    session_complete=True even pre-"close" because there's no session;
    the guard must NOT fire."""
    mod = _load_fetch_data_module()
    saturday = pd.Timestamp("2026-05-09")  # Sat
    # On a non-trading day, _today_session_status returns close=None,
    # complete=True (line 109 of fetch_data.py).
    fake_status = (saturday, None, True)

    monkeypatch.setattr(mod, "_today_session_status", lambda: fake_status)
    sentinel_called = {"value": False}
    def _sentinel(*a, **kw):
        sentinel_called["value"] = True
        raise RuntimeError("sentinel — guard passed")
    monkeypatch.setattr(mod, "load_config", _sentinel)
    monkeypatch.setattr(sys, "argv", ["fetch_data.py"])

    with pytest.raises(RuntimeError, match="sentinel"):
        mod.main()
    assert sentinel_called["value"] is True


# ── §4 boundary: half-day session also raises pre-close ────────────────


def test_half_day_preclose_raises(monkeypatch):
    """Half-day sessions (Black Friday / Christmas Eve) close at 13:00 ET.
    Pre-close on those days (e.g., 11:00 ET) must still raise."""
    mod = _load_fetch_data_module()
    black_friday = pd.Timestamp("2026-11-27")  # half-day
    fake_status = (black_friday,
                   pd.Timestamp("2026-11-27 18:00", tz="UTC"),  # 13:00 ET
                   False)  # session NOT yet complete

    monkeypatch.setattr(mod, "_today_session_status", lambda: fake_status)
    monkeypatch.setattr(sys, "argv", ["fetch_data.py"])

    with pytest.raises(SystemExit) as ei:
        mod.main()
    assert "REFUSED" in str(ei.value)
