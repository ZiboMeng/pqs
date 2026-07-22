# PQS Mining V5：Balanced Drawdown 与账户风险分层下的策略挖掘 PRD

版本：1.1

日期：2026-07-22

状态：`PROPOSED / MUST_PAUSE_FOR_GOVERNANCE_V3_APPROVAL`

证据范围：`DEVELOPMENT_ONLY`

当前机器权威：`config/research_governance.yaml`（schema v2；本 PRD 尚未生效）

前置 PRD：`docs/prd/20260720-governed-semantic-ml-mining-prd.md`

本 PRD 替代前置 PRD 的“下一轮策略方向、label horizon、组合构造和候选冻结门”；已经完成的历史
实现、失败证据、ledger 和审计记录不回写、不删除。

v1.1 同时吸收：

- `docs/audit/20260722-drawdown-gate-authoritative-web-research.md`；
- 外部审计员对绝对账户风险、SPY 口径、D5 materiality 和 36-month 有效样本数的复核；
- `docs/audit/20260722-drawdown-auditor-opinion-disposition.md` 的独立处置。

因为 v1.1 改变正式 evaluation definition，它需要新的 research-governance schema v3、evaluation
contract v2 和 Qualification V4。用户明确批准并完成实现前，schema v2/Qualification V3 仍是唯一机器
权威，且**不得启动本 PRD 的方向性 return trial**。

## 1. 执行摘要

下一阶段正式主线不是继续扩大因子 zoo 或直接用 LLM 猜收益，而是构造一个完整的
`SPY-plus defensive alpha` 组合：

1. SPY 参与锚，保留长期股票风险溢价；
2. 低换手的质量、动量、低风险 alpha sleeve；
3. 无杠杆的波动/趋势防御层，未使用的风险预算进入 BIL；
4. SEC filing 语义、peer clustering 和浅层 ML 只作为对上述规则组合的可证伪增量；
5. LLM 只做带证据位置的结构化抽取，不直接预测收益、不生成仓位。

每个被评估的对象必须是**完整可交易组合**，不是单独 sleeve。正式 research-candidate 目标同时满足：

1. base 和 2x 成本后整体收益跑赢 canonical SPY total-return hurdle；
2. full-period、36-month rolling、SPY material-drawdown episode、downside capture 和年度 material-harm
   veto 组成的 Balanced Drawdown Gate；
3. DSR/PBO/MinBTL/CPCV、时序、复现、数据来源和多重试验纪律不放松。

绝对风险不与相对 gate 混为一件事。原始 research candidate 不恢复旧 15%/20%/25% 历史 MaxDD cap；
但任何 `RISK_GOVERNED_PAPER_ELIGIBLE` 状态必须额外证明账户部署组合的风险覆盖层满足第 11.3 节的
绝对风险合同。未完成时只允许 `SHADOW_PAPER_OBSERVATION`，无资本权限。

本轮仍遵守既定退出标准：最多 30 个新的方向性 trial，或提前获得 5 个通过 Qualification V4 的
冻结候选，以先到者为准。鉴于当前历史区间已经被观察，所谓“通过”只能产生
`FROZEN_FORWARD_CANDIDATE`，不能把历史开发结果改写为 sealed OOS 或直接晋升实盘。

## 2. 为什么选这条主线

### 2.1 文献支持，但不照抄论文收益

| 证据 | 可采纳结论 | 不能外推的部分 | 本项目动作 |
|---|---|---|---|
| Moskowitz、Ooi、Pedersen 的 time-series momentum | 趋势在多资产期货上有长期机制依据 | 原策略可做空、用期货且波动缩放；后续研究认为资产级 TSM 证据偏弱 | 趋势仅作为 long-only 去风险器，不当作独立收益引擎 |
| Moreira、Muir 的 volatility management | 高波动时降低风险可能改善风险调整收益 | 后续多因子研究显示结果依赖组合、样本与成本；不等于免费 alpha | 只允许简单、封顶、无杠杆 scaler，并与 buy-and-hold/趋势控制对照 |
| Quality Minus Junk 与 S&P Quality 方法 | 盈利能力、低应计、低杠杆是可解释的质量维度 | QMJ 的核心证据是 long-short，不能等同于 long-only 超额收益 | 使用 PIT 质量 tilt，必须单独证明 long-only、成本后增量 |
| 动量文献 | 中期价格趋势是强候选特征 | 动量存在 crash、换手与交易成本风险 | 与质量/低风险组合，使用 enter/hold buffer 和最短持有期 |
| Novy-Marx、Velikov 的交易成本研究 | buy/hold spread 是有效降成本方法，高换手异常净收益较弱 | 论文成本样本不等于本项目实际成交成本 | 季度硬调仓、月度 review、进入/退出阈值分离、30/60/90 bps 压测 |
| Gu、Kelly、Xiu 的 ML 资产定价 | 非线性交互可能有增量，浅层模型在低信噪比金融数据上很重要 | 论文使用约 29,000 支股票、丰富特征和 long-short 组合；本项目样本远小 | 规则、ridge、浅约束 GBDT 同口径比较；不直接上深度模型 |
| Lazy Prices 与 Loughran-McDonald | filing 语言变化、金融专用词典有信息价值 | Lazy Prices 最强组合是 long nonchangers/short changers | 只研究低频 long-only filing change，必须胜过 structured/shuffled controls |
| Hoberg、Phillips | 10-K 产品描述可构造动态 product-market peers | 文本相似不自动产生可交易 alpha | 用作 peer residualization/clustering，不直接给仓位 |
| BloombergGPT | 金融领域语料可改善金融 NLP 任务 | 闭源、不能复现，也没有证明可交易 alpha | 仅证明 domain representation 值得研究，不构成晋升证据 |

### 2.2 对 LLM 证据的特殊降级

芝加哥 Booth 教授 Valeri Nikolaev 的官方页面披露，工作论文
“Financial Statement Analysis with Large Language Models”因底层数据与分析无法一致复现而暂时撤回，
且其他相关 LLM 项目也被复核。这个事件并不证明“LLM 对金融无用”，但足以否定把单篇 LLM 回测当作
本项目直接收益依据。

