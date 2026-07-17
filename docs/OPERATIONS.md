# 本地运维与 Runbook

## 当前安全状态

真实 LIVE 不可用。`scripts/run_paper.py --mode live` 是旧命名的内部 PAPER 当日执行。
在新的 runtime gate 完成前，不应向该入口接入真实 Broker。

## 基线检查

```bash
.venv/bin/python -m core.config.loader --validate
.venv/bin/pytest -q
.venv/bin/ruff check core scripts tests
.venv/bin/mypy core
.venv/bin/python scripts/run_backtest.py --help
.venv/bin/python scripts/run_paper.py --help
```

当前审计时 ruff/mypy 预期失败，详 `AUDIT.md`；不得把历史失败误报为新回归。

## Paper 启动前检查

1. 确认 mode 为 PAPER、live gate 为 false。
2. 校验配置和 production strategy fingerprint。
3. 校验最新完成的 NYSE session 与行情 event time/received time。
4. 校验 VIX、SPY、所有拟交易 symbol 和 options quote 新鲜度/质量。
5. 查询 kill switches、open/UNKNOWN orders、Broker health。
6. reconcile cash/positions/open orders。
7. 输出风险上限和启用策略摘要后才允许循环运行。

## 故障响应

| 故障 | 自动动作 | 人工动作 |
|---|---|---|
| stale/missing data | 禁止新增风险 | 修复 feed，验证时间和来源 |
| Broker timeout | 订单置 UNKNOWN，不重提 | 用 client_order_id 查询/对账 |
| reconcile mismatch | global risk halt | 核对 Broker statement 与 event log |
| duplicate callback | event ID 幂等忽略 | 检查 adapter 序列号 |
| partial fill | 更新已成交风险，管理剩余单 | 按 policy 撤单/继续/补救 |
| DB unavailable/corrupt | 停止提交 | 恢复备份，Broker 真源重建 |
| daily loss/drawdown halt | 停止新增风险 | 审核后人工恢复 |
| clock/session mismatch | 停止提交 | 校时并验证交易日历 |

## Kill switch 操作原则

当前旧 KillSwitch 仅供 paper；新 control-plane CLI 落地前，不提供可能被误解为 production
的解除命令。解除 HALT 必须记录操作者、时间、原因、旧/新状态和 evidence link。

## Backup/restore

备份对象包括 config fingerprint、order/event/state DB、paper/forward manifests、报告和
migration version。恢复后先只读启动，执行 Broker reconciliation 和事件重放校验，再
开放 PAPER 新订单。
