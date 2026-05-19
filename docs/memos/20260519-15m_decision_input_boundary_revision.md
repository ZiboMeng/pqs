# 15m: "research only" → "可作决策输入" — RATIFIED (2026-05-19 user explicit-go)

**Authority**: User explicit-go 2026-05-19（"ratify 15m boundary，继续
推进 P2.3"）。Resident-quant 起草，遵 QQQ-deprecation 先例
(`docs/memos/20260502-qqq_benchmark_deprecation.md`：decision memo +
CLAUDE.md Invariant 注记 + reversibility clause)。本 memo **不是"待
ratify"草稿**——用户已显式批准；先前 PRD-2 ralph-loop R9 要求的
"标待 ratify 不当已批" 约束已由本次 explicit-go 解除。

**触发**: PRD-2 `docs/prd/20260518-prd2_construction_dof_tiered.md`
§P2.3 + §5（research-boundary 修订必做、不静默）。binding constraint
是构建层（long-only 月度 cap_aware top-N），P2.3 要把 60m/30m + 日/月
cascade 作为 timing/sizing/veto 的构建/执行 DOF；其中 15m 作为决策
**输入**触及原 "Intraday: 60m/30m primary, 15m research only" 不变量，
故按先例显式文档化。

**Scope**: 1 项 invariant 修订 ⚙️ + 边界钉死 3 条 🔒（无量化阈值改动）。

---

## Why（要点，非 8-angle 长篇——本修订远小于 QQQ）

### W1 — 原边界的语义 vs 新用途不冲突
原 "15m research only" 限制的是：**15m 不得作为正式验证层 / 不得用
15m 历史下结论当 production 依据**（因 yfinance 15m 仅 60 天历史，统计
不足）。P2.3 用 15m 的方式 **不是** 拿 15m 序列做 alpha 验证 / 下
production 结论，而是把已收盘的 15m bar 作为**日线决策的执行/构建
timing 输入**（entry/exit/sizing/veto）。统计充分性的顾虑落在
"用它验证什么"，不落在 "用它做执行择时"——后者由日线层 alpha 背书，
15m 只决定"同一笔日线决策何时/以多大力度落地"。

### W2 — 框架边界本已写明 intraday=timing 非 alpha
CLAUDE.md Multi-TF Timing Contract 既有结论：naive bar-方向投票严格
输 60m-only。该负结论 scope 在 **naive voting**，非 blanket "intraday
无信号"。本修订严格落在 timing/执行/构建 DOF，**不**开 15m alpha
mining（intraday 信号是 PRD-3 组件 B，单独 gated 于 P2.3，且 PRD-3
明禁 15m 动量挖矿=老路子）。

### W3 — 先例与可逆
QQQ-deprecation 已确立 "invariant-adjacent 修订 = decision memo +
CLAUDE.md 注记 + 用户 explicit-go + reversibility" 的合规路径。本修订
严格沿用，且范围更窄（不动任何风险阈值/基准 gate）。

---

## Specific change（1 ⚙️ invariant 注记）

### ⚙️ CLAUDE.md Invariant Constraints

**Before**:
```
- Intraday: 60m/30m primary, 15m research only
```

**After**（注记式修订，照 QQQ `[REVISED … per memo]` 先例）：
```
- Intraday: 60m/30m primary（**正式验证层不变**）;
  15m 允许作**决策输入**（construction/execution timing：
  entry/exit/sizing/veto），**非** intraday-alpha-mining、**非**
  正式验证层 [REVISED 2026-05-19 per
  docs/memos/20260519-15m_decision_input_boundary_revision.md]
```

---

## 边界钉死（🔒 不变项——明确不在本修订范围）

1. **60m/30m 仍是唯一正式验证层**。15m 不得作为 alpha 验证 / OOS /
   production 结论的统计依据（其 60 天历史不足这一原始理由未变）。
2. **不开 15m / 5m alpha mining（老路子永禁）**。本修订只授权 15m 作
   *已有日线决策*的执行/构建 timing 输入；任何"挖 15m 动量/方向因子"
   仍属 PRD-3 组件 B 范畴且单独 gated，不被本 memo 解锁。
3. **SQQQ blacklist / no-margin(T0·T1) / long-only / 风险不变量
   (DD 15-20% / 2008-≤25% / halt 0.25) 全部不变**。本修订 0 阈值改动、
   0 基准 gate 改动。

---

## P2.3 实跑解锁

- 本 ratify 后 PRD-2 P2.3 R9 = ✅（directional 停等点解除）。
- 解锁 R10（Multi-TF leakage rules 单测）/ R11（intraday 成本模型
  硬化 3x）/ R12（multi-TF cascade wiring，timing/sizing/veto 非
  alpha）/ R13（P2.3 acceptance experiment：A/B 去混淆 + 3x 成本仍正
  + 不劣 60m-only，否则按 naive-voting 先例淘汰记 root-cause）。
- P2.3 实跑全程守 leakage-correct(PRD-1) + Multi-TF Leakage Rules
  (bar-completion / 无未来高 TF / ≥1-bar 执行延迟) + 60m-only baseline
  回归不得劣化。

---

## Reversibility

- 撤销本修订需 **用户 explicit-go** + 起草
  `docs/memos/YYYY-MM-DD-15m_boundary_revision_revoke_memo.md` +
  CLAUDE.md 注记回退（15m 复归 "research only"）。
- 与 QQQ-deprecation 撤销相互独立。
- 本修订**不**自动 cascade 到 5m（5m 仍 research/prototype only，
  其修订需另行 explicit-go + memo）。

---

**关联**: `docs/prd/20260518-prd2_construction_dof_tiered.md` §P2.3/§5、
`docs/prd/20260519-prd2_ralph_loop_execution.md` R9-R13、
`docs/memos/20260502-qqq_benchmark_deprecation.md`（合规先例）、
`docs/memos/20260518-prd123_execution_ledger.md`（执行账本 SoT）。
