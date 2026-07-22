# PQS V6：PIT 数据地基与条件式 Alpha 挖掘 PRD

版本：1.0

日期：2026-07-22

状态：PROPOSED FOR USER REVIEW

建议实施顺序：`Phase A 数据工程与无收益 QA -> Data Readiness Gate -> Phase B 受限方向性挖掘 -> 同日起 future PAPER`

上位治理：

- `config/research_governance.yaml` schema v3；
- `docs/prd/20260722-annual-spy-relative-dd-strategy-mining-v5-prd.md`；
- `docs/audit/20260722-mining-v5-execution-and-independent-verification.md`；
- `docs/prd/20260721-short-paper-research-lane-prd.md`（独立、未开放的 short lane）。

证据范围：Phase A 为 `DATA_ENGINEERING_NO_DIRECTIONAL_RETURN`；Phase B 的历史结果均为
`DEVELOPMENT_ONLY`，不能被重命名为 sealed/OOS。

## 1. 执行摘要

下一阶段不应继续追加第 31 个 ETF/risk-overlay sibling，也不应先把 XGBoost 换成更大的模型或把 LLM
接到买卖端。V5 的 11 个可运行构造已经给出清晰证据：防御层确实改善了相对回撤，但 broad factor ETF
sleeve 没有产生足够的成本后 alpha 支付收益损耗；其余 company-stock、semantic、ML、LLM 方向不是被
收益门否定，而是因为没有真正历史 PIT universe、PIT fundamental panel 和合规 filing corpus 而无法验证。

本 PRD 因此采用两个严格隔离的阶段：

1. **Phase A：PIT 数据地基。** 建立永久证券身份、历史上市/退市与公司行动、逐 accession 的 as-filed
   fundamentals、acceptance-bound 10-K/10-Q corpus、时段化行业分类和统一 as-of 查询接口。Phase A
   禁止查看任何候选策略收益，因此不增加方向性 trial N。
2. **Phase B：条件式 alpha 挖掘。** 只有 Data Readiness Gate 全部通过并冻结 manifest 后才开放。按
   `rule -> ridge -> constrained GBDT -> deterministic text -> sparse/dense semantic -> constrained LLM`
   的顺序最多运行 20 个方向性 trial；binding raw independent N 从现有 60 继续累加，不能重置。

核心判断是：**历史 PIT universe 不等于历史 S&P 500 成分表。** 本项目可采用“当时全部符合条件的美国
上市普通股”并按当时可见的价格、成交量、上市状态和 filing 信息重建动态 universe，从而避免把指数
委员会选择本身引入策略。真正不可省略的是永久证券身份、完整退市处理、历史公司行动和无 current-
survivor filter 的价格数据。

本 PRD 同时保留一条免费 prospective 路径：从批准日开始冻结官方 current listings 与后续变更，持续积累
真实 PIT security master。它对未来研究有价值，但**不能补造过去的历史 universe，也不能解锁 Phase B
formal historical qualification**。若无法取得研究级历史证券数据，项目应诚实停在 prospective collector
与 `SURVIVOR_BIASED_DEVELOPMENT_ONLY`，而不是用 Yahoo/current SEC 名单冒充 PIT。

## 2. 本轮开工前独立审计结论

### 2.1 可复用资产

当前仓库已经具备下列有效基础，应复用而不是重写：

- `core/research/sec_filing_corpus.py`：解析 submissions main/shard 的 accession 与
  `acceptanceDateTime`；
- `core/research/sec_document_corpus.py`：确定 primary document URL、不可变存储名和 hash；
- `dev/scripts/mining_v4/build_sec_submissions_corpus.py`：限速、重试、原始响应与 manifest；
- `dev/scripts/mining_v4/build_sec_primary_document_corpus.py`：可恢复、不可变 document corpus；
- `core/research/company_pool.py`：适合“今天冻结、面向未来”的 current-company pool；
- `core/research/qualification_v4.py`、canonical SPY、composite trial ledger 与 account-risk layer：继续作为
  Phase B 资格权威；
- exact-cash 与 T+1 open execution 语义：继续作为成交/收益口径，不新建近似回测器。

### 2.2 不可直接用于 formal PIT 的资产

下列实现可以作工程原型，但在修复前不能进入 Phase B 正式 panel：

1. `core/data/edgar_provider.py::get_chain_facts()` 按 `(end, form)` 保留 latest-filed row，会在构造今日
   snapshot 时丢弃同一报告期的早期 as-filed vintage；
2. `FundamentalsStore` 以 `filed` 日作为有效日，而 formal 路径需要逐 accession join submissions 的
   `acceptanceDateTime`，并统一映射到 acceptance 后下一交易 session；
3. 当前 Company Facts tag-chain 是全局、人工排序的 fallback，尚未保存“本次选择了哪个 tag、哪个
   context、哪个 accession、为什么”的逐值 provenance；
4. `semantic_ml_company_pool_v1` 明确是 2026 current snapshot，
   `point_in_time_historical_membership=false`；
5. Nasdaq/SEC current ticker 文件和现有 yfinance/Polygon bars 不能独立证明完整历史退市收益、ticker
   history 与 corporate-action lifecycle；
6. 当前 worktree 只有测试级 EDGAR cache；旧审计中记录的大型 submissions/document corpus 是外部数据
   artifact，不是仓库内可假定存在的依赖，必须通过 manifest 发现而不能靠路径猜测。

### 2.3 V5 负结果对本轮的约束

