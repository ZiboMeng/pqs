# PQS Phase 3 Sealed Evidence 契约

版本：v1

日期：2026-07-20

状态：本地能力已实现；无真实 sealed batch、无真实 evaluator submission

## 1. 目标与不夸大的能力边界

本模块用于未来、预注册之后产生的新证据，提供：

- 原始 batch 的单文件原子 append、content hash、全局 previous-hash chain 和 revision lineage；
- 不可静默覆盖、重复 batch 幂等、同 ID 冲突拒绝、chain tamper 检测；
- hypothesis 预注册和 artifact-bound submission；
- global、family、hypothesis lineage、artifact root 四层并发安全信息预算；
- 只返回固定聚合指标和 pass/fail 的隔离 evaluator；
- 成功、失败、duplicate、budget reject 和 infrastructure refund 的 durable audit。

“sealed”在这里不表示同主机管理员不可读取。当前本地实现能抵抗常规调用方误读、公共 API 泄漏、
非授权覆写、改名绕过的正常流程和事后静默篡改；相同 Unix UID、root、调试器或直接磁盘访问仍可读取
临时 evaluator input 或修改文件后造成系统 fail-closed。真正的组织隔离需要独立 UID/容器、远端对象锁、
独立密钥或独立评审服务，本阶段没有声称完成这些外部能力。

已经公开或被研究人员看过的 2024–2026 历史不会因为复制到该目录而重新变成 unseen。Phase 3 store 只
接受未来预注册证据；旧 holdout 的访问历史继续由原有 ledger 管理。

## 2. 权威文件

- 配置：`config/sealed_evaluator.yaml`
- store/governance/controller：`core/research/sealed_evidence.py`
- 隔离 worker：`core/research/sealed_worker.py`
- CLI：`scripts/sealed_evidence.py`
- hypothesis registry：`research/registries/hypothesis_registry.json`
- submission 目录：`research/submissions/`
- summary result 目录：`research/sealed_results/`
- operational raw/store DB：`data/sealed_evidence/`（git ignored）

配置固定为 `mode=PAPER`、`live_enabled=false`。sealed evaluator 不接触 broker、LIVE 或付费云资源。
当前 allowlist 的 benchmark policy 为 `spy_total_return_after_costs_v1`；QQQ 不再具有 gate 权限。

## 3. Append-only store

每个 batch 包含：

```text
batch_id / sequence / source
event_time / available_time / received_time
data_schema / row_count / quality_flags
revision_of / content_sha256
previous_record_sha256 / record_sha256
rows
```

时间必须 timezone-aware 且满足 event ≤ available ≤ received。batch id 和 schema id 只能使用受限安全字符；
绝对路径、`..`、symlink、异常 journal 文件、重复 JSON key、NaN/Inf、超大 batch 或超行数都会失败。

append 在本地 advisory lock 内完成：先完整复核现有 chain，再在目标目录创建临时文件、flush、fsync、
chmod 0400，最后用 hard link 创建不可覆盖的最终文件并 fsync 目录。进程若在 link 后崩溃，该 record 已是
完整 chain 记录；不会出现“文件被覆盖一半”。

同 batch id 只有所有内容、三类时间、source、schema、quality flags 和 revision parent 完全相同时才返回
`reused=true`。revision 必须引用 chain 中更早存在的 batch；它新增记录，不替换旧记录。

公共 `verify_chain`/`metadata` 只返回 batch metadata 和 hash，不返回 rows，也不返回直接文件路径。

## 4. Hypothesis preregistration

tracked registry 已 hash 冻结一项未来候选边界：

```text
hypothesis_id: spy_defensive_vol_target_v1
family_id: defensive_allocation
lineage_id: spy_defensive_vol_target
eligible_data_start: 2026-07-21
evidence_origin: FUTURE_UNSEEN
```

这是经济假设和证据起点的预注册，不是策略参数、回测通过、PAPER 批准或第二策略。它只允许未来研究在
独立证据足够时沿该 lineage 提交；不授权读取旧 holdout 调参。

registry 自身有 per-record SHA256 和 root SHA256。CLI 启动时验证并导入 operational governance DB。
同 hypothesis id 内容变化失败；同 lineage 的 alias 共享预算且不能换 family。系统不能从自然语言中可靠
判断蓄意换措辞的全新 alias，因此 lineage 声明、tracked Git history 和独立评审仍是必要治理层。

## 5. Submission 与 artifact binding

submission 是 immutable mapping：

```text
submission_id / hypothesis_id
artifact_path / artifact_id / artifact_version / artifact_root_sha256
sealed_batch_id
metric_policy_id / benchmark_policy_id / cost_policy_id
```

