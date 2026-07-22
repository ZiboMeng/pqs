# PQS 隔离 Short PAPER Research Lane PRD

日期：2026-07-21

版本：1.0

状态：IMPLEMENTED MINIMUM CORRECT ACCOUNTING；真实 broker/borrow collector 未接入

## 1. 决策与边界

建立独立的 `SHORT_RESEARCH_ONLY` lane，目的是验证同一 cross-sectional score 的 bottom bucket
能否提供可交易 alpha，以及 short overlay 能否改善冻结 core。它不修改现有 long-only production、
backtest、PAPER、risk schema、allocator、broker adapter 或 reconciliation。

本 PRD 不授权 LIVE，不授权发送 broker short order，不允许用 inverse ETF 代替长期 short，也不允许在缺少
point-in-time borrow 数据时把历史模拟写成 `PAPER_PASS`。

证据等级：

- `SYNTHETIC_SHORT_RESEARCH`：保守假设 fee/recall/locate，只能研究机制；
- `RESEARCH_INCOMPLETE`：没有完整 broker PIT borrow batch；不能计入正式冻结候选；
- `FROZEN_SHORT_PAPER_CANDIDATE`：score/construction/accounting 已冻结，等待未来同日起 observation；
- `SHORT_PAPER_EVIDENCE_ELIGIBLE`：每次 decision/order/accrual 都绑定当时已可获得的 broker borrow batch；
- `FORWARD_EVIDENCE`：冻结后逐 session 累积，仍需统计、风险与组合 SPY gate；
- `PROMOTION_PASS`：沿用正式 promotion，且仍需人工/既有流程；本模块本身无权生成。

## 2. 为什么不能直接打开现有 T2 开关

现有 production path 在 schema、allocator、target quantity、sell 数量和 reconciliation 多层拒绝负仓位。这是
正确隔离，不是待删除障碍。原 `LongShortConfig` 只有研究配置字段，没有 restricted proceeds、signed NAV、
借券、保证金、股息代付、召回或强平语义。把负权重塞入现有 engine 会生成错误账户。

新入口固定为 `core/research/short_paper/`。production/runtime 不得 import 此包；未来 broker adapter 也必须在
显式授权后单独实现。

## 3. 借券数据契约

每个 symbol、每个 observation batch 至少保存：

- `observed_at_utc` 与 `available_at_utc`；
- `shortable`、`available_quantity`、`annual_borrow_fee`、proceeds rebate；
- ETB/HTB、locate id/expiry、recall/buy-in、source/provider；
- raw response SHA-256、collector commit、batch hash；
- 决策时刻是否已知，禁止日后回填成当时可用。

`BROKER_PIT` 必须有原始 batch hash；`SYNTHETIC_ASSUMPTION` 永远不能自动升级。缺 symbol、缺数量、snapshot
晚于 order、recalled 或 fee 非法均 fail-closed。

## 4. 当前数据源可行性（2026-07-21）

### IBKR

IBKR 当前 API/TWS 可提供 shortable shares（generic tick 236，TWS Build 974+）、当前可借数量和 indicative
fee rate；其 SLB 工具还显示 lenders 数和当天 indicative borrow rate。它适合从未来某一 session 开始定时
冻结 broker PIT batch。公开接口没有证明可以无偏获得本项目 2007–2024 的逐日 availability、quantity、fee、
recall 历史，因此不能拿今天字段回填历史。

官方依据：

- <https://www.interactivebrokers.eu/campus/ibkr-api-page/twsapi-doc/>
- <https://brokerage.ibkr.com/en/trading/short-securities-availability.php?menu=A>

### Alpaca

Assets API 暴露 `shortable`、`easy_to_borrow` 和 maintenance margin requirement；当前文档也描述 ETB/HTB
locate workflow。它可作为未来 PAPER 的可借性旁证或替代 collector，但普通 asset snapshot 不是历史 borrow
quantity/fee/recall 语料。

官方依据：

- <https://github.com/alpacahq/alpaca-docs/blob/master/content/api-references/broker-api/assets.md>
- <https://docs.alpaca.markets/us/docs/margin-and-short-selling>

### 法规/执行

Regulation SHO Rule 201 在证券相对前收盘日内下跌至少 10% 后触发；限制持续触发当日余下时间和下一交易日，
非豁免 short order 不能在当前 NBB 或以下执行。本项目若没有当时 NBBO/price-test 状态，不模拟一个虚构成交，
而是拒绝该 short entry。