- 不继续搜索 15% vol target、126/252 SMA、60/40 anchor 或 QUAL/MTUM/USMV 的近邻参数；
- Phase B 主策略先验证无 risk-overlay 的 company-level alpha，防御/账户 sizing 只在 raw candidate 已
  证明收益能力后处理；
- 不能用 2025-2026 已观察结果选择 universe、特征、模型、prompt 或阈值；
- V5 blocked 的 R13-R30 已经消费旧 campaign slot。V6 是绑定新 PIT snapshot 的新协议，不会擦除旧 N；
- LLM 继续只做带 evidence span 的结构化抽取，不直接输出 expected return、权重或 gate verdict。

## 3. 决策原则

### 3.1 优先级

本轮固定优先级为：

`身份/退市/公司行动真实性 > as-filed 基本面 > 低换手规则基线 > 线性 ML > 受限树模型 > 语义 > LLM`

模型复杂度只有在更简单层已经产生可复算的增量问题时才有意义。

### 3.2 三种不能混写的状态

| 状态 | 可以做什么 | 不能声称什么 |
|---|---|---|
| `FREE_PROSPECTIVE_PIT` | 从批准日起冻结 current listing 和未来变更；支持未来 replay | 不能重建批准日前 historical PIT universe |
| `SURVIVOR_BIASED_DEVELOPMENT_ONLY` | 工程 smoke test、性能测试、特征 missingness 诊断 | 不能 formal qualification、不能自动 promotion |
| `FORMAL_HISTORICAL_PIT` | 在 Data Readiness Gate 后运行 Phase B | 仍只是 development，不是 fresh OOS/sealed |

报告、API 和 artifact 必须使用这些精确枚举，不允许用模糊的 `PIT=true` 覆盖不同证据等级。

### 3.3 付费数据决策边界

正式历史轨需要能够提供或等价重建下列字段的数据源：永久证券 ID、名称/ticker/share-class 时段、
上市/退市状态、日频 open/close/volume、分红/拆股/特殊分配、退市日期/原因/收益，以及可追溯的修订
政策。CRSP/WRDS 是可接受的研究级参考实现，但不是本 PRD 强制指定的唯一 vendor。

任何订阅、采购、云资源或付费 API 创建都需要用户显式批准；当前 `cloud.paid_resource_creation_enabled`
保持 false。未获批准时可以完成 adapter、schema、SEC corpus 与 prospective collector，但 Phase B
formal historical lane 必须 fail closed。

## 4. 目标与非目标

### 4.1 目标

1. 建立可逐日 as-of 查询、可 hash、可 replay 的 PIT 数据层；
2. 消除 current-survivor selection、ticker reuse、restatement backfill 和 delisting-last-price 偏差；
3. 生成机器可读 Data Readiness Artifact，独立验证器从 raw manifest 重算；
4. Data Gate 通过后，在最多 20 个方向性 trial 内验证 company-level quality/momentum/low-risk、ridge、
   shallow GBDT、filing semantic 与 constrained LLM 的真实增量；
5. 最多冻结 3 个机制不同的 future PAPER candidate，并在同一未来 session 启动观察；
6. 所有正负结果进入跨 campaign append-only trial universe。

### 4.2 非目标

- 不开放 short、borrow、margin、inverse ETF、期权、期货或杠杆产品；
- 不采购任何资源，不创建真实 broker/LIVE 权限；
- 不把 current S&P/Nasdaq/SEC 名单向历史回填；
- 不要求重建历史 S&P 500 membership；
- 不用 Company Facts 当前 snapshot 的 latest value 覆盖旧时点；
- 不用 filing period end、`filed` 日期午夜或新闻抓取时间替代 public acceptance timestamp；
- 不训练大语言模型、Transformer 或端到端深度选股模型；
- 不进行大规模 hyperparameter search、权重连续优化或 risk-overlay 参数微调；
- 不删除旧 PRD、失败结果、ledger 或历史资格 artifact；
- 不重新打开 2025-2026 作为 pristine/sealed holdout。

short 继续留在独立 PRD。没有 PIT borrow/locate/fee/recall/Rule 201 数据前，不允许因本轮有了股票 PIT
数据就自动开放 short。

## 5. 权威数据来源与准入

### 5.1 可作为正式原始来源

1. SEC EDGAR submissions、Archives filing documents、filing-level XBRL instance；
2. 具备永久证券 ID、退市、历史公司行动与修订政策的研究级证券数据库；
3. 官方交易所 current/daily-list feed，用于 prospective collector 和 vendor reconciliation；
4. 项目现有 canonical SPY total-return snapshot，继续作为 benchmark；
5. 经冻结、版本化并在 outer-train-only 使用的 Loughran-McDonald dictionary 或公开模型权重。

### 5.2 只允许 diagnostic/prospective 的来源

- SEC `company_tickers_exchange.json` 与 Nasdaq current Symbol Directory；
- yfinance current/history 下载；
- current company pool；
- 没有退市收益与 corporate-action completeness 证明的本地 bars；
- current Company Facts aggregation，除非逐 accession 与原 filing XBRL 完成 reconciliation。

### 5.3 网络研究纪律

只有官方机构、监管机构、数据提供者正式文档、同行评审论文和作者 replication package 可以改变设计。
营销回测、博客、社交媒体、匿名策略和未说明 universe/成本/timestamp 的收益数字不得改变参数或 trial
顺序。所有检索 URL、日期、采纳/拒绝理由进入 evidence manifest。

