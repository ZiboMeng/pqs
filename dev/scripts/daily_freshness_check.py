"""Daily-ritual freshness check. Fires on Claude Code SessionStart.

Prints a reminder if today's options VRP scan or per-candidate forward
observation hasn't run yet for the most-recent NYSE trading day.
Silent when everything is fresh.

Target date logic:
- Mon-Fri, before ~13:30 PT (NYSE 16:30 ET): target = previous trading day
  (today's data not yet available, so "expected" is yesterday).
- Mon-Fri, after ~13:30 PT: target = today.
- Sat/Sun: target = last Friday.

Holidays not modeled (rough proxy = NYSE weekday calendar). False
positives on holidays = harmless reminder.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

PROJ = Path(__file__).resolve().parents[2]
# Active forward candidates as of 2026-05-14 (post comprehensive audit).
# Terminal candidates (rcm_v1_defensive_composite_01 aborted 2026-04-30,
# candidate_2_orthogonal_01 aborted 2026-04-30, trial9_diversifier_001
# completed_fail 2026-05-12) removed. PEAD evidence-only candidate uses
# its own observe path (dev/scripts/pead/observe_pead_evidence.py) and
# is checked separately in _check_pead_evidence below.
CANDIDATES = (
    "trial9_diversifier_002",
)
NYSE_CLOSE_PT_HOUR = 13  # 13:30 PT ≈ 16:30 ET; round down for safety


def _last_trading_weekday(d: datetime) -> datetime:
    while d.weekday() >= 5:  # 5=Sat 6=Sun
        d -= timedelta(days=1)
    return d


def _target_date() -> str:
    now = datetime.now()
    if now.weekday() >= 5:
        return _last_trading_weekday(now).strftime("%Y-%m-%d")
    if now.hour < NYSE_CLOSE_PT_HOUR:
        return _last_trading_weekday(now - timedelta(days=1)).strftime("%Y-%m-%d")
    return now.strftime("%Y-%m-%d")


def _check_options(target: str) -> str | None:
    msgs: list[str] = []

    # VRP scan history
    p = PROJ / "data" / "options" / "analysis" / "vrp_history.parquet"
    if not p.exists():
        msgs.append(
            "📉 options VRP scan: no parquet yet\n"
            "   bootstrap: /home/zibo/miniconda3/envs/pqs/bin/python "
            "dev/scripts/options/cumulative_vrp_scan.py --bootstrap")
    else:
        df = pd.read_parquet(p)
        last = str(df["snapshot_date"].max())
        if last < target:
            msgs.append(
                f"📉 options VRP scan stale: last={last}, target={target}\n"
                f"   /home/zibo/miniconda3/envs/pqs/bin/python "
                f"dev/scripts/options/cumulative_vrp_scan.py")

    # Paper-run manifests
    paper_dir = PROJ / "data" / "options" / "paper_runs"
    if paper_dir.exists():
        for run_dir in sorted(paper_dir.iterdir()):
            mf = run_dir / "manifest.json"
            if not mf.exists():
                continue
            d = json.loads(mf.read_text())
            last = d.get("last_observe_date")
            if last is None or str(last) < target:
                msgs.append(
                    f"📊 options paper run stale: {run_dir.name} "
                    f"last={last or 'never'}, target={target}\n"
                    f"   /home/zibo/miniconda3/envs/pqs/bin/python "
                    f"dev/scripts/options/observe_options_forward.py "
                    f"--candidate-id {run_dir.name}")

    return "\n".join(msgs) if msgs else None


def _check_forward(target: str) -> str | None:
    # Terminal statuses absorb observe() per v2.1/PRD-F evidence contract
    # (see core/research/forward/runner.py); not actionable, exclude from
    # nag list. ``requires_data_review`` is also halt-class but recoverable
    # via ``recover`` CLI under PRD 20260505 — keep it on the nag list so
    # the operator sees it.
    TERMINAL = {"aborted", "decided", "promoted", "rejected"}
    stale_lines: list[str] = []
    stale_cids: list[str] = []
    for cid in CANDIDATES:
        m = PROJ / "data" / "research_candidates" / f"{cid}_forward_manifest.json"
        if not m.exists():
            stale_lines.append(f"   {cid}: manifest missing")
            stale_cids.append(cid)
            continue
        d = json.loads(m.read_text())
        status = d.get("current_status")
        if status in TERMINAL:
            continue
        runs = d.get("runs", [])
        last = runs[-1].get("as_of_date") if runs else None
        if last is None or str(last) < target:
            stale_lines.append(f"   {cid}: last={last or 'never'} (status={status})")
            stale_cids.append(cid)
    if not stale_lines:
        return None
    body = "\n".join(stale_lines)
    cmds = ("\n".join(
        f"   /home/zibo/miniconda3/envs/pqs/bin/python "
        f"dev/scripts/oos_mvp/run_forward_observe.py observe --candidate-id {cid}"
        for cid in stale_cids))
    return ("🔬 forward observe stale (target: " + target + ")\n"
            + body
            + "\n   1) /home/zibo/miniconda3/envs/pqs/bin/python "
              "scripts/fetch_data.py  (NYSE close+15min)\n"
              "   2) per stale candidate:\n"
            + cmds)


def _check_pead_evidence(target: str) -> str | None:
    """PEAD evidence-only candidate uses a standalone observe path."""
    m = PROJ / "data/research_candidates/pead_sue_trial1_evidence_v1_forward_manifest.json"
    if not m.exists():
        return None
    d = json.loads(m.read_text())
    status = d.get("current_status")
    TERMINAL = {"aborted", "decided", "promoted", "rejected", "completed_pass",
                "completed_fail", "requires_data_review"}
    if status in TERMINAL:
        return None
    tds = d.get("td_observations", [])
    if not tds:
        return None
    # Look for forward_observation phase TDs (skip TD000 initial_baseline)
    fwd_tds = [t for t in tds if t.get("td_phase") == "forward_observation"]
    last_obs = fwd_tds[-1].get("observation_date") if fwd_tds else None
    start_date = d.get("start_date")
    if last_obs is None and (start_date is None or str(start_date) <= target):
        return ("🔬 PEAD evidence-only candidate stale (target: " + target + ")\n"
                f"   pead_sue_trial1_evidence_v1: TD000 baseline only, "
                f"no forward TDs yet (start={start_date})\n"
                f"   1) /home/zibo/miniconda3/envs/pqs/bin/python scripts/fetch_data.py\n"
                f"   2) /home/zibo/miniconda3/envs/pqs/bin/python "
                f"dev/scripts/pead/observe_pead_evidence.py")
    if last_obs is not None and str(last_obs) < target:
        return ("🔬 PEAD evidence-only candidate stale (target: " + target + ")\n"
                f"   pead_sue_trial1_evidence_v1: last={last_obs}\n"
                f"   1) /home/zibo/miniconda3/envs/pqs/bin/python scripts/fetch_data.py\n"
                f"   2) /home/zibo/miniconda3/envs/pqs/bin/python "
                f"dev/scripts/pead/observe_pead_evidence.py")
    return None


def main() -> int:
    target = _target_date()
    msgs = [m for m in (_check_options(target), _check_forward(target),
                        _check_pead_evidence(target)) if m]
    if not msgs:
        return 0
    print("=" * 60)
    print(f"PQS daily ritual — pending (target trading day: {target})")
    print("=" * 60)
    for m in msgs:
        print(m)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
