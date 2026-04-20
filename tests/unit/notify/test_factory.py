"""Tests for get_notifier() factory + config loading."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest
import yaml

from core.notify import (
    NullNotifier,
    ServerChanNotifier,
    StdoutNotifier,
    WecomBotNotifier,
    get_notifier,
    load_notify_config,
)


_WECOM = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc"


class TestGetNotifier:
    def test_disabled_returns_null(self):
        assert isinstance(get_notifier({"enabled": False}), NullNotifier)

    def test_missing_config_returns_null(self):
        assert isinstance(get_notifier({}), NullNotifier)

    def test_stdout_backend(self):
        n = get_notifier({"enabled": True, "backend": "stdout"})
        assert isinstance(n, StdoutNotifier)

    def test_null_backend_explicit(self):
        assert isinstance(
            get_notifier({"enabled": True, "backend": "null"}), NullNotifier
        )

    def test_unknown_backend_falls_back_to_null(self):
        assert isinstance(
            get_notifier({"enabled": True, "backend": "zoom"}), NullNotifier
        )

    def test_wecom_bot_with_url(self):
        n = get_notifier({
            "enabled": True, "backend": "wecom_bot",
            "wecom_bot": {"webhook_url": _WECOM},
        })
        assert isinstance(n, WecomBotNotifier)
        assert n.url == _WECOM

    def test_wecom_bot_without_url_falls_back(self):
        n = get_notifier({
            "enabled": True, "backend": "wecom_bot",
            "wecom_bot": {"webhook_url": ""},
        })
        assert isinstance(n, NullNotifier)

    def test_wecom_bot_bad_url_falls_back(self):
        n = get_notifier({
            "enabled": True, "backend": "wecom_bot",
            "wecom_bot": {"webhook_url": "https://wrong.example.com/hook"},
        })
        assert isinstance(n, NullNotifier)

    def test_server_chan_with_key(self):
        n = get_notifier({
            "enabled": True, "backend": "server_chan",
            "server_chan": {"send_key": "SCT_valid_key_12345"},
        })
        assert isinstance(n, ServerChanNotifier)

    def test_server_chan_without_key_falls_back(self):
        n = get_notifier({
            "enabled": True, "backend": "server_chan",
            "server_chan": {"send_key": ""},
        })
        assert isinstance(n, NullNotifier)

    def test_min_level_applied(self):
        from core.notify.base import Level
        n = get_notifier({
            "enabled": True, "backend": "stdout",
            "min_level": "warning",
        })
        assert n.min_level == Level.WARNING

    def test_rate_limit_applied(self):
        n = get_notifier({
            "enabled": True, "backend": "stdout",
            "rate_limit": {"max_per_window": 3, "window_seconds": 30},
        })
        assert n.rate_limiter.max == 3


class TestEnvExpansion:
    def test_env_var_expanded(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("TEST_WEBHOOK", _WECOM)
        cfg_path = tmp_path / "notify.yaml"
        cfg_path.write_text(yaml.safe_dump({
            "notify": {
                "enabled": True,
                "backend": "wecom_bot",
                "wecom_bot": {"webhook_url": "${TEST_WEBHOOK}"},
            }
        }))
        cfg = load_notify_config(cfg_path)
        assert cfg["wecom_bot"]["webhook_url"] == _WECOM

    def test_missing_env_expands_empty(self, tmp_path: Path, monkeypatch):
        monkeypatch.delenv("NOPE_NOPE_NOPE", raising=False)
        cfg_path = tmp_path / "notify.yaml"
        cfg_path.write_text(yaml.safe_dump({
            "notify": {
                "enabled": True, "backend": "wecom_bot",
                "wecom_bot": {"webhook_url": "${NOPE_NOPE_NOPE}"},
            }
        }))
        cfg = load_notify_config(cfg_path)
        assert cfg["wecom_bot"]["webhook_url"] == ""
        # And the resulting notifier falls back to Null:
        assert isinstance(get_notifier(cfg), NullNotifier)

    def test_missing_file_returns_disabled_default(self, tmp_path: Path):
        cfg = load_notify_config(tmp_path / "does-not-exist.yaml")
        assert cfg["enabled"] is False
        assert isinstance(get_notifier(cfg), NullNotifier)
