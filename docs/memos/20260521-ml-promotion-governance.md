# ML Promotion Governance

**PRD**: `docs/prd/20260521-rerisk-and-ml-training-audit-prd.md` §12 Package P5
**Lineage**: `rerisk-and-ml-training-audit-2026-05-21`
**Written**: 2026-05-22 (ralph-loop Round 30)

This memo connects the validated ML stack (Packages P0–P4) to the
project's **existing** promotion / paper / forward governance. It does
NOT create a parallel promotion system — it defines the *freeze bundle*
and *demotion triggers* that let an ML candidate ride the same
`core/research/forward/` observation machinery every other candidate
uses (daily ritual, `docs/forward_observation_log.md`, Track-A gates).

## 1. What the ML stack produces

By the end of P4, a validated ML path is a chain of artifacts:

| layer | artifact / config | package |
|---|---|---|
| source contracts | `config/ml_sources.yaml` | P0 |
| label spec | `config/ml_labeling.yaml` | P1 |
| feature set | the named factor bundle (e.g. cycle06) | P1/P2 |
| model | `ModelArtifact` (`core/research/ml/artifact.py`) | P2 |
| allocation | `config/ml_allocation.yaml` | P3 |
| acceptance | `data/audit/ml_rank_portfolio_acceptance_*.json` | P4 |

A promotion decision must reference **all six** — not just the model.

## 2. The freeze bundle

A validated ML candidate is frozen as **one reproducible config
bundle** — a single JSON recording the SHA-256 of each layer above:

```
ml_freeze_bundle = {
  bundle_id, frozen_utc, lineage,
  source_contract_hash   : sha256(config/ml_sources.yaml),
  label_config_hash      : sha256(config/ml_labeling.yaml),
  allocation_config_hash : sha256(config/ml_allocation.yaml),
  feature_set            : {name, factor_names, factor_registry_hash},
  model_artifact_hash    : sha256(<ModelArtifact .pkl>),
  acceptance_ref         : <ml_rank_portfolio_acceptance_*.json path>,
  acceptance_verdict     : PASS|FAIL,
  temporal_split_hash    : sha256(config/temporal_split.yaml),
}
```

Freezing rule: a bundle may be frozen **only** when the P4 acceptance
verdict is PASS *and* the §9.6 overfit control is recorded (DSR + PBO
in the acceptance artifact). The builder is
`dev/scripts/ml/freeze_ml_bundle.py` (P5 sub-step); it writes
`data/audit/ml_freeze_bundle_<id>.json` — a version-controlled path,
since a frozen bundle is a durable promotion record.

Reproducibility: any future run can re-hash the six components and
compare to the bundle — identical hashes ⇒ the validated spec is
being reproduced exactly.

## 3. Drift detection on forward runs

Each forward observation of a promoted ML candidate re-computes the
six hashes and compares them to the frozen bundle. A mismatch is a
**drift flag** (diagnostic — a human adjudicates, no auto-kill, per
the project's PBO-red-flag precedent):

| frozen field changed | drift class |
|---|---|
| `source_contract_hash` | data-contract drift |
| `label_config_hash` | label drift |
| `allocation_config_hash` | allocation drift |
| `feature_set` / `factor_registry_hash` | factor drift |
| `model_artifact_hash` | model drift (unexpected retrain) |
| `temporal_split_hash` | split drift (holdout integrity risk) |

## 4. Demotion triggers

A promoted ML candidate is **demoted** (back to research / evidence
status) when any of the following is observed on the forward path:

1. **Forward drift** — realized forward Track-A metric falls below the
   frozen acceptance verdict's basis by more than the TD60 band (reuse
   the existing forward-observation TD60 self-clearing logic).
2. **Data-contract breach** — `source_contract_hash` mismatch, OR a
   source tier violates its PIT rule in `config/ml_sources.yaml`.
3. **Allocation instability** — realized portfolio turnover, single-
   name weight, or gross exposure breaches `config/ml_allocation.yaml`
   caps; or realized vol persistently exceeds `risk_scaling.target_vol`.
4. **Cost blowout** — realized net-of-cost Sharpe falls below the
   acceptance artifact's `cost_60bps` figure (the stress-cost case).

Demotion = the candidate reverts to `evidence_only` / research status;
it requires a fresh freeze bundle (new P4 acceptance) to re-promote.
Demotion is **not** auto-kill — it raises a flag a human adjudicates,
consistent with `feedback_promotion_only_falsification_evidence_gated`
(promotion and demotion are both evidence-gated, never reactive).

## 5. Connection to existing governance

- The freeze bundle is referenced from the candidate's record under
  `data/research_candidates/` (the same place every forward candidate
  lives) — the ML candidate is just another forward candidate with an
  `ml_freeze_bundle` pointer.
- The daily forward ritual (`feedback_forward_observation_ritual`)
  runs the drift check as part of `observe`; drift flags land in
  `docs/forward_observation_log.md`.
- Track-A promotion gates (full-period + 2025-holdout vs SPY) are
  unchanged — the ML path must clear the SAME Track-A bar as any
  other candidate. P4 acceptance is *additional* (portfolio-level),
  not a substitute for Track-A.
- `config/production_strategy.yaml` (PRD M1 SoT) is edited only after
  Track-A PASS + a frozen bundle + user explicit-go.

## 6. Open items (carried, non-blocking)

- The exact P4 acceptance gate wording (strict "Sharpe AND MaxDD both
  beat baseline" vs the relaxed "Sharpe beats AND MaxDD within the
  15–20 % invariant" adopted 2026-05-22) — prompt §〇 #5 待讨论项 ①.
- The promoted path-D config (plain vs vol-target 0.10) — §〇 #5 ②.

These do not block P5: the freeze-bundle + drift + demotion mechanism
is independent of which exact gate wording / config is chosen.
