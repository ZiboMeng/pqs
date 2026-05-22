"""P5 — ML freeze bundle + drift detection TDD (PRD 20260521 §12 P5)."""
import json

import pytest

from core.research.ml.freeze_bundle import (
    FreezeBundleError,
    build_freeze_bundle,
    check_drift,
)


def _proj(tmp_path):
    """A minimal fake project root with the 4 config layers + a dummy
    model artifact (S7 M9 — build_freeze_bundle now requires one)."""
    (tmp_path / "config").mkdir()
    for name in ("ml_sources.yaml", "ml_labeling.yaml",
                 "ml_allocation.yaml", "temporal_split.yaml"):
        (tmp_path / "config" / name).write_text(f"# {name}\nkey: v\n")
    (tmp_path / "model.pkl").write_bytes(b"dummy-model-bytes")
    return tmp_path


def _build(proj, *args, model_artifact_path=None, **kw):
    """build_freeze_bundle with the dummy model path defaulted (S7 M9)."""
    if model_artifact_path is None:
        model_artifact_path = proj / "model.pkl"
    return build_freeze_bundle(proj, *args,
                               model_artifact_path=model_artifact_path, **kw)


def _acceptance(tmp_path, verdict="PASS", overfit=True,
                overfit_block=None):
    acc = {"verdict": verdict}
    if overfit:
        # a VALID §9.6 overfit_control (S5): n_trials>=2, finite DSR + PBO
        acc["overfit_control"] = overfit_block if overfit_block is not None \
            else {"n_trials": 10,
                  "dsr_promoted_D_xgb": {"deflated_sharpe": 0.81},
                  "pbo": {"pbo": 0.33}}
    p = tmp_path / "acceptance.json"
    p.write_text(json.dumps(acc))
    return p


class TestBuildFreezeBundle:
    def test_builds_with_pass_verdict(self, tmp_path):
        proj = _proj(tmp_path)
        b = _build(proj, _acceptance(tmp_path),
                                "cycle06", ["fa", "fb", "fc"])
        assert b["acceptance_verdict"] == "PASS"
        assert len(b["bundle_id"]) == 16
        for f in ("source_contract_hash", "label_config_hash",
                  "allocation_config_hash", "temporal_split_hash",
                  "feature_set_hash", "model_artifact_hash"):
            assert len(b[f]) == 64          # sha256 hexdigest (S7 M9)

    def test_fail_verdict_refused(self, tmp_path):
        proj = _proj(tmp_path)
        with pytest.raises(FreezeBundleError, match="not PASS"):
            _build(proj, _acceptance(tmp_path, verdict="FAIL"),
                                "cycle06", ["fa"])

    def test_missing_overfit_control_refused(self, tmp_path):
        proj = _proj(tmp_path)
        with pytest.raises(FreezeBundleError, match="overfit_control"):
            _build(proj, _acceptance(tmp_path, overfit=False),
                                "cycle06", ["fa"])

    def test_feature_set_hash_order_independent(self, tmp_path):
        proj = _proj(tmp_path)
        b1 = _build(proj, _acceptance(tmp_path),
                                 "cycle06", ["fa", "fb", "fc"])
        b2 = _build(proj, _acceptance(tmp_path),
                                 "cycle06", ["fc", "fa", "fb"])
        assert b1["feature_set_hash"] == b2["feature_set_hash"]


class TestCheckDrift:
    def test_no_drift_when_unchanged(self, tmp_path):
        proj = _proj(tmp_path)
        b = _build(proj, _acceptance(tmp_path),
                                "cycle06", ["fa", "fb"])
        assert check_drift(b, proj, factor_names=["fa", "fb"]) == []

    def test_config_drift_detected(self, tmp_path):
        proj = _proj(tmp_path)
        b = _build(proj, _acceptance(tmp_path),
                                "cycle06", ["fa"])
        (proj / "config" / "ml_allocation.yaml").write_text("key: CHANGED\n")
        flags = check_drift(b, proj)
        assert len(flags) == 1
        assert flags[0]["field"] == "allocation_config_hash"
        assert flags[0]["drift_class"] == "allocation drift"

    def test_feature_drift_detected(self, tmp_path):
        proj = _proj(tmp_path)
        b = _build(proj, _acceptance(tmp_path),
                                "cycle06", ["fa", "fb"])
        flags = check_drift(b, proj, factor_names=["fa", "fb", "fc_new"])
        assert len(flags) == 1
        assert flags[0]["drift_class"] == "factor drift"


