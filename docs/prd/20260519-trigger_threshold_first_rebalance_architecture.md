# PRD-X — Trigger/Threshold-First 调仓与执行决策架构 (v2 post-audit)

**日期**: 2026-05-19 · **lineage**: `trigger-threshold-first-rebalance-2026-05-19`
**性质**: 新主轴 PRD。把项目从 `cadence-first`（先定日/周/月再调仓）重构为 `decision-trigger-first`（先定义何时该动、动多少、为何退出，再决定 review cadence / execution schedule）。
**纪律**: `feedback_no_over_conservative_scoping`、`feedback_no_blanket_failure_verdict`、`feedback_temporal_split_discipline`、`feedback_self_audit_methodology`、`feedback_audit_surfaces_not_thorough`。
**触发**: 用户明确指出“别总卡在 daily/monthly/weekly 调仓窠臼；有 factor / event 就该能决定要不要调、何时退出、是否可用 ML 决定调仓”。
**外部依据(R3 grep + 一手源 verified 2026-05-19)**:
- [AQR 2017 "Portfolio Rebalancing, Common Misconceptions"](https://www.aqr.com/Insights/Research/White-Papers/Portfolio-Rebalancing-Common-Misconceptions): "trending behavior favors **less-frequent rebalancing or wider tolerance bands**"。
- [MSCI Momentum Index Methodology](https://www.msci.com/index/methodology/latest/Momentum): "**Conditional Rebalancing Triggers** checked every month except the four quarterly Index Reviews"; 30% one-way turnover cap; 历史用过 staggered rebalance（2024-02 后部分指数移除该步）。
- BlackRock *Time to Tilt*: dynamic factor timing 由 regime / valuation / sentiment / factor-specific 指标组合驱动。
- [Lynch-Balduzzi 2000](https://pages.stern.nyu.edu/~alynch/pdfs/LT10_jfqa.pdf): no-trade region — 仅当 weight 远离 no-cost optimum 至 benefit 超过 transaction cost 时才调仓。
- Leland 1999: 最优 rebalancing 成本比 periodic complete rebalance 低 50%；**no-trade region should be LARGE when volatility is HIGH**（PRD v1 未含此关键 mechanic，v2 已纳入 §5.3）。
- 学术 transaction-cost-aware 文献：no-trade band / tolerance region / cost-aware rebalance 属标准方法。

---

## §0 v2 修订史(audit-driven)

v1 → v2 的变化由 2026-05-19 内部全面 audit 驱动（外部 auditor + operator R3 grep + 一手源核验，共 18 issue + 3 conflict）。所有原文 claim 保留在 v1 git history。v2 主要修订：

| 修订点 | v1 性质 | v2 处理 |
|---|---|---|
| `rebalance_threshold` 表达 | understates（仅 TAA harness 有，主 backtest 无） | §2.1 精化 |
| exit policy "弱" | **完全空白**（不是"弱"） | §2.2 精化 |
| 7 Strategy 类无统一接口 | scope 严重低估 | §F.2 Protocol+Adapter solution（**6/7 已共享 `.generate()`，1/7 是 blueprint**） |
| dividend "未并入主收益链" | **infra 已建完**，缺 SPY/QQQ 数据 + atr flag | §11 X0 + §13 gate2 精化 |
| no-trade band 缺 vol-conditional | 缺 Leland 关键 mechanic | §5.3.1 新增 |
| lifecycle 9 states vs `SignalStatus` 3 states | mapping 不清 | §4.1.1 新增 mapping 说明 |
| risk exit 不复用 KillSwitch/FailureDetector/StressTester | 漏复用 | §5.2.C 精化 |
| regime trigger 缺 RegimeDetector API contract | 缺接口规格 | §5.1.C 精化 |
| L0/L1/L2 review cadence "降级现有" | 是新建抽象（grep `review_cadence`=空） | §8 精化 |
| Evidence Layer "整理" | 完全新建（grep 空） | §3.1 精化 |
| 9 action enum 与现有重合度 | 完全 disjoint，新建 | §4.3 标注 |
| sealed-2026 / strict walk-forward 在 phase AC 缺位 | 关键纪律遗漏 | §11 各 phase + §12 补 |
| 不变量（long-only/no-margin/SQQQ/MaxDD/2008）在 PRD 缺位 | 关键纪律遗漏 | §6.4 新增 invariant guards 节 |
| fleet allocator 接口契约缺 | core/fleet/* 已在 | §10.3.1 新增 |
| phase X1-X5 顺序与已建/新建错位 | X4 deferred 已建，X3 partial 才是真新建 | §11 重排 + 新 X0 |
| §12 缺 cycle06 baseline regression | 项目唯一 PASS baseline 缺 | §12.0 新增 |
| §11 X4 M11 parity AC 不可验证 | AC 模糊 | §11 X4 精化 test matrix |
| §11 X1 "最小改动 bit-identical" 表达 | scope 误导 | §11 X1 精化 |

3 处 architectural conflicts(详 §F)经 R3 grep 全部找到现有 pattern → **不是"冲突",是"延伸现有"**：
- C1 backtest_engine 主路径 → 已有 `signal_driven_runner.py` pattern：weight panel → BacktestEngine.run unchanged，M11 parity 保留。
- C2 7 Strategy 不统一 → 6/7 已共享 `.generate()`，1/7 是状态机 blueprint；Protocol+Adapter 0 strategy 改动。
- C3 dividend → infra+876-row distributions.parquet+9 callers 全在，缺 SPY/QQQ 数据 + atr flag。

---

## §1 核心论点

当前项目的主研究纪律已经足够严格，但**决策层抽象仍偏旧**：

- `rebalance_cadence`
- `min_holding_days`
- `rebalance_threshold`(仅 TAA harness)
- `timing/defer/veto`(cascade_overlay R12)
- confirmation / deferred execution(intraday_reversal & confirmation_pattern 已用)
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

## §2 问题定义（对当前系统的诚实审计，post-audit 精化）

### 2.1 目前做得好的（reusable，R3-verified）

- PRD-1/2/3 已经建立了 leakage-correct、walk-forward、stress、cost、DSR/PBO 的严谨研究纪律。
- `core/intraday/multi_timescale.py` 已把 60m/30m 定义为 context，15m/5m 定义为 trigger/defer/veto（grep-verified line 15-30）。
- `core/backtest/deferred_execution.py` 已有 `DeferredExecutionSchedule` + `ExecutionScheduleEntry`（但**当前仅 intraday_reversal_runner + confirmation_pattern 消费**，主 backtest 路径未接通）。
- `core/signals/signal_state.py` 已有 `SignalStateMachine` + `SignalStatus.{ARMED, CONFIRMED, EXPIRED}` 3-state enum（v1 写"armed → confirmed → fill"准确，但**只有 3 个 state**，本 PRD §4 的 9 个 lifecycle 状态需要做 mapping，详 §4.1.1）。
- `min_holding_days`（`core/research/harness/composite_evaluator.py:74`）+ `timing_scale`（`core/research/cascade_overlay.py:79`）局部控件存在。
- `rebalance_threshold`（`core/research/taa/taa_harness.py:129` default 0.02）— **仅 TAA harness 路径有**，主 `BacktestEngine.run()` 仍是 rebalance-cadence-driven，**无 delta-to-trade policy**。这是 §11 X3 的真新建空间，不是"升级"。
- `core/backtest/signal_driven_runner.py` 已存在，明文不修改 `BacktestEngine.run` 而通过 weight panel 接口消费 → **M11a/M11b parity bit-for-bit 保留** —— 这是 §F C1 的 architectural solution（决定层 → weight panel → BacktestEngine.run）。

### 2.2 目前真正缺的（R3-verified）

1. **决策层无统一接口** —— 7 个独立 Strategy 类：MultiFactorStrategy / DualMomentumStrategy / TrendFollowingStrategy / SimpleBaselineStrategy / IntradayReversalStrategy / CrossAssetRotationStrategy / ConfirmationPatternStrategy。**6/7 已共享 `.generate()` 方法签名**（grep-verified），**1/7（IntradayReversalStrategy）有 4 方法状态机**（`detect_setups` / `confirm_signals` / `build_target_weights` / `step_day`）—— **这个状态机模式正是本 PRD §4 decision-layer 的 blueprint，不是异类**。Solution 在 §F.2。

2. **调仓被建模为固定频率动作，而非 evidence-triggered 动作** —— 主 backtest 路径默认 monthly cadence，TAA harness 是唯一例外。

3. **exit 机制完全空白**（不是"弱"） —— `grep exit_trigger | exit_threshold | thesis_decay | factor_exit | alpha_decay | exit_policy = EMPTY`。系统有 entry / selection 逻辑，**零** 统一的 factor-exit / event-exit / risk-exit policy。`core/risk/{kill_switch, failure_detector, sr_stops, stress_tester}` 4 模块已存（KillSwitch 3-tier with auto-recovery），但**不被 decision layer 调用**，仅做 ex-post 监控。详 §5.2。

4. **Evidence Layer 抽象完全空白**（不是"分散存在"） —— `grep EvidenceProvider | class Evidence layer = EMPTY`。本 PRD §3.1 第 1 层是**完全新建**的抽象。

5. **production/live 闭环未成型** —— `config/production_strategy.yaml status="conservative_default"`（grep-verified）；dividend 处理 infrastructure 已在但 SPY/QQQ 不在 distributions.parquet sidecar（详 §13 gate2）；`core/execution/broker_adapter.py` 有 `BrokerAdapter ABC` + `SimulatedBrokerAdapter` 但无 real broker 子类。

### 2.3 这轮审计抓到、且已在 2026-05-19 修正的历史问题（必须留痕）

- `core/research/b1_intraday_features.py::intraday_volume_z()` 先前实现对"日内 volume 的日内 z-score"求均值，理论上恒等于 0，属于死特征；现已修为 volume-distribution skew，并有回归测试。
- `dev/scripts/track_a/a1_b1_nav_track_a.py` 先前读取 concentration 指标 key 错（`top1_max`），用缺失 key 默认 `0.0` 形成 false-PASS；现已改读真实 `m12_top1_weight_max` / `m12_top3_weight_max`。
- 同一 Track-A 脚本先前即使 `--only a1` 也执行 B-side gate，造成假耦合；现已把 gate 挪回 B1 分支。

这些问题**不再是当前 blocker**，但它们改变了 intraday-ML 若干旧结论的可信度，**本 PRD 制度设计必须以 REVISION memo 的 post-fix verdict 为准**：`docs/memos/20260519-strategic_close_out_REVISION_post_audit_fix.md`。

### 2.4 修正后新增的更强战略结论（post-fix data-driven）

REVISION memo 给出的 post-fix 结论对本 PRD 有直接约束：

- intraday ML 预测的**方向(sign)** 在 3 类模型（DLinear / Shallow XGB / Deep SSL）上都保留正信息（info IC +0.076 ~ +0.091 普世正）。
- intraday ML 预测的**连续幅度(magnitude)** 在 3 类模型上都表现为噪声或负贡献（timing contribution 全负）。

因此，本 PRD 后续若做 ensemble / trigger policy，**有本项目实测支持**地默认应优先：

- `sign-vote`
- `rank-vote`
- `include / veto`

而**不是**连续加权平均预测值。这和本 PRD 的 trigger-first 架构是同向的：ML 更适合给出 `trade / no-trade / include / veto / urgency`，而不是直接无约束输出全仓位强度。

---

## §3 新架构：从 Cadence-First 到 Trigger-First

### 3.1 五层抽象（新的单 SoT；建设状态显式标注）

| 层 | 职责 | 例子 | 现状（v2 精化） |
|---|---|---|---|
| **Evidence Layer** | 提供 alpha / factor / event / regime / risk 证据 | value signal, momentum decay, earnings event, VIX spike | **完全新建抽象**（无现成 `EvidenceProvider` 类） |
| **Decision Layer** | 决定 enter / hold / trim / exit / no-trade | "信号增强但未过阈值 → hold" | **完全新建**（7 Strategy 类需经 Adapter 适配，详 §F.2） |
| **Execution Layer** | 决定 now / defer / split / partial / veto | 15m conflict → defer；流动性差 → partial | **partial 复用 deferred_execution + cascade_overlay**；split/veto 新建 |
| **Construction Layer** | 把决策转成目标权重变化 | top-N, cap-aware, cross-asset overlay | **复用 PRD-2 cascade_overlay R12 + tier_overlay**；delta-to-trade policy 新建 |
| **Review Layer** | 固定 cadence 的审查 / 兜底，不是主驱动 | weekly sanity review / monthly full refresh | **完全新建 L0/L1/L2 三层 review hierarchy**（`grep review_cadence = 空`） |

### 3.2 关键定义

- **Review cadence**: 多久强制全量审查一次，不等于必须调仓一次。
- **Decision trigger**: 满足某些证据 / 阈值 / 事件后才允许调仓。
- **Exit trigger**: 导致减仓/平仓的证据，不要求等到下一个固定 cadence。
- **No-trade band**: 有轻微信号变化但未越过成本敏感阈值时，不交易。**Vol/regime-conditional**（详 §5.3.1，Leland 1999）。
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

### 4.1.1 与现有 `SignalStatus` 3-state enum 的 mapping（v2 新增）

现有 `core/signals/signal_state.py::SignalStatus` 只有 `ARMED / CONFIRMED / EXPIRED` 3 个 state。本 PRD 的 9 个 lifecycle states 须通过 **复合 (SignalStatus, ActionType, PositionState) 三元组** 表达，**不扩展 SignalStatus enum**（避免破坏既有 intraday_reversal_runner / confirmation_pattern 调用方）：

| PRD lifecycle state | (SignalStatus, ActionType, PositionState) |
|---|---|
| FLAT | (—, —, FLAT) |
| ARMED_ENTRY | (ARMED, ENTER_FULL\|PARTIAL\|ADD, FLAT\|HOLD) |
| CONFIRMED_ENTRY | (CONFIRMED, ENTER_*, FLAT\|HOLD) |
| ENTERED | (—, —, HOLD) |
| HOLD | (—, HOLD, HOLD) |
| ARMED_EXIT | (ARMED, EXIT, HOLD) |
| ARMED_TRIM | (ARMED, TRIM, HOLD) |
| CONFIRMED_EXIT | (CONFIRMED, EXIT, HOLD) |
| CONFIRMED_TRIM | (CONFIRMED, TRIM, HOLD) |
| EXITED | (—, —, FLAT) |

新增 `PositionState` enum（`FLAT / HOLD`）+ `ActionType` enum（9 actions 见 §4.3）是**新建 enum，与 SignalStatus 正交**。

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

### 4.3 决策动作集合（**新建 enum，与 SignalStatus 正交**）

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

`grep ENTER_FULL | ARMED_TRIM | ActionType = EMPTY` —— 这 9 个 action 是新增 enum，本 PRD 自带 SoT。

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
- event-window factor 显著转正（注：archetype `event_window` 已在 `core/research/component_b_gate.py:55` differentiated list，但 detector 未建，本 PRD 须新建）
- catalyst 兑现前，允许进入 armed but unfilled 状态

#### C. Regime trigger（v2 精化 API contract）

复用 `core/regime/regime_detector.py::RegimeDetector`（已存，6 states：`BULL / RISK_ON / NEUTRAL / CAUTIOUS / RISK_OFF` + 派生）：

```python
# API contract（新增，本 PRD 定义）
class RegimeTrigger(Protocol):
    def evaluate(self, ctx) -> Optional[RegimeTriggerEvent]:
        """如 RegimeDetector 当前 state ∈ favorable_zone，返回 Event；
        favorable_zone 由 per-factor regime affinity table 决定，
        本 PRD 须落地 affinity table（数据驱动 from cycle04-10
        regime-conditional metrics）。"""
```

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

#### C. Risk exit（v2 精化复用既有 risk module）

**v2 新增显式复用**:

| Risk source | 复用模块 |
|---|---|
| volatility / drawdown breach | `core/risk/kill_switch.py::KillSwitch`（3-tier with auto-recovery） |
| signal decay / fault | `core/risk/failure_detector.py::FailureDetector` + `FailureSignal` |
| stop-loss / support-resistance breach | `core/risk/sr_stops.py` |
| stress regime entry | `core/risk/stress_tester.py` |

PRD-X 新增 `RiskExitTrigger` Protocol 订阅以上 4 模块的事件 → 转 `ARMED_EXIT`：

```python
class RiskExitTrigger(Protocol):
    def subscribe_kill_switch(self, ks: KillSwitch) -> ...
    def subscribe_failure(self, fd: FailureDetector) -> ...
    def subscribe_sr_stops(self, ss) -> ...
    def evaluate(self, ctx) -> Optional[RiskExitEvent]
```

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

### 5.3.1 Vol/regime-conditional band 宽度（**v2 新增 Leland mechanic**）

[Leland 1999](https://www.researchgate.net/publication/237927444_Optimal_Portfolio_Rebalancing_with_Transaction_Costs) 关键论点：**"no-trade region should be LARGE when volatility is HIGH"**。固定 band 宽度是 v1 缺失的关键 mechanic。

v2 band 宽度公式（schema-level，参数 calibrate 落到 §11 X2）：

```python
band_width(symbol, t) = base_band
                       * vol_multiplier(realized_vol(symbol, lookback))
                       * regime_multiplier(RegimeDetector.state(t))
```

- `vol_multiplier`: vol 上升 → multiplier ↑ → band 宽 → 更难触发交易（减少 churn）
- `regime_multiplier`: RISK_OFF / CAUTIOUS regime → multiplier ↑（同向，risk-off 期间避免不必要 turnover）

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
  - **现仅 intraday_reversal_runner + confirmation_pattern 消费；本 PRD §11 X4 须扩展到主 backtest 路径，M11 parity 测试矩阵覆盖 7 strategy（详 §11 X4 v2 AC）**
- `core/signals/signal_state.py`
  - 作为 armed / confirmed / TTL / expire 的状态机基座
- `core/research/cascade_overlay.py`（PRD-2 R12）
  - 作为 multi-TF timing/sizing/veto overlay 出口（mode="off" 默认 bit-identical）
- `core/research/construction_tiers.py`（PRD-2 R2-b）
  - 作为 T0/T1 hedge overlay 出口（T2 永久 gated 不实现 execution）

### 6.3 新 execution policy 允许的 4 类行为

1. **Immediate full**
2. **Deferred**
3. **Partial**
4. **Staggered / split**

### 6.4 不变量守护（**v2 新增节，覆盖 audit issue #14**）

本 PRD 的所有 decision/execution/construction policy **硬绑** CLAUDE.md `Invariant Constraints`，不随任何 flag / mode 放松：

| Invariant | 守护方式 |
|---|---|
| `long-only` / `no-short` | ActionType 集合无 SHORT_*；任何 weight 输出 ≥ 0 elementwise 由 cascade_overlay / tier_overlay 已有 guard 保留 |
| `no-margin` | 总权重 ≤ 1.0 校验在 construction layer，遵守 PRD-2 T0/T1 |
| `SQQQ blacklist` + 杠杆-inverse 永禁 | 经 `core/research/component_b_gate.py::_LEVERAGED_INVERSE` set + cascade_overlay 既有 guard |
| `MaxDD 15-20% / 2008-≤25%` | 复用 `core/risk/kill_switch.py` 3-tier + `stress_tester.py` |
| `Intraday: 60m/30m primary, 15m 决策输入非 alpha-mining` | RB1 gate (`assert_archetype_differentiated`) + multi_timescale R10 leakage rules + 15m boundary memo（2026-05-19 ratified） |
| `sealed 2026 永不读` | §11 各 phase AC + §12 验证矩阵硬绑 |
| `真 short P2.4 execution` | §14 非目标 + 现有 R14 T2 stub gated guard |

### 6.5 明确禁止

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
- T1 hedge / overlay（`core/research/construction_tiers.py::apply_tier_overlay`，mode="off" 默认 bit-identical）
- cascade timing overlay（`core/research/cascade_overlay.py::apply_cascade_overlay`，mode="off" 默认 bit-identical）
- future fleet allocator（详 §10.3.1）

### 7.2 部分调仓是一等公民

构建层必须支持：

- target weight delta < full delta
- hold existing but block new adds
- trim without full exit
- exit one symbol while freezing others

当前项目已有 `rebalance_threshold`（仅 TAA harness），但还不够，需要升级为显式的 **delta-to-trade policy**（详 §11 X3）。

---

## §8 Review Cadence 的新定位（v2 精化：完全新建抽象）

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

### 8.2 推荐层次（v2 显式标注：完全新建，`grep review_cadence = 空`）

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

**实现层**：本 PRD §11 X4 须新建 `ReviewScheduler` 类（无既有模块复用，是新抽象）。

---

## §9 ML 在调仓中的角色（允许，但严格限边界）

### 9.0 Post-audit-fix 数据基础（**v2 新增**）

`docs/memos/20260519-strategic_close_out_REVISION_post_audit_fix.md` post-fix A/B FORCED 跨 DLinear / Shallow XGB / Deep SSL 3 类模型一致显示：

- **sign IC +0.076 ~ +0.091 普世正**
- **continuous magnitude IC 普世负**（timing contribution 全负 -0.046 ~ -0.170）

因此本 PRD §9.1-9.3 的 ML 应用方向（sign-vote / include-veto / trade-no-trade）**有本项目实测支持**，非纯理念。

### 9.1 可以做什么

ML 可以用于：

- `trade / no-trade` classifier
- `include / veto` sign decision
- `partial size` regression（但谨慎，post-fix 表明 continuous magnitude 易过拟合）
- `expected hold horizon` estimation
- `exit probability` / `decay probability`
- execution urgency / slippage-aware scheduling

### 9.2 不建议一上来做什么

- 直接端到端输出全组合调仓矩阵
- 跳过可解释 trigger，完全交给 black-box policy
- 在样本不大、成本模型未定、live闭环未成型时上 RL 直接控全流程
- **使用 ML 预测的 continuous magnitude 直接作 size weight**（post-audit-fix 实测全空）

### 9.3 顺序建议

先做：

1. rule-based trigger
2. no-trade band（含 §5.3.1 vol/regime-conditional）
3. partial rebalance
4. ML sign-vote / trade-no-trade
5. ML exit / hold horizon
6. 更复杂的 dynamic control

---

## §10 与现有 PRD 的关系

### 10.1 与 PRD-2

PRD-2 负责 construction-DOF（T0/T1/T2 + cascade timing + cross-asset cap）。  
本 PRD 负责 **上游决策层**，回答"何时有资格触发这些 DOF"。**所有 construction-layer 出口仍走 PRD-2 的 cascade_overlay + tier_overlay**，本 PRD 不重造 construction 机制。

### 10.2 与 PRD-3

PRD-3 负责 signal-layer ML arms（RA1-RA8 + RB1-RB5）。  
本 PRD 负责 **这些 signal 如何转化为 enter/hold/trim/exit**，避免 signal ≈ rebalance 命令。**严格按 §9.0 post-audit-fix 数据基础约束**：ML 输出走 sign-vote / include-veto，**不**走 continuous magnitude as size weight。

### 10.3 与 forward / paper / fleet

本 PRD 是 future paper/live/fleet 的公共决策内核。  
如果没有它，后续 fleet allocator 只会接收到"固定 cadence 产出的静态目标权重"，表达力不够。

### 10.3.1 与 fleet allocator 的接口契约（**v2 新增**）

`core/fleet/{allocator.py, manifest_schema.py}` 已存。本 PRD 输出给 fleet 的契约：

```python
# 本 PRD DecisionPolicy → fleet allocator 数据契约
@dataclass
class CandidateDecisionPanel:
    """Per-candidate, per-date decision state."""
    candidate_id: str
    date: pd.Timestamp
    position_state: PositionState        # FLAT / HOLD
    pending_actions: List[ActionDecision]  # [ENTER_PARTIAL, HOLD, ARMED_EXIT, ...]
    desired_weight: float                 # post-decision target weight (≥0)
    confidence: float                     # for fleet-level weighting
    review_layer: Literal["L0", "L1", "L2"]
```

Fleet allocator 消费 `List[CandidateDecisionPanel]`（多候选合成），调用既有 `core/fleet/allocator.py` 完成 fleet-level weighting + cap-aware aggregation。**本 PRD 不修改 allocator 内部逻辑**（§14 非目标），只规范输入契约。

---

## §11 实施分期（v2 重排：dividend 先、已建整合次之、真新建后置）

### Phase X0 — Dividend extension + atr flag flip（**v2 新增**，覆盖 audit issue #6）

#### 目标

`bar_store.adjusted_total_return` infra + `data/ref/distributions.parquet` 876-row sidecar 已存（9 个 callers 在用，包括 cycle06/cycle12/chart_native_l3/TAA/forward）。**唯一 gap**：SPY/QQQ 不在 distributions.parquet，cycle06 `atr = sym in cross_asset_set` → SPY/QQQ 走 split-only 非 TR。

#### 交付

- 跑 `dev/scripts/data_integrity/build_distributions_parquet.py` 扩展覆盖 SPY/QQQ + 主 equity universe（builder 已在）
- 各 driver 把 `atr` flag 改为 `True` for SPY/QQQ + tradeable equities（保留 macro_reference 非 TR）
- 重跑 cycle06 baseline + Track-A 与 v1 数字对照，**诚实记录 vs-SPY 变化方向**（预期 strategy NAV 和 SPY 都升 ~1.5-2%/yr dividend yield，相对 gap 可能更负因为 momentum-leaning strategy 通常股息率低于 SPY）

#### AC

- distributions.parquet 含 SPY/QQQ 行（builder 数据 R3 实测）
- cycle06 baseline 数字诚实更新到 ledger
- **sealed 2026 永不读** + bar-integrity smoke（weekend rows / monotone / sealed-year guard）

---

### Phase X1 — 统一决策 schema（v2 精化：Protocol-based 不破 strategy）

#### 目标

建立统一的 `DecisionPolicy` Protocol + `ExecutionPolicy` Protocol + `ActionDecision` schema。**关键 design choice**：**Protocol-based（Python 3.8+ Protocol，零继承）+ `GenerateStrategyAdapter`**（详 §F.2）—— 6/7 strategy 通过 1 个共享 Adapter 接入（强 strategy 本身），1/7（intraday_reversal）已是状态机 blueprint 零修改。

#### 交付

- `core/research/decision/__init__.py`
  - `DecisionPolicy` Protocol (`detect_setups` / `confirm_signals` / `build_target_weights` / `step_day`)
  - `ExecutionPolicy` Protocol (`schedule_fill` / `should_defer` / `partial_size`)
  - `ActionDecision` dataclass（含 9 个 ActionType + (SignalStatus, ActionType, PositionState) 三元组）
- `core/research/decision/adapter.py::GenerateStrategyAdapter`
- 7 个 strategy thin registration（不改 strategy 本身）

#### AC

- 新 schema 单测全绿
- 既有 backtest / paper 默认路径 `bit-identical`（**默认 mode="off" 不启用 decision layer，所有 7 strategy 的 generate/step_day 既有出口完全不变**——同 cascade_overlay R12 / construction_tier T0 bit-identical-default pattern）
- **sealed 2026 永不读**（schema-only 不接 panel 数据，本 phase 不触发但纪律预设）

---

### Phase X2 — Rule-based trigger + exit policy（含 vol-conditional no-trade band）

#### 目标

把 factor / event / regime / risk 证据统一接成 rule-based 决策层。

#### 交付

- factor entry / exit threshold detector（**exit policy 是真新建，复用 `core/diagnostics/detectors.py::BaseDetector` pattern**）
- event trigger / invalidate trigger（event_window detector 也是新建，archetype 占位已在）
- regime trigger via `RegimeDetector` subscription (§5.1.C API contract)
- `RiskExitTrigger` 订阅 `KillSwitch / FailureDetector / sr_stops / StressTester` (§5.2.C)
- higher-TF veto / defer 接口统一（复用 `multi_timescale.decide_timing`）
- **vol/regime-conditional no-trade band**（§5.3.1，新建公式 + calibration）

#### AC

- 能表达"review 了但不交易"
- 能表达 partial / defer / veto
- 不能因为 cadence 到点而强制生成订单
- band 宽度在 high vol regime ≥ low vol regime（R3 实测两个 regime samples）
- **sealed 2026 永不读 + strict-chronological walk-forward 在所有 backtest 路径硬绑**（覆盖 audit issue #13）

---

### Phase X3 — Partial rebalance / delta-to-trade policy（**v2：真新建**）

#### 目标

把"想要的目标变化"映射成"实际交易变化"。**主 backtest 路径无 rebalance_threshold（仅 TAA harness 有）—— 这是真新建**。

#### 交付

- full / partial / staged rebalance policy
- delta buffer / tolerance region
- **turnover budget hook（MSCI 30% one-way precedent；按 §5.3.1 vol-conditional 紧度）**

#### AC

- 同一 target change 在不同 cost/liquidity 下可产出不同 trade size
- 在成本放大 2x/3x 下，仍可执行 no-trade / partial fallback（复用 PRD-2 R11 sensitivity_multiplier）
- rolling 12-mo turnover budget 不超 per-asset-class cap
- **sealed 2026 永不读 + strict-chronological walk-forward**

---

### Phase X4 — Deferred execution / confirmation integration（**v2：integrate existing**）

#### 目标

把 armed / confirmed / fill 调成主路径（**deferred_execution kernel 已存，仅 intraday_reversal_runner + confirmation_pattern 消费；本 phase 是 integrate existing 到主 backtest，不是新建**）。

#### 交付

- `signal_state` + `deferred_execution` 与 backtest/paper 主路径统一接线（via signal_driven_runner pattern → BacktestEngine.run unchanged）
- entry/exit 的 TTL / expire / cancel 规则
- **M11 parity 测试矩阵覆盖全 7 Strategy 类**（v2 精化 AC）

#### AC

- paper/backtest 行为一致
- signal_date / fill_date / eod mark 语义明确
- **M11 parity 不退化**，具体 test fixtures：
  - `test_m11_parity_multi_factor.py`
  - `test_m11_parity_dual_momentum.py`
  - `test_m11_parity_trend_following.py`
  - `test_m11_parity_simple_baseline.py`
  - `test_m11_parity_intraday_reversal.py`（既有）
  - `test_m11_parity_cross_asset_rotation.py`
  - `test_m11_parity_confirmation_pattern.py`
  每个 fixture 比较 (decision-layer mode=off) vs (legacy strategy.generate path) 在 sample windows 上 bit-identical
- **sealed 2026 永不读**

---

### Phase X5 — ML-assisted decision policy（后置，post-audit-fix 约束）

#### 目标

在 rule-based 架构跑通后，用 ML 学 trade/no-trade、trim、exit probability。

#### 交付

- ML classifier/regressor 不直接控全组合，只做 policy sidecar
- **ML 输出严格 sign-vote / include-veto / classifier，禁用 continuous magnitude as size weight**（§9.0 post-audit-fix data-driven 约束）

#### AC

- 必须优于 rule-based baseline（**包括 cycle06 deterministic factor-composite baseline**，详 §12.0）
- 成本放大与 deconfound 都要过
- 不允许黑箱跳过 risk/exit hard guard
- **sealed 2026 永不读 + DSR honest-N + PBO（per PRD-1/2/3 既有纪律）**

---

## §12 验证与研究纪律

### 12.0 cycle06 deterministic baseline regression（**v2 新增**，覆盖 audit issue #17）

`cycle06_track_a_eval.py` 是项目**唯一 Track-A PASS** 的 deterministic factor-composite baseline（cum/Sharpe/MaxDD/vs-SPY 全过）。本 PRD 的所有 decision-driven 路径**至少不劣于 cycle06**：

- 同一 train+val partition、同一 cap_aware_cross_asset construction、同一 cost model
- decision-driven Sharpe ≥ cycle06 Sharpe - tolerance（tolerance 待 §11 X1 定）
- decision-driven MaxDD ≤ cycle06 MaxDD + tolerance
- decision-driven turnover ≤ cycle06 turnover × 2（trigger-first 不应大幅放大 turnover）

不满足 → FAIL_recorded_root_cause（同 PRD-1/2/3 funnel 纪律），非 blanket "trigger-first 无用"。

### 12.1 研究问题不能再写成"哪个 cadence 更好"

新的 research question 应改成：

- 哪类 trigger 带来正净值增量？
- no-trade band 是否降低 churn 且不伤 edge？
- partial rebalance 是否改善 cost-adjusted NAV？
- exit factor 是否优于 fixed holding period？
- ML policy sidecar 是否优于 rule baseline？

### 12.2 最少实验矩阵

必须比较：

- **cycle06 baseline**（v2 新增,§12.0）
- fixed cadence baseline
- trigger-only
- trigger + no-trade band（含 §5.3.1 vol-conditional）
- trigger + no-trade band + partial
- trigger + no-trade band + partial + deferred/confirmation

### 12.3 绑定指标

- net vs SPY（**TR-adjusted post-X0**）
- cost sensitivity（R11 sensitivity_multiplier 1x/2x/3x）
- turnover level + turnover concentration
- drawdown / crisis behavior
- decision frequency
- average hold time distribution
- canceled/deferred trade ratio
- **leakage-correct frozen-OOS IC**（PRD-1 canonical）
- **DSR(honest-N) + PBO**（PRD-1/2/3 既有纪律）

### 12.4 全 phase 纪律（v2 新增，覆盖 audit issue #13/#14）

所有 §11 各 phase 的 backtest / experiment 必须：

- `sealed 2026 永不读`（cycle06 selector partition 强制）
- `strict-chronological walk-forward`（Track-A R1 temporal-leakage 教训）
- `bar-integrity smoke`（weekend rows / monotone / sealed-year guard）before any heavy ML/backtest
- `M11 parity`（per Phase X4 test matrix）
- `invariant guards`（§6.4 long-only / no-margin / SQQQ / MaxDD / 2008-≤25%）

---

## §13 Live / Production 边界

本 PRD 明确：**当前还不是 production-ready，只是为 production-ready 铺决策内核。**

在以下条件未满足前，不进入真钱 live：

1. `production_strategy.yaml` 不再是 `conservative_default`（grep-verified status field）
2. **dividend 口径**：Phase X0 已扩 SPY/QQQ + tradeable equities into distributions.parquet（infra+876-row 已建，本 PRD scope 内补全；非 Phase 边界外工作）
3. paper vs replay vs backtest drift 成为 hard gate（M11 parity test matrix per §11 X4 AC）
4. broker/live-feed seam 升级为真实 shadow workflow（`core/execution/broker_adapter.py` 现有 `BrokerAdapter ABC` + `SimulatedBrokerAdapter`，缺 real-broker 子类）
5. trigger/exit policy 经过至少一轮真实 paper soak

---

## §14 非目标

- 不在本 PRD 内实现真 short execution（PRD-2 P2.4 R14 stub 现有 guard，永久 TODO）
- 不在本 PRD 内直接改 fleet allocator 内部逻辑（**仅规范输入契约，见 §10.3.1**）
- 不在本 PRD 内直接上 RL 全自动调仓
- 不因"追求 trigger-first"废除 monthly full refresh（§8 L2）
- 不放松任何 §6.4 不变量
- 不在 phase X1-X5 任何 backtest 路径读 sealed 2026

---

## §15 R1-R4 自审

- **R1 事实**: 方向是否只是理念输出？  
  否。本文显式绑定现有模块：`multi_timescale` / `signal_state` / `deferred_execution` / `rebalance_threshold` / `cascade_overlay` / `construction_tiers` / `regime_detector` / `kill_switch` / `failure_detector` / `sr_stops` / `stress_tester` / `signal_driven_runner` / `bar_store.adjusted_total_return` / `distributions.parquet` / paper/backtest parity。全部 R3 grep-verified 2026-05-19。

- **R2 逻辑**: 是否偷换成"换个 cadence"老路子？  
  否。本文明确把 cadence 降级为 review/fallback，不再当 primary decision variable。

- **R3 真跑对比期望**: 是否脱离外部标准？  
  否。AQR / MSCI / BlackRock / Lynch-Balduzzi / Leland 一手源 4/4 verified 2026-05-19。Leland "vol 高 no-trade region 应大" 关键 mechanic（v1 缺）现已并入 §5.3.1。

- **R4 边界 / cross-module**: 是否对当前项目状态过度乐观？  
  否。已显式写入 recent bug、active strategy 缺失、dividend gap（infra 已建仅缺数据+flag）、broker/live-feed gap，并把它们列为 live gate 前置。3 个 conflict 全由 R3 grep 找到现有 pattern → 不是冲突，是延伸。不变量守护（§6.4）+ sealed-year + strict-chronological + M11 parity matrix 全在 phase AC。

---

## §16 一句话版本

> 这个项目下一步不该继续问"日调/周调/月调哪个好"，而该问：  
> **什么证据值得动仓、何时确认、何时退出、动多少、什么时候宁可不动。**  
> cadence 只是 review 节奏，不应再是调仓的主语。

---

## §F Reusable Inventory + Conflict Resolutions（**v2 新增**）

### F.1 可直接复用（R3 grep-verified 2026-05-19）

| 模块 | 用途 | 接入点 |
|---|---|---|
| `core/intraday/multi_timescale.py::decide_timing` + `TimingDecision` | execution layer timing/sizing/veto kernel | §6.2 |
| `core/signals/signal_state.py::SignalStateMachine` + `SignalStatus`(3-state) | §4.1.1 三元组左分量 | §11 X1/X4 |
| `core/backtest/deferred_execution.py::DeferredExecutionSchedule` | CONFIRMED → fill canonical kernel | §11 X4 integrate existing |
| `core/research/cascade_overlay.py::apply_cascade_overlay`(R12,mode="off") | multi-TF veto/sizing overlay 出口 | §7.1 |
| `core/research/construction_tiers.py::apply_tier_overlay`(R2-b,T0/T1) | hedge overlay 出口（T2 gated） | §7.1 |
| `core/research/cascade_overlay::apply_*` mode="off" pattern | bit-identical-default 设计模板 | §11 X1 AC |
| `core/diagnostics/detectors.py::BaseDetector`(triggered/value/threshold) | exit-trigger detector 基类 | §11 X2 |
| `core/risk/{kill_switch, failure_detector, sr_stops, stress_tester}.py` | RiskExitTrigger 订阅源 | §5.2.C |
| `core/regime/regime_detector.py::RegimeDetector`(6 states) | regime trigger API contract | §5.1.C |
| `core/factors/signal_confirmation_factors.py` | confirmation factor lib | §11 X2 |
| `core/research/pead/sue_calculator.py` + `price_jump_signal.py` | event trigger 案例（SUE / AR threshold） | §11 X2 |
| `core/backtest/signal_driven_runner.py` | weight-panel → BacktestEngine.run wrapper pattern（M11 parity 保留 by design） | §F.C1 solution |
| `core/data/bar_store.py::load(adjusted_total_return=True)` + `data/ref/distributions.parquet` (876 rows) | dividend cascade infra | §11 X0 |
| `dev/scripts/data_integrity/build_distributions_parquet.py` | sidecar builder | §11 X0 |
| `core/fleet/{allocator, manifest_schema}.py` | 下游消费方 | §10.3.1 |

### F.2 需要新建

- `core/research/decision/` 新模块（`DecisionPolicy` / `ExecutionPolicy` / `ActionDecision` / `ActionType` / `PositionState` / `GenerateStrategyAdapter`）
- exit-trigger detectors（thesis-decay / factor-exit / event-invalidation；复用 `BaseDetector` pattern）
- `RiskExitTrigger` Protocol（订阅 4 现有 risk module）
- event_window detector（archetype 占位已在 RB1 differentiated list）
- regime affinity table（per-factor regime favored zone）
- `NoTradeBandCalculator`（vol/regime-conditional，§5.3.1）
- `DeltaToTradePolicy`（partial rebalance kernel，§11 X3）
- `ReviewScheduler`（L0/L1/L2，§8.2）
- `ReviewLayer` 三层 review state（L0 daily / L1 weekly / L2 monthly）
- `decision_driven_runner.py`（扩展 `signal_driven_runner` pattern）
- M11 parity 测试 fixture × 7 strategies（§11 X4）
- production_strategy.yaml 扩展或 sibling 配置（trigger policy params）

### F.3 三个 Conflict 的 Solution（R3 grep 找到现有 pattern）

| Conflict（v1 描述） | R3 grep 实证 | Solution |
|---|---|---|
| C1: backtest_engine 主路径 monthly-cadence-driven | `signal_driven_runner.py` 已存，明文 "we do NOT modify BacktestEngine.run — preserves M11a/M11b parity bit-for-bit" via "(date×symbol) weight panel" 接口 | **新建 `decision_driven_runner.py` 扩展同 pattern**；backtest_engine.run() 不动；M11 parity 自动保留 |
| C2: 7 Strategy 类无统一接口 | 6/7 已共享 `def generate(...)` 签名；1/7 (`intraday_reversal`) 有 4 方法状态机（detect_setups/confirm_signals/build_target_weights/step_day）**正是 §4 blueprint** | **Protocol + 1 个 `GenerateStrategyAdapter`**：6/7 经 adapter，1/7 已是 blueprint 直接实现；strategy 本身零修改 |
| C3: dividend gap | `bar_store.adjusted_total_return=False` 参数已在，distributions.parquet sidecar 876 rows 已建，9 callers 已用 `atr=True`；SPY/QQQ 不在 sidecar、cycle06 atr 仅 cross_asset | **§11 X0**：跑既有 builder 扩 SPY/QQQ + equity universe；driver flip atr=True；几小时数据工作，非 multi-week infra |

净结论:三个 conflict **全都不需要新 infrastructure**。架构延伸,非重造。
