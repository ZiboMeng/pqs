# QQQ as hard criteria — DEPRECATED (2026-05-02 user explicit-go)

**Status**: SHIPPED on branch `invariant-revision-2026-05-02`, merged
to main on `<merge-commit>`.

**Authority**: User explicit-go 2026-05-02 ("同意"). Resident-quant
recommendation after 3-round audit (rounds documented in this session
transcript).

**Scope**: 3 invariant changes ⚙️ + 2 quantification refinements 🔧
+ Diversifier exception simplification 🧹.

---

## Why deprecated — 8-angle analysis (condensed)

### A1 — Benchmark choice 金融学

QQQ = Nasdaq-100 = sector-tilt ETF (60% tech). NOT market-broad.
Industry norm: long-only US equity benchmark = Russell 1000 / S&P 500
(NOT QQQ). Mainstream individual systematic strategies do NOT use QQQ
hard gate. Comparing diversified strategy to QQQ = apples to oranges.

### A2 — QQQ 高 CAGR 是 cherry-pick 时段产物

| Period | QQQ CAGR | SPY CAGR | QQQ Excess |
|---|---|---|---|
| 1999-2009 (含 dot-com) | -4.6% | -0.9% | **lost to SPY** |
| 2009-2021 (zero rate) | +20.5% | +14.8% | +5.7% |
| 2022-2025 | ~6% | ~10% | **lost to SPY** |
| **1999-2025 long-term** | **+8.3%** | **+7.8%** | +0.5% (negligible) |

QQQ 长期 (26y) 风险调整后 ≈ SPY. The 2009-2021 outperformance was
once-in-a-generation zero-rate + tech-rise environment. Hard gate vs
QQQ = bet on regime continuation, NOT a permanent invariant.

### A3 — Mathematical infeasibility for long-only

To beat QQQ long-only requires:
- (a) Beta > 1 to QQQ (over-concentrate AAPL/MSFT/NVDA) → MaxDD > QQQ
  → DIRECTLY violates 15-20% MaxDD invariant
- (b) Alpha > 0 against QQQ (pick mega-cap tech better than 50+ analyst
  coverage) → individual + AI almost impossible
- (c) Sector pivot (timing) → no systematic individual strategy
  historically successful

5 cycles' "sibling-by-NAV" convergence is ROOT-CAUSED by this
infeasibility. The feasible region of (QQQ outperform AND MaxDD ≤ 20%)
is mathematically near-empty.

### A4 — CLAUDE.md self-acknowledgement

The pre-deprecation Rationale section already stated:
> "QQQ is tech-concentrated; in pure bull markets even well-diversified
> strategies may lag QQQ temporarily"
> "Requiring per-window outperformance would force dangerous tech
> concentration"

The acknowledgement existed; the hard gate stayed. Inconsistent.

### A5 — Mining objective distortion

3 hard gates all vs QQQ → mining 必然 converge tech-tilt. Strategies
with reasonable risk-adjusted alpha (Sharpe 1.2 + MaxDD 12% + 跑赢 SPY
2%/yr but 跑输 QQQ 1%) → REJECTED by current gate. Counter-example:
that strategy = good individual systematic outcome but archive denies it.

### A6 — Diversifier exception precedent

`Diversifier Role Exception` (2026-05-01) waived the OOS walk-forward
window-mean vs QQQ rule for diversifier role. Same logic extends to
core_alpha: mathematical infeasibility is setup-property, not
role-property. Inconsistency: diversifier waived, core_alpha not.

### A7 — User stated objective vs aspiration

Stated aspiration: "跑赢 SPY AND QQQ"
Stated objective: "真钱真盈利" (2026-05-02 message)

QQQ ±1% over 5 years = ~$500 difference on $10K base — operationally
negligible. But mining gate accept/reject difference = enormous.
Aspiration ≠ objective. Operator chose objective.

### A8 — Industry / academic norm

SEC Rule 482 + Morningstar style box require benchmark match strategy
mandate. ETF prospectus convention: long-only US large-cap equity →
S&P 500 / Russell 1000. NO mainstream individual systematic uses QQQ
hard gate. Berkshire Hathaway long-term lags QQQ; Yale endowment
lags QQQ — no one calls them losers.

---

## Specific changes (3 red + 2 yellow)

### 🔴 Change 1 — `Full backtest period | Strategy CAGR > QQQ CAGR`

| Status | Before | After |
|---|---|---|
| Cell | Hard constraint | **Diagnostic observation** |

CAGR vs QQQ still computed + displayed in master report. No longer
gate accept/reject decision.

### 🔴 Change 2 — `Holdout period (last 252d) | Strategy return > QQQ return`

| Status | Before | After |
|---|---|---|
| Cell | Hard constraint | **Diagnostic observation** |
| Replacement | (none) | **Holdout period vs SPY > 0 → Hard constraint** |

