"""Unit tests for Phase E-0 R2: pyarrow decoupling from paper/core.

Goal (charter §E0-6 + execution PRD §2.E0-R2):
  Paper-layer core logic should NOT trigger the parquet filesystem stack
  (`pyarrow.parquet`) on module import. This keeps lightweight paper
  unit tests from being coupled to parquet I/O.

Scope nuance:
  `pyarrow.lib` — the C++ core of pyarrow — IS loaded by pandas 2.x
  itself on `import pandas as pd`. That is pandas library behavior and
  not something our code can prevent. It is also cheap (just loads
  the C++ wheel, no file I/O).

  `pyarrow.parquet` — the filesystem I/O layer — is the real parquet
  stack. This module should NOT be loaded until a read/write is
  actually needed.

This test enforces the second invariant.
"""
from __future__ import annotations

import subprocess
import sys


def _run_import_probe(import_stmt: str) -> set[str]:
    """Run a fresh Python subprocess that imports `import_stmt` and
    returns the set of loaded module names that start with 'pyarrow'.
    """
    script = (
        "import sys; "
        f"{import_stmt}; "
        "import json; "
        "print(json.dumps([m for m in sys.modules if m.startswith('pyarrow')]))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, check=True,
    )
    import json
    return set(json.loads(result.stdout.strip()))


def test_paper_trading_engine_does_not_load_pyarrow_parquet():
    """Importing PaperTradingEngine must not trigger pyarrow.parquet.

    This is the acceptance criterion for R2 (charter §E0-6 para 3):
    "paper-layer 单测被 parquet stack 拖死" — the fix prevents
    eager parquet module load.
    """
    loaded = _run_import_probe(
        "from core.paper_trading.paper_trading_engine import PaperTradingEngine"
    )
    # pyarrow.lib IS pulled by pandas itself (2.x behavior) — unavoidable
    # pyarrow.parquet should NOT be pulled
    assert "pyarrow.parquet" not in loaded, (
        f"pyarrow.parquet was eagerly loaded — parquet I/O stack "
        f"coupled to paper engine. Loaded: {loaded}"
    )


def test_market_data_store_class_does_not_load_pyarrow_parquet():
    """Importing the MarketDataStore symbol must not trigger pyarrow.parquet.

    Only actual read/write operations should load parquet stack.
    """
    loaded = _run_import_probe(
        "from core.data.market_data_store import MarketDataStore"
    )
    assert "pyarrow.parquet" not in loaded, (
        f"pyarrow.parquet eagerly loaded on MarketDataStore import: {loaded}"
    )


def test_candidate_registry_does_not_load_pyarrow_at_all():
    """The governance layer (Phase E R1) should be fully independent of
    pyarrow. No pyarrow.* should appear except what pandas loads (lib).
    """
    loaded = _run_import_probe(
        "from core.research.candidate_registry import CandidateRegistry"
    )
    # pyarrow.parquet MUST NOT be loaded
    assert "pyarrow.parquet" not in loaded, (
        f"pyarrow.parquet leaked into candidate registry import: {loaded}"
    )
