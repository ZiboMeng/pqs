"""Unit tests for core/research/pead/earnings_dates.py.

Covers PIT semantics:
  - First-filed per period_end (handles SEC comparative-data restatement)
  - Standalone-Q duration filter (60-100 days for 10-Q, 300-380 for 10-K)
  - Multi-form acceptance (10-Q + 10-K + amendments)
  - Empty / missing-ticker handling

Uses a mock EdgarProvider returning crafted TagFact lists so tests are
deterministic and do NOT depend on the cached AAPL JSON.
"""

from __future__ import annotations

from typing import List
from unittest.mock import MagicMock

import pandas as pd
import pytest

from core.data.edgar_provider import TagFact
from core.research.pead.earnings_dates import (
    extract_earnings_dates,
    extract_earnings_dates_panel,
)


def _fact(end, filed, val, form="10-Q", fy=2020, fp="Q1", start=None) -> TagFact:
    if start is None:
        # Default to ~91 days before end (standalone-Q)
        start = (pd.Timestamp(end) - pd.Timedelta(days=91)).strftime("%Y-%m-%d")
    return TagFact(
        start=start, end=end, val=float(val), accn="X",
        fy=fy, fp=fp, form=form, filed=filed, unit="USD/shares",
    )


def _mock_provider(facts: List[TagFact]) -> MagicMock:
    p = MagicMock()
    p.get_tag_facts.return_value = facts
    return p


# ── Empty / missing data ──

def test_empty_facts_returns_empty_df():
    p = _mock_provider([])
    df = extract_earnings_dates("AAPL", edgar_provider=p)
    assert df.empty


def test_missing_cik_returns_empty_df():
    p = MagicMock()
    p.get_tag_facts.side_effect = ValueError("no cik")
    df = extract_earnings_dates("XXX", edgar_provider=p)
    assert df.empty


def test_missing_cache_file_returns_empty_df():
    p = MagicMock()
    p.get_tag_facts.side_effect = FileNotFoundError("no cache")
    df = extract_earnings_dates("AAPL", edgar_provider=p)
    assert df.empty


# ── Single clean filing ──

def test_single_filing_one_row():
    p = _mock_provider([
        _fact("2024-03-30", "2024-05-02", 1.50, fy=2024, fp="Q2",
              start="2023-12-31"),
    ])
    df = extract_earnings_dates("AAPL", edgar_provider=p)
    assert len(df) == 1
    assert df.iloc[0]["ticker"] == "AAPL"
    assert df.iloc[0]["period_end"] == pd.Timestamp("2024-03-30")
    assert df.iloc[0]["first_filed_date"] == pd.Timestamp("2024-05-02")
    assert df.iloc[0]["eps_value"] == 1.50


# ── First-filed selection (the load-bearing logic) ──

def test_first_filed_wins_over_restatement():
    """Same period_end, two filed_dates → MIN(filed_date) wins."""
    p = _mock_provider([
        # initial filing
        _fact("2023-09-30", "2023-11-02", 1.46, fy=2023, fp="Q3"),
        # 1 year later "restatement" via comparative data in Q3 2024 filing
        _fact("2023-09-30", "2024-11-01", 1.46, fy=2024, fp="Q3"),
    ])
    df = extract_earnings_dates("AAPL", edgar_provider=p)
    assert len(df) == 1
    assert df.iloc[0]["first_filed_date"] == pd.Timestamp("2023-11-02")
    assert df.iloc[0]["fy"] == 2023


def test_three_way_restatement_takes_earliest():
    """Same period_end across 3 fy reports → earliest filed_date."""
    p = _mock_provider([
        _fact("2022-12-31", "2023-02-01", 0.95, fy=2022, fp="Q4"),
        _fact("2022-12-31", "2024-02-01", 0.95, fy=2023, fp="Q4"),
        _fact("2022-12-31", "2025-02-01", 0.95, fy=2024, fp="Q4"),
    ])
    df = extract_earnings_dates("AAPL", edgar_provider=p)
    assert len(df) == 1
    assert df.iloc[0]["first_filed_date"] == pd.Timestamp("2023-02-01")
    assert df.iloc[0]["fy"] == 2022


# ── Duration filter ──

def test_ytd_cumulative_filtered_out():
    """10-Q with YTD-cumulative window (270 days) is excluded; only
    standalone-Q (91d) survives.

    EDGAR reports both for same filed_date — duration filter discriminates.
    """
    p = _mock_provider([
        _fact("2023-09-30", "2023-11-02", 1.46, fy=2023, fp="Q3",
              start="2023-07-01"),  # 91d — standalone Q3
        _fact("2023-09-30", "2023-11-02", 4.13, fy=2023, fp="Q3",
              start="2023-01-01"),  # 272d — YTD-cumulative Q1+Q2+Q3
    ])
    df = extract_earnings_dates("AAPL", edgar_provider=p)
    assert len(df) == 1
    assert df.iloc[0]["duration_days"] == 91
    assert df.iloc[0]["eps_value"] == 1.46


def test_short_duration_q_filtered_out():
    """10-Q with start-end < 60 days is excluded (degenerate)."""
    p = _mock_provider([
        _fact("2023-03-31", "2023-05-02", 0.50, start="2023-03-01"),  # 30d
    ])
    df = extract_earnings_dates("AAPL", edgar_provider=p)
    assert df.empty


