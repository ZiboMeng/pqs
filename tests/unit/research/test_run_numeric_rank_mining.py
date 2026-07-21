from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from dev.scripts.mining_v4.run_numeric_rank_mining import (
    _portfolio_trial_intent,
    _validate_snapshot_manifest,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot(tmp_path: Path) -> tuple[Path, dict]:
    (tmp_path / "daily").mkdir()
    (tmp_path / "ref").mkdir()
    rows = []
    for symbol in ("AAA", "SPY"):
        path = tmp_path / "daily" / f"{symbol}.parquet"
        pd.DataFrame(
            {"close": [1.0]},
            index=pd.DatetimeIndex(["2024-01-02"], name="date"),
        ).to_parquet(path)
        rows.append({"symbol": symbol, "output_sha256": _sha(path)})
    splits = tmp_path / "ref" / "splits.parquet"
    splits.write_bytes(b"governed-splits-fixture")
    manifest = {
        "snapshot_id": "fixture",
        "pool_artifact_sha256": "pool-hash",
        "through": "2024-12-31",
        "price_basis": "RAW_OHLCV_WITH_SPLITS_APPLIED_AT_READ_TIME",
        "splits_sha256": _sha(splits),
        "symbols": rows,
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    return tmp_path, manifest


def test_snapshot_manifest_verifies_every_input_hash(tmp_path: Path):
    root, _ = _snapshot(tmp_path)
    evidence = _validate_snapshot_manifest(
        root,
        pool_hash="pool-hash",
        symbols=["AAA", "SPY"],
        through="2024-12-31",
    )
    assert evidence["symbols_verified"] == 2
    assert evidence["snapshot_id"] == "fixture"


def test_snapshot_manifest_rejects_post_build_daily_mutation(tmp_path: Path):
    root, _ = _snapshot(tmp_path)
    with (root / "daily" / "AAA.parquet").open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(RuntimeError, match="hash mismatch for AAA"):
        _validate_snapshot_manifest(
            root,
            pool_hash="pool-hash",
            symbols=["AAA", "SPY"],
            through="2024-12-31",
        )


def test_trial_intent_allows_event_label_contract():
    intent = _portfolio_trial_intent(
        trial_id="trial",
        model_name="model",
        construction="signal_only",
        cost_bps=0.0,
        universe_hash="universe",
        data_hash="data",
        config_hash="config",
        code_commit="commit",
        feature_id="features",
        start="2020-01-01",
        end="2024-12-31",
        observed_through="2026-07-17",
        seed=42,
        label_id="open_to_fifth_session_close_market_residual_rank",
    )
    assert intent.label_id == "open_to_fifth_session_close_market_residual_rank"
