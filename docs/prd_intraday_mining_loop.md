# PRD: Intraday Mining Ralph-Loop Phase

Status: **DRAFT — ready for execution**
Author: generated 2026-04-20 post smoke-mining verification
Predecessor: completed P0/P1 closeout (8 items) + Mining-前最后收口 (4 items)
+ smoke-run NaN blocker fix (`d562934`). Baseline: 1009 tests passing.

---

## 0. One-paragraph summary

The project's semantic-correctness base is now verified end-to-end.
Next phase: run a **ralph-loop** of ≤10 rounds that each (a) selects one
mining/research sub-goal, (b) runs the full
mine→archive→acceptance→report pipeline, (c) audits the repo for new
silent failures, (d) commits. Every round holds the current `lineage_tag`
constant unless the round deliberately changes methodology; then the tag
increments. Rounds are strictly bounded — no round may spawn a second
round in parallel.

---

## 1. Scope

### 1.1 In-scope for this phase

- Intraday factor mining (driven by factor_registry + factor_generator)
- Cross-timeframe feature training (on 60m/30m/15m bar stores)
- Model comparison (ridge vs XGB vs current linear composite) — but
  ONLY as feature-importance tools, not as alpha swaps
- Parameter search (Optuna + strategy_space) for MultiFactor + future
  strategy types
- Extending LLM factor system (via the registry-funneled promotion flow)
- Shadowed-factor merge (register→implement→deregister the duplicate)
- Real-time feed adapter (when external data source is in scope)
- Broker adapter (when execution venue is in scope)

### 1.2 Out-of-scope

- Any change to hard constraints in CLAUDE.md (long-only, no-margin,
  QQQ Outperformance Rule, etc.) without explicit user sign-off
- Refactors that change the meaning of existing archive rows — every
  methodology change MUST bump `lineage_tag`
- Anything that bypasses the factor_registry promotion flow

---

## 2. Operating rules (ralph-loop)

### 2.1 Loop cadence

```
Round N:
  Step 1  Pre-round audit (≤15 min):
            - git log since last round
            - test suite passes?
            - archive schema consistent?
            - no uncommitted changes
  Step 2  Topic pick (from §3 menu) + 中文 round plan posted
  Step 3  Implementation (one main goal only)
  Step 4  Full pipeline run:
            - unit + integration tests
            - smoke mining (when relevant) or
              focused validation script
            - archive the run with the round's lineage_tag
  Step 5  Post-round audit (≤15 min):
            - scan for new warnings/errors
            - verify no silent failure (look for -999 scores,
              NaN-to-int crashes, VIX stubs, ghost positions,
              QQQ gate bypasses)
            - leaderboard filtered by this round's lineage_tag
  Step 6  CLAUDE.md update (facts only, not plans)
  Step 7  Commit with round number + topic in subject
  Step 8  Update this PRD's Appendix A (round log) if needed
```

### 2.2 Hard rules per round

- **One main goal per round.** Do not combine topics.
- **No direct edits to hard constraints** (see §1.2).
- **Every round's output must fit the 11-part 中文 report format**
  (当前阶段 → 本轮目标 → ... → TODO checklist).
- **Every mining run must pass `--lineage-tag`** explicitly. No
  legacy-tag writes allowed.
- **After any fix that changes evaluator semantics, `lineage_tag`
  MUST bump** to a new string (e.g. `post-2026-04-20-closeout-r3`).
- **If a round introduces a new silent failure** (new -999 trial
  class, new warning storm, etc.), that round must close it before
  advancing.
- **No round may run more than 2 hours of wall-clock mining** without
  an intermediate progress report.

### 2.3 Lineage_tag progression

| Round state | Tag example |
|---|---|
| Unchanged methodology | Same as prior round |
| Evaluator/acceptance/factor-set changes | Bump to `...-r{N}` |
| New strategy type added to search space | Bump with strategy prefix |
| Universe or start-date changes | Bump with suffix |

---

## 3. Round-topic menu

Rounds should pick from this menu in roughly the order listed, but
the pick is determined at the start of each round from the pre-round
audit + standing TODO list (not pre-committed here).

### 3.1 First priorities (before any scale-up)

| # | Topic | Completion signal |
|---|---|---|
| A | **Full-scale smoke with QQQ gate actually firing.** Re-run mining at `--trials 80 --budget 1800` so ≥1 trial reaches Stage 6. Verify `passed_qqq_gate` column gets populated with real values in at least some rows. | Archive shows ≥1 row with non-NULL `qqq_full_period_excess`. |
| B | **Leaderboard UX.** Update `--leaderboard` output to surface: `lineage_tag`, `passed_qqq_gate`, `qqq_*_excess`, and a per-lineage summary block. | Default leaderboard output contains all new columns + a "by lineage" breakdown. |
| C | **Stale-counts checkpoint.** Intraday ghost cleanup's `_intraday_stale_counts` is process-local; persist to `bar_checkpoints` and restore on resume. | Test: kill mid-day halt run, restart, counter reloaded. |
| D | **Factor gate WARN/ERROR configurable.** Add a `strict_registry_mode` config flag; ERROR mode raises instead of warn-drop on unregistered factor names. | New test: strict mode raises; default (warn) unchanged. |

