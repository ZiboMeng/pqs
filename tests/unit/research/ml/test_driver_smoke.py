"""Light-weight smoke for dev/scripts/ml/walk_forward_rank_sign.py.

Real-data run is the deliverable verdict (see ledger Round 25). This
test only verifies:
  - CLI parses
  - --help exposes the key flags
  - module imports cleanly without triggering data load
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJ = Path(__file__).resolve().parents[4]
DRIVER = PROJ / "dev" / "scripts" / "ml" / "walk_forward_rank_sign.py"


def test_driver_help_exposes_key_flags():
    result = subprocess.run(
        [sys.executable, str(DRIVER), "--help"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    out = result.stdout
    for flag in ("--universe", "--horizon-days", "--start-year",
                 "--end-year", "--train-window", "--val-window",
                 "--model", "--features", "--save-dir", "--no-save"):
        assert flag in out, f"--help missing flag: {flag}"


def test_driver_module_imports_without_loading_data():
    """Just verify the driver module is importable as Python — does
    not call main() so no data load happens."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "walk_forward_rank_sign_driver", DRIVER,
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # main() exists and is callable
    assert callable(getattr(mod, "main", None))
    # key helpers exist
    for fn in ("_load_panel", "_slice_to_year_range", "_print_per_fold_table",
               "_filter_factors_to_panel", "_build_xgb_factory"):
        assert callable(getattr(mod, fn, None)), f"missing helper: {fn}"


def test_driver_rejects_expanded_v2_with_clear_message():
    """expanded_v2 wiring intentionally deferred to P4.5 acceptance per
    sub-step 3b scope; driver must refuse with non-zero exit + clear
    stderr message."""
    result = subprocess.run(
        [sys.executable, str(DRIVER), "--universe", "expanded_v2",
         "--no-save"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 2
    assert "expanded_v2" in result.stderr
    assert "P4.5" in result.stderr
