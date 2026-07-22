# PQS Mining V5：逐年 SPY 相对回撤约束下的策略挖掘 PRD

版本：1.0

日期：2026-07-22

状态：`PROPOSED / READY_FOR_PREREGISTRATION`

证据范围：`DEVELOPMENT_ONLY`

上位治理：`config/research_governance.yaml`（schema v2）

前置 PRD：`docs/prd/20260720-governed-semantic-ml-mining-prd.md`

本 PRD 替代前置 PRD 的“下一轮策略方向、label horizon、组合构造和候选冻结门”；已经完成的历史
实现、失败证据、ledger 和审计记录不回写、不删除。

## 1. 执行摘要

下一阶段正式主线不是继续扩大因子 zoo 或直接用 LLM 猜收益，而是构造一个完整的
`SPY-plus defensive alpha` 组合：

1. SPY 参与锚，保留长期股票风险溢价；
2. 低换手的质量、动量、低风险 alpha sleeve；
3. 无杠杆的波动/趋势防御层，未使用的风险预算进入 BIL；
4. SEC filing 语义、peer clustering 和浅层 ML 只作为对上述规则组合的可证伪增量；
5. LLM 只做带证据位置的结构化抽取，不直接预测收益、不生成仓位。

每个被评估的对象必须是**完整可交易组合**，不是单独 sleeve。正式目标同时满足：成本后整体收益
跑赢 SPY，并在每个对齐日历年、base 与所有冻结成本压力情景下，年度 MaxDD 严格优于 SPY。
绝对 MaxDD 继续完整报告，但不设任何绝对硬阈值。

本轮仍遵守既定退出标准：最多 30 个新的方向性 trial，或提前获得 5 个通过 Qualification V3 的
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

1. 建立完整的 SPY-plus 组合与严格可复现的年度相对回撤资格计算；
2. 找到最多 5 个机制不同、通过 Qualification V3 的 future-forward 候选；
3. 独立判断 quality/momentum/low-risk、risk overlay、semantic、ML、LLM 各自是否有增量；
4. 将所有正负结果写入跨 campaign 的 append-only trial universe；
5. 对通过者统一冻结，在同一个未来 session 开始 PAPER observation。

### 3.2 成功定义

`FORMAL_V5_CANDIDATE` 必须同时满足第 11 节全部机器 gate、数据 gate 与复现 gate，并生成完整
Qualification V3 artifact。5 个 candidate 必须具有不同的 mechanism ID；仅改变权重、lookback、seed、
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

Qualification V3 的 `raw_independent_n` 下限是 30 加本轮已消费的独立方向性 trial 数；若审计发现其他
相关历史 trial，必须继续向上修正，不能向下裁剪。

### R0.2 V5 evaluation contract

在看任何候选收益前冻结：

- protocol/program ID；
- evaluation start/end、return-date index 和 SHA-256；
- 纳入比较的完整对齐日历年集合；
- base 30 bps、stress 60/90 bps 的准确引擎语义；
- 每个情景的 candidate 与 canonical SPY daily return series；
- benchmark cost/entry policy，不允许通过给 SPY 增加未记录成本改善候选；
- 252-session rolling window、CPCV、DSR、PBO、MinBTL 参数；
- full-period 和命名 stress-slice 诊断集合；
- candidate selection rule 与 sibling 去重规则。

### R0.3 数据可行性

- 扩展 `yahoo_exact_cash_ledger_2007_2024_v6`，覆盖 SPY、BIL、QUAL、MTUM、USMV；
- 每个 symbol 的 raw price/distribution payload、抓取时间、hash、复权/现金台账和发行方 metadata 对账；
- 共同评估起点不得早于所有组件真实 inception 后的第一个完整日历年；禁止 proxy backfill；
- 公司股票轨若没有真正 PIT 历史 universe，只能标 `SURVIVOR_BIASED_DEVELOPMENT_ONLY`；
- SEC filing 只从官方 submissions/XBRL/bulk archive 取得，保存 acceptance timestamp 与原文 hash；
- 所有缺失、ticker/CIK 变化、并购、退市、corporate action 必须 fail closed 或显式进入 quarantine。

### R0.4 代码不变量