### 3.2 Second priorities (research — after §3.1 clean)

| # | Topic | Completion signal |
|---|---|---|
| E | **Shadowed-factor merge.** Pick 1-2 research→production-mapped pairs (e.g. `vol_63d ↔ low_vol`) and port the research implementation into MultiFactorStrategy, removing the duplicate inline path. Update registry. | Registry map shrinks by N; MultiFactor backtest delta < 50bps CAGR. |
| F | **Intraday factor family introduction.** Start with ONE intraday feature family (e.g. realized_vol_60m + intraday_mean_reversion_15m) in factor_generator. Do NOT promote to production yet — only research IC screen. | `run_factor_screen.py` shows intraday family with non-trivial IC. |
| G | **Cross-TF feature training.** Use `decide_timing` output + factor_generator output jointly to compute a timing-aware composite signal. Validate via `validate_timing_value.py` delta. | Script shows `net_delta_bps_per_event` > current +3.26 with new features, or explicit NEGATIVE finding. |
| H | **Model comparison (feature importance only).** Run XGBRegressor vs ridge on the same feature panel; compare permutation importance rankings. | Side-by-side leaderboard of top-20 factors by method. |
| I | **Parameter search expansion.** Introduce a second strategy type's `ParameterSpace` to mining (e.g. dual_momentum variants) and verify QQQ gate filters its promotions just as strictly. | ≥3 non-multi_factor trials archived. |

### 3.3 Third priorities (infra, when research earns the right)

| # | Topic | Completion signal |
|---|---|---|
| J | **LLM factor system expansion.** Add a candidate-generation script that emits YAML per the factor_candidate schema; promote through the funnel. | ≥1 LLM-generated candidate passes IC + OOS + regime + promotes. |
| K | **Real-time feed adapter.** Stand up a minimal DataProvider subclass backed by a real vendor (IEX / Polygon / etc.). Live mode uses it; backtest/research unchanged. | `run_paper.py --mode live` works without the stored-data fallback. |
| L | **Broker adapter.** Minimal `BrokerAdapter` skeleton per CLAUDE.md §4.1. Paper runs route orders through an adapter instance (no real broker connected yet). | Interface test: submit → ack → fill → reconcile round-trip. |

---

## 4. Per-round quality gates

Every round's PR must pass these before claiming completion.

### 4.1 Correctness gates

- Unit suite green (≥1009 tests as of this PRD; any new topic should
  add focused tests, not remove them).
- If the round touches mining: fresh smoke run with `--trials ≥20`
  under the round's lineage_tag; zero -999 score crashes.
- If the round touches timing: `validate_timing_value.py` still
  produces a verdict (POSITIVE/NEUTRAL/NEGATIVE) without crashing.
- If the round touches config: one focused test that asserts config
  field flows to the consumer attribute.

### 4.2 Semantic gates

- No regression in apply_extra_shift default (must stay False).
- No script reintroduces silent VIX=20 fallback (strict in live).
- No archive row written without lineage_tag.
- No path bypasses `save_eval` / `promote`.
- QQQ gate enforced at both evaluator AND acceptance.

### 4.3 Research honesty gates

- A round that produces a "positive" result must also state its
  sample size, confidence, and what would invalidate the finding.
- A round that produces a "neutral" or "negative" result must say so
  explicitly — no burying in an appendix.
- Every mining round must disclose: total trials, passed_quick,
  passed_oos, passed_robustness, promoted, QQQ-gate-failed.

---

## 5. Exit criteria for this phase

The phase is DONE when any of:

1. **Research win:** At least one strategy promotes under
   `lineage_tag=post-2026-04-20-closeout` (or a round-bumped
   descendant) with all gates green (OOS IR ≥ 0.20, passed_holdout,
   passed_qqq_gate, passed_robustness) AND reproduces under a fresh
   archive with the same lineage_tag.
2. **Infra readiness:** Rounds J/K/L are complete (LLM system + real
   feed + broker adapter minimal).
3. **User-initiated stop:** User instructs phase stop for any reason.

If neither (1) nor (2) happens after 10 rounds, re-scope via a new
PRD rather than continuing the loop.

---

## 6. Known risks the loop must watch

### 6.1 Silent-failure patterns

- `score=-999.0` bucket: always check after each mining run. The
  P0.5 regression that caused 13/20 crashes in the first smoke run
  would not have been found by the static audit.
- Warning storms: any single log pattern emitted >100 times in a
  run should be investigated, not tolerated.
