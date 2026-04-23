# Feature Data-Tier Classification

**Date**: 2026-04-23
**Purpose**: Classify all candidate research features by the data
infrastructure they require, so future PRDs (`Research Composite Miner v1
+ Orthogonal Feature Expansion` and successors) can reference this as a
single source of truth instead of re-auditing each time.
**Source**: Consolidation of feat-v1 audit (2026-04-23) + user-curated
feature map (same session).
**Consumes**: `core/factors/factor_registry.py` (current state),
`core/data/yfinance_provider.py` (data interface), `config/universe.yaml`
(benchmark + sector ETFs inventory).
**Consumed by**: upcoming PRD for Research Composite Miner v1, and any
subsequent feature-expansion PRDs.

---

## Quick decision table

| Tier | Data requirement | Code ready? | Current-round PRD? |
|------|---|---|---|
| **T1** | Adjusted per-symbol OHLCV only | ✅ yes | ✅ IN — core of next PRD |
| **T2** | + benchmark OHLCV (SPY / QQQ / sector ETFs) | ⚠ partial: `generate_all_factors` accepts only 1 `benchmark_col` | ✅ IN — requires multi-benchmark plumbing prerequisite |
| **T3** | + point-in-time sector / industry classification | ❌ no — `YFinanceProvider` does not implement metadata pipeline | ❌ OUT — future PRD after PIT sector data vendor |
| **T4** | + point-in-time shares outstanding / float | ❌ no | ❌ OUT — future PRD |
| **T5** | + per-symbol earnings + analyst data | ❌ no (only `config/events.yaml` generic window config) | ❌ OUT — future PRD |
| **T6** | + options / short-interest / ownership / alt data | ❌ no | ❌ OUT — future PRD + new data engineering |

---

## T1 — Adjusted OHLCV only

**Data source**: `yfinance_provider.fetch_daily(symbols, start, end)` —
already live. `auto_adjust=True` makes open/high/low/close split-and-
dividend adjusted. Volume included.