- signal 只使用 decision close 及以前信息，最早 T+1 open 成交；
- long-only、gross<=1、cash>=0、无 margin；
- future append、future mutation、timestamp/weekend/holiday、deterministic replay 测试全部通过；
- Qualification V3 必须绑定 clean commit、governance、evaluation contract、composite ledger 和 raw returns；
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
| R01 | canonical SPY exact-cash replication | benchmark、日期、成本、replay 正控制；不是候选 |
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
2. 通过逐年/逐成本 SPY 相对 MaxDD 的年份/情景数量最多；
3. 再比较最差年度的 `abs(SPY DD) - abs(candidate DD)` margin；
4. 再比较 90 bps 后 CAGR excess；
5. 再比较较低 annual turnover；
6. 完全相同时选择机制更简单、feature 更少者。

该规则不会把“接近通过”改写成 gate pass。若任何正式 gate 失败，状态只能是 `REVIEW_HOLD` 或
`REJECTED/BLOCKED`；极小正 drawdown margin 可以通过数学硬门，但必须额外报告 `epsilon_margin_warning`，
供人工判断而不构成隐藏阈值。

同 family 中 NAV correlation>=0.70 的 siblings 最多冻结一个；不同 mechanism 也必须报告 return、active
return、drawdown-state correlation，不能靠 ticker 名称差异制造“5 个策略”。

## 11. 资格门与处置

### 11.1 Qualification V3 机器硬门

每个正式候选必须由 raw inputs 机械重算并同时满足：

1. base 30 bps 后 candidate CAGR 严格大于 canonical SPY CAGR；
2. 252-session rolling excess-positive fraction>=60%；
3. 每个对齐完整日历年，base candidate `abs(MaxDD)` 严格小于 SPY；
4. 60 bps、90 bps 每个冻结情景的每个对齐完整日历年也严格小于匹配 SPY；
5. DSR statistic>=0.95；其语义是相对多重检验调整后 `SR0` 的 PSR statistic，不是“真 Sharpe>0 概率”；
6. PBO<=0.50；
7. MinBTL PASS；
8. CPCV development return-distribution stability PASS；它是开发稳定性诊断，不是假 OOS；
9. prefix invariance、next-session execution、deterministic replay、future mutation 全 PASS；
10. clean commit、governance、evaluation contract、composite ledger、raw candidate/SPY/stress returns 的 hash
    binding 全 PASS。

### 11.2 不得加入的隐藏 MaxDD 门

以下只强制报告，不得决定机器 PASS/FAIL：

- full-period absolute MaxDD；
- Covid、2022 rate-hike 及其他预命名 stress-slice absolute MaxDD；
- 15%/20%/25% 等绝对 MaxDD cap；
- “至少改善 5%/10%”等额外相对回撤阈值。

年度严格优于 SPY 是唯一 binding drawdown comparison。每年 margin、最小 margin 和数值容差必须输出，
但除严格 `<` 外不新设阈值。

### 11.3 组合前置 gate

在构造 Qualification bundle 前还必须通过：

- PIT/price/distribution/SEC provenance；
- long-only、gross、cash、concentration、eligibility 不变量；
- 30/60/90 bps 完整成本轨迹；
- turnover 与成交缺失报告；
- Track B 的 survivor-bias 标记；
- representation/LLM incremental gate（若适用）。

这些是数据真实性和实现有效性要求，不是新增绝对风险门。

### 11.4 失败处置

- 正式 gate 任一失败：`REVIEW_HOLD`，不自动删除；
- 数据/时间因果无法证明：`BLOCKED_DATA` 或 `RESEARCH_INCOMPLETE`；
- 模型只有裸 IC、没有成本后组合增量：`REJECTED_NO_ECONOMIC_INCREMENT`；
- survivor-biased Track B 历史 PASS：仍只能 `DEVELOPMENT_ONLY_FORWARD_ELIGIBLE`，不能称历史 formal OOS；
- 人工例外需要用户显式批准，并且永远不得重标为 machine gate PASS。

## 12. 必须输出的 artifact

每个 trial 至少产生：

