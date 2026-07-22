# PQS Drawdown Gate 权威资料复审与建议

日期：2026-07-22

状态：`RECOMMENDATION_ONLY / NOT_YET_EFFECTIVE`

当前机器权威：`config/research_governance.yaml`（schema v2）

当前实现：Qualification V3

## 1. 结论先行

经过同行评审论文、GIPS、SEC、CFA Institute、Morningstar、MSCI、S&P Dow Jones Indices、BlackRock
和 Man Group 一手资料的交叉复核，我不建议继续把：

`每个自然年 × 每个成本情景的 MaxDD 都必须严格小于 SPY`

作为自动晋升的硬门。

这不是因为“低回撤不重要”，而是因为该规则把一个路径依赖、期限依赖、估计误差较大的极值统计量，
按人为日历边界切成十个小样本，再要求十次结果全部同号。它实际检验的是近似“逐年路径支配”，远强于
“长期风险更低且收益更高”，并会系统性偏向现金稀释、极低 tracking-error 或针对 gate 设计的组合。

我也不建议退回“只看 full-period MaxDD”或恢复 1.25x 宽松倍数。推荐 prospectively 引入
`Balanced Drawdown Gate`：

1. full-period MaxDD 必须优于 SPY；
2. 36 个月滚动 MaxDD 至少 60% 窗口优于 SPY；
3. 所有 SPY 跌幅达到 15% 的 benchmark-defined episode 必须优于 SPY；
4. monthly downside capture 必须小于 100%；
5. 年度 MaxDD 不再要求每年都赢，但任何一年不得比 SPY 多回撤超过 5 percentage points；
6. base/60/90 bps 的适用范围预先冻结，绝对 MaxDD 继续报告但不设绝对硬 cap；
7. CAGR、DSR、PBO、MinBTL、CPCV、timing、replay 和 PAPER alignment 等其他门不放松。

其中“60%”和“5 percentage points”是结合本项目风险偏好作出的治理选择，不是外部文献宣称的唯一
正确常数。权威资料支持的是**多期限、多指标、与基准对齐和避免单一 MaxDD 点估计**这一结构。

本报告没有修改当前 governance、Qualification V3、历史 artifact 或 V5 PRD。是否采用必须由用户明确
决定；若采用，应新建 prospective Qualification V4，不能回签旧候选。

## 2. 研究问题

本次复审回答四个问题：

1. MaxDD 是否适合做风险 gate？
2. 是否适合要求每个自然年严格优于 SPY？
3. 权威机构实际如何评价基金、主动经理和风险控制指数？
4. 在坚持“为什么不直接买 SPY”的前提下，PQS 应使用什么可执行标准？

资料准入仅包括：

- 同行评审期刊或大学/作者正式 publication record；
- SEC、GIPS、CFA Institute 等监管/行业标准；
- S&P DJI、MSCI、Morningstar 的正式 methodology；
- BlackRock、Man Group 等大型机构公开的一手研究，并明确其机构利益与回测边界。

博客、社交媒体、匿名回测、营销型“最佳策略”、无方法说明的排行未进入结论。

## 3. MaxDD 可以保留，但不能单点独裁

### 3.1 MaxDD 的优点

MaxDD 直接回答投资者最关心的问题之一：从一个历史高点持有到后续低点，最大资本损失是多少。它能够
捕捉波动率、Sharpe 或单日 Expected Shortfall 看不到的跨期损失路径，因此必须保留。

Cambridge University Press 发表的 Brownian-motion 研究表明，expected maximum drawdown 随观察期限和
drift 改变：正 drift 下长期可按对数增长，零 drift 下按平方根增长，负 drift 下可线性增长。这意味着
不同期限的 MaxDD 不能当成同一个稳定参数比较。

### 3.2 MaxDD 的局限

