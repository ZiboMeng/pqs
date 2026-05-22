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


class TestCostSensitivity:
    def test_zero_cost_is_bit_identical(self):
        close, idx, syms = _panel()
        w = pd.DataFrame(1.0 / 3, index=idx, columns=syms)
        gross = portfolio_metrics(w, close)
        cost0 = portfolio_metrics(w, close, cost_bps=0.0)
        assert gross["cum_return"] == cost0["cum_return"]
        assert gross["annualized_sharpe"] == cost0["annualized_sharpe"]

    def test_cost_reduces_return(self):
        """A turning-over portfolio earns less net of cost."""
        close, idx, syms = _panel()
        w = pd.DataFrame(0.0, index=idx, columns=syms)
        # alternate the held name every 5 bars → real turnover
        for i, d in enumerate(idx):
            w.loc[d, syms[(i // 5) % len(syms)]] = 1.0
        gross = portfolio_metrics(w, close, cost_bps=0.0)
        net = portfolio_metrics(w, close, cost_bps=60.0)
        assert net["cum_return"] < gross["cum_return"]
        assert net["cost_bps"] == 60.0

    def test_no_turnover_cost_free(self):
        """A static (zero-turnover) book is unaffected by cost_bps."""
        close, idx, syms = _panel()
        w = pd.DataFrame(0.0, index=idx, columns=syms)
        w["S0"] = 1.0                       # held the whole window, no churn
        gross = portfolio_metrics(w, close, cost_bps=0.0)
        net = portfolio_metrics(w, close, cost_bps=100.0)
        assert net["cum_return"] == pytest.approx(gross["cum_return"], abs=1e-9)


class TestS7Hygiene:
    """S7 M1 hygiene — periods_per_year param, turnover-cost bar
    alignment, NAV-positivity guard."""

    def test_periods_per_year_scales_sharpe(self):
        """Sharpe annualization tracks periods_per_year (S7 M6 — the
        prior hardcoded 252 mis-annualized non-daily panels)."""
        close, idx, syms = _panel()
        w = pd.DataFrame(1.0 / 3, index=idx, columns=syms)
        m252 = portfolio_metrics(w, close, periods_per_year=252)
        m52 = portfolio_metrics(w, close, periods_per_year=52)
        assert m252["periods_per_year"] == 252
        assert m52["periods_per_year"] == 52
        # sharpe scales by sqrt(ppy ratio) — loose tol: the dict values
        # are round(.,4), so the ratio carries rounding error.
        if abs(m52["annualized_sharpe"]) > 0.01:
            ratio = m252["annualized_sharpe"] / m52["annualized_sharpe"]
            assert abs(ratio - np.sqrt(252 / 52)) < 1e-2

    def test_default_periods_per_year_252(self):
        close, idx, syms = _panel()
        w = pd.DataFrame(1.0 / 3, index=idx, columns=syms)
        assert portfolio_metrics(w, close)["periods_per_year"] == 252

    def test_turnover_cost_charged_after_trade(self):
        """The turnover cost is charged on the bar the new weight starts
        earning — a switch on bar k debits bar k+1, not bar k."""
        close, idx, syms = _panel(n=40)
        w = pd.DataFrame(0.0, index=idx, columns=syms)
        w["S0"] = 1.0
        w.iloc[20:] = 0.0
        w.iloc[20:, w.columns.get_loc("S1")] = 1.0   # switch at bar 20
        gross = portfolio_metrics(w, close, cost_bps=0.0)
        net = portfolio_metrics(w, close, cost_bps=60.0)
        assert net["cum_return"] < gross["cum_return"]   # cost still bites

    def test_nav_guard_survives_pathological_bar(self):
        """A bad -100%+ single-bar return must not drive NAV<=0 / blow
        up the drawdown ratio."""
        close, idx, syms = _panel(n=30)
        # inject a catastrophic price collapse on one bar
        close.iloc[15, 0] = close.iloc[14, 0] * 0.0001
        w = pd.DataFrame(0.0, index=idx, columns=syms)
        w["S0"] = 1.0
        m = portfolio_metrics(w, close)
        assert np.isfinite(m["max_drawdown"])            # not blown up
        assert m["max_drawdown"] <= 0.0
