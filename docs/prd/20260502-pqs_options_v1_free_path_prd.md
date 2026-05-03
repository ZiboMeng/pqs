# PRD — PQS Options v1 (Free Path Start)

**Status**: ACTIVE on branch `pqs-options-v1-2026-05-02`. Authority: user
explicit-go 2026-05-02 ("开始做"). Prior session converged path:
- Q1 strategy mix: covered call + cash-secured put + uncovered (with stop)
  + wheel + iron condor
- Q2 historical edge: put-selling most profitable (consistent with VRP)
- Q3 conservative scaling: 80% SPY core + 20% options satellite initial
- Q4 broker/data: $0 free path Phase 1, defer broker / paid data decision
  to next Monday after Phase 1 viability validated

**Trial 9 stock workstream isolation**: HARD constraint. See Appendix B.

---

## 1. Goal

Validate whether systematic options strategies (initially cash-secured put
+ covered call + wheel) can deliver positive risk-adjusted alpha vs SPY
buy-hold for individual scale ($10K-100K), under strict tail-risk
discipline (no naked-vol-fund-killer scenarios).

**Acceptance**:
- VRP (vol risk premium) historically positive AND quantified
- Synthetic cash-secured put backtest with tail-risk overlay produces:
  - Sharpe > SPY (>0.50)
  - MaxDD with overlay ≤ -25% (vs SPY -56% in 2008-style)
  - Positive expected return (does not need to beat SPY absolute; Sharpe
    improvement + MaxDD reduction is the win condition)

**Non-acceptance** (kill switch):
- VRP historically near-zero or negative → vol-selling NOT a real edge
- Synthetic backtest with realistic tail discipline shows MaxDD worse than
  SPY → defeats whole purpose
- Strategy requires position concentration > 20% in single underlying

---

## 2. Tail-risk-first design (non-negotiable)

User Q1 explicitly mentioned "uncovered call/put 带止损 低 delta 带提前
止盈" — this discipline is **encoded as core architecture from day 1**,
not retrofitted later.

### 2.1 Position-level discipline (per-trade)

Every options strategy MUST have:

| Rule | Default | Rationale |
|---|---|---|
| **Stop loss trigger** | loss = 2× premium received → close immediately | Caps single-trade loss; common option-seller discipline |
| **Early profit-take** | premium decay = 50% → close | Lock in gains, avoid late-cycle gamma risk |
| **Time-stop** | 21 DTE remaining → close OR roll | Avoid expiration-week gamma blow-up |
| **Delta cap at entry** | absolute delta ≤ 0.25 (default; configurable per strategy) | Low-delta = far OTM = lower assignment probability + higher prob of profit |
| **No earnings exposure** | close 2 days before earnings | Earnings IV crush is binary, not systematic edge |
| **No event week** | skip entry if FOMC / CPI / NFP within 5 DTE | Event-driven IV spikes can blow through stop |

### 2.2 Account-level circuit breakers

Beyond per-position rules, account-level halts:

| Trigger | Action | Rationale |
|---|---|---|
| **VIX spike day-over-day > 50%** | HALT new entries 24h | 2018-02-05 vol-XIV scenario; entry into this regime = catastrophic |
| **Account drawdown > 5% intraday** | Close all positions, no new entries today | Survive to fight tomorrow |
| **Account drawdown > 10% within 5 days** | Close all + 1 week halt | Reset before continuing |
| **Single underlying notional > 30% of capital** | Block new entry | Concentration limit |
| **Total short-vol notional > 200% of cash** | Block new entry | Leverage cap (sized for 2008-style scenario) |
| **Implied vol < 12 (low-vol regime)** | Reduce position size 50% | VRP lowest in low-VIX, edge thin |

### 2.3 Position sizing — survive-tail-first

Default sizing rule:

```
position_size = min(
    fixed_fraction_of_capital * tail_risk_multiplier(VIX),
    kelly_fraction_size,
    notional_concentration_limit,
)

# Tail risk multiplier (from VIX):
#   VIX < 15: 0.5x base size (low edge)
#   VIX 15-25: 1.0x base size (normal)
#   VIX 25-35: 0.7x base size (volatile, careful)
#   VIX > 35: 0.3x base size (crisis, minimal exposure)
#   VIX > 50: 0x (no entry)
```

**Worst-case scenario sizing test (mandatory)**:
Before any strategy ships, must pass: "If SPY drops -30% overnight (à la
2020-03-16 -12% single-day), what's the account drawdown?"
- Required: ≤ 25% account drawdown
- Failure: reduce position sizing until passes

### 2.4 Strategy-tier mandatory features

Per user Q1 categorization:

**Tier 1 (cash-secured put / covered call / wheel)**:
- Defined-cash-required, naturally bounded loss
- Tail risk = underlying drops to 0 (rare but bounded)
- Stop loss + early TP discipline applied