因此本轮 LLM 的证据等级固定为 `EXPERIMENTAL_REPRESENTATION_ONLY`：

- 只能从 SEC 原文抽取版本化字段并返回原文 evidence span；
- 必须打败 deterministic parser、financial dictionary 和 frozen encoder；
- 不允许读取未来市场数据、未冻结网页或研究者手工补分；
- 不允许输出 expected return、target weight、buy/sell 或 gate 决策；
- 模型、权重、prompt、tokenizer、quantization、response 全部 hash 后才可进入 replay。

### 2.3 与上一轮负结果的关系

上一轮 30 个 trial 得到 0 formal candidate。结果显示：

- 高收益候选多伴随较高 beta 和较差的逐年 MaxDD；
- numeric XGB 没有稳定战胜规则/线性基线；
- 5 日 SEC event 的换手经济性失败；
- lexical/text 同一 cohort 有少量增量迹象，但没有成本后完整组合证据；
- 当前公司池按今天的存续公司生成，存在 survivor bias，不能冒充历史 PIT universe。

所以本轮先重构**组合几何和风险预算**，再验证 representation 的边际价值。不能把“换一个模型名”当成
新机制，也不能借 V5 protocol 名称把既有 30 次试验从多重检验 N 中清零。

## 3. 目标、成功定义与非目标

### 3.1 目标

1. 建立完整的 SPY-plus 组合与严格可复现的 Balanced Drawdown 资格计算；
2. 找到最多 5 个机制不同、通过 Qualification V4 的 future-forward 候选；
3. 独立判断 quality/momentum/low-risk、risk overlay、semantic、ML、LLM 各自是否有增量；
4. 将所有正负结果写入跨 campaign 的 append-only trial universe；
5. 对通过者统一冻结，在同一个未来 session 开始 PAPER observation。

### 3.2 成功定义

`FORMAL_V5_RESEARCH_CANDIDATE` 必须同时满足第 11.1、11.2、11.4 节的机器 gate、数据 gate 与复现
gate，并生成完整 Qualification V4 artifact。`RISK_GOVERNED_PAPER_ELIGIBLE` 还必须满足第 11.3 节。
5 个 candidate 必须具有不同的 mechanism ID；仅改变权重、lookback、seed、
模型深度或 ticker 组合的 sibling 不算不同正式策略。

### 3.3 非目标

- 不开放 true short、borrow、margin、期货、期权、inverse/leveraged ETF；
- 不用 short 论文的 long-short alpha 代替本项目 long-only 证据；
- 不进行 factor valuation timing；
- 不重跑上一轮 5 日 SEC event strategy；
- 不直接训练大语言模型，不使用 LLM 预测收益或生成仓位；
- 不用 TQQQ、SQQQ 或任何杠杆/反向产品满足收益或回撤门；
- 不把 2025-2026 已观察市场结果用于选参数或宣称新 OOS；
- 不因绝对 MaxDD 较低就绕过 SPY 收益 gate；
- 不创建 LIVE/broker 权限，不改变现有 PAPER 账户。

short 研究保留在 `docs/prd/20260721-short-paper-research-lane-prd.md` 的隔离路径。没有 point-in-time borrow、
locate、fee、recall 和 Rule 201 数据前，short 结果保持 `RESEARCH_INCOMPLETE`，不占本轮正式挖掘预算。

## 4. 证据与网络资料准入政策

策略研究只允许以下来源影响预注册方向：

1. 同行评审期刊的出版社页面或作者 replication package；
2. NBER、SEC、美联储及其他监管/官方数据源；
3. 指数提供商的正式 methodology；
4. 大型机构公开的研究论文，但必须标明利益冲突、回测与不可复现边界；
5. 模型作者/机构的一手技术论文。

社交媒体、SEO 博客、匿名回测、营销页面、未给成本/宇宙/时间戳的“高收益策略”不得影响 hypothesis、
参数、trial 选择或结果解释。搜索日期、URL、来源类别和采纳/拒绝理由写入 evidence manifest。

任何在 2025-01-01 以后发布的资料可以用于**机制、方法和风险审计**，但不得把其中 2025-2026 的市场
表现、成分股或最优参数带入本轮历史策略选择。

## 5. 强制前置工作 R0

任何方向性 return 被计算前，以下事项必须全部完成；这些是建设/数据 QA，不计入 30 个 directional trial。

### R0.1 跨 campaign 试验全集

建立 immutable composite trial-universe manifest：

- 绑定上一轮 30-trial ledger 的路径、head hash、独立 content hash 集合；
- 绑定本轮 append-only ledger；
- 去重后机械计算 `raw_independent_n`；
- 禁止通过 program/protocol/candidate 改名重置 N；
- 所有曾被研究者查看并影响后续选择的 return run 都必须纳入；
- blocked/failed/near-miss 方向性 intent 也占用一个 trial slot；
- 单纯 parser、data QA、单元测试且未查看策略收益的运行不计方向性 trial。

Qualification V4 的 `raw_independent_n` 下限是 30 加本轮已消费的独立方向性 trial 数；若审计发现其他
相关历史 trial，必须继续向上修正，不能向下裁剪。

### R0.2 V5 evaluation contract v2

在看任何候选收益前冻结：

- protocol/program ID；
- evaluation start/end、return-date index 和 SHA-256；
- 纳入比较的完整对齐日历年、month-end 36-month window 和 SPY episode 集合；
- base 30 bps、stress 60/90 bps 的准确引擎语义；
- 每个情景的 candidate 与同一 canonical SPY daily total-return series；
- SPY material episode 的 15% trigger、recovery/end 和 evaluation-end 规则；
- 36-month rolling return/DD 的 month-end 取样、60% 阈值和 overlap-adjusted effective-count 方法；
- annual material-harm budget=`3 percentage points`、比较方向、equality 和浮点容差；
- downside capture 的月频、负 SPY 月筛选和几何复合方法；
- canonical benchmark basis 与 benchmark cost policy，不允许通过给 SPY 增加未记录成本改善候选；
- CPCV、DSR、PBO、MinBTL 参数，以及保留为 diagnostic 的 252-session 结果；
- full-period、GFC/Covid/2022 和其他预命名 stress-slice 集合；
- raw candidate 与 deployed-account-composite 的身份、position-sizing/risk-overlay 边界；
- candidate selection rule 与 sibling 去重规则。

