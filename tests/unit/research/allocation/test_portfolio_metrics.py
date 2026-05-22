"""P4 — portfolio_metrics reusable acceptance-metric TDD."""
import numpy as np
import pandas as pd
import pytest

from core.research.allocation.portfolio_metrics import portfolio_metrics


def _panel(n=60, k=3, seed=5):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2022-01-03", periods=n)
    syms = [f"S{i}" for i in range(k)]
    close = pd.DataFrame(
        100.0 * np.cumprod(1 + rng.normal(0.0005, 0.012, (n, k)), axis=0),
        index=idx, columns=syms)
    return close, idx, syms


class TestPortfolioMetrics:
    def test_empty_weights(self):
        m = portfolio_metrics(pd.DataFrame(), pd.DataFrame())
        assert m["n_periods"] == 0 and m["cum_return"] == 0.0

    def test_full_invest_single_name_matches_that_name(self):
        """100% in S0 the whole window → cum_return == S0's full-window
        return. The 1-bar shift means the day-0 weight earns the
        day-0→day-1 return, so the held position captures the complete
        close[0]→close[-1] path."""
        close, idx, syms = _panel()
        w = pd.DataFrame(0.0, index=idx, columns=syms)
        w["S0"] = 1.0
        m = portfolio_metrics(w, close)
        s0_ret = float(close["S0"].iloc[-1] / close["S0"].iloc[0] - 1.0)
        assert m["cum_return"] == pytest.approx(s0_ret, abs=1e-4)
        assert m["n_periods"] == len(idx)

    def test_cash_is_flat(self):
        close, idx, syms = _panel()
        w = pd.DataFrame(0.0, index=idx, columns=syms)   # all cash
        m = portfolio_metrics(w, close)
        assert m["cum_return"] == pytest.approx(0.0, abs=1e-9)
        assert m["max_drawdown"] == pytest.approx(0.0, abs=1e-9)
        assert m["turnover_mean"] == pytest.approx(0.0, abs=1e-9)

    def test_turnover_counts_rebalances(self):
        close, idx, syms = _panel()
        w = pd.DataFrame(0.0, index=idx, columns=syms)
        w["S0"] = 1.0
        w.iloc[30:] = 0.0
        w.iloc[30:, w.columns.get_loc("S1")] = 1.0   # one switch S0→S1
        m = portfolio_metrics(w, close)
        # one full 2.0-turnover switch over n days → mean > 0
        assert m["turnover_mean"] > 0.0

    def test_max_drawdown_non_positive(self):
        close, idx, syms = _panel()
        w = pd.DataFrame(1.0 / 3, index=idx, columns=syms)
        m = portfolio_metrics(w, close)
        assert m["max_drawdown"] <= 0.0

    def test_benchmark_excess(self):
        close, idx, syms = _panel()
        w = pd.DataFrame(0.0, index=idx, columns=syms)
        w["S0"] = 1.0
        bench = close["S0"]               # benchmark == the held name
        m = portfolio_metrics(w, close, benchmark=bench)
        # holding exactly the benchmark → excess ≈ 0 (within entry-shift)
        assert abs(m["vs_benchmark_excess_cum"]) < 0.02

    def test_deterministic(self):
        close, idx, syms = _panel()
        w = pd.DataFrame(1.0 / 3, index=idx, columns=syms)
        assert portfolio_metrics(w, close) == portfolio_metrics(w, close)
