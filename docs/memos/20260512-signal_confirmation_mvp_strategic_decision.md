# Strategic memo — Signal-confirmation MVP kickoff decision (2026-05-12)

**Date**: 2026-05-12
**Author**: operator (zibomeng@), with Claude Code assist
**Status**: APPROVED — proceed to PRD v1.1 ship + Phase 1 kickoff
**Cross-ref**: `docs/prd/20260512-signal_confirmation_strategy_expansion_prd.md` (v1 → v1.1)

---

## Trigger

2026-05-12 全盘审计 finding —— PQS 当前所有 forward observation
candidate 均已 dead or pending:

| Candidate | Status |
|---|---|
| RCMv1 (core_alpha) | aborted 2026-04-30 (108 bps NAV drift fail-closed) |
| Cand-2 (core_alpha orthogonal) | aborted 2026-04-30 (同上) |
| trial9_diversifier_001 (diversifier) | completed_fail 2026-05-12 (bound_only halt) |
| trial9_diversifier_002 (diversifier) | not_started, TD001 = 2026-05-13 EOD |
| spy_8otm_bull_put_v1 (options paper) | 5 obs / 0 trades / NAV unchanged |

**已确证 PQS 在生产新框架下能产出独立 NAV alpha 的 candidate 数量 = 0**。

Cycle04-08 + Trial 3 共 5 个 mining cycle 试图找新的 core_alpha 因子组合，结果集体陷入 sibling-by-NAV
geometry：长仓 + 78-stock universe + 同 cap_aware monthly top-10 construction → Trial 3
(唯一 Track A 17/17 PASS 的) NAV corr vs RCMv1 = 0.874 / vs Cand-2 = 0.892。**问题不在因子选择，在 construction layer**。

PRD `docs/prd/20260512-signal_confirmation_strategy_expansion_prd.md`
提出走"strategy-type pivot"路径——把"截面排名 → 立即买"改为
"setup → 等 TTL window 内 confirmation → 才买"，引入时间作为新的
signal-state 维度。理论上有打破 sibling-by-NAV 的 potential（empirical question, NOT a-priori guaranteed）。

---

## 决策

**Decision 1 — ASAP kickoff (no evidence-conditional gating)**

不等 trial9_diversifier_002 forward evidence (TD30 ~6/25 / TD60 ~8/6)
来决定是否启动 signal-confirmation MVP。**直接开工**。

Reason:
1. PQS 当前在 "0 NAV-distinct candidate" 状态。等 60 天 evidence 而不在
   parallel 上独立工作流，整体进度风险大于工程投入风险。
2. Signal-confirmation MVP 测的假设（"TTL + confirmation 能打破 sibling
   construction 几何"）跟 trial9_002 测的假设（"diversifier role 角色分工能跑出独立 NAV"）
   **是不同的、independent 的假设**。Trial 9 v2 GREEN 或 RED 都不会直接告知
   signal-confirmation MVP 的 alpha 价值。
3. 工程时间窗 ~3.5 周 + 1 cycle mining (~6/10) 跟 trial9_002 TD30
   (~6/25) 重叠；不是 serial 串行而是 parallel，互不阻塞。

**Decision 2 — Dual-role acceptance (不预设 mining 应该产 diversifier 还是 core_alpha)**

Mining cycle yaml **不预设 candidate role**。Mining 出来的候选评估时：
- 优先跑 core_alpha gate (vs SPY HARD full period + 2025 holdout HARD +
  per-year max_dd ≤ 20% + concentration + stress slice)
- 如果 core_alpha gate fail，但满足 diversifier gate (vs SPY > 0 +
  cross-asset utilization ≥ 15% + factor_overlap_with_active_core = 0 +
  raw NAV corr < 0.70 + residual < 0.50)
  → 接受为 diversifier-role nominee
- 双重 fail → 0 nominee

Reason: PRD v1 §4.3 隐含偏向 "core_alpha" sibling-breaking (acceptance 用
RCMv1 / Cand-2 / Trial 9 NAV corr < 0.85 作 reject)。但 mining 出来如果是
diversifier-style 候选 (e.g., 跟 SPY 完全脱钩、cross-asset 重 weight)，
也应该接受。**两种 role 都是 fleet allocator 可用产出**。

**Decision 3 — Scope: §3.1 + §3.3, drop §3.2**

PRD v1 提了 3 个 sub-pattern：
- §3.1 same-bar AND-gate (volume confirmation): KEEP. Cheap (~1 day extra).
  作为 "无 state machine" 的 baseline 对比。