### R0.3 数据可行性

- 扩展 `yahoo_exact_cash_ledger_2007_2024_v6`，覆盖 SPY、BIL、QUAL、MTUM、USMV；
- 每个 symbol 的 raw price/distribution payload、抓取时间、hash、复权/现金台账和发行方 metadata 对账；
- 共同评估起点不得早于所有组件真实 inception 后的第一个完整日历年；禁止 proxy backfill；
- 公司股票轨若没有真正 PIT 历史 universe，只能标 `SURVIVOR_BIASED_DEVELOPMENT_ONLY`；
- SEC filing 只从官方 submissions/XBRL/bulk archive 取得，保存 acceptance timestamp 与原文 hash；
- 所有缺失、ticker/CIK 变化、并购、退市、corporate action 必须 fail closed 或显式进入 quarantine。

### R0.4 canonical SPY benchmark 修复

上一轮 Qualification input 绑定的 SPY backtest path 不能直接沿用。独立复算发现，它在 2015–2024 的
CAGR 为 12.35%、2020/2022 年度 MaxDD 为 31.43%/22.71%；直接从同一 exact-cash snapshot 的
`total_return_close` 重算则为 13.04%、33.70%/24.50%。差异与 single-entry SPY backtest 将历年现金分红
留在 cash、没有持续再投资的实现一致。审计员的 raw-close 34.10%/25.36% 也不是正式口径，因为它忽略
分红；正确结论是**旧 bound path 和 raw close 都不能充当 V4 canonical total-return hurdle**。

V4 必须：

- 硬 benchmark 使用冻结 SPY `total_return_close.pct_change()` 或与其逐日等价的、分红持续再投资的独立
  recurrence；
- candidate 使用 30/60/90 bps after-cost returns，hard SPY hurdle 不随 candidate cost scenario 改写；
- implementable SPY one-time entry cost 另作 diagnostic，不能代替更严格的 costless total-return hurdle；
- 将 raw payload、distribution ledger、total-return series、date index 和 SHA-256 全部绑定；
- 建立 direct-total-return、独立 exact-cash reinvest recurrence 和 Qualification input 三方 parity test；
- 专门测试“分红留现金”negative control 必须与 canonical benchmark 不相等；
- 旧 Qualification V2/V3 和旧 31.43%/22.71% 数值保留为历史证据，不回写、不用于 V4 阈值校准。

### R0.5 权威与代码不变量

- signal 只使用 decision close 及以前信息，最早 T+1 open 成交；
- long-only、gross<=1、cash>=0、无 margin；
- future append、future mutation、timestamp/weekend/holiday、deterministic replay 测试全部通过；
- schema v2/Qualification V3 在批准前保持有效，但 V5 runner 必须 fail closed，不得用 V3 近似 V4；
- Qualification V4 必须绑定 clean commit、governance v3、evaluation contract v2、composite ledger 和
  raw candidate/SPY/deployment returns；
- `temporal_split_v1/v2/v3` 的 20%/25% gate 只属于锁定历史 protocol，不得被 V4 误读为当前权威；
- 旧 artifact 不重签、不覆盖。

## 6. 数据和时间边界

### 6.1 历史研究范围

- development end 固定为 2024-12-31；
- 2025-01-01 至 2026-07-17 已被项目观察，不能被重新命名为 pristine/sealed；
- 若只为工程 replay 使用 2025-2026 数据，必须预先指定、结果不得参与策略选择；
- future forward start 必须严格晚于项目最后实际观察 session，并由 source-batch binding 证明。

### 6.2 两条实现轨

**Track A：ETF implementability baseline**

- SPY、BIL、QUAL、MTUM、USMV；
- 共同起点按真实 inception 和 exact-cash coverage 机械确定；
- 可以形成历史 development qualification，但仍不构成 fresh OOS。

**Track B：company-stock alpha research**

- 使用现有固定 company pool 与 causal daily eligibility；
- 由于 pool 是今天按存续/流动性生成，历史结论必须标 survivor-biased；
- 在 PIT universe 未建立前，Track B 不能成为正式历史 qualification 的唯一依据；
- 它可以在完全冻结后进入真实未来 forward，从那一天起积累有效证据。

Track A 和 Track B 不得混用起点来延长样本，也不得用 ETF 历史替代 stock model 的训练样本。

### 6.3 宏观数据

宏观变量不是本轮主信号。若用于诊断，只能使用 ALFRED vintage，按当时实际发布日期和 revision
状态 point-in-time 重建。没有权威 macro event calendar 时，精确事件择时继续 fail closed。

## 7. 完整组合架构

所有权重均为总 NAV 权重，并在下一交易日 open 按同一成本/缺失开盘规则成交。

### 7.1 Layer A：SPY participation anchor

主构造固定为：

`70% SPY + 30% alpha sleeve`

只允许一个预注册灵敏度邻居：

`60% SPY + 40% alpha sleeve`

这不是保证跑赢的技巧。静态 SPY/BIL 稀释虽然容易降低回撤，却通常牺牲收益，因此 R02 专门作为
gate-gaming negative control。没有成本后超额收益的低风险组合仍然失败。

### 7.2 Layer B：低换手 alpha sleeve

#### ETF sleeve

主 ETF sleeve 固定为：

`1/3 QUAL + 1/3 MTUM + 1/3 USMV`

两因子 ablation 只允许 `QUAL+MTUM`、`QUAL+USMV`、`MTUM+USMV` 三种等权组合，不做连续权重搜索。

#### company-stock sleeve

每个 eligible stock 的基础分数由以下三个等权 family rank 构成：

1. `quality`：高 ROE/盈利能力、低 accrual、低 financial leverage；所有会计值按 filing
   acceptance 后下一交易日才可用；
2. `momentum`：`12-1` 与 `6-1` total-return rank 等权；跳过最近 21 sessions；
3. `low_risk`：低 252-session SPY-residual volatility 与低 63-session realized volatility。

组合规则：

