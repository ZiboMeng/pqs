# Paper Artifact Schema (Phase E-2)

> **Status**: Active. Defines the file contract between
> `scripts/run_paper_candidate.py` (R8 writer) and
> `scripts/paper_drift_report.py` (R10 reader) + future paper
> consumers.
>
> **Update policy**: This document and `core/research/paper_artifacts.py`
> must stay in sync. A mismatch will silently break drift-report
> consumption. When adding a new artifact, add it here first, then in
> the writer, then in the test.

## 1. Output layout

A paper run writes ALL artifacts under a single timestamped directory:

```
data/paper_runs/<candidate_id>/<UTC-timestamp>/
    signals_daily.csv
    target_portfolio_daily.csv
    pnl_daily.csv
    fills.csv
    run_meta.json
    live_like_pnl.csv                 (R9)
    benchmark_relative_paper.csv      (R9, if SPY/QQQ present)
    turnover_log.csv                  (R9)
```

UTC-timestamp format: `%Y%m%dT%H%M%SZ` (e.g. `20260424T171600Z`).

When `--out-dir` is passed explicitly, that path overrides the default.

## 2. File contracts

### 2.1 `signals_daily.csv`

Composite signal values from the frozen spec.

| column | dtype | description |
|---|---|---|
| (index) `date` | datetime64 | one row per trading date in the paper window |
| `<symbol>` | float | composite z-score value for that symbol. NaN when research_mask excludes the symbol that date (below min_price / below min_usd_volume rolling threshold) or the feature chain produces NaN (warmup, data gap) |

Produced by: `core.research.paper_artifacts.*` is NOT used for this; the CLI dumps the composite DataFrame directly from `core.mining.research_miner.zscore_cs` + weighted sum + `apply_research_mask`. The shape is `(n_dates, n_symbols)`.

### 2.2 `target_portfolio_daily.csv`

Target portfolio weights per date, post-portfolio-construction rule.

| column | dtype | description |
|---|---|---|
| (index) `date` | datetime64 | one row per trading date |
| `<symbol>` | float | target weight in [0, 1]. MVP rule (R8): top-N by composite rank, equal-weighted (`1/top_n`); all other symbols `0.0` |

Sum across any row is either `1.0` (when enough symbols have valid composite values to select top-N) or `0.0` (not enough valid data that date).

### 2.3 `pnl_daily.csv`

Raw BacktestEngine output. Legacy name; `live_like_pnl.csv` is the
more structured version for drift consumption.

| column | dtype | description |
|---|---|---|
| (index) `date` | datetime64 | |
| `equity_curve` | float | total portfolio value (NAV) |
| `cash_curve` | float | cash balance |
| `ret` | float | daily pct change of equity_curve; `0.0` on first row |

### 2.4 `fills.csv`

Flattened simulated trade ledger.

| column | dtype | description |
|---|---|---|
| `date` | YYYY-MM-DD | fill date (T+1 of the signal date) |
| `symbol` | str | |
| `side` | str | `BUY` or `SELL` |
| `quantity` | float | shares filled |
| `price` | float | executed price (including slippage) |
| `commission` | float | commission_usd |
| `slippage` | float | slippage_usd |
| `cash_delta` | float | net cash impact (negative = outflow) |

No row index. Empty DataFrame (schema only) written when no trades.

### 2.5 `run_meta.json`

Self-describing metadata. Not loaded by drift report; primary use is
audit + debugging.

```json
{
  "candidate_id": "...",
  "status_at_run": "S1_research_candidate" | "S2_paper_candidate",
  "frozen_spec_path": "data/research_candidates/<id>.yaml",
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "top_n": 10,
  "n_dates": 26,
  "n_symbols": 79,
  "n_active_rows": 16,
  "final_equity": 105085.18,
  "n_trades": 27,
  "generated_at_utc": "ISO 8601"
}
```

### 2.6 `live_like_pnl.csv` (R9)

Structured live-like NAV series.  Read by drift report; `pnl_daily.csv`
is kept for legacy consumers.

| column | dtype | description |
|---|---|---|
| (index) `date` | datetime64 | |
| `nav` | float | total portfolio value |
| `cash` | float | cash balance |
| `ret_daily` | float | daily pct change; `0.0` on first row |
| `ret_cumulative` | float | `nav / initial_capital - 1.0` |
| `dd` | float | drawdown from running max NAV (0 or negative) |

Writer: `core.research.paper_artifacts.write_live_like_pnl`.

### 2.7 `benchmark_relative_paper.csv` (R9)

Paper performance vs buy-and-hold benchmarks. Only written if at least
one benchmark symbol is present in the panel (default: SPY and QQQ
from `benchmark_map`).

| column | dtype | description |
|---|---|---|
| (index) `date` | datetime64 | |
| `paper_cum_ret` | float | cumulative paper return (fractional) |
| `SPY_cum_ret` | float | cumulative SPY buy-and-hold return (if SPY on panel) |
| `QQQ_cum_ret` | float | cumulative QQQ buy-and-hold return (if QQQ on panel) |
| `excess_vs_SPY_bps` | float | (paper_cum_ret - SPY_cum_ret) × 10000 |
| `excess_vs_QQQ_bps` | float | (paper_cum_ret - QQQ_cum_ret) × 10000 |

Symbols absent from the panel silently skipped (drop the columns).

Writer: `core.research.paper_artifacts.write_benchmark_relative_paper`.

Consumer (R10): drift report will cite `excess_vs_SPY_bps` as the
headline "paper vs benchmark" metric for a candidate's paper window.

### 2.8 `turnover_log.csv` (R9)

Daily turnover derived from `target_portfolio_daily.csv`.

| column | dtype | description |
|---|---|---|
| (index) `date` | datetime64 | |
| `turnover` | float | `0.5 * sum(abs(w_t - w_{t-1}))`; first row uses `0.5 * sum(abs(w_0))` (entering positions) |
| `n_positions` | int | count of non-zero weights that date |
| `total_weight` | float | `sum(abs(w_i))` (gross exposure; should be ≤ 1 for long-only top-N) |

Writer: `core.research.paper_artifacts.write_turnover_log`.

Semantic: `turnover == 0` on "warmup" dates (no composite data yet,
no positions). Steady-state top-N equal-weight with full monthly
rebalance produces daily turnover ≈ 0 except on rebalance dates.

## 3. Invariants

- Every artifact is ASCII-safe CSV (or UTF-8 JSON for meta).
- All datetime indices are tz-naive US/Eastern trading-day index.
- Drift report is allowed to fail with "insufficient data" if
  `live_like_pnl.csv` has < 5 valid NAV rows.
- Writers create parent directories; readers assume directories exist.

## 4. Versioning

Schema version is implicit (Phase E-2 initial). Any breaking change
must:
1. Bump Phase E synthesis doc with a migration note
2. Add a readable `schema_version` field to `run_meta.json`
3. Update drift report to tolerate both versions for at least one
   release

## 5. Related

- Writers: `core/research/paper_artifacts.py`
- Writer CLI: `scripts/run_paper_candidate.py` (R8)
- Reader CLI: `scripts/paper_drift_report.py` (R10, upcoming)
- Tests: `tests/unit/research/test_paper_artifacts.py` (R9)
- Governance: the paper run itself is a pure data operation; the
  registry state transition S1 → S2 happens via
  `scripts/paper_enter.py` (R11), not by running this pipeline.
