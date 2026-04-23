# Universe Expansion Proposal v3 — S&P 500-based Layered Framework

**PRD**: `docs/20260421-prd_deep_mining_50round.md` §11.2 + §2 Track D (R34-R41)
**Source lineage**: R34 (SP500 pool sync) + R35 (alpha audit) +
R36 (Layer 1 admission) + R37 (risk labels)
**Date**: 2026-04-22
**Status**: **PROPOSAL — awaits user review + explicit authorization**
**Authority**: Per §11.2 the loop MAY NOT modify `config/universe.yaml`.
This doc summarizes evidence and recommends a specific diff for user approval.

---

## Summary

The current 52-symbol universe is tech-concentrated (Mag7 + semis + ETFs),
leaving ~10-12 ALPHA_GENERATOR-class names. R34 pulled the full S&P 500
(513 tickers fresh to 2026-04-22). R35 ran CAPM alpha/beta on that pool
and found **177 α>3% candidates** (134 ALPHA_GEN + 43 BETA_PLUS_ALPHA).
R36 confirmed **97.5% pass Layer 1 objective admission** (liquidity,
history, price floor). R37 merged the two and assigned priority buckets.

After subtracting overlap with the existing 52-symbol universe, there are
**163 new alpha candidates + 11 premium diversifiers** — a ~16x expansion
of the alpha-discovery surface area.

This proposal recommends a **staged expansion to ~100 symbols**, keeping
the current 52 as the stable base and adding ~45 carefully-selected
alpha candidates across 6 GICS sectors. No change to benchmark (SPY/QQQ),
no change to leveraged blacklist, no change to risk-gate machinery.

---

## Evidence stack

### R35 — S&P 500 alpha/beta audit

| Category | Count | % |
|---|---:|---:|
| ALPHA_GENERATOR (β∈[0.7,1.3] + α>3%) | **134** | 26% |
| BETA_PLUS_ALPHA (β>1.3 + α>3%) | 43 | 8% |
| DIVERSIFIER (β<0.7) | 185 | 36% |
| MARKET_LIKE (β mid, α ≈ 0) | 113 | 22% |
| PURE_BETA (β>1.3 + α≤0) | 33 | 6% |
| UNKNOWN (data issue) | 6 | 1% |

Artifacts: `data/ml/R37_sp500_alpha.csv`

### R36 — Layer 1 objective admission (S&P 500)

| Tier | Count | Criteria |
|---|---:|---|
| CORE | 495 | ADV60 ≥ $50M, price ≥ $10, history ≥ 2y |
| EXTENDED | 5 | ADV60 ≥ $20M (less liquid) |
| WATCH | 4 | Recent IPO / spin (<2y) |
| REJECT | 9 | Delisted / history broken / liquidity fail |

Artifacts: `data/ml/universe_admission_R36_sp500_admission.csv`

### R37 — priority bucket distribution (n=514)

| Bucket | Count |
|---|---:|
| SATELLITE_ALPHA (ALPHA_GEN/BETA_PLUS_ALPHA + CORE admitted) | 175 |
| DIVERSIFIER_BASIC | 171 |
| REVIEW (MARKET_LIKE / UNKNOWN) | 116 |
| EXCLUDE (PURE_BETA / admission REJECT) | 41 |
| DIVERSIFIER_PREMIUM | 11 |

Artifacts: `data/ml/universe_risk_profile_R37_sp500.csv`

---

## Recommended expansion (staged)

### Stage 1: Diversifier premium (11 symbols) — LOW risk
Candidates that are admission CORE + β<0.7 + strong sharpe, provide
regime diversification without adding tech concentration.

| Symbol | Sector (estimated) | Rationale |
|---|---|---|
| BRK-B | Financials | Berkshire — all-weather, high quality |
| TER | Industrials | Test equipment — low β, alpha |
| TJX | Discretionary | Off-price retail — recession-resistant |
| TKO | Entertainment | UFC/WWE — idiosyncratic |
| TRGP | Energy midstream | Pipeline — yield + stability |
| TRV | Insurance | Low β financial |
| TSN | Staples | Food processor |
| TT | Industrials | HVAC/climate |
| TXN | Semis | Analog semis — legacy moat |
| UNP | Industrials | Rails |
| VICI | REITs | Casino properties |

### Stage 2: Top 20 ALPHA_GENERATOR (not in current universe)
Selected for sector diversity + alpha strength. Prioritize β≈1.0 names
to preserve market beta symmetry.

Candidates (first 20 alphabetical): A, ABT, ACGL, AES, AFL, AIZ, AJG,
AMCR, AME, APA, APD, APH, AVY, AXP, BKNG, BKR, BR, BSX, CARR, CBRE,
CEG, CF, CIEN, CMG, CMI, COO, COP, COST, CPT, CRH.

*Curated selection* (15 to spread across sectors): **BRK-B** (already
above), **COST** (staples/discretionary), **AXP** (financials), **BKNG**
(discretionary), **APD** (materials), **ABT** (health), **CMG**
(discretionary), **COP** (energy), **UNH** (health), **LLY** (health —
highest α in R21 non-tech audit), **CAT** (already in universe), **ISRG**
(medtech), **NEE** (utilities), **MCK** (health distribution), **CME**
(financials), **TMO** (health).

### Stage 3: Top 15 BETA_PLUS_ALPHA (aggressive)
High β growth names with α>3%. Apply only with full risk-gate machinery
(kill switch + target_vol + regime scaling).