**Code prerequisites**: none (already supported). `generate_all_factors`
accepts `open_df / high_df / low_df / volume_df` since feat-v1 R01-R02.
8 downstream research scripts still need upgrade to pass OHLC (feat-v1
audit #1) — this is a coding task, not a data task.

### T1 feature inventory

#### 1a. Returns family
- `ret_cc_1d`, `ret_cc_2d`, `ret_cc_5d`, `ret_cc_10d`, `ret_cc_20d`,
  `ret_cc_60d`, `ret_cc_120d`, `ret_cc_252d`
- `overnight_ret` (1-bar)
- `intraday_ret` (1-bar)
- Already in registry (partial): `ret_1d`, `ret_2d`, `ret_5d`,
  `overnight_ret_1d`, `intraday_ret_1d`, `mom_21d`, `mom_63d`,
  `mom_126d`, `mom_252d`, `mom_12_1`

#### 1b. Volatility family
- `vol_20d`, `vol_60d`, `vol_120d` (rolling std of daily returns)
- `downside_vol_20d` (std of negative returns only)
- `vol_ratio_5_20` (short/long vol term structure)
- `ret_skew_20d`, `ret_kurt_20d` (distribution moments)
- `worst_day_20d`, `max_drawdown_60d` (tail measures)
- `jump_freq_20d` (discrete large-move counter)
- High-frequency estimators (Parkinson / Garman-Klass / Rogers-Satchell
  / Yang-Zhang): require H + L + optionally O + C, still T1
- Already in registry (partial): `vol_21d`, `vol_63d`, `vol_regime`,
  `vol_20d` (alias), `hl_range`

#### 1c. Trend / position family
- `dist_ma20`, `dist_ma60`, `ma20_ma60_spread` (MA-based)
- `breakout_20d` (continuous: close / max(20d) - 1)
- `dist_52w_high`, `range_pos_252d` (distinct math — see below)
- `days_since_52w_high`, `new_high_flag_252` (time-state)
- `ols_slope_20d`, `trend_tstat_20d`, `ols_r2_20d` (regression-based)
- `drawdown_current`, `drawup_from_252d_low` (extremum-based)
- Already in registry (partial): `mean_rev_sma20`, `mean_rev_sma50`,
  `spy_trend_200d`, `dist_52w_high`, `drawup_from_252d_low`,
  `drawdown_current`, `max_dd_126d`

Note on `dist_52w_high` vs `range_pos_252d`:
- `dist_52w_high` = `close / max(close, 252) - 1` ∈ [-∞, 0]
- `range_pos_252d` = `(close - min(252)) / (max(252) - min(252))` ∈ [0, 1]
- Different economic semantics; both worth keeping.

#### 1d. Liquidity / volume family
- `amihud_20d` = `|ret_cc_1d| / dollar_volume`, rolling mean (illiquidity)
- `zero_return_freq_20d` (fraction of flat days)
- `log_adv20`, `dollar_vol_zscore` (liquidity state)
- `obv_delta_20d` (on-balance-volume)
- `win_rate_20d` (fraction of up days)
- Already in registry (partial): `volume_surge_20d`, `price_volume_div`,
  `dollar_vol_20d`, `volume_ratio_20d` (alias)

#### 1e. Quality family (all T1 because definitions are price-only)
- `return_per_risk_21d`, `rolling_sharpe_126d` (both in registry)
- `risk_adj_mom_63d` (in registry)
- No new T1 quality candidates worth prioritizing this round — existing
  coverage adequate.

### T1 current-round scope (12-feature PRD)
Per audit consensus, next PRD brings in this T1 subset:
- `amihud_20d`, `downside_vol_20d`, `vol_ratio_5_20`
- `range_pos_252d`, `days_since_52w_high`, `new_high_flag_252` (modifier)
- `breakout_20d` (modifier or continuous — TBD by PRD)
- `trend_tstat_20d`

Deferred T1 (still doable without new data, but not prioritized this round):
- `ret_cc_{10d, 60d, 120d, 252d}` (extend granularity — overlaps existing mom_*)
- Parkinson / Garman-Klass / Rogers-Satchell / Yang-Zhang (richer vol
  estimators — marginal improvement over vol_20d)
- `ret_skew_20d`, `ret_kurt_20d` (moments)
- `obv_delta_20d`, `win_rate_20d`, `jump_freq_20d`, `zero_return_freq_20d`
- `ma20_ma60_spread`, `ols_slope_20d`, `ols_r2_20d`
- `drawdown_from_peak` (near-duplicate of `dist_52w_high`)
- `day_of_week`, `day_of_month` (pure calendar — no data need)

---

## T2 — Benchmark OHLCV

**Data source**: SPY, QQQ already in universe. Sector ETFs (XLK / XLF /
XLY / XLP / XLE / XLV / XLI / XLU / XLB / XLRE / XLC) in
`config/universe.yaml::sector_etfs` — OHLCV available via same yfinance
path.

**Code prerequisites** — 3 blocking items:

1. **Multi-benchmark in `generate_all_factors`**: current signature
   accepts `benchmark_col: str = "SPY"` only. Need to extend to
   `benchmark_map: Dict[str, pd.DataFrame]` or equivalent so features
   can reference SPY AND QQQ AND sector-ETF benchmarks simultaneously.

2. **Residualization helper**: `core/factors/base_relative.py::residualize
   (stock_df, benchmark_ret, lookback)` — rolling OLS residual. Reused
   across `residual_mom_spy_20d`, future sector-neutral features, and
   any benchmark-regressed factor.

3. **Multi-beta helper**: `rolling_beta(stock_df, benchmark_ret, lookback)`
   for `beta_spy_60d` etc. Trivial on top of residualize output.

### T2 feature inventory

- `rel_spy_20d` — close-to-close stock return minus SPY return over 20d
- `rel_qqq_20d` — same vs QQQ (invariant-mandated second benchmark)
- `beta_spy_60d` — rolling 60d OLS beta vs SPY returns
- `beta_qqq_60d` — optional, same vs QQQ
- `residual_mom_spy_20d` — 20d return residual after beta-adjusting
- `residual_vol_spy_20d` — std of residuals (optional, lower priority)
- `sector_etf_rel_20d` — stock ret minus its mapped sector ETF's ret
  (requires static symbol→sector-ETF map, which `config/universe.yaml`
  implicitly has via `sector_etfs` section, though not wired)
- Already in registry (partial): `rs_vs_spy_21d`, `rs_vs_spy_63d`,
  `rs_vs_spy_126d`, `rs_acceleration`, `rel_spy_5d`

### T2 current-round scope
Per audit consensus:
- `rel_spy_20d`, `rel_qqq_20d`
- `beta_spy_60d`
- `residual_mom_spy_20d`

Deferred T2 (doable but not prioritized):
- `beta_qqq_60d`, `residual_vol_spy_20d`
- `sector_etf_rel_20d` (requires static sector-ETF map wire-up —
  borderline T2/T3 depending on how strict "point-in-time" requirement
  is interpreted; see below)

---

## T3 — Sector / industry classification

**Data required**: point-in-time GICS (or similar) sector + sub-industry
tags per ticker per date. Static current-day tags are NOT sufficient —
retrospectively applying today's tag to 2015 contaminates research (a
stock reclassified in 2020 would look wrongly tagged for 2015-2019).