**Tier 2 (iron condor / vertical spreads)**:
- Defined-risk by structure
- Max loss = spread width - premium
- Per-trade stop loss + IC management at 21-DTE / 50%-profit / 200%-loss

**Tier 3 (uncovered / naked with discipline)**:
- HIGHEST risk; NOT in v1 scope
- Defer until Tier 1+2 verified positive 6+ months
- When eventually shipped: MUST have account-level circuit breakers + 
  position concentration limits + automated stop enforcement (no manual
  override)

---

## 3. Phase 1 — Free-path validation (this PRD scope)

### 3.1 Phase 1.1: Branch + isolation contract (this commit)

- Branch `pqs-options-v1-2026-05-02` created
- This PRD with full isolation list (Appendix B)
- `tests/unit/options/test_isolation_contract.py` CI gate

### 3.2 Phase 1.2: VIX/RV gap historical analysis

**Goal**: Confirm VRP exists at meaningful magnitude.

**Free data**: yfinance `^VIX` + `SPY` history (2007+)

**Computation**:
- Daily 30-day forward realized vol of SPY
- VIX (current 30-day implied vol) - RV(t+30)
- VRP statistics: mean, percentiles, worst-month
- VRP regime conditional on VIX level

**Output**: `data/options/analysis/vrp_analysis_2007_2024.json` + summary
plot + decision

**Decision**: 
- VRP mean > 2% AND positive in > 65% of months → vol-selling has edge
  (proceed Phase 1.3)
- Else → vol-selling NOT a real edge, reconsider whole approach

### 3.3 Phase 1.3: Synthetic cash-secured put backtest with tail discipline

**Goal**: Backtest if user's "卖 put 盈利最多" (Q2) observation holds
systematically.

**Free data**: yfinance SPY history + VIX (used as IV proxy)

**Strategy** (encoded with §2 tail discipline):
- Universe: SPY only (tightest IV proxy from VIX)
- Entry: monthly, 30-DTE, 25-delta cash-secured put
- Position size: 1 contract per $20K capital × tail_risk_multiplier(VIX)
- Stop loss: close if loss > 2× premium received
- Early TP: close at 50% premium decay
- Time-stop: close at 21 DTE
- Skip entry if VIX up > 50% day-over-day previous day
- Skip entry if VIX < 12 OR > 50

**Output**: `data/options/backtest/csp_spy_2007_2024_tail_disciplined.json`
+ NAV curve + trade log + Sharpe / MaxDD / win rate

**Decision**:
- Sharpe > 0.6 (vs SPY 0.5) AND MaxDD < -25% AND >150 trades → ship to 
  Phase 2 (paper trading)
- Else → revise discipline rules OR retire strategy

### 3.4 Phase 1.4: Results memo + Monday data decision

Compare Phase 1.2 + 1.3 results to user's prior manual experience. Decision
options:
- (a) Stay $0: continue Phase 2 paper with yfinance current chain
- (b) Pay ORATS $99/mo: precision backtest + production-grade
- (c) Pay OptionsDX $30/mo: middle ground (if 2024-2026 data confirmed)
- (d) Stop: if numbers don't validate edge

---

## 4. Phase 2-4 (Future, NOT in this PRD scope)

Documented for context only. Each gated on prior phase success.

- **Phase 2** (3-4 weeks): Paper trading on tastytrade + daily chain
  snapshot accumulation. Verify execution mechanics.
- **Phase 3** (3-6 months): Forward observation. Validate paper-vs-real-fill
  drift. Gather statistical sample.
- **Phase 4** (later): Live small capital ($1-5K). Then scale per Q3
  conservative plan.

Live trading authorization requires user explicit-go AND Phase 3 numbers
positive AND tail-risk dry-run on stress scenarios passed.

---

## 5. Acceptance criteria for Phase 1 close

| # | Gate | Pass? |
|---|---|---|
| A1 | Branch + PRD + isolation contract test ship | TBD |
| A2 | VIX/RV gap analysis output produced | TBD |
| A3 | A2 verifies VRP > 2% mean AND > 65% positive months | TBD (data decides) |
| A4 | Synthetic CSP backtest with tail discipline output produced | TBD |
| A5 | A4 verifies Sharpe > 0.6 AND MaxDD < -25% on 17-yr backtest | TBD |
| A6 | Results memo with Monday data decision recommendation | TBD |
| A7 | Trial 9 forward observation NOT touched (manifest hash unchanged) | TBD |
| A8 | Isolation contract test passes (no stock workstream files modified) | TBD |

If A3 OR A5 fail → STOP. Re-evaluate options direction.
If all pass → ship Phase 2 PRD next week.

---

## Appendix A — User-provided context (preserved verbatim)

**Q1 strategy mix**: covered call put, uncovered call and put 带止损 低
delta 带提前止盈, wheel, iron spread

**Q2 historical edge**: 卖 put 盈利最多

**Q3 capital scaling**: 先从保守开始

