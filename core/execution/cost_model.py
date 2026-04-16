"""
CostModel: 运行时成本计算层。

封装 CostModelConfig（pydantic 配置），提供：
  apply_cost      — 从名义金额扣除交易成本，返回实际净金额
  estimate_cost   — 预估成本（USD）
  cost_bps        — 查询总成本 bps

与 BacktestEngine / ExecutionSimulator 共享同一实例，确保 backtest 和
paper trading 使用完全一致的成本假设。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.config.schemas.cost_model import CostModelConfig
from core.logging_setup import get_logger

logger = get_logger(__name__)


# ── 成本明细 ──────────────────────────────────────────────────────────────────

@dataclass
class CostBreakdown:
    """单笔交易的成本明细。"""
    symbol:         str
    notional_usd:   float   # 名义金额（abs）
    commission_usd: float
    slippage_usd:   float
    total_cost_usd: float
    total_bps:      float

    @property
    def total_cost_ratio(self) -> float:
        """总成本占名义金额的比例。"""
        return self.total_cost_usd / self.notional_usd if self.notional_usd else 0.0


# ── CostModel ─────────────────────────────────────────────────────────────────

class CostModel:
    """
    运行时成本计算器，基于 CostModelConfig。

    Parameters
    ----------
    config : CostModelConfig
        来自 YAML 加载的 pydantic 配置。
    """

    def __init__(self, config: CostModelConfig):
        self._cfg = config

    # ── 公开 API ──────────────────────────────────────────────────────────────

    def cost_bps(
        self,
        symbol: str,
        freq:   str = "interday",
        vix:    float = 15.0,
    ) -> float:
        """
        返回总成本（commission + slippage）的 bps 值。

        Parameters
        ----------
        symbol : ticker
        freq   : 'interday' 或 'intraday'
        vix    : 当前 VIX 水平（用于应激压力倍数）
        """
        return self._cfg.get_total_cost_bps(symbol, freq, vix)

    def estimate_cost(
        self,
        symbol:       str,
        notional_usd: float,
        freq:         str = "interday",
        vix:          float = 15.0,
    ) -> CostBreakdown:
        """
        预估一笔交易的成本明细。

        Parameters
        ----------
        notional_usd : 交易名义金额（正数，不区分买卖）
        """
        notional_usd = abs(notional_usd)
        if notional_usd == 0:
            return CostBreakdown(symbol, 0, 0, 0, 0, 0)

        commission_bps  = self._cfg.get_commission_bps(symbol)
        slippage_bps    = self._cfg.get_slippage_bps(symbol, freq, vix)
        total_bps       = commission_bps + slippage_bps

        commission_usd  = notional_usd * commission_bps / 10_000
        slippage_usd    = notional_usd * slippage_bps   / 10_000
        total_cost_usd  = commission_usd + slippage_usd

        return CostBreakdown(
            symbol         = symbol,
            notional_usd   = notional_usd,
            commission_usd = commission_usd,
            slippage_usd   = slippage_usd,
            total_cost_usd = total_cost_usd,
            total_bps      = total_bps,
        )

    def apply_cost(
        self,
        symbol:       str,
        notional_usd: float,
        freq:         str = "interday",
        vix:          float = 15.0,
        is_buy:       bool = True,
    ) -> tuple[float, CostBreakdown]:
        """
        从名义金额中扣除成本，返回净金额。

        买入：净金额 = notional + cost（多花钱）
        卖出：净金额 = notional - cost（少收钱）

        Returns
        -------
        (net_usd, CostBreakdown)
        """
        bd = self.estimate_cost(symbol, notional_usd, freq, vix)
        if is_buy:
            net_usd = notional_usd + bd.total_cost_usd   # 买入多付
        else:
            net_usd = notional_usd - bd.total_cost_usd   # 卖出少收
        return net_usd, bd