Harvey 等人在 *Journal of Portfolio Management* 的研究指出，MaxDD 在实践中常用，但因路径依赖而
估计不确定性较大；其分布受到评估期限、Sharpe 和风险持续性的显著影响。Man Group 同一研究的公开
说明也强调，用 drawdown rule 降风险会同时改变 expected return 与 risk，不能视为免费保护。

Goldberg、Mahmoud 在 *Mathematics and Financial Economics* 中将风险扩展为 Conditional Expected
Drawdown（CED），即 MaxDD 分布尾部的均值，并显示 CED 对 serial correlation 特别敏感。这说明：

- 只观察一次历史最大事件的信息量有限；
- i.i.d. 日收益假设会低估路径相关风险；
- 应同时观察 drawdown distribution、duration、recovery 和 downside capture；
- 若做 bootstrap，必须保留时序结构，不能打散为普通 i.i.d. bootstrap。

Chekhlov、Uryasev、Zabarankin 的同行评审研究同样提出 Conditional Drawdown family，将 average
drawdown 与 maximum drawdown 视为同一族的不同极端，而不是宣称只用一次历史 MaxDD 足以决定组合。

### 3.3 自然年边界没有特殊金融含义

calendar-year reset 会产生三个问题：

1. 12 月开始、1 月继续的真实 drawdown 被人为切断；
2. 每年样本只有约 252 个 daily observations，且最终只保留一个 extremum；
3. SPY 平静年 2%–5% 的 MaxDD 会使几百分点的普通 active-risk excursion 变成硬失败，而危机年同样的
   几百分点差异可能很有经济意义。

年度表格非常适合解释 consistency 和定位异常，却不适合要求十次极值比较全部严格同号。

## 4. 权威机构实践

| 来源 | 实际做法 | 对 PQS 的含义 |
|---|---|---|
| GIPS Standards | 至少展示 5 年，逐步扩展至 10 年；要求 strategy 与 benchmark 的 3 年 annualized ex-post standard deviation；明确没有单一风险指标能完整捕捉所有风险 | 使用多期限与多风险指标，不用单一年度 MaxDD 决策 |
| SEC Form N-1A/相关规则 | 标准化展示 1、5、10 年平均年化回报及宽基准；年度变化用于说明 variability，不要求每年胜过基准 | 年度结果应披露，长期 benchmark-relative 结果用于评价 |
| Morningstar Rating | 使用 3、5、10 年 risk-adjusted returns；月度波动并更重视 downside variation；不足 3 年不评级 | 以 3 年为最低稳定评价单位更接近行业实践 |
| Morningstar downside capture | 在 benchmark 为负的月/季度比较策略损失比例；低于 100% 表示下跌期损失更少 | 直接回答“市场跌时是否真正保护” |
| CFA Institute manager selection | 同时使用 upside/downside capture、MaxDD、drawdown duration、style/risk exposures 和定性/运营尽调 | MaxDD 是工具之一，不是唯一 gate |
| MSCI IndexMetrics | 同时报 volatility、Sharpe、downside deviation、VaR、Expected Shortfall、MaxDD、drawdown period、capture ratio | 多指标联合报告是主流方法 |
| S&P Risk Control Indices | 用 realized volatility 动态调整 equity/cash，目标是接近风险 target；方法文件明确不保证实现目标 | 风险 overlay 应控制风险分布，不承诺逐年 MaxDD dominance |
| S&P low/minimum volatility research | 防御策略通常上涨少、下跌少，outperformance 不会在所有时期出现；常用 10 年 rolling volatility 评价 | 每年必须赢会错误拒绝机制正常的防御策略 |
| SPIVA | 对适当 benchmark 做 1/3/5/10 年和 persistence 评价；纠正 survivorship bias | PQS 必须坚持 SPY/匹配被动基准、成本和 survivor-bias 边界 |
| BlackRock institutional research | 强调 whole-portfolio risk、情景、风险预算和下行概率，而不是一个历史年度极值 | 风险层要在完整组合层评价 |

没有找到 SEC、GIPS、CFA、Morningstar、MSCI、S&P 或大型资管机构采用“每个自然年 MaxDD 必须严格
优于同一 benchmark”作为通用 manager/fund acceptance rule。

