"""Tests for MiningArchive lineage tagging (closeout 2026-04-20).

Every trial and promotion is stamped with the archive's `lineage_tag`.
Existing DBs migrate to the default `pre-2026-04-20` so old rows are
clearly distinguishable from post-closeout rows.

Covers:
  1. Fresh archive creates column and applies default
  2. Save eval writes the instance's tag
  3. Migration: a DB with rows missing the column gets it via ALTER
     and existing rows inherit the default
  4. Leaderboard can filter by lineage_tag
  5. Promotions also carry lineage
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pandas as pd

from core.mining.archive import MiningArchive
from core.mining.evaluator import EvalResult


def _tmpdir():
    return Path(tempfile.mkdtemp())


def _make_eval(spec_id: str, tier: str = "A", score: float = 1.0) -> EvalResult:
    r = EvalResult(spec_id=spec_id, strategy_type="multi_factor",
                   params={"x": 1})
    r.passed_quick = True
    r.passed_oos = True
    r.tier = tier
    r.composite_score = score
    return r


class TestSchemaHasLineage:
    def test_fresh_db_has_lineage_column(self):
        d = _tmpdir()
        MiningArchive(db_path=d / "a.db", equity_curve_dir=d / "ec")
        conn = sqlite3.connect(d / "a.db")
        trial_cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(trials)").fetchall()}
        promo_cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(promotions)").fetchall()}
        conn.close()
        assert "lineage_tag" in trial_cols
        assert "lineage_tag" in promo_cols

    def test_qqq_columns_added(self):
        d = _tmpdir()
        MiningArchive(db_path=d / "a.db", equity_curve_dir=d / "ec")
        conn = sqlite3.connect(d / "a.db")
        cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(trials)").fetchall()}
        conn.close()
        for c in ("qqq_full_period_excess", "qqq_holdout_excess",
                  "qqq_oos_avg_excess", "passed_qqq_gate"):
            assert c in cols


class TestLineageWrites:
    def test_save_eval_stamps_instance_tag(self):
        d = _tmpdir()
        arch = MiningArchive(db_path=d / "a.db", equity_curve_dir=d / "ec",
                             lineage_tag="post-test-tag")
        arch.save_eval(_make_eval("x1"))
        conn = sqlite3.connect(d / "a.db")
        (tag,) = conn.execute(
            "SELECT lineage_tag FROM trials WHERE spec_id='x1'"
        ).fetchone()
        conn.close()
        assert tag == "post-test-tag"

    def test_promote_stamps_tag(self):
        d = _tmpdir()
        arch = MiningArchive(db_path=d / "a.db", equity_curve_dir=d / "ec",
                             lineage_tag="post-test-tag")
        arch.promote(_make_eval("x2", tier="S"))
        conn = sqlite3.connect(d / "a.db")
        (tag,) = conn.execute(
            "SELECT lineage_tag FROM promotions WHERE spec_id='x2'"
        ).fetchone()
        conn.close()
        assert tag == "post-test-tag"

    def test_qqq_fields_persisted(self):
        d = _tmpdir()
        arch = MiningArchive(db_path=d / "a.db", equity_curve_dir=d / "ec",
                             lineage_tag="post")
        r = _make_eval("q1")
        r.qqq_full_period_excess = 0.05
        r.qqq_holdout_excess = 0.03
        r.qqq_oos_avg_excess = 0.01
        r.passed_qqq_gate = True
        arch.save_eval(r)
        conn = sqlite3.connect(d / "a.db")
        row = conn.execute(
            "SELECT qqq_full_period_excess, qqq_holdout_excess, "
            "qqq_oos_avg_excess, passed_qqq_gate FROM trials "
            "WHERE spec_id='q1'"
        ).fetchone()
        conn.close()
        assert row == (0.05, 0.03, 0.01, 1)


class TestMigration:
    def test_legacy_db_gets_default_lineage(self):
        """Create an old-schema DB (no lineage_tag column), open via
        MiningArchive, verify migration added column with default."""
        d = _tmpdir()
        db = d / "legacy.db"
        # Minimal old schema: just the base trials columns prior to
        # lineage addition
        conn = sqlite3.connect(db)
        conn.execute("""
            CREATE TABLE trials (
                spec_id TEXT PRIMARY KEY,
                strategy_type TEXT NOT NULL,
                params_json TEXT NOT NULL,
                tier TEXT NOT NULL DEFAULT 'D',
                composite_score REAL NOT NULL DEFAULT 0.0,
                passed_quick INTEGER NOT NULL DEFAULT 0,
                passed_oos INTEGER NOT NULL DEFAULT 0,
                passed_robustness INTEGER NOT NULL DEFAULT 0,
                passed_diversity INTEGER NOT NULL DEFAULT 0,
                evaluated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE promotions (
                spec_id TEXT PRIMARY KEY,
                strategy_type TEXT NOT NULL,
                params_json TEXT NOT NULL,
                tier TEXT NOT NULL,
                composite_score REAL NOT NULL,
                promoted_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            )
        """)
        conn.execute(
            "INSERT INTO trials (spec_id, strategy_type, params_json, "
            "evaluated_at) VALUES ('legacy1', 'x', '{}', '2020-01-01')"
        )
        conn.commit(); conn.close()

        # Open via MiningArchive → migration should run
        _ = MiningArchive(db_path=db, equity_curve_dir=d / "ec",
                          lineage_tag="post-new")

        conn = sqlite3.connect(db)
        (tag,) = conn.execute(
            "SELECT lineage_tag FROM trials WHERE spec_id='legacy1'"
        ).fetchone()
        conn.close()
        assert tag == "pre-2026-04-20"


class TestLineageSummary:
    """lineage_summary() aggregates per-lineage trial stats for the CLI
    leaderboard view (Round 2 Topic B, closeout 2026-04-20)."""

    def test_empty_archive_returns_empty_df(self):
        d = _tmpdir()
        arch = MiningArchive(db_path=d / "empty.db", equity_curve_dir=d / "ec",
                             lineage_tag="tagX")
        df = arch.lineage_summary()
        assert df.empty

    def test_aggregates_two_lineages(self):
        d = _tmpdir()
        db = d / "a.db"
        # Tag A: 3 trials, 2 quick pass, 1 oos pass, 1 holdout pass
        arch_a = MiningArchive(db_path=db, equity_curve_dir=d / "ec",
                               lineage_tag="A")
        r1 = _make_eval("a1"); r1.passed_holdout = True
        r1.qqq_full_period_excess = 0.05; r1.passed_qqq_gate = True
        r1.quick_sharpe = 0.8; r1.oos_ir = 0.4
        arch_a.save_eval(r1)
        r2 = _make_eval("a2"); r2.passed_oos = False
        r2.quick_sharpe = 0.5; r2.oos_ir = -0.2
        arch_a.save_eval(r2)
        r3 = _make_eval("a3"); r3.passed_quick = False; r3.passed_oos = False
        r3.quick_sharpe = 0.1; r3.oos_ir = -0.5
        arch_a.save_eval(r3)

        # Tag B: 2 trials, both quick pass, 0 oos
        arch_b = MiningArchive(db_path=db, equity_curve_dir=d / "ec",
                               lineage_tag="B")
        r4 = _make_eval("b1"); r4.passed_oos = False
        r4.quick_sharpe = 0.6; r4.oos_ir = -0.1
        arch_b.save_eval(r4)
        r5 = _make_eval("b2"); r5.passed_oos = False
        r5.quick_sharpe = 0.7; r5.oos_ir = -0.3
        arch_b.save_eval(r5)

        df = arch_b.lineage_summary()
        # Two rows, sorted by lineage_tag
        assert len(df) == 2
        assert list(df["lineage_tag"]) == ["A", "B"]

        row_a = df[df["lineage_tag"] == "A"].iloc[0]
        assert row_a["n_trials"] == 3
        assert row_a["n_quick_pass"] == 2
        assert row_a["n_oos_pass"] == 1
        assert row_a["n_holdout_pass"] == 1
        assert row_a["n_qqq_gate_pass"] == 1  # r1 has qqq_gate=True with non-NULL excess
        assert row_a["n_gate_evaluated"] == 1  # only r1 reached Stage 6
        assert abs(row_a["worst_oos_ir"] - (-0.5)) < 1e-9
        assert abs(row_a["best_oos_ir"] - 0.4) < 1e-9

        row_b = df[df["lineage_tag"] == "B"].iloc[0]
        assert row_b["n_trials"] == 2
        assert row_b["n_quick_pass"] == 2
        assert row_b["n_oos_pass"] == 0
        assert row_b["n_gate_evaluated"] == 0  # neither reached Stage 6

    def test_gate_evaluated_vs_gate_pass(self):
        """Verify distinction: gate_evaluated = Stage 6 reached;
        gate_pass = Stage 6 reached AND passed_qqq_gate=1. Critical
        for understanding leaderboard semantics when QQQ gate fails."""
        d = _tmpdir()
        arch = MiningArchive(db_path=d / "a.db", equity_curve_dir=d / "ec",
                             lineage_tag="X")
        r_pass = _make_eval("p1")
        r_pass.qqq_full_period_excess = 0.05
        r_pass.passed_qqq_gate = True
        arch.save_eval(r_pass)
        r_fail = _make_eval("f1")
        r_fail.qqq_full_period_excess = -0.03  # lose to QQQ
        r_fail.passed_qqq_gate = False
        arch.save_eval(r_fail)
        r_stage5 = _make_eval("s1")  # never reached Stage 6
        r_stage5.qqq_full_period_excess = None
        r_stage5.passed_qqq_gate = True  # default True when gate disabled
        arch.save_eval(r_stage5)

        df = arch.lineage_summary()
        row = df.iloc[0]
        assert row["n_trials"] == 3
        assert row["n_gate_evaluated"] == 2  # p1 + f1 reached Stage 6
        assert row["n_qqq_gate_pass"] == 1   # only p1 cleared the gate


class TestLeaderboardFilter:
    def test_leaderboard_filters_by_lineage(self):
        d = _tmpdir()
        db = d / "a.db"
        arch_a = MiningArchive(db_path=db, equity_curve_dir=d / "ec",
                               lineage_tag="tagA")
        arch_a.save_eval(_make_eval("specA", score=0.9))
        # Reopen with different tag, add another eval
        arch_b = MiningArchive(db_path=db, equity_curve_dir=d / "ec",
                               lineage_tag="tagB")
        arch_b.save_eval(_make_eval("specB", score=0.5))

        all_df = arch_b.leaderboard(n=10)
        assert {"specA", "specB"} <= set(all_df["spec_id"])
        assert set(all_df["lineage_tag"]) == {"tagA", "tagB"}

        only_b = arch_b.leaderboard(n=10, lineage_tag="tagB")
        assert set(only_b["spec_id"]) == {"specB"}
        assert set(only_b["lineage_tag"]) == {"tagB"}
