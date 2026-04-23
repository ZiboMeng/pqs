# PRD — Feature Engineering v1 (Pre-Mining Baseline)

**Date**: 2026-04-23
**Status**: DRAFT — awaits user approval before implementation
**Precedes**: next mining loop (post-R38, post-R39 bug-fix closeout)
**Driver**: user spec 2026-04-23 — "美股日频量化系统第一版最小可用特征表"
**Lineage for downstream mining**: `post-2026-04-23-feat-v1-<round>`

---

## 1. Goal

Ship a **12-feature + 4-label baseline set** aligned with US daily-frequency
quant conventions, so the next mining loop operates on a clean, well-named,
leak-free feature surface. The current `RESEARCH_FACTORS` registry (35+
names) was built organically across Phase B/C/D; it has coverage gaps and
sign-flipped/rolling-only variants that obscure the basics.

This PRD does **not** try to outperform the existing composite. It
establishes a clean, reproducible, easy-to-explain foundation that future
mining + LLM candidate funnel can build on.

---

## 2. Invariants (inherited, do not break)

- Long-only, no-margin, no-short
- Signal timestamp ≤ data availability timestamp (temporal leakage rules
  per CLAUDE.md §3.1 of original PRD)
- Adjusted prices (split + dividend) for all feature computation. yfinance
  `auto_adjust=True` already provides this.
- Chinese reporting, English code naming
- Every new feature goes to `RESEARCH_FACTORS` first, **not** directly
  to `PRODUCTION_FACTORS` — promotion requires IC/OOS/regime funnel per
  `docs/20260421-promotion_flow.md`.
- `factor_registry.py` drift detector (`test_factor_registry`) enforces
  the list stays in sync with `factor_generator` output.

---

## 3. Feature Coverage Audit

### 3.1 User's 12-feature target

| # | User feature | Formula | Current state | Gap |
|---:|---|---|---|---|
| 1 | `ret_1d` | `close/close[-1] - 1` | MISSING as registered factor | ADD |
| 2 | `ret_2d` | `close/close[-2] - 1` | MISSING | ADD |
| 3 | `ret_5d` | `close/close[-5] - 1` | PARTIAL — `reversal_5d` = **-ret_5d** (sign-flipped for mean-rev) | ADD **unsigned** `ret_5d` |
| 4 | `overnight_ret` | `open_t/close_{t-1} - 1` | PARTIAL — computed inside `_overnight_factors` but only exposed as 5d/21d rolling means | ADD raw 1-bar `overnight_ret_1d` |
| 5 | `intraday_ret` | `close_t/open_t - 1` | PARTIAL — computed but only `overnight_vs_intraday` composite exposed | ADD raw `intraday_ret_1d` |
| 6 | `hl_range` | `(high_t - low_t) / close_{t-1}` | MISSING — no ATR-lite feature | ADD |
| 7 | `vol_20d` | `std(ret_1d, 20)` | PRESENT — `vol_21d` (21d ≈ 20d) | KEEP existing; document mapping |
| 8 | `volume_ratio_20d` | `volume / mean(volume, 20)` | PRESENT — `volume_surge_20d` | KEEP; document mapping |
| 9 | `dollar_vol_20d` | `mean(close*volume, 20)` | MISSING as factor; PRESENT in admission screen | ADD as factor (daily per-symbol series) |
| 10 | `dist_ma20` | `close/mean(close, 20) - 1` | PARTIAL — `mean_rev_sma20` = **-dist_ma20** (sign-flipped) | ADD **unsigned** `dist_ma20` |
| 11 | `dist_52w_high` | `close/max(close, 252) - 1` | MISSING — have `max_dd_126d` (126d not 252d), `drawdown_current` (cumulative max, not rolling 252d) | ADD |
| 12 | `rel_spy_5d` | `ret_5d_stock - ret_5d_SPY` | MISSING — have `rs_vs_spy_21d/63d/126d`, no 5d | ADD |

**Coverage**: 3/12 present, 4/12 partial (need unsigned/raw exposure),
5/12 fully missing.

