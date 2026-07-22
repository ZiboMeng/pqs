# PQS 下一阶段审计后行动计划

日期：2026-07-21

状态：AUDITED RECOMMENDATION — 可按顺序执行，尚未因此授权 LIVE 或真实 short

依据：

- `docs/audit/20260721-codex-independent-reaudit-and-hardening.md`
- `docs/audit/20260721-profitable_strategies_gates_and_short_review.md`
- `docs/memos/20260721-next-step-qualification-evidence-and-mining.md`
- 当前分支 `codex/governance-and-semantic-strategy-v4`，审计基线 commit `b3736ea2`

## 1. 最终方向

下一阶段采用一条共享的 score-research 主线、两种预注册 construction、三个 PAPER 观察账本：

1. 同一 cross-sectional score 模型依次比较 rule、linear、XGB、structured SEC、semantic sidecar；
2. 每个冻结 score 同时映射为 long-only top bucket 与 0.5 long / 0.5 short 的 sector/beta-neutral book；
3. PAPER 同时观察 long-only standalone、short standalone 和 frozen core + short overlay combined portfolio。

这样可以直接回答“short 是否突破 long-only construction ceiling”，而不是为 short 重开一轮模型动物园。两种 construction 都写入同一 trial ledger，不能通过换名字少计搜索。

## 2. 当前已经完成，不应返工

- 自动晋升的主基准已经统一为 SPY total return after strategy costs，QQQ 仅为诊断；
- exact cash distribution / split-adjusted execution 语义已经进入 acceptance 路径；
- promotion 已要求 candidate-bound commit/source/evidence hash，缺失进入 `REVIEW_HOLD`；
- force/skip promotion 与 PAPER alignment bypass 已封闭；
- 已观察的 2024-2026 区间继续是 consumed/not-pristine，不可重签；
- 当前 long-only 配置、allocator、下单、account snapshot 与 reconciliation 多层拒绝 short，这一隔离必须保留；
- options synthetic PAPER 不具备真实可成交性证据，暂不进入本阶段。

## 3. 本次复审发现的真实缺口

### P0-1：Qualification 仍是“上游报数 + hash”，不是独立重算

`build_promotion_evidence.py` 会绑定 qualification JSON，但当前 validator 主要校验其中申报的 DSR、PBO、MinBTL 和 CPCV 字段。手工构造一个格式正确的 qualification JSON 仍可能把未经 canonical engine 重算的数字送进门。

必须改为：artifact 引用 immutable raw returns/predictions、trial universe 和 split definitions；validator 或独立 verifier 从这些输入重算指标，并比较结果 hash。上游布尔值不能成为事实来源。

### P0-2：旧 MiningArchive 不是诚实的全局 trial ledger

`core/mining/archive.py` 以 `spec_id` 为主键并使用 `INSERT OR REPLACE`，同 ID 可覆盖；它在结果完成后才保存，无法证明失败、崩溃、被剪枝和人工查看后派生的尝试都已计数。`dsr_trial_accounting.py` 的局部常量也不能替代 program-level raw N。

必须新增 append-only event ledger，计算前写 intent，完成/失败/中止只追加 outcome；旧 archive 只读保留，不迁移成伪完整历史。

### P0-3：历史单名股票选择仍有 PIT/survivorship 边界

当前公司池适合“今天冻结、明天 forward”，不等于历史 PIT index membership。若无法获得可靠历史 membership、delisting 和 availability-time 数据，历史单名结果必须标为 `PROSPECTIVE_POOL_ONLY / DEVELOPMENT_BIASED`，不能声称干净历史 SPY alpha。

### P0-4：Short PAPER 没有可复用的真实账户语义

当前 engine 会拒绝或截断负权重，也没有 restricted proceeds、borrow、margin、short dividend、recall/buy-in 和 signed reconciliation。直接切开关会产出错误账本。

### P1-1：Timing evidence 仍偏通用，不够 candidate-specific

现有 evidence builder 运行固定的公共 timing tests，但这些测试不必然执行候选的完整 feature/model/prompt/data path。必须增加 candidate-specific prefix invariance、availability-time、T-close/T+1-open、replay 和 targeted mutation tests。

### P1-2：统计 artifact 的字段语义仍太弱

