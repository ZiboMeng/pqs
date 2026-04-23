# PQS Universe Expansion Spec v2.2

**Status**: v2.2 — integrated 4 items from user R23 critique of v2.1
**Date**: 2026-04-21
**Author**: LLM-phase ralph-loop (R22 drafting, user-directed revisions)
**Lineage**: R21 v1 → user critique → R22 v2 → user R22 second critique → v2.1 → **user R23 third critique → v2.2 (this doc)**

**Calibration note**: Thresholds in this document are **default
production starting points** and remain **subject to empirical
calibration** via backtest coverage tests. Tuning a threshold after
launch does NOT constitute a spec change; only the rule structure
is normative.

**Purpose**: production-ready specification for PQS universe admission,
risk labeling, portfolio priority buckets, and ongoing reconstitution.
Strictly separates *admission* (objective, forward-looking rules) from
*alpha scoring* (which operates on the admitted pool) to avoid
survivorship / look-ahead bias.

---

## 1. Four-Layer Architecture

```
  ┌─────────────────────────────────────────────────┐
  │  Tradable Universe (Layer 1 hard admission)     │  ← actual trading pool
  │                                                 │
  │  ───────────────────────────────────────────    │
  │  Discovery Watchlist (separate set, monitored)  │  ← NOT tradable, NOT
  │  symbols meeting 252d listing + other L1 rules  │    optimized over
  │  but not yet 504d hard admit                    │
  └─────────────────────────────────────────────────┘
  ┌─────────────────────────────────────────────────┐
  │  Layer 2: Risk Exposure Labels (metadata)       │  ← tags, not filters
  ├─────────────────────────────────────────────────┤
  │  Layer 3: Priority Buckets (portfolio construct)│  ← alpha scoring here
  ├─────────────────────────────────────────────────┤
  │  Layer 4: Portfolio Constraints (weight-level)  │  ← real exposure limits
  └─────────────────────────────────────────────────┘
  + Reconstitution rules (cross-layer cadence + buffers)
```

**Key clarification (R23 item 1, v2.1→v2.2)**: "Tradable Universe" and
"Discovery Watchlist" are **two separate sets**. Only Tradable Universe
symbols enter Layer 3 bucket assignment and Layer 4 portfolio
optimization. Discovery Watchlist symbols are monitored for eventual
admission when they reach the 504d history threshold, but are NEVER
allowed into holdings or optimization decisions.

---

## 2. Layer 1 — Tradable Universe (admission)

### 2.1 Security Type (whitelist)

**Admit**: US common stock (listed on NYSE / NASDAQ / BATS / IEX).

**Reject**:
- ETF / ETN / CEF / BDC
- Leveraged or inverse products
- Preferred shares / warrants / rights / units
- SPAC / de-SPAC within first 6 months of merger
- OTC / pink sheet
- ADR (excluded by default; optional sub-pool requires explicit flag)

**REIT policy**: REITs admitted to the equity universe by default,
tagged `is_reit=true` in Layer 2. Layer 4 has a separate REIT cap
(rate-sensitive bucket).

### 2.2 Listing History (R23 item 1, Tradable vs Watchlist clarified)

| Set membership | Listing history |
|---|---|
| **Tradable Universe** (admitted) | ≥ **504 trading days** (~2y) |
| **Discovery Watchlist** (monitored only) | ≥ 252d and < 504d |
| Not yet eligible | < 252 trading days |
| `stability_label = full_history` tag | ≥ 1260 trading days (~5y) |

**Contract**: Discovery Watchlist symbols:
- Have Layer 2 risk labels computed (for preview)
- Do NOT participate in Layer 3 bucket assignment
- Do NOT receive any portfolio weight allocation
- Are re-evaluated at each monthly reconstitution; when history crosses
  504d + other L1 pass, they graduate to Tradable Universe

### 2.3 Price Floor

| Pool | Median close over last 60d |
|---|---|
| CORE | ≥ $10 |
| EXTENDED | ≥ $5 |
| Reject below | < $5 |

### 2.4 Liquidity — Dollar Volume (unified definition)

Let `DV(t) = close(t) × volume(t)` (daily dollar volume).

