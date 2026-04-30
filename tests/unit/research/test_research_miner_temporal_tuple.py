"""Codex R25 P1 — ResearchMiner __init__ temporal tuple validation.

The CLI script enforces ``--temporal-split`` requires ``--role``, but
direct API construction with partial temporal fingerprints would
silently bypass the C5 role-remint guard. Reject at __init__.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.mining.research_miner import (
    FAMILIES_V1,
    ResearchMiner,
)


def _build_inputs():
    np.random.seed(0)
    dates = pd.bdate_range("2018-01-01", periods=20)
    syms = [f"S{i:02d}" for i in range(5)]
    factor_panels = {}
    for family in FAMILIES_V1:
        for feat in family.factors:
            factor_panels[feat] = pd.DataFrame(
                np.random.randn(len(dates), len(syms)), index=dates, columns=syms,
            )
    fwd = pd.DataFrame(np.random.randn(len(dates), len(syms)), index=dates, columns=syms)
    mask = pd.DataFrame(True, index=dates, columns=syms)
    return factor_panels, fwd, mask


def test_partial_temporal_tuple_split_only_rejected():
    factor_panels, fwd, mask = _build_inputs()
    with pytest.raises(ValueError, match="partial temporal-fingerprint"):
        ResearchMiner(
            factor_panel_map=factor_panels, fwd_returns=fwd, mask=mask,
            families=FAMILIES_V1,
            split_name="alt_year_v1",  # only one of three set
        )


def test_partial_temporal_tuple_role_only_rejected():
    factor_panels, fwd, mask = _build_inputs()
    with pytest.raises(ValueError, match="partial temporal-fingerprint"):
        ResearchMiner(
            factor_panel_map=factor_panels, fwd_returns=fwd, mask=mask,
            families=FAMILIES_V1,
            role="core",  # only role set
        )


def test_partial_temporal_tuple_split_and_sha_no_role_rejected():
    """The exact bypass codex flagged: split_name + split_sha256 set,
    role=None silently disables the C5 guard."""
    factor_panels, fwd, mask = _build_inputs()
    with pytest.raises(ValueError, match="partial temporal-fingerprint"):
        ResearchMiner(
            factor_panel_map=factor_panels, fwd_returns=fwd, mask=mask,
            families=FAMILIES_V1,
            split_name="alt_year_v1",
            split_sha256="abc123",
            role=None,
        )


def test_complete_temporal_tuple_accepted():
    factor_panels, fwd, mask = _build_inputs()
    # Need archive + study for the complete construction to actually happen
    # (record_study is called in __init__). Use an in-memory archive stub.
    class _MockArchive:
        def record_study(self, **kwargs):
            self.last_record = kwargs

    miner = ResearchMiner(
        factor_panel_map=factor_panels, fwd_returns=fwd, mask=mask,
        families=FAMILIES_V1,
        archive=_MockArchive(),
        lineage_tag="t",
        study_id="s",
        split_name="alt_year_v1",
        split_sha256="abc123",
        role="core",
    )
    assert miner.split_name == "alt_year_v1"
    assert miner.role == "core"


def test_legacy_no_temporal_fields_accepted():
    """Pure legacy mining (no temporal fingerprint) must still work."""
    factor_panels, fwd, mask = _build_inputs()
    miner = ResearchMiner(
        factor_panel_map=factor_panels, fwd_returns=fwd, mask=mask,
        families=FAMILIES_V1,
    )
    assert miner.split_name is None
    assert miner.role is None
