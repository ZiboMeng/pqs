# Mining v4 治理、价格口径修复与策略挖掘审计

> **后续作废通知（2026-07-21）：** 本文对 `v5` 总回报口径和基于它的研究结论已被精确现金复审推翻，只保留为历史审计证据。当前有效记录见 `docs/audit/20260721-exact-cash-revalidation-and-next-round.md` 和 `research/results/governance/price_basis_v5_invalidation.json`。

日期：2026-07-20（America/Los_Angeles）

分支：`codex/governance-and-semantic-strategy-v4`

结论：治理与本轮开发期挖掘完成；没有新策略获准进入 sealed forward 或 paper。

## 1. 独立结论

本轮最重要的结果不是找到一个“漂亮模型”，而是推翻了错误的数据基础并重新运行全部相关研究：

1. `raw_daily_snapshot_v3` 日历合规但价格口径混杂，旧 numeric、SEC structured、8-K lexical 三份结果全部失效；
2. 新建并逐文件校验了同源 Yahoo 1d 快照，再由拆股已调整 OHLC 与现金分配事件构造 `v5` 总回报价基；
3. numeric 规则模型有值得保留的低回撤 near-miss，但未通过滚动超额和成本稳健性门；
4. structured SEC 模型存在正 IC，但事件组合在零成本下的约 `+2.7%` 至 `+3.1%` 年化超额，被约定的
   30 bps 单边成本完全吞噬；
5. lexical 文本没有给 structured baseline 提供稳定增量，因此不升级到 FinBERT、embedding 或生成式 LLM；
6. 现有正式策略保持 `PAPER_OBSERVATION_ONLY / REVIEW_HOLD`，本轮没有重签、放宽 gate 或动用 sealed 数据。

有效结果概览：

| 研究轨 | 最强表面结果 | 未通过的关键门 | 处置 |
|---|---:|---|---|
| Numeric rule / active top10 / 30 bps | CAGR 超额 `+3.27%`，MDD 为 SPY 的 `0.91x` | 252 日滚动超额胜率 `55.77% < 60%`；60 bps 下超额 `-1.99%` | `REVIEW_HOLD` 研究线索，不 forward |
| Numeric XGB / SPY35 rank-vol / 30 bps | CAGR 超额 `+4.50%`，滚动胜率 `64.77%` | MDD 为 SPY 的 `1.65x > 1.25x` | 拒绝进入 forward |
| Structured SEC event / frictionless | CAGR 超额 `+3.09%` Linear、`+2.69%` XGB | 零成本只作机制诊断 | 不可 promotion |
| Structured SEC event / 30 bps | CAGR 超额 `-20.79%` Linear、`-21.22%` XGB | CAGR、滚动胜率均失败 | 当前组合构造停止 |
| 8-K lexical + structured XGB | mean rank IC `+0.01357` | 低于同 cohort structured XGB `+0.01440`，且仅 3/5 fold 为正 | 停止语义升级 |

## 2. 治理边界与清理决定

- 接管前基线已以 tag `codex-pre-governance-v4-20260720` 保存在 commit `f5497ec`；开发在独立分支进行并持续推送。
- 正式 benchmark 仍是 SPY。完整期超额、252 日滚动超额胜率和相对最大回撤均保留；失败不会自动删除，
  exceptional near-miss 可以进入人工讨论，但不能被自动视为 PASS。
- 300 家公司池按 2026-07-17 当时的当前公司冻结，因此有 survivorship bias。所有新报告明确为
  `DEVELOPMENT_ONLY`、`historical_oos_claim_allowed=false`、`automatic_promotion_eligible=false`。
- 没有清理旧报告、失败 trial 或 `.partial` 下载目录。旧报告是审计证据，partial 目录含 resumable intent/journal；
  在没有逐消费者证明和数据保留政策前删除它们会破坏 provenance。它们均不被有效 pipeline 引用。
- 没有修改原工作树中 Claude 的未跟踪审计文档。

