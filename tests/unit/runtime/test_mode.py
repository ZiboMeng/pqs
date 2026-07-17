from __future__ import annotations

import pytest

from core.runtime.mode import (
    LIVE_APPROVAL_PHRASE,
    LiveAuthorizationError,
    RuntimeMode,
    authorize_runtime,
)


@pytest.mark.parametrize("mode", [RuntimeMode.BACKTEST, RuntimeMode.PAPER])
def test_non_live_modes_are_safe_by_default(mode):
    assert authorize_runtime(mode, environ={}) is mode


def test_live_is_refused_when_config_disabled_even_with_token():
    with pytest.raises(LiveAuthorizationError, match="disabled by configuration"):
        authorize_runtime(
            RuntimeMode.LIVE,
            live_enabled=False,
            environ={"PQS_LIVE_APPROVAL_TOKEN": LIVE_APPROVAL_PHRASE},
        )


def test_live_is_refused_without_independent_approval_token():
    with pytest.raises(LiveAuthorizationError, match="requires PQS_LIVE_APPROVAL_TOKEN"):
        authorize_runtime(RuntimeMode.LIVE, live_enabled=True, environ={})


def test_live_requires_both_independent_gates():
    assert authorize_runtime(
        "live",
        live_enabled=True,
        environ={"PQS_LIVE_APPROVAL_TOKEN": LIVE_APPROVAL_PHRASE},
    ) is RuntimeMode.LIVE


def test_unknown_mode_fails_closed():
    with pytest.raises(LiveAuthorizationError, match="Unknown runtime mode"):
        authorize_runtime("production", environ={})
