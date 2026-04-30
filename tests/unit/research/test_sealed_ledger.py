"""Tests for core.research.sealed_ledger.

PRD: docs/prd/20260429-temporal_split_holdout_discipline_prd.md (v1.1)
Step A.7 — sealed-eval ledger; M5 fail_closed_on_repeat + codex R20 B1
fail_closed_on_split_failure.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from core.research.sealed_ledger import (
    SealedEvalDeniedError,
    check_eligibility,
    compute_result_metrics_sha256,
    read_ledger,
    record_eval,
    run_sealed_eval_record,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _passing_metrics():
    return {
        "validation": {
            "2025": {"excess_vs_qqq": 0.02, "maxdd": 0.14},
        },
        "stress_slice": {"covid_flash": {"maxdd": 0.20}},
        "concentration": {"top1_max": 0.30},
    }


# ---------------------------------------------------------------------------
# Empty ledger + read API
# ---------------------------------------------------------------------------


def test_read_ledger_returns_empty_when_path_absent(tmp_path):
    df = read_ledger(tmp_path / "no_such.parquet")
    assert df.empty
    assert "split_name" in df.columns
    assert "candidate_spec_sha256" in df.columns


def test_check_eligibility_passes_on_empty_ledger(tmp_path):
    # No raise — empty ledger → first eval allowed
    check_eligibility(
        spec_sha256="x",
        split_name="alternating_regime_holdout_v1",
        role="core",
        ledger_path=tmp_path / "ledger.parquet",
    )


# ---------------------------------------------------------------------------
# record_eval round-trip
# ---------------------------------------------------------------------------


def test_record_eval_creates_ledger_with_one_row(tmp_path):
    ledger = tmp_path / "ledger.parquet"
    entry = record_eval(
        spec_sha256="aaa111",
        split_name="alternating_regime_holdout_v1",
        split_sha256="b" * 64,
        role="core",
        git_sha="deadbeef",
        panel_max_date="2025-12-31",
        result_metrics=_passing_metrics(),
        ledger_path=ledger,
    )
    assert ledger.exists()
    assert entry.candidate_spec_sha256 == "aaa111"
    assert entry.role == "core"
    df = read_ledger(ledger)
    assert len(df) == 1
    assert df.iloc[0]["candidate_spec_sha256"] == "aaa111"


def test_record_eval_appends_multiple_distinct_specs(tmp_path):
    """Different specs under different roles can both record (one core, one diversifier)."""
    ledger = tmp_path / "ledger.parquet"
    record_eval(
        spec_sha256="core_spec",
        split_name="v1", split_sha256="x" * 64, role="core",
        git_sha="g1", panel_max_date="2025-12-31",
        result_metrics={"a": 1}, ledger_path=ledger,
    )
    # Different spec, role=diversifier: B1 only blocks core+core
    record_eval(
        spec_sha256="div_spec",
        split_name="v1", split_sha256="x" * 64, role="diversifier",
        git_sha="g2", panel_max_date="2025-12-31",
        result_metrics={"b": 2}, ledger_path=ledger,
    )
    df = read_ledger(ledger)
    assert len(df) == 2


# ---------------------------------------------------------------------------
# M5 fail_closed_on_repeat — same (split, spec)
# ---------------------------------------------------------------------------


def test_repeat_same_spec_same_split_blocked(tmp_path):
    ledger = tmp_path / "ledger.parquet"
    record_eval(
        spec_sha256="repeat_spec",
        split_name="v1", split_sha256="x" * 64, role="core",
        git_sha="g1", panel_max_date="2025-12-31",
        result_metrics={"a": 1}, ledger_path=ledger,
    )
    with pytest.raises(SealedEvalDeniedError) as excinfo:
        record_eval(
            spec_sha256="repeat_spec",
            split_name="v1", split_sha256="x" * 64, role="core",
            git_sha="g2", panel_max_date="2025-12-31",
            result_metrics={"a": 1}, ledger_path=ledger,
        )
    assert excinfo.value.rule == "fail_closed_on_repeat"
    assert "M5" in str(excinfo.value)
    assert "bump split_name" in str(excinfo.value)


def test_repeat_blocked_even_with_diversifier_role(tmp_path):
    """M5 is identity-level: same spec under any role + same split blocked."""
    ledger = tmp_path / "ledger.parquet"
    record_eval(
        spec_sha256="x_spec",
        split_name="v1", split_sha256="x" * 64, role="core",
        git_sha="g1", panel_max_date="2025-12-31",
        result_metrics={"a": 1}, ledger_path=ledger,
    )
    with pytest.raises(SealedEvalDeniedError, match="M5"):
        # Even role=diversifier same-spec is blocked by M5
        record_eval(
            spec_sha256="x_spec",
            split_name="v1", split_sha256="x" * 64, role="diversifier",
            git_sha="g2", panel_max_date="2025-12-31",
            result_metrics={"a": 1}, ledger_path=ledger,
        )


def test_repeat_allowed_in_different_split(tmp_path):
    """Same spec under different split_name is OK (different governance domain)."""
    ledger = tmp_path / "ledger.parquet"
    record_eval(
        spec_sha256="x_spec",
        split_name="v1", split_sha256="aa" * 32, role="core",
        git_sha="g1", panel_max_date="2025-12-31",
        result_metrics={"a": 1}, ledger_path=ledger,
    )
    # Different split: allowed
    record_eval(
        spec_sha256="x_spec",
        split_name="v2", split_sha256="bb" * 32, role="core",
        git_sha="g2", panel_max_date="2026-12-31",
        result_metrics={"a": 1}, ledger_path=ledger,
    )
    df = read_ledger(ledger)
    assert len(df) == 2


# ---------------------------------------------------------------------------
# Codex R20 B1 fail_closed_on_split_failure — second core eval blocked
# ---------------------------------------------------------------------------


def test_second_core_eval_in_same_split_blocked(tmp_path):
    """Different spec + role=core + same split: B1 blocks (holdout already consumed)."""
    ledger = tmp_path / "ledger.parquet"
    record_eval(
        spec_sha256="first_core",
        split_name="v1", split_sha256="x" * 64, role="core",
        git_sha="g1", panel_max_date="2025-12-31",
        result_metrics={"a": 1}, ledger_path=ledger,
    )
    with pytest.raises(SealedEvalDeniedError) as excinfo:
        record_eval(
            spec_sha256="second_core",
            split_name="v1", split_sha256="x" * 64, role="core",
            git_sha="g2", panel_max_date="2025-12-31",
            result_metrics={"a": 2}, ledger_path=ledger,
        )
    assert excinfo.value.rule == "fail_closed_on_split_failure"
    assert "B1" in str(excinfo.value)
    assert "bump split_name" in str(excinfo.value)


def test_second_core_eval_allowed_in_different_split(tmp_path):
    """split_v1 has core eval; split_v2 first core eval is allowed."""
    ledger = tmp_path / "ledger.parquet"
    record_eval(
        spec_sha256="first_core",
        split_name="v1", split_sha256="aa" * 32, role="core",
        git_sha="g1", panel_max_date="2025-12-31",
        result_metrics={"a": 1}, ledger_path=ledger,
    )
    # First core in v2: allowed (different split = different holdout)
    record_eval(
        spec_sha256="second_core",
        split_name="v2", split_sha256="bb" * 32, role="core",
        git_sha="g2", panel_max_date="2026-12-31",
        result_metrics={"a": 2}, ledger_path=ledger,
    )
    df = read_ledger(ledger)
    assert len(df) == 2


def test_diversifier_eval_after_core_in_same_split_allowed(tmp_path):
    """B1 only blocks core+core; diversifier eval after core eval is OK
    (diversifier promotion is downstream of an already-locked core decision)."""
    ledger = tmp_path / "ledger.parquet"
    record_eval(
        spec_sha256="core_spec",
        split_name="v1", split_sha256="x" * 64, role="core",
        git_sha="g1", panel_max_date="2025-12-31",
        result_metrics={"a": 1}, ledger_path=ledger,
    )
    # Diversifier eval (different spec): allowed
    record_eval(
        spec_sha256="div_spec_1",
        split_name="v1", split_sha256="x" * 64, role="diversifier",
        git_sha="g2", panel_max_date="2025-12-31",
        result_metrics={"a": 2}, ledger_path=ledger,
    )
    # Second diversifier (different spec): also allowed
    record_eval(
        spec_sha256="div_spec_2",
        split_name="v1", split_sha256="x" * 64, role="diversifier",
        git_sha="g3", panel_max_date="2025-12-31",
        result_metrics={"a": 3}, ledger_path=ledger,
    )
    df = read_ledger(ledger)
    assert len(df) == 3


# ---------------------------------------------------------------------------
# Result-metrics sha256 determinism
# ---------------------------------------------------------------------------


def test_result_metrics_sha256_deterministic():
    m1 = {"a": 1, "b": [1, 2, 3], "c": {"d": 0.5}}
    m2 = {"c": {"d": 0.5}, "b": [1, 2, 3], "a": 1}  # key reorder
    assert compute_result_metrics_sha256(m1) == compute_result_metrics_sha256(m2)


def test_result_metrics_sha256_sensitive_to_value_change():
    m1 = {"a": 1, "b": [1, 2, 3]}
    m2 = {"a": 1, "b": [1, 2, 4]}
    assert compute_result_metrics_sha256(m1) != compute_result_metrics_sha256(m2)


def test_recorded_metrics_hash_persisted(tmp_path):
    ledger = tmp_path / "ledger.parquet"
    metrics = _passing_metrics()
    entry = record_eval(
        spec_sha256="abc", split_name="v1", split_sha256="x" * 64,
        role="core", git_sha="g", panel_max_date="2025-12-31",
        result_metrics=metrics, ledger_path=ledger,
    )
    expected = compute_result_metrics_sha256(metrics)
    assert entry.result_metrics_sha256 == expected
    df = read_ledger(ledger)
    assert df.iloc[0]["result_metrics_sha256"] == expected


# ---------------------------------------------------------------------------
# Driver: run_sealed_eval_record
# ---------------------------------------------------------------------------


def test_run_sealed_eval_record_default_path_succeeds(tmp_path):
    """End-to-end: load yaml + compute split_sha256 + record."""
    ledger = tmp_path / "ledger.parquet"
    entry = run_sealed_eval_record(
        spec_sha256="end2end",
        role="core",
        git_sha="g",
        panel_max_date="2025-12-31",
        result_metrics=_passing_metrics(),
        ledger_path=ledger,
    )
    assert entry.split_name == "alternating_regime_holdout_v1"
    assert len(entry.split_sha256) == 64
    assert ledger.exists()


# ---------------------------------------------------------------------------
# Atomic append (no torn writes on concurrent access — single writer
# assumption; verify ledger always parsable after each record)
# ---------------------------------------------------------------------------


def test_ledger_parquet_well_formed_after_appends(tmp_path):
    ledger = tmp_path / "ledger.parquet"
    for i in range(5):
        record_eval(
            spec_sha256=f"spec_{i}",
            split_name=f"v_{i}",  # Distinct split each time → no fail-closed
            split_sha256="z" * 64,
            role="diversifier",
            git_sha=f"g{i}",
            panel_max_date="2025-12-31",
            result_metrics={"i": i},
            ledger_path=ledger,
        )
    df = pd.read_parquet(ledger)
    assert len(df) == 5
    assert list(df.columns) == [
        "split_name", "split_sha256", "candidate_spec_sha256", "role",
        "git_sha", "panel_max_date", "evaluation_timestamp_utc",
        "result_metrics_sha256", "extra_json",
    ]


# ---------------------------------------------------------------------------
# Audit BUG #2 regression (2026-04-29 R1) — numpy types in result_metrics
# ---------------------------------------------------------------------------


def test_record_eval_with_numpy_int_and_float(tmp_path):
    """BUG #2: prior compute_result_metrics_sha256 used json.dumps directly
    and crashed with TypeError on numpy.int64 / numpy.float64 returned by
    pandas operations. Real Track C mining will return these.
    """
    import numpy as np
    ledger = tmp_path / "ledger.parquet"
    entry = record_eval(
        spec_sha256="np_test_spec",
        split_name="np_split",
        split_sha256="z" * 64,
        role="core",
        git_sha="abc",
        panel_max_date="2025-12-31",
        result_metrics={
            "cagr_np_float": np.float64(0.15),
            "trial_count_np_int": np.int64(100),
            "deterministic_native_float": 0.20,
        },
        ledger_path=ledger,
    )
    assert entry.result_metrics_sha256
    assert len(entry.result_metrics_sha256) == 64  # hex sha256


def test_record_eval_with_numpy_array_and_pandas_series(tmp_path):
    """BUG #2 sister case: ndarrays + pandas Series in nested metrics."""
    import numpy as np
    import pandas as pd
    ledger = tmp_path / "ledger.parquet"
    entry = record_eval(
        spec_sha256="arr_test_spec",
        split_name="arr_split",
        split_sha256="z" * 64,
        role="core",
        git_sha="abc",
        panel_max_date="2025-12-31",
        result_metrics={
            "ic_per_year": np.array([0.05, 0.07, 0.12]),
            "by_symbol": {"AAPL": np.float64(0.1), "MSFT": np.int64(2)},
        },
        ledger_path=ledger,
    )
    assert entry.result_metrics_sha256


def test_compute_result_metrics_sha_stable_across_native_vs_numpy():
    """The hash computed for native Python types must equal the hash for
    semantically equivalent numpy types (so a re-run that happens to pull
    bytes off pandas vs YAML produces the same fingerprint).
    """
    import numpy as np
    from core.research.sealed_ledger import compute_result_metrics_sha256
    h_native = compute_result_metrics_sha256({"cagr": 0.15, "count": 100})
    h_numpy = compute_result_metrics_sha256(
        {"cagr": np.float64(0.15), "count": np.int64(100)}
    )
    assert h_native == h_numpy
