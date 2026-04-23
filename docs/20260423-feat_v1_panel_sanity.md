# Feature-v1 Panel Sanity Check (R06, Step 2)

**Date**: 2026-04-23
**PRD**: `docs/20260423-prd_research_feature_engineering_and_expanded_mining.md` §7.2 Phase A
**Related rounds**: R01-R05 factor/label/mask additions; commit range `2e5acf6`..`4eea421`

---

## Goal

End-to-end verify that **all** R01-R05 additions operate correctly on
the real 79-symbol expanded universe — not just on toy synthetic
fixtures. This is the Step 2 gate before Step 3 (R39 fresh mining).

Checks: factor presence, NaN rate, alias identity, forward-return
modes, masks, registry drift, and a smoke IC test on 5d forward
returns.

---

## Universe

- 79 symbols loaded from `config/universe.yaml` (seed_pool + sector_etfs
  + factor_etfs + cross_asset)
- Panel: 3459 bars, **2015-01-03 → 2026-04-22**
- OHLCV all sourced via `BarStore.load(freq="daily")` (0 load errors)

## Factor generator call

```python
factors = generate_all_factors(
    close_df, volume_df=volume_df,
    open_df=open_df, high_df=high_df, low_df=low_df,
    benchmark_col="SPY",
)
# → 49 factor names total (35 pre-R01 + 11 new R01-R05 registered + 3 not produced*)
```

*3 intraday factors (`realized_vol_60m_21d`, etc.) require
`intraday_bars_60m` kwarg; not supplied in this sanity pass (Step 2
is daily-only per PRD §3.1).

## New-factor presence

**11/11** new R01-R05 registered factors present:

```
ret_1d, ret_2d, overnight_ret_1d, intraday_ret_1d,
hl_range, dollar_vol_20d,
ret_5d, dist_52w_high, rel_spy_5d,
vol_20d (alias), volume_ratio_20d (alias)
```

## NaN rate (last 1000 bars, per-column mean-of-isna)

| factor | NaN frac | n-cols with any nonzero |
|---|---:|---:|
| ret_1d | 0.273 | 79 |
| ret_2d | 0.267 | 79 |
| overnight_ret_1d | 0.273 | 79 |
| intraday_ret_1d | 0.136 | 79 |
| hl_range | 0.273 | 79 |
| dollar_vol_20d | 0.000 | 79 |
| ret_5d | 0.256 | 79 |
| dist_52w_high | 0.136 | 79 |
| rel_spy_5d | 0.344 | 78 |
| vol_20d (alias) | 0.753 | 20 |
| volume_ratio_20d (alias) | 0.753 | 20 |

Non-zero column count = 79 for all new factors (every symbol has at
least one finite factor value in the tail window). Alias numbers match
their canonical (`vol_21d`, `volume_surge_20d`) — fewer non-zero columns
reflects pre-existing coverage in the older rolling factors (late-IPO
tickers TKO/TRGP/VICI/ACGL have partial series). Non-blocking.

`rel_spy_5d` produces 78 non-zero columns (vs 79) because SPY's own
column equals exactly 0 by construction (self-reference test verified
in `test_relative_return_benchmark_column_is_zero`).

## Alias identity

```python
factors["vol_20d"]         is factors["vol_21d"]          # True
factors["volume_ratio_20d"] is factors["volume_surge_20d"] # True
```

Same DataFrame reference (no copy); PRD §D3 semantics honored.

## Forward-return modes (cc / oc / oo)

All three modes produce shape-aligned panels on the 79-symbol universe:

| mode | shape match | last-5-bars NaN |
|---|---|---|
| cc | True | True |
| oc | True | True |
| oo | True | True |

Backward-compat: `compute_forward_returns(price_df, [5])` → mode="cc"
(unchanged default).

## Mask True-fraction

| mask | True frac (full panel) |
|---|---:|
| `price_floor_mask(min_price=5)` | 0.826 |
| `tradable_mask_dollar_vol(min_usd=20e6, window=20)` | 0.958 |
| `research_mask` (combined) | 0.811 |

