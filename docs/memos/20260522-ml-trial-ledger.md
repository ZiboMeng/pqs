# ML Trial Ledger — §9.6 selection-bias accounting

**PRD**: `docs/prd/20260522-rerisk-ml-audit-remediation-supplement-prd.md` §2 S5
**Lineage**: `rerisk-ml-audit-remediation-2026-05-22`
**Ledger file**: `data/audit/ml_trial_ledger.json`

## Why this exists

Audit finding O1: `dev/scripts/ml/portfolio_acceptance.py` hardcoded the
DSR trial count (`--n-trials` default 5). The Deflated Sharpe Ratio's
whole job is the **selection-bias correction** — it deflates an observed
Sharpe by how many configurations were examined to find it. A hardcoded,
understated `n_trials` makes DSR under-deflate, which would wave through
a strategy that is merely the luckiest of a wide search.

S5 fixes this: `n_trials` is now sourced from a **persisted, auditable
trial ledger** — `data/audit/ml_trial_ledger.json` — and DSR uses
`n_trials = len(ledger["trials"])`.

## What the ledger records

One entry per **distinct model / config variation actually examined** to
land on the promoted rank-to-portfolio path (`path_D_xgb_ranker_ndcg`).
As of 2026-05-22 the ledger holds **10 trials**:

| kind | trials |
|---|---|
| baseline | `path_A_non_ml_composite` |
| model family | `LinearBaselineRankModel`, `XGBRanker`, `LGBMRanker` |
| objective | XGBRanker `rank:pairwise`, `rank:ndcg` |
| mapping mode | `top_k_capped`, `score_proportional_clipped`, `score_vol_scaled` |
| risk scaling | vol-target `0.10`, `0.15` |

Each entry carries the ralph-loop round it was run in, so the count is
traceable, not asserted.

## The maintenance rule

**Any new config that informs the path-D selection — a new model
family, objective, mapping mode, feature set, or risk overlay actually
run — MUST append a trial to the ledger.** Otherwise DSR silently
under-deflates again. The ledger's `n_trials_note` field states this;
`portfolio_acceptance.py` reads `len(trials)` at run time so the
correction tracks the ledger automatically.

## How it feeds the §9.6 controls

- **DSR**: `deflated_sharpe_ratio(promoted_path_daily_returns,
  n_trials=len(ledger))` — consumes a real **return series** (not
  rank-IC; the rank-IC misuse was the other half of O1, fixed in the
  rank-walk-forward driver via `_rank_ic_significance`).
- **PBO**: run over a **model-diverse** sweep (composite + 3 genuinely
  different model families), not cosmetic mapping re-skins of one
  ranker — a collinear sweep gives an optimistically low PBO (verified:
  0.135 collinear → 0.333 model-diverse on the 2015-2017 smoke).

## Honest caveat

The ledger is **curated by hand** from the ralph-loop log — it is the
honest enumeration of what was run, but it is not auto-generated from
run artifacts. A future enhancement is to derive it mechanically from
the `data/audit/ml_rank_portfolio_acceptance_*.json` corpus. Until then,
the maintenance rule above is the discipline that keeps it correct.
