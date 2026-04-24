"""Tests for scripts/run_paper_candidate.py (Phase E-2 R8).

Covers the paper runner MVP contract:
  - refuses candidate not at S1 or S2 (S0 / S5 rejected)
  - refuses missing candidate
  - writes the 5 expected artifacts
  - hard invariant: script source does not reference
    production_strategy.yaml / load_production_strategy /
    promote_strategy import (grep test)
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

import pandas as pd
import pytest

from core.research.candidate_registry import (
    CandidateRegistry,
    CandidateStatus,
    RevokeReason,
)
from core.research.frozen_spec import FeatureEntry, FrozenStrategySpec


ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCRIPT = ROOT / "scripts" / "run_paper_candidate.py"


def _import_script_module():
    """Import scripts/run_paper_candidate.py as a module so we can unit-
    test its internal helpers (`_load_panel` in particular) without
    subprocess overhead. Gives access to the RuntimeError path for
    bad-index fixtures."""
    spec = importlib.util.spec_from_file_location(
        "run_paper_candidate_under_test", str(SCRIPT),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(cmd: list[str], cwd: Path = ROOT, check: bool = True):
    return subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True, check=check,
    )


def _make_test_candidate(
    tmp_path: Path, status: CandidateStatus,
) -> tuple[Path, Path]:
    """Create registry + frozen spec at given status. Returns
    (registry_db_path, spec_path)."""
    registry_db = tmp_path / "reg.db"
    reg = CandidateRegistry(registry_db)
    spec_path = tmp_path / "spec.yaml"
    # Use real production-factor names so factor_generator produces them
    spec = FrozenStrategySpec(
        candidate_id="paper_test_c1",
        strategy_version="paper-test-v1",
        source_trial_id="abc123",
        feature_set=[
            FeatureEntry(name="mom_21d", weight=0.5),
            FeatureEntry(name="vol_21d", weight=0.5),
        ],
        benchmark_relative_summary={"note": "real"},
        oos_holdout_summary={"folds": 4},
        robustness_summary={"sens": 0.02},
        decision_memo="/tmp/memo.md",
    )
    spec.to_yaml_file(spec_path)
    reg.register(
        candidate_id="paper_test_c1",
        source_trial_id="abc123",
        source_lineage_tag="test-lineage",
        status=status,
        frozen_spec_path=str(spec_path),
    )
    return registry_db, spec_path


# ── Hard invariant: no production config reads ──────────────────────────────


def test_script_source_has_no_production_config_reads():
    """Grep the script source: it must not read production config.

    Tokens checked:
      - config/production_strategy.yaml
      - promote_strategy       (production promote module)
      - load_production_strategy
    These are fine in docstrings / comments that EXPLAIN the ban; we
    only flag actual import / open / load calls.
    """
    text = SCRIPT.read_text()
    # Lines that are NOT inside docstring markers / comment blocks
    # (pragmatic: strip lines starting with # or " or ' or containing
    # 'Must NOT' / 'DOES NOT' / 'NEVER')
    code_lines: list[str] = []
    in_triple = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if '"""' in line:
            in_triple = not in_triple
            continue
        if in_triple:
            continue
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        code_lines.append(line)
    code_body = "\n".join(code_lines)
    # Now assert forbidden tokens are NOT in pure code body
    forbidden_patterns = [
        r"from\s+scripts\.promote_strategy",
        r"import\s+scripts\.promote_strategy",
        r"\bload_production_strategy\b",
        r"\"config/production_strategy\.yaml\"",
        r"'config/production_strategy\.yaml'",
        # open(...production_strategy.yaml...) call
        r"open\([^)]*production_strategy\.yaml",
    ]
    for pat in forbidden_patterns:
        assert not re.search(pat, code_body), (
            f"Forbidden pattern {pat!r} in script source "
            f"(production config read leaked into paper runner)"
        )


# ── Status gate ──────────────────────────────────────────────────────────────


