"""Unit tests for core/mining/rcm_archive.py (PRD 20260424 §12.2, R12)."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from core.mining.rcm_archive import (
    RCMArchive,
    _hash_spec,
)
from core.mining.research_miner import (
    CompositeMetrics,
    FamilyConfig,
    ResearchCompositeSpec,
    ResearchMiner,
    TrialResult,
)


@pytest.fixture
def tmp_db(tmp_path):
    return tmp_path / "rcm_archive.db"


@pytest.fixture
def sample_trial():
    spec = ResearchCompositeSpec(
        features=("rel_spy_20d", "range_pos_252d", "amihud_20d"),
        weights=(0.4, 0.35, 0.25),
        family_counts={"A": 1, "B": 1, "C": 1},
    )
    m = CompositeMetrics(
        n_features=3, n_families=3, n_dates=100,
        ic_mean=0.03, ic_std=0.05, ic_ir=0.6,
        turnover_proxy=0.12, corr_concentration=0.18,
    )
    return TrialResult(spec=spec, metrics=m, objective=0.45)


# ── Schema creation ──────────────────────────────────────────────────────────


def test_archive_creates_tables_on_init(tmp_db):
    arch = RCMArchive(tmp_db)
    # Idempotent: second init doesn't error
    arch2 = RCMArchive(tmp_db)
    assert tmp_db.exists()
    # Introspect tables
    import sqlite3
    with sqlite3.connect(str(tmp_db)) as conn:
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "rcm_trials" in tables
    assert "rcm_studies" in tables


def test_archive_creates_parent_dir(tmp_path):
    nested = tmp_path / "sub" / "nested" / "rcm.db"
    assert not nested.parent.exists()
    arch = RCMArchive(nested)
    assert nested.exists()


# ── _hash_spec determinism ──────────────────────────────────────────────────


def test_hash_spec_is_deterministic():
    s1 = json.dumps({"features": ["a"], "weights": [1.0]}, sort_keys=True)
    s2 = json.dumps({"features": ["a"], "weights": [1.0]}, sort_keys=True)
    assert _hash_spec(s1) == _hash_spec(s2)
    assert len(_hash_spec(s1)) == 12


def test_hash_spec_differs_for_different_specs():
    s1 = json.dumps({"features": ["a"], "weights": [1.0]}, sort_keys=True)
    s2 = json.dumps({"features": ["b"], "weights": [1.0]}, sort_keys=True)
    assert _hash_spec(s1) != _hash_spec(s2)


# ── record_study ────────────────────────────────────────────────────────────


def test_record_study_stores_metadata(tmp_db):
    arch = RCMArchive(tmp_db)
    arch.record_study(
        study_id="run-A",
        lineage_tag="post-2026-04-24-rcm-v1",
        objective_weights={"w_ir": 1.0, "w_turnover": 0.5},
        panel_description="79-sym × 4y",
    )
    import sqlite3
    with sqlite3.connect(str(tmp_db)) as conn:
        row = conn.execute(
            "SELECT study_id, lineage_tag, panel_description, "
            "objective_weights_json FROM rcm_studies WHERE study_id=?",
            ("run-A",),
        ).fetchone()
    assert row[0] == "run-A"
    assert row[1] == "post-2026-04-24-rcm-v1"
    assert row[2] == "79-sym × 4y"
    assert json.loads(row[3])["w_ir"] == 1.0


def test_record_study_is_idempotent(tmp_db):
    arch = RCMArchive(tmp_db)
    arch.record_study("run-A", "tag-X", {"w_ir": 1.0})
    arch.record_study("run-A", "tag-X", {"w_ir": 1.0})
    import sqlite3
    with sqlite3.connect(str(tmp_db)) as conn:
        cnt = conn.execute(
            "SELECT COUNT(*) FROM rcm_studies WHERE study_id=?",
            ("run-A",),
        ).fetchone()[0]
    assert cnt == 1


# ── insert_trial ─────────────────────────────────────────────────────────────


def test_insert_trial_round_trip(tmp_db, sample_trial):
    arch = RCMArchive(tmp_db)
    arch.record_study("s1", "tag")
    tid = arch.insert_trial(sample_trial, lineage_tag="tag", study_id="s1")
    assert len(tid) == 12
    assert arch.n_trials() == 1
    df = arch.top_k(k=10)
    assert len(df) == 1
    row = df.iloc[0]
    assert row.trial_id == tid
    assert row.study_id == "s1"
    assert row.lineage_tag == "tag"
    assert row.n_features == 3
    assert row.n_families == 3
    assert abs(row.objective - 0.45) < 1e-10
    assert row.features_csv == "rel_spy_20d,range_pos_252d,amihud_20d"


def test_insert_trial_dedups_by_spec_hash(tmp_db, sample_trial):
    """Same spec twice → only one row (REPLACE)."""
    arch = RCMArchive(tmp_db)
    arch.record_study("s1", "tag")
    arch.insert_trial(sample_trial, lineage_tag="tag", study_id="s1")
    # Re-insert same spec (different metrics) — should replace
    m2 = CompositeMetrics(
        n_features=3, n_families=3, n_dates=150,
        ic_mean=0.05, ic_std=0.06, ic_ir=0.9,
        turnover_proxy=0.08, corr_concentration=0.10,
    )
    replay = TrialResult(spec=sample_trial.spec, metrics=m2, objective=0.77)
    arch.insert_trial(replay, lineage_tag="tag", study_id="s1")
    assert arch.n_trials() == 1
    df = arch.top_k(k=10)
    assert abs(df.iloc[0].objective - 0.77) < 1e-10  # latest metrics kept


def test_insert_trial_nan_fields_become_null(tmp_db):
    """NaN ic_std / turnover / corr_concentration → NULL in DB (not 'nan' string)."""
    spec = ResearchCompositeSpec(
        features=("rel_spy_20d",), weights=(1.0,),
        family_counts={"A": 1, "B": 1, "C": 1},
    )
    m = CompositeMetrics(
        n_features=1, n_families=3, n_dates=5,
        ic_mean=float("nan"), ic_std=float("nan"), ic_ir=float("nan"),
        turnover_proxy=float("nan"), corr_concentration=float("nan"),
    )
    tr = TrialResult(spec=spec, metrics=m, objective=float("nan"))
    arch = RCMArchive(tmp_db)
    arch.record_study("s1", "tag")
    arch.insert_trial(tr, lineage_tag="tag", study_id="s1")
    import sqlite3
    with sqlite3.connect(str(tmp_db)) as conn:
        row = conn.execute(
            "SELECT ic_std, turnover_proxy, corr_concentration, objective "
            "FROM rcm_trials"
        ).fetchone()
    assert row == (None, None, None, None)


def test_insert_trial_bumps_study_counter(tmp_db, sample_trial):
    arch = RCMArchive(tmp_db)
    arch.record_study("s1", "tag")
    arch.insert_trial(sample_trial, lineage_tag="tag", study_id="s1")
    # Different spec → second row
    spec2 = ResearchCompositeSpec(
        features=("trend_tstat_20d",), weights=(1.0,),
        family_counts={"D": 1, "A": 1, "B": 1},
    )
    tr2 = TrialResult(
        spec=spec2, metrics=sample_trial.metrics, objective=0.2,
    )
    arch.insert_trial(tr2, lineage_tag="tag", study_id="s1")
    import sqlite3
    with sqlite3.connect(str(tmp_db)) as conn:
        cnt = conn.execute(
            "SELECT n_trials_recorded FROM rcm_studies WHERE study_id=?",
            ("s1",),
        ).fetchone()[0]
    assert cnt == 2


# ── top_k + lineage filter ──────────────────────────────────────────────────


def test_top_k_sorts_by_objective_desc(tmp_db):
    arch = RCMArchive(tmp_db)
    arch.record_study("s1", "tag")
    for i, obj in enumerate([0.1, 0.5, 0.3, 0.8, 0.2]):
        spec = ResearchCompositeSpec(
            features=(f"feat_{i}",), weights=(1.0,),
            family_counts={"A": 1, "B": 1, "C": 1},
        )
        m = CompositeMetrics(
            n_features=1, n_families=3, n_dates=10,
            ic_mean=0.01, ic_std=0.02, ic_ir=obj,
            turnover_proxy=0.0, corr_concentration=0.0,
        )
        tr = TrialResult(spec=spec, metrics=m, objective=obj)
        arch.insert_trial(tr, lineage_tag="tag", study_id="s1")
    top = arch.top_k(k=3)
    assert len(top) == 3
    assert list(top.objective) == [0.8, 0.5, 0.3]


def test_top_k_filters_by_lineage(tmp_db):
    arch = RCMArchive(tmp_db)
    arch.record_study("s1", "tag-A")
    arch.record_study("s2", "tag-B")
    # Two trials under tag-A, one under tag-B
    for i, (tag, study, obj) in enumerate(
        [("tag-A", "s1", 0.5), ("tag-A", "s1", 0.3), ("tag-B", "s2", 0.9)]
    ):
        spec = ResearchCompositeSpec(
            features=(f"feat_{i}",), weights=(1.0,),
            family_counts={"A": 1, "B": 1, "C": 1},
        )
        m = CompositeMetrics(
            n_features=1, n_families=3, n_dates=10,
            ic_mean=0.01, ic_std=0.02, ic_ir=obj,
            turnover_proxy=0.0, corr_concentration=0.0,
        )
        arch.insert_trial(
            TrialResult(spec=spec, metrics=m, objective=obj),
            lineage_tag=tag, study_id=study,
        )
    df_a = arch.top_k(k=10, lineage_tag="tag-A")
    assert len(df_a) == 2
    assert all(df_a.lineage_tag == "tag-A")
    df_b = arch.top_k(k=10, lineage_tag="tag-B")
    assert len(df_b) == 1
    assert abs(df_b.iloc[0].objective - 0.9) < 1e-10


def test_lineage_summary(tmp_db):
    arch = RCMArchive(tmp_db)
    arch.record_study("s1", "tag-A")
    arch.record_study("s2", "tag-B")
    for i, (tag, study, obj, ic_ir) in enumerate(
        [("tag-A", "s1", 0.5, 0.6),
         ("tag-A", "s1", 0.3, 0.4),
         ("tag-B", "s2", 0.9, 0.8)]
    ):
        spec = ResearchCompositeSpec(
            features=(f"feat_{i}",), weights=(1.0,),
            family_counts={"A": 1, "B": 1, "C": 1},
        )
        m = CompositeMetrics(
            n_features=1, n_families=3, n_dates=10,
            ic_mean=0.01, ic_std=0.02, ic_ir=ic_ir,
            turnover_proxy=0.0, corr_concentration=0.0,
        )
        arch.insert_trial(
            TrialResult(spec=spec, metrics=m, objective=obj),
            lineage_tag=tag, study_id=study,
        )
    summary = arch.lineage_summary()
    assert len(summary) == 2
    # Sorted by best_objective DESC: tag-B (0.9) first
    assert summary.iloc[0].lineage_tag == "tag-B"
    assert summary.iloc[0].n_trials == 1
    assert abs(summary.iloc[0].best_objective - 0.9) < 1e-10
    assert summary.iloc[1].lineage_tag == "tag-A"
    assert summary.iloc[1].n_trials == 2


def test_top_k_on_empty_archive(tmp_db):
    arch = RCMArchive(tmp_db)
    df = arch.top_k(k=10)
    assert len(df) == 0


# ── ResearchMiner ↔ archive integration ─────────────────────────────────────


@pytest.fixture
def mini_panels():
    np.random.seed(42)
    idx = pd.bdate_range("2024-01-02", periods=40)
    cols = [f"S{i}" for i in range(8)]
    base = pd.DataFrame(np.random.randn(40, 8), index=idx, columns=cols)
    panels = {
        "rel_spy_20d": base + np.random.randn(40, 8) * 0.1,
        "range_pos_252d": base * 0.5 + np.random.randn(40, 8) * 0.5,
        "amihud_20d": pd.DataFrame(
            np.abs(np.random.randn(40, 8)), index=idx, columns=cols,
        ),
        "trend_tstat_20d": pd.DataFrame(
            np.random.randn(40, 8), index=idx, columns=cols,
        ),
    }
    panels = {
        k: (v if isinstance(v, pd.DataFrame)
            else pd.DataFrame(v, index=idx, columns=cols))
        for k, v in panels.items()
    }
    fwd = base * 0.15 + pd.DataFrame(
        np.random.randn(40, 8) * 0.85, index=idx, columns=cols,
    )
    return panels, fwd


@pytest.fixture
def restricted_families():
    return (
        FamilyConfig(name="A", title="A", factors=frozenset({"rel_spy_20d"})),
        FamilyConfig(name="B", title="B", factors=frozenset({"range_pos_252d"})),
        FamilyConfig(name="C", title="C", factors=frozenset({"amihud_20d"})),
        FamilyConfig(name="D", title="D", factors=frozenset({"trend_tstat_20d"})),
    )


def test_miner_requires_lineage_tag_and_study_id_with_archive(
    tmp_db, mini_panels, restricted_families,
):
    panels, fwd = mini_panels
    arch = RCMArchive(tmp_db)
    with pytest.raises(ValueError, match="lineage_tag and study_id"):
        ResearchMiner(
            factor_panel_map=panels, fwd_returns=fwd,
            families=restricted_families, archive=arch,
            # missing lineage_tag and study_id
        )


def test_miner_persists_to_archive_on_run_trial(
    tmp_db, mini_panels, restricted_families,
):
    """Small 3-trial Optuna run writes trials to archive with lineage_tag."""
    optuna = pytest.importorskip("optuna")
    panels, fwd = mini_panels
    arch = RCMArchive(tmp_db)
    miner = ResearchMiner(
        factor_panel_map=panels, fwd_returns=fwd,
        families=restricted_families, min_families=3,
        archive=arch,
        lineage_tag="post-2026-04-24-rcm-v1",
        study_id="rcm-test-01",
    )
    results = miner.mine(n_trials=3, seed=11)
    # At least some trials should have persisted
    assert arch.n_trials(lineage_tag="post-2026-04-24-rcm-v1") >= 1
    df = arch.top_k(k=10, lineage_tag="post-2026-04-24-rcm-v1")
    # Same count of rows as successful trials (no completed-but-not-archived)
    assert len(df) == len(miner.results)
    # All rows have the correct lineage_tag + study_id
    assert all(df.lineage_tag == "post-2026-04-24-rcm-v1")
    assert all(df.study_id == "rcm-test-01")


def test_miner_mine_with_optuna_storage_persists_study(
    tmp_path, mini_panels, restricted_families,
):
    """optuna_storage + study_name persists sampler state across calls."""
    optuna = pytest.importorskip("optuna")
    panels, fwd = mini_panels
    opt_db = tmp_path / "rcm_optuna.db"
    storage = f"sqlite:///{opt_db}"
    miner = ResearchMiner(
        factor_panel_map=panels, fwd_returns=fwd,
        families=restricted_families, min_families=3,
    )
    # First call creates the study
    miner.mine(
        n_trials=2, seed=3,
        optuna_storage=storage, study_name="rcm-resume-test",
    )
    assert opt_db.exists()
    # Second call with load_if_exists=True should resume
    miner2 = ResearchMiner(
        factor_panel_map=panels, fwd_returns=fwd,
        families=restricted_families, min_families=3,
    )
    miner2.mine(
        n_trials=2, seed=3,
        optuna_storage=storage,
        study_name="rcm-resume-test",
        load_if_exists=True,
    )
    # The second miner should see the cumulative trial history via Optuna
    # (optuna's internal view, not miner.results which is per-instance)
    study = optuna.load_study(
        study_name="rcm-resume-test", storage=storage,
    )
    # Two mine() calls × n_trials=2 = at least 4 trials in Optuna study
    assert len(study.trials) >= 4


def test_miner_mine_with_storage_requires_study_name(mini_panels, restricted_families):
    panels, fwd = mini_panels
    miner = ResearchMiner(
        factor_panel_map=panels, fwd_returns=fwd,
        families=restricted_families, min_families=3,
    )
    with pytest.raises(ValueError, match="study_name required"):
        miner.mine(
            n_trials=1, optuna_storage="sqlite:///tmp.db",
            # missing study_name
        )
