from __future__ import annotations

import numpy as np
import pandas as pd

from core.research.sec_event_features import (
    build_lexical_event_panel,
    build_structured_event_panel,
    event_eligibility_from_previous_close,
    make_event_open_to_close_residual_rank_labels,
)


def _metadata() -> pd.DataFrame:
    rows = []
    for position, ticker in enumerate(("A", "B", "C"), start=1):
        rows.append({
            "ticker": ticker,
            "cik": position,
            "accession_number": f"000{position}-24-000001",
            "form": "8-K" if ticker != "C" else "10-Q",
            "report_date": "2023-12-31",
            "acceptance_datetime_utc": "2024-01-05T21:30:00Z",
            "items": "2.02,9.01" if ticker != "C" else "",
            "primary_document": "filing.htm",
            "size_bytes": 100 * position,
            "is_xbrl": ticker == "C",
            "is_inline_xbrl": ticker == "C",
        })
    return pd.DataFrame(rows)


def test_acceptance_maps_to_strictly_next_session_and_features_are_causal():
    sessions = pd.bdate_range("2024-01-02", "2024-01-12")
    panel = build_structured_event_panel(
        _metadata(), sessions, ["A", "B", "C"],
        development_start="2024-01-01", development_end="2024-12-31")
    assert panel.event_mask.index.tolist() == [pd.Timestamp("2024-01-08")]
    assert panel.event_mask.loc["2024-01-08"].all()
    assert panel.features["any_after_close"].loc["2024-01-08", "A"] == 1.0
    assert panel.features["has_10q"].loc["2024-01-08", "C"] == 1.0


def test_event_label_uses_execution_open_and_fifth_session_close():
    sessions = pd.bdate_range("2024-01-02", periods=12)
    symbols = ["A", "B", "C"]
    base = 100.0 + np.arange(len(sessions))
    close = pd.DataFrame(
        {symbol: base.copy() for symbol in symbols}, index=sessions)
    close.loc[sessions[9], ["B", "C"]] += [5.0, 10.0]
    open_ = close - 0.5
    market_close = pd.Series(100.0 + np.arange(len(sessions)), index=sessions)
    market_open = market_close - 0.25
    event_date = sessions[5]
    mask = pd.DataFrame(True, index=pd.DatetimeIndex([event_date]), columns=symbols)
    labels = make_event_open_to_close_residual_rank_labels(
        open_, close, market_open, market_close, mask,
        holding_sessions=5, beta_window_sessions=3)
    assert labels.loc[event_date].notna().all()
    assert labels.loc[event_date, "C"] > labels.loc[event_date, "A"]


def test_event_label_excludes_entry_ex_date_cash_and_includes_later_cash():
    sessions = pd.bdate_range("2024-01-02", periods=12)
    symbols = ["A", "B", "C"]
    close = pd.DataFrame(
        {symbol: 100.0 + np.arange(len(sessions)) for symbol in symbols},
        index=sessions,
    )
    open_ = close - 0.5
    market_close = pd.Series(100.0 + np.arange(len(sessions)), index=sessions)
    market_open = market_close - 0.25
    event_date = sessions[5]
    mask = pd.DataFrame(
        True, index=pd.DatetimeIndex([event_date]), columns=symbols)
    cash = pd.DataFrame(0.0, index=sessions, columns=symbols)
    cash.loc[event_date, "B"] = 50.0
    cash.loc[sessions[7], "A"] = 10.0
    market_cash = pd.Series(0.0, index=sessions)
    total_return_close = close.copy()
    total_return_close.loc[sessions[7]:, "A"] *= (
        close.loc[sessions[7], "A"] + 10.0
    ) / close.loc[sessions[7], "A"]
    labels = make_event_open_to_close_residual_rank_labels(
        open_, close, market_open, market_close, mask,
        holding_sessions=5,
        beta_window_sessions=3,
        cash_distributions=cash,
        market_cash_distributions=market_cash,
        total_return_close_prices=total_return_close,
        market_total_return_close=market_close,
    )
    assert labels.loc[event_date, "A"] > labels.loc[event_date, "B"]
    assert labels.loc[event_date, "B"] == labels.loc[event_date, "C"]


def test_event_eligibility_uses_previous_close_not_execution_day_close():
    sessions = pd.bdate_range("2024-01-02", periods=4)
    daily = pd.DataFrame(
        {"A": [False, True, False, False]}, index=sessions)
    event = pd.DataFrame(
        {"A": [True]}, index=pd.DatetimeIndex([sessions[2]]))
    eligible = event_eligibility_from_previous_close(daily, event)
    assert eligible.loc[sessions[2], "A"]


def test_lexical_documents_join_by_permanent_filing_key():
    sessions = pd.bdate_range("2024-01-02", "2024-01-12")
    structured = build_structured_event_panel(
        _metadata(), sessions, ["A", "B", "C"],
        development_start="2024-01-01", development_end="2024-12-31")
    lexical = _metadata()[
        ["cik", "accession_number", "primary_document"]].copy()
    lexical["parse_status"] = ["PASS", "MISSING", "PASS"]
    lexical["tone"] = [1.0, 99.0, -1.0]
    panel = build_lexical_event_panel(
        structured,
        lexical,
        ["A", "B", "C"],
        lexical_feature_names=["tone"],
    )
    assert panel.joined_filing_records == 2
    assert panel.event_mask.loc["2024-01-08", ["A", "C"]].all()
    assert not panel.event_mask.loc["2024-01-08", "B"]
