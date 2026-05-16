"""Structured Phase 2 attempts log — chart-structure P2B·R4 (P2-d7).

Per chart-structure ralph-loop execution PRD §6. Phase 2 explores
whether a *structured representation* of the price window adds
predictive information over the existing tabular factor zoo. Each
distinct representation tried is one ``Phase2Attempt``. The log is
machine-checkable (schema-validated, AC P2-A7) and — like the Phase 3
attempt records — forbids a blanket "structure doesn't work" verdict:
a negative result is scoped to the exact representation + config tried
and must carry a ``root_cause``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

_STATUS = Literal["built", "experimented"]
_VERDICT = Literal[
    "no_significant_increment",   # ran an experiment, no edge found
    "representation_shipped",     # build round — layer shipped, not yet tested
    "significant_increment",      # ran an experiment, edge found
]
_SCOPE = Literal["config_scoped", "global"]  # 'global' is intentionally hard


class Phase2Attempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_id: str
    phase: Literal["2A", "2B"]
    representation: str            # e.g. "swing_structure_family_t", "minirocket"
    status: _STATUS
    verdict: _VERDICT
    verdict_scope: _SCOPE
    artifact: str                  # path to the evidence artifact / module
    root_cause: Optional[str] = None
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _negative_needs_root_cause_and_scope(self) -> "Phase2Attempt":
        if self.verdict == "no_significant_increment":
            if not self.root_cause:
                raise ValueError(
                    f"{self.attempt_id}: a no_significant_increment verdict "
                    f"must carry a root_cause (no blanket conclusions).")
            if self.verdict_scope != "config_scoped":
                raise ValueError(
                    f"{self.attempt_id}: a negative verdict must be "
                    f"config_scoped, never global.")
        return self


class Phase2AttemptsLog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    updated_at: str
    attempts: list[Phase2Attempt] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> "Phase2AttemptsLog":
        ids = [a.attempt_id for a in self.attempts]
        if len(ids) != len(set(ids)):
            raise ValueError("attempt_id values must be unique")
        return self


def load_phase2_attempts(path: str | Path) -> Phase2AttemptsLog:
    """Load + schema-validate the Phase 2 attempts log."""
    return Phase2AttemptsLog.model_validate(json.loads(Path(path).read_text()))
