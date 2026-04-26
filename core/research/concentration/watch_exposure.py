"""Watch-list / thin-data exposure markdown section.

Renders the R4 "Watch-list exposure" report section for a candidate.
Reads two artifacts:

  1. ``data/research_candidates/<id>_concentration_report.json`` (R3)
     - per-symbol watch-list weight-day shares
     - aggregate watch / thin-data totals
     - narrative_permission status

  2. ``data/ref/data_quality_watch.parquet`` (round-3 step-3b sidecar)
     - watch_reason / thin_data_count / quarantine_count per symbol

Both consumers (``core.reporting.master_report.MasterReport`` and
``scripts/paper_drift_report.py``) call this helper. Graceful degrade
if either artifact is missing — the section still renders, with a
"data quality unknown" note replacing the table.

PRD: docs/prd/20260425-oos_mvp_ralph_loop_execution.md §3 R4
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pandas as pd

DEFAULT_WATCH_PARQUET = Path("data/ref/data_quality_watch.parquet")
DEFAULT_CANDIDATES_DIR = Path("data/research_candidates")


def _load_concentration(candidate_id: str, candidates_dir: Path) -> Optional[dict]:
    p = candidates_dir / f"{candidate_id}_concentration_report.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _load_watch_sidecar(watch_parquet: Path) -> Optional[pd.DataFrame]:
    if not watch_parquet.exists():
        return None
    try:
        return pd.read_parquet(watch_parquet)
    except Exception:
        return None


def _format_pct(v: Optional[float]) -> str:
    if v is None:
        return "n/a"
    return f"{v * 100:.2f}%"


def render_watch_exposure_section(
    candidate_id: str,
    *,
    watch_parquet: Path = DEFAULT_WATCH_PARQUET,
    candidates_dir: Path = DEFAULT_CANDIDATES_DIR,
    section_heading: str = "## Watch-list exposure",
    top_n: int = 10,
) -> list:
    """Render the watch-list / thin-data exposure section.

    Returns markdown lines (no trailing newline). The section is always
    headed; if data is missing the body says so explicitly rather than
    silently producing an empty section.
    """
    lines: list = [section_heading, ""]

    conc = _load_concentration(candidate_id, candidates_dir)
    sidecar = _load_watch_sidecar(watch_parquet)

    if conc is None and sidecar is None:
        lines.extend([
            "_no concentration report and no watch sidecar — "
            "data quality unknown for this candidate_",
            "",
        ])
        return lines

    if conc is None:
        lines.extend([
            "_no concentration report at "
            f"`{candidates_dir / (candidate_id + '_concentration_report.json')}` "
            "— skip watch-list exposure summary; run "
            "`dev/scripts/oos_mvp/run_robustness_eval.py` to generate it_",
            "",
        ])
        return lines

    if sidecar is None:
        lines.extend([
            f"_no watch sidecar at `{watch_parquet}` — "
            "data quality unknown; concentration aggregates still shown below_",
            "",
        ])
        sidecar = pd.DataFrame(
            columns=["symbol", "watch_reasons", "thin_data_count", "quarantine_count"]
        )

    # Top table per-symbol watch shares + sidecar columns.
    per_symbol = conc.get("per_symbol_watch_shares") or {}
    rows = sorted(per_symbol.items(), key=lambda kv: -kv[1])[:top_n]

    if rows:
        sidecar_indexed = sidecar.set_index("symbol") if "symbol" in sidecar.columns else pd.DataFrame()
        lines.extend([
            "| symbol | weight-day share | watch_reason | thin_data_days | quarantine_days |",
            "| --- | --- | --- | --- | --- |",
        ])
        for sym, share in rows:
            if not sidecar_indexed.empty and sym in sidecar_indexed.index:
                row = sidecar_indexed.loc[sym]
                reason = str(row.get("watch_reasons", "")).strip() or "—"
                # Escape any pipes coming from the sidecar so they don't
                # break the markdown table column boundaries.
                reason = reason.replace("|", "\\|")
                thin_days = int(row.get("thin_data_count", 0) or 0)
                quar_days = int(row.get("quarantine_count", 0) or 0)
            else:
                reason = "—"
                thin_days = 0
                quar_days = 0
            lines.append(
                f"| {sym} | {_format_pct(share)} | {reason} | {thin_days} | {quar_days} |"
            )
        lines.append("")
    else:
        lines.extend([
            "_candidate had no overlap with watch-list symbols during the eval window_",
            "",
        ])

    # Prose summary. Use the WEIGHTED thin metric (post-2026-04-25 audit
    # fix is the gate); also surface the binary diagnostic alongside so
    # readers can compare. Pre-fix artifacts may carry the old
    # ``thin_data_total_share`` key — fall back to it for back-compat.
    watch_total = conc.get("watchlist_total_share")
    thin_weighted = conc.get(
        "thin_data_weighted_share",
        conc.get("thin_data_total_share"),
    )
    thin_binary = conc.get("thin_data_binary_share", thin_weighted)
    n_dates = conc.get("n_dates")

    distinct_thin_days_total = (
        int(sidecar["thin_data_count"].fillna(0).sum())
        if "thin_data_count" in sidecar.columns and not sidecar.empty
        else 0
    )
    distinct_quar_days_total = (
        int(sidecar["quarantine_count"].fillna(0).sum())
        if "quarantine_count" in sidecar.columns and not sidecar.empty
        else 0
    )

    # Day counters from the sidecar are summed across all watch symbols —
    # they are SYMBOL-DAYS, not unique calendar days. Spell that out so
    # readers don't conflate "9523 thin_data flagged days" with calendar
    # days during the eval window.
    prose = (
        f"Candidate has {_format_pct(watch_total)} weight-day-share on watch-list "
        f"names over {n_dates} eval days; thin-data WEIGHTED share (gate) "
        f"{_format_pct(thin_weighted)}, thin-data binary share (diagnostic) "
        f"{_format_pct(thin_binary)}; watch-list sidecar reports "
        f"{distinct_thin_days_total} thin_data flagged symbol-days and "
        f"{distinct_quar_days_total} quarantined symbol-days summed across all "
        f"watch symbols (NOT unique calendar days)."
    )
    lines.extend([prose, ""])

    # Explicit narrative_permission echo so consumers cannot miss it.
    perm = conc.get("narrative_permission")
    status = conc.get("concentration_gate_status")
    if perm is not None or status is not None:
        lines.extend([
            f"**concentration_gate_status**: `{status}`",
            f"**narrative_permission**: `{perm}`",
            "",
        ])

    return lines
