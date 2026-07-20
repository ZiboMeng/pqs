# PQS Phase 3 开工前审计

日期：2026-07-20（America/Los_Angeles）  
分支：`codex/forward-paper-and-sealed-evidence-v3`  
回退标签：`codex-pre-forward-paper-phase3-20260720`  
基线提交：`3b9baf8d34b890ca3520f37b28ef55ab9d63cfdc`

## 1. 结论

Phase 2 的研究结论和唯一 `PAPER_APPROVED` 策略仍然成立，但现有运行器是有因果约束的
历史 PAPER replay，不是真正按收盘决策、次日开盘执行的长期 Forward PAPER 服务。开工审计以
可执行反例发现并关闭了晋升边界、VIX 新鲜度、健康检查、broker 权威对账、部分成交生命周期、
幂等键、卖空造现金和非有限数值等问题。

审计后允许进入 Phase 3 基础设施开发；不允许据此宣称已部署云端、已接入真实券商、已获得第二
策略或已具备 LIVE 条件。

## 2. 审计范围与方法

审计不以“文件存在”为通过标准，覆盖以下层次：

1. 配置、registry、promotion evidence 和代码提交之间的治理边界；
2. 调整后总回报数据、事件时间、可用时间、新鲜度和乱序处理；
3. T 日信号、T+1 成交、成本、持仓、现金、NAV 和回测/PAPER 一致性；
4. pre-trade veto、long-only、no-margin、symbol cap、pause 和 kill switch；
5. 订单幂等、部分成交、UNKNOWN、重启、原子提交和 broker 权威对账；
6. 密封证据、提交预算、未来第二策略的统计边界；
7. 健康检查、CI、依赖、漏洞、凭据、容器和部署路径；
8. 文档与代码清理候选的调用方、证据价值和交叉引用。

使用了单元/集成反例、真实本地数据 replay、配置加载、证据 hash 复核、Git 完整性检查、
CI 等价静态检查、`pip check`、`pip-audit`、编译检查和全量回归。

## 3. 当前系统实况

| 领域 | 当前权威实现 | 审计结论 |
|---|---|---|
| 获批策略 | `dual_index_growth_v1` | registry 为 `PAPER_APPROVED`，LIVE 为 false |
| 策略实现 | `core/signals/strategies/phase2_etf.py` | 参数约束和 long-only 权重不变量存在 |
| PAPER 配置 | `config/strategies.paper.yaml`、`portfolio.paper.yaml` | 当前参数与 Phase 2 证据一致，但开发前没有跨文件冻结根 hash |
| PAPER runtime | `core/paper_trading/phase2_runtime.py` | replay 有因果切片；尚无真实两阶段 forward 生命周期 |
| 执行与账务 | `PaperTradingEngine`、order kernel、simulated broker | 原子账务基础可复用；本轮修复见 §4 |
| promotion | `research/registry/promotion_registry.json` | 三个 promotion evidence SHA256 均复核通过 |
| 数据 | `BarStore`/`MarketDataStore`/adjusted panel | Phase 2 总回报数据路径有效；forward 尚缺 available/received time 契约 |
| sealed evidence | 历史 sealed ledger/holdout 纪律 | 尚无满足 Phase 3 权限边界和预算的独立 evaluator |
| 运维 | health check、CI、SQLite、本地报告 | 可作为基础；scheduler、lease、告警和 Phase 3 readiness 尚缺 |
| 部署 | 旧 Dockerfile | 运行旧 `run_paper.py`，未携带 Phase 3 artifact/registry，不可作为验收部署 |

## 4. 已确认并修复的问题

| ID | 级别 | 反例与影响 | 修复 |
|---|---|---|---|
| A-01 | P1 | `RESEARCH_QUALIFIED` 策略可直接进入 PAPER runtime | 只接受精确 `PAPER_APPROVED` |
| A-02 | P1 | 严格 VIX 模式被 `ffill` 掩盖，陈旧尾部仍可交易 | 最新目标 session 必须有同日有效 VIX |
| A-03 | P0 | LIVE 意外开启时 health check 返回 0 | readiness 改为 failed、退出码 1 |
| A-04 | P1 | runtime 把 broker 未结订单硬编码为空 | 使用稳定 broker order identity 做双向对账 |
| A-05 | P1 | 模拟部分成交余量永远停在非终态 | 部分成交后原子取消未成交余量 |
| A-06 | P1 | 同一 canonical order 的不同部分成交被错误去重 | 幂等键加入 execution identity/成交签名 |
| A-07 | P0 | 无持仓 SELL 在 simulated broker 中增加现金 | 超卖在 broker 边界拒绝，不改变账务 |
| A-08 | P1 | NaN/Inf 价格、VIX、现金或仓位可能绕过比较 | 所有执行和快照数值显式 finite/long-only 校验 |
| A-09 | P1 | 新现金校验把 `-4.5e-13` 浮点残差当成 margin | 一美分内残差按会计零处理，真实负现金仍拒绝 |

