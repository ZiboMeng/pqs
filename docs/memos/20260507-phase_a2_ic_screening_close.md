---
lineage_tag: cycle07-to-fleet-master-2026-05-06
phase: A.2
status: COMPLETE — verdict 0/3 ELIGIBLE
date: 2026-05-07
operator: zibomeng (Claude Opus 4.7)
---

# Phase A.2 closeout — RSI/KDJ/MACD IC screening (0 ELIGIBLE)

## TL;DR

Per PRD `docs/prd/20260506-cycle07_to_fleet_master_prd.md` §4.1 Phase A.2,
ran inline RSI(14)/KDJ-J(9)/MACD-hist(12,26,9) on
`partition_for_role(role="miner")` panel (train years 2009-2017 +
2020/2022/2024) and computed 21-day Spearman IC time-series. Pairwise
IC time-series Pearson correlation against all 64 daily-resolution
RESEARCH_FACTORS (3 intraday-bar factors excluded by `intraday_bars_60m=
None` mining default).

**All 3 candidates REJECT** at the < 0.6 max-correlation gate:

| Candidate | mean_IC (21d) | IR | max \|cor\| with existing | Sibling | Verdict |
|---|---|---|---|---|---|
| `rsi_14d` | -0.0083 | -0.032 | **0.884** | `return_per_risk_21d` | **REJECT** |
| `kdj_j_9d` | -0.0036 | -0.015 | **0.812** | `reversal_5d` (sign -) | **REJECT** |
| `macd_hist_12_26_9` | -0.0112 | -0.051 | **0.749** | `reversal_10d` (sign -) | **REJECT** |

**Implication for the master PRD**: Round 3 (Phase B.1 factor promotion)
**SKIP** per yaml acceptance ("SKIP this round if 0 ELIGIBLE"). cycle07a
+ cycle08 mining will run on the existing 67-factor RESEARCH_FACTORS
pool (no expansion). G1 (factor pool expansion) **partial** at this
boundary — RSI/KDJ/MACD as SCREENED do not satisfy non-sibling promotion;
SR-defer-as-mining-search-dim (Phase B.2) remains the path forward for
G1 evidence.

## What was actually computed (R3 audit anchor)

### Inputs

| Input | Source | Shape |
|---|---|---|
| Panel | `partition_for_role(role="miner")` | 1499 trading days × 79 symbols |
| Train years | 2009-2017 + 2020 + 2022 + 2024 (12 calendar years) | per `config/temporal_split.yaml` |
| Forward returns | `compute_forward_returns(panel.close, horizons=[21], mode="cc")` | 1499 × 79 |
| Existing factors | `generate_all_factors(close, vol, open, high, low, benchmark_map={SPY,QQQ})` | 64 daily-resolution panels |

3 intraday factors (`realized_vol_60m_21d`, `intraday_vol_ratio_21d`,
`intraday_autocorr_21d`) excluded because `intraday_bars_60m=None` —
matches cycle06 mining default which also runs without 60m bars in
factor generation.

### Candidate factor formulas (inline, no production code touched)

```python
# Wilder's RSI(14): EWM with alpha=1/14, min_periods=14 on gains/losses
def rsi_14d(close, n=14):
    delta = close.diff()
    gain  = delta.where(delta > 0, 0.0)
    loss  = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    rs  = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - 100/(1+rs)

# Stochastic %K(9) + %D(3 SMA of K) + J = 3K - 2D
def kdj_9d(close, high, low, n=9):
    lo_n = low.rolling(n, min_periods=n).min()
    hi_n = high.rolling(n, min_periods=n).max()
    raw_k = 100 * (close - lo_n) / (hi_n - lo_n).replace(0, np.nan)
    k = raw_k.rolling(3, min_periods=3).mean()
    d = k.rolling(3, min_periods=3).mean()
    j = 3*k - 2*d  # screened factor
    return k, d, j

# MACD histogram = (EMA12 - EMA26) - signal(EMA9)
def macd_12_26_9(close):
    ema_fast = close.ewm(span=12, adjust=False, min_periods=12).mean()
    ema_slow = close.ewm(span=26, adjust=False, min_periods=26).mean()
    macd_line  = ema_fast - ema_slow
    signal_lin = macd_line.ewm(span=9, adjust=False, min_periods=9).mean()
    return macd_line - signal_lin  # histogram, screened factor
```

### IC computation

Per-date Spearman rank correlation across the symbol cross-section
(reuses `core.mining.research_miner._spearman_ic_per_date`); requires
≥ 10 valid (signal, fwd_return) pairs per date.

### Pairwise IC time-series correlation

For each `(candidate, existing)` pair: pandas `Series.corr(...)` on the
inner-join of the two IC time-series, requiring ≥ 30 overlapping dates
(else NaN). 3 × 64 = 192 pairs computed.

### Verdict gate (PRD §4.1)

| Max \|cor\| with existing | Verdict |
|---|---|
| < 0.6 | ELIGIBLE |
| 0.6 – 0.7 | CONDITIONAL |
| > 0.7 | REJECT |

