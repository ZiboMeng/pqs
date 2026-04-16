"""
ExecutionSimulator: 订单成交模拟。

设计原则
--------
- 日线级别：以下一交易日 OPEN 价格成交（无 look-ahead）
- 滑点方向：买入时价格上移，卖出时价格下移
- 成本：通过 CostModel 统一计算（backtest / paper trading 共享）
- 硬约束：long_only=True，不允许卖空，现金不允许为负

数据类
------
  Order   — 输入：目标仓位意图
  Fill    — 输出：实际成交明细
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

import numpy as np
import pandas as pd

from core.execution.cost_model import CostBreakdown, CostModel
from core.logging_setup import get_logger

logger = get_logger(__name__)


# ── 枚举 ──────────────────────────────────────────────────────────────────────

class OrderSide(str, Enum):
    BUY  = "BUY"
    SELL = "SELL"


# ── 数据类 ────────────────────────────────────────────────────────────────────

@dataclass
class Order:
    """
    一笔委托单。

    Attributes
    ----------
    symbol      : ticker
    side        : BUY 或 SELL
    qty_shares  : 委托股数（正整数或正浮点数）
    signal_date : 信号产生日期（T日，成交在T+1）
    comment     : 可选备注（如触发原因）
    """
    symbol:      str
    side:        OrderSide
    qty_shares:  float
    signal_date: pd.Timestamp
    comment:     str = ""


@dataclass
class Fill:
    """
    实际成交结果。

    Attributes
    ----------
    order           : 原始委托
    executed_price  : 成交价（含滑点，不含佣金）
    executed_qty    : 实际成交股数
    cost_breakdown  : 佣金 + 滑点明细
    fill_date       : 成交日期（T+1）
    cash_delta      : 对现金账户的净影响（正=入账，负=出账）
    """
    order:          Order
    executed_price: float
    executed_qty:   float
    cost_breakdown: CostBreakdown
    fill_date:      pd.Timestamp
    cash_delta:     float       # 正数=卖出收入，负数=买入支出

    @property
    def symbol(self) -> str:
        return self.order.symbol

    @property
    def side(self) -> OrderSide:
        return self.order.side

    @property
    def notional_usd(self) -> float:
        return self.executed_price * self.executed_qty

    @property
    def signal_date(self) -> pd.Timestamp:
        return self.order.signal_date


# ── ExecutionSimulator ────────────────────────────────────────────────────────

class ExecutionSimulator:
    """
    模拟订单成交（日线级别，T+1 成交）。

    Parameters
    ----------
    cost_model   : CostModel 实例（backtest / paper trading 共享）
    freq         : 'interday' 或 'intraday'（影响滑点档位）
    allow_partial: 若 True，现金不足时按比例缩减买入量；
                   若 False，现金不足时拒绝整笔买入。
    """

    def __init__(
        self,
        cost_model:    CostModel,
        freq:          str = "interday",
        allow_partial: bool = True,
    ):
        self._cost   = cost_model
        self._freq   = freq
        self._allow_partial = allow_partial

    # ── 主接口 ────────────────────────────────────────────────────────────────

    def simulate_fill(
        self,
        order:      Order,
        open_price: float,      # T+1 开盘价
        vix:        float,
        cash:       float,      # 成交前现金余额
    ) -> Optional[Fill]:
        """
        模拟单笔委托成交。

        Returns
        -------
        Fill 对象，若委托被拒绝则返回 None（附日志警告）。
        """
        if open_price <= 0 or np.isnan(open_price):
            logger.warning("[%s] Invalid open price %.4f — order rejected", order.symbol, open_price)
            return None

        if order.qty_shares <= 0:
            return None

        is_buy     = order.side == OrderSide.BUY
        slip_bps   = self._cost.cost_bps(order.symbol, self._freq, vix)
        slip_ratio = slip_bps / 10_000

        # 滑点调整后的成交价
        if is_buy:
            exec_price = open_price * (1 + slip_ratio)
        else:
            exec_price = open_price * (1 - slip_ratio)

        qty = order.qty_shares

        # 买入：检查现金是否充足
        if is_buy:
            required = exec_price * qty
            bd       = self._cost.estimate_cost(order.symbol, required, self._freq, vix)
            total_needed = required + bd.commission_usd  # 滑点已计入 exec_price

            if total_needed > cash:
                if self._allow_partial and cash > 0:
                    # 按可用现金等比例缩减
                    scale = cash / total_needed
                    qty   = np.floor(qty * scale)   # 整手化（简单取整）
                    if qty <= 0:
                        logger.debug("[%s] Not enough cash for even 1 share — skipped", order.symbol)
                        return None
                else:
                    logger.debug("[%s] Insufficient cash %.2f < %.2f — order rejected",
                                 order.symbol, cash, total_needed)
                    return None

        notional    = exec_price * qty
        bd          = self._cost.estimate_cost(order.symbol, notional, self._freq, vix)

        if is_buy:
            cash_delta = -(notional + bd.commission_usd)
        else:
            cash_delta = notional - bd.commission_usd

        fill_date = order.signal_date + pd.tseries.offsets.BDay(1)

        return Fill(
            order          = order,
            executed_price = exec_price,
            executed_qty   = qty,
            cost_breakdown = bd,
            fill_date      = fill_date,
            cash_delta     = cash_delta,
        )

    def simulate_fills(
        self,
        orders:      List[Order],
        open_prices: dict,      # symbol → open_price
        vix:         float,
        cash:        float,
    ) -> List[Fill]:
        """
        批量模拟成交。卖单优先处理（先卖后买，确保现金充足）。
        """
        sells = [o for o in orders if o.side == OrderSide.SELL]
        buys  = [o for o in orders if o.side == OrderSide.BUY]

        fills:    List[Fill] = []
        cur_cash: float      = cash

        for order in sells + buys:
            price = open_prices.get(order.symbol)
            if price is None:
                logger.warning("[%s] No open price available — order skipped", order.symbol)
                continue
            fill = self.simulate_fill(order, float(price), vix, cur_cash)
            if fill is not None:
                fills.append(fill)
                cur_cash += fill.cash_delta

        return fills