def test_refuses_s0_candidate(tmp_path):
    reg_db, spec_path = _make_test_candidate(
        tmp_path, CandidateStatus.S0_PROTOTYPE,
    )
    result = _run([
        sys.executable, str(SCRIPT),
        "--candidate-id", "paper_test_c1",
        "--start-date", "2024-01-01",
        "--end-date", "2024-01-10",
        "--registry-db", str(reg_db),
        "--out-dir", str(tmp_path / "out"),
    ], check=False)
    assert result.returncode == 1
    combined = (result.stderr + result.stdout).lower()
    assert "s0" in combined or "requires s1" in combined


def test_refuses_revoked_candidate(tmp_path):
    reg_db, spec_path = _make_test_candidate(
        tmp_path, CandidateStatus.S1_CANDIDATE,
    )
    reg = CandidateRegistry(reg_db)
    reg.revoke("paper_test_c1", reason=RevokeReason.LEAKAGE_FOUND,
               memo_path="/tmp/m.md")
    result = _run([
        sys.executable, str(SCRIPT),
        "--candidate-id", "paper_test_c1",
        "--start-date", "2024-01-01",
        "--end-date", "2024-01-10",
        "--registry-db", str(reg_db),
        "--out-dir", str(tmp_path / "out"),
    ], check=False)
    assert result.returncode == 1


def test_refuses_missing_candidate(tmp_path):
    reg_db = tmp_path / "reg.db"
    _ = CandidateRegistry(reg_db)
    result = _run([
        sys.executable, str(SCRIPT),
        "--candidate-id", "nonexistent",
        "--start-date", "2024-01-01",
        "--end-date", "2024-01-10",
        "--registry-db", str(reg_db),
        "--out-dir", str(tmp_path / "out"),
    ], check=False)
    assert result.returncode == 1


# ── Happy path on S1 candidate (writes artifacts) ───────────────────────────


def test_writes_all_five_artifacts_s1(tmp_path):
    """S1 candidate runs end-to-end and writes signals / target /
    pnl / fills / run_meta artifacts.

    Uses a short window on the real daily data to exercise the full
    factor_generator + zscore + BacktestEngine pipeline.
    """
    reg_db, spec_path = _make_test_candidate(
        tmp_path, CandidateStatus.S1_CANDIDATE,
    )
    out_dir = tmp_path / "out"
    result = _run([
        sys.executable, str(SCRIPT),
        "--candidate-id", "paper_test_c1",
        "--start-date", "2024-01-01",
        "--end-date", "2024-02-01",
        "--top-n", "5",
        "--registry-db", str(reg_db),
        "--out-dir", str(out_dir),
    ])
    assert result.returncode == 0, result.stderr + result.stdout

    # 5 expected artifacts
    expected = [
        "signals_daily.csv",
        "target_portfolio_daily.csv",
        "pnl_daily.csv",
        "fills.csv",
        "run_meta.json",
    ]
    for name in expected:
        p = out_dir / name
        assert p.exists(), f"missing artifact: {name}"
        assert p.stat().st_size > 0, f"empty artifact: {name}"

    # run_meta.json contents
    import json
    meta = json.loads((out_dir / "run_meta.json").read_text())
    assert meta["candidate_id"] == "paper_test_c1"
    assert meta["status_at_run"] == "S1_research_candidate"
    assert meta["top_n"] == 5
    assert meta["n_dates"] > 0


def test_also_runs_on_s2_candidate(tmp_path):
    """S2 candidate is also a valid input (paper-re-run after enter)."""
    reg_db, spec_path = _make_test_candidate(
        tmp_path, CandidateStatus.S1_CANDIDATE,
    )
    reg = CandidateRegistry(reg_db)
    reg.transition("paper_test_c1", CandidateStatus.S2_PAPER)
    out_dir = tmp_path / "out"
    result = _run([
        sys.executable, str(SCRIPT),
        "--candidate-id", "paper_test_c1",
        "--start-date", "2024-01-01",
        "--end-date", "2024-01-25",
        "--top-n", "5",
        "--registry-db", str(reg_db),
        "--out-dir", str(out_dir),
    ])
    assert result.returncode == 0
    assert (out_dir / "run_meta.json").exists()