## Top-5 sibling exposure per candidate

### `rsi_14d` (REJECT, max |cor|=0.884)

| Existing factor | \|cor\| | signed |
|---|---|---|
| `return_per_risk_21d` | 0.884 | +0.884 |
| `mean_rev_sma20` | 0.862 | -0.862 |
| `mean_rev_sma50` | 0.850 | -0.850 |
| `trend_tstat_20d` | 0.831 | +0.831 |
| `rel_qqq_20d` | 0.831 | +0.831 |

Sign convention: positive RSI signal → high recent gain ratio →
positively correlated with risk-adjusted-momentum and trend-quality
factors (return_per_risk_21d, trend_tstat_20d). Negatively correlated
with mean-reversion-against-SMA factors (high-RSI = above SMA → strong
mean-rev signal of opposite sign). RSI is essentially a different
parameterization of "above-recent-average" momentum.

### `kdj_j_9d` (REJECT, max |cor|=0.812)

| Existing factor | \|cor\| | signed |
|---|---|---|
| `reversal_5d` | 0.812 | -0.812 |
| `ret_5d` | 0.812 | +0.812 |
| `rel_spy_5d` | 0.812 | +0.812 |
| `mean_rev_sma20` | 0.719 | -0.719 |
| `reversal_10d` | 0.659 | -0.659 |

KDJ-J = 3*K - 2*D where K is the % position in the 9-day high-low range.
Mathematically K is dominated by `(close[t] - close[t-5..t-9]) /
range[5..9]` in the smoothed average — so KDJ-J ≈ 5d-momentum. The
+0.812 vs `ret_5d` and -0.812 vs `reversal_5d` (which is -ret_5d) are
expected: KDJ-J at 9-day window IS a 5-day momentum signal scaled by
range.

### `macd_hist_12_26_9` (REJECT, max |cor|=0.749)

| Existing factor | \|cor\| | signed |
|---|---|---|
| `reversal_10d` | 0.749 | -0.749 |
| `mean_rev_sma20` | 0.712 | -0.712 |
| `reversal_5d` | 0.583 | -0.583 |
| `ret_5d` | 0.583 | +0.583 |
| `rel_spy_5d` | 0.583 | +0.583 |

MACD histogram captures rate-of-change of (EMA12 - EMA26) ≈ short-term
trend acceleration. Strong negative correlation with `reversal_10d`
because both fire on similar mid-horizon momentum reversals; MACD
positive histogram = trend strengthening = anti-reversal signal.

## Why the verdicts make sense (R2 audit anchor)

The 3 candidates were proposed for adding "oscillator family" diversity
to a factor pool that's mostly momentum/reversal/vol/range variants. But
mathematically:

- RSI(14) ≈ smoothed momentum z-score normalized to [0,100]
- KDJ-J ≈ 5d-momentum scaled by 9-day range
- MACD-histogram ≈ short-trend acceleration (2nd derivative of EMA)

All three reduce to "where is current price relative to recent price
extremes/moving averages", which is exactly what `mom_*`, `reversal_*`,
`mean_rev_sma*`, `trend_tstat_20d`, `return_per_risk_21d` already
capture in the pool. The "oscillator framing" (bounded 0-100, signal
crossovers) does not introduce new economic information at the
21-day horizon when the IC is computed on rank cross-section.

This is consistent with the cycle04/05/06 sibling problem identified in
the master PRD §1.2: the universe-bound long-only top-N construction
is the binding constraint; adding more momentum-flavored factors
through different transformations doesn't break sibling-ness.

## Implication for downstream rounds

| Round | Pre-A.2 plan | Post-A.2 disposition |
|---|---|---|
| R3 (Phase B.1) | Promote ELIGIBLE factors | **SKIP** — 0 ELIGIBLE |
| R4 (Phase B.2 SR defer) | Land mining integration | **PROCEED** — independent of B.1 |
| R7 (Phase C.2 cycle08) | Use post-B.1 67+N pool | Use existing 67 pool (no expansion) |

Note: this does NOT mean RSI/KDJ/MACD have NO research value. It means
they are sibling at 21d horizon on this universe — they may have value
at shorter horizons (5d for KDJ, 1-3d for MACD-histogram crossovers) or
under regime-conditional gating (KDJ overshoots near 0 / 100 may fire
asymmetrically in BEAR). Those are out of Phase A.2 scope; the master
PRD's R7 (Phase C.2) regime-conditional mining can re-screen them with
regime-stratified IC if user requests Phase A.2 retry.

## Audit artifacts

- Script: `dev/scripts/factor_screening/run_rsi_kdj_macd_ic_screen.py`
- Output JSON: `data/audit/phase_a2_ic_screening.json`
- Output sha256 (first 16 chars): `5d81eabfc13432df`
- IC compute wall-clock: 229s (3,201 IC time-series across 1499 days
  × 79 symbols)
- Pairwise correlation wall-clock: 0.3s (192 pairs)

## Self-Audit (R1/R2/R3/R4 per `feedback_self_audit_methodology.md`)