## 3. 价格口径审计与修复

### 3.1 `v3` 为什么失效

`raw_daily_snapshot_v3` 修复了 weekend date shift、混合日历和 ticker reuse，但进一步沿 split 路径逆向抽查发现：

- AAPL、TSLA 等序列仍保留拆股跳变；
- SHOP、NFLX、V、CRM 等序列已经被历史供应链回溯拆股调整；
- loader 却对全体标的统一再次应用 canonical split sidecar；
- canonical 与新 Yahoo split 事件逐标的对照仅 255/301 完全一致，46 家不一致，其中有 vendor-only、
  canonical-only 和 ratio mismatch。

因此，同一个 panel 同时可能出现未调整和双重调整。weekday、calendar containment、finite OHLC、hash 完整性
都无法证明价格口径一致。机器可读失效记录为
`research/results/governance/price_basis_v3_invalidation.json`；以下文件只允许作为历史审计证据：

- `governed_numeric_rank_raw_snapshot_v3.json`；
- `governed_sec_structured_event_v2.json`；
- `governed_sec_8k_lexical_v1.json`。

其 trial 仍保留在 multiplicity ledger 中，不能借失效重置试验次数。

### 3.2 Corporate-action query 不能单独认证总回报

治理后的 3-month interval Yahoo action corpus 有 301/301 HTTP 200、11,721 条现金分配、151 条 split，但与
同一供应商 1d response 对照时有 35 家缺少事件。因此该 corpus 被标记为
`CORPORATE_ACTION_QUERY_CORPUS_NOT_YET_CERTIFIED`，只作诊断，不能作为组合回测的 distribution coverage 证明。

### 3.3 同源 1d 快照 `v4`

`yahoo_daily_total_return_2007_2024_v4` 直接冻结 301 个 Yahoo chart 1d responses：

- 301 responses、126,249,649 bytes、约 1,163,699 行；
- 逐 response、逐 parquet、manifest、builder、parser 全部哈希；
- 全体日期落在 SPY session，OHLC/calendar/finite/unique/monotonic 校验通过；
- 4 个孤立的 vendor `open` 越界行按固定最小规则修复：close 不改；open 夹到 high/low 最近边界；
  其余 high/low 只做保持 OHLC 包络所需的最小扩展；残余大于 20% 则 fail-close；
- 1d response 是价格与现金事件的权威来源；3-month query 的 35 家差异保留为 provenance diagnostic，不再让
  次级 query 否决更完整的同源响应。

Yahoo `Adj Close` 在复杂 spin-off 日可能产生不合理大跳，不能直接当作所有 corporate action 的无歧义真值。

### 3.4 可用总回报快照 `v5`

`yahoo_cash_total_return_2007_2024_v5` 不直接采用 Adj Close 路径，而是从 `v4` 的 split-adjusted OHLC 出发，
只应用同一 1d response 中明确的正现金分配事件：

- price basis：`YAHOO_SPLIT_ADJUSTED_OHLC_PLUS_CASH_EVENT_TOTAL_RETURN_V1`；
- 应用 11,799 个现金分配事件；4 个发生在价格历史开始前的事件显式跳过；
- 与 normalized Adj Close 的非歧义日收益最大绝对差 `1.44e-6 < 5e-6`；
- `ASML/DHR/JCI/TMUS/TSM` 存在同日 distribution + split 组合歧义，fail-closed 排除；
- 295 家公司加 SPY 可研究，301 个源文件仍全部保留并校验；
- manifest SHA-256：`411ec970276bcd88f44c874d18993f20532159a736692f4540a2670e30428009`。

这解决了开发期 total-return preflight，但 Yahoo 是非官方行情源、当前公司池有 survivorship bias，所以仍不能
把 `v5` 称为 production 或真正历史样本外证据。

## 4. Numeric v5 重跑

有效报告：`research/results/governed_numeric_rank_yahoo_cash_v5.json`。

