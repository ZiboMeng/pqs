"""Deterministic helpers for the preregistered diverse mining campaign."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import yaml


class MiningCampaignError(RuntimeError):
    """Raised when the preregistered campaign contract is violated."""


def load_campaign(path: str | Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise MiningCampaignError("unsupported mining campaign schema")
    rounds = payload.get("rounds")
    if not isinstance(rounds, list) or len(rounds) != 30:
        raise MiningCampaignError("campaign must preregister exactly 30 rounds")
    numbers = [row.get("round") for row in rounds]
    if numbers != list(range(1, 31)):
        raise MiningCampaignError("campaign rounds must be contiguous 1..30")
    ids = [str(row.get("id", "")) for row in rounds]
    if any(not item for item in ids) or len(ids) != len(set(ids)):
        raise MiningCampaignError("campaign round ids must be unique and non-empty")
    exit_rule = payload.get("exit_rule") or {}
    if exit_rule.get("stop_when_formal_candidates") != 5:
        raise MiningCampaignError("formal candidate exit threshold must be 5")
    if exit_rule.get("maximum_rounds") != 30:
        raise MiningCampaignError("maximum round count must be 30")
    return payload


def cross_sectional_rule_score(
    features: Mapping[str, pd.DataFrame],
    eligibility: pd.DataFrame,
    feature_weights: Mapping[str, float],
) -> pd.DataFrame:
    """Combine causal features after per-date rank normalization."""

    if not feature_weights:
        raise MiningCampaignError("rule round has no features")
    score = pd.DataFrame(0.0, index=eligibility.index, columns=eligibility.columns)
    total_weight = 0.0
    for name, raw_weight in feature_weights.items():
        if name not in features:
            raise MiningCampaignError(f"unknown preregistered feature {name!r}")
        weight = float(raw_weight)
        if not math.isfinite(weight) or weight == 0:
            raise MiningCampaignError(f"invalid weight for feature {name!r}")
        values = features[name].reindex(
            index=eligibility.index, columns=eligibility.columns
        )
        oriented = values if weight > 0 else -values
        ranked = oriented.rank(axis=1, pct=True, method="average")
        score = score.add(ranked * abs(weight), fill_value=0.0)
        total_weight += abs(weight)
    score = score / total_weight
    return score.where(eligibility)


def synthetic_market_neutral_returns(
    scores: pd.DataFrame,
    asset_total_returns: pd.DataFrame,
    *,
    top_k: int = 10,
    gross_exposure: float = 1.0,
    cost_bps: float = 30.0,
    annual_borrow_fee: float = 0.03,
) -> pd.Series:
    """Conservative close-to-close diagnostic, never formal short evidence.

    Weights formed at decision close become effective one session later.
    Turnover and borrow are charged explicitly.  Absence of PIT locate/fee and
    open/NBBO execution keeps every consumer at ``RESEARCH_INCOMPLETE``.
    """

    if top_k < 1 or gross_exposure <= 0 or cost_bps < 0 or annual_borrow_fee < 0:
        raise ValueError("invalid synthetic short parameters")
    common_columns = scores.columns.intersection(asset_total_returns.columns)
    scores = scores.loc[:, common_columns]
    asset_total_returns = asset_total_returns.loc[:, common_columns]
    target_rows: list[pd.Series] = []
    for date, row in scores.iterrows():
        valid = row.dropna().sort_values(kind="mergesort")
        target = pd.Series(0.0, index=common_columns, name=date)
        if len(valid) >= 2 * top_k:
            leg_weight = gross_exposure / 2.0 / top_k
            target.loc[valid.tail(top_k).index] = leg_weight
            target.loc[valid.head(top_k).index] = -leg_weight
        target_rows.append(target)
    decisions = pd.DataFrame(target_rows)
    daily_targets = decisions.reindex(asset_total_returns.index).ffill().shift(1)
    daily_targets = daily_targets.fillna(0.0)
    gross_returns = (daily_targets * asset_total_returns.fillna(0.0)).sum(axis=1)
    decision_turnover = decisions.diff().abs().sum(axis=1)
    if len(decision_turnover):
        decision_turnover.iloc[0] = decisions.iloc[0].abs().sum()
    cost = pd.Series(0.0, index=asset_total_returns.index)
    for decision_date, turnover in decision_turnover.items():
        position = asset_total_returns.index.searchsorted(decision_date, side="right")
        if position < len(cost):
            cost.iloc[position] += float(turnover) * cost_bps / 10_000.0
    short_gross = daily_targets.clip(upper=0.0).abs().sum(axis=1)
    borrow = short_gross * annual_borrow_fee / 252.0
    return (gross_returns - cost - borrow).rename("synthetic_short_return")


def select_formal_candidates(
    ordered_candidates: list[dict[str, Any]],
    returns: Mapping[str, pd.Series],
    *,
    maximum: int = 5,
    max_correlation: float = 0.70,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Enforce canonical PASS, one sibling/family, and correlation budget."""

    selected: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    families: set[str] = set()
    for candidate in ordered_candidates:
        candidate_id = str(candidate["candidate_id"])
        family = str(candidate["family"])
        if candidate.get("qualification_passed") is not True:
            rejected.append({"candidate_id": candidate_id, "reason": "QUALIFICATION_FAILED"})
            continue
        if family in families:
            rejected.append({"candidate_id": candidate_id, "reason": "SIBLING_FAMILY_LIMIT"})
            continue
        correlations: dict[str, float] = {}
        for prior in selected:
            pair = pd.concat(
                [returns[candidate_id], returns[str(prior["candidate_id"])]],
                axis=1,
                join="inner",
            ).dropna()
            correlation = float(pair.corr().iloc[0, 1]) if len(pair) >= 20 else 1.0
            correlations[str(prior["candidate_id"])] = correlation
        if any(abs(value) >= max_correlation for value in correlations.values()):
            rejected.append({
                "candidate_id": candidate_id,
                "reason": "RETURN_CORRELATION_BUDGET",
                "correlations": correlations,
            })
            continue
        selected.append(candidate)
        families.add(family)
        if len(selected) == maximum:
            break
    return selected, rejected


__all__ = [
    "MiningCampaignError",
    "cross_sectional_rule_score",
    "load_campaign",
    "select_formal_candidates",
    "synthetic_market_neutral_returns",
]
