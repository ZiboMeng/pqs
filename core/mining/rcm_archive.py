"""
RCMArchive: Research Composite Miner v1 archive (PRD 20260424 §12.2).

Distinct from `core/mining/archive.py::MiningArchive`:
  - Separate file (`data/mining/rcm_archive.db` by default)
  - Schema captures research-composite semantics (family counts, objective
    components, correlation concentration, turnover proxy) NOT present in
    the production-linked archive
  - NEVER mixed with production MiningArchive to avoid re-introducing the
    production-linked coupling Research Composite Miner was built to break

Companion: `data/mining/rcm_optuna.db` (Optuna's own SQLite storage) —
separate DB as well; managed by Optuna directly via
`optuna.create_study(storage="sqlite:///...", study_name=...)`.

Schema
------
  rcm_trials  : every ResearchMiner.run_trial outcome (success + failure)
  rcm_studies : per-study metadata (creation time, objective weights, panel description)

Usage
-----
    from core.mining.rcm_archive import RCMArchive
    arch = RCMArchive("data/mining/rcm_archive.db")
    arch.insert_trial(trial_result, lineage_tag="post-2026-04-24-rcm-v1",
                      study_id="run-2026-04-24-a")
    top = arch.top_k(k=20, lineage_tag="post-2026-04-24-rcm-v1")
    df  = arch.lineage_summary()
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import pandas as pd

from core.logging_setup import get_logger

from core.mining.research_miner import TrialResult

logger = get_logger(__name__)


_CREATE_TRIALS = """
CREATE TABLE IF NOT EXISTS rcm_trials (
    trial_id            TEXT    PRIMARY KEY,
    study_id            TEXT    NOT NULL,
    lineage_tag         TEXT    NOT NULL,
    created_at          TEXT    NOT NULL,

    -- Spec
    spec_json           TEXT    NOT NULL,
    n_features          INTEGER NOT NULL,
    n_families          INTEGER NOT NULL,
    features_csv        TEXT    NOT NULL,
    weights_csv         TEXT    NOT NULL,
    family_counts_json  TEXT    NOT NULL,

    -- Metrics (NULL permitted: e.g. NaN when n_dates=0 or ic_std=0)
    n_dates             INTEGER NOT NULL,
    ic_mean             REAL,
    ic_std              REAL,
    ic_ir               REAL,
    turnover_proxy      REAL,
    corr_concentration  REAL,

    -- Objective components (v1: benchmark_excess + regime_stddev default 0).
    -- objective NULL permitted when compute_objective returns NaN (rare —
    -- -inf is stored as -inf, a valid sqlite REAL).
    benchmark_excess    REAL    NOT NULL DEFAULT 0.0,
    regime_stddev       REAL    NOT NULL DEFAULT 0.0,
    objective           REAL
)
"""

_CREATE_STUDIES = """
CREATE TABLE IF NOT EXISTS rcm_studies (
    study_id            TEXT    PRIMARY KEY,
    lineage_tag         TEXT    NOT NULL,
    created_at          TEXT    NOT NULL,
    objective_weights_json TEXT,
    panel_description   TEXT,
    n_trials_recorded   INTEGER NOT NULL DEFAULT 0,

    -- Track A v1 (PRD 20260429): temporal split fingerprint at study level.
    -- All NULL on legacy studies (pre-Track-A); populated by record_study()
    -- when the temporal split flow is active. ALTER TABLE ADD COLUMN handles
    -- migration in _init_schema (idempotent: silently skipped if present).
    split_name          TEXT,
    split_sha256        TEXT,
    role                TEXT
)
"""

# ALTER TABLE migrations for legacy archives that pre-date Track A. Each
# statement is wrapped in try/except OperationalError (SQLite emits this
# when the column already exists). _init_schema() runs CREATE then ALTER
# unconditionally; CREATE is idempotent for new DBs and ALTER is no-op
# for already-migrated DBs.
_ALTER_STUDIES_TRACK_A = [
    "ALTER TABLE rcm_studies ADD COLUMN split_name TEXT",
    "ALTER TABLE rcm_studies ADD COLUMN split_sha256 TEXT",
    "ALTER TABLE rcm_studies ADD COLUMN role TEXT",
]
_ALTER_TRIALS_TRACK_A = [
    "ALTER TABLE rcm_trials ADD COLUMN split_sha256 TEXT",
    "ALTER TABLE rcm_trials ADD COLUMN panel_max_date TEXT",
    "ALTER TABLE rcm_trials ADD COLUMN role TEXT",
    "ALTER TABLE rcm_trials ADD COLUMN max_factor_lookback_days INTEGER",
]

_CREATE_INDEX_LINEAGE = """
CREATE INDEX IF NOT EXISTS idx_rcm_trials_lineage
    ON rcm_trials(lineage_tag)
