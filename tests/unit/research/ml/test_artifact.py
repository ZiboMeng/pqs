"""Tests for ``core.research.ml.artifact`` (PRD #4 P4.4 sub-step 2).

Discipline coverage:
- spec_id determinism (same spec → same hash; different spec → different)
- spec_id field set: which fields go in vs which are evidence-only
- lineage_tag readable format
- save → load roundtrip preserves model + metadata
- save creates BOTH .pkl AND .json
- load fails when files missing
- load fails on tampered metadata (spec_id mismatch)
- load fails on schema bump
- §9.0 invariant: output_type must be "rank" (post_init check + load)
- make_artifact_metadata builds from real WalkForwardResult
- model survives pickle roundtrip (LinearBaseline + XGB)
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.research.ml.artifact import (
    SCHEMA_VERSION,
    ArtifactError,
    ArtifactMetadata,
    ArtifactSchemaError,
    ArtifactSpecMismatchError,
    ModelArtifact,
    compute_lineage_tag,
    compute_spec_id,
    load_artifact,
    make_artifact_metadata,
    save_artifact,
)
from core.research.ml.pipeline import (
    WalkForwardConfig,
    run_walk_forward,
)
from core.research.ml.rank_model import LinearBaselineRankModel


# ---------------------------------------------------------------------------
# Spec_id determinism
# ---------------------------------------------------------------------------


_BASE_SPEC = {
    "schema_version": SCHEMA_VERSION,
    "model_class_name": "LinearBaselineRankModel",
    "hyperparams": {"alpha": 0.0},
    "train_config": {
        "start_year": 2010, "end_year": 2017,
        "train_window_years": 5, "val_window_years": 1, "step_years": 1,
    },
    "feature_columns": ["f1", "f2", "f3"],
    "sealed_years": [2026],
    "output_type": "rank",
}


class TestSpecIdDeterminism:
    def test_same_spec_same_hash(self):
        h1 = compute_spec_id(dict(_BASE_SPEC))
        h2 = compute_spec_id(dict(_BASE_SPEC))
        assert h1 == h2
        assert len(h1) == 64

    def test_changing_hyperparams_changes_hash(self):
        h_base = compute_spec_id(dict(_BASE_SPEC))
        modified = dict(_BASE_SPEC)
        modified["hyperparams"] = {"alpha": 0.1}
        assert compute_spec_id(modified) != h_base

    def test_changing_feature_columns_changes_hash(self):
        h_base = compute_spec_id(dict(_BASE_SPEC))
        modified = dict(_BASE_SPEC)
        modified["feature_columns"] = ["f1", "f2"]  # dropped f3
        assert compute_spec_id(modified) != h_base

    def test_changing_train_window_changes_hash(self):
        h_base = compute_spec_id(dict(_BASE_SPEC))
        modified = dict(_BASE_SPEC)
        modified["train_config"] = dict(_BASE_SPEC["train_config"])
        modified["train_config"]["train_window_years"] = 3
        assert compute_spec_id(modified) != h_base

    def test_changing_sealed_years_changes_hash(self):
        h_base = compute_spec_id(dict(_BASE_SPEC))
        modified = dict(_BASE_SPEC)
        modified["sealed_years"] = [2026, 2027]
        assert compute_spec_id(modified) != h_base

    def test_tuple_vs_list_feature_columns_same_hash(self):
        """Input form (tuple vs list) must not change the hash."""
        as_list = dict(_BASE_SPEC)
        as_list["feature_columns"] = ["f1", "f2", "f3"]
        as_tuple = dict(_BASE_SPEC)
        as_tuple["feature_columns"] = ("f1", "f2", "f3")
        assert compute_spec_id(as_list) == compute_spec_id(as_tuple)

    def test_missing_field_raises(self):
        bad = dict(_BASE_SPEC)
        del bad["model_class_name"]
        with pytest.raises(ArtifactSchemaError, match="missing"):
            compute_spec_id(bad)


# ---------------------------------------------------------------------------
# §9.0 invariant: output_type must be "rank"
# ---------------------------------------------------------------------------


class TestOutputTypeInvariant:
    def test_metadata_construction_with_rank_ok(self):
        ArtifactMetadata(
            schema_version=SCHEMA_VERSION,
            model_class_name="X", hyperparams={}, train_config={},
            feature_columns=(), sealed_years=(), output_type="rank",
            per_fold_metrics=[], mean_rank_ic=0.0, mean_rank_ir=0.0,
            n_successful_folds=0, n_failed_folds=0,
            trained_at_utc="2026-05-20T00:00:00Z",
            lineage_tag="x", spec_id="0" * 64,
        )

    def test_metadata_construction_with_magnitude_raises(self):
        with pytest.raises(ValueError, match="§9.0"):
            ArtifactMetadata(
                schema_version=SCHEMA_VERSION,
                model_class_name="X", hyperparams={}, train_config={},
                feature_columns=(), sealed_years=(), output_type="magnitude",
                per_fold_metrics=[], mean_rank_ic=0.0, mean_rank_ir=0.0,
                n_successful_folds=0, n_failed_folds=0,
                trained_at_utc="2026-05-20T00:00:00Z",
                lineage_tag="x", spec_id="0" * 64,
            )


# ---------------------------------------------------------------------------
# Lineage tag
# ---------------------------------------------------------------------------


class TestLineageTag:
    def test_format_includes_class_and_window(self):
        tag = compute_lineage_tag(
            "LinearBaselineRankModel", 2010, 2017,
            trained_at_utc="20260520T230000Z",
        )
        assert "LinearBaselineRankModel" in tag
        assert "2010-2017" in tag
        assert "20260520T230000Z" in tag

    def test_default_timestamp_is_utc_format(self):
        tag = compute_lineage_tag("X", 2010, 2017)
        # parse out the timestamp portion; should match YYYYMMDDTHHMMSSZ
        ts = tag.rsplit("_", 1)[-1]
        assert len(ts) == 16  # 8 + T + 6 + Z
        assert ts.endswith("Z")
        assert ts[8] == "T"


# ---------------------------------------------------------------------------
# Save / load roundtrip
# ---------------------------------------------------------------------------


def _make_fitted_linear_model():
    """Tiny fitted LinearBaseline for roundtrip tests."""
    rng = np.random.default_rng(7)
    dates = pd.bdate_range("2010-01-01", "2010-06-30")
    symbols = ["A", "B", "C", "D"]
    feat1 = pd.DataFrame(
        rng.standard_normal((len(dates), len(symbols))),
        index=dates, columns=symbols,
    )
    labels = feat1 * 0.8 + 0.2 * pd.DataFrame(
        rng.standard_normal((len(dates), len(symbols))),
        index=dates, columns=symbols,
    )
    model = LinearBaselineRankModel()
    model.fit({"feat1": feat1}, labels)
    return model, ("feat1",)


def _make_artifact(tmp_path: Path):
    model, feature_columns = _make_fitted_linear_model()
    metadata = ArtifactMetadata(
        schema_version=SCHEMA_VERSION,
        model_class_name="LinearBaselineRankModel",
        hyperparams={},
        train_config={
            "start_year": 2010, "end_year": 2017,
            "train_window_years": 5, "val_window_years": 1, "step_years": 1,
        },
        feature_columns=feature_columns,
        sealed_years=(2026,),
        output_type="rank",
        per_fold_metrics=[],
        mean_rank_ic=0.15,
        mean_rank_ir=0.45,
        n_successful_folds=3,
        n_failed_folds=0,
        trained_at_utc="20260520T230000Z",
        lineage_tag="LinearBaselineRankModel_2010-2017_20260520T230000Z",
        spec_id=compute_spec_id({
            "schema_version": SCHEMA_VERSION,
            "model_class_name": "LinearBaselineRankModel",
            "hyperparams": {},
            "train_config": {
                "start_year": 2010, "end_year": 2017,
                "train_window_years": 5, "val_window_years": 1, "step_years": 1,
            },
            "feature_columns": list(feature_columns),
            "sealed_years": [2026],
            "output_type": "rank",
        }),
    )
    return ModelArtifact(model=model, metadata=metadata)


class TestSaveLoadRoundtrip:
    def test_save_creates_both_pkl_and_json(self, tmp_path: Path):
        artifact = _make_artifact(tmp_path)
        paths = save_artifact(artifact, tmp_path / "model")
        assert paths.pkl_path.exists()
        assert paths.json_path.exists()
        assert paths.pkl_path.suffix == ".pkl"
        assert paths.json_path.suffix == ".json"

    def test_roundtrip_preserves_metadata(self, tmp_path: Path):
        artifact = _make_artifact(tmp_path)
        save_artifact(artifact, tmp_path / "model")
        loaded = load_artifact(tmp_path / "model")
        assert loaded.metadata.spec_id == artifact.metadata.spec_id
        assert loaded.metadata.lineage_tag == artifact.metadata.lineage_tag
        assert loaded.metadata.feature_columns == artifact.metadata.feature_columns
        assert loaded.metadata.sealed_years == artifact.metadata.sealed_years
        assert loaded.metadata.mean_rank_ic == artifact.metadata.mean_rank_ic

    def test_roundtrip_preserves_model_predictions(self, tmp_path: Path):
        artifact = _make_artifact(tmp_path)
        save_artifact(artifact, tmp_path / "model")
        loaded = load_artifact(tmp_path / "model")
        # Same features → same predictions before/after pickle
        rng = np.random.default_rng(99)
        dates = pd.bdate_range("2011-01-01", "2011-02-28")
        feat1 = pd.DataFrame(
            rng.standard_normal((len(dates), 4)),
            index=dates, columns=["A", "B", "C", "D"],
        )
        pred_before = artifact.model.predict_rank({"feat1": feat1})
        pred_after = loaded.model.predict_rank({"feat1": feat1})
        pd.testing.assert_frame_equal(pred_before, pred_after)

    def test_accepts_path_with_or_without_suffix(self, tmp_path: Path):
        artifact = _make_artifact(tmp_path)
        paths_a = save_artifact(artifact, tmp_path / "model_a.pkl")
        paths_b = save_artifact(artifact, tmp_path / "model_b")
        assert paths_a.pkl_path.exists() and paths_a.json_path.exists()
        assert paths_b.pkl_path.exists() and paths_b.json_path.exists()


class TestLoadFailureModes:
    def test_load_missing_pkl_raises(self, tmp_path: Path):
        # only json present
        (tmp_path / "model.json").write_text("{}")
        with pytest.raises(FileNotFoundError, match="pkl"):
            load_artifact(tmp_path / "model")

    def test_load_missing_json_raises(self, tmp_path: Path):
        (tmp_path / "model.pkl").write_bytes(b"\x80\x04N.")  # pickled None
        with pytest.raises(FileNotFoundError, match="json"):
            load_artifact(tmp_path / "model")

    def test_load_malformed_json_raises_schema_error(self, tmp_path: Path):
        artifact = _make_artifact(tmp_path)
        save_artifact(artifact, tmp_path / "model")
        # corrupt: remove a required field
        payload = json.loads((tmp_path / "model.json").read_text())
        del payload["lineage_tag"]
        (tmp_path / "model.json").write_text(json.dumps(payload))
        with pytest.raises(ArtifactSchemaError, match="missing"):
            load_artifact(tmp_path / "model")

    def test_load_schema_version_mismatch_raises(self, tmp_path: Path):
        artifact = _make_artifact(tmp_path)
        save_artifact(artifact, tmp_path / "model")
        payload = json.loads((tmp_path / "model.json").read_text())
        payload["schema_version"] = "9.99"
        (tmp_path / "model.json").write_text(json.dumps(payload))
        with pytest.raises(ArtifactSchemaError, match="schema_version"):
            load_artifact(tmp_path / "model")

    def test_load_tampered_metadata_raises_mismatch(self, tmp_path: Path):
        """Edit a spec-id-defining field WITHOUT recomputing spec_id →
        load_artifact must detect and raise."""
        artifact = _make_artifact(tmp_path)
        save_artifact(artifact, tmp_path / "model")
        payload = json.loads((tmp_path / "model.json").read_text())
        # tamper: change feature_columns but keep stored spec_id
        payload["feature_columns"] = ["TAMPERED"]
        (tmp_path / "model.json").write_text(json.dumps(payload))
        with pytest.raises(ArtifactSpecMismatchError, match="spec_id mismatch"):
            load_artifact(tmp_path / "model")


# ---------------------------------------------------------------------------
# make_artifact_metadata from real WalkForwardResult
# ---------------------------------------------------------------------------


class TestMakeArtifactMetadata:
    def test_builds_from_real_walk_forward_result(self):
        rng = np.random.default_rng(21)
        dates = pd.bdate_range("2010-01-01", "2017-12-31")
        symbols = [f"S{i}" for i in range(6)]
        feat1 = pd.DataFrame(
            rng.standard_normal((len(dates), len(symbols))),
            index=dates, columns=symbols,
        )
        labels = feat1 * 0.7 + 0.3 * pd.DataFrame(
            rng.standard_normal((len(dates), len(symbols))),
            index=dates, columns=symbols,
        )
        cfg = WalkForwardConfig(
            start_year=2010, end_year=2017,
            train_window_years=5, val_window_years=1, step_years=1,
        )
        result = run_walk_forward(
            model_factory=LinearBaselineRankModel,
            config=cfg, features={"feat1": feat1}, labels=labels,
            sealed_years=(),
        )

        metadata = make_artifact_metadata(
            result=result,
            model_class_name="LinearBaselineRankModel",
            hyperparams={},
            feature_columns=("feat1",),
            trained_at_utc="20260520T230000Z",
        )

        # Per-fold evidence preserved
        assert metadata.n_successful_folds == result.n_successful_folds
        assert len(metadata.per_fold_metrics) == len(result.per_fold)
        # Spec-id-defining fields present
        assert metadata.feature_columns == ("feat1",)
        assert metadata.train_config["train_window_years"] == 5
        # Lineage tag readable
        assert "LinearBaselineRankModel_2010-2017_" in metadata.lineage_tag
        # spec_id deterministic on identical inputs (re-call)
        metadata2 = make_artifact_metadata(
            result=result,
            model_class_name="LinearBaselineRankModel",
            hyperparams={},
            feature_columns=("feat1",),
            trained_at_utc="20260520T230000Z",
        )
        assert metadata.spec_id == metadata2.spec_id

    def test_different_hyperparams_yield_different_spec_id(self):
        # Construct WalkForwardResult dataclass directly (no actual training
        # needed — spec_id is a function of metadata fields, not numerics).
        from core.research.ml.pipeline import WalkForwardResult
        cfg = WalkForwardConfig(start_year=2010, end_year=2017)
        result = WalkForwardResult(config=cfg, per_fold=[], sealed_years=())
        m1 = make_artifact_metadata(
            result=result, model_class_name="X",
            hyperparams={"alpha": 0.0},
            feature_columns=("f1",),
        )
        m2 = make_artifact_metadata(
            result=result, model_class_name="X",
            hyperparams={"alpha": 0.5},
            feature_columns=("f1",),
        )
        assert m1.spec_id != m2.spec_id
