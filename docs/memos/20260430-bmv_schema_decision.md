# B.MV schema decision memo

**Date**: 2026-04-30
**Status**: SHIPPED at YAML/proposal level; not yet implemented in
`core/research/forward/runner.py`.
**Triggered by**: external auditor R35 §2.2-2.3 (auditor flagged that
`decay_classification` and `estimated_beta_at_freeze` were referenced
in proposal text but not yet machine-readable in spec yamls; called
for canonical contract before B.MV implementation).
**Authority**: operator decision per Q12 disposition (see
`docs/memos/20260430-concerns_abE_proposed_solutions.md` §Q12);
auditor reviewed.

---

## Why this memo exists

This project has accumulated a real risk of confusing four artifact
states that look similar in writing:

| State | Where it lives | What it means |
|-------|---------------|---------------|
| Proposal pseudocode | docs/memos/*.md | Reasoning artifact only; not executable |
| Schema annotation | candidate spec yaml | Machine-readable; read by future runners |
| Implementation | core/research/forward/runner.py | Executable code path |
| Deployed behavior | observed in real forward runs | What actually ran |

R35 auditor caught me writing "B.MV runner code updated" in commit
message + R35 review log when in fact only the proposal pseudocode
and yaml annotations changed. The runner does not yet exist. This
memo formalizes the contract those layers are racing toward, so
when B.MV is actually implemented, all four layers agree.

---

## Canonical schema contract

### `decay_classification` (top-level dict on candidate spec yaml)

**Purpose**: machine-readable candidate lifecycle state. Distinct
from `realized_nav_correlation_status` which describes a
PAIR-FINDING (RCMv1 × Cand-2 NAV correlation). Distinct from
`reason_unused` which is a human-readable string in another block.

**Required fields**:

```yaml
decay_classification:
  label: <enum>             # see "label values" below
  reason: <str>             # short machine-friendly slug + human prose
  evidence_memo: <path>     # path to memo justifying the label
  set_at: <YYYY-MM-DD>      # date label was stamped
  set_by: <slug>            # source process (manual, track_a_acceptance, etc.)
```

**Optional fields**: none currently. Future fields (e.g. `auto_revoke_after`)
require a forward-only schema bump with a new memo.

**Label values** (enum, additions require memo update):

| Label | Meaning | B.MV behavior |
|-------|---------|---------------|
| absent / null | Candidate is operational | normal |
| `legacy_decay_verification` | Pre-current-framework candidate, observation-only | SKIP B.MV at dispatch |

Future labels may be added as the framework evolves (e.g.
`promoted_to_live`, `revoked_after_breach`). Each addition requires
a memo update + reviewer signoff.

### `estimated_beta_at_freeze` (top-level dict on candidate spec yaml)

**Purpose**: persist β estimates at freeze time for B.MV trigger T4
(beta-adjusted residual underperformance, per reviewer §6 2026-04-30).

**Required fields**:

```yaml
estimated_beta_at_freeze:
  beta_to_spy: <float>           # β vs SPY daily returns
  beta_to_qqq: <float>           # β vs QQQ daily returns
  method: <slug>                 # e.g. cov_ret_d_div_var_bench_ret_d
  window: <slug>                 # e.g. train_plus_validation OR pooled_post_step3b_paper_154d
  n_obs: <int>                   # number of trading days in window
  source: <slug>                 # e.g. track_a_acceptance OR pooled_paper_sample_post_step3b
  computed_at: <YYYY-MM-DD>      # when computed
  computed_by: <path>            # script or function path
  used_by_b_mv: <bool>           # whether B.MV trigger T4 reads this block
```

**Optional fields**:

```yaml
  reason_unused: <str>           # required when used_by_b_mv=false; human prose
```

### Why these schemas, not flat fields

Original B.MV proposal pseudocode used `candidate_spec.get("estimated_beta_to_spy")`
(flat field). YAML uses nested. Auditor R35 §2.3 caught the
divergence. **Decision: nested schema is canonical.** Reasons:

1. Audit-friendly: all β-related metadata in one block, including
   `method` / `window` / `n_obs` (which differ between legacy
   paper-sample and new train+validation).
2. Self-documenting: `source` field disambiguates "this β came from
   Track A acceptance" vs "this β came from post-hoc paper sample".
3. Extensible: future fields (e.g. rolling β re-estimation in
   B.Full) fit naturally without flat-field proliferation.
4. Honest about asymmetry: legacy backfill semantics genuinely
   differ from new-candidate stamps; the schema makes this visible
   instead of pretending they're the same number.

### B.MV runner reads

```python
# Dispatch on decay_classification before any other gate.
decay_block = candidate_spec.get("decay_classification") or {}
if decay_block.get("label") == "legacy_decay_verification":
    return (False, [])

# T4 reads nested beta block. Fail loud on missing.
beta_block = candidate_spec.get("estimated_beta_at_freeze") or {}
beta_spy = beta_block.get("beta_to_spy")
if beta_spy is None:
    raise ValueError(
        f"candidate {candidate_spec.get('candidate_id')!r} missing "
        f"estimated_beta_at_freeze.beta_to_spy; B.MV trigger T4 "
        f"requires this stamped at freeze. Track A acceptance bug "
        f"if not legacy."
    )
```

`used_by_b_mv` and `reason_unused` are NOT read by B.MV runner.
They are documentation fields for human auditors. The runner
relies on `decay_classification.label` short-circuit for legacy.

### Track A acceptance writes

When Track A acceptance promotes a Track C candidate, it computes:

```python
import numpy as np
def estimate_beta(strat_ret_d: pd.Series, bench_ret_d: pd.Series) -> float:
    bm_var = float(bench_ret_d.var())
    if not np.isfinite(bm_var) or bm_var == 0.0:
        raise ValueError("zero-variance benchmark in beta estimation")
    return float(strat_ret_d.cov(bench_ret_d) / bm_var)
```

over the **train + validation period of the candidate's spec**
(NOT validation alone, NOT the holdout, NOT the sealed slice — this
is the period the candidate has actually seen and that Track A
accepted). Window labeled `train_plus_validation`, source labeled
`track_a_acceptance`, used_by_b_mv labeled `true`.

---

## What is shipped vs not shipped (R35 cleanup commit boundary)

| Layer | RCMv1 | Cand-2 | Track C nominees |
|-------|-------|--------|------------------|
| `decay_classification` block in YAML | ✅ shipped | ✅ shipped | N/A — set at freeze by Track A acceptance only if applicable |
| `estimated_beta_at_freeze` block in YAML | ✅ shipped (legacy semantics) | ✅ shipped (legacy semantics) | Will be stamped by Track A at freeze with `source=track_a_acceptance` |
| B.MV runner code | ❌ not implemented | ❌ not implemented | ❌ not implemented |
| Track A acceptance writes the block | ❌ not implemented | ❌ not implemented | ❌ not implemented |

**Order to ship** (parallelizable steps marked):

1. ✅ schema decision memo (this file)
2. ✅ YAML annotations on RCMv1 + Cand-2
3. ✅ proposal pseudocode aligned with this schema
4. ⏸ A.MV implementation (sealed_eval freeze-date HARD + market-path SOFT)  [parallel]
5. ⏸ B.MV implementation (dispatch + T1-T5 triggers)  [parallel]
6. ⏸ Track A acceptance auto-stamp `estimated_beta_at_freeze` and (if applicable) `decay_classification`
7. ⏸ B.MV regression tests (RCMv1 + Cand-2 SKIP path; new-candidate fail-loud path)
8. ⏸ Forward init enabled for first nominee

---

## What this memo does NOT decide

- The exact label set beyond `legacy_decay_verification`. Future
  labels (e.g. `revoked_after_breach`) are left to a downstream memo.
- Whether `panel_max_date_at_freeze` lives on the spec yaml or on
  `SealedLedgerEntry`. That is the A.MV concern, not B.MV; tracked
  separately in `concerns_abE_proposed_solutions.md` Q11.
- The B.Full upgrade path (rolling β re-estimation from forward TDs).
  Out of MV scope.

---

## Audit trail

- 2026-04-30 commit pending: this memo + RCMv1+Cand-2 yaml schema
  blocks shipped + concerns memo proposal pseudocode aligned.
- Auditor R35 §2.2-2.3 disposition recorded in `docs/claude_review_loop.md`
  Round 36.
