"""
Reference-data integrity test for `data/ref/splits.parquet`.

Ships with round-3 step 2 (data-integrity workstream): pins
known-correct stock splits for the universe and rejects known-bad
entries that this round removed. Future ingest / re-build operations
must preserve these — the BarStore read-time cascade depends on
splits.parquet being accurate, and the round-3 root cause analysis
identified two reference bugs (round-2 §1.1 + §4):

  TJX:    remove bogus 2018-11-07 entry (no public split)
  TJX:    add 2017-04-05 (1:2 split, public record)
  GOOGL:  add 2014-04-03 (1:2 split, public record)

This test does NOT lock the full splits.parquet contents (4960+
rows). It only pins the universe-relevant entries that:
  (a) are well-documented by NASDAQ / company filings, and
  (b) are load-bearing for any post-2015 BarStore data.

If a future ingest re-pull of splits adds new entries, this test
keeps passing as long as the locked entries remain.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture(scope="module")
def splits_df() -> pd.DataFrame:
    p = Path("data/ref/splits.parquet")
    if not p.exists():
        pytest.skip("data/ref/splits.parquet not present")
    df = pd.read_parquet(p)
    # Schema sanity
    assert set(df.columns) >= {"symbol", "date", "from", "to"}, df.columns.tolist()
    df["date"] = pd.to_datetime(df["date"])
    return df


def _has_split(
    df: pd.DataFrame, symbol: str, date: str, frm: int, to: int,
) -> bool:
    """Return True iff (symbol, date, from, to) row exists exactly."""
    target = pd.Timestamp(date)
    rows = df[
        (df["symbol"] == symbol)
        & (df["date"] == target)
        & (df["from"].astype(int) == frm)
        & (df["to"].astype(int) == to)
    ]
    return not rows.empty


def _has_any_entry(df: pd.DataFrame, symbol: str, date: str) -> bool:
    """Return True iff any row at (symbol, date) regardless of from/to."""
    rows = df[(df["symbol"] == symbol) & (df["date"] == pd.Timestamp(date))]
    return not rows.empty


# ──────────────── Round-3 step 2 fixes (locked) ──────────────────────────


def test_tjx_2017_04_05_present(splits_df):
    """TJX 2:1 split on 2017-04-05 (public record). Added in round-3."""
    assert _has_split(splits_df, "TJX", "2017-04-05", 1, 2), (
        "TJX 2017-04-05 (1:2) split MUST be in splits.parquet "
        "(round-3 step 2 reference fix)"
    )


def test_tjx_2018_11_07_absent(splits_df):
    """TJX 2018-11-07 entry was bogus (no public split that date).
    Removed in round-3 step 2 — must NOT regress."""
    assert not _has_any_entry(splits_df, "TJX", "2018-11-07"), (
        "TJX 2018-11-07 entry MUST NOT be in splits.parquet — "
        "no public TJX split on that date (round-3 step 2 reference fix)"
    )


def test_googl_2014_04_03_present(splits_df):
    """GOOGL 2:1 split on 2014-04-03 (public record).
    Does not affect post-2018 BS coverage but locked for cleanliness."""
    assert _has_split(splits_df, "GOOGL", "2014-04-03", 1, 2), (
        "GOOGL 2014-04-03 (1:2) split MUST be in splits.parquet "
        "(round-3 step 2 reference fix)"
    )


# ──────────────── Pre-existing universe splits (regression guard) ─────────


# Lock known-correct splits for universe symbols. Each entry comes
# from NASDAQ / company filings and was verified during round-2 §1.1.
# If a future splits.parquet rebuild loses one of these, this test
# fires loudly.
_LOCKED_UNIVERSE_SPLITS = [
    # AAPL
    ("AAPL",  "2014-06-09", 1, 7),
    ("AAPL",  "2020-08-31", 1, 4),
    # TSLA
    ("TSLA",  "2020-08-31", 1, 5),
    ("TSLA",  "2022-08-25", 1, 3),
    # NVDA
    ("NVDA",  "2021-07-20", 1, 4),
    ("NVDA",  "2024-06-10", 1, 10),
    # GOOGL  (2022-07-18 is the splits.parquet date for the
    #         GOOGL 20:1 — calendar convention may differ from
    #         the 2022-07-15 public ex-date by a few days, lock
    #         the existing splits.parquet date.)
    ("GOOGL", "2022-07-18", 1, 20),
    # TJX  (2012 split kept; 2017 added by round-3)
    ("TJX",   "2012-02-03", 1, 2),
    # LRCX
    ("LRCX",  "2024-10-03", 1, 10),
]


@pytest.mark.parametrize("symbol,date,frm,to", _LOCKED_UNIVERSE_SPLITS)
def test_known_universe_split_present(splits_df, symbol, date, frm, to):
    assert _has_split(splits_df, symbol, date, frm, to), (
        f"{symbol} {date} ({frm}:{to}) split MUST be in splits.parquet"
    )


# ──────────────── Schema / sanity ────────────────────────────────────────


_UNIVERSE = {
    "AAPL","MSFT","NVDA","TSLA","GOOGL","AMZN","META",
    "SOXL","TQQQ","SPY","QQQ","TJX","LRCX","DG","ED",
    "GILD","GIS","MTUM","QUAL","XLRE","SLV","VICI","TSN","MU",
}


def test_no_zero_or_negative_split_ratios_in_universe(splits_df):
    """Every UNIVERSE split row must have positive integer from/to.
    NOTE: pre-existing reference data has ~7 non-universe symbols
    (BQ / HUBC / IRS / etc.) with `to=0` placeholders for delisting /
    reverse-split events. Those are out of scope for round-3 step 2;
    universe symbols are the contract this test pins."""
    universe_df = splits_df[splits_df["symbol"].isin(_UNIVERSE)]
    bad = universe_df[
        (universe_df["from"].astype(int) <= 0)
        | (universe_df["to"].astype(int) <= 0)
    ]
    assert bad.empty, (
        f"non-positive split ratios in UNIVERSE: "
        f"{bad.to_dict('records')[:5]}"
    )


def test_no_duplicate_symbol_date_entries_in_universe(splits_df):
    """A given UNIVERSE (symbol, date) should have exactly one row.
    NOTE: pre-existing reference data has ~15 non-universe duplicates
    (TSM, BTX, CZFS, etc.). Out of scope for round-3 step 2; universe
    symbols are the contract this test pins."""
    universe_df = splits_df[splits_df["symbol"].isin(_UNIVERSE)]
    grouped = universe_df.groupby(["symbol", "date"]).size()
    duplicates = grouped[grouped > 1]
    assert duplicates.empty, (
        f"duplicate UNIVERSE (symbol, date) entries: {duplicates.to_dict()}"
    )


def test_no_universe_split_after_today_for_past_window(splits_df):
    """A split with a far-future date for a universe symbol would
    indicate a data-poisoning regression — splits should be in the
    past or near future (next ~30 days)."""
    universe = {"AAPL","MSFT","NVDA","TSLA","GOOGL","AMZN","META",
                "SOXL","TQQQ","SPY","QQQ","TJX","LRCX","DG","ED",
                "GILD","GIS","MTUM","QUAL","XLRE","SLV","VICI","TSN","MU"}
    today = pd.Timestamp.today().normalize()
    cutoff = today + pd.Timedelta(days=60)
    far_future = splits_df[
        (splits_df["symbol"].isin(universe))
        & (splits_df["date"] > cutoff)
    ]
    assert far_future.empty, (
        f"far-future universe splits (likely poisoned): "
        f"{far_future.to_dict('records')}"
    )
