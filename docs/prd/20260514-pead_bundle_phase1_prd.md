# PEAD Bundle Phase 1 — Dual-Track Free-Path PRD

**Lineage**: `pead-bundle-2026-05-14`
**Date**: 2026-05-14
**Status**: design locked, implementation kicking off
**Roadmap reference**: cycle11-to-fleet roadmap v2 Q2 LOCK (T1c PEAD+FOMC bundle)
**Prior context**:
- T1c FOMC drift confirmed dead post-2015 (`docs/memos/20260513-fomc_drift_smoke.md`)
- cycle11 informative null on parametric breakouts (`docs/audit/20260514-cycle11_smoke_execution_artifact.md`)
- Operator hypothesis: parametric technical strategies hit TC ceiling. Real next-increment must be exogenous event signals (earnings dates from SEC EDGAR, 0 timing parameter).

## §1 Motivation

PEAD (Post-Earnings Announcement Drift) is one of the most-replicated
anomalies in equity research (Bernard-Thomas 1989 → 30+ years OOS).
Standard finding:

> Stocks with positive earnings surprise continue to drift up for ~60
> trading days post-announcement; magnitude ~2-5% annualized excess
> return; statistically significant but slowly arb'd as institutional
> participation grew (Bernard-Thomas 1989, Chordia-Goyal-Jegadeesh-
> Shivakumar 2009, Hirshleifer-Lim-Teoh 2009).

For PQS this is structurally different from cycle04-11 mining:
- **Trigger is exogenous** (SEC filing date, 0 lookback/hold parameter
  in the trigger itself)
- **Signal magnitude is per-event** (not continuous panel)
- **Capacity binding** (each event is one stock, naturally diversifies)

## §2 Constraints (carried forward, NEVER violate)

- long-only, no-margin, no-short
- 30bp baseline cost (cycle11+ standard per `docs/memos/20260514-cost_gate_revision_6x.md`)
- open_df pass-through MANDATORY (cycle11 lesson)
- weekend-row + cross-symbol date integrity smoke before mining
  (per `[[feedback_bar_level_data_integrity_smoke]]`)
- Sealed 2026 panel NEVER read this round
- Universe: 52 stocks with EDGAR ingest (config/universe.yaml ∩ EDGAR cache)

## §3 Two paths in scope

### Path 1 — SUE-based PEAD (academic standard)

```
expected_EPS(Q) = EPS(Q-4)                                    # naive same-quarter-LY
residual(Q)    = actual_EPS(Q) - expected_EPS(Q)
SUE(Q)         = residual(Q) / std(residual_{Q-1 .. Q-8})     # 8-q rolling std

Signal day T   = first 10-Q / 10-K filed date for fiscal period Q
Entry  = SUE(Q) > +SUE_threshold (long-only)
Hold   = max_hold business days post-T
Exit   = bar T + max_hold (or earlier exit signal)
```

**Hyperparameter grid** (Path 1 smoke):
- `SUE_threshold` ∈ {+1.0σ, +1.5σ, +2.0σ}
- `max_hold` ∈ {21, 42, 60} BD
- `top_n` ∈ {5, 10, 20}
- 3 × 3 × 3 = 27 cells; reduce to 9 representative cells for smoke

### Path 2 — Price-jump anchored PEAD (Chan-Jegadeesh-Lakonishok 1996)

```
Signal day T  = first 10-Q / 10-K filed date for fiscal period Q
AR(T)        = ret_stock(T) - ret_SPY(T)                      # abnormal return
Entry        = AR(T) > +AR_threshold
Hold         = max_hold BD post-T
```

**Hyperparameter grid** (Path 2 smoke):
- `AR_threshold` ∈ {+3%, +5%, +7%}
- `max_hold` ∈ {21, 42, 60} BD
- `top_n` ∈ {5, 10, 20}
- 9 representative cells

### Why both paths (user explicit-go 2026-05-14 = C)

- Path 1 uses fundamentals (EPS surprise), captures slow-information-
  diffusion mechanism. Predicted weakness: SUE with naive forecast
  misses 30%+ of "true" surprise (analyst-anchored).
- Path 2 uses price reaction as surprise proxy. Predicted weakness:
  AR contains confounds (guidance, macro reaction, sector co-move on
  the same day). Tradeoff is sharper trigger.
- Side-by-side comparison disambiguates: if both win → robust PEAD;
  if only Path 1 → fundamental-anchored real; if only Path 2 → price-
  momentum echo (not "true" PEAD).

## §4 Backtest design

### 4.1 Time period

- Train: 2009-2017 + 2020/2022/2024 (per `config/temporal_split.yaml`
  alternating_regime_holdout_v1)
- Validation: 2018/2019/2021/2023/2025 (held out, Track A acceptance
  gate is per-year)
- 2026 sealed window NOT touched

### 4.2 Execution

- `core.backtest.signal_driven_runner.SignalDrivenBacktest` (K1 wrapper)
- `execution_delay_bars=1` (T+1 open fill)
- `open_df` MUST be passed
- `cost_model=CostModel(2bp commission + 30bp slippage)` (cycle11+ baseline)

### 4.3 Universe

- Start from `config/universe.yaml::seed_pool` minus ETFs minus
  inverse-3x ETFs (`SPY`, `QQQ`, `GLD`, `TQQQ`, `SOXL`, `SQQQ`, `SOXS`)
- Intersect with EDGAR cache coverage (52/59 stocks have companyfacts JSON)
- Final universe size: ~50 (verified at smoke time)

### 4.4 Signal mechanics (K1-compatible)

