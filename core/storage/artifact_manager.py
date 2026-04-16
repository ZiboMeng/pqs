"""
ArtifactManager: manages run output directories, config snapshots, and latest symlinks.

Each run gets a timestamped directory:
    reports/{run_type}/runs/YYYYMMDD_HHMMSS_<tag>/
    reports/{run_type}/latest -> (symlink to most recent run)

Usage:
    from core.storage.artifact_manager import ArtifactManager
    am = ArtifactManager(reports_dir=Path("reports"))
    ctx = am.create_run("backtest", tag="ai_swing")
    ctx.save_df(result_df, "backtest_result.csv")
    ctx.save_yaml(config_dict, "config_snapshot.yaml")
    am.update_latest(ctx)
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
import yaml

from core.logging_setup import get_logger

logger = get_logger(__name__)


class RunContext:
    """
    A single run's output directory context.
    All writes go to self.run_dir.
    """

    def __init__(self, run_dir: Path, run_id: str, run_type: str, tag: str):
        self.run_dir = run_dir
        self.run_id = run_id
        self.run_type = run_type
        self.tag = tag
        self._manifest: Dict[str, Any] = {
            "run_id": run_id,
            "run_type": run_type,
            "tag": tag,
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
            "files": [],
        }

    # ── Write helpers ─────────────────────────────────────────────────────────

    def save_df(self, df: pd.DataFrame, filename: str, index: bool = True) -> Path:
        """Save a DataFrame as CSV."""
        path = self.run_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=index)
        self._track_file(filename, "csv")
        return path

    def save_parquet(self, df: pd.DataFrame, filename: str) -> Path:
        """Save a DataFrame as Parquet."""
        path = self.run_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=True)
        self._track_file(filename, "parquet")
        return path

    def save_yaml(self, data: Dict, filename: str) -> Path:
        """Save a dict as YAML."""
        path = self.run_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
        self._track_file(filename, "yaml")
        return path

    def save_text(self, content: str, filename: str) -> Path:
        """Save a text/markdown file."""
        path = self.run_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self._track_file(filename, "text")
        return path

    def save_figure(self, fig, filename: str, dpi: int = 150) -> Path:
        """Save a matplotlib figure."""
        path = self.run_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=dpi, bbox_inches="tight")
        self._track_file(filename, "figure")
        return path

    def path(self, filename: str) -> Path:
        """Return a path within the run directory (creates parent dirs)."""
        p = self.run_dir / filename
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    # ── Snapshot helpers ─────────────────────────────────────────────────────

    def snapshot_config_dir(self, config_dir: Path) -> None:
        """Copy the entire config directory into the run output."""
        dest = self.run_dir / "config_snapshot"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(config_dir, dest)
        logger.debug("Config snapshot saved to %s", dest)

    def write_manifest(self) -> Path:
        """Write run manifest JSON (call at end of run)."""
        self._manifest["completed_at"] = datetime.now(tz=timezone.utc).isoformat()
        path = self.run_dir / "manifest.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(self._manifest, f, indent=2)
        return path

    # ── Internal ─────────────────────────────────────────────────────────────

    def _track_file(self, filename: str, ftype: str) -> None:
        self._manifest["files"].append({"name": filename, "type": ftype})

    def __repr__(self) -> str:
        return f"RunContext(run_id={self.run_id!r}, dir={self.run_dir})"


class ArtifactManager:
    """
    Central manager for all run output directories.

    Directory layout:
        {reports_dir}/
        ├── daily/
        │   ├── runs/
        │   │   └── 20240115_163045_daily/
        │   └── latest -> runs/20240115_163045_daily
        ├── backtests/
        │   ├── runs/
        │   └── latest -> ...
        └── ...
    """

    RUN_TYPES = {"daily", "backtest", "paper_trading", "research", "optimize"}

    def __init__(self, reports_dir: Path):
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def create_run(self, run_type: str, tag: str = "") -> RunContext:
        """
        Create a new timestamped run directory.

        Args:
            run_type: one of 'daily', 'backtest', 'paper_trading', 'research', 'optimize'
            tag:      optional short label appended to the directory name

        Returns:
            RunContext for this run
        """
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_id = f"{ts}_{run_type}" + (f"_{tag}" if tag else "")
        run_dir = self.reports_dir / run_type / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Run started: %s → %s", run_id, run_dir)
        return RunContext(run_dir=run_dir, run_id=run_id, run_type=run_type, tag=tag)

    def update_latest(self, ctx: RunContext) -> None:
        """
        Update the `latest` symlink for a run_type to point to this run.
        Works on both macOS/Linux (symlink) and falls back to a text pointer.
        """
        latest_link = self.reports_dir / ctx.run_type / "latest"
        target = Path("runs") / ctx.run_id  # relative path

        try:
            if latest_link.is_symlink() or latest_link.exists():
                latest_link.unlink()
            latest_link.symlink_to(target)
            logger.debug("Updated latest symlink: %s → %s", latest_link, target)
        except OSError:
            # Fallback for environments that don't support symlinks
            latest_ptr = self.reports_dir / ctx.run_type / "latest.txt"
            latest_ptr.write_text(str(ctx.run_dir), encoding="utf-8")
            logger.debug("Updated latest pointer (text fallback): %s", latest_ptr)

    def get_latest_run_dir(self, run_type: str) -> Optional[Path]:
        """Return the directory of the most recent run for a given type."""
        latest_link = self.reports_dir / run_type / "latest"
        if latest_link.is_symlink():
            resolved = (self.reports_dir / run_type / latest_link.readlink()).resolve()
            return resolved if resolved.exists() else None

        latest_ptr = self.reports_dir / run_type / "latest.txt"
        if latest_ptr.exists():
            p = Path(latest_ptr.read_text(encoding="utf-8").strip())
            return p if p.exists() else None

        return None

    def list_runs(self, run_type: str, limit: int = 10) -> list[Path]:
        """List the most recent N run directories for a given type."""
        runs_dir = self.reports_dir / run_type / "runs"
        if not runs_dir.exists():
            return []
        dirs = sorted(
            (d for d in runs_dir.iterdir() if d.is_dir()),
            key=lambda d: d.name,
            reverse=True,
        )
        return dirs[:limit]

    def cleanup_old_runs(self, run_type: str, keep_n: int = 30) -> int:
        """Delete old run directories beyond the most recent keep_n."""
        all_runs = self.list_runs(run_type, limit=9999)
        to_delete = all_runs[keep_n:]
        for run_dir in to_delete:
            shutil.rmtree(run_dir, ignore_errors=True)
            logger.debug("Deleted old run: %s", run_dir)
        return len(to_delete)