artifact path 必须 repo-relative、不能 traversal。当前 runtime submission 必须引用治理绑定的 observation
artifact，而非历史 `v1.json`。evaluation 前重新验证传递 artifact 根 hash、全部 component、
策略/version 和精确 Python/package 环境。artifact root 是预算维度，因此仅改 strategy/version 名字不能获得
新额度。

hypothesis 注册时间必须早于 batch event，batch event date 不能早于 `eligible_data_start`。违规 submission
的 evaluator attempt 已经消耗预算，不能靠异常请求免费查看边界反馈。

## 6. 信息预算

当前冻结 policy：

| 维度 | 最大 counted attempts |
|---|---:|
| global | 20 |
| family | 8 |
| hypothesis lineage | 4 |
| artifact root/version | 2 |

SQLite `BEGIN IMMEDIATE` 在一个事务内检查四层计数并预留 attempt，防止并发超额。`RESERVED` 即计数；
进程崩溃留下的 reservation 继续计数，默认 fail-closed。

成功、指标失败、artifact/data/policy 失败和重复 evaluation 都计数。重复 submission 会返回第一次的固定
summary，但先消耗新 attempt 并写 `DUPLICATE` audit。只有 controller 明确识别为 worker timeout 或 OS
launch/I/O 基础设施故障时，状态才是 `INFRASTRUCTURE_FAILED` 且 `counted=0`；refund 本身进入 audit。
普通异常不能由调用方自行标成基础设施故障。

budget policy、metric thresholds、allowlisted benchmark/cost policy 和 worker source hash 都在首次运行时
冻结。看到结果后修改任一项会使同一 governance DB 初始化失败，必须建立新隔离版本并接受独立审核。

## 7. Evaluator 边界

当前固定输入 schema 是 `sealed_artifact_returns_v1`。每行只允许：

```text
session
artifact_root_sha256
strategy_return
benchmark_return
```

这是由受信任、artifact-bound 的上游 runner 生成的 sealed return block；evaluator 不接受任意查询表达式、
Python 代码路径、列名或用户函数。每行 artifact root 必须与 submission 一致，session 必须唯一且严格递增，
收益必须有限且大于 -100%。quality-flagged batch 拒绝评估。

controller 把单个 block 写入 mode 0400 的临时目录，用当前冻结 Python 加 `-I` 启动 worker；环境仅保留
`PYTHONHASHSEED`、locale，不继承 token、broker key 或调用进程 secret。worker stdout/stderr 不作为结果，
只允许受大小限制的固定 JSON output。

返回 schema 只有：session count、total/annualized return、annualized volatility、max drawdown、Sharpe、
beta、固定 gates 和 pass/fail，再加 artifact/batch/policy hash provenance。没有 rows、逐日收益、session 日期、
任意中间统计或文件路径。结果以不可覆盖 JSON 保存到 `research/sealed_results/<submission>/<attempt>.json`。

需要强调：当前仓库尚无真实 future return block。上游 data/forward runner 还必须以同一 artifact root 生成
可信 batch；测试中的 synthetic rows 只证明隔离、预算和统计边界，不是策略证据。

## 8. CLI

状态（不返回 raw）：

```bash
.venv/bin/python scripts/sealed_evidence.py status
```

预注册、submission 和 append 分别使用固定 JSON request：

```bash
.venv/bin/python scripts/sealed_evidence.py preregister --request request.json
.venv/bin/python scripts/sealed_evidence.py submit --request submission.json
.venv/bin/python scripts/sealed_evidence.py append --request batch.json
.venv/bin/python scripts/sealed_evidence.py evaluate --submission-id submission-1
```

append 是受信任数据导入操作，不应开放给普通研究进程。正常研究调用方只提交已注册 ID 并接收 summary。

## 9. 已验证反例

- path traversal、root/journal symlink、unexpected file、duplicate JSON key；
- batch ID conflict、missing revision parent、record/content/previous hash tamper；
- 8 个并发 append 仍形成连续唯一 chain；
- prereg/submission conflict 和 family-lineage drift；
- alias 共享 lineage budget、artifact rename 共享 root budget；
- 6 个并发 attempt 不能突破 global limit；
- evaluation failure 计数、timeout 自动 audit/refund；
- evaluator policy/worker/metric drift；
- artifact root mismatch、row schema/顺序/finite 失败；
- duplicate evaluation 消耗预算但不新增 result；
- subprocess 环境 secret 和 raw/session rows 不出现在 summary/result/audit。

## 10. 当前真实状态

```text
sealed_batches: 0
hypotheses: 1（仅未来经济假设边界）
submissions: 0
counted_attempts: 0
sealed_results: 0
```

因此没有新的 alpha 结论，也没有第二策略晋升。正常第二策略仍需至少 252 个严格晚于 2026-07-17、且
在预注册后产生的独立 unseen sessions，或用户另行批准不相交 point-in-time 数据协议。
