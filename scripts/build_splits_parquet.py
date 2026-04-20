#!/usr/bin/env python3
"""
Normalize splits.csv → ref/splits.parquet.

Source: ~/Documents/projects/Data/1m/splits.csv (columns: symbol, date, from, to)
Output: pqs/data/ref/splits.parquet

Applied as forward-adjustment factor at read time:
    adj_factor(t) = Π (from_i / to_i) over splits i where date_i > t
    adj_price     = raw_price * adj_factor
    adj_volume    = raw_volume / adj_factor
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

SRC = Path(os.path.expanduser("~/Documents/projects/Data/1m/splits.csv"))
OUT = Path(os.path.expanduser("~/Documents/projects/pqs/data/ref/splits.parquet"))


def main() -> None:
    df = pd.read_csv(SRC, encoding="utf-8-sig")
    df.columns = [c.strip().lstrip("\ufeff") for c in df.columns]
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    df["from"] = df["from"].astype("int64")
    df["to"] = df["to"].astype("int64")
    df["symbol"] = df["symbol"].astype("string")
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, compression="snappy", index=False)

    today = pd.Timestamp.today().normalize()
    future = (df["date"] > today).sum()
    print(f"splits: {len(df)} rows, {df['symbol'].nunique()} tickers")
    print(f"  date range: {df['date'].min().date()} → {df['date'].max().date()}")
    print(f"  future-dated (> {today.date()}): {future}")
    print(f"  wrote {OUT}")


if __name__ == "__main__":
    main()
