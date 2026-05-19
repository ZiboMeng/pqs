<!-- PQS module CONTEXT.md — 由 CLAUDE.md 2026-05-19 reorg 拆出。
CLAUDE.md = context 入口,仅留项目级(不变量/纪律/架构/概括)。
本文件 = 本模块的历史/契约细节(content-preserving 搬迁,无删改)。
回指: ../../CLAUDE.md ; 索引见 CLAUDE.md 末「Module CONTEXT.md 索引」。 -->

# core/data/CONTEXT.md — module history / contract detail


## [1m Bar Pipeline / Trades Backfill / Data Provenance Sidecar]

### 1m Bar Pipeline

Multi-source 1m bar ingest, stored RAW (unadjusted) under
`data/intraday/1m/<SYMBOL>.parquet`, aggregated up to 5/15/30/60m +
daily. Splits applied at READ time via `BarStore.load(adjusted=True)`
using `data/ref/splits.parquet`. Sources: Polygon flat files
(2015-2023), per-ticker CSV (2024-2025/11 stocks-only), C-drive CSV
(2025-12+ stocks-only). ETF gap auto-filled from yfinance fallback.

Key API: `from core.data.bar_store import BarStore`.

Full pipeline details (source layouts, schema, validated reliability,
build scripts) archived in
`docs/20260424-claude_md_phase_e_history.md` §1m Bar Pipeline.

### Trades Backfill Pipeline

Separate ingest path for ETF 2024+ bars (upstream CSV is stocks-only).
Reads encrypted tick-level zips (`trades_v1_YYYY-MM-DD.csv.gz`),
aggregates to 1m bars with extras (vwap, block_n, exchange shares).
Strategy B merge: only writes tickers not already in the `.staging/`
dir, preserving existing stocks_csv bars. Filter rules pinned via
`trades_v2_late_report_dedup_2026-04-19` rule-version.

Hard rule: new ingest scripts MUST write synchronously to
`data/ref/bar_provenance.parquet`.

Full ingest scripts / resilience design / filter rule list archived
in `docs/20260424-claude_md_phase_e_history.md` §Trades Backfill.

### Data Provenance Sidecar

Every (symbol, freq) bar range carries source metadata in
`data/ref/bar_provenance.parquet`. Source types: `polygon_gz`,
`stocks_csv`, `stocks_csv_c_drive`, `trades_backfill`, `yfinance_daily`,
`yfinance_fallback`. Used by: cross-source merge sanity check, factor
guard (volume-sensitive factors masked for `trades_backfill` tickers),
report per-epoch attribution.

Read via `BarStore.load(...).attrs['provenance']` or
`store.get_provenance(symbol, freq)`. Full schema + factor-guard
config archived in `docs/20260424-claude_md_phase_e_history.md`
§Data Provenance Sidecar.
