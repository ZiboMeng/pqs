# PRD-X — Trigger/Threshold-First 调仓与执行决策架构 (v1, pre-audit, archived)

**Status**: ARCHIVED v1 — superseded by post-audit v2
(`20260519-trigger_threshold_first_rebalance_architecture.md`).
This file is preserved for audit-trail purposes per the project's
non-deletion discipline. The v2 was authored 2026-05-19 after a
two-round audit that integrated 18 issues + 3 architectural-
conflict resolutions; the active PRD is v2.

**Honesty note (2026-05-19)**: I (Claude) initially claimed v1 was
"preserved in git history" — this was WRONG. v1 was never
committed to git (the user uploaded it as an unstaged file; my
Write tool overwrote it in-place creating v2 in a single commit
which git treated as net-new content). R3 self-audit (post-commit
`git log --oneline path`) caught the mistake. This file
reconstructs v1 from my context buffer (full 552-line content
displayed by Read tool earlier in the same session). The hash
`be8e44a` (PRD-2 P2.1 R6-final commit chain context) does NOT
contain v1 — only the 2026-05-19 v2 commit `806ab58` touched this
file path. v1 below = best-effort reconstruction from session
context, not git history.

---

# PRD-X — Trigger/Threshold-First 调仓与执行决策架构

**日期**: 2026-05-19 · **lineage**: `trigger-threshold-first-rebalance-2026-05-19`
**性质**: 新主轴 PRD。把项目从 `cadence-first`（先定日/周/月再调仓）重构为 `decision-trigger-first`（先定义何时该动、动多少、为何退出，再决定 review cadence / execution schedule）。
**纪律**: `feedback_no_over_conservative_scoping`、`feedback_no_blanket_failure_verdict`、`feedback_temporal_split_discipline`、`feedback_self_audit_methodology`。
**触发**: 用户明确指出"别总卡在 daily/monthly/weekly 调仓窠臼；有 factor / event 就该能决定要不要调、何时退出、是否可用 ML 决定调仓"。
**外部依据**:
- AQR：rebalancing 本身是 active decision；应结合 momentum / cost / tolerance，不应机械定频。
- MSCI：业界常用 buffer rules / turnover budget / staggered rebalance / ad-hoc trigger，不是只有固定频率。
- BlackRock：dynamic factor timing 以 regime / valuation / sentiment / factor-specific 指标组合驱动。
- 学术 transaction-cost 文献：no-trade band / tolerance region / cost-aware rebalance 属标准方法，不是"土办法"。

---

## §1 核心论点

当前项目的主研究纪律已经足够严格，但**决策层抽象仍偏旧**：

- `rebalance_cadence`
- `min_holding_days`
- `rebalance_threshold`
- `timing/defer/veto`
- confirmation / deferred execution
- event-window / signal-confirmation features

这些能力已经分散存在，但还没有被统一成一套"**何时该动、动多少、为何退出、如何执行**"的决策架构。

因此，本 PRD 的目标**不是**"把月调仓改成周调仓"，而是把系统升级为：

```text
alpha / factor / event evidence
  -> decision policy (enter / hold / trim / exit / no-trade)
  -> execution policy (when / how much / split / defer / veto)
  -> portfolio construction update
```

**固定 cadence 退位为 review / safety / fallback 机制，不再是主逻辑。**

---

## §2 问题定义（对当前系统的诚实审计）

### 2.1 目前做得好的

- PRD-1/2/3 已经建立了 leakage-correct、walk-forward、stress、cost、DSR/PBO 的严谨研究纪律。
- `core/intraday/multi_timescale.py` 已把 60m/30m 定义为 context，15m/5m 定义为 trigger/defer/veto。
- `core/backtest/deferred_execution.py` 已有 deferred fill kernel。
- `core/signals/signal_state.py` 已支持 armed → confirmed → fill 的状态机。
- `rebalance_threshold` / `min_holding_days` / `timing_scale` 等局部控件已存在。

### 2.2 目前真正缺的