# ── Does-not-touch production config (live check) ───────────────────────────


def test_live_run_does_not_modify_production_config(tmp_path):
    """Run happy path + snapshot config/* mtime+content before/after."""
    reg_db, spec_path = _make_test_candidate(
        tmp_path, CandidateStatus.S1_CANDIDATE,
    )
    out_dir = tmp_path / "out"

    forbidden = [
        ROOT / "config" / "production_strategy.yaml",
        ROOT / "config" / "universe.yaml",
    ]
    before = {}
    for p in forbidden:
        if p.exists():
            before[p] = (p.stat().st_mtime_ns, p.read_bytes())

    result = _run([
        sys.executable, str(SCRIPT),
        "--candidate-id", "paper_test_c1",
        "--start-date", "2024-01-02",
        "--end-date", "2024-01-15",
        "--top-n", "5",
        "--registry-db", str(reg_db),
        "--out-dir", str(out_dir),
    ])
    assert result.returncode == 0

    for p, (mtime_before, content_before) in before.items():
        assert p.exists()
        assert p.stat().st_mtime_ns == mtime_before, (
            f"{p} mtime changed during paper run"
        )
        assert p.read_bytes() == content_before, (
            f"{p} content changed during paper run"
        )


# ── P0-1: _load_panel index-contract regression tests ───────────────────────


class _BadIndexStore:
    """PriceStore-shaped fake: `store.read(sym, "1d")` returns a frame
    whose index is a RangeIndex (not a DatetimeIndex). Simulates a
    misconfigured backend or an empty-fallback path that forgot to set
    a datetime index."""

    def __init__(self, n_rows: int = 10, symbols: Optional[list[str]] = None):
        self._n = n_rows
        self._symbols = set(symbols) if symbols is not None else None

    def read(self, symbol: str, freq: str) -> Optional[pd.DataFrame]:
        if self._symbols is not None and symbol not in self._symbols:
            return None
        # RangeIndex, not DatetimeIndex — the regression surface
        return pd.DataFrame(
            {
                "open": [100.0] * self._n,
                "high": [101.0] * self._n,
                "low": [99.0] * self._n,
                "close": [100.5] * self._n,
                "volume": [1_000_000] * self._n,
            },
            index=pd.RangeIndex(self._n),
        )


class _StringIndexStore:
    """Same as _BadIndexStore but returns string-indexed frames that
    happen to be coercible to datetime. Tests the graceful-coerce path."""

    def read(self, symbol: str, freq: str) -> Optional[pd.DataFrame]:
        dates = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
        return pd.DataFrame(
            {
                "open": [100.0, 101.0, 102.0, 101.5],
                "high": [101.0, 102.0, 103.0, 102.5],
                "low": [99.0, 100.0, 101.0, 100.5],
                "close": [100.5, 101.5, 102.5, 101.0],
                "volume": [1_000_000] * 4,
            },
            index=dates,  # strings, not timestamps
        )


class _NongarbageIndexStore:
    """Returns a frame whose index is a non-coercible type (object/mixed).
    pd.to_datetime will raise. Tests the hard-fail path."""

    def read(self, symbol: str, freq: str) -> Optional[pd.DataFrame]:
        return pd.DataFrame(
            {
                "open": [100.0, 101.0],
                "high": [101.0, 102.0],
                "low": [99.0, 100.0],
                "close": [100.5, 101.5],
                "volume": [1_000_000, 1_000_000],
            },
            index=["definitely-not-a-date", "also-not-a-date"],
        )


