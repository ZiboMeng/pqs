"""Causal structured SEC filing features and event-return labels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class StructuredEventPanel:
    features: dict[str, pd.DataFrame]
    event_mask: pd.DataFrame
    event_records: pd.DataFrame
    filing_records: pd.DataFrame


@dataclass(frozen=True, slots=True)
class LexicalEventPanel:
    features: dict[str, pd.DataFrame]
    event_mask: pd.DataFrame
    joined_filing_records: int


def _validate_sessions(sessions: pd.DatetimeIndex) -> None:
    if not isinstance(sessions, pd.DatetimeIndex):
        raise TypeError("sessions must be a DatetimeIndex")
    if sessions.tz is not None:
        raise ValueError("sessions must be timezone-naive exchange dates")
    if not sessions.is_monotonic_increasing or sessions.has_duplicates:
        raise ValueError("sessions must be sorted and unique")
    if bool((sessions.dayofweek >= 5).any()):
        raise ValueError("sessions must not contain weekends")


def build_structured_event_panel(
    metadata: pd.DataFrame,
    sessions: pd.DatetimeIndex,
    symbols: Sequence[str],
    *,
    development_start: str | pd.Timestamp,
    development_end: str | pd.Timestamp,
) -> StructuredEventPanel:
    """Map acceptance-time metadata to the strictly next session open."""

    _validate_sessions(sessions)
    required = {
        "ticker", "cik", "accession_number", "form", "report_date",
        "acceptance_datetime_utc", "items", "primary_document", "size_bytes",
        "is_xbrl", "is_inline_xbrl",
    }
    missing = required - set(metadata)
    if missing:
        raise ValueError(f"filing metadata lacks columns: {sorted(missing)}")
    frame = metadata.copy()
    frame["acceptance_datetime_utc"] = pd.to_datetime(
        frame["acceptance_datetime_utc"], utc=True, errors="raise")
    frame = frame.sort_values(
        ["ticker", "acceptance_datetime_utc", "accession_number"])
    frame["prior_filing_gap_days"] = (
        frame.groupby("ticker")["acceptance_datetime_utc"]
        .diff().dt.total_seconds().div(86_400.0)
    )
    frame["prior_same_form_gap_days"] = (
        frame.groupby(["ticker", "form"])["acceptance_datetime_utc"]
        .diff().dt.total_seconds().div(86_400.0)
    )

    local = frame["acceptance_datetime_utc"].dt.tz_convert(
        "America/New_York")
    frame["acceptance_local"] = local
    frame["acceptance_local_date"] = local.dt.tz_localize(None).dt.normalize()
    start = pd.Timestamp(development_start)
    end = pd.Timestamp(development_end)
    if start.tzinfo is not None or end.tzinfo is not None:
        raise ValueError("development boundaries must be timezone-naive dates")
    frame = frame[
        (frame["acceptance_local_date"] >= start)
        & (frame["acceptance_local_date"] <= end)
        & frame["ticker"].isin(symbols)
    ].copy()
    positions = np.searchsorted(
        sessions.to_numpy(dtype="datetime64[ns]"),
        frame["acceptance_local_date"].to_numpy(dtype="datetime64[ns]"),
        side="right",
    )
    valid = positions < len(sessions)
    frame = frame.loc[valid].copy()
    positions = positions[valid]
    frame["execution_date"] = sessions[positions].to_numpy()

    item_sets = frame["items"].fillna("").map(
        lambda value: {part.strip() for part in str(value).split(",")})
    frame["has_8k_202"] = (
        frame["form"].eq("8-K") & item_sets.map(lambda value: "2.02" in value)
    ).astype(float)
    frame["has_8k_701"] = (
        frame["form"].eq("8-K") & item_sets.map(lambda value: "7.01" in value)
    ).astype(float)
    frame["has_10q"] = frame["form"].eq("10-Q").astype(float)
    frame["has_10k"] = frame["form"].eq("10-K").astype(float)
    frame["size_log1p"] = np.log1p(frame["size_bytes"].clip(lower=0))
    frame["is_xbrl_float"] = frame["is_xbrl"].astype(float)
    frame["is_inline_xbrl_float"] = frame["is_inline_xbrl"].astype(float)
    local_minutes = local.loc[frame.index].dt.hour * 60 + local.loc[frame.index].dt.minute
    frame["after_close"] = (local_minutes >= 16 * 60).astype(float)
    frame["pre_open"] = (local_minutes < 9 * 60 + 30).astype(float)
    frame["prior_filing_gap_log1p"] = np.log1p(
        frame["prior_filing_gap_days"].clip(lower=0, upper=3650).fillna(3650))
    frame["prior_same_form_gap_log1p"] = np.log1p(
        frame["prior_same_form_gap_days"].clip(
            lower=0, upper=3650).fillna(3650))
    report_date = pd.to_datetime(frame["report_date"], errors="coerce")
    report_lag = (
        frame["acceptance_local_date"] - report_date
    ).dt.days.clip(lower=0, upper=3650)
    frame["report_date_present"] = report_date.notna().astype(float)
    frame["report_lag_log1p"] = np.log1p(report_lag.fillna(0))
    frame["primary_document_present"] = frame[
        "primary_document"].fillna("").ne("").astype(float)
    frame["filing_count"] = 1.0

    keys = ["execution_date", "ticker"]
    aggregated = frame.groupby(keys, sort=True).agg(
        filing_count=("filing_count", "sum"),
        has_8k_202=("has_8k_202", "max"),
        has_8k_701=("has_8k_701", "max"),
        has_10q=("has_10q", "max"),
        has_10k=("has_10k", "max"),
        size_log1p=("size_log1p", "max"),
        any_xbrl=("is_xbrl_float", "max"),
        any_inline_xbrl=("is_inline_xbrl_float", "max"),
        any_after_close=("after_close", "max"),
        any_pre_open=("pre_open", "max"),
        prior_filing_gap_log1p=("prior_filing_gap_log1p", "min"),
        prior_same_form_gap_log1p=("prior_same_form_gap_log1p", "min"),
        report_date_present=("report_date_present", "max"),
        report_lag_log1p=("report_lag_log1p", "min"),
        primary_document_present=("primary_document_present", "max"),
    ).reset_index()
    aggregated["filing_count_log1p"] = np.log1p(aggregated["filing_count"])
    feature_names = [
        "filing_count_log1p", "has_8k_202", "has_8k_701", "has_10q",
        "has_10k", "size_log1p", "any_xbrl", "any_inline_xbrl",
        "any_after_close", "any_pre_open", "prior_filing_gap_log1p",
        "prior_same_form_gap_log1p", "report_date_present",
        "report_lag_log1p", "primary_document_present",
    ]
    dates = pd.DatetimeIndex(sorted(aggregated["execution_date"].unique()))
    columns = list(symbols)
    features: dict[str, pd.DataFrame] = {}
    for name in feature_names:
        features[name] = aggregated.pivot(
            index="execution_date", columns="ticker", values=name,
        ).reindex(index=dates, columns=columns)
    event_mask = features["filing_count_log1p"].notna()
    return StructuredEventPanel(
        features=features,
        event_mask=event_mask,
        event_records=aggregated,
        filing_records=frame,
    )


def build_lexical_event_panel(
    structured: StructuredEventPanel,
    lexical_features: pd.DataFrame,
    symbols: Sequence[str],
    *,
    lexical_feature_names: Sequence[str],
) -> LexicalEventPanel:
    """Join immutable per-document features to causal filing event bundles."""

    keys = ["cik", "accession_number", "primary_document"]
    required = set(keys) | {"parse_status"} | set(lexical_feature_names)
    missing = required - set(lexical_features)
    if missing:
        raise ValueError(f"lexical artifact lacks columns: {sorted(missing)}")
    lexical = lexical_features[lexical_features["parse_status"].eq("PASS")].copy()
    if lexical.duplicated(keys).any():
        raise ValueError("lexical artifact has duplicate CIK/accession/document keys")
    filing = structured.filing_records.copy()
    joined = filing.merge(
        lexical[keys + list(lexical_feature_names)],
        on=keys,
        how="inner",
        validate="many_to_one",
    )
    if joined.empty:
        raise ValueError("no filing records match PASS lexical documents")
    group_keys = ["execution_date", "ticker"]
    aggregations = {
        name: (name, "mean") for name in lexical_feature_names
    }
    aggregated = joined.groupby(group_keys, sort=True).agg(**aggregations)
    aggregated["text_document_count_log1p"] = np.log1p(
        joined.groupby(group_keys).size())
    aggregated = aggregated.reset_index()
    dates = pd.DatetimeIndex(sorted(aggregated["execution_date"].unique()))
    columns = list(symbols)
    feature_names = list(lexical_feature_names) + ["text_document_count_log1p"]
    features = {
        name: aggregated.pivot(
            index="execution_date", columns="ticker", values=name,
        ).reindex(index=dates, columns=columns)
        for name in feature_names
    }
    return LexicalEventPanel(
        features=features,
        event_mask=features[feature_names[0]].notna(),
        joined_filing_records=len(joined),
    )


def make_event_open_to_close_residual_rank_labels(
    open_prices: pd.DataFrame,
    close_prices: pd.DataFrame,
    market_open: pd.Series,
    market_close: pd.Series,
    event_mask: pd.DataFrame,
    *,
    holding_sessions: int = 5,
    beta_window_sessions: int = 252,
    cash_distributions: pd.DataFrame | None = None,
    market_cash_distributions: pd.Series | None = None,
    total_return_close_prices: pd.DataFrame | None = None,
    market_total_return_close: pd.Series | None = None,
) -> pd.DataFrame:
    """Rank cash-aware open(T) to close(T+h-1) residual returns.

    A position bought at the execution-date open is not entitled to a cash
    distribution whose ex-date is that same session. Distributions from the
    following session through the exit session are added to terminal cash.
    Optional total-return close series are used only for trailing beta.
    """

    if holding_sessions < 1 or beta_window_sessions < 2:
        raise ValueError("holding and beta windows must be positive")
    if not open_prices.index.equals(close_prices.index):
        raise ValueError("open and close price indexes must match")
    if not open_prices.columns.equals(close_prices.columns):
        raise ValueError("open and close price columns must match")
    sessions = close_prices.index
    _validate_sessions(sessions)
    missing_dates = event_mask.index.difference(sessions)
    if len(missing_dates):
        raise KeyError(f"event dates absent from price sessions: {list(missing_dates[:5])}")
    market_open = market_open.reindex(sessions)
    market_close = market_close.reindex(sessions)
    if cash_distributions is None:
        cash = pd.DataFrame(
            0.0, index=sessions, columns=close_prices.columns)
    else:
        if (
            not cash_distributions.index.equals(sessions)
            or not cash_distributions.columns.equals(close_prices.columns)
        ):
            raise ValueError("cash distributions must align with stock prices")
        cash = cash_distributions.astype(float)
    if market_cash_distributions is None:
        market_cash = pd.Series(0.0, index=sessions)
    else:
        if not market_cash_distributions.index.equals(sessions):
            raise ValueError("market cash distributions must align with sessions")
        market_cash = market_cash_distributions.astype(float)
    if (
        not np.isfinite(cash.to_numpy()).all()
        or not np.isfinite(market_cash.to_numpy()).all()
        or bool((cash < 0).any().any())
        or bool((market_cash < 0).any())
    ):
        raise ValueError("cash distributions must be finite and non-negative")
    beta_close = (
        close_prices
        if total_return_close_prices is None
        else total_return_close_prices
    )
    if (
        not beta_close.index.equals(sessions)
        or not beta_close.columns.equals(close_prices.columns)
    ):
        raise ValueError("total-return stock closes must align with prices")
    if (
        market_total_return_close is not None
        and not market_total_return_close.index.equals(sessions)
    ):
        raise ValueError("total-return market close must align with sessions")
    beta_market_close = (
        market_close if market_total_return_close is None
        else market_total_return_close
    )
    stock_returns = beta_close.pct_change(fill_method=None)
    market_returns = beta_market_close.pct_change(fill_method=None)
    beta = stock_returns.rolling(
        beta_window_sessions, min_periods=beta_window_sessions,
    ).cov(market_returns).div(
        market_returns.rolling(
            beta_window_sessions, min_periods=beta_window_sessions).var(),
        axis=0,
    ).shift(1)
    residual = pd.DataFrame(
        np.nan, index=event_mask.index, columns=event_mask.columns)
    for date in event_mask.index:
        position = sessions.get_loc(date)
        exit_position = position + holding_sessions - 1
        if exit_position >= len(sessions):
            continue
        exit_date = sessions[exit_position]
        entitled_slice = sessions[position + 1:exit_position + 1]
        terminal_cash = cash.loc[entitled_slice].sum(axis=0)
        market_terminal_cash = float(market_cash.loc[entitled_slice].sum())
        stock_return = close_prices.loc[exit_date].add(
            terminal_cash).div(open_prices.loc[date]) - 1.0
        market_return = (
            (market_close.loc[exit_date] + market_terminal_cash)
            / market_open.loc[date]
            - 1.0
        )
        value = stock_return - beta.loc[date] * market_return
        residual.loc[date] = value.where(event_mask.loc[date])
    return residual.rank(axis=1, pct=True)


def event_eligibility_from_previous_close(
    daily_eligibility: pd.DataFrame,
    event_mask: pd.DataFrame,
) -> pd.DataFrame:
    """Apply trailing eligibility known immediately before event execution."""

    sessions = daily_eligibility.index
    _validate_sessions(sessions)
    output = pd.DataFrame(
        False, index=event_mask.index, columns=event_mask.columns)
    for date in event_mask.index:
        position = sessions.get_loc(date)
        if position == 0:
            continue
        output.loc[date] = daily_eligibility.iloc[position - 1].reindex(
            event_mask.columns).fillna(False) & event_mask.loc[date]
    return output.astype(bool)


__all__ = [
    "LexicalEventPanel",
    "StructuredEventPanel",
    "build_lexical_event_panel",
    "build_structured_event_panel",
    "event_eligibility_from_previous_close",
    "make_event_open_to_close_residual_rank_labels",
]
