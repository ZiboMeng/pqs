# PQS Universe Expansion Spec v2.1

**Status**: v2.1 — integrated 9 items from user R22 critique of v2
**Date**: 2026-04-21
**Author**: LLM-phase ralph-loop (R22 drafting, user-directed revisions)
**Lineage**: R21 v1 → user critique → R22 v2 → user R22 second critique → **v2.1 (this doc)**

**Purpose**: production-ready specification for PQS universe admission,
risk labeling, portfolio priority buckets, and ongoing reconstitution.
Strictly separates *admission* (objective, forward-looking rules) from
*alpha scoring* (which operates on the admitted pool) to avoid
survivorship / look-ahead bias.

---

## 1. Four-Layer Architecture

```
  ┌────────────────────────────────────────────────────┐
  │  Layer 1: Tradable Universe (hard admission)       │  ← objective only
  ├────────────────────────────────────────────────────┤
  │  Layer 2: Risk Exposure Labels (metadata)          │  ← tagging, not filtering
  ├────────────────────────────────────────────────────┤
  │  Layer 3: Priority Buckets (portfolio construction)│  ← alpha scoring here
  ├────────────────────────────────────────────────────┤
  │  Layer 4: Portfolio Constraints (weight-level)     │  ← real exposure limits
  └────────────────────────────────────────────────────┘
  + Reconstitution rules (cross-layer cadence + buffers)
```

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

**REIT policy (R22 item A)**: REITs are admitted to the equity universe
by default, but tagged `is_reit=true` in Layer 2 so portfolio constructor
can optionally constrain REIT exposure separately (rate-sensitive bucket).

### 2.2 Listing History

| Requirement | Threshold |
|---|---|
| Hard admission | ≥ **504 trading days** (~2 years) |
| Discovery tier (WATCH only) | ≥ 252 trading days |
| Full-stability tag | ≥ 1260 trading days (~5 years) |

### 2.3 Price Floor

| Pool | Median close over last 60d |
|---|---|
| CORE | ≥ $10 |
| EXTENDED | ≥ $5 |
| Reject below | < $5 |

### 2.4 Liquidity — Dollar Volume (R22 item 2, unified definition)

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
| WATCH | $10M |
| Reject | < $10M |

### 2.5 Market Cap

| Pool | Threshold |
|---|---|
| CORE | ≥ $5B |
| EXTENDED | ≥ $2B |
| WATCH | ≥ $500M |
| Reject | < $500M |

### 2.6 Data Completeness

- No all-NaN windows longer than 10 days in last 252d
- Corporate actions (splits, dividends) correctly applied
- No stale quote flags in last 20 days

### 2.7 Non-Blacklisted

Per `config/universe.yaml::blacklist`. Additive to type whitelist (e.g.,
explicit human-flagged exclusions).

---

## 3. Layer 2 — Risk Exposure Labels (metadata only)

These are **computed and stored** for each admitted symbol but **never
used as admission filters**.

### 3.1 Risk-Estimation Readiness (R22 item 1)

Separate from admission. Two flags:

- `risk_estimation_ready`: SPY AND QQQ overlap ≥ 252d (enables beta/α
  estimation with reasonable precision)
- `risk_estimation_stable`: overlap ≥ 504d (multi-regime coverage)

Symbols admitted via Discovery (252d listing) may have
`risk_estimation_ready = false` initially; their Layer 3 bucketing
defers to "unscored" until ready.

### 3.2 Beta and Correlation

Compute (and update monthly):

- `beta_spy_252d`, `beta_spy_504d` (rolling)
- `beta_qqq_252d`, `beta_qqq_504d` (rolling) — **mandatory** for
  tech-exposure control
- `r2_spy_252d`, `r2_qqq_252d`
- `max(r2_spy, r2_qqq)` — "index-proxy score"
- `downside_beta_spy` (conditional on SPY return < -1σ)

### 3.3 Alpha Metrics (R22 item 3, consistency-first)

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

### 3.4 Tail-Risk Metrics (R22 item replacing COVID hardcode)