### 3.2 Labels

| Label | Formula | Current state | Gap |
|---|---|---|---|
| `y_cc_1d` | `close_{t+1}/close_t - 1` | PRESENT — `compute_forward_returns(horizons=[1])` | KEEP |
| `y_cc_5d` | `close_{t+5}/close_t - 1` | PRESENT | KEEP |
| `y_oc_1d` | `close_{t+1}/open_{t+1} - 1` | MISSING (requires open_df alignment) | ADD |
| `y_oo_1d` | `open_{t+1}/open_t - 1` | MISSING | ADD |

### 3.3 Universe filters (already ok, formalize)

| Filter | Current state | Gap |
|---|---|---|
| `price > 5` | In `scripts/universe_admission_screen.py::_check_price_floor` ($5 extended, $10 core) | KEEP; expose as daily per-symbol mask |
| `dollar_vol_20d > threshold` | In admission screen as ADV60 ($20M/$50M) | KEEP; expose as daily per-symbol mask |

Gap: admission layer is run once per universe refresh. The masks should
also be queryable **per-date-per-symbol** so ML training / factor IC can
exclude below-threshold bars. Not urgent — admission already prevents
these tickers from entering the panel.

---

## 4. Deliverables

### 4.1 New factor helpers (`core/factors/base_factors.py`)

Reusable one-line primitives that both `factor_generator` and
`MultiFactorStrategy` can share (same pattern as existing `low_vol_factor`,
`rel_strength_factor`):

```python
def simple_return(price_df, lookback: int) -> pd.DataFrame: ...
def overnight_return(open_df, close_df) -> pd.DataFrame: ...
def intraday_return(open_df, close_df) -> pd.DataFrame: ...
def hl_range(high_df, low_df, close_df) -> pd.DataFrame: ...
def dist_from_ma(close_df, window: int) -> pd.DataFrame: ...
def dist_from_rolling_max(close_df, window: int) -> pd.DataFrame: ...
def relative_strength(stock_df, benchmark, lookback: int) -> pd.DataFrame: ...
def dollar_volume_ma(close_df, volume_df, window: int) -> pd.DataFrame: ...
```

### 4.2 New factor family (`core/factors/factor_generator.py`)

New helper `_baseline_factors(price_df, high_df, low_df, open_df, volume_df,
spy_close)` generating:

| Factor name | Origin | Helper used |
|---|---|---|
| `ret_1d` | NEW | `simple_return(lookback=1)` |
| `ret_2d` | NEW | `simple_return(lookback=2)` |
| `ret_5d` | NEW (unsigned sibling of `reversal_5d`) | `simple_return(lookback=5)` |
| `overnight_ret_1d` | NEW (raw 1-bar sibling of `overnight_gap_5d/21d`) | `overnight_return()` |
| `intraday_ret_1d` | NEW | `intraday_return()` |
| `hl_range_1d` | NEW | `hl_range()` |
| `dist_ma20` | NEW (unsigned sibling of `mean_rev_sma20`) | `dist_from_ma(20)` |
| `dist_52w_high` | NEW (252d sibling of `max_dd_126d`) | `dist_from_rolling_max(252)` |
| `rel_spy_5d` | NEW (5d sibling of `rs_vs_spy_21d/63d/126d`) | `relative_strength(lookback=5)` |
| `dollar_vol_20d` | NEW (factor-side; universe-side already exists) | `dollar_volume_ma(20)` |

That's **10 new registered factors**. User's 12 minus 2 already-present
(`vol_20d` → `vol_21d`, `volume_ratio_20d` → `volume_surge_20d`).

### 4.3 Label extension (`core/factors/factor_generator.py`)

```python
def compute_forward_returns(
    price_df, open_df=None, horizons=None, mode="cc",
): ...
# mode ∈ {"cc", "oc", "oo"}:
#   cc: close[t+h] / close[t] - 1           (existing)
#   oc: close[t+h] / open[t+h] - 1          (new)
#   oo: open[t+h] / open[t] - 1             (new)
```

Backward-compat: default `mode="cc"` preserves the existing signature.

