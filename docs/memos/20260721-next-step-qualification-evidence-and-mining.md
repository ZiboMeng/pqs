# 下一阶段执行建议：先打通 Qualification Evidence，再启动多候选挖掘

日期：2026-07-21

状态：RATIFIED — 已结合盈利策略/gate 报告与 short mandate 独立复审修订

## 决策

下一步不立即扩大参数搜索，也不打开已消耗的 sealed/holdout。先让 governed semantic/ML miner 对每个实际尝试机械地产出 canonical qualification artifact，再在统一数据、价格、成本、执行与 SPY 主基准口径下比较多个机制不同的候选。

本决定经 `docs/audit/20260721-profitable_strategies_gates_and_short_review.md` 复审后维持。该报告没有改变“先证据、后扩搜”的顺序；它只修订了策略优先级与 short 的研究边界。

## 必须先完成的证据输出

每个候选的 qualification artifact 至少绑定：

- candidate/trial identity、完整 trial ledger 与有效独立试验数；
- code/config/data/universe/corporate-action hashes；
- timing/lookahead 测试结果；
- DSR、PBO、Minimum Backtest Length、CPCV 分布及其输入；
- after-cost SPY excess、滚动窗口、stress、concentration 与 turnover；
- evidence scope=`DEVELOPMENT_ONLY`、observed-through 与 `automatic_promotion_eligible=false`。

缺失或校验失败统一进入 `REVIEW_HOLD`，不得用布尔 attestation、force、skip-pass 或重命名 trial 绕过。

## 第一批候选比较

在完全相同的数据与组合映射下，至少比较：

1. 低维、因果的 rule-based cross-sectional rank baseline；
2. linear rank baseline；
3. 浅层 XGB learning-to-rank；
4. structured SEC event baseline；
5. structured + lexical/semantic sidecar，并包含 shuffled-text negative control。

同一 family 只保留一个 sibling；候选 NAV 高相关时保留机制更清楚、自由度更低者。通过开发门的候选再冻结并从同一未来 session 开始并行 PAPER observation。

策略侧的第一优先级不是直接把 vol-target、PUT 或 dual momentum 宣称为 alpha，而是：

1. 用 shareholder yield / quality / profitability / residual momentum 等低换手、可解释信号构成 long-only baseline；
2. 让 linear rank、浅层 learning-to-rank 和 semantic sidecar 在相同组合映射下竞争；
3. 把 dual momentum / trend / vol-targeting 仅作为预注册的风险 overlay 变量，分别报告 standalone 与组合增量，禁止把降低 beta 冒充 alpha；
4. options VRP 在真实期权链、会计、成交、assignment/settlement 与 margin/capital 模型完成前降为低优先级研究，不进入 promotion。

## 当前不做

- 不因为当前零自动晋升候选而放松门槛；
- 不把 heuristic macro dates 当 precise semantic evidence；
- 不重签已漂移的 sealed artifact；
- 不让 LLM 直接生成仓位或决定晋升；
- 在 short mandate 未单独审计、借券/保证金/强平/召回/税务和极端风险边界未定义前，不把 short 纳入现有 long-only 生产路径。

## Short 决策

批准建立隔离的 `SHORT_RESEARCH_ONLY` PAPER lane，用来检验 long-only 是否确实是当前 sibling/construction collapse 的绑定约束；不批准修改现有 long-only production/backtest/paper 路径，也不批准真实交易、裸 short options 或用 inverse ETF 伪装长期 short。

第一项实验应是大盘高流动股票的 sector/beta-neutral cross-sectional top-minus-bottom book，同时比较 gross=1.0 的 0.5 long / 0.5 short 与 long-only baseline。任何结果必须扣 point-in-time borrow fee、融资、股息代付、locate reject、recall/buy-in、Rule 201 执行约束和成本压力；借券数据缺失只能输出 `RESEARCH_INCOMPLETE`。

若未来研究要求“100% SPY + market-neutral alpha overlay”，必须明确承认 gross exposure>1、margin/financing 与尾部强平风险已经改变 mandate，另行批准，不能从本记录推导授权。short sleeve standalone 不使用 raw SPY CAGR 作经济门；只有与冻结 core 组合后的 after-cost portfolio 才接受 SPY 主门，同时 short sleeve 自身必须通过正 alpha、beta/sector neutrality、borrow feasibility、squeeze/recall stress 和无限损失边界门。
