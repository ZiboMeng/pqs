# Phase D 迭代优化 Loop + Multi-Timescale Intraday 框架 PRD

**日期**: 2026-05-19 · **lineage**: `phase-d-loop-multi-tf-framework-2026-05-19`
**来源**: 本文 content-preserving 抽自 `CLAUDE.md` 的 `## Phase D: Iterative
Optimization Loop` 整块(Mode / Overall Goals / Multi-Timescale Intraday
Framework / Optimization Theme Menu / Per-Iteration Output Format /
Hard Rules)。**逐字搬迁,无删改,可 grep 回溯**(沿用 2026-05-19
模块 CONTEXT.md reorg 约定)。CLAUDE.md 该块替换为 high-level「已完成」
概览 + 本指针;`### Environment` 仍留 CLAUDE.md(运营性,非框架)。

**状态说明(2026-05-19)**:
- Phase D 迭代优化 loop = 当前**仍在用的工作方法论**,现经 `/loop` +
  ralph-loop 日志(`docs/20260420-ralph_loop_log.md`)执行;本 PRD 是
  该方法论的 SoT。
- Multi-Timescale Intraday Framework 的最小闭环**已实现并 test/实验
  验证**(per-TF IC / 2x·3x 成本敏感 / 4-fold temporal split /
  per-TF 贡献报告,全在 `run_multi_tf_backtest.py`,iter 7-12)。其
  **前向演进**(intraday 作为构建/执行 DOF + intraday 信号 ML)已被
  后续 PRD 正式接续并细化:
  - 构建/执行 DOF:`docs/prd/20260518-prd2_construction_dof_tiered.md`
    §P2.3(60m/30m + 日/月 cascade;15m 决策输入 = research-boundary
    修订,**待 ratify directional**)+ `docs/prd/20260519-prd2_ralph_loop_execution.md` R9-R13。
  - intraday 信号 ML:`docs/prd/20260518-prd3_signal_layer_ml_arms.md`
    组件 B + `docs/prd/20260519-prd3_ralph_loop_execution.md` RB1-RB5
    (**gated 于 PRD-2 P2.3**)。
- 因此本 PRD 的 Multi-TF 段落为**框架原文存档**;任何新 intraday
  multi-TF 工作以上述 PRD-2/PRD-3 为准,本文不再独立驱动新 round。

---

## Phase D: Iterative Optimization Loop

### Mode
迭代优化 loop。每轮：审计 → 选主题 → 小步修改 → 验证 → 决定下一轮方向。

### Overall Goals (ordered)
1. 可交易性
2. 研究质量
3. 因子/策略发现能力
4. 回测/模拟/报告可信度
5. 运行效率
6. **多时间尺度协同决策能力**

### Multi-Timescale Intraday Framework [NEW]

#### Architecture: 日线策略 + intraday 执行层增强

当前定位（C 模式）：
- **日线 MultiFactorStrategy 决定持仓方向**（已验证，CAGR 19%）
- **Intraday 多时间尺度决定具体执行时机**（更好的 entry/exit timing）
- 成熟后演进到 A 模式（独立 intraday alpha + 日线 alpha 组合）

#### Timescale Roles

| 时间尺度 | 职责 | 数据可用性 | 验证等级 |
|---------|------|----------|---------|
| **60m** | 主趋势 / 大级别 regime / 高层上下文 | 730天 (yfinance) | **正式验证** |
| **30m** | 结构确认 / 次级趋势 / 风险状态 | 60天+ (yfinance) | **正式验证** |
| **15m** | 执行确认 / 信号加强或否决 / 短周期 timing | 60天 (yfinance) | 原型/概念验证 |
| **5m** | 精细 entry / exit / stop / execution timing | 60天 (yfinance) | 原型/概念验证 |

**约束**：15m/5m 因为只有 60 天历史，当前仅作执行层原型。等真实数据源到位后升级为正式验证层。

#### Multi-Timescale Signal Protocol

