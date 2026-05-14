"""Data completeness admission gate — P0.b (Codex 2026-05-14 audit).

Scans the universe panel for stale-bar streaks within each symbol's
valid window. Used as a preflight gate before mining cycles + forward
init to prevent silent ghost-position-cleanup events.

Authority: docs/audit/20260514-comprehensive_project_audit.md §1.2 +
docs/memos/20260514-mining_full_inventory_for_discussion.md §14.10.7.

Codex finding: 81/81 symbol 都有 cross-symbol gap; ACGL/CMG/ISRG/MCK
ghost-position cleanup at 6+ stale days within their valid trading
window (e.g., ACGL 2017-01-25 ghost cleanup, ACGL data starts 2015-01-06).
Those are real internal gaps, not first_trade_date artifacts.

API
----
``check_symbol_completeness(panel: pd.DataFrame, symbol: str,
                            first_trade_date: Optional[pd.Timestamp] = None,
                            max_consecutive_missing_bd: int = 5
                            ) -> SymbolCompletenessResult``

``check_panel_completeness(panel: pd.DataFrame, universe: List[str],
                           first_trade_dates: Dict[str, str] = None,
                           max_consecutive_missing_bd: int = 5
                           ) -> PanelCompletenessReport``

Returns structured report; caller decides whether to abort or proceed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd


@dataclass
class GapSpan:
    """One consecutive-missing-business-day span for one symbol."""
    start_date: pd.Timestamp
    end_date: pd.Timestamp
    n_business_days: int

    def to_dict(self) -> dict:
        return {
            "start_date": self.start_date.strftime("%Y-%m-%d"),
            "end_date": self.end_date.strftime("%Y-%m-%d"),
            "n_business_days": self.n_business_days,
        }


@dataclass
class SymbolCompletenessResult:
    """Completeness scan result for one symbol."""
    symbol: str
    valid_start: Optional[pd.Timestamp]
    valid_end: Optional[pd.Timestamp]
    n_rows: int
    n_expected_business_days: int
    severe_gaps: List[GapSpan] = field(default_factory=list)  # > threshold
    minor_gaps: List[GapSpan] = field(default_factory=list)   # <= threshold but > 0
    passed: bool = True

    @property
    def n_severe_gaps(self) -> int:
        return len(self.severe_gaps)

    @property
    def total_missing_bd(self) -> int:
        return sum(g.n_business_days for g in self.severe_gaps + self.minor_gaps)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "valid_start": (self.valid_start.strftime("%Y-%m-%d")
                            if self.valid_start is not None else None),
            "valid_end": (self.valid_end.strftime("%Y-%m-%d")
                          if self.valid_end is not None else None),
            "n_rows": self.n_rows,
            "n_expected_business_days": self.n_expected_business_days,
            "passed": self.passed,
            "n_severe_gaps": self.n_severe_gaps,
            "total_missing_bd": self.total_missing_bd,
            "severe_gaps": [g.to_dict() for g in self.severe_gaps],
            "minor_gaps": [g.to_dict() for g in self.minor_gaps],
        }


@dataclass
class PanelCompletenessReport:
    """Aggregate scan result for a universe panel."""
    universe_size: int
    threshold_bd: int
    n_pass: int
    n_fail: int
    per_symbol: Dict[str, SymbolCompletenessResult] = field(default_factory=dict)

    @property
    def overall_passed(self) -> bool:
        return self.n_fail == 0

    @property
    def failed_symbols(self) -> List[str]:
        return sorted(s for s, r in self.per_symbol.items() if not r.passed)

    @property
    def passed_symbols(self) -> List[str]:
        return sorted(s for s, r in self.per_symbol.items() if r.passed)

    def to_dict(self) -> dict:
        return {
            "universe_size": self.universe_size,
            "threshold_bd": self.threshold_bd,
            "overall_passed": self.overall_passed,
            "n_pass": self.n_pass,
            "n_fail": self.n_fail,
            "failed_symbols": self.failed_symbols,
            "per_symbol": {s: r.to_dict() for s, r in self.per_symbol.items()},
        }


def _detect_gap_spans(
    actual_dates: pd.DatetimeIndex,
    expected_dates: pd.DatetimeIndex,
) -> List[Tuple[pd.Timestamp, pd.Timestamp, int]]:
    """Find consecutive-missing-business-day spans.

    Returns list of (start_date, end_date, n_bd) tuples for each span of
    expected business days that are missing from actual_dates.

    Spans are merged: 3 consecutive missing days → ONE span of n_bd=3.
    """
    if len(expected_dates) == 0:
        return []
    actual_set = set(actual_dates)
    missing = [d for d in expected_dates if d not in actual_set]
    if not missing:
        return []

    spans: List[Tuple[pd.Timestamp, pd.Timestamp, int]] = []
    span_start = missing[0]
    prev = missing[0]
    n = 1
    # Build B-day index ordering for "consecutive" check
    pos = {d: i for i, d in enumerate(expected_dates)}
    for cur in missing[1:]:
        if pos[cur] == pos[prev] + 1:
            n += 1
            prev = cur
        else:
            spans.append((span_start, prev, n))
            span_start = cur
            prev = cur
            n = 1
    spans.append((span_start, prev, n))
    return spans


def check_symbol_completeness(
    panel: pd.DataFrame,
    symbol: str,
    first_trade_date: Optional[pd.Timestamp] = None,
    max_consecutive_missing_bd: int = 5,
) -> SymbolCompletenessResult:
    """Scan one symbol's column in `panel` for stale-bar streaks.

    Args:
        panel: DataFrame indexed by date with `symbol` as a column.
        symbol: column name to scan.
        first_trade_date: scan window starts at max(symbol's first non-NaN,
            first_trade_date). Defaults to symbol's first non-NaN date.
        max_consecutive_missing_bd: threshold above which a gap is "severe".

    Returns:
        SymbolCompletenessResult.
    """
    if symbol not in panel.columns:
        return SymbolCompletenessResult(
            symbol=symbol, valid_start=None, valid_end=None,
            n_rows=0, n_expected_business_days=0, passed=False,
        )
    series = panel[symbol].dropna()
    if len(series) == 0:
        return SymbolCompletenessResult(
            symbol=symbol, valid_start=None, valid_end=None,
            n_rows=0, n_expected_business_days=0, passed=False,
        )
    actual_first = series.index.min()
    actual_last = series.index.max()
    if first_trade_date is not None:
        valid_start = max(actual_first, pd.Timestamp(first_trade_date))
    else:
        valid_start = actual_first
    valid_end = actual_last
    if valid_start > valid_end:
        return SymbolCompletenessResult(
            symbol=symbol, valid_start=valid_start, valid_end=valid_end,
            n_rows=len(series), n_expected_business_days=0, passed=True,
        )

    expected_bd = pd.bdate_range(valid_start, valid_end)
    in_window = series.index[(series.index >= valid_start)
                              & (series.index <= valid_end)]
    spans = _detect_gap_spans(in_window, expected_bd)

    severe = [GapSpan(s, e, n) for s, e, n in spans if n > max_consecutive_missing_bd]
    minor = [GapSpan(s, e, n) for s, e, n in spans if n <= max_consecutive_missing_bd]
    passed = len(severe) == 0

    return SymbolCompletenessResult(
        symbol=symbol, valid_start=valid_start, valid_end=valid_end,
        n_rows=len(in_window), n_expected_business_days=len(expected_bd),
        severe_gaps=severe, minor_gaps=minor, passed=passed,
    )


def check_panel_completeness(
    panel: pd.DataFrame,
    universe: List[str],
    first_trade_dates: Optional[Dict[str, str]] = None,
    max_consecutive_missing_bd: int = 5,
) -> PanelCompletenessReport:
    """Run completeness scan over each symbol in `universe`.

    Args:
        panel: date × symbol DataFrame (e.g., close panel from BarStore).
        universe: list of symbols to scan.
        first_trade_dates: optional mapping {symbol: 'YYYY-MM-DD'}; gaps
            BEFORE first_trade_date are not counted (e.g., from
            universe.yaml::first_trade_dates).
        max_consecutive_missing_bd: severe threshold; default 5 matches
            BacktestEngine.stale_days_threshold (= ghost-cleanup trigger).

    Returns:
        PanelCompletenessReport.
    """
    ftd_map = first_trade_dates or {}
    per_symbol: Dict[str, SymbolCompletenessResult] = {}
    n_pass = 0
    n_fail = 0
    for sym in universe:
        ftd_raw = ftd_map.get(sym)
        ftd = pd.Timestamp(ftd_raw) if ftd_raw else None
        res = check_symbol_completeness(
            panel, sym, first_trade_date=ftd,
            max_consecutive_missing_bd=max_consecutive_missing_bd,
        )
        per_symbol[sym] = res
        if res.passed:
            n_pass += 1
        else:
            n_fail += 1
    return PanelCompletenessReport(
        universe_size=len(universe),
        threshold_bd=max_consecutive_missing_bd,
        n_pass=n_pass, n_fail=n_fail, per_symbol=per_symbol,
    )
