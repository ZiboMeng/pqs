"""Unit tests for BacktestEngine and compute_metrics."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.config.schemas.cost_model import CostModelConfig, CostTierConfig
from core.execution.cost_model import CostModel
from core.backtest.backtest_engine import BacktestEngine, BacktestResult, compute_metrics


# ── 辅助函数 ──────────────────────────────────────────────────────────────────

def _make_cost_model() -> CostModel:
    cfg = CostModelConfig(
        tiers={
            "default": CostTierConfig(
                symbols=[],
                commission_bps=0.5,
                slippage_interday_bps=3.0,
                slippage_intraday_bps=5.0,
            )
        }
    )
    return CostModel(cfg)


def _make_price_df(
    n: int = 200,
    syms: list[str] = ("SPY", "QQQ"),
    start: str = "2022-01-03",
    seed: int = 42,
) -> pd.DataFrame:
    """生成合成日线收盘价矩阵（随机游走）。"""
    rng  = np.random.default_rng(seed)
    idx  = pd.bdate_range(start, periods=n)
    data = {}
    for sym in syms:
        ret  = rng.normal(0.0003, 0.012, n)   # 略带正漂移
        price = 100.0 * np.cumprod(1 + ret)
        data[sym] = price
    return pd.DataFrame(data, index=idx)


def _make_signals(
    price_df: pd.DataFrame,
    equal_weight: bool = True,
) -> pd.DataFrame:
    """生成等权重信号（所有 symbol 同等权重）。"""
    n    = len(price_df)
    syms = price_df.columns.tolist()
    w    = 1.0 / len(syms)
    data = {sym: [w] * n for sym in syms}
    return pd.DataFrame(data, index=price_df.index)


# ── BacktestEngine.run ────────────────────────────────────────────────────────

class TestBacktestEngineRun:
    def test_returns_backtest_result(self):
        price   = _make_price_df()
        signals = _make_signals(price)
        engine  = BacktestEngine(_make_cost_model(), initial_capital=100_000.0)
        result  = engine.run(signals, price)
        assert isinstance(result, BacktestResult)

    def test_equity_curve_length_matches_dates(self):
        price   = _make_price_df(100)
        signals = _make_signals(price)
        engine  = BacktestEngine(_make_cost_model())
        result  = engine.run(signals, price)
        assert len(result.equity_curve) == 100

    def test_equity_starts_at_initial_capital(self):
        price   = _make_price_df(100)
        signals = _make_signals(price)
        engine  = BacktestEngine(_make_cost_model(), initial_capital=100_000.0)
        result  = engine.run(signals, price)
        assert result.equity_curve.iloc[0] == pytest.approx(100_000.0)

    def test_equity_curve_positive(self):
        price   = _make_price_df(200)
        signals = _make_signals(price)
        engine  = BacktestEngine(_make_cost_model())
        result  = engine.run(signals, price)
        assert (result.equity_curve > 0).all()

    def test_no_negative_cash(self):
        price   = _make_price_df(100)
        signals = _make_signals(price)
        engine  = BacktestEngine(_make_cost_model())
        result  = engine.run(signals, price)
        # 现金可以因持仓而接近 0，但不应大幅负值
        assert result.cash_curve.min() > -1_000.0   # 小额浮动允许

    def test_trades_recorded(self):
        price   = _make_price_df(100)
        signals = _make_signals(price)
        engine  = BacktestEngine(_make_cost_model())
        result  = engine.run(signals, price)
        assert result.n_trades > 0

    def test_metrics_populated(self):
        price   = _make_price_df(200)
        signals = _make_signals(price)
        engine  = BacktestEngine(_make_cost_model())
        result  = engine.run(signals, price)
        for key in ["cagr", "sharpe", "max_drawdown", "volatility"]:
            assert key in result.metrics, f"Missing metric: {key}"

    def test_empty_signals_returns_empty_result(self):
        price   = _make_price_df(50)
        signals = pd.DataFrame()   # 空信号
        engine  = BacktestEngine(_make_cost_model())
        result  = engine.run(signals, price)
        assert result.equity_curve.empty

    def test_fills_use_open_prices_not_close(self):
        """Verify T-day signal executes at T+1 open, not T-day close."""
        zero_cost = CostModel(CostModelConfig(tiers={
            "default": CostTierConfig(
                symbols=[], commission_bps=0, slippage_interday_bps=0,
                slippage_intraday_bps=0,
            )
        }))
        n = 20
        idx = pd.bdate_range("2022-01-03", periods=n)
        close = pd.DataFrame({"A": [100.0] * n}, index=idx)
        open_df = pd.DataFrame({"A": [200.0] * n}, index=idx)
        signals = pd.DataFrame({"A": [1.0] * n}, index=idx)

        engine = BacktestEngine(zero_cost, initial_capital=10000)
        result = engine.run(signals, close, open_df=open_df)
        if result.trades:
            assert result.trades[0].executed_price == pytest.approx(200.0, rel=0.01)

    def test_nan_open_skips_order_no_fallback_to_close(self):
        """NaN T+1 open must cause the order to be skipped — not silently
        filled at close (previously the code did `open_row.get(sym,
        price_row.get(sym, 0.0))` creating lookahead)."""
        zero_cost = CostModel(CostModelConfig(tiers={
            "default": CostTierConfig(
                symbols=[], commission_bps=0, slippage_interday_bps=0,
                slippage_intraday_bps=0,
            )
        }))
        n = 5
        idx = pd.bdate_range("2022-01-03", periods=n)
        close = pd.DataFrame({"A": [100.0] * n}, index=idx)
        open_df = pd.DataFrame({"A": [np.nan] * n}, index=idx)  # no opens ever
        signals = pd.DataFrame({"A": [1.0] * n}, index=idx)

        engine = BacktestEngine(zero_cost, initial_capital=10000)
        result = engine.run(signals, close, open_df=open_df)
        # No fills should execute at close price (100)
        close_priced_fills = [t for t in result.trades
                              if abs(t.executed_price - 100.0) < 0.5]
        assert len(close_priced_fills) == 0, (
            "Orders should NOT have been filled at close when open is NaN"
        )
        # Diagnostic counter should be > 0
        assert engine._skipped_missing_open > 0, (
            "Missing-open skip counter should record at least one skipped order"
        )

    def test_no_ffill_on_reindexed_opens(self):
        """A date missing from open_df must stay NaN in the reindexed opens
        (previously `method='ffill'` silently copied prior date's open)."""
        zero_cost = CostModel(CostModelConfig(tiers={
            "default": CostTierConfig(
                symbols=[], commission_bps=0, slippage_interday_bps=0,
                slippage_intraday_bps=0,
            )
        }))
        idx = pd.bdate_range("2022-01-03", periods=5)
        close = pd.DataFrame({"A": [100.0] * 5}, index=idx)
        # Open only on odd-indexed days; even days → NaN (no ffill)
        open_data = [100.0, np.nan, 100.0, np.nan, 100.0]
        open_df = pd.DataFrame({"A": open_data}, index=idx)
        signals = pd.DataFrame({"A": [1.0] * 5}, index=idx)

        engine = BacktestEngine(zero_cost, initial_capital=10000)
        result = engine.run(signals, close, open_df=open_df)
        # Some orders skipped (NaN days) but the valid-open days should fill
        assert engine._skipped_missing_open > 0

    def test_open_df_none_uses_close_not_lookahead(self):
        """open_df=None → execution price = same-day close (no lookahead) —
        previously `prices.shift(-1).ffill()` used T+2 close (lookahead)."""
        zero_cost = CostModel(CostModelConfig(tiers={
            "default": CostTierConfig(
                symbols=[], commission_bps=0, slippage_interday_bps=0,
                slippage_intraday_bps=0,
            )
        }))
        idx = pd.bdate_range("2022-01-03", periods=10)
        # Make prices unambiguous: 100, 101, 102, ...
        close = pd.DataFrame({"A": [100.0 + i for i in range(10)]}, index=idx)
        signals = pd.DataFrame({"A": [1.0] * 10}, index=idx)

        engine = BacktestEngine(zero_cost, initial_capital=10000)
        result = engine.run(signals, close, open_df=None)
        # First trade (signal date=T=idx[0], exec at idx[1]) with open=None
        # should use close.loc[idx[1]] = 101.0 (not 102 or 103).
        if result.trades:
            first = result.trades[0]
            assert first.executed_price == pytest.approx(101.0, rel=0.01), (
                f"First fill should be at next-day close (101), got {first.executed_price}"
            )

    def test_hold_nothing_equity_flat(self):
        """全零信号（不持仓）→ 权益曲线应等于初始资金（全部在现金）。"""
        price    = _make_price_df(50)
        signals  = pd.DataFrame(0.0, index=price.index, columns=price.columns)
        engine   = BacktestEngine(_make_cost_model(), initial_capital=100_000.0)
        result   = engine.run(signals, price)
        assert (result.equity_curve - 100_000.0).abs().max() < 0.01

    def test_rebalance_threshold_reduces_trades(self):
        """高阈值换仓 → 交易次数应少于低阈值。"""
        price   = _make_price_df(100)
        signals = _make_signals(price)
        low  = BacktestEngine(_make_cost_model(), rebalance_threshold=0.001)
        high = BacktestEngine(_make_cost_model(), rebalance_threshold=0.20)
        r_low  = low.run(signals, price)
        r_high = high.run(signals, price)
        assert r_high.n_trades <= r_low.n_trades

    def test_bullish_signals_grow_equity(self):
        """持续上涨行情 + 满仓信号 → 期末权益应高于初始资金。"""
        n    = 200
        idx  = pd.bdate_range("2022-01-03", periods=n)
        # 构造单调上涨价格
        price   = pd.DataFrame({"SPY": 100.0 * (1.001 ** np.arange(n))}, index=idx)
        signals = pd.DataFrame({"SPY": 0.95}, index=idx)
        engine  = BacktestEngine(_make_cost_model(), initial_capital=100_000.0)
        result  = engine.run(signals, price)
        assert result.equity_curve.iloc[-1] > 100_000.0


# ── compute_metrics ───────────────────────────────────────────────────────────

class TestComputeMetrics:
    def _make_equity(self, n: int = 252, cagr: float = 0.10) -> pd.Series:
        idx  = pd.bdate_range("2022-01-03", periods=n)
        daily_ret = (1 + cagr) ** (1 / 252) - 1
        vals = 100_000.0 * np.cumprod([1 + daily_ret] * n)
        return pd.Series(vals, index=idx)

    def test_returns_dict(self):
        eq = self._make_equity()
        m  = compute_metrics(eq)
        assert isinstance(m, dict)

    def test_positive_cagr_for_rising_equity(self):
        eq = self._make_equity(cagr=0.15)
        m  = compute_metrics(eq)
        assert m["cagr"] > 0

    def test_total_return_positive(self):
        eq = self._make_equity(cagr=0.10)
        m  = compute_metrics(eq)
        assert m["total_return"] > 0

    def test_max_drawdown_negative(self):
        eq = self._make_equity()
        m  = compute_metrics(eq)
        assert m["max_drawdown"] <= 0

    def test_empty_equity_returns_empty_dict(self):
        m = compute_metrics(pd.Series(dtype=float))
        assert m == {}

    def test_sharpe_with_benchmark(self):
        eq    = self._make_equity(252)
        bench = self._make_equity(252, cagr=0.08)
        m     = compute_metrics(eq, initial_capital=100_000.0, benchmark=bench)
        assert "ir" in m
        assert "alpha" in m
        assert "beta" in m

    def test_flat_equity_zero_vol(self):
        idx = pd.bdate_range("2022-01-03", periods=10)
        eq  = pd.Series([100_000.0] * 10, index=idx)
        m   = compute_metrics(eq)
        assert m.get("volatility", 0.0) == pytest.approx(0.0, abs=1e-6)


# ── M12 concentration metrics surfaced in BacktestResult.metrics ──────────────
#
# Per codex Round-5 audit (`docs/claude_review_loop.md`): every
# BacktestEngine.run() must expose `m12_top1_weight_max` and
# `m12_top3_weight_max` so research / acceptance flows can opt-in
# enforce concentration without re-running the backtest. These are
# pure metrics — no policy is applied here; enforcement lives in
# acceptance_pack.Gate 7.


class TestBacktestResultM12Metrics:
    def test_m12_top1_top3_present_in_metrics(self):
        price   = _make_price_df()
        signals = _make_signals(price)
        engine  = BacktestEngine(_make_cost_model())
        result  = engine.run(signals, price)
        assert "m12_top1_weight_max" in result.metrics
        assert "m12_top3_weight_max" in result.metrics
        assert "m12_n_dates_with_weights" in result.metrics

    def test_m12_metrics_match_compute_concentration_metrics(self):
        """Sanity: the M12 fields in BacktestResult.metrics are identical
        to what compute_concentration_metrics(weights_df) returns
        directly. This confirms no transformation is happening between
        the engine and the helper."""
        from core.backtest.concentration_metrics import compute_concentration_metrics

        price   = _make_price_df()
        signals = _make_signals(price)
        engine  = BacktestEngine(_make_cost_model())
        result  = engine.run(signals, price)

        recomputed = compute_concentration_metrics(result.weights)
        assert result.metrics["m12_top1_weight_max"] == pytest.approx(
            recomputed["m12_top1_weight_max"]
        )
        assert result.metrics["m12_top3_weight_max"] == pytest.approx(
            recomputed["m12_top3_weight_max"]
        )

    def test_m12_metrics_do_not_break_default_run(self):
        """Equal-weight 2-symbol portfolio realizes top-1 ≈ 0.5 and
        would fail the opt-in validator, but the engine itself does
        NOT raise — M12 is opt-in in research / acceptance flows, not
        a default in BacktestEngine.

        This pins codex Round-5 §"do not make concentration enforcement
        break unrelated diagnostic or single-asset tests by default"."""
        price   = _make_price_df(syms=("SPY", "QQQ"))   # only 2 symbols
        signals = _make_signals(price)
        engine  = BacktestEngine(_make_cost_model())
        # Must NOT raise — just record metrics. The realized top-1 will
        # drift around 0.5 due to price action between rebalances; the
        # exact value is not the contract — engine-doesn't-raise is.
        result  = engine.run(signals, price)
        assert "m12_top1_weight_max" in result.metrics
        assert 0.4 < result.metrics["m12_top1_weight_max"] < 0.7, (
            "concentrated 2-symbol equal-weight should land in 0.4-0.7 "
            "neighborhood; getting outside this range likely indicates "
            "the metric extractor regressed"
        )


# ── Snapshot alignment (audit 2026-05-21) ─────────────────────────────────────

class TestSnapshotAlignment:
    """equity_curve / cash_curve / positions 必须描述同一个 (pre-fill,
    T-close) 组合状态。旧实现把 cash/positions 放在 T+1-open 成交循环
    之后 append → 同 index 上 equity 是 pre-fill、cash/positions 是
    post-fill，off-by-one。修复后三者满足会计恒等式。"""

    def test_equity_reconciles_with_cash_and_positions(self):
        price   = _make_price_df(60, syms=("SPY", "QQQ", "IWM"))
        signals = _make_signals(price)
        engine  = BacktestEngine(_make_cost_model(), initial_capital=100_000.0)
        result  = engine.run(signals, price)

        for dt in result.equity_curve.index:
            mark = sum(
                result.positions.loc[dt, s] * price.loc[dt, s]
                for s in price.columns if s in result.positions.columns
            )
            recon = result.cash_curve.loc[dt] + mark
            assert abs(recon - result.equity_curve.loc[dt]) < 1e-6, (
                f"{dt}: equity={result.equity_curve.loc[dt]:.6f} != "
                f"cash+positions={recon:.6f} — snapshot off-by-one"
            )
