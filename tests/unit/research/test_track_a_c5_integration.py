"""Integration tests for codex R21 P0.1 — M6 C5 role-remint guard wired
into the actual mining path (not just direct unit test of the helper).

The unit test for `enforce_c5_no_role_remint` itself lives in
`test_temporal_split.py`; here we exercise the guard as the mining code
calls it: through ``ResearchMiner.run_trial`` with a real archive.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from core.mining.rcm_archive import RCMArchive, compute_spec_id
from core.mining.research_miner import (
    CompositeMetrics,
    FAMILIES_V1,
    ResearchCompositeSpec,
    ResearchMiner,
    TrialResult,
)


@pytest.fixture
def mining_inputs():
    np.random.seed(42)
    dates = pd.bdate_range("2018-01-01", "2018-06-30")
    syms = [f"SYM{i:03d}" for i in range(20)]

    factor_panels = {}
    for family in FAMILIES_V1:
        for feat in family.factors:
            factor_panels[feat] = pd.DataFrame(
                np.random.randn(len(dates), len(syms)), index=dates, columns=syms
            )
    fwd = pd.DataFrame(
        np.random.randn(len(dates), len(syms)), index=dates, columns=syms
    )
    mask = pd.DataFrame(True, index=dates, columns=syms)
    return factor_panels, fwd, mask


@pytest.fixture
def deterministic_spec():
    """A canonical spec with three real factor names from FAMILIES_V1.

    `family_counts` is bookkeeping only for the spec hash; the C5 guard
    only cares about the spec's hash matching a prior insertion.
    """
    return ResearchCompositeSpec(
        features=("amihud_20d", "beta_spy_60d", "breakout_20d_strength"),
        weights=(0.4, 0.3, 0.3),
        family_counts={"A": 1, "B": 1, "C": 1},
    )


def _seed_prior_core_trial(archive, spec):
    """Insert a prior trial under role=core, split=alt_year_v1."""
    archive.record_study(
        study_id="study_core",
        lineage_tag="audit-c5-integration",
        split_name="alt_year_v1",
        split_sha256="hash_v1",
        role="core",
    )
    metrics = CompositeMetrics(
        n_features=3, n_families=3, n_dates=100,
        ic_mean=0.05, ic_std=0.1, ic_ir=0.5,
        turnover_proxy=0.2, corr_concentration=0.3,
    )
    archive.insert_trial(
        TrialResult(spec=spec, metrics=metrics, objective=0.5),
        lineage_tag="audit-c5-integration",
        study_id="study_core",
        split_sha256="hash_v1",
        panel_max_date="2024-12-31",
        role="core",
    )


# ---------------------------------------------------------------------------
# C5 enforcement through ResearchMiner.run_trial
# ---------------------------------------------------------------------------


def test_run_trial_blocks_same_spec_different_role_same_split(
    tmp_path, mining_inputs, deterministic_spec
):
    """The core P0.1 path: spec X mined under role=core; a subsequent
    miner with role=diversifier on the SAME split must be blocked at
    run_trial — not after evaluation, not after archive write.
    """
    factor_panels, fwd, mask = mining_inputs
    spec = deterministic_spec
    archive = RCMArchive(tmp_path / "rcm.db")
    _seed_prior_core_trial(archive, spec)

    archive.record_study(
        study_id="study_div",
        lineage_tag="audit-c5-integration",
        split_name="alt_year_v1",
        split_sha256="hash_v1",
        role="diversifier",
    )
    miner = ResearchMiner(
        factor_panel_map=factor_panels, fwd_returns=fwd, mask=mask,
        families=FAMILIES_V1,
        archive=archive,
        lineage_tag="audit-c5-integration", study_id="study_div",
        split_name="alt_year_v1", split_sha256="hash_v1",
        role="diversifier",
    )
    fake_trial = MagicMock()
    with patch("core.mining.research_miner.suggest_composite_spec", return_value=spec):
        with pytest.raises(Exception) as exc_info:
            miner.run_trial(fake_trial)
    msg = str(exc_info.value)
    assert "C5" in msg or "role-remint" in msg or "remint" in msg.lower() \
        or type(exc_info.value).__name__ == "TrialPruned"

    # No trial under role=diversifier should have been inserted
    spec_id = compute_spec_id(spec)
    rows = archive.find_studies_by_spec_role(spec_id, "alt_year_v1")
    assert len(rows) == 1
    assert rows[0]["role"] == "core"


def test_run_trial_allows_same_spec_same_role_same_split(
    tmp_path, mining_inputs, deterministic_spec
):
    """Same spec, same role, same split = deterministic re-run; permitted
    (rcm_archive ON CONFLICT REPLACE handles dedup)."""
    factor_panels, fwd, mask = mining_inputs
    spec = deterministic_spec
    archive = RCMArchive(tmp_path / "rcm.db")
    _seed_prior_core_trial(archive, spec)

    miner = ResearchMiner(
        factor_panel_map=factor_panels, fwd_returns=fwd, mask=mask,
        families=FAMILIES_V1,
        archive=archive,
        lineage_tag="audit-c5-integration", study_id="study_core",
        split_name="alt_year_v1", split_sha256="hash_v1",
        role="core",
    )
    fake_trial = MagicMock()
    with patch("core.mining.research_miner.suggest_composite_spec", return_value=spec):
        # Should NOT raise C5; evaluate_composite may still raise on fake
        # data, but the C5 guard itself must let it through.
        try:
            miner.run_trial(fake_trial)
        except Exception as exc:
            msg = str(exc)
            assert "C5" not in msg and "role-remint" not in msg, (
                f"C5 incorrectly fired on same-role re-run: {msg}"
            )


def test_run_trial_allows_same_spec_different_split(
    tmp_path, mining_inputs, deterministic_spec
):
    """Different split_name = independent governance scope. Same spec
    under role=diversifier in split v2 must be allowed even if it was
    role=core in split v1."""
    factor_panels, fwd, mask = mining_inputs
    spec = deterministic_spec
    archive = RCMArchive(tmp_path / "rcm.db")
    _seed_prior_core_trial(archive, spec)

    archive.record_study(
        study_id="study_div_v2", lineage_tag="audit-c5-integration",
        split_name="alt_year_v2", split_sha256="hash_v2", role="diversifier",
    )
    miner = ResearchMiner(
        factor_panel_map=factor_panels, fwd_returns=fwd, mask=mask,
        families=FAMILIES_V1,
        archive=archive,
        lineage_tag="audit-c5-integration", study_id="study_div_v2",
        split_name="alt_year_v2",  # different split
        split_sha256="hash_v2",
        role="diversifier",
    )
    fake_trial = MagicMock()
    with patch("core.mining.research_miner.suggest_composite_spec", return_value=spec):
        try:
            miner.run_trial(fake_trial)
        except Exception as exc:
            msg = str(exc)
            assert "C5" not in msg and "role-remint" not in msg, (
                f"C5 incorrectly fired across split boundary: {msg}"
            )


def test_run_trial_skips_c5_when_temporal_split_inactive(
    tmp_path, mining_inputs, deterministic_spec
):
    """Legacy mining (no split_name / role) is a no-op for the C5 guard."""
    factor_panels, fwd, mask = mining_inputs
    spec = deterministic_spec
    archive = RCMArchive(tmp_path / "rcm.db")
    _seed_prior_core_trial(archive, spec)

    miner = ResearchMiner(
        factor_panel_map=factor_panels, fwd_returns=fwd, mask=mask,
        families=FAMILIES_V1,
        archive=archive,
        lineage_tag="legacy-flow", study_id="study_legacy",
        # split_name + role intentionally None → C5 must be skipped
    )
    archive.record_study(
        study_id="study_legacy", lineage_tag="legacy-flow",
        split_name=None, split_sha256=None, role=None,
    )
    fake_trial = MagicMock()
    with patch("core.mining.research_miner.suggest_composite_spec", return_value=spec):
        try:
            miner.run_trial(fake_trial)
        except Exception as exc:
            msg = str(exc)
            assert "C5" not in msg and "role-remint" not in msg, (
                f"C5 fired in legacy flow without temporal split: {msg}"
            )


# ---------------------------------------------------------------------------
# compute_spec_id stability + match with insert_trial
# ---------------------------------------------------------------------------


def test_compute_spec_id_matches_archive_trial_id(tmp_path, deterministic_spec):
    """The public ``compute_spec_id`` MUST equal the trial_id stored by
    ``insert_trial`` for the same spec — this is what the C5 guard
    relies on. Drift here = guard sees one id, archive stores another,
    same-spec violations slip through.
    """
    spec = deterministic_spec
    archive = RCMArchive(tmp_path / "rcm.db")
    archive.record_study(
        study_id="s", lineage_tag="t",
        split_name="alt_year_v1", split_sha256="h", role="core",
    )
    metrics = CompositeMetrics(n_features=3, n_families=3, n_dates=10,
                               ic_mean=0.0, ic_std=0.1, ic_ir=0.0,
                               turnover_proxy=0.0, corr_concentration=0.0)
    archive.insert_trial(
        TrialResult(spec=spec, metrics=metrics, objective=0.0),
        lineage_tag="t", study_id="s",
        split_sha256="h", panel_max_date="2024-12-31", role="core",
    )

    expected = compute_spec_id(spec)
    rows = archive.find_studies_by_spec_role(expected, "alt_year_v1")
    assert len(rows) == 1, (
        f"compute_spec_id={expected} did not match the archive's trial_id "
        f"for the same spec; the C5 guard would silently miss this case."
    )
