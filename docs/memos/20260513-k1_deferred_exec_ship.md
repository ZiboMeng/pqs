# K1 Ship Memo — Deferred-Execution Wrapper Complete

**Date**: 2026-05-13
**Status**: K1 SHIPPED (commits `37417ab` design + `7ee24f3` tests + `47ca31f` impl)
**Authors**: operator (zibomeng@) + Claude Code assist

---

## §1 What shipped

K1 (post-cycle10 strategic roadmap v2 §9 keystone) is COMPLETE.

Deliverables:
- `core/backtest/signal_driven_runner.py` — 212 lines, `SignalDrivenBacktest` wrapper class
- `tests/unit/backtest/test_signal_driven_runner.py` — 30 unit + integration tests
- `docs/audit/20260513-k1_deferred_exec_design.md` — design audit (K1.1)
- `docs/audit/20260513-k1_regression_report.md` — regression validation (K1.4)
- This closeout memo (K1.5)

Test surface delta: +30 tests (~1.3% of 2323 baseline), well under the
+84 test budget projected in Q6 audit conclusion. 30/30 GREEN.

---

## §2 What it does

`SignalDrivenBacktest` lets a strategy define backtest behavior as:
- `entry_signals: pd.DataFrame[date × symbol] bool` — when does ARMED state begin?
- `exit_signals: pd.DataFrame[date × symbol] bool` — when does position close?
- `confirmation_predicate(state, bar_idx, ctx) -> bool` (optional) — TTL window confirmation logic
- `position_sizing_rule(state, bar_idx, ctx) -> float` (optional) — fill weight
- `ttl_bars: int` — 0 = same-bar AND-gate (§3.1); 1+ = TTL window (§3.2)
- `top_n: int + max_single_weight + cluster_cap` — cap_aware position constraints

Internally, it drives `SignalStateMachine` + `DeferredExecutionSchedule`
(existing kernels) through bars, produces a (date × symbol) weight panel,
and delegates to existing `BacktestEngine.run` for NAV/cost computation.

**The existing `BacktestEngine` is UNCHANGED**. M11a/M11b parity bit-for-bit
preserved for all cycle04-10 backtests by construction.

---

## §3 Why wrapper, not engine modification

K1.1 design originally planned to extend `BacktestEngine.run` with
`execution_mode={"calendar", "signal_driven"}` dispatch. During K1.2 RED
phase the kernel was audited and revealed already to be a clean
weight-panel producer — engine modification was unnecessary.

Wrapper benefits:
- **Zero M11a/M11b parity risk** — `BacktestEngine.run` source unchanged
- **No API surface bloat** — `BacktestEngine.__init__` and `.run()` signatures unchanged
- **Wrapper testable in isolation** — 30 tests against pure wrapper logic, not engine internals
- **Composable** — wrapper can be subclassed for T1a alt-A intraday, T1b ConfirmationPattern, etc.

This is a design refinement during implementation, not a scope cut. All
PRD §4.1 acceptance criteria met.

---

## §4 Test-first discipline verified

Per Q6 audit conclusion: K1 = strict TDD. Verified:
- K1.2 (commit `7ee24f3`): 30 tests written; 27 RED + 3 GREEN (the 3 green = validation tests in `__init__`, which were also satisfied by stub)
- K1.3 (commit `47ca31f`): implementation; 30 RED → 30 GREEN
- K1.4 (this commit): regression validation; 199/199 backtest unit-tests PASS

No test was retroactively rewritten to match implementation. Every test in K1.2 was authored from the K1.1 design spec.

---

## §5 What's unlocked

T1a alt-A `IntradayReversalStrategy` Phase 2-3 (Track A acceptance + NAV correlation gate) is now unblocked. Estimated 3-5 days. Will be the first real consumer of `SignalDrivenBacktest`.

T1b ConfirmationPatternStrategy Phase 2-3 unblocked. Estimated 1 week (after T1a end-to-end validation).

T1c alt-B event-calendar (PEAD+FOMC bundle) unblocked. Estimated 3-4 weeks.

T2a + T2c (signal-driven cycle11 + ML Phase 2) unblocked once T1 sleeves ship.

Per roadmap v2 §5, K1 → T1a → (T1b ∥ T1c) → (T2a + T2c) = 8-10 weeks to 4-sleeve fleet.

---

## §6 Self-audit (R1-R4)

**R1 事实**：
- ✅ 5 个 commit：`10838c5` v1 / `a6aa4f0` v1.1 / `7b12d85` v2 / `37417ab` K1.1 / `7ee24f3` K1.2 / `47ca31f` K1.3
- ✅ K1.5 (this memo) + CLAUDE.md edit 准备 commit
- ✅ 30/30 K1.2 tests GREEN
- ✅ 199/199 backtest tests PASS（无回归）

**R2 逻辑**：
- ✅ Wrapper pattern 在每一个 K1.2 test 都验证（30 tests cover state machine / TTL / fills / exits / caps / leakage / costs / regression）
- ✅ M11a sorted-iteration discipline 保留在 wrapper 内部（4 处 sorted iteration）
- ✅ K1.1 §11 acceptance 6 项 5/6 ✓（剩 1 项 = 此 memo）

**R3 真正执行**：
- ✅ K1.2 测试在 RED 阶段 collect 成功
- ✅ K1.3 实现后 30/30 GREEN（实际跑 pytest 验证）
- ✅ M11a hash determinism test PASS
- ✅ 199 个 backtest 单元测试 PASS（regression check）

**R4 边界**：
- ⚠️ T1b 第一次实际消费 wrapper 可能暴露 `ctx` 字典需要扩展（`indicator_panels` / `regime_series`）—— additive change，不破现有 K1.2 测试
- ⚠️ 未在 K1 范围测试：risk overlay / kill_switch 集成（K1.1 §3 列了，但 K1.2 测试集没覆盖；defer 到 T1a 真正接入时验证）
- ✅ Sealed 2026 panel 未读

---

## §7 Next session task

下一步 = **T1a alt-A IntradayReversalStrategy Phase 2-3**。

T1a 子任务（待 K1.5 commit + push 完成后开 task）：
1. T1a.1 — 读 `core/signals/strategies/intraday_reversal.py` 现有 skeleton + PRD `docs/prd/20260512-alt_archetype_intraday_reversal_prd.md`
2. T1a.2 — 写 `IntradayReversalStrategy` 端到端单元 + 集成测试
3. T1a.3 — 跑 Track A 17 闸 acceptance
4. T1a.4 — NAV correlation gate vs trial9_diversifier_002（如果通过 Track A 17 闸）
5. T1a.5 — Closeout memo + Track A nominee（如果通过）OR informative null（如果不通过）

预计 3-5 天 wall-clock。

---

## §8 What this memo locks in

K1 ship status = **PRODUCTION**:
- `SignalDrivenBacktest` is the canonical signal-driven backtest entry for PQS
- All T1 / T2 workstreams will consume it
- API contract: see `core/backtest/signal_driven_runner.py` docstring
- Test surface: `tests/unit/backtest/test_signal_driven_runner.py` (30 tests)
- Design rationale: `docs/audit/20260513-k1_deferred_exec_design.md`
- Regression report: `docs/audit/20260513-k1_regression_report.md`
- Closeout (this): `docs/memos/20260513-k1_deferred_exec_ship.md`