这不是“不存在即证明错误”，但说明当前 PQS 规则属于项目自定义的超强路径支配约束，不是行业标准。

## 5. 为什么 all-years conjunction 过强

假设某策略在任意一年有概率 `p` 实现比 SPY 更低的 MaxDD。暂时忽略年份间依赖，仅作强度直觉：

| 单年成功概率 p | 连续 10 年全部成功 p^10 |
|---:|---:|
| 60% | 0.60% |
| 70% | 2.82% |
| 80% | 10.74% |
| 90% | 34.87% |
| 95% | 59.87% |

所以，即使一个真实机制有 80% 的年度优势概率，十年“每年全胜”仍约只有 10.7% 机会通过。再要求
30/60/90 bps 三个成本情景全部通过，筛选强度只会更高；这些情景高度相关，不能简单再做独立乘法，
但 conjunction 的 false-negative 风险仍然明确存在。

这个 gate 更接近寻找“几乎确定逐年支配 SPY”的产品，而不是寻找“长期净收益更高、downside 更好”的
主动策略。

## 6. PQS 本地事实复算

以下只是对已经观察历史的治理诊断，不是新的 OOS，也不用于回签候选。

### 6.1 SPY 年度 MaxDD 的尺度变化

使用上一轮 Qualification input 中实际绑定的 SPY daily return series，2015–2024 年度 MaxDD 为：

| 年份 | SPY MaxDD |
|---:|---:|
| 2015 | 11.80% |
| 2016 | 9.00% |
| 2017 | 2.51% |
| 2018 | 18.25% |
| 2019 | 6.20% |
| 2020 | 31.43% |
| 2021 | 4.76% |
| 2022 | 22.71% |
| 2023 | 9.05% |
| 2024 | 7.70% |

2017 的 2.51% 和 2020 的 31.43% 被当前 gate 赋予相同的一票，并且都要求 strict `<`。这在代码上
确定、在经济意义上却不是等价证据。

### 6.2 上一轮代表性候选

base cost、已观察开发区间的诊断如下：

| 候选 | 年度 DD 胜年 | full MDD÷SPY | monthly downside capture | 3 年 rolling DD 胜窗 | 最差年度额外回撤 |
|---|---:|---:|---:|---:|---:|
| `residual_momentum_active` | 3/10 | 0.841 | 86.2% | 6/8 | 21.66pp |
| `residual_momentum_buffer15` | 3/10 | 0.876 | 93.2% | 7/8 | 6.30pp |
| `residual_momentum_hybrid` | 3/10 | 0.860 | 92.9% | 7/8 | 13.49pp |
| `volatility_regime_overlay` | 4/10 | 0.918 | 96.1% | 8/8 | 4.98pp |

这张表同时说明两个方向：

- “每年全胜”确实会拒绝某些 full-period、downside capture、3 年窗口都较好的组合；
- 只看 full-period 也太宽松，例如 `residual_momentum_active` 虽 full MDD 很好，2021 年却比 SPY 多
  回撤 21.66pp，应该被 material-harm veto 拒绝。

上一轮 0 formal 结论不变。这些候选还受 DSR、timing、PBO/MinBTL 等其他 gate 约束，而且旧 bundle
缺少完整的 V4 proposal 输入。任何新规则都不能将它们 retroactively promotion。

## 7. 备选方案比较

| 方案 | 优点 | 主要缺陷 | 结论 |
|---|---|---|---|
| A. 每年、每成本都严格优于 SPY | 最直观、最难出现年度失望 | 极高 false-negative；日历边界任意；偏向 cash dilution/gate gaming | 不推荐作为硬门 |
| B. 只看 full-period MaxDD | 简单、与长期财富路径一致 | 一个事件决定结论；可能掩盖某年/某 regime 的严重失控 | 不推荐 |
| C. 恢复 full MDD<=1.25x SPY | 给主动风险空间 | 与“防御”目标不一致，且 1.25 没有当前风险偏好依据 | 不推荐 |
| D. 只看年度胜率>=60% | 比全胜稳定 | 仍忽略跨年 drawdown、严重 episode 和幅度 | 不足以单独使用 |
| E. 多期限 Balanced Drawdown Gate | 同时控制长期、滚动、危机、下跌期和年度灾难 | 实现/验证更复杂，需要 Qualification V4 | 推荐 |

