# 云端迁移计划

## 推荐拓扑

```text
scheduler / control plane
          |
strategy worker ---- market/options data adapters
          |
order manager ---- broker adapter
          |
PostgreSQL (orders/state/events) + object storage (bars/artifacts)
          |
metrics/logs/alerts + daily reports
```

第一阶段单实例主动运行，数据库和对象存储持久化；通过 leader lease 防双活下单。只有
完成幂等和 failover drill 后才考虑 active/standby，不做双 active Broker submitter。

## 迁移顺序

1. 消除本地绝对路径，所有路径/时区/供应商通过配置和依赖注入。
2. 容器化 worker/CLI；镜像固定 Python 和依赖 constraints。
3. 引入 migration-managed PostgreSQL，SQLite 保持本地 adapter。
4. bars/research artifacts 迁到 versioned object storage。
5. secret 进入云 Secret Manager，短期凭据和最小权限；不进镜像/日志。
6. durable scheduler/queue 驱动幂等 jobs；使用分布式 lease。
7. 接 metrics/log/trace、alerts、dashboard 和 paging。
8. IaC 创建网络、DB、storage、service account、backup 和 monitoring；不自动创建或
   授权真实 Broker 账户。

## 网络与安全

- Broker/data egress allow-list、固定 egress IP（供应商需要时）、TLS、最小 IAM；
- private DB、加密 at rest/in transit、审计 secret access；
- 禁止将 Prompt、日志或错误堆栈中的账户/secret 发往 LLM；
- production config 与 research config 分账户/namespace/权限。

## 高可用与恢复

- PostgreSQL PITR + 每日恢复演练；对象存储 versioning/retention；
- worker 无本地唯一状态，重启从 order/event store 和 Broker reconcile 恢复；
- deployment 使用 canary/blue-green，但任何时刻只有一个拥有 submit lease；
- rollback 回滚代码，不回滚已发生的 Broker 事件；新版本必须能读旧事件 schema。

## Observability

必须监控 data age/quality、regime/confidence、enabled strategies、risk budget、orders by
state、UNKNOWN age、fills、reconcile diff、PnL/drawdown、kill switches、LLM decisions、
job lag、DB/queue/broker health。关键告警：stale data、unknown order、reconcile mismatch、
daily loss、kill halt、duplicate idempotency conflict、clock drift。

## 成本控制

先用单 worker + managed small PostgreSQL + lifecycle object storage；研究批任务与 paper
runtime 分离，GPU 和大规模 backtest 按需启动；设置预算告警和 artifact retention。

## 明确不做

当前不在未知云账户部署、不写入真实 secret、不打开公网 DB、不自动启用 LIVE、不把
高可用等同于多实例同时下单。
