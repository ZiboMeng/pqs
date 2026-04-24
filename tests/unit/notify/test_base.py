"""Tests for Notifier ABC, Level, RateLimiter, SendResult."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional


from core.notify.base import (
    Level,
    Notifier,
    RateLimiter,
    SendResult,
    parse_level,
)


# ─── Level parsing ────────────────────────────────────────────────────────────

class TestParseLevel:
    def test_level_passthrough(self):
        assert parse_level(Level.WARNING) == Level.WARNING

    def test_str_lowercase(self):
        assert parse_level("warning") == Level.WARNING
        assert parse_level("WARN") == Level.WARNING
        assert parse_level(" Error ") == Level.ERROR

    def test_str_aliases(self):
        assert parse_level("fatal") == Level.CRITICAL
        assert parse_level("warn") == Level.WARNING

    def test_unknown_str_defaults_info(self):
        assert parse_level("banana") == Level.INFO

    def test_int_valid(self):
        assert parse_level(30) == Level.WARNING

    def test_int_invalid_defaults_info(self):
        assert parse_level(999) == Level.INFO


# ─── RateLimiter ──────────────────────────────────────────────────────────────

class TestRateLimiter:
    def test_allows_up_to_max(self):
        rl = RateLimiter(max_per_window=3, window_seconds=60)
        assert rl.allow() and rl.allow() and rl.allow()
        assert not rl.allow()

    def test_window_expires(self):
        rl = RateLimiter(max_per_window=2, window_seconds=60)
        t0 = datetime.now(timezone.utc)
        assert rl.allow(t0)
        assert rl.allow(t0)
        assert not rl.allow(t0 + timedelta(seconds=1))
        # After window: allowed again
        assert rl.allow(t0 + timedelta(seconds=61))

    def test_zero_means_unlimited(self):
        rl = RateLimiter(max_per_window=0, window_seconds=60)
        for _ in range(1000):
            assert rl.allow()


# ─── Notifier abstract behaviour ──────────────────────────────────────────────

class _Recorder(Notifier):
    """Test double: records every _send call, returns error str or None."""
    backend_name = "recorder"

    def __init__(self, *, return_error: Optional[str] = None,
                 raises: bool = False, **kwargs):
        super().__init__(**kwargs)
        self._return_error = return_error
        self._raises = raises
        self.calls: List[tuple[str, str, Level]] = []

    def _send(self, title, body, level):
        self.calls.append((title, body, level))
        if self._raises:
            raise RuntimeError("boom")
        return self._return_error


class TestNotifierSend:
    def test_success(self):
        n = _Recorder()
        r = n.info("hello", "body")
        assert r.success and r.error is None and r.skipped_reason is None
        assert r.backend == "recorder"
        assert r.title == "hello"
        assert r.level == Level.INFO
        assert n.calls == [("hello", "body", Level.INFO)]

    def test_below_min_level_skipped(self):
        n = _Recorder(min_level=Level.WARNING)
        r = n.info("low")
        assert not r.success
        assert r.skipped_reason == "level"
        assert n.calls == []

    def test_rate_limit_skipped(self):
        n = _Recorder(rate_limiter=RateLimiter(max_per_window=1))
        r1 = n.warning("first")
        r2 = n.warning("second")
        assert r1.success
        assert not r2.success and r2.skipped_reason == "rate_limited"
        assert len(n.calls) == 1  # second call never reached _send

    def test_exception_caught_not_raised(self):
        n = _Recorder(raises=True)
        r = n.error("bang")
        assert not r.success
        assert r.error is not None and "RuntimeError" in r.error
        assert r.skipped_reason is None

    def test_backend_error_reported(self):
        n = _Recorder(return_error="http_500")
        r = n.info("x")
        assert not r.success
        assert r.error == "http_500"

    def test_convenience_methods(self):
        n = _Recorder()
        n.info("i"); n.warning("w"); n.error("e"); n.critical("c")
        levels = [c[2] for c in n.calls]
        assert levels == [Level.INFO, Level.WARNING, Level.ERROR, Level.CRITICAL]


# ─── SendResult ───────────────────────────────────────────────────────────────

class TestSendResult:
    def test_skipped_property(self):
        now = datetime.now(timezone.utc)
        r = SendResult(False, "x", now, "t", Level.INFO, skipped_reason="level")
        assert r.skipped is True

    def test_success_not_skipped(self):
        now = datetime.now(timezone.utc)
        r = SendResult(True, "x", now, "t", Level.INFO)
        assert r.skipped is False
