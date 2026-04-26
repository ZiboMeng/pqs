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
from typing import Iterable, Mapping, Optional

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

    # Thin-data exposure — TWO metrics shipped per post-MVP M12 fix
    # (2026-04-25 audit, see docs/memos/20260425-m12_review_decision.md):
    #
    #   thin_data_weighted_share  ← the GATE metric (used by tier
    #     classification). Sum over symbols of weight_day_share[s] *
    #     thin_data_pct[s]. Reflects "how much of this candidate's
    #     PnL/exposure actually depends on thin-data bars".
    #
    #   thin_data_binary_share    ← DIAGNOSTIC ONLY. Old definition
    #     (pre-2026-04-25): weight-day share on symbols that have ANY
    #     thin_data history. Kept for backward comparability with
    #     pre-fix artifacts; does NOT participate in tier classification.
    #
    # The PRD v3 §C "thin-data exposure > 5% / > 10%" thresholds map to
    # the WEIGHTED metric per the audit decision memo.
    thin_data_weighted_share: float = 0.0
    thin_data_binary_share: float = 0.0

    # per-symbol watch-list shares (for the R4 watch_exposure section
    # downstream). Includes any symbol in watch_symbols that had non-zero
    # weight-day exposure during the eval window. Empty dict if no
    # watch_symbols passed or none overlapped the panel.
    per_symbol_watch_shares: dict = field(default_factory=dict)

    # Sector concentration — populated when a sector mapping is provided.
    # Pre-2026-04-26 audit-fix: shipped as ``{"status": "not_computed"}``
    # (no mapping wired). Post-fix: per-sector weight-day shares + the
    # max share + a "block_for_review" flag (PRD v3 §C line 287:
    # single-sector weight-days > 50% → block-for-review label, not
    # part of the warning/extreme tier classification).
    sector_concentration: dict = field(default_factory=lambda: {"status": "not_computed"})

    # Benchmark beta concentration — portfolio-level beta dispersion.
    # PRD v3 §C lists this as a dimension but specifies no numeric
    # threshold. We therefore SHIP IT AS REPORT-ONLY (no tier
    # classification): the field carries portfolio-weighted beta
    # statistics so consumers can flag visually, but no automatic
    # warning/extreme tier is set on this axis.
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
    thin_data_weighted: float,
    watch_single: float,
) -> tuple[list, list, ConcentrationGateStatus, NarrativePermission]:
    """Tier classification.

    ``thin_data_weighted`` is THE gate metric (post-MVP audit fix
    2026-04-25). The pre-fix binary share is kept on the report for
    backward comparability but is NOT classified here.
    """
    warnings: list = []
    extremes: list = []

    if top1 > WARNING_TOP1:
        warnings.append(f"top1_weight={top1:.4f}>{WARNING_TOP1}")
    if top3 > WARNING_TOP3:
        warnings.append(f"top3_weight={top3:.4f}>{WARNING_TOP3}")
    if thin_data_weighted > WARNING_THIN_DATA:
        warnings.append(
            f"thin_data_weighted_share={thin_data_weighted:.4f}>{WARNING_THIN_DATA}"
        )
    if watch_single >= WARNING_WATCH_SINGLE:
        warnings.append(f"watch_single_share={watch_single:.4f}>={WARNING_WATCH_SINGLE}")

    if top1 > EXTREME_TOP1:
        extremes.append(f"top1_weight={top1:.4f}>{EXTREME_TOP1}")
    if top3 > EXTREME_TOP3:
        extremes.append(f"top3_weight={top3:.4f}>{EXTREME_TOP3}")
    if thin_data_weighted > EXTREME_THIN_DATA:
        extremes.append(
            f"thin_data_weighted_share={thin_data_weighted:.4f}>{EXTREME_THIN_DATA}"
        )
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


# PRD v3 §C line 287: "single-sector weight-days > 50% → block-for-review".
# This label is separate from warning/extreme tiers and does NOT freeze
# narrative permission on its own (only thin-data extreme + top-1/3
# extreme + watch-single extreme freeze). It IS surfaced on the report
# so that downstream paper / report consumers can flag the candidate
# for an explicit sector-exposure conversation.
SECTOR_BLOCK_REVIEW = 0.50


