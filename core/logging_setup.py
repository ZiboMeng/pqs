"""
Unified logging setup for PQS.

Usage:
    from core.logging_setup import get_logger, setup_logging
    setup_logging(level="INFO", log_dir=Path("reports/logs"))
    logger = get_logger(__name__)
    logger.info("System started")
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional

_INITIALIZED = False
_FMT = "%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    level: str = "INFO",
    log_dir: Optional[Path] = None,
    log_file: str = "pqs.log",
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
    rich_console: bool = True,
) -> None:
    """
    Configure root logger once. Safe to call multiple times (idempotent after first call).

    Args:
        level:        log level string (DEBUG/INFO/WARNING/ERROR)
        log_dir:      if provided, also write rotating file logs here
        log_file:     filename for the rotating file handler
        max_bytes:    max size before rotation (default 10 MB)
        backup_count: number of rotated backups to keep
        rich_console: use rich for coloured console output if available
    """
    global _INITIALIZED
    if _INITIALIZED:
        return
    _INITIALIZED = True

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove any existing handlers
    root.handlers.clear()

    # Console handler (rich if available, otherwise plain)
    console_handler = _build_console_handler(rich_console)
    root.addHandler(console_handler)

    # Rotating file handler (optional)
    if log_dir is not None:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            filename=log_dir / log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter(_FMT, datefmt=_DATE_FMT))
        root.addHandler(file_handler)

    # Silence noisy third-party loggers
    for noisy in ["yfinance", "urllib3", "requests", "httpx", "apscheduler"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _build_console_handler(use_rich: bool) -> logging.Handler:
    """Return a Rich console handler if available, otherwise a plain StreamHandler."""
    if use_rich:
        try:
            from rich.logging import RichHandler
            handler = RichHandler(
                rich_tracebacks=True,
                show_path=False,
                log_time_format="[%H:%M:%S]",
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            return handler
        except ImportError:
            pass

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FMT, datefmt=_DATE_FMT))
    return handler


def get_logger(name: str) -> logging.Logger:
    """
    Get a named logger. Call setup_logging() first to configure handlers.

    Args:
        name: typically __name__ of the calling module
    """
    return logging.getLogger(name)


def reset_logging() -> None:
    """Reset logging state (for tests only)."""
    global _INITIALIZED
    _INITIALIZED = False
    logging.getLogger().handlers.clear()
