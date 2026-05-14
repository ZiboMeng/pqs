# T1a alt-A Intraday Reversal Closeout — Informative Null

**Date**: 2026-05-14 (next session after K1 ship + Option A SPY fix on 2026-05-13)
**Lineage**: `alt-archetype-intraday-reversal-2026-05-12`
**Status**: COMPLETE — T1a.1-T1a.7 shipped; verdict = informative null
**Authors**: operator (zibomeng@) + Claude Code assist
**PRD**: `docs/prd/20260512-alt_archetype_intraday_reversal_prd.md`

---

## §1 TL;DR

alt-A intraday reversal strategy under PRD §11 LOCKED defaults
(53-stock universe / weekly_reversal_signal_5d setup / 60m volume +
early-return confirmation / 5d hold / 2.5bp slip):

- **Track A acceptance: FAIL** (14/17 gates PASS; 3 fail on
  vs SPY/QQQ outperformance — strategy underperformed SPY by ~130pp
  over 2018-2025)
- **NAV correlation gate: PASS** (raw 0.15-0.16 vs all 3 fleet anchors,
  well under 0.85 threshold; residual essentially zero vs SPY)

Verdict = **informative null**. alt-A is structurally distinct from
existing fleet (RCMv1 + Cand-2 + trial9_v2) at NAV level — TC ceiling
escape via horizon change is REAL — but the locked-parameter spec
does not produce SPY-beating absolute returns over the 8-year
validation period. Not deployable as core_alpha; not deployable as
diversifier (full-period vs SPY HARD gate fails for both roles).

---

## §2 Workflow shipped today

| Sub-task | Status | Module / Output |
|---|---|---|
| T1a.1 | ✅ K1 design audit (already in K1.1) | `docs/audit/20260513-k1_deferred_exec_design.md` |
| T1a.2 | ✅ IntradayReversalRunner bridge | `core/backtest/intraday_reversal_runner.py` + 12 tests GREEN |
| T1a.3 | ✅ intraday_factor_bundle helper | `core/factors/intraday_factor_bundle.py` + 6 tests GREEN |
| T1a.4 | ✅ 60m bar coverage validation | 54/54 PQS seed_pool stocks ≥95% coverage in 2025 |
| T1a.5 | ✅ Track A 17-gate acceptance | `data/audit/alt_a_phase3_track_a_verdict.json` (re-run on clean SPY post-A.3) |
| T1a.6 | ✅ NAV correlation gate | `data/audit/alt_a_phase3_anti_sibling.json` (re-run on clean SPY) |
| T1a.7 | ✅ This memo | `docs/memos/20260514-t1a_alt_a_closeout.md` |

---

## §3 Track A results (clean SPY post-A.3 fix)

NAV: 2011 daily bars 2018-01-02 → 2025-12-31. Final equity 12,531 from
10,000 initial = **+25.31% total return** vs **SPY +155.79%** over
same window (8 years). vs_spy aggregate = **-130.48 pp**.

| Gate | Result | Notes |
|---|---|---|
| role_core_eligibility | ✓ | no constraints for core |
| validation_year_2018_maxdd | ✓ | -10.69% (≤ 20% threshold) |
| validation_year_2019_maxdd | ✓ | -6.67% |
| validation_year_2021_maxdd | ✓ | -9.70% |
| validation_year_2023_maxdd | ✓ | -12.74% |
| validation_year_2025_maxdd | ✓ | -10.64% |
| **validation_aggregate_excess_vs_spy** | **✗** | aggregate negative ~ -130pp |
| **validation_aggregate_excess_vs_qqq** | **✗** | aggregate negative |
| stress_slice_covid_flash_maxdd | ✓ | -10.04% (vs 25% threshold) |
| stress_slice_rate_hike_2022_maxdd | ✓ | -4.70% |
| **role_core__validation__2025__excess_vs_qqq** | **✗** | 2025 vs_qqq -23.43% |
| role_core__validation__2025__maxdd | ✓ | -10.64% |
| concentration_top1 | ✓ | top_n=5 equal-weight, max single ~20% |
| concentration_top3 | ✓ | 3-of-5 = 60%, under 70% cap |
| concentration_no_leveraged_etf | ✓ | universe has no leveraged ETFs |
| beta_to_qqq | ✓ | 0.0746 (very low — by construction of 3% time-in-market) |
| cost_robustness_2x | ✓ | survives 2× cost (turnover ~24x annual but small notional) |

Per-validation-year vs SPY:
- 2018: **+2.32%** (only positive year — bear-onset capture)
- 2019: -29.09%
- 2021: -34.19%
- 2023: -13.05%
- 2025: -19.67%

---

## §4 NAV correlation gate results (clean SPY post-A.3 fix)

Threshold: raw Pearson < 0.85 (PASS) AND residual vs SPY < 0.50 (PASS).

| Anchor | raw Pearson | residual vs SPY | n_overlap_days | Verdict |
|---|---|---|---|---|
| rcm_v1_defensive_composite_01 | **0.145** | -0.008 | 2010 | PASS |
| candidate_2_orthogonal_01 | **0.163** | +0.035 | 2010 | PASS |
| trial9_diversifier_002 | **0.153** | +0.007 | 2010 | PASS |

