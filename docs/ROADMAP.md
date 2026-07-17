# 实施路线

## P0 — 执行安全

1. 引入 `BACKTEST/PAPER/LIVE` runtime mode，paper 默认，live 双重显式授权且无默认值。
2. 建立 session-aware data freshness/quote quality gate，新增风险前 fail closed。
3. 建立 order domain + 显式状态机 + durable idempotency repository。
4. 建立独立 RiskEngine 和 pre-trade validator，统一所有 Broker 提交入口。
5. 将 PaperBroker 变成执行真源，支持 ACK/reject/partial fill/timeout/UNKNOWN。
6. 建立 position/order reconciliation；mismatch 或 unknown 自动隔离新增风险。
7. 建立 global/strategy/symbol kill switches 和结构化 audit event。

## P1 — 研究与会计正确性

1. 修复 options NAV credit double-count，增加会计不变量与历史 artifact invalidation。
2. options paper 状态改为原子事务/锁/事件幂等。
3. 统一 UTC Clock、NYSE calendar、event/available/received time。
4. 强化 regime 为 required taxonomy + confidence + UNKNOWN + hysteresis。
5. 建立 versioned promotion evidence contract，统一 OOS/walk-forward/DSR/PBO/成本证据。
6. 补齐 portfolio accounting、cash interest 和 failure injection/restart 测试。

## P2 — 多策略与期权框架

1. 实现 strategy registry/policy mapping 与组合级 risk budget。
2. 完成 stable base、SPY/QQQ risk-on、受限 TQQQ growth、risk-off 资产政策。
3. 建立 OptionsContract/Quote/Chain/Position/Greeks 数据模型和 provider contract。
4. 实现 defined-risk vertical/iron-condor 的真实 quote-aware paper execution、assignment/
   expiry 和 multi-leg recovery；无商业数据时使用明确标记 synthetic fixture。
5. 完成 fleet drawdown throttle/role cap/observe。
6. 分批收敛 ruff/mypy，先零 F/E 类错误，再收紧格式/命名。

## P3 — 本地生产化与云准备

1. Makefile：setup/test/lint/typecheck/backtest/paper/report。
2. Docker/Compose、数据库 migration、health/readiness/liveness、metrics/alerts。
3. CI、dependency constraints、secret scanning、artifact retention。
4. Operations runbook、backup/restore drill、cloud/IaC skeleton。

每个阶段以小 commit 完成：实现 → focused tests → full regression → docs/progress → push。