- `max_dd_rolling_3y`, `max_dd_rolling_5y`
- `worst_5pct_days_cond_return` (tail behavior on market's worst 5% days)
- `tail_correlation_to_spy` (correlation conditional on SPY < -2σ)

### 3.5 Sector / Industry

- `gics_sector`, `gics_industry` (from vendor or hand-mapped)
- `is_reit`, `is_ipo_recent` (< 1 year since IPO)

### 3.6 Execution Cost Metadata (R22 item C, new)

Compute for each symbol:

- `median_spread_bps` (from intraday bars if available, else proxy via
  daily high-low range)
- `spread_pct_of_price`
- `volume_concentration_first_30m` (fraction of daily DV in first 30m)
- `volume_concentration_last_30m` (fraction in last 30m — MOC flow)
- `realized_gap_risk` (avg |overnight_gap| / daily_vol)

### 3.7 Shortability (R22 item B, schema reservation)

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

Each admitted symbol is classified into ONE primary bucket based on
Layer 2 labels. Bucket membership drives allocation weight limits and
selection priority.

### 4.1 Alpha Core

Requirements (**all** must hold):

- `alpha_positive_rate_rolling > 0.60` (primary — consistency)
- `alpha_t_stat_504d > 1.5`
- `alpha_subperiod_consistency = true`
- `max(r2_spy, r2_qqq) < 0.75` (not pure index proxy)
- `cost_adjusted_residual_return > 0`
- `corr_to_portfolio < 0.80` (adds diversification)

### 4.2 Diversifiers (R22 item 4, real value required)

Requirements (**all** must hold):

- `beta_spy_252d < 0.70` AND `beta_qqq_252d < 0.70` (low on BOTH)
- `corr_to_portfolio < 0.50`
- `tail_correlation_to_spy < 0.50` (**truly** diversifies in stress
  — R22 item 4)
- `marginal_drawdown_contribution <= 0` (improves portfolio drawdown
  when added)
- `marginal_sharpe_contribution ≥ 0` (doesn't drag risk-adjusted
  returns)
- `alpha_252d ≥ 0` OR `tail_correlation < 0.30` (may allow zero-alpha
  symbols if exceptional stress diversifier)

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

Symbols admitted via Discovery tier (252d listing < 504d) OR with
`risk_estimation_ready = false`.

**Treatment**: excluded from portfolio; re-evaluated at each
reconstitution.

---

## 5. Layer 4 — Portfolio Constraints (R22 item 5, 3-layer tech control)

### 5.1 Single-Name

- `max_single_name_weight ≤ 10%` (tighter cap = risk.yaml value)

### 5.2 Sector

- `max_gics_sector_weight ≤ 25%`
- `max_active_sector_weight_vs_spy ≤ 10%` (relative to benchmark)

### 5.3 Tech Exposure (3 layers per R22 item 5)

Three separate caps (**all must hold**):

| Layer | Cap | Universe |
|---|---|---|
| **Sector-level** | IT + Communication Services total weight ≤ 35% | GICS sector labels |
| **Factor-level** | Weight-avg β_qqq across holdings ≤ 1.10 | Layer 2 β_qqq |
| **Cluster-level** | Total weight on "tech correlation cluster" ≤ 40% | cluster identified via rolling corr network |

"Tech correlation cluster" = symbols with rolling 252d correlation to
the QQQ > 0.75 (updated monthly).

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

## 6. Reconstitution Rules (R22 item 6, new)

### 6.1 Cadence

| Layer | Recompute |
|---|---|
| Layer 1 admission | Monthly (first trading day of month) |
| Layer 2 risk labels | Weekly rolling, snapshot monthly |
| Layer 3 bucket assignment | Monthly |
| Layer 4 weight caps | Enforced continuously at rebalance |
| Risk overrides | Daily (kill switch, stale data flags) |

### 6.2 Entry/Exit Buffers

Buffers prevent flip-flopping at threshold boundaries.

| Field | Entry Threshold | Exit Threshold (stricter) |
|---|---|---|
| ADV60 | ≥ $20M | drops below $15M for 20 consecutive days |
| Price | ≥ $5 | drops below $4 for 20 consecutive days |
| Market Cap | ≥ $2B | drops below $1.5B for 20 consecutive days |
| Listing history | ≥ 504d | N/A (monotonic) |
| α_positive_rate (for Alpha Core exit) | ≥ 0.60 | drops below 0.50 for 3 consecutive months |

Buffer rationale: entry is strict to avoid premature admission; exit
is lenient to avoid whipsawing on transient drops.

### 6.3 Immediate Forced Exit

Some conditions trigger immediate removal (override buffer):

- Corporate event: merger / delisting / bankruptcy filing
- Blacklist addition (human override)
- Data integrity incident (e.g., fraud allegation confirmed by exchange)
- Security type change (reclassified as non-common-stock)

---

## 7. YAML Schema Sketch (for `config/universe.yaml`)

```yaml
universe:
  version: "v2.1"
  reconstitution:
    cadence:
      admission:   monthly
      risk_labels: weekly_rolling_monthly_snapshot
      buckets:     monthly
    buffers:
      adv60_enter_usd: 20_000_000
      adv60_exit_usd:  15_000_000
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
    reit_policy: "admit_with_tag"  # or "exclude" or "sub_pool"
    listing_history_days:
      hard_admit:   504
      discovery:    252
      stability_label: 1260
    price_floor_usd:
      core:     10.0
      extended:  5.0
    liquidity:
      core_adv60_usd:     50_000_000
      extended_adv60_usd: 20_000_000
      watch_adv60_usd:    10_000_000
      persistence_days:   60
      persistence_fraction: 0.80
      persistence_day_threshold_mult: 0.5   # 0.5 × main threshold for persistence
    market_cap_usd:
      core:     5_000_000_000
      extended: 2_000_000_000
      watch:      500_000_000
    data_completeness:
      max_nan_fraction_252d: 0.10
      max_stale_days: 20

  risk_labels:
    estimation_ready_overlap_days: 252
    estimation_stable_overlap_days: 504
    betas: ["spy_252d", "spy_504d", "qqq_252d", "qqq_504d"]
    alpha_primary_metric: "alpha_positive_rate_rolling"
    alpha_window_days: 63
    alpha_window_step_days: 5
    alpha_subperiod_lengths_days: [252, 504]
    tail_risk:
      max_dd_windows_years: [3, 5]
      downside_return_pct: 0.05
    execution_metadata:
      spread_source: "intraday_bars"    # or "hl_proxy"
      volume_windows_minutes: [30]

  priority_buckets:
    alpha_core:
      alpha_positive_rate_min: 0.60
      alpha_t_stat_min: 1.5
      alpha_subperiod_consistency_required: true
      r2_max: 0.75
      cost_adjusted_return_min: 0.0
      corr_to_portfolio_max: 0.80
    diversifier:
      beta_spy_max: 0.70
      beta_qqq_max: 0.70
      corr_to_portfolio_max: 0.50
      tail_correlation_max: 0.50
      marginal_dd_contribution_max: 0.0
      marginal_sharpe_contribution_min: 0.0
    tactical_high_beta_alpha:
      beta_spy_or_qqq_min: 1.30
      alpha_positive_rate_min: 0.55
      alpha_t_stat_min: 1.0
      max_bucket_weight: 0.15
    proxy_redundant:
      r2_min: 0.75
      alpha_positive_rate_max: 0.55
      excluded_from_holdings: true

  portfolio_constraints:
    max_single_name_weight: 0.10
    max_gics_sector_weight: 0.25
    max_active_sector_weight_vs_spy: 0.10
    tech_exposure:
      sector_weight_max:         0.35   # IT + Comm Services
      weighted_avg_beta_qqq_max: 1.10
      correlation_cluster_weight_max: 0.40
      cluster_definition:
        corr_to_qqq_threshold: 0.75
        corr_window_days: 252
    top_5_weight_max:  0.40
    top_10_weight_max: 0.60
    max_reit_weight:   0.10
    bucket_weights:
      alpha_core_plus_diversifier_min: 0.70
      tactical_max: 0.15
      proxy_max:    0.00
```

---

## 8. Changes vs v2 (R22 item resolutions)

| # | Item | v2 | v2.1 |
|---|---|---|---|
| 1 | SPY/QQQ overlap location | Data completeness | Separate `risk_estimation_ready` + `risk_estimation_stable` flags in Layer 2 |
| 2 | Liquidity persistence | "avg ADV + persist 80%" (ambiguous) | median ADV60 + ADV20 + persist on DV ≥ 0.5×threshold |
| 3 | Alpha Core selection | "rolling α > 0 + consistency" | Consistency FIRST (`positive_rate`), point alpha secondary |
| 4 | Diversifier definition | low β + low corr + downside ok | Added `tail_correlation`, `marginal_dd_contribution`, `marginal_sharpe_contribution` checks |
| 5 | Tech exposure control | cluster by "QQQ β>1.1 OR GICS IT/Comm" | Three separate caps: sector + factor + correlation cluster |
| 6 | Reconstitution | not addressed | Full §6 with monthly cadence + entry/exit buffers + immediate forced exit |
| A | REIT policy | silent | explicit admit-with-tag; Layer 4 cap 10% |
| B | Shortability | silent | Schema fields reserved in Layer 2 |
| C | Execution cost | silent | Layer 2 metadata fields: spread, concentration, gap risk |

---

## 9. Open Questions / Deferred

- International ADRs policy: currently REJECT, but should revisit if
  international diversification becomes strategic priority
- Sector boundaries: GICS Level 1 vs Level 2 (more granular sub-sector
  control possible)
- Cluster definition stability: QQQ corr > 0.75 is static threshold;
  could use community-detection algorithm on correlation graph
- IPO waiting period: currently 6 months for SPAC, 0 for regular IPO
  (beyond 252d listing floor). May want specific IPO buffer.
- Backtest-time-travel discipline: when recomputing `alpha_positive_rate`
  or `tail_correlation`, must use only data available at the evaluation
  date to avoid look-ahead. Enforcement in code (not spec).

---

*v2.1 finalized 2026-04-21. Ready for user sign-off → implementation.*
