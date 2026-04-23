# Universe-Expanded Mining Phase — R0 Baseline Snapshot

**Generated**: 2026-04-21 (post-R28 + post-review fixes)
**Required by**: `docs/20260421-prd_universe_expanded_mining.md` §2.3
**Purpose**: freeze pre-loop state so R58 final report can attribute
progress precisely ("进步从何而来"). Without this snapshot, any
improvement over 30 rounds is not attributable to loop activity
vs. other changes.

---

## 1. Test Suite Status

```
pytest -q
=========== 1108 passed, 1 xfailed, 3 warnings in ~104s ============
```

**Expected xfail**: `tests/integration/test_backtest_paper_consistency.py::TestQQQOutperformance::test_full_period_cagr_beats_qqq`

Reason: R28 universe expansion (32→53 symbols) dropped MFS default-
weights CAGR from 19% to 16.3%, below QQQ 17.6%. Marked
`@pytest.mark.xfail(strict=False)` pending this loop's recalibration.

**Stop condition** (§7.1): any new non-xfail failure in suite → stop.
Any newly-passing xfail (strict=False allows it) → log as outcome
signal (auto-pass = recalibration succeeded).

---

## 2. Config Fingerprints

```
config/universe.yaml               : 2fcaae999895d529bc5b544191505a020e94f7fe
core/factors/factor_registry.py    : 2973a00079238e7ccc44866ff82371ac9fcbe6ad
core/signals/strategies/multi_factor.py : b648f9a464f460b160f5e2bffb03f23fa11efff3
```

These are `git hash-object` SHA-1 of the unmodified file contents.
Any modification to these three files during the loop must be
explicitly noted in the round log.

---

## 3. Universe Composition (post-R28, 53 symbols)

### 3.1 `config/universe.yaml::seed_pool` (33 common-stock entries)

**Core Mag7 + benchmarks + leveraged** (12, original pre-R28):
SPY, QQQ, GLD, AAPL, MSFT, GOOGL, AMZN, META, NVDA, TSLA, TQQQ, SOXL

**R28 v2 additions** (21 new common stocks):
- Alpha Core: PWR
- Diversifier: WMT, GILD, JNJ, K, VZ, OXY, GIS, WEC, EA, ED, DG, CLX
- Tactical: GS, MS, C, LRCX, KLAC, CAT, MU, AVGO

### 3.2 Other pools (ETFs, factor ETFs, macro)
(unchanged)
- `sector_etfs`: 11 SPDR sector ETFs
- `factor_etfs`: 5 factor ETFs
- `cross_asset`: 4 treasury/commodity
- `macro_reference`: VIX / TNX / DXY (non-tradeable)

### 3.3 Total tradeable universe
- 33 common stocks + 11 sector ETFs + 5 factor ETFs + 4 cross-asset
- = **53 unique tradeable symbols** (minus macro_reference + blacklist)

---

## 4. Archive State for New Lineage

```sql
SELECT COUNT(*) FROM trials
WHERE lineage_tag LIKE 'post-2026-04-21-universe-mining%';
```

Result: **0 trials** (as expected — R29 will be the first entry).

**Stop condition** (§7.3): if 200 trials accumulate under this lineage
prefix without a tier ≠ D promote, halt and ask user.

---

## 5. Bucket Population (R28 v2 expansion — 134 symbol pool)

Per `data/ml/universe_buckets_expansion_v2.csv` (R27 pipeline output):

| Bucket | Count | Symbols (subset) |
|---|---:|---|
| PROVISIONAL_ALPHA_CORE | **1** | PWR |
| PROVISIONAL_DIVERSIFIER | 12 | WMT, GILD, WEC, JNJ, EA, K, ED, VZ, DG, CLX, OXY, GIS |
| TACTICAL_HIGH_BETA_ALPHA | 8 | GS, MS, C, LRCX, KLAC, CAT, MU, AVGO |
| UNSCORED | 196 | (others) |

