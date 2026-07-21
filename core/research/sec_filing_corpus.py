"""Point-in-time SEC submissions parsing for the governed semantic track."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Any, Mapping

import pandas as pd

GOVERNED_FORMS = frozenset({"8-K", "10-Q", "10-K"})
GOVERNED_8K_ITEMS = frozenset({"2.02", "7.01"})


@dataclass(frozen=True, slots=True)
class FilingMetadata:
    ticker: str
    cik: int
    accession_number: str
    form: str
    filing_date: str
    report_date: str
    acceptance_datetime_utc: str
    items: str
    primary_document: str
    primary_doc_description: str
    size_bytes: int
    is_xbrl: bool
    is_inline_xbrl: bool


def _column(recent: Mapping[str, Any], name: str, count: int) -> list[Any]:
    values = recent.get(name)
    if not isinstance(values, list) or len(values) != count:
        raise ValueError(
            f"SEC submissions recent.{name} must contain {count} rows")
    return values


def parse_recent_submissions(
    payload: Mapping[str, Any],
    *,
    ticker: str,
    cik: int,
) -> list[FilingMetadata]:
    """Parse governed recent filings without using filing/report date as time."""

    filings = payload.get("filings")
    if not isinstance(filings, Mapping):
        raise ValueError("SEC submissions response lacks filings object")
    recent = filings.get("recent")
    if not isinstance(recent, Mapping):
        raise ValueError("SEC submissions response lacks filings.recent object")
    accessions = recent.get("accessionNumber")
    if not isinstance(accessions, list):
        raise ValueError("SEC submissions recent.accessionNumber must be a list")
    count = len(accessions)
    names = (
        "form", "filingDate", "reportDate", "acceptanceDateTime", "items",
        "primaryDocument", "primaryDocDescription", "size", "isXBRL",
        "isInlineXBRL",
    )
    columns = {name: _column(recent, name, count) for name in names}
    records: list[FilingMetadata] = []
    for idx, accession in enumerate(accessions):
        form = str(columns["form"][idx]).upper().strip()
        if form not in GOVERNED_FORMS:
            continue
        items = str(columns["items"][idx] or "")
        if form == "8-K" and not any(
            item in {part.strip() for part in items.split(",")}
            for item in GOVERNED_8K_ITEMS
        ):
            continue
        acceptance = pd.Timestamp(columns["acceptanceDateTime"][idx])
        if acceptance.tzinfo is None:
            raise ValueError(
                f"{ticker} {accession}: acceptanceDateTime must be timezone-aware")
        acceptance = acceptance.tz_convert("UTC")
        document = str(columns["primaryDocument"][idx] or "")
        _validate_primary_document(document)
        records.append(FilingMetadata(
            ticker=ticker,
            cik=int(cik),
            accession_number=str(accession),
            form=form,
            filing_date=str(columns["filingDate"][idx] or ""),
            report_date=str(columns["reportDate"][idx] or ""),
            acceptance_datetime_utc=acceptance.isoformat(),
            items=items,
            primary_document=document,
            primary_doc_description=str(
                columns["primaryDocDescription"][idx] or ""),
            size_bytes=int(columns["size"][idx] or 0),
            is_xbrl=bool(columns["isXBRL"][idx]),
            is_inline_xbrl=bool(columns["isInlineXBRL"][idx]),
        ))
    return records


def _validate_primary_document(document: str) -> None:
    path = PurePosixPath(document)
    if not document or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe SEC primary document path: {document!r}")


def filing_document_url(record: FilingMetadata) -> str:
    accession = record.accession_number.replace("-", "")
    if not accession.isdigit():
        raise ValueError(f"invalid SEC accession number: {record.accession_number}")
    _validate_primary_document(record.primary_document)
    return (
        f"https://www.sec.gov/Archives/edgar/data/{record.cik}/"
        f"{accession}/{record.primary_document}"
    )


def records_frame(records: list[FilingMetadata]) -> pd.DataFrame:
    columns = list(FilingMetadata.__dataclass_fields__)
    frame = pd.DataFrame([asdict(record) for record in records], columns=columns)
    if frame.empty:
        return frame
    if frame["accession_number"].duplicated().any():
        duplicates = frame.loc[
            frame["accession_number"].duplicated(), "accession_number"].tolist()
        raise ValueError(f"duplicate SEC accessions: {duplicates[:5]}")
    frame["acceptance_datetime_utc"] = pd.to_datetime(
        frame["acceptance_datetime_utc"], utc=True)
    return frame.sort_values(
        ["acceptance_datetime_utc", "ticker", "accession_number"]
    ).reset_index(drop=True)


__all__ = [
    "FilingMetadata",
    "GOVERNED_8K_ITEMS",
    "GOVERNED_FORMS",
    "filing_document_url",
    "parse_recent_submissions",
    "records_frame",
]
