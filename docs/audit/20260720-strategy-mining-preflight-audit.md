# PQS 策略挖掘开工前独立审计

日期：2026-07-20

状态：完成；本文是新挖掘 PRD 的事实输入，不是候选晋升结论

治理上游：`config/research_governance.yaml`

## 1. 审计结论

下一步不应再开一轮广义 factor-zoo，也不应把“换成 XGBoost/Transformer/LLM”本身当作进步。
现有失败的主要约束依次是：价格证据覆盖、静态宇宙回看选择、组合映射与风险、诚实试验计数，以及
真正未见未来数据；模型复杂度不是第一约束。

推荐路径是：

1. 建立以当前日期冻结、面向未来 forward 的公司候选池，并在每个历史决策日继续使用 trailing-only
   eligibility；历史结果只标 `DEVELOPMENT_ONLY`。
2. 在同一数据和 T+1 open 引擎上比较规则基线、线性 ranker 和 XGBRanker；首选组合不是旧的
   100% top-N，而是受约束的 SPY core + active sleeve。
3. 另建机制独立的 SEC filing/event 语义轨；先用可解释 lexical/FinBERT/embedding 特征，生成式
   LLM 只做有 schema 的事件抽取和研究去重，不直接输出买卖分数。
4. 每个实际尝试自动写入 append-only trial ledger。通过开发门的不同机制候选一起冻结、从同一未来
   日期并行 forward；历史开发结果不自动 promotion。

## 2. 已核验的事实

| 项目 | 实际状态 | 判断 |
|---|---|---|
| 历史挖掘 | 约 16 轮主要尝试，0 个仍具可投资证据的新增策略 | 继续同构 top-N factor 搜索的边际收益很低 |
| 排名 ML | canonical XGB `rank:ndcg`、Linear/LGBM 基线、purge/embargo 已存在 | XGBoost 是真正的 learning-to-rank ML，不是 rule-based |
| S6 真验证 | plain XGB 平均 Sharpe 0.9732、最差 MaxDD -26.11%；10% vol target 平均 Sharpe 0.8484、PBO 0.968 | 信号可能有信息，但两个组合配置都不可晋升 |
| 旧 LLM | 26 个公式候选只留下 1 个 research factor，最终组合仍未过 SPY | 再让 LLM 生成 OHLCV 公式不是首选 |
| PEAD | SUE/price-jump、T+1 open engine 已存在 | 机制不同，值得保留；filing date 是保守代理，不是 earnings timestamp |
| EDGAR 本地库 | 54 家、约 211 MB，仅 Company Facts；无 submissions、正文、transcript/news | 现在没有可直接训练语义策略的文本 corpus |
| 日频/分钟数据 | 日频 25,344 个 parquet，1m 同规模；约 137 GB 总数据 | 数据广度足够做新宇宙，但现有挖掘器没有诚实利用 |
| expanded_v2 | 1,000 名，含 ATVI/BBBY/SIVB 等已退市/停牌名称 | 并非纯 current-survivor 池，但不是 PIT membership |
| 算力 | 10 CPU、23 GiB RAM、GTX 1650 Ti 4 GiB；XGBoost/LightGBM/Torch 可用，Transformers 未装 | 排名树模型和冻结 encoder inference 可行；大模型训练不合理 |

## 3. 必须先修的问题

### P0-A：expanded_v2 的历史 OOS 语义不成立

生成器实际用截至 2024-12-31 的完整窗口按 median dollar volume 选出静态名单，然后部分实验回头
评价 2018/2019/2021/2023。这会把未来流动性和存活信息带回早期年份。配置还错误写成
`start<=2009 / rows>=3000 / completeness>=0.95`，实际实现是 `rows>=2000 / completeness>=0.90 /
无 start hard filter`。

已修：

- `config/universe_expanded_v2.yaml` 明确为 `research_candidate_pool_only`、`DEVELOPMENT_ONLY`、
  `point_in_time_membership: false`、禁止历史 OOS 声明；
- 生成器与配置恢复一致；
- 旧 JSON 保留原样作历史证据，不篡改旧结果。

### P0-B：inverse ETF 漏过 long-only/no-short 边界

expanded_v2 中有 15 个已知 inverse/short-equivalent 产品，旧 blacklist 只覆盖 6 个。实际漏过：
`DUST/JDST/LABD/QID/SCO/SDOW/SH/SVXY/TBT`。

已修：补入 blacklist；resolver 对 executable/expanded_v1/expanded_v2 均无上述泄漏。

同时发现 expanded_v2 中有 16 个杠杆多头产品，而旧风险帽只覆盖 TQQQ/SOXL。已把池内所有已知
leveraged-long 加入 high-risk 列表和 10% single-name cap。新股票 rank 策略默认仍不使用杠杆产品。

### P0-C：1000 名池尚不具备统一 total-return 价格证据

expanded_v2 的覆盖实测：

| 证据 | 覆盖 |
|---|---:|
| bar provenance | 998 / 1000 |
| split 事件表中出现过 | 409 / 1000（无事件不等于缺失，不能据此单独判错） |
| dividend/distribution query coverage | 74 / 1000 |
| canonical daily source boundary | 74 / 1000 |

