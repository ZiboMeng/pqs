from __future__ import annotations

from pathlib import Path

from core.data.bar_store import BarStore, resolve_default_root


def test_default_root_is_project_relative_not_developer_home(monkeypatch):
    monkeypatch.delenv("PQS_DATA_DIR", raising=False)
    root = resolve_default_root()
    assert root.name == "data"
    assert BarStore().root == root


def test_default_root_honors_explicit_environment_override(monkeypatch, tmp_path):
    requested = tmp_path / "market-data"
    monkeypatch.setenv("PQS_DATA_DIR", str(requested))
    assert resolve_default_root() == requested.resolve()
    assert BarStore().root == requested.resolve()


def test_explicit_constructor_root_has_highest_priority(monkeypatch, tmp_path):
    monkeypatch.setenv("PQS_DATA_DIR", str(tmp_path / "environment"))
    explicit = Path("relative-data")
    assert BarStore(explicit).root == explicit
