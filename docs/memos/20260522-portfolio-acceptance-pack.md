# Portfolio Acceptance Pack — rank-to-portfolio (P4)

**PRD**: `docs/prd/20260521-rerisk-and-ml-training-audit-prd.md` §9 / §12.3 P4
**Supplement**: `docs/prd/20260522-rerisk-ml-audit-remediation-supplement-prd.md` S7
**Written**: 2026-05-22 (supplement ralph-loop Round 24)

This is the §12.3-P4-named acceptance pack — the human-readable summary
of the rank-to-portfolio acceptance. Machine-readable artifacts:
`data/audit/ml_rank_portfolio_acceptance_*.json`.

## 1. The paths

| path | what | where |
|---|---|---|
| A | non-ML Stage-1 cycle06 composite → score-to-weight → backtest | `dev/scripts/ml/portfolio_acceptance.py` |
| D | XGBRanker (rank:ndcg) ranker → score-to-weight → backtest | same harness |
| B | ML sign-veto sidecar | `dev/scripts/ml/r29_acceptance_r_ml_a_vs_b.py` |
| C | sign sidecar + partial rebalance | same (r29) |

**Honest scoping note (S7):** paths A and D — the load-bearing
rank-to-portfolio comparison — run in the unified `portfolio_acceptance.py`
harness on one walk-forward fold schedule. Paths B and C (the sign-veto
sidecar, PRD #4 P4.5) remain in the older `r29_acceptance_r_ml_a_vs_b.py`
and were NOT ported into the unified harness. Reason: B/C are a
different mechanism (a per-name veto stage, not a ranker-to-portfolio
allocator) and the sign sidecar is not the promoted path; porting them
is a future enhancement, recorded here rather than silently dropped.

## 2. Latest acceptance result

Train-only window 2012-2017, 3-fold walk-forward, concatenated OOS
2015-2017, monthly rebalance, full constraint set (turnover cap +
exit_policy signal-decay + turnover-band), embargo = trading-bar exact
(audit C1 fix), 30 bps cost:

| path | net Sharpe @30bps | MaxDD | cum |
|---|---|---|---|
| A — non-ML composite | ~0.25–0.73 | ~ −12 % | — |
| D — XGBRanker rank:ndcg (plain) | ~0.81–1.18 | ~ −19 % | — |

(Ranges span the constraint-set evolution across supplement rounds; the
definitive numbers come from the S6 validation-partition run — see §4.)

**§9.6 overfit control** (latest, model-diverse sweep):
- DSR(promoted) = 0.806 — deflated for `n_trials = 10` sourced from the
  persisted trial ledger (`data/audit/ml_trial_ledger.json`).
- PBO = 0.333 over a model-diverse sweep (composite + XGB + Linear +
  LGBM) — below the 0.5 red-flag threshold.

## 3. Verdict

**PASS** under the §9.3 acceptance criteria as relaxed by the
supplement (`SUPPLEMENT-2026-05-22`): path D beats the non-ML baseline
on net Sharpe, and path-D MaxDD is within the 15-20 % MaxDD invariant
(the criterion is "MaxDD ≤ 20 %", not "MaxDD ≤ baseline" — §9.3).

**Honest caveat:** this verdict is on a TRAIN-ONLY smoke window. It is
NOT the §12.6-unlock verdict — that requires the S6 validation-partition
run. The numbers also sit close to the 20 % MaxDD line, so S6 carries a
real FAIL risk (flagged repeatedly in the supplement log).

## 4. Promoted-config decision — DEFERRED to S6

§〇#5 open item ②: which path-D config is the promoted one —

- **D plain** (top_k_capped, no vol-target overlay): highest Sharpe /
  cum, MaxDD ~ −19 % (closest to the 20 % line).
- **D vol-target 0.10**: MaxDD ~ −14 % (comfortable inside invariant),
  lower Sharpe / cum.

This is **deliberately not decided here.** Per prompt §〇 (2026-05-22
ratification), the promoted-config choice is deferred until the **S6
real-OOS validation** result is in — the validation-partition MaxDD
(which includes the 2018 bear year) is the number that should drive the
plain-vs-vol-target choice, not the train-only smoke.

## 5. Status

- §12.3 P4 named output: this pack satisfies the
  `portfolio-acceptance-pack.md` deliverable.
- The companion `ml_sign_portfolio_acceptance_*.json` (paths B/C) is
  produced by `r29_acceptance_r_ml_a_vs_b.py` — see §1 scoping note.
