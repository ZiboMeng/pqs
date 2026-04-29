---
title: Track A — Temporal Split & Holdout Discipline implementation log
date: 2026-04-29
type: implementation_log
status: shipped
prd: docs/prd/20260429-temporal_split_holdout_discipline_prd.md (v1.1)
roadmap: docs/memos/20260429-post_audit_strategic_roadmap.md (v3)
authority: codex round 19 + 20 PRD-level approved; user explicit-go received
---

# Track A implementation log

## Summary

Track A (Temporal Split & Holdout Discipline) shipped on 2026-04-29 in
8 commits across 8 modules. All 18 PRD §11 acceptance criteria have
pytest coverage; combined test surface is **126/126 passed in 4.16s**.

## What shipped

| Module | Lines | Purpose |
|---|---|---|
| `config/temporal_split.yaml` | 213 | SOT for split / roles / acceptance / audit guards |
| `core/research/temporal_split.py` | 580 | pydantic loader + panel filter + leak guards + factor cap + C5 enforcement + label purge |
| `core/research/temporal_split_acceptance.py` | 430 | per-year + per-slice + role-gate + cross-cutting evaluator (no backtest) |
| `core/research/sealed_ledger.py` | 220 | M5 + B1 fail-closed sealed-eval ledger (parquet) |
| `core/research/regime_classifier.py` | 165 | M9 manual + auto regime tag with tiered disagreement policy |
| `core/mining/rcm_archive.py` | +90 | 7 new columns (3 study + 4 trial); idempotent ALTER; find_studies_by_spec_role |
| `core/mining/research_miner.py` | +35 | thread Track A fingerprint to record_study + insert_trial |
| `scripts/run_research_miner.py` | +60 | --temporal-split + --role flags; restrict + leak guard + summary metadata |
| Tests (6 files) | ~1700 | 126 unit tests covering acceptance #1-#18 |

## Commit timeline (2026-04-29)

| Step | Commit | Title |
|---|---|---|
| A.1 | `8465616` | Schema + pydantic loader + 31 unit tests |
| A.2 | `dbb5649` | Panel restriction + leak detection + role enforcement + run_research_miner wiring |
| A.3 | `95a35ea` | Acceptance evaluator (per-year + stress + role + cross-cutting) + 25 tests |
| A.4 | `4452a93` | Archive metadata + C5 role-remint guard + 16 tests |
| A.7 + A.8 | `d45b766` | Sealed-eval ledger + regime auto-classifier + 27 tests |
| A.5 + A.10 | (this commit) | Label purge + factor cap + leak detection consolidated + F1/F2 fork memo + implementation log |
| A.6 | (this commit) | This implementation log |
| A.9 | (next commit) | Docs sync — CLAUDE.md + README + INDEX |

## Acceptance criteria coverage (PRD §11)

| # | Criterion | Test file | Status |
|---|---|---|---|
| 1 | 2026 row in train panel → abort | test_temporal_split.py | ✅ |
| 2 | validation year in train panel → abort | test_temporal_split.py | ✅ |
| 3 | split_sha256 + panel_max_date determinism | test_temporal_split.py | ✅ |
| 4 | 2025 hard gate kills 2018/2019/2021/2023-pass candidate | test_temporal_split_acceptance.py | ✅ |
| 5 | stress slice independent of validation | test_temporal_split_acceptance.py | ✅ |
| 6 | split_name v1→v2 isolation | test_temporal_split.py | ✅ |
| 7 | yaml-swap behavior test (replaces grep, codex R20 B3) | test_temporal_split_acceptance.py | ✅ |
| 8 | M4 label purge crosses train→validation boundary | test_temporal_split_leak_detection.py | ✅ |
| 9 | M5 fail_closed_on_repeat | test_sealed_ledger.py | ✅ |
| 10 | role unspecified → abort | test_temporal_split.py | ✅ |
| 11 | F1/F2 fork synthetic distribution dispatch | test_temporal_split_acceptance.py (yaml schema) | ✅ |
| 12 | auto_classifier_tag null check | test_regime_classifier.py | ✅ |
| 13 | factor lookback > 504 → reject | test_temporal_split_leak_detection.py | ✅ |
| 14 | max_factor_lookback recorded per trial | test_temporal_split_archive.py | ✅ |
| 15 | B1 split-level core sealed lock | test_sealed_ledger.py | ✅ |
| 16 | F1 floor max(0.10, IR_p75) + user-go below | test_temporal_split_acceptance.py | ✅ |
| 17 | C5 same-spec different-role within split blocked | test_temporal_split_archive.py | ✅ |
| 18 | regime disagreement tiered (memo / user-go / hard-error) | test_regime_classifier.py | ✅ |

## Rounds 19 + 20 coverage table