- intent/outcome ledger events 与 content hash；
- exact data/source manifest；
- daily target、fill、turnover、cost、cash、position 和 NAV；
- base/60/90 bps candidate 与匹配 SPY daily returns；
- calendar-year CAGR、volatility、MaxDD、margin；
- rolling 252d excess、beta/alpha（诊断）、active return distribution；
- DSR/PBO/MinBTL/CPCV inputs 与结果；
- concentration、sector、factor exposure、missing/quarantine；
- timing/future-mutation/deterministic-replay test evidence；
- 若为 text/LLM：accession、acceptance time、section/document hash、representation/model/prompt hash、
  extraction JSON、evidence spans 与 negative controls；
- Qualification V3 artifact 或明确 prescreen/block reason。

campaign 结束必须生成：

1. 30-trial 或 5-candidate exit summary；
2. composite trial-universe snapshot；
3. candidate correlation/机制去重矩阵；
4. 每个 gate 的 candidate × year × cost scenario 矩阵；
5. formal、REVIEW_HOLD、blocked、rejected 的完整清单；
6. 冻结 forward manifest 与同日起 PAPER 计划（如有）；
7. 负结果和未解决数据边界，不得只报告 winner。

## 13. PAPER forward

通过者在同一个未来 session 并行进入 PAPER observation：

- 每个 candidate 独立 signed account/manifest，不共享可变模型状态；
- code/config/data/model/prompt/universe/cost/execution 全 hash；
- forward 期间不重训、不重聚类、不改 prompt、不换阈值；
- source-batch 必须绑定 collector 实际消费的数据；未完成时只允许 replay；
- 最少 252 个 future sessions 前不得自动 promotion；
- PAPER 与 backtest equity drift 必须<=10 bps；
- 年中只报告 year-to-date drawdown margin，年度 gate 只能在完整日历年结束后正式判定；
- 组合只读诊断不能把多个未通过策略合成后规避单策略 gate。

## 14. 实施顺序与停止规则

1. 冻结本 PRD、evidence manifest、composite trial universe 与 V5 evaluation contract；
2. 补全 ETF/defense exact-cash 数据并做 benchmark parity；
3. 运行 R01-R05，验证风险层是否真的改善逐年回撤，而不先假定有收益；
4. 运行 R06-R12 的可实现 ETF/SPY-plus 主线；
5. 独立审计 Track B survivor/PIT 边界后运行 R13-R20；
6. 只有 deterministic 文本地基通过才运行 R21-R25；
7. 只有规则基线有效才运行 R26-R27；
8. 按机械 selector 运行 R28-R30；
9. 达到 5 个 Qualification V3 candidate 或消费 30 个方向性 trial 立即停止挖掘；
10. 完成独立复算、审计报告、候选冻结和同日起 forward handoff。

若前面已产生 5 个正式候选，后续 trial 不得为了“看一眼”继续。若 30 轮仍为 0 formal，这是有效结论，
不得扩大搜索空间、修改 gate、重新打开 2025-2026 或把 near-miss 写成成功。

## 15. 验收测试

### 数据与 benchmark

- SPY exact-cash replay 与 canonical benchmark 在冻结 date index 上逐日一致；
- distribution 缺失、ETF inception 前数据、proxy backfill 均使 evaluation fail closed；
- 在末尾追加未来 rows 不改变任何历史 eligibility、feature、cluster、signal 或 target；
- filing acceptance 在盘后/周末/节假日时映射到正确 next tradable open。

### 回撤 gate

- synthetic 多年样本证明每个 calendar year 独立重置 high-water mark；
- candidate 仅某一年等于 SPY DD 时严格失败；
- base 通过但 60/90 bps 任一情景任一年失败时严格失败；
- full-period absolute DD 很低但某一年不优于 SPY 时失败；
- absolute DD 超过任意 legacy 15%/20%/25% 但逐年优于 SPY时，不得因 legacy cap 失败；
- evaluation date hash、year set 或 scenario set 变化使 artifact invalid。

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

理由不是“传统模型一定更好”，而是当前最强约束是每年相对 SPY 的完整组合回撤、交易成本、PIT 数据和
样本量，而不是模型表达能力。只有前一级已经产生可交易、可复算的基线时，更智能的 representation 才有
明确的增量问题可回答。