"""
_CREATE_INDEX_OBJECTIVE = """
CREATE INDEX IF NOT EXISTS idx_rcm_trials_objective
    ON rcm_trials(objective DESC)
"""
_CREATE_INDEX_STUDY = """
CREATE INDEX IF NOT EXISTS idx_rcm_trials_study
    ON rcm_trials(study_id)
"""


def _hash_spec(spec_json: str) -> str:
    """Deterministic trial_id = first 12 hex chars of sha256(spec_json).

    Same spec (features + weights + family_counts) → same id → dedup via
    ON CONFLICT REPLACE.
    """
    return hashlib.sha256(spec_json.encode("utf-8")).hexdigest()[:12]


def _serialize_spec(spec) -> dict:
    return {
        "features": list(spec.features),
        "weights": list(spec.weights),
        "family_counts": dict(spec.family_counts),
    }


def compute_spec_id(spec) -> str:
    """Public canonical spec identifier matching ``insert_trial``'s trial_id.

    Codex R21 P0.1: required by the M6 C5 role-remint guard so the mining
    path can look up "has this spec already been recorded under a
    different role in this split?" using the same identifier the archive
    uses internally. Keeping a single hashing function eliminates the
    drift risk of "guard saw spec A; archive recorded spec B".
    """
    return _hash_spec(json.dumps(_serialize_spec(spec), sort_keys=True))


class RCMArchive:
    """SQLite archive for research composite miner trials."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(_CREATE_TRIALS)
            conn.execute(_CREATE_STUDIES)
            conn.execute(_CREATE_INDEX_LINEAGE)
            conn.execute(_CREATE_INDEX_OBJECTIVE)
            conn.execute(_CREATE_INDEX_STUDY)
            # Track A v1 migrations (idempotent — silent skip if already applied)
            for stmt in (_ALTER_STUDIES_TRACK_A + _ALTER_TRIALS_TRACK_A):
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError as exc:
                    if "duplicate column name" not in str(exc):
                        raise
            conn.commit()

    # ── Study metadata ───────────────────────────────────────────────────

    def record_study(
        self,
        study_id: str,
        lineage_tag: str,
        objective_weights: Optional[dict] = None,
        panel_description: Optional[str] = None,
        split_name: Optional[str] = None,
        split_sha256: Optional[str] = None,
        role: Optional[str] = None,
    ) -> None:
        """Record study metadata. Track A fields (split_name/split_sha256/role)
        default to NULL for legacy mining flows; populated when temporal split
        is active.
        """
        now = datetime.now(timezone.utc).isoformat()
        ow_json = json.dumps(objective_weights) if objective_weights else None
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO rcm_studies
                    (study_id, lineage_tag, created_at,
                     objective_weights_json, panel_description,
                     n_trials_recorded,
                     split_name, split_sha256, role)
                VALUES (?, ?, ?, ?, ?,
                        COALESCE((SELECT n_trials_recorded FROM rcm_studies
                                  WHERE study_id=?), 0),
                        ?, ?, ?)
                """,
                (study_id, lineage_tag, now, ow_json, panel_description,
                 study_id,
                 split_name, split_sha256, role),
            )
            conn.commit()

    def find_studies_by_spec_role(
        self,
        spec_sha256: str,
        split_name: str,
    ) -> List[dict]:
        """Codex R20 Q3 (M6 C5) lookup: return prior trials matching this
        spec_sha256 within the given split_name, with their assigned role.

        Used by mining startup to enforce: a candidate spec already mined
        under role=core in split_v1 cannot be reminted under role=diversifier
        in the same split_v1.
        """
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT t.trial_id, t.study_id, t.role, t.lineage_tag, t.created_at
                  FROM rcm_trials t
                  JOIN rcm_studies s ON t.study_id = s.study_id
                 WHERE t.trial_id = ? AND s.split_name = ?
                """,
                (spec_sha256, split_name),
            )
            return [
                {"trial_id": r[0], "study_id": r[1], "role": r[2],
                 "lineage_tag": r[3], "created_at": r[4]}
                for r in cursor.fetchall()
            ]

    # ── Trial insert ─────────────────────────────────────────────────────

    def insert_trial(
        self,
        trial: TrialResult,
        *,
        lineage_tag: str,
        study_id: str,
        benchmark_excess: float = 0.0,
        regime_stddev: float = 0.0,
        split_sha256: Optional[str] = None,
        panel_max_date: Optional[str] = None,
        role: Optional[str] = None,
        max_factor_lookback_days: Optional[int] = None,
    ) -> str:
        """Insert a TrialResult. Deterministic trial_id from spec hash.

        Re-inserting the same spec (same features+weights+family_counts)
        replaces the prior row (ON CONFLICT REPLACE via primary key).
        Returns the trial_id.

        Track A v1 (PRD 20260429) added 4 optional per-trial fingerprint
        fields. They default to NULL on legacy mining flows.
        """
        spec_dict = _serialize_spec(trial.spec)
        spec_json = json.dumps(spec_dict, sort_keys=True)
        trial_id = _hash_spec(spec_json)
        now = datetime.now(timezone.utc).isoformat()
        m = trial.metrics
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO rcm_trials (
                    trial_id, study_id, lineage_tag, created_at,
                    spec_json, n_features, n_families,
                    features_csv, weights_csv, family_counts_json,
                    n_dates, ic_mean, ic_std, ic_ir,
                    turnover_proxy, corr_concentration,
                    benchmark_excess, regime_stddev, objective,
                    split_sha256, panel_max_date, role, max_factor_lookback_days
                )
                VALUES (
                    ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?
                )
                """,
                (
                    trial_id, study_id, lineage_tag, now,
                    spec_json, m.n_features, m.n_families,
                    ",".join(spec_dict["features"]),
                    ",".join(f"{w:.6f}" for w in spec_dict["weights"]),
                    json.dumps(spec_dict["family_counts"], sort_keys=True),
                    m.n_dates,
                    _as_float(m.ic_mean),
                    _as_float(m.ic_std),
                    _as_float(m.ic_ir),
                    _as_float(m.turnover_proxy),
                    _as_float(m.corr_concentration),
                    float(benchmark_excess),
                    float(regime_stddev),
                    _as_float(trial.objective),
                    split_sha256, panel_max_date, role, max_factor_lookback_days,
                ),
            )
            # Bump study trial counter
            conn.execute(
                """
                UPDATE rcm_studies
                    SET n_trials_recorded = n_trials_recorded + 1
                    WHERE study_id = ?
                """,
                (study_id,),
            )
            conn.commit()
        return trial_id

    # ── Query ────────────────────────────────────────────────────────────

    def top_k(
        self,
        k: int = 20,
        *,
        lineage_tag: Optional[str] = None,
    ) -> pd.DataFrame:
        """Return top-K trials by objective (descending).

        Filters to a lineage_tag if provided; excludes NULL/NaN objective.
        """
        where = "WHERE objective IS NOT NULL"
        params: List = []
        if lineage_tag is not None:
            where += " AND lineage_tag = ?"
            params.append(lineage_tag)
        sql = f"""
            SELECT trial_id, study_id, lineage_tag, created_at,
                   n_features, n_families, features_csv, weights_csv,
                   family_counts_json,
                   n_dates, ic_mean, ic_std, ic_ir,
                   turnover_proxy, corr_concentration,
                   benchmark_excess, regime_stddev, objective
            FROM rcm_trials
            {where}
            ORDER BY objective DESC
            LIMIT ?
        """
        params.append(int(k))
        with self._connect() as conn:
            df = pd.read_sql_query(sql, conn, params=params)
        return df

    def lineage_summary(self) -> pd.DataFrame:
        """Per-lineage aggregate (trial count, best/worst objective,
        mean IC_IR, best IC_IR)."""
        sql = """
            SELECT
                lineage_tag,
                COUNT(*)                  AS n_trials,
                AVG(ic_ir)                AS avg_ic_ir,
                MAX(ic_ir)                AS best_ic_ir,
                AVG(objective)            AS avg_objective,
                MAX(objective)            AS best_objective,
                MIN(objective)            AS worst_objective
            FROM rcm_trials
            GROUP BY lineage_tag
            ORDER BY best_objective DESC
        """
        with self._connect() as conn:
            return pd.read_sql_query(sql, conn)

    def n_trials(self, *, lineage_tag: Optional[str] = None) -> int:
        sql = "SELECT COUNT(*) FROM rcm_trials"
        params: List = []
        if lineage_tag is not None:
            sql += " WHERE lineage_tag = ?"
            params.append(lineage_tag)
        with self._connect() as conn:
            cur = conn.execute(sql, params)
            return int(cur.fetchone()[0])


def _as_float(x) -> Optional[float]:
    """SQLite-safe float. NaN → None (NULL in SQLite for clean sort)."""
    try:
        fx = float(x)
    except (TypeError, ValueError):
        return None
    if fx != fx:  # NaN check without numpy dependency here
        return None
    return fx
