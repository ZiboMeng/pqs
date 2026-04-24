#!/usr/bin/env python
"""Dump a git-committable snapshot of candidate registry + paper runs.

Auditor P1-2 fix. The registry DB (`data/research_candidates/registry.db`)
and paper artifacts (`data/paper_runs/`) are gitignored. That makes
README / CLAUDE.md claims about "registry has N candidates at S2" or
"Candidate-2 has paper artifacts at <path>" impossible to independently
verify from a fresh clone — a reader has to trust docs alone.

This script emits a read-only snapshot markdown that CAN be committed,
giving the repo a self-sufficient view of the governance state:

  - all rows in `data/research_candidates/registry.db` (candidate_id,
    status, lineage, memo / spec paths, promoted/revoked timestamps)
  - per-candidate paper run directory listing (run timestamp + filename
    manifest)
  - generation metadata (git HEAD, timestamp)

The DB itself is NOT committed — too noisy, schema-dependent, and
recreatable. The snapshot doc IS committed as the audit surface.

Usage:
    python dev/scripts/export/dump_phase_state_snapshot.py \\
        --out docs/$(date -u +%Y%m%d)-phase_state_snapshot.md

Defaults to writing under `docs/` with UTC-date prefix, so snapshots
stack as history over time (the latest snapshot reflects today's
governance state; older ones preserve past state for audit).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from core.research.candidate_registry import CandidateRegistry


def _git_head_short() -> str:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
            text=True,
        ).strip()
        return out or "<no-git>"
    except Exception:
        return "<no-git>"


def _rel_to_root(p: Path) -> str:
    """Best-effort render of a path relative to the project root; falls
    back to absolute string if outside the tree (e.g. a fixture in /tmp)."""
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def _list_paper_runs(candidate_id: str) -> list[dict]:
    """Return [{run_dir, files: [name, ...]}, ...] for all paper runs
    of the given candidate, newest first."""
    base = ROOT / "data" / "paper_runs" / candidate_id
    if not base.exists():
        return []
    runs = []
    for run_dir in sorted(
        (d for d in base.iterdir() if d.is_dir()),
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    ):
        files = sorted(f.name for f in run_dir.iterdir() if f.is_file())
        runs.append({"run_dir": _rel_to_root(run_dir), "files": files})
    return runs


def _render(registry_db: Path) -> str:
    reg = CandidateRegistry(registry_db)
    records = reg.list_by_status()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    head = _git_head_short()

    lines = [
        "# Phase State Snapshot",
        "",
        f"**Generated**: {now}",
        f"**Git HEAD**: `{head}`",
        f"**Registry DB**: `{_rel_to_root(registry_db)}` "
        f"(total rows: **{reg.count()}**)",
        "",
        "This is a read-only, git-committable snapshot of the research",
        "candidate registry and paper-run artifacts. The underlying",
        "SQLite DB and paper-run CSV/JSON files are gitignored; this",
        "markdown is the repo-level audit surface.",
        "",
        "Regenerate with:",
        "",
        "```bash",
        "python dev/scripts/export/dump_phase_state_snapshot.py \\",
        "    --out docs/$(date -u +%Y%m%d)-phase_state_snapshot.md",
        "```",
        "",
        "---",
        "",
        "## Registry records",
        "",
    ]

    if not records:
        lines.append("_(registry is empty)_")
    else:
        for rec in records:
            lines.append(f"### `{rec.candidate_id}`")
            lines.append("")
            lines.append("| Field | Value |")
            lines.append("|-------|-------|")
            lines.append(f"| status | **{rec.status.value}** |")
            lines.append(f"| source_trial_id | `{rec.source_trial_id}` |")
            lines.append(
                f"| source_lineage_tag | `{rec.source_lineage_tag}` |"
            )
            lines.append(
                f"| frozen_spec_path | `{rec.frozen_spec_path or ''}` |"
            )
            lines.append(
                f"| decision_memo_path | `{rec.decision_memo_path or ''}` |"
            )
            lines.append(f"| created_at | {rec.created_at} |")
            lines.append(f"| promoted_at | {rec.promoted_at or ''} |")
            lines.append(f"| updated_at | {rec.updated_at} |")
            if rec.revoked_at or rec.revoke_reason:
                lines.append(f"| revoked_at | {rec.revoked_at or ''} |")
                lines.append(
                    f"| revoke_reason | {rec.revoke_reason or ''} |"
                )
                lines.append(
                    f"| revoke_memo_path | "
                    f"`{rec.revoke_memo_path or ''}` |"
                )
            lines.append("")

            runs = _list_paper_runs(rec.candidate_id)
            if runs:
                lines.append(f"**Paper runs** ({len(runs)}):")
                lines.append("")
                for r in runs:
                    lines.append(f"- `{r['run_dir']}/`")
                    for fname in r["files"]:
                        lines.append(f"    - `{fname}`")
                lines.append("")
            else:
                lines.append(
                    "_(no paper runs under "
                    f"`data/paper_runs/{rec.candidate_id}/`)_"
                )
                lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Notes on scope")
    lines.append("")
    lines.append(
        "- This snapshot lists **registry rows only** — it does not"
    )
    lines.append(
        "  reproduce the contents of frozen spec YAMLs or decision"
    )
    lines.append(
        "  memos. Those files are already committed under their listed"
    )
    lines.append(
        "  paths and serve as their own audit surface."
    )
    lines.append(
        "- Paper-run file listings are file names only (not content)."
    )
    lines.append(
        "  Content sampling should use `scripts/paper_drift_report.py`."
    )
    lines.append(
        "- A snapshot becomes stale as soon as the registry changes."
    )
    lines.append(
        "  Re-run the script whenever governance state changes."
    )
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Dump a git-committable phase-state snapshot "
            "(registry + paper runs)"
        ),
    )
    parser.add_argument(
        "--registry-db",
        default=str(ROOT / "data" / "research_candidates" / "registry.db"),
        help="Path to candidate registry DB",
    )
    parser.add_argument(
        "--out",
        default=None,
        help=(
            "Output markdown path. Default: "
            "docs/<UTC-YYYYMMDD>-phase_state_snapshot.md"
        ),
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Also print the rendered markdown to stdout",
    )
    args = parser.parse_args()

    registry_db = Path(args.registry_db)
    if not registry_db.exists():
        print(
            f"ERROR: registry DB not found at {registry_db}",
            file=sys.stderr,
        )
        return 1

    content = _render(registry_db)

    if args.out:
        out_path = Path(args.out)
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        out_path = ROOT / "docs" / f"{stamp}-phase_state_snapshot.md"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content)
    print(f"Snapshot written to {out_path}")
    if args.stdout:
        print()
        print(content)
    return 0


if __name__ == "__main__":
    sys.exit(main())