All 3 raw correlations are 0.14-0.16 — **far below the 0.85 cycle04-08
sibling level** (which clustered at 0.85-0.95). Residuals ≈ 0 after
subtracting SPY beta — meaning the small raw correlation IS the
shared market beta, not shared alpha.

**This is the strongest TC-ceiling-escape evidence so far in PQS.**
Horizon change (60m intraday execution + 5d hold vs daily monthly-rebalance
top-N) produces NAV that is genuinely orthogonal to cycle04-08's beta-stack.

---

## §5 Interpretation

### 5.1 Why Track A fails despite NAV being structurally distinct

The TC ceiling argument predicted that legitimate horizon-change attacks
on bundle binding (intraday execution + heterogeneous time-in-market)
would produce NAV-distinct candidates. They did — confirmed by §4.

But TC ceiling escape doesn't AUTO-PRODUCE SPY-beating alpha. The strategy
operates only ~3% of trading days (316 days with positions / 2011 total
business days). The remaining 97% is held in cash earning 0%. SPY
compounded at ~12.4%/yr over the period; alt-A compounded at ~2.9%/yr.
The compounding gap over 8 years is structural, not data-related.

### 5.2 Why this is informative

cycle04-08 + cycle10 sibling-by-NAV findings established that
construction-bound + factor-bound mining cannot escape bundle binding.
alt-A demonstrates that HORIZON-bound + CONFIRMATION-bound execution
CAN escape NAV correlation. This is the FIRST PQS evidence that
TC ceiling can be partially escaped.

**Strategic implication**: the path forward isn't "find a better intraday
reversal parameter set" — the absolute-return shortfall is structural to
the strategy's time-in-market design. Path forward is:
- Combine alt-A's NAV-distinct character with a HIGHER time-in-market
  alpha source (combine via fleet allocator, NOT replace SPY)
- Try DIFFERENT horizon-change variants (event-calendar T1c, signal
  confirmation T1b) — same TC escape mechanism, different alpha quality

### 5.3 What this does NOT mean

- alt-A as locked is NOT deployable (neither core_alpha nor diversifier
  role passes the vs SPY HARD gate)
- The PRD §11 LOCKED defaults are NOT going to be retuned in-place per
  immutability discipline (wrong-in-hindsight values → new lineage
  per cycle04-08 precedent)
- The strategy ISN'T broken — it's a thin-slice reversal capturing
  ~3% time-in-market with low beta to QQQ (0.07). For some fleet
  composition that needs "near-zero-correlation defensive component"
  it could fit, but vs SPY HARD gate makes it non-fleet-eligible
  under current acceptance discipline.

---

## §6 Strategic next steps (NOT auto-actioned)

| Option | Description | Triggers |
|---|---|---|
| **A** | Document alt-A as informative null + proceed T1b ConfirmationPatternStrategy + T1c alt-B event-calendar | Default — per roadmap v2 §9 sequence |
| B | Tune alt-A under NEW lineage (e.g. alt-archetype-intraday-reversal-2026-05-14b with different setup_quantile_threshold, top_n, or holding_period_max_days) | User explicit-go required (wrong-in-hindsight pivot) |
| C | Use alt-A NAV as a low-beta defensive sleeve in fleet allocator (PRD-E TAA-style overlay) | Trial 9 v2 TD60 verdict ~2026-08-06 + alt-B closeout |
| D | Try INVERSE alt-A: short-reversal (long when wr is HIGHEST instead of lowest) — flip the sign hypothesis | User explicit-go (sign-flip is a non-trivial alpha hypothesis change) |

**Operator recommendation = Option A** (informative null + continue path).
The roadmap v2 §9 path remains valid:
- K1 ✅
- T1a alt-A ✅ (this memo — informative null)
- T1b ConfirmationPattern (next)
- T1c alt-B event-calendar (parallel after T1a closes)
- T2a + T2c (after T1 sleeves)

---

## §7 What was unaffected by the SPY off-by-one bug

The verdict (FAIL Track A vs_spy by ~130pp) is robust to the SPY data
bug. Re-running on clean SPY produced the same 3-gate-fail pattern
(only minor pp-level changes in individual year metrics). Bug magnitude
~0.5-2pp/yr; alt-A's gap is ~130pp over 8 years.

**Anti-sibling NAV correlation result** is meaningfully cleaner post-fix:
residual_vs_spy dropped from 0.14-0.18 (pre-fix) to ≈0 (post-fix).
This is a directional reinforcement: alt-A is even more NAV-orthogonal
than the pre-fix measurement suggested.

---

## §8 Asks for user

Nothing required. T1a closes as informative null per roadmap v2 §9 path.
Continue with T1b (ConfirmationPatternStrategy Phase 2-3, est 1 week)
or in parallel start T1c (alt-B event-calendar PEAD+FOMC PRD scoping).

**Per memory `feedback_per_round_close_ritual`**: self-audit + todo
list with deps follows in commit message body.
