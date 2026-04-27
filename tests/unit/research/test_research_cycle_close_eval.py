"""Unit tests for the research-cycle close-eval decision-table layer.

Targets `dev/scripts/research_cycle/run_close_eval.py`'s
`gate_check` and `build_decision_table` helpers — the pure functions
that turn (criteria thresholds, IC summary, walk-forward folds,
concentration metrics) into the G2.A pass/fail decision table.

The hard-gate-fail path (the cycle 2026-04-26-01 outcome:
watchlist_total_share = 0.395 > 0.30 ceiling) is the most important
case to protect: a regression that returned `passed=True` when the
gate should fail would silently advance a rejected candidate. These
tests pin that path.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]


def _load_close_eval_module():
    spec = importlib.util.spec_from_file_location(
        "research_cycle_run_close_eval_test_import",
        ROOT / "dev" / "scripts" / "research_cycle" / "run_close_eval.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# Mirror cycle 2026-04-26-01 criteria.yaml's hard_requirements (canonical)
HARD = {
    "min_ic_ir_full_period": 0.25,
    "min_walk_forward_folds_positive": 3,
    "walk_forward_n_folds": 4,
    "m12_concentration_tier_ceiling": "warning",
    "watchlist_total_share_ceiling": 0.30,
    "thin_data_weighted_share_ceiling": 0.10,
    "top1_weight_max_ceiling": 0.40,
    "top3_weight_max_ceiling": 0.70,
}


# ── gate_check primitive ────────────────────────────────────────────


def test_gate_check_ge_passes_when_at_or_above_threshold():
    mod = _load_close_eval_module()
    r = mod.gate_check("ic_ir", 1.04, "ge", 0.25)
    assert r["passed"] is True
    r = mod.gate_check("ic_ir", 0.25, "ge", 0.25)  # equal → passes
    assert r["passed"] is True


def test_gate_check_ge_fails_when_below_threshold():
    mod = _load_close_eval_module()
    r = mod.gate_check("ic_ir", 0.24, "ge", 0.25)
    assert r["passed"] is False


def test_gate_check_le_fails_when_above_threshold():
    """Critical: this is the watchlist gate's mode. 0.395 > 0.30 must
    return passed=False."""
    mod = _load_close_eval_module()
    r = mod.gate_check("watchlist", 0.3950, "le", 0.30)
    assert r["passed"] is False
    assert r["measured"] == 0.3950
    assert r["op"] == "le"
    assert r["threshold"] == 0.30


def test_gate_check_le_passes_when_at_or_below_threshold():
    mod = _load_close_eval_module()
    assert mod.gate_check("watchlist", 0.30, "le", 0.30)["passed"] is True
    assert mod.gate_check("watchlist", 0.10, "le", 0.30)["passed"] is True


def test_gate_check_in_set_membership():
    mod = _load_close_eval_module()
    assert mod.gate_check("tier", "warning", "in_set",
                          ["pass", "warning"])["passed"] is True
    assert mod.gate_check("tier", "manual_review_required", "in_set",
                          ["pass", "warning"])["passed"] is False


def test_gate_check_none_measured_never_passes_numeric_ops():
    """A missing measurement is a hard fail, not a silent pass."""
    mod = _load_close_eval_module()
    assert mod.gate_check("ic_ir", None, "ge", 0.25)["passed"] is False
    assert mod.gate_check("watchlist", None, "le", 0.30)["passed"] is False


def test_gate_check_unknown_op_raises():
    mod = _load_close_eval_module()
    with pytest.raises(ValueError, match="unknown gate op"):
        mod.gate_check("x", 1.0, "eq", 1.0)


# ── build_decision_table — hard-gate-fail path (the cycle outcome) ──


def test_build_decision_table_cycle_2026_04_26_01_actual_failure():
    """Pin the actual cycle outcome: 6 of 7 gates pass, watchlist
    fails. Any regression that flips the watchlist row to passed=True
    would silently advance a rejected candidate."""
    mod = _load_close_eval_module()
    rows = mod.build_decision_table(
        hard=HARD,
        ic_ir_full_period=1.0405,        # actual cycle measurement
        folds_positive=4,                 # actual cycle measurement
        concentration_dict={
            "tier": "warning",
            "watchlist_total_share": 0.3950,    # the binding fail
            "thin_data_weighted_share": 0.0751,
            "top1_weight_max": 0.10,
            "top3_weight_max": 0.30,
        },
    )

    assert len(rows) == 7
    by_gate = {r["gate"]: r for r in rows}
    assert by_gate["min_ic_ir_full_period"]["passed"] is True
    assert by_gate["min_walk_forward_folds_positive"]["passed"] is True
    assert by_gate["m12_concentration_tier"]["passed"] is True
    assert by_gate["watchlist_total_share"]["passed"] is False, (
        "watchlist_total_share=0.395 must FAIL the 0.30 ceiling — "
        "this is the cycle 2026-04-26-01 binding fail; a regression "
        "here would silently advance a rejected candidate"
    )
    assert by_gate["thin_data_weighted_share"]["passed"] is True
    assert by_gate["top1_weight_max"]["passed"] is True
    assert by_gate["top3_weight_max"]["passed"] is True

    # Overall pass = AND of all rows
    assert all(r["passed"] for r in rows) is False


def test_build_decision_table_all_pass_path_works():
    """Counter-case: a synthetic candidate that satisfies every gate
    must produce overall_pass=True. Without this, a regression that
    accidentally hard-codes False would not be caught by the fail
    test alone."""
    mod = _load_close_eval_module()
    rows = mod.build_decision_table(
        hard=HARD,
        ic_ir_full_period=0.50,
        folds_positive=4,
        concentration_dict={
            "tier": "pass",
            "watchlist_total_share": 0.10,
            "thin_data_weighted_share": 0.05,
            "top1_weight_max": 0.20,
            "top3_weight_max": 0.50,
        },
    )
    assert all(r["passed"] for r in rows) is True
    assert len(rows) == 7


def test_build_decision_table_walk_forward_3_of_4_passes():
    """3/4 folds positive is the threshold. 2/4 should fail."""
    mod = _load_close_eval_module()
    base_conc = {
        "tier": "pass",
        "watchlist_total_share": 0.10,
        "thin_data_weighted_share": 0.05,
        "top1_weight_max": 0.20,
        "top3_weight_max": 0.50,
    }
    pass_rows = mod.build_decision_table(
        hard=HARD, ic_ir_full_period=0.5, folds_positive=3,
        concentration_dict=base_conc,
    )
    fail_rows = mod.build_decision_table(
        hard=HARD, ic_ir_full_period=0.5, folds_positive=2,
        concentration_dict=base_conc,
    )
    by_gate_pass = {r["gate"]: r for r in pass_rows}
    by_gate_fail = {r["gate"]: r for r in fail_rows}
    assert by_gate_pass["min_walk_forward_folds_positive"]["passed"] is True
    assert by_gate_fail["min_walk_forward_folds_positive"]["passed"] is False


def test_build_decision_table_tier_manual_review_required_blocks():
    """The M12 tier ceiling is 'warning'; tier='manual_review_required'
    must be classified as not-in-set → fail. This is a cycle-2026-04-26-01-
    aligned rule (criteria yaml hard_requirements +
    docs/memos/20260425-m12_review_decision.md §5)."""
    mod = _load_close_eval_module()
    rows = mod.build_decision_table(
        hard=HARD, ic_ir_full_period=0.5, folds_positive=4,
        concentration_dict={
            "tier": "manual_review_required",
            "watchlist_total_share": 0.10,
            "thin_data_weighted_share": 0.05,
            "top1_weight_max": 0.20,
            "top3_weight_max": 0.50,
        },
    )
    by_gate = {r["gate"]: r for r in rows}
    assert by_gate["m12_concentration_tier"]["passed"] is False


def test_build_decision_table_missing_concentration_metric_fails():
    """If concentration measurement is missing for a numeric gate,
    the gate must FAIL. Silent passes on missing measurements would
    let a candidate slip through if a future eval bug zeroed-out a
    metric."""
    mod = _load_close_eval_module()
    rows = mod.build_decision_table(
        hard=HARD, ic_ir_full_period=0.5, folds_positive=4,
        concentration_dict={
            "tier": "pass",
            # watchlist_total_share missing -> .get() returns None
            "thin_data_weighted_share": 0.05,
            "top1_weight_max": 0.20,
            "top3_weight_max": 0.50,
        },
    )
    by_gate = {r["gate"]: r for r in rows}
    assert by_gate["watchlist_total_share"]["measured"] is None
    assert by_gate["watchlist_total_share"]["passed"] is False


# ── canonical-YAML finalize step (post Round-2 audit, 2026-04-27) ────


def _synthetic_closeout_payload_fail() -> dict:
    """Mirror the cycle 2026-04-26-01 hard-gate-fail closeout shape."""
    return {
        "lineage_tag": "research-cycle-2026-04-26-01",
        "candidate_id": "research-cycle-2026-04-26-01_top_trial_rejected_at_g2a",
        "evaluated_at_utc": "2026-04-26T19:01:00+00:00",
        "g2_a_decision_table": [
            {"gate": "min_ic_ir_full_period", "measured": 1.0405, "op": "ge", "threshold": 0.25, "passed": True},
            {"gate": "min_walk_forward_folds_positive", "measured": 4, "op": "ge", "threshold": 3, "passed": True},
            {"gate": "m12_concentration_tier", "measured": "warning", "op": "in_set", "threshold": ["pass", "warning"], "passed": True},
            {"gate": "watchlist_total_share", "measured": 0.3950, "op": "le", "threshold": 0.30, "passed": False},
            {"gate": "thin_data_weighted_share", "measured": 0.0751, "op": "le", "threshold": 0.10, "passed": True},
            {"gate": "top1_weight_max", "measured": 0.10, "op": "le", "threshold": 0.40, "passed": True},
            {"gate": "top3_weight_max", "measured": 0.30, "op": "le", "threshold": 0.70, "passed": True},
        ],
        "g2_a_overall_pass": False,
        "g2_b_report_only": {
            "regime_breakdown": {
                "BULL":     {"ic_ir": 0.402, "n_dates": 568},
                "BEAR":     {"ic_ir": 1.204, "n_dates": 393},
                "RISK_ON":  {"ic_ir": 1.354, "n_dates": 168},
                "RISK_OFF": {"ic_ir": 1.138, "n_dates": 266},
                "CRISIS":   {"ic_ir": 4.452, "n_dates": 75},
                "SIDEWAYS": {"ic_ir": 1.170, "n_dates": 762},
            },
            "benchmark_beta_statistics": {
                "portfolio_weighted_mean_beta": 1.7957,
                "portfolio_weighted_std_beta": 1.3288,
            },
            "pseudo_oos_2024": {
                "cum_ret": 0.2801, "sharpe": 0.8888, "max_dd": -0.2884,
                "vs_spy": 0.0401, "vs_qqq": 0.0102,
            },
            "turnover_full_period": 0.0814,
            "correlation_vs_existing_pair": {
                "rcm_v1_defensive_composite_01": 0.6148,
                "candidate_2_orthogonal_01": 0.6137,
            },
        },
        "concentration_report_summary": {
            "tier": "warning",
            "watchlist_total_share": 0.3950,
            "watchlist_single_max_share": 0.0862,
            "thin_data_weighted_share": 0.0751,
            "thin_data_binary_share": 0.3867,
            "top1_weight_max": 0.10,
            "top3_weight_max": 0.30,
        },
    }


def _synthetic_full_summary() -> dict:
    return {"ic_mean": 0.0739, "ic_std": 0.2458, "ic_ir": 1.0405, "n_dates": 2232}


def test_build_summary_blocks_from_payload_fail_case_shape():
    """Pin the exact shape produced for the cycle 2026-04-26-01 fail."""
    mod = _load_close_eval_module()
    blocks = mod.build_summary_blocks_from_payload(
        closeout_payload=_synthetic_closeout_payload_fail(),
        full_summary=_synthetic_full_summary(),
        candidate_id="research-cycle-2026-04-26-01_top_trial_rejected_at_g2a",
        output_dir=ROOT / "data" / "research_candidates",
        walk_n_folds=4,
        walk_lag_bars=1,
    )

    assert set(blocks.keys()) == {
        "benchmark_relative_summary", "oos_holdout_summary",
        "robustness_summary", "acceptance_decision",
        "acceptance_decision_details",
    }

    # Acceptance decision: rejected, naming the binding fail gate
    assert blocks["acceptance_decision"] == "rejected_at_g2a_watchlist_total_share"
    details = blocks["acceptance_decision_details"]
    assert details["g2_a_overall_pass"] is False
    assert details["binding_fail_gate"] == "watchlist_total_share"
    assert details["binding_fail_measured"] == 0.3950
    assert details["binding_fail_threshold"] == 0.30
    assert details["binding_fail_op"] == "le"
    assert details["retroactive_softening_applied"] is False

    # OOS holdout: numeric IR + walk-forward + pseudo-OOS preserved
    oos = blocks["oos_holdout_summary"]
    assert oos["full_period_ic_ir"] == 1.0405
    assert oos["walk_forward_n_folds"] == 4
    assert oos["walk_forward_folds_positive"] == 4
    assert oos["walk_forward_lag_bars"] == 1
    assert oos["pseudo_oos_2024_max_dd"] == -0.2884

    # Robustness: tier + watchlist + regime stats
    rob = blocks["robustness_summary"]
    assert rob["m12_concentration_tier"] == "warning"
    assert rob["watchlist_total_share"] == 0.3950
    assert rob["regime_n_total"] == 6
    assert rob["regime_folds_positive"] == 6
    assert rob["regime_strongest"] == "CRISIS"   # max IC_IR
    assert rob["regime_weakest"] == "BULL"        # min IC_IR

    # Benchmark relative: corr vs existing pair + realized beta
    bench = blocks["benchmark_relative_summary"]
    assert bench["composite_corr_vs_rcm_v1_defensive_composite_01"] == 0.6148
    assert bench["composite_corr_vs_candidate_2_orthogonal_01"] == 0.6137
    assert bench["realized_portfolio_weighted_mean_beta"] == 1.7957
    assert bench["vs_spy_qqq"] == "deferred_to_paper_layer"


def test_build_summary_blocks_never_emits_S1_or_pending_tokens():
    """Critical contract test: the finalize output must never re-introduce
    the forbidden tokens that Codex's Round 2 acceptance bar enumerates,
    even on a synthetic pass case."""
    import json
    mod = _load_close_eval_module()

    fail_blocks = mod.build_summary_blocks_from_payload(
        closeout_payload=_synthetic_closeout_payload_fail(),
        full_summary=_synthetic_full_summary(),
        candidate_id="research-cycle-2026-04-26-01_top_trial_rejected_at_g2a",
        output_dir=ROOT / "data" / "research_candidates",
        walk_n_folds=4, walk_lag_bars=1,
    )

    pass_payload = _synthetic_closeout_payload_fail()
    pass_payload["g2_a_overall_pass"] = True
    for row in pass_payload["g2_a_decision_table"]:
        row["passed"] = True
    pass_blocks = mod.build_summary_blocks_from_payload(
        closeout_payload=pass_payload,
        full_summary=_synthetic_full_summary(),
        candidate_id="research-cycle-2026-04-26-01_top_trial_rejected_at_g2a",
        output_dir=ROOT / "data" / "research_candidates",
        walk_n_folds=4, walk_lag_bars=1,
    )

    for blocks in (fail_blocks, pass_blocks):
        flat = json.dumps(blocks, default=str)
        for forbidden in ("S1_nominee", "S1_RESEARCH_CANDIDATE", "pending_closeout_eval"):
            assert forbidden not in flat, (
                f"build_summary_blocks_from_payload emitted forbidden "
                f"token {forbidden!r}; output={flat[:300]}"
            )


def _make_fixture_yaml(tmp_path, body_inside_markers: str = "") -> object:
    """Write a minimal canonical YAML fixture with the marker pair."""
    p = tmp_path / "fixture.yaml"
    text = (
        "candidate_id: fixture_top_trial_rejected_at_g2a\n"
        "feature_set: []\n"
        "\n"
        "# ── BEGIN closeout finalize block (auto-written by run_close_eval.py) ─\n"
        f"{body_inside_markers}"
        "# ── END closeout finalize block ──────────────────────────────────────\n"
    )
    p.write_text(text)
    return p


def test_finalize_canonical_yaml_replaces_marker_block(tmp_path):
    mod = _load_close_eval_module()
    spec_path = _make_fixture_yaml(tmp_path, body_inside_markers="placeholder line\n")

    blocks = mod.build_summary_blocks_from_payload(
        closeout_payload=_synthetic_closeout_payload_fail(),
        full_summary=_synthetic_full_summary(),
        candidate_id="fixture_top_trial_rejected_at_g2a",
        output_dir=tmp_path,
        walk_n_folds=4, walk_lag_bars=1,
    )
    new_text = mod._finalize_canonical_yaml(spec_path, blocks)

    # Marker pair survives
    assert mod.CLOSEOUT_BEGIN_MARKER in new_text
    assert mod.CLOSEOUT_END_MARKER in new_text
    # Content outside markers untouched
    assert "candidate_id: fixture_top_trial_rejected_at_g2a" in new_text
    # Region content replaced (placeholder line gone)
    assert "placeholder line" not in new_text
    # Critical canonical fields present
    assert "acceptance_decision: rejected_at_g2a_watchlist_total_share" in new_text
    assert "benchmark_relative_summary:" in new_text
    assert "oos_holdout_summary:" in new_text
    assert "robustness_summary:" in new_text
    assert "acceptance_decision_details:" in new_text


def test_finalize_canonical_yaml_strips_forbidden_tokens(tmp_path):
    mod = _load_close_eval_module()
    # Seed the fixture with the forbidden tokens inside the marker region
    seeded = (
        "acceptance_decision: pending_closeout_eval\n"
        "stage: S1_RESEARCH_CANDIDATE\n"
        "candidate_label: S1_nominee\n"
    )
    spec_path = _make_fixture_yaml(tmp_path, body_inside_markers=seeded)

    blocks = mod.build_summary_blocks_from_payload(
        closeout_payload=_synthetic_closeout_payload_fail(),
        full_summary=_synthetic_full_summary(),
        candidate_id="fixture_top_trial_rejected_at_g2a",
        output_dir=tmp_path,
        walk_n_folds=4, walk_lag_bars=1,
    )
    new_text = mod._finalize_canonical_yaml(spec_path, blocks)

    for tok in ("S1_nominee", "S1_RESEARCH_CANDIDATE", "pending_closeout_eval"):
        assert tok not in new_text, f"finalize did not strip token {tok!r}"


def test_finalize_canonical_yaml_preserves_notes(tmp_path):
    """Editorial `note:` fields inside summary blocks must survive a re-run."""
    mod = _load_close_eval_module()
    seeded = (
        "benchmark_relative_summary:\n"
        "  evidence_artifact: data/x.json\n"
        "  note: this editorial note must survive\n"
        "oos_holdout_summary:\n"
        "  full_period_ic_ir: 0.0\n"
        "  note: oos editorial prose\n"
        "robustness_summary:\n"
        "  note: rob editorial prose\n"
        "acceptance_decision: stale_will_be_overwritten\n"
    )
    spec_path = _make_fixture_yaml(tmp_path, body_inside_markers=seeded)

    blocks = mod.build_summary_blocks_from_payload(
        closeout_payload=_synthetic_closeout_payload_fail(),
        full_summary=_synthetic_full_summary(),
        candidate_id="fixture_top_trial_rejected_at_g2a",
        output_dir=tmp_path,
        walk_n_folds=4, walk_lag_bars=1,
    )
    new_text = mod._finalize_canonical_yaml(spec_path, blocks)

    assert "this editorial note must survive" in new_text
    assert "oos editorial prose" in new_text
    assert "rob editorial prose" in new_text
    # And the canonical decision was still re-written
    assert "rejected_at_g2a_watchlist_total_share" in new_text
    assert "stale_will_be_overwritten" not in new_text


def test_finalize_canonical_yaml_is_idempotent(tmp_path):
    """Running finalize twice with the same payload yields the same file."""
    mod = _load_close_eval_module()
    spec_path = _make_fixture_yaml(tmp_path, body_inside_markers="seed\n")

    blocks = mod.build_summary_blocks_from_payload(
        closeout_payload=_synthetic_closeout_payload_fail(),
        full_summary=_synthetic_full_summary(),
        candidate_id="fixture_top_trial_rejected_at_g2a",
        output_dir=tmp_path,
        walk_n_folds=4, walk_lag_bars=1,
    )
    first = mod._finalize_canonical_yaml(spec_path, blocks)
    second = mod._finalize_canonical_yaml(spec_path, blocks)
    assert first == second


def test_finalize_canonical_yaml_missing_markers_raises(tmp_path):
    """If markers are absent the function must refuse to silently
    rewrite the whole file."""
    mod = _load_close_eval_module()
    bad = tmp_path / "no_markers.yaml"
    bad.write_text("candidate_id: x\nfeature_set: []\n")
    blocks = mod.build_summary_blocks_from_payload(
        closeout_payload=_synthetic_closeout_payload_fail(),
        full_summary=_synthetic_full_summary(),
        candidate_id="x",
        output_dir=tmp_path,
        walk_n_folds=4, walk_lag_bars=1,
    )
    with pytest.raises(RuntimeError, match="missing the closeout finalize"):
        mod._finalize_canonical_yaml(bad, blocks)


def test_finalize_canonical_yaml_pass_case_emits_no_S1_advancement_token(tmp_path):
    """Even on a synthetic g2_a pass, the acceptance_decision string
    must not use any forbidden token. (We do not advance to a paper
    slot from this pipeline; that is a separate manual decision.)"""
    mod = _load_close_eval_module()
    spec_path = _make_fixture_yaml(tmp_path)

    pass_payload = _synthetic_closeout_payload_fail()
    pass_payload["g2_a_overall_pass"] = True
    for row in pass_payload["g2_a_decision_table"]:
        row["passed"] = True
    blocks = mod.build_summary_blocks_from_payload(
        closeout_payload=pass_payload,
        full_summary=_synthetic_full_summary(),
        candidate_id="fixture_top_trial_rejected_at_g2a",
        output_dir=tmp_path,
        walk_n_folds=4, walk_lag_bars=1,
    )
    new_text = mod._finalize_canonical_yaml(spec_path, blocks)

    for tok in ("S1_nominee", "S1_RESEARCH_CANDIDATE", "pending_closeout_eval"):
        assert tok not in new_text
    assert "passed_g2a" in new_text   # something honest about the pass