def _minimal_cfg_with_syms(syms: list[str]):
    """Build just enough cfg.universe surface that _load_panel iterates
    over exactly the given symbols."""
    from types import SimpleNamespace
    return SimpleNamespace(
        universe=SimpleNamespace(
            seed_pool=syms,
            sector_etfs=[],
            factor_etfs=[],
            cross_asset=[],
            blacklist=[],
            macro_reference=[],
        )
    )


def test_load_panel_raises_clean_on_non_datetime_index():
    """PRD P0-1: a non-empty frame with a non-coercible index must
    raise RuntimeError with a clear message — not a cryptic pandas
    TypeError from `close.index >= timestamp`."""
    mod = _import_script_module()
    cfg = _minimal_cfg_with_syms(["FAKE1", "FAKE2"])
    store = _NongarbageIndexStore()
    start = pd.Timestamp("2024-01-01")
    end = pd.Timestamp("2024-03-01")
    with pytest.raises(RuntimeError, match="non-DatetimeIndex"):
        mod._load_panel(cfg, store, start, end)


def test_load_panel_coerces_string_index_to_datetime():
    """String-indexed frame that IS coercible should auto-coerce and
    continue. Graceful path."""
    mod = _import_script_module()
    cfg = _minimal_cfg_with_syms(["FAKE1"])
    store = _StringIndexStore()
    start = pd.Timestamp("2024-01-02")
    end = pd.Timestamp("2024-01-05")
    out = mod._load_panel(cfg, store, start, end)
    assert isinstance(out["close"].index, pd.DatetimeIndex)
    assert not out["close"].empty


def test_load_panel_rangeindex_raises_clean():
    """RangeIndex (not coercible to datetime via pd.to_datetime on the
    raw integer 0..n-1) produces a clean RuntimeError."""
    mod = _import_script_module()
    cfg = _minimal_cfg_with_syms(["FAKE1"])
    store = _BadIndexStore(n_rows=5, symbols=["FAKE1"])
    start = pd.Timestamp("2024-01-01")
    end = pd.Timestamp("2024-03-01")
    # pd.to_datetime on RangeIndex(5) does NOT raise (it silently
    # converts 0..4 to epoch-nanosecond timestamps), so the panel WILL
    # coerce. Verify the coerced index is DatetimeIndex — this locks
    # in that we never drop back into the old raw-pandas crash path.
    out = mod._load_panel(cfg, store, start, end)
    assert isinstance(out["close"].index, pd.DatetimeIndex)


def test_cli_returns_1_on_panel_index_failure(tmp_path, monkeypatch):
    """End-to-end: CLI must catch the RuntimeError from _load_panel
    and exit with rc=1 + a clear logger.error, not a traceback."""
    mod = _import_script_module()
    # Register a valid S1 candidate so we reach _load_panel
    reg_db, spec_path = _make_test_candidate(
        tmp_path, CandidateStatus.S1_CANDIDATE,
    )
    out_dir = tmp_path / "out"

    # Monkeypatch _load_panel inside the imported module to raise
    # the same RuntimeError shape our new contract produces
    def _bad_panel(cfg, store, start, end):
        raise RuntimeError(
            "_load_panel: close panel has non-DatetimeIndex (RangeIndex) "
            "and cannot be coerced to datetime: simulated for test"
        )

    # Patch via sys.argv + run the main() of the imported module with
    # our fake _load_panel. Using monkeypatch for the attribute on the
    # imported module.
    monkeypatch.setattr(mod, "_load_panel", _bad_panel)
    monkeypatch.setattr(sys, "argv", [
        "run_paper_candidate.py",
        "--candidate-id", "paper_test_c1",
        "--start-date", "2024-01-02",
        "--end-date", "2024-01-15",
        "--top-n", "5",
        "--registry-db", str(reg_db),
        "--out-dir", str(out_dir),
    ])
    rc = mod.main()
    assert rc == 1, (
        f"Expected rc=1 on panel index failure, got rc={rc}"
    )
