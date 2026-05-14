# ML Phase 2 — Architecture Sketch

**Date**: 2026-05-14
**Status**: DRAFT — sketch only; gated on T2b cycle11 outcome
**Authors**: operator (zibomeng@) + Claude Code assist
**Trigger**: roadmap v2 Q4 LOCKED = ML Phase 2 couples with T2; T2b verdict determines T2c scope

---

## §1 Background

ML Phase 1.6 (commit log `f0ab349..f1bcf79`, 2026-05-12) shipped XGBoost
LambdaRank composite mining on cycle04-10 factor pool. **Track A 0/0 PASS**
— ML Phase 1 hit the SAME sibling-by-NAV ceiling as cycle04-08 manual
mining. The conclusion: ML over the cycle04-10 SELECTION SPACE (composite
scoring of stock-level factors, monthly top-N) doesn't escape bundle binding.

The PRD-implicit assumption was ML's pattern-recognition power could find
non-linear factor combinations that beat linear weighted sums. Empirically,
the bundle constraint is structural, not factor-selection. ML couldn't help.

**Phase 2 changes the selection space**, not just the model class.

---

## §2 Three options (per roadmap v2 §6 Q4)

### Option A: Multi-timescale transformer on bar-level features

Architecture: sequence model (small transformer or LSTM) ingesting:
- Daily features: 60d window
- 60m features: 100 most-recent 60m bars
- Output: per-symbol predicted return distribution

Cons:
- 60m data 2009-2014 sparse (per CLAUDE.md trades_backfill notes)
- Training cost: ~$50-200 / run with GPU
- High overfit risk on PQS small dataset (~2500 daily bars × 78 syms = 200k examples — small by modern transformer standards)

### Option B: Regime-conditional ranker

Architecture: separate ranker per regime (BULL / NEUTRAL / BEAR / CRISIS).
Use existing PRD-E TAA regime classifier output. Each regime trains its own
gradient-boosted ranker on factor → forward return.

Cons:
- Already implicit in cycle10 NAV-residualized mining
- Trial 9 v1's `max_dd_126d` was a similar regime-aware factor
- Doesn't actually change selection space (still composite-score top-N)

### Option C: Signal-driven ML over cycle11 trade outcomes ⭐ (recommended)

**Architecture**: Cycle11 mining produces trade-by-trade outcomes (per-trade
P&L, hold-period return, signal context features). Phase 2 ML trains a
RANKER on those trades:
- Input: signal context at trigger time (entry_seed_id, regime_state,
  pre-entry vol z-score, sector context, market breadth at entry)
- Label: realized trade P&L
- Output: predicted P&L → use to RANK competing signal triggers when
  multiple fire simultaneously

This is fundamentally different from cycle04-10 ML because:
- Selection unit = SIGNAL TRIGGER (not stock at monthly rebalance)
- Label = realized trade P&L (not 21d forward return)
- Feature space = trigger-time context (not stock-level factor score)

The ML model becomes a SIGNAL FILTER, not an alpha source — it's a learned
"which triggers to act on" classifier on top of cycle11's mined signal
predicates.

---

## §3 Recommended path = Option C (coupled with T2)

**Trigger**: T2b cycle11 mini-mining + full 200-trial mining produces
archived trade-by-trade outcomes → ~10k-100k labeled trades.

**Phase 2 modules**:

| Module | Path | Status |
|---|---|---|
| `core/ml/signal_ranker.py` (new) | NEW | Sketched, not built |
| `core/ml/feature_extractor.py` (extend) | EXISTING | extend with signal-context features |
| `tests/unit/ml/test_signal_ranker.py` | NEW | TDD |
| `scripts/run_signal_ranker_mining.py` | NEW | mining driver |

**Engineering est**: ~2 weeks gated on cycle11 producing enough trades.

---

## §4 Why this design ≠ cycle04-10 ML

cycle04-10 ML (Phase 1.6):
- Input: 162 stock-level factors at each rebalance bar
- Output: composite_score per stock
- Selection: top-N by score, monthly rebalance
- Acceptance: Track A on resulting NAV

Phase 2 (Option C):
- Input: signal trigger context (when a signal fired)
- Output: P&L prediction
- Selection: filter triggers (reject low-predicted-P&L ones)
- Acceptance: Track A on resulting NAV (now with FEWER triggers)

The MECHANISM is filtering at the trigger-event level, which is upstream
of stock selection. This is what's structurally different.

---

## §5 Open questions

1. **Sample size**: cycle11 produces ~?? trades over 200-trial mining.
   At 5 trades/year/strategy × 200 strategies × 9 years = 9000 trades.
   Sufficient for gradient-boosted ranker; insufficient for transformer.
2. **Train/test split**: must respect cycle11's temporal split. Phase 2
   train = cycle11 train years; Phase 2 OOS = cycle11 validation years.
   Cannot use cycle11's CHOSEN best trial for Phase 2 training (target
   leakage).
3. **Acceptance criterion**: Phase 2 ranker filtering produces a NAV
   series. Run Track A on filtered NAV vs unfiltered. If filtered ≥
   unfiltered + meaningfully more positive vs SPY → Phase 2 ships.

---

## §6 Status + gating

This doc is a SKETCH. Implementation gated on:
- T2b cycle11 mini-mining outcome (Sharpe vs SPY)
- If T2b best trial > SPY Sharpe → full 200-trial cycle11 → THEN T2c
- If T2b 0 trials beat SPY → re-evaluate before building T2c
  (might be that signal-driven mining itself fails to produce trade-level
   alpha, in which case T2c filter-on-top-of-mining adds nothing)

Updated when T2b verdict lands.
