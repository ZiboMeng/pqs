"""
Concrete notifier backends.

  - NullNotifier: discard everything (when notify disabled)
  - StdoutNotifier: print to stdout (dev / tests)
  - WecomBotNotifier: POST to WeChat Work group-bot webhook
  - ServerChanNotifier: POST to Server 酱 Turbo

All HTTP backends swallow network exceptions and return them in SendResult.error;
they never raise. Timeouts are bounded so a trading loop won't block.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import requests

from core.notify.base import Level, Notifier, RateLimiter, SendResult


# ─── Null: discard ────────────────────────────────────────────────────────────

class NullNotifier(Notifier):
    backend_name = "null"

    def __init__(self):
        super().__init__(min_level=Level.CRITICAL + 1,
                         rate_limiter=RateLimiter(0))

    def send(self, title, body="", level=Level.INFO) -> SendResult:
        return SendResult(False, "null",
                          datetime.now(timezone.utc), title,
                          Level(level) if not isinstance(level, Level) else level,
                          skipped_reason="disabled")

    def _send(self, title, body, level):
        return None


# ─── Stdout: print locally ────────────────────────────────────────────────────

class StdoutNotifier(Notifier):
    backend_name = "stdout"

    def _send(self, title: str, body: str, level: Level) -> Optional[str]:
        print(f"[NOTIFY {level.name}] {title}\n{body}\n", flush=True)
        return None


# ─── WeChat Work group bot ────────────────────────────────────────────────────

_WECOM_COLOR_BY_LEVEL = {
    Level.DEBUG: "comment",     # gray
    Level.INFO: "info",         # green
    Level.WARNING: "warning",   # orange
    Level.ERROR: "warning",     # orange (no red; warning is the strongest)
    Level.CRITICAL: "warning",
}

_WECOM_ICON_BY_LEVEL = {
    Level.DEBUG: "·",
    Level.INFO: "ℹ",
    Level.WARNING: "⚠",
    Level.ERROR: "❗",
    Level.CRITICAL: "🚨",
}

# WeChat Work markdown payload limit: 4096 bytes.
_WECOM_MAX_BYTES = 4000  # leave slack for our wrapping


class WecomBotNotifier(Notifier):
    """WeChat Work group bot webhook. Markdown msgtype.

    https://developer.work.weixin.qq.com/document/path/91770
    """

    backend_name = "wecom_bot"

    def __init__(
        self,
        webhook_url: str,
        *,
        min_level: Level = Level.INFO,
        rate_limiter: Optional[RateLimiter] = None,
        timeout_seconds: float = 10.0,
    ):
        super().__init__(min_level=min_level, rate_limiter=rate_limiter)
        if not webhook_url or "qyapi.weixin.qq.com/cgi-bin/webhook/send" not in webhook_url:
            raise ValueError(
                "webhook_url must look like "
                "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...")
        self.url = webhook_url
        self.timeout = timeout_seconds

    def _build_markdown(self, title: str, body: str, level: Level) -> str:
        color = _WECOM_COLOR_BY_LEVEL.get(level, "info")
        icon = _WECOM_ICON_BY_LEVEL.get(level, "·")
        md = (
            f"### {icon} <font color=\"{color}\">{title}</font>\n\n"
            f"{body}" if body else f"### {icon} <font color=\"{color}\">{title}</font>"
        )
        # Enforce size budget (WeChat Work rejects >4096 bytes markdown).
        b = md.encode("utf-8")
        if len(b) > _WECOM_MAX_BYTES:
            md = b[: _WECOM_MAX_BYTES - 32].decode("utf-8", "ignore") + "…(truncated)"
        return md

    def _send(self, title: str, body: str, level: Level) -> Optional[str]:
        payload = {
            "msgtype": "markdown",
            "markdown": {"content": self._build_markdown(title, body, level)},
        }
        try:
            resp = requests.post(self.url, json=payload, timeout=self.timeout)
        except requests.RequestException as e:
            return f"http_error: {e}"
        if resp.status_code != 200:
            return f"http_{resp.status_code}: {resp.text[:200]}"
        try:
            data = resp.json()
        except ValueError:
            return f"non_json_response: {resp.text[:200]}"
        if data.get("errcode") != 0:
            return f"wecom_errcode_{data.get('errcode')}: {data.get('errmsg')}"
        return None


# ─── Server 酱 Turbo ──────────────────────────────────────────────────────────

class ServerChanNotifier(Notifier):
    """Server 酱 Turbo sendkey. https://sct.ftqq.com/

    Free tier: 5 messages/day. Keep for critical events only.
    """

    backend_name = "server_chan"
    _URL_FMT = "https://sctapi.ftqq.com/{key}.send"

    def __init__(
        self,
        send_key: str,
        *,
        min_level: Level = Level.WARNING,  # default: free-tier friendly
        rate_limiter: Optional[RateLimiter] = None,
        timeout_seconds: float = 10.0,
    ):
        if rate_limiter is None:
            # Free tier ≈ 5/day; cap at 5/hour to smear.
            rate_limiter = RateLimiter(max_per_window=5, window_seconds=3600)
        super().__init__(min_level=min_level, rate_limiter=rate_limiter)
        if not send_key or not send_key.startswith(("SCT", "SCU")):
            raise ValueError("send_key must start with SCT/SCU")
        self.url = self._URL_FMT.format(key=send_key)
        self.timeout = timeout_seconds

    def _send(self, title: str, body: str, level: Level) -> Optional[str]:
        # Server 酱 accepts title and desp (markdown) form-encoded.
        data = {"title": f"[{level.name}] {title}"[:128], "desp": body or ""}
        try:
            resp = requests.post(self.url, data=data, timeout=self.timeout)
        except requests.RequestException as e:
            return f"http_error: {e}"
        if resp.status_code != 200:
            return f"http_{resp.status_code}: {resp.text[:200]}"
        try:
            payload = resp.json()
        except ValueError:
            return f"non_json_response: {resp.text[:200]}"
        if payload.get("code") != 0:
            return f"sct_code_{payload.get('code')}: {payload.get('message')}"
        return None