# ── S5 (supplement PRD 2026-05-22) — freeze gate checks overfit VALIDITY
class TestOverfitControlValidity:
    """S5: build_freeze_bundle must reject an overfit_control block that
    is present but degenerate (not merely check the key exists)."""

    def test_valid_block_builds(self, tmp_path):
        proj = _proj(tmp_path)
        b = _build(proj, _acceptance(tmp_path),
                                "cycle06", ["fa", "fb"])
        assert b["acceptance_verdict"] == "PASS"

    def test_n_trials_below_2_refused(self, tmp_path):
        proj = _proj(tmp_path)
        acc = _acceptance(tmp_path, overfit_block={
            "n_trials": 1,
            "dsr_promoted_D_xgb": {"deflated_sharpe": 0.8},
            "pbo": {"pbo": 0.3}})
        with pytest.raises(FreezeBundleError, match="n_trials"):
            _build(proj, acc, "cycle06", ["fa"])

    def test_nan_dsr_refused(self, tmp_path):
        proj = _proj(tmp_path)
        acc = _acceptance(tmp_path, overfit_block={
            "n_trials": 10,
            "dsr_promoted_D_xgb": {"deflated_sharpe": float("nan")},
            "pbo": {"pbo": 0.3}})
        with pytest.raises(FreezeBundleError, match="DSR"):
            _build(proj, acc, "cycle06", ["fa"])

    def test_missing_dsr_block_refused(self, tmp_path):
        proj = _proj(tmp_path)
        acc = _acceptance(tmp_path, overfit_block={
            "n_trials": 10, "pbo": {"pbo": 0.3}})
        with pytest.raises(FreezeBundleError, match="dsr"):
            _build(proj, acc, "cycle06", ["fa"])

    def test_nan_pbo_refused(self, tmp_path):
        proj = _proj(tmp_path)
        acc = _acceptance(tmp_path, overfit_block={
            "n_trials": 10,
            "dsr_promoted_D_xgb": {"deflated_sharpe": 0.8},
            "pbo": {"pbo": float("nan")}})
        with pytest.raises(FreezeBundleError, match="PBO"):
            _build(proj, acc, "cycle06", ["fa"])


# ── S7 (supplement PRD 2026-05-22) — freeze must hash the model (M9) ──
class TestModelArtifactRequired:
    """S7 M9: a freeze bundle that does not hash the trained model is not
    reproducible — build_freeze_bundle now requires the model path."""

    def test_missing_model_path_refused(self, tmp_path):
        proj = _proj(tmp_path)
        with pytest.raises(FreezeBundleError, match="model_artifact_path"):
            build_freeze_bundle(proj, _acceptance(tmp_path),
                                "cycle06", ["fa"])  # no model_artifact_path

    def test_nonexistent_model_refused(self, tmp_path):
        proj = _proj(tmp_path)
        with pytest.raises(FreezeBundleError, match="not found"):
            build_freeze_bundle(proj, _acceptance(tmp_path),
                                "cycle06", ["fa"],
                                model_artifact_path=proj / "missing.pkl")

    def test_model_hash_in_bundle(self, tmp_path):
        proj = _proj(tmp_path)
        b = _build(proj, _acceptance(tmp_path), "cycle06", ["fa"])
        assert len(b["model_artifact_hash"]) == 64

    def test_model_drift_detected(self, tmp_path):
        """check_drift catches a changed model artifact (M9 — model
        drift was previously undetectable because the hash was None)."""
        proj = _proj(tmp_path)
        b = _build(proj, _acceptance(tmp_path), "cycle06", ["fa"])
        (proj / "model.pkl").write_bytes(b"RETRAINED-different-bytes")
        flags = check_drift(b, proj, factor_names=["fa"],
                            model_artifact_path=proj / "model.pkl")
        assert any(f["field"] == "model_artifact_hash" for f in flags)