- `entry_signals[t, sym] = True` iff sym had filed-date T on day t AND
  threshold passed
- `exit_signals[t, sym] = entry_signals[t - max_hold, sym]` (shift max_hold)
- Default `top_n` rank-by-magnitude (SUE or AR) when more entries than
  top_n on same day
- TTL=0 (immediate confirm; no ARMED → CONFIRMED state since signal
  triggers on close)

## §5 Track A acceptance (post-smoke)

If smoke top trial Sharpe > SPY Sharpe (≈ 0.76 baseline 2017-2025):
- Run `core.research.temporal_split_acceptance.run_split_acceptance`
- 17 gates including per-validation-year MaxDD ≤ 20%, vs SPY > 0
  per year, 2x cost robustness, stress slices (covid_flash,
  rate_hike_2022), concentration ceilings (top1 ≤ 40%, top3 ≤ 70%)
- NAV correlation vs anchors (T1b ConfirmationPattern, alt-A intraday
  reversal Phase 3 backtest, Trial 9 v2 forward NAV):
  - raw NAV corr < 0.85 → forward-init candidate
  - 0.85 ≤ raw < 0.95 → evidence-only memo
  - raw ≥ 0.95 → sibling-by-NAV, do not initialize

## §6 Stop rules

Pre-committed before any trial runs (per cycle04 close memo discipline):

- **R1 smoke informative null**: if Path 1 best + Path 2 best both fail
  to beat SPY Sharpe at 30bp, close PEAD bundle Phase 1; document as
  "PEAD does not survive 30bp realistic cost in 50-stock US large-cap
  universe over 2017-2025 sample"; pivot per user-go
- **R2 partial win**: if exactly one path beats SPY, run Track A
  acceptance only on the winning path's best trial
- **R3 sibling-by-NAV**: if Track A passes but raw NAV corr ≥ 0.85
  vs T1b or alt-A or Trial 9 v2, log as evidence-only (not fleet)
- **R4 full pass**: ≥ 1 path passes Track A AND raw NAV corr < 0.85
  AND 2x cost robustness → forward-init candidate

## §7 Known limitations (documented up front, not hidden)

### 7.1 filed_date ≠ earnings announcement date

10-Q filing typically 0-14 days AFTER the actual earnings call (which
is 8-K). EDGAR companyfacts only ships 10-Q/10-K data, not 8-K timing.

**Impact**: signal day T is ~7-10 days later than the academic
PEAD anchor day. The "first 21 trading days post-announcement" portion
of the drift (which is the strongest in literature) may be partially
or fully missed.

**Mitigation**: Document. If Path 1/Path 2 fail under this
constraint, the true PEAD signal may be stronger than what we measure
— this is the relevant Phase 2 follow-up (consider Polygon / IEX 8-K
data feed if PEAD shows signal).

### 7.2 Restatement filings inflate filed_date count

EDGAR returns BOTH initial 10-Q + 10-Q/A restatement filings.
Restatements typically file ~1 year later (gap 398d vs 34d for
initial). **Must groupby (fy, fp, form) and take MIN(filed_date)**;
verified empirically AAPL shows clear 34d/398d bimodal split.

### 7.3 Universe restricted to 52 stocks

Smaller than cycle04-11's 78-stock universe. Limits diversification.
Earnings dates cluster (most US large caps report in same 3-4 week
window per quarter) — capacity check at smoke time (verify daily
n_entries averaged over time).

### 7.4 EPS-source ambiguity

EDGAR has multiple us-gaap tags for EPS (`EarningsPerShareBasic`,
`EarningsPerShareDiluted`, `IncomeLossFromContinuingOperationsPerBasicShare`).
Path 1 will use `EarningsPerShareDiluted` (standard for sell-side
analyst comparisons). 8-q rolling-std requires 8 prior quarters of
non-NaN EPS — verify coverage at smoke time.

## §8 Files / Deliverables

- `core/research/pead/__init__.py`
- `core/research/pead/earnings_dates.py` — first-filed extractor
- `core/research/pead/sue_calculator.py` — Path 1
- `core/research/pead/price_jump_signal.py` — Path 2
- `core/research/pead/pead_universe.py` — EDGAR ∩ universe filter
- `tests/unit/research/pead/test_*.py` — ~40 tests total
- `dev/scripts/pead/run_path1_sue_smoke.py`
- `dev/scripts/pead/run_path2_pricejump_smoke.py`
- `dev/scripts/pead/run_pead_track_a_acceptance.py` (post-smoke)
- `data/audit/pead_path1_sue_smoke.json`
- `data/audit/pead_path2_pricejump_smoke.json`
- `docs/memos/20260514-pead_bundle_phase1_close.md` — closeout

## §9 Out of scope this round

- Polygon/IEX 8-K real-announce-date feed (Phase 2 if Phase 1 shows signal)
- Analyst consensus estimates / IBES (paid data; gated on Trial 9 v2 TD60 GREEN)
- Cross-asset earnings events (FRED FOMC dates) — T1c FOMC bundle already dead
- Macro events (CPI / NFP / PMI surprises) — out of scope for earnings-only PEAD
- ML over PEAD-magnitude × cross-sectional features — Phase 2 if Phase 1 wins
- Forward init runner integration — only if R4 (full pass) fires

## §10 Acceptance / Done definition

**Phase 1 done** =
- All 4 module files shipped, ≥ 40 unit tests pass
- Both smoke scripts produce JSON output with 9 trials each
- Stop rule R1-R4 fired and documented
- Closeout memo + commit + push complete
- CLAUDE.md TODO updated
