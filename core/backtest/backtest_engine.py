"""
BacktestEngine: 日线级别向量化回测引擎。

设计原则
--------
- 无 look-ahead：信号由 T 日收盘数据生成，T+1 日开盘成交
- Long-only / no-margin：硬约束（与 RiskConfig 一致）
- 成本：通过 ExecutionSimulator + CostModel 统一应用
- 再平衡：每日根据目标权重与当前权重之差生成订单

核心概念
--------
  signals_df     : DataFrame，index=日期，columns=symbol，值=目标权重 [0, 1]
                   （已考虑 regime / confluence 过滤后的最终目标权重）
  price_df       : DataFrame，index=日期，columns=symbol，值=OHLCV close
  open_df        : DataFrame，index=日期，columns=symbol，值=next-day open
  vix_series     : pd.Series，index=日期，值=VIX 收盘价（用于压力倍数）

输出
----
  BacktestResult : 权益曲线、持仓历史、交易记录、绩效指标
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from core.execution.cost_model import CostModel
from core.execution.execution_simulator import (
    ExecutionSimulator, Fill, Order, OrderSide,
)
from core.logging_setup import get_logger

logger = get_logger(__name__)

_DEFAULT_VIX = 15.0


# ── 结果数据类 ────────────────────────────────────────────────────────────────

@dataclass
class BacktestResult:
    """回测输出。"""
    equity_curve:    pd.Series              # index=日期，值=组合总价值
    positions:       pd.DataFrame           # index=日期，columns=symbol，值=持股数
    weights:         pd.DataFrame           # index=日期，columns=symbol，值=权重
    cash_curve:      pd.Series              # index=日期，值=现金余额
    trades:          List[Fill]             # 所有成交记录
    metrics:         Dict[str, float] = field(default_factory=dict)

    @property
    def n_trades(self) -> int:
        return len(self.trades)

    @property
    def total_commission_usd(self) -> float:
        return sum(f.cost_breakdown.commission_usd for f in self.trades)

    @property
    def total_slippage_usd(self) -> float:
        return sum(f.cost_breakdown.slippage_usd for f in self.trades)

    def __repr__(self) -> str:
        if self.equity_curve.empty:
            return "BacktestResult(empty)"
        final  = self.equity_curve.iloc[-1]
        start  = self.equity_curve.iloc[0]
        ret    = (final / start - 1) * 100
        mdd    = self.metrics.get("max_drawdown", float("nan"))
        sharpe = self.metrics.get("sharpe", float("nan"))
        return (
            f"BacktestResult("
            f"return={ret:.1f}%, "
            f"max_dd={mdd:.1%}, "
            f"sharpe={sharpe:.2f}, "
            f"trades={self.n_trades})"
        )


# ── BacktestEngine ────────────────────────────────────────────────────────────

class BacktestEngine:
    """
    日线级别回测引擎。

    Parameters
    ----------
    cost_model      : CostModel 实例
    initial_capital : 初始资金（USD）
    min_trade_usd   : 低于此金额的交易忽略（避免频繁小额换仓）
    rebalance_threshold : 权重偏离超过此阈值才触发换仓（0.02 = 2%）
    """

    def __init__(
        self,
        cost_model:            CostModel,
        initial_capital:       float = 100_000.0,
        min_trade_usd:         float = 100.0,
        rebalance_threshold:   float = 0.02,
    ):
        self._cost      = cost_model
        self._sim       = ExecutionSimulator(cost_model, freq="interday", allow_partial=True)
        self._capital   = initial_capital
        self._min_trade = min_trade_usd
        self._rebal_thr = rebalance_threshold

    # ── 主入口 ────────────────────────────────────────────────────────────────

    def run(
        self,
        signals_df:       pd.DataFrame,
        price_df:         pd.DataFrame,
        open_df:          Optional[pd.DataFrame] = None,
        vix_series:       Optional[pd.Series] = None,
        regime_series:    Optional[pd.Series] = None,
        benchmark_series: Optional[pd.Series] = None,
    ) -> BacktestResult:
        """
        执行回测。

        Parameters
        ----------
        signals_df    : 目标权重矩阵（T日信号，T+1成交）
        price_df      : 收盘价矩阵（用于计算组合市值）
        open_df       : 次日开盘价矩阵；若为 None，则使用 T+1 收盘价代替
        vix_series    : VIX 日序列；若为 None，则使用默认值 15.0
        regime_series : RegimeState 字符串序列（可选）；
                        按当前 regime 约束最大总敞口（Q5-C：BacktestEngine 层 regime 感知）
        """
        # 对齐所有日期轴
        dates = signals_df.index.intersection(price_df.index)
        if len(dates) == 0:
            logger.warning("BacktestEngine.run: no overlapping dates — returning empty result")
            return _empty_result()

        signals  = signals_df.loc[dates]
        prices   = price_df.loc[dates]

        # Regime 总敞口约束（Q5-C）：按当前 regime 缩放信号权重
        if regime_series is not None:
            signals = _apply_regime_exposure_cap(signals, regime_series)

        # open_df：若无则 fallback 到 close（T+1 close，轻微 look-ahead 但用于近似）
        if open_df is not None:
            opens = open_df.reindex(dates, method="ffill")
        else:
            opens = prices.shift(-1)   # T+1 close 近似

        vix = vix_series.reindex(dates, method="ffill").fillna(_DEFAULT_VIX) \
              if vix_series is not None \
              else pd.Series(_DEFAULT_VIX, index=dates)

        # ── 状态初始化 ────────────────────────────────────────────────────────
        cash:     float = self._capital
        shares:   Dict[str, float] = {}      # symbol → 持股数
        equity_records:   list = []
        weight_records:   list = []
        position_records: list = []
        cash_records:     list = []
        all_fills:        List[Fill] = []

        # ── 逐日迭代 ──────────────────────────────────────────────────────────
        for i, date in enumerate(dates):
            # 1. 当日市值计算（用当日 close）
            price_row = prices.loc[date]
            portfolio_value = cash + sum(
                shares.get(sym, 0) * price_row.get(sym, 0)
                for sym in shares
            )

            # 2. 当日权重快照（市值权重）
            cur_weights: Dict[str, float] = {}
            if portfolio_value > 0:
                for sym, qty in shares.items():
                    p = price_row.get(sym, 0)
                    cur_weights[sym] = (qty * p) / portfolio_value

            # 3. 目标权重（T日信号）
            sig_row = signals.loc[date].fillna(0.0)
            tgt_weights: Dict[str, float] = {
                sym: float(w) for sym, w in sig_row.items() if w > 0
            }

            # 4. 生成换仓订单（若明日有开盘价）
            if i < len(dates) - 1:
                next_date  = dates[i + 1]
                open_row   = opens.loc[next_date] if next_date in opens.index else pd.Series(dtype=float)
                vix_val    = float(vix.loc[date])

                orders = self._generate_orders(
                    cur_weights   = cur_weights,
                    tgt_weights   = tgt_weights,
                    portfolio_val = portfolio_value,
                    price_row     = price_row,
                    open_row      = open_row,
                    signal_date   = date,
                )

                fills = self._sim.simulate_fills(
                    orders      = orders,
                    open_prices = open_row.to_dict(),
                    vix         = vix_val,
                    cash        = cash,
                )

                # 更新持仓与现金
                for fill in fills:
                    prev_qty = shares.get(fill.symbol, 0.0)
                    if fill.side == OrderSide.BUY:
                        shares[fill.symbol] = prev_qty + fill.executed_qty
                    else:
                        shares[fill.symbol] = max(prev_qty - fill.executed_qty, 0.0)
                    cash += fill.cash_delta
                    all_fills.append(fill)

                # 清除零仓位
                shares = {s: q for s, q in shares.items() if q > 1e-6}

            # 5. 记录快照
            equity_records.append(portfolio_value)
            cash_records.append(cash)

            # 权重 & 持仓快照
            all_syms = sorted(set(list(cur_weights) + list(tgt_weights)))
            weight_records.append({s: cur_weights.get(s, 0.0) for s in all_syms})
            position_records.append({s: shares.get(s, 0.0) for s in all_syms})

        # ── 结果封装 ──────────────────────────────────────────────────────────
        equity_curve = pd.Series(equity_records, index=dates, name="equity")
        cash_curve   = pd.Series(cash_records,   index=dates, name="cash")
        weights_df   = pd.DataFrame(weight_records, index=dates).fillna(0.0)
        positions_df = pd.DataFrame(position_records, index=dates).fillna(0.0)

        bench = benchmark_series.reindex(equity_curve.index, method="ffill") if benchmark_series is not None else None
        metrics = compute_metrics(equity_curve, initial_capital=self._capital, benchmark=bench)

        return BacktestResult(
            equity_curve = equity_curve,
            positions    = positions_df,
            weights      = weights_df,
            cash_curve   = cash_curve,
            trades       = all_fills,
            metrics      = metrics,
        )

    # ── 内部方法 ──────────────────────────────────────────────────────────────

    def _generate_orders(
        self,
        cur_weights:   Dict[str, float],
        tgt_weights:   Dict[str, float],
        portfolio_val: float,
        price_row:     pd.Series,
        open_row:      pd.Series,
        signal_date:   pd.Timestamp,
    ) -> List[Order]:
        """
        将目标权重变化转换为委托单列表。

        规则：
          - 权重偏差 < rebalance_threshold → 不动
          - 目标权重 = 0 且当前 > 0 → 全部卖出
          - 目标权重 > 当前 → 买入差额
          - 目标权重 < 当前（且 > 0）→ 卖出差额
        """
        all_syms = set(list(cur_weights) + list(tgt_weights))
        orders:  List[Order] = []

        for sym in all_syms:
            cur_w = cur_weights.get(sym, 0.0)
            tgt_w = tgt_weights.get(sym, 0.0)
            delta_w = tgt_w - cur_w

            # 绝对偏差小于阈值 且 不是清仓 → 跳过
            if abs(delta_w) < self._rebal_thr and tgt_w > 0:
                continue

            # 使用开盘价（若可用）否则用收盘价估算数量
            exec_price = float(open_row.get(sym, price_row.get(sym, 0.0)))
            if exec_price <= 0:
                continue

            delta_usd = abs(delta_w) * portfolio_val
            if delta_usd < self._min_trade:
                continue

            qty = delta_usd / exec_price
            if qty < 1e-6:
                continue

            side = OrderSide.BUY if delta_w > 0 else OrderSide.SELL
            orders.append(Order(
                symbol      = sym,
                side        = side,
                qty_shares  = qty,
                signal_date = signal_date,
            ))

        return orders


# ── 绩效指标计算 ──────────────────────────────────────────────────────────────

def compute_metrics(
    equity_curve:    pd.Series,
    initial_capital: float = 100_000.0,
    benchmark:       Optional[pd.Series] = None,
    risk_free_rate:  float = 0.04,
    annualization:   int = 252,
) -> Dict[str, float]:
    """
    从权益曲线计算标准绩效指标。

    Returns
    -------
    dict with keys:
      total_return, cagr, sharpe, sortino, max_drawdown,
      calmar, volatility, alpha, beta, ir  (后三项需 benchmark)
    """
    if equity_curve.empty or len(equity_curve) < 2:
        return {}

    returns = equity_curve.pct_change().dropna()
    n_years = len(equity_curve) / annualization

    total_return = float(equity_curve.iloc[-1] / equity_curve.iloc[0] - 1)
    cagr         = float((1 + total_return) ** (1 / max(n_years, 1e-6)) - 1) if n_years > 0 else np.nan

    vol     = float(returns.std() * np.sqrt(annualization))
    rf_daily = risk_free_rate / annualization
    excess   = returns - rf_daily
    sharpe   = float(excess.mean() / excess.std() * np.sqrt(annualization)) if excess.std() > 0 else np.nan

    downside = returns[returns < rf_daily]
    sortino  = float(excess.mean() / downside.std() * np.sqrt(annualization)) \
               if len(downside) > 1 and downside.std() > 0 else np.nan

    roll_max = equity_curve.cummax()
    drawdown = (equity_curve - roll_max) / roll_max
    max_dd   = float(drawdown.min())
    calmar   = float(cagr / abs(max_dd)) if max_dd != 0 else np.nan

    m: Dict[str, float] = {
        "total_return": total_return,
        "cagr":         cagr,
        "sharpe":       sharpe,
        "sortino":      sortino,
        "max_drawdown": max_dd,
        "calmar":       calmar,
        "volatility":   vol,
    }

    # 相对基准指标
    if benchmark is not None and not benchmark.empty:
        b_ret = benchmark.pct_change().dropna()
        common = returns.index.intersection(b_ret.index)
        if len(common) > 10:
            r_c = returns.loc[common]
            b_c = b_ret.loc[common]
            cov      = np.cov(r_c, b_c)
            beta     = float(cov[0, 1] / cov[1, 1]) if cov[1, 1] > 0 else np.nan
            alpha    = float((r_c.mean() - beta * b_c.mean()) * annualization) if not np.isnan(beta) else np.nan
            tracking = float((r_c - b_c).std() * np.sqrt(annualization))
            ir       = float((r_c - b_c).mean() / (r_c - b_c).std() * np.sqrt(annualization)) \
                       if (r_c - b_c).std() > 0 else np.nan
            m.update({"alpha": alpha, "beta": beta, "tracking_error": tracking, "ir": ir})

    return m


# ── Regime 敞口约束 ────────────────────────────────────────────────────────────

_REGIME_MAX_EXPOSURE: Dict[str, float] = {
    "BULL":     1.00,
    "RISK_ON":  0.95,
    "NEUTRAL":  0.85,
    "CAUTIOUS": 0.70,
    "RISK_OFF": 0.50,
    "CRISIS":   0.20,
}


def _apply_regime_exposure_cap(
    signals_df:    pd.DataFrame,
    regime_series: pd.Series,
) -> pd.DataFrame:
    """
    按 regime 约束总敞口上限，对信号权重进行按比例缩放。

    与 PortfolioConstructor._apply_regime_caps 使用相同的默认映射，
    确保 BacktestEngine 与 PortfolioConstructor 两层约束一致（Q5-C）。

    Parameters
    ----------
    signals_df    : 目标权重矩阵，行和可能 > regime 上限
    regime_series : RegimeState 字符串序列

    Returns
    -------
    缩放后的权重矩阵（行和 ≤ regime 对应的最大敞口）
    """
    aligned = regime_series.reindex(signals_df.index, method="ffill").fillna("NEUTRAL")
    result  = signals_df.copy()

    for date in signals_df.index:
        regime      = str(aligned.loc[date])
        max_exposure = _REGIME_MAX_EXPOSURE.get(regime, 0.85)
        total       = float(signals_df.loc[date].sum())
        if total > max_exposure and total > 0:
            result.loc[date] = signals_df.loc[date] * (max_exposure / total)

    return result


# ── 工具 ──────────────────────────────────────────────────────────────────────

def _empty_result() -> BacktestResult:
    return BacktestResult(
        equity_curve = pd.Series(dtype=float),
        positions    = pd.DataFrame(),
        weights      = pd.DataFrame(),
        cash_curve   = pd.Series(dtype=float),
        trades       = [],
        metrics      = {},
    )