**Unified requirement**:
- `median(DV over last 60d) > threshold` (median is robust to spikes)
- AND `ADV20 > threshold` (recent trend check)
- AND `≥ 80% of last 60 days individually had DV ≥ 0.5 × threshold`
  (persistence — no pulse-volume names)

| Pool | Threshold |
|---|---|
| CORE | $50M |
| EXTENDED | $20M |
| WATCH (for Discovery) | $10M |
| Reject | < $10M |

### 2.5 Market Cap

| Pool | Threshold |
|---|---|
| CORE | ≥ $5B |
| EXTENDED | ≥ $2B |
| WATCH (for Discovery) | ≥ $500M |
| Reject | < $500M |

### 2.6 Data Completeness

- No all-NaN windows longer than 10 days in last 252d
- Corporate actions (splits, dividends) correctly applied
- No stale quote flags in last 20 days

### 2.7 Non-Blacklisted

Per `config/universe.yaml::blacklist`. Additive to type whitelist
(e.g., explicit human-flagged exclusions).

---

## 3. Layer 2 — Risk Exposure Labels (metadata only)

These are **computed and stored** for each symbol (both Tradable
Universe and Discovery Watchlist) but **never used as admission
filters**.

### 3.1 Risk-Estimation Readiness

Separate from admission. Two flags:

- `risk_estimation_ready`: SPY AND QQQ overlap ≥ 252d (enables beta/α
  estimation with reasonable precision)
- `risk_estimation_stable`: overlap ≥ 504d (multi-regime coverage)

### 3.2 Beta and Correlation

Compute (and update monthly):

- `beta_spy_252d`, `beta_spy_504d` (rolling)
- `beta_qqq_252d`, `beta_qqq_504d` (rolling) — **mandatory** for
  tech-exposure control
- `r2_spy_252d`, `r2_qqq_252d`
- `max(r2_spy, r2_qqq)` — "index-proxy score"
- `downside_beta_spy` (conditional on SPY return < -1σ)

### 3.3 Alpha Metrics (consistency-first)

Compute:

- `alpha_252d`, `alpha_504d` (annualized)
- `alpha_t_stat_252d`, `alpha_t_stat_504d`
- **`alpha_positive_rate_rolling`**: fraction of 63-day rolling windows
  (with 5-day step) where α > 0. **PRIMARY** metric; point estimates
  are secondary.
- `alpha_subperiod_consistency`: α sign agreement across non-overlapping
  252d subperiods
- `cost_adjusted_residual_return`: residual return minus estimated
  round-trip cost at median trade size

### 3.4 Tail-Risk Metrics (generic, non-regime-specific)