对应提交：`ef447f1`、`0b91d20`、`8ecb67e`。所有修复都有先失败后通过的回归反例。

## 5. Phase 3 必须补齐、但不属于 Phase 2 结论回滚的缺口

### 5.1 策略冻结

当前只对 promotion evidence 保存 hash。运行时没有验证策略代码、配置、feature/regime、allocator、
risk、cost、data schema、schedule 和依赖环境组成的传递闭包。单个 source hash 不能证明行为冻结。

### 5.2 真正 Forward PAPER

现有 `run_session` 在一次调用中同时读取前一收盘、当日开盘和当日收盘；它适用于有因果约束的
replay，但不能证明 T 收盘决策在看到 T+1 前已经冻结。Phase 3 必须拆为：

```text
T close complete + buffer
→ freeze decision
→ T+1 open event
→ execute exactly once
→ T+1 EOD mark/reconcile/report
```

每一步必须有 event time、available time、received time、幂等 event id 和持久状态。

### 5.3 权限与密封证据

同一用户、同一文件系统中的“隐藏目录”不等于不可变或组织隔离。Phase 3 本地实现只能证明
hash-chain、原子 append、冲突拒绝和 evaluator capability boundary；若没有独立 UID、容器或远端
对象锁，报告必须明确不能声称抵御同主机管理员篡改。

### 5.4 调度与部署

单机文件锁不能防止云端多副本 split-brain。共享状态必须使用 lease、过期时间和 fencing token。
云端验收限于 IaC/static/container/local smoke；本任务没有付费资源授权。

### 5.5 broker 与成交真实性

日频 OHLC 无法真实还原队列、盘口和任意限价单部分成交。没有 bid/ask 时只能标记为 synthetic，
不能把模拟参数写成真实成交事实。真实券商只允许 mock、sandbox-read-only 或文件快照适配器。

## 6. 量化结论复核

- `dual_index_growth_v1` 的 Phase 2 promotion evidence 三个 SHA256 与 registry 完全一致。
- Phase 2 报告的 holdout 指标和 28/28 gate 记录未被本轮修改。
- 当前一个策略不足以估计多策略互补性；不得从单策略结果外推组合结论。
- 2024—2026 holdout 已被观察。sealed store 能证明代码访问轨迹，不能抹除研究人员已经知道的市场结果。
- 第二策略的正常解锁条件仍是：至少 252 个严格晚于 2026-07-17 的未见交易 session，且在读取该
  block 前完成预注册；或用户批准一套不相交、point-in-time、可审计的新数据协议。
- 短期 Forward PAPER 的主要价值是验证工程、成本和状态一致性，不是用少量收益自动证明 alpha。

## 7. 清理审计

删除候选必须同时满足：

1. 不被 import、CLI、config、CI、测试或运行时路径使用；
2. 不承担实验失败、sealed access、promotion 或事故证据；
3. 不被 README、CLAUDE、INDEX、代码注释或其他文档引用；
4. 内容可由更权威的现行来源完整重建。

本轮没有 tracked 文件同时满足四项。大量旧 PRD/memo 看似不参与运行，却是研究自由度、失败策略、
密封窗口访问和历史决策的审计链；删除会使未来无法判断某个假设是否已经试过。未发现 `.bak`、
`.orig`、临时 tracked 文件或可安全删除的大型生成物。因此删除数量为 0。

## 8. 工程与安全验证

- 配置加载：通过，long-only/no-margin/blacklist 保持。
- promotion evidence hash：3/3 通过。
- `pip check`：通过。
- `pip-audit`：无已知漏洞；本地包 `pqs` 因不在 PyPI 跳过。
- CI 等价 Ruff fatal rules：通过。
- CI 范围 mypy（`core/trading core/runtime`）：通过。
- `compileall core scripts`：通过。
- secret pattern scan：未发现凭据或私钥。
- Git fsck：无损坏；仅有可回收 dangling objects，不执行破坏性清理。
- 全仓 Ruff 完整规则存在 2,323 项历史格式/命名/未使用告警。CI 有意只阻止 fatal rules；本阶段不做
  与功能无关的全仓机械重排，以免制造巨大无关 diff。新增/修改文件执行完整 Ruff。
- 全量 pytest：运行中；完成后在本文件和最终报告记录准确计数，不用部分结果冒充全量通过。

## 9. 审计出口

进入 Phase 3 开发的条件：

- 现有运行路径中已知 P0/P1 有回归测试并关闭；
- promotion 和数据证据未被重算或改写；
- PRD 先按本审计的隔离、因果时间和诚实声明要求修订；
- 新模块默认 PAPER、默认 fail-closed、绝不创建真实 broker/cloud 外部状态。

以上条件已满足；全量回归仍作为阶段最终验收门持续执行。
