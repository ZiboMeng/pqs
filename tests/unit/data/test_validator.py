"""
Unit tests for DataValidator.

All tests use synthetic data — no network calls.
"""

import numpy as np
import pandas as pd

from core.data.validator import DataValidator, ValidationResult


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_clean(
    periods:  int = 300,
    start:    str = "2023-01-03",
    freq:     str = "D",
    close:    float = 100.0,
    volume:   float = 1_000_000.0,
) -> pd.DataFrame:
    """Synthetic clean OHLCV DataFrame (no issues)."""
    idx = pd.bdate_range(start, periods=periods)  # business days
    n   = len(idx)
    rng = np.random.default_rng(42)
    c   = close + rng.normal(0, 0.2, n).cumsum()
    c   = np.maximum(c, 1.0)
    df  = pd.DataFrame(
        {
            "open":   c * (1 - rng.uniform(0, 0.003, n)),
            "high":   c * (1 + rng.uniform(0, 0.005, n)),
            "low":    c * (1 - rng.uniform(0, 0.005, n)),
            "close":  c,
            "volume": volume,
        },
        index=idx,
    )
    df.index.name = "date"
    return df


# ── ValidationResult ──────────────────────────────────────────────────────────

class TestValidationResult:
    def test_passes_by_default(self):
        r = ValidationResult(symbol="SPY", freq="1d", passed=True)
        assert r.passed

    def test_add_issue_fails(self):
        r = ValidationResult(symbol="SPY", freq="1d", passed=True)
        r.add_issue("bad data")
        assert not r.passed
        assert "bad data" in r.issues

    def test_add_warning_doesnt_fail(self):
        r = ValidationResult(symbol="SPY", freq="1d", passed=True)
        r.add_warning("minor issue")
        assert r.passed
        assert "minor issue" in r.warnings

    def test_str_pass(self):
        r = ValidationResult(symbol="SPY", freq="1d", passed=True)
        assert "[PASS]" in str(r)

    def test_str_fail(self):
        r = ValidationResult(symbol="SPY", freq="1d", passed=True)
        r.add_issue("bad")
        assert "[FAIL]" in str(r)


# ── DataValidator — clean data ────────────────────────────────────────────────

class TestValidatorClean:
    def test_clean_data_passes(self):
        v   = DataValidator(min_bars=252)
        df  = _make_clean(300)
        res = v.validate(df, "SPY", "1d")
        assert res.passed, f"Expected PASS, got issues: {res.issues}"

    def test_validate_multi(self):
        v      = DataValidator()
        frames = {"SPY": _make_clean(300), "QQQ": _make_clean(300)}
        results = v.validate_multi(frames)
        assert all(r.passed for r in results.values())


# ── min_bars check ────────────────────────────────────────────────────────────

class TestMinBars:
    def test_few_bars_adds_warning(self):
        v   = DataValidator(min_bars=252)
        df  = _make_clean(50)  # less than 252
        res = v.validate(df, "SPY", "1d")
        # min_bars is a warning, not an issue
        assert any("bars" in w for w in res.warnings)
        # Still passes
        assert res.passed

    def test_none_df_fails(self):
        v   = DataValidator()
        res = v.validate(None, "SPY", "1d")
        assert not res.passed

    def test_empty_df_fails(self):
        v   = DataValidator()
        res = v.validate(pd.DataFrame(), "SPY", "1d")
        assert not res.passed


# ── price_sanity check ────────────────────────────────────────────────────────

class TestPriceSanity:
    def test_negative_close_fails(self):
        v  = DataValidator()
        df = _make_clean(50)
        df.loc[df.index[5], "close"] = -1.0
        res = v.validate(df, "SPY", "1d")
        assert not res.passed
        assert any("negative" in i for i in res.issues)

    def test_close_above_high_warns(self):
        v  = DataValidator()
        df = _make_clean(50)
        # Force close > high on one bar
        df.loc[df.index[5], "close"] = df.loc[df.index[5], "high"] * 1.1
        res = v.validate(df, "SPY", "1d")
        assert any("outside" in w for w in res.warnings)


# ── zero volume check ─────────────────────────────────────────────────────────

class TestZeroVolume:
    def test_excessive_zero_volume_warns(self):
        v  = DataValidator(max_zero_volume_ratio=0.05)
        df = _make_clean(100)
        # Set 20% of bars to zero volume
        df.loc[df.index[:20], "volume"] = 0.0
        res = v.validate(df, "SPY", "1d")
        assert any("zero volume" in w for w in res.warnings)

    def test_few_zero_volume_ok(self):
        v  = DataValidator(max_zero_volume_ratio=0.10)
        df = _make_clean(100)
        df.loc[df.index[:5], "volume"] = 0.0  # 5% exactly, not above threshold
        res = v.validate(df, "SPY", "1d")
        # Should not add warning for zero_volume
        assert not any("zero volume" in w for w in res.warnings)


# ── outlier check ─────────────────────────────────────────────────────────────

class TestOutliers:
    def test_extreme_outlier_warns(self):
        v  = DataValidator(outlier_sigma=3.0, max_outlier_ratio=0.001)
        df = _make_clean(300)
        # Inject a 50% single-day move
        df.loc[df.index[100], "close"] = df.loc[df.index[99], "close"] * 1.5
        res = v.validate(df, "SPY", "1d")
        assert any("outlier" in w.lower() for w in res.warnings)

    def test_no_outliers_on_clean_data(self):
        v  = DataValidator(outlier_sigma=5.0, max_outlier_ratio=0.005)
        df = _make_clean(300)
        res = v.validate(df, "SPY", "1d")
        # No outlier warning on clean synthetic data
        assert not any("outlier" in w.lower() for w in res.warnings)


# ── corporate action check ────────────────────────────────────────────────────

class TestCorporateActions:
    def test_large_gap_warns(self):
        v  = DataValidator(corp_action_threshold=0.15)
        df = _make_clean(100)
        # Simulate a 50% gap (unadjusted split)
        df.loc[df.index[50]:, "close"] *= 2.0
        res = v.validate(df, "SPY", "1d")
        assert any("corporate action" in w.lower() or "price move" in w.lower() for w in res.warnings)

    def test_normal_moves_no_warning(self):
        v  = DataValidator(corp_action_threshold=0.15)
        df = _make_clean(300)
        res = v.validate(df, "SPY", "1d")
        assert not any("corporate" in w.lower() for w in res.warnings)


# ── intraday skips daily-only checks ─────────────────────────────────────────

class TestIntradaySkip:
    def test_missing_days_skipped_for_intraday(self):
        """Missing trading day check should not run for intraday freq."""
        v   = DataValidator()
        idx = pd.date_range("2024-01-02 09:30", periods=50, freq="60min")
        df  = pd.DataFrame(
            {
                "open": 1.0, "high": 1.01, "low": 0.99,
                "close": 1.0, "volume": 1e6,
            },
            index=idx,
        )
        res = v.validate(df, "SPY", "60m")
        # Should not have "missing trading days" in issues
        assert not any("missing trading day" in i.lower() for i in res.issues)


# ── log_results (smoke test) ──────────────────────────────────────────────────

class TestLogResults:
    def test_log_results_no_exception(self):
        v   = DataValidator()
        df  = _make_clean(300)
        res = v.validate(df, "SPY", "1d")
        # Should not raise
        v.log_results({"SPY": res})
