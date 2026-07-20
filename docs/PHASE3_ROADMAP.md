# PQS Phase 3 实施路线图

日期：2026-07-20  
权威需求：`docs/PHASE3_PRD.md`  
状态文件：`.codex/phase3_state.json`

## 执行原则

每个阶段遵循：反例/验收测试 → 最小实现 → focused regression → 自审 → 显式文件提交 → push。不得使用
`git add .` 或 `git add -A`。任何外部 broker/cloud 写操作都不在授权范围。

## R0 基线与开工审计

状态：完成（全量回归最终结果待阶段收口回填）。

- 推送 Phase 2 基线和回退标签；
- 创建独立 Phase 3 分支和状态文件；
- 复核 promotion/data/config/broker/runtime；
- 修复审计发现的现有 P0/P1；
- 完成依赖、漏洞、secret、CI 等价和清理审计；
- 保存 `PHASE3_AUDIT.md`、修订 PRD 和本路线图。

## R1 策略工件冻结

目标：创建传递行为 manifest，不以单文件 hash 冒充冻结。

- 实现 canonical serializer、component hasher、artifact builder/validator；
- 建立 `research/registries/strategy_artifacts/`；
- 冻结 `dual_index_growth_v1` 代码、参数、schema、regime/allocator/risk/cost/schedule/evidence；
- runtime 启动和决策前验证；
- drift、symlink、path escape、证据 hash 变化反例；
- 生成策略 artifact 和冻结报告。

出口：原 artifact 通过；任一行为 component 变化 fail-closed 且 global pause；新版本不继承批准状态。

## R2 三阶段 Forward PAPER

状态：完成（提交 `f456dd8`；三阶段状态机、lease/fencing、CLI 和反例已通过）。

目标：从 replay 升级为真实事件生命周期。

- 定义 injected clock、market event envelope、session calendar；
- 持久化 close decision、open execution、EOD finalize 状态机；
- 添加 cursor、decision hash、event id 和恢复逻辑；
- 实现 SQLite lease + fencing token；
- 新建 Phase 3 CLI，支持 `status`、单阶段 `run-once` 和 scheduler；
- 复用 strategy/allocator/risk/order/accounting，不复制一套交易逻辑；
- 生成 daily audit 和 tracking snapshot。

出口：手动时钟 E2E 证明 T 决策在 T+1 数据出现前冻结；重复/乱序/崩溃/双实例不重复订单。

## R3 Broker authority 与 tracking

状态：完成（持久 broker history、file read-only authority、snapshot freshness、冻结 tracking policy 和
分类报告已通过；真实 broker 与真实 forward observation 仍按权限/时间边界明确未发生）。

- 持久化 simulated broker fill/open-order history；
- 添加 file/sandbox-read-only snapshot adapter，写接口硬拒绝；
- 新鲜度、稳定 identity 和双向 reconcile；
- 冻结 tracking benchmark/control policy；
- 输出收益、风险、成本、延迟、错误率和 tracking error；
- fault injection 覆盖 partial、duplicate、UNKNOWN、timeout、stale snapshot。

出口：任何 broker 不确定性阻止风险增加；tracking 不自动改参数或 promotion。

## R4 Sealed evidence

状态：完成本地实现（store、registry、budget、subprocess evaluator 和 16 个专项反例通过）；真实 future
batch/submission/result 均为 0，同 UID/admin 隔离和远端 object lock 未声称具备。

- 实现 atomic append-only batch、content hash、previous hash、revision lineage；
- 防 path traversal、symlink、覆盖和链断；
- 建立 preregistration/submission registry；
- 实现全局/family/hypothesis/version 并发安全预算；
- evaluator 以 scrubbed subprocess 运行，固定输入输出 schema；
- 生成 tamper/budget/access audit evidence。

出口：研究调用方无法通过公共 API 取得 raw sealed rows；重复/改名/并发不能绕过预算；本地隔离限制被明确记录。

## R5 数据采集

状态：完成本地 collect-only 实现（三类固定 schema、file/mock adapter、物理 trusted/quarantine 全局哈希链、
revision/cursor 恢复和合成 E2E）；真实 provider、真实持续调度和真实批次均为 0。

- 统一 ingestion envelope 和 provider protocol；
- 日频 total-return/corporate-action file/mock E2E；
- 日内 quote/bar file/mock E2E，仅采集；
- 期权 chain file/mock E2E，仅采集；
- checksum、quality、quarantine、revision 和三类时间；
- 调度/断点续传/重复批次幂等。

出口：三类管线均可在无付费 provider 时运行并生成可验证 manifest；不得声称已有真实持续数据源。

## R6 控制面、告警与运维

- 只读 CLI/API status snapshot；
- pause/resume/reconcile 显式确认和审计；
- durable local alert sink、dedup、severity、ack/resolution；
- missed schedule、data、artifact、broker、risk、DB、LIVE 规则；
- health/readiness 扩展为 artifact/lease/reconcile/sealed 状态；
- 完成 `FORWARD_PAPER.md`、`SEALED_EVIDENCE.md`、`DATA_COLLECTION.md`、
  `CONTROL_PLANE.md`、`PHASE3_OPERATIONS.md`。

出口：无通知凭据时本地告警仍不丢失；LIVE true 始终 readiness failed。

## R7 部署准备

- 更新非 root Docker image 和 Phase 3 entrypoint；
- 添加 compose/local smoke、只读 mount、持久卷和 shutdown；
- 添加 Terraform/OpenTofu 或等价 IaC 模块及静态校验；
- 设计 singleton lease、备份、恢复、rollback 和 least privilege；
- 不创建任何付费资源；记录 Docker/IaC 工具缺失的条件性结果。

出口：本地可用工具范围内 build/start/health/restart/volume persistence smoke 通过，IaC 静态验证通过。

## R8 最终验证与诚实收口

- 执行全部必测反例和故障注入；
- 运行全量 pytest、CI 等价 Ruff/mypy、config、artifact、pip check/audit；
- 对实现逐条反向映射 PRD；
- 检查 tracked/untracked、文档链接、secret 和外部状态；
- 更新 `.codex/phase3_state.json`、`docs/INDEX.md`；
- 生成 `CLOUD_PAPER_DEPLOYMENT.md` 和 `PHASE3_FINAL_REPORT.md`；
- 分逻辑提交并 push。

出口：报告清楚区分“代码/测试验证”“本地运行”“真实 forward 已积累时长”“外部集成”“blocked”。没有新
证据时，第二策略保持 blocked；没有云账户时，云部署写作 prepared/smoke-tested，不能写 deployed。