**Q4 infrastructure**: 目前券商 fidelity (recommended IBKR for systematic
live; tastytrade paper for free Phase 2)

**Free path requirement (2026-05-02 message)**: 上来不想 live trading;
options 经验已有; OptionsDX 看上去只到 2023; 想 free 起步

**This-session directive (2026-05-02)**: "开始做 咱们现在做应该很快 做完
验证可行 那就下周一考虑开数据 但是要考虑黑天鹅或者极端条件下的止损"

---

## Appendix B — Isolation contract (HARD)

This branch must NOT modify any of the following files. Pre-merge gate test
enforces compliance.

### Config layer (most critical — drift triggers Trial 9 forward HALT)

- `config/universe.yaml`
- `config/factor_registry.py`  
- `config/risk.yaml`
- `config/system.yaml`
- `config/research_mask.yaml`
- `config/temporal_split.yaml`
- `config/temporal_split_v2.yaml`
- `config/temporal_split_v3.yaml`
- `config/cost_model.yaml`
- `config/notify.yaml`
- `config/backtest.yaml`
- `config/regime.yaml`
- `config/events.yaml`
- `config/production_strategy.yaml`
- `config/reporting.yaml`
- `config/acceptance.yaml`
- `config/fleet.yaml`

### Data layer

- `data/daily/*`
- `data/intraday/*`
- `data/ref/splits.parquet`
- `data/ref/bar_provenance.parquet`
- `data/ref/distributions.parquet`
- `data/research_candidates/trial9_*`
- `data/research_candidates/rcm_v1_*`
- `data/research_candidates/candidate_2_*`
- `data/research_candidates/*_promotion_criteria.yaml`
- `data/baseline/*`
- `data/ml/forward_runs/*` (when Trial 9 starts populating)
- `data/ml/research_miner/*`
- `data/paper_runs/*`

### Forward observation code

- `core/research/forward/runner.py`
- `core/research/forward/manifest_schema.py`
- `core/research/forward/revalidate.py`
- `core/research/forward/readiness.py`
- `core/research/forward/attention_report.py`
- `core/research/forward/source_layer.py`
- `core/research/forward/manifest_io.py`
- `core/research/forward/bar_hash.py`

### Track A code

- `core/research/temporal_split.py`
- `core/research/temporal_split_acceptance.py`
- `core/research/sealed_ledger.py`
- `core/research/candidate_registry.py`
- `core/research/regime_classifier.py`
- `core/research/acceptance_helpers.py`
- `core/research/frozen_spec.py`
- `core/research/risk_cluster_map.py`
- `core/research/concentration/*`
- `core/research/robustness/*`

### Mining + factor

- `core/mining/*`
- `core/factors/factor_registry.py`
- `core/factors/factor_engine.py`
- `core/factors/factor_evaluator.py`

### Stock backtest core

- `core/backtest/*` (read-only OK, no mods)
- `core/signals/*`
- `core/risk/*`

### Diagnostics + reporting + paper

- `core/diagnostics/*`
- `core/reporting/*`
- `core/paper_trading/*`
- `core/universe/*`
- `core/fleet/*`

### Stock data layer (read-only OK)

- `core/data/bar_store.py` (read OK; no schema modifications)
- `core/data/yfinance_provider.py` (read OK)
- `core/data/calendar.py`
- `core/data/market_data_store.py`
- `core/data/validator.py`
- `core/data/daily_aggregator.py`
- `core/data/trades_scanner.py`

### Stock dev scripts

- `dev/scripts/forward/*`
- `dev/scripts/baseline/*`
- `dev/scripts/cycle*/`
- `dev/scripts/correlation/*`
- `dev/scripts/oos_mvp/*`

### Stock tests

- `tests/unit/research/*`
- `tests/unit/backtest/*`
- `tests/unit/factors/*`
- `tests/unit/signals/*`
- `tests/unit/fleet/*`
- `tests/unit/data/*`
- `tests/unit/risk/*`
- `tests/unit/paper_trading/*`
- `tests/unit/reporting/*`
- `tests/unit/diagnostics/*`
- `tests/integration/*`

### Stock scripts

- `scripts/*` (all existing)

### Stock docs

- `CLAUDE.md` (no edits — append future entries via separate non-options branch if needed)
- `README.md` (no edits)
- `docs/prd/*` other than this PRD
- `docs/checkpoints/*`
- `docs/memos/*` other than options-* memos

---

### NEW space (this branch's only write target)

- `core/options/*` (new module)
- `config/options_*.yaml` (new config files)
- `data/options/*` (new data dir)
- `tests/unit/options/*` (new test dir)
- `dev/scripts/options/*` (new script dir)
- `docs/prd/2026*-pqs_options*.md` (this PRD + future)
- `docs/memos/2026*-options_*.md` (decisions + audit memos)
- `docs/checkpoints/2026*-options_*.md` (formal checkpoints)
