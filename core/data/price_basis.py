"""Machine-checkable pricing-basis contract for certified research paths."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import pandas as pd


class PriceBasisError(RuntimeError):
    """Raised when total-return pricing evidence is missing or stale."""


@dataclass(frozen=True, slots=True)
class PriceBasisEvidence:
    basis: str
    symbols: tuple[str, ...]
    coverage_end: pd.Timestamp
    splits_table_sha: str
    distribution_rows: int
    coverage_rows: int


def _file_sha16(path: Path) -> str:
    if not path.exists():
        raise PriceBasisError(f"required pricing sidecar is missing: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def validate_total_return_coverage(
    root: str | Path,
    symbols: Sequence[str],
    *,
    through: str | pd.Timestamp,
) -> PriceBasisEvidence:
    """Validate query coverage and split-hash lineage through a cutoff.

    A symbol with zero distributions is valid only when the coverage sidecar
    proves the provider was queried successfully through ``through``.  This
    distinguishes a genuine no-distribution result from missing data.
    """
    data_root = Path(root)
    ref = data_root / "ref"
    split_path = ref / "splits.parquet"
    distributions_path = ref / "distributions.parquet"
    coverage_path = ref / "distribution_coverage.parquet"
    split_sha = _file_sha16(split_path)

    if not distributions_path.exists():
        raise PriceBasisError(f"distribution sidecar is missing: {distributions_path}")
    if not coverage_path.exists():
        raise PriceBasisError(f"distribution coverage is missing: {coverage_path}")

    distributions = pd.read_parquet(distributions_path)
    coverage = pd.read_parquet(coverage_path)
    required_coverage = {
        "symbol", "checked_end", "status", "splits_table_sha"
    }
    missing_cols = required_coverage - set(coverage.columns)
    if missing_cols:
        raise PriceBasisError(
            f"distribution coverage schema missing columns: {sorted(missing_cols)}"
        )

    wanted = tuple(dict.fromkeys(str(s).upper() for s in symbols))
    cutoff = pd.Timestamp(through).tz_localize(None).normalize()
    rows = coverage[coverage["symbol"].astype(str).str.upper().isin(wanted)].copy()
    rows["symbol"] = rows["symbol"].astype(str).str.upper()
    rows["checked_end"] = pd.to_datetime(rows["checked_end"]).dt.tz_localize(None)
    latest = rows.sort_values("checked_at" if "checked_at" in rows else "checked_end").drop_duplicates(
        "symbol", keep="last"
    )

    missing_symbols = sorted(set(wanted) - set(latest["symbol"]))
    if missing_symbols:
        raise PriceBasisError(
            f"distribution coverage missing symbols: {missing_symbols}"
        )
    bad_status = latest[latest["status"] != "OK"]
    if not bad_status.empty:
        raise PriceBasisError(
            "distribution provider query failed for: "
            f"{sorted(bad_status['symbol'].tolist())}"
        )
    stale = latest[latest["checked_end"] < cutoff]
    if not stale.empty:
        raise PriceBasisError(
            f"distribution coverage ends before {cutoff.date()} for: "
            f"{sorted(stale['symbol'].tolist())}"
        )
    bad_coverage_sha = latest[latest["splits_table_sha"] != split_sha]
    if not bad_coverage_sha.empty:
        raise PriceBasisError(
            f"coverage split hash mismatch for: {sorted(bad_coverage_sha['symbol'].tolist())}"
        )

    if not distributions.empty:
        required_dist = {"symbol", "splits_table_sha"}
        if not required_dist.issubset(distributions.columns):
            raise PriceBasisError("distribution sidecar lacks split-hash lineage")
        selected = distributions[
            distributions["symbol"].astype(str).str.upper().isin(wanted)
        ]
        bad_dist = selected[selected["splits_table_sha"] != split_sha]
        if not bad_dist.empty:
            raise PriceBasisError(
                f"distribution split hash mismatch for: "
                f"{sorted(bad_dist['symbol'].astype(str).unique().tolist())}"
            )

    return PriceBasisEvidence(
        basis="split_and_distribution_adjusted_total_return",
        symbols=wanted,
        coverage_end=cutoff,
        splits_table_sha=split_sha,
        distribution_rows=int(len(distributions)),
        coverage_rows=int(len(latest)),
    )
