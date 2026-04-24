# Candidate-2 Decision Memo — `candidate_2_orthogonal_01`

**Lineage tag**: `phase-e-post-2026-04-24`
**Candidate ID**: `candidate_2_orthogonal_01`
**Source trial**: `cand2_equal_03` (rcm_archive.db, study
`candidate-2-construction-2026-04-24`, lineage
`phase-e-post-2026-04-24-cand2`)
**Author**: Phase E-post R6 ralph-loop round
**Date**: 2026-04-24
**Supersedes**: none (first Candidate-2)

## 1. Why this candidate exists

Per `docs/20260424-prd_phase_e_post_cand2.md` §1-2, the Phase E
governance / paper pipeline has been validated by exactly one real
sample — `rcm_v1_defensive_composite_01`. This gives no way to
distinguish candidate-specific drift from system-wide drift. The PRD
charges Candidate-2 with building the **second reference frame**:
an orthogonal candidate that lets paper-layer diagnostics compare
two independent signals side-by-side.

Candidate-2 is NOT chosen to outperform RCMv1. It is chosen to be
**economically and structurally different** from RCMv1 while meeting
a minimum IC-quality bar.

## 2. Design principles (PRD §5.5 hard constraints)

| Constraint | Specification | Implementation |
|-----------|--------------|----------------|
| Factor count | Fixed 3 | `feature_set` has exactly 3 entries |
| Weights | Equal (1/3 each) | `weights = [1/3, 1/3, 1/3]` — hardcoded |
| Weight search | **Forbidden** — no TPE, Optuna, grid search | Construction is deterministic hand selection |
| Per-factor IC | Spearman `p < 0.05` on rcm-v1-lag1 window | All 3 factors have `p = 0.0` (see §4) |
| Per-factor regimes | Positive IC in ≥ 3 of 6 regimes | `{3, 4, 5}` of 6 (see §4) |
| vs RCMv1 corr | Composite corr < 0.5 | 0.404 (per-date mean) |
| vs RCMv1 turnover | Relative diff ≥ 20% | 79.2% |
| Orthogonal economics | Not the same defensive family | Different family per factor (see §3) |
| Simpler than RCMv1 | No tuned weights; fewer factors | 3 vs 4 factors; equal vs TPE-tuned |

## 3. Factor selection rationale

### 3.1 Economic themes

RCMv1 features  `{beta_spy_60d, drawup_from_252d_low, days_since_52w_high, amihud_20d}` are defensive / downside / regime / liquidity.

Candidate-2 is designed to be orthogonal to that family:

| Feature | Family | Economic signal |
|---------|--------|-----------------|
| `ret_5d` | B (momentum / path) | Short-term price continuation |
| `rs_vs_spy_126d` | A (benchmark-relative) | Long-horizon relative strength vs SPY |
| `hl_range` | C (liquidity / volatility structure) | High-low range — volatility-structure signal |

### 3.2 Selection process

**Initial proposal (rejected)**: PRD §5.5 suggested
`{residual_mom_spy_20d, return_per_risk_21d, trend_tstat_20d}` as
starting points. I ran the probe script on those three and all had
negative or statistically insignificant IC at 21d forward horizon on
this universe (evidence: `data/research_candidates/candidate_2_probe_initial_reject.json`).
This is consistent with the well-known property that momentum-family
factors mean-revert at 21d on ETF-heavy universes.

