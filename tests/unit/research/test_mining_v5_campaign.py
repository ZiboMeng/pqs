from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from core.research.mining_v5_campaign import (
    build_track_a_targets,
    load_v5_campaign,
)

ROOT = Path(__file__).resolve().parents[3]
PREREG = ROOT / "research/preregistrations/20260722-mining-v5-balanced-v1.yaml"


def _levels() -> pd.DataFrame:
    index = pd.bdate_range("2013-01-01", "2024-12-31")
    base = np.linspace(100.0, 240.0, len(index))
    return pd.DataFrame(
        {symbol: base * (1.0 + offset) for offset, symbol in enumerate(
            ["SPY", "BIL", "QUAL", "MTUM", "USMV", "IEF", "GLD"]
        )},
        index=index,
    )


def test_preregistration_is_hash_bound_and_has_exact_exit_rule() -> None:
    campaign = load_v5_campaign(PREREG, repo_root=ROOT)
    assert len(campaign["rounds"]) == 30
    assert campaign["exit_rule"]["stop_when_formal_candidates"] == 5


def test_all_track_a_targets_are_long_only_unlevered_and_deterministic() -> None:
    levels = _levels()
    first = pd.Timestamp("2014-12-31")
    last = pd.Timestamp("2024-12-31")
    constructions = [
        "static_80_20", "spy_vol_only", "spy_trend_only", "spy_vol_trend",
        "qmlv_no_overlay", "qmlv_risk", "qm_risk", "qlv_risk", "mlv_risk",
        "qmlv_60_40_risk", "qmlv_multidefense",
    ]
    for construction in constructions:
        first_run = build_track_a_targets(
            construction, levels, first_decision=first, last_decision=last
        )
        second_run = build_track_a_targets(
            construction, levels, first_decision=first, last_decision=last
        )
        pd.testing.assert_frame_equal(first_run, second_run)
        assert (first_run >= 0.0).all().all()
        assert (first_run.sum(axis=1) <= 1.0 + 1e-12).all()


def test_future_mutation_does_not_change_prior_targets() -> None:
    levels = _levels()
    first = pd.Timestamp("2014-12-31")
    cutoff = pd.Timestamp("2023-12-29")
    baseline = build_track_a_targets(
        "qmlv_risk", levels, first_decision=first, last_decision=cutoff
    )
    mutated = levels.copy()
    mutated.iloc[-1] *= 10.0
    comparison = build_track_a_targets(
        "qmlv_risk", mutated, first_decision=first, last_decision=cutoff
    )
    pd.testing.assert_frame_equal(baseline, comparison)
