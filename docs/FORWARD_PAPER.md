# PQS Phase 3 Forward PAPER 运行与证据契约

版本：v2（governance reconciliation）

日期：2026-07-20

模式：`FORWARD_PAPER` / `PAPER`

LIVE：始终关闭

## 1. 已实现结论

Phase 3 runtime 不再把一段历史数据一次性 replay 后称为 forward。每个交易周期被拆成三个可恢复、
可幂等、带市场时间和数据可用时间的事件：

```text
T EOD_FINALIZE（先完成当日账务）
→ T CLOSE_DECISION（冻结 T+1 决策）
→ T+1 OPEN_EXECUTION（只执行已冻结决策）
→ T+1 EOD_FINALIZE
```

首次启动没有旧持仓时可以直接从 `CLOSE_DECISION` bootstrap。进入连续运行后，同一 session 的 EOD
必须先于新 close decision 完成；配置固定 EOD buffer 为 5 分钟、close-decision buffer 为 10 分钟，
避免两个阶段在同一时刻竞态。

本实现证明因果时序、状态恢复、执行幂等、账务一致性和工程可运行性。它不证明未来收益，不把历史
replay 天数计作 forward 时长，也不授权真实券商或 LIVE。

## 2. 权威入口与配置

- 配置：`config/forward_paper.yaml`
- CLI：`scripts/run_forward_paper.py`
- runtime：`core/paper_trading/forward_runtime.py`
- durable state：`core/paper_trading/forward_state.py`
- scheduler lease：`core/runtime/lease.py`
- target/order parity：`core/execution/target_weight_planner.py`
- tracking：`core/paper_trading/forward_tracking.py`
- file broker authority：`core/execution/read_only_broker.py`

运行入口每次启动都严格验证 observation artifact 的根 hash、全部传递组件、参数、universe、schedule 和精确
Python/package 环境。CLI 不提供跳过 artifact 环境校验的生产开关。

当前 `run-once` 明确 fail-closed：collector 仍是 `COLLECT_ONLY`，本地策略价格 loader 并未消费并验证
collector record，所以调用者提供任意 64 位 hash 不能建立数据血缘。只有未来实现“验证 trusted record →
读取该 record 的 rows → 证明 phase 时间可用 → 将同一 record hash 写入事件”的闭环后，才允许真实事件。
直接调用 runtime 的单元/合成 E2E 只证明状态机，不计作真实 forward。

配置边界必须同时满足：

```yaml
mode: PAPER
live_enabled: false
broker_write_enabled: false
paid_cloud_create_enabled: false
broker:
  adapter: simulated
  external_write_enabled: false
```

任一值漂移会在 runtime 构建前失败。

## 3. 事件契约

每个事件必须提供：

- 唯一 `event_id`；
- NYSE 合法 `session`；
- phase 对应的交易所 open/close `event_time`；
- 数据完成并可消费的 `available_time`；
- 系统接收的 `received_time`；
- 小写 64 位 `source_batch_sha256`；
- 当前 scheduler lease 和 fencing token。

三个时间必须 timezone-aware，且满足 `event_time <= available_time <= received_time <= now`。事件超过
30 分钟、早于阶段 completion buffer、落在非交易日、缺少精确日线/VIX 或 source hash 格式不合法都会
失败。相同 event id 与相同内容复用原结果；相同 id 不同内容硬失败。

### 3.1 CLOSE_DECISION

只向策略暴露截至 T close 的历史。runtime 记录可见数据最后日期、close/VIX history hash、regime、
confidence、原始 target、allocator/risk/kill-switch 后 target、账户权益、artifact hash 和 T+1 session，
再以 canonical content hash 生成不可变 decision id。

如果 broker reconciliation、pause、regime 或 kill switch 不允许新增风险，仍可保存证据，但 approved
target 为零。已有连续运行状态时，T 的 EOD 未完成则不得冻结 T 的下一日决策。

### 3.2 OPEN_EXECUTION

只接受 execution session 与冻结 decision 精确匹配、状态为 `FROZEN` 的记录。下单前再次验证 artifact、
lease、broker snapshot、全局/策略/symbol pause、long-only/no-margin、现金、turnover、symbol cap 和订单
notional。target-to-order 规划器使用 T+1 实际 open 和真实持仓股数，并用 parity 测试锁定到认证
backtest order kernel 的语义。

订单注册、订单状态、fills、PAPER 账户和 forward event 在同一 SQLite 事务提交。simulated broker side
effect 先发生；若 broker outcome 为 timeout/UNKNOWN/reject，系统 global pause，且不把本地 decision
推进到 `EXECUTED`。重启后 broker 与 ledger 不一致会阻止重试，不能盲目重复下单。

### 3.3 EOD_FINALIZE

以 execution session 的完整 close mark-to-market，执行 broker-authoritative reconcile，写 NAV、daily
PnL、position、fills/cost、event processing time、tracking observation 和 daily JSON report。SQLite 状态先
durable commit；若进程在 report 前崩溃，同一 EOD event 会从已提交结果恢复报告而不重复交易。

## 4. Lease、fencing 与多实例

`SQLiteLeaseManager` 使用共享数据库中的 lease row、过期时间和单调递增 fencing token：

- 未过期时只有同 owner 能续租；
- 过期接管使 token 加一；
- release 保留 fencing 历史；
- 每个阶段在副作用前检查 lease；
- 每个状态事务在 commit 内使用最新 clock 再检查 token 和 expiry。

因此旧 writer 即使完成了耗时计算，也不能在 lease 过期或被接管后提交。CLI 在单次阶段结束后释放
lease。SQLite lease 适合共享持久卷上的单写 PAPER 服务；最终部署仍需验证目标文件系统的 SQLite/WAL
一致性，不把普通本地 file lock 当成云端互斥证明。

