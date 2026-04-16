"""
StressTester: 历史情景压力测试 + Bootstrap Monte Carlo 模拟。

内置四个经典情景（针对长仓 ETF 组合设计）：
  gfc_2008         — 2008 全球金融危机（SPY -57%，持续 ~350 天）
  covid_2020       — 2020 COVID 闪崩（SPY -34%，约 23 交易日）
  rate_hike_2022   — 2022 加息周期（SPY -20%，全年）
  dot_com_2000     — 2000–2002 互联网泡沫（QQQ -83%，约 630 天）

Monte Carlo 使用 Bootstrap 重采样（保留历史日收益的非正态特性）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from core.logging_setup import get_logger

logger = get_logger(__name__)


# ── 情景定义 ──────────────────────────────────────────────────────────────────

@dataclass
class StressScenario:
    """
    压力情景定义。

    Attributes
    ----------
    name          : 情景标识（如 "gfc_2008"）
    description   : 情景描述
    asset_shocks  : {symbol: 总收益率冲击}，如 {"SPY": -0.57}
                    未出现的 symbol 使用 "default" 键的值（若有）
    duration_days : 情景持续天数（仅用于说明，不影响计算）
    """
    name:          str
    description:   str
    asset_shocks:  Dict[str, float]
    duration_days: int = 252


@dataclass
class StressResult:
    """单个情景的压力测试结果。"""
    scenario_name:     str
    portfolio_return:  float   # 加权组合总收益率
    estimated_pnl:     float   # 按当前权益估算的 PnL（USD）
    worst_asset:       str     # 受冲击最大的标的
    worst_asset_shock: float   # 受冲击最大标的的收益率

    def __str__(self) -> str:
        return (
            f"[{self.scenario_name}] "
            f"组合收益: {self.portfolio_return:+.2%}  "
            f"估算 PnL: ${self.estimated_pnl:,.0f}  "
            f"最差标的: {self.worst_asset} ({self.worst_asset_shock:+.2%})"
        )


@dataclass
class MonteCarloResult:
    """Monte Carlo 模拟汇总结果。"""
    n_sims:        int
    horizon_days:  int
    median_return: float
    pct_5:         float    # 5th 百分位总收益
    pct_95:        float    # 95th 百分位总收益
    prob_loss:     float    # 亏损概率（P(return < 0)）
    var_95:        float    # 95% VaR（5th pct 总收益，即最差 5% 的下界）
    cvar_95:       float    # 95% CVaR（最差 5% 的均值）

    def __str__(self) -> str:
        return (
            f"Monte Carlo ({self.n_sims} 模拟 × {self.horizon_days} 天)\n"
            f"  中位收益:   {self.median_return:+.2%}\n"
            f"  5th~95th:  [{self.pct_5:+.2%}, {self.pct_95:+.2%}]\n"
            f"  亏损概率:   {self.prob_loss:.1%}\n"
            f"  95% VaR:   {self.var_95:+.2%}\n"
            f"  95% CVaR:  {self.cvar_95:+.2%}"
        )


# ── 内置情景 ──────────────────────────────────────────────────────────────────

_BUILTIN_SCENARIOS: List[StressScenario] = [
    StressScenario(
        name="gfc_2008",
        description="2008 全球金融危机（2007/10–2009/03，~350 交易日）",
        asset_shocks={
            "SPY": -0.57, "QQQ": -0.52, "IWM": -0.60,
            "TLT": +0.25, "GLD": +0.05, "default": -0.55,
        },
        duration_days=350,
    ),
    StressScenario(
        name="covid_2020",
        description="2020 COVID 闪崩（2020/02/19–2020/03/23，约 23 交易日）",
        asset_shocks={
            "SPY": -0.34, "QQQ": -0.30, "IWM": -0.42,
            "TLT": +0.10, "GLD": -0.02, "default": -0.35,
        },
        duration_days=23,
    ),
    StressScenario(
        name="rate_hike_2022",
        description="2022 加息周期（全年，SPY -20%）",
        asset_shocks={
            "SPY": -0.20, "QQQ": -0.33, "IWM": -0.22,
            "TLT": -0.28, "GLD": -0.02, "default": -0.22,
        },
        duration_days=252,
    ),
    StressScenario(
        name="dot_com_2000",
        description="2000–2002 互联网泡沫（约 630 交易日，QQQ -83%）",
        asset_shocks={
            "SPY": -0.49, "QQQ": -0.83, "IWM": -0.40,
            "TLT": +0.20, "GLD": +0.05, "default": -0.50,
        },
        duration_days=630,
    ),
]


# ── StressTester ──────────────────────────────────────────────────────────────

class StressTester:
    """
    历史情景压力测试 + Bootstrap Monte Carlo 模拟。

    Parameters
    ----------
    equity           : 当前组合权益（USD），用于估算 PnL
    custom_scenarios : 附加自定义情景列表（追加到内置情景后）
    """

    def __init__(
        self,
        equity:           float = 100_000.0,
        custom_scenarios: Optional[List[StressScenario]] = None,
    ) -> None:
        self._equity    = equity
        self._scenarios = list(_BUILTIN_SCENARIOS)
        if custom_scenarios:
            self._scenarios.extend(custom_scenarios)

    # ── 情景压力测试 ──────────────────────────────────────────────────────────

    def apply_scenario(
        self,
        weights:  Dict[str, float],
        scenario: StressScenario,
    ) -> StressResult:
        """
        对当前持仓权重施加情景冲击，计算组合收益。

        Parameters
        ----------
        weights  : {symbol: weight}，自动归一化
        scenario : StressScenario 实例

        Returns
        -------
        StressResult
        """
        total_w = sum(weights.values())
        if total_w <= 0:
            return StressResult(
                scenario_name="", portfolio_return=0.0,
                estimated_pnl=0.0, worst_asset="", worst_asset_shock=0.0,
            )
        norm_w = {s: w / total_w for s, w in weights.items()}

        port_ret = 0.0
        for sym, w in norm_w.items():
            shock     = scenario.asset_shocks.get(
                sym, scenario.asset_shocks.get("default", -0.30)
            )
            port_ret += w * shock

        worst_sym = min(
            norm_w,
            key=lambda s: scenario.asset_shocks.get(
                s, scenario.asset_shocks.get("default", -0.30)
            ),
        )
        worst_shock = scenario.asset_shocks.get(
            worst_sym, scenario.asset_shocks.get("default", -0.30)
        )

        return StressResult(
            scenario_name     = scenario.name,
            portfolio_return  = port_ret,
            estimated_pnl     = self._equity * port_ret,
            worst_asset       = worst_sym,
            worst_asset_shock = worst_shock,
        )

    def run_all(self, weights: Dict[str, float]) -> List[StressResult]:
        """对所有内置 + 自定义情景运行压力测试。"""
        return [self.apply_scenario(weights, s) for s in self._scenarios]

    def get_scenario(self, name: str) -> Optional[StressScenario]:
        """按名称查找情景，不存在返回 None。"""
        for s in self._scenarios:
            if s.name == name:
                return s
        return None

    @property
    def scenario_names(self) -> List[str]:
        """所有情景名称列表。"""
        return [s.name for s in self._scenarios]

    # ── Monte Carlo ───────────────────────────────────────────────────────────

    def monte_carlo(
        self,
        equity_curve: pd.Series,
        n_sims:       int = 1_000,
        horizon:      int = 252,
        seed:         int = 42,
    ) -> MonteCarloResult:
        """
        Bootstrap 重采样 Monte Carlo 模拟。

        从历史日收益有放回地抽取 horizon 天，累积乘积得到每次模拟的总收益。
        保留历史收益的非正态分布特性（厚尾、偏态）。

        Parameters
        ----------
        equity_curve : 历史权益曲线（pd.Series，至少 20 个点）
        n_sims       : 模拟次数（默认 1000）
        horizon      : 预测期天数（默认 252 = 1 年）
        seed         : 随机种子（可复现）

        Returns
        -------
        MonteCarloResult（数据不足时各字段返回 nan）
        """
        _nan = MonteCarloResult(
            n_sims=n_sims, horizon_days=horizon,
            median_return=float("nan"), pct_5=float("nan"),
            pct_95=float("nan"), prob_loss=float("nan"),
            var_95=float("nan"), cvar_95=float("nan"),
        )

        if len(equity_curve) < 20:
            logger.warning("monte_carlo: 数据不足（%d 点），返回 nan", len(equity_curve))
            return _nan

        rets = equity_curve.pct_change().dropna().values
        rng  = np.random.default_rng(seed)

        # (n_sims, horizon) 矩阵：每行为一次模拟的日收益序列
        idx          = rng.integers(0, len(rets), size=(n_sims, horizon))
        sim_daily    = rets[idx]
        sim_total    = np.prod(1.0 + sim_daily, axis=1) - 1.0   # (n_sims,)

        sorted_rets  = np.sort(sim_total)
        tail_cut     = max(int(0.05 * n_sims), 1)
        var_95       = float(sorted_rets[tail_cut - 1])
        cvar_95      = float(sorted_rets[:tail_cut].mean())

        return MonteCarloResult(
            n_sims        = n_sims,
            horizon_days  = horizon,
            median_return = float(np.median(sim_total)),
            pct_5         = float(np.percentile(sim_total, 5)),
            pct_95        = float(np.percentile(sim_total, 95)),
            prob_loss     = float((sim_total < 0).mean()),
            var_95        = var_95,
            cvar_95       = cvar_95,
        )