## 6. Phase A：PIT 数据地基

Phase A 禁止调用 candidate portfolio return、SPY excess、Sharpe、MaxDD、IC 或 label 计算。允许检查价格
连续性、事实值、coverage、schema、hash、prefix invariance 和人工抽样，但 QA UI 不得显示后续收益。

### 6.1 A1：永久证券身份与动态 universe

建立 vendor-neutral `security_master_v1`，核心键为项目自有 `asset_id`，vendor permanent ID 作为外键，
ticker 永远不能作为主键。

每条 identity interval 至少包含：

- `asset_id`、`vendor_security_id`、`issuer_id`、CIK（允许为空但有原因）；
- ticker、名称、exchange、share class、security type、domicile；
- `valid_from_session`、`valid_to_session_exclusive`；
- list/delist date、delist code、successor/predecessor link；
- common-stock/ETF/ADR/preferred/unit/test-issue flags；
- source record ID、source as-of、ingested-at、raw payload hash、schema version。

初始正式 universe 固定为美国主要交易所上市的美国发行人普通股；排除 ETF/ETN、ADR/foreign ordinary、
preferred、rights/warrants/units、SPAC pre-combination units、OTC、test issue、inverse/leveraged products。
这样可避免在首轮同时引入 IFRS、外币、20-F/6-K 与 ADR ratio 复杂度。

每个 decision month-end 用当时已知数据重建 eligibility：

- 已上市且尚未退市；
- 至少 504 个已完成 sessions；
- trailing 63-session 价格/成交量 density>=95%；
- decision close>=5 美元；
- trailing 63-session median dollar volume>=20M 美元；
- 最近一 session 有可估值价格；
- 按 trailing liquidity 最多保留 600 名，不使用未来 market cap 或完整样本期 liquidity；
- eligibility 在 month-end close 冻结，最早下一 session open 生效。

阈值全部写入 `config/pit_data_v1.yaml`。改变任一阈值需要新 data-contract version；Data Gate 之后改变还
需要新 directional protocol，不能在同一 V6 trial 内静默更新。

### 6.2 A2：价格、公司行动与退市

正式 daily store 必须同时保留 raw 与派生口径：

- raw open/high/low/close/volume；
- split factor、cash distribution、special distribution；
- total return 与 ex-distribution return；
- delisting return/price/date/code；
- trading status、halt/stale/missing flags；
- vendor revision/as-of 和项目 ingest hash。

执行与估值继续遵循 T close signal -> T+1 open fill -> T+1 close mark。发生退市时必须使用 source-bound
delisting return/consideration 或明确的 bankruptcy liquidation rule；**不得按最后一个 stale close 无损
清仓**。缺少退市处置的 held position 使整个 formal trial fail closed。

股票 total-return、成交 open 和 benchmark 需要各自保留，不允许用 adjusted close 推算无法审计的 open。
公司行动变换需满足：raw -> adjusted execution/valuation -> exact-cash recurrence 三方可逆或可解释对账。

### 6.3 A3：逐 accession 的 as-filed fundamentals

正式 `pit_fundamental_fact_v1` 的原子记录是 filing accession 内的一个 XBRL fact，不是“公司-季度最新值”。
至少保存：

- CIK、asset/issuer mapping、accession、form、amendment lineage；
- acceptance UTC、filing/report dates、period start/end、fiscal year/period；
- taxonomy/version、namespace、concept、label、unit、decimals、scale；
- dimensions/context ID、value、nil flag、document/instance hash；
- `available_from_session`；
- parser version、selection-rule version、source URL/hash。

availability 规则固定为：

`available_from_session = first exchange session strictly after SEC acceptanceDateTime`

即使 filing 在开盘前被接受，首版仍统一延迟到下一 session，以降低日频执行歧义。周末、节假日、时区和
DST 必须走 exchange calendar。缺少 acceptance timestamp 的 fact 进入 quarantine，不能回退到 period end。

10-Q/A、10-K/A 和 restatement 必须追加新 vintage；在 amendment acceptance 前，as-of query 仍返回旧值。
`companyfacts` 可用于 coverage/reconciliation，但正式值优先从 accession-bound filing XBRL instance
重建。现有 `get_chain_facts()` 的 latest-wins 输出不得进入正式 panel。

### 6.4 A4：概念标准化与财务特征

先冻结最小、可解释的 concept set，不一次性搬入 factor zoo：

- revenue、gross profit、operating income、net income、CFO、capex；
- total/current assets、total/current liabilities、cash、long-term debt、equity；
- shares outstanding、accounts receivable、inventory、PPE；
- filing-level restatement/amendment、auditor/going-concern（若有可靠结构字段）。

标准化规则：

1. tag mapping 是版本化规则，不根据回测收益排序；
2. duration fact 区分 standalone quarter、YTD 与 annual，不以简单 rolling sum 猜测；
3. dimensions 不可无条件聚合，合并值与 segment 值必须分开；
4. currency/scale/unit 必须显式转换并记录；
5. 任一 non-null standardized value 可回溯到唯一或明确列出的 source facts；
6. 缺失保持 NA，不用横截面未来中位数或 current filing 回填；
7. TTM 与同比基于 as-of 当时已公开 vintage 计算；
8. financial sector 的概念可比性不足时，首轮允许单独 feature schema 或直接排除，不用通用 tag 硬套。

### 6.5 A5：acceptance-bound 10-K/10-Q corpus

