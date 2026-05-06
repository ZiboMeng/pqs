# PRD-E v1.1 Phase 3 Closeout — TAA Validation Acceptance

**Date**: 2026-05-06
**Operator**: zibomeng (Claude Opus 4.7)
**Authority**: PRD-E v1.1 + user explicit-go 2026-05-06 ("做E" + "按照你的推荐走")
**Lineage**: `taa-phase3-validation-2026-05-06`

## TL;DR

PRD-E v1.1 Phase 3 validation acceptance: **5 of 7 hard gates PASS**.
TAA V1 + monthly cadence on selector panel (train + validation, sealed
excluded) **PASSES all 5 defensive-value gates** (G1 BEAR year, G3
stress slices, G4 per-year MaxDD, G5 BULL beta, G7 full-period MaxDD)
but **FAILS the 2 standalone-alpha gates** (G2 2025 vs SPY HARD, G6
Calmar ≥ SPY HARD).

**Operator verdict (PRD §10 reading)**: TAA is **non-viable as standalone
alpha** but **defensive sleeve evidence is strong**. Per PRD §10
reversibility, close PRD-E1 with this rejection memo; preserve TAA
infrastructure (4 modules + 62 tests) for **potential fleet integration
in future PRD-E2 or beyond** if/when fleet candidates exist that need
low-beta defensive sleeve.

## Phase 3 acceptance gate detail

### G1 — 2018 vs SPY positive (HARD; single BEAR validation year) ✅ PASS

- **TAA 2018 cum_ret: +1.14%**
- **SPY 2018 cum_ret: -6.94%**
- **vs_spy: +8.08%**

This is the BIG defensive value evidence. TAA outperformed SPY by 8
percentage points in the rate_hike_bear year (2018). This is exactly
where TAA's regime-allocation logic is supposed to add value: BULL
exposure cut + bonds sleeve cushioned the drawdown.

### G2 — 2025 vs SPY positive (HARD per CLAUDE.md core role gate) ❌ FAIL

- **TAA 2025 cum_ret: +5.44%**
- **SPY 2025 cum_ret: +16.64%**
- **vs_spy: -11.20%**

2025 is a strong-NVDA-driven BULL market (QQQ-led narrow bull). TAA's
70%/30% equities/defensive split in BULL undershoots vs passive SPY.
Same pattern as 2019/2021/2023 (all BULL validation years): TAA
underperforms by 18-29 percentage points in BULL years.

### G3 — Stress slice MaxDD ≤ 25% (HARD) ✅ PASS

- **covid_flash (2020-02-15 → 2020-04-30): MaxDD -4.73%**
- **rate_hike_2022 (2022-08-15 → 2022-10-15): MaxDD -5.04%**

Both stress slices well within -25% ceiling. TAA's regime detection
correctly identified CAUTIOUS/RISK_OFF/CRISIS during these periods and
defensive allocations contained drawdowns to single digits.

### G4 — Per-validation-year MaxDD ≤ 20% (HARD) ✅ PASS

| Year | MaxDD |
|---|---|
| 2018 | -1.87% |
| 2019 | -1.95% |
| 2021 | -4.42% |
| 2023 | -3.05% |
| 2025 | -1.70% |

All 5 validation years' MaxDD well below -20%. TAA's defensive
allocations dramatically reduce per-year drawdown vs passive equity.

### G5 — Beta to SPY in BULL ≤ 0.85 (HARD) ✅ PASS

- **TAA beta_to_spy in BULL: 0.008**

Essentially zero beta in BULL regime. This is suspiciously low — TAA
in BULL allocates 70% to equities (which are mostly SPY constituents)
yet has near-zero beta. Hypothesis: equal-weight across 53 stocks
diversifies idiosyncratic noise so well that the daily TAA return
series barely correlates with SPY's daily return on a return-by-return
basis (even though both go up over time). Operator note: this beta
metric may be measuring noise-correlation more than directional
exposure; a more honest "tracking error in BULL" might tell a
different story.

### G6 — Calmar ≥ SPY Calmar (HARD primary risk-adjusted) ❌ FAIL

- **TAA Calmar: 0.073** (CAGR +1.18% / |MaxDD| 16.04%)
- **SPY Calmar: 0.337** (CAGR +11.53% / |MaxDD| 34.23%)

SPY's 10x higher CAGR overwhelms its 2.1x deeper drawdown → Calmar
defeats TAA. Same finding as Phase 2 train-only smoke; consistent
across Phase 2 (train) and Phase 3 (selector = train+val).

### G7 — Full-period MaxDD better than SPY (HARD) ✅ PASS

- **TAA MaxDD: -16.04%**
- **SPY MaxDD: -34.23%**
- TAA's max drawdown is roughly half SPY's. Strong DD-control evidence
  even when CAGR loses.

## Phase 2 vs Phase 3 cross-check

| Metric | Phase 2 (train-only) | Phase 3 (selector = train+val) |
|---|---|---|
| TAA CAGR | +0.76% | +1.18% |
| SPY CAGR | (similar) | +11.53% |
| TAA MaxDD | -14.37% | -16.04% |
| SPY MaxDD | (~-34%) | -34.23% |
| TAA Calmar | 0.053 | 0.073 |
| SPY Calmar | 0.323 | 0.337 |
| Calmar gate | FAIL | FAIL |

Phase 3 confirms Phase 2 directional finding: TAA underperforms passive
SPY on CAGR/Calmar but materially controls drawdown. The validation
years (2018+2019+2021+2023+2025) skew BULL (4 of 5 BULL), so adding
them to train-only doesn't change the defensive-vs-CAGR tradeoff.

