#!/usr/bin/env python3
"""
scripts/generate_report.py — 独立生成主报告（无需重跑回测）。

从 ArtifactManager 最近一次 backtest run 加载结果，生成 MasterReport。

用法
----
    python scripts/generate_report.py                     # 最新 backtest run
    python scripts/generate_report.py --from-run 20240115_143022  # 指定 run
    python scripts/generate_report.py --format json       # 输出 json 而非 md
    python scripts/generate_report.py --paper-status      # 包含模拟盘状态
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config.loader import load_config
from core.paper_trading.paper_trading_engine import PaperTradingEngine
from core.paper_trading.pnl_tracker import PnLTracker
from core.execution.cost_model import CostModel
from core.risk.kill_switch import KillSwitch, KillSwitchConfig
from core.mining.archive import MiningArchive
from core.reporting.master_report_builder import MasterReportBuilder
from core.logging_setup import setup_logging, get_logger

setup_logging()
logger = get_logger("generate_report")


def main():
    parser = argparse.ArgumentParser(description="PQS 报告生成器")
    parser.add_argument("--format",       choices=["md", "json"], default="md")
    parser.add_argument("--paper-status", action="store_true", help="包含模拟盘状态")
    parser.add_argument("--output",       default=None, help="输出文件路径")
    parser.add_argument("--config-dir",   default="config")
    parser.add_argument("--db-path",      default="data/paper_trading/pt.db")
    args = parser.parse_args()

    cfg = load_config(Path(args.config_dir))

    builder = MasterReportBuilder()

    # ── 模拟盘状态（可选） ────────────────────────────────────────────────────
    if args.paper_status:
        try:
            cost_model  = CostModel(cfg.cost_model)
            pnl_tracker = PnLTracker()
            engine = PaperTradingEngine(
                cost_model      = cost_model,
                pnl_tracker     = pnl_tracker,
                db_path         = args.db_path,
                initial_capital = cfg.system.account.initial_capital_usd,
            )
            summary = engine.get_pnl_summary()
            builder.set_paper_trading(
                equity         = engine.get_equity(),
                total_return   = summary.get("total_return", 0),
                max_drawdown   = summary.get("max_drawdown", 0),
                sharpe         = summary.get("sharpe"),
                n_days         = summary.get("n_days", 0),
                kill_switch    = engine.is_kill_switch_triggered,
            )
            logger.info("模拟盘状态已加载")
        except Exception as exc:
            logger.warning("加载模拟盘状态失败: %s", exc)

    # ── Mining 排行榜（可选） ────────────────────────────────────────────────
    mining_archive_db = "data/mining/archive.db"
    if Path(mining_archive_db).exists():
        try:
            archive = MiningArchive(db_path=mining_archive_db)
            promoted = archive.get_promoted()
            stats    = archive.stats()
            builder.set_factors(
                factor_summary = [
                    {"strategy": p["strategy_type"], "tier": p["tier"],
                     "score": p["composite_score"], "spec_id": p["spec_id"]}
                    for p in promoted
                ]
            )
            logger.info("Mining 结果已加载 (%d 个晋升策略)", len(promoted))
        except Exception as exc:
            logger.warning("加载 Mining 存档失败: %s", exc)

    report      = builder.build()
    output_path = args.output or f"reports/master_report.{args.format}"
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    report.save(output_path)
    logger.info("报告已保存: %s", output_path)

    if args.format == "md":
        print(report.to_markdown())


if __name__ == "__main__":
    main()
