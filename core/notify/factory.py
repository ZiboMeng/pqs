"""
Notifier factory: resolve config dict → concrete Notifier.

Config schema (see config/notify.yaml):

  notify:
    enabled: true
    backend: wecom_bot          # wecom_bot | server_chan | stdout | null
    min_level: info             # debug | info | warning | error | critical
    rate_limit:
      max_per_window: 20
      window_seconds: 60
    wecom_bot:
      webhook_url: "${PQS_WECOM_WEBHOOK_URL}"
    server_chan:
      send_key: "${PQS_SCT_SEND_KEY}"

`${ENV_VAR}` strings are expanded at load time. Missing env vars for the selected
backend fall back to NullNotifier + a logged warning (so trading code can still
call notifier.send without crashing if the operator forgot to set the env).
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from core.notify.backends import (
    NullNotifier,
    ServerChanNotifier,
    StdoutNotifier,
    WecomBotNotifier,
)
from core.notify.base import Notifier, RateLimiter, parse_level

_logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "notify.yaml"
_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_env(value):
    """Recursively expand ${ENV} references in strings within dict/list/str values."""
    if isinstance(value, str):
        return _ENV_RE.sub(
            lambda m: os.environ.get(m.group(1), ""), value
        )
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def load_notify_config(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load config/notify.yaml and expand ${ENV} references.
    Returns the 'notify' sub-dict (or empty defaults if file missing)."""
    path = path or _DEFAULT_CONFIG_PATH
    if not path.exists():
        return {"enabled": False, "backend": "null"}
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    cfg = raw.get("notify", raw) if isinstance(raw, dict) else {}
    return _expand_env(cfg)


def _make_rate_limiter(cfg: Dict[str, Any]) -> RateLimiter:
    rl = cfg.get("rate_limit") or {}
    return RateLimiter(
        max_per_window=int(rl.get("max_per_window", 20)),
        window_seconds=int(rl.get("window_seconds", 60)),
    )


def get_notifier(cfg: Optional[Dict[str, Any]] = None) -> Notifier:
    """Build a Notifier from config dict. Falls back to NullNotifier if:
      - enabled is False / missing
      - selected backend's required credentials are missing
    """
    if cfg is None:
        cfg = load_notify_config()

    if not cfg.get("enabled", False):
        return NullNotifier()

    backend = (cfg.get("backend") or "stdout").strip().lower()
    min_level = parse_level(cfg.get("min_level", "info"))
    rate_limiter = _make_rate_limiter(cfg)

    try:
        if backend == "null":
            return NullNotifier()

        if backend == "stdout":
            return StdoutNotifier(min_level=min_level, rate_limiter=rate_limiter)

        if backend == "wecom_bot":
            bot_cfg = cfg.get("wecom_bot") or {}
            url = (bot_cfg.get("webhook_url") or "").strip()
            if not url:
                _logger.warning("notify: wecom_bot webhook_url missing; "
                                "falling back to NullNotifier")
                return NullNotifier()
            return WecomBotNotifier(url, min_level=min_level,
                                    rate_limiter=rate_limiter)

        if backend == "server_chan":
            sct_cfg = cfg.get("server_chan") or {}
            key = (sct_cfg.get("send_key") or "").strip()
            if not key:
                _logger.warning("notify: server_chan send_key missing; "
                                "falling back to NullNotifier")
                return NullNotifier()
            return ServerChanNotifier(key, min_level=min_level,
                                      rate_limiter=rate_limiter)

        _logger.warning("notify: unknown backend %r; falling back to NullNotifier",
                        backend)
        return NullNotifier()
    except Exception as e:
        _logger.warning("notify: backend %s init failed: %s; "
                        "falling back to NullNotifier", backend, e)
        return NullNotifier()