1. **决策层没有统一接口**  
   进入、加仓、减仓、退出、延后执行、部分执行，分别散在不同模块。

2. **调仓被建模为固定频率动作，而不是 evidence-triggered 动作**  
   当前更像"到月末再看 top-N"，而不是"有何证据值得动仓"。

3. **exit 机制弱于 entry 机制**  
   系统有不少 entry / selection 逻辑，但缺统一的 factor-exit / event-exit / risk-exit policy。

4. **production/live 闭环未成型**  
   当前仍无 active validated production strategy；dividend 口径未完全并入主收益链；broker/live-feed 仍是 seam 而非完整执行闭环。

### 2.3 这轮审计抓到、且已在 2026-05-19 修正的历史问题（必须留痕）

- `core/research/b1_intraday_features.py::intraday_volume_z()` 先前实现对"日内 volume 的日内 z-score"求均值，理论上恒等于 0，属于死特征；现已修为 volume-distribution skew，并有回归测试。
- `dev/scripts/track_a/a1_b1_nav_track_a.py` 先前读取 concentration 指标 key 错，用缺失 key 默认 `0.0` 形成 false-PASS；现已改读真实 `m12_*` key。
- 同一 Track-A 脚本先前即使 `--only a1` 也执行 B-side gate，造成假耦合；现已把 gate 挪回 B1 分支。

这些问题**不再是当前 blocker**，但它们改变了 intraday-ML 若干旧结论的可信度，因此后续制度设计必须以修正后的 verdict 为准，而不是以原 close-out 为准。

### 2.4 修正后新增的更强战略结论

`docs/memos/20260519-strategic_close_out_REVISION_post_audit_fix.md` 给出的 post-fix 结论，对本 PRD 有直接约束：

- intraday ML 预测的**方向(sign)**在 3 类模型上都保留了正信息。
- intraday ML 预测的**连续幅度(magnitude)**在 3 类模型上都表现为噪声或负贡献。

因此，本 PRD 后续若做 ensemble / trigger policy，默认应优先考虑：

- `sign-vote`
- `rank-vote`
- `include / veto`

而**不是**连续加权平均预测值。这和本 PRD 的 trigger-first 架构是同向的：ML 更适合给出 `trade / no-trade / include / veto / urgency`，而不是直接无约束输出全仓位强度。

---

## §3 新架构：从 Cadence-First 到 Trigger-First

### 3.1 五层抽象（新的单 SoT）

| 层 | 职责 | 例子 |
|---|---|---|
| **Evidence Layer** | 提供 alpha / factor / event / regime / risk 证据 | value signal, momentum decay, earnings event, VIX spike |
| **Decision Layer** | 决定 enter / hold / trim / exit / no-trade | "信号增强但未过阈值 → hold" |
| **Execution Layer** | 决定 now / defer / split / partial / veto | 15m conflict → defer；流动性差 → partial |
| **Construction Layer** | 把决策转成目标权重变化 | top-N, cap-aware, cross-asset overlay |
| **Review Layer** | 固定 cadence 的审查/兜底，不是主驱动 | weekly sanity review / monthly full refresh |

### 3.2 关键定义

- **Review cadence**: 多久强制全量审查一次，不等于必须调仓一次。
- **Decision trigger**: 满足某些证据 / 阈值 / 事件后才允许调仓。
- **Exit trigger**: 导致减仓/平仓的证据，不要求等到下一个固定 cadence。
- **No-trade band**: 有轻微信号变化但未越过成本敏感阈值时，不交易。
- **Partial rebalance**: 达到动作条件，但只执行一部分目标变化。
- **Execution schedule**: 决定立即成交、下一 bar 成交、分批成交、或 veto。

---

## §4 决策状态机（本 PRD 的中心）

### 4.1 Position 生命周期

```text
FLAT
  -> ARMED_ENTRY
  -> CONFIRMED_ENTRY
  -> ENTERED
  -> HOLD
  -> ARMED_EXIT / ARMED_TRIM
  -> CONFIRMED_EXIT / CONFIRMED_TRIM
  -> EXITED / TRIMMED
  -> FLAT
```