**Current state**:
- `DataProvider.get_metadata(symbol)` is an ABC, not implemented by
  `YFinanceProvider`.
- yfinance's `Ticker.info["sector"]` exists but is current snapshot only —
  NOT point-in-time.
- `config/universe.yaml::sector_etfs` gives the universe-level list but
  no ticker-to-sector mapping.

**Options to enable T3**:
1. Manual curated static map in `config/sector_map.yaml` — acceptable
   for near-term research if we accept 5-10% misclassification from
   historical re-tags. Cheapest.
2. Third-party PIT data (e.g. Sharadar's sector history, Simple Wall
   Street, Factset-lite services) — paid, authoritative.
3. yfinance one-shot snapshot cached + manual overrides for known
   reclassifications — hybrid.

**Recommended path for next PRD**: defer. If Option 1 is acceptable,
propose in a follow-up narrow PRD (~2 days: curation + `sector_resolver`
helper + audit of stale tags); only then enable T3 features.

### T3 feature inventory
- `sector_rel_20d` — stock ret minus sector average ret over 20d
  (requires sector membership + per-sector aggregation)
- `sector_neutral_mom_20d` — residual after sector mean removal
- `industry_neutral_mom_20d` — same at sub-industry level (needs finer
  classification than GICS-10)
- `sector_leader_rank` — cross-sectional rank within sector
- `sector_momentum_spread` — rolling sector-level rotation signal

---

## T4 — Shares outstanding / float

**Data required**: point-in-time shares outstanding (diluted), free float,
insider holdings.

**Current state**:
- yfinance provides `Ticker.info["sharesOutstanding"]` snapshot only.
- Historical `sharesOutstanding` series is NOT available from free
  sources reliably.
- `core/data/yfinance_provider.py` does not pull it.

**Options**:
1. SEC 10-Q / 10-K filings parsing (quarterly shares outstanding at filing
   date, interpolated) — doable but requires EDGAR ingest pipeline.
2. Sharadar / Simfin / quandl-successor (paid PIT fundamentals data).
3. Skip — treat T4 features as out-of-scope until a structural data
   upgrade.

### T4 feature inventory
- `turnover_20d` = `volume / shares_outstanding`, rolling mean
- `float_turnover_20d` = `volume / float_shares` (harder: free float vs
  total shares)

Lower-priority T4: not critical for current research program.

---

## T5 — Earnings + analyst data

**Data required**:
- Per-symbol earnings calendar (announcement date, after/before market,
  fiscal period)
- Consensus EPS / revenue estimates
- Actual EPS / revenue
- Analyst coverage count
- Target price
- Estimate revisions history

**Current state**:
- `config/events.yaml` contains generic event-window config (not per-
  symbol calendar).
- No earnings data ingest.
- yfinance's `Ticker.earnings_dates` gives forward calendar for ~8
  quarters, usable for `days_to_earnings` / `days_since_earnings` but
  NOT for PIT historical surprises.

**Options to enable T5**:
1. yfinance for days-to-earnings only (T5-lite, future-leaning).
2. Estimize / Zacks / IBES / Factset for estimates + actuals (paid).
3. Web-scraping earnings calendar + actual EPS (unreliable at scale).

### T5 feature inventory
- T5-lite (yfinance-based, cheap):
  - `days_to_earnings`
  - `days_since_earnings`
  - `post_earnings_flag` (T+1..T+3 window indicator)
- T5-full (needs paid data):
  - `eps_surprise` — (actual - consensus) / consensus
  - `rev_surprise`
  - `eps_revision_30d`
  - `target_price_gap` = (target_price - close) / close
  - `coverage_count`

### T5 decision
Consider T5-lite as a **future narrow PRD** (`days_to_earnings` family):
doable with yfinance, cheap, meaningful for post-earnings drift / pre-
earnings positioning studies. T5-full needs a data vendor decision and
is out of research scope until budget/sourcing decided.

---

## T6 — Options / alt data

**Data required** (each independent):
- Options (any vendor): PUT/CALL ratio, IV surface, IV rank, IV term
  structure, skew.
- Short interest (FINRA monthly, twice-monthly): short_interest /
  float, days_to_cover.
- Ownership (13F filings quarterly): institutional ownership %, insider
  activity.
