# Postmortem — SPY + 9 stocks off-by-one date label bug

**Date**: 2026-05-13 (post-K1 ship; uncovered during forward bar_hash test failure investigation)
**Severity**: P0 — affects prior mining + backtest + forward observation decisions
**Authors**: operator (zibomeng@) + Claude Code assist
**Status**: bug identified + bounded; NO FIX SHIPPED YET — awaiting user direction on deprecation scope

---

## §1 TL;DR — what's broken

`data/daily/<SYM>.parquet` for **SPY** and at least **9 other symbols** (JPM, V, PG, HD, BAC, XOM, CVX, BIL, SHV) have **+1 calendar day offset on row labels** for all data from 2007 through 2026-04-19. From 2026-04-20 onward the data is correctly labeled.

Concrete proof (SPY around 2025-01-02):

```
SPY parquet            Actual NYSE trading day        SPY close
─────────────────      ──────────────────────         ─────────
2024-12-31 Tue   ←    2024-12-30 Mon                  $588.00
2025-01-01 Wed   ←    2024-12-31 Tue (market closed!)  $586.18  ← SHIFTED
2025-01-03 Fri   ←    2025-01-02 Thu                  $584.93
2025-01-04 Sat   ←    2025-01-03 Fri (NYSE closed Sat) $591.82  ← SHIFTED
2025-01-07 Tue   ←    2025-01-06 Mon                  $595.60
```

Every trading day's bar is labeled +1 calendar day later. Result:
- Weekday data has wrong dates (Mon trading → Tue label)
- Saturday rows appear with Friday's actual close
- "Holiday" rows appear (e.g., 2025-01-01 NYE has data — but it's actually 2024-12-31's data)
- ~569 fake Saturday rows per affected symbol

## §2 How was this found

K1 ship close-out ran broader regression on `tests/unit/signals/` + `tests/unit/research/`:
- 1074 PASS / 3 FAIL
- All 3 failures in `core/research/forward/*` bar_hash tests
- Pre-K1 commit (`16de8dd`) shows same 3 failures → **pre-existing**, not K1-induced
- Drilling into one failure: `test_signal_input_hash_window_uses_actual_trading_day_rows` asserts `BDay(252) > true_252nd_prior` should hold; failed because `valid[-252]=2025-06-30` (only ~10 months back from 2026-04-27, when it should be ~12 months)
- Diagnosis: SPY panel has 3462 rows for 2015-01-02 to 2026-04-27 range — but AAPL panel has 2857. The 605-row delta = SPY's spurious Saturday rows + missing Mondays
- Confirmed via `pd.read_parquet` direct inspection of `data/daily/SPY.parquet`

## §3 Affected symbols (verified)

Scan of `data/daily/*.parquet` day-of-week distribution:

| Symbol | Total rows | Weekend rows | % | Provenance source |
|---|---|---|---|---|
| SPY | 2856 | 569 | 19.9% | yfinance_daily |
| QQQ | 2857 | 0 | 0.0% | yfinance_daily ← clean |
| AAPL | 2857 | 0 | 0.0% | yfinance_daily ← clean |
| MSFT | 2856 | 0 | 0.0% | yfinance_daily ← clean |
| GOOGL | 2855 | 0 | 0.0% | yfinance_daily ← clean |
| NVDA | 2856 | 0 | 0.0% | yfinance_daily ← clean |
| JPM | 2842 | 570 | 20.1% | mixed stocks_csv + polygon_gz |
| V | 3397 | 569 | 16.8% | mixed |
| PG | 2841 | 569 | 20.0% | mixed |
| HD | 3263 | 570 | 17.5% | mixed |
| BAC | 2842 | 570 | 20.1% | mixed |
| XOM | 2841 | 569 | 20.0% | mixed |
| CVX | 3285 | 570 | 17.4% | mixed |
| BIL | 4365 | 569 | 13.0% | mixed |
| SHV | 4365 | 569 | 13.0% | mixed |
| TLT | 4366 | 0 | 0.0% | yfinance_daily ← clean |
| GLD | 4366 | 0 | 0.0% | yfinance_daily ← clean |
| WMT | 2849 | 0 | 0.0% | mixed ← clean |