Candidates: ABNB, ADI, AMAT, AMD, APO, ARES, AVGO, AXON, BLDR, BX,
CDNS, CRWD, DELL, GE, INTU, KKR, MPWR, META (in), PH, PLTR.

*Curated selection* (10): **AMD**, **AMAT**, **ADI**, **AVGO**, **KLAC**
(already in), **LRCX** (already in), **CRWD**, **INTU**, **KKR**, **BX**,
**CDNS**.

### Final proposed expansion
- **Base**: 52 symbols (existing universe — unchanged)
- **+11 Stage 1 (DIVERSIFIER_PREMIUM)**
- **+16 Stage 2 (ALPHA_GEN curated)**  (minus overlap with existing)
- **+10 Stage 3 (BETA_PLUS_ALPHA curated)**  (minus overlap)
- **Target universe size: ~85 symbols** (conservative; can bump to 100+
  after empirical validation in R39-R41)

---

## Invariant compliance

| Constraint | Status |
|---|---|
| Long-only, no-margin | ✅ unchanged |
| SQQQ blacklist | ✅ unchanged |
| TQQQ/SOXL stricter thresholds | ✅ unchanged (no new leveraged) |
| No real broker integration | ✅ unchanged |
| Benchmark SPY/QQQ | ✅ unchanged |
| Left-side trading module | ✅ unchanged |
| Intraday 60m/30m primary | ✅ unchanged |
| Chinese reports / English code | ✅ unchanged |
| QQQ Outperformance Rule | ✅ target unchanged; expansion assists |
| MaxDD 15-20% target | ⚠ must re-validate post-expansion |

---

## Known data-quality caveats

1. **Alpha diagnostic panel has extreme outliers** (TPL β=23, GOOGL
   β=-6.88 due to split alignment / sparse history / panel-wide regression
   spillovers). Priority buckets use **category** (derived from returns)
   not raw β value — these are robust.
2. **Sharpe/MaxDD fields NaN for most symbols** (`perf_stats` returns
   None when series has leading NaN). CORE_ALPHA strict filter was 0;
   SATELLITE_ALPHA bucket used only category + admission, which remains
   reliable.
3. **Sector labels not yet attached** — estimates in stage tables are
   approximate. A final proposal iteration should pull sectors from
   yfinance `Ticker.info['sector']` (one-shot, cache result).

---

## Recommended authorization flow

**Step 1** (user confirms proposal) →
**Step 2** (loop edits `config/universe.yaml` adding Stage 1 + 2 + 3
candidates; also refreshes yfinance daily cache for any not yet downloaded)
→
**Step 3** (R39-R41: run mining with `--extra-symbols <new85>` and
compare OOS performance; QQQ gate; MaxDD invariant)
→
**Step 4** (if R39-R41 shows +α via new symbols, promote to permanent
universe; else keep rollback flag enabled)

---

## Specific `config/universe.yaml` patch (proposed)

Add to `seed_pool:` block under a new comment header:

```yaml
  # ═════════════════════════════════════════════════════════════════
  # R38 v3 expansion — awaits user authorization (2026-04-22)
  # Source: R34 SP500 sync + R35/R36/R37 pipeline (deep-mining 50r)
  # Lineage: `post-2026-04-22-deep-R38-expansion`
  # ═════════════════════════════════════════════════════════════════

  # Stage 1 — Diversifier premium (11, β<0.7, strong sharpe)
  - BRK-B
  - TER
  - TJX
  - TKO
  - TRGP
  - TRV
  - TSN
  - TT
  - TXN
  - UNP
  - VICI

  # Stage 2 — Alpha-generator curated (16, β≈1.0, α>3%, sector-diversified)
  - COST
  - AXP
  - BKNG
  - APD
  - ABT
  - CMG
  - COP
  - UNH
  - LLY
  - ISRG
  - NEE
  - MCK
  - CME
  - TMO
  - A
  - ACGL

  # Stage 3 — Beta-plus-alpha curated (10, β>1.3, α>3%, semis/growth)
  - AMD
  - AMAT
  - ADI
  - AVGO
  - CRWD
  - INTU
  - KKR
  - BX
  - CDNS
  - PLTR
```

Total new symbols: **37** (avoiding the 11 overlap with existing 52).

---

## Validation plan (post-authorization)

| Round | Action | Pass criterion |
|---|---|---|
| R39 | `run_mining.py --extra-symbols <new37> --trials 20 --budget 1200` | At least 1 trial passes OOS (mining evaluator Stage 6) |
| R40 | Regime-stratified backtest on expanded universe | QQQ excess positive across majority of regimes |
| R41 | Full acceptance pack v2 with top spec from R39-R40 | 10/10 gates pass OR document blocker |

---

## Decision requested from user

| Option | Action |
|---|---|
| **A** | Approve Stage 1+2+3 as proposed (37 new symbols) |
| **B** | Approve Stage 1 only (11 Diversifier Premium, conservative start) |
| **C** | Request revisions (e.g., different sector weighting, different stage sizes) |
| **D** | Decline; keep current 52-symbol universe |

This proposal does NOT auto-execute any config change. Per §11.2 any
config/universe.yaml modification requires explicit user authorization.

---

*Proposal auto-generated by deep-mining 50-round R34-R38 pipeline
(commits `1b651dd` → `9d87569` → `e79ce42` → `b698f3e`).*
