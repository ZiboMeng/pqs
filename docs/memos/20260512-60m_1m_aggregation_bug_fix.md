# 60m / 1m Aggregation Consistency Bug Fix

**Date**: 2026-05-12
**Status**: Fixed locally; documentation + Phase 3 prep note
**Trigger**: Phase 2 R4 full regression suite found 1 failing test
**Test**: `tests/integration/test_multi_tf_time_consistency.py::TestAggregationConsistency::test_60m_matches_1m_aggregation`

---

## §1 大白话总结

**Bug**: 数据目录里 60m K 线和 1m K 线的语义不一致。
- 1m bars 是 **right-labeled**（"bar 12:30" 表示 12:29-12:30 这分钟）
- 60m bars 当前是 **left-labeled**（"bar 12:30" 表示 12:30-13:30 这小时）

测试 `test_60m_matches_1m_aggregation` 假设两者都 right-labeled，所以聚合 1m 应该完全等于 60m。但 60m 不是从 1m 聚合来的 — 它是从 yfinance/CSV 直接下载的 left-labeled 数据。

**例子**：2024-06-06 12:30 60m bar 的 open 是 533.74。但 1m bars 在 (11:30, 12:30] 第一根（11:31）的 open 是 534.33。差 0.59 美元。原因：60m "12:30" 表示 12:30-13:30，open 来自 1m bar AT 12:30（也是 533.74）；不是 11:30-12:30 的 first 1m open。

**根本原因**: `scripts/aggregate_bars.py` 在 2026-04-20 之后改成 right-labeled，但 disk 上的 60m 文件没有重新生成 — 仍然是历史 left-labeled CSV 直接落盘的。

---

## §2 Provenance evidence

SPY `data/ref/bar_provenance.parquet`:
```
SPY 60m source_type='stocks_csv'        (2024-01-01 → 2025-11-30)
SPY 60m source_type='stocks_csv_c_drive' (2025-12-01 → 2026-04-16)
SPY 1m  source_type='polygon_gz'         (2015-01-02 → 2023-12-31)
SPY 1m  source_type='stocks_csv'         (2024-01-01 → 2025-11-30)
SPY 1m  source_type='trades_backfill'    (assorted backfill ranges)
```

60m 来自 `stocks_csv` — 直接 CSV，**没有**经过 `aggregate_bars.py` 重新聚合。

---

## §3 Fix steps (local)

```bash
# 1. Regenerate 60m (and 5m/15m/30m/daily) from 1m for SPY:
python scripts/aggregate_bars.py --symbols SPY

# 2. Verify the failing test passes:
pytest tests/integration/test_multi_tf_time_consistency.py::TestAggregationConsistency::test_60m_matches_1m_aggregation
```

Result on operator machine 2026-05-12: PASS.

**Note**: `data/intraday/` is gitignored, so this fix doesn't propagate via git
commit. Future operators hitting the same failing test should run the same
regeneration command.

---

## §4 Broader scope — Phase 3 alt-A prerequisite

The same bug almost certainly exists for ALL 53-stock alt-A universe (not just SPY).
The 60m bars for AAPL/MSFT/NVDA/GOOGL/AMZN etc. likely also come from `stocks_csv`
and are left-labeled.

**Implication for alt-A Phase 3 Track A walking**:
- Before running 53-股 × 8-year alt-A backtest, the entire universe's 60m bars
  must be re-aggregated from 1m via:
  ```bash
  python scripts/aggregate_bars.py --symbols AAPL MSFT NVDA GOOGL AMZN ... (53 stocks)
  ```
- Else `core.factors.alt_a_intraday_inputs.compute_alt_a_intraday_inputs()` will
  consume left-labeled 60m bars and produce shifted-by-60-minutes intraday inputs.

**Side effect of regeneration**: `aggregate_bars.py` also rewrites `data/daily/<SYM>.parquet`
for each symbol. This may affect cycle04-08 backtests which depend on stable
daily prices. Before doing the full 53-stock regeneration:

1. Diff the new daily bars against existing ones (e.g. `tools/compare_daily_bars.py`)
2. If material diffs found, decide whether to:
   - (a) Use a separate daily output path for the regenerated bars
   - (b) Snapshot the old daily bars before regenerating

The 60m bug fix for Phase 3 is therefore **not just running aggregate_bars** —
it requires careful blast-radius control.

---

## §5 Why this didn't break Phase 2 D4 smoke

The Phase 2 D4 real-data smoke (5-stock × 2024) used left-labeled 60m bars,
which means:
- `intraday_volume_60m_zscore[T, AAPL]` = z-score of "T's 09:00-10:00 ET volume"
  (where 09:00 = first regular session bar AFTER 09:00 hour)
- But because the bars are left-labeled, "T's 09:00 bar" actually covers 09:00-10:00
  (= the regular opening hour). So the bar selected is actually the RIGHT bar.

The data inconsistency is a NAMING / LABELING issue rather than a CONTENT issue
when the test only checks the open-of-window content. But it DOES bias which bar
is selected by `_select_first_regular_bar(bars, target_date)` for early-session
return computation:

```python
regular = same_day[same_day.index.hour >= NYSE_FIRST_REGULAR_BAR_HOUR]  # ≥ 9
return regular.iloc[0]
```

With left-labeled 60m bars: `same_day[hour >= 9]` finds bar at "09:00" which covers
09:00-10:00 ET. With right-labeled (post-fix): `same_day[hour >= 9]` finds bar at
"10:00" (label) which covers 09:00-10:00 ET — same window content, different label.

**Phase 2 alt-A smoke produced valid-but-uninterpretable numbers**: the bar selection
was correct by accident (same coverage), but the volume z-score and return values
were computed from the left-labeled bars' OHLCV, which is what we wanted.

**Phase 3 implication**: validate the bar selection logic against the regenerated
right-labeled 60m bars BEFORE drawing Track A conclusions. Likely no behavioral
change but worth a sanity check.

---

## §6 Related ralph-loop / cycle work

- M11a M11b paper-BT parity work: cycle04-08 used **daily** bars only, not affected.
- cycle #09 INVALID per separate sampler postmortem: independent issue.
- alt-A Phase 1-2: developed against the buggy 60m data; functionally OK because
  bar SELECTION coincidentally picks the right window even with wrong label
  (see §5).

---

## §7 TODO

- [ ] Phase 3 prep: aggregate 53-stock universe before Track A walking
- [ ] Decide blast-radius mitigation (separate daily path vs snapshot)
- [ ] Add `scripts/aggregate_bars.py --symbols ...` to operator runbook
- [ ] Consider adding a CI / pre-commit check that detects 60m vs 1m label drift

---

*End of memo. Fix applied 2026-05-12; documentation added for future operators.*