- 在 sector 内 rank；semantic peer 版本仅在 R20 测试；
- 新进入需位于 top 15%，持有直到跌出 top 35%；
- 最短持有 63 sessions；
- 月末只做 eligibility/review，季度末才做常规换仓；风险/退市/missing-data 卖出不等待季度末；
- sleeve 内等权，不允许 optimizer 根据已看收益调权；
- 目标 20 支；不足 12 支则该日 sleeve 分配回 SPY/BIL，不降低 eligibility；
- 总组合单名<=2.5%，top-3<=7.5%，单 sector 总权重<=30%；
- 任一 cap 无法满足时 fail closed，不按排名硬塞。

### 7.3 Layer C：无杠杆防御层

主 risk engine 只有一套固定参数：

1. 在每月最后一个 session close 计算 SPY 的 21d 与 63d annualized realized volatility；
2. `vol_scale = min(1, 15% / max(RV21, RV63))`；
3. 用 SPY total-return level 对 126d/252d SMA 形成两个 causal trend votes；
4. 两票为正时 `trend_scale=1.00`，一票为正时 `0.50`，零票为正时 `0.25`；
5. `equity_scale = min(vol_scale, trend_scale)`，禁止 scale>1；
6. 所有 equity target（SPY anchor 与 alpha sleeve）同比缩放，剩余权重进入 BIL；
7. 信号在月末 close 冻结，下一 session open 执行。

15%、21/63/126/252 这些数值是为了限制自由度而预先冻结的工程选择，不宣称是文献给出的最优参数。
如果主 engine 失败，本轮不围绕这些值做局部搜索。

只允许以下机制 ablation，不搜索窗口/阈值：

- vol-only；
- trend-only；
- vol+trend 主 engine；
- 主 engine 的 defense basket：默认剩余权重进入 BIL；单独 trial 可测试
  `50% BIL + 25% IEF + 25% GLD`，其中 IEF/GLD 只有自身高于 252d SMA 才可持有，否则对应份额回 BIL。

IEF/GLD 需要与 Track A 同等级 exact-cash certification；没有数据时该 trial 为 `BLOCKED_DATA`，不得用
相近 ETF 或回看结果后另选资产补位。

## 8. 表征、clustering、ML 与 LLM

### 8.1 表征阶梯

严格按以下顺序推进，高级层必须相对前一层有增量：

1. PIT structured financials/filing metadata；
2. Loughran-McDonald finance dictionary + 同 form 文档变化；
3. fold-train-only TF-IDF/SVD；
4. frozen finance encoder embedding/novelty；
5. fold-train-only clustering 与 peer-centroid residual；
6. schema-constrained LLM extraction。

10-K 与 10-Q 是正式文本对象；8-K 仅保留 structured metadata 诊断，不重开上一轮 5 日 event trading。
文本特征在 filing acceptance 后下一交易日生效，并保持到下一份同 form filing，避免事件式高换手。

### 8.2 semantic peers

- 产品描述来自 10-K 的可追溯 section；
- vectorizer/encoder、SVD、cluster 数、centroid 只能在 outer train fold fit；
- validation firm 只能映射到已经冻结的 train representation；
- peer residual label 与 feature rank 不得使用 validation/future centroid；
- sector-neutral 与 semantic-peer-neutral 必须做独立 ablation，不能混为一个 trial。

### 8.3 ML 任务

primary label 改为 63-session sector/semantic-peer residual total return rank，与季度换仓经济性匹配。
21-session label 只作诊断，不驱动组合。模型顺序固定为：

1. equal-weight rule rank；
2. regularized linear/ridge rank；
3. shallow constrained GBDT。

GBDT 必须限制深度、叶子数和 feature interaction；超参数只在 inner train folds 的预注册小网格选择。
所有 winsorization、rank、imputation、feature clustering、SVD、embedding normalization 和 model fit 都只在
train fold 完成。outer fold 使用 purged rolling-origin + 63-session embargo，不能在看到 outer 结果后改模型。

神经网络、Transformer、端到端深度模型和“更大的 XGBoost search”不进入本轮。

### 8.4 文本与模型增量门

某一高级表示只有同时满足下列条件才可进入完整 portfolio trial：

- 至少 60% outer folds 的 incremental rank IC 相对 structured/rule baseline 为正；
- 合并后的成本前 signal 不是由单一年份/单一 sector 主导；
- shuffled text、future mutation、section shuffle 负对照没有稳定正 edge；
- 对应完整组合在 30/60/90 bps 下相对前一级改善，而不是只改善裸 IC；
- turnover、coverage、missingness 和 cohort 完全对齐。

失败后关闭该 family，保留 corpus/artifact，不用更大模型“救结果”。

### 8.5 LLM schema

允许字段仅包括：

- risk-factor delta；
- liquidity/going-concern change；
- customer/supplier concentration change；
- accounting-policy/nonrecurring-item change；
- capex/capital-allocation change；
- management guidance（只有原文明确给出时）；
- evidence spans、confidence、missing/ambiguous reason。

优先使用 pinned、可本地重放的 open-weight model。若使用 API，必须冻结 exact snapshot/model ID、system/
user prompt、temperature、seed（若 provider 支持）、request/response 和重试顺序；mutable alias 结果不得进入
formal artifact。LLM extraction 必须经分层人工双审样本和 deterministic evidence-span validator，字段准确率
未达到下列冻结 QA 要求或无法重放时，R30 记录 `BLOCKED_LLM_VALIDITY`，不得换模型补位：

- 在不知道后续收益的前提下，按 form、年份、sector、文本长度分层抽取 200 个 field-level 样本；不足
  200 时使用全部可用样本并报告 power limitation；
- 两名独立标注者只看 filing 原文，disagreement 由第三人裁决；
- JSON schema validity=100%，field precision>=95%，evidence-span support>=98%；
- missing/ambiguous 不计为错误逃生口，coverage 必须单独报告且不得低于 deterministic baseline；
- 任何 QA 样本或阈值变更都产生新 trial intent，不得在 R30 内静默调整。

## 9. 30 个 trial 的预注册矩阵

