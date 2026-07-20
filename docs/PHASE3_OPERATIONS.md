# Phase 3 PAPER 运维手册

日期：2026-07-20

## 1. 每次启动前

1. 确认分支/部署版本和 `git status`，不得在有未知策略组件 drift 时启动。
2. 运行 `.venv/bin/python scripts/freeze_phase3_strategy.py verify`。
3. 运行 `.venv/bin/python scripts/sealed_evidence.py status` 和
   `.venv/bin/python scripts/collect_phase3_data.py status`。
4. 运行 `.venv/bin/python scripts/phase3_control.py evaluate-alerts`，再运行 `readiness`。
5. 若 readiness 不是 `READY`，停止；不能用 resume 绕过 failed gates。

当前正式 forward state/broker DB 尚未初始化，且 collector trusted record 尚未绑定到 runtime 实际消费的
价格，所以第 4 步预期为 `NOT_READY`。初始化数据库不能消除 `trusted_source_batch_bound`；不得手工建表、
编辑配置或填入任意 hash 伪造 READY。

## 2. 日常运行

Forward 事件严格按 `FORWARD_PAPER.md`：T close decision、T+1 open execution、T+1 EOD finalize。scheduler
必须持有单实例 lease；每个外部市场事件使用唯一 event ID、source batch hash 和真实 available/received time。
在 source-binding bridge 实现并认证前，`run-once` 会在创建 state 之前失败；不得把直接 runtime 测试或
历史 replay 作为绕过入口。
运行单阶段前后均保存：

```bash
.venv/bin/python scripts/run_forward_paper.py status
.venv/bin/python scripts/phase3_control.py status
.venv/bin/python scripts/phase3_control.py evaluate-alerts
```

不要把 replay 计入 FORWARD_PAPER session，不要补写未来 available time，不要手工编辑 decision/event/order/NAV
表。日内和期权 collection 仍为 collect-only，不能接入策略。

## 3. 事故处理顺序

对 UNKNOWN、duplicate、stale data/snapshot、artifact drift、DB error、reconciliation、NAV/risk/drawdown 或 LIVE
异常：

1. 用唯一 request ID 立即 GLOBAL pause；
2. 保存 control-plane status、相关 alert ID、event ID 和 deployment version；
3. 不重试可能已提交的订单，不删除 PENDING/UNKNOWN 记录；
4. 修复外部原因或恢复数据/DB；
5. 执行带确认的 reconcile；
6. 重新 verify artifact、DB quick check、evaluate alerts 和 readiness；
7. 对已调查 alert 先 ack，确认条件消失后 resolve；
8. 仅当 resume blockers 为空时，用新的 request ID resume。

对账失败会自动 pause。告警 resolve、对账通过和进程重启都不会自动 resume。

## 4. 崩溃与重启

- close 决策已落库：相同 event ID/content 重试返回已有结果；不同内容冲突。
- broker fill 后 ledger 前崩溃：保持 pause/UNKNOWN，先 broker-authoritative reconcile，禁止盲重发。
- EOD DB commit 后 report 前崩溃：相同 event 重试补 report，不重复 NAV。
- lease 过期：旧 fencing writer 不得 commit；新 owner 取得更高 token 后再恢复。
- operator request PENDING：保存现场，检查 control/reconcile audit，不用相同 ID 改内容。

## 5. 数据库与备份

在进程停止且无 active lease 时备份整个 writable state volume，而不是只复制主 `.db`；SQLite WAL 模式必须
包含一致 checkpoint 或使用 SQLite backup API。至少包含 forward state、simulated broker、alerts、collection、
sealed governance/batches 和 reports。备份后在隔离目录执行：

- `PRAGMA quick_check`；
- artifact verify；
- collection/sealed chain verify；
- control-plane status；
- 只读 reconcile。

本地 volume 示例：

```bash
.venv/bin/python scripts/phase3_backup.py backup \
  --source data/paper_trading/phase3_forward/dual_index_growth_v1 \
  --destination /safe/off-volume/pqs-state-YYYYMMDD
.venv/bin/python scripts/phase3_backup.py verify \
  --backup /safe/off-volume/pqs-state-YYYYMMDD
```

restore 只允许不存在的新目录，并要求 `--confirm RESTORE:<manifest_sha256>`；先在隔离目录完成全部验证，
再由人工切换 volume。不要把 backup 放在 source 里面，也不要把同一磁盘目录称作灾备。

恢复必须先 GLOBAL pause，以新目录启动并验证，再原子切换显式 volume。不得用空 DB 覆盖旧 DB，不得删除
quarantine、alert、operator request 或 lease audit 来“恢复绿色”。R7 会提供本地备份/恢复脚本和容器卷 smoke。

## 6. 关闭与回滚

优雅关闭先停止新 schedule，等待当前事务结束，释放 lease，再停止进程。若必须回滚代码，回到
`codex-pre-forward-paper-phase3-20260720` 只代表回到 Phase 3 接管前代码；Phase 3 新 DB schema/状态需隔离保存，
不能让旧代码直接覆盖。回滚前后都记录 deployment version、artifact root、DB quick check 和 reconciliation。

## 7. 明确禁止

- 不设置或读取真实 broker 写凭据；
- 不创建付费云资源；
- 不提供 LIVE toggle；
- 不修改冻结 artifact hash 来消除 drift；
- 不用 resume 绕过 critical alert/reconcile/risk gate；
- 不把合成 collection fixture、空 alert sink 或本地 process smoke 写成真实市场运行证据。
