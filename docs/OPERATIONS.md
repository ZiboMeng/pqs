# 本地运维与 Runbook

## 当前安全状态

真实 LIVE 不可用。`scripts/run_paper.py --mode live` 是旧命名的内部 PAPER 当日执行，
并由 runtime 双钥匙边界固定为 PAPER。仓库配置 `runtime.live_enabled: false`；不得向该
入口接入真实 Broker。

## 基线检查

```bash
.venv/bin/python -m core.config.loader --validate
.venv/bin/pytest -q
.venv/bin/ruff check core scripts tests
.venv/bin/mypy core
.venv/bin/python scripts/run_backtest.py --help
.venv/bin/python scripts/run_paper.py --help
.venv/bin/python scripts/health_check.py --config-dir config
.venv/bin/pip-audit --progress-spinner off
```

全仓历史 ruff/mypy 仍有存量债务；CI 当前强制 fatal Ruff、`core/trading`、
`core/runtime` 和完整 pytest。不得把已记录的非 fatal 历史债务误报为新回归。

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

旧 KillSwitch 与新持久 pause control 均只供内部 paper。暂停示例：

```bash
.venv/bin/python scripts/trading_control.py pause \
  --scope GLOBAL --reason "reconciliation mismatch" --operator "oncall-name"
.venv/bin/python scripts/trading_control.py status
.venv/bin/python scripts/trading_control.py resume \
  --scope GLOBAL --reason "broker ledger reconciled" --operator "reviewer-name"
```

`STRATEGY --key paper-runtime` 和 `SYMBOL --key SPY` 提供更窄作用域。解除必须记录操作者、
时间和原因；CLI/SQLite event table 自动保留版本化事件。UNKNOWN order 未完成人工对账前，
新订单仍会被 risk veto。

## Backup/restore

备份对象包括 config fingerprint、order/event/state DB、paper/forward manifests、报告和
migration version。恢复后先只读启动，执行 Broker reconciliation 和事件重放校验，再
开放 PAPER 新订单。
