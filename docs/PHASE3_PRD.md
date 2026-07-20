# PQS Phase 3 产品需求文档（审计修订版）

版本：v1.1  
日期：2026-07-20  
状态：APPROVED_FOR_IMPLEMENTATION  
上游：用户提供的 Phase 3 PRD v1.0 与自主执行任务  
审计依据：`docs/PHASE3_AUDIT.md`

## 1. 产品目标

将 PQS 从“历史 backtest 与 PAPER replay 已验证”推进为一个可长期运行、可恢复、可审计的 Forward
PAPER 系统，并建立不依赖重复查看旧 holdout 的 sealed evidence 和新数据积累机制。

必须交付：

1. `dual_index_growth_v1` 的不可静默漂移策略工件；
2. 严格分离收盘决策、次日开盘执行和日终对账的 Forward PAPER runtime；
3. append-only、hash-chained、预算约束的 sealed store/evaluator；
4. 股票/ETF 日频、日内和期权数据采集契约与可运行 mock/file 路径；
5. 只读控制面、明确确认的暂停操作、告警、运维和部署材料；
6. 云兼容的容器/IaC/多实例互斥设计与本地 smoke evidence；
7. LIVE 在 config、registry/artifact、runtime 三层保持关闭。

第二策略不是无条件验收项。没有新独立证据时，正确结果是基础设施完成、候选边界预注册、晋升继续
阻塞，而不是降低门槛。

## 2. v1.0 审计修订

本版保留原业务方向，并作以下约束性修订：

1. `source_code_hash` 升级为传递行为 manifest 根 hash，覆盖策略、参数、feature/regime、allocator、
   risk、cost、data schema、schedule、promotion evidence、commit 和运行环境；
2. 本地“不可变”限定为 canonical payload、SHA256、hash-chain、原子写、冲突拒绝和权限收紧，
   不声称能抵御同主机管理员；
3. sealed evaluator 的每次指标输出也消耗信息预算；family/hypothesis/version/全局预算均不可通过改名重置；
4. 公开市场历史不能因为写入 sealed 目录就重新变成“人类未见”。新候选必须在未来 block 前预注册；
5. Forward PAPER 拆为 close-decision、open-execution、EOD-finalize 三个持久阶段；
6. 日线 OHLC 的限价/部分成交只能标记 synthetic；有真实 bid/ask 才可使用 quote-based 模拟；
7. `PAPER enabled` 只表示模式和策略被选择，实际订单还必须通过 artifact、data、lease、risk 和 reconcile gate；
8. scheduler 使用 lease + fencing token，不以本地 file lock 冒充多实例安全；
9. broker 范围限于 simulated、mock、file snapshot 和 sandbox-read-only；无写权限、无真实订单；
10. 云端范围限于 IaC/static/container/local smoke，不创建付费资源；
11. tracking threshold 在 forward 数据产生前冻结，任何参数变化只能生成未继承 promotion 的新版本；
12. LIVE 不提供普通控制面开关，必须继续受三层 fail-closed 检查和未来单独用户授权约束。

## 3. 不变量与权限边界

### 3.1 交易不变量

- long-only、no-margin、no-short；
- SQQQ/SOXS/SPXU/SPXS/SDS/TZA blacklist 不得绕过；
- 现金不能低于会计容差外的零；
- 任何风险增加订单必须通过独立 pre-trade veto；
- stale/missing/out-of-order/UNKNOWN/hash drift/reconcile failure 一律不新增风险；
- risk-reducing liquidation 是否允许必须由显式 policy 决定，不隐式放行；
- T close 信号不得读取 T+1 数据，只能在下一合法 execution event 使用。

### 3.2 环境不变量

```yaml
mode: PAPER
live_enabled: false
broker_write_enabled: false
paid_cloud_create_enabled: false
```

任一层出现 LIVE true，health/readiness 必须失败。运行代码不得读取真实 broker 写凭据。

### 3.3 研究权限

- 研究进程只能读取 development/approved validation；
- sealed evaluator 只接收冻结 artifact 和预注册 submission，不接受任意研究代码路径；
- evaluator 子进程使用最小环境变量、独立工作目录、只读 artifact 和受限输出 schema；
- 原始 sealed 数据、逐日收益和未批准中间量不得返回；
- 每次成功、失败、异常或重复提交都进入 append-only audit journal。

## 4. Strategy Artifact Registry

每个 artifact 是 canonical JSON。至少包含：