### 4.4 Registry updates (`core/factors/factor_registry.py`)

- `RESEARCH_FACTORS`: +10 names listed above
- `RESEARCH_TO_PRODUCTION_MAP`: explicit entries so drift detector knows
  these are NEW (no production sibling yet), not shadows of existing prod.
  Mappings:
  - `ret_1d` → None (research-only)
  - `ret_2d` → None
  - `ret_5d` → None (existing `reversal_5d` is sign-flipped, treated
    as distinct signal)
  - `overnight_ret_1d` → None
  - `intraday_ret_1d` → None
  - `hl_range_1d` → None
  - `dist_ma20` → None (`mean_rev_sma20` sign-flipped, distinct)
  - `dist_52w_high` → None
  - `rel_spy_5d` → None (shorter horizon than existing `rs_vs_spy_*`)
  - `dollar_vol_20d` → None
- **No `PRODUCTION_FACTORS` changes**. Promotion (if any) is a separate
  round that follows the standard funnel — per invariant §2.

### 4.5 Tests

- `tests/unit/factors/test_base_factors.py` — unit test each new helper
  on toy DataFrames (8 tests minimum, one per helper + one edge case)
- `tests/unit/factors/test_factor_generator.py` — extend to assert all 10
  new factor names are produced by `generate_all_factors()` and have the
  expected shape (price_df panel alignment)
- `tests/unit/factors/test_factor_registry.py` — drift detector must pass
  (i.e. every name in `_baseline_factors` output is listed in
  `RESEARCH_FACTORS`)
- `tests/unit/factors/test_forward_returns.py` — 3 tests for cc/oc/oo
  semantics on a synthetic 10-bar panel

Target: **≥15 new tests**, full suite stays green.

### 4.6 IC screening smoke

Run `scripts/run_factor_screen.py --factors <10 new>` on the default panel
(2015-01 through today, 79-symbol expanded universe). Record each new
factor's IC mean / IR vs forward return `y_cc_5d`. This is a **sanity
check**, not a promotion gate. Output: `data/ml/baseline_feature_screen.csv`
+ a short `docs/YYYYMMDD-baseline_feature_screen_findings.md` with
commentary on surprises.

### 4.7 Gitignore handling

No data file commits. All artifacts go under `data/ml/` (gitignored).
`docs/` files are code-tracked.

---

## 5. Out of Scope

- NO changes to `PRODUCTION_FACTORS` (keep current 7; promotion is a
  separate round)
- NO changes to `MultiFactorStrategy` (doesn't consume research factors
  directly; it has its own inline computation)
- NO changes to universe / admission / data pipeline
- NO new LLM-candidate seeding here — this PRD is about established
  conventions, not research hypotheses
- NO changes to `MiningEvaluator` gates or acceptance pack

---

## 6. Acceptance Criteria

| Criterion | Standard |
|---|---|
| All 10 new factors produced by `generate_all_factors` | Panel shape matches `price_df`, no NaN columns in steady state |
| All 10 names in `RESEARCH_FACTORS` | `test_factor_registry::test_research_set_matches_generator` green |
| `compute_forward_returns` supports mode ∈ {cc, oc, oo} | 3 new tests green |
| Backward compat | Default signatures unchanged; existing 1215 tests stay green |
| IC smoke shows plausible sign | At least 3 of the 10 should have \|IC\| > 0.02 — weaker is not fatal, just flag |
| Reproducibility | Artifact paths + config fingerprint logged |

---

## 7. Rollout

| Step | Estimated LOC | Blocking |
|---|---:|---|
| 1 | `base_factors.py` helpers + unit tests | ~200 | — |
| 2 | `_baseline_factors` in `factor_generator.py` + integration with `generate_all_factors` | ~80 | 1 |
| 3 | `compute_forward_returns` mode extension + tests | ~60 | — |
| 4 | `RESEARCH_FACTORS` + `RESEARCH_TO_PRODUCTION_MAP` updates + drift tests | ~30 | 2 |
| 5 | IC screening run + findings doc | — | 4 |
| 6 | commit split into 2: (helpers + gen + registry) / (labels + screen) | — | — |

