# 架构决策记录

## ADR-001：渐进加固而非重写

- 问题：现有系统 61K+ core LOC、4,103 tests，并有大量研究 evidence。
- 选择：保留数据、策略、回测和研究治理；新增执行安全 kernel 和兼容 adapter。
- 原因：降低不可验证迁移风险，保持旧研究结果可追溯。
- 代价：过渡期需要旧/新接口兼容层。

## ADR-002：真实 Broker 必须经过 durable OrderManager

- 选项：继续让 PaperTradingEngine 先模拟再 mirror；或让 Broker 成为提交/成交真源。
- 选择：所有 PAPER/LIVE 提交都经同一 OrderManager；PaperBroker 也实现 Broker 契约。
- 原因：只有这样才能统一幂等、UNKNOWN、partial fill、重启和 reconciliation。
- 代价：需要把现有 simulator 包装为 fill policy，而非直接修改 cash/positions。

## ADR-003：LIVE 双重显式授权且无安全默认值

- 选择：默认 mode=PAPER；LIVE 同时需要配置 `live_enabled=true` 和短期人工 approval，
  启动时打印并审计风险配置。缺任一条件即拒绝构造真实 adapter。
- 原因：防环境变量、CLI 拼写或错误配置导致真实下单。

## ADR-004：UNKNOWN 和 reconciliation mismatch 隔离新增风险

- 选择：订单状态未知或本地/Broker 不一致时，禁止新开仓；允许风险降低型撤单/平仓
  必须经过专用 policy 和审计。
- 原因：盲目重试是重复订单的主要事故路径。

## ADR-005：Regime 是风险分配输入，不是无约束 alpha oracle

- 选择：regime 输出状态、概率/置信度和质量；低置信/缺数据进入 UNKNOWN 并降风险。
- 原因：避免单指标择时和状态过度拟合。

## ADR-006：合成期权证据与可执行期权证据分级

- 选择：synthetic BS 结果明确标记 `SYNTHETIC_RESEARCH`，不得用于可成交性或 live
  promotion；只有带 PIT chain、bid/ask、质量、成本和 lifecycle 的结果才是
  `EXECUTABLE_PAPER_EVIDENCE`。
- 原因：防把理论 spread mid price 当可实现收益。

## ADR-007：静态检查分阶段收敛

- 选择：先修 F/E 和关键路径类型错误；建立“新增代码零问题”门，再逐步清历史 I/N。
- 原因：一次自动修 600+ 文件会产生高风险、低信号 diff。

## ADR-008：Regime 只保留质量 fail-close，不叠加无增量择时

- 证据：validation 中额外 risk-on-only gate 将 CAGR 11.39% 降至 2.10%、Sharpe 0.732
  降至 -0.353，且换手升至 7.39x。
- 选择：`dual_index_growth_v1` 的经济开关使用自身 dual-index long-trend state；外部
  regime 只在 UNKNOWN、低 confidence、缺失或陈旧时拒绝新增风险。
- 代价：不能把 regime 状态当成额外 alpha；未来修改必须重新预注册和验证。

## ADR-009：不足两个策略时关闭当前搜索，而不是复用已读 holdout

- 证据：adaptive core、sector rotation v2 已最终拒绝；controlled growth、reversion、
  risk balance、defensive growth、multi-asset trend、crash-buffer core 均在开发/验证停止；
  只有 dual-index growth 完成研究和 PAPER 门禁。
- 选择：保留一个 `PAPER_APPROVED`，不制造第二个。当前搜索在 2026-07-17 数据截止处关闭。
- 解锁：等待至少 252 个新的、未见的未来 sessions，或由用户明确批准采用不重叠的
  point-in-time 数据与新协议；不得仅降低 gate 或重看 2024–2026 holdout。

## ADR-010：历史晋升事实与当前有效权限分离

- 证据：`dual_index_growth_v1` 确实按 Phase 2 冻结规则通过 28/28 gate；但该规则的
  `growth_engine` 分支没有项目级 SPY 收益超额硬门，最终 holdout CAGR 15.31%，同期
  SPY 24.79%。
- 选择：历史 `PAPER_APPROVED` 记录和 `v1.json` 不改写；治理 overlay 将当前身份解析为
  `PAPER_OBSERVATION_ONLY / REVIEW_HOLD`，禁止自动晋升和资本资格，允许冻结模拟观察。
- 原因：同时保护审计真实性和当前授权正确性，避免“改历史”或“错误继承权限”。

## ADR-011：SPY 硬门失败进入 REVIEW_HOLD，不自动淘汰

- 选择：自动晋升必须在同口径、计入策略成本后跑赢 SPY；QQQ 只做诊断。
- 选择：未跑赢不自动 DROP。低回撤等显著风险优势可进入人工 near-miss 评审，但须补充
  风险匹配被动组合、DSR/PBO/CPCV 与 forward 证据。
- 约束：人工例外需要用户显式批准，并永久标记为 exception，不得改写成原 gate PASS。

## ADR-012：已读区间不能通过改名重新密封

- 证据：2024-01-02 至 2026-07-17 已被 d2r2/d2r3/d2r5 三个 finalist 依次访问。
- 选择：该区间标记为 `OBSERVED_NOT_PRISTINE`；旧 split 标记为
  `CONSUMED_NOT_PRISTINE`。新名称、版本号或 hash 不恢复信息新颖性。
- 运行约束：正式 forward 前必须验证 trusted source batch 与时间因果性；Yahoo 收盘后
  日线不能冒充可在同一已过去开盘成交的实时证据。