## 8. 推荐的 Balanced Drawdown Gate

### 8.1 Return gates：不降低“为什么不买 SPY”的要求

1. `base_30bps_after_cost_cagr > SPY_cagr`；
2. `60bps_after_cost_cagr >= SPY_cagr`，证明 2x 成本下仍有经济价值；
3. 90bps CAGR excess 强制报告，第一版只作 tail-cost diagnostic；若要变成硬门必须另行批准；
4. 36-month rolling after-cost excess-positive fraction>=60%；
5. DSR>=0.95、PBO<=0.50、MinBTL PASS、CPCV development stability PASS；
6. timing、next-open、future mutation、deterministic replay、data provenance、PAPER alignment 不变。

这里把当前 252-session rolling return consistency 提升为 36 个月，是因为 SEC、GIPS、Morningstar 的
共同实践支持多年度评价；252-session 结果继续完整报告。

### 8.2 Drawdown hard gates

对 base 30bps、60bps、90bps candidate returns 使用同一冻结 SPY benchmark series：

#### D1. 完整周期

`abs(full_period_candidate_MDD) < abs(full_period_SPY_MDD)`

三种成本情景全部必须通过。

#### D2. 36 个月滚动稳定性

- 每个 month-end 形成 trailing 36-month window；
- strategy 与 SPY 使用完全相同 date index；
- 至少 60% 窗口 candidate MaxDD 严格优于 SPY；
- 报告 overlap-adjusted effective window count，不把高度重叠窗口冒充独立样本。

三种成本情景全部必须达到 60%。

#### D3. 严重 benchmark drawdown episodes

用纯 SPY 路径机械定义 episode：

- episode 从 SPY high-water mark 开始；
- SPY peak-to-trough 达到 15% 时成为 binding episode；
- 到 SPY 回到原 high-water mark 或 evaluation end 结束；
- candidate 不能参与 episode 选择；
- 在该 aligned episode 内，candidate MDD 必须严格小于 SPY episode MDD。

历史与未来所有满足条件的 episode、所有成本情景都必须通过。这样直接要求危机保护，却不把 2017
这类平静年的 2.5% SPY MaxDD 与 2020 的 31% 等权处理。

15% 是预先冻结的“material market drawdown”治理阈值，不是绝对 candidate MaxDD cap。

#### D4. Downside capture

- 用 monthly total returns；
- 只取 SPY monthly return<0 的月份；
- candidate/benchmark 按同一几何方法计算；
- `downside_capture < 100%`；
- base/60/90bps 全部通过。

这对应 Morningstar/CFA 的标准解释：市场下跌期策略总体损失必须少于 SPY。

#### D5. 年度 material-harm veto

每个完整 calendar year 继续计算并公布 MaxDD，但不再要求每年都赢。改为：

`abs(candidate_annual_MDD) - abs(SPY_annual_MDD) <= 5 percentage points`

任一年、任一成本情景超过 5pp 即失败。等于 5pp 可通过，浮点容差必须在 evaluation contract 冻结。

这个 veto 会允许“2017 SPY -2.5%、策略 -5%”这类小幅 active-risk excursion，但拒绝“2021 SPY
-4.8%、策略 -26%”这类机制失控。5pp 是本项目建议的 materiality budget；它是**相对 SPY 的额外
损失上限**，不是 candidate absolute MaxDD cap。

### 8.3 强制诊断但暂不 binding

