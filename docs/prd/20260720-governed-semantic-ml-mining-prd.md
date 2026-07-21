# PQS Governed Semantic + ML Strategy Mining PRD

版本：1.0

日期：2026-07-20

状态：APPROVED FOR IMPLEMENTATION

事实依据：`docs/audit/20260720-strategy-mining-preflight-audit.md`

上位治理：`config/research_governance.yaml`

## 1. 目标

在不重开任何已观察历史区间、不放松 long-only/no-short/no-margin、不把历史开发结果冒充 sealed OOS
的前提下，建立三个可比较、机制不同的候选族：

1. rule-based rank baseline；
2. benchmark-aware XGB learning-to-rank；
3. SEC filing/event semantic sidecar。

通过开发门的候选可以冻结并一起进入未来 PAPER forward observation。历史测试永不自动 promotion；
最终自动晋升仍要求同口径、成本后的 SPY excess 为正。接近 SPY 且有显著低回撤等特征时进入
`REVIEW_HOLD`，不自动删除，也不改写成 PASS。

## 2. 非目标

- 不再做无边界的 LLM OHLCV 公式生成；
- 不训练本地大语言模型，不优先重跑 chart Transformer；
- 不使用 inverse/short-equivalent ETF；
- 不改变生产策略、LIVE、broker 写权限或当前 PAPER observation artifact；
- 不把 expanded_v2、2018-2025 validation 或 2024-2026 区间称作新 OOS/sealed；
- 不删除历史文档、失败结果或 registry。

## 3. 统一证据等级

| 等级 | 含义 | 允许动作 |
|---|---|---|
| `DEVELOPMENT_ONLY` | 已看历史上的诊断、CV、回测 | 选型、反证、冻结 forward 候选；不可 promotion |
| `FROZEN_FORWARD_CANDIDATE` | 代码/数据/参数/模型/prompt 已 hash，尚无未来证据 | 并行 PAPER observation |
| `FORWARD_EVIDENCE` | 冻结后逐日累积且 source-bound | 进入正式 review |
| `PROMOTION_PASS` | SPY 硬门、风险/成本/稳健性与最小 forward 时长全部满足 | 仍需既有 promotion 流程 |
| `REVIEW_HOLD` | SPY near-miss 或有非收益型突出性质 | 人工讨论；不得自动写成 PASS |

所有历史输出必须包含 `evidence_scope`、`observed_through` 和
`automatic_promotion_eligible: false`。

## 4. R1：数据与宇宙地基

### 4.1 当前公司候选池

建立 `semantic_ml_company_pool_v1`：

- snapshot date 为运行日，forward start 必须严格晚于 snapshot；
- SEC `company_tickers_exchange.json` 提供 CIK/ticker/exchange；
- 仅 NYSE/Nasdaq 且本地 daily bars 可用；
- snapshot 时要求 last bar fresh<=5 calendar days、price>=5、history>=756 sessions、
  trailing 63-session median dollar volume>=20M；
- 按 snapshot trailing liquidity 取最多 300 名；
- 排除 project blacklist、inverse、short-vol、杠杆 ETF；
- 保存 exact ordered symbols、CIK、名称、exchange、输入 hash、selection timestamp 和代码 commit。

它是“今天冻结、面向明天”的 pool，不是历史 index membership。历史实验仍标 `DEVELOPMENT_ONLY`。

### 4.2 每日 causal eligibility

在固定 pool 内，每个 decision date 只用该日及以前数据计算：

- min history 252；
- trailing 63-session price/volume density>=95%；
- price>=5；
- trailing median dollar volume>=20M；
- last observation 当日可用；
- warmup/missing/delisted 后均不可持有。

mask 必须通过 prefix-invariance 测试：在末尾追加未来 bars，不得改变之前任何 eligibility cell。

### 4.3 价基与 provenance