```text
artifact_schema_version
strategy_id / strategy_version / promotion_status
allowed_runtime_modes / live_enabled
code_commit / python_version / dependency_lock_hash
component_paths[]: path, sha256, role
strategy_parameters / universe / schedule
feature_schema_hash / data_contract_hash
regime_policy_hash / allocator_policy_hash
risk_policy_hash / cost_model_hash
promotion_evidence[]: path, sha256
created_at_utc / artifact_root_sha256
```

根 hash 由排除根 hash 字段后的 canonical payload 计算。artifact 创建后同 ID 内容不同必须拒绝；runtime
每次启动和每次决策前验证根 hash及所有 component。任何 drift 自动 global pause 并发出 critical alert。

修改任何行为组件必须创建新版本，`promotion_status=UNREVIEWED`，不得继承旧批准状态。

## 5. Forward PAPER 事件模型

### 5.1 三阶段生命周期

1. `CLOSE_DECISION`：交易所确认 T session 完成并经过 configured buffer；数据质量通过；只加载
   `available_at <= decision_cutoff` 的数据；生成并冻结 target、regime、risk inputs 和 decision hash。
2. `OPEN_EXECUTION`：只处理前一合法 session 的已冻结 decision；校验 artifact、lease/fencing、data、
   pause 和 reconciliation；生成 canonical orders 并恰好执行一次。
3. `EOD_FINALIZE`：用 T+1 完整收盘 mark-to-market，更新 NAV，执行 broker-authoritative reconcile，
   写 daily report 和 tracking snapshot。

每个事件记录 `event_time`、`available_time`、`received_time`、`processed_time`、session、phase、event id、
decision id、artifact hash 和 fencing token。阶段乱序或重复必须拒绝/复用，不能重复订单。

### 5.2 Clock、calendar 与 scheduler

- 所有内部时间为 timezone-aware UTC；交易 session 由 NYSE calendar 决定；
- production clock、manual/test clock 通过依赖注入替换；
- scheduler 只能在 lease 有效且 fencing token 最新时写状态；
- 崩溃恢复从持久 cursor/decision/order/account state 继续；
- replay 必须明确标记 `PAPER_REPLAY`，不得计入 `FORWARD_PAPER` 时长。

## 6. PAPER broker 与权威对账

接口必须提供稳定 order/fill identity、positions、cash、open orders、fills、snapshot time 和 source。支持拒单、
部分成交、撤单、超时、UNKNOWN、重复 callback 和重启恢复。没有 quote 的 market/open fill 使用共享成本模型；
limit/queue 结果标记 synthetic。相同订单的多个 fill 依 execution id 区分，重复 execution id 幂等。

本地 ledger 与 broker snapshot 对 cash、positions、open order ids 和 snapshot freshness 双向比较。任何非有限、
负仓位、超卖、未知身份或不一致触发 global pause。真实 broker 适配器仅可实现 read-only snapshot；写接口
必须在本阶段硬拒绝。

## 7. Forward tracking

跟踪收益、波动、drawdown、beta、turnover、持仓周期、signal/regime 分布、成本、slippage、延迟、拒单、
部分成交、缺失率、停机、reconciliation 和 backtest-to-forward tracking error。

控制限、最小 session 数和比较基准在首个 forward observation 前冻结。少量亏损不自动改策略，超出控制限
只触发 pause/review。tracking 报告必须区分工程异常、成交模型差异和市场表现，禁止自动优化参数。

## 8. Sealed evidence 与提交预算

### 8.1 Store

每批数据保存 source、event/available/received time、schema、quality flags、content hash、previous record hash
和 revision lineage。写入使用临时文件 + fsync + 原子 rename；journal 链断、同 ID 冲突或旧版本覆盖均失败。

### 8.2 Evaluator

输入仅限 artifact id、preregistered hypothesis id、metric policy id、benchmark/cost policy id。评估器验证
artifact 和预算后，在 scrubbed subprocess 中读取 sealed block。输出固定 summary schema 和 pass/fail，不返回
raw rows、逐日曲线或任意查询结果。

### 8.3 Budget

至少执行全局、family、hypothesis 和 artifact version 四级预算。alias/rename 通过 immutable hypothesis lineage
归并。异常提交也计入 attempt；只有 evaluator 明确判定为基础设施故障时可由审计事件返还额度。预算政策
本身 hash 冻结，不能在看到结果后扩大。

## 9. 新数据采集

