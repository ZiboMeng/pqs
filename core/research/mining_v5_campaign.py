"""Frozen Track-A constructions and preregistration checks for Mining V5."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import yaml

from core.research.qualification_v2 import sha256_file


class MiningV5Error(RuntimeError):
    """Raised when V5 inputs or a frozen construction drift."""


def load_v5_campaign(path: str | Path, *, repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    prereg = Path(path).resolve()
    payload = yaml.safe_load(prereg.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise MiningV5Error("unsupported V5 preregistration schema")
    rounds = payload.get("rounds")
    if not isinstance(rounds, list) or len(rounds) != 30:
        raise MiningV5Error("V5 must preregister exactly 30 rounds")
    if [row.get("round") for row in rounds] != list(range(1, 31)):
        raise MiningV5Error("V5 rounds must be contiguous 1..30")
    if len({row.get("id") for row in rounds}) != 30:
        raise MiningV5Error("V5 round IDs must be unique")
    if payload.get("exit_rule") != {
        "stop_when_formal_candidates": 5,
        "maximum_rounds": 30,
        "one_sibling_per_family": True,
        "maximum_absolute_candidate_correlation": 0.70,
    }:
        raise MiningV5Error("V5 exit or diversity rule drifted")
    for label in ("prd", "governance", "evaluation_contract", "canonical_benchmark"):
        reference = payload.get(label)
        if not isinstance(reference, Mapping):
            raise MiningV5Error(f"V5 {label} reference missing")
        source = (root / str(reference.get("path", ""))).resolve()
        try:
            source.relative_to(root)
        except ValueError as exc:
            raise MiningV5Error(f"V5 {label} is outside repo") from exc
        if not source.is_file() or sha256_file(source) != reference.get("sha256"):
            raise MiningV5Error(f"V5 {label} hash mismatch")
    data_reference = payload.get("track_a_data")
    if not isinstance(data_reference, Mapping):
        raise MiningV5Error("V5 Track-A data reference missing")
    manifest = (root / str(data_reference.get("manifest_path", ""))).resolve()
    try:
        manifest.relative_to(root)
    except ValueError as exc:
        raise MiningV5Error("V5 Track-A manifest is outside repo") from exc
    if (
        not manifest.is_file()
        or sha256_file(manifest) != data_reference.get("manifest_sha256")
    ):
        raise MiningV5Error("V5 Track-A manifest hash mismatch")
    return payload


def month_end_sessions(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    marker = index.to_period("M")
    return index[~marker.duplicated(keep="last")]


def risk_scales(spy_total_return_close: pd.Series) -> pd.DataFrame:
    """Compute the sole preregistered monthly 15% vol / dual-SMA overlay."""

    if not isinstance(spy_total_return_close.index, pd.DatetimeIndex):
        raise TypeError("SPY total-return level requires DatetimeIndex")
    values = spy_total_return_close.astype(float)
    returns = values.pct_change(fill_method=None)
    rv21 = returns.rolling(21, min_periods=21).std(ddof=1) * math.sqrt(252.0)
    rv63 = returns.rolling(63, min_periods=63).std(ddof=1) * math.sqrt(252.0)
    vol_scale = (0.15 / pd.concat([rv21, rv63], axis=1).max(axis=1)).clip(
        upper=1.0
    )
    vote126 = values > values.rolling(126, min_periods=126).mean()
    vote252 = values > values.rolling(252, min_periods=252).mean()
    votes = vote126.astype(int) + vote252.astype(int)
    trend_scale = votes.map({0: 0.25, 1: 0.50, 2: 1.00}).astype(float)
    output = pd.DataFrame({
        "vol_scale": vol_scale,
        "trend_scale": trend_scale,
        "combined_scale": pd.concat([vol_scale, trend_scale], axis=1).min(axis=1),
    })
    return output.loc[month_end_sessions(output.index)].dropna()


def build_track_a_targets(
    construction: str,
    total_return_close: pd.DataFrame,
    *,
    first_decision: pd.Timestamp,
    last_decision: pd.Timestamp,
) -> pd.DataFrame:
    """Build exactly one of the preregistered R02-R12 target-weight paths."""

    required = {"SPY", "BIL", "QUAL", "MTUM", "USMV"}
    if construction == "qmlv_multidefense":
        required |= {"IEF", "GLD"}
    if required - set(total_return_close):
        raise MiningV5Error(f"Track-A data missing {sorted(required-set(total_return_close))}")
    scales = risk_scales(total_return_close["SPY"])
    decisions = scales.index[
        (scales.index >= first_decision) & (scales.index <= last_decision)
    ]
    if first_decision not in decisions:
        raise MiningV5Error("first decision must be a valid month-end session")
    columns = list(total_return_close.columns)
    targets = pd.DataFrame(0.0, index=decisions, columns=columns)

    factor_map: dict[str, tuple[float, tuple[str, ...], str | None]] = {
        "qmlv_no_overlay": (0.70, ("QUAL", "MTUM", "USMV"), None),
        "qmlv_risk": (0.70, ("QUAL", "MTUM", "USMV"), "combined_scale"),
        "qm_risk": (0.70, ("QUAL", "MTUM"), "combined_scale"),
        "qlv_risk": (0.70, ("QUAL", "USMV"), "combined_scale"),
        "mlv_risk": (0.70, ("MTUM", "USMV"), "combined_scale"),
        "qmlv_60_40_risk": (0.60, ("QUAL", "MTUM", "USMV"), "combined_scale"),
        "qmlv_multidefense": (0.70, ("QUAL", "MTUM", "USMV"), "combined_scale"),
    }
    if construction == "static_80_20":
        targets.loc[:, "SPY"] = 0.80
        targets.loc[:, "BIL"] = 0.20
        return targets.iloc[[0]]
    if construction in {"spy_vol_only", "spy_trend_only", "spy_vol_trend"}:
        scale_name = {
            "spy_vol_only": "vol_scale",
            "spy_trend_only": "trend_scale",
            "spy_vol_trend": "combined_scale",
        }[construction]
        scale = scales.loc[decisions, scale_name]
        targets.loc[:, "SPY"] = scale
        targets.loc[:, "BIL"] = 1.0 - scale
        return targets
    if construction not in factor_map:
        raise MiningV5Error(f"unknown Track-A construction {construction!r}")
    anchor, factors, scale_name = factor_map[construction]
    equity = pd.Series(1.0, index=decisions)
    if scale_name is not None:
        equity = scales.loc[decisions, scale_name]
    targets.loc[:, "SPY"] = anchor * equity
    sleeve_total = (1.0 - anchor) * equity
    for symbol in factors:
        targets.loc[:, symbol] = sleeve_total / len(factors)
    residual = 1.0 - equity
    if construction != "qmlv_multidefense":
        targets.loc[:, "BIL"] = residual
    else:
        ief_on = total_return_close["IEF"] > total_return_close["IEF"].rolling(
            252, min_periods=252
        ).mean()
        gld_on = total_return_close["GLD"] > total_return_close["GLD"].rolling(
            252, min_periods=252
        ).mean()
        ief_weight = residual * 0.25 * ief_on.reindex(decisions).astype(float)
        gld_weight = residual * 0.25 * gld_on.reindex(decisions).astype(float)
        targets.loc[:, "IEF"] = ief_weight
        targets.loc[:, "GLD"] = gld_weight
        targets.loc[:, "BIL"] = residual - ief_weight - gld_weight
    if bool((targets < -1e-12).any().any()) or bool(
        (targets.sum(axis=1) > 1.0 + 1e-12).any()
    ):
        raise MiningV5Error("Track-A target violates long-only/gross constraints")
    if construction == "qmlv_no_overlay":
        return targets.iloc[[0]]
    return targets


__all__ = [
    "MiningV5Error",
    "build_track_a_targets",
    "load_v5_campaign",
    "month_end_sessions",
    "risk_scales",
]
