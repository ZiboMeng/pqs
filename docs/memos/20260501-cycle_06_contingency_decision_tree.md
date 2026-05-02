# Cycle #06 Contingency Decision Tree (Pre-TD20 Placeholder)

**Status**: PLACEHOLDER — branches keyed by Trial 9 forward RED root cause.
Branch contents to be filled in **after TD20 attention check** (~2026-06-01)
when first attribution data arrives. Not pre-locked because the right
cycle #06 axis depends on what *actually* breaks in forward, not what
Option A historical prior estimated.

**Authority**: parent PRD `prd/20260501-two_stage_allocation_architecture_prd.md`
§7.1 + Option A closeout `memos/20260501-trial9_historical_walkforward_prior_close.md`
§4.4 (RED reasons distribution).

**Forward state**: Trial 9 forward observation runs `2026-05-04` →
`~2026-07-30` (60 trading days). TD20/TD40/TD60 milestones produce
attention reports; this decision tree consumes them.

**Stop rule (PRE-COMMITTED)**: if Trial 9 TD60 = RED AND no obvious axis
fix from this tree, **NO cycle #06 mining** — pivot to strategic review
(see Option E in Cycle #05 closeout / parent PRD §11 Option E).

---

## Decision tree (branches by RED root cause)

### Branch A: RED dominated by `trial9 60d max_dd > 10%` [Option A: 39% of RED]

**What it means**: Trial 9 single-candidate alpha failed under forward
conditions. Drawdown deeper than D10c soft-warn 18% maxdd evidence
band suggested. Trial 9 spec (`beta_spy_60d + max_dd_126d + ret_1d`)
under-defenses against the actual forward regime.

**Cycle #06 axis hypothesis**: alpha-axis redesign — replace one or more
of the 3 anchor factors. Core question: which factor failed?

**Pre-TD20 placeholder for branch contents** (fill after attention data):

- Identify which of the 3 factors most degraded between in-sample (cycle
  05 archive) and forward
- Candidate replacement factors from `RESEARCH_FACTORS` pool that satisfy:
  - Long-only construction compatibility (no shorts)
  - Cap_aware_cross_asset reachability (computes on bonds/cash)
  - Factor-overlap with active core ≤ 1 (anti-sibling)
  - Family diversity (don't replace Family B with another Family B)
- Construction unchanged: keep cap_aware_cross_asset + monthly + top-N
- Mining trial budget: 200 (same as cycle #05)
- Pre-registration: criteria yaml MUST predate any mining trial
  (anti-narrative discipline)

**Anti-pattern guards**:
- Do NOT relax `max_dd_per_year ≤ 20%` hard fail (would be
  result-driven yaml softening = research integrity violation)
- Do NOT add a 4th factor to "balance" — cardinality=3 stays locked
  (parent PRD §6.2 anti-loophole)
- Do NOT switch construction to non-cap_aware_cross_asset (would lose
  the diversifier role's structural property)

---

### Branch B: RED dominated by `residual_corr > 0.6` vs anchor [Option A: 50% of RED]

**What it means**: Trial 9 lost diversifier property — its residual
NAV (after stripping market beta) became correlated with RCMv1 or
Cand-2. Most likely cause: the same factor families are exposed to the
same regime stress.

**Cycle #06 axis hypothesis**: universe / horizon / construction-axis
redesign — keep alpha factors similar but change WHEN or WHERE they
trade so the residual diverges.

**Pre-TD20 placeholder for branch contents** (fill after attention data):

- Identify WHICH anchor's residual_corr blew out (RCMv1 vs Cand-2 vs both)
- If both: structural same-regime issue → universe expansion candidate
  (e.g. add international ETFs / commodities not in cycle04+05 universe)
- If only one: factor-overlap with that specific anchor → swap one
  factor that contributes most to the overlap
- Cadence experiment: weekly cadence (not monthly) — different rebalance
  timing produces different exposure trajectories even with similar
  factors
- Universe experiment: add 2-3 sector ETFs not in cycle04+05 (XLF / XLE /
  XLU / EFA) to break the equity-sector concentration that may drive
  shared regime exposure
- Construction unchanged otherwise: cap_aware_cross_asset stays

**Anti-pattern guards**:
- Do NOT swap to long/short construction (violates `no-short` invariant)
- Do NOT abandon factor-overlap rule (== 0 vs active core); if
  operational evidence says factor-overlap rule is broken, that's a
  separate parent-PRD revision, not cycle #06 inline change

---

### Branch C: RED dominated by `combo Sharpe AND MaxDD both worse` [Option A: 22% of RED]

**What it means**: Trial 9 ADDED to RCMv1+Cand-2 portfolio is *worse*
than RCMv1+Cand-2 alone — on every dimension. This is the most severe
RED type because the diversifier hypothesis itself fails.

**Cycle #06 axis hypothesis**: NONE. Strategic review required.

**Pre-TD20 placeholder for branch contents** (fill after attention data):

- Confirm no other sub-cause masking (e.g., Branch A + B both partially
  triggered along with C)
- If C is dominant + isolated: cycle #06 mining cannot help (the
  diversifier framing itself was wrong for forward regime)
- Likely strategic options (parent PRD §11 Option E):
  - Demote Trial 9 to legacy_decay_verification, freeze fleet expansion
  - Re-evaluate parent PRD diversifier-role definition (does CLAUDE.md
    QQQ-rule waiver still apply? Should it?)
  - Fall back to cycle #05 strict mode (no diversifier exception, only
    core_alpha mining)
  - User explicit-go required for any fleet-architecture pivot

**Anti-pattern guards**:
- Do NOT spin up cycle #06 to "find a better diversifier" without first
  understanding why the current diversifier hypothesis broke — that's
  research-as-flailing
- Do NOT propose adding Trial 10/11/12 in parallel (would compound the
  unknowns)

---

### Branch D: Mixed RED (multiple sub-causes triggered)

**What it means**: TD60 RED comes from a combination of A + B (and
possibly C). Most likely outcome empirically (Option A 96 valid windows
showed multiple triggers per RED window).

**Cycle #06 axis hypothesis**: rank by *severity* (which trigger
breached the threshold by most), not by *count* (how many triggered).

**Pre-TD20 placeholder for branch contents** (fill after attention data):

- Quantify each sub-cause severity:
  - Branch A severity = `trial9_max_dd - (-0.10)` (negative = breach
    magnitude)
  - Branch B severity = `max(residual_corr_anchors) - 0.6` (positive =
    breach magnitude)
  - Branch C severity = `combo_cum_ret` if negative, else 0
- Select branch corresponding to LARGEST severity for cycle #06 axis
- If two severities are within 20% of each other, the tree devolves to
  Branch C (strategic review) — too many simultaneous breaks for a
  single mining axis to fix

---

### Branch GREEN/YELLOW (no RED)

**What it means**: Trial 9 forward TD60 succeeded (GREEN) or partially
succeeded (YELLOW). Not a "contingency" but the happy path.

**Cycle #06 actions**:

- GREEN: trigger Phase C-PRD-2 implementation (parent PRD §11). Cycle
  #06 still on hold — fleet now has 1 active diversifier; need to
  complete C-PRD-2 + observe combined NAV before pursuing cycle #06.
- YELLOW: continue Trial 9 forward to TD90/TD120 (parent PRD §7.1
  YELLOW path). Cycle #06 NOT triggered. Re-evaluate at TD120.

---

## TD20 attention check action (fill schedule)

When `dev/scripts/forward/attention_check.py` runs at TD20 (~2026-06-01):

1. Read attention report JSON output
2. Identify which RED-precursor signal is most prominent (even if not
   yet at threshold):
   - max_dd already at -8% to -10%? → flag Branch A precursor
   - residual_corr already at 0.55-0.65? → flag Branch B precursor
   - combo NAV negative even with 20 days observed? → flag Branch C
3. Fill in branch placeholder for the dominant precursor (research
   factor swap candidates / universe expansion list / etc.)
4. Re-fill at TD40 if precursor signal changes
5. At TD60, classify RED root cause (A/B/C/D) and execute pre-filled
   branch — NO new branch design at TD60

This is the **pre-commit-then-execute** discipline that prevents
narrative-driven retroactive contingency design.

---

## Reversibility

This entire decision tree is documentation, not code. Reversibility
trivial — edit the file. The substance (cycle #06 mining) is governed
by:

- Pre-registered criteria yaml (mandatory before mining starts; CLAUDE.md
  Phase E governance)
- User explicit-go for cycle #06 launch (per current freeze policy)
- Sealed 2026 panel still untouched (sealed_ledger.py M5
  fail_closed_on_repeat enforced)

No automated trigger from this tree. All mining decisions remain manual.

---

## Related

- Parent PRD: `prd/20260501-two_stage_allocation_architecture_prd.md`
- C-PRD-2 spec draft: `prd/20260501-c_prd_2_dd_throttle_role_caps_DRAFT.md`
- Option A prior: `memos/20260501-trial9_historical_walkforward_prior_close.md`
- Diversifier decision memo: `memos/20260501-diversifier_role_decision.md`
- Cycle #05 closeout: `memos/20260501-track_c_cycle_2026-05-01-05_close.md`
- Forward attention check: `dev/scripts/forward/attention_check.py`
- Sealed ledger gate: `core/research/sealed_ledger.py` M5
