"""Unit tests for ArtifactManager."""

import pytest
import pandas as pd
from pathlib import Path

from core.storage.artifact_manager import ArtifactManager, RunContext


@pytest.fixture
def reports_dir(tmp_path):
    return tmp_path / "reports"


@pytest.fixture
def am(reports_dir):
    return ArtifactManager(reports_dir=reports_dir)


class TestArtifactManager:
    def test_create_run_returns_context(self, am):
        ctx = am.create_run("backtest", tag="test")
        assert isinstance(ctx, RunContext)
        assert ctx.run_dir.exists()

    def test_run_dir_has_timestamp_prefix(self, am):
        ctx = am.create_run("backtest", tag="test")
        assert ctx.run_id.startswith("20")  # YYYYMMDD...

    def test_run_dir_contains_tag(self, am):
        ctx = am.create_run("backtest", tag="mytag")
        assert "mytag" in ctx.run_id

    def test_save_df_creates_csv(self, am):
        ctx = am.create_run("backtest")
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        path = ctx.save_df(df, "result.csv")
        assert path.exists()
        loaded = pd.read_csv(path, index_col=0)
        assert list(loaded.columns) == ["a", "b"]

    def test_save_yaml_creates_file(self, am):
        ctx = am.create_run("backtest")
        path = ctx.save_yaml({"key": "value"}, "config.yaml")
        assert path.exists()
        import yaml
        with path.open() as f:
            data = yaml.safe_load(f)
        assert data["key"] == "value"

    def test_save_text_creates_file(self, am):
        ctx = am.create_run("daily")
        path = ctx.save_text("# Report\nHello", "report.md")
        assert path.exists()
        assert "Hello" in path.read_text()

    def test_write_manifest(self, am):
        ctx = am.create_run("backtest")
        path = ctx.write_manifest()
        assert path.exists()
        import json
        manifest = json.loads(path.read_text())
        assert manifest["run_type"] == "backtest"
        assert "created_at" in manifest
        assert "completed_at" in manifest

    def test_update_latest_creates_symlink_or_pointer(self, am):
        ctx = am.create_run("daily")
        am.update_latest(ctx)
        latest = am.get_latest_run_dir("daily")
        assert latest is not None
        assert latest.exists()

    def test_list_runs_returns_most_recent_first(self, am):
        ctx1 = am.create_run("backtest", tag="first")
        ctx2 = am.create_run("backtest", tag="second")
        runs = am.list_runs("backtest")
        assert len(runs) == 2
        # most recent first (alphabetically descending by timestamp)
        assert runs[0].name > runs[1].name

    def test_cleanup_old_runs(self, am):
        for i in range(5):
            am.create_run("backtest", tag=f"run{i}")
        deleted = am.cleanup_old_runs("backtest", keep_n=2)
        assert deleted == 3
        remaining = am.list_runs("backtest")
        assert len(remaining) == 2