每一行在运行前写 ledger intent。上游 gate 失败时，下游行记录明确 `BLOCKED_*` outcome 并消费该 slot；
不得用临时想出的 sibling 回填。任何额外 return inspection 都使本轮立刻达到/超过 30-trial 退出条件。

| ID | 完整组合/机制 | 目的 |
|---|---|---|
| R01 | canonical SPY total-return replication + dividend-cash negative control | benchmark、日期、分红再投资、replay 正/负控制；不是候选 |
| R02 | 80% SPY + 20% BIL | 静态稀释的 gate-gaming 负控制 |
| R03 | SPY + vol-only scaler | 单独识别 volatility management |
| R04 | SPY + trend-only scaler | 单独识别 long-only trend defense |
| R05 | SPY + 主 vol/trend engine | 冻结防御层 baseline |
| R06 | 70% SPY + 30% Q/M/LV ETF | 无 overlay 的 factor sleeve |
| R07 | R06 + 主 risk engine | ETF 主候选 |
| R08 | 70% SPY + 30% QUAL/MTUM + risk | 去 low-vol ablation |
| R09 | 70% SPY + 30% QUAL/USMV + risk | 去 momentum ablation |
| R10 | 70% SPY + 30% MTUM/USMV + risk | 去 quality ablation |
| R11 | 60% SPY + 40% Q/M/LV + risk | 唯一 anchor 灵敏度邻居 |
| R12 | R07 + frozen BIL/IEF/GLD defense basket | 2022 类股债同跌环境的独立防御机制 |
| R13 | 70% SPY + 30% stock quality + risk | stock quality long-only 证据 |
| R14 | 70% SPY + 30% stock momentum + risk | stock momentum long-only 证据 |
| R15 | 70% SPY + 30% stock low-risk + risk | stock low-risk long-only 证据 |
| R16 | 70% SPY + 30% stock Q+M + risk | quality 对 momentum crash/质量的互补 |
| R17 | 70% SPY + 30% stock Q+M+LV + risk | 三因子规则主组合 |
| R18 | R17 + sector-neutral rank | 检验 sector 暴露混淆 |
| R19 | R17 取消 enter/hold buffer、其余不变 | 相对 R17 量化低换手 buffer 的净价值 |
| R20 | R17 + train-only semantic-peer residualization | 检验产品市场 peers 的增量 |
| R21 | R17 + PIT structured filing change | 文本轨的 deterministic baseline |
| R22 | R21 + LM dictionary filing-change features | 金融词典增量 |
| R23 | R21 + train-only TF-IDF/SVD novelty | 稀疏语义增量 |
| R24 | R21 + frozen encoder novelty | dense representation 增量 |
| R25 | pre-registered winner(R22:R24) + structured | 只有文本增量门通过才运行 |
| R26 | ridge 63d residual rank full portfolio | 规则对线性学习 |
| R27 | shallow constrained GBDT full portfolio | 非线性交互增量 |
| R28 | 主 risk engine + 机械选出的最佳 numeric sleeve | 冻结数值主候选，不手选 |
| R29 | R28 + 最佳 semantic sidecar | 只有 R25 通过才运行 |
| R30 | R29/R28 + schema LLM extraction | 只有 LLM QA 与全部增量门通过才运行 |

R19 只生成一条新的“无 buffer”return series，并与已经存在的 R17 比较；不再增加第三种阈值或 cadence。
任何额外查看的 buffer variant 都必须单独计 N，并使本轮相应提前退出。

## 10. 机械 candidate selection

禁止研究者在看完表格后“凭感觉”拼最终组合。R25、R28、R29、R30 的上游 winner 按以下字典序规则选择：

1. 必须先通过数据、timing、replay、成本与本 family 的增量门；
2. 必须先通过第 11.1、11.2、11.4 节全部 formal research gate；
3. 再比较 SPY>=15% material episode 中最差的 candidate-vs-SPY drawdown improvement；
4. 再比较 36-month rolling DD win fraction；
5. 再比较 90 bps 后 CAGR excess；
6. 再比较较低 annual turnover；
7. 完全相同时选择机制更简单、feature 更少者。

该规则不会把“接近通过”改写成 gate pass。若任何正式 gate 失败，状态只能是 `REVIEW_HOLD` 或
`REJECTED/BLOCKED`；不能靠人工调整 episode、window、年度 budget 或 benchmark basis 把 near-miss 改写
为 PASS。

同 family 中 NAV correlation>=0.70 的 siblings 最多冻结一个；不同 mechanism 也必须报告 return、active
return、drawdown-state correlation，不能靠 ticker 名称差异制造“5 个策略”。

## 11. 资格门与处置

### 11.1 Qualification V4 return 与统计硬门

每个正式候选必须由 raw inputs 机械重算并同时满足：

1. base 30 bps 后 candidate CAGR 严格大于 canonical SPY CAGR；
2. 60 bps 后 candidate CAGR 大于或等于 canonical SPY CAGR；
3. 90 bps 后 CAGR excess 强制报告，v1.1 只作 tail-cost diagnostic；
4. month-end trailing 36-month after-cost excess-positive fraction>=60%，base/60 bps 均通过；
5. 252-session rolling excess-positive fraction 继续报告但不 binding；
6. DSR statistic>=0.95；其语义是相对多重检验调整后 `SR0` 的 PSR statistic，不是“真 Sharpe>0 概率”；
7. PBO<=0.50；
8. MinBTL PASS；
9. CPCV development return-distribution stability PASS；它是开发稳定性诊断，不是假 OOS；
10. prefix invariance、next-session execution、deterministic replay、future mutation 全 PASS；
11. clean commit、governance v3、evaluation contract v2、composite ledger、raw candidate/SPY/deployment
    returns 的 hash binding 全 PASS。

### 11.2 Balanced Drawdown Gate（D1-D5）

除明确写明者外，D1-D5 对 candidate 的 30/60/90 bps 三条 after-cost return path 全部执行，SPY 始终是
R0.4 定义的同一条 canonical costless total-return path。

#### D1. Full-period relative MaxDD

`abs(candidate_full_period_MDD) < abs(SPY_full_period_MDD)`

三种成本情景都必须严格通过。不能恢复旧 `<=1.25x SPY` 宽松倍数。

