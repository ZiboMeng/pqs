---
date: 2026-04-28
event: first real forward observe under v2.1.3 + R8 DST fix
trigger: codex round-11 review priority A1
candidates:
  - rcm_v1_defensive_composite_01
  - candidate_2_orthogonal_01
---

# Forward observe — first real append after v2.1.3 hardening + R8 DST fix

**Trigger**: codex round-11 review (`docs/audit/20260428-codex_round_11_review.md` priority A1) — "把两个 manifest 从 TD001 推进到真实新 TD". Concretely the gap codex flagged: "框架的'审计完备度'已经开始领先于'真实 forward 证据积累'".

This is the **first real `forward observe` call since v2.1.3 shipped (4abc3c9 + 051d869) and since the R8 DST fix landed**. Prior state of both manifests was TD001 only, written under v2.1.0 schema (no hashes, pre-lazy-migration boundary).

## Pre-state

```
[rcm_v1_defensive_composite_01]
  current_status     = in_progress
  evidence_class     = forward_oos
  n_runs             = 1   (TD001 only, pre-v2.1)
  first_run_date     = 2026-04-24

[candidate_2_orthogonal_01]
  current_status     = in_progress
  evidence_class     = forward_oos
  n_runs             = 1   (TD001 only, pre-v2.1)
  first_run_date     = 2026-04-24
```

Readiness for both:
```
last_observed_date  = 2026-04-24 (Friday)
latest_data_date    = 2026-04-28 (Tuesday, today)
next_expected_td    = 2026-04-27 (Monday)
n_potential_new_tds = 2
can_append_now      = true
benchmark_lag       = SPY/QQQ both 2026-04-28 (current)
source_layer_status = mixed (yfinance frontier — boundary cross since panel was constructed on polygon canonical)
```

## Observe execution

Single sequential call to `from core.research.forward.runner import observe; observe(run_id)` for each candidate.

## Post-state

```
[rcm_v1_defensive_composite_01]  3 runs
  TD001 2026-04-24: legacy=True   bar_hash=None         smix=True
  TD002 2026-04-27: legacy=False  bar_hash=48c128480116 smix=True
  TD003 2026-04-28: legacy=False  bar_hash=ac5bb7335bdf smix=True

[candidate_2_orthogonal_01]      3 runs
  TD001 2026-04-24: legacy=True   bar_hash=None         smix=True
  TD002 2026-04-27: legacy=False  bar_hash=d22be7fc985b smix=True
  TD003 2026-04-28: legacy=False  bar_hash=c4e54f3c2df9 smix=True
```

### v2.1.3 schema integrity

- **TD001 lazy-migration boundary**: pre-existing TD001 entries get `legacy_unhashed_inputs=True` and remain hash-field-empty (no retroactive recomputation). This is the v2.1.3 lazy-migration contract working correctly — no fake-hash backfill, no manifest mutation of the historical record.
- **TD002 / TD003 v2.1.3 hash fields populated for both candidates**: `bar_hash`, `signal_input_hash`, `execution_nav_hash`, `benchmark_hash` — all four scopes hashed. `bar_hash_inputs` carries the full `BarHashInputs` model with per-scope `symbols`, `bar_attributes`, `window_start`, `window_end`, `bar_revision`, and (for `execution_nav` scope only, per v2.1.1 storage budget) `per_cell_digest`.
- **`signal_input.per_cell_digest = {}` on both candidates**: this is the production default `track_per_cell=False` per v2.1.1 (storage budget pinned). Per the R5 audit (B2 lens) confirmation, this does NOT under-classify revisions because the v2.1.3 codex Round-10 Blocker-2 fix means an empty per_cell_digest unconditionally fail-closes to `bound_only` when the rolling hash differs.
- **Cross-candidate benchmark_hash invariant**: both candidates emit identical `benchmark_hash` on the same TD (`1de2f326c4b6` on TD002; `bb4b050da368` on TD003) because both manifests pin the same SPY+QQQ benchmark and the benchmark hash only encodes the benchmark panel state, not the candidate spec. Expected.

### R8 DST fix path (not exercised this observe)

