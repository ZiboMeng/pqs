"""P5 — ML freeze bundle + drift detection (PRD 20260521 §12 P5).

Implements the mechanism defined in
`docs/memos/20260521-ml-promotion-governance.md`: a validated ML
candidate is frozen as ONE reproducible config bundle (the SHA-256 of
each layer the candidate depends on); a forward run re-hashes the same
layers and any mismatch is a drift flag.

Freezing rule (governance memo §2): a bundle may be built ONLY when the
P4 acceptance verdict is PASS *and* §9.6 overfit control (DSR + PBO) is
recorded in the acceptance artifact.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

__all__ = ["build_freeze_bundle", "check_drift", "FreezeBundleError"]

# config layers hashed into every bundle (governance memo §2)
_CONFIG_LAYERS = {
    "source_contract_hash": "config/ml_sources.yaml",
    "label_config_hash": "config/ml_labeling.yaml",
    "allocation_config_hash": "config/ml_allocation.yaml",
    "temporal_split_hash": "config/temporal_split.yaml",
}

# which frozen field maps to which drift class (governance memo §3)
_DRIFT_CLASS = {
    "source_contract_hash": "data-contract drift",
    "label_config_hash": "label drift",
    "allocation_config_hash": "allocation drift",
    "temporal_split_hash": "split drift",
    "feature_set_hash": "factor drift",
    "model_artifact_hash": "model drift",
}


class FreezeBundleError(RuntimeError):
    """Raised when the freezing rule is violated."""


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _feature_set_hash(factor_names) -> str:
    """Stable hash of the feature set — order-independent."""
    joined = "|".join(sorted(factor_names))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _overfit_control_valid(oc) -> tuple[bool, str]:
    """S5 — an overfit_control block is VALID (not merely present) when
    it has n_trials >= 2, a finite DSR, and a finite PBO. A degenerate
    block (single trial, NaN DSR/PBO) must NOT pass the freeze gate.
    Returns (ok, reason)."""
    if not isinstance(oc, dict):
        return False, "overfit_control is not a dict"
    if int(oc.get("n_trials", 0)) < 2:
        return False, f"n_trials={oc.get('n_trials')} < 2"
    dsr_keys = [k for k in oc if k.startswith("dsr_promoted")]
    if not dsr_keys:
        return False, "no dsr_promoted* block"
    dsr = (oc[dsr_keys[0]] or {}).get("deflated_sharpe")
    try:
        if dsr is None or not math.isfinite(float(dsr)):
            return False, "DSR deflated_sharpe not finite"
    except (TypeError, ValueError):
        return False, "DSR deflated_sharpe not numeric"
    pbo = (oc.get("pbo") or {}).get("pbo")
    try:
        if pbo is None or not math.isfinite(float(pbo)):
            return False, "PBO not finite"
    except (TypeError, ValueError):
        return False, "PBO not numeric"
    return True, "ok"


def build_freeze_bundle(
    proj_root: Path,
    acceptance_json: Path,
    feature_set_name: str,
    factor_names,
    model_artifact_path: Path | None = None,
    lineage: str = "rerisk-and-ml-training-audit-2026-05-21",
) -> dict:
    """Freeze a validated ML candidate into one reproducible bundle.

    Raises FreezeBundleError if the acceptance artifact's verdict is not
    PASS or its §9.6 overfit control is missing (governance memo §2).
    """
    acc = json.loads(Path(acceptance_json).read_text())
    if acc.get("verdict") != "PASS":
        raise FreezeBundleError(
            f"cannot freeze: acceptance verdict is {acc.get('verdict')!r}, "
            "not PASS (governance memo §2)")
    if "overfit_control" not in acc:
        raise FreezeBundleError(
            "cannot freeze: acceptance artifact has no §9.6 overfit_control "
            "(DSR + PBO) record (governance memo §2)")
    # S5: the freeze gate checks the overfit_control is VALID, not merely
    # present — a degenerate (n_trials<2, NaN DSR/PBO) block must not pass.
    _ok, _why = _overfit_control_valid(acc["overfit_control"])
    if not _ok:
        raise FreezeBundleError(
            f"cannot freeze: §9.6 overfit_control is present but invalid "
            f"— {_why} (supplement S5).")

    bundle = {
        "lineage": lineage,
        "frozen_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "feature_set": {"name": feature_set_name,
                        "factor_names": sorted(factor_names)},
        "feature_set_hash": _feature_set_hash(factor_names),
        "acceptance_ref": str(Path(acceptance_json).relative_to(proj_root))
        if Path(acceptance_json).is_absolute() else str(acceptance_json),
        "acceptance_verdict": acc["verdict"],
    }
    for field, rel in _CONFIG_LAYERS.items():
        bundle[field] = _sha256_file(proj_root / rel)
    bundle["model_artifact_hash"] = (
        _sha256_file(Path(model_artifact_path))
        if model_artifact_path is not None else None)
    bundle["bundle_id"] = hashlib.sha256(
        json.dumps({k: bundle[k] for k in sorted(bundle)
                    if k.endswith("_hash")}, sort_keys=True).encode()
    ).hexdigest()[:16]
    return bundle


def check_drift(
    bundle: dict,
    proj_root: Path,
    factor_names=None,
    model_artifact_path: Path | None = None,
) -> list[dict]:
    """Re-hash the frozen layers and return a drift flag per mismatch.

    Drift is diagnostic — the caller (a human) adjudicates; this never
    auto-kills (governance memo §3, PBO-red-flag precedent).
    """
    flags: list[dict] = []
    for field, rel in _CONFIG_LAYERS.items():
        current = _sha256_file(proj_root / rel)
        if current != bundle.get(field):
            flags.append({"field": field, "drift_class": _DRIFT_CLASS[field],
                          "frozen": bundle.get(field), "current": current})
    if factor_names is not None:
        current = _feature_set_hash(factor_names)
        if current != bundle.get("feature_set_hash"):
            flags.append({"field": "feature_set_hash",
                          "drift_class": _DRIFT_CLASS["feature_set_hash"],
                          "frozen": bundle.get("feature_set_hash"),
                          "current": current})
    if model_artifact_path is not None and bundle.get("model_artifact_hash"):
        current = _sha256_file(Path(model_artifact_path))
        if current != bundle["model_artifact_hash"]:
            flags.append({"field": "model_artifact_hash",
                          "drift_class": _DRIFT_CLASS["model_artifact_hash"],
                          "frozen": bundle["model_artifact_hash"],
                          "current": current})
    return flags