#### D2. Month-end trailing 36-month relative MaxDD

- 每个 month-end 形成 trailing 36 calendar months aligned window；
- candidate/SPY 使用相同 date index、opening NAV 和 MaxDD 算法；
- 至少 60% 窗口满足 `abs(candidate_MDD) < abs(SPY_MDD)`；
- base/60/90 bps 分别计算并全部达到 60%；
- 强制报告窗口总数、失败窗口、overlap-adjusted effective count 和方法敏感性。

36-month 窗口高度重叠；10 年样本的有效独立信息通常只有少数几个 regime。60% 是 pre-registered
consistency gate，不得被解释为大量独立样本或显著性证明。若覆盖不足 36 个月则 fail closed；prospective
PAPER 未满 756 sessions 时不得宣称已经完成该门的 forward 验证。

#### D3. SPY-defined material drawdown episode

- episode 从 SPY high-water mark 开始；
- SPY peak-to-trough 首次达到 15% 时成为 binding episode；
- 到 SPY 恢复原 high-water mark 或 evaluation end 结束；
- candidate 不得参与 episode 选择、边界或合并；
- aligned episode 内 `abs(candidate_MDD) < abs(SPY_episode_MDD)`；
- 历史与未来每个 binding episode、每个成本情景都必须通过。

15% 是 material-market-episode trigger，不是 candidate absolute MaxDD cap。

#### D4. Monthly downside capture

- 从 daily canonical returns 机械复合为 calendar-month total returns；
- 只选 SPY monthly return<0 的月份；
- 使用 evaluation contract 冻结的几何 capture 方法；
- `downside_capture < 100%`，base/60/90 bps 全部通过；
- upside capture、down-market hit rate、downside deviation 和 Expected Shortfall 同时报告但不替代 D4。

#### D5. Annual material-harm veto

完整日历年 MaxDD 继续逐年报告，但不再要求每年都赢：

`abs(candidate_annual_MDD) - abs(SPY_annual_MDD) <= 3 percentage points`

任一年、任一成本情景超过 3pp 即失败；等于 3pp 可通过，浮点容差写入 evaluation contract。3pp 是
结合本项目账户规模和保守偏好作出的 materiality budget，不是权威文献的普适常数。年度 win rate、最差/
中位 margin 强制报告，但不额外设“至少赢 X 年”的隐藏 gate。

### 11.3 账户绝对风险合同：与 raw strategy qualification 分层

审计员的极端反例成立：若 SPY 在 GFC 跌 55%，candidate 跌 50%，它可能通过相对门，却不适合承受能力
有限的个人账户。因此 v1.1 采用架构 B，但不把旧 cap 偷渡回 raw strategy gate：

- `FORMAL_V5_RESEARCH_CANDIDATE`：由 11.1、11.2、11.4 决定；绝对 MaxDD 是强制报告项；
- `SHADOW_PAPER_OBSERVATION`：冻结原始信号并只做内部模拟，无资本权限；
- `RISK_GOVERNED_PAPER_ELIGIBLE`：candidate 经过独立、冻结、无杠杆的 account sizing/risk overlay 后，
  还必须通过本节；
- `CAPITAL_ELIGIBLE`：本阶段一律为 false，真实 broker/LIVE 不在本 PRD 范围。

账户风险合同的 proposed hard requirements 是：

1. deployed composite 的设计/运营 MaxDD target band 为 15%-20%，目标不是历史保证；
2. 在可真实重放的 GFC-2008、Covid-2020、rate-hike-2022 路径中，deployed composite MaxDD<=25%；
3. 组件在某历史危机尚未发行时不得 proxy backfill 或用 terminal shock 冒充 drawdown path；必须标
   `BLOCKED_DEPLOYMENT_STRESS_DATA`，最多进入 shadow observation；
4. 现有 `core/risk/stress_tester.py` 只产生 terminal weighted shock，不能计算路径 MaxDD，因此不得为
   requirement 2 出具 PASS；
5. risk overlay 的 decision timestamp、next-open execution、cost、cash、gap、distribution 和 PAPER replay
   必须与策略层同口径；
6. runtime 15% alert、20% mandatory de-risk、25% halt 是响应控制，不得宣传为能防止隔夜 gap 超过阈值；
7. raw 与 deployed NAV、收益损耗、exposure、trigger、override 和 parity 全部并列输出，不能用 sizing 后
   结果替换或美化 raw strategy evidence。

本节会新增账户部署评价定义，因此与整个 v1.1 一样处于 `PENDING_USER_APPROVAL`。批准前不得改
`config/research_governance.yaml`，也不得声称旧 `stress_slice_absolute_drawdown_gate_enabled:false` 已被
悄悄反转。若用户最终决定绝对风险仍只作诊断，则状态必须继续停在 shadow、不能授予资本权限。

### 11.4 组合前置 gate

在构造 Qualification bundle 前还必须通过：

- PIT/price/distribution/SEC provenance；
- long-only、gross、cash、concentration、eligibility 不变量；
- 30/60/90 bps 完整成本轨迹；
- turnover 与成交缺失报告；
- Track B 的 survivor-bias 标记；
- representation/LLM incremental gate（若适用）。

这些是数据真实性和实现有效性要求，不是用于绕过 D1-D5 或账户风险合同的例外。

### 11.5 失败处置

- 正式 gate 任一失败：`REVIEW_HOLD`，不自动删除；
- 数据/时间因果无法证明：`BLOCKED_DATA` 或 `RESEARCH_INCOMPLETE`；
- 模型只有裸 IC、没有成本后组合增量：`REJECTED_NO_ECONOMIC_INCREMENT`；
- survivor-biased Track B 历史 PASS：仍只能 `DEVELOPMENT_ONLY_FORWARD_ELIGIBLE`，不能称历史 formal OOS；
- 通过 research gate 但账户风险合同未完成：只能 `SHADOW_PAPER_OBSERVATION`；
- 人工例外需要用户显式批准，并且永远不得重标为 machine gate PASS。

## 12. 必须输出的 artifact

每个 trial 至少产生：

