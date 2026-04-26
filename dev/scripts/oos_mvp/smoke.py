#!/usr/bin/env python
"""OOS MVP integration smoke (PRD §3 R6).

End-to-end consistency check across the artifacts produced by R1-R5
plus a negative-result simulation that exercises the R5 schema's hard
``evidence_class == forward_oos`` contract.

For each candidate, verify:
  1. ``<id>_robustness_window.yaml`` parses as CandidateRobustnessWindow
  2. evidence_class is exactly ``pseudo_oos_robustness`` (NOT
     forward_oos, NOT historical_replay)
  3. ``<id>_robustness_eval.{json,md}`` exist
  4. ``<id>_concentration_report.json`` has ``per_symbol_watch_shares``
     + ``concentration_gate_status`` + ``narrative_permission``
  5. watch_exposure markdown section renders non-empty

Negative simulation (PRD §3 R6 explicit):
  6. Build a forward_run_manifest payload with
     ``evidence_class=historical_replay`` and
     ``evidence_class=pseudo_oos_robustness`` — both must be rejected
     by ``ForwardRunManifest.model_validate``.

This script does NOT mutate any artifact and does NOT re-run
BacktestEngine. It's a parser/contract verification only.

Usage:
    python dev/scripts/oos_mvp/smoke.py
    python dev/scripts/oos_mvp/smoke.py --candidate-id rcm_v1_defensive_composite_01
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from core.research.concentration import render_watch_exposure_section  # noqa: E402
from core.research.forward import ForwardRunManifest  # noqa: E402
from core.research.robustness.window_spec import (  # noqa: E402
    CandidateRobustnessWindow,
    EvidenceClass,
)


DEFAULT_CANDIDATES = [
    "rcm_v1_defensive_composite_01",
    "candidate_2_orthogonal_01",
]
DEFAULT_CANDIDATES_DIR = Path("data/research_candidates")
DEFAULT_WATCH_PARQUET = Path("data/ref/data_quality_watch.parquet")


@dataclass
class CandidateSmokeResult:
    candidate_id: str
    window_yaml_ok: bool = False
    evidence_class_ok: bool = False
    robustness_artifacts_ok: bool = False
    concentration_artifacts_ok: bool = False
    watch_exposure_renders: bool = False
    errors: list = field(default_factory=list)

    @property
    def all_ok(self) -> bool:
        return (
            self.window_yaml_ok
            and self.evidence_class_ok
            and self.robustness_artifacts_ok
            and self.concentration_artifacts_ok
            and self.watch_exposure_renders
        )


@dataclass
class NegativeSimResult:
    historical_replay_rejected: bool = False
    pseudo_oos_rejected: bool = False
    errors: list = field(default_factory=list)

    @property
    def all_ok(self) -> bool:
        return self.historical_replay_rejected and self.pseudo_oos_rejected


@dataclass
class SmokeResult:
    candidates: list = field(default_factory=list)
    negative_sim: NegativeSimResult = field(default_factory=NegativeSimResult)

    @property
    def all_ok(self) -> bool:
        return all(c.all_ok for c in self.candidates) and self.negative_sim.all_ok


def _smoke_one_candidate(
    candidate_id: str,
    *,
    candidates_dir: Path,
    watch_parquet: Path,
) -> CandidateSmokeResult:
    res = CandidateSmokeResult(candidate_id=candidate_id)

    # 1. window yaml parses
    win_path = candidates_dir / f"{candidate_id}_robustness_window.yaml"
    try:
        payload = yaml.safe_load(win_path.read_text())
        window = CandidateRobustnessWindow.model_validate(payload)
        res.window_yaml_ok = True
    except (FileNotFoundError, yaml.YAMLError, ValidationError, OSError) as exc:
        res.errors.append(f"window_yaml parse: {type(exc).__name__}: {exc}")
        return res  # bail early; downstream checks need window

    # 2. evidence_class is pseudo_oos_robustness
    if window.evidence_class is EvidenceClass.pseudo_oos_robustness:
        res.evidence_class_ok = True
    else:
        res.errors.append(
            f"evidence_class={window.evidence_class.value!r}, "
            f"expected pseudo_oos_robustness"
        )

    # 3. robustness eval artifacts present
    eval_json = candidates_dir / f"{candidate_id}_robustness_eval.json"
    eval_md = candidates_dir / f"{candidate_id}_robustness_eval.md"
    if eval_json.exists() and eval_md.exists():
        res.robustness_artifacts_ok = True
    else:
        res.errors.append(
            f"robustness_eval artifacts missing: json={eval_json.exists()} "
            f"md={eval_md.exists()}"
        )

    # 4. concentration report json has required fields
    conc_json = candidates_dir / f"{candidate_id}_concentration_report.json"
    if not conc_json.exists():
        res.errors.append("concentration_report.json missing")
    else:
        try:
            conc = json.loads(conc_json.read_text())
            required = {
                "per_symbol_watch_shares",
                "concentration_gate_status",
                "narrative_permission",
                "watchlist_total_share",
                "thin_data_total_share",
            }
            missing = required - set(conc.keys())
            if missing:
                res.errors.append(f"concentration_report missing fields: {sorted(missing)}")
            else:
                res.concentration_artifacts_ok = True
        except (json.JSONDecodeError, OSError) as exc:
            res.errors.append(f"concentration_report parse: {exc}")

    # 5. watch_exposure section renders without crash + non-empty body
    try:
        lines = render_watch_exposure_section(
            candidate_id,
            watch_parquet=watch_parquet,
            candidates_dir=candidates_dir,
        )
        body = "\n".join(lines).strip()
        if body and "narrative_permission" in body:
            res.watch_exposure_renders = True
        else:
            res.errors.append(
                "watch_exposure section rendered but missing narrative_permission echo"
            )
    except Exception as exc:  # pragma: no cover — render is graceful by design
        res.errors.append(f"watch_exposure render crashed: {type(exc).__name__}: {exc}")

    return res


def _negative_simulation() -> NegativeSimResult:
    """Verify R5 schema rejects non-forward_oos evidence classes.

    PRD v3 §B + execution PRD §3 R6: deliberately try to construct a
    forward_run_manifest claiming pseudo_oos_robustness or historical_replay
    is forward OOS evidence. The R5 schema must reject both at construction.
    """
    res = NegativeSimResult()
    base = {
        "schema_version": "1.0",
        "candidate_id": "smoke_negative_test",
        "spec_hash": "abcdef012345",
        "start_date": "2026-04-25",
        "benchmark": "SPY",
        "secondary_benchmark": "QQQ",
        "cost_assumptions": {
            "source": "config/cost_model.yaml",
            "config_hash": "cafebabe1234deadbeef",
        },
        "checkpoint_cadence": {"weekly": True, "decision_days": [10, 20, 40, 60]},
        "current_status": "not_started",
        "data_integrity_snapshot": {
            "daily_store_rebuild_commit": "abcdef012345",
            "baseline_snapshot_path": "data/baseline/latest.json",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        },
        "runs": [],
    }

    for fake_class, attr in [
        ("historical_replay", "historical_replay_rejected"),
        ("pseudo_oos_robustness", "pseudo_oos_rejected"),
    ]:
        payload = {**base, "evidence_class": fake_class}
        try:
            ForwardRunManifest.model_validate(payload)
            res.errors.append(
                f"NEGATIVE SIM FAILED: schema accepted evidence_class={fake_class!r} "
                f"as forward OOS (should have raised ValidationError)"
            )
        except ValidationError as exc:
            if "forward_oos" in str(exc):
                setattr(res, attr, True)
            else:
                res.errors.append(
                    f"schema rejected {fake_class!r} but message lacks 'forward_oos': {exc}"
                )

    return res


def run_smoke(
    candidate_ids: Optional[list] = None,
    *,
    candidates_dir: Path = DEFAULT_CANDIDATES_DIR,
    watch_parquet: Path = DEFAULT_WATCH_PARQUET,
) -> SmokeResult:
    """Run the OOS MVP integration smoke.

    Returns a SmokeResult with per-candidate + negative-simulation status.
    Caller checks ``result.all_ok`` to decide pass/fail.
    """
    cids = candidate_ids or DEFAULT_CANDIDATES
    out = SmokeResult()
    for cid in cids:
        out.candidates.append(
            _smoke_one_candidate(
                cid, candidates_dir=candidates_dir, watch_parquet=watch_parquet,
            )
        )
    out.negative_sim = _negative_simulation()
    return out


def _format_result(result: SmokeResult) -> str:
    lines = ["[oos-mvp smoke]"]
    for c in result.candidates:
        marker = "✓" if c.all_ok else "✗"
        lines.append(
            f"  {marker} {c.candidate_id}: "
            f"window={c.window_yaml_ok} class={c.evidence_class_ok} "
            f"robustness={c.robustness_artifacts_ok} "
            f"concentration={c.concentration_artifacts_ok} "
            f"watch_exposure={c.watch_exposure_renders}"
        )
        for err in c.errors:
            lines.append(f"      ! {err}")
    ns = result.negative_sim
    marker = "✓" if ns.all_ok else "✗"
    lines.append(
        f"  {marker} negative_sim: historical_replay={ns.historical_replay_rejected} "
        f"pseudo_oos={ns.pseudo_oos_rejected}"
    )
    for err in ns.errors:
        lines.append(f"      ! {err}")
    lines.append(
        f"\noverall: {'PASS' if result.all_ok else 'FAIL'}"
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="OOS MVP integration smoke (R6)")
    parser.add_argument("--candidate-id", action="append", default=None)
    parser.add_argument("--candidates-dir", type=Path, default=DEFAULT_CANDIDATES_DIR)
    parser.add_argument("--watch-parquet", type=Path, default=DEFAULT_WATCH_PARQUET)
    args = parser.parse_args()

    result = run_smoke(
        candidate_ids=args.candidate_id,
        candidates_dir=args.candidates_dir,
        watch_parquet=args.watch_parquet,
    )
    print(_format_result(result))
    return 0 if result.all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
