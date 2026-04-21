"""
MiningArchive: 策略挖掘结果持久化（SQLite）。

表结构
------
  trials       : 每次 Optuna trial 的完整评估结果
  promotions   : 已晋升到活跃池的策略（含权益曲线路径）
  leaderboard  : (view) 按 composite_score DESC 排序的 top-N
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from core.logging_setup import get_logger

logger = get_logger(__name__)


_CREATE_TRIALS = """
CREATE TABLE IF NOT EXISTS trials (
    spec_id              TEXT    PRIMARY KEY,
    strategy_type        TEXT    NOT NULL,
    params_json          TEXT    NOT NULL,

    -- Quick eval
    quick_sharpe         REAL,
    quick_max_dd         REAL,
    quick_cagr           REAL,
    passed_quick         INTEGER NOT NULL DEFAULT 0,

    -- OOS eval
    oos_ir               REAL,
    oos_pass_rate        REAL,
    oos_sharpe           REAL,
    oos_excess_return    REAL,
    passed_oos           INTEGER NOT NULL DEFAULT 0,

    -- Robustness
    regime_robust        INTEGER NOT NULL DEFAULT 0,
    cost_robust          INTEGER NOT NULL DEFAULT 0,
    param_robust         INTEGER NOT NULL DEFAULT 0,
    passed_robustness    INTEGER NOT NULL DEFAULT 0,

    -- Stress
    stress_passed        INTEGER NOT NULL DEFAULT 0,
    stress_results_json  TEXT,

    -- Holdout
    holdout_ir           REAL,
    holdout_excess_return REAL,
    holdout_max_dd       REAL,
    passed_holdout       INTEGER NOT NULL DEFAULT 0,

    -- Overfit
    oos_is_sharpe_ratio  REAL,

    -- Overall
    tier                 TEXT    NOT NULL DEFAULT 'D',
    composite_score      REAL    NOT NULL DEFAULT 0.0,
    diversity_corr       REAL,
    passed_diversity     INTEGER NOT NULL DEFAULT 0,

    evaluated_at         TEXT    NOT NULL,
    optuna_value         REAL,

    -- QQQ hard gate (P0.4, 2026-04-20)
    qqq_full_period_excess  REAL,
    qqq_holdout_excess      REAL,
    qqq_oos_avg_excess      REAL,
    passed_qqq_gate         INTEGER NOT NULL DEFAULT 1,

    -- Lineage (closeout 2026-04-20). Marks which code/config generation
    -- produced this row. Prevents silent mixing of pre-fix and post-fix
    -- results when comparing scores across runs.
    lineage_tag          TEXT    NOT NULL DEFAULT 'pre-2026-04-20'
)
"""

_CREATE_PROMOTIONS = """
CREATE TABLE IF NOT EXISTS promotions (
    spec_id          TEXT PRIMARY KEY,
    strategy_type    TEXT NOT NULL,
    params_json      TEXT NOT NULL,
    tier             TEXT NOT NULL,
    composite_score  REAL NOT NULL,
    equity_curve_path TEXT,
    promoted_at      TEXT NOT NULL,
    active           INTEGER NOT NULL DEFAULT 1,

    -- Lineage (closeout 2026-04-20)
    lineage_tag      TEXT NOT NULL DEFAULT 'pre-2026-04-20'
)
"""


class MiningArchive:
    """
    SQLite 持久化存档。

    Parameters
    ----------
    db_path          : SQLite 数据库路径（自动创建父目录）
    equity_curve_dir : 存放权益曲线 Parquet 文件的目录
    """

    def __init__(
        self,
        db_path:          str | Path = "data/mining/archive.db",
        equity_curve_dir: str | Path = "data/mining/equity_curves",
        lineage_tag:      str = "pre-2026-04-20",
    ) -> None:
        """lineage_tag (closeout 2026-04-20): stamps every save_eval /
        promote with a tag identifying which code generation wrote it.
        Pre-fix rows in an existing DB inherit 'pre-2026-04-20' via the
        ALTER TABLE DEFAULT. Callers running the post-closeout code
        should pass `post-2026-04-20-closeout` (or later) so leaderboard
        / analysis can filter or join across generations. Never mix
        scores across lineage tags without explicit intent."""
        self._db   = Path(db_path)
        self._ec_dir = Path(equity_curve_dir)
        self._lineage_tag = lineage_tag
        self._db.parent.mkdir(parents=True, exist_ok=True)
        self._ec_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ── Write ─────────────────────────────────────────────────────────────────

    def save_eval(self, result: "EvalResult") -> None:  # type: ignore[name-defined]
        """保存或更新单次评估结果。"""
        import json as _json
        stress_json = _json.dumps(result.stress_results) if hasattr(result, 'stress_results') else None
        conn = self._connect()
        conn.execute(
            """INSERT OR REPLACE INTO trials (
                spec_id, strategy_type, params_json,
                quick_sharpe, quick_max_dd, quick_cagr, passed_quick,
                oos_ir, oos_pass_rate, oos_sharpe, oos_excess_return, passed_oos,
                regime_robust, cost_robust, param_robust, passed_robustness,
                stress_passed, stress_results_json,
                holdout_ir, holdout_excess_return, holdout_max_dd, passed_holdout,
                oos_is_sharpe_ratio,
                tier, composite_score, diversity_corr, passed_diversity,
                evaluated_at, optuna_value,
                qqq_full_period_excess, qqq_holdout_excess, qqq_oos_avg_excess,
                passed_qqq_gate, lineage_tag
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                result.spec_id,
                result.strategy_type,
                json.dumps(result.params),
                result.quick_sharpe,
                result.quick_max_dd,
                result.quick_cagr,
                int(result.passed_quick),
                result.oos_ir,
                result.oos_pass_rate,
                result.oos_sharpe,
                result.oos_excess_return,
                int(result.passed_oos),
                int(result.regime_robust),
                int(result.cost_robust),
                int(result.param_robust),
                int(result.passed_robustness),
                int(getattr(result, 'stress_passed', False)),
                stress_json,
                getattr(result, 'holdout_ir', None),
                getattr(result, 'holdout_excess_return', None),
                getattr(result, 'holdout_max_dd', None),
                int(getattr(result, 'passed_holdout', False)),
                getattr(result, 'oos_is_sharpe_ratio', None),
                result.tier,
                result.composite_score,
                result.diversity_corr,
                int(result.passed_diversity),
                result.evaluated_at or datetime.now().isoformat(),
                result.composite_score,
                getattr(result, 'qqq_full_period_excess', None),
                getattr(result, 'qqq_holdout_excess', None),
                getattr(result, 'qqq_oos_avg_excess', None),
                int(getattr(result, 'passed_qqq_gate', True)),
                self._lineage_tag,
            ),
        )
        conn.commit()
        conn.close()
        logger.debug("Archive: saved %s (score=%.3f, tier=%s)", result.spec_id, result.composite_score, result.tier)

    def save_equity_curve(self, spec_id: str, equity: pd.Series) -> Path:
        """保存权益曲线 Parquet，返回文件路径。"""
        path = self._ec_dir / f"{spec_id}.parquet"
        equity.to_frame("equity").to_parquet(path)
        return path

    def promote(
        self,
        result: "EvalResult",  # type: ignore[name-defined]
        equity_curve: Optional[pd.Series] = None,
    ) -> None:
        """将策略晋升到活跃池。"""
        ec_path = None
        if equity_curve is not None:
            ec_path = str(self.save_equity_curve(result.spec_id, equity_curve))

        conn = self._connect()
        conn.execute(
            """INSERT OR REPLACE INTO promotions (
                spec_id, strategy_type, params_json, tier, composite_score,
                equity_curve_path, promoted_at, active, lineage_tag
            ) VALUES (?,?,?,?,?,?,?,1,?)""",
            (
                result.spec_id,
                result.strategy_type,
                json.dumps(result.params),
                result.tier,
                result.composite_score,
                ec_path,
                datetime.now().isoformat(),
                self._lineage_tag,
            ),
        )
        conn.commit()
        conn.close()
        logger.info("Archive: promoted %s (tier=%s, score=%.3f)", result.spec_id, result.tier, result.composite_score)

    def deactivate(self, spec_id: str) -> None:
        """将策略标记为不活跃（软删除）。"""
        conn = self._connect()
        conn.execute("UPDATE promotions SET active=0 WHERE spec_id=?", (spec_id,))
        conn.commit()
        conn.close()

    # ── Read ──────────────────────────────────────────────────────────────────

    def has_spec(self, spec_id: str) -> bool:
        """检查 spec_id 是否已评估过。"""
        conn = self._connect()
        row  = conn.execute("SELECT 1 FROM trials WHERE spec_id=?", (spec_id,)).fetchone()
        conn.close()
        return row is not None

    def get_score(self, spec_id: str) -> float:
        """获取已存档的 composite_score（未找到返回 -999）。"""
        conn  = self._connect()
        row   = conn.execute("SELECT composite_score FROM trials WHERE spec_id=?", (spec_id,)).fetchone()
        conn.close()
        return float(row[0]) if row else -999.0

    def get_promoted(self, active_only: bool = True) -> List[Dict]:
        """返回活跃晋升策略列表，按 composite_score DESC。"""
        conn = self._connect()
        where = "WHERE active=1" if active_only else ""
        rows  = conn.execute(
            f"SELECT spec_id, strategy_type, params_json, tier, composite_score, equity_curve_path "
            f"FROM promotions {where} ORDER BY composite_score DESC"
        ).fetchall()
        conn.close()
        return [
            {
                "spec_id":          r[0],
                "strategy_type":    r[1],
                "params":           json.loads(r[2]),
                "tier":             r[3],
                "composite_score":  r[4],
                "equity_curve_path": r[5],
            }
            for r in rows
        ]

    def load_promoted_equity_curves(self) -> Dict[str, pd.Series]:
        """加载所有活跃晋升策略的权益曲线（spec_id → Series）。"""
        promoted = self.get_promoted()
        curves: Dict[str, pd.Series] = {}
        for p in promoted:
            path = p.get("equity_curve_path")
            if path and Path(path).exists():
                df = pd.read_parquet(path)
                curves[p["spec_id"]] = df["equity"]
        return curves

    def leaderboard(self, n: int = 20, strategy_type: Optional[str] = None,
                    lineage_tag: Optional[str] = None) -> pd.DataFrame:
        """返回 top-N 策略排行榜 DataFrame.

        `lineage_tag` filters to a single code/config generation
        (closeout 2026-04-20). Omit to include all lineages (but a
        'lineage' column is always returned so downstream can spot
        mixing)."""
        conn    = self._connect()
        clauses = []
        params: list = []
        if strategy_type:
            clauses.append("strategy_type=?")
            params.append(strategy_type)
        if lineage_tag:
            clauses.append("lineage_tag=?")
            params.append(lineage_tag)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        df    = pd.read_sql_query(
            f"""SELECT spec_id, strategy_type, tier, composite_score,
                       quick_sharpe, oos_ir, oos_pass_rate, oos_excess_return,
                       quick_max_dd, regime_robust, cost_robust, param_robust,
                       stress_passed, holdout_ir, holdout_excess_return,
                       passed_holdout, oos_is_sharpe_ratio,
                       passed_quick, passed_oos,
                       passed_qqq_gate, qqq_full_period_excess,
                       qqq_holdout_excess, qqq_oos_avg_excess,
                       lineage_tag,
                       evaluated_at
                FROM trials {where}
                ORDER BY composite_score DESC LIMIT {n}""",
            conn, params=params,
        )
        conn.close()
        return df

    def stats(self) -> Dict[str, int]:
        """返回存档统计（各阶段通过数量）。"""
        conn = self._connect()
        total   = conn.execute("SELECT COUNT(*) FROM trials").fetchone()[0]
        quick   = conn.execute("SELECT COUNT(*) FROM trials WHERE passed_quick=1").fetchone()[0]
        oos     = conn.execute("SELECT COUNT(*) FROM trials WHERE passed_oos=1").fetchone()[0]
        robust  = conn.execute("SELECT COUNT(*) FROM trials WHERE passed_robustness=1").fetchone()[0]
        promo   = conn.execute("SELECT COUNT(*) FROM promotions WHERE active=1").fetchone()[0]
        conn.close()
        return {
            "total_evaluated": total,
            "passed_quick":    quick,
            "passed_oos":      oos,
            "passed_robustness": robust,
            "promoted_active": promo,
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db)

    def _init_db(self) -> None:
        conn = self._connect()
        conn.execute(_CREATE_TRIALS)
        conn.execute(_CREATE_PROMOTIONS)
        conn.commit()
        self._migrate_db(conn)
        conn.close()

    @staticmethod
    def _migrate_db(conn: sqlite3.Connection) -> None:
        """Add columns introduced in Round 1 if they don't exist yet."""
        existing = {row[1] for row in conn.execute("PRAGMA table_info(trials)").fetchall()}
        migrations = [
            ("stress_passed",       "INTEGER NOT NULL DEFAULT 0"),
            ("stress_results_json", "TEXT"),
            ("holdout_ir",          "REAL"),
            ("holdout_excess_return","REAL"),
            ("holdout_max_dd",      "REAL"),
            ("passed_holdout",      "INTEGER NOT NULL DEFAULT 0"),
            ("oos_is_sharpe_ratio", "REAL"),
            # 2026-04-20 closeout
            ("qqq_full_period_excess", "REAL"),
            ("qqq_holdout_excess",     "REAL"),
            ("qqq_oos_avg_excess",     "REAL"),
            ("passed_qqq_gate",        "INTEGER NOT NULL DEFAULT 1"),
            ("lineage_tag",            "TEXT NOT NULL DEFAULT 'pre-2026-04-20'"),
        ]
        for col, typedef in migrations:
            if col not in existing:
                conn.execute(f"ALTER TABLE trials ADD COLUMN {col} {typedef}")

        # Same lineage migration for promotions table
        existing_p = {row[1] for row in conn.execute(
            "PRAGMA table_info(promotions)").fetchall()}
        if "lineage_tag" not in existing_p:
            conn.execute(
                "ALTER TABLE promotions ADD COLUMN lineage_tag TEXT "
                "NOT NULL DEFAULT 'pre-2026-04-20'"
            )
        conn.commit()