- feature 可以使用统一 split-adjusted price-return basis；
- 组合收益、SPY gate、候选冻结必须是 distribution-adjusted total return；
- 目标 pool 每个标的必须有 successful split 与 distribution query coverage，且同时覆盖历史起点和 cutoff；
- split coverage 必须逐事件日期/比例与 canonical table 对账；“事件表里没有该 ticker”不能视为零拆股证明；
- `validate_total_return_coverage()` 不通过时，portfolio run fail-closed；
- 所有 source manifest、split/distribution hash 和 observed cutoff 写入结果。

## 5. R2：自动试验台账

实现 append-only JSONL ledger，单写入口、file lock、fsync/atomic replace；每个 trial 在计算前写 intent：

- trial id/content hash；
- hypothesis family、mechanism id；
- universe/data/config/code hash；
- feature/model/label/construction/cost/execution ids；
- seed、train/validation dates、observed boundary；
- parent trial 与是否由前一结果触发。

完成后追加 outcome event，不覆盖 intent。重复 content hash 可复跑验证但不得增加“独立发现”数量。
DSR/PBO 的 trial universe 从账本机械生成；任何影响选择的实际运行都计数，包括失败、near-miss 和
被人工查看后产生的变体。

## 6. R3：numeric rank baseline 与 ML

### 6.1 预注册模型

首轮只允许：

1. equal-weight causal factor rank baseline；
2. linear rank baseline；
3. XGBRanker `rank:ndcg`。

XGB 是浅层 tabular learning-to-rank：它从 feature/label 学非线性排序，不是手写规则。首轮不加神经
网络，除非 XGB 相对 linear/rule 有稳定增量而组合映射仍无法解决。

### 6.2 feature engineering

输入只选机制明确的低维集合：

- momentum/trend/change；
- realized risk/drawdown/liquidity；
- filing-gated quality/growth/accrual（有 PIT coverage 才启用）；
- market/sector context；
- event state。

每个 train fold 内做 winsorize、cross-sectional rank、可选 sector neutralization。feature correlation
clustering 也只能在 train fold fit，选择 cluster medoid 后冻结到 validation；禁止全样本 cluster 后再 CV。
原始文字不能直接喂排序器，必须先经过 R4 的可复现 semantic representation。

### 6.3 label 与验证

- primary：21-session market-residual cross-sectional rank；
- secondary：5-session event residual return；
- purged rolling-origin + embargo；
- model selection 内层完成，外层仅报告；
- 所有历史区间仍是 development，不使用“fresh OOS”字样；
- 报告 IC、ICIR、coverage、calibration、top-minus-universe spread，以及按 year/regime 的稳定性。

### 6.4 组合映射

预注册并严格计数三种 construction，首选第二种：

1. active-only top-10（旧几何的对照）；
2. 35% SPY + 65% active top-10，active 单名<=10%；
3. 35% SPY + 65% active inverse-vol/rank blend，active 单名<=10%。

总 gross<=1、无 margin、无 short、无 inverse ETF。信号在 T close 形成，正式收益必须由
`BacktestEngine` 在 T+1 open 成交，包含 gap、30 bps base cost、2x/3x stress、turnover、missing-open
fail-closed。vectorized close-to-close metric 只能作筛选旁证。

## 7. R4：SEC filing semantic 轨

### 7.1 corpus

- 使用 SEC submissions API/bulk archive 获取 accession、form、items、primary document、
  `acceptanceDateTime`；
- 首轮 forms：8-K Item 2.02/7.01、10-Q、10-K；
- 保存 raw response hash、fetch time、HTTP provenance、document hash、parser version；
- 去 HTML/XBRL boilerplate 后保存 section-level text，不覆盖 raw；
- amendment 与 duplicate accession 显式关联；
- historical signal 一律在 acceptance 后的下一交易日 open 执行。

### 7.2 表征阶梯

按成本由低到高比较，任何高级层必须打败前一层：

