from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from core.data.pit_contract import PitDataContract
from core.data.pit_source_inventory import build_source_inventory

PROJECT = Path(__file__).resolve().parents[3]
CONTRACT = PitDataContract.load(PROJECT / "config" / "pit_data_v1.yaml")


def test_inventory_reports_sources_without_secret_values_or_directional_metrics(
    tmp_path: Path,
):
    data = tmp_path / "data"
    (data / "daily").mkdir(parents=True)
    (data / "ref").mkdir()
    pd.DataFrame({"source": ["fixture"]}).to_parquet(
        data / "ref" / "bar_provenance.parquet", index=False
    )
    (data / "fundamentals" / "edgar_cache").mkdir(parents=True)
    (data / "fundamentals" / "edgar_cache" / "0000000001.json").write_text(
        "{}\n", encoding="utf-8"
    )
    manifest_dir = (
        data / "research" / "mining_v4" / "sec_submissions_complete_v2"
    )
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "manifest.json").write_text(
        json.dumps({"corpus_id": "fixture", "selected_filings": 2}) + "\n",
        encoding="utf-8",
    )
    pd.DataFrame({"accession": ["a", "b"]}).to_parquet(
        manifest_dir / "filing_metadata.parquet", index=False
    )

    inventory = build_source_inventory(
        tmp_path,
        contract=CONTRACT,
        environment={"WRDS_USERNAME": "secret-user", "UNRELATED": "value"},
    )
    assert inventory["directional_compute_performed"] is False
    markers = inventory["historical_security_master_access"]
    assert markers["environment_variable_names"] == ["WRDS_USERNAME"]
    assert "secret-user" not in json.dumps(inventory)
    assert inventory["local_market_data"]["reference_tables"][
        "bar_provenance.parquet"
    ]["rows"] == 1
    assert inventory["historical_source_assessment"]["status"] == (
        "BLOCKED_NO_APPROVED_HISTORICAL_SECURITY_MASTER"
    )