- News / social / web traffic: vendor-specific.

**Current state**: none of these are ingested.

**Options**:
- Options: ORATS, Sentimental Trader, Bloomberg (paid). Interactive
  Brokers API can provide real-time IVs but not historical easily.
- Short interest: FINRA free publishing (biweekly), manageable ingest.
- Ownership: SEC EDGAR 13F parsing (quarterly, manageable).
- Alt data: vendor-specific (Thinknum, YipitData, Bloomberg Terminal).

### T6 feature inventory
- Options: `put_call_ratio`, `iv_rank`, `iv_term_slope`, `skew_25d`
- Short: `short_interest_pct_float`, `days_to_cover`, `si_change_30d`
- Ownership: `institutional_ownership`, `inst_own_change`, `insider_buy_flag`
- Alt: `news_sentiment_score`, `web_traffic_zscore`, `app_rank_change`

### T6 decision
All out-of-scope for current research program. Each is a data
engineering effort, not "add a factor". Individual T6 features could
be studied after core research space is stabilized, and should each
have its own narrow PRD + data-source authorization.

---

## Appendix A — Mapping: audit's 12-feature scope → tier

| Feature | Tier | Notes |
|---|---|---|
| `rel_spy_20d` | T2 | needs multi-benchmark plumbing prerequisite |
| `rel_qqq_20d` | T2 | same |
| `beta_spy_60d` | T2 | needs `rolling_beta` helper |
| `residual_mom_spy_20d` | T2 | needs `residualize` helper |
| `range_pos_252d` | T1 | distinct math from dist_52w_high; keep both |
| `days_since_52w_high` | T1 | time-state modifier |
| `new_high_flag_252` | T1 | boolean; recommend modifier-only |
| `breakout_20d` | T1 | continuous preferred (close/max(20)-1) |
| `amihud_20d` | T1 | |ret|/$vol rolling mean |
| `downside_vol_20d` | T1 | asymmetric risk |
| `vol_ratio_5_20` | T1 | vol term structure |
| `trend_tstat_20d` | T1 | preferred over ols_slope_20d alone |

**Summary**: 8 × T1 + 4 × T2 + 0 × T3+. All achievable with current
data infrastructure after 3 plumbing prerequisites (multi-benchmark +
residualize + rolling_beta helpers).

---

## Appendix B — Plumbing prerequisites for this round's PRD

Without these, the 12-feature scope half-lands (as feat-v1 did):

| Prereq | Code location | Effort |
|---|---|---:|
| Multi-benchmark `generate_all_factors` | `core/factors/factor_generator.py` | ~1d |
| `residualize(stock, benchmark, lookback)` helper | `core/factors/base_relative.py` | ~0.5d |
| `rolling_beta(stock, benchmark, lookback)` helper | `core/factors/base_relative.py` | ~0.25d |
| 8 downstream scripts upgraded to pass OHLC + new factors | scripts/run_xgb_*.py, scripts/run_transformer_research.py, scripts/run_model_comparison.py, scripts/run_factor_interaction_mine.py, scripts/llm_composite_backtest.py, scripts/llm_candidate_orthogonalization.py | ~0.5d |
| `apply_research_mask()` replaces `fillna(0)` in miner / IC screen / ML panel | various | ~0.5d |

---

## Appendix C — Out-of-scope but documented for future PRDs

These features / data sources are **genuine alpha sources** worth pursuing
but each requires its own authorization + data engineering effort. Listed
here so no future round has to re-do this audit:

- **Sector classification (T3)**: narrow PRD after point-in-time vendor decision
- **Earnings calendar-lite (T5-lite)**: narrow PRD on yfinance earnings dates → `days_to_earnings` family
- **Shares outstanding / float (T4)**: narrow PRD requiring SEC filings ingest OR paid vendor
- **Earnings surprise (T5-full)**: narrow PRD requiring IBES / Factset or equivalent
- **Options (T6)**: separate data engineering project; lowest priority until alpha research stabilized
- **Short interest (T6)**: FINRA ingest — cheapest T6, if user wants to prioritize
- **Ownership (T6)**: EDGAR 13F parsing — moderate effort

Each of these, when addressed, should produce its own tier-specific
narrow PRD, reference this document, and update the tier table in
place.

---

## Version note

- v1.0 — 2026-04-23: initial classification after feat-v1 loop exit,
  consolidating audit observations + user-curated feature map +
  code-interface audit. Serves as single reference for the upcoming
  `Research Composite Miner v1 + Orthogonal Feature Expansion` PRD.
