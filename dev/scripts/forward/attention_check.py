"""Forward attention check CLI — TD20/TD40/TD60 milestone diagnostics.

Phase C-PRD-1 follow-up. Reads a candidate's forward manifest + N anchor
manifests, computes derived metrics (residual corr, combo NAV, rolling
maxdd, non-equity exposure), classifies TD60 verdict (PRD §7.1) when
n_observed >= 60.

Default targets:
  - candidate: trial9_diversifier_001
  - anchors:   rcm_v1_defensive_composite_01, candidate_2_orthogonal_01

Output:
  - JSON report at data/ml/forward_attention/<candidate_id>_<TDxxx>_<UTC>.json
  - Stdout markdown summary

Idempotent: re-running with same TD label produces same numbers (modulo
generated_at_utc + benchmark price drift if BarStore was updated between runs).

Usage:
    python dev/scripts/forward/attention_check.py
    python dev/scripts/forward/attention_check.py --candidate trial9_diversifier_001
    python dev/scripts/forward/attention_check.py --output-dir /tmp/foo
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJ))

from core.research.forward import runner
from core.research.forward.attention_report import (
    AttentionReport,
    generate_attention_report,
)

DEFAULT_CANDIDATE = "trial9_diversifier_001"
DEFAULT_ANCHORS = [
    "rcm_v1_defensive_composite_01",
    "candidate_2_orthogonal_01",
]


def _load_manifest(candidate_id: str):
    output_dir = runner.DEFAULT_OUTPUT_DIR
    mp = runner.manifest_path(candidate_id, output_dir)
    if not mp.exists():
        raise FileNotFoundError(f"forward manifest not found: {mp}")
    return runner.load_manifest(mp)


def _format_markdown(report: AttentionReport) -> str:
    """Compact markdown summary for stdout."""
    lines = [
        f"# Forward attention — {report.candidate_id} @ {report.td_label}",
        "",
        f"- Generated: {report.generated_at_utc}",
        f"- n_observed: {report.n_observed}",
        f"- anchors: {report.anchor_ids}",
        "",
    ]

    if report.candidate_metrics:
        m = report.candidate_metrics
        lines.append("## Candidate metrics")
        lines.append(f"- as_of: {m.get('as_of_date')}")
        lines.append(f"- cum_ret: {m.get('cum_ret'):+.4f}" if m.get('cum_ret') is not None else "- cum_ret: —")
        lines.append(f"- sharpe:  {m.get('sharpe'):+.4f}" if m.get('sharpe') is not None else "- sharpe: —")
        lines.append(f"- max_dd:  {m.get('max_dd'):+.4f}" if m.get('max_dd') is not None else "- max_dd: —")
        lines.append(f"- vs_spy:  {m.get('vs_spy'):+.4f}" if m.get('vs_spy') is not None else "- vs_spy: —")
        lines.append(f"- vs_qqq:  {m.get('vs_qqq'):+.4f}" if m.get('vs_qqq') is not None else "- vs_qqq: —")
        rolling = m.get('rolling_60d_max_dd_min')
        if rolling is not None:
            lines.append(f"- rolling_60d_max_dd_min: {rolling:+.4f}")
        else:
            lines.append("- rolling_60d_max_dd_min: — (need ≥60 TDs)")
        lines.append("")

    if report.residual_corrs:
        lines.append("## Residual NAV correlation (after stripping benchmark beta)")
        for aid, corr in report.residual_corrs.items():
            if corr is None:
                lines.append(f"- vs {aid}: — (insufficient data)")
            else:
                tier = (
                    "true_diversifier" if corr < 0.50
                    else "partial_diversifier" if corr < 0.70
                    else "warn_label_void" if corr < 0.85
                    else "REJECT"
                )
                lines.append(f"- vs {aid}: {corr:+.4f} → {tier}")
        lines.append("")

    if report.non_equity_exposure:
        ne = report.non_equity_exposure
        lines.append("## Non-equity exposure (latest day)")
        lines.append(f"- as_of: {ne['as_of_date']}")
        lines.append(f"- equity:        {ne['equity_weight']:.3f}")
        lines.append(f"- bond:          {ne['bond_weight']:.3f}")
        lines.append(f"- commodity:     {ne['commodity_weight']:.3f}")
        lines.append(f"- cash_anchor:   {ne['cash_anchor_weight']:.3f}")
        lines.append(f"- non_equity:    {ne['non_equity_weight']:.3f} (avg over period: {ne['non_equity_weight_avg']:.3f})")
        if ne['unknown_weight'] > 1e-6:
            lines.append(f"- ⚠️  unknown:    {ne['unknown_weight']:.3f}")
        lines.append("")

    if report.combo_metrics:
        c = report.combo_metrics
        lines.append("## Portfolio combo (candidate + anchors)")
        weights_str = " / ".join(f"{cid}={w:.3f}" for cid, w in c.get("weights", {}).items())
        lines.append(f"- weights: {weights_str}")
        lines.append(f"- n_observed: {c['n_observed']}")
        lines.append(f"- cum_ret_latest: {c['cum_ret_latest']:+.4f}")
        lines.append(f"- max_dd_latest:  {c['max_dd_latest']:+.4f}")
        lines.append("")

    if report.soft_warn_status:
        lines.append("## Soft-warn status")
        for flag, status in report.soft_warn_status.items():
            symbol = {
                "cleared": "✅",
                "active_uncleared": "❌",
                "pending_insufficient_data": "⏳",
                "active_unknown_clear_rule": "❓",
            }.get(status, "?")
            lines.append(f"- {symbol} {flag}: {status}")
        lines.append("")

    if report.td60_verdict:
        v = report.td60_verdict
        emoji = {
            "GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴", "INSUFFICIENT": "⏳",
        }.get(v["label"], "?")
        lines.append(f"## TD60 verdict: {emoji} {v['label']}")
        for reason in v["reasons"]:
            lines.append(f"- {reason}")
        lines.append("")

    if report.notes:
        lines.append("## Notes")
        for n in report.notes:
            lines.append(f"- {n}")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidate", default=DEFAULT_CANDIDATE,
                    help=f"target candidate id (default: {DEFAULT_CANDIDATE})")
    ap.add_argument("--anchors", nargs="*", default=DEFAULT_ANCHORS,
                    help=f"anchor candidate ids (default: {DEFAULT_ANCHORS})")
    ap.add_argument("--td-label", default=None,
                    help="override TD label; default = derived from manifest")
    ap.add_argument("--benchmark", default="QQQ", choices=["QQQ", "SPY"],
                    help="benchmark for residual regression (default: QQQ)")
    ap.add_argument("--output-dir", default=str(PROJ / "data" / "ml" / "forward_attention"),
                    help="JSON output directory")
    ap.add_argument("--no-json", action="store_true",
                    help="skip JSON write; stdout markdown only")
    ap.add_argument("--quiet", action="store_true",
                    help="suppress markdown stdout (JSON still written)")
    args = ap.parse_args()

    cand_manifest = _load_manifest(args.candidate)
    anchor_manifests = {aid: _load_manifest(aid) for aid in args.anchors}

    report = generate_attention_report(
        candidate_manifest=cand_manifest,
        anchor_manifests=anchor_manifests,
        td_label=args.td_label,
        benchmark_symbol=args.benchmark,
    )

    if not args.no_json:
        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        from datetime import datetime, timezone
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = out_dir / f"{args.candidate}_{report.td_label}_{stamp}.json"
        with out_path.open("w") as f:
            json.dump(report.to_dict(), f, indent=2, default=str)
        if not args.quiet:
            print(f"[attention] wrote {out_path}")

    if not args.quiet:
        print(_format_markdown(report))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