`_first_post_freeze_trading_day` only fires on `init()` (when a manifest is created from a fresh `promoted_at`). Today's append is on existing manifests, so the DST code path was not on the call stack. The fix is regression-pinned by the 2 R8 unit tests; it stays validated for future `init()` calls.

### source_mix=True on TD002 + TD003

Same status as TD001: forward observation reads the yfinance frontier, while the panel's historical training/construction window was on polygon canonical. Per CLAUDE.md "Forward OOS active workstream", this is the honest source-boundary surfacing — not a defect.

## Performance numbers (early forward window — 4 trading days)

| Candidate | TD | as_of | cum_ret | vs SPY | vs QQQ | sharpe | maxdd | fills |
|---|---|---|---|---|---|---|---|---|
| rcm_v1_defensive_composite_01 | TD002 | 2026-04-27 | -0.478% | -0.651% | -0.531% | -11.22 | -0.478% | 1 |
| rcm_v1_defensive_composite_01 | TD003 | 2026-04-28 | -3.930% | -3.402% | -2.597% | -11.11 | -3.930% | 0 |
| candidate_2_orthogonal_01     | TD002 | 2026-04-27 | -0.658% | -0.830% | -0.711% | -11.22 | -0.658% | 9 |
| candidate_2_orthogonal_01     | TD003 | 2026-04-28 | -4.492% | -3.964% | -3.159% | -11.58 | -4.492% | 7 |

**Reading**: this is forward day 2-3 only (n_observed_trading_days=2 on TD002 / 3 on TD003). The Sharpe = -11.x is the canonical artifact of measuring annualized Sharpe on a 2-3-day window with a single sharply negative move; **not** a strategy-quality signal. Cum_ret -3.9% / -4.5% on TD003 reflects a single bad day on Tuesday 2026-04-28 (held names sold off broadly; vs-benchmark drag also -3.4% / -3.9% absolute). Both candidates are close to peer with each other and lag SPY/QQQ in this short window.

The numbers themselves carry **no decision weight** — far below any checkpoint cadence (R-fwd PRD's first decision pack is at TD010 / 10 trading days). The point of this observe was to verify the **mechanics** under v2.1.3, not to evaluate strategy.

## Idempotency

After both observes appended TD002+TD003, re-running `observe(run_id)` on each candidate returned `len=0` (no new TDs to append since already at today's data) and left `n_runs=3` unchanged. Idempotency holds (audit lens R6 S08 contract preserved).

## What this validates (codex's review asks)

- **DST fix**: stays untouched on observe-path; fix pinned by 2 R8 regression tests; future `init()` calls will exercise.
- **v2.1.3 hash mechanics under live data**: PASS — schema migration boundary correct, all 4 scopes populated, per_cell_digest only on `execution_nav` per v2.1.1 storage policy.
- **Idempotency**: PASS.
- **R6 S25 (revalidate non-mutating on real manifest)**: STILL CONFIRMED — re-observing did not corrupt history.
- **codex Q1 (cumulative-pass design value)**: this observe demonstrates the design payoff: R1-R10 audit cycle hardened the mechanics so the **first real forward append since ship works on the first try**, with no surprise drift, no schema mismatch, no halts.

## Codex roadmap progress (queue from `20260428-codex_round_11_review.md` §"我给 Claude 的优先级排序")

| Item | Status |
|---|---|
| 1. 真实 forward observe（两个候选）| **DONE** (this memo) |
| 2. Acceptance Threshold Unification PRD | not started — codex priority #2 |
| 3. candidate fleet allocator 最小版设计 | not started |
| 4. forward daily ritual 固化 | not started — recommend pairing with #1 cadence |
| 5. config/universe snapshot hardening PRD | not started |
| 6. capacity/liquidity realism 升级 | not started |
| 7. M17 live-feed infra | gated behind 1+3 |
| 8. M18 / 更复杂模型研究 | gated behind everything above |

## Suggested next session move

If user signals "继续" or "下一步", default to **#2 Acceptance Threshold Unification PRD** (F01 + F02 unification scope). It is the cheapest of the open items, addresses real research-governance drift, and codex was specific that it's "短期合理 defer implementation, 不可以 defer prioritization".

If user signals "数据来了" / "新数据", repeat this observe ritual (and remember it should be lightweight after this first real run — append-only, hash check, log).