- `max_dd_rolling_3y`, `max_dd_rolling_5y`
- `worst_5pct_days_cond_return` (tail behavior on market's worst 5% days)
- `tail_correlation_to_spy` (correlation conditional on SPY < -2σ)

### 3.5 Sector / Industry

- `gics_sector`, `gics_industry` (from vendor or hand-mapped)
- `is_reit`, `is_ipo_recent` (< 1 year since IPO)

### 3.6 Execution Cost Metadata

- `median_spread_bps` (from intraday bars if available, else proxy via
  daily high-low range)
- `spread_pct_of_price`
- `volume_concentration_first_30m` (fraction of daily DV in first 30m)
- `volume_concentration_last_30m` (fraction in last 30m — MOC flow)
- `realized_gap_risk` (avg |overnight_gap| / daily_vol)

### 3.7 Shortability (schema reservation)

Reserve schema fields even if not immediately populated:

- `shortable` (bool)
- `borrow_cost_bps` (annualized)
- `hard_to_borrow_flag`

Sourced from broker API when live integration arrives.

### 3.8 Portfolio Marginal Metrics (computed dynamically)

- `corr_to_portfolio` (correlation to current holdings)
- `marginal_drawdown_contribution`
- `marginal_sharpe_contribution` (when added at small weight)

---

## 4. Layer 3 — Priority Buckets (portfolio construction)

Each **Tradable Universe** symbol (NOT Discovery Watchlist) is
classified into ONE primary bucket based on Layer 2 labels.

### 4.1 Alpha Core

Requirements (**all** must hold):

- `alpha_positive_rate_rolling > 0.60` (primary — consistency)
- `alpha_t_stat_504d > 1.5`
- `alpha_subperiod_consistency = true`
- `max(r2_spy, r2_qqq) < 0.75` (not pure index proxy)
- `cost_adjusted_residual_return > 0`
- `corr_to_portfolio < 0.80` (adds diversification)

### 4.2 Diversifiers (R23 item 2 — target definition; coverage-tested)

Requirements (**all** must hold by target definition):

- `beta_spy_252d < 0.70` AND `beta_qqq_252d < 0.70` (low on BOTH)
- `corr_to_portfolio < 0.50`
- `tail_correlation_to_spy < 0.50` (**truly** diversifies in stress)
- `marginal_drawdown_contribution ≤ 0` (improves portfolio drawdown
  when added)
- `marginal_sharpe_contribution ≥ 0` (doesn't drag risk-adjusted
  returns)
- `alpha_252d ≥ 0` OR `tail_correlation < 0.30` (may allow zero-alpha
  symbols if exceptional stress diversifier)

**R23 item 2 note**: This definition may be empirically too strict on
single-stock level. **Pre-launch coverage test required**: if candidate
count is too small, relax the easiest-to-relax condition (likely
`corr_to_portfolio < 0.50` → `< 0.60`, or `tail_correlation < 0.50` →
`< 0.60`). Do NOT relax `marginal_dd_contribution ≤ 0` or
`tail_correlation < 0.50` without explicit discussion — these are the
semantic core of "real diversifier".

### 4.3 Tactical High-Beta Alpha

Requirements:

- `beta_spy_252d > 1.30` OR `beta_qqq_252d > 1.30`
- `alpha_positive_rate_rolling > 0.55`
- `alpha_t_stat_504d > 1.0`

**Allocation limit**: total tactical bucket weight ≤ 15% of portfolio.

### 4.4 Proxy / Redundant

Requirements:

- `max(r2_spy, r2_qqq) ≥ 0.75`
- `alpha_positive_rate_rolling < 0.55`

**Treatment**: excluded from core holdings by default; kept in pool
for research reference only.

### 4.5 Unscored

Tradable Universe symbols that fail **all** of Alpha Core, Diversifier,
and Tactical bucket criteria. Excluded from portfolio; re-evaluated at
each reconstitution.

### 4.6 Implementation status (R_post_review clarification, 2026-04-21)

The current `scripts/universe_bucket_assign.py` is a **provisional
intrinsic-only implementation** of this Layer 3 specification:

- **Implemented** (symbol-intrinsic criteria, computable from Layer 2
  labels alone):
  - `alpha_positive_rate_rolling`, `alpha_t_stat_504d`,
    `alpha_subperiod_*`, `r2_max`, `beta_spy`, `beta_qqq`,
    `tail_correlation_to_spy`, bucket priority order
- **Deferred** (portfolio-relative criteria — require a
  portfolio-aware second pass; current output uses `PROVISIONAL_*`
  prefix on buckets where these criteria would apply):
  - `cost_adjusted_residual_return` (Alpha Core)
  - `corr_to_portfolio` (Alpha Core + Diversifier)
  - `marginal_drawdown_contribution` (Diversifier)
  - `marginal_sharpe_contribution` (Diversifier)

These deferred criteria will be evaluated at **portfolio construction
stage** (during MFS composite scoring with active holdings). Full
v2.2 bucket finalization therefore requires both the provisional
pass (this tool) and a subsequent portfolio-aware pass (not yet
implemented; to be built in the universe-expanded mining loop as
needed).

This is **documented as a known partial implementation**, not a bug —
portfolio-relative metrics are undefined before a portfolio exists.

---

## 5. Layer 4 — Portfolio Constraints

### 5.1 Single-Name

- `max_single_name_weight ≤ 10%` (tighter cap = risk.yaml value)

### 5.2 Sector

- `max_gics_sector_weight ≤ 25%`
- `max_active_sector_weight_vs_spy ≤ 10%`

### 5.3 Tech Exposure — Three Separate Caps

(**All three must hold**):

| Layer | Cap | Definition |
|---|---|---|
| **Sector-level** | IT + Communication Services total weight ≤ 35% | GICS sector labels |
| **Factor-level** | Weight-avg β_qqq across holdings ≤ 1.10 | Layer 2 β_qqq |
| **Cluster-level** | Total weight on `qqq_high_corr_cluster` ≤ 40% | see §5.3.1 |

#### 5.3.1 `qqq_high_corr_cluster` definition (R23 item 3, renamed)

**Initial proxy definition** (subject to later graph-algorithm
replacement):
- Cluster = all symbols with rolling 252d return correlation to QQQ
  > 0.75
- Updated monthly at reconstitution
- NOT a true graph-theoretic community detection — just a
  correlation-threshold set. **Renamed from "tech correlation cluster"
  to avoid misleading semantics.**

### 5.4 Concentration

- Top-5 holdings weight ≤ 40%
- Top-10 holdings weight ≤ 60%

### 5.5 REIT Cap

- Total REIT weight ≤ 10%

### 5.6 Bucket Caps

- Alpha Core + Diversifiers combined ≥ 70%
- Tactical High-Beta Alpha ≤ 15%
- Proxy / Redundant = 0%

---

## 6. Reconstitution Rules

### 6.1 Cadence

| Layer | Recompute |
|---|---|
| Layer 1 admission (Tradable Universe + Discovery Watchlist) | Monthly (first trading day of month) |
| Layer 2 risk labels | Weekly rolling, snapshot monthly |
| Layer 3 bucket assignment (Tradable only) | Monthly |
| Layer 4 weight caps | Enforced continuously at rebalance |
| Risk overrides | Daily (kill switch, stale data flags) |

### 6.2 Entry/Exit Buffers

| Field | Entry Threshold | Exit Threshold (stricter) |
|---|---|---|
| ADV60 | ≥ $20M | drops below $15M for 20 consecutive days |
| Price | ≥ $5 | drops below $4 for 20 consecutive days |
| Market Cap | ≥ $2B | drops below $1.5B for 20 consecutive days |
| Listing history | ≥ 504d | N/A (monotonic) |
| α_positive_rate (for Alpha Core exit) | ≥ 0.60 | drops below 0.50 for 3 consecutive months |

### 6.3 Immediate Forced Exit

- Corporate event: merger / delisting / bankruptcy filing
- Blacklist addition (human override)
- Data integrity incident (e.g., fraud allegation confirmed by exchange)
- Security type change (reclassified as non-common-stock)

---

## 7. YAML Schema Sketch (for `config/universe.yaml`)

*All threshold values below are default production starting points
and subject to empirical calibration via backtest coverage tests.*

```yaml
universe:
  version: "v2.2"
  # Calibration note: all thresholds are defaults; subject to
  # empirical calibration via backtest coverage tests.

  reconstitution:
    cadence:
      admission:   monthly
      risk_labels: weekly_rolling_monthly_snapshot
      buckets:     monthly
    buffers:
      adv60_enter_usd: 20_000_000    # default; calibration-eligible
      adv60_exit_usd:  15_000_000    # default
      adv60_exit_consecutive_days: 20
      price_enter_usd: 5.0
      price_exit_usd:  4.0
      alpha_exit_consecutive_months: 3

  admission:
    security_types:
      admit: ["us_common_stock"]
      reject: ["etf", "etn", "cef", "bdc", "preferred", "warrant",
               "right", "unit", "leveraged", "inverse", "adr",
               "spac_pre_merger"]
    reit_policy: "admit_with_tag"    # "exclude" | "sub_pool"

    # Tradable vs Discovery membership (R23 item 1 clarified)
    listing_history_days:
      tradable_universe:       504   # hard admission — gets Layer 3/4
      discovery_watchlist_min: 252   # monitoring only, no portfolio weight
      stability_label_full:    1260  # tag only

    price_floor_usd:
      core: 10.0                     # default; calibration-eligible
      extended: 5.0
    liquidity:
      core_adv60_usd:     50_000_000    # default; calibration-eligible
      extended_adv60_usd: 20_000_000
      watch_adv60_usd:    10_000_000
      persistence_days:   60
      persistence_fraction: 0.80
      persistence_day_threshold_mult: 0.5
    market_cap_usd:
      core:     5_000_000_000            # default
      extended: 2_000_000_000
      watch:      500_000_000
    data_completeness:
      max_nan_fraction_252d: 0.10
      max_stale_days: 20

  risk_labels:
    estimation_ready_overlap_days: 252
    estimation_stable_overlap_days: 504
    betas: ["spy_252d","spy_504d","qqq_252d","qqq_504d"]
    alpha_primary_metric: "alpha_positive_rate_rolling"
    alpha_window_days: 63
    alpha_window_step_days: 5
    alpha_subperiod_lengths_days: [252, 504]
    tail_risk:
      max_dd_windows_years: [3, 5]
      downside_return_pct: 0.05
    execution_metadata:
      spread_source: "intraday_bars"   # "hl_proxy"
      volume_windows_minutes: [30]

  priority_buckets:
    # All thresholds below are defaults; subject to backtest
    # coverage calibration before freeze.
    alpha_core:
      alpha_positive_rate_min: 0.60       # default
      alpha_t_stat_min: 1.5               # default
      alpha_subperiod_consistency_required: true
      r2_max: 0.75                        # default
      cost_adjusted_return_min: 0.0
      corr_to_portfolio_max: 0.80
    diversifier:
      beta_spy_max: 0.70                  # default
      beta_qqq_max: 0.70
      corr_to_portfolio_max: 0.50         # default; may relax to 0.60
                                           # if coverage test shows
                                           # candidate count too small
      tail_correlation_max: 0.50          # default; may relax to 0.60
                                           # if coverage too thin
      marginal_dd_contribution_max: 0.0   # DO NOT relax without review
      marginal_sharpe_contribution_min: 0.0
    tactical_high_beta_alpha:
      beta_spy_or_qqq_min: 1.30           # default
      alpha_positive_rate_min: 0.55
      alpha_t_stat_min: 1.0
      max_bucket_weight: 0.15
    proxy_redundant:
      r2_min: 0.75                        # default
      alpha_positive_rate_max: 0.55
      excluded_from_holdings: true

  portfolio_constraints:
    max_single_name_weight: 0.10           # default
    max_gics_sector_weight: 0.25           # default
    max_active_sector_weight_vs_spy: 0.10

    tech_exposure:
      sector_weight_max: 0.35              # default
      weighted_avg_beta_qqq_max: 1.10      # default
      qqq_high_corr_cluster_weight_max: 0.40   # (renamed from
                                                # "correlation_cluster"
                                                # per R23 item 3)
      qqq_high_corr_cluster_definition:
        corr_to_qqq_threshold: 0.75        # initial proxy; may be
                                            # replaced by graph
                                            # community detection later
        corr_window_days: 252

    top_5_weight_max:  0.40                 # default
    top_10_weight_max: 0.60
    max_reit_weight:   0.10

    bucket_weights:
      alpha_core_plus_diversifier_min: 0.70
      tactical_max: 0.15
      proxy_max:    0.00
```

---

## 8. Changes vs v2.1 (R23 item resolutions)

| # | Item | v2.1 | v2.2 |
|---|---|---|---|
| 1 | Tradable Universe vs Discovery | "admission" with Discovery as "WATCH tier" in same set | **Two separate sets**: Tradable Universe (504d+ hard admit, gets Layer 3/4) + Discovery Watchlist (252d, monitored only, no portfolio weight) |
| 2 | Diversifier strictness | 6 simultaneous constraints, no discussion of coverage | Explicit **coverage-test note**: if candidates too few, relax `corr_to_portfolio` or `tail_correlation` to 0.60; DO NOT relax `marginal_dd` or the semantic core |
| 3 | "Tech correlation cluster" | Name misleading (sounds like graph clustering) | **Renamed** to `qqq_high_corr_cluster`; marked as "initial proxy definition" to allow future graph-community-detection replacement |
| 4 | Threshold calibration status | Silent | **Explicit calibration note** in header + YAML comments: defaults subject to backtest calibration; tuning is NOT a spec change |

---

## 9. Open Questions / Deferred

- International ADRs policy (currently REJECT)
- GICS Level 1 vs Level 2 granularity
- `qqq_high_corr_cluster` eventual replacement with graph community
  detection
- IPO waiting period beyond 252d listing floor
- Backtest-time-travel discipline: `alpha_positive_rate` and
  `tail_correlation` must use as-of-date data (implementation concern,
  not spec)

---

*v2.2 finalized 2026-04-21. Ready for user sign-off → implementation.*