def test_long_duration_q_filtered_out():
    """10-Q with start-end > 100 days is excluded (likely YTD or annual)."""
    p = _mock_provider([
        _fact("2023-12-31", "2024-02-02", 5.0, fp="Q4",
              start="2023-01-01"),  # 364d as a 10-Q — illegal
    ])
    df = extract_earnings_dates("AAPL", edgar_provider=p)
    assert df.empty


def test_annual_10k_accepted():
    p = _mock_provider([
        _fact("2023-09-30", "2023-11-02", 6.13, form="10-K", fy=2023, fp="FY",
              start="2022-10-01"),  # ~365 days
    ])
    df = extract_earnings_dates("AAPL", edgar_provider=p)
    assert len(df) == 1
    assert df.iloc[0]["form"] == "10-K"
    assert df.iloc[0]["duration_days"] == 364  # 2022-10-01 → 2023-09-30 = 364d


def test_short_10k_filtered_out():
    """10-K with start-end < 300 days is excluded."""
    p = _mock_provider([
        _fact("2023-12-31", "2024-02-15", 5.0, form="10-K", fp="FY",
              start="2023-06-30"),  # 184d as 10-K — illegal
    ])
    df = extract_earnings_dates("AAPL", edgar_provider=p)
    assert df.empty


# ── Form acceptance ──

def test_amendment_form_accepted():
    """10-Q/A should be accepted as a valid form."""
    p = _mock_provider([
        _fact("2023-06-30", "2024-01-15", 1.30, form="10-Q/A", fy=2023, fp="Q2"),
    ])
    df = extract_earnings_dates("AAPL", edgar_provider=p)
    assert len(df) == 1
    assert df.iloc[0]["form"] == "10-Q/A"


def test_8k_form_rejected():
    """8-K (earnings release) is NOT in accepted forms — skipped."""
    p = _mock_provider([
        _fact("2023-06-30", "2023-08-02", 1.30, form="8-K", fy=2023, fp="Q2"),
    ])
    df = extract_earnings_dates("AAPL", edgar_provider=p)
    assert df.empty


def test_amendment_takes_initial_if_earlier():
    """If both 10-Q and 10-Q/A exist for same period_end, MIN(filed) wins."""
    p = _mock_provider([
        _fact("2023-06-30", "2023-08-02", 1.30, form="10-Q", fy=2023, fp="Q2"),
        _fact("2023-06-30", "2024-01-15", 1.32, form="10-Q/A", fy=2023, fp="Q2"),
    ])
    df = extract_earnings_dates("AAPL", edgar_provider=p)
    assert len(df) == 1
    assert df.iloc[0]["form"] == "10-Q"
    assert df.iloc[0]["first_filed_date"] == pd.Timestamp("2023-08-02")
    assert df.iloc[0]["eps_value"] == 1.30


# ── Missing start field ──

def test_missing_start_field_skipped():
    """TagFact with start=None is skipped (cannot validate duration)."""
    p = _mock_provider([
        _fact("2023-09-30", "2023-11-02", 1.46, start=None),
    ])
    # _fact() default start fills, so override explicitly
    f = TagFact(
        start=None, end="2023-09-30", val=1.46, accn="X",
        fy=2023, fp="Q3", form="10-Q", filed="2023-11-02", unit="USD/shares",
    )
    p2 = _mock_provider([f])
    df = extract_earnings_dates("AAPL", edgar_provider=p2)
    assert df.empty


# ── Sort + multi-period contract ──

def test_output_sorted_by_period_end():
    p = _mock_provider([
        _fact("2024-03-30", "2024-05-02", 1.50, fp="Q2"),
        _fact("2023-12-30", "2024-02-01", 1.40, fp="Q1"),
        _fact("2024-06-29", "2024-08-01", 1.60, fp="Q3"),
    ])
    df = extract_earnings_dates("AAPL", edgar_provider=p)
    assert len(df) == 3
    assert list(df["period_end"]) == [
        pd.Timestamp("2023-12-30"),
        pd.Timestamp("2024-03-30"),
        pd.Timestamp("2024-06-29"),
    ]


# ── Multi-ticker panel ──

def test_panel_concatenates_multiple_tickers():
    p = MagicMock()

    def _facts(tag, unit):
        # Different facts per ticker. Mock doesn't support 'ticker' arg
        # so we use side_effect with a counter.
        pass

    call_count = {"n": 0}

    def side(ticker, *args, **kwargs):
        call_count["n"] += 1
        if ticker == "AAPL":
            return [_fact("2024-03-30", "2024-05-02", 1.50)]
        if ticker == "MSFT":
            return [_fact("2024-03-30", "2024-04-25", 2.94)]
        return []

    p.get_tag_facts.side_effect = side
    df = extract_earnings_dates_panel(["AAPL", "MSFT", "XYZ"], edgar_provider=p)
    assert len(df) == 2
    assert set(df["ticker"]) == {"AAPL", "MSFT"}
    # Sorted by first_filed_date ascending → MSFT before AAPL
    assert df.iloc[0]["ticker"] == "MSFT"
    assert df.iloc[1]["ticker"] == "AAPL"


def test_panel_empty_tickers_returns_empty():
    p = MagicMock()
    p.get_tag_facts.return_value = []
    df = extract_earnings_dates_panel(["XXX", "YYY"], edgar_provider=p)
    assert df.empty


def test_panel_single_ticker_with_data():
    p = MagicMock()
    p.get_tag_facts.return_value = [
        _fact("2024-03-30", "2024-05-02", 1.50),
    ]
    df = extract_earnings_dates_panel(["AAPL"], edgar_provider=p)
    assert len(df) == 1
    assert df.iloc[0]["ticker"] == "AAPL"
