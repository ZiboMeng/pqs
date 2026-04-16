"""Unit tests for RegimeDetector, RegimeReading, RegimeState."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.config.schemas.regime import (
    RegimeConfig,
    VixThresholdsConfig,
    DrawdownThresholdsConfig,
    RegimePositionConstraintConfig,
)
from core.regime.regime_detector import RegimeDetector, RegimeReading, RegimeState


# ── 辅助函数 ──────────────────────────────────────────────────────────────────

def _make_config(**kw) -> RegimeConfig:
    """构造最小可用 RegimeConfig（含 position_constraints）。"""
    constraints = {
        regime: RegimePositionConstraintConfig(
            target_cash_pct_min   = 0.0,
            target_cash_pct_max   = 1.0,
            max_single_position   = 0.35,
            leveraged_etf_allowed = True,
        )
        for regime in ["BULL", "RISK_ON", "NEUTRAL", "CAUTIOUS", "RISK_OFF", "CRISIS"]
    }
    defaults = dict(
        spy_ema_fast         = 50,
        spy_ema_slow         = 200,
        smoothing_window     = 3,
        position_constraints = constraints,
    )
    defaults.update(kw)
    return RegimeConfig(**defaults)


def _make_spy(n: int = 260, start: float = 400.0, trend: float = 0.0003) -> pd.Series:
    """生成趋势性 SPY 收盘价序列（默认微涨）。"""
    idx  = pd.bdate_range("2022-01-03", periods=n)
    vals = start * np.cumprod(1 + np.full(n, trend))
    return pd.Series(vals, index=idx)


def _make_vix(n: int = 260, level: float = 15.0) -> pd.Series:
    """生成恒定 VIX 序列。"""
    idx = pd.bdate_range("2022-01-03", periods=n)
    return pd.Series(level, index=idx)


def _make_detector(smoothing: int = 1) -> RegimeDetector:
    """返回 smoothing_window=1 的检测器（等效无平滑，便于精确断言）。"""
    return RegimeDetector(_make_config(smoothing_window=smoothing))


# ── RegimeState ───────────────────────────────────────────────────────────────

class TestRegimeState:
    def test_all_6_states_exist(self):
        states = {s.value for s in RegimeState}
        assert states == {"BULL", "RISK_ON", "NEUTRAL", "CAUTIOUS", "RISK_OFF", "CRISIS"}

    def test_string_enum_values(self):
        assert RegimeState.BULL == "BULL"
        assert RegimeState.CRISIS == "CRISIS"


# ── VIX 分层（无平滑） ────────────────────────────────────────────────────────

class TestVixClassification:
    """VIX 水平 → 正确状态（趋势为上升趋势以排除趋势下限）。"""

    def _result(self, vix_level: float) -> str:
        det = _make_detector(smoothing=1)
        spy = _make_spy(300, trend=0.0003)          # 持续上升 → 高于所有 EMA
        vix = _make_vix(300, level=vix_level)
        s   = det.classify_series(spy, vix)
        return str(s.iloc[-1])

    def test_bull_regime(self):
        assert self._result(12.0) == RegimeState.BULL.value

    def test_risk_on_regime(self):
        assert self._result(17.0) == RegimeState.RISK_ON.value

    def test_neutral_regime(self):
        assert self._result(22.0) == RegimeState.NEUTRAL.value

    def test_cautious_regime(self):
        assert self._result(27.0) == RegimeState.CAUTIOUS.value

    def test_risk_off_regime(self):
        assert self._result(32.0) == RegimeState.RISK_OFF.value

    def test_crisis_regime(self):
        assert self._result(40.0) == RegimeState.CRISIS.value

    def test_boundary_at_bull_threshold(self):
        """VIX = 15.0（bull 上限）→ RISK_ON。"""
        assert self._result(15.0) == RegimeState.RISK_ON.value

    def test_just_below_bull_threshold(self):
        assert self._result(14.9) == RegimeState.BULL.value


# ── SPY 趋势下限 ──────────────────────────────────────────────────────────────

class TestSpyTrendFloor:
    def test_below_slow_ema_forces_cautious(self):
        """SPY 跌破 200-EMA + VIX = 12（BULL 区间）→ 至少 CAUTIOUS。"""
        det = _make_detector(smoothing=1)
        n   = 260
        idx = pd.bdate_range("2020-01-02", periods=n)
        # 前 200 天上升（建立高 EMA），后 60 天急跌到 EMA 以下
        spy_up   = 400.0 * np.cumprod(1 + np.full(200, 0.001))
        spy_down = spy_up[-1] * np.cumprod(1 + np.full(60, -0.005))
        spy = pd.Series(np.concatenate([spy_up, spy_down]), index=idx)
        vix = pd.Series(12.0, index=idx)  # 假设 VIX 维持低位

        result = det.classify_series(spy, vix)
        last = result.iloc[-1]
        # 最终应至少 CAUTIOUS（SPY 跌破 200-EMA）
        assert RegimeState(last) in [
            RegimeState.CAUTIOUS, RegimeState.RISK_OFF, RegimeState.CRISIS
        ]

    def test_above_both_emas_allows_bull(self):
        """SPY 高于 50-EMA 和 200-EMA，VIX=12 → BULL。"""
        det = _make_detector(smoothing=1)
        spy = _make_spy(300, trend=0.0003)
        vix = _make_vix(300, level=12.0)
        result = det.classify_series(spy, vix)
        assert result.iloc[-1] == RegimeState.BULL.value


# ── SPY 回撤下限 ──────────────────────────────────────────────────────────────

class TestDrawdownFloor:
    def _make_dd_spy(self, dd_pct: float, n_up: int = 100, n_down: int = 30) -> pd.Series:
        """构造峰值后下跌 dd_pct 的 SPY 序列。"""
        n   = n_up + n_down
        idx = pd.bdate_range("2020-01-02", periods=n)
        up  = 400.0 * np.cumprod(1 + np.full(n_up, 0.001))
        end = up[-1] * (1 + dd_pct)
        dn  = np.linspace(up[-1], end, n_down)
        return pd.Series(np.concatenate([up, dn]), index=idx)

    def test_crisis_drawdown_forces_crisis(self):
        """回撤 -20% → 至少 CRISIS。"""
        det = _make_detector(smoothing=1)
        spy = self._make_dd_spy(-0.20)
        vix = pd.Series(12.0, index=spy.index)
        result = det.classify_series(spy, vix)
        assert result.iloc[-1] == RegimeState.CRISIS.value

    def test_risk_off_drawdown_forces_risk_off(self):
        """回撤 -12% → 至少 RISK_OFF（VIX 维持低位不足以触发 CRISIS）。"""
        det = _make_detector(smoothing=1)
        spy = self._make_dd_spy(-0.12)
        vix = pd.Series(12.0, index=spy.index)
        result = det.classify_series(spy, vix)
        last = result.iloc[-1]
        assert RegimeState(last) in [RegimeState.RISK_OFF, RegimeState.CRISIS]

    def test_small_drawdown_no_floor(self):
        """回撤 -3%（< 5% 阈值）→ 回撤下限不触发，状态最差为 NEUTRAL（趋势可能触发）。"""
        det = _make_detector(smoothing=1)
        spy = self._make_dd_spy(-0.03, n_up=200)
        vix = pd.Series(12.0, index=spy.index)
        result = det.classify_series(spy, vix)
        # 回撤下限（cautious=-5%）未触发，状态不超过 NEUTRAL
        last = RegimeState(result.iloc[-1])
        assert last in [RegimeState.BULL, RegimeState.RISK_ON, RegimeState.NEUTRAL], (
            f"3% 回撤不应触发 CAUTIOUS+，实际={last.value}"
        )


# ── TNX 骤升下限 ──────────────────────────────────────────────────────────────

class TestTnxFloor:
    def test_tnx_spike_forces_at_least_cautious(self):
        """TNX 单日涨幅 0.15+ → 至少 CAUTIOUS（即便 VIX 极低）。"""
        det = _make_detector(smoothing=1)
        n   = 100
        idx = pd.bdate_range("2022-01-03", periods=n)
        spy = _make_spy(n, trend=0.0003)
        vix = pd.Series(12.0, index=idx)

        # 最后一天 TNX 骤升 0.20（阈值 0.15）
        tnx        = pd.Series(2.0, index=idx)
        tnx.iloc[-1] = 2.20

        result = det.classify_series(spy, vix, tnx)
        last   = RegimeState(result.iloc[-1])
        assert last in [RegimeState.CAUTIOUS, RegimeState.RISK_OFF, RegimeState.CRISIS]

    def test_small_tnx_change_no_floor(self):
        """TNX 单日涨幅 0.05 < 0.15 阈值 → 不触发 TNX 下限。"""
        det = _make_detector(smoothing=1)
        n   = 100
        idx = pd.bdate_range("2022-01-03", periods=n)
        spy = _make_spy(n, trend=0.0003)
        vix = pd.Series(12.0, index=idx)

        tnx        = pd.Series(2.0, index=idx)
        tnx.iloc[-1] = 2.05

        result = det.classify_series(spy, vix, tnx)
        assert result.iloc[-1] == RegimeState.BULL.value


# ── 平滑逻辑 ──────────────────────────────────────────────────────────────────

class TestSmoothing:
    def test_worsening_is_immediate(self):
        """
        环境恶化（BULL → CRISIS）立即生效，无需等待平滑窗口。
        """
        det = RegimeDetector(_make_config(smoothing_window=5))
        n   = 60
        idx = pd.bdate_range("2022-01-03", periods=n)

        # 前 50 天 VIX=12（BULL），后 10 天 VIX=50（CRISIS）
        vix_vals = [12.0] * 50 + [50.0] * 10
        spy = _make_spy(n, trend=0.0003)
        vix = pd.Series(vix_vals, index=idx)

        result = det.classify_series(spy, vix)
        # 第 51 条（index 50）立即变为 CRISIS
        assert result.iloc[50] == RegimeState.CRISIS.value

    def test_improvement_requires_window(self):
        """
        环境改善（CRISIS → BULL）需要 smoothing_window 根 K 线才确认。
        """
        window = 3
        det    = RegimeDetector(_make_config(smoothing_window=window))
        n      = 20
        idx    = pd.bdate_range("2022-01-03", periods=n)

        # 先 CRISIS（VIX=50），然后切换到 BULL（VIX=12）
        vix_vals  = [50.0] * 5 + [12.0] * 15
        spy = _make_spy(n, trend=0.0003)
        vix = pd.Series(vix_vals, index=idx)

        result = det.classify_series(spy, vix)
        # 前 5 天 CRISIS
        assert result.iloc[4] == RegimeState.CRISIS.value
        # 改善后第 1、2 条仍为 CRISIS
        assert result.iloc[5] == RegimeState.CRISIS.value
        assert result.iloc[6] == RegimeState.CRISIS.value
        # 连续 window=3 条 BULL 之后确认
        assert result.iloc[5 + window - 1] == RegimeState.BULL.value

    def test_interrupted_improvement_resets(self):
        """
        改善过程被打断 → 重新计数，不会错误切换。
        """
        window = 3
        det    = RegimeDetector(_make_config(smoothing_window=window))
        n      = 20
        idx    = pd.bdate_range("2022-01-03", periods=n)

        # CRISIS 5 天，然后 BULL 2 天，CRISIS 1 天，BULL 3 天
        vix_vals = (
            [50.0] * 5   # CRISIS
            + [12.0] * 2  # BULL（改善中，但不够 3 根）
            + [50.0] * 1  # CRISIS（打断）
            + [12.0] * 12  # BULL（重新开始，足够 3 根）
        )
        spy = _make_spy(n, trend=0.0003)
        vix = pd.Series(vix_vals, index=idx)

        result = det.classify_series(spy, vix)
        # 第 7 条（index=6）为 BULL 的第 2 根，仍应为 CRISIS
        assert result.iloc[6] == RegimeState.CRISIS.value
        # 第 8 条（index=7）打断，立即恶化为 CRISIS
        assert result.iloc[7] == RegimeState.CRISIS.value
        # 第 8+3=11 条（index=10）改善完成 → BULL
        assert result.iloc[10] == RegimeState.BULL.value


# ── classify_series 输出格式 ──────────────────────────────────────────────────

class TestClassifySeriesOutput:
    def test_returns_string_series(self):
        det    = _make_detector()
        spy    = _make_spy(100)
        vix    = _make_vix(100)
        result = det.classify_series(spy, vix)
        assert isinstance(result, pd.Series)
        assert result.dtype == object  # string

    def test_length_equals_common_dates(self):
        det = _make_detector()
        spy = _make_spy(200)
        vix = _make_vix(200)
        assert len(det.classify_series(spy, vix)) == 200

    def test_all_values_valid_states(self):
        det    = _make_detector()
        spy    = _make_spy(200)
        vix    = _make_vix(200)
        result = det.classify_series(spy, vix)
        valid  = {s.value for s in RegimeState}
        assert set(result.unique()).issubset(valid)

    def test_insufficient_data_returns_neutral(self):
        det = _make_detector()
        spy = _make_spy(1)
        vix = _make_vix(1)
        result = det.classify_series(spy, vix)
        assert len(result) <= 1
        if len(result) == 1:
            assert result.iloc[0] == RegimeState.NEUTRAL.value

    def test_misaligned_index_uses_intersection(self):
        """spy 与 vix 的日期轴不完全重叠 → 取交集。"""
        det  = _make_detector()
        spy  = _make_spy(100)
        vix  = _make_vix(120)    # vix 多出 20 天
        res  = det.classify_series(spy, vix)
        assert len(res) == 100


# ── get_current ───────────────────────────────────────────────────────────────

class TestGetCurrent:
    def test_returns_regime_reading(self):
        det     = _make_detector()
        spy     = _make_spy(100)
        vix     = _make_vix(100)
        reading = det.get_current(spy, vix)
        assert isinstance(reading, RegimeReading)

    def test_date_is_last_date(self):
        det     = _make_detector()
        spy     = _make_spy(100)
        vix     = _make_vix(100)
        reading = det.get_current(spy, vix)
        assert reading.date == spy.index[-1]

    def test_vix_stored_correctly(self):
        det = _make_detector()
        spy = _make_spy(100)
        vix = _make_vix(100, level=22.5)
        reading = det.get_current(spy, vix)
        assert reading.vix == pytest.approx(22.5)

    def test_state_matches_classify_series_last(self):
        """get_current().state 与 classify_series().iloc[-1] 一致。"""
        det     = _make_detector()
        spy     = _make_spy(200)
        vix     = _make_vix(200, level=27.0)
        reading = det.get_current(spy, vix)
        series  = det.classify_series(spy, vix)
        assert reading.state.value == series.iloc[-1]

    def test_insufficient_data_returns_neutral(self):
        det     = _make_detector()
        spy     = _make_spy(1)
        vix     = _make_vix(1)
        reading = det.get_current(spy, vix)
        assert reading.state == RegimeState.NEUTRAL

    def test_str_representation(self):
        det     = _make_detector()
        spy     = _make_spy(100)
        vix     = _make_vix(100)
        reading = det.get_current(spy, vix)
        text    = str(reading)
        assert any(s.value in text for s in RegimeState)


# ── get_constraints ───────────────────────────────────────────────────────────

class TestGetConstraints:
    def test_returns_constraint_config(self):
        det  = _make_detector()
        constr = det.get_constraints(RegimeState.BULL)
        assert isinstance(constr, RegimePositionConstraintConfig)

    def test_all_6_states_have_constraints(self):
        det = _make_detector()
        for state in RegimeState:
            constr = det.get_constraints(state)
            assert constr is not None

    def test_unknown_state_raises_key_error(self):
        """position_constraints 缺失全部 regime → 构造时 model_validator 报 ValidationError。"""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            RegimeConfig(
                spy_ema_fast         = 50,
                spy_ema_slow         = 200,
                smoothing_window     = 3,
                position_constraints = {},   # 故意为空
            )

    def test_crisis_constraints_stricter_than_bull(self):
        """CRISIS 状态现金最低占比应高于 BULL。"""
        cfg = _make_config(
            position_constraints={
                "BULL":     RegimePositionConstraintConfig(target_cash_pct_min=0.00, target_cash_pct_max=0.10, max_single_position=0.35),
                "RISK_ON":  RegimePositionConstraintConfig(target_cash_pct_min=0.05, target_cash_pct_max=0.15, max_single_position=0.30),
                "NEUTRAL":  RegimePositionConstraintConfig(target_cash_pct_min=0.15, target_cash_pct_max=0.30, max_single_position=0.25),
                "CAUTIOUS": RegimePositionConstraintConfig(target_cash_pct_min=0.30, target_cash_pct_max=0.50, max_single_position=0.20),
                "RISK_OFF": RegimePositionConstraintConfig(target_cash_pct_min=0.50, target_cash_pct_max=0.80, max_single_position=0.15),
                "CRISIS":   RegimePositionConstraintConfig(target_cash_pct_min=0.80, target_cash_pct_max=1.00, max_single_position=0.10),
            }
        )
        det   = RegimeDetector(cfg)
        bull  = det.get_constraints(RegimeState.BULL)
        crisis = det.get_constraints(RegimeState.CRISIS)
        assert bull.max_single_position > crisis.max_single_position
        assert bull.target_cash_pct_min < crisis.target_cash_pct_min


# ── 多因子交互 ────────────────────────────────────────────────────────────────

class TestMultiFactorInteraction:
    def test_worst_factor_wins(self):
        """VIX = 12（BULL），但 SPY 回撤 -20%（CRISIS）→ 最终 CRISIS。"""
        det = _make_detector(smoothing=1)
        n   = 150
        idx = pd.bdate_range("2020-01-02", periods=n)
        # 前 100 天上涨 → 建立历史高点
        spy_up  = 400.0 * np.cumprod(1 + np.full(100, 0.001))
        # 后 50 天下跌 20%
        end_val = spy_up[-1] * 0.80
        spy_dn  = np.linspace(spy_up[-1], end_val, 50)
        spy = pd.Series(np.concatenate([spy_up, spy_dn]), index=idx)
        vix = pd.Series(12.0, index=idx)

        result = det.classify_series(spy, vix)
        assert result.iloc[-1] == RegimeState.CRISIS.value

    def test_tnx_spike_overrides_bull_vix(self):
        """TNX 骤升 + VIX 极低 → 状态至少 CAUTIOUS。"""
        from core.regime.regime_detector import _REGIME_RANK
        det = _make_detector(smoothing=1)
        n   = 50
        idx = pd.bdate_range("2022-01-03", periods=n)
        spy = _make_spy(n, trend=0.0003)
        vix = pd.Series(10.0, index=idx)
        tnx        = pd.Series(1.5, index=idx)
        tnx.iloc[-1] = 1.70  # 骤升 0.20 ≥ 0.15 阈值

        result = det.classify_series(spy, vix, tnx)
        last   = RegimeState(result.iloc[-1])
        assert _REGIME_RANK[last] >= _REGIME_RANK[RegimeState.CAUTIOUS]


# ── 辅助函数导入验证 ──────────────────────────────────────────────────────────

class TestImports:
    def test_can_import_from_package(self):
        from core.regime import RegimeDetector, RegimeReading, RegimeState
        assert RegimeDetector is not None

    def test_regime_rank_ordering(self):
        from core.regime.regime_detector import _REGIME_RANK
        assert _REGIME_RANK[RegimeState.BULL] < _REGIME_RANK[RegimeState.RISK_ON]
        assert _REGIME_RANK[RegimeState.RISK_ON] < _REGIME_RANK[RegimeState.NEUTRAL]
        assert _REGIME_RANK[RegimeState.NEUTRAL] < _REGIME_RANK[RegimeState.CAUTIOUS]
        assert _REGIME_RANK[RegimeState.CAUTIOUS] < _REGIME_RANK[RegimeState.RISK_OFF]
        assert _REGIME_RANK[RegimeState.RISK_OFF] < _REGIME_RANK[RegimeState.CRISIS]
