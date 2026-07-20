# PQS Phase 3 最终审计与交付报告

日期：2026-07-20  
分支：`codex/forward-paper-and-sealed-evidence-v3`  
基线：`3b9baf8d34b890ca3520f37b28ef55ab9d63cfdc`  
回退标签：`codex-pre-forward-paper-phase3-20260720`  
结论：`CODE_COMPLETE / LOCALLY_VERIFIED / EXTERNAL_RUNTIME_NOT_STARTED`

## 1. 最终结论

经开工审计、PRD 独立修订、八个实施阶段和最终反向验证，Phase 3 在获授权的本地范围内完成。系统已从
Phase 2 replay 基础升级为具备因果事件状态机、租约/fencing、broker-authoritative 对账、冻结 tracking、
密封证据预算、collect-only 数据入口、只读控制面、本地 durable 告警和安全部署模板的 Forward PAPER
代码库。

这不是“策略已经在线运行”的结论。正式 runtime 和 broker 数据库尚未初始化，真实 Forward PAPER session
为 0，sealed batch/submission/evaluation 为 0，真实采集 batch 为 0，容器和云资源均未创建。控制面的权威
结果是 `NOT_READY`、`ready_for_live=false`。第二策略没有新独立证据，继续 blocked。

## 2. 开工审计与修复

开工前不是只看文件结构，而是沿 promotion、数据可用时间、订单、现金、broker snapshot、重启和 health
路径执行反例。共关闭 2 个 P0 和 7 个 P1：LIVE 误开仍健康、无持仓卖出造现金、晋升状态过宽、VIX
尾部陈旧、未结订单对账缺失、部分成交不终止、fill 幂等冲突、NaN/Inf 绕过以及浮点现金容差。

清理审计逐一检查 import、CLI、配置、CI、测试、文档引用和历史证据用途。没有 tracked 文件同时满足
“无调用、无证据价值、无引用、可完整重建”，所以删除 0 个文件。保留旧 PRD/memo 是为了保存研究自由度、
失败候选、sealed 访问与事故审计链，不是忽略清理。

开发中还发生了一次有效的反向验证：新增控制面时曾触碰被冻结的 `core/trading/controls.py`，artifact
验证立即报告 drift。改动被完整撤回，扩展逻辑移到新 operations 模块，原策略根哈希随后恢复并通过。
这证明冻结门实际 fail-closed，而不是仅有文档声明。

## 3. PRD 审计结果

用户 PRD 的方向保留，但 v1.1 在实现前收紧了十二项关键边界：单源 hash 改为传递行为 manifest；本地
不可变不冒充管理员隔离；每次指标输出消耗四层预算；已公开历史不重新变成未见数据；forward 拆为三阶段；
日线部分成交明确 synthetic；PAPER enabled 不等于准许下单；file lock 升级为 lease/fencing；broker 仅
simulated/file/read-only；云范围限于准备和 smoke；tracking 阈值先冻结；LIVE 不提供普通开关。

修订后的权威需求是 `docs/PHASE3_PRD.md`，开工证据是 `docs/PHASE3_AUDIT.md`。实现没有降低量化晋升门槛。

## 4. PRD 反向映射

| PRD 领域 | 实现与证据 | 最终状态 |
|---|---|---|
| §3 不变量 | long-only/no-margin/blacklist、finite 校验、risk-increase veto、LIVE 三层 false | PASS |
| §4 策略制品 | canonical 传递组件 manifest、环境/evidence hash、启动与决策前复验、drift pause | PASS |
| §5 Forward PAPER | close/open/EOD 持久状态机、可用时间、cursor、幂等、恢复、lease/fencing | PASS（合成 E2E；真实 session 0） |
| §6 Broker | 持久 simulated history、稳定 execution id、partial/UNKNOWN、file read-only snapshot、双向对账 | PASS（无真实 broker 写入） |
| §7 Tracking | benchmark/control policy 预冻结，收益/风险/成本/延迟/错误/tracking error 分类 | PASS（observation 0） |
| §8 Sealed evidence | append-only hash chain、revision、预注册、四层并发预算、固定 subprocess evaluator | PASS（真实提交 0；同 UID 限制保留） |
| §9 数据采集 | 日频、1m/5m、期权固定 schema；file/mock；trusted/quarantine；revision/cursor | PASS（collect-only；真实 provider 0） |
| §10 第二策略 | 一个未来假设已预注册；未读新 block、未提交、未晋升 | BLOCKED AS DESIGNED |
| §11 控制/告警 | 真只读 status/readiness；显式确认且幂等的操作；16-rule durable local sink | PASS（外部通知未配置） |
| §12 部署 | 非 root/read-only image、Compose/K8s/IaC 契约、supervisor、备份恢复 | CONDITIONAL PASS（未 build/deploy） |
| §13 反例 | drift/future/乱序/崩溃/fencing/broker/tamper/budget/ingestion/alerts/LIVE/restart | PASS |
| §14 总验收 | 完整回归、CI 等价、证据认证、文档、Git 推送和诚实外部状态 | PASS |

## 5. 核心实现

### 5.1 策略与运行

