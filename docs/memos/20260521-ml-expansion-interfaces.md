# ML Expansion Interfaces

**PRD**: `docs/prd/20260521-rerisk-and-ml-training-audit-prd.md` §12 Package P6
**Lineage**: `rerisk-and-ml-training-audit-2026-05-21`
**Written**: 2026-05-22 (ralph-loop Round 32)

P6 makes future enrichments **additive** — a new data family or model
type plugs into the contracts built in P0–P5 without an architectural
rewrite and without touching the core promotion logic. This memo names
the extension hook for each foreseen enrichment.

## 1. The four contracts a new family plugs into

P0–P5 produced four stable contracts. Any enrichment attaches by
extending these — never by editing core logic:

| contract | file / module | extension point |
|---|---|---|
| source | `config/ml_sources.yaml` | add a tier under `source_tiers` (the schema already carries an `optional` slot + per-tier PIT rule) |
| label | `config/ml_labeling.yaml` | reuse a `label_mode`, or add one to `label_modes` (schema_version bump) |
| allocation | `config/ml_allocation.yaml` | unchanged — a score is a score; `score_to_weight` maps any rank panel |
| acceptance | `dev/scripts/ml/portfolio_acceptance.py` | a new feature set / path; `portfolio_metrics` + `_overfit_control` are family-agnostic |
| model | `RankModelProtocol` (`core/research/ml/rank_model.py`) | a new class implementing the Protocol (LGBMRankerRankModel is the precedent) |
| freeze | `core/research/ml/freeze_bundle.py` | hashes whatever config layers are present — a new tier is hashed automatically |

## 2. Extension hook per enrichment family

### 2.1 Text / filing / transcript features
- **source**: a `text` tier in `ml_sources.yaml` with a PIT rule
  `available_at = filing_timestamp` (filings are point-in-time by SEC
  timestamp; transcripts by call end-time).
- **label**: reuse `cross_sectional_residual_rank` — text features are
  just more columns in the feature panel.
- **acceptance**: a new feature-set name passed to the harness.
- No core change. PIT discipline (P0) is the only hard requirement.

### 2.2 Options features
- **source**: an `options` tier; PIT rule `available_at = quote_close`.
- Surface metrics (IV skew, term structure, put/call) become feature
  columns. SQQQ-blacklist / TQQQ-SOXL invariants are universe-level
  (CLAUDE.md) and unaffected — options features are signals, not
  instruments traded.
- **label / allocation / acceptance**: unchanged.

### 2.3 Intraday features
- **source**: an `intraday` tier. **Hard boundary**: 60m/30m are the
  validation-layer primary; 15m is a *decision-input* only (entry/exit/
  sizing/veto), never an intraday-alpha-mining or validation layer
  (CLAUDE.md invariant, `docs/memos/20260519-15m_decision_input_boundary_revision.md`).
  A new intraday feature tier MUST declare its timescale role and a 15m
  feature may only feed construction/execution timing.
- **label / allocation / acceptance**: unchanged.

### 2.4 Sequence-model embeddings
- **model**: a sequence model (e.g. a temporal encoder) is a new class
  implementing `RankModelProtocol` — `fit(features, labels)` /
  `predict_rank(features) → rank ∈ [0,1]`. The §9.0 invariant (output
  is rank, never a magnitude size-weight) is enforced by the Protocol.
- Embeddings may be precomputed and fed as feature columns, OR the
  sequence model IS the ranker. Either way: same Protocol, same
  walk-forward driver, same acceptance harness.
- §4.11 stacking-leakage rule applies if an embedding feeds a
  meta-model — train only on OOS base predictions.

## 3. Invariants every supplement inherits (never overrides)

A future supplement PRD for any family above is **narrower** than this
master PRD and may not override its hard controls:

- temporal_split discipline — train / validation / sealed partitions.
- §9.0 — ML output is rank / sign-vote, never continuous magnitude
  as a size weight.
- §9.6 — any cross-fold / cross-config selection passes DSR / PBO.
- P5 freeze + drift — a new tier is hashed into the freeze bundle
  automatically; promotion still requires P4 acceptance PASS.
- long-only / no-margin / no-short; SQQQ blacklist; benchmark = SPwI
  hard, QQQ diagnostic — all CLAUDE.md invariants stand.

## 4. Gate (PRD §12.3 P6)

- **every new source family attaches without changing core promotion
  logic** — satisfied: §1 shows all attachment is via config-tier
  extension or a Protocol implementation; `freeze_bundle.check_drift`
  and the acceptance harness are family-agnostic.
- **supplements are narrower than the master PRD and never override
  its hard controls** — satisfied: §3 enumerates the inherited
  invariants a family-specific supplement must respect.
