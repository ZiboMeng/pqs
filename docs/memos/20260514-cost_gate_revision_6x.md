# Cost Gate Revision — 2× → 6× for High-Turnover Strategies

**Date**: 2026-05-14
**Status**: SHIPPED — applies to cycle11+ candidates; cycle04-10 archive immutability preserved
**Authors**: operator (zibomeng@) + Claude Code assist
**Trigger**: T2b cycle11 mini-smoke cost sensitivity showed Connors RSI(2)
Sharpe 3.54 (at 5bp) → 0.67 (at 30bp realistic retail). Existing
`cost_robustness.multiplier_2x_must_remain_positive` is too lenient for
high-turnover signal-driven strategies.

---

## §1 Change

For cycle11+ candidates (signal-driven mining, high-turnover):
- **Baseline slippage cost** in mining backtest: 5bp → **30bp** (interday)
- This is 6× the cycle04-10 baseline, calibrated to realistic retail
  at-market execution
- The Track A `cost_robustness.multiplier_2x_must_remain_positive` gate
  is preserved as-is, but it now operates ON TOP OF the 30bp baseline
  (i.e., effectively 60bp = 12× of original 5bp benchmark)

**No yaml change to `config/temporal_split.yaml` v1/v2/v3** — those are
`locked_after_first_use: true` per Track A invariant. Future cycle11+
mining yamls will inject the new baseline through their own cost_model
config.

## §2 Why 6× not 2×

Per Frazzini-Israel-Moskowitz 2019 FAJ trading-cost study + retail broker
typical fills:

| Strategy turnover | Realistic execution cost | Old 2× ratio adequate? |
|---|---|---|
| cycle04-10 monthly (~12 rebal/yr) | 5-15bp | Yes (2× of 5bp = 10bp, covers ~95% of retail) |
| cycle11 daily signal (>500 rebal/yr) | 20-60bp | NO (2× of 5bp = 10bp, ~3× understatement) |

cycle04-10 had ~12 turnovers/year. cycle11 (e.g., Connors RSI(2) hold=3)
has ~411 turnovers/year per position × 5 positions = ~2000 effective
turnovers/year — 170× the cycle04-10 turnover rate. Transaction cost
matters proportionally to turnover.

## §3 Scope of effect

**Affects (going forward only)**:
- cycle11 mini-mining smoke (`dev/scripts/cycle11/run_cycle11_mini_smoke.py`):
  baseline cost updated to 30bp slip + 2bp commission
- Future cycle11 full 200-trial mining (when authorized): same baseline
- Future signal-driven candidates: same baseline
- Future T2c ML Phase 2 filter outputs: trained on 30bp-baseline trades

**Does NOT affect**:
- cycle04-10 archived trial results (5bp baseline preserved)
- simple_baseline_v1 backtest (yfinance-direct, no BarStore path)
- alt-A intraday reversal Phase 3 closeout (5bp baseline preserved;
  closeout already established informative null at that cost level)
- T1b ConfirmationPattern closeout (uses inline 5bp; verdict stands as
  "informative-positive but year-inconsistent at backtest level")

## §4 Future PRD amendment (not in this commit)

For Track A v4 yaml (when authorized):
- Add `cost_robustness.multiplier_6x_must_remain_positive: true` as
  ADDITIONAL gate (does not replace 2× gate)
- Add `cost_robustness.baseline_slip_bps: 5` field (explicit; current
  implicit value is 5bp from CostModel default)
- Mining yamls can declare `cost_model.baseline_slip_bps: 30` to override
  for high-turnover cycles

This is documented for future PRD work; not landed here.

## §5 Per-cycle calibration table (operator reference)

| Cycle | Turnover/yr (est.) | Recommended baseline | Recommended Nx for Track A |
|---|---|---|---|
| cycle04-10 (monthly) | ~12 | 5bp (cycle04-10 standard) | 2× = 10bp |
| Trial 9 v2 forward (monthly diversifier) | ~12 | 5bp | 2× |
| cycle11+ (signal-driven daily) | 200-2000 | **30bp (revised)** | 2× of 30bp = 60bp |
| Future intraday-execution sleeves | >1000 | 50bp+ | 2× of 50bp = 100bp |

This table is operator-reference, not yaml-enforced.

## §6 Verification

cycle11 mini-smoke re-run with 30bp baseline cost: see
`docs/memos/20260514-t2b_cycle11_mini_smoke_v2_realistic_cost.md` (TBD).

If 0/20 trials beat SPY Sharpe under realistic cost → cycle11 not viable
as standalone; T2c ML Phase 2 mandatory for cost-aware filtering.

If ≥1 trial beats SPY → cycle11 alpha survives realistic cost; full
200-trial mining authorized at user explicit-go.