### 4.2 每个状态的触发来源

| 状态变化 | 允许来源 |
|---|---|
| `FLAT -> ARMED_ENTRY` | factor trigger / event trigger / regime trigger |
| `ARMED_ENTRY -> CONFIRMED_ENTRY` | confirmation rule / multi-TF alignment / persistence |
| `ENTERED -> HOLD` | signal still valid but below action threshold |
| `HOLD -> ARMED_TRIM` | factor weakening / volatility spike / crowding / cross-asset better opportunity |
| `HOLD -> ARMED_EXIT` | exit factor / event invalidation / hard risk / thesis break |
| `ARMED_* -> CONFIRMED_*` | repeated evidence / TTL-in-window confirmation |
| `CONFIRMED_* -> EXECUTED` | execution policy permits fill |

### 4.3 决策动作集合

动作不再只有"换/不换仓"：

- `ENTER_FULL`
- `ENTER_PARTIAL`
- `ADD`
- `HOLD`
- `TRIM`
- `EXIT`
- `DEFER`
- `VETO`
- `NO_TRADE`

---

## §5 触发器体系（替代"固定每周/每月必须动"）

### 5.1 Entry triggers

#### A. Factor-strength trigger

当以下任一满足时，允许从 `FLAT` 进入 `ARMED_ENTRY`：

- factor score 穿越上阈值
- factor rank 从中性区跃迁至候选区
- composite score / sign-vote / rank-vote 与现持仓机会集拉开足够 gap
- residualized alpha 对已持仓组合产生真实增量

#### B. Event trigger

- earnings / macro / FOMC / sector event 后，既有 thesis 被显著增强
- event-window factor 显著转正
- catalyst 兑现前，允许进入 armed but unfilled 状态

#### C. Regime trigger

- 当前 regime 进入某 factor historically favored zone
- 风险状态从 risk-off 切回 neutral/risk-on

### 5.2 Exit triggers

#### A. Thesis decay / factor exit

- alpha score 跌破 exit threshold
- sibling-overlap 上升，edge 消失
- expected excess 低于成本缓冲

#### B. Event invalidation

- 事件后 drift 不成立
- catalyst 已兑现且 edge 消退
- fundamental trigger 被反证

#### C. Risk exit

- volatility / drawdown / liquidity deterioration
- concentration / crowding / correlation budget breached
- higher-TF context 从 confirm 变为 strong veto

### 5.3 No-trade band

不是所有 signal 变化都值得动仓。应定义：

- `enter_band`
- `add_band`
- `trim_band`
- `exit_band`

当证据只落在 band 内时：

- 保持 `HOLD`
- 不生成订单
- 只记录"decision reviewed, no trade"

这条是 transaction-cost-aware 的核心，而不是附属优化。

---

## §6 Execution Policy（从"是否该动"拆到"如何去动"）

### 6.1 执行动作不由 alpha 单独决定

alpha 只能决定"想动"；execution layer 决定：

- 现在动还是下一 bar 动
- 一次全动还是分批动
- 动 100% 还是 30%
- 因冲突 / 流动性 / 风险而 veto

### 6.2 已有模块如何接入

- `core/intraday/multi_timescale.py`
  - 保持"60m/30m = context，15m/5m = trigger/defer/veto"
  - 不允许 lower TF 反向发明方向
- `core/backtest/deferred_execution.py`
  - 作为 `CONFIRMED_* -> fill_at_bar` 的 canonical kernel
- `core/signals/signal_state.py`
  - 作为 armed / confirmed / TTL / expire 的状态机基座

### 6.3 新 execution policy 允许的 4 类行为

1. **Immediate full**
2. **Deferred**
3. **Partial**
4. **Staggered / split**

### 6.4 明确禁止

- 15m/5m 反向决定新的方向
- 因为到了周末/月末就强行动仓
- signal 很弱但为"保持 cadence"硬下单