- §3.2 next-bar deferred (T+1 confirmation candle): DROP. 它实质上是
  §3.3 ttl_bars=1 的 degenerate case；多写一个 code path 浪费 effort。
- §3.3 multi-bar TTL window (breakout-then-retest): KEEP. 主菜。

Total scope: 3 patterns → 2 patterns。Engineering total 仍然 ~3.5 周
(PRD §5 + audit F7 修正后的估算)。

---

## 拒绝的备选方案

**A. Evidence-gated approach** — 等 trial9_002 TD30 verdict 再 kickoff。
**Rejected because**:
- 60 天 wait 期间整体推进 = 0；signal-confirmation MVP 跟 trial9_002 是
  independent hypothesis，evidence-gate 没逻辑必要
- 6/25 之后再 kickoff，~8 月初才出第一波 evidence → trial9_002 TD60 (~8/6)
  和 signal-confirmation evidence 同时到，反而 decision 更复杂

**B. Role-restricted MVP (只产 diversifier-style or 只产 core_alpha)** —
预设 mining 只搜索一种 role 的候选。
**Rejected because**:
- 预设 role 等于预设 "alpha source 在哪个方向"，但 signal-confirmation 测的
  正是 "construction 改变能产生什么样的 NAV 形状" —— 让 mining 自己 surface
- PQS 当前两种 role 都缺 candidate (RCMv1 dead / trial9 等观察)，无偏废
  原则

**C. 等 codex review 1 轮再 kickoff** —
PRD scope 不小 (state machine + backtest engine 改造 + 新因子族)，
codex external review 价值高。
**Rejected because**:
- ASAP 决策的本意是不等。审计 + codex review 都加上等于变成 ~2 周前置。
- F1-F9 audit findings 已经在 PRD v1.1 修了 9 个，operator 4-round audit
  覆盖了主要 R1-R4 boundary。Codex review 可以 in-flight 跟工程并行。

---

## 风险承认

1. **0-NAV-distinct-candidate 状态下的基础设施投资**：trial9_002 forward
   未开始，整个 PQS 没有任何活着且确证 NAV-distinct 的 candidate。3.5 周工程
   + 1 cycle mining 时间 = 沉没成本，如果 mining 0 nominee 而 trial9_002 也
   RED，那时需要更深层的 "PQS 整个 selection 范式有没有问题" 的反思
   (universe / 数据频率 / strategy-type) 而不是再 swing strategy type。
2. **PRD v1.1 没过 codex review**：F1-F9 是 operator audit 找到的，外部独立
   reviewer 可能发现 architectural 风险（最大概率：backtest engine
   deferred-execution 跟 M11a/M11b 已硬化的 parity 互相影响；factor
   pipeline contract 跟新 multi-bar 因子族冲突）。
3. **acceptance criteria 双 role gate 的 cherry-pick 风险**：post-mining
   两个 gate 都试，相当于 "P(reject) 降低"。需要保留 yaml 的 immutability
   原则——双 gate 必须在 cycle yaml pre-register，不能 post-hoc 加。

---

## Follow-up 行动 (this memo 不 enforces 调整规则)

per Decision 1，**no conditional adjustment rules**。trial9_002 evidence
跟 signal-confirmation MVP 各自独立 evaluation，两条路 verdict 出来后
另起 directional 决策 memo（不在本 memo 范围）。

只 enforces：
1. PRD v1.1 ship (F1-F9 + Decision 2 dual-role + Decision 3 scope = 2 patterns)
2. PRD v1.1 ship 后 ASAP kickoff Phase 1 (state machine + tests)
3. ~6/10 出第一 mining cycle evidence；按 PRD v1.1 §4.3 dual-gate 走 acceptance
4. Post-acceptance 写 closeout memo (包括 dual-gate 路径的 verdict 解释)

---

## 跨引用

- PRD v1: `docs/prd/20260512-signal_confirmation_strategy_expansion_prd.md` (现状)
- Audit 输入 1 (sibling-by-NAV evidence): `docs/memos/20260507-cycle07a_trial3_red_verdict_evidence_only.md`
- Audit 输入 2 (cycle direction options): `docs/memos/20260506-cycle07_to_fleet_final_synthesis.md`
- Audit 输入 3 (priority realign — guard before alpha 警告): `docs/memos/20260430-priority_realign_alpha_first.md`
- Trial 9 v2 closeout: `docs/memos/20260512-trial9_diversifier_001_closeout.md`
- Trial 9 forward evidence (load-bearing for "0-candidate state"
  claim): `data/research_candidates/trial9_diversifier_002_forward_manifest.json` (TD000)
