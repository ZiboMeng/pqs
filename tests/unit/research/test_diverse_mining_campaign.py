from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.research.diverse_mining_campaign import (
    MiningCampaignError,
    cross_sectional_rule_score,
    load_campaign,
    select_formal_candidates,
    synthetic_market_neutral_returns,
    validate_qualification_partition,
)

ROOT = Path(__file__).resolve().parents[3]


def test_preregistration_has_exact_exit_semantics_and_30_rounds() -> None:
    campaign = load_campaign(
        ROOT / "research/preregistrations/20260721-diverse-mining-campaign-v1.yaml"
    )
    assert len(campaign["rounds"]) == 30
    assert campaign["exit_rule"]["stop_when_formal_candidates"] == 5
    assert campaign["rounds"][-1]["kind"] == "blocked_feasibility"


def test_rule_score_uses_oriented_cross_sectional_ranks() -> None:
    dates = pd.DatetimeIndex(["2024-01-31"])
    columns = ["A", "B", "C"]
    eligibility = pd.DataFrame(True, index=dates, columns=columns)
    features = {
        "momentum": pd.DataFrame([[1.0, 2.0, 3.0]], index=dates, columns=columns),
        "risk": pd.DataFrame([[3.0, 2.0, 1.0]], index=dates, columns=columns),
    }
    score = cross_sectional_rule_score(
        features, eligibility, {"momentum": 1.0, "risk": -1.0}
    )
    assert score.loc[dates[0], "C"] > score.loc[dates[0], "B"]
    assert score.loc[dates[0], "B"] > score.loc[dates[0], "A"]


def test_synthetic_short_is_next_session_and_cost_sensitive() -> None:
    dates = pd.bdate_range("2024-01-02", periods=6)
    symbols = [f"S{i}" for i in range(20)]
    score = pd.DataFrame([np.arange(20)], index=[dates[1]], columns=symbols)
    returns = pd.DataFrame(0.0, index=dates, columns=symbols)
    returns.loc[dates[2]:, symbols[-10:]] = 0.01
    returns.loc[dates[2]:, symbols[:10]] = -0.01
    low_cost = synthetic_market_neutral_returns(
        score, returns, cost_bps=0.0, annual_borrow_fee=0.0
    )
    high_cost = synthetic_market_neutral_returns(
        score, returns, cost_bps=90.0, annual_borrow_fee=0.10
    )
    assert low_cost.loc[dates[1]] == 0.0
    assert low_cost.loc[dates[2]] > 0.0
    assert high_cost.sum() < low_cost.sum()


def test_formal_selection_enforces_family_and_correlation() -> None:
    index = pd.bdate_range("2024-01-02", periods=30)
    base = pd.Series(np.linspace(-0.01, 0.01, len(index)), index=index)
    candidates = [
        {"candidate_id": "a", "family": "f1", "qualification_passed": True},
        {"candidate_id": "b", "family": "f1", "qualification_passed": True},
        {"candidate_id": "c", "family": "f2", "qualification_passed": True},
        {"candidate_id": "d", "family": "f3", "qualification_passed": False},
    ]
    selected, rejected = select_formal_candidates(
        candidates,
        {"a": base, "b": -base, "c": base * 0.99, "d": base},
    )
    assert [row["candidate_id"] for row in selected] == ["a"]
    reasons = {row["candidate_id"]: row["reason"] for row in rejected}
    assert reasons == {
        "b": "SIBLING_FAMILY_LIMIT",
        "c": "RETURN_CORRELATION_BUDGET",
        "d": "QUALIFICATION_FAILED",
    }


def test_qualification_paths_are_an_exact_partition() -> None:
    validate_qualification_partition(
        ["a", "b", "c"],
        ["a", "c"],
        [{"candidate_id": "b"}],
    )

    with pytest.raises(MiningCampaignError, match="overlap"):
        validate_qualification_partition(
            ["a", "b"],
            ["a"],
            [{"candidate_id": "a"}, {"candidate_id": "b"}],
        )

    with pytest.raises(MiningCampaignError, match="do not partition"):
        validate_qualification_partition(
            ["a", "b"],
            ["a"],
            [],
        )
