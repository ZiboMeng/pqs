"""Explicit runtime-mode authorization.

Research, paper simulation, and real-capital execution must never be inferred
from a legacy command name. In particular, ``run_paper --mode live`` means a
current-session *paper simulation* and is therefore authorized as PAPER.
Any future broker-connected entrypoint must request LIVE here and satisfy both
independent gates.
"""

from __future__ import annotations

import os
from enum import StrEnum
from typing import Mapping


class RuntimeMode(StrEnum):
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    LIVE = "LIVE"


class LiveAuthorizationError(RuntimeError):
    """Raised when a real-capital runtime is not explicitly authorized."""


LIVE_APPROVAL_PHRASE = "I_UNDERSTAND_LIVE_TRADING"


def authorize_runtime(
    requested_mode: RuntimeMode | str,
    *,
    live_enabled: bool = False,
    live_approval_env: str = "PQS_LIVE_APPROVAL_TOKEN",
    environ: Mapping[str, str] | None = None,
) -> RuntimeMode:
    """Validate and return an explicit runtime mode.

    BACKTEST and PAPER are safe by default. LIVE requires both a reviewed
    configuration opt-in and a separate process-level approval phrase.
    """
    try:
        mode = RuntimeMode(str(requested_mode).upper())
    except ValueError as exc:
        raise LiveAuthorizationError(
            f"Unknown runtime mode {requested_mode!r}; expected BACKTEST, PAPER, or LIVE"
        ) from exc

    if mode is not RuntimeMode.LIVE:
        return mode
    if not live_enabled:
        raise LiveAuthorizationError(
            "LIVE runtime is disabled by configuration (runtime.live_enabled=false)"
        )

    values = os.environ if environ is None else environ
    if values.get(live_approval_env) != LIVE_APPROVAL_PHRASE:
        raise LiveAuthorizationError(
            f"LIVE runtime requires {live_approval_env}={LIVE_APPROVAL_PHRASE}"
        )
    return mode
