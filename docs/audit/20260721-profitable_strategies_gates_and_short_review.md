# PQS 盈利策略、Gate 与开放 Short 独立复审

日期：2026-07-21

复审对象：原工作区用户提供、未修改的 `docs/audit/20260721-profitable_strategies_and_gates_research.md`

源文件 SHA-256：`ec57efbd4e9abec35b7c948967193fae8a693111d0b8eeb20db3762f1c714ab2`（101,921 bytes）

结论：**方向大体同意，但不能原样作为实施 PRD；存在会改变优先级和 gate 正确性的实质错误。**

## 总结判断

同意报告最核心的诚实判断：在 long-only / no-margin / no-short、净成本后跑赢 SPY 且严格限制回撤的共同约束下，没有文献能替 PQS 证明某个现成策略将稳定晋升；ML 文献中的高 Sharpe 多为 long-short、gross-of-cost，并依赖更宽股票池；trend、dual momentum、low-vol 和 vol-targeting 的主要价值通常是风险塑形，不应自动改名为 alpha。

不同意报告把若干样本期结果写成普遍事实，也不同意把大量相关统计检验全部堆成硬门。正确治理应保留少数正交门：数据/时间正确性、完整 trial ledger、DSR/PBO/CPCV 证据、净成本 SPY 经济门、风险/压力门、一次性 holdout 与 prospective paper。其余检验按候选类型作诊断或二级复核，不能靠“工具越多越严谨”的表象替代可识别的零假设和统计功效。

## 同意并采纳

1. **先打通 qualification evidence，再扩大挖掘。** 当前零自动晋升候选是诚实结果；下一项工程是让 miner 产出候选/commit/data/trial-bound DSR、PBO、MinBTL、CPCV 和 replay artifact。
2. **SPY 是 long-only core alpha 的唯一自动晋升主基准。** QQQ 可作诊断，不得按 strategy type 路由规避 SPY；同时报告 raw after-cost SPY excess、active-return statistics 和 beta-adjusted alpha，三者不可互相冒充。
3. **ML 只能作为信号组合器候选。** Gu–Kelly–Xiu 证明横截面可预测性，不证明 PQS 的大盘、long-only、净成本 top-decile 一定跑赢 SPY；Avramov–Cheng–Metzker 也显示剔除微盘/困境股与加入合理成本会明显削弱表现。
4. **dual momentum/trend/vol-targeting 先按 overlay 研究。** 它们可降低左尾或改善组合路径，但 standalone 跑输 SPY 时不能被自动记录为 core alpha PASS。
5. **完整保留 raw trial count。** `N_eff` 只能作为敏感性估计，不能替换累计 raw N 或删除失败 trial；报告 raw N、多个 N_eff 估计和最保守结论。
6. **holdout/sealed 必须记账。** 已观察区间不能重命名为未见数据；多个 finalist 若共享同一未来窗口，必须事前冻结并做 multiplicity adjustment。

## 必须更正的实质问题

### 1. Cboe PUT 不是仍然成立的“直接跑赢 S&P”证据

报告引用 1986-2008 的旧回测：PUT 年化 10.32% 对 S&P 8.77%。但 Cboe 2026-06 官方 factsheet 显示，自 2007-01-03 起 PUT 年化约 7.0%，S&P 500 Total Return 约 11.0%；PUT 最大回撤约 -32.7%，也超过 PQS 的 25% stress cap。旧窗口只能证明特定 regime 的历史表现，不能支撑“唯二真跑赢”或当前优先落地。

处置：PUT/cash-secured put 降为低-beta、short-volatility 风险塑形候选，不是 SPY-beating alpha；在真实 options 数据与执行会计完成前不进入 promotion。

### 2. “vol-targeting 是数学恒等且不衰减”不成立

波动聚集和股票收益/波动负相关给 vol scaling 提供机制，但收益改进依赖资产、估计窗、杠杆/去杠杆边界、交易成本与反转路径。Harvey 等只在 risk assets/含 risk assets 的组合中发现更强效果；Cederburg 等的实时/OOS 研究发现，volatility management 对多数被测因子缺乏稳健增益，market 组合的实时 Sharpe 反而下降。

处置：vol-targeting 保留为低成本风险 overlay 实验，但必须与 `no scaling` baseline 做 prospective after-cost A/B；不能预登记为“不衰减 edge”。

### 3. GRS 不能按报告所说反转成“reject 就是好事”

GRS 的联合零假设是全部截距为零。拒绝只说明至少一个 alpha 非零；显著负 alpha、正负混合或模型错误都能导致拒绝。它不证明 fleet 的 alpha 为正，也不证明组合优于 SPY。

处置：GRS 只作联合模型诊断；晋升仍要求预注册组合的 after-cost alpha/active return 为正且置信区间满足门槛。不得把 GRS reject 当 hard PASS。

