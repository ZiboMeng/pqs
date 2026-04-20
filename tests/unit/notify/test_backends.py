"""Tests for concrete notifier backends (mocked HTTP)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from core.notify.backends import (
    NullNotifier,
    ServerChanNotifier,
    StdoutNotifier,
    WecomBotNotifier,
)
from core.notify.base import Level


_WECOM_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc-123"


# ─── Null ─────────────────────────────────────────────────────────────────────

class TestNullNotifier:
    def test_always_skipped(self):
        n = NullNotifier()
        r = n.critical("urgent", "body")
        assert not r.success
        assert r.skipped_reason == "disabled"


# ─── Stdout ───────────────────────────────────────────────────────────────────

class TestStdoutNotifier:
    def test_prints_and_succeeds(self, capsys):
        n = StdoutNotifier()
        r = n.info("hello", "world")
        assert r.success
        captured = capsys.readouterr()
        assert "hello" in captured.out and "world" in captured.out
        assert "INFO" in captured.out


# ─── WecomBot ─────────────────────────────────────────────────────────────────

class TestWecomBotNotifier:
    def _ok_response(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"errcode": 0, "errmsg": "ok"}
        return resp

    def _err_response(self, code=93000, msg="invalid webhook key"):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"errcode": code, "errmsg": msg}
        return resp

    def test_url_validation(self):
        with pytest.raises(ValueError):
            WecomBotNotifier("https://example.com/webhook")
        with pytest.raises(ValueError):
            WecomBotNotifier("")

    def test_url_accepted(self):
        n = WecomBotNotifier(_WECOM_URL)
        assert n.url == _WECOM_URL

    def test_successful_send(self):
        n = WecomBotNotifier(_WECOM_URL)
        with patch("requests.post", return_value=self._ok_response()) as mp:
            r = n.warning("title", "body")
        assert r.success and r.error is None
        # Verify payload
        args, kwargs = mp.call_args
        assert args[0] == _WECOM_URL
        payload = kwargs["json"]
        assert payload["msgtype"] == "markdown"
        content = payload["markdown"]["content"]
        assert "title" in content and "body" in content
        assert "warning" in content  # color tag for WARNING level

    def test_errcode_nonzero(self):
        n = WecomBotNotifier(_WECOM_URL)
        with patch("requests.post", return_value=self._err_response(93000)):
            r = n.error("x", "y")
        assert not r.success
        assert r.error is not None and "93000" in r.error

    def test_http_500(self):
        resp = MagicMock()
        resp.status_code = 500
        resp.text = "Internal Server Error"
        n = WecomBotNotifier(_WECOM_URL)
        with patch("requests.post", return_value=resp):
            r = n.info("x")
        assert not r.success
        assert "http_500" in r.error

    def test_timeout_caught(self):
        n = WecomBotNotifier(_WECOM_URL)
        with patch("requests.post", side_effect=requests.Timeout("slow")):
            r = n.info("x")
        assert not r.success
        assert "http_error" in r.error

    def test_truncation_over_size_budget(self):
        n = WecomBotNotifier(_WECOM_URL)
        big_body = "漢" * 2000  # ~6000 UTF-8 bytes
        md = n._build_markdown("title", big_body, Level.INFO)
        assert len(md.encode("utf-8")) <= 4000
        assert "truncated" in md

    def test_level_icon_in_markdown(self):
        n = WecomBotNotifier(_WECOM_URL)
        md_info = n._build_markdown("t", "", Level.INFO)
        md_err = n._build_markdown("t", "", Level.ERROR)
        assert "ℹ" in md_info
        assert "❗" in md_err


# ─── Server 酱 ────────────────────────────────────────────────────────────────

class TestServerChanNotifier:
    def _ok(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"code": 0, "message": "", "data": {}}
        return resp

    def _err(self, code=40001, msg="invalid sendkey"):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"code": code, "message": msg}
        return resp

    def test_key_validation(self):
        with pytest.raises(ValueError):
            ServerChanNotifier("")
        with pytest.raises(ValueError):
            ServerChanNotifier("not-a-sct-key")

    def test_key_accepted_sct(self):
        n = ServerChanNotifier("SCT1234abcd")
        assert "SCT1234abcd" in n.url

    def test_successful_send(self):
        n = ServerChanNotifier("SCT1234abcd", min_level=Level.INFO)
        with patch("requests.post", return_value=self._ok()) as mp:
            r = n.warning("title", "body")
        assert r.success
        args, kwargs = mp.call_args
        data = kwargs["data"]
        assert "WARNING" in data["title"]
        assert data["desp"] == "body"

    def test_errcode_nonzero(self):
        n = ServerChanNotifier("SCT1234abcd", min_level=Level.INFO)
        with patch("requests.post", return_value=self._err(40001)):
            r = n.error("x", "y")
        assert not r.success and "40001" in r.error

    def test_default_min_level_warning(self):
        """Server 酱 free tier is rate-limited; default min_level filters
        INFO chatter."""
        n = ServerChanNotifier("SCT1234abcd")
        with patch("requests.post", return_value=self._ok()) as mp:
            r = n.info("ignore me")
        assert not r.success and r.skipped_reason == "level"
        mp.assert_not_called()