Note: "Provisional" prefix indicates bucket assignment uses intrinsic
metrics only; portfolio-relative metrics (corr_to_portfolio,
marginal_dd_contribution, marginal_sharpe_contribution) are deferred
pending a portfolio-aware second pass.

---

## 6. Outstanding Blockers at R0

Per PRD §1.3:

- **Blocker A** (in-loop): MFS default_weights → CAGR 16.3% < QQQ 17.6%
  on expanded universe (xfail until recalibration)
- **Blocker B** (in-loop): OOS IR barrier — 0/83 pre-R28 trials passed
  0.20 threshold; untested on expanded universe
- **Blocker C** (decision): Alpha Core density (currently 1 symbol);
  this loop produces evidence to inform v3 small-cap branch decision

---

## 7. LLM Phase Deliverables (available to this loop)

14 tools built during LLM phase R1-R27, fully usable:

- `scripts/run_mining.py` (with `--extra-symbols` per R28)
- `scripts/run_factor_interaction_mine.py`
- `scripts/run_llm_cross_signal_mining.py`
- `scripts/run_model_comparison.py`
- `scripts/llm_factor_propose.py`
- `scripts/llm_candidate_deep_check.py`
- `scripts/llm_candidate_factor_backtest.py`
- `scripts/llm_candidate_orthogonalization.py`
- `scripts/llm_composite_backtest.py`
- `scripts/universe_alpha_diagnostic.py` (R_post_review fixes)
- `scripts/universe_admission_screen.py`
- `scripts/universe_risk_labels.py` (R_post_review: field-name
  aligned to v2.2 spec; added 504d metrics; uses panel_loader)
- `scripts/universe_bucket_assign.py`
- `scripts/send_round_summary.py`

Plus `core/data/panel_loader.py` (R_post_review: shared load guards).

---

## 8. Post-Review Fixes Applied (before loop launch)

User review of PRD v1.1 identified 5 runtime / implementation issues.
All P0 fixes applied:

1. **Empty-panel guards**: new `core/data/panel_loader.py` with
   `load_close_panel_or_exit` / `load_benchmark_close_or_exit` /
   `load_close_panel_or_skip`. Applied to
   `scripts/universe_alpha_diagnostic.py`,
   `scripts/universe_risk_labels.py`, and the
   `TestQQQOutperformance` fixture.

2. **Field naming alignment** (Layer 2 vs v2.2 spec):
   - `alpha_positive_rate` → `alpha_positive_rate_rolling`
   - `tail_correlation_spy` → `tail_correlation_to_spy`
   - `alpha_t_stat_252` → `alpha_t_stat_252d` (+ new
     `alpha_t_stat_504d`)
   - new `beta_qqq_504d` metric

3. **start_universe_mining_loop.sh**: hardcoded
   `/home/zibo/miniconda3/...` replaced with `python` (relies on
   active venv).

4. **Bucket assigner** updated to read new field names with
   backward-compat fallback to legacy names.

5. **This baseline file** (docs/20260421-universe_mining_r0_baseline.md).

---

## 9. R58 Attribution Template

When writing the final report, compare R58 state against R0
(this file) across these dimensions:

| Dimension | R0 | R58 | Delta Attribution |
|---|---|---|---|
| pytest non-xfail count | 1108 | ? | (regression / new tests?) |
| xfail list | {qqq_full_period} | ? | (resolved? new?) |
| universe.yaml hash | 2fcaae99... | ? | (changed? auth'd?) |
| factor_registry hash | 2973a000... | ? | (changed? auth'd?) |
| Alpha Core count | 1 | ? | (attributable to bucket rule tuning? universe re-audit?) |
| Best OOS IR (new lineage) | n/a | ? | (breakthrough? null?) |
| Trial count (new lineage) | 0 | ? | (full 200? stopped early?) |
| Hard goals (§2.1) | Open | ? | — |
| Outcome goals (§2.2) | Open | ? | — |

---

*This document freezes R0 state. Do not modify after R29 starts.*
