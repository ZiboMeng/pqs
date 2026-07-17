# 差距分析

## 总览

| 目标 | 当前 | 差距 | 优先级 |
|---|---|---|---|
| Live 默认关闭 | 无真实 live，但 paper CLI 名为 live | 强类型 mode + live gate + approval | P0 |
| 独立风险最终否决 | 权重 cap + CLI kill switch | 统一 pre-trade RiskEngine | P0 |
| 幂等订单状态机 | bar/fill existence 检查 | durable order IDs/transitions/reconcile | P0 |
| 陈旧数据禁止开仓 | VIX 局部 strict | session-aware freshness/quote gate | P0 |
| Broker 异常 fail closed | warning + local simulator truth | broker truth + UNKNOWN quarantine | P0 |
| 正确 options NAV | credit 被重复计入 | 修会计并重算历史证据 | P1 |
| Defined-risk options execution | 合成 spread 数学 | chain/quotes/legs/assignment/fills | P1/P2 |
| Required regime + confidence | 6 态规则 | 8 态、UNKNOWN、confidence/hysteresis | P1 |
| 统一 UTC/PIT 数据 | tz-naive frames | event/available/received time contract | P1 |
| 全候选统一 OOS 门 | 多套研究入口 | versioned evidence/promotion contract | P1 |
| restart/reconcile tests | 部分 bar checkpoint | order/fill transaction + fault injection | P1 |
| static quality | tests 较多 | ruff 1,236 / mypy 127 | P2 |
| reproducible build | dependency lower bounds | constraints/lock + CI matrix | P2 |
| observability | logs/reports/notify | health/metrics/alerts/audit journal | P2 |
| local one-command | run_all.sh only | Makefile + isolated safe commands | P3 |
| cloud ready | none | container/IaC skeleton/runbook/DR | P3 |

## 复用与新增边界

应复用：BarStore/price_access、现有策略、PortfolioConstructor、CostModel、
ExecutionSimulator 的价格/成本算法、temporal split/CPCV/forward governance、SQLite
paper 数据和报告逻辑。

应新增：runtime mode、Clock、freshness gate、RiskEngine、order domain/state machine、
repositories/event store、durable PaperBroker、reconciler、health/metrics/control plane。

应隔离：旧 `run_paper --mode live` 作为 paper session，不允许其名称传播到真实 Broker；
options synthetic research 与 future executable options engine 必须以 evidence class 区分。

## 外部依赖

本地可完成接口、mock、paper、测试、容器和部署骨架。以下只有在启用对应能力时才是
外部 blocker：真实 Broker 凭据和账户权限、商业 PIT options chain、云账户、真实资金
参数与合规/税务决定。