## 5. Broker authority

### 5.1 Simulated broker

Phase 3 默认使用持久化 simulated broker。现金、仓位、fill keys、完整 fill payload、订单生命周期和未结
订单都保存在独立 SQLite DB。重启会恢复 fills 和 crash 前 `SUBMITTED` 订单；重复 fill execution identity
幂等。SELL 超过 long position、非有限值或会造成负现金的 BUY 在 broker 边界拒绝。

### 5.2 File/sandbox read-only

`FileBrokerSnapshotAdapter` 读取独立 file snapshot，验证 schema、重复 JSON key、文件竞态、symlink、
大小、稳定 order/fill identity、有限 cash/positions 和 timezone-aware source timestamp。`submit_order`、
`cancel_order`、`mirror_fill` 全部硬抛 `BrokerWriteForbiddenError`。

它是 reconciliation authority，不是执行 destination。当前阶段没有读取真实 broker 写凭据，也没有任何
真实订单接口。

### 5.3 Freshness 和双向对账

forward runtime 只接受 coherent `BrokerAccountSnapshot`，不再分别读取 cash/position 后伪造当前时间。
快照超过 120 秒或领先 runtime clock 超过 5 秒即失败。cash、positions 和 open-order ids 双向比较；
stale、future、非有限、负仓位、未知 identity 或差异都会 global pause。simulated adapter 在被注入的
runtime observation time 产生同一时点的 coherent snapshot；file adapter 使用文件内的独立 source time。

## 6. Forward tracking

tracking policy 在 runtime 第一次打开状态库时写入并 hash 冻结。改变 benchmark、样本门槛或 control
limit 会失败并要求新的隔离版本，不能在看到 forward 结果后扩门槛。

当前 policy：

- benchmark：SPY；annualization：252 sessions；QQQ 仅诊断；
- performance minimum：60 sessions；promotion evidence minimum：252 sessions；
- max drawdown：25%；max annualized volatility：45%；
- max backtest-to-forward tracking error：15%；
- reconciliation failure：0；missing rate：0；reject rate：20%。

每个 EOD observation 记录实际收益、benchmark 收益、turnover、positions、regime/gross target、cost、
slippage、orders/fills/rejects/partials、latency、missing/downtime 和 reconciliation。报告分开输出：

1. `engineering`：reconciliation、missing、downtime 和 event latency；
2. `execution_model`：turnover、cost、slippage、reject/partial 和 tracking error；
3. `performance`：return、volatility、drawdown 和 beta；
4. `exposure`：regime distribution、gross target 和当前持仓持续 session。

没有独立 certified backtest reference 的 session 明确输出
`tracking_error_status=INSUFFICIENT_REFERENCE` 和 `null`，绝不把缺失引用写成零偏差。control breach 只
触发 pause/review，不修改策略参数。tracking 永远输出 `automatic_promotion_enabled=false`；即使超过
252 sessions，也仍需独立人工审查。

## 7. 命令示例

状态检查：

```bash
.venv/bin/python scripts/run_forward_paper.py status
```

单阶段事件（当前会被 source-binding gate 拒绝，保留为未来接口示例）：

```bash
.venv/bin/python scripts/run_forward_paper.py run-once \
  --phase close \
  --session 2026-07-20 \
  --event-id vendor-daily-close-2026-07-20-v1 \
  --source-batch-sha256 <64-char-lowercase-sha256> \
  --available-at 2026-07-20T20:10:00Z \
  --received-at 2026-07-20T20:10:03Z
```

`open` 与 `eod` 使用同一参数结构。仅提供真实 provider batch identity 仍不够；runtime 必须实际消费该
trusted record。当前不得通过编辑 `config/data_collection.yaml` 或伪造目录来打开该门。旧 event 也会因
stale gate 失败。

## 8. 恢复与故障处理

- close 前崩溃：没有 decision，重放同 event；
- close commit 后崩溃：同 event 返回冻结结果；
- open 注册后、broker 前崩溃：相同 idempotency key 可安全恢复；
- broker fill 后、本地 ledger 前崩溃：global pause，先 reconcile，不自动重发；
- EOD state 后、tracking/report 前崩溃：同 EOD event 补写 immutable tracking observation 和 report；
- artifact drift：立即 pause，后续阶段拒绝；
- stale fencing writer：事务 commit 前拒绝；
- tracking policy drift：runtime 初始化失败，旧 evidence 不被新 policy 继承。

恢复不能通过删除 SQLite、改 event id 或清空 pause 绕过。pause/resume 的显式操作和告警将在 Phase 3
控制面文档中定义。

## 9. 已验证反例

当前自动化覆盖：future T+1 数据不能改变 T 决策、阶段乱序、重复 event、event 内容冲突、artifact drift、
pre-buffer/stale event、lease 过期与计算中到期、同 session EOD 顺序、broker stale snapshot、timeout、
UNKNOWN、duplicate/partial fill、oversell、负现金、NaN/Inf、fill 与 open-order 重启恢复、file snapshot
symlink/duplicate key/write attempt、tracking policy drift、observation conflict、缺失 reference 不伪装零误差、
control breach 分类和禁止自动 promotion。

## 10. 尚未声称具备

- 没有真实 forward observation，当前 `n_forward_sessions=0`；
- collector record 尚未与 runtime 实际消费的价格绑定，`run-once` 硬阻断；
- 没有真实 broker sandbox 账号或任何写权限；
- 没有 certified future-session backtest reference，因此 tracking error 暂为 unavailable；
- 没有在云端启动 scheduler 或付费资源；
- 没有 LIVE toggle；
- 没有第二个获批策略。

这些是明确的外部条件或后续 workstream，不是用 mock 测试可以替代的事实。