官方依据：

- <https://www.sec.gov/files/rules/final/2010/34-61595-secg.htm>
- <https://www.sec.gov/rules-regulations/staff-guidance/trading-markets-frequently-asked-questions-7>

结论：未来 PIT collection 可行，历史正式 borrow certification 当前不可行。历史 short mining 只能输出
`RESEARCH_INCOMPLETE`；达到 5 个“正式策略”的退出计数时不计算这些 short 结果。

## 5. 账户与成交语义

仓位为 signed quantity：long `>0`、short `<0`。本阶段 short-only account 不接受普通 SELL 冒充开空；动作
只能是 `SHORT_SELL` 或 `BUY_TO_COVER`。

核心等式：

`equity = cash + Σ(signed_quantity × mark)`

开空收到的现金进入 cash，同时同额 short liability 进入 signed market value，所以开空本身不增加 NAV。
`restricted_short_proceeds` 单独限制 buying power，不能再从 NAV 二次扣除。

成交固定使用 next-session open：

- 缺 open 则拒单，不能用 close 伪成交；
- 开空按不利方向向下滑点，回补按不利方向向上滑点；
- 开空前必须有时点正确且数量足够的 locate；
- Rule 201 已触发而无 `price > NBB` 证据时拒单。

## 6. 每日负债和公司行动

每个持仓 session 逐日记：

- `short_market_value × annual_borrow_fee / day_count`；
- restricted proceeds 的明确 rebate；
- 除息日前已持有 short 的 `abs(qty) × cash_distribution` 股息代付；
- split 后数量乘 ratio、entry price 除 ratio，经济敞口不变；fractional cash-in-lieu 缺 broker 证据则拒绝；
- merger/delist/tender 暂无 canonical broker action 时 fail-closed，不用最后 close 猜结算。

## 7. 保证金、召回和强平

- initial margin 默认 50%，entry 后立即检查；
- maintenance/house margin 默认 30%，但未来以 broker batch 较严格值为准；
- recall、buy-in、margin breach、kill switch 使用独立 forced-cover 事件；
- forced cover 仍必须有下一 session open；halt/missing open 保持未解决风险并升级告警；
- short squeeze stress 至少覆盖 2x/5x gap、borrow fee 跳升、availability 归零和全量 recall。

## 8. 持久化、幂等与 reconciliation

- 每个 external event 有唯一 id，重复事件不得二次成交/计费；
- state 使用临时文件、file fsync、atomic replace 和 directory fsync；
- broker reconciliation 比较 signed quantity，`+100` 与 `-100` 不得相互抵消；
- 任一不一致触发 fail-closed，禁止继续生成可晋升证据。

## 9. PAPER 运行方式

formal short PAPER 不从 Yahoo 重建借券。它和 long candidates 从同一未来 session 开始：

1. close decision 前/后按冻结 schedule 抓 broker borrow batch并 hash；
2. score 在 T close 形成；
3. T+1 open 前重新验证 locate、quantity、fee、Rule 201 与 margin；
4. 使用 broker/open batch产生 PAPER fill 或明确 reject；
5. session accrual 记 borrow/rebate/dividend，close mark 并 signed reconcile；
6. 所有 source/action/state hash 进入 append-only manifest；
7. forward 期间不把 short 表现反馈给 miner。

独立虚拟账户包括 short standalone、long standalone、core + short overlay；只有 combined portfolio 使用 SPY
raw outperformance 主门，short standalone 使用 after-cost alpha、beta/sector neutrality、borrow coverage、
recall/squeeze/margin 门。

## 10. 已实现验收反例

`tests/unit/research/test_short_paper_account.py` 已覆盖：

- 开空收入不增加 NAV；价格上涨产生无上限方向损失；
- borrow fee 和 short dividend 扣款；split 前后经济敞口一致；
- locate、quantity、Rule 201、missing-open fail-closed；
- margin breach、recall forced cover、event id 幂等、signed reconciliation 和 atomic save；
- synthetic snapshot 只能得到 `RESEARCH_INCOMPLETE`。

仍未实现且明确阻断真实运行：broker collector/source-batch bridge、NBBO/Rule-201 feed、merger/delist action、
broker-specific margin/interest、真实 recall/buy-in 消费器和 production broker adapter。