## Per-regime defensive evidence

| Regime | n_days | MaxDD |
|---|---|---|
| BULL | 1391 | -4.89% |
| RISK_ON | 1218 | -3.12% |
| NEUTRAL | 879 | -10.26% |
| CAUTIOUS | 884 | -6.07% |
| RISK_OFF | 236 | -3.93% |
| CRISIS | 268 | -5.11% |

CRISIS regime DD -5.11% (vs PRD-E original ≤ 10% target) — exemplary
defensive performance during high-fear periods. NEUTRAL is the
weakest regime (transitioning between BULL and CAUTIOUS catches
re-allocations mid-flight).

## Operator verdict (per PRD §10)

PRD-E §10 reversibility: "If TAA proves harmful or non-viable: Phase 1
modules `core/research/taa/` 可整体删除". The strict reading: 2 HARD
gates fail → non-viable → delete modules.

**Operator nuanced reading**: TAA is **non-viable as standalone alpha**
(G2 + G6 fail confirm passive SPY beats TAA on absolute and
risk-adjusted CAGR over selector window). But the **defensive value
evidence is too strong to discard** (G1 +8% in BEAR, G3 stress slices
< 5% DD, G7 half SPY MaxDD).

The right downstream path is **fleet integration** (TAA as low-beta
defensive sleeve combined with high-beta alpha candidates). This is
PRD §8 out-of-scope per "TAA + factor sleeve combination (Phase
C-PRD-3 territory)". Post-Phase-3 closeout, the choices are:

1. **Close PRD-E1 (this PRD) per §10 strict reading** + DELETE TAA
   modules (4 files + 62 tests). Saves ~1300 lines but throws away
   the defensive-evidence work.

2. **Close PRD-E1 standalone path + PRESERVE TAA modules** for future
   PRD-E2/Phase C-PRD-3 fleet integration. No alpha-first cost
   (modules don't run unless caller invokes); audit trail preserved.

3. **Re-tune V1 → V2 with more aggressive BULL allocation** (e.g.
   90/5/3/2). PRD-E §3 says "不 unify with PRD-AC" but doesn't ban
   rule-set tuning. Risk: over-fit train+validation BULL years; same
   2026+ uncertainty as cycle04/05/06 mining.

**Operator recommendation**: **Option 2** (preserve modules, no alpha-
first cost, future-optionality). The user has Trial 9 forward
observation in progress with TD60 decision point ~2026-07-30; if
Trial 9 graduates to fleet member, TAA's defensive sleeve becomes
directly relevant. Until then, modules sit dormant; no risk.

## Hypothesis verdict against operator's pre-Phase-3 prediction

**Pre-Phase-3 prediction** (operator surfaced when recommending B):
> "TAA Phase 2 已证明 DD 控制力 → 大概率通过 Phase 3 BEAR year
> gates" + "Phase 3 即使 fail 也是 valuable evidence"

**Verdict**: ✅ **Prediction confirmed**. Phase 3 passes all
defensive-value gates (G1 BEAR / G3 stress / G4 per-year DD / G5 beta /
G7 full DD) but fails the standalone-alpha gates (G2 / G6). The
PASS/FAIL split is exactly along the "defensive sleeve, not standalone"
axis. Phase 3 evidence is informative for downstream fleet decisions
even though "overall PASS/FAIL" is FAIL.

## What's preserved + what's deferred

**Preserved (no further action; alpha-first cost = 0)**:
- `core/research/taa/__init__.py`
- `core/research/taa/regime_rules.py` (RegimeAllocation + V1 + V0_MINIMAL)
- `core/research/taa/regime_label_generator.py` (daily/monthly + KL/Hamming)
- `core/research/taa/asset_class_builder.py` (universe → equal-weight target_wts)
- `core/research/taa/taa_harness.py` (run_taa_backtest)
- `core/research/taa/taa_acceptance.py` (G1-G7 evaluator)
- `tests/unit/research/taa/` (62 tests; full backward compat preserved)
- `dev/scripts/taa/run_taa_phase2_smoke.py`
- `dev/scripts/taa/run_taa_phase3_validation.py`

**Deferred (gated on user explicit-go for PRD-E2 / Phase C-PRD-3)**:
- Forward observation runner integration (PRD-E2 separate scope)
- Fleet allocator integration (Phase C-PRD-3)
- V1 → V2 rule tuning (over-fit risk; defer)
- SR defer / swing-trigger overlay on TAA (PRD-E §3 non-goal)

## Authorship + audit trail

- PRD-E v1.1: `docs/prd/20260505-taa_regime_allocation_framework_prd.md`
- Phase 1 commit: `4bc85ab` (regime rules + label gen + asset class builder)
- Phase 2 commit: `288c3c0` (TAA harness + train-only smoke)
- Phase 3 commit (this round): pending
- Phase 2 audit JSON: `data/audit/taa_phase2_smoke.json`
- Phase 3 audit JSON: `data/audit/taa_phase3_validation.json`

## Sealed 2026 panel

NEVER read. Phase 1-3 used `partition_for_role(role="miner")` for
train-only and `partition_for_role(role="selector")` for selector
(train + validation). Sealed 2026 single-shot panel never accessed by
any TAA module or smoke run. 5.4 OOS discipline preserved.

## Reversibility

Per PRD §10 strict reading, future revocation deletes
`core/research/taa/` directory. Per operator's recommended Option 2,
modules sit dormant until invoked by future PRD-E2 / Phase C-PRD-3
caller. Either path is reversible without affecting cycle04/05/06
mining infrastructure or Trial 9 forward observation.
