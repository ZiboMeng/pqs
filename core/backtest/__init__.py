"""core.backtest — 日线/日内回测引擎与滚动窗口分析。"""

from core.backtest.backtest_engine import BacktestEngine, BacktestResult, compute_metrics
from core.backtest.intraday_engine import IntradayBacktestEngine, DayResult
from core.backtest.window_analyzer import WindowAnalyzer, WindowResult, AcceptanceResult

__all__ = [
    "BacktestEngine", "BacktestResult", "compute_metrics",
    "IntradayBacktestEngine", "DayResult",
    "WindowAnalyzer", "WindowResult", "AcceptanceResult",
]
