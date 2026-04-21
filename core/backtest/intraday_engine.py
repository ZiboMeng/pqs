"""
IntradayBacktestEngine: 日内（60m 主线）回测引擎。

设计原则
--------
- 无 look-ahead：bar T 的信号在 bar T+1 开盘成交
- EOD 强制平仓：每日最后一根 K 线（≥15:30）后，用收盘价清仓
- Confluence 过滤：
    score < 0.6  → 不入场（空仓）
    0.6 ≤ score < 0.8 → 半仓（目标权重 × 0.5）
    score ≥ 0.8 → 全仓
- 与 Stage 6 完全共享 ExecutionSimulator + CostModel

run_single_day()
----------------
核心最小单元：输入"一天的 K 线 + 信号 + 初始状态"，返回 DayResult。
BacktestEngine.run() 和 Paper Trading 都调用这同一个函数，
确保回测与实盘模拟行为一致。

数据约定
--------
  intraday_df  : OHLCV DataFrame，index=DatetimeIndex（ET tz-naive）
  signals_df   : 目标权重 DataFrame，与 intraday_df 同 index/columns，值 ∈ [0,1]
  confluence_df: 多空一致性评分 DataFrame，同 index/columns，值 ∈ [0,1]
                 若为 None，则默认全部为 1.0（不做 confluence 过滤）
  vix_series   : pd.Series，index=日期（不含时间），值=VIX 当日收盘
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from core.execution.cost_model import CostModel
from core.execution.execution_simulator import (
    ExecutionSimulator, Fill, Order, OrderSide,
)
from core.backtest.backtest_engine import BacktestResult, compute_metrics
from core.logging_setup import get_logger

logger = get_logger(__name__)

# EOD 强制平仓触发时间（分钟数，相对于 ET 0:00）
_EOD_CLOSE_MIN = 15 * 60 + 30  # 930

# Module-level defaults (used only when no config is injected)
_DEFAULT_CONF_NO_TRADE  = 0.60
_DEFAULT_CONF_FULL_SIZE = 0.80


# ── 单日结果 ──────────────────────────────────────────────────────────────────

@dataclass
class DayResult:
    """run_single_day() 的输出。"""
    date:          pd.Timestamp
    trades:        List[Fill]
    eod_positions: Dict[str, float]   # symbol → 股数（EOD 清仓后应全为 0）
    eod_cash:      float
    gross_pnl:     float              # 当日 P&L（不含成本）
    net_pnl:       float              # 当日 P&L（含成本）
    forced_close:  bool               # 是否触发 EOD 强制平仓

    @property
    def n_trades(self) -> int:
        return len(self.trades)

    @property
    def total_cost(self) -> float:
        return sum(f.cost_breakdown.total_cost_usd for f in self.trades)


@dataclass
class BarUpdate:
    """Per-bar state emitted by the intraday runtime.

    Fired once per bar processed by run_multi_day() when on_bar_complete
    is set. Gives callers (live paper engine, replay persistence, UI) a
    uniform view of what happened on this bar.
    """
    date:            pd.Timestamp
    bar_ts:          pd.Timestamp
    bar_index:       int
    is_last_bar:     bool
    orders:          List[Order]
    fills:           List[Fill]
    positions:       Dict[str, float]
    cash:            float
    portfolio_value: float
    equity:          float


# ── IntradayBacktestEngine ────────────────────────────────────────────────────

class IntradayBacktestEngine:
    """
    日内回测引擎。

    Parameters
    ----------
    cost_model          : CostModel 实例（与 BacktestEngine 共享）
    initial_capital     : 初始资金（USD）
    eod_force_close     : 是否在每日最后一根 K 线后强制清仓（默认 True）
    confluence_enabled  : 是否启用 confluence 过滤（默认 True）
    min_trade_usd       : 低于此金额的换仓忽略
    rebalance_threshold : 权重偏差小于此值不换仓
    """

    def __init__(
        self,
        cost_model:            CostModel,
        initial_capital:       float = 100_000.0,
        eod_force_close:       bool  = True,
        confluence_enabled:    bool  = True,
        min_trade_usd:         float = 100.0,
        rebalance_threshold:   float = 0.02,
        conf_no_trade:         float = _DEFAULT_CONF_NO_TRADE,
        conf_full_size:        float = _DEFAULT_CONF_FULL_SIZE,
    ):
        self._cost         = cost_model
        self._sim          = ExecutionSimulator(cost_model, freq="intraday", allow_partial=True)
        self._capital      = initial_capital
        self._eod_close    = eod_force_close
        self._conf_enabled = confluence_enabled
        self._min_trade    = min_trade_usd
        self._rebal_thr    = rebalance_threshold
        self._conf_no_trade  = conf_no_trade
        self._conf_full_size = conf_full_size
        # Diagnostic counter: incremented when a symbol is SKIPPED because its
        # T+1 open is missing / NaN / non-positive. Previously this path fell
        # back silently to same-bar close → lookahead bias. Expose for reports.
        self._skipped_missing_open: int = 0

    # ── 主入口 ────────────────────────────────────────────────────────────────

    def run(
        self,
        intraday_df:   pd.DataFrame,
        signals_df:    pd.DataFrame,
        confluence_df: Optional[pd.DataFrame] = None,
        vix_series:    Optional[pd.Series]    = None,
    ) -> BacktestResult:
        """
        完整日内回测（跨多个交易日）。

        Parameters
        ----------
        intraday_df  : 60m OHLCV，DatetimeIndex（ET tz-naive）
        signals_df   : 目标权重，同 index/columns
        confluence_df: confluence 评分，同 index/columns；None 表示不过滤
        vix_series   : 日度 VIX，index=date（不含时间）

        Returns
        -------
        BacktestResult（权益曲线 index 为交易日，非 K 线时间戳）
        """
        if intraday_df.empty or signals_df.empty:
            return _empty_result()

        # 对齐 index
        common_idx = intraday_df.index.intersection(signals_df.index)
        bars    = intraday_df.loc[common_idx]
        sigs    = signals_df.loc[common_idx]
        confs   = confluence_df.loc[common_idx] if confluence_df is not None else None

        # 按交易日分组
        dates = sorted(set(bars.index.date))

        # ── 状态 ──────────────────────────────────────────────────────────────
        cash:     float              = self._capital
        shares:   Dict[str, float]   = {}
        all_fills: List[Fill]        = []
        equity_records:  list        = []
        date_index:      list        = []

        for date in dates:
            date_ts  = pd.Timestamp(date)
            day_mask = bars.index.date == date
            day_bars = bars.loc[day_mask]
            day_sigs = sigs.loc[day_mask]
            day_conf = confs.loc[day_mask] if confs is not None else None

            vix_val  = _get_vix(vix_series, date_ts)

            day_res = self.run_single_day(
                date      = date_ts,
                day_bars  = day_bars,
                day_sigs  = day_sigs,
                day_conf  = day_conf,
                positions = shares.copy(),
                cash      = cash,
                vix       = vix_val,
            )

            # 更新状态
            shares = day_res.eod_positions
            cash   = day_res.eod_cash
            all_fills.extend(day_res.trades)

            # 日末权益 = 现金 + 持仓市值（EOD 已平仓则仅现金）
            if "close" in day_bars.columns:
                last_bar = day_bars.iloc[-1]
                if isinstance(last_bar.get("close"), (int, float, np.floating)):
                    eod_prices = {"_default": float(last_bar["close"])}
                else:
                    eod_prices = {}
            else:
                eod_prices = {}
            port_val = cash + sum(
                shares.get(sym, 0) * eod_prices.get(sym, eod_prices.get("_default", 0))
                for sym in shares
            )
            equity_records.append(port_val)
            date_index.append(date_ts)

        equity_curve = pd.Series(equity_records, index=pd.DatetimeIndex(date_index), name="equity")
        metrics      = compute_metrics(equity_curve, initial_capital=self._capital)

        return BacktestResult(
            equity_curve = equity_curve,
            positions    = pd.DataFrame(),     # 日内持仓不跨日，简化
            weights      = pd.DataFrame(),
            cash_curve   = pd.Series(dtype=float),
            trades       = all_fills,
            metrics      = metrics,
        )

    # ── Multi-asset 单日执行 ────────────────────────────────────────────────────

    def run_multi_day(
        self,
        date:        pd.Timestamp,
        day_bars:    Dict[str, pd.DataFrame],
        target_wts:  Dict[str, float],
        positions:   Dict[str, float],
        cash:        float,
        vix:         float = 15.0,
        target_wts_fn: Optional[Callable[[pd.Timestamp, Dict[str, float], float], Dict[str, float]]] = None,
        on_bar_complete: Optional[Callable[["BarUpdate"], None]] = None,
        skip_bar_fn: Optional[Callable[[pd.Timestamp], bool]] = None,
    ) -> DayResult:
        """
        Execute one trading day across multiple assets using intraday bars.

        Parameters
        ----------
        day_bars   : {symbol → DataFrame with OHLCV columns} for this day
        target_wts : {symbol → target weight} from strategy signal (static)
        positions  : {symbol → shares held} at start of day
        cash       : cash at start of day
        vix        : VIX value for cost model

        Optional per-bar hooks (enables live / replay / persistence):
        target_wts_fn  : called at each bar as fn(bar_ts, positions, cash) →
                         dict; overrides static `target_wts` when provided.
                         Return None or {} to hold current allocation.
        on_bar_complete: called AFTER fills are booked on each bar with a
                         BarUpdate snapshot (bar index, orders, fills,
                         positions, cash, equity). Used by paper engine for
                         persistence + checkpoint.
        skip_bar_fn    : called at the start of each bar as fn(bar_ts) →
                         bool. True = skip this bar entirely (no order gen,
                         no fills, no hook). Used for idempotent re-runs.

        Returns DayResult with fills, eod_positions, eod_cash.
        """
        shares = positions.copy()
        cur_cash = cash
        fills: List[Fill] = []

        if not day_bars:
            return DayResult(date=date, trades=[], eod_positions=shares,
                             eod_cash=cur_cash, gross_pnl=0.0, net_pnl=0.0, forced_close=False)

        ref_sym = next(iter(day_bars))
        ref_df = day_bars[ref_sym]
        bar_times = ref_df.index
        n_bars = len(bar_times)

        init_val = cur_cash + self._multi_portfolio_value(shares, day_bars, 0)

        for i in range(n_bars - 1):
            bar_ts = bar_times[i]
            next_idx = i + 1

            if skip_bar_fn is not None and skip_bar_fn(bar_ts):
                continue

            port_val = cur_cash + self._multi_portfolio_value(shares, day_bars, i)
            if port_val <= 0:
                continue

            # Per-bar target weight refresh hook (live mode uses this to
            # re-compute signals as new bars close).
            if target_wts_fn is not None:
                tw = target_wts_fn(bar_ts, dict(shares), cur_cash)
                if tw is None:
                    bar_targets = target_wts
                else:
                    bar_targets = tw
            else:
                bar_targets = target_wts

            cur_w = {}
            for sym, qty in shares.items():
                if sym in day_bars and i < len(day_bars[sym]):
                    p = day_bars[sym]["close"].iloc[i]
                    if not np.isnan(p) and float(p) > 0:
                        cur_w[sym] = (qty * float(p)) / port_val

            open_prices = {}
            for sym in set(list(cur_w) + list(bar_targets)):
                if sym in day_bars and next_idx < len(day_bars[sym]):
                    op = day_bars[sym]["open"].iloc[next_idx]
                    if not np.isnan(op) and op > 0:
                        open_prices[sym] = float(op)

            orders = _generate_orders(
                cur_weights=cur_w, tgt_weights=bar_targets,
                portfolio_val=port_val, open_prices=open_prices,
                signal_date=bar_ts, min_trade_usd=self._min_trade,
                rebal_thr=self._rebal_thr,
            )

            new_fills = self._sim.simulate_fills(
                orders=orders, open_prices=open_prices, vix=vix, cash=cur_cash,
            )
            for f in new_fills:
                prev = shares.get(f.symbol, 0.0)
                if f.side == OrderSide.BUY:
                    shares[f.symbol] = prev + f.executed_qty
                else:
                    shares[f.symbol] = max(prev - f.executed_qty, 0.0)
                cur_cash += f.cash_delta
                fills.append(f)

            shares = {s: q for s, q in shares.items() if q > 1e-6}

            if on_bar_complete is not None:
                port_val_post = self._multi_portfolio_value(shares, day_bars, next_idx)
                equity_post = cur_cash + port_val_post
                on_bar_complete(BarUpdate(
                    date=date,
                    bar_ts=bar_ts,
                    bar_index=i,
                    is_last_bar=(i == n_bars - 2),
                    orders=list(orders),
                    fills=list(new_fills),
                    positions=dict(shares),
                    cash=cur_cash,
                    portfolio_value=port_val_post,
                    equity=equity_post,
                ))

        if self._eod_close and shares:
            eod_prices = {}
            for sym in list(shares):
                if sym in day_bars and len(day_bars[sym]) > 0:
                    eod_prices[sym] = float(day_bars[sym]["close"].iloc[-1])
            for sym, qty in list(shares.items()):
                if sym in eod_prices and eod_prices[sym] > 0:
                    order = Order(symbol=sym, side=OrderSide.SELL,
                                  qty_shares=qty, signal_date=date)
                    f = self._sim.simulate_fill(order, eod_prices[sym], vix, cur_cash)
                    if f:
                        shares[sym] = max(shares.get(sym, 0) - f.executed_qty, 0)
                        cur_cash += f.cash_delta
                        fills.append(f)
            shares = {s: q for s, q in shares.items() if q > 1e-6}

        end_val = cur_cash + self._multi_portfolio_value(shares, day_bars, -1)
        net_pnl = end_val - init_val

        return DayResult(date=date, trades=fills, eod_positions=shares,
                         eod_cash=cur_cash, gross_pnl=net_pnl, net_pnl=net_pnl,
                         forced_close=self._eod_close and len(shares) == 0)

    @staticmethod
    def _multi_portfolio_value(
        shares: Dict[str, float],
        day_bars: Dict[str, pd.DataFrame],
        bar_idx: int,
    ) -> float:
        total = 0.0
        for sym, qty in shares.items():
            if sym in day_bars and len(day_bars[sym]) > 0:
                idx = bar_idx if bar_idx >= 0 else len(day_bars[sym]) + bar_idx
                idx = max(0, min(idx, len(day_bars[sym]) - 1))
                p = day_bars[sym]["close"].iloc[idx]
                if not np.isnan(p):
                    total += qty * float(p)
        return total

    # ── 单日核心逻辑（Paper Trading 同样调用此函数）────────────────────────────

    def run_single_day(
        self,
        date:      pd.Timestamp,
        day_bars:  pd.DataFrame,      # 当日 60m OHLCV
        day_sigs:  pd.DataFrame,      # 当日目标权重信号
        day_conf:  Optional[pd.DataFrame],  # 当日 confluence 评分
        positions: Dict[str, float],  # 开盘前持仓（{symbol: qty}）
        cash:      float,
        vix:       float = 15.0,
    ) -> DayResult:
        """
        执行单个交易日的完整日内回测流程。

        流程：
          1. 逐 K 线遍历（bar T 信号 → bar T+1 成交）
          2. Confluence 过滤调整目标权重
          3. 生成差量订单 → 模拟成交
          4. EOD 强制平仓（若启用）

        这是 backtest 与 paper trading 共用的最小执行单元。
        """
        if day_bars.empty:
            return DayResult(
                date=date, trades=[], eod_positions=positions.copy(),
                eod_cash=cash, gross_pnl=0.0, net_pnl=0.0, forced_close=False,
            )

        bar_times  = day_bars.index
        n_bars     = len(bar_times)
        shares     = positions.copy()
        cur_cash   = cash
        fills:     List[Fill] = []
        init_val   = cash + _portfolio_value(shares, day_bars.iloc[0])
        forced     = False

        for i in range(n_bars - 1):
            bar_ts      = bar_times[i]
            next_bar_ts = bar_times[i + 1]
            next_bar    = day_bars.loc[next_bar_ts]

            # 当前 bar 的信号
            sig_row  = _get_row(day_sigs, bar_ts)
            conf_row = _get_row(day_conf, bar_ts) if day_conf is not None else None

            # Confluence 过滤 → 实际目标权重
            tgt_w = _apply_confluence(
                sig_row, conf_row, self._conf_enabled,
                self._conf_no_trade, self._conf_full_size,
            )

            # 当前权重
            port_val = cur_cash + _portfolio_value(shares, day_bars.loc[bar_ts])
            cur_w    = _current_weights(shares, day_bars.loc[bar_ts], port_val)

            # 生成订单（T+1 开盘价成交）。缺失或 NaN open → 跳过该 symbol（
            # 不再回退到同 bar close，避免同 bar 执行 / lookahead）。
            open_prices: Dict[str, float] = {}
            for sym in set(list(cur_w) + list(tgt_w)):
                op = next_bar.get("open", float("nan")) if hasattr(next_bar, "get") else float("nan")
                try:
                    op_f = float(op)
                except (TypeError, ValueError):
                    continue
                if np.isnan(op_f) or op_f <= 0:
                    self._skipped_missing_open += 1
                    continue
                open_prices[sym] = op_f

            orders = _generate_orders(
                cur_weights   = cur_w,
                tgt_weights   = tgt_w,
                portfolio_val = port_val,
                open_prices   = open_prices,
                signal_date   = bar_ts,
                min_trade_usd = self._min_trade,
                rebal_thr     = self._rebal_thr,
            )

            new_fills = self._sim.simulate_fills(
                orders      = orders,
                open_prices = open_prices,
                vix         = vix,
                cash        = cur_cash,
            )

            for f in new_fills:
                prev = shares.get(f.symbol, 0.0)
                if f.side == OrderSide.BUY:
                    shares[f.symbol] = prev + f.executed_qty
                else:
                    shares[f.symbol] = max(prev - f.executed_qty, 0.0)
                cur_cash += f.cash_delta
                fills.append(f)

        # ── EOD 强制平仓 ──────────────────────────────────────────────────────
        if self._eod_close and shares:
            last_bar  = day_bars.iloc[-1]
            last_time = bar_times[-1]
            last_min  = last_time.hour * 60 + last_time.minute

            if last_min >= _EOD_CLOSE_MIN or i == n_bars - 2:
                eod_fills = self._force_close(shares, last_bar, last_time, vix, cur_cash)
                for f in eod_fills:
                    shares[f.symbol] = max(shares.get(f.symbol, 0.0) - f.executed_qty, 0.0)
                    cur_cash += f.cash_delta
                    fills.append(f)
                forced = True

        # 清除零仓位
        shares = {s: q for s, q in shares.items() if q > 1e-6}

        final_val = cur_cash + _portfolio_value(shares, day_bars.iloc[-1])
        net_pnl   = final_val - init_val

        return DayResult(
            date          = date,
            trades        = fills,
            eod_positions = shares,
            eod_cash      = cur_cash,
            gross_pnl     = net_pnl,
            net_pnl       = net_pnl,
            forced_close  = forced,
        )

    # ── EOD 强制平仓 ──────────────────────────────────────────────────────────

    def _force_close(
        self,
        shares:    Dict[str, float],
        last_bar:  pd.Series,
        bar_ts:    pd.Timestamp,
        vix:       float,
        cash:      float,
    ) -> List[Fill]:
        """以最后一根 K 线的收盘价强制平仓所有持仓。"""
        orders = []
        for sym, qty in shares.items():
            if qty > 1e-6:
                orders.append(Order(
                    symbol      = sym,
                    side        = OrderSide.SELL,
                    qty_shares  = qty,
                    signal_date = bar_ts,
                    comment     = "EOD_FORCE_CLOSE",
                ))

        if not orders:
            return []

        # EOD 平仓用收盘价（而非次日开盘）
        close_prices = {}
        for sym in shares:
            col = "close" if "close" in last_bar.index else last_bar.index[0]
            close_prices[sym] = float(last_bar.get(col, 0))

        return self._sim.simulate_fills(
            orders      = orders,
            open_prices = close_prices,   # 用收盘价模拟 EOD 成交
            vix         = vix,
            cash        = cash,
        )


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _apply_confluence(
    sig_row:      Optional[pd.Series],
    conf_row:     Optional[pd.Series],
    enabled:      bool,
    conf_no_trade:  float = _DEFAULT_CONF_NO_TRADE,
    conf_full_size: float = _DEFAULT_CONF_FULL_SIZE,
) -> Dict[str, float]:
    """
    对目标权重应用 confluence 过滤。

    Returns
    -------
    dict  symbol → adjusted_weight
    """
    if sig_row is None:
        return {}

    tgt: Dict[str, float] = {}
    for sym, raw_w in sig_row.items():
        w = float(raw_w) if not np.isnan(raw_w) else 0.0
        if w <= 0:
            continue

        if enabled and conf_row is not None:
            score = float(conf_row.get(sym, 1.0))
            if score < conf_no_trade:
                w = 0.0
            elif score < conf_full_size:
                w = w * 0.5   # 半仓

        if w > 0:
            tgt[sym] = w

    return tgt


def _portfolio_value(shares: Dict[str, float], bar: pd.Series) -> float:
    """用 close 价格估算持仓市值。"""
    total = 0.0
    close = bar.get("close", 0) if hasattr(bar, "get") else 0
    for sym, qty in shares.items():
        p = float(bar.get(sym, close)) if hasattr(bar, "get") else float(close)
        total += qty * p
    return total


def _current_weights(
    shares:    Dict[str, float],
    bar:       pd.Series,
    port_val:  float,
) -> Dict[str, float]:
    if port_val <= 0:
        return {}
    close = float(bar.get("close", 0)) if hasattr(bar, "get") else 0.0
    return {
        sym: (qty * close) / port_val
        for sym, qty in shares.items()
        if qty > 0
    }


def _get_row(df: Optional[pd.DataFrame], ts: pd.Timestamp) -> Optional[pd.Series]:
    if df is None or ts not in df.index:
        return None
    return df.loc[ts]


def _get_vix(vix_series: Optional[pd.Series], date: pd.Timestamp) -> float:
    if vix_series is None:
        return 15.0
    d = date.normalize()
    if d in vix_series.index:
        return float(vix_series.loc[d])
    return 15.0


def _generate_orders(
    cur_weights:   Dict[str, float],
    tgt_weights:   Dict[str, float],
    portfolio_val: float,
    open_prices:   Dict[str, float],
    signal_date:   pd.Timestamp,
    min_trade_usd: float,
    rebal_thr:     float,
) -> List[Order]:
    """从权重差生成委托单（与 BacktestEngine._generate_orders 逻辑一致）。"""
    orders: List[Order] = []
    all_syms = set(list(cur_weights) + list(tgt_weights))

    for sym in all_syms:
        cur_w   = cur_weights.get(sym, 0.0)
        tgt_w   = tgt_weights.get(sym, 0.0)
        delta_w = tgt_w - cur_w

        if abs(delta_w) < rebal_thr and tgt_w > 0:
            continue

        price = open_prices.get(sym, 0.0)
        if price <= 0:
            continue

        delta_usd = abs(delta_w) * portfolio_val
        if delta_usd < min_trade_usd:
            continue

        qty  = delta_usd / price
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


def _empty_result() -> BacktestResult:
    return BacktestResult(
        equity_curve = pd.Series(dtype=float),
        positions    = pd.DataFrame(),
        weights      = pd.DataFrame(),
        cash_curve   = pd.Series(dtype=float),
        trades       = [],
        metrics      = {},
    )