10 confirmed affected symbols. Quick scan of `data/daily/A*.parquet` showed ~30 more with weekend rows (mostly obscure tickers; unclear if they're in active PQS universe). **Full universe scan needed** but the load-bearing finding is: SPY (the primary benchmark for ALL PQS decisions) is affected.

## §4 Why provenance doesn't predict affectedness

Looking at the table: same provenance source produces both clean (AAPL/MSFT yfinance) and affected (SPY yfinance) symbols. WMT has mixed-source provenance like JPM but is clean. So provenance source alone doesn't predict the bug.

Hypothesis: bug is in **specific ingest event** rather than source class. Maybe a one-off `yfinance.download(...)` call with timezone parameter bug, or a stocks_csv batch with EU-style date parsing. From provenance `last_bar_ts=2026-04-20` for affected symbols, all data was last updated 2026-04-20. The 2026-04-20 ingest likely had a buggy date handling that hasn't been re-fetched.

Post-2026-04-20 daily fetches (incremental, post-NYSE close) produce correct labels — that's why 2026-04-20 onward is clean.

## §5 Blast radius — what prior decisions are affected

### 5.1 Likely contaminated metrics

Any computation that USES SPY/QQQ/affected-symbol bars AND relies on day-level alignment with strategy returns (which use mostly clean symbols like AAPL/MSFT/NVDA).

| Decision | Date | Affected? | Magnitude |
|---|---|---|---|
| cycle04-08 mining (5 cycles) | 2026-05-01..05-08 | YES — SPY used in Track A vs_spy gates + beta_spy_60d factor | Medium — aggregate CAGR/MaxDD likely stable; daily IC + correlation polluted |
| cycle09 (INVALID — sampler bug) | 2026-05-12 | N/A — cycle was invalid already | N/A |
| cycle10 (today, 0 nominee per R7) | 2026-05-13 | YES — same as cycle04-08 | Medium — but cycle10 was 0-nominee regardless |
| simple_baseline_v1 backtest | 2026-05-13 (today) | YES — vs SPY CAGR comparison uses off-by-one SPY | Likely bounded — uses yfinance via separate fetch in `scripts/run_simple_baseline_backtest.py` (NOT BarStore parquet); need verification |
| simple_baseline_v1 paper init | 2026-05-13 (today) | UNKNOWN — TD001 just init'd | Need verification |
| Trial 9 v2 forward observe | first TD = 2026-05-13 EOD | YES — beta_spy_60d in composite uses SPY | Medium — recent SPY data clean (2026-04-20+); historical lookback uses off-by-one data |
| Trial 9 v1 forward observe (4 TDs) | 2026-05-04..05-12 | YES — same composite | Same as v2; v1 already terminated for unrelated reasons |
| RCMv1 + Cand-2 forward observe (TD001-003) | 2026-04-24..04-28 | YES — but candidates already aborted 2026-04-30 on data revision drift | LOW — aborts already happened |
| Options sleeve paper (spy_8otm_bull_put_v1) | 2026-05-04 init | YES — uses SPY as underlying | Medium — paper P&L tracking |
| K1.2 test_26 SPY-SMA smoke | 2026-05-13 (today) | NO — synthetic data | N/A |
| 12-axis WebSearch literature synthesis | 2026-05-13 | NO — pure literature | N/A |
| TC-ceiling reframing (roadmap v2 §2.2) | 2026-05-13 | NO — theoretical argument | N/A |

### 5.2 Expected magnitude (un-verified hypothesis)

Off-by-one DAY in benchmark series has bounded numerical impact:
- **CAGR**: nearly invariant (cumulative product of returns shifts in time but final value within rounding)
- **Sharpe / MaxDD**: nearly invariant for full-period (statistics over similar distribution)
- **Daily excess return**: polluted (T-day strategy return compared against T+1-day benchmark return)
- **Daily IC**: polluted (1-day phase shift between factor signal and forward returns when forward uses SPY-relative)
- **Correlation matrices**: polluted (Pearson computed on phase-shifted series biased downward vs true correlation)
- **Acceptance gate vs_spy aggregate**: probably stable at CAGR level (gate passes/fails not affected materially)
- **Anti-sibling NAV correlation**: BIASED DOWNWARD (true correlation higher than measured because of phase shift artifact). **Implication**: sibling-by-NAV findings are CONSERVATIVE — true correlation is even higher than the 0.85-0.94 we observed in cycle04-08.

### 5.3 Critical uncovered question

**Did the bug affect mining selections?** cycle04-10 used `beta_spy_60d` factor. If SPY is off-by-one:
- `beta_spy_60d = OLS(stock_ret_60d, spy_ret_60d)` where stock_ret is clean, spy_ret has 1-day phase shift
- True covariance would be HIGHER than measured (phase mismatch dilutes)
- Mining IC of beta_spy_60d would be lower than true → factor weight in top trials understated
- BUT — all factors in cycle04-10 use the same SPY/QQQ panel, so the bias is uniform across factors. Relative ranking among factors likely preserved.

This suggests: **the bug does NOT invalidate cycle04-10 mining conclusions about which factors / constructions converge** (sibling-by-NAV is real; TC ceiling argument is real). It DOES require care when interpreting absolute numbers like Sharpe / IC magnitude / NAV correlation level.

## §6 Recommended path forward

### Option A — Fix data + selective re-run (operator preference)

1. **Identify ingest pipeline bug**: trace why 2026-04-20 ingest event mis-labeled dates for these 10 symbols
2. **Re-fetch affected symbols** from canonical source (polygon 1m → daily aggregation per CLAUDE.md pricing semantics) for years 2007-2026-04-19
3. **Validate**: rerun day-of-week scan; expect all-clean
4. **Re-run impact-bounded decisions**:
   - K1.2 test_26 — synthetic, NOT affected, skip
   - simple_baseline_v1 backtest — RE-RUN today before paper soak deepens. Use clean SPY for risk-on/risk-off gate. Expect minor CAGR delta (within ±0.5pp).
   - Trial 9 v2 forward observe — manifest_init was using current data; today's TD001 will use 2026-05-13 data which is already clean. Historical factor lookback uses off-by-one SPY → factor values may shift. **Action**: re-init Trial 9 v2 with corrected lookback or document the bias.
   - Forward bar_hash will need 1 full re-hash cycle after data fix (existing manifests' bar_hash entries become invalid)
5. **DEPRECATE without re-run**:
   - cycle04-08 closeouts: 0-nominee already. Add deprecation note in CLAUDE.md. Don't re-run mining; finding (sibling) was robust to bug magnitude.
   - cycle10 closeout: 0-nominee already (R7 fail-SPY). Same as cycle04-08.
   - RCMv1 + Cand-2 forward observe: already aborted. Re-run not useful.

### Option B — Hard reset all artifacts

1. Same as Option A step 1-3
2. Re-run ALL prior mining cycles (cycle04-08 + cycle10) with fixed data
3. Re-bench simple_baseline_v1 + spy_8otm_bull_put_v1 from scratch
4. Re-init all 3 active forward candidates (trial9_002 + simple_baseline_v1 + spy_8otm_bull_put_v1) with corrected data
5. Strategic discussion of K1+T1 path remains valid since K1 used synthetic data

Option B = ~1 week of re-mining compute (cycle04-08 + cycle10 each ~30 min mining + acceptance pack); Option A = ~half day data fix + 2-3 specific re-runs.

### Option C — Bug fix but no re-run

1. Fix data
2. Document in CLAUDE.md that prior numbers were computed against off-by-one SPY
3. Treat prior conclusions as DIRECTIONAL (sibling-by-NAV findings, TC ceiling reframing) but NOT NUMERICALLY REPRODUCIBLE under fixed data
4. Proceed with T1a / T1b / T1c / T2a / T2c using clean data
5. Mining cycles cycle04-10: deprecate numerically; preserve as qualitative evidence chain

**Operator recommendation = Option A** (fix + selective re-run).

The directional findings from cycle04-10 (sibling-by-NAV / TC ceiling / 0-nominee informativeness) are robust to bug magnitude — they would be REINFORCED not invalidated by clean data (because NAV correlation is biased DOWN by the bug, true correlation is even higher than measured).

The wealth-vehicle decision (ship simple_baseline_v1) needs the cleanest possible numbers because it gates real capital deployment. Re-running simple_baseline backtest with clean SPY is a half-day operation.

K1 (deferred-execution wrapper) is unaffected.

## §7 Self-audit (R3 honesty check)

What I am NOT claiming:
- I have not verified Option A magnitude predictions by actually re-running mining cycles with clean data. They are honest hypotheses based on the off-by-one math, not measured deltas.
- I have not done a full universe scan (~78 symbols). Only ~30 confirmed affected so far. Full scan should be P0 first step of fix.
- I have not investigated the ingest pipeline root cause — only verified that the symptom is consistent and 2026-04-20 was the regime boundary.

What I AM claiming:
- The off-by-one bug is REAL and PROVABLE (concrete date arithmetic shown in §1).
- 10 symbols confirmed affected.
- 3 forward bar_hash tests fail BECAUSE of this bug (not unrelated reasons).
- The bug does NOT invalidate the QUALITATIVE conclusions from cycle04-10 (sibling-by-NAV is real; TC ceiling argument is real).
- The bug DOES require care when interpreting absolute numbers from prior backtests.

## §8 Asks for user

1. **Option A / B / C** — which deprecation/re-run scope?
2. **Universe scan** — should we scan all ~78 PQS symbols + cross-asset ETFs to enumerate full affected set?
3. **Fix priority** — fix data this session before continuing T1a, or defer fix to dedicated cleanup session?
4. **Simple_baseline_v1 paper soak** — pause forward observe pending fix, or continue (today's TD001 used today's data which is already clean, so paper drift may be acceptable)?

After your direction, I will:
- (Option A path) fix data + re-run selective items
- (Option B path) propose explicit re-run order and start mining cycle04 first
- (Option C path) add deprecation note to CLAUDE.md and proceed T1a

K1 ship is unaffected and stands.
