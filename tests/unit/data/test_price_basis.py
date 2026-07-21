from __future__ import annotations

import hashlib

import pandas as pd
import pytest

from core.data.price_basis import PriceBasisError, validate_total_return_coverage


def _write_sidecars(
    tmp_path,
    *,
    status="OK",
    split_status="OK",
    checked_start="2007-01-01",
    checked_end="2026-07-17",
    sha=None,
):
    ref = tmp_path / "ref"
    ref.mkdir(parents=True)
    split_path = ref / "splits.parquet"
    pd.DataFrame(
        [{"symbol": "AAA", "date": pd.Timestamp("2020-01-02"), "from": 1, "to": 2}]
    ).to_parquet(split_path, index=False)
    actual_sha = hashlib.sha256(split_path.read_bytes()).hexdigest()[:16]
    stamped_sha = sha or actual_sha
    pd.DataFrame(
        columns=[
            "symbol", "ex_date", "cash_amount", "ref_close_pre_ex", "factor",
            "source", "pulled_at", "splits_table_sha",
        ]
    ).to_parquet(ref / "distributions.parquet", index=False)
    pd.DataFrame(
        [{
            "symbol": "AAA",
            "checked_start": pd.Timestamp(checked_start),
            "checked_end": pd.Timestamp(checked_end),
            "checked_at": "2026-07-18T00:00:00Z",
            "status": status,
            "splits_table_sha": stamped_sha,
        }]
    ).to_parquet(ref / "distribution_coverage.parquet", index=False)
    pd.DataFrame(
        [{
            "symbol": "AAA",
            "checked_start": pd.Timestamp(checked_start),
            "checked_end": pd.Timestamp(checked_end),
            "checked_at": "2026-07-18T00:00:00Z",
            "status": split_status,
            "splits_table_sha": stamped_sha,
        }]
    ).to_parquet(ref / "split_coverage.parquet", index=False)
    return actual_sha


def test_zero_distribution_symbol_requires_and_accepts_explicit_query_coverage(tmp_path):
    sha = _write_sidecars(tmp_path)
    evidence = validate_total_return_coverage(
        tmp_path, ["AAA"], from_date="2007-01-01", through="2026-07-17"
    )
    assert evidence.splits_table_sha == sha
    assert evidence.distribution_coverage_rows == 1
    assert evidence.split_coverage_rows == 1
    assert evidence.basis == "split_and_distribution_adjusted_total_return"


@pytest.mark.parametrize(
    ("status", "checked_end", "sha", "match"),
    [
        ("ERROR", "2026-07-17", None, "query failed"),
        ("OK", "2026-07-16", None, "ends before"),
        ("OK", "2026-07-17", "wrong", "hash mismatch"),
    ],
)
def test_coverage_contract_fails_closed(tmp_path, status, checked_end, sha, match):
    _write_sidecars(tmp_path, status=status, checked_end=checked_end, sha=sha)
    with pytest.raises(PriceBasisError, match=match):
        validate_total_return_coverage(
            tmp_path,
            ["AAA"],
            from_date="2007-01-01",
            through="2026-07-17",
        )


def test_split_mismatch_fails_closed(tmp_path):
    _write_sidecars(tmp_path, split_status="MISMATCH")
    with pytest.raises(PriceBasisError, match="split verification failed"):
        validate_total_return_coverage(
            tmp_path,
            ["AAA"],
            from_date="2007-01-01",
            through="2026-07-17",
        )


def test_coverage_must_span_requested_start(tmp_path):
    _write_sidecars(tmp_path, checked_start="2010-01-01")
    with pytest.raises(PriceBasisError, match="starts after"):
        validate_total_return_coverage(
            tmp_path,
            ["AAA"],
            from_date="2007-01-01",
            through="2026-07-17",
        )
