"""M12 concentration report.

PRD v3 §C: report-only concentration gate. Two tiers:
  - warning (top-1 > 40% / top-3 > 70% / thin-data > 5% / watch-single >= 8%)
  - extreme (top-1 > 50% / top-3 > 80% / thin-data > 10% / watch-single > 15%)
Extreme tier sets ``concentration_gate_status: manual_review_required``
and ``narrative_permission: frozen``. **No hard block** — the candidate
still produces an artifact; downstream paper / report consumers see the
status string and gate themselves.

Sector and benchmark-beta concentration are listed as dimensions in the
PRD but only sector has a "block-for-review label" (not in the extreme
tier). Both are marked ``not_computed`` here for MVP — neither
participates in tier classification.

Execution PRD: docs/prd/20260425-oos_mvp_ralph_loop_execution.md §3 R3
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd


# ── thresholds (numeric copies of PRD v3 §C lines 281-294) ──────────────
WARNING_TOP1 = 0.40
WARNING_TOP3 = 0.70
WARNING_THIN_DATA = 0.05
WARNING_WATCH_SINGLE = 0.08

EXTREME_TOP1 = 0.50
EXTREME_TOP3 = 0.80
EXTREME_THIN_DATA = 0.10
EXTREME_WATCH_SINGLE = 0.15


class ConcentrationGateStatus(str, Enum):
    pass_ = "pass"
    warning = "warning"
    manual_review_required = "manual_review_required"


class NarrativePermission(str, Enum):
    allowed = "allowed"
    frozen = "frozen"


@dataclass
class ConcentrationReport:
    """Concentration metrics + tier classification for a single candidate."""

    candidate_id: str
    n_dates: int

    # top-N max-across-dates weight
    top1_weight_max: float
    top3_weight_max: float
    top5_weight_max: float

    # name-days
    distinct_names_count: int
    name_days_max_share: float

    # weight-day shares
    watchlist_single_max_share: float
    watchlist_total_share: float
    thin_data_total_share: float

    # per-symbol watch-list shares (for the R4 watch_exposure section
    # downstream). Includes any symbol in watch_symbols that had non-zero
    # weight-day exposure during the eval window. Empty dict if no
    # watch_symbols passed or none overlapped the panel.
    per_symbol_watch_shares: dict = field(default_factory=dict)

    # not computed for MVP (sector mapping + beta data not wired here)
    sector_concentration: dict = field(default_factory=lambda: {"status": "not_computed"})
    benchmark_beta_concentration: dict = field(default_factory=lambda: {"status": "not_computed"})

    # tier classification
    triggered_warnings: list = field(default_factory=list)
    triggered_extremes: list = field(default_factory=list)
    concentration_gate_status: ConcentrationGateStatus = ConcentrationGateStatus.pass_
    narrative_permission: NarrativePermission = NarrativePermission.allowed

    def to_dict(self) -> dict:
        d = asdict(self)
        d["concentration_gate_status"] = self.concentration_gate_status.value
        d["narrative_permission"] = self.narrative_permission.value
        return d


def _classify(
    *,
    top1: float,
    top3: float,
    thin_data: float,
    watch_single: float,
) -> tuple[list, list, ConcentrationGateStatus, NarrativePermission]:
    warnings: list = []
    extremes: list = []

    if top1 > WARNING_TOP1:
        warnings.append(f"top1_weight={top1:.4f}>{WARNING_TOP1}")
    if top3 > WARNING_TOP3:
        warnings.append(f"top3_weight={top3:.4f}>{WARNING_TOP3}")
    if thin_data > WARNING_THIN_DATA:
        warnings.append(f"thin_data_share={thin_data:.4f}>{WARNING_THIN_DATA}")
    if watch_single >= WARNING_WATCH_SINGLE:
        warnings.append(f"watch_single_share={watch_single:.4f}>={WARNING_WATCH_SINGLE}")

    if top1 > EXTREME_TOP1:
        extremes.append(f"top1_weight={top1:.4f}>{EXTREME_TOP1}")
    if top3 > EXTREME_TOP3:
        extremes.append(f"top3_weight={top3:.4f}>{EXTREME_TOP3}")
    if thin_data > EXTREME_THIN_DATA:
        extremes.append(f"thin_data_share={thin_data:.4f}>{EXTREME_THIN_DATA}")
    if watch_single > EXTREME_WATCH_SINGLE:
        extremes.append(f"watch_single_share={watch_single:.4f}>{EXTREME_WATCH_SINGLE}")

    if extremes:
        status = ConcentrationGateStatus.manual_review_required
        permission = NarrativePermission.frozen
    elif warnings:
        status = ConcentrationGateStatus.warning
        permission = NarrativePermission.allowed
    else:
        status = ConcentrationGateStatus.pass_
        permission = NarrativePermission.allowed
    return warnings, extremes, status, permission


def _row_topk(weights_df: pd.DataFrame, k: int) -> pd.Series:
    """Per-date top-k weight sum (or first-k if fewer columns)."""
    abs_w = weights_df.abs()
    return abs_w.apply(lambda r: r.nlargest(min(k, len(r))).sum(), axis=1)


def _weight_day_share(weights_df: pd.DataFrame, symbols: Iterable[str]) -> float:
    """Sum |weight| over (date, symbol in given set) divided by total |weight|.

    Treats sum of absolute weights as the weight-day denominator.
    """
    total = weights_df.abs().to_numpy().sum()
    if total <= 0:
        return 0.0
    selected = weights_df.reindex(columns=list(symbols), fill_value=0.0)
    return float(selected.abs().to_numpy().sum() / total)


def _per_symbol_weight_day_share(weights_df: pd.DataFrame) -> pd.Series:
    """Per-symbol fraction of total weight-days (sum |weight| over all dates,
    normalized by total |weight|).
    """
    total = weights_df.abs().to_numpy().sum()
    if total <= 0:
        return pd.Series(dtype=float)
    return weights_df.abs().sum(axis=0) / total


def compute(
    candidate_id: str,
    weights_df: pd.DataFrame,
    *,
    watch_symbols: Optional[Iterable[str]] = None,
    thin_data_symbols: Optional[Iterable[str]] = None,
) -> ConcentrationReport:
    """Compute concentration metrics + tier classification for a candidate.

    Parameters
    ----------
    candidate_id : str
    weights_df : DataFrame index=date, columns=symbols, values=portfolio weights
        (positive long-only is the normal case; absolute values are used for
        all share calculations so signed weights still produce sensible
        concentration metrics).
    watch_symbols : iterable of str, optional
        Symbols on the data_quality_watch list. Used for watch-list
        concentration (single-name max share + total share).
    thin_data_symbols : iterable of str, optional
        Symbols flagged thin_data. Used for thin-data exposure.
    """
    n_dates = int(weights_df.shape[0])
    if n_dates == 0:
        return ConcentrationReport(
            candidate_id=candidate_id,
            n_dates=0,
            top1_weight_max=0.0,
            top3_weight_max=0.0,
            top5_weight_max=0.0,
            distinct_names_count=0,
            name_days_max_share=0.0,
            watchlist_single_max_share=0.0,
            watchlist_total_share=0.0,
            thin_data_total_share=0.0,
        )

    top1 = float(_row_topk(weights_df, 1).max())
    top3 = float(_row_topk(weights_df, 3).max())
    top5 = float(_row_topk(weights_df, 5).max())

    name_share = _per_symbol_weight_day_share(weights_df)
    distinct = int((name_share > 0).sum())
    name_days_max = float(name_share.max()) if len(name_share) else 0.0

    watch_set = set(watch_symbols or [])
    thin_set = set(thin_data_symbols or [])

    watch_in_panel = [s for s in watch_set if s in weights_df.columns]
    if watch_in_panel:
        watch_shares_series = name_share.reindex(watch_in_panel).fillna(0.0)
        watch_single_max = float(watch_shares_series.max())
        per_symbol_watch_shares = {
            s: float(v) for s, v in watch_shares_series.items() if v > 0.0
        }
    else:
        watch_single_max = 0.0
        per_symbol_watch_shares = {}
    watch_total = _weight_day_share(weights_df, watch_in_panel)

    thin_in_panel = [s for s in thin_set if s in weights_df.columns]
    thin_total = _weight_day_share(weights_df, thin_in_panel)

    warnings, extremes, status, permission = _classify(
        top1=top1, top3=top3, thin_data=thin_total, watch_single=watch_single_max
    )

    return ConcentrationReport(
        candidate_id=candidate_id,
        n_dates=n_dates,
        top1_weight_max=top1,
        top3_weight_max=top3,
        top5_weight_max=top5,
        distinct_names_count=distinct,
        name_days_max_share=name_days_max,
        watchlist_single_max_share=watch_single_max,
        watchlist_total_share=watch_total,
        thin_data_total_share=thin_total,
        per_symbol_watch_shares=per_symbol_watch_shares,
        triggered_warnings=warnings,
        triggered_extremes=extremes,
        concentration_gate_status=status,
        narrative_permission=permission,
    )


def _format_md(report: ConcentrationReport) -> str:
    lines = [
        f"# Concentration report — {report.candidate_id}",
        "",
        f"**concentration_gate_status**: `{report.concentration_gate_status.value}`",
        f"**narrative_permission**: `{report.narrative_permission.value}`",
        "",
        "## Metrics",
        "",
        f"- top-1 max weight: {report.top1_weight_max * 100:.2f}%",
        f"- top-3 max weight: {report.top3_weight_max * 100:.2f}%",
        f"- top-5 max weight: {report.top5_weight_max * 100:.2f}%",
        f"- distinct names held: {report.distinct_names_count}",
        f"- max single-name weight-day share: {report.name_days_max_share * 100:.2f}%",
        f"- watch-list single-name max share: {report.watchlist_single_max_share * 100:.2f}%",
        f"- watch-list total share: {report.watchlist_total_share * 100:.2f}%",
        f"- thin-data total share: {report.thin_data_total_share * 100:.2f}%",
        "",
        "## Tier classification (PRD v3 §C)",
        "",
        "Triggered warnings:",
    ]
    if report.triggered_warnings:
        lines.extend(f"  - {w}" for w in report.triggered_warnings)
    else:
        lines.append("  - (none)")
    lines.extend([
        "",
        "Triggered extremes:",
    ])
    if report.triggered_extremes:
        lines.extend(f"  - {e}" for e in report.triggered_extremes)
    else:
        lines.append("  - (none)")

    lines.extend([
        "",
        "## Caveats",
        "",
        "- This report is **read-only**: it never auto-blocks or auto-revokes",
        "  a candidate. `manual_review_required` freezes narrative permission",
        "  but does not stop further paper runs.",
        "- Sector + benchmark-beta concentration are not computed in this MVP",
        "  (no per-symbol sector mapping wired); both are marked",
        "  `not_computed` in the JSON. Neither participates in tier",
        "  classification per PRD v3 §C extreme thresholds.",
        "",
    ])
    return "\n".join(lines)


def write_artifacts(report: ConcentrationReport, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{report.candidate_id}_concentration_report.json"
    md_path = output_dir / f"{report.candidate_id}_concentration_report.md"
    json_path.write_text(json.dumps(report.to_dict(), indent=2, default=str))
    md_path.write_text(_format_md(report))
    return {
        "concentration_json": str(json_path),
        "concentration_md": str(md_path),
    }
