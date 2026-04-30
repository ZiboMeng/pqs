"""Sealed-evaluation ledger for the 2026 single-shot holdout.

PRD: docs/prd/20260429-temporal_split_holdout_discipline_prd.md (v1.1)
Step A.7 — machine-auditable ledger that enforces:

  M5 fail_closed_on_repeat:
    Same (split_name, candidate_spec_sha256) cannot be re-evaluated
    against 2026 sealed test. Forces "intentional bump split_name"
    rather than silent retries that would consume the holdout.

  Codex R20 B1 fail_closed_on_split_failure:
    Any core-role candidate sealed eval consumes the holdout for that
    split_name; no further core sealed eval is permitted under the
    same split_name. Diversifier-role evals do NOT block subsequent
    diversifier evals (PRD §5.2 — diversifier promotion is downstream
    of an already-locked core decision).

The ledger is an append-only parquet at the path declared in
``audit.sealed_eval_ledger.path``. ``record_eval`` is the single
write entry point; it computes the result_metrics_sha256, writes the
new row, and never mutates prior rows. ``check_eligibility`` is the
read-only fail-closed guard called BEFORE any sealed evaluation.

Public API
----------
- ``SealedLedgerEntry``: dataclass for a single ledger row.
- ``SealedEvalDeniedError``: raised when fail-closed rules trigger.
- ``check_eligibility(spec_sha256, split_name, role, ledger_path)``:
  pre-flight; raises SealedEvalDeniedError if disallowed.
- ``record_eval(spec_sha256, split_name, role, git_sha,
  panel_max_date, result_metrics, ledger_path)``: atomic append.
- ``read_ledger(ledger_path)``: utility to inspect the ledger.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from core.research.temporal_split import (
    TemporalSplitConfig,
    compute_split_sha256,
    load_temporal_split,
)


_DEFAULT_LEDGER_REL_PATH = "data/research_candidates/sealed_eval_ledger.parquet"


# ---------------------------------------------------------------------------
# Errors + dataclasses
# ---------------------------------------------------------------------------


class SealedEvalDeniedError(RuntimeError):
    """Raised when fail-closed sealed-ledger rules block an evaluation."""

    def __init__(self, message: str, *, rule: str, prior_rows: List[dict]):
        super().__init__(message)
        self.rule = rule
        self.prior_rows = prior_rows


@dataclass
class SealedLedgerEntry:
    """A single ledger row. All fields are required at write time."""

    split_name: str
    split_sha256: str
    candidate_spec_sha256: str
    role: str
    git_sha: str
    panel_max_date: str
    evaluation_timestamp_utc: str
    result_metrics_sha256: str
    extra_json: str = ""  # Optional JSON for ad-hoc metadata

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Result-metrics hashing (deterministic content fingerprint)
# ---------------------------------------------------------------------------


def compute_result_metrics_sha256(metrics: Dict[str, Any]) -> str:
    """Hash a result-metrics dict deterministically.

    Canonicalization: keys sorted recursively; floats serialized via
    ``repr`` to avoid platform-dependent str() formatting; lists keep
    order. Numpy/pandas scalars are coerced to native Python via
    ``.item()`` (audit BUG #2 fix 2026-04-29 R1: real Track C mining
    returns numpy.int64 / numpy.float64 from pandas operations and
    json.dumps fails on them). Returns full hex SHA-256.
    """
    import numpy as _np

    def _canon(obj):
        if isinstance(obj, dict):
            return {k: _canon(obj[k]) for k in sorted(obj.keys(), key=str)}
        if isinstance(obj, (list, tuple)):
            return [_canon(x) for x in obj]
        if isinstance(obj, _np.ndarray):
            return [_canon(x) for x in obj.tolist()]
        if isinstance(obj, _np.generic):
            return _canon(obj.item())
        if isinstance(obj, float):
            return repr(obj)
        return obj

    canonical = json.dumps(_canon(metrics), sort_keys=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Ledger I/O
# ---------------------------------------------------------------------------


def _ledger_columns() -> List[str]:
    """Field order for parquet (matches SealedLedgerEntry attrs + tz fields)."""
    return [
        "split_name",
        "split_sha256",
        "candidate_spec_sha256",
        "role",
        "git_sha",
        "panel_max_date",
        "evaluation_timestamp_utc",
        "result_metrics_sha256",
        "extra_json",
    ]


def read_ledger(ledger_path: Optional[str | Path] = None) -> pd.DataFrame:
    """Load the sealed-eval ledger as a DataFrame.

    Returns an empty DataFrame with the canonical columns when the
    ledger does not exist yet (first eval scenario).
    """
    path = Path(ledger_path) if ledger_path is not None else Path(_DEFAULT_LEDGER_REL_PATH)
    if not path.exists():
        return pd.DataFrame(columns=_ledger_columns())
    return pd.read_parquet(path)


def _append_to_ledger(entry: SealedLedgerEntry, ledger_path: Path) -> None:
    """Atomic append: write a temp parquet, then rename.

    Concurrent writers are not supported in v1 (single-user research
    workflow). If multi-process write contention surfaces in practice,
    a fcntl/lock layer can be added without breaking the file format.
    """
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    new_row = pd.DataFrame([entry.as_dict()], columns=_ledger_columns())
    if ledger_path.exists():
        existing = pd.read_parquet(ledger_path)
        combined = pd.concat([existing, new_row], ignore_index=True)
    else:
        combined = new_row
    tmp = ledger_path.with_suffix(".parquet.tmp")
    combined.to_parquet(tmp, index=False)
    tmp.replace(ledger_path)


# ---------------------------------------------------------------------------
# Eligibility check (fail-closed) — M5 + B1
# ---------------------------------------------------------------------------


def check_eligibility(
    spec_sha256: str,
    split_name: str,
    role: str,
    ledger_path: Optional[str | Path] = None,
) -> None:
    """Pre-flight gate. Raises SealedEvalDeniedError if the eval is denied.

    Rule 1 (M5) — fail_closed_on_repeat:
      Same (split_name, spec_sha256) already evaluated → DENY.
      Deterministic re-runs are blocked because each sealed eval
      consumes the holdout sample.

    Rule 2 (codex R20 B1) — fail_closed_on_split_failure:
      Any prior **core** eval under the same split_name → DENY further
      **core** evals (must bump split_name). Diversifier role exempt
      per PRD §5.2.
    """
    df = read_ledger(ledger_path)
    if df.empty:
        return

    same_split = df[df["split_name"] == split_name]
    if same_split.empty:
        return

    # Rule 1: same (split, spec)
    same_spec = same_split[same_split["candidate_spec_sha256"] == spec_sha256]
    if len(same_spec) > 0:
        raise SealedEvalDeniedError(
            f"M5 fail_closed_on_repeat: candidate spec {spec_sha256[:12]} "
            f"already evaluated against split {split_name!r}. To re-evaluate "
            f"after intentional gate change, bump split_name to a new version.",
            rule="fail_closed_on_repeat",
            prior_rows=same_spec.to_dict(orient="records"),
        )

    # Rule 2: same split + core role
    if role == "core":
        prior_core = same_split[same_split["role"] == "core"]
        if len(prior_core) > 0:
            raise SealedEvalDeniedError(
                f"Codex R20 B1 fail_closed_on_split_failure: a core sealed "
                f"eval has already been performed under split {split_name!r}. "
                f"To re-evaluate, bump split_name to a new version (which by "
                f"locked_after_first_use:true also requires adjusting "
                f"validation/sealed years).",
                rule="fail_closed_on_split_failure",
                prior_rows=prior_core.to_dict(orient="records"),
            )


# ---------------------------------------------------------------------------
# record_eval — single write entry point
# ---------------------------------------------------------------------------


def record_eval(
    spec_sha256: str,
    split_name: str,
    split_sha256: str,
    role: str,
    git_sha: str,
    panel_max_date: str,
    result_metrics: Dict[str, Any],
    ledger_path: Optional[str | Path] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> SealedLedgerEntry:
    """Record a sealed evaluation. Calls check_eligibility first.

    Workflow:
      1. ``check_eligibility`` — raise if M5 or B1 deny.
      2. Hash result_metrics for tamper detection.
      3. Atomic append to ledger.
      4. Return the persisted entry.

    Subsequent eligibility checks read this row and apply the
    same-(split,spec) and same-(split,core) rules above.
    """
    check_eligibility(spec_sha256, split_name, role, ledger_path)

    entry = SealedLedgerEntry(
        split_name=split_name,
        split_sha256=split_sha256,
        candidate_spec_sha256=spec_sha256,
        role=role,
        git_sha=git_sha,
        panel_max_date=panel_max_date,
        evaluation_timestamp_utc=datetime.now(timezone.utc).isoformat(),
        result_metrics_sha256=compute_result_metrics_sha256(result_metrics),
        extra_json=(json.dumps(extra, sort_keys=True) if extra else ""),
    )
    path = Path(ledger_path) if ledger_path is not None else Path(_DEFAULT_LEDGER_REL_PATH)
    _append_to_ledger(entry, path)
    return entry


# ---------------------------------------------------------------------------
# Convenience driver — wires split YAML + computes split_sha256
# ---------------------------------------------------------------------------


def run_sealed_eval_record(
    spec_sha256: str,
    role: str,
    git_sha: str,
    panel_max_date: str,
    result_metrics: Dict[str, Any],
    split_yaml_path: Optional[str | Path] = None,
    ledger_path: Optional[str | Path] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> SealedLedgerEntry:
    """High-level driver: compute split_sha256 + persist entry."""
    cfg: TemporalSplitConfig = load_temporal_split(
        Path(split_yaml_path) if split_yaml_path else None
    )
    split_sha = compute_split_sha256(
        Path(split_yaml_path) if split_yaml_path else None
    )
    return record_eval(
        spec_sha256=spec_sha256,
        split_name=cfg.split_name,
        split_sha256=split_sha,
        role=role,
        git_sha=git_sha,
        panel_max_date=panel_max_date,
        result_metrics=result_metrics,
        ledger_path=ledger_path,
        extra=extra,
    )
