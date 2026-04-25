# Round-3 Step 3a-rev — Delta Audit (two-tier N_min + BRK-B drop)

**Date**: 2026-04-25
**Status**: delta dry-run completed; no parquet writes yet.
**Predecessor**: `20260425-data_integrity_round3_step3a_audit.md`
(initial audit with single 350 threshold).

User pinning post step-3a audit:
- §9.1 BRK-B: **drop**, no yfinance fallback, no per-symbol backfill;
  flagged in audit sidecar as unsupported.
- §9.2 N_min: **two-tier**:
  - `complete`: endpoints present + `n_bars >= 350`
  - `thin_data`: endpoints present + `300 <= n_bars < 350` →
    accepted into store with `thin_data=True` flag in sidecar
  - `quarantine`: `n_bars < 300` OR missing 09:30 / 15:59 anchor
- Single canonical source = polygon 1m. **No fallback.**

---

## Delta — five groups

### 1. Overall

| bucket | OLD (single 350) | NEW (two-tier) |
|--------|--------:|--------:|
| complete (n≥350) | 141,090 (89.38%) | 141,090 (89.38%) |
| thin_data (300-349) | n/a | **6,748 (4.27%)** |
| partial (NYSE half-day) | 1,231 (0.78%) | 1,231 (0.78%) |
| quarantined | 15,535 (9.84%) | **8,787 (5.57%)** |
| **accepted into store** | n/a | **149,069 (94.43%)** |

Quarantine drop: **−43.4%** (15,535 → 8,787).

### 2. 2022-H2 paper window (4,446 records)

```
complete:   4,066    thin_data:  121    partial:   55    quarantined: 204
quarantine pct: 7.31% → 4.59%
top quarantined: CMG 77 / BKNG 68 / TT 19 / LLY 14 / DG 6 / TJX 4 / MCK 4 / MS 3
```

### 3. 2024 paper window (4,408 records)

```
complete:   3,819    thin_data:  267    partial:    0    quarantined: 322
quarantine pct: 13.36% → 7.30%
top quarantined: BKNG 75 / CMG 74 / MCK 44 / DG 28 / TT 28 / KLAC 21 / ABT 16 / PWR 10
```

### 4. ETF subset (5 in seed_pool)

| ETF  | complete | thin | partial | quarantined | q_pct |
|------|---------:|-----:|--------:|------------:|------:|
| SPY  | 2,815 |   0 | 23 |   0 |  0.00% |
| QQQ  | 2,815 |   0 | 23 |   0 |  0.00% |
| GLD  | 2,815 |   0 | 23 |   0 |  0.00% |
| TQQQ | 2,805 |   9 | 23 |   1 |  0.04% |
| **SOXL** | 1,768 | 435 | 22 | 613 | **21.60%** |

SOXL 36.93% → 21.60% (still elevated; accepted under no-fallback rule).

### 5. Watch list

| sym | complete | thin | partial | quarantined | q_pct | written? |
|-----|---------:|-----:|--------:|------------:|------:|----------|
| BKNG  |   181 | 278 | 18 | 1,569 | 76.69% | YES (mostly thin_data + quarantine) |
| CMG   |   936 | 412 | 17 | 1,474 | 51.92% | YES |
| TKO   |   205 | 249 |  6 |   191 | 29.34% | YES |
| TT    | 1,000 | 223 |  8 |   309 | 20.06% | YES |
| SOXL  | 1,768 | 435 | 22 |   613 | 21.60% | YES |
| **BRK-B** |     0 |   0 |  0 |     0 | n/a   | **NO — drop, flagged unsupported** |

---

## Stop-signal review

| Original signal (step 3a §9) | User pinning | Resolution |
|------------------------------|--------------|------------|
| 9.1 BRK-B no 1m | drop, no fallback | ✅ 0 rows written, audit-sidecar `unsupported` flag |
| 9.2 N_min too strict | two-tier (350 / 300) | ✅ quarantine 9.84% → 5.57%, recovers 6,748 thin_data rows |
| 9.3 BKNG/CMG/TKO/TT chronic | accept under no-fallback | mixed thin_data + quarantine; flagged in watch sidecar |
| 9.4 SOXL anomaly | accept under no-fallback | 36.93% → 21.60% (still elevated; flagged) |
| 9.5 2024 paper window 13% q | accept | improved to 7.30% via N_min two-tier |
| 9.6 partial count low | low severity | unchanged; informational |

**No new stop signals.** §9.3 / §9.4 / §9.5 are now `accept-and-flag`
under the no-fallback constraint. Approved to proceed to step 3b.

---

## Step 3b deliverables (per user direction)

1. Full universe daily parquet rebuild via aggregator.
2. `incomplete_days` sidecar at `data/ref/incomplete_days.parquet`.
3. **Watch-list sidecar** at `data/ref/data_quality_watch.parquet`
   covering SOXL / BKNG / CMG / TKO / TT (and any future entries),
   so step 4 paper-cell review can join on it without rummaging the
   audit log.
4. Write **manifest** at `data/ref/daily_rebuild_manifest.parquet`
   with one row per symbol: `symbol / old_row_count / new_row_count
   / thin_data_count / quarantine_count / written / drop_reason`.
5. **No fallback source.** Single canonical source = polygon 1m.
6. BRK-B: not written; sidecar entry `drop_reason='no_1m_data'`.

After step 3b → step 4 (baseline + 4 paper cells re-run) →
step 5 (headline-4 docs refresh) → step 6 (date-reference sweep).

---

## Artifacts

- `/tmp/audit_step3a_rev.pkl` — full per-day records under two-tier
- `/tmp/audit_aggregator_v3.py` — script (read-only, vectorized)
- No code changes outside `core/data/daily_aggregator.py` (two-tier
  threshold + `thin_data` sidecar column) and three new tests:
  `test_thin_data_accept_tier_300_to_350`,
  `test_quarantine_below_300_threshold`,
  `test_full_session_above_350_is_NOT_thin_data`.
