"""Top-level system configuration schema."""

from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class PathsConfig(BaseModel):
    """Filesystem paths. All are relative to project root unless absolute."""

    data_dir: str = "data"
    reports_dir: str = "reports"
    config_dir: str = "config"
    db_path: str = "data/trading.db"

    def resolve(self, root: Path) -> "ResolvedPaths":
        return ResolvedPaths(
            data_dir=root / self.data_dir,
            reports_dir=root / self.reports_dir,
            config_dir=root / self.config_dir,
            db_path=root / self.db_path,
        )


class ResolvedPaths(BaseModel):
    """Absolute resolved paths (computed at runtime)."""

    model_config = {"arbitrary_types_allowed": True}

    data_dir: Path
    reports_dir: Path
    config_dir: Path
    db_path: Path


class LoggingConfig(BaseModel):
    level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    format: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    log_to_file: bool = True
    log_file_name: str = "pqs.log"
    max_bytes: int = Field(default=10 * 1024 * 1024, ge=0)  # 10 MB
    backup_count: int = Field(default=5, ge=0)


class AccountConfig(BaseModel):
    """Account-level settings."""

    initial_capital_usd: float = Field(default=10_000.0, ge=100)
    currency: str = "USD"
    timezone: str = "America/New_York"


class AlignmentConfig(BaseModel):
    """Runtime alignment check mode (PRD M3 / M13).

    mode='warn' (default): hash mismatch logs WARN but does not block
    mode='fail': hash mismatch raises AlignmentCheckError; live paper blocked
    live_only_fail=True: FAIL mode only applies to live paper; backtest /
        research always WARN even in fail mode. Recommended default for
        safety.
    """

    mode: str = Field(default="warn", pattern="^(warn|fail)$")
    live_only_fail: bool = True


class SystemConfig(BaseModel):
    """Global system settings."""

    env: str = Field(default="local", pattern="^(local|staging|aws)$")
    project_name: str = "pqs"
    version: str = "0.1.0"

    paths: PathsConfig = Field(default_factory=PathsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    account: AccountConfig = Field(default_factory=AccountConfig)
    alignment: AlignmentConfig = Field(default_factory=AlignmentConfig)
