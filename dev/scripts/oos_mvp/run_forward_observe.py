#!/usr/bin/env python
"""CLI for the forward OOS runner (R-fwd-1 minimum closed loop).

Sub-commands:

  init     create a forward_run_manifest.json for a candidate
  status   read-only summary of a candidate's manifest
  observe  multi-day catch-up; append-only ForwardRun entries
  decide   user-driven status mutation (completed_success /
           completed_fail / aborted)

PRD: docs/prd/20260426-forward_oos_runner_prd.md
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from core.research.forward import (  # noqa: E402
    ForwardHaltError,
    ForwardRunStatus,
    check_readiness,
    decide,
    init,
    observe,
    recover,
    status,
)


def _cmd_init(args: argparse.Namespace) -> int:
    manifest = init(
        candidate_id=args.candidate_id,
        start_date=args.start_date,
        benchmark=args.benchmark,
        secondary_benchmark=args.secondary_benchmark,
        decision_days=args.decision_days,
        weekly=not args.no_weekly,
        cost_model_path=args.cost_model_path,
        config_dir=Path(args.config_dir),
        overwrite=args.overwrite,
    )
    print(f"[forward] init OK for {args.candidate_id}")
    print(f"  start_date: {manifest.start_date.isoformat()}")
    print(f"  spec_hash:  {manifest.spec_hash[:16]}...")
    print(f"  cost_hash:  {manifest.cost_assumptions.config_hash[:16]}...")
    print(f"  cadence:    weekly={manifest.checkpoint_cadence.weekly} "
          f"decision_days={list(manifest.checkpoint_cadence.decision_days)}")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    payload = status(args.candidate_id)
    print(json.dumps(payload, indent=2, default=str))
    return 0


def _cmd_observe(args: argparse.Namespace) -> int:
    try:
        appended = observe(
            candidate_id=args.candidate_id,
            up_to=args.up_to,
            cost_model_path=args.cost_model_path,
            top_n=args.top_n,
            dry_run=args.dry_run,
            config_dir=Path(args.config_dir),
        )
    except ForwardHaltError as exc:
        print(f"[forward] HALT: {exc}", file=sys.stderr)
        return 3
    if not appended:
        print(f"[forward] observe: no new bars for {args.candidate_id} "
              f"(idempotent no-op)")
        return 0
    print(f"[forward] observe: appended {len(appended)} entries"
          f"{' (DRY-RUN — not saved)' if args.dry_run else ''}")
    for r in appended[-5:]:
        print(f"  {r.checkpoint_label} {r.as_of_date.isoformat()} "
              f"cum_ret={(r.cum_ret or 0)*100:+.2f}% "
              f"vs_spy={(r.vs_spy or 0)*100:+.2f}% "
              f"vs_qqq={(r.vs_qqq or 0)*100:+.2f}% "
              f"max_dd={(r.max_dd or 0)*100:+.2f}%")
    return 0


def _cmd_readiness(args: argparse.Namespace) -> int:
    report = check_readiness(args.candidate_id)
    print(json.dumps(report.to_dict(), indent=2, default=str))
    return 0


def _cmd_decide(args: argparse.Namespace) -> int:
    new_status = ForwardRunStatus(args.status)
    decide(
        candidate_id=args.candidate_id,
        new_status=new_status,
        notes=args.notes,
    )
    print(f"[forward] decide: {args.candidate_id} -> {new_status.value}")
    return 0


def _cmd_recover(args: argparse.Namespace) -> int:
    try:
        ev = recover(
            candidate_id=args.candidate_id,
            cost_model_path=args.cost_model_path,
            operator_note=args.operator_note,
            dry_run=args.dry_run,
            config_dir=Path(args.config_dir),
        )
    except ForwardHaltError as exc:
        print(f"[forward] HALT: {exc}", file=sys.stderr)
        return 3
    print(
        f"[forward] recover: {args.candidate_id} -> in_progress"
        f"{' (DRY-RUN — not saved)' if args.dry_run else ''}"
    )
    print(f"  recovered_run_label: {ev.recovered_run_label}")
    print(f"  prior_triggers:      {ev.prior_triggers}")
    print(f"  new_triggers:        {ev.new_triggers}")
    print(f"  prd_reference:       {ev.prd_reference}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Forward OOS runner CLI (R-fwd-1)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="Create a forward manifest")
    p_init.add_argument("--candidate-id", required=True)
    p_init.add_argument(
        "--start-date", default=None,
        help="ISO date; defaults to candidate's promoted_at + 1 day",
    )
    p_init.add_argument("--benchmark", default="SPY")
    p_init.add_argument("--secondary-benchmark", default="QQQ")
    p_init.add_argument(
        "--decision-days", type=lambda s: [int(x) for x in s.split(",")],
        default=None,
        help="Comma-separated TDs (e.g. 10,20,40,60). Default: 10,20,40,60",
    )
    p_init.add_argument("--no-weekly", action="store_true")
    p_init.add_argument("--cost-model-path", default="config/cost_model.yaml")
    p_init.add_argument(
        "--config-dir", default="config",
        help=(
            "Root config dir for ConfigSnapshot pinning (PRD F). "
            "Default: config/. Override for hermetic tests or alternative "
            "deployments — must match the dir observe() will be invoked with."
        ),
    )
    p_init.add_argument(
        "--overwrite", action="store_true",
        help="Replace an existing manifest (drops its runs[])",
    )
    p_init.set_defaults(func=_cmd_init)

    p_status = sub.add_parser("status", help="Print manifest summary")
    p_status.add_argument("--candidate-id", required=True)
    p_status.set_defaults(func=_cmd_status)

    p_ready = sub.add_parser(
        "readiness",
        help="Forward data readiness / freshness guard (read-only)",
    )
    p_ready.add_argument("--candidate-id", required=True)
    p_ready.set_defaults(func=_cmd_readiness)

    p_observe = sub.add_parser("observe", help="Append-only multi-day catch-up")
    p_observe.add_argument("--candidate-id", required=True)
    p_observe.add_argument("--up-to", default=None, help="ISO date upper bound")
    p_observe.add_argument("--cost-model-path", default="config/cost_model.yaml")
    p_observe.add_argument(
        "--config-dir", default="config",
        help=(
            "Root config dir used by F-PRD revalidate (drift detection). "
            "Default: config/. MUST match the value used at init time so the "
            "snapshot pinned in the manifest is comparable against the same "
            "tree on every observe."
        ),
    )
    p_observe.add_argument("--top-n", type=int, default=10)
    p_observe.add_argument("--dry-run", action="store_true")
    p_observe.set_defaults(func=_cmd_observe)

    p_decide = sub.add_parser("decide", help="User-driven status mutation")
    p_decide.add_argument("--candidate-id", required=True)
    p_decide.add_argument(
        "--status",
        choices=[
            ForwardRunStatus.completed_success.value,
            ForwardRunStatus.completed_fail.value,
            ForwardRunStatus.aborted.value,
        ],
        required=True,
    )
    p_decide.add_argument("--notes", default=None)
    p_decide.set_defaults(func=_cmd_decide)

    p_recover = sub.add_parser(
        "recover",
        help=(
            "Re-evaluate a requires_data_review manifest under current "
            "policy; flip status back to in_progress if the same drift "
            "no longer escalates to invalidated. PRD: "
            "docs/prd/20260505-revalidate_e4_near_zero_cum_ret_exemption_prd.md"
        ),
    )
    p_recover.add_argument("--candidate-id", required=True)
    p_recover.add_argument("--cost-model-path", default="config/cost_model.yaml")
    p_recover.add_argument(
        "--config-dir", default="config",
        help=(
            "Root config dir for revalidate's drift detection. Default: "
            "config/. MUST match the value used at observe() time."
        ),
    )
    p_recover.add_argument(
        "--operator-note", default=None,
        help="Freeform audit note recorded on the PolicyRecoveryEvent",
    )
    p_recover.add_argument("--dry-run", action="store_true")
    p_recover.set_defaults(func=_cmd_recover)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