- NaN propagation through _generate_orders / cost model /
  compute_metrics: pattern recurs whenever a new code path produces
  NaN weights.

### 6.2 Semantic-drift patterns

- Mining trials stored in archive but not on the current lineage tag
  (drift between runs).
- `apply_extra_shift=True` reintroduced via a "legacy reproduce" test
  that leaks into production.
- QQQ gate accidentally bypassed via a new evaluate() code path that
  doesn't forward `qqq_series`.
- Concentration knobs disabled via a config edit that doesn't update
  the matching schema default.

### 6.3 Methodology-drift patterns

- Timing decisions flowing back into direction authority (e.g. a new
  factor that uses 15m bar direction as alpha rather than timing).
- Factor_generator outputs used directly in execution without going
  through the promotion funnel.
- A round's ΔSharpe claim computed on overlapping data with the
  comparison strategy (test window bleed).

---

## 7. Appendix A — round log (update as you go)

| Round | Date | Topic | lineage_tag | Outcome |
|---|---|---|---|---|
| 0 (smoke) | 2026-04-20 | smoke + audit + NaN fix | post-2026-04-20-closeout | 19/20 quick pass, 0 OOS pass, NaN blocker found+fixed (`d562934`) |
| 0.5 (config) | 2026-04-20 | initial_capital 10k → 100k | — | methodology change; bump lineage_tag for all subsequent rounds |
| 1 | 2026-04-20 | Topic A (full smoke 80/1800 @ $100k) | post-2026-04-20-capital-100k | 37 trials, 56/57 quick pass, **0 OOS pass** → QQQ gate 未触发; completion signal 未达; plumbing 在单测层已充分覆盖; 研究 blocker: post-P0.1 口径下 80 trials 不足; Phase B "current best" 参数已标注为旧口径 (`07d51e5`) |
| 2 | 2026-04-20 | Topic B (leaderboard lineage + QQQ + per-lineage summary) | post-2026-04-20-capital-100k | 新 `lineage_summary()` + CLI 13 列 + `--lineage-filter` 参数; 3 新单测 1009→1012; Round 1 研究发现在 CLI 里一目了然 (`add1f80`) |
| 3 | 2026-04-20 | Topic C (stale_counts 持久化到 bar_checkpoints) | post-2026-04-20-capital-100k | save/load_bar_checkpoint 持久化 stale_counts dict; run_day_intraday 总是从 cp 恢复 counter 支持跨日累积; 6 新单测 1012→1018; 端到端验证 5+6 days halt cumulative 触发 ghost cleanup (`5bc3e4e`) |
| 4 | 2026-04-20 | Topic D (factor gate WARN/ERROR 可配置) | post-2026-04-20-capital-100k | 新 UnregisteredFactorError + enforce_execution_factor_names(strict=...) + FactorRegistryConfig schema + config/risk.yaml 段; 生产脚本 + mining space 全透传; 11 新单测 1018→1029; **§3.1 A-D 全部关闭** (`f4ee30d`) |
| 5 | 2026-04-20 | Topic F (intraday factor family: realized_vol_60m_21d, intraday_vol_ratio_21d, intraday_autocorr_21d) | post-2026-04-20-capital-100k | factor_generator 加 `intraday_bars_60m` 参数 + 3 个新 research-only 因子; registry 同步; 10 新单测 1029→1039; 真实数据 IC smoke 显示 **realized_vol_60m_21d IC_21d = +0.096** (非平凡), 其余 marginal; 不 promote (`710e8c3`) |
| 6 | _pending_ | 推荐 Topic E (shadowed-factor merge) | post-2026-04-20-capital-100k | _pending_ |
| ... | | | | |

---

## 8. Appendix B — decision record

### 2026-04-20 / smoke mining v1 findings

- **BLOCKER:** `int(NaN)` crash in `_generate_orders` when
  `integer_shares=True` + NaN target weight (happens during composite
  warmup). Fix: guard `cur_w` / `tgt_w` / `qty` with `np.isfinite`
  before arithmetic (`d562934`). Added `test_generate_orders_nan_guard.py`.
- **DATA POINT:** On this universe + budget, 19/20 strategies pass
  quick but ALL fail OOS (mean oos_ir ≈ -0.49). Not a bug — consistent
  with prior documented finding that direction voting at intraday/mixed
  lookbacks is hard to make work. QQQ gate never fires because Stage 6
  is gated on passed_oos.
- **NON-FINDING:** open_df warning fires in mining because Mining
  Evaluator runs backtest without open_df (falls back to close as
  execution proxy). Acceptable for mining research (documented in
  CLAUDE.md §Pricing and Valuation Semantics); not acceptable for
  production paper. Left as a NON-BLOCKER.

---

## 9. Change log for this PRD

| Date | Change |
|---|---|
| 2026-04-20 | Initial draft after smoke mining v2 verification |
