# 风险政策

## 权限层级

RiskEngine 独立于策略，对所有订单拥有最终否决权。策略、LLM、allocator、operator CLI
都不能绕过。Risk evaluation 和 reason codes 必须先于 Broker side effect 持久化。

## 默认运行政策

- 默认 `PAPER`；`LIVE` 关闭。
- 缺数据、数据陈旧、报价异常、Broker 不健康、订单 UNKNOWN、reconciliation mismatch、
  配置无效或风险计算不完整时 fail closed。
- UNKNOWN regime 降低风险并禁止杠杆 ETF/新增 short-vol exposure。
- 裸卖期权、无上限亏损、0DTE、martingale、亏损后无限加仓禁止。

## Pre-trade 检查

至少覆盖：

- global/strategy/symbol kill switch；
- client order/idempotency/decision lineage 完整；
- finite positive price/quantity、side/asset/market session 合法；
- max order notional、cash/buying power、gross/net exposure、max leverage；
- symbol/strategy/sector/ETF overlap concentration；
- daily loss、rolling drawdown、trade count/cooldown；
- data/quote freshness、spread、volume/OI、price deviation；
- TQQQ/SOXL 独立 cap 与允许 regime；
- options defined-risk、max loss、Greeks、expiry concentration、short gamma/tail stress；
- corporate event/earnings/expiration/assignment risk；
- existing open/unknown orders 的聚合风险。

## Kill switch

必须有 global、strategy、symbol 三层；触发/恢复均写 audit event。HALT 默认只能人工恢复；
自动恢复只允许从低等级状态逐级恢复，且需要连续健康期。kill switch 持久化，不因重启
回到 NORMAL。

## Reconciliation

每次启动、每次 Broker reconnect、每批 fill 后和 EOD 执行。差异超过容差时：记录
expected/actual/diff，进入 `RECONCILIATION_REQUIRED`，禁止新增风险，不自动用本地状态
覆盖 Broker。

## Options

组合最大亏损必须在 quote/cost 后重新计算。Broker 支持原子 combo 时优先 combo；不支持
时默认拒绝自动 legging，除非显式策略定义最大 legging exposure、超时、撤单和补救。
assignment/exercise/expiration 必须形成可重放事件并更新 cash、underlying 和 option legs。

## Live 上线人工门

上线前必须完成 Broker credentials、账户权限、商业数据许可、最终风险参数、合规/税务
决定、小额 canary、kill/reconcile drill、backup/restore 和告警演练。任何示例配置都不能
替代这些批准。
