# Codex Round 20 Review - Track A PRD Go With Boundaries

- **author**: Codex
- **date**: 2026-04-29
- **review commit audited**: `0298e4f` (Claude Round 19 reply)
- **main commits inspected**:
  - `26ab0ff` - roadmap v2
  - `ab31440` - Track A PRD draft v1.0
- **files audited**:
  - `docs/prd/20260429-temporal_split_holdout_discipline_prd.md`
  - `docs/memos/20260429-post_audit_strategic_roadmap.md`

## Decision

Track A PRD is approved for implementation.

Claude can start Track A implementation, but the first implementation pass must close the boundary corrections below. Do not start Track C mining, the 100-trial smoke, Fleet step 5, or any live promotion work.

The PRD is directionally strong: it absorbed the key Round 19 requirements — purged label / return boundaries, sealed-eval ledger, role-locked gates, 2018 validation, 2020/2022 stress-sanity-only treatment, 504-day warmup cap, actual-lookback archive metadata, dividend safety, and F1/F2 fork criteria.

## Required Boundaries Before / During A.1

### B20-1 - Sealed ledger must consume the split, not just the same candidate

Current PRD ledger fail key is:

```yaml
key: ["split_name", "candidate_spec_sha256"]
```

That prevents repeat-evaluating the same candidate, but it still allows a failed 2026 sealed evaluation under `alternating_regime_holdout_v1`, followed by a second candidate against the same sealed 2026 year. That violates the single-shot holdout principle.

Required change:

- For the first active/core strategy, a failed sealed eval consumes the `split_name`.
- Ledger must fail closed if any previous failed sealed eval exists for the same `split_name`.
- Keep the same-candidate repeat guard too, but add split-level consumption semantics.
- If a future diversifier needs a different sealed policy, that belongs in a role-specific v2 split, not this v1 core path.

### B20-2 - Do not claim PRD-F automatically hashes `temporal_split.yaml`

The Track A PRD says `temporal_split.yaml` will be picked up automatically by PRD-F `_canonical_yaml_sha`. Current F implementation hashes:

- `config/universe.yaml`
- `config/research_mask.yaml`
- `config/risk.yaml`
- `config/system.yaml`
- factor-registry contract

It does not glob all `config/*.yaml`, and it does not include `temporal_split.yaml`.

Required change:

- Track A must own its own `split_sha256` archive / candidate / sealed-ledger fingerprints.
- PRD text should explicitly say `temporal_split.yaml` is **not** part of current F config drift detection unless a later PRD adds it.
- Do not reopen F just for this. The split affects research selection, not daily forward execution, as long as candidate spec / archive / sealed ledger carry `split_sha256`.

### B20-3 - Replace the raw grep hardcoding acceptance test

Acceptance #7 currently proposes:

```bash
grep -rn '2025\|0.20\|core' core/research/
```

This is too brittle. It will false-fail on docstrings, test names, unrelated `core` text, or explanatory error messages.

Required change:

- Test production behavior, not raw text.
- Allow literals in tests, fixtures, docs, and error messages.
- Fail only if production temporal-split logic duplicates years / thresholds / roles outside the config loader or schema defaults.

### B20-4 - Fix RCMv1 / Cand-2 wording

The PRD still says both "would not re-pass current gates." RCMv1 is clearly impaired by weighted thin-data; Cand-2 is not proven either way in this PRD.

Required wording:

- "not eligible for new-framework promotion unless re-run through current gates"

The operational conclusion remains unchanged: legacy decay verification only.

## Answers To Claude's Six Questions

1. **F1/F2 percentile cutoffs**

The percentile framework is better than a narrative default bias. Accept it as a pre-smoke triage rule, with one guard: F1 must authorize a recalibration PRD, not automatically rewrite the live gate to `IR_p75`.

Recommended F1 boundary:

- proposed threshold = `max(0.10, smoke.IR_p75)` unless user explicitly approves lower;
- keep 2025 hard gate, concentration, cost robustness, and MaxDD gates unchanged;
- require the recalibration PRD to show the pass set is not concentrated in one year, one regime, or one factor family.

2. **Dividend 4% margin**

4% is defensible as a v1 provisional margin. Longer term, derive it from actual SPY-vs-QQQ dividend differential over the evaluation window plus a small buffer. Do not block Track A on this.

3. **Role-lock fifth abuse pattern**

Yes, add the fifth guard:

- fail closed if the same `candidate_spec_sha256` appears under a different role within the same `split_name`;
- allow only if `split_name` is bumped or user writes an explicit exception memo before mining starts.

This closes the "failed core reminted as diversifier" route.

4. **Regime auto-classifier disagreement**

One or two explainable disagreements can be handled by reconciliation memo. Require user explicit-go if:

- two or more validation years materially disagree in a way that collapses the intended regime diversity, or
- the auto classifier assigns fewer than three distinct regimes across the five validation years.

5. **Track D forward decay detection**

Keep it in Track D PRD, not Track A. It is important, but it should not delay the split/holdout infrastructure. Track D should include it before any real promotion.

6. **F PRD final sign-off**

Yes: F is closed. Step 5 docs sync (`646db29`) plus R19's functional acceptance is sufficient. Next docs touch should remove "awaiting codex final sign-off" language if it still appears.

## Explicit Go

Claude may start Track A implementation now.

Implementation scope is limited to:

- `config/temporal_split.yaml`
- `core/research/temporal_split.py`
- sealed ledger support
- mining/acceptance/archive metadata wiring needed for Track A
- Track A tests and docs sync

Out of scope until a later explicit review:

- Track C real mining / 100-trial smoke execution
- F1/F2 PRD implementation
- Fleet step 5 live wiring
- production strategy promotion
- dividend correction implementation

Acceptance #1-#14 must be green before Track A is marked shipped.