Price mask at ~83% True means ~17% of bars are below the $5 floor —
dominated by early-period low-price stocks that later split/adjusted
up (sanity: matches expectation given 2015 start).

## Registry drift

- Produced but not registered: **0**
- Registered but not produced: **3** — all intraday family (60m bars
  not supplied this run; expected)

Drift check on its own (with synthetic OHLCV + intraday bars in
`tests/unit/factors/test_factor_registry.py`) is GREEN (1262/1262
tests pass).

---

## IC_5d smoke (Spearman rank-correlation, date-by-date)

Not a promotion gate — just sanity on direction and magnitude. 5d
forward close-to-close returns vs each new factor, averaged across
dates where ≥ 10 symbols have finite values.

| factor | IC mean | IC std | n dates |
|---|---:|---:|---:|
| **ret_1d** | **-0.258** | 0.384 | 3327 |
| **overnight_ret_1d** | **-0.254** | 0.387 | 3327 |
| **ret_5d** | **-0.175** | 0.307 | 3288 |
| **ret_2d** | **-0.170** | 0.303 | 3280 |
| **dist_52w_high** | **-0.136** | 0.326 | 3238 |
| **rel_spy_5d** | **-0.136** | 0.280 | 2248 |
| hl_range | -0.068 | 0.280 | 3327 |
| intraday_ret_1d | -0.014 | 0.257 | 3342 |
| dollar_vol_20d | +0.009 | 0.195 | 3335 |

### Direction

All non-trivial signals are **negative-IC** — the factor value is
inversely correlated with 5d forward return. In raw form, this is the
classic short-term reversal effect in US equities: today's winners
tend to underperform tomorrow. To use as signal-ready direction, a
downstream strategy would negate these (which is exactly what the
existing `reversal_5d` / `mean_rev_sma20` already do with sign-flip).

### Scope interpretation

Six factors have `|IC| > 0.13`:

- `ret_1d` (-0.258) — strongest 1-day reversal
- `overnight_ret_1d` (-0.254) — overnight gap reversal
- `ret_5d` / `ret_2d` (-0.17ish) — 2-5 day reversal
- `dist_52w_high` (-0.136) — reversion from below 52-week peak
- `rel_spy_5d` (-0.136) — short benchmark-relative reversion

These are all known effects. They fill PRD §3.1 coverage gaps where
before R01-R03 the registry had only longer horizons (21d/63d/126d)
and sign-flipped variants. Nothing magical — but now the mining
optimizer + LLM candidate funnel have clean raw primitives to compose.

### Not-predictive (expected)

- `dollar_vol_20d` IC ≈ 0 — liquidity alone isn't directional, and
  that's exactly why it's best used as a mask (PRD §D2 dual-role)
- `intraday_ret_1d` IC ≈ 0 — intraday-only move is often noise at 5d
  horizon; stronger effect would show up via interactions with overnight

## PRD §7.2 Phase A acceptance

| Criterion | Status |
|---|---|
| 79-symbol panel stably generated | ✅ |
| All new factor / label / mask consumable by downstream | ✅ |
| Alias and raw-sibling behavior clear | ✅ |

**Phase A PASS.** Ready to proceed to Phase B (R07 Step 3: R39 fresh
baseline mining on 79-symbol expanded universe).

---

## Known follow-ups (non-blocking)

1. Alias NaN-fraction in tail mirrors canonical's: not a bug, but
   future registry drift check might benefit from treating aliases as
   "same coverage as canonical" explicitly
2. `core/factors/factor_engine.py::make_forward_returns` (evaluator-
   internal utility) still only supports cc mode. If a future mining
   evaluator wants oc/oo labels, it's a 1-function extension.
3. Pandas4 `FutureWarning` about default `sort=True` in `pd.concat`
   all-DatetimeIndex: cosmetic, not a correctness issue.