---

## §7 Construction Layer 如何配合

### 7.1 组合构建不再直接消费"raw factor score"

新的构建输入应是：

```text
desired_position_change
  = decision_policy(evidence)
  x execution_policy(context, liquidity, cost)
```

然后才进入：

- top-N
- cap-aware
- cap-aware_cross_asset
- T1 hedge / overlay
- future fleet allocator

### 7.2 部分调仓是一等公民

构建层必须支持：

- target weight delta < full delta
- hold existing but block new adds
- trim without full exit
- exit one symbol while freezing others

当前项目已有 `rebalance_threshold`，但还不够，需要升级为显式的 **delta-to-trade policy**。

---

## §8 Review Cadence 的新定位

### 8.1 cadence 不消失，但退居次要

仍保留：

- daily review
- weekly review
- monthly full recompute

但其角色改成：

1. **健康检查**
2. **兜底刷新**
3. **慢因子重估**
4. **状态超时清理**

而不是"因为到周五了所以必须调"。

### 8.2 推荐层次

#### L0 每日

- 风险检查
- armed/confirmed 状态推进
- exit factor 检查
- execution fill 检查

#### L1 每周

- 重新评估中速因子
- 检查 no-trade band 外的增量机会
- 检查 partial rebalance 是否需续执行

#### L2 每月

- 全 universe / full ranking / structural rebalance
- 大权重迁移
- cross-asset exposure refresh

**结论**：`monthly` 更适合作为 full refresh，`daily/weekly` 更适合作为 trigger review，不应混为一谈。

---

## §9 ML 在调仓中的角色（允许，但严格限边界）

### 9.1 可以做什么

ML 可以用于：

- `trade / no-trade` classifier
- `include / veto` sign decision
- `partial size` regression
- `expected hold horizon` estimation
- `exit probability` / `decay probability`
- execution urgency / slippage-aware scheduling

### 9.2 不建议一上来做什么

- 直接端到端输出全组合调仓矩阵
- 跳过可解释 trigger，完全交给 black-box policy
- 在样本不大、成本模型未定、live闭环未成型时上 RL 直接控全流程

### 9.3 顺序建议

先做：

1. rule-based trigger
2. no-trade band
3. partial rebalance
4. ML sign-vote / trade-no-trade
5. ML exit / hold horizon
6. 更复杂的 dynamic control

---

## §10 与现有 PRD 的关系

### 10.1 与 PRD-2

PRD-2 负责 construction-DOF。  
本 PRD 负责 **上游决策层**，回答"何时有资格触发这些 DOF"。

### 10.2 与 PRD-3

PRD-3 负责 signal-layer ML arms。  
本 PRD 负责 **这些 signal 如何转化为 enter/hold/trim/exit**，避免 signal ≈ rebalance 命令。

### 10.3 与 forward / paper / fleet

本 PRD 是 future paper/live/fleet 的公共决策内核。  
如果没有它，后续 fleet allocator 只会接收到"固定 cadence 产出的静态目标权重"，表达力不够。

---

## §11 实施分期（可执行，不空谈）

## Phase X1 — 统一决策 schema（最小改动，先建 SoT）

### 目标

建立统一的 `DecisionPolicy` / `ExecutionPolicy` / `ActionDecision` schema。

### 交付

- 新 decision dataclasses / enums
- enter/hold/trim/exit/defer/veto/no_trade 统一动作字典
- 不改现有策略收益路径，只增加表达层

### AC

- 新 schema 单测全绿
- 既有 backtest/paper 默认路径 bit-identical

## Phase X2 — Rule-based trigger + exit policy

### 目标

把 factor / event / regime / risk 证据统一接成 rule-based 决策层。

### 交付

- factor entry / exit threshold
- event trigger / invalidate trigger
- higher-TF veto / defer 接口统一
- no-trade band

### AC

- 能表达"review 了但不交易"
- 能表达 partial / defer / veto
- 不能因为 cadence 到点而强制生成订单