- 日频股票/ETF：OHLCV、total-return adjustment、dividend、split、corporate action、calendar、三类时间、source、quality；
- 日内：1m/5m、bid/ask/volume、session flag、latency、missing/out-of-order，仅采集不晋升策略；
- 期权：chain、bid/ask、volume/OI、IV/Greeks、strike/expiry/type、timestamps、multiplier、quality，仅采集；
- provider 通过 adapter 注入；无外部凭据时 file/mock 路径必须端到端可运行；
- 原始批次 append-only，校验失败进入 quarantine，不覆盖最后可信版本；
- 所有 revision 可追溯，不把事后修订伪装成当时可用数据。

## 10. 第二策略边界

允许预注册经济假设和数据需求，不允许再读旧 holdout 调参。优先方向保持：SPY volatility target、防御 ETF
轮动、日频 ETF 均值回归、宽基与现金/短债配置。高度相似的 QQQ/TQQQ trend、换窗口克隆和根据已见结果
反向设计均拒绝。

正常晋升的解锁条件是 252 个严格晚于 2026-07-17 的未见 session，或用户批准不相交的 point-in-time
数据协议。即使解锁，也必须独立通过 preregistration、submission budget、sealed evaluator、PAPER operational
gates 和与现有策略的聚合风险/互补性测试。

## 11. 控制面、告警与操作

只读状态必须展示：service/data/scheduler 状态、artifact hash、regime/confidence、targets、positions/orders、
cash/NAV/PnL/drawdown、risk budget、reconciliation、kill switch、alerts、deployment version 和最新 event cursor。

pause/resume/reconcile 等写操作必须显式确认、记录 actor/reason/request id，并幂等。Phase 3 不提供 LIVE toggle。

告警规则来自 hash-tracked config，至少覆盖 missed schedule、stale/missing/out-of-order data、artifact drift、
UNKNOWN、duplicate、reconciliation/NAV/risk breach、daily loss/drawdown、DB failure、registry anomaly 和 LIVE true。
没有外部通知凭据时使用 durable local sink，并提供 adapter contract。

## 12. 部署与安全

- 非 root 容器、只读根文件系统、显式 writable volumes、health/readiness、graceful shutdown；
- secrets 仅从环境或 secret mount 注入，日志脱敏，仓库不保存 secret；
- IaC 定义最小权限、持久卷、备份、scheduler singleton/lease 和回滚；
- CI 运行 dependency/vulnerability、fatal static、mypy safety scope、完整 tests、config/artifact validation；
- 本阶段只执行 Docker/IaC/static/local smoke，不登录或创建任何付费云资源；
- 缺少 Docker 时以静态验证加本地进程 smoke 记录为条件性结果，不能写成实际云部署成功。

## 13. 必测反例

artifact/config/code drift；future data；pre-close partial bar；duplicate/out-of-order event；close 阶段崩溃；open
阶段崩溃；broker fill 后 ledger 前崩溃；report 前崩溃；lease 过期和 stale fencing writer；duplicate/partial/
UNKNOWN order；oversell；NaN/Inf；stale snapshot；reconcile mismatch；global/strategy/symbol pause；kill switch；
sealed chain tamper；path traversal/symlink；subprocess env leak；budget race/rename bypass；ingestion revision/quarantine；
alert dedup；LIVE true；restart determinism；BT/replay parity；container/IaC smoke。

## 14. 交付物与验收

交付原 PRD 要求的 10 份文档、4 个配置、`research/registries`、`research/submissions`、
`research/sealed_results`、`deployment`、`monitoring`，以及实现和测试。

Phase 3 完成必须满足：

- 审计 P0/P1 全关闭并有反例；
- 获批策略 artifact 创建、验证、漂移 fail-closed；
- 三阶段 Forward PAPER 端到端、重启、幂等、lease 和 reconciliation 通过；
- sealed store/evaluator/budget 安全反例通过；
- 三类采集 adapter 的 mock/file E2E 通过；
- 控制面和本地 durable alerts 可运行；
- 容器/IaC/static/local smoke 有真实记录；
- PAPER 是默认模式但仍受全部 order gates；LIVE 在三层为 false；
- 完整回归、CI 等价检查和最终自我审计通过；
- 所有未具备的外部能力、实际运行时长和第二策略状态如实标记为条件性或 blocked。

## 15. 非目标

真实资金、broker 写权限、付费云资源、购买商业数据、高频交易、日内/期权策略晋升、降低 promotion gate、
重复挖掘已见 holdout、用模拟 bid/ask 冒充真实盘口、在有限 forward 样本上自动优化策略，均不在本阶段授权内。