- 295 家候选；180 个 month-end；41,231 eligible cells；28 个预注册特征；
- Rule mean IC `+0.00320`，4/10 fold 为正；
- Linear mean IC `-0.01488`，4/10 为正；
- XGB rank:ndcg mean IC `-0.01159`，5/10 为正，后期 fold 偏弱；
- split + cash distribution total-return portfolio preflight 为 PASS；
- 固定 3 个模型 × 3 个构造 × 30/60/90 bps，共 27 个组合 trial。

30 bps 下所有构造的完整期 CAGR 都表面跑赢 SPY，但没有一个同时通过三个 primary gate：

- Rule active top10：超额 `+3.27%`、滚动胜率 `55.77%`、MDD ratio `0.91x`；
- Rule SPY35 equal：超额 `+2.32%`、滚动胜率 `56.57%`、MDD ratio `0.94x`；
- XGB SPY35 rank-vol：超额 `+4.50%`、滚动胜率 `64.77%`、MDD ratio `1.65x`。

Rule 的低回撤是有研究价值的 near-miss，但 60 bps 下 active top10 年化超额变为 `-1.99%`，不能把 30 bps
单点视为可 forward 策略。XGB 则以显著更坏的尾部风险换取超额，不符合用户“为何不直接买 SPY”的治理原则。

## 5. SEC structured、文本与事件组合

### 5.1 SEC 语料和因果时间

完整 submissions corpus 含 300 main responses 与 374 个相交 historical shards，49,634 条目标 filing。
正文 corpus 冻结 16,180 份 2015–2024 8-K primary documents，全部 HTTP 200，共 665,155,833 bytes、
16,176 个唯一文档 hash。lexical parser 为 16,179 PASS、1 MISSING，通过率 99.994%。

所有事件使用 SEC `acceptanceDateTime`，转换为 America/New_York 后严格映射到接受日期之后的下一 exchange
session open；这比允许 pre-open 当日成交更保守。label 是该 open 到第 5 个 session close 的 market-beta
residual cross-sectional rank。

### 5.2 Structured v5

有效报告：`research/results/governed_sec_structured_yahoo_cash_v5.json`。

- 2,012 个 `>=3` 名事件执行日、19,634 eligible cells、22,044 个 development event records；
- Linear mean IC `+0.01270`，3/5 fold 为正；
- XGB mean IC `+0.03999`，4/5 fold 为正，年度 IC 为
  `+0.07233/+0.00261/+0.05133/-0.00543/+0.07911`。

这足以触发固定组合转化测试，但仍只是当前公司池上的 validation-only 诊断。

### 5.3 8-K lexical v5 与 LLM gate

有效报告：`research/results/governed_sec_8k_lexical_yahoo_cash_v5.json`。同一文本 cohort 有 1,729 个事件日、
13,445 cells、15,987 个匹配文档：

- same-cohort structured XGB：mean IC `+0.01440`，3/5 fold 为正；
- lexical-only XGB：`+0.01109`，3/5 为正；
- structured + lexical XGB：`+0.01357`，3/5 为正；
- shuffled lexical control XGB：`-0.02680`，2/5 为正。

负对照这次没有复制真实文本，但文本组合仍低于相同 cohort 的 structured baseline，年度符号也不稳定。
因此 lexical incremental gate 失败。继续上 FinBERT、embedding cluster 或生成式 LLM 只会增加自由度和试验次数，
没有足够证据支付这笔复杂度成本。LLM 仍只允许未来在低成本文本层先通过后做 schema-constrained extraction，
不得直接给权重。

### 5.4 Event portfolio：信号存在但不可交易

有效报告：`research/results/governed_sec_event_portfolio_yahoo_cash_v5.json`。唯一固定构造为：score ≥ 0.8、
5 session holding、单股 10% cap、active target 最多 65%、其余 SPY；T 事件严格下一 session open 成交，
第 5 个持有日收盘后下一 session open 退出并支付成本。尾部 2024-12-24 事件因没有完整退出 session 被排除。