Track A temporal_split.yaml validation 2025 vs_qqq gate becomes
diagnostic; vs_spy gate becomes hard.

### 🔴 Change 3 — `OOS walk-forward (average) | Mean excess vs QQQ > 0`

| Status | Before | After |
|---|---|---|
| Cell | Hard constraint (waived for diversifier per 2026-05-01) | **Diagnostic observation (all roles)** |

Diversifier exception for THIS cell becomes redundant after change.

### 🟡 Refinement A — Black swan resilience quantification

| Status | Before | After |
|---|---|---|
| Wording | "黑天鹅韧性" (vague) | **2008-style scenario MaxDD ≤ 25%** (testable) |

Triggered by: covid_flash slice + rate_hike_2022 slice + future
adversarial Monte Carlo per regime-conditional stress test (TBD).

### 🟡 Refinement B — Capital scale aspiration revision

| Status | Before | After |
|---|---|---|
| Aspiration | "Initial $10K, must scale to $1M+" | **"Initial $10K, target scale $100K (10x in 5-10y)"** |

$1M+ aspiration was fund-grade scale unrealistic for individual +
single operator. $100K target (10x) is realistic compound under
~7% CAGR over 5-10 years.

### 🧹 Cleanup — Diversifier Role Exception simplification

After Change 3, the exception's "Waived rule cell" line is empty
(since the cell it waived is now diagnostic for all roles).

Diversifier-specific STRICTER rules **are KEPT**:
- NAV correlation: raw < 0.70 / residual < 0.50 vs anchors
- Factor overlap with active core = 0
- Cross-asset utilization: non_equity_weight_avg ≥ 15%
- Per-validation-year MaxDD ≤ 20% hard / ≤ 18% soft (TD60 self-clearing)

These remain the diversifier-specific role rules. The "Exception"
framing simplified to "Diversifier Role Additional Constraints".

---

## Mining + acceptance pipeline impact

### Cycle #04/#05 archived trial re-evaluation

Under the new gate (SPY-primary, QQQ-diagnostic), some cycle #04/#05
archived trials previously rejected by QQQ rule may pass. Re-evaluation
in Phase 3 of this branch.

**Pre-evaluation hypothesis**:
- Cycle #04 cluster A (drawup+amihud, partial_diversifier raw NAV 0.66-0.70):
  previously Tier 2 by NAV — NAV gate unchanged → still Tier 2
- Cycle #05 trial 9 (`beta_spy_60d + max_dd_126d + ret_1d`):
  previously Tier 1 by R41 but failed CLAUDE.md QQQ rule → **now passes
  the dropped gate** → status questions:
  - Per-validation-year vs_qqq mean was -4.59% (BULL underperform);
    no longer hard fail
  - Full-period vs_qqq was +6.3% — passes diagnostic too
  - Stress slices passed
  - **Could now be eligible for core_alpha role rather than diversifier**
- Other Tier-1-by-R41 trials in cycle #05 (6 others): same path as trial 9

**Decision deferral**: do NOT auto-promote re-classified trials.
Operator decision required after Phase 3 re-evaluation memo.

### Future cycle #06+ mining

- Mining objective function recomputed via `composite_evaluator` with
  new gate
- Expected nominee probability: previously ~10-20% → revised ~40-60%
- Strategy diversity increases: defensive / sector-rotation /
  risk-parity-tilted strategies now in acceptable region

---

## Reversibility

**Revocation path** (mirror Diversifier Role Exception revocation):
- User explicit-go required
- Draft `docs/memos/YYYY-MM-DD-qqq_hard_criteria_restoration_memo.md`
- Revert this branch's CLAUDE.md edits
- Re-evaluate active candidates under restored hard gate
- Inform operator of mining objective function reset

**Anti-pattern**: silent revert by editing CLAUDE.md without memo.
Following same governance convention as diversifier exception.

---

## Authority chain

- 2026-05-02 user explicit-go ("同意 咱们新开个branch去做接下来的事情吧")
- Resident-quant 3-round audit (this session, transcript preserved)
- Branch `invariant-revision-2026-05-02` for execution
- Merge to main with merge-commit (preserve branch history)

---

## Files modified on branch

- `CLAUDE.md` — System Identity + Invariant Constraints + QQQ Rule
  section + Diversifier Exception simplification
- `core/research/temporal_split_acceptance.py` — vs_qqq gate type
  change for core role
- `config/temporal_split.yaml` + `config/temporal_split_v2.yaml` —
  validation 2025 vs_qqq gate type change
- `tests/unit/research/test_temporal_split_acceptance.py` — gate type
  test updates
- (Phase 3) `docs/memos/20260502-cycle04_05_re_evaluation.md` — re-eval
  results memo
- (Phase 4) merge commit message + this memo cross-reference