复用现有 submissions/document builder，但把输入从 current 300-company pool 改为 historical issuer set。
正式 corpus 只纳入 10-K、10-Q 及其 amendments；8-K 保留历史诊断，不进入本轮主信号。

每份文档必须绑定：CIK、asset/issuer interval、accession、form、acceptance UTC、primary document、
document hash、content type、parser version、section spans 与 available-from session。

文本层按以下优先级解析：

1. filing metadata 与数值变化；
2. 同公司、同 form、相邻 filing 的 section-level delta；
3. LM dictionary；
4. outer-train-only TF-IDF/SVD；
5. frozen encoder；
6. outer-train-only cluster/semantic peer；
7. constrained LLM extraction。

正文缺失、HTML 异常或 section 解析失败不能静默丢弃。coverage 和 failure reason 必须进入 panel，避免只
对容易解析的大公司形成隐藏选择。

### 6.6 A6：行业/peer 时段化

sector-neutral 不是默认安全操作。只有存在有效时段与 source provenance 的历史 SIC/GICS/NAICS 等分类时，
才能进入 formal feature。当前 SEC company metadata 的 current SIC 不能向历史回填。

若 vendor 未提供时段化 sector：

- rule baseline 使用不依赖 sector 的 global cross-sectional rank；
- ML label 使用 SPY beta-residual return，而不是虚构 sector residual；
- B10 sector-neutral trial 记录 `BLOCKED_NO_PIT_INDUSTRY`，且不会临时改成 current sector；
- semantic peer 只从 outer-train filing representation 构建，不等同于官方 sector。

### 6.7 A7：统一 as-of API

所有训练、回测和 PAPER 调用同一 read interface：

```text
get_security_state(asset_id, decision_session)
get_eligible_assets(decision_session, universe_contract_id)
get_price(asset_id, session, basis)
get_fundamental(asset_id, concept_id, decision_session)
get_filing_documents(asset_id, decision_session, forms)
get_industry(asset_id, decision_session)
```

每个返回值必须附 provenance reference。API 禁止 `latest=true` 之类可能绕开 as-of 的 production shortcut。
历史研究与 PAPER 只能改变 cutoff，不改变语义。

### 6.8 A8：免费 prospective collector

在不采购数据的情况下，建立每日 append-only collector：

- 冻结 Nasdaq/official listing current snapshot 与 daily additions/deletions/symbol changes；
- 冻结 SEC company ticker、submissions、filing/XBRL 更新；
- 冻结项目实际消费的 market-data source batch；
- 每日生成 diff、hash chain、缺失/延迟告警；
- 不回写历史 interval，不用 later snapshot 修饰 earlier snapshot；
- 从批准日后的第一个完整 session 起产生 `FREE_PROSPECTIVE_PIT` 证据。

它与历史 vendor adapter 共用 schema，但 evidence scope 永远由 source manifest 决定。

## 7. Data Readiness Gate

Data Gate 的所有阈值只使用 metadata/coverage/人工 fact 核对，不查看策略收益。

### 7.1 必须全部通过的硬门

| ID | Gate | 通过标准 |
|---|---|---|
| G1 | Identity integrity | 所有 formal rows 有永久 `asset_id`；有效区间不重叠；ticker reuse/name/share-class changes 不破坏 identity |
| G2 | No current-survivor filter | historical eligible set 从当时 listing state 机械生成；不存在 current ticker/company intersection |
| G3 | Delisting completeness | 每个 held/eligible delisted asset 有 source-bound disposition；缺失时 formal lane fail closed |
| G4 | Corporate-action parity | raw、adjustment ledger、total-return recurrence 与 vendor return 在冻结容差内；所有差异有 disposition |
| G5 | Fundamental provenance | 每个 non-null standardized value 100% 回溯 accession/context/unit/value；无 latest-wins overwrite |
| G6 | Acceptance timing | 100% used facts/docs 有 acceptance UTC 与严格 next-session availability；缺失值不回退到 filed/period end |
| G7 | Vintage replay | 任一 cutoff 的 fact/feature 只由 cutoff 前 raw records 重建；未来 append/mutation 不改变历史输出 |
| G8 | Corpus provenance | 100% included documents 有 accession/hash/acceptance/parser version；解析失败显式计入 coverage |
| G9 | Universe breadth | 2012-2024 每个正式 rebalance 至少 200 eligible assets，年度中位数至少 300；不足则缩短/阻断而非放宽阈值 |
| G10 | Feature coverage | 主 rule composite 在每个正式 rebalance 至少覆盖 150 assets，年度中位数至少 250；missingness 按年/行业报告 |
| G11 | Temporal tests | prefix invariance、future append、future mutation、weekend/DST、amendment、ticker change、delist 全部 PASS |
| G12 | Immutability | raw snapshot、contract、code、schema、calendar、source license/edition 与 verifier 全部 hash-bound |

G9/G10 是容量/统计最低线，不是为得到更好收益而挑选的参数。若免费或已获数据无法达到，项目应报告
`BLOCKED_INSUFFICIENT_FORMAL_PIT_COVERAGE`，不得回到 current top-300 pool 补数。

### 7.2 人工独立抽样

在不知道未来收益的前提下，分层抽取至少：

- 50 个 identity/corporate-action cases，包括 ticker change、merger、spin-off、delist、bankruptcy、dual class；
- 200 个 standardized fundamental values，覆盖 10-K/10-Q/amendment、不同年份/行业/tag/dimension；
- 100 份 filing section spans，覆盖 parser success/failure；
- 所有缺失 delisting disposition 和所有 reconciliation exception。