| Codex R19 ask | Where folded |
|---|---|
| #1 Purged label / forward-return boundary | M4 + §5.1 + audit guard #8 + test 8 |
| #2 Sealed-eval ledger | M5 + §5.2 + audit guard #9 + test 9 |
| #3 2025 hard gate role-specific | §6 + M2 + M6 + test 4 |
| #4 2018 validation + stress sanity-only | §4.1 + §4.3 + M1 + test 5 |
| #5 504-day cap + record actual lookback | §4.2 + audit fields + tests 13/14 |
| #6 Dividend pass margin Track C/D | §8 + M8 (schema in A; enforcement in D) |
| #7 Pointer hygiene (push main) | DONE pre-PRD (push c62b1d8 then ab31440) |

| Codex R20 ask | Where folded |
|---|---|
| B1 split-level sealed fail-close | M5 + §5.2 + sealed_eval_ledger.fail_closed_on_split_failure + test 15 |
| B2 Track A owns split_sha256 (F PRD non-coupling) | §2.2 corrected; sealed ledger writes split_sha256 itself |
| B3 production-behavior test #7 (replace grep) | test 7 yaml-swap |
| B4 RCMv1/Cand-2 wording softened | §1.1 |
| Q1 F1 floor max(0.10, IR_p75) + user-go below | M7 + fork_criteria + test 16 |
| Q3 Role lock C5 (same spec cannot remint different role) | §6.1 C5 + test 17 |
| Q4 Regime disagreement tiered | §5.3 + test 18 |

## Things explicitly NOT shipped (deferred)

| Item | Defer to | Reason |
|---|---|---|
| Real mining run | Track C | Track A is discipline infra; mining is alpha discovery |
| F1 PRD (gate recalibration) | post-smoke | Anti-anchoring (codex R19 + R20) |
| F2 PRD (new factor family) | post-smoke | Anti-anchoring (codex R19 + R20) |
| Forward decay detection submodule | Track D D.7 | Out of Track A scope |
| Dividend safety enforcement | Track D D.5 | Schema only in Track A |
| auto_classifier_tag actual yaml population | Step A.8 follow-up | Requires real SPY/VIX data load; orchestration script lives under dev/scripts/research/ when run |
| Factor registry hook calling validate_factor_lookback | Track C | Existing factor registry stays untouched in Track A |
| F PRD ConfigSnapshot extension to include temporal_split_hash | PRD-F-v2 | Cross-PRD coupling deferred per codex R20 B2 |

## Test surface progression

- Pre-Track-A research module: 419 tests
- After Track A:
  - test_temporal_split.py: 48 (loader + helpers + leak guards + role)
  - test_temporal_split_acceptance.py: 25 (per-year + stress + role + cross-cutting)
  - test_temporal_split_archive.py: 16 (schema migration + C5 guard)
  - test_sealed_ledger.py: 15 (M5 + B1 ledger)
  - test_regime_classifier.py: 12 (year-level + tiered policy)
  - test_temporal_split_leak_detection.py: 10 (M4 purge + factor cap + meta + integration)
- **Track A total: 126 tests**
- Combined research suite: 419 + 126 = 545 tests (pre-existing 419 unchanged)

## Files NOT touched (intentional non-coupling)

- `core/mining/acceptance_pack.py` — codex round 13 frozen contract for
  already-promoted specs; Track A acceptance is a separate evaluator
  (PRD §1.2 + module docstring explicitly state non-coupling).
- `core/research/forward/*` — F PRD's evidence v2.1.3 stays untouched;
  Track A owns its own split_sha256 per codex R20 B2.
- `config/production_strategy.yaml` — Track A does not change production
  strategy; promotion is Track D.
- `core/factors/factor_registry.py` — registration hook for
  validate_factor_lookback is deferred to Track C (no factor library
  changes in Track A).

## Operational rules

- Forward fetchdata must run after NYSE 16:15-16:30 ET (codex R20
  operational note + folded into CLAUDE.md "Forward observation daily
  ritual" via Step A.9).
- F1/F2 fork criteria are locked pre-smoke; see
  `docs/memos/20260429-track_a_f1_f2_fork_criteria.md`.
- Sealed eval is single-shot per `split_name`; bumping `split_name`
  triggers a new audit cycle.

## Pointers

- PRD: `docs/prd/20260429-temporal_split_holdout_discipline_prd.md`
- Roadmap: `docs/memos/20260429-post_audit_strategic_roadmap.md`
- F1/F2 fork memo: `docs/memos/20260429-track_a_f1_f2_fork_criteria.md`
- Codex R19 review: `docs/audit/20260429-codex_round_19_strategic_redirection_review.md`
- Codex R20 review: `docs/audit/20260429-codex_round_20_track_a_prd_go.md`
- Review log: `docs/claude_review_loop.md` (review/claude-collab branch)
