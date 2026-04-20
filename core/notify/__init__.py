"""Notification module: send alerts to WeChat / WeChat Work / stdout / null.

Typical usage:

    from core.notify import get_notifier

    notifier = get_notifier()  # config from config/notify.yaml
    notifier.info("Daily summary", f"NAV={nav:,.0f}, PnL={pnl:+,.0f}")
    notifier.error("Kill switch stage 2", f"drawdown={dd:.2%}")

Every send returns a `SendResult` and never raises on transport failure.
"""
from core.notify.base import (
    Level,
    Notifier,
    RateLimiter,
    SendResult,
    parse_level,
)
from core.notify.backends import (
    NullNotifier,
    ServerChanNotifier,
    StdoutNotifier,
    WecomBotNotifier,
)
from core.notify.factory import get_notifier, load_notify_config

__all__ = [
    "Level",
    "Notifier",
    "NullNotifier",
    "RateLimiter",
    "SendResult",
    "ServerChanNotifier",
    "StdoutNotifier",
    "WecomBotNotifier",
    "get_notifier",
    "load_notify_config",
    "parse_level",
]