1. filing metadata + XBRL/SUE/price-jump baseline；
2. lexical uncertainty/sentiment/readability + TF-IDF linear；
3. frozen FinBERT sentiment/embedding；
4. semantic novelty：当前 filing vs 上次同 form 的 cosine delta；
5. train-only embedding clusters、到 peer centroid 距离、cluster 内 cross-sectional rank；
6. schema-constrained generative LLM event extraction。

LLM 输出必须是版本化 JSON schema，temperature/model/prompt 固定，response 全量缓存并 hash；解析失败
视为 missing，不允许人工补分。LLM 不直接生成 target weight，不读取未来价格或未缓存新闻，不自行改 gate。

### 7.3 模型与 ablation

semantic feature 进入 linear/XGB sidecar；必须报告：

- structured-only；
- text-only；
- structured + text；
- 去掉 sentiment；
- 去掉 novelty；
- shuffled-text negative control。

若 text 对 structured baseline 没有稳定增量，semantic family 关闭但保留 corpus，不用更大模型救结果。

## 8. 候选冻结门

历史开发门只决定“是否值得占用未来 forward 槽位”，不是 promotion：

- after-cost aggregate excess vs SPY > 0；
- >=60% rolling evaluation windows excess > 0；
- worst configured stress MaxDD 不差于 SPY 的 1.25x；
- DSR/PBO/CPCV 无明确过拟合红旗；
- data/price/execution/provenance gates 全 PASS；
- 同一 family 只选一个 sibling；候选间 NAV corr>=0.70 时只保留机制更清楚者。

near-miss：年化 excess 不低于 -1.0 percentage point，且 MaxDD/Calmar/尾部风险显著优于 SPY，可进
`REVIEW_HOLD` 讨论是否 forward；它不自动 drop，也不能被标成 gate PASS。

## 9. 并行 forward

通过冻结门的 rule/ML/event 候选使用同一个 future start session 并行观察：

- frozen artifact 包含 code/config/data/model/prompt/universe/cost/execution 全部 hash；
- forward 期间不训练、不重聚类、不改 prompt、不根据结果换阈值；
- 每个候选独立账户和 manifest，另生成只读组合诊断；
- daily close batch 必须与 collector 实际消费数据绑定；未完成 source-batch bridge 前只允许 replay；
- 先积累 forward，再由统一 SPY gate、风险匹配 passive、DSR/PBO 和人工 review 决定下一步。

## 10. 验收标准

### R1

- universe artifact 可复现且 future append 不改变历史 mask；
- inverse/short-equivalent 0 泄漏；
- total-return coverage 缺一名即组合评估 fail-closed。

### R2

- 并发/崩溃/重复 trial 不丢、不覆盖、不少计；
- DSR N 与 ledger mechanically equal；改 trial 名不能重置计数。

### R3

- synthetic gap-open 证明 T signal -> T+1 open；
- rule/linear/XGB 在完全相同数据、label、cost 和 construction 上比较；
- clustering prefix-invariant 且 train-only；
- SPY 是唯一自动收益 gate，QQQ 仅诊断。

### R4

- accepted timestamp -> next tradable session 的时区/周末/节假日测试；
- raw/document/section/embedding hash 可追溯；
- shuffled-text negative control 不得表现出稳定正 edge；
- 无文本或模型不可用时 structured baseline 正常运行，semantic 不得静默填 0。

### R5

- 只有 frozen candidate 能初始化 forward；
- observed 历史不能写入 sealed store；
- 未完成 trusted source-batch binding 时 readiness 保持 NOT_READY。

## 11. 实施顺序

1. 审计修复与文档冻结；
2. dynamic eligibility + automatic trial ledger；
3. 当前公司池与 corporate-action certification；
4. rule/linear/XGB apples-to-apples baseline；
5. SEC submissions/text corpus + structured/lexical baseline；
6. frozen FinBERT/embedding/cluster ablation；
7. 候选审计、冻结、同日起并行 forward。

任一步的负结果是有效结论；不得通过扩大 search space、改名或继续打开已见历史来制造候选。