两名审阅者独立检查；分歧由第三人裁决。样本 precision 不是替代机器 gate：任何确认的 lookahead 或
identity collision 都使 G1/G5/G6/G7 失败并要求修复后重新抽样。

### 7.3 Data Readiness Artifact

建议输出：

- `config/pit_data_v1.yaml`；
- `research/data_readiness/pit_v1/data_contract.json`；
- `research/data_readiness/pit_v1/source_manifest.json`；
- `research/data_readiness/pit_v1/coverage.parquet`；
- `research/data_readiness/pit_v1/exceptions.parquet`；
- `research/data_readiness/pit_v1/manual_review.json`；
- `research/data_readiness/pit_v1/readiness.json`；
- `scripts/verify_pit_data_readiness.py`；
- `docs/audit/YYYYMMDD-pit-data-readiness-independent-verification.md`。

大体积 raw 数据不进入 git，但 manifest、schema、small QA fixtures、license boundary 与 hashes 必须可审计。

### 7.4 Phase B 解锁条件

Phase B 只有同时满足下列条件才生效：

1. G1-G12 全 PASS；
2. 独立 verifier 从 clean commit 重算 PASS；
3. readiness artifact 明确 `FORMAL_HISTORICAL_PIT`；
4. data/evaluation contract、calendar、universe cutoff、raw independent N>=60 已冻结；
5. 用户对任何新增付费数据使用范围已显式批准；
6. 在首个 directional intent 前，代码未读取任何 V6 candidate return。

若任一条件失败，Phase A 仍可继续改进，Phase B 不创建 blocked trial intents，binding N 保持 60。

## 8. Phase B：条件式 Alpha 挖掘

### 8.1 时间范围与证据语义

- 原始数据可从 2007 起用于 warm-up/identity reconciliation；
- 正式 development evaluation 固定为 2012-01-03 至 2024-12-31，若 G9/G10 要求更晚起点，只能由
  coverage 机械决定并在看收益前冻结；
- 2025-01-01 至 2026-07 已观察，完全排除在模型选择与 qualification 外；
- future PAPER start 严格晚于最新实际观察 session，并绑定 collector source batch；
- historical PASS 仍标 `DEVELOPMENT_ONLY`，不是 sealed OOS。

### 8.2 特征与规则基线

初始规则 family：

1. **profitability**：gross profitability、ROA/ROE、CFO/assets、operating margin；
2. **conservative accounting/investment**：低 accrual、低 leverage、低 asset growth、无异常 dilution；
3. **momentum**：12-1 与 6-1 total return rank，跳过最近 21 sessions；
4. **low risk**：低 252-session SPY-residual volatility 与低 63-session realized volatility。

所有 accounting feature 使用 acceptance 后下一 session 可见的 vintage；所有横截面 winsorization/rank
只用当日 eligible cohort。规则方向来自经济定义和冻结文献，不根据全样本 IC 翻转。

主 composite 固定为 family rank 等权。行业不可得时使用 global rank；行业可得时只在单独 ablation 中
测试 sector-neutral，不能把结果更好的版本事后设为默认。

### 8.3 组合构造

每个 signal 的 binding 完整组合固定为：

`70% SPY anchor + 30% company-stock alpha sleeve`

alpha sleeve：

- 季度常规换仓，月末只更新 eligibility/risk exit；
- enter top 15%，跌出 top 35% 才退出；
- 最短持有 63 sessions；
- 目标 20 名，sleeve 内等权；
- 单名总 NAV<=2.5%，top-3<=7.5%；
- 若 PIT sector 可用，单 sector 总 NAV<=30%；
- 少于 12 个合格名称时未分配 sleeve 回到 SPY，不用 BIL 稀释收益门；
- 退市、交易停止、数据失真可即时 risk exit；
- T close signal，T+1 real open 成交，整数股/现金/缺失 open 与 PAPER 同核。

同时报告 alpha sleeve standalone 结果用于机制诊断，但 formal gate 只评价完整 70/30 组合。V5 已证明
简单 risk overlay 可能吃掉 alpha，因此 Phase B 不把 vol/trend overlay 叠到每个 trial。只有 raw full
portfolio 通过 return 与 Balanced D1-D5 后，才进入既有 account-deployment risk layer。

### 8.4 ML 任务与 split

primary label 固定为 63-session forward SPY-beta-residual total-return cross-sectional rank。只有 PIT industry
通过 G1/G11 后，B10 才可单独测试 sector residual label。21-session label 仅诊断。

outer validation 使用 expanding rolling-origin：

- 首个 train 至少 5 年；
- outer validation 为下一个完整 calendar year；
- 63-session purge/embargo；
- inner train folds 只选择预注册小网格；
- scaler、winsorizer、imputer、feature selection、SVD、cluster、encoder normalization 全部 train-only；
- missing indicator 与 coverage feature 可用，但不能把 future coverage 当信号；
- outer predictions 只允许一次写入不可变 artifact。

模型阶梯：equal-weight rule -> ridge/elastic-net ranker -> shallow constrained GBDT。GBDT max depth、leaf
count、feature subsampling 和 monotonic constraints 写入 Phase B contract；不进行 Bayesian/large grid search。

### 8.5 semantic 与 LLM 增量门

高级文本层只有同时满足下列条件才可进入下一层：