实现审计发现并修复了首版遗漏退出成交/退出成本的问题；修复后单元测试覆盖恰好 5 日持有、重叠事件、权重上限、
尾部不完整 round-trip 和 prior-session routing adapter。

结果：

- frictionless Linear：CAGR `17.62%` vs SPY `14.53%`，超额 `+3.09%`，滚动胜率 `84.10%`；
- frictionless XGB：CAGR `17.22%` vs SPY `14.53%`，超额 `+2.69%`，滚动胜率 `72.66%`；
- 30 bps Linear：CAGR `-6.33%` vs SPY `14.46%`，超额 `-20.79%`，滚动胜率 `0%`；
- 30 bps XGB：CAGR `-6.76%` vs SPY `14.46%`，超额 `-21.22%`，滚动胜率 `0%`。

30 bps 场景约 16,600 笔 fills。由总 slippage / 30 bps 反推，累计单边成交名义额约 3,000 万美元，约为
10 万美元初始资本每年 60–62 turns。60/90 bps 结果进一步恶化，证明当前事件覆盖与日常新增/到期组合在经济上
不可交易。零成本 PASS 只是机制诊断，绝不具有 promotion 资格。

本轮不在看过结果后调 score threshold、持有期或模型参数。若未来重开，必须将“更稀疏的、机制明确的事件子集
加显式 turnover budget”作为新假设预注册，并完整计入 multiplicity；不能把同一结果包装成修复。

## 6. Trial accounting

外部 append-only hash-chain ledger：`data/research/mining_v4/trial_ledger.jsonl`。最终为 156 events、78 trials、
0 incomplete：

- numeric signal 15；
- numeric portfolio 27；
- structured SEC signal 6；
- 8-K lexical signal 16；
- structured SEC event portfolio 14。

失效 `v3` 的尝试仍计数。事件组合第一次 6 个成本 trial 后，因补入预先解释用的 frictionless control 并产生
新 code commit，又保守计入 8 个 trial；没有借 replay 名称减计。早期 4 个 structured SEC intent 的 ledger
`label_id` 曾误记为 21-session label，实际计算和 JSON 都是 5-session；账本不可篡改，错误在本报告披露，后续
intent 已修正。

## 7. 验证状态

- 本轮价格、corporate-action、numeric、SEC corpus、lexical 和 event portfolio 定向测试：39/39 通过；
- 本轮相关文件 ruff：全部通过；
- bytecode compile：通过；
- 更早的完整 `tests/unit/research`：1,740 passed、4 skipped、20 failed。14 个失败来自隔离 worktree 缺少
  Git-ignored `data/daily`；6 个是旧 sealed artifact 发现绑定组件 drift 后正确 fail-close；
- 不为追求绿色测试重签旧 sealed artifact。正式策略处于 `REVIEW_HOLD`，恢复需新 artifact version 和审批。

## 8. 下一步的独立判断

本轮不建议进入 sealed forward 的新策略，也不建议继续加 LLM/更深模型。下一轮若继续挖掘，优先级应是：

1. 预注册一个低换手 numeric rule near-miss 改进，目标是保持低 MDD，同时在 60 bps 和滚动窗口门下成立；
2. 与其调 SEC score，不如定义机制清晰的稀疏事件族（例如只研究 earnings-release 8-K 2.02），先冻结事件选择、
   turnover budget 和成本，再只跑一次；
3. 只有上述文本无关 baseline 在含成本组合层接近 gate，才恢复 schema-constrained LLM extraction；
4. 任何 candidate 必须先在开发期全 gate 通过，再冻结代码/数据/参数进入独立 sealed forward；不共享 sealed
   feedback 给同期挖掘。

这保留了“多挖几个策略后一起 forward”的时间优势，同时切断 forward 结果反向指导开发造成的数据窥探。
