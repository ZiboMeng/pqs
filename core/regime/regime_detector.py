"""
RegimeDetector: 六状态市场环境识别。

状态层次（从乐观到防守）
-----------------------
  BULL → RISK_ON → NEUTRAL → CAUTIOUS → RISK_OFF → CRISIS

判断维度
--------
1. VIX 水平：主要参考
   - VIX < bull_thr (15)          → BULL
   - bull_thr ≤ VIX < risk_on_thr → RISK_ON
   - risk_on_thr ≤ VIX < neutral  → NEUTRAL
   - neutral ≤ VIX < cautious     → CAUTIOUS
   - cautious ≤ VIX < risk_off    → RISK_OFF
   - VIX ≥ risk_off (35)          → CRISIS

2. SPY EMA 趋势（强制下限）
   - 价格 < 200-EMA → 至少 CAUTIOUS
   - 价格 < 50-EMA（且 > 200-EMA）→ 至少 NEUTRAL

3. SPY 距 52 周高点的回撤（强制下限）
   - 回撤 ≤ -20% → CRISIS
   - 回撤 ≤ -10% → RISK_OFF
   - 回撤 ≤  -5% → CAUTIOUS

4. 10Y 国债收益率（TNX）日内骤升（强制下限）
   - 单日涨幅 ≥ tnx_spike_threshold (0.15) → 至少 CAUTIOUS

5. 平滑窗口
   - 恶化（防守方向）：立即生效
   - 改善（乐观方向）：需连续 smoothing_window 根 K 线才确认

使用示例
--------
    from core.config.loader import load_config
    cfg      = load_config()
    detector = RegimeDetector(cfg.regime)
    states   = detector.classify_series(spy_close, vix_close)
    reading  = detector.get_current(spy_close, vix_close)
    constr   = detector.get_constraints(reading.state)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional

import pandas as pd

from core.config.schemas.regime import RegimeConfig, RegimePositionConstraintConfig
from core.logging_setup import get_logger

logger = get_logger(__name__)


# ── 状态枚举 ─────────────────────────────────────────────────────────────────

class RegimeState(str, Enum):
    BULL     = "BULL"
    RISK_ON  = "RISK_ON"
    NEUTRAL  = "NEUTRAL"
    CAUTIOUS = "CAUTIOUS"
    RISK_OFF = "RISK_OFF"
    CRISIS   = "CRISIS"


# 有序列表：index 越大越防守
_REGIME_ORDER: list[RegimeState] = [
    RegimeState.BULL,
    RegimeState.RISK_ON,
    RegimeState.NEUTRAL,
    RegimeState.CAUTIOUS,
    RegimeState.RISK_OFF,
    RegimeState.CRISIS,
]

_REGIME_RANK: Dict[RegimeState, int] = {s: i for i, s in enumerate(_REGIME_ORDER)}


def _max_regime(*states: RegimeState) -> RegimeState:
    """返回最防守的状态（rank 最大）。"""
    return max(states, key=lambda s: _REGIME_RANK[s])


# ── 结果数据类 ────────────────────────────────────────────────────────────────

@dataclass
class RegimeReading:
    """
    单点市场环境读数。

    Attributes
    ----------
    date                  : 对应日期
    state                 : 平滑后的确认状态
    raw_state             : 平滑前的原始状态
    vix                   : 当日 VIX 值
    spy_drawdown_from_peak: SPY 距 52 周高点的回撤（负值）
    tnx_spike             : 当日 TNX 是否骤升
    spy_above_fast_ema    : SPY 价格是否高于 fast EMA
    spy_above_slow_ema    : SPY 价格是否高于 slow EMA
    """
    date:                   pd.Timestamp
    state:                  RegimeState
    raw_state:              RegimeState
    vix:                    float
    spy_drawdown_from_peak: float
    tnx_spike:              bool
    spy_above_fast_ema:     bool
    spy_above_slow_ema:     bool

    def __str__(self) -> str:
        smooth_tag = "" if self.state == self.raw_state else f" (raw={self.raw_state.value})"
        return (
            f"[{self.date.date()}] {self.state.value}{smooth_tag} | "
            f"VIX={self.vix:.1f} | "
            f"SPY_DD={self.spy_drawdown_from_peak:.1%} | "
            f"TNX_spike={self.tnx_spike}"
        )


# ── RegimeDetector ────────────────────────────────────────────────────────────

class RegimeDetector:
    """
    六状态市场环境检测器。

    Parameters
    ----------
    config : RegimeConfig
        来自 YAML 加载的 pydantic 配置对象。
    """

    def __init__(self, config: RegimeConfig) -> None:
        self._cfg = config

    # ── 主接口 ────────────────────────────────────────────────────────────────

    def classify_series(
        self,
        spy:       pd.Series,
        vix:       pd.Series,
        tnx:       Optional[pd.Series] = None,
    ) -> pd.Series:
        """
        为每个日期分类市场环境（含平滑）。

        Parameters
        ----------
        spy : SPY 每日收盘价（DatetimeIndex）
        vix : VIX 每日收盘价（DatetimeIndex）
        tnx : 10Y 国债收益率（可选），用于检测骤升

        Returns
        -------
        pd.Series  index=日期，dtype=str（RegimeState.value）
        """
        common = spy.index.intersection(vix.index)
        if len(common) < 2:
            logger.warning("RegimeDetector: 可用数据不足（需要 spy + vix 共同日期 ≥ 2）")
            return pd.Series(RegimeState.NEUTRAL.value, index=common, dtype=str)

        spy_c = spy.loc[common]
        vix_c = vix.loc[common]
        tnx_c = tnx.reindex(common).ffill() if tnx is not None else None

        fast_w = self._cfg.spy_ema_fast
        slow_w = self._cfg.spy_ema_slow

        spy_fast_ema = spy_c.ewm(span=fast_w, adjust=False).mean()
        spy_slow_ema = spy_c.ewm(span=slow_w, adjust=False).mean()
        spy_peak_1y  = spy_c.rolling(min(252, len(spy_c))).max()
        spy_drawdown = (spy_c - spy_peak_1y) / spy_peak_1y  # 负值

        # TNX 日涨幅
        tnx_spike: pd.Series
        if tnx_c is not None:
            tnx_diff  = tnx_c.diff().fillna(0.0)
            tnx_spike = tnx_diff >= self._cfg.tnx_spike_threshold
        else:
            tnx_spike = pd.Series(False, index=common)

        raw_states = []
        for i, date in enumerate(common):
            raw = self._classify_raw(
                vix_val    = float(vix_c.loc[date]),
                spy_price  = float(spy_c.loc[date]),
                fast_ema   = float(spy_fast_ema.loc[date]),
                slow_ema   = float(spy_slow_ema.loc[date]),
                drawdown   = float(spy_drawdown.loc[date]),
                tnx_spike  = bool(tnx_spike.loc[date]),
            )
            raw_states.append(raw)

        raw_series = pd.Series(raw_states, index=common)
        smoothed   = self._smooth(raw_series, self._cfg.smoothing_window)

        return smoothed.map(lambda s: s.value if hasattr(s, 'value') else str(s))

    def get_current(
        self,
        spy:  pd.Series,
        vix:  pd.Series,
        tnx:  Optional[pd.Series] = None,
    ) -> RegimeReading:
        """
        返回最新日期的市场环境读数。

        数据不足时返回 NEUTRAL 状态。
        """
        common = spy.index.intersection(vix.index)
        if len(common) < 2:
            return RegimeReading(
                date                   = pd.Timestamp.now().normalize(),
                state                  = RegimeState.NEUTRAL,
                raw_state              = RegimeState.NEUTRAL,
                vix                    = float("nan"),
                spy_drawdown_from_peak = float("nan"),
                tnx_spike              = False,
                spy_above_fast_ema     = False,
                spy_above_slow_ema     = False,
            )

        spy_c = spy.loc[common]
        vix_c = vix.loc[common]
        tnx_c = tnx.reindex(common).ffill() if tnx is not None else None

        fast_w = self._cfg.spy_ema_fast
        slow_w = self._cfg.spy_ema_slow

        spy_fast_ema = spy_c.ewm(span=fast_w, adjust=False).mean()
        spy_slow_ema = spy_c.ewm(span=slow_w, adjust=False).mean()
        spy_peak_1y  = spy_c.rolling(min(252, len(spy_c))).max()
        spy_drawdown = (spy_c - spy_peak_1y) / spy_peak_1y

        tnx_spike_val = False
        if tnx_c is not None:
            tnx_diff      = tnx_c.diff().fillna(0.0)
            tnx_spike_val = bool(tnx_diff.iloc[-1] >= self._cfg.tnx_spike_threshold)

        last_date = common[-1]
        vix_val   = float(vix_c.iloc[-1])
        spy_val   = float(spy_c.iloc[-1])
        fast_val  = float(spy_fast_ema.iloc[-1])
        slow_val  = float(spy_slow_ema.iloc[-1])
        dd_val    = float(spy_drawdown.iloc[-1])

        raw = self._classify_raw(
            vix_val   = vix_val,
            spy_price = spy_val,
            fast_ema  = fast_val,
            slow_ema  = slow_val,
            drawdown  = dd_val,
            tnx_spike = tnx_spike_val,
        )

        # 使用完整序列得到平滑后状态
        smoothed_series = self.classify_series(spy, vix, tnx)
        if last_date in smoothed_series.index:
            smoothed_val = RegimeState(smoothed_series.loc[last_date])
        else:
            smoothed_val = raw

        return RegimeReading(
            date                   = last_date,
            state                  = smoothed_val,
            raw_state              = raw,
            vix                    = vix_val,
            spy_drawdown_from_peak = dd_val,
            tnx_spike              = tnx_spike_val,
            spy_above_fast_ema     = spy_val > fast_val,
            spy_above_slow_ema     = spy_val > slow_val,
        )

    def get_constraints(
        self, state: RegimeState
    ) -> RegimePositionConstraintConfig:
        """返回指定环境状态的持仓约束。"""
        constraints = self._cfg.position_constraints
        if state.value not in constraints:
            raise KeyError(
                f"No position_constraints defined for regime '{state.value}'. "
                f"Available: {list(constraints.keys())}"
            )
        return constraints[state.value]

    # ── 内部：原始分类 ────────────────────────────────────────────────────────

    def _classify_raw(
        self,
        vix_val:   float,
        spy_price: float,
        fast_ema:  float,
        slow_ema:  float,
        drawdown:  float,
        tnx_spike: bool,
    ) -> RegimeState:
        """
        基于当日数据计算原始（未平滑）市场环境。

        多因子取最防守值。
        """
        thr = self._cfg.vix_thresholds

        # 1. VIX 分层
        if vix_val < thr.bull:
            vix_regime = RegimeState.BULL
        elif vix_val < thr.risk_on:
            vix_regime = RegimeState.RISK_ON
        elif vix_val < thr.neutral:
            vix_regime = RegimeState.NEUTRAL
        elif vix_val < thr.cautious:
            vix_regime = RegimeState.CAUTIOUS
        elif vix_val < thr.risk_off:
            vix_regime = RegimeState.RISK_OFF
        else:
            vix_regime = RegimeState.CRISIS

        # 2. SPY 趋势下限
        if spy_price < slow_ema:          # 低于 200-EMA
            trend_floor = RegimeState.CAUTIOUS
        elif spy_price < fast_ema:        # 低于 50-EMA（但高于 200-EMA）
            trend_floor = RegimeState.NEUTRAL
        else:
            trend_floor = RegimeState.BULL

        # 3. SPY 回撤下限
        dd_thr = self._cfg.drawdown_thresholds
        if drawdown <= dd_thr.crisis:
            dd_floor = RegimeState.CRISIS
        elif drawdown <= dd_thr.risk_off:
            dd_floor = RegimeState.RISK_OFF
        elif drawdown <= dd_thr.cautious:
            dd_floor = RegimeState.CAUTIOUS
        else:
            dd_floor = RegimeState.BULL

        # 4. TNX 骤升下限
        tnx_floor = RegimeState.CAUTIOUS if tnx_spike else RegimeState.BULL

        # 5. 取最防守
        return _max_regime(vix_regime, trend_floor, dd_floor, tnx_floor)

    # ── 内部：平滑 ────────────────────────────────────────────────────────────

    @staticmethod
    def _smooth(raw: pd.Series, window: int) -> pd.Series:
        """
        状态切换平滑：
        - 恶化方向（更防守）：立即确认
        - 改善方向（更乐观）：需连续 `window` 根 K 线才确认切换
        """
        if len(raw) == 0:
            return raw.copy()

        values      = list(raw)
        confirmed   = list(raw)
        current     = values[0]
        candidate:  Optional[RegimeState] = None
        streak      = 0

        for i in range(1, len(values)):
            r = values[i]

            if r == current:
                # 保持当前状态
                candidate = None
                streak    = 0

            elif _REGIME_RANK[r] > _REGIME_RANK[current]:
                # 恶化：立即确认
                current   = r
                candidate = None
                streak    = 0

            else:
                # 改善：开始累计
                if r == candidate:
                    streak += 1
                else:
                    candidate = r
                    streak    = 1

                if streak >= window:
                    current   = r
                    candidate = None
                    streak    = 0

            confirmed[i] = current

        return pd.Series(confirmed, index=raw.index)