- 相对前一级，在至少 60% outer folds 的 incremental rank IC 为正；
- matched cohort、matched dates、matched missingness；
- shuffled text、future mutation、section shuffle、ticker permutation 负对照不产生稳定 edge；
- 30/60/90 bps 完整组合相对前一级有经济增量；
- 不由单一年份、行业或极少数文档覆盖驱动；
- turnover 与容量不恶化到无法执行。

LLM 只可抽取：风险因素变化、流动性/going-concern、客户/供应商集中度、会计政策/非经常项目、资本
开支/资本配置和原文明示 guidance。输出必须有 JSON schema、evidence spans、confidence 与
missing/ambiguous reason。禁止 expected return、buy/sell、target weight、gate verdict。

LLM formal 入场还要求 pinned/replayable model 或 exact immutable API snapshot、prompt/model/tokenizer/hash、
temperature/seed/retry order、request/response archive，以及不知道收益的双人 QA：schema validity=100%、
field precision>=95%、evidence-span support>=98%。失败则 B20 关闭，不换模型补位。

## 9. Phase B 的 20 个方向性 trial

下表在 Data Gate 通过后生成 immutable preregistration manifest；每行首次计算前写 ledger intent。上游 family
gate 失败后，下游行记录 `BLOCKED_*` 并消费 slot；不得用临时 sibling 回填。

| ID | 完整组合/机制 | 目的 |
|---|---|---|
| B01 | 70% SPY + 30% causal-liquidity equal-weight control | 测量动态 universe/构造本身，不宣称 alpha |
| B02 | profitability rule | 单独验证盈利质量 |
| B03 | conservative accounting/investment rule | accrual/leverage/asset-growth 独立证据 |
| B04 | momentum rule | 12-1/6-1 低换手动量 |
| B05 | low-risk rule | residual/realized volatility 独立证据 |
| B06 | quality composite(B02+B03) | 质量内部互补 |
| B07 | quality + momentum | 主要双 family 规则基线 |
| B08 | quality + momentum + low-risk | 主三 family 规则基线 |
| B09 | B08 去 enter/hold buffer，其余相同 | 唯一 turnover-buffer ablation |
| B10 | B08 + PIT sector-neutral rank/label | 只有 PIT industry gate 通过才运行 |
| B11 | ridge numeric ranker | 规则对线性学习 |
| B12 | shallow constrained GBDT | 受限非线性交互增量 |
| B13 | structured filing-change rule 作为唯一 sleeve score | accession-bound deterministic text standalone baseline |
| B14 | B13 + LM dictionary delta | 金融词典增量 |
| B15 | B13 + train-only TF-IDF/SVD novelty | 稀疏语义增量 |
| B16 | B13 + frozen encoder novelty | dense representation 增量 |
| B17 | B08 + train-only semantic-peer residual | clustering/peer manipulation 的独立价值 |
| B18 | 机械最佳 numeric + structured sidecar | 规则/ML 与低自由度 filing 组合 |
| B19 | B18 + 机械最佳非 LLM semantic sidecar | 只有 B14-B17 增量门通过才运行 |
| B20 | B19/B18 + schema-constrained LLM extraction | 只有 QA 与所有前级增量门通过才运行 |

sidecar 组合固定为 `75% numeric rank + 25% sidecar rank`，不连续搜权重。B02-B12 的 mechanical numeric
winner、B14-B17 的 semantic winner 按第 10 节选择，不能人工挑“看起来最合理”的组合。

任何额外查看的 feature family、lookback、top-N、anchor weight、buffer、label horizon、model seed ensemble、
prompt 或 sidecar weight 都是新 trial，并使本轮相应提前达到 20-trial 上限。

## 10. 机械选择与 family closure

同一阶段 winner 按以下字典序选择：

1. data/timing/replay/negative-control 全 PASS；
2. 通过 Qualification V4 的 return、Balanced D1-D5、DSR/PBO/MinBTL/CPCV 与实现门；
3. 90 bps 后 CAGR excess；
4. SPY material episodes 中最差 drawdown improvement；
5. 36-month rolling excess win fraction；
6. 较低 annual turnover；
7. 较低模型自由度与更高 coverage。

若没有 formal PASS，不从 near-miss 中强制选 winner。某高级 family 的 incremental gate 失败即关闭，不以
更大模型、更多 embedding、更多 prompt 或多 seed ensemble 继续“救”。

同 family NAV correlation>=0.70 最多冻结一个。不同 family 也要报告 raw/active return、drawdown-state、
holdings 和 factor-exposure correlation；不能靠模型名字制造多样性。

## 11. 治理、trial N 与资格门

### 11.1 Trial accounting

- V6 开始时 binding `raw_independent_n>=60`；
- Phase A 不计算方向性 return/IC/label，不增加 N；
- Phase B 每个 B01-B20 intent 至少增加 1，最大 raw N>=80；
- 30/60/90 bps 是同一 target path 的成本情景，不重复计为独立 hypothesis；
- mechanical inner-CV 不单独计数，前提是 grid 预注册且 inner 结果不被人工用于产生新模型；
- crash/replay 使用相同 content hash，只追加 corrective event，不虚增独立 N；
- 所有失败、blocked、near-miss、手工查看后产生的变体都进入 append-only ledger。

### 11.2 Qualification V4 不放松

本 PRD 不修改现行 gate。正式 candidate 必须至少满足：

