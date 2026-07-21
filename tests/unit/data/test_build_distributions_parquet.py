from __future__ import annotations

import pandas as pd

from dev.scripts.data_integrity import build_distributions_parquet
from dev.scripts.data_integrity.build_distributions_parquet import (
    _atomic_to_parquet,
    _merge_distributions,
)


def _events(symbols: list[str]) -> pd.DataFrame:
    return pd.DataFrame({
        "symbol": symbols,
        "ex_date": pd.to_datetime(["2026-01-02"] * len(symbols)),
        "cash_amount": [1.0] * len(symbols),
    })


def test_append_replaces_requested_symbol_with_verified_zero_events():
    existing = _events(["AAA", "BBB"])
    merged = _merge_distributions(
        existing,
        pd.DataFrame(columns=existing.columns),
        requested_symbols={"AAA"},
    )
    assert merged["symbol"].tolist() == ["BBB"]


def test_append_replaces_old_events_without_touching_other_symbols():
    existing = _events(["AAA", "BBB"])
    new = _events(["AAA"])
    new.loc[:, "cash_amount"] = 2.0
    merged = _merge_distributions(
        existing, new, requested_symbols={"AAA"})
    assert merged.set_index("symbol")["cash_amount"].to_dict() == {
        "AAA": 2.0,
        "BBB": 1.0,
    }


def test_atomic_parquet_publish_round_trip(tmp_path):
    destination = tmp_path / "ref" / "evidence.parquet"
    expected = _events(["AAA"])
    _atomic_to_parquet(expected, destination)
    pd.testing.assert_frame_equal(pd.read_parquet(destination), expected)
    assert not list(destination.parent.glob("*.tmp"))


def test_failed_batch_never_overwrites_canonical_sidecars(tmp_path, monkeypatch):
    ref = tmp_path / "ref"
    ref.mkdir()
    (ref / "splits.parquet").write_bytes(b"split-evidence")
    distributions = ref / "distributions.parquet"
    coverage = ref / "distribution_coverage.parquet"
    _events(["KEEP"]).to_parquet(distributions, index=False)
    pd.DataFrame({"symbol": ["KEEP"], "status": ["OK"]}).to_parquet(
        coverage, index=False)
    before_distributions = distributions.read_bytes()
    before_coverage = coverage.read_bytes()

    def fail(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        build_distributions_parquet, "_fetch_distributions_yfinance", fail)
    monkeypatch.setattr(
        "sys.argv",
        [
            "build_distributions_parquet.py",
            "--symbols", "AAA",
            "--data-root", str(tmp_path),
            "--append",
        ],
    )
    assert build_distributions_parquet.main() == 2
    assert distributions.read_bytes() == before_distributions
    assert coverage.read_bytes() == before_coverage
    assert len(list((tmp_path / "audit").glob("distribution_coverage_errors_*.parquet"))) == 1
