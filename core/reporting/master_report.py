"""
MasterReport: 统一主报告数据结构。

职责
----
- 汇集各模块输出（策略绩效 / 滚动回测 / 因子 / 宇宙 / 模拟盘）
- 提供 to_dict() / to_markdown() 两种序列化格式
- save(path, fmt) 写入磁盘（markdown / json）
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


# ── 格式化工具 ────────────────────────────────────────────────────────────────

def _fmt_pct(v: Optional[float]) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "N/A"
    return f"{v:+.2%}"


def _fmt_f2(v: Optional[float]) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "N/A"
    return f"{v:.2f}"


def _fmt_f3(v: Optional[float]) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "N/A"
    return f"{v:.3f}"


def _fmt_usd(v: Optional[float]) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "N/A"
    return f"${v:,.2f}"


# ── MasterReport ─────────────────────────────────────────────────────────────

@dataclass
class MasterReport:
    """
    统一主报告。

    各 section 均为可选 dict，对应 MasterReportBuilder 注入的数据。
    未注入的 section 为 None，to_markdown() 会跳过对应章节。

    Sections
    --------
    performance     : BacktestResult 绩效指标
    rolling_windows : 滚动窗口分析汇总
    acceptance      : Tier D 验收结果
    factor_summary  : 因子层级分布与 Top 因子
    universe_status : 投资宇宙当前状态
    paper_trading   : 模拟盘 P&L 状态
    risk_summary    : 综合风险摘要
    """

    generated_at:    pd.Timestamp
    performance:     Optional[Dict] = None
    rolling_windows: Optional[Dict] = None
    acceptance:      Optional[Dict] = None
    factor_summary:  Optional[Dict] = None
    universe_status: Optional[Dict] = None
    paper_trading:   Optional[Dict] = None
    risk_summary:    Optional[Dict] = None

    # ── 序列化 ────────────────────────────────────────────────────────────────

    def to_dict(self) -> Dict:
        return {
            "generated_at":    str(self.generated_at),
            "performance":     self.performance,
            "rolling_windows": self.rolling_windows,
            "acceptance":      self.acceptance,
            "factor_summary":  self.factor_summary,
            "universe_status": self.universe_status,
            "paper_trading":   self.paper_trading,
            "risk_summary":    self.risk_summary,
        }

    def to_markdown(self) -> str:
        """生成结构化 Markdown 报告字符串。"""
        ts = self.generated_at.strftime("%Y-%m-%d %H:%M:%S")
        lines: List[str] = [
            "# PQS Master Report",
            "",
            f"**生成时间**: {ts}",
            "",
        ]

        section_idx = 0

        # ── 1. 策略绩效 ───────────────────────────────────────────────────────
        if self.performance is not None:
            section_idx += 1
            p = self.performance
            lines += [
                "---",
                f"## {section_idx}. 策略绩效",
                "",
                "| 指标 | 值 |",
                "|------|---|",
                f"| 总收益 | {_fmt_pct(p.get('total_return'))} |",
                f"| CAGR | {_fmt_pct(p.get('cagr'))} |",
                f"| Sharpe | {_fmt_f2(p.get('sharpe'))} |",
                f"| Sortino | {_fmt_f2(p.get('sortino'))} |",
                f"| 最大回撤 | {_fmt_pct(p.get('max_drawdown'))} |",
                f"| Calmar | {_fmt_f2(p.get('calmar'))} |",
                f"| 年化波动率 | {_fmt_pct(p.get('volatility'))} |",
                f"| 交易笔数 | {p.get('n_trades', 'N/A')} |",
                "",
            ]
            if p.get("alpha") is not None:
                lines += [
                    "**相对 Benchmark**",
                    "",
                    "| 指标 | 值 |",
                    "|------|---|",
                    f"| Alpha | {_fmt_pct(p.get('alpha'))} |",
                    f"| Beta | {_fmt_f2(p.get('beta'))} |",
                    f"| Tracking Error | {_fmt_pct(p.get('tracking_error'))} |",
                    f"| IR | {_fmt_f2(p.get('ir'))} |",
                    "",
                ]

        # ── 2. 滚动窗口分析 ───────────────────────────────────────────────────
        if self.rolling_windows is not None:
            section_idx += 1
            rw = self.rolling_windows
            lines += [
                "---",
                f"## {section_idx}. 滚动窗口分析",
                "",
                f"- 窗口数量: **{rw.get('n_windows', 0)}**",
                f"- 正收益窗口占比 (胜率): **{rw.get('win_rate_pct', 0):.1f}%**",
                f"- 平均 CAGR: **{_fmt_pct(rw.get('avg_cagr'))}**",
                f"- 平均 Sharpe: **{_fmt_f2(rw.get('avg_sharpe'))}**",
                "",
            ]
            table = rw.get("windows_table", [])
            if table:
                lines += [
                    "| 窗口 | 测试起始 | 测试结束 | CAGR | Sharpe | Max DD |",
                    "|------|---------|---------|------|--------|--------|",
                ]
                for row in table:
                    lines.append(
                        f"| {row['id']} | {row['start']} | {row['end']} | "
                        f"{_fmt_pct(row.get('cagr'))} | "
                        f"{_fmt_f2(row.get('sharpe'))} | "
                        f"{_fmt_pct(row.get('max_drawdown'))} |"
                    )
                lines.append("")

        # ── 3. Tier D 验收 ────────────────────────────────────────────────────
        if self.acceptance is not None:
            section_idx += 1
            a = self.acceptance
            badge = "✅ PASS" if a.get("passed") else "❌ FAIL"
            lines += [
                "---",
                f"## {section_idx}. Tier D 验收",
                "",
                f"**结果: {badge}**",
                "",
                "| 指标 | 值 | 要求 |",
                "|------|------|------|",
                f"| 超额收益 | {_fmt_pct(a.get('excess_return'))} | > +5% |",
                f"| IR | {_fmt_f2(a.get('ir'))} | > 0.3 |",
                f"| DD 倍数 | {_fmt_f2(a.get('dd_ratio'))}x | ≤ 1.5x |",
                "",
            ]
            if a.get("failed_criteria"):
                lines += [f"**未通过项**: {', '.join(a['failed_criteria'])}", ""]

        # ── 4. 因子研究 ───────────────────────────────────────────────────────
        if self.factor_summary is not None:
            section_idx += 1
            fs = self.factor_summary
            td = fs.get("tier_distribution", {})
            tier_str = "  ".join(
                f"{k}={v}" for k, v in sorted(td.items())
            )
            lines += [
                "---",
                f"## {section_idx}. 因子研究摘要",
                "",
                f"- 因子总数: **{fs.get('n_factors', 0)}**",
                f"- 层级分布: {tier_str or '无'}",
                "",
            ]
            top = fs.get("top_factors", [])
            if top:
                lines += [
                    "| 因子名 | 层级 | IR | 平均 IC |",
                    "|--------|------|----|---------|",
                ]
                for f in top:
                    lines.append(
                        f"| {f.get('name', '—')} | {f.get('tier', '—')} | "
                        f"{_fmt_f2(f.get('ir'))} | {_fmt_f3(f.get('mean_ic'))} |"
                    )
                lines.append("")

        # ── 5. 投资宇宙 ───────────────────────────────────────────────────────
        if self.universe_status is not None:
            section_idx += 1
            u = self.universe_status
            syms = u.get("active_symbols", [])
            lines += [
                "---",
                f"## {section_idx}. 投资宇宙",
                "",
                f"- 候选标的: **{u.get('n_candidates', 0)}**",
                f"- 活跃标的: **{u.get('n_active', 0)}**",
                f"- 活跃列表: {', '.join(syms) if syms else '（空）'}",
                "",
            ]

        # ── 6. 模拟盘状态 ─────────────────────────────────────────────────────
        if self.paper_trading is not None:
            section_idx += 1
            pt = self.paper_trading
            ks_badge = "🚨 已触发" if pt.get("kill_switch") else "✅ 正常"
            lines += [
                "---",
                f"## {section_idx}. 模拟盘状态",
                "",
                "| 指标 | 值 |",
                "|------|---|",
                f"| 运行天数 | {pt.get('n_days', 0)} |",
                f"| 最新权益 | {_fmt_usd(pt.get('latest_equity'))} |",
                f"| 累计收益 | {_fmt_pct(pt.get('total_return'))} |",
                f"| 最大回撤 | {_fmt_pct(pt.get('max_drawdown'))} |",
                f"| 当前回撤 | {_fmt_pct(pt.get('running_drawdown'))} |",
                f"| Sharpe | {_fmt_f2(pt.get('sharpe'))} |",
                f"| 总交易笔数 | {pt.get('total_trades', 0)} |",
                f"| 总成本 | {_fmt_usd(pt.get('total_cost_usd'))} |",
                f"| Kill Switch | {ks_badge} |",
                "",
            ]

        # ── 7. 风险摘要 ───────────────────────────────────────────────────────
        if self.risk_summary is not None:
            section_idx += 1
            r = self.risk_summary
            ks_status = "🚨 已触发" if r.get("kill_switch_triggered") else "✅ 正常"
            lines += [
                "---",
                f"## {section_idx}. 风险摘要",
                "",
                f"- 历史最大回撤: **{_fmt_pct(r.get('max_drawdown'))}**",
                f"- 当前回撤: **{_fmt_pct(r.get('current_drawdown'))}**",
                f"- Kill Switch: **{ks_status}**",
                "",
            ]

        return "\n".join(lines)

    def save(self, path: str | Path, fmt: str = "markdown") -> None:
        """
        将报告写入磁盘。

        Parameters
        ----------
        path : 输出路径（扩展名会被强制替换为 .md 或 .json）
        fmt  : "markdown"（默认）或 "json"
        """
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)

        if fmt == "markdown":
            out = p.with_suffix(".md")
            out.write_text(self.to_markdown(), encoding="utf-8")
        elif fmt == "json":
            out = p.with_suffix(".json")
            out.write_text(
                json.dumps(self.to_dict(), default=str, indent=2),
                encoding="utf-8",
            )
        else:
            raise ValueError(f"不支持的格式: {fmt!r}（支持 'markdown' / 'json'）")