### 4. `E[MDD]` 不是“理论下限”

Brownian maximum drawdown 公式给定模型下的期望/分布性质，不是任一有限样本回撤的下界。观测 MDD 小于期望不能据此判 lookahead。

处置：删除“低于理论下限即泄漏”的 hard gate；保留历史/块 bootstrap drawdown 分布、明确 stress paths 和恢复时间。

### 5. 延迟敏感不是泄漏证明

真实但衰减很快的信号可能在 T+2 大幅下降；慢信号也可能因 overnight gap 与 T+1 open 执行产生显著差异。固定要求 `rho(2)>=0.7` 或 CAGR 差小于 0.2% 没有普适依据。把未来特征故意前移后表现改善，也不等于原实现已经泄漏。

处置：timing correctness 由 available-time lineage、T-close/T+1-open 契约、PIT data、purge/embargo 和针对实际 off-by-one 的 mutation tests 证明；delay curve 只判可实现性和半衰期，不单独判 leakage。

### 6. Gate stack 存在重复惩罚和口径冲突

报告同时强制 DSR、PBO、MinBTL、CPCV、WRC、SPA、StepM、HLZ t>3、haircut Sharpe、Ledoit-Wolf CI 和 GRS，多个检验处理的是相近的 selection/multiple-testing 风险。全部 AND 会在小样本下极度低功效，却不保证输入数据正确。

此外，报告一处要求 CSCV `S=16` 计算 PBO，另一处用 CPCV `N=6,k=2` 的 5 条路径喂 PBO；两套对象和分辨率没有统一。`PSR(SR*=SPY Sharpe)` 也不能替代对成对 active returns 或 regression alpha 的检验。

处置：

- screening：数据/时间 fail-closed、成本、trial ledger、参数邻域；
- freeze：CPCV OOS 分布 + PBO/DSR（定义清楚各自输入）+ net active return；
- family selection：SPA 或 Romano-Wolf 二选一，事前指定；
- promotion：一次性 holdout + prospective paper；
- 其余只作诊断，不重复写成自动 hard gate。

### 7. MinTRL 约束 PASS，不阻止安全性提前 FAIL

统计功效不足时不能宣称 alpha PASS；但发生风险越界、数据泄漏、会计错误、borrow/locate 失败或预注册 sequential-futility 条件时，可以提前 FAIL/STOP。报告“`T<MinTRL` 禁止 PASS/FAIL”过宽。

### 8. options 落地准备度被高估

当前 PQS options 路径仍缺真实链/quote、American exercise、dividend/borrow、assignment、combo fill、partial fill、margin/capital 与可靠恢复状态机，历史 synthetic paper 不能证明真实可成交 P&L。

报告同时把 SPY/XSP 与 wheel 混用；SPY ETF options 实物交割，XSP 是现金结算且到期不会生成 SPY 份额，因此 XSP 不能按“被行权后转 covered call”的经典 wheel 状态机实现。

### 9. “证伪”措辞过满

2022 的 regime failure 足以判 HFEA 不符合当前回撤 mandate，却不构成对所有 leveraged risk-parity 的数学证伪；一篇 sector-cycle 研究或 factor-timing 批判也只应降低先验与优先级，不能证明整个策略族永远无效。

处置：改为 `out_of_current_mandate / low_prior / requires_new_evidence`，避免把经验反例写成普遍定理。

### 10. shareholder yield 是合理候选，不是已确认 HIGH edge

报告自己承认没有独立评估，却把它列为最大遗漏和最高优先。可把 shareholder yield / net issuance 加入低换手 baseline，但必须与 quality/profitability 的相关性、PIT corporate-action/fundamental availability 和净成本共同验证。

## 关于开放 Short 的独立决定

### 决定

**批准独立 `SHORT_RESEARCH_ONLY` PAPER lane；不批准在当前 long-only engine 中切 flag，也不批准 live。**

理由不是“short 一定更赚钱”，而是项目历史已经显示 long-only × top-N × 大盘 universe 存在结构性 sibling/NAV-correlation floor；short 能让研究真正复制 long-short factor spread，并直接检验该约束是否是 alpha 上限。但 short 自身没有正期望保证，且改变账户、资本和尾部风险语义。

### 为什么开放 short 不自动解决“跑赢 SPY”

0.5 long / 0.5 short 的 dollar-neutral book 即使有正 alpha，市场 beta 接近零，在强牛市 raw return 很可能低于 SPY。要把 market-neutral alpha 叠加到 100% SPY 上形成 portable alpha，gross exposure 必然高于 1，并引入 margin/financing/forced-liquidation；这和现有 no-margin mandate 不是同一产品。

