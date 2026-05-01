# Heterogeneous Split-Adjustment Audit — Scope (Task #49 Stage-1)

**Date**: 2026-04-30 19:15 PT
**Trigger**: cycle #02 closeout (`docs/memos/20260430-track_c_cycle_2026-04-30-02_close.md` §6) flagged `data/daily/<sym>.parquet` heterogeneous split-adjustment as a blocker for Step 1 harness realized-NAV evaluation. Auditor was instructed to scope (not fix) the issue.
**Tool**: `dev/scripts/audit/scan_heterogeneous_split_adjustment.py`
**Output**: `data/audit/heterogeneous_split_audit_2026-04-30.json` (12.3 MB; per-symbol details for 25,344 parquet files)

---

## 0. Scope finding

**13 of 78 symbols in the production universe are likely heterogeneously split-adjusted** (16.7% of universe). Detection heuristic: `n_anomalous_ratio_outside_(0.2x, 5.0x) > 5` AND `n_rapid_alternation_pairs > 2`. Real splits show ONE anomalous day at the split date; heterogeneous mixing shows MANY rapid alternations.

| Symbol | Anomalous days | Rapid-alternation pairs | Date range | Notes |
|---|---|---|---|---|
| AMZN | 764 | 509 | 2007-2026 | 4 splits historical |
| AVGO | 946 | 626 | 2009-2026 | 1 split (2024) |
| BKNG | 260 | 162 | 2007-2026 | 0 splits |
| CMG | 570 | 388 | 2007-2026 | 1 split (2024) |
| GOOGL | 798 | 554 | 2007-2026 | 1 split (2014) + 1 (2022) |
| ISRG | 94 | 49 | 2007-2026 | 1 split (2017) |
| LRCX | 1118 | 793 | 2007-2026 | 1 split (2024) |
| META | 34 | 27 | 2012-2026 | 0 splits |
| NEE | 239 | 154 | 2007-2026 | 0 splits |
| NVDA | 926 | 605 | 2007-2026 | 4 splits historical |
| SOXL | 448 | 285 | 2010-2026 | 4 splits historical |
| TQQQ | 618 | 402 | 2010-2026 | 5 splits historical |
| TSLA | 618 | 417 | 2010-2026 | 2 splits (2020, 2022) |

Anomalous day count >> historical split count → confirms heterogeneous mixing, not just normal split history.

---

## 1. Hypothesis on root cause (NOT verified — first stage)

`data/daily/<sym>.parquet` is the canonical daily source post round-3 step3b (CLAUDE.md §"Pricing and Valuation Semantics"), built from `core/data/daily_aggregator.py` aggregating 1m bars. The 1m bars come from multiple sources per `data/ref/bar_provenance.parquet`:
- `polygon_gz` (2015-2023)
- `stocks_csv` (2024-2025/11)
- `stocks_csv_c_drive` (2025-12+)
- `trades_backfill` (ETF 2024+)
- `yfinance_daily` / `yfinance_fallback` (gap fill)

**Likely failure mode**: different sources use different reference dates for split adjustment (or some pre-adjusted, some raw). The polygon-gz feed is split-adjusted to its query date; if it was queried in 2023 (pre-LRCX 2024 split), pre-2024 LRCX bars are at the pre-split scale. trades_backfill from 2024+ is at the post-split scale. The aggregator merges them without re-applying a unifying split cascade. `splits.parquet` is then expected to reconcile via `BarStore.load(adjusted=True)` cascade — but it can only forward-cascade, not unmix.

**Why now (not Step 0)**: Step 0 noticed LRCX/NVDA/TQQQ/SOXL anomalies (4 symbols). Today's full audit found 13 in-universe + 22 outside-universe (warrants / test tickers). The bug is more pervasive than Step 0 indicated.

---

## 2. Impact assessment

