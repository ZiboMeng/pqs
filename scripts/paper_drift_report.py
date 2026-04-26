#!/usr/bin/env python
"""Paper drift report (Phase E-2 R10).

Compares a historical paper run's artifacts against a fresh replay of
the same frozen spec over the same window. Produces
`drift_report_<timestamp>.md` summarizing NAV delta (bps) + position
set delta + worst drift day.

**Thresholds are informational only** (per auditor fix): a 50 bps
mean drift or 2% any-single-day drift surfaces a "manual review"
flag in the report but does NOT auto-action anything (no demote, no
revoke, no config change).

Usage:
    # Report on the latest paper run for a candidate (auto-detect
    # the newest run directory under data/paper_runs/<candidate>/)
    python scripts/paper_drift_report.py \
        --candidate-id rcm_v1_defensive_composite_01

    # Explicit paper run path
    python scripts/paper_drift_report.py \
        --paper-run-dir data/paper_runs/my_candidate/20260424T171600Z

Hard refusals:
  - paper run dir missing or incomplete (< 5 NAV rows per charter)
  - candidate not in registry (if using --candidate-id)
  - fresh replay fails

Report written to: <paper_run_dir>/drift_report_<YYYYMMDDThhmmssZ>.md

PRDs:
    docs/20260424-prd_phase_e_execution.md §2 E2-R10
    docs/20260424-prd_phase_e_governance_and_paper.md §E-2
    docs/20260424-paper_artifact_schema.md (reader contract)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

from core.logging_setup import get_logger, setup_logging
from core.research.candidate_registry import CandidateRegistry
from core.research.drift_metrics import (
    DriftThresholds,
    compute_nav_drift,
    compute_position_drift,
    worst_drift_day,
)

setup_logging()
logger = get_logger("paper_drift_report")


_DEFAULT_REGISTRY_DB = "data/research_candidates/registry.db"
_DEFAULT_PAPER_ROOT = Path("data/paper_runs")
_MIN_NAV_ROWS = 5     # per charter §6.3: require ≥ 5 days to report


# ── Paper run discovery ─────────────────────────────────────────────────────


def _latest_run_dir(candidate_id: str) -> Optional[Path]:
    """Return the most-recent paper run directory for a candidate, or
    None if no runs exist."""
    base = _DEFAULT_PAPER_ROOT / candidate_id
    if not base.exists():
        return None
    dirs = [d for d in base.iterdir() if d.is_dir()]
    if not dirs:
        return None
    # Sort by modification time; newest first
    return max(dirs, key=lambda d: d.stat().st_mtime)


def _load_paper_run(run_dir: Path) -> tuple[pd.Series, pd.DataFrame, dict]:
    """Load paper NAV series + target weights + meta from a run dir.

    Returns (nav_series, target_wts, meta_dict).
    Raises RuntimeError if the dir is missing required artifacts.
    """
    required = ("live_like_pnl.csv", "target_portfolio_daily.csv",
                "run_meta.json")
    for f in required:
        if not (run_dir / f).exists():
            raise RuntimeError(f"paper run missing {f} under {run_dir}")
    meta = json.loads((run_dir / "run_meta.json").read_text())
    live = pd.read_csv(run_dir / "live_like_pnl.csv",
                      index_col="date", parse_dates=["date"])
    nav = live["nav"]
    targets = pd.read_csv(run_dir / "target_portfolio_daily.csv",
                         index_col=0, parse_dates=True)
    # Index column name may be 'date' or unnamed; normalize
    targets.index.name = "date"
    return nav, targets, meta


# ── Fresh replay ────────────────────────────────────────────────────────────


def _run_fresh_replay(
    candidate_id: str, start_date: str, end_date: str, top_n: int,
    registry_db: str,
) -> Path:
    """Call run_paper_candidate.py in a subprocess into a tmpdir.

    Returns the tmpdir containing the fresh replay artifacts. Caller is
    responsible for tmpdir cleanup (use a context manager).
    """
    tmpdir = Path(tempfile.mkdtemp(prefix="drift_replay_"))
    cmd = [
        sys.executable, str(ROOT / "scripts" / "run_paper_candidate.py"),
        "--candidate-id", candidate_id,
        "--start-date", start_date,
        "--end-date", end_date,
        "--top-n", str(top_n),
        "--registry-db", registry_db,
        "--out-dir", str(tmpdir),
    ]
    logger.info("Replaying: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("Fresh replay failed (exit %d)", result.returncode)
        logger.error("stderr: %s", result.stderr)
        logger.error("stdout: %s", result.stdout)
        raise RuntimeError(
            f"fresh replay exited {result.returncode}; see logs"
        )
    return tmpdir


# ── Markdown report ─────────────────────────────────────────────────────────


def _build_markdown(
    candidate_id: str,
    paper_run_dir: Path,
    meta: dict,
    nav_drift: pd.DataFrame,
    position_drift: pd.DataFrame,
    worst: Optional[dict],
    thresholds: DriftThresholds,
) -> str:
    """Render a markdown drift report."""
    ts = datetime.now(timezone.utc).isoformat()
    n_rows = len(nav_drift)
    mean_bps = (float(nav_drift["delta_bps"].abs().mean())
                if n_rows else None)
    max_bps = (float(nav_drift["delta_bps"].abs().max())
               if n_rows else None)

    # Informational flags
    flags: list[str] = []
    if mean_bps is not None and mean_bps > thresholds.mean_drift_bps:
        flags.append(
            f"Mean |delta| = {mean_bps:.1f} bps exceeds "
            f"{thresholds.mean_drift_bps:.0f} bps → **manual review**"
        )
    if max_bps is not None and max_bps > thresholds.worst_day_fraction * 10_000:
        flags.append(
            f"Worst day |delta| = {max_bps:.1f} bps exceeds "
            f"{thresholds.worst_day_fraction * 10_000:.0f} bps "
            f"({thresholds.worst_day_fraction * 100:.1f}%) → **manual review**"
        )
    if not flags:
        flags.append("No informational review flags triggered.")

    lines: list[str] = [
        f"# Paper Drift Report — `{candidate_id}`",
        "",
        f"**Generated**: {ts}  ",
        f"**Paper run**: `{paper_run_dir}`  ",
        f"**Window**: {meta.get('start_date')} → {meta.get('end_date')}  ",
        f"**Source spec**: `{meta.get('frozen_spec_path')}`  ",
        f"**Status at paper run**: `{meta.get('status_at_run')}`",
        "",
        "## 1. NAV drift",
        "",
        f"| metric | value |",
        f"| --- | --- |",
        f"| n_rows compared | {n_rows} |",
        f"| mean \\|delta\\| (bps) | {mean_bps:.2f} |"
        if mean_bps is not None else "| mean \\|delta\\| (bps) | n/a |",
        f"| max \\|delta\\| (bps) | {max_bps:.2f} |"
        if max_bps is not None else "| max \\|delta\\| (bps) | n/a |",
    ]
    if worst:
        lines.append(
            f"| worst drift day | {worst['date']} ({worst['delta_bps']:+.1f} bps) |"
        )

    lines += [
        "",
        "## 2. Position-set drift",
        "",
    ]
    if not position_drift.empty:
        n_pos_diff_days = int((position_drift["n_symbol_diff"] > 0).sum())
        mean_l1 = float(position_drift["weight_l1_diff_half"].mean())
        max_l1 = float(position_drift["weight_l1_diff_half"].max())
        lines += [
            f"| metric | value |",
            f"| --- | --- |",
            f"| days with symbol-set difference | {n_pos_diff_days} / {len(position_drift)} |",
            f"| mean daily weight L1/2 | {mean_l1:.4f} |",
            f"| max daily weight L1/2 | {max_l1:.4f} |",
        ]
    else:
        lines.append("_no position drift data (empty comparison)_")

    lines += [
        "",
        "## 3. Informational flags",
        "",
    ]
    for f in flags:
        lines.append(f"- {f}")

    # OOS MVP R4: watch-list / thin-data exposure section.
    # Reads <candidate_id>_concentration_report.json + data_quality_watch.parquet
    # produced by the R3 robustness pipeline. Graceful degrade if either is
    # missing.
    from core.research.concentration import render_watch_exposure_section

    watch_lines = render_watch_exposure_section(
        candidate_id,
        section_heading="## 4. Watch-list exposure",
    )
    lines += ["", *watch_lines]

    lines += [
        "",
        "## 5. Interpretation",
        "",
        (
            "A drift between paper artifacts and fresh replay indicates "
            "one of:\n\n"
            "1. **Code change since the paper run** — factor logic, "
            "portfolio rule, or cost model changed. Expected after any "
            "merge to trunk; the magnitude is a signal of impact.\n"
            "2. **Data backfill** — bars added or revised in "
            "`data/mining/*.db` or `data/daily/` since the paper run "
            "(e.g. trades scanner processing a corrected day).\n"
            "3. **Non-determinism** — should not exist; investigate if "
            "drift is nonzero but code + data are unchanged.\n"
            "4. **Future**: paper vs live-execution divergence when real "
            "broker is wired (out of Phase E scope).\n"
        ),
        "",
        "## 6. Thresholds (informational)",
        "",
        f"- mean |delta| above {thresholds.mean_drift_bps:.0f} bps flagged",
        f"- any single day above {thresholds.worst_day_fraction * 100:.1f}%"
        f" ({thresholds.worst_day_fraction * 10_000:.0f} bps) flagged",
        "",
        (
            "Flags are **informational only** (PRD §E2-R10 + auditor "
            "§7.3 fix). This report does not auto-revoke or auto-demote; "
            "action requires explicit `scripts/revoke_candidate.py` "
            "invocation."
        ),
    ]
    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Paper drift report — paper artifacts vs fresh replay",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--candidate-id",
                       help="Auto-detect latest paper run for this candidate")
    group.add_argument("--paper-run-dir",
                       help="Explicit path to the paper run directory")
    parser.add_argument("--registry-db", default=_DEFAULT_REGISTRY_DB)
    parser.add_argument("--top-n", type=int, default=None,
                        help="Top-N for fresh replay; defaults to "
                             "run_meta.json::top_n")
    parser.add_argument("--mean-drift-bps", type=float, default=50.0,
                        help="Informational threshold for mean drift")
    parser.add_argument("--worst-day-fraction", type=float, default=0.02,
                        help="Informational threshold for any single day")
    args = parser.parse_args()

    # Resolve paper run dir
    if args.paper_run_dir:
        paper_run_dir = Path(args.paper_run_dir)
        if not paper_run_dir.exists():
            logger.error("paper_run_dir does not exist: %s", paper_run_dir)
            return 1
        # Determine candidate_id from meta
        meta_path = paper_run_dir / "run_meta.json"
        if not meta_path.exists():
            logger.error("run_meta.json missing in %s", paper_run_dir)
            return 1
        candidate_id = json.loads(meta_path.read_text())["candidate_id"]
    else:
        candidate_id = args.candidate_id
        paper_run_dir = _latest_run_dir(candidate_id)
        if paper_run_dir is None:
            logger.error(
                "No paper runs found for %s under %s",
                candidate_id, _DEFAULT_PAPER_ROOT,
            )
            return 1
        logger.info("Auto-detected paper run: %s", paper_run_dir)

    # Verify candidate exists (registry sanity check)
    registry = CandidateRegistry(args.registry_db)
    if not registry.exists(candidate_id):
        logger.error("Candidate %s not in registry", candidate_id)
        return 1

    # Load paper run artifacts
    try:
        paper_nav, paper_targets, meta = _load_paper_run(paper_run_dir)
    except RuntimeError as e:
        logger.error("%s", e)
        return 1

    if len(paper_nav) < _MIN_NAV_ROWS:
        logger.error(
            "Paper run has only %d NAV rows; need ≥ %d for drift report "
            "(charter §6.3 requirement)",
            len(paper_nav), _MIN_NAV_ROWS,
        )
        return 1

    # Fresh replay
    top_n = args.top_n or meta.get("top_n", 10)
    try:
        replay_dir = _run_fresh_replay(
            candidate_id, meta["start_date"], meta["end_date"],
            top_n, args.registry_db,
        )
    except RuntimeError as e:
        logger.error("%s", e)
        return 1

    try:
        replay_nav, replay_targets, _ = _load_paper_run(replay_dir)

        # Drift metrics
        thresholds = DriftThresholds(
            mean_drift_bps=args.mean_drift_bps,
            worst_day_fraction=args.worst_day_fraction,
        )
        nav_drift = compute_nav_drift(paper_nav, replay_nav)
        position_drift = compute_position_drift(paper_targets, replay_targets)
        worst = worst_drift_day(nav_drift)

        # Write drift artifacts under paper_run_dir
        ts_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        nav_drift.to_csv(paper_run_dir / f"drift_nav_{ts_stamp}.csv")
        position_drift.to_csv(paper_run_dir / f"drift_positions_{ts_stamp}.csv")

        md = _build_markdown(
            candidate_id=candidate_id,
            paper_run_dir=paper_run_dir,
            meta=meta,
            nav_drift=nav_drift,
            position_drift=position_drift,
            worst=worst,
            thresholds=thresholds,
        )
        md_path = paper_run_dir / f"drift_report_{ts_stamp}.md"
        md_path.write_text(md)

        print("=" * 70)
        print(f"Drift report: {candidate_id}")
        print("=" * 70)
        if len(nav_drift):
            mean_bps = float(nav_drift["delta_bps"].abs().mean())
            max_bps = float(nav_drift["delta_bps"].abs().max())
            print(f"  NAV drift mean |delta| : {mean_bps:.2f} bps")
            print(f"  NAV drift max  |delta| : {max_bps:.2f} bps")
        if worst:
            print(f"  Worst drift day         : {worst['date']} "
                  f"({worst['delta_bps']:+.1f} bps)")
        if len(position_drift):
            print(f"  Position-set diff days : "
                  f"{int((position_drift['n_symbol_diff'] > 0).sum())} "
                  f"/ {len(position_drift)}")
        print(f"\nReport   : {md_path}")
        print(f"NAV CSV  : drift_nav_{ts_stamp}.csv (next to report)")
        print(f"Pos CSV  : drift_positions_{ts_stamp}.csv")
        print("\nNOTE: thresholds are informational only; no auto-action "
              "taken.")
    finally:
        # Clean tmpdir
        import shutil
        shutil.rmtree(replay_dir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