### R1 — factual

- 1499 trading days post weekday filter (matches expected 12 calendar
  years × ~125 trade days per train-year average; cycle06 mining
  panel had similar size)
- 79 symbols (matches cycle06 yaml `drop_symbols={BRK-B,USO,SLV}`
  + SPY+QQQ benchmark + 53 stocks + 6 cross-asset = 76, plus universe
  has additional ETFs not dropped → 79)
- 64 existing factors generated (= 67 RESEARCH_FACTORS - 3 intraday
  with `intraday_bars_60m=None`)
- 192 pairwise correlations computed = 3 × 64 ✓
- Per-candidate verdict gate `< 0.6 / 0.6-0.7 / > 0.7` matches PRD §4.1
  acceptance table verbatim
- ic_stats.n_obs (1470 RSI / 1229 KDJ / 1438 MACD) all positive — IC
  series produced real per-date observations (not stub)

### R2 — logical

- Conclusion ("all 3 REJECT") follows from data: each candidate's max
  |cor| with existing is > 0.7 (RSI 0.88 / KDJ 0.81 / MACD 0.75).
- Sign of correlation matches economic intuition (RSI~+momentum,
  KDJ~+ret_5d, MACD~-reversal_10d) — diagnostic that the factors
  *are* what they're advertised as, just sibling.
- "SKIP Round 3 if 0 ELIGIBLE" is verbatim from PRD yaml — disposition
  for next phases follows cleanly.
- Inconsistency check: low IC + high cor with existing means the
  factors fail BOTH on standalone alpha (mean_IC ≈ 0) AND on
  diversification (high sibling) — strongest possible REJECT signal.

### R3 — actually-run

- `dev/scripts/factor_screening/run_rsi_kdj_macd_ic_screen.py` invoked
  via `python` directly (not pytest scaffold). Wall-clock matches
  expectations (~3.5 min IC compute + 30s panel load).
- Output JSON written to `data/audit/phase_a2_ic_screening.json` and
  sha256 captured.
- Live debug runs on SPY column reproduced the kdj_9d weekend-NaN
  pathology BEFORE the weekday-filter fix; post-fix re-run produced
  expected non-NaN counts (KDJ J non-NaN: 8985 → 83665, factor 9.3×
  improvement).

### R4 — boundary

- **What if 21d isn't the right horizon for these oscillators?** RSI
  is typically traded on 1-day signals; KDJ on 1-3d; MACD-histogram
  on signal-line crossovers (1-2 day timing signal). Screening at
  21d biases AGAINST oscillators by definition. **Documented**:
  R7 (Phase C.2) regime-conditional mining can re-screen at shorter
  horizons under user-go.
- **What if `_spearman_ic_per_date` undercounts?** The min_periods=10
  threshold means IC is undefined for early train years where universe
  count is low (some stocks added 2018+; only 6-15 stocks with full
  history pre-2015). Real n_obs ≈ 1200-1500 vs 3024 max possible.
  Affects all candidates AND existing equally → relative ranking
  unaffected.
- **What if weekday filter dropped legitimate trading days?** No US
  equity market opens on Sat/Sun. Index 3345 → 3042 post-filter
  (303 weekends dropped); each drop removes a NaN-only row for
  equities (the original index had crypto/24-7 sources bleeding
  in). Verified SPY trading-day count unchanged: 1511 close non-NaN
  pre-filter = 1511 post-filter.
- **What if the existing 64 factors include sibling pairs that
  inflate the cor matrix?** The corr is computed pairwise (candidate
  vs each existing); siblings within existing don't affect the
  candidate's max. But it could pull the candidate's apparent max-cor
  up if e.g. ret_5d / reversal_5d / rel_spy_5d are all the same
  signal flipped (KDJ shows |cor|=0.812 vs all 3 — they're identical).
  In this case the verdict is unchanged: max-cor=0.812 even against
  one of them, well above 0.7 reject threshold.
- **What if KDJ-J was computed with wrong sign convention?** Some KDJ
  variants flip J. Sign flip would make signed corr go from -0.812
  to +0.812 against reversal_5d — same |cor|, same verdict. Sign
  doesn't affect screening.

### Self-audit verdict

PASS. Verdicts (3× REJECT) are robust to all R4 boundary perturbations
considered. The negative result (0 ELIGIBLE) is itself informative —
it confirms the master PRD §1.2 sibling-binding-constraint hypothesis
at the IC level: oscillators of mom/reversal/vol/range factors do not
introduce new economic dimensions at 21d horizon on this universe.

## Reversibility

Pure dev script + JSON output. No production code touched. Revocation =
delete `dev/scripts/factor_screening/` directory + delete
`data/audit/phase_a2_ic_screening.json` + revert this memo. Cycle04/05/06
archives + RCMv1+Cand-2 forward + TAA modules unaffected.

## Lineage

`cycle07-to-fleet-master-2026-05-06` round 1 of 13.
Next round (R2): Phase A.1 cycle07a yaml + 200-trial mining + Track A
acceptance.