- intent/outcome ledger events 与 content hash；
- exact data/source manifest；
- daily target、fill、turnover、cost、cash、position 和 NAV；
- base/60/90 bps candidate 与 canonical costless SPY daily total returns；
- SPY raw-close、旧 bound path、canonical total-return path 的 basis reconciliation（前两者只作诊断）；
- calendar-year CAGR、volatility、MaxDD、3pp gap、win/loss 与 margin；
- full-period 和 month-end 36-month rolling return/DD、window pass fraction、overlap-adjusted effective count；
- SPY>=15% episode state machine、episode boundaries、candidate/SPY episode MaxDD；
- monthly downside/upside capture、downside deviation、Expected Shortfall；
- rolling 252d excess、beta/alpha（诊断）、active return distribution；
- raw strategy 与 deployed-account-composite 的独立 NAV、absolute stress path、trigger 和 exposure；
- DSR/PBO/MinBTL/CPCV inputs 与结果；
- concentration、sector、factor exposure、missing/quarantine；
- timing/future-mutation/deterministic-replay test evidence；
- 若为 text/LLM：accession、acceptance time、section/document hash、representation/model/prompt hash、
  extraction JSON、evidence spans 与 negative controls；
- Qualification V4 artifact 或明确 prescreen/block reason。

campaign 结束必须生成：

1. 30-trial 或 5-candidate exit summary；
2. composite trial-universe snapshot；
3. candidate correlation/机制去重矩阵；
4. 每个 gate 的 candidate × full/rolling/episode/year × cost scenario 矩阵；
5. formal、REVIEW_HOLD、blocked、rejected 的完整清单；
6. 冻结 forward manifest 与同日起 PAPER 计划（如有）；
7. 负结果和未解决数据边界，不得只报告 winner。

## 13. PAPER forward

通过者在同一个未来 session 并行进入 PAPER observation：

- 每个 candidate 独立 signed account/manifest，不共享可变模型状态；
- code/config/data/model/prompt/universe/cost/execution 全 hash；
- forward 期间不重训、不重聚类、不改 prompt、不换阈值；
- source-batch 必须绑定 collector 实际消费的数据；未完成时只允许 replay；
- raw shadow 与 risk-governed account 必须分账户/分 manifest；前者不能获得 capital eligibility；
- 最少 252 个 future sessions 前不得作任何自动 promotion；
- 满 252 sessions 只提供一年运营/执行证据；未满 756 sessions 不得宣称 forward 已验证 36-month gate；
- PAPER 与 backtest equity drift 必须<=10 bps；
- 每月更新 rolling/episode/downside-capture；完整年度结束后更新 D5，但不恢复 annual-all-win；
- 组合只读诊断不能把多个未通过策略合成后规避单策略 gate。

## 14. 实施顺序与停止规则

1. 用户显式批准或拒绝 v1.1 的新 evaluation definition 与第 11.3 节账户风险合同；
2. 批准后新建 governance schema v3、evaluation contract v2、Qualification V4；不原地改 V3；
3. 修复并三方验证 canonical SPY total-return benchmark；
4. 冻结本 PRD、evidence manifest、composite trial universe 与 V5 evaluation contract v2；
5. 补全 ETF/defense exact-cash 数据并完成账户 risk-overlay/path-stress 可行性审计；
6. 运行 R01-R05，验证风险层是否真的改善 D1-D5，而不先假定有收益；
7. 运行 R06-R12 的可实现 ETF/SPY-plus 主线；
8. 独立审计 Track B survivor/PIT 边界后运行 R13-R20；
9. 只有 deterministic 文本地基通过才运行 R21-R25；
10. 只有规则基线有效才运行 R26-R27；
11. 按机械 selector 运行 R28-R30；
12. 达到 5 个 Qualification V4 research candidate 或消费 30 个方向性 trial 立即停止挖掘；
13. 完成独立复算、审计报告、候选冻结和同日起 shadow/risk-governed forward handoff。

若前面已产生 5 个正式候选，后续 trial 不得为了“看一眼”继续。若 30 轮仍为 0 formal，这是有效结论，
不得扩大搜索空间、修改 gate、重新打开 2025-2026 或把 near-miss 写成成功。

## 15. 验收测试

### 数据与 benchmark

- canonical SPY direct total return 与独立 dividend-reinvestment recurrence 在冻结 date index 上逐日一致；
- single-entry、dividend-cash-not-reinvested SPY negative control 必须与 canonical benchmark 不一致；
- hard SPY hurdle 在 30/60/90 candidate cost scenarios 中逐日完全相同；
- 对 frozen snapshot 复算 2020/2022 canonical total-return MaxDD 应为约 33.70%/24.50%，精确期望值及容差
  由 source hash 绑定；不得误用 raw-close 34.10%/25.36% 或旧 bound 31.43%/22.71%；
- distribution 缺失、ETF inception 前数据、proxy backfill 均使 evaluation fail closed；
- 在末尾追加未来 rows 不改变任何历史 eligibility、feature、cluster、signal 或 target；
- filing acceptance 在盘后/周末/节假日时映射到正确 next tradable open。

### 回撤 gate

- cross-year drawdown 不得在 D1/D2/D3 中被 calendar reset；calendar reset 只用于 D5 报告/veto；
- D1 equality 必须失败，base 通过但 60/90 bps 任一失败时整体失败；
- month-end trailing 36-month date index、60% equality、overlap count 与 insufficient-history fail-closed；
- SPY 15% episode 的 peak/trigger/recovery/evaluation-end 状态机，以及 candidate mutation 不能改变 episode；
- D4 只选负 SPY 月、几何复合，99.999% 通过而 100% equality 失败；
- D5 annual extra DD 2.999pp/3.000pp/3.001pp 与冻结浮点容差边界；
- synthetic calm-year slight lag 可以通过 D5，但 2021-like 20pp blow-up 必须失败；
- raw research candidate 不因 legacy absolute cap 隐藏失败；deployed account 则必须按 11.3 独立判定；
- evaluation date hash、window set、episode set、year set 或 scenario set 变化使 artifact invalid；
- V2/V3 artifact 在 V4 validator 下 fail closed，不自动迁移。

### 账户绝对风险

