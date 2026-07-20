# Phase 3 控制面与告警

日期：2026-07-20

## 1. 接口边界

权威入口是 `scripts/phase3_control.py`。它只有 status/readiness、PAPER pause/resume/reconcile、alert evaluate/list/
ack/resolve；不存在 LIVE toggle。`status` 和 `readiness` 使用 SQLite `mode=ro + query_only`，不会初始化 runtime
DB、取得 lease、改变订单或创建控制记录。状态输出包括：

- service 与 deployment version；
- artifact 根 hash、registry 状态及所有 LIVE/broker-write flags；
- scheduler lease/fencing 和最新 event cursor；
- regime/confidence、approved targets、kill-switch state；
- cash、equity、positions、orders、daily PnL、drawdown；
- risk budget、最新 reconciliation；
- collection/sealed 状态和计数；
- durable alerts 及其冻结 policy hash；
- PAPER readiness gates，以及恒为 false 的 `ready_for_live`。

`status` 返回成功只表示快照成功生成；是否可处理 PAPER 事件必须看 `readiness.status`。当前正式状态为
`NOT_READY`：artifact/registries/sealed/collection/alerts 正常，但 trusted source batch 尚未绑定，且 forward state 与 simulated broker DB 尚未由真实
forward lifecycle 初始化。它不表示部署或实盘就绪。

```bash
.venv/bin/python scripts/phase3_control.py status
.venv/bin/python scripts/phase3_control.py readiness
```

## 2. 写操作确认与幂等

所有人工写操作必须同时提供 actor、reason、request ID，以及和 request ID 精确绑定的确认文本：

```bash
.venv/bin/python scripts/phase3_control.py pause \
  --scope GLOBAL --request-id incident-20260720-001 \
  --actor oncall-name --reason "broker reconciliation investigation" \
  --confirm YES:incident-20260720-001
```

GLOBAL 的 key 固定为 `*`；STRATEGY/SYMBOL 还要求 `--key`。同 request ID、相同内容重试返回 `reused=true`，
不会增加 control version；同 ID 不同内容失败。Phase 3 的 request ledger 和 control update 在同一 SQLite
transaction 中完成，同时保留旧 `trading_control_events` 审计链。该封装位于新 operations 模块，没有修改
已冻结的 `core/trading/controls.py`；冻结策略 artifact 根仍为
`7d1c2d96ea06f051f298331a6a9a8a5bc6e0b85af72fd158e8524cc56b0a553c`。

resume 不是 pause 的无条件反操作。除 `global_not_paused` 外，artifact、registry、runtime/broker DB、account、
reconcile、critical alerts、sealed、collection 和 LIVE gates 必须全部通过；否则即使确认正确也拒绝 resume。
恢复前应先消除原因、执行 reconcile、处理 alerts，再使用新的 request ID。

## 3. 对账操作

`reconcile` 只读比较 forward ledger 与持久 simulated broker 的 cash、positions 和双向 open-order identity，不提交
或撤销订单：

```bash
.venv/bin/python scripts/phase3_control.py reconcile \
  --request-id reconcile-20260720-001 --actor oncall-name \
  --reason "post-restart authority check" \
  --confirm YES:reconcile-20260720-001
```

request 会先写 `PENDING`，成功后以固定 result 变为 `COMPLETE`；相同完成请求幂等返回。对账失败自动通过派生
request ID 设 GLOBAL pause，但永不自动 resume。PENDING/FAILED 的不确定请求不会用新内容覆盖，应按 runbook
检查 DB 和 control events 后使用新 request ID。真实 broker 写 API 在本阶段不存在。

## 4. Durable alerts

`config/alerts.yaml` 定义 16 个强制 rule、severity 和阈值；完整 policy 以 canonical SHA-256 在第一次使用时写入
`alerts.db`，以后配置漂移会 fail closed。规则覆盖 missed schedule、data stale/missing/out-of-order、artifact
drift、stale broker snapshot、UNKNOWN/duplicate order、reconciliation、NAV/risk、daily loss/drawdown、DB、
registry 和 LIVE true。

告警先持久化到本地 SQLite，之后才允许可选 notification adapter fan-out。当前没有外部通知凭据，也未配置
邮件/Slack/PagerDuty；这不会丢失本地事件。相同 `rule_id + dedup_key` 在 resolve 前只保留一个 active instance，
增加 occurrence；resolve 后再次出现会产生新 generation。并发测试验证 16 次同时 emit 只得到一个 active alert
和 16 个 occurrence。

```bash
.venv/bin/python scripts/phase3_control.py evaluate-alerts
.venv/bin/python scripts/phase3_control.py alerts

.venv/bin/python scripts/phase3_control.py ack-alert \
  --alert-id <id> --request-id ack-001 --actor oncall-name \
  --reason "investigating" --confirm YES:ack-001

.venv/bin/python scripts/phase3_control.py resolve-alert \
  --alert-id <id> --request-id resolve-001 --actor oncall-name \
  --reason "root cause removed and readiness green" --confirm YES:resolve-001
```

自动 monitor 可用固定 signal schema 调用 evaluate；`--signals` 只用于受控测试/monitor adapter，并拒绝未知字段。
ack 只表示有人接手，不解除条件、不 resume。resolve 需要原因，也不自动 resume。

## 5. Health 与 readiness

`scripts/health_check.py` 保留为进程/基础 config/SQLite liveness 检查。`phase3_control.py readiness` 是更严格
的可处理 PAPER 事件检查。任意 config 或 registry 出现 LIVE true，readiness 必失败，并生成 `live_true`
critical alert；输出仍然写明 `ready_for_live=false`。Phase 3 没有任何普通命令能改变这一点。

本地同 UID 或 root 可以直接修改 SQLite/文件，这是本地部署的权限边界，不是远端强隔离。R7 会用非 root、
只读 root filesystem 和显式持久卷缩小边界；不能把它描述为防 root 篡改。