- 每年是否优于 SPY、年度胜率、最差/中位 margin；
- Conditional Expected Drawdown/CED90；
- paired stationary-block bootstrap 下的 252-session MaxDD difference distribution；
- 20-session 与 63-session mean block length 的敏感性；
- drawdown duration、time-to-recovery、underwater area；
- monthly downside/upside capture、downside deviation、Expected Shortfall；
- beta、tracking error、information ratio、risk-matched passive benchmark；
- Covid、2022 rate-hike 等命名 stress slice。

CED/bootstrap 第一轮只作诊断，因为 bootstrap model、block length 和 regime non-stationarity 本身也会引入
模型风险。完成独立实现、synthetic calibration 和一轮 prospective observation 后，再决定是否升级为硬门。

### 8.4 没有绝对 MaxDD cap

继续禁止以下机器硬门：

- candidate MaxDD 必须小于 15%/20%/25%；
- stress slice candidate MaxDD 的绝对 cap；
- “至少比 SPY 改善 5%/10%”的隐藏 improvement threshold。

full-period、rolling、episode、annual 和 CED 的绝对数值仍必须全部报告。

## 9. 为什么这个方案更符合用户目标

用户的核心判断是：“如果收益和风险都不如 SPY，直接买 SPY 更简单，还少手续费和滑点。”推荐方案没有
改变这个原则：

- base 和 2x 成本后都要跑赢 SPY；
- full-period 最大回撤必须更小；
- 真实严重市场回撤 episode 必须更小；
- 所有负 SPY 月份合起来必须少跌；
- 三年滚动窗口要多数更好；
- 任一年都不能出现超过 SPY 5pp 的额外资本损失。

它只删除了“每个任意自然年、哪怕差 0.01pp 也永久失败”的逻辑。

这比旧 1.25x gate 严格得多，但比十年逐年全胜更贴合经济目标，也更不鼓励用大量 BIL 稀释 SPY 来
机械赢回撤门。现金稀释若不能在 30/60bps 成本后跑赢 SPY，仍会直接失败。

## 10. 对 V5 mining PRD 的影响

若用户批准：

1. 保留 V5 的 SPY anchor、quality/momentum/low-risk sleeve、无杠杆 risk engine 和受治理语义/ML 方向；
2. 将 V5 §11 的 Qualification V3 annual all-years gate 替换为本报告的 Balanced Drawdown Gate；
3. 将 return rolling window 从 252 sessions 改为 36 months，252 sessions 降为诊断；
4. R01-R05 风险层首先验证 D1-D5，而不是优化年度全胜数量；
5. trial budget、过去 30 次试验并集、survivor-bias、PIT、成本、LLM 和 short 边界不变；
6. 新建 `research_governance` schema v3、evaluation contract v2、Qualification V4；
7. 新规则正式生效前不得运行方向性 V5 return trial。

若用户不批准，当前 schema v2/Qualification V3 继续是唯一机器权威，V5 按逐年全胜标准执行。

## 11. 历史与 forward 边界

- 本报告使用了已经观察的 2015–2024 候选结果来校准 materiality，因此新 gate 不是 pristine discovery；
- 所有旧候选仍为 0 formal，不允许按新建议 retroactive promotion；
- 旧 Qualification V2/V3 artifact 不回写、不重签；
- 新 gate 只适用于新 protocol、新 ledger intent 之后生成的 returns；
- future PAPER 前 252 sessions 继续积累，不以不完整 calendar year 作正式年度结论；
- PAPER/LIVE 的最短 forward 长度是否从 252 增加到 756 sessions 是独立治理问题，本报告不擅自修改；
- 未完成 source-batch binding、broker authority 和 PAPER/backtest parity 前仍不得真实执行。

## 12. 验收测试要求

Qualification V4 至少需要：

