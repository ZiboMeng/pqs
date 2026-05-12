# data/fundamentals/

Fundamental data from SEC EDGAR companyfacts API + FRED macro.

Layout:
- edgar_cache/<CIK>.json  raw companyfacts dump
- macro/macro_panel.parquet  FRED-sourced daily macro panel

Pipeline: dev/scripts/fundamentals/build_edgar_cache.py
