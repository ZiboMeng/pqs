"""
Notifier base classes: abstract Notifier, Level enum, SendResult, RateLimiter.

Design:
  - `Notifier.send(title, body, level)` returns a `SendResult` — never raises
    on transport failure (so trading loops can call it defensively).
  - Level is a gate: messages below `min_level` return `skipped_reason="level"`.
  - Rate limiter is per-notifier, sliding 60s window.
  - Backends are plain Notifier subclasses in `core.notify.backends`.
  - Factory `get_notifier(cfg)` resolves config dict → concrete backend.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import IntEnum
from threading import Lock
from typing import Optional


class Level(IntEnum):
    """Message severity. Higher = more important."""
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50


_LEVEL_ALIAS = {
    "debug": Level.DEBUG,
    "info": Level.INFO,
    "warning": Level.WARNING,
    "warn": Level.WARNING,
    "error": Level.ERROR,
    "critical": Level.CRITICAL,
    "fatal": Level.CRITICAL,
}


def parse_level(value) -> Level:
    """Accept Level, str ('info'/'warning'/…), or int. Unknown → INFO."""
    if isinstance(value, Level):
        return value
    if isinstance(value, str):
        return _LEVEL_ALIAS.get(value.strip().lower(), Level.INFO)
    if isinstance(value, int):
        try:
            return Level(value)
        except ValueError:
            return Level.INFO
    return Level.INFO


@dataclass(frozen=True)
class SendResult:
    """Result of a send attempt. `success=False` with `skipped_reason` means
    the backend chose not to send (rate-limit / below min_level / disabled);
    `error` means the transport failed."""
    success: bool
    backend: str
    sent_at: datetime
    title: str
    level: Level
    error: Optional[str] = None
    skipped_reason: Optional[str] = None

    @property
    def skipped(self) -> bool:
        return self.skipped_reason is not None


class RateLimiter:
    """Sliding-window rate limiter. `max_per_window` events per `window_seconds`.
    Thread-safe; suitable for one-process notifier instance.
    """

    def __init__(self, max_per_window: int = 20, window_seconds: int = 60):
        self.max = max(0, int(max_per_window))
        self.window = timedelta(seconds=max(1, int(window_seconds)))
        self._events: deque[datetime] = deque()
        self._lock = Lock()

    def allow(self, now: Optional[datetime] = None) -> bool:
        if self.max <= 0:
            return True  # 0 / unlimited sentinel
        now = now or datetime.now(timezone.utc)
        cutoff = now - self.window
        with self._lock:
            while self._events and self._events[0] < cutoff:
                self._events.popleft()
            if len(self._events) >= self.max:
                return False
            self._events.append(now)
            return True


class Notifier(ABC):
    """Abstract notifier. Subclass and implement `_send`."""

    backend_name: str = "abstract"

    def __init__(
        self,
        *,
        min_level: Level = Level.INFO,
        rate_limiter: Optional[RateLimiter] = None,
    ):
        self.min_level = parse_level(min_level)
        self.rate_limiter = rate_limiter or RateLimiter(max_per_window=20)

    def send(self, title: str, body: str = "",
             level: Level = Level.INFO) -> SendResult:
        """Public send with gating. Returns SendResult (never raises)."""
        lvl = parse_level(level)
        now = datetime.now(timezone.utc)
        if lvl < self.min_level:
            return SendResult(False, self.backend_name, now, title, lvl,
                              skipped_reason="level")
        if not self.rate_limiter.allow(now):
            return SendResult(False, self.backend_name, now, title, lvl,
                              skipped_reason="rate_limited")
        try:
            err = self._send(title, body, lvl)
        except Exception as e:
            return SendResult(False, self.backend_name, now, title, lvl,
                              error=f"{type(e).__name__}: {e}")
        return SendResult(err is None, self.backend_name, now, title, lvl,
                          error=err)

    @abstractmethod
    def _send(self, title: str, body: str, level: Level) -> Optional[str]:
        """Perform actual send. Return None on success, error message on failure."""

    # Convenience wrappers
    def info(self, title: str, body: str = "") -> SendResult:
        return self.send(title, body, Level.INFO)

    def warning(self, title: str, body: str = "") -> SendResult:
        return self.send(title, body, Level.WARNING)

    def error(self, title: str, body: str = "") -> SendResult:
        return self.send(title, body, Level.ERROR)

    def critical(self, title: str, body: str = "") -> SendResult:
        return self.send(title, body, Level.CRITICAL)