def compute(
    candidate_id: str,
    weights_df: pd.DataFrame,
    *,
    watch_symbols: Optional[Iterable[str]] = None,
    thin_data_symbols: Optional[Iterable[str]] = None,
    thin_data_pct_map: Optional[Mapping[str, float]] = None,
    sector_map: Optional[Mapping[str, str]] = None,
    beta_map: Optional[Mapping[str, float]] = None,
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
        Symbols with ANY thin-data history. Used for the legacy
        ``thin_data_binary_share`` diagnostic. Pre-2026-04-25 audit fix
        this drove tier classification; post-fix it is diagnostic only.
    thin_data_pct_map : Mapping[str, float], optional
        Per-symbol thin-data fraction in (0, 1]. Used to compute
        ``thin_data_weighted_share`` — the GATE metric that drives tier
        classification (audit fix per docs/memos/20260425-m12_review_decision.md).
        Symbols not in the map default to 0.0 contribution.
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
            thin_data_weighted_share=0.0,
            thin_data_binary_share=0.0,
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

    # Legacy binary share (diagnostic only post-audit): every symbol in
    # ``thin_data_symbols`` contributes its FULL weight-day share.
    thin_in_panel = [s for s in thin_set if s in weights_df.columns]
    thin_binary = _weight_day_share(weights_df, thin_in_panel)

    # Audit-fix weighted share (THE gate metric):
    # Σ_s name_share[s] * thin_data_pct[s] over s in panel ∩ map.
    pct_map = dict(thin_data_pct_map or {})
    thin_weighted = 0.0
    for sym, share in name_share.items():
        pct = pct_map.get(sym, 0.0)
        if pct < 0.0:
            pct = 0.0
        if pct > 1.0:
            # tolerate sidecar that stores percent (0–100) instead of (0–1)
            pct = pct / 100.0
        thin_weighted += float(share) * float(pct)
    thin_weighted = float(thin_weighted)

    # Sector concentration (post-MVP audit fix). Populates only if a
    # sector_map is provided; otherwise leaves the legacy not_computed
    # placeholder.
    sector_payload: dict = {"status": "not_computed"}
    if sector_map is not None:
        sector_shares: dict = {}
        unknown_count = 0
        for sym, share in name_share.items():
            if share <= 0.0:
                continue
            sector = sector_map.get(sym, "Unknown")
            sector_shares[sector] = sector_shares.get(sector, 0.0) + float(share)
            if sector == "Unknown":
                unknown_count += 1
        if sector_shares:
            top_sector_label, top_sector_share = max(
                sector_shares.items(), key=lambda kv: kv[1]
            )
            block_for_review = top_sector_share > SECTOR_BLOCK_REVIEW
        else:
            top_sector_label = None
            top_sector_share = 0.0
            block_for_review = False
        sector_payload = {
            "status": "computed",
            "per_sector_weight_day_share": sector_shares,
            "top_sector_label": top_sector_label,
            "top_sector_weight_day_share": float(top_sector_share),
            "block_for_review_threshold": SECTOR_BLOCK_REVIEW,
            "block_for_review": bool(block_for_review),
            "unknown_symbol_count": unknown_count,
        }

    # Benchmark beta concentration (post-MVP audit fix). PRD v3 §C lists
    # the dimension; thresholds are NOT specified, so we ship report-only
    # statistics (weighted mean / weighted std / max abs |beta|) and let
    # the consumer flag visually. Tier classification is unchanged.
    beta_payload: dict = {"status": "not_computed"}
    if beta_map is not None and len(name_share) > 0:
        weighted_betas = []
        weight_sum = 0.0
        max_abs_beta = 0.0
        for sym, share in name_share.items():
            if share <= 0.0:
                continue
            beta = beta_map.get(sym)
            if beta is None:
                continue
            weighted_betas.append((float(share), float(beta)))
            weight_sum += float(share)
            if abs(beta) > max_abs_beta:
                max_abs_beta = abs(float(beta))
        if weight_sum > 0.0:
            mean_beta = sum(s * b for s, b in weighted_betas) / weight_sum
            var_beta = sum(s * (b - mean_beta) ** 2 for s, b in weighted_betas) / weight_sum
            std_beta = var_beta ** 0.5
            beta_payload = {
                "status": "computed",
                "portfolio_weighted_mean_beta": float(mean_beta),
                "portfolio_weighted_std_beta": float(std_beta),
                "max_abs_per_symbol_beta": float(max_abs_beta),
                "n_symbols_with_beta": int(len(weighted_betas)),
            }

    warnings, extremes, status, permission = _classify(
        top1=top1,
        top3=top3,
        thin_data_weighted=thin_weighted,
        watch_single=watch_single_max,
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
        thin_data_weighted_share=thin_weighted,
        thin_data_binary_share=thin_binary,
        sector_concentration=sector_payload,
        benchmark_beta_concentration=beta_payload,
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
        f"- thin-data WEIGHTED share (gate metric): "
        f"{report.thin_data_weighted_share * 100:.2f}%",
        f"- thin-data binary share (diagnostic, pre-2026-04-25 definition): "
        f"{report.thin_data_binary_share * 100:.2f}%",
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

    # Sector concentration section (computed only if sector_map passed).
    sect = report.sector_concentration
    if sect.get("status") == "computed":
        top_sector = sect.get("top_sector_label")
        top_share = sect.get("top_sector_weight_day_share", 0.0)
        block = sect.get("block_for_review")
        block_thresh = sect.get("block_for_review_threshold", SECTOR_BLOCK_REVIEW)
        per_sector = sect.get("per_sector_weight_day_share", {})
        lines.extend([
            "",
            "## Sector concentration",
            "",
            f"- top sector: `{top_sector}` ({top_share * 100:.2f}%)",
            f"- block-for-review (top > {block_thresh * 100:.0f}%): "
            f"**{'YES' if block else 'no'}**",
            f"- unknown-sector symbols: {sect.get('unknown_symbol_count', 0)}",
            "",
            "Per-sector weight-day shares:",
        ])
        for s, v in sorted(per_sector.items(), key=lambda kv: -kv[1]):
            lines.append(f"  - {s}: {v * 100:.2f}%")
    elif sect.get("status") == "not_computed":
        lines.extend(["", "## Sector concentration", "",
                      "_not computed (no sector_map passed to compute())_"])

    # Benchmark beta concentration section (computed only if beta_map passed).
    beta = report.benchmark_beta_concentration
    if beta.get("status") == "computed":
        lines.extend([
            "",
            "## Benchmark beta concentration",
            "",
            f"- portfolio-weighted mean β: {beta['portfolio_weighted_mean_beta']:.3f}",
            f"- portfolio-weighted std β: {beta['portfolio_weighted_std_beta']:.3f}",
            f"- max |per-symbol β|: {beta['max_abs_per_symbol_beta']:.3f}",
            f"- n symbols with β: {beta['n_symbols_with_beta']}",
            "",
            "_(Report-only — PRD v3 §C lists the dimension but does not "
            "specify numeric thresholds; tier classification is unchanged.)_",
        ])
    elif beta.get("status") == "not_computed":
        lines.extend(["", "## Benchmark beta concentration", "",
                      "_not computed (no beta_map passed to compute())_"])

    lines.extend([
        "",
        "## Caveats",
        "",
        "- This report is **read-only**: it never auto-blocks or auto-revokes",
        "  a candidate. `manual_review_required` freezes narrative permission",
        "  but does not stop further paper runs.",
        "- Sector concentration: warning when top-sector > 50% weight-days",
        "  (block-for-review label per PRD v3 §C line 287). This label is",
        "  separate from the warning/extreme tier and does NOT freeze",
        "  narrative permission; it surfaces a candidate for explicit",
        "  sector-exposure review by the user.",
        "- Benchmark beta concentration is REPORT-ONLY (no automatic tier).",
        "  PRD v3 §C lists it as a dimension but specifies no numeric",
        "  thresholds; statistics are surfaced for visual review.",
        "- **Thin-data metric semantics (post-MVP audit fix 2026-04-25)**:",
        "  the gate uses `thin_data_weighted_share` =",
        "  Σ weight_day_share[s] × thin_data_pct[s], which honestly",
        "  measures how much of the candidate's PnL depends on thin-data",
        "  bars. The legacy `thin_data_binary_share` (any-thin-history",
        "  flag × full weight) is kept for diagnostic continuity but",
        "  systematically over-counts; it does NOT participate in tier",
        "  classification anymore. See",
        "  `docs/memos/20260425-m12_review_decision.md`.",
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
