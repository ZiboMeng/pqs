#!/usr/bin/env python3
"""Execute the preregistered Mining V5 campaign (5 candidates or 30 rounds)."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.backtest.backtest_engine import BacktestEngine  # noqa: E402
from core.config.schemas.cost_model import CostModelConfig, CostTierConfig  # noqa: E402
from core.execution.cost_model import CostModel  # noqa: E402
from core.research.mining_v4_portfolio import expand_decision_signals  # noqa: E402
from core.research.mining_v5_campaign import (  # noqa: E402
    build_track_a_targets,
    load_v5_campaign,
)
from core.research.qualification_v2 import (  # noqa: E402
    canonical_sha256,
    sha256_file,
)
from core.research.qualification_v4 import (  # noqa: E402
    build_qualification_artifact,
    validate_qualification_artifact,
)
from core.research.trial_ledger import AppendOnlyTrialLedger, TrialIntent  # noqa: E402

COST_NAMES = {
    30.0: "base_30bps",
    60.0: "double_60bps",
    90.0: "triple_90bps",
}
TRACK_A_CONSTRUCTIONS = {
    "spy80_bil20_negative_control": "static_80_20",
    "spy_vol_only": "spy_vol_only",
    "spy_trend_only": "spy_trend_only",
    "spy_vol_trend": "spy_vol_trend",
    "spy70_qmlv30": "qmlv_no_overlay",
    "spy70_qmlv30_risk": "qmlv_risk",
    "spy70_qm30_risk": "qm_risk",
    "spy70_qlv30_risk": "qlv_risk",
    "spy70_mlv30_risk": "mlv_risk",
    "spy60_qmlv40_risk": "qmlv_60_40_risk",
    "qmlv_multidefense": "qmlv_multidefense",
}


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _sha(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _finite(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _finite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(item) for item in value]
    if isinstance(value, (float, np.floating)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _flat_cost_model(cost_bps: float) -> CostModel:
    return CostModel(CostModelConfig(tiers={
        "default": CostTierConfig(
            symbols=[],
            commission_bps=0.0,
            slippage_interday_bps=cost_bps,
            slippage_intraday_bps=cost_bps,
        )
    }))


def _load_panel(snapshot_root: Path, manifest: Mapping[str, Any]) -> dict[str, pd.DataFrame]:
    fields = ("open", "high", "low", "close", "cash_distribution", "total_return_close")
    by_symbol: dict[str, pd.DataFrame] = {}
    for symbol, reference in manifest["symbols"].items():
        path = ROOT / str(reference["daily_path"])
        if sha256_file(path) != reference["daily_sha256"]:
            raise RuntimeError(f"Track-A daily hash mismatch: {symbol}")
        frame = pd.read_parquet(path)
        frame.index = pd.DatetimeIndex(frame.index).tz_localize(None).normalize()
        by_symbol[str(symbol)] = frame
    common: pd.DatetimeIndex | None = None
    for frame in by_symbol.values():
        common = frame.index if common is None else common.intersection(frame.index)
    if common is None or len(common) < 756:
        raise RuntimeError("Track-A common calendar is too short")
    common = common.sort_values()
    return {
        field: pd.DataFrame({
            symbol: frame[field].reindex(common)
            for symbol, frame in by_symbol.items()
        })
        for field in fields
    }


def _run_candidate(
    targets: pd.DataFrame,
    panel: Mapping[str, pd.DataFrame],
    evaluation_index: pd.DatetimeIndex,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    signals = expand_decision_signals(targets, panel["close"].index)
    paths: dict[str, np.ndarray] = {}
    execution: dict[str, Any] = {}
    for cost, name in COST_NAMES.items():
        result = BacktestEngine(
            _flat_cost_model(cost),
            initial_capital=100_000.0,
            min_trade_usd=0.0,
            rebalance_threshold=0.0,
            integer_shares=False,
        ).run(
            signals,
            panel["close"],
            open_df=panel["open"],
            benchmark_series=panel["total_return_close"]["SPY"],
            rebalance_dates=targets.index,
            cash_distributions_df=panel["cash_distribution"],
        )
        returns = result.equity_curve.pct_change(fill_method=None).reindex(
            evaluation_index
        )
        if returns.isna().any() or not np.isfinite(returns.to_numpy()).all():
            raise RuntimeError(f"candidate {name} return path is incomplete")
        if not result.trades or not all(
            pd.Timestamp(fill.fill_date) > pd.Timestamp(fill.signal_date)
            for fill in result.trades
        ):
            raise RuntimeError("next-session execution evidence failed")
        paths[name] = returns.to_numpy(dtype=float)
        execution[name] = {
            "trades": result.n_trades,
            "commission_usd": result.total_commission_usd,
            "slippage_usd": result.total_slippage_usd,
            "cash_distributions_usd": result.metrics[
                "cash_distributions_usd"
            ],
            "minimum_cash": float(result.cash_curve.min()),
            "maximum_gross_weight": float(result.weights.sum(axis=1).max()),
        }
    return paths, execution


def _timing_evidence(
    construction: str,
    levels: pd.DataFrame,
    targets: pd.DataFrame,
) -> dict[str, bool]:
    first = targets.index[0]
    last = targets.index[-1]
    replay = build_track_a_targets(
        construction, levels, first_decision=first, last_decision=last
    )
    deterministic = replay.equals(targets)
    mutated = levels.copy()
    mutated.iloc[-1] *= 7.0
    prior_last = targets.index[-2] if len(targets) > 1 else targets.index[-1]
    mutation_replay = build_track_a_targets(
        construction, mutated, first_decision=first, last_decision=prior_last
    )
    prefix = targets.loc[:prior_last].equals(mutation_replay)
    return {
        "prefix_invariance_passed": prefix,
        "next_session_execution_passed": True,
        "deterministic_replay_passed": deterministic,
        "future_mutation_passed": prefix,
    }


def _intent(
    spec: Mapping[str, Any],
    *,
    commit: str,
    data_hash: str,
    prereg_hash: str,
) -> TrialIntent:
    return TrialIntent(
        trial_id=f"mining-v5-r{int(spec['round']):02d}-{spec['id']}",
        hypothesis_family=str(spec["family"]),
        mechanism_id=str(spec["mechanism"]),
        universe_hash=data_hash,
        data_hash=data_hash,
        config_hash=prereg_hash,
        code_commit=commit,
        feature_id=_sha(spec),
        model_id=str(spec["kind"]),
        label_id="after_cost_total_return_vs_canonical_costless_spy",
        construction_id=str(spec.get("construction", "none")),
        cost_id="candidate_30_60_90bps_vs_costless_spy",
        execution_id="month_end_close_to_next_session_open_exact_cash",
        seed=20260722,
        period_start="2015-01-02",
        period_end="2024-12-31",
        observed_through="2026-07-17",
    )


def _selection_score(computed: Mapping[str, Any]) -> tuple[float, float, float, float]:
    base = computed["balanced_drawdown"]["scenario_metrics"]["base_30bps"]
    episode_improvements = [
        abs(row["spy_max_drawdown"]) - abs(row["candidate_max_drawdown"])
        for row in base["material_episodes"]["episodes"]
    ]
    worst_episode = min(episode_improvements) if episode_improvements else -math.inf
    return (
        worst_episode,
        float(base["rolling_36m"]["drawdown_win_fraction"]),
        float(computed["triple_90bps_cagr_excess_diagnostic"]),
        -float(computed.get("annual_turnover_diagnostic", math.inf)),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preregistration",
        default="research/preregistrations/20260722-mining-v5-balanced-v1.yaml",
    )
    parser.add_argument(
        "--output-dir",
        default="research/results/mining_v5_balanced_20260722_v1",
    )
    parser.add_argument(
        "--corrective-replay",
        action="store_true",
        help=(
            "Reuse a complete failed ledger after a non-directional runner bug. "
            "Replay intents retain their original content hash and do not reset N."
        ),
    )
    args = parser.parse_args()
    prereg_path = (ROOT / args.preregistration).resolve()
    output = (ROOT / args.output_dir).resolve()
    if output.exists() and not args.corrective_replay:
        raise RuntimeError(f"campaign output is immutable: {output}")
    if args.corrective_replay and (output / "campaign_report.json").exists():
        raise RuntimeError("corrective replay cannot overwrite a completed report")
    if _git("status", "--porcelain", "--untracked-files=no"):
        raise RuntimeError("tracked worktree must be clean before V5 execution")
    _git("ls-files", "--error-unmatch", str(prereg_path.relative_to(ROOT)))
    commit = _git("rev-parse", "HEAD")
    campaign = load_v5_campaign(prereg_path, repo_root=ROOT)
    prereg_hash = sha256_file(prereg_path)
    data_ref = campaign["track_a_data"]
    snapshot_manifest_path = ROOT / data_ref["manifest_path"]
    if sha256_file(snapshot_manifest_path) != data_ref["manifest_sha256"]:
        raise RuntimeError("Track-A snapshot manifest hash mismatch")
    snapshot_manifest = json.loads(snapshot_manifest_path.read_text(encoding="utf-8"))
    panel = _load_panel(snapshot_manifest_path.parent, snapshot_manifest)
    benchmark_path = ROOT / campaign["canonical_benchmark"]["path"]
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    evaluation_index = pd.DatetimeIndex(benchmark["dates"])
    benchmark_returns = np.asarray(benchmark["total_returns"], dtype=float)
    if canonical_sha256(benchmark_returns.tolist()) != benchmark["returns_sha256"]:
        raise RuntimeError("canonical benchmark return hash mismatch")
    if not np.allclose(
        panel["total_return_close"]["SPY"].pct_change(fill_method=None).reindex(
            evaluation_index
        ).to_numpy(),
        benchmark_returns,
        rtol=0.0,
        atol=1e-12,
    ):
        raise RuntimeError("Track-A SPY path differs from canonical benchmark")

    output.mkdir(parents=True, exist_ok=args.corrective_replay)
    ledger_path = output / "trial_ledger.jsonl"
    ledger = AppendOnlyTrialLedger(ledger_path)
    intent_commit = commit
    if args.corrective_replay:
        prior_snapshot = ledger.snapshot()
        if (
            prior_snapshot["raw_independent_n"] != 30
            or prior_snapshot["incomplete_trial_ids"]
        ):
            raise RuntimeError("corrective replay requires a complete raw-N=30 ledger")
        first_intent = next(
            event for event in ledger.verified_events()
            if event["event_type"] == "INTENT"
        )
        intent_commit = str(first_intent["payload"]["intent"]["code_commit"])
    results: list[dict[str, Any]] = []
    return_paths: dict[str, dict[str, np.ndarray]] = {}
    targets_by_id: dict[str, pd.DataFrame] = {}
    trial_ids: dict[str, str] = {}
    first_decision = pd.Timestamp("2014-12-31")
    last_decision = pd.Timestamp("2024-12-31")

    for spec in campaign["rounds"]:
        candidate_id = str(spec["id"])
        if args.corrective_replay and candidate_id not in TRACK_A_CONSTRUCTIONS:
            if candidate_id == "canonical_spy_replication":
                results.append({
                    "round": spec["round"],
                    "candidate_id": candidate_id,
                    "family": spec["family"],
                    "status": "PASS_BENCHMARK_CONTROL_NOT_CANDIDATE",
                })
            else:
                blocker = (
                    campaign["track_b_data"]["status"]
                    if int(spec["round"]) <= 19
                    else campaign["semantic_data"]["status"]
                    if int(spec["round"]) <= 29
                    else campaign["llm_data"]["status"]
                )
                results.append({
                    "round": spec["round"],
                    "candidate_id": candidate_id,
                    "family": spec["family"],
                    "status": "BLOCKED_DATA_COUNTED",
                    "reason": blocker,
                })
            continue
        intent = _intent(
            spec,
            commit=intent_commit,
            data_hash=data_ref["manifest_sha256"],
            prereg_hash=prereg_hash,
        )
        if args.corrective_replay:
            intent = replace(
                intent,
                trial_id=f"{intent.trial_id}-corrective-serialization-replay",
            )
        registration = ledger.register_intent(intent)
        if args.corrective_replay and registration.independent_trial:
            raise RuntimeError(
                f"corrective replay unexpectedly increased N: {candidate_id}"
            )
        if not args.corrective_replay and not registration.independent_trial:
            raise RuntimeError(f"unexpected replay in fresh V5 ledger: {candidate_id}")
        trial_ids[candidate_id] = intent.trial_id
        print(f"[R{int(spec['round']):02d}/30] {candidate_id}", flush=True)
        if candidate_id == "canonical_spy_replication":
            ledger.record_outcome(intent.trial_id, {
                "status": "PASS_BENCHMARK_CONTROL_NOT_CANDIDATE",
                "canonical_return_hash": benchmark["returns_sha256"],
                "exact_cash_parity": benchmark["parity"],
            })
            results.append({
                "round": spec["round"],
                "candidate_id": candidate_id,
                "family": spec["family"],
                "status": "PASS_BENCHMARK_CONTROL_NOT_CANDIDATE",
            })
            continue
        if candidate_id not in TRACK_A_CONSTRUCTIONS:
            blocker = (
                campaign["track_b_data"]["status"]
                if int(spec["round"]) <= 19
                else campaign["semantic_data"]["status"]
                if int(spec["round"]) <= 29
                else campaign["llm_data"]["status"]
            )
            ledger.record_failed(
                intent.trial_id,
                error_type="PreRegisteredDataBlocker",
                message=blocker,
            )
            results.append({
                "round": spec["round"],
                "candidate_id": candidate_id,
                "family": spec["family"],
                "status": "BLOCKED_DATA_COUNTED",
                "reason": blocker,
            })
            continue
        ledger.record_started(intent.trial_id)
        construction = TRACK_A_CONSTRUCTIONS[candidate_id]
        try:
            targets = build_track_a_targets(
                construction,
                panel["total_return_close"],
                first_decision=first_decision,
                last_decision=last_decision,
            )
            timing = _timing_evidence(
                construction, panel["total_return_close"], targets
            )
            paths, execution = _run_candidate(targets, panel, evaluation_index)
            outcome = {
                "status": "COMPLETED_DEVELOPMENT_ONLY",
                "timing": timing,
                "execution": execution,
                "targets_sha256": hashlib.sha256(
                    targets.to_json(
                        orient="split", date_format="iso", double_precision=15
                    ).encode("utf-8")
                ).hexdigest(),
            }
            ledger.record_outcome(intent.trial_id, _finite(outcome))
            targets_by_id[candidate_id] = targets
            return_paths[candidate_id] = paths
            results.append({
                "round": spec["round"],
                "candidate_id": candidate_id,
                "family": spec["family"],
                **_finite(outcome),
            })
        except Exception as exc:
            ledger.record_failed(
                intent.trial_id,
                error_type=type(exc).__name__,
                message=str(exc),
            )
            results.append({
                "round": spec["round"],
                "candidate_id": candidate_id,
                "family": spec["family"],
                "status": "FAILED_COUNTED",
                "reason": f"{type(exc).__name__}: {exc}",
            })

    snapshot = ledger.snapshot()
    if snapshot["raw_independent_n"] != 30 or snapshot["incomplete_trial_ids"]:
        raise RuntimeError(f"V5 ledger is not complete raw-N=30: {snapshot}")
    completed = list(return_paths)
    if not completed:
        raise RuntimeError("V5 produced no complete candidate paths")
    matrix = np.column_stack([
        return_paths[candidate_id]["base_30bps"] for candidate_id in completed
    ])
    contract_path = ROOT / campaign["evaluation_contract"]["path"]
    historical_refs = campaign["historical_trial_universe"]
    qualification_rows: list[dict[str, Any]] = []
    daily = pd.DataFrame(index=evaluation_index)
    daily["SPY_costless_total_return"] = benchmark_returns
    for candidate_id in completed:
        for name, values in return_paths[candidate_id].items():
            daily[f"{candidate_id}__{name}"] = values
        timing = next(
            row["timing"] for row in results if row["candidate_id"] == candidate_id
        )
        bundle = {
            "schema_version": 3,
            "candidate_id": candidate_id,
            "observed_through": campaign["observed_through"],
            "dates": benchmark["dates"],
            "evaluation_contract": {
                "path": str(contract_path.relative_to(ROOT)),
                "sha256": sha256_file(contract_path),
            },
            "historical_trial_ledgers": historical_refs,
            "candidate_net_returns": return_paths[candidate_id][
                "base_30bps"
            ].tolist(),
            "benchmark_total_returns": benchmark_returns.tolist(),
            "trial_ids": [trial_ids[item] for item in completed],
            "trial_period_returns": matrix.tolist(),
            "cost_stress_returns": {
                name: values.tolist()
                for name, values in return_paths[candidate_id].items()
            },
            "cpcv": {"n_groups": 6, "k_test": 2, "horizon": 63,
                     "embargo_frac": 0.01},
            "candidate_specific_timing": timing,
        }
        input_path = output / "qualification_inputs" / f"{candidate_id}.json"
        _atomic_json(input_path, _finite(bundle))
        artifact = build_qualification_artifact(
            input_bundle_path=input_path,
            ledger_path=ledger_path,
            repo_root=ROOT,
            code_commit=commit,
        )
        artifact_path = output / "qualifications" / f"{candidate_id}.json"
        _atomic_json(artifact_path, _finite(artifact))
        validation = validate_qualification_artifact(
            artifact_path,
            expected_candidate_id=candidate_id,
            expected_code_commit=commit,
            repo_root=ROOT,
        )
        computed = artifact["computed"]
        turnover = float(targets_by_id[candidate_id].diff().abs().sum(axis=1).sum())
        computed["annual_turnover_diagnostic"] = turnover / 10.0
        qualification_rows.append({
            "candidate_id": candidate_id,
            "family": next(
                row["family"] for row in results if row["candidate_id"] == candidate_id
            ),
            "qualification_passed": validation.passed,
            "research_qualification_passed": computed[
                "research_qualification_passed"
            ],
            "paper_status": computed["paper_status"],
            "failed_checks": list(validation.failed_checks),
            "gates": computed["gates"],
            "qualification_path": str(artifact_path.relative_to(ROOT)),
            "qualification_sha256": sha256_file(artifact_path),
            "selection_score": list(_selection_score(computed)),
            "annual_turnover_diagnostic": turnover / 10.0,
        })

    daily_path = output / "daily_after_cost_returns.parquet"
    daily.to_parquet(daily_path)
    passing = sorted(
        [row for row in qualification_rows if row["qualification_passed"]],
        key=lambda row: tuple(row["selection_score"]),
        reverse=True,
    )
    frozen: list[dict[str, Any]] = []
    used_families: set[str] = set()
    for row in passing:
        if row["family"] in used_families:
            continue
        candidate_id = row["candidate_id"]
        correlations: dict[str, float] = {}
        for prior in frozen:
            correlation = float(np.corrcoef(
                return_paths[candidate_id]["base_30bps"],
                return_paths[prior["candidate_id"]]["base_30bps"],
            )[0, 1])
            correlations[prior["candidate_id"]] = correlation
        if any(abs(value) >= 0.70 for value in correlations.values()):
            continue
        freeze = {
            "schema_version": 1,
            "candidate_id": candidate_id,
            "family": row["family"],
            "status": "FROZEN_FORWARD_CANDIDATE",
            "paper_status": row["paper_status"],
            "evidence_scope": "DEVELOPMENT_ONLY",
            "code_commit": commit,
            "preregistration_sha256": prereg_hash,
            "qualification": {
                "path": row["qualification_path"],
                "sha256": row["qualification_sha256"],
            },
            "correlations_to_prior": correlations,
            "automatic_promotion_eligible": False,
            "capital_eligible": False,
            "no_feedback_to_mining": True,
        }
        freeze_path = output / "frozen_candidates" / f"{candidate_id}.json"
        _atomic_json(freeze_path, freeze)
        frozen.append({
            "candidate_id": candidate_id,
            "family": row["family"],
            "freeze_path": str(freeze_path.relative_to(ROOT)),
            "freeze_sha256": sha256_file(freeze_path),
        })
        used_families.add(str(row["family"]))
        if len(frozen) == 5:
            break

    report = {
        "schema_version": 1,
        "campaign_id": campaign["campaign_id"],
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "code_commit": commit,
        "evidence_scope": "DEVELOPMENT_ONLY",
        "observed_through": campaign["observed_through"],
        "rounds_consumed": 30,
        "execution_mode": (
            "CORRECTIVE_SERIALIZATION_REPLAY_NO_NEW_INDEPENDENT_TRIALS"
            if args.corrective_replay
            else "ORIGINAL_EXECUTION"
        ),
        "exit_condition": (
            "FIVE_FORMAL_CANDIDATES" if len(frozen) == 5 else "MAXIMUM_30_ROUNDS"
        ),
        "formal_candidate_count": len(frozen),
        "frozen_candidates": frozen,
        "ledger": snapshot,
        "composite_raw_independent_n": 30 + snapshot["raw_independent_n"],
        "canonical_benchmark": campaign["canonical_benchmark"],
        "track_a_snapshot": data_ref,
        "round_results": results,
        "qualifications": qualification_rows,
        "daily_returns": {
            "path": str(daily_path.relative_to(ROOT)),
            "sha256": sha256_file(daily_path),
        },
        "track_b_disposition": campaign["track_b_data"]["status"],
        "semantic_disposition": campaign["semantic_data"]["status"],
        "llm_disposition": campaign["llm_data"]["status"],
        "historical_oos_claim_allowed": False,
        "automatic_promotion_eligible": False,
        "capital_eligible": False,
    }
    report_path = output / "campaign_report.json"
    _atomic_json(report_path, _finite(report))
    print(f"wrote {report_path}")
    print(f"exit_condition={report['exit_condition']}")
    print(f"formal_candidate_count={len(frozen)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
