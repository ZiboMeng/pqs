"""
Minimal intraday report: fills summary, equity path, drawdown, anomalies.

Reads from PaperTradingEngine's intraday persistence tables.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

import pandas as pd

from core.logging_setup import get_logger

logger = get_logger(__name__)


def generate_intraday_report(db_path: str, run_id: Optional[str] = None) -> str:
    """
    Generate a markdown intraday report from persistence tables.

    Parameters
    ----------
    db_path : path to paper trading SQLite DB
    run_id  : specific run_id to report on; None = latest
    """
    conn = sqlite3.connect(db_path)

    if run_id is None:
        row = conn.execute(
            "SELECT run_id FROM bar_checkpoints ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        if row is None:
            conn.close()
            return "# Intraday Report\n\nNo intraday sessions found."
        run_id = row[0]

    lines = [
        "# Intraday Session Report",
        "",
        f"**Run ID**: {run_id}",
        "",
    ]

    # ── Fills Summary ────────────────────────────────────────────────────────
    fills = pd.read_sql_query(
        "SELECT date, bar_ts, symbol, side, qty, price, slippage_usd, commission_usd, cash_delta "
        "FROM intraday_fills WHERE run_id=? ORDER BY date, bar_ts",
        conn, params=(run_id,),
    )

    lines += ["---", "## 1. Fills Summary", ""]
    if fills.empty:
        lines.append("No fills recorded.")
    else:
        n_buys = int((fills["side"] == "BUY").sum())
        n_sells = int((fills["side"] == "SELL").sum())
        total_volume = float(fills["qty"].abs().sum())
        total_commission = float(fills["commission_usd"].sum())
        total_slippage = float(fills["slippage_usd"].sum())

        lines += [
            f"- 总成交笔数: **{len(fills)}** (买入 {n_buys}, 卖出 {n_sells})",
            f"- 总成交量 (shares): **{total_volume:.0f}**",
            f"- 总佣金: **${total_commission:.2f}**",
            f"- 总滑点: **${total_slippage:.2f}**",
            "",
        ]

        sym_summary = fills.groupby("symbol").agg(
            n_fills=("qty", "count"),
            total_qty=("qty", "sum"),
            avg_price=("price", "mean"),
        ).sort_values("n_fills", ascending=False)
        lines += ["**按标的统计:**", ""]
        lines += ["| 标的 | 成交次数 | 总量 | 均价 |"]
        lines += ["|------|---------|------|------|"]
        for sym, row in sym_summary.iterrows():
            lines.append(f"| {sym} | {row['n_fills']:.0f} | {row['total_qty']:.0f} | ${row['avg_price']:.2f} |")
        lines.append("")

    # ── Equity Path ──────────────────────────────────────────────────────────
    equity = pd.read_sql_query(
        "SELECT date, bar_ts, equity, cash, portfolio_value "
        "FROM intraday_equity WHERE run_id=? ORDER BY date, bar_ts",
        conn, params=(run_id,),
    )

    lines += ["---", "## 2. Equity Path", ""]
    if equity.empty:
        lines.append("No equity records.")
    else:
        eq_series = equity["equity"].astype(float)
        start_eq = eq_series.iloc[0]
        end_eq = eq_series.iloc[-1]
        total_ret = (end_eq / start_eq - 1) if start_eq > 0 else 0

        max_eq = eq_series.cummax()
        dd = (eq_series - max_eq) / max_eq
        max_dd = float(dd.min())

        # Drawdown duration
        in_dd = dd < -0.001
        dd_lens = []
        cur = 0
        for v in in_dd:
            if v:
                cur += 1
            else:
                if cur > 0:
                    dd_lens.append(cur)
                cur = 0
        if cur > 0:
            dd_lens.append(cur)

        lines += [
            f"- 起始权益: **${start_eq:,.2f}**",
            f"- 结束权益: **${end_eq:,.2f}**",
            f"- 总收益: **{total_ret:.2%}**",
            f"- 最大回撤: **{max_dd:.2%}**",
            f"- 回撤天数: **{len(dd_lens)} 段, 最长 {max(dd_lens) if dd_lens else 0}**",
            f"- 记录天数: **{len(equity)}**",
            "",
        ]

    # ── Anomalies / Diagnostics ──────────────────────────────────────────────
    lines += ["---", "## 3. 诊断", ""]

    # Check for days with no fills but with target weights
    all_dates = equity["date"].unique() if not equity.empty else []
    fill_dates = fills["date"].unique() if not fills.empty else []
    no_fill_dates = set(all_dates) - set(fill_dates)
    if no_fill_dates:
        lines.append(f"- 无成交天数: **{len(no_fill_dates)}** / {len(all_dates)}")
    else:
        lines.append("- 每个交易日都有成交 ✅")

    # Large single-day moves
    if not equity.empty and len(eq_series) > 1:
        daily_ret = eq_series.pct_change().dropna()
        large_moves = daily_ret[daily_ret.abs() > 0.03]
        if not large_moves.empty:
            lines.append(f"- 大幅日波动 (>3%): **{len(large_moves)} 天**")
        else:
            lines.append("- 无大幅日波动 (>3%) ✅")

    # Checkpoint status
    cp = conn.execute(
        "SELECT last_bar_ts, updated_at FROM bar_checkpoints WHERE run_id=?",
        (run_id,),
    ).fetchone()
    if cp:
        lines.append(f"- 最新 checkpoint: bar={cp[0]}, updated={cp[1]}")
    else:
        lines.append("- 无 checkpoint ⚠️")

    lines.append("")
    conn.close()
    return "\n".join(lines)