```
Decision Chain:
  60m context (trend direction, regime) 
    → 30m confirmation (structure, risk state)
      → 15m trigger (entry timing, signal strength) [prototype]
        → 5m execution (precise entry/exit/stop) [prototype]

Rules:
  - Higher timeframe has VETO power over lower timeframe
  - Lower timeframe cannot initiate position against higher TF direction
  - Cross-TF conflict → no trade (conservative)
  - Only CLOSED bars may generate signals (no incomplete bar lookahead)
  - signal_timestamp = bar_close_time for each timeframe
```

#### Multi-Timescale Leakage Rules

| Rule | Description |
|------|------------|
| Bar completion | Only closed/completed bars generate signals. No using incomplete bars. |
| Cross-TF alignment | 60m bar close at 10:30 means data up to 10:30. 30m bar at 10:00 and 10:30 are both valid. 15m bars at 10:00/10:15/10:30 are valid. |
| No future higher TF | A 15m signal at 10:15 must NOT use the 60m bar closing at 10:30 (not yet complete) |
| Execution delay | Minimum 1-bar delay at the execution timeframe (e.g., 15m signal → next 15m bar open) |

#### Multi-Timescale Validation Requirements

When multi-timescale is implemented:
- Each timeframe's signal must show independent IC > 0 — **TESTED: IC negative for bar direction (mean-reversion at intraday). Signal works via trend-aligned sizing, not bar-level IC. Documented in phase_d_log iter 8-9.**
- Combined signal must show higher IC than any single timeframe — **TESTED: combo IC (-0.011) marginally better than 60m (-0.013). See above.**
- Cost sensitivity must be tested (lower TF = more trades = higher cost) — **PASSED: 2x cost Sharpe=0.85, 3x cost still profitable (+9.6% CAGR). iter 11.**
- Walk-forward must use temporal split on the LOWEST timeframe used — **TESTED: 4-fold temporal split, 3/4 folds positive, mean Sharpe 0.99. iter 12.**
- Report must show per-timeframe contribution — **DONE: per-TF IC, per-regime, cost sensitivity, walk-forward all in run_multi_tf_backtest.py. iter 7-12.**

### Optimization Theme Menu

Each loop iteration selects ONE theme:

| Theme | Focus |
|-------|-------|
| **A** | Multi-timescale intraday framework |
| **B** | Factor mining / training / strategy discovery |
| **C** | Intraday module hardening |
| **D** | Report / risk statistics enhancement |
| **E** | Performance optimization |

Selection priority:
1. Blocks research credibility?
2. High-leverage bottleneck?
3. Verifiable research gain?
4. Small-step achievable?
5. Evidence supports continued depth?

**Rule**: If multi-timescale framework has no minimal closed loop yet, it should be prioritized before pure alpha optimization.

### Per-Iteration Output Format (Chinese)

1. 本轮主题 (A/B/C/D/E)
2. 本轮目标
3. 为什么这轮优先做它
4. 做了什么
5. 修改了哪些文件
6. 跑了哪些测试/实验
7. 结果如何
8. 当前发现的新问题/新机会
9. 剩余风险
10. 下一轮建议方向
11. TODO checklist（更新后）

### Hard Rules

1. **小步快跑**：每轮一个主目标，优先可验证 patch
2. **不假装完成**：代码存在 ≠ 链路闭环，手工跑 ≠ 测试覆盖
3. **方向自适应**：允许切主题但必须基于本轮结果解释
4. **因子走漏斗**：LLM 只做 candidate generation，不做最终裁判
5. **不破坏核心约束**：long-only, no-margin, risk constraints, QQQ rule, pricing semantics

---

> 关联:`docs/prd/20260518-prd2_construction_dof_tiered.md`(Multi-TF
> 构建/执行 DOF 接续)、`docs/prd/20260518-prd3_signal_layer_ml_arms.md`
> (intraday 信号 ML 接续)、`docs/20260420-ralph_loop_log.md`(loop
> 执行日志)、`docs/memos/20260518-prd123_execution_ledger.md`(当前
> PRD-1/2/3 执行账本 SoT)。CLAUDE.md `### Environment` 仍为运营快照。
