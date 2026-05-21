# P2 — Canonical Rank-Model Decision

**PRD**: `docs/prd/20260521-rerisk-and-ml-training-audit-prd.md` §1.5 / §12.3 Package P2
**Lineage**: `rerisk-and-ml-training-audit-2026-05-21`
**Decided**: 2026-05-21 (ralph-loop Round 16)

PRD §1.5 made it a binding P2 rule: there are three pre-existing
rank-model implementations; P2 must pick **one** canonical and migrate,
**never add a fourth**. This memo records that decision.

## 1. The three candidates

| # | path | what it is | usage |
|---|---|---|---|
| 1 | `core/research/ml/rank_model.py` + `core/research/ml/xgb_rank_model.py` | PRD #4 P4.1 rank stack — `RankModelProtocol`, `LinearBaselineRankModel`, `rank_ic`/`rank_ir` metrics, cross-sectional standardize/rank helpers; `XGBRankerRankModel` (xgboost.XGBRanker, per-bar query groups) | imported by `pipeline.py`, `artifact.py`, `walk_forward_rank_sign.py`, `walk_forward_sign_classifier.py`, `r29_acceptance`, `train_sign_classifier.py` — the pipeline spine |
| 2 | `core/ml/xgb_ranking.py` | Phase-1.6 ranking objectives — `XGBRankingModel` (native rank:pairwise/ndcg + qid groups), `LambdaRankICModel` (custom Rank-IC objective), `XGBQuintileModel` | imported by **1** place (`dev/scripts/chart_structure/phase2a_incremental_ic.py`) — near-orphan |
| 3 | `core/ml/xgb_alpha.py` | older alpha model | legacy |

## 2. Decision

**Canonical = candidate 1: `core/research/ml/rank_model.py` +
`core/research/ml/xgb_rank_model.py`.**

Rationale:

- It is the PRD #4 P4.1 deliverable and is **§9.0-compliant** (rank /
  percentile output ∈ [0,1], never a magnitude used as a size weight).
- It is **Protocol-based** (`RankModelProtocol`) — Linear baseline,
  XGBRanker, and a future LightGBM ranker all plug in behind one API.
- It is **tested** (`test_rank_model.py` + `test_xgb_rank_model.py`,
  20 tests) and is the module the whole walk-forward / acceptance
  pipeline already imports — making it canonical is zero-migration.
- It lives in `core/research/ml/`, the directory the loop protocol
  designates for the ML pipeline.
- `XGBRankerRankModel` already exposes `objective` (`rank:pairwise`
  default; `rank:ndcg` / `rank:map` supported) — so the §4.7 default
  of **`rank:ndcg` (LambdaMART)** for top-k selection is a one-line
  constructor argument, no new module needed.

## 3. What the other two become

- `core/ml/xgb_ranking.py` — **NOT promoted to canonical.** Its one
  unique asset is `LambdaRankICModel` (a custom objective that directly
  optimizes Rank-IC). Per PRD §4.7 that is an **A/B candidate** against
  `XGBRankerRankModel(objective="rank:ndcg")`, to be compared inside
  P2/P4 acceptance — not a parallel canonical path. The file stays as a
  research-objective module; P2 does not extend it.
- `core/ml/xgb_alpha.py` — **legacy, untouched.** Not part of the P2
  rank stack.

## 4. P2 build plan (consequences of this decision)

- `dev/scripts/ml/train_ranker.py` and `walk_forward_ranker.py` (the
  new P2 drivers) construct the ranker as
  `XGBRankerRankModel(objective="rank:ndcg")` and the
  `LinearBaselineRankModel` Pareto-floor — both from the canonical
  stack. No new model class is created.
- LightGBM parity = a new `LGBMRankerRankModel` implementing the SAME
  `RankModelProtocol` (a Protocol implementation, not a fourth
  competing stack).
- The `LambdaRankICModel` A/B is wired in P4 acceptance, optional.

**Gate (PRD §12.3 P2 "canonical rank-model path chosen, no fourth"):
satisfied by this memo.**