当前治理只要求 `cpcv_n_folds>=2`，无法区分 groups、splits 与 paths；PBO 阈值 0.50 也只能视为底线诊断。下一版必须分别记录 CSCV/PBO performance matrix 与 CPCV 的 `n_groups/k_test/n_splits/n_paths`，禁止用一个 `folds` 数字混过去。

### P1-3：真实 forward 仍依赖 trusted source-batch bridge

未完成 collector batch 与 paper consumer 的实际 hash binding 前，只能 replay，不能把每天生成的文件称为 prospective forward evidence。

## 4. 执行顺序与验收标准

### A0：冻结权威与审计基线

行动：

- 以当前治理分支和 `research_boundary.observed_through=2026-07-17` 为基线；
- 新建 protocol/version，不修改旧 registry、archive、sealed artifact；
- 记录 Python/data mount/source manifest；
- 将本计划和 short research PRD 纳入 docs index。

出口：tracked worktree clean；旧 holdout 未读；所有新结果默认 `DEVELOPMENT_ONLY`。

### A1：Canonical Trial Ledger（最高优先级）

行动：

- 新建单一 append-only ledger，事件至少包括 `trial_intent/trial_started/trial_outcome/trial_failed/artifact_bound`；
- intent 在任何 feature fit/backtest 前写入并 fsync；
- 记录 content hash、family/mechanism、parent、code/config/data/universe/model/construction/cost/seed/date boundary；
- 重复 content hash 可验证复跑，但不能增加独立发现数；
- raw N 永久保留，`N_eff` 仅作并列敏感性估计；
- 并发、崩溃恢复、重复提交、rename 和失败 trial 全部测试。

出口：任一实际选择尝试都能从 ledger 机械重建；旧 `INSERT OR REPLACE` archive 不再作为 N 的 authority。

### A2：Qualification Artifact V2

行动：

- artifact 绑定原始 net return/prediction matrix、SPY active returns、split/embargo definitions 和 trial set digest；
- canonical verifier 重算 DSR、PBO、MinBTL、CPCV、active-return CI、beta-adjusted alpha、cost stress 和 drawdown/stress；
- PBO/CSCV 与 CPCV 分开建模，不再共用模糊 `n_folds`；
- candidate-specific timing/replay tests 随实际模型运行；
- behavior manifest 覆盖模型文件、prompt、corpus/parser、feature list 与外部 data manifests，不只静态公共源码清单；
- 构造 adversarial fixture，证明篡改 DSR/PBO 布尔值、替换 return matrix 或漏记 trial 会 fail。

出口：promotion validator 只相信 canonical verifier 的重算结果；手写 qualification JSON 不能制造 PASS。

### A3：PIT 数据与候选池

行动：

- 冻结 `semantic_ml_company_pool_v1` ordered symbols/CIK/exchange/liquidity snapshot；
- 实现 daily causal eligibility 与 prefix-invariance；
- 完成 split/distribution/corporate-action coverage；
- SEC filing 使用 acceptance timestamp，并映射到下一可交易 session；
- 调查历史 PIT membership/delisting/fundamental availability 数据；不可获得时启用 `DEVELOPMENT_BIASED` 标签并禁止历史自动 SPY PASS；
- short 侧定义 PIT borrow snapshot schema：shortable、available quantity、fee/rebate、HTB、observed/available time、source。

出口：追加未来数据不改变过去 eligibility/feature；任何缺失 availability/corporate-action/borrow 输入均 fail-closed 或明确 `RESEARCH_INCOMPLETE`。

### A4：共享 Score Mining

首批固定模型：

1. low-DOF rule rank；
2. linear rank；
3. shallow XGBRanker；
4. structured SEC/XBRL/event baseline；
5. structured + lexical/semantic sidecar，含 shuffled-text negative control。

首批低换手特征补充：shareholder yield/net issuance、quality、profitability、residual momentum；没有 PIT fundamental availability 的字段不启用。

每个 score 必须在完全相同的 label、universe、cost、execution 上映射：

- `L0`：long-only top bucket；
- `S0`：0.5 long / 0.5 short、sector/beta-neutral；
- `C0`：冻结 core + 固定比例 S0 overlay，仅作组合研究。

出口：rule/linear/XGB apples-to-apples；trial ledger 数量与实际运行一致；每 family 最多冻结一个 sibling；不碰旧 holdout。

### A5：Short PAPER 基础设施

先写独立 PRD，再实现隔离模块；不得改现有 long-only schema 使其同时承担两套语义。

必须实现：