| Use case | Impact | Mitigation in place? |
|---|---|---|
| Mining IC objective (cross-sectional rank) | Mild bias near anomaly days; rank IC partially absorbs scale jumps | Yes — IC objective is robust |
| Mining factor generation | Mild bias for momentum / volatility / breakout factors at anomaly days | Yes — research_mask drops some |
| **Step 1 harness realized NAV** | **Severe — 10^100 NAV explosion** | **NO — broken on production data** |
| run_paper_candidate cell artifacts | Bounded by 1-year cell window; less scale-mixing within a year | Acceptable for current 4 cells |
| Forward observation | Unaffected (uses yfinance frontier, separate feed) | Yes |
| Track A acceptance NAV gates | Severe — uses Step 1 harness path | Blocked until fix |

The cycle #01 + #02 closeouts were both able to complete WITHOUT harness NAV (IC + sibling discipline). But any cycle producing a Tier-1 nominee would be blocked at Track A acceptance.

---

## 3. Fix options (NOT executed; user decision tomorrow)

### Option A — Re-aggregate affected 13 symbols from canonical 1m → daily

1. For each of the 13 affected symbols, re-run `core/data/daily_aggregator.py` from clean 1m bars
2. Verify post-aggregation parquet has no rapid-alternation anomalies (re-run scan)
3. Update `bar_provenance.parquet` accordingly
4. Cost: ~2-4 hours of compute + ~1 hour code review (assumes 1m bars are clean — needs verification)
5. Risk: 1m bars may have the same heterogeneous mixing → no fix possible without external data re-source

### Option B — Quarantine list

1. Add an `excluded_from_paper_engine_due_to_heterogeneous_split_adjustment` field to research yaml
2. Harness drops these 13 symbols at panel construction
3. Cost: 30 min code change
4. Risk: changes alpha by removing 13 of the largest US stocks (incl. NVDA, TSLA, GOOGL, AMZN, META). Backtests no longer represent the actual investable universe. Sealed-window evaluation would need same exclusion.

### Option C — Reload from external source

1. Re-download daily bars for the 13 symbols from yfinance / Alpaca / direct broker
2. Replace `data/daily/<sym>.parquet` for those symbols only
3. Update `bar_provenance.parquet` accordingly
4. Cost: 1 hour download + 1-2 hour QA
5. Risk: external data may not match our canonical adjustment semantics

### Option D — Status quo + IC-only ceiling for cycles

1. Document this as a known issue; future cycles use IC-only closeouts (matching cycle #01 + #02 pattern)
2. No fix; harness deferred
3. Cost: 0
4. Risk: Track A acceptance unreachable until fix; project genuinely stuck if a Tier-1 candidate ever appears

**Recommendation** (operator, pending user input tomorrow): **Option A first** (re-aggregate from 1m), with **Option C** as fallback if 1m bars also mixed. Option B is a pragmatic interim if Option A/C take longer than 1 day. Option D leaves the project stuck.

---

## 4. Stage-2 (NOT done tonight)

- Verify 1m bars are clean for one affected symbol (e.g. LRCX): scan `data/intraday/1m/LRCX.parquet` for the same anomaly pattern. If clean, Option A is viable.
- Inspect `bar_provenance.parquet` for affected symbols to identify source-mixing pattern.
- Pilot Option A on one symbol; verify scan is clean post-fix.

These are tomorrow-morning items, gated on user direction.

---

## 5. Closeout

The cycle #02 closeout's "open follow-up: data/daily/<sym>.parquet heterogeneous split-adjustment" item is now scoped at the 13-symbol level. Investigation tool committed at `dev/scripts/audit/scan_heterogeneous_split_adjustment.py`. Audit JSON at `data/audit/heterogeneous_split_audit_2026-04-30.json` (gitignored due to size; reproducible from the script).

Decision authority: operator scoped tonight per memory `feedback_decision_authority_operator_audit_split.md`. Fix-option selection requires user input (directional decision).

— operator, 2026-04-30 19:15 PT