- base 30 bps 后 CAGR 严格大于 canonical costless SPY；
- 60 bps 后 CAGR 不低于 SPY；90 bps 强制报告；
- base/60 bps month-end trailing 36-month excess-positive fraction>=60%；
- DSR statistic>=0.95、PBO<=0.50、MinBTL PASS、CPCV stability PASS；
- prefix invariance、future mutation、deterministic replay、next-open execution PASS；
- Balanced Drawdown D1-D5 在所有 binding cost scenarios PASS：
  - D1 full-period relative MaxDD strict win；
  - D2 trailing 36-month relative MaxDD win fraction>=60%；
  - D3 每个 SPY-defined >=15% material episode strict win；
  - D4 monthly downside capture<100%；
  - D5 任一完整年度 MaxDD 相对伤害不超过 3pp；
- clean commit、governance/evaluation/data/universe/code/model/ledger hashes 全绑定。

calendar-year strict all-win 不恢复；绝对回撤也不从账户层偷渡回 raw-strategy gate。

### 11.3 账户绝对风险层

formal raw candidate 仍不等于可部署账户。进入 `RISK_GOVERNED_PAPER_ELIGIBLE` 前，deployed composite
必须由冻结、无杠杆、可 replay 的 account sizing/risk layer 证明：

- operating MaxDD target band 15%-20%；
- GFC-2008、Covid-2020、rate-hike-2022 可真实重放路径 MaxDD<=25%；
- terminal weighted shock 不能冒充 path PASS；
- evidence 不完整只能 `SHADOW_PAPER_OBSERVATION`；
- 本阶段 `capital_eligible=false`。

## 12. 停止条件与失败处置

Phase A 停止条件：

- G1-G12 全 PASS，转 Phase B；或
- 数据采购/授权缺失使 formal lane 无法推进，输出 `BLOCKED_EXTERNAL_DATA_AUTHORITY`，但 prospective
  collector 可继续；或
- 事实证明当前可得数据无法满足最小 coverage，输出完整 negative readiness report。

Phase B 立即停止于以下较早者：

1. 3 个机制不同的 formal candidate；
2. 20 个方向性 trial 全部消费；
3. data integrity 失效；
4. raw N/contract/observed boundary 无法证明；
5. family closure 后已无预注册可运行方向。

正式 gate 失败默认 `REVIEW_HOLD`，不自动删除；数据真实性失败为 `BLOCKED_DATA`；只有裸 IC、没有成本后
组合增量为 `REJECTED_NO_ECONOMIC_INCREMENT`；manual exception 必须用户显式批准且永不重标 machine PASS。

## 13. PAPER forward

最多 3 个通过者在同一个未来 session 并行进入 PAPER：

- 每个 candidate 独立 signed manifest/account；
- code/config/data/model/prompt/universe/cost/execution/source batch 全 hash；
- raw shadow 与 risk-governed account 分开；
- forward 期间不重训、不重聚类、不改 prompt/threshold/universe contract；
- prospective listing/filing/price collector 与 runtime 实际消费 batch 必须一致；
- 最少 252 future sessions 前不得自动 promotion；
- 未满 756 future sessions 不得声称完成 36-month forward drawdown gate；
- forward 结果只能触发 review/kill，不给后续 mining 反馈，除非关闭当前 protocol、计入已观察边界并新建
  campaign。

## 14. 实施顺序

### Phase A0：合同与只读审计

1. 冻结 `pit_data_v1` schema、evidence scope、license boundary 和 no-return guard；
2. inventory 现有外部 SEC corpus、market data、ref tables 与 hashes；
3. 对 existing current-pool/Company Facts path 加 formal-lane fail-closed 标签；
4. 建立 fixtures：ticker reuse、amendment、restatement、delist、split/dividend、weekend acceptance。

### Phase A1：身份/价格适配器

1. 实现 vendor-neutral security master 与 interval validator；
2. 实现 corporate-action/delist adapter；
3. 实现动态 universe 与 current-survivor negative control；
4. 同时启动 free prospective collector。

### Phase A2：SEC as-filed 层

1. 将 historical issuer set 接入 submissions/document corpus；
2. accession join acceptance timestamp；
3. filing-level XBRL raw facts 与 standardized fact selection；
4. amendment/restatement vintage replay；
5. 10-K/10-Q section corpus 与 parser coverage。

### Phase A3：统一 API 与 Data Gate

1. as-of API；
2. prefix/future-mutation/identity/delist tests；
3. coverage + manual QA；
4. readiness artifact 与独立 verifier；
5. clean commit 上重跑。

### Phase B0：冻结研究合同

1. 绑定 PIT snapshot、calendar、2012-2024 date index、canonical SPY；
2. 绑定 20-trial matrix、models、feature schema、portfolio、cost 和 Qualification V4；
3. 绑定 composite raw N>=60；
4. 启用 directional-return permission，写 B01 intent。

### Phase B1-B5：顺序挖掘

1. B01-B10 rules/ablation；
2. 只有规则 baseline 有经济意义时运行 B11-B12；
3. 只有 structured filing baseline 有 coverage/增量时运行 B13-B17；
4. 机械组合 B18-B19；
5. 只有 pinned model + QA 完整时运行 B20；
6. 达到停止条件后输出 campaign report，不追加 sibling。

## 15. 必须验收的测试

### 15.1 身份、universe 与退市

- 同一 ticker 先后属于不同证券时 asset_id 不合并；
- ticker/name/exchange change 保持正确 issuer/security lineage；
- current-company intersection negative control 必须与 formal universe 不同；
- future listing/delisting append 不改变历史 eligibility；
- delisted held asset 不会永久 stale mark，也不会按无损 last close 清仓；
- share class、ETF、ADR、preferred、unit/test issue 排除规则可解释并可 replay。

