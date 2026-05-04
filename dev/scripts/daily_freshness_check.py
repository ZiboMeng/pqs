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
CANDIDATES = (
    "rcm_v1_defensive_composite_01",
    "candidate_2_orthogonal_01",
    "trial9_diversifier_001",
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
    p = PROJ / "data" / "options" / "analysis" / "vrp_history.parquet"
    if not p.exists():
        return ("📉 options VRP scan: no parquet yet\n"
                "   bootstrap: /home/zibo/miniconda3/envs/pqs/bin/python "
                "dev/scripts/options/cumulative_vrp_scan.py --bootstrap")
    df = pd.read_parquet(p)
    last = str(df["snapshot_date"].max())
    if last >= target:
        return None
    return (f"📉 options VRP scan stale: last={last}, target={target}\n"
            f"   /home/zibo/miniconda3/envs/pqs/bin/python "
            f"dev/scripts/options/cumulative_vrp_scan.py")


def _check_forward(target: str) -> str | None:
    stale: list[str] = []
    for cid in CANDIDATES:
        m = PROJ / "data" / "research_candidates" / f"{cid}_forward_manifest.json"
        if not m.exists():
            stale.append(f"   {cid}: manifest missing")
            continue
        d = json.loads(m.read_text())
        runs = d.get("runs", [])
        last = runs[-1].get("as_of_date") if runs else None
        if last is None or str(last) < target:
            stale.append(f"   {cid}: last={last or 'never'}")
    if not stale:
        return None
    body = "\n".join(stale)
    cmds = ("\n".join(
        f"   /home/zibo/miniconda3/envs/pqs/bin/python "
        f"dev/scripts/oos_mvp/run_forward_observe.py observe --candidate-id {cid}"
        for cid in CANDIDATES))
    return ("🔬 forward observe stale (target: " + target + ")\n"
            + body
            + "\n   1) /home/zibo/miniconda3/envs/pqs/bin/python "
              "scripts/fetch_data.py  (NYSE close+15min)\n"
              "   2) per candidate:\n"
            + cmds)


def main() -> int:
    target = _target_date()
    msgs = [m for m in (_check_options(target), _check_forward(target)) if m]
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
