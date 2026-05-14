"""Extract first-filed 10-Q / 10-K announcement dates from SEC EDGAR cache.

Used as the anchor date for PEAD signals (Path 1 SUE + Path 2 price-jump).

PIT semantics:
  - "First-filed for period_end T" = MIN(filed_date) across ALL rows where end == T.
  - This handles the SEC comparative-data artifact: when company files Q3 2024,
    SEC re-tags Q3 2023 (the same period_end) under fy=2024 too. Without
    grouping on period_end and taking MIN, the dedupe-by-(end, form) path
    in `edgar_provider.get_chain_facts` returns the LATEST filed_date,
    inflating the announcement date by ~365 days (verified empirically on AAPL).

Duration filter:
  - 10-Q must be standalone-Q (60-100 days end-start duration).
  - 10-K must be full FY (300-380 days end-start duration).
  - Mirrors the same artifact-fix from Bucket B fundamentals work (commit aa0182e):
    EDGAR reports YTD-cumulative AND standalone-Q under the same tag; we need
    standalone-Q.

Forms accepted: 10-Q, 10-K, 10-Q/A, 10-K/A.

Known limitation (documented in PRD §7.1):
  filed_date is the EDGAR filing date (10-Q submission), which is typically
  7-14 days AFTER the actual 8-K earnings announcement. For Phase 1 free-path,
  this is the best proxy. Phase 2 will swap in 8-K announcement dates from
  paid feeds if Phase 1 shows signal.
"""

from __future__ import annotations

from typing import List, Optional

import pandas as pd

from core.data.edgar_provider import EdgarProvider


_DEFAULT_EPS_TAG = "EarningsPerShareDiluted"
_EPS_UNIT = "USD/shares"

_ACCEPTED_FORMS = ("10-Q", "10-K", "10-Q/A", "10-K/A")
_Q_DURATION_RANGE = (60, 100)
_K_DURATION_RANGE = (300, 380)


def extract_earnings_dates(
    ticker: str,
    edgar_provider: Optional[EdgarProvider] = None,
    eps_tag: str = _DEFAULT_EPS_TAG,
) -> pd.DataFrame:
    """Extract first-filed earnings dates for a single ticker.

    Returns DataFrame with columns:
        ticker            str
        period_end        pd.Timestamp  (fiscal period end)
        period_start      pd.Timestamp
        first_filed_date  pd.Timestamp  (min filed_date for this period_end)
        form              str           (form of first-filed row)
        fy                int           (fiscal year of first-filed row)
        fp                str           ('Q1'/'Q2'/'Q3'/'FY')
        eps_value         float         (diluted EPS, standalone period)
        duration_days     int           (end - start, days)

    Sorted by period_end ascending. One row per period_end.

    Returns empty DataFrame if ticker has no EDGAR cache or no diluted EPS.
    """
    provider = edgar_provider or EdgarProvider()
    try:
        facts = provider.get_tag_facts(ticker, eps_tag, unit=_EPS_UNIT)
    except (FileNotFoundError, ValueError):
        return pd.DataFrame()

    rows: List[dict] = []
    for f in facts:
        if f.form not in _ACCEPTED_FORMS:
            continue
        if not f.start:
            continue
        start = pd.Timestamp(f.start)
        end = pd.Timestamp(f.end)
        duration_days = (end - start).days
        if f.form.startswith("10-Q"):
            if not (_Q_DURATION_RANGE[0] <= duration_days <= _Q_DURATION_RANGE[1]):
                continue
        else:  # 10-K family
            if not (_K_DURATION_RANGE[0] <= duration_days <= _K_DURATION_RANGE[1]):
                continue
        rows.append({
            "period_end": end,
            "period_start": start,
            "filed_date": pd.Timestamp(f.filed),
            "form": f.form,
            "fy": int(f.fy),
            "fp": f.fp,
            "eps_value": float(f.val),
            "duration_days": int(duration_days),
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # First-filed per period_end. Sort ascending by filed_date and take first.
    # If multiple rows share the same (period_end, filed_date) — pick smallest
    # accn-like (deterministic via fy first, then eps_value as tiebreak) so
    # the result is reproducible across runs.
    df = df.sort_values(["period_end", "filed_date", "fy", "eps_value"])
    first = df.groupby("period_end", as_index=False).first()
    first = first.rename(columns={"filed_date": "first_filed_date"})
    first["ticker"] = ticker

    cols = [
        "ticker", "period_end", "period_start", "first_filed_date",
        "form", "fy", "fp", "eps_value", "duration_days",
    ]
    return first[cols].sort_values("period_end").reset_index(drop=True)


def extract_earnings_dates_panel(
    tickers: List[str],
    edgar_provider: Optional[EdgarProvider] = None,
    eps_tag: str = _DEFAULT_EPS_TAG,
) -> pd.DataFrame:
    """Multi-ticker version. Concatenates per-ticker DataFrames.

    Returns the union of `extract_earnings_dates(t)` for each t in tickers.
    Sorted by (first_filed_date, ticker). Empty per-ticker results are
    silently dropped.
    """
    provider = edgar_provider or EdgarProvider()
    frames = []
    for t in tickers:
        df = extract_earnings_dates(t, edgar_provider=provider, eps_tag=eps_tag)
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    return out.sort_values(["first_filed_date", "ticker"]).reset_index(drop=True)
