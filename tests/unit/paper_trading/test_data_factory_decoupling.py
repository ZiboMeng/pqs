"""Phase E-post R4 (E-post-1): paper path ↔ MarketDataStore decoupling.

Locks in the PRD §4.1 acceptance criteria:
  - paper engine does not statically couple to MarketDataStore
  - paper-layer unit tests do not need to touch the parquet stack
  - scripts go through core.data.factory.create_default_store, not a
    direct MarketDataStore constructor call
  - factory's returned object satisfies the narrow PriceStore Protocol

Note on pyarrow: the PRD text "PaperTradingEngine import 不触发 pyarrow"
is achievable in spirit (our code does not import MarketDataStore from
the paper engine), but pandas itself pulls pyarrow via pandas.compat on
`import pandas` in this pandas version — that is environmental and out
of scope for this PRD. These tests verify the *structural* decoupling
invariants we CAN control.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Optional

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]


# ── Structural: paper engine does not import MarketDataStore ───────────────


def _static_imports(path: Path) -> set[str]:
    """Return dotted module names imported at top level by this file."""
    tree = ast.parse(path.read_text())
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                imports.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
    return imports


def test_paper_engine_does_not_import_market_data_store():
    """core/paper_trading/paper_trading_engine.py must not pull in
    MarketDataStore — paper layer owns orders/fills/PnL, not data."""
    eng = REPO_ROOT / "core" / "paper_trading" / "paper_trading_engine.py"
    imports = _static_imports(eng)
    assert "core.data.market_data_store" not in imports
    assert "core.data.factory" not in imports  # engine doesn't even need factory


def test_paper_scripts_use_factory_not_direct_store():
    """scripts/run_paper.py and scripts/run_paper_candidate.py must
    import via the factory, not the concrete store class."""
    for rel in ("scripts/run_paper.py", "scripts/run_paper_candidate.py"):
        path = REPO_ROOT / rel
        imports = _static_imports(path)
        assert "core.data.market_data_store" not in imports, (
            f"{rel} still imports core.data.market_data_store; should go "
            f"through core.data.factory.create_default_store"
        )
        assert "core.data.factory" in imports, (
            f"{rel} is missing the core.data.factory import"
        )


# ── Protocol satisfaction ──────────────────────────────────────────────────


class _FakeStore:
    """Minimal in-memory PriceStore implementation — no parquet, no
    filesystem, no pyarrow code path."""

    def __init__(self, data: dict[tuple[str, str], pd.DataFrame]):
        self._data = data

    def read(self, symbol: str, freq: str) -> Optional[pd.DataFrame]:
        return self._data.get((symbol, freq))


def test_protocol_recognizes_fake_store():
    """Runtime PriceStore Protocol must accept an in-memory fake — this
    proves paper-layer tests can inject fakes without touching
    MarketDataStore."""
    from core.data.factory import PriceStore

    fake = _FakeStore(data={})
    # runtime_checkable protocol — isinstance check works
    assert isinstance(fake, PriceStore)


def test_factory_returns_protocol_instance():
    """create_default_store(cfg) must produce a PriceStore-compatible
    object (the concrete type remains MarketDataStore today, but callers
    rely on the Protocol)."""
    from core.config.loader import load_config
    from core.data.factory import PriceStore, create_default_store

    cfg = load_config(REPO_ROOT / "config")
    store = create_default_store(cfg)
    assert isinstance(store, PriceStore)
    # Sanity: .read() on a known real symbol returns a DataFrame or None
    out = store.read("SPY", "1d")
    assert out is None or isinstance(out, pd.DataFrame)


# ── Paper scripts do not instantiate MarketDataStore by name ───────────────


def test_paper_scripts_do_not_instantiate_store_directly():
    """No `MarketDataStore(...)` call site should remain in the paper
    scripts — construction must flow through the factory."""
    for rel in ("scripts/run_paper.py", "scripts/run_paper_candidate.py"):
        text = (REPO_ROOT / rel).read_text()
        # Only allowed appearance of the identifier is inside a comment or
        # string; we assert the bare call-site pattern is gone.
        assert "MarketDataStore(" not in text, (
            f"{rel} still calls MarketDataStore(...) — use "
            "create_default_store(cfg) instead"
        )


# ── Paper unit-test surface doesn't require parquet ────────────────────────


def test_paper_engine_import_does_not_touch_parquet_files(tmp_path, monkeypatch):
    """Importing PaperTradingEngine must not trigger any filesystem
    read under data/ — this is the behavioral guarantee that tests in
    this file (and other paper unit tests) can run in a container
    without the data directory mounted."""
    accesses: list[str] = []
    orig_open = open

    def tracked_open(path, *a, **kw):
        if isinstance(path, (str, Path)):
            s = str(path)
            # Flag any data/ read during import
            if "/data/" in s and s.endswith((".parquet", ".db")):
                accesses.append(s)
        return orig_open(path, *a, **kw)

    # Patch builtins.open in the paper_trading module space for the
    # duration of the re-import
    import builtins
    monkeypatch.setattr(builtins, "open", tracked_open)
    # Force re-import
    mod_name = "core.paper_trading.paper_trading_engine"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    __import__(mod_name)
    assert accesses == [], (
        f"paper engine import touched data/ files: {accesses[:3]}"
    )