- synthetic candidate 跌 50%、SPY 跌 55% 时可通过相对 comparison 的反例必须存在，但 account-risk gate
  必须拒绝其 `RISK_GOVERNED_PAPER_ELIGIBLE`；
- terminal weighted shock 不得被 validator 接受为 path MaxDD；
- 组件 inception 不覆盖 GFC 且无已批准 path model 时 fail closed 到 shadow；
- raw/deployed NAV 不可互换，risk overlay 的未来信息 mutation 必须被检测；
- 15/20/25% runtime trigger 发生后仍可能 gap overshoot，报告不得声称硬保证。

### 组合与执行

- T close signal 只能在 T+1 open 或之后成交；
- gap、missing open、distribution、split、delisting、现金余额在 replay 与 PAPER 一致；
- 所有路径 long-only、gross<=1、cash>=0；
- enter/hold buffer 和 min-hold 在 synthetic rank crossing 上行为确定；
- 单名、top-3、sector cap 与不足最小持仓数 fail-closed。

### ML/text/LLM

- outer validation/future 数据无法影响 scaler、SVD、cluster、peer centroid 或模型 fit；
- shuffled text、future mutation、section shuffle 控制可机械复算；
- LLM 删除 evidence span、修改 prompt/model alias 或 response 时 artifact invalid；
- LLM unavailable 时 deterministic baseline 正常运行且不得静默填 0；
- blocked semantic/LLM slot 不得被临时 sibling 回填。

### 试验治理

- prior 30-trial ledger 与 V5 ledger union 后 raw N 不小于实际方向性试验数；
- duplicate content hash 不增加独立 N，改名不减少 N；
- 并发、crash、retry 后 ledger 不丢 intent/outcome；
- 第 31 次未经授权的方向性 return inspection 被 runner 拒绝。
- governance v3 未获用户显式批准时，V5 runner 在首个方向性 trial 前拒绝运行。

## 16. 可信来源

### 同行评审与 NBER

- [Time Series Momentum, Journal of Financial Economics](https://www.sciencedirect.com/science/article/pii/S0304405X11002613)
- [Time series momentum: Is it there?, Journal of Financial Economics](https://www.sciencedirect.com/science/article/abs/pii/S0304405X19301953)
- [Volatility Managed Portfolios, NBER](https://www.nber.org/papers/w22208)
- [A Multifactor Perspective on Volatility-Managed Portfolios, Journal of Finance](https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13395)
- [Quality Minus Junk, Review of Accounting Studies](https://link.springer.com/article/10.1007/s11142-018-9470-2)
- [Momentum Crashes, Journal of Financial Economics](https://www.sciencedirect.com/science/article/pii/S0304405X16301490)
- [A Taxonomy of Anomalies and Their Trading Costs, Review of Financial Studies](https://academic.oup.com/rfs/article-abstract/29/1/104/1844518)
- [Empirical Asset Pricing via Machine Learning, Review of Financial Studies](https://academic.oup.com/rfs/article/33/5/2223/5758276)
- [Lazy Prices, Journal of Finance](https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12885)
- [When Is a Liability Not a Liability? Textual Analysis, Dictionaries, and 10-Ks, Journal of Finance](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2010.01625.x)
- [Text-Based Network Industries and Endogenous Product Differentiation, NBER](https://www.nber.org/papers/w15991)

### 官方数据、指数与机构一手资料

- [GIPS Standards Handbook for Firms](https://www.gipsstandards.org/standards/gips-standards-for-firms/gips-standards-handbook-for-firms/)
- [SEC standardized 1/5/10-year benchmark disclosure](https://www.sec.gov/files/rules/final/33-7941.htm)
- [CFA Institute Investment Manager Selection](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/investment-manager-selection)
- [Morningstar Rating for Funds Methodology](https://www.morningstar.com/content/dam/marketing/shared/research/methodology/771945_Morningstar_Rating_for_Funds_Methodology.pdf)
- [Drawdowns, Journal of Portfolio Management / Duke record](https://scholars.duke.edu/publication/1461725)
- [Drawdown: From Practice to Theory and Back Again](https://doi.org/10.1007/s11579-016-0181-9)
- [SEC EDGAR submissions/XBRL APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
- [S&P Quality Indices Methodology](https://www.spglobal.com/spdji/en/documents/methodologies/methodology-sp-quality-indices.pdf)
- [S&P Low Volatility Indices Methodology](https://www.spglobal.com/spdji/en/documents/methodologies/methodology-sp-low-volatility-indices.pdf)
- [BlackRock/iShares QUAL official fund page](https://www.ishares.com/us/products/256101/ishares-msci-usa-quality-factor-etf)
- [BlackRock/iShares MTUM official fund page](https://www.ishares.com/us/products/251614/ishares-msci-usa-momentum-factor-etf)
- [BlackRock/iShares USMV official fund page](https://www.ishares.com/us/products/239695/ishares-msci-usa-minimum-volatility-etf)
- [ALFRED real-time vintage documentation](https://fred.stlouisfed.org/docs/api/fred/alfred.html)
- [The Siren Song of Factor Timing, AQR](https://www.aqr.com/Insights/Research/Journal-Article/The-Siren-Song-of-Factor-Timing)
- [BloombergGPT technical paper](https://arxiv.org/abs/2303.17564)
- [Chicago Booth: Ongoing Research Projects / LLM paper withdrawal notice](https://faculty.chicagobooth.edu/valeri-nikolaev/ongoing-research-projects)

## 17. 最终决策

本轮优先级固定为：

`可实现的风险/组合几何 > 低换手规则 alpha > 语义 representation > 浅层 ML > LLM extraction`

理由不是“传统模型一定更好”，而是当前最强约束是完整组合的成本后 SPY excess、Balanced Drawdown、
账户绝对风险边界、PIT 数据和样本量，而不是模型表达能力。只有前一级已经产生可交易、可复算的基线时，
更智能的 representation 才有明确的增量问题可回答。

本 PRD 的建议不是恢复旧 annual-all-win，也不是允许“只要比 SPY 少跌一点就承受任意绝对损失”。它把
研究策略的相对质量与账户部署的绝对承受能力分别治理；任何一层证据不足都不能跨层借 PASS。