- signed position/account ledger；
- `SHORT_SELL` 与 `BUY_TO_COVER` 独立 order semantics；
- `equity = cash + long_market_value - short_market_value`，并单列 restricted proceeds/buying power；
- gross/net/beta/sector exposure；
- initial、maintenance 和 broker house margin；
- borrow fee/rebate、short dividend、split/merger/delist liability；
- locate reject、Rule 201、recall/buy-in、halt/gap/squeeze 和 forced cover；
- restart idempotency、atomic state、signed broker reconciliation 和 kill switch。

最低反例测试：卖空收入不增加 NAV；价格上涨产生无上限方向损失；股息/borrow fee 正确扣除；split 保持经济敞口；locate 缺失拒单；recall/margin breach 强制回补；缺 open 不用 close 伪成交。

出口：synthetic PAPER 会计和风险反例全部通过；没有 PIT borrow source 时状态仍为 `RESEARCH_INCOMPLETE`，不能进入 promotion。

### A6：同日起并行 Prospective PAPER

前置：A1-A5 完成，trusted source-batch bridge 可用，候选和组合权重已冻结。

账户：

- long-only candidate standalone；
- short book standalone；
- frozen core + short overlay combined；
- SPY total-return benchmark；
- 可选 risk-matched passive 仅作诊断。

纪律：所有 finalist 从同一未来 session 开始；独立虚拟账户共享同一 source/borrow batch；不训练、不改 prompt/threshold/borrow 假设；结果不反馈 miner；安全/数据/会计越界可提前 FAIL，统计功效不足只禁止 PASS。

出口：逐日 append-only manifest、replay parity、source hash、borrow/margin events 和组合 attribution 完整。

## 5. Gate 分工

| 对象 | 主收益门 | 必要补充门 | 不应使用的错误门 |
|---|---|---|---|
| long-only core | after-cost standalone excess vs SPY > 0 | active-return CI、beta alpha、成本/压力/回撤 | QQQ routing、降低 beta 冒充 alpha |
| short standalone | after-cost positive alpha；相对 cash/risk-free 与 beta-adjusted 诊断 | neutrality、borrow coverage、margin、recall/squeeze | 要求零 beta book 每个牛市窗口 raw 跑赢 SPY |
| core + short combined | after-cost portfolio excess vs SPY > 0 | MaxDD/stress、gross/margin、incremental attribution | 用 short standalone PASS 替代组合 PASS |
| risk overlay | 组合增量而非 standalone alpha | 预注册 utility/risk contribution | GRS reject、`E[MDD]` 理论下限、延迟即泄漏 |

near-miss 或低回撤亮点统一进入 `REVIEW_HOLD`，不自动 drop，也不重写为硬门 PASS。

## 6. 并行化方式

可以安全并行：

- A1/A2 的 schema/test 设计与 A5 short PRD/borrow source 调研；
- A3 long-only PIT pool 与 short borrow schema；
- structured numeric baseline 与 SEC corpus ingestion。

必须串行：

- 没有 A1 ledger 不开始正式搜索；
- 没有 A2 canonical verifier 不冻结候选；
- 没有 A5 signed accounting/borrow/margin 不启动 short PAPER；
- 没有 trusted source binding 不声称真实 prospective forward。

## 7. 本阶段明确不做

- 不重签或重开任何已消耗 holdout；
- 不把旧 archive 补写成看似完整的 trial ledger；
- 不用 inverse ETF 代替中长期 short；
- 不让 LLM 直接生成仓位、gate 或 promotion 决策；
- 不扩大到神经网络，除非 XGB 相对 rule/linear 有稳定增量；
- 不推进 options VRP，直到真实 quote/exercise/assignment/margin/accounting 路径完成；
- 不开 LIVE、不接真实 broker short order。

## 8. 建议的立即开工包

下一次实施从 `A1 + A2` 开始，同时只做 `A5` 的 PRD 与数据源可行性调研：

1. append-only trial ledger；
2. Qualification Artifact V2 schema + canonical recomputation；
3. adversarial/fail-closed tests；
4. short PAPER PRD（不写 execution）；
5. 完成后再审一次可行性，才启动 A3/A4 正式挖掘。

这一路径的停止条件也明确：若 canonical 重算证明候选全部无效，保留零结果，不降门；若 short borrow 数据不可获得，short 只停在 synthetic feasibility，不伪装成可晋升 PAPER。
