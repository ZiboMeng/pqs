# Phase-two strategy promotion

> Historical record notice (2026-07-20): the decision below remains immutable
> evidence of the Phase 2 policy outcome. It no longer grants current automatic
> promotion or capital authority. The active overlay resolves this strategy to
> `PAPER_OBSERVATION_ONLY / REVIEW_HOLD`; see
> `docs/memos/20260720-governance-reconciliation.md` and
> `config/research_governance.yaml`.

The frozen policy is `config/strategy_promotion.yaml`; the executable evaluator
is `core/research/phase2/promotion.py`; the fail-closed PAPER transition is
`core/research/phase2/paper_promotion.py`.

## Decision

`dual_index_growth_v1` is `PAPER_APPROVED` under policy
`phase2-paper-promotion-v1`. The finalizer evaluated 28/28 gates as PASS and
recorded evidence hashes at code commit `8d16d8a4966988dee2b1f1918d8810de4062e744`.
Approval does not enable LIVE.

Key final-holdout results:

| Metric | Actual | Required | Result |
|---|---:|---:|---|
| CAGR | 15.31% | >=5% | PASS |
| Sharpe | 0.934 | >=0.30 | PASS |
| Sortino | 1.281 | >=0.40 | PASS |
| MaxDD | -9.43% | <=23% magnitude | PASS |
| Calmar | 1.624 | >=0.30 | PASS |
| QQQ beta | 0.433 | <=0.90 | PASS |
| annual turnover | 2.371x | <=8x | PASS |
| best-year positive-PnL share | 57.48% | <=60% | PASS |

Validation robustness was frozen before holdout access: 6/7 positive annual
folds, 100% parameter-neighbor pass, 2x-cost Sharpe 0.724, delayed-signal
Sharpe 0.824 and worst configured stress drawdown -13.47%. Research controls
report zero unresolved P0/P1, no known lookahead, deterministic rerun, tested
cooldown/internal risk gate and LIVE disabled.

Operational gates passed a 250-session PAPER replay, clean broker reconciliation,
restart-identical NAV/cash/positions/orders, 250/250 idempotent report reuse,
zero unresolved orders, explicit risk veto, stale/missing fail-close and 16 fault
scenarios. The promotion registry stores every actual/required gate value and
SHA-256 for validation, final holdout and operational evidence.

The finalizer is idempotent. It refuses missing/false controls, wrong evidence
intervals, candidate identity drift, a non-frozen holdout, non-PAPER or
LIVE-enabled configuration, failed gate values, and conflicting prior records.

## Count limitation

Only one strategy qualified. No pairwise return/drawdown correlation or combined
portfolio promotion is reported because doing so with a rejected second member
would fabricate complementarity. Exact failure history is in
`docs/RESEARCH_FAILURES.md`.