Expected effort: ~0.5 day for experienced implementer.

---

## 8. Known Risks

1. **Name collision risk**: `ret_1d` could be confused with intraday
   returns if future multi-TF work uses similar naming. Mitigation:
   register names + reserve in `RESEARCH_FACTORS` first; any
   intraday-timescale sibling needs suffix (e.g. `ret_1d_60m`).
2. **Dollar-volume factor semantics**: `dollar_vol_20d` overlaps with
   admission-layer ADV60. They measure the same quantity at different
   time horizons. Clear docstring required: "factor = per-day signal;
   admission = stable filter".
3. **Sign conventions**: existing `reversal_5d`, `mean_rev_sma20` are
   sign-flipped for strategy convenience. New unsigned siblings
   (`ret_5d`, `dist_ma20`) might confuse. Mitigation: naming makes sign
   explicit (`ret_5d` = raw return, `reversal_5d` = negative of it).
4. **MaxDD leaking into `dist_52w_high`**: `dist_52w_high` on a freshly
   IPO'd stock (< 252 bars) should be NaN, not 0. Enforce via
   `min_periods` in rolling max.
5. **Label with `open`**: `y_oc_1d` / `y_oo_1d` require open_df from
   `open_df` input; must pass through `factor_engine` and propagate
   correctly in `evaluator.py` pipelines.

---

## 9. Open Questions (user to confirm before start)

1. **Helper location**: new helpers in `core/factors/base_factors.py`
   (current path for `low_vol_factor`, `rel_strength_factor`) — OK to
   extend that file, or split into `base_returns.py` / `base_volatility.py`
   etc.? Default: extend `base_factors.py`.
2. **Dollar volume semantics**: is `dollar_vol_20d` treated as a raw
   factor (for ML feature), or is its role purely tradability filter?
   Default: both. Register as factor, also expose a `dollar_vol_mask`
   helper for filtering.
3. **20d vs 21d decision**: user spec says 20d, registry has 21d. Do we
   add `vol_20d` as a separate factor, or alias `vol_20d := vol_21d`?
   Default: keep `vol_21d`, document as the de-facto 20d.
4. **`dist_52w_high` window**: user says 252 days (52 weeks × 5 days).
   Some industry conventions use 250 (50 weeks) for weekly-compatible.
   Default: 252, matches `max_dd_126d`'s 252-day lookback for max-high.
5. **IC screen panel**: run on pre-expansion (52-sym) or post-expansion
   (79-sym) universe? Default: **post-expansion** (79-sym) because this
   is the universe the next mining loop will operate on.

---

## 10. Connection to Next Mining Round

After this PRD is shipped:

- `config/universe.yaml` unchanged (79 symbols, from R38 Stage 1+2)
- `config/cross_ticker_rules.yaml` unchanged (5 rules, incl. Rule 2
  suppress_if + fixed Rule 5)
- `RESEARCH_FACTORS` grows from 41 → 51 names (35 existing + 10 new)
- `PRODUCTION_FACTORS` unchanged at 7 names
- Bug-fix stack (M14 + std-floor + _check_qqq_gate leading-NaN) already
  landed via commits `ee3effb`, `1f7e08e`, `2f9fbe9`

Next mining round will use these features via `MultiFactorSpace.suggest()`
(if any get promoted to PRODUCTION) or via `run_factor_screen.py` /
`run_xgb_importance.py` (research-only). Exact round design is a separate
PRD, driven by user.

---

## 11. References

- User spec 2026-04-23 (feature list, labels, filters, pitfalls)
- 52-week high momentum: George & Hwang 2004 (JSTOR 3694820)
- QuantConnect docs on adjusted prices + temporal leakage
- `docs/20260421-promotion_flow.md` — factor promotion procedure
- `docs/20260422-deep_mining_50round_final_synthesis.md` — latest
  research state; this PRD is the immediate successor baseline

---

*PRD v0.1 draft. Waiting for user sign-off on §9 open questions before
implementation begins.*
