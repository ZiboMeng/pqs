"""Pretrain-corpus manifest schema — chart-structure P2B·R3.

Per chart-structure ralph-loop execution PRD §6 round P2B·R3. The
self-supervised window encoder (P2B·R2 ``TS2VecEncoder``) is pretrained
on a corpus of price windows; this manifest pins WHICH windows are
eligible so the pretraining cannot see holdout data.

Discipline (feedback_temporal_split_discipline + AC P2-A5): the corpus
is ``train_years_only`` — validation years and the sealed 2026 window
are excluded. A representation encoder that had seen the distribution
of validation/sealed windows would leak into any model later evaluated
there, even though pretraining itself uses no labels.

v1 is a daily-only freeze (execution PRD §3 q7); ``timeframes_reserved``
keeps the schema forward-compatible with a later multi-timeframe corpus
without a schema bump.
"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExcludedYears(BaseModel):
    """Years deliberately kept OUT of the pretraining corpus."""
    model_config = ConfigDict(extra="forbid")
    validation: list[int] = Field(default_factory=list)
    sealed: list[int] = Field(default_factory=list)
    reference: list[int] = Field(default_factory=list)


class DateRange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: str  # YYYY-MM-DD
    end: str    # YYYY-MM-DD


class PretrainCorpusManifest(BaseModel):
    """Frozen description of the self-supervised pretraining corpus."""
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    corpus_id: str
    created_at: str
    # which temporal split this corpus respects (holdout discipline source)
    split_name: str
    # MUST be True for v1 — the loader hard-fails otherwise
    train_years_only: bool
    timeframe: str = Field(pattern="^daily$")  # daily-only freeze (v1)
    timeframes_reserved: list[str]             # multi-TF schema reservation
    window_len: int = Field(gt=0)
    universe_name: str
    universe_size: int = Field(gt=0)
    eligible_years: list[int] = Field(min_length=1)
    excluded_years: ExcludedYears
    date_range: DateRange
    n_symbols_with_data: int = Field(ge=0)
    n_windows: int = Field(ge=0)
    source: str

    @model_validator(mode="after")
    def _holdout_discipline(self) -> "PretrainCorpusManifest":
        if not self.train_years_only:
            raise ValueError(
                "train_years_only must be True — a pretraining corpus that "
                "spans validation/sealed windows leaks holdout structure.")
        excl = (set(self.excluded_years.validation)
                | set(self.excluded_years.sealed)
                | set(self.excluded_years.reference))
        overlap = set(self.eligible_years) & excl
        if overlap:
            raise ValueError(
                f"eligible_years overlap excluded years: {sorted(overlap)}")
        # date_range must sit inside the eligible year span
        sy, ey = self.date_range.start[:4], self.date_range.end[:4]
        if int(sy) < min(self.eligible_years) or int(ey) > max(self.eligible_years):
            raise ValueError(
                f"date_range {sy}..{ey} steps outside eligible years "
                f"{min(self.eligible_years)}..{max(self.eligible_years)}")
        return self


def load_pretrain_corpus_manifest(path: str | Path) -> PretrainCorpusManifest:
    """Load + schema-validate a pretrain-corpus manifest JSON."""
    doc = json.loads(Path(path).read_text())
    return PretrainCorpusManifest.model_validate(doc)
