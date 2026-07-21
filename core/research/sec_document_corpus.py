"""Deterministic SEC primary-document request selection and storage keys."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Sequence

import pandas as pd

from core.research.sec_filing_corpus import FilingMetadata, filing_document_url


@dataclass(frozen=True, slots=True)
class DocumentRequest:
    ticker: str
    cik: int
    accession_number: str
    form: str
    acceptance_datetime_utc: str
    primary_document: str
    url: str
    storage_name: str

    @property
    def key(self) -> str:
        return f"{self.cik}:{self.accession_number}:{self.primary_document}"


def document_storage_name(
    cik: int,
    accession_number: str,
    primary_document: str,
) -> str:
    accession = accession_number.replace("-", "")
    if not accession.isdigit():
        raise ValueError(f"invalid SEC accession number: {accession_number}")
    document_hash = hashlib.sha256(primary_document.encode("utf-8")).hexdigest()[:12]
    suffix = primary_document.rsplit(".", 1)[-1].lower()
    suffix = suffix if re.fullmatch(r"[a-z0-9]{1,8}", suffix) else "bin"
    return f"CIK{int(cik):010d}_{accession}_{document_hash}.{suffix}"


def select_primary_document_requests(
    metadata: pd.DataFrame,
    *,
    forms: Sequence[str],
    start_year: int,
    end_year: int,
) -> list[DocumentRequest]:
    required = set(FilingMetadata.__dataclass_fields__)
    missing = required - set(metadata)
    if missing:
        raise ValueError(f"filing metadata lacks columns: {sorted(missing)}")
    accepted = pd.to_datetime(
        metadata["acceptance_datetime_utc"], utc=True, errors="raise")
    requested_forms = {form.upper() for form in forms}
    selected = metadata[
        metadata["form"].str.upper().isin(requested_forms)
        & accepted.dt.year.between(start_year, end_year)
        & metadata["primary_document"].fillna("").ne("")
    ].copy()
    selected["acceptance_datetime_utc"] = accepted.loc[selected.index]
    selected = selected.sort_values([
        "acceptance_datetime_utc", "cik", "accession_number",
        "primary_document",
    ])
    duplicate = selected.duplicated(
        ["cik", "accession_number", "primary_document"], keep="first")
    selected = selected.loc[~duplicate]
    output: list[DocumentRequest] = []
    for row in selected.itertuples(index=False):
        record = FilingMetadata(**{
            name: getattr(row, name)
            for name in FilingMetadata.__dataclass_fields__
        })
        output.append(DocumentRequest(
            ticker=record.ticker,
            cik=int(record.cik),
            accession_number=record.accession_number,
            form=record.form,
            acceptance_datetime_utc=pd.Timestamp(
                record.acceptance_datetime_utc).isoformat(),
            primary_document=record.primary_document,
            url=filing_document_url(record),
            storage_name=document_storage_name(
                record.cik, record.accession_number, record.primary_document),
        ))
    return output


__all__ = [
    "DocumentRequest",
    "document_storage_name",
    "select_primary_document_requests",
]
