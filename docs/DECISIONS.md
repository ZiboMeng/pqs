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
