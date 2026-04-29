---
title: Track A — F1/F2 fork criteria one-page (locked pre-smoke)
date: 2026-04-29
type: decision_memo
status: locked_pre_smoke
parent_prd: docs/prd/20260429-temporal_split_holdout_discipline_prd.md (v1.1)
authority: codex round 20 PRD-level approved (M7 + Q1 floor); user explicit-go received
---

# Track A — F1/F2 fork criteria one-page memo

## Why this memo exists

Track C cannot start until Track A's 100-trial smoke test on the
alternating split + current 64 research factors has produced an IR
distribution. The fork between **F1 (gate recalibration PRD)** vs
**F2 (new factor family PRD)** must be determined by quantitative
percentile thresholds — locked **before** the smoke runs — to prevent
post-hoc anchoring (codex R19 said "default bias to F2"; Claude
modified to data-grounded percentile rules per M7 + R20 Q1).

This document is the canonical fork rule. After the smoke runs, the
result is compared against these rules and the chosen path is the
rule-determined one. No narrative override permitted.

## Smoke test contract

| Field | Value |
|---|---|
| Trial count | 100 |
| Sampler | TPE (matches existing mining default) |
| Universe | current 64 research factors (no expansion) |
| Split | `alternating_regime_holdout_v1` (this PRD) |
| Train years | 2009-2017 + 2020 + 2022 + 2024 (per yaml) |
| Validation evaluation | per-year IR computed across 2018/2019/2021/2023/2025 |
| Single trial IR | `mean(per_year_IR)` aggregated across the 5 validation years |
| Distribution metrics | `IR_p10`, `IR_p25`, `IR_p50` (median), `IR_p75`, `IR_p90`; plus `fraction_above_0.10` |
| Run command | `scripts/run_research_miner.py --temporal-split config/temporal_split.yaml --role core --trials 100 --lineage smoke-track-a-2026-04-29` |
| Output | `data/ml/research_miner/smoke-track-a-2026-04-29/run_summary.json` |

## Fork rules (locked)

The fork is decided by reading `acceptance.fork_criteria` from the
shipped YAML. The same logic in plain English:

### Rule F1 — gate recalibration triggers

**All** of:
- `IR_p90 > 0.15`
- `fraction_above_0.10 ≥ 0.20`

→ **F1**: alpha exists in current factor library; current OOS IR
gate (0.20) is too tight relative to the alpha strength. Recalibrate
to:

```
new_oos_ir_threshold = max(0.10, IR_p75)
```

The `max(0.10, …)` floor is the codex R20 Q1 guardrail: if smoke's
75th-percentile IR falls below 0.10, the recalibration **may NOT**
auto-apply; user explicit-go required to push lower (and that approval
must include a written rationale re-examining whether F2 is more
appropriate).

After F1 is triggered, the next workstream is the F1 PRD — a
separate document that:
- bumps `config/acceptance.yaml` version
- documents the recalibration rationale + smoke distribution evidence
- states "this lower threshold is valid only for `split_name=alternating_regime_holdout_v1`"
- gets codex sign-off before Track C real mining begins under the new threshold

### Rule F2 — new factor family triggers

**All** of:
- `IR_p90 < 0.05`
- `IR_p50 < -0.05`

→ **F2**: alpha is not in the current factor space. Current 64-factor
library is exhausted; need new families. Next workstream is the F2 PRD —
a separate document that:
- proposes 1-3 new factor families (intraday microstructure / event-driven /
  cross-asset / option-flow-derived)
- runs each through the LLM funnel (see CLAUDE.md "Factor Pipeline Contract")
- demonstrates each new family adds non-redundant signal vs existing 64
- gets codex sign-off before Track C mining incorporates them

### Rule Escalate — neither F1 nor F2

If smoke does not satisfy F1 or F2 conditions (e.g. `IR_p90 = 0.10,
IR_p50 = 0.0`), the fork goes to **user explicit decision**. Claude
writes a decision memo summarizing the smoke distribution + reasoning
for both options + recommended path with rationale; user picks F1, F2,
or "adjust the split / re-run smoke."

## Default bias question (codex R19 → R20 confirmed)

Codex R19 originally suggested "default bias to F2 unless smoke shows
broad near-threshold positive evidence." Claude rejected the bias
direction in R19 reply and proposed quantitative percentile rules
above. Codex R20 confirmed the percentile approach is acceptable as
pre-smoke triage with the F1 floor guardrail (Q1 above).

The escalate branch is the safety valve. It does the same job R19's
"unless ... obviously over-tight" did, but it's machine-readable and
cannot be retroactively reframed.

## Why this is in a memo, not a PRD

Per codex R19 §6 + auditor #5: the F1/F2 PRDs are written **after**
smoke triggers them, not in advance. Writing both PRDs pre-smoke
would anchor the answer regardless of evidence. This memo is the
trigger criteria; the actual recalibration or new-factor-family PRD
will reference this memo as its origin.

## Anti-anchoring discipline

To prevent the operator (zibo) from gaming the fork:

- The smoke run is single-shot; multiple smoke runs to cherry-pick a
  favorable distribution is prohibited.
- The lineage_tag for the smoke run must be `smoke-track-a-2026-04-29`
  (this exact string); rerunning under a different tag does not bypass
  the lock.
- The IR distribution metrics must be computed by the standard
  `_write_artifacts` summary path; manual recomputation is not
  authorized.
- After fork is triggered, this memo's content is fixed. Edits to
  thresholds require a new memo + bumping `split_name`.

## Concrete action when fork fires

1. Run smoke command above.
2. Read `IR_p90`, `IR_p75`, `IR_p50`, `fraction_above_0.10` from
   `run_summary.json`.
3. Apply rules above mechanically.
4. If F1: write `docs/prd/<DATE>-f1_gate_recalibration_prd.md`.
5. If F2: write `docs/prd/<DATE>-f2_new_factor_family_prd.md`.
6. If Escalate: write `docs/memos/<DATE>-track_a_smoke_escalate_<x>.md`
   summarizing distribution + asking user to decide.
7. Wait for codex sign-off + user explicit-go before Track C real mining.

## Pointers

- PRD: `docs/prd/20260429-temporal_split_holdout_discipline_prd.md` §7
- Yaml: `config/temporal_split.yaml::acceptance.fork_criteria`
- Roadmap: `docs/memos/20260429-post_audit_strategic_roadmap.md` §6.1
- Codex R19: `docs/audit/20260429-codex_round_19_strategic_redirection_review.md` (F1/F2 ask)
- Codex R20: `docs/audit/20260429-codex_round_20_track_a_prd_go.md` (Q1 floor + Q3 C5)