`BarStore(adjusted_total_return=True)` 对无 distribution 行的标的会 no-op；只有
`validate_total_return_coverage()` 能区分“确实无分红”和“根本未查询”。所以 broad-pool factor IC 可以做
split-adjusted price-return 开发诊断，但任何和 SPY 比收益的组合结论必须先扩展 corporate-action coverage
并通过该 validator。

### P1-A：旧 ML portfolio metric 与正式执行语义不完全一致

`portfolio_metrics()` 用权重 shift(1) 乘 close-to-close return，因果上不前视，但没有精确模拟信号后
T+1 open 的 gap、订单和实际成交成本。它适合模型筛选，不足以冻结 forward 候选。正式候选必须走
`BacktestEngine` 的 T+1 open execution 或等价且有 gap-open parity 测试的路径。

### P1-B：trial accounting 仍依赖手工枚举

现有 `data/audit/ml_trial_ledger.json` 是 10 个手工整理配置。它改正了曾经硬编码 `n_trials=5`，但仍可能
漏掉未记入的尝试。新程序必须在运行前原子写 trial intent，在完成后追加 outcome；重复 id fail-closed，
DSR 的 N 从账本机械计算，不允许人工填写。

### P1-C：旧 LLM funnel 不是语义策略，且曾绕过价基入口

`core/research/llm_mining.py` / `core/factors/llm_candidate.py` 主要验证 LLM 提议的 pandas 因子公式，
不是对 filing/news 文本做 semantic representation。`scripts/llm_factor_propose.py` 还使用 raw
`MarketDataStore.read()`；已改为 `BarStore` split-adjusted price-return，并强制输出
`DEVELOPMENT_ONLY` 与非自动晋升标记。该修复不把旧公式轨升级为推荐方向。

## 4. 边界验证

### PEAD 时间语义

Company Facts 只有 `filed` 日期，没有 accepted time。PEAD 将 filing date 映射成 signal date，但所有
执行脚本设置 `execution_delay_bars=1`，所以实际在下一交易日开盘成交；这是保守，不是同日泄漏。
不足之处是 10-Q filed date 常晚于真实 earnings release，导致事件识别延迟。

新的语义轨应改用 SEC submissions 的 `acceptanceDateTime` 和 accession。SEC 官方 API 提供 filer
submissions history，API 几乎实时更新并有 nightly bulk archive；抓取仍需遵守每秒不超过 10 次的
fair-access 规则：

- [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
- [SEC rate control](https://www.sec.gov/filergroup/announcements-old/new-rate-control-limits)

离线日频回测一律选择 acceptance timestamp 之后的下一交易日开盘，不尝试利用同日盘前的理想成交。

### 动态 eligibility 可行性

在 expanded_v2 上做了不写盘的 trailing-only probe：history>=252、fresh<=5 calendar days、price>=5、
最近 60 个观测 median dollar volume>=10M、相对 SPY 60-session density>=90%。可用数从 2015 年的
818 增至 2023 年的 930；池中 32 个名称在 2025 前停止交易。说明按日期进入/退出的动态 mask 在本机
可算，也能保留部分 dead-name 信息。但上游 1000 名池本身仍是 2024 hindsight 选出的，所以只能作为
开发 proxy，不能被重新命名成 PIT OOS。

## 5. LLM / semantic 的独立判断

FinBERT 的一手论文支持“金融领域预训练能改善金融情感分类”，不等于证明情感分数能预测净收益：
[Araci, FinBERT](https://arxiv.org/abs/1908.10063)。因此设计上必须比较：

1. lexical/财务词典或 TF-IDF 线性基线；
2. 冻结 FinBERT sentiment/embedding；
3. embedding novelty、与上次同类 filing 的 delta、train-only cluster/peer rank；
4. 只有前三者有增量后，才允许 schema-constrained generative LLM extraction。

LLM 可做：事件分类、guidance/risk 结构化抽取、假设去重、failure-mode 枚举。LLM 不可做：直接
discretionary buy/sell、在未缓存外部上下文下打分、修改 gate、看 forward 结果后改 prompt。

## 6. 清理判断

本轮不删除历史 PRD、memo、旧 artifact 或失败结果。它们被大量文档和治理代码引用，且是试验次数、
失败模式与 observed-boundary 的证据。可以修索引和明确 supersession，但在没有完整反向引用图与 hash
迁移方案前，删除会破坏审计链，收益远小于风险。

## 7. 最终可行性判定

- XGB ranking：**GO，作为必须打败的智能基线**；不是最终答案。
- numeric feature clustering/ranking：**GO**，但只在 train fold fit，禁止全样本 clustering。
- chart Transformer/大模型训练：**NO-GO for now**；旧结果和 4 GiB GPU 都不支持优先投入。
- SEC filing semantic sidecar：**CONDITIONAL GO**；先补 submissions/text/provenance corpus。
- LLM 直接选股：**NO-GO**。
- 多机制候选同日起 forward：**GO**；前提是各自先冻结、无结果反馈改参、runtime source-batch 绑定完成。
