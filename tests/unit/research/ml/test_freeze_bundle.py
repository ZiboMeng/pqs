"""P5 — ML freeze bundle + drift detection TDD (PRD 20260521 §12 P5)."""
import json

import pytest

from core.research.ml.freeze_bundle import (
    FreezeBundleError,
    build_freeze_bundle,
    check_drift,
)


def _proj(tmp_path):
    """A minimal fake project root with the 4 config layers."""
    (tmp_path / "config").mkdir()
    for name in ("ml_sources.yaml", "ml_labeling.yaml",
                 "ml_allocation.yaml", "temporal_split.yaml"):
        (tmp_path / "config" / name).write_text(f"# {name}\nkey: v\n")
    return tmp_path


def _acceptance(tmp_path, verdict="PASS", overfit=True):
    acc = {"verdict": verdict}
    if overfit:
        acc["overfit_control"] = {"n_trials": 5, "pbo": {"pbo": 0.07}}
    p = tmp_path / "acceptance.json"
    p.write_text(json.dumps(acc))
    return p


class TestBuildFreezeBundle:
    def test_builds_with_pass_verdict(self, tmp_path):
        proj = _proj(tmp_path)
        b = build_freeze_bundle(proj, _acceptance(tmp_path),
                                "cycle06", ["fa", "fb", "fc"])
        assert b["acceptance_verdict"] == "PASS"
        assert len(b["bundle_id"]) == 16
        for f in ("source_contract_hash", "label_config_hash",
                  "allocation_config_hash", "temporal_split_hash",
                  "feature_set_hash"):
            assert len(b[f]) == 64          # sha256 hexdigest
        assert b["model_artifact_hash"] is None

    def test_fail_verdict_refused(self, tmp_path):
        proj = _proj(tmp_path)
        with pytest.raises(FreezeBundleError, match="not PASS"):
            build_freeze_bundle(proj, _acceptance(tmp_path, verdict="FAIL"),
                                "cycle06", ["fa"])

    def test_missing_overfit_control_refused(self, tmp_path):
        proj = _proj(tmp_path)
        with pytest.raises(FreezeBundleError, match="overfit_control"):
            build_freeze_bundle(proj, _acceptance(tmp_path, overfit=False),
                                "cycle06", ["fa"])

    def test_feature_set_hash_order_independent(self, tmp_path):
        proj = _proj(tmp_path)
        b1 = build_freeze_bundle(proj, _acceptance(tmp_path),
                                 "cycle06", ["fa", "fb", "fc"])
        b2 = build_freeze_bundle(proj, _acceptance(tmp_path),
                                 "cycle06", ["fc", "fa", "fb"])
        assert b1["feature_set_hash"] == b2["feature_set_hash"]


class TestCheckDrift:
    def test_no_drift_when_unchanged(self, tmp_path):
        proj = _proj(tmp_path)
        b = build_freeze_bundle(proj, _acceptance(tmp_path),
                                "cycle06", ["fa", "fb"])
        assert check_drift(b, proj, factor_names=["fa", "fb"]) == []

    def test_config_drift_detected(self, tmp_path):
        proj = _proj(tmp_path)
        b = build_freeze_bundle(proj, _acceptance(tmp_path),
                                "cycle06", ["fa"])
        (proj / "config" / "ml_allocation.yaml").write_text("key: CHANGED\n")
        flags = check_drift(b, proj)
        assert len(flags) == 1
        assert flags[0]["field"] == "allocation_config_hash"
        assert flags[0]["drift_class"] == "allocation drift"

    def test_feature_drift_detected(self, tmp_path):
        proj = _proj(tmp_path)
        b = build_freeze_bundle(proj, _acceptance(tmp_path),
                                "cycle06", ["fa", "fb"])
        flags = check_drift(b, proj, factor_names=["fa", "fb", "fc_new"])
        assert len(flags) == 1
        assert flags[0]["drift_class"] == "factor drift"