## Phase X3 — Partial rebalance / delta-to-trade policy

### 目标

把"想要的目标变化"映射成"实际交易变化"。

### 交付

- full / partial / staged rebalance policy
- delta buffer / tolerance region
- turnover budget hook

### AC

- 同一 target change 在不同 cost/liquidity 下可产出不同 trade size
- 在成本放大 2x/3x 下，仍可执行 no-trade / partial fallback

## Phase X4 — Deferred execution + confirmation integration

### 目标

把 armed / confirmed / fill 调成主路径，而不是边缘实验件。

### 交付

- `signal_state` + `deferred_execution` 与 backtest/paper 统一接线
- entry/exit 的 TTL / expire / cancel 规则

### AC

- paper/backtest 行为一致
- signal_date / fill_date / eod mark 语义明确
- M11 parity 不退化

## Phase X5 — ML-assisted decision policy（后置）

### 目标

在 rule-based 架构跑通后，用 ML 学 trade/no-trade、trim、exit probability。

### 交付

- ML classifier/regressor 不直接控全组合，只做 policy sidecar

### AC

- 必须优于 rule-based baseline
- 成本放大与 deconfound 都要过
- 不允许黑箱跳过 risk/exit hard guard

---

## §12 验证与研究纪律

### 12.1 研究问题不能再写成"哪个 cadence 更好"

新的 research question 应改成：

- 哪类 trigger 带来正净值增量？
- no-trade band 是否降低 churn 且不伤 edge？
- partial rebalance 是否改善 cost-adjusted NAV？
- exit factor 是否优于 fixed holding period？
- ML policy sidecar 是否优于 rule baseline？

### 12.2 最少实验矩阵

必须比较：

- fixed cadence baseline
- trigger-only
- trigger + no-trade band
- trigger + no-trade band + partial
- trigger + no-trade band + partial + deferred/confirmation

### 12.3 绑定指标

- net vs SPY
- cost sensitivity
- turnover level + turnover concentration
- drawdown / crisis behavior
- decision frequency
- average hold time distribution
- canceled/deferred trade ratio

---

## §13 Live / Production 边界

本 PRD 明确：**当前还不是 production-ready，只是为 production-ready 铺决策内核。**

在以下条件未满足前，不进入真钱 live：

1. `production_strategy.yaml` 不再是 `conservative_default`
2. dividend 口径进入主收益链或被明确量化豁免
3. paper vs replay vs backtest drift 成为 hard gate
4. broker/live-feed seam 升级为真实 shadow workflow
5. trigger/exit policy 经过至少一轮真实 paper soak

---

## §14 非目标

- 不在本 PRD 内实现真 short execution
- 不在本 PRD 内直接改 fleet allocator
- 不在本 PRD 内直接上 RL 全自动调仓
- 不因"追求 trigger-first"废除 monthly full refresh

---

## §15 R1-R4 自审

- **R1**: 方向是否只是理念输出？  
  否。本文显式绑定现有模块：`multi_timescale` / `signal_state` / `deferred_execution` / `rebalance_threshold` / paper/backtest parity。

- **R2**: 是否偷换成"换个 cadence"老路子？  
  否。本文明确把 cadence 降级为 review/fallback，不再当 primary decision variable。

- **R3**: 是否脱离外部标准？  
  否。buffer / trigger / ad-hoc rebalance / dynamic factor timing / no-trade band 都有 MSCI / BlackRock / AQR / SSRN 的一手依据。

- **R4**: 是否对当前项目状态过度乐观？  
  否。已显式写入 recent bug、active strategy 缺失、dividend gap、broker/live-feed gap，并把它们列为 live gate 前置。

---

## §16 一句话版本

> 这个项目下一步不该继续问"日调/周调/月调哪个好"，而该问：
> **什么证据值得动仓、何时确认、何时退出、动多少、什么时候宁可不动。**
> cadence 只是 review 节奏，不应再是调仓的主语。