1. cross-year drawdown 不被错误 reset 的 full/rolling test；
2. month-end 36-month window date-index/hash test；
3. overlapping-window effective count diagnostic；
4. SPY 15% episode start/trigger/recovery/end state-machine test；
5. candidate 不能改变 episode selection 的 mutation test；
6. downside capture 的负 benchmark 月筛选与几何复合 test；
7. annual 5pp gap 的 equality、floating tolerance、成本情景 test；
8. base/60/90 scenario completeness 与 benchmark alignment test；
9. legacy absolute MaxDD config 不得重新进入 hard gate；
10. old artifact 在 V4 validator 下 fail closed，而不是自动迁移；
11. synthetic cash-dilution strategy 因 return gate 失败；
12. synthetic crisis-protection strategy 可以在一个平静年小幅落后、但仍通过 drawdown structure；
13. synthetic 2021-like annual blow-up 即使 full-period MDD 较好也被 D5 拒绝。

## 13. 权威来源

### Drawdown 统计与风险研究

- [On the Maximum Drawdown of a Brownian Motion, Journal of Applied Probability](https://www.cambridge.org/core/journals/journal-of-applied-probability/article/abs/on-the-maximum-drawdown-of-a-brownian-motion/F9E3B8A454B020DDEBF0AC3390EF7807)
- [Drawdowns, Journal of Portfolio Management / Duke publication record](https://scholars.duke.edu/publication/1461725)
- [Drawdown: From Practice to Theory and Back Again, Mathematics and Financial Economics](https://doi.org/10.1007/s11579-016-0181-9)
- [Drawdown Measure in Portfolio Optimization, peer-reviewed publication record](https://researchconnect.suny.edu/en/publications/drawdown-measure-in-portfolio-optimization/)
- [Benchmark-based deviation and drawdown measures, Optimization Letters](https://link.springer.com/article/10.1007/s11590-024-02124-x)

### 标准、监管与评价方法

- [GIPS Standards Handbook for Firms](https://www.gipsstandards.org/standards/gips-standards-for-firms/gips-standards-handbook-for-firms/)
- [SEC mutual-fund standardized 1/5/10-year benchmark disclosure](https://www.sec.gov/files/rules/final/33-7941.htm)
- [CFA Institute Investment Manager Selection](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/investment-manager-selection)
- [Morningstar Rating for Funds Methodology](https://www.morningstar.com/content/dam/marketing/shared/research/methodology/771945_Morningstar_Rating_for_Funds_Methodology.pdf)
- [Morningstar Downside Capture Ratio](https://www.morningstar.com/investing-terms/downside-capture-ratio)
- [MSCI IndexMetrics risk-measure definitions](https://www.msci.com/downloads/documents/indexes/consultations/equity/Simulated%20Impact%20-%20Key%20MSCI%20ACWI%20Screened%20Index.pdf)
- [S&P SPIVA methodology and persistence](https://www.spglobal.com/spdji/en/research-insights/spiva/about-spiva)

### 大型机构与指数商一手实践

- [S&P Risk Control Indices](https://www.spglobal.com/spdji/en/index-family/commodities/quantitative-strategies/risk-control/)
- [S&P: Limiting Risk Exposure with Risk Control Indices](https://www.spglobal.com/spdji/en/research/article/limiting-risk-exposure-with-sp-risk-control-indices/)
- [BlackRock: Dampening the Downside](https://www.blackrock.com/institutions/en-gb/insights/portfolio-design/dampening-downside-protection-strategies)
- [BlackRock: Total Portfolio Approach](https://www.blackrock.com/corporate/insights/blackrock-investment-institute/our-take-on-total-portfolio-approach)
- [Man Group: Drawdowns](https://www.man.com/insights/drawdowns)

## 14. 最终建议

我的独立建议是：

`拒绝继续使用 annual-all-years strict dominance；批准 Balanced Drawdown Gate 作为新的 prospective 方向。`

如果风险偏好仍希望更保守，优先把 annual material-harm veto 从 5pp 收紧到 3pp，而不是恢复“每年差
0.01pp 也失败”。前者表达可理解的资本损失容忍度，后者主要表达统计符号一致性。

在用户明确批准前，当前逐年全胜规则保持有效，本报告只作为决策依据。
