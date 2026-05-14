# Cycle11 Signal-Driven Mining PRD

**Date**: 2026-05-14
**Lineage**: `track-c-cycle-2026-05-14-11-signal-driven`
**Status**: DRAFT — ready for user explicit-go + sha256 lock
**Authors**: operator (zibomeng@) + Claude Code assist
**Trigger**: roadmap v2 §9 path — T1 sleeves complete with no Track-A nominee → T2 cycle11 attempts signal-driven attack on bundle binding

---

## §1 Hypothesis

cycle04-10 sibling-by-NAV is the **TC ceiling** on long-only top-N over a 78-stock universe with calendar (monthly) rebalance. T1 sleeves (alt-A intraday reversal + T1b confirmation pattern + T1c FOMC) demonstrated that **horizon/cadence change DOES escape sibling-by-NAV** (correlation 0.15-0.17 vs cycle04-08's 0.85-0.95). But none individually produced a Track-A-passing candidate.

cycle11 attempts mining over SIGNAL-DRIVEN game (entry_predicate × confirmation_predicate × exit_predicate × seed-signal selection) to find a Track-A nominee. The hypothesis: by searching the joint space of signal triggers + holding rules (which T1 sleeves had FIXED), mining can produce a sleeve with consistent year-by-year vs SPY excess.

---

## §2 What's NEW vs cycle04-10

| Dimension | cycle04-10 (factor + objective mining) | cycle11 (signal-driven mining) |
|---|---|---|
| Selection space | Composite_score = Σ wᵢ × factor_i; weights uniform | (setup_predicate, confirmation_predicate, exit_predicate, max_hold) |
| Cadence | Monthly rebalance (fixed) | Signal-triggered (variable time-in-market) |
| Universe | 78 stocks | 53 seed_pool stocks (T1a/T1b precedent) |
| Construction | top_n=10 equal-weight (cap_aware) | top_n=5 equal-weight per fire (smaller capacity) |
| Objective | IC_IR / Sharpe / nav_sharpe / nav_residualized | Sharpe-of-trades / NAV Calmar / IR-vs-benchmark (all 3 per roadmap v2 Q3) |
| Mining engine | Optuna TPE on factor weight space | Optuna TPE on signal-predicate space |
| Backtest engine | BacktestEngine.run(signals_df) calendar | K1 SignalDrivenBacktest wrapper |
| Stop rule | 0-nominee → next cycle pivot | 0-nominee → informative null + multi-archetype combine |

---

## §3 Signal seed pool (per roadmap v2 Q8 = all 6)

Per roadmap v2 §4 signal candidate seed library (Faber 2007 / Connors 2008 /
Donchian 1980s / HY OAS / Zweig 1986 / GKM 2001):

| ID | Signal | Role |
|---|---|---|
| **S1** | Faber 10-mo / 200-SMA cross | Regime gate (risk-off) |
| **S2** | Connors RSI(2) < 5 above 200-SMA | Mean-reversion entry |
| **S3** | Donchian 20/55 breakout | Trend-following entry |
| **S4** | HY OAS rolling 60d z-score (FRED BAMLH0A0HYM2) | Cross-asset risk gate |
| **S5** | Zweig breadth thrust (10d EMA A/(A+D) 0.40→0.615 in ≤10 days) | Bottom-detection |
| **S6** | Gervais-Kaniel-Mingelgrin abnormal-volume | Visibility tilt |

Plus the 3 orthogonal archetype combinations:
- **A**: Trend-following = S3 (Donchian) + ADX(14)>25 + S1 (Faber gate)
- **B**: Mean-reversion = S2 (Connors RSI(2)) + S1 (Faber gate)
- **C**: Cross-asset risk gate = S4 (HY OAS) + VIX/VXV

---

## §4 Mining search space

```python
class SignalDrivenSpace(ParameterSpace):
    """Cycle11 signal-driven mining."""

    def sample(self, trial):
        return {
            # Entry signal: pick one from S1-S6
            "entry_seed": trial.suggest_categorical(
                "entry_seed", ["faber_200sma", "connors_rsi2", "donchian55",
                               "hy_oas_zscore", "zweig_breadth", "gkm_volume"]),
            "entry_lookback_days": trial.suggest_int("entry_lookback", 10, 252),
            "entry_threshold_pct": trial.suggest_float("entry_thresh_pct", 0.5, 5.0, step=0.25),

            # Confirmation predicate
            "confirmation_type": trial.suggest_categorical(
                "conf_type", ["same_bar", "adx_filter", "volume_surge", "none"]),
            "confirmation_ttl_bars": trial.suggest_int("ttl_bars", 0, 10),

            # Exit predicate
            "exit_type": trial.suggest_categorical(
                "exit_type", ["max_hold_only", "atr_stop", "sma_cross", "opposite_signal"]),
            "max_hold_days": trial.suggest_int("max_hold", 5, 60),
            "atr_stop_multiplier": trial.suggest_float("atr_mult", 1.0, 3.0, step=0.25),

            # Regime gate (optional)
            "regime_gate": trial.suggest_categorical(
                "regime_gate", ["none", "faber_only", "vix_threshold", "credit_spread"]),

            # Construction
            "top_n": trial.suggest_int("top_n", 3, 10),
        }
```

Estimated search space size: 6 × 24 × 19 × 4 × 11 × 4 × 56 × 9 × 4 × 8 ≈ 1.7M combinations. Optuna TPE samples ~200 trials → ~0.01% coverage.

---

## §5 Acceptance criteria

Per roadmap v2 Q3 LOCKED = all 3 objectives all-try:

For each completed trial:
1. Compute trade-by-trade Sharpe (Objective A)
2. Compute NAV Calmar (Objective B)
3. Compute IR-vs-benchmark (Objective C)

Mining archives top-10 trials per objective × 3 = up to 30 archived trials.

Then Track A acceptance:
- Standard 17-gate evaluator on each archived trial
- Anti-sibling NAV correlation: raw < 0.85 vs all of {RCMv1, Cand-2, trial9_v2, alt-A, T1b}
- 0-nominee = informative null per cycle04-10 precedent

---

## §6 Engineering decomposition

| Phase | Scope | Time |
|---|---|---|
| Phase 1 | SignalDrivenSpace + signal-seed compute (6 entry + 3 confirmation + 4 exit + 4 regime) | 4 days |
| Phase 2 | Mining harness — Optuna TPE wraps SignalDrivenBacktest end-to-end | 2 days |
| Phase 3 | 200-trial mining run + per-objective archive | 1 day (compute) |
| Phase 4 | Track A acceptance + anti-sibling on top trials | 0.5 day |
| Phase 5 | Closeout memo | 0.5 day |
| **Total** | | **~1-1.5 weeks** |

---

## §7 Stop rule (pre-committed)

Per cycle04-10 precedent + roadmap v2 §9:

- **If ≥1 trial passes Track A + anti-sibling**: promote to S2_paper_candidate; forward init authorized
- **If 0 nominee**: cycle11 closes informative null. T2c ML Phase 2 becomes next attack vector (rank candidate setups via XGB/Transformer over signal-driven trade outcomes — different selection mechanism than Optuna TPE)

NO auto-cycle12. User explicit-go required for further attempts.

---

## §8 Sealed window discipline

- Train years 2009-2017 + 2020 + 2022 + 2024 → mining selection
- Validation 2018/19/21/23/25 → Track A 17-gate eval
- **Sealed 2026 panel NOT consumed unless nominee passes acceptance + forward soak**

---

## §9 Open questions — all LOCKED per roadmap v2

Q1 Tier 1 ordering = T1a first then T1b ∥ T1c → DONE
Q2 PEAD scope = PEAD + FOMC bundle → FOMC dead, PEAD deferred
Q3 cycle11 objective = all 3 → LOCKED here
Q4 ML Phase 2 scope = couple with T2 → T2c will use cycle11 outputs
Q5 F1/F2/F3 = all → not yet
Q6 test surface = K1 strict TDD / T1 mix / T2 integration-only → T2 will be integration-test-only
Q7 forward observation = unified runner → T2 will use SignalDrivenBacktest
Q8 signal seed library = full 6 + 3 archetypes → LOCKED here

---

## §10 Authorization

User explicit-go needed to:
1. Freeze this PRD (sha256 lock)
2. Implement Phase 1 + Phase 2 (~6 days eng)
3. Authorize 200-trial mining run (1 day compute)

Pre-implementation, mining run is NOT authorized. This PRD is the
authorization framework, not the authorization itself.

---

## §11 Status

**DRAFT** as of 2026-05-14. Ready for user explicit-go to ship Phase 1.