### 15.2 Fundamentals

- initial filing 与 amendment 在各自 acceptance 前后返回正确 vintage；
- 同一 period 的 early value 不被 latest filing 从历史抹除；
- 10-Q standalone/YTD、10-K annual、dimensions、units、scale 测试；
- Company Facts reconciliation discrepancy fail closed；
- 每个 standardized value 可回源到 accession/context；
- filing accepted 周末/节假日/DST 时映射到严格下一 session；
- future accession append 与 future value mutation 不改变历史 feature。

### 15.3 文本/ML

- section parser failure 不被静默排除；
- vectorizer/SVD/cluster/scaler/model 仅 train fold fit；
- validation issuer/doc 不进入 train vocabulary/centroid；
- shuffled/future-mutation/section-shuffle/ticker-permutation controls；
- LLM schema/evidence-span/replay/QA；
- outer predictions append-only 且不可被 retrain 覆盖。

### 15.4 组合、资格与账本

- T close -> T+1 real open；
- integer shares、cash、cost、missing open、corporate action 与 PAPER parity；
- 30/60/90 bps target path 同源；
- Qualification V4 从 raw daily returns 重算；
- B01-B20 前置 intent、crash replay、content-hash dedupe；
- Phase A 尝试读取 return/label/IC 时 runner 拒绝；
- 第 21 个未经授权 directional intent 被 runner 拒绝；
- binding raw N 永不低于 60 + 已消费 V6 intents。

## 16. 主要风险与预先处置

| 风险 | 处置 |
|---|---|
| 数据源费用或许可不可接受 | 保留 adapter + free prospective collector；formal historical lane fail closed |
| Company Facts restatement/backfill | filing-level accession facts 为 SoT；Company Facts 只 reconciliation |
| ticker/CIK 映射错误 | security-level permanent ID + issuer interval；CIK 不作为证券唯一 ID |
| 小公司 XBRL/文档 coverage 低 | 缺失显式保留；G9/G10 阻断，不 current-survivor 补齐 |
| 模型自由度再膨胀 | 20-trial cap、family closure、机械 winner、无大网格 |
| 语义模型只学行业/公司规模 | matched cohort、PIT sector/semantic peer controls、negative controls |
| LLM 不可重放/幻觉 | evidence spans、pinned snapshot、双人 QA；失败即关闭 |
| 70/30 anchor 稀释 stock alpha | sleeve standalone 仅诊断；binding full portfolio 保持用户可实现目标 |
| risk overlay 再次吃掉收益 | 不在挖掘期叠加；formal alpha 后才走账户层 |
| 历史开发被误称 OOS | `DEVELOPMENT_ONLY`、observed boundary 与 future start hash-bound |

## 17. 权威资料

- [SEC EDGAR APIs：submissions、Company Facts 与 nightly bulk archives](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
- [SEC EDGAR fair access：当前自动化访问上限 10 requests/second](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)
- [SEC EDGAR XBRL Guide](https://www.sec.gov/files/edgar/filer-information/specifications/xbrl-guide.pdf)
- [Nasdaq Symbol Directory：信息为 current trading day](https://www.nasdaqtrader.com/trader.aspx?id=symbollookup)
- [Nasdaq Daily List specification：add/delete/name/symbol changes](https://www.nasdaqtrader.com/content/technicalSupport/specifications/dataproducts/dlspec_1130prior.pdf)
- [CRSP US Stock Databases：PERMNO permanent security identity](https://www.crsp.org/research/crsp-us-stock-databases/)
- [WRDS CRSP stock structure：prices、returns、corporate actions、delisting](https://wrds-www.wharton.upenn.edu/pages/grid-items/crsp-stock-database-structure/)
- [Quality Minus Junk, Review of Accounting Studies](https://link.springer.com/article/10.1007/s11142-018-9470-2)
- [Momentum Crashes, Journal of Financial Economics](https://www.sciencedirect.com/science/article/pii/S0304405X16301490)
- [A Taxonomy of Anomalies and Their Trading Costs, Review of Financial Studies](https://academic.oup.com/rfs/article-abstract/29/1/104/1844518)
- [Empirical Asset Pricing via Machine Learning, Review of Financial Studies](https://academic.oup.com/rfs/article/33/5/2223/5758276)
- [Lazy Prices, Journal of Finance](https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12885)
- [Loughran-McDonald 10-K dictionaries, Journal of Finance](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2010.01625.x)
- [Text-Based Network Industries, NBER](https://www.nber.org/papers/w15991)

## 18. 最终建议

建议批准本 PRD 的总体方向，但把批准拆成两个权限：

1. **Phase A GO**：立即做 schema、适配器、SEC as-filed、free prospective collector、测试与 Data Gate；
   全程禁止方向性收益计算。
2. **历史数据源 MUST-DECIDE**：在已有访问权审计后，由用户决定是否使用 CRSP/WRDS 或其他满足同等
   合同的数据源；未批准任何付费行为。
3. **Phase B CONDITIONAL GO**：仅在 G1-G12 全 PASS 后自动按本 PRD 的 20-trial matrix 开始；不再为
   “是否先试一个模型”单独开口子。

这条路线不会保证挖出盈利策略，但它能让下一次“通过/失败”真正回答 company-level alpha 是否存在，而
不是再次回答免费 current-survivor 数据和复杂模型能否在已看历史上拟合出漂亮数字。