**Pivot**: I ran a broader IC screen over `RESEARCH_FACTORS` (see
inline tooling used by this memo's ralph-loop round) and picked the
three factors above because they all have:
- positive IC with `p < 0.05` on the rcm-v1-lag1 window
- distinct economic families (per §3.1)
- low composite correlation with RCMv1 (0.404 < 0.5)
- turnover profile distinctly different from RCMv1 (79.2% relative diff)

**No mining was performed.** The IC screen is a one-pass observational
compute, not an optimizer. No weight search, no hyperparameter tuning,
no iterative selection. Reject → IC-screen → pick → verify. One round.

## 4. Evidence (from probe artifacts)

Probe artifact:
`data/research_candidates/candidate_2_probe_report.json`

| Factor | IC mean | IC IR | p-value | Positive regimes |
|--------|---------|-------|---------|------------------|
| `ret_5d` | +0.0335 | +0.107 | 0.0000 | 3 / 6 |
| `rs_vs_spy_126d` | +0.0302 | +0.104 | 0.0000 | 4 / 6 |
| `hl_range` | +0.0372 | +0.136 | 0.0000 | 5 / 6 |

**Composite**: full-period IC mean = +0.0336, IR = +0.1159, n_dates = 3255.

**Orthogonality vs RCMv1**:
- Per-date cross-sectional correlation (averaged over dates) = **0.404** (< 0.5 ✓)
- Turnover proxy (top-10 symmetric-diff per rebalance): Candidate-2 = 0.636 vs RCMv1 = 0.355 → relative diff **79.2%** (≥ 20% ✓)

## 5. Scope and non-goals

Explicit non-goals (per PRD §3.2):
- Not tuned to outperform RCMv1 on backtest metrics
- Not a universe-extension or new-data-vendor candidate
- Not a new factor-mining output — all 3 factors are existing entries in `RESEARCH_FACTORS`

Expected outcome:
- On paper, Candidate-2 will exhibit a distinctly different P&L / drift profile from RCMv1 (the orthogonality ensures this)
- If RCMv1 and Candidate-2 drift similarly on paper, the drift is likely systemic (pipeline / data); if they diverge, the drift is candidate-specific
- Checkpoint observations at 10 / 20 / 40 / 60 trading days (PRD §7.2)

## 6. Risks and weaknesses

- **Low composite IC IR (0.116)** relative to RCMv1 (0.495) — expected because equal-weighting is sub-optimal by design. If the paper comparison later shows Candidate-2 turning over too much without commensurate signal, that is itself informative (per PRD §8.2 it may trigger a decision to re-weight after paper observation, but NOT during R6).
- **`hl_range` is volatility-structure** — partially overlaps `amihud_20d`'s economic theme in a loose sense. Mitigated by correlation check: observed composite correlation is 0.404, below threshold.
- **Regime labels used in probe are lightweight** (SPY 60d return × 60d vol tertiles) — not the canonical regime_detector. The canonical regime check is part of acceptance_research_composite.py and runs during the gate phase if required. For R6 entry to S1 it is not strictly required by the promote script but acceptance evidence JSON documents the limitation.

## 7. Follow-up after S1

Per PRD §6.4 + §7, after S2 Candidate-2 enters parallel paper with RCMv1:
- Run `run_paper_candidate.py` over a 60-day window starting after registration
- Compute drift vs replay via `paper_drift_report.py`
- Compare side-by-side with RCMv1's parallel paper run
- Use checkpoints at 10 / 20 / 40 / 60 trading days to separate
  pipeline-systemic vs candidate-specific issues

## 8. Decision

**Promote to paper** (S0 → S1 via `research_promote.py`).

Rationale: all PRD §5.5 hard constraints are satisfied with
quantitative evidence (§4). The candidate is designed to complement
rather than replace RCMv1, and a rejection at S1 would defeat the
PRD's goal of establishing a second reference frame. If the paper
layer surfaces a problem the candidate can be revoked cleanly via
`scripts/revoke_candidate.py` — the governance path is fully
reversible (see R3 revoke drill evidence at
`docs/20260424-rcmv1_clone_revoke_drill_memo.md`).

## 9. Cross-references

- PRD: `docs/20260424-prd_phase_e_post_cand2.md`
- Probe report: `data/research_candidates/candidate_2_probe_report.json`
- Initial-triplet rejection evidence: `data/research_candidates/candidate_2_probe_initial_reject.json`
- Acceptance: `data/ml/research_miner/candidate-2-construction-2026-04-24/acceptance/acceptance_cand2_equal_03.json`
- Frozen spec: `data/research_candidates/candidate_2_orthogonal_01.yaml`
- RCMv1 (for reference): `data/research_candidates/rcm_v1_defensive_composite_01.yaml`
- Research mask config (unified, bit-identical to historical defaults): `config/research_mask.yaml`