唯一获批策略 `dual_index_growth_v1/v1` 的根哈希为
`7d1c2d96ea06f051f298331a6a9a8a5bc6e0b85af72fd158e8524cc56b0a553c`。它绑定策略、配置、
feature/regime、allocator、risk、cost、data contract、runtime、依赖和 promotion evidence。任何组件漂移均
在订单前失败并暂停。

Forward runtime 严格执行 `T close decision → T+1 open execution → T+1 EOD finalize`。阶段、事件、决策、
order、execution、cursor 和 fencing token 均持久化；重复事件复用结果，乱序/陈旧 writer 拒绝。broker
snapshot 在对账时是权威来源，UNKNOWN、陈旧或不一致禁止增加风险。

### 5.2 研究与数据边界

sealed store 不向研究调用方返回 raw rows。预注册、submission、attempt 和 result 分离，global/family/
hypothesis/version 预算由 SQLite 事务串行控制；异常默认计数。固定 evaluator 在 scrubbed subprocess 中只
返回允许的 summary。当前只有 1 个未来假设，最早 eligible date 为 2026-07-21，没有真实 submission。

日频、日内和期权采集共享 event/available/received time、source、quality、content hash、previous hash
和 revision lineage。trusted 与 quarantine 物理分区但在同一全局链上；策略消费开关固定为 false。

### 5.3 控制与部署

status 使用 SQLite `mode=ro/query_only`，不会为了“查看状态”初始化 runtime。pause/resume/reconcile/
ack/resolve 必须提供 request id 和精确 `YES:<request-id>`，并写幂等操作账本。resume 会重新检查所有
readiness gate，不能越过 artifact、数据库、broker 或 LIVE 问题。

部署层的 supervisor 只监控，不生成市场事件。镜像、Compose、Kubernetes 和 Terraform 模板均 fail-closed；
详细条件见 `docs/CLOUD_PAPER_DEPLOYMENT.md`。

## 6. 最终验证

| 检查 | 结果 |
|---|---|
| 完整 pytest | `4320 passed, 23 skipped, 1 xfailed, 43 warnings in 1977.48s` |
| 配置加载 | PASS |
| Ruff fatal rules | PASS |
| mypy `core/trading core/runtime` | PASS |
| compileall | PASS |
| `pip check` | PASS |
| `pip-audit` | 无已知第三方漏洞；本地 `pqs` 包不在 PyPI，按工具语义跳过 |
| 策略 artifact | PASS |
| 部署静态 validator | PASS |
| 凭据特征扫描 | 未发现凭据或私钥 |
| `git fsck --full` | 无损坏；24 个可恢复 dangling objects 保留，garbage 为 0 |

23 个 skip 已逐项解释：20 个需要未安装的可选 Torch，2 个仅适用于 options-only 分支，1 个验证
`expanded_v1` 已存在时的幂等分支；无未解释 skip。43 个 warning 全部来自明确构造的非法价格、常量序列
相关系数、模拟模型崩溃、calendar embargo fallback 或非法 datetime 反例。

唯一 xfail 是冻结 conservative 策略在 expanded universe 上尚未稳定证明全周期 CAGR 超过 QQQ；holdout
断言仍通过。这是保留的量化限制，不是工程跳过，也不能用 Phase 3 基础设施完成来抹掉。

机器证据：

- `research/results/phase3/final_validation.json`
- `research/registries/runtime_certifications/phase3_forward_v1.json`
- runtime certification root：
  `438d366637d146be189617eaefd678f8127a634222eeb6ad2428ee4bacc93cb0`

## 7. 当前权威运行状态

| 状态 | 数值 |
|---|---|
| mode / LIVE | `FORWARD_PAPER` / false |
| readiness | `NOT_READY`；runtime account、runtime DB、broker DB 未初始化 |
| active / critical alerts | 0 / 0 |
| real Forward PAPER sessions | 0 |
| tracking observations | 0 |
| sealed batches / submissions / attempts | 0 / 0 / 0 |
| preregistered hypotheses | 1 |
| daily / intraday / options real batches | 0 / 0 / 0 |
| real provider configured | false |
| container built / cloud deployed | false / false |
| cloud resources created | 0 |
| second strategy promoted | false |

所以最准确的完成语义是：代码和本地安全性质通过验收；长期 Forward PAPER、真实数据积累、外部隔离和
云端运行尚未发生。当前绝不满足 LIVE readiness。

## 8. 交付与后续

Phase 3 的十份主文档已齐备：开工审计、修订 PRD、路线图、Forward PAPER、sealed evidence、数据采集、
控制面、运维、云部署准备和本最终报告。配置、registries/submissions/sealed_results、deployment、monitoring、
实现和测试也已落库。

下一步不是继续调参，而是由获授权 operator 完成安全部署前置、初始化 PAPER runtime/broker snapshot，随后
按真实市场日历累计 forward observations。第二策略必须等待至少 252 个严格晚于 2026-07-17 的未见 session，
或用户批准的不相交 point-in-time 协议；之后仍需独立 sealed、PAPER 与聚合风险验收。

在这些外部条件发生前，系统应保持 PAPER、broker write false、LIVE false 和第二策略 blocked。
