"""Phase 3 chart-native model attempt records — chart-structure P3.

Per chart-structure ralph-loop execution PRD §7. Each Phase 3 attempt
(a concrete model trained + evaluated) writes one
``data/audit/chart_structure/phase3_attempt_<id>.json``.

Discipline (execution PRD §2.2 + user decision D2): an experiment that
underperforms is NOT a failure of the round — but the attempt MUST
record (a) the exact config used (``config`` — "记录下使用了什么"),
(b) a ``root_cause`` for any negative verdict, and (c) a
``verdict_scope`` that is never ``global``. There is no blanket "CNN
doesn't work" verdict — only "this CNN, this config, underperformed,
because <root_cause>".

The eval block (AC P3-A3) must always declare ``eval_method``,
``cost_model`` and ``turnover_penalty`` so a high-IC / high-turnover
model cannot be reported as a win without its cost being visible.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

_MODEL = Literal["3B", "3A", "3C"]
_VERDICT = Literal[
    "beats_tabular_baseline",
    "no_significant_increment",
    "underperforms_tabular_baseline",
]
_SCOPE = Literal["config_scoped"]  # 'global' is intentionally not allowed


class Phase3Eval(BaseModel):
    """Cost-aware evaluation block — required fields keep the eval honest."""
    model_config = ConfigDict(extra="allow")  # extra metrics permitted

    eval_method: str          # how IC / returns were computed
    cost_model: str           # the cost assumption (e.g. "30bp_per_side")
    turnover_penalty: str     # how turnover was charged / accounted
    oos_rank_ic: float        # primary signal-quality metric
    vs_tabular_baseline: float  # oos_rank_ic(model) − oos_rank_ic(baseline)


class Phase3Attempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    attempt_id: str
    model: _MODEL
    created_at: str
    representation: str
    status: Literal["experimented"]
    verdict: _VERDICT
    verdict_scope: _SCOPE
    config: dict              # exact knobs used — D2 "记录下使用了什么"
    eval: Phase3Eval
    root_cause: Optional[str] = None
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _negative_needs_root_cause(self) -> "Phase3Attempt":
        negative = self.verdict in (
            "no_significant_increment", "underperforms_tabular_baseline")
        if negative and not (self.root_cause and len(self.root_cause) > 20):
            raise ValueError(
                f"{self.attempt_id}: a negative verdict ({self.verdict}) "
                f"must carry a substantive root_cause — no blanket verdicts.")
        if not self.config:
            raise ValueError(
                f"{self.attempt_id}: config must record what was used.")
        return self


def load_phase3_attempt(path: str | Path) -> Phase3Attempt:
    """Load + schema-validate a Phase 3 attempt JSON."""
    return Phase3Attempt.model_validate(json.loads(Path(path).read_text()))