因此：long-only core 继续使用 standalone after-cost SPY gate；short research sleeve 用正净 alpha、neutrality 与 borrow feasibility gate；只有冻结权重后的“core + short overlay”组合才使用 after-cost SPY 主门。任何例外必须标为不同 mandate，不能借 diversifier 标签绕过。

### 第一个受控实验

- universe：高流动、大盘、可获得 point-in-time borrow 的美股；排除 microcap、penny stock、hard-to-borrow 与 corporate-action 数据不全者；
- construction：sector-neutral、beta-neutral cross-sectional top-minus-bottom；先测 gross=1.0（0.5 long / 0.5 short），不直接上 1.0/1.0；
- baseline：相同 feature/rank、相同 rebalance/cost 的 long-only top bucket；
- 必算成本：borrow fee/rebate、融资、短仓股息代付、spread/slippage、locate reject、recall/buy-in、Rule 201 约束与税费诊断；
- 压力：单名上跳、停牌、borrow recall、fee spike、crowded squeeze、相关性趋一、开盘 gap 与强制去杠杆；
- 结论范围：没有 point-in-time borrow/locate 数据时只能 `RESEARCH_INCOMPLETE`，不能 promotion。

### 为什么必须另建路径

当前代码在多个层级把 long-only 写成结构契约：risk schema 拒绝 `allow_short=true`；allocator 拒绝负目标；backtest 目标数量被钳到非负且 SELL 不得超过当前多仓；account snapshot/reconciliation 拒绝负持仓。单改配置会得到错误回测/错误账本，而不是 short support。

新路径至少需要 signed-position ledger、restricted short proceeds、gross/net/beta exposure、initial/maintenance/house margin、point-in-time borrow/locate、recall/buy-in、dividend/corporate-action liability、mark-to-market、short-sale price restriction、kill switch 和 broker reconciliation。完成这些之前，现有 long-only 路径保持不变是正确隔离。

## 对当前代码状态的校正

原报告的若干 gate 发现描述的是加固前状态。`codex/governance-and-semantic-strategy-v4` 的 `d065d0b8` 已经：统一自动晋升的 SPY/total-return/after-cost 口径；将 QQQ 降为诊断；移除 Phase 2 硬编码 lookahead attestation；要求 candidate-bound DSR/PBO/MinBTL/CPCV/replay evidence；禁止 force/skip promotion；对 PAPER evidence drift fail-closed。

所以不应重新执行报告行动 #1-#6 并重签旧证据。当前真实缺口是 miner 尚未机械地产出新 qualification artifact，以及 short/options 均没有达到独立可验证执行语义。

## 最终优先级

1. 完成 canonical qualification artifact 与 trial ledger 接线；
2. 在同一证据协议下并行比较 rule/linear/XGB/structured/semantic 候选；
3. 加入 shareholder-yield/quality/profitability/residual-momentum 的低换手 baseline；
4. 同步启动隔离的 short feasibility PRD 与 synthetic/PIT-borrow PAPER research，但不接 production；
5. dual momentum/vol target 仅作为 overlay A/B；
6. options VRP 等真实数据、会计和执行模型后再评；
7. 不重开已消耗 holdout，不因为零候选降低门槛。

## 核验来源

- Cboe PUT factsheet（截至 2026-06）：https://cdn.cboe.com/resources/indices/factsheet/CboeGlobalIndices_PUT-Index.pdf
- Cboe XSP settlement：https://www.cboe.com/tradable_products/sp_500/mini_spx_options/cash_settlement/
- Moreira & Muir, *Volatility-Managed Portfolios*：https://www.nber.org/papers/w22208
- Cederburg et al., *On the performance of volatility-managed portfolios*：https://www.sciencedirect.com/science/article/abs/pii/S0304405X2030132X
- Harvey et al., *The Impact of Volatility Targeting*：https://people.duke.edu/~charvey/Research/Published_Papers/P135_The_impact_of.pdf
- Gu, Kelly & Xiu, *Empirical Asset Pricing via Machine Learning*：https://academic.oup.com/rfs/article/33/5/2223/5758276
- Avramov, Cheng & Metzker, *Machine Learning vs. Economic Restrictions*：https://pubsonline.informs.org/doi/abs/10.1287/mnsc.2022.4449
- Gibbons, Ross & Shanken (1989)：https://ideas.repec.org/a/ecm/emetrp/v57y1989i5p1121-52.html
- SEC Regulation SHO / short-sale requirements：https://www.sec.gov/rules-regulations/staff-guidance/trading-markets-frequently-asked-questions-8
- FINRA Rule 4210 margin requirements：https://www.finra.org/rules-guidance/rulebooks/finra-rules/4210?page=1
- Federal Reserve Regulation T：https://www.federalreserve.gov/frrs/regulations/background-and-summary-of-regulation-t.htm
- SEC leveraged/inverse ETF bulletin：https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-alerts/sec
