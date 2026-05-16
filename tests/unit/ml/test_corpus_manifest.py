"""Unit tests for the pretrain-corpus manifest — chart-structure P2B·R3.

Gate P2-A5: schema validation + train_years_only=true +
test_corpus_no_sealed_window.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from core.ml.corpus_manifest import (
    PretrainCorpusManifest,
    load_pretrain_corpus_manifest,
)
from core.research.temporal_split import (
    load_temporal_split,
    sealed_year_set,
    train_year_set,
    validation_year_set,
)

_PROJ = Path(__file__).resolve().parents[3]
_MANIFEST = _PROJ / "data" / "manifests" / "chart_structure_pretrain_corpus_v1.json"


def _load() -> PretrainCorpusManifest:
    return load_pretrain_corpus_manifest(_MANIFEST)


def test_manifest_exists_and_schema_valid():
    m = _load()
    assert m.corpus_id == "chart_structure_pretrain_corpus_v1"
    assert m.window_len == 63
    assert m.timeframe == "daily"
    assert m.n_windows > 0 and m.universe_size > 0


def test_train_years_only_true():
    assert _load().train_years_only is True


def test_corpus_no_sealed_window():
    """P2-A5: the sealed 2026 window must not be in the corpus."""
    m = _load()
    cfg = load_temporal_split()
    sealed = sealed_year_set(cfg)
    assert sealed and not (set(m.eligible_years) & sealed)
    assert set(m.excluded_years.sealed) == sealed
    assert int(m.date_range.end[:4]) < min(sealed)


def test_corpus_no_validation_years():
    m = _load()
    val = validation_year_set(load_temporal_split())
    assert val and not (set(m.eligible_years) & val)
    assert set(m.excluded_years.validation) == val


def test_eligible_years_match_temporal_split_train_set():
    m = _load()
    assert set(m.eligible_years) == train_year_set(load_temporal_split())


def test_multi_timeframe_schema_reserved():
    """v1 is daily-only but reserves the multi-TF field (no future bump)."""
    assert _load().timeframes_reserved  # non-empty reservation


def test_schema_rejects_train_years_only_false():
    m = _load().model_dump()
    m["train_years_only"] = False
    with pytest.raises(ValidationError, match="train_years_only"):
        PretrainCorpusManifest.model_validate(m)


def test_schema_rejects_eligible_excluded_overlap():
    m = _load().model_dump()
    m["eligible_years"] = sorted(set(m["eligible_years"]) | {2026})
    with pytest.raises(ValidationError, match="overlap"):
        PretrainCorpusManifest.model_validate(m)


def test_schema_forbids_extra_keys():
    m = _load().model_dump()
    m["sneaky_extra"] = 1
    with pytest.raises(ValidationError):
        PretrainCorpusManifest.model_validate(m)
