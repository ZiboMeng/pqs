# 30 轮挖掘首次运行后的窗口语义纠正

日期：2026-07-21

状态：原 campaign report 的绩效/qualification 字段已失效；30 个 intent/outcome ledger 保留有效

## 1. 审计发现

首次 30 轮完成后，没有直接接受 `formal_candidate_count=0`，而是把 round metrics、raw returns 和
Qualification V2 逐项对账。发现两个相反方向的窗口错误：

1. round-level `BacktestResult.metrics` 从 panel 起点 2007 年计算，但第一笔 numeric signal 在 2015 年。
   2007–2014 的纯现金被纳入 CAGR 年数和 252 日 rolling 分母，系统性稀释 CAGR、并把 cash-vs-cash 的相等
   窗口计为“不跑赢”；
2. 为让 2020 才开始的 SEC event candidate 进入同一 performance matrix，qualification 又统一截成
   2020–2024。这个窗口丢掉 numeric 2015–2019 的开发表现，并在 2020 后 current-company survivor 牛市段产生
   过度有利的 active excess。

原报告出现同一 candidate 的 full-round rolling 约 44% 而 qualification rolling 约 78%，不是 gate
冲突，而是评估窗口不一致。机器失效记录：
`research/results/governance/diverse_mining_v1_window_invalidation.json`。

## 2. 哪些证据仍有效

- 30 个 preregistered hypotheses 和顺序未变；
- append-only ledger 为 118 events、raw independent N=30、29 outcome、1 counted failure、0 incomplete；
- 每个 round 的 T+1 open/cash-distribution/cost replay 已实际执行；
- short 两轮仍是 `RESEARCH_INCOMPLETE`，LLM blocker 仍是 counted failure；
- 没有第 31 个参数、没有看结果后修改 feature/model/construction。

因此 ledger 不能删除或重置；原 result artifacts 作为失效审计证据保留。失效的是跨窗口汇总和基于它的
qualification/freeze 判断。

## 3. 纠正方式

执行同一 30 个 frozen specs 的 `CORRECTIVE_REPLAY_NO_NEW_TRIALS`：

- 不向 ledger 追加 intent/outcome，raw N 仍为 30；
- numeric 正式 evaluation 从 2015-01-01 开始；
- SEC event 在 2020 前保持 cash，而不能把所有 numeric evidence 截短到 2020；
- daily matrix/qualification 使用 2015–2024 一致日期；
- round metrics 从 evaluation start 的 equity 重新调用 canonical `compute_metrics`；
- 先执行 SPY excess、rolling、30/60/90 bps drawdown 和 candidate-specific timing primary pre-screen；
- primary fail 的 candidate 不再复制大型 qualification matrix；primary pass 才运行 DSR/PBO/MinBTL/CPCV；
- DSR/PBO/MinBTL 继续使用完整 ledger raw N=30 和 active returns，不因 replay 减计或增加 N。

该 replay 是证据纠错，不是新 mining round。若纠正后达到 5 个 formal candidates，仍按原退出定义冻结；否则
以已完成 30 轮收口，不继续搜索。

## 4. 独立判断

首次错误窗口下仍为 0 formal candidates：即使只看更有利的 2020–2024，多数强势 momentum candidate 的
active DSR 仅约 0.18–0.34，MinBTL 需要约 5.6–8.9 年而实际只有约 5 年。这个结果提示 formal=0 很可能
稳健，但不能用“很可能”替代正确 replay。

两条 synthetic short 在固定 3% borrow 假设下也没有突破：momentum long/short 30 bps 累计约 -7.2%，
60/90 bps 约 -33.0%/-51.7%；residual long/short 更差。它们本来就无 PIT borrow 资格，因此只作为机制反证。

SEC structured+lexical event 30 bps 仍呈显著负 after-cost active return，且 12,641 fills；文本 IC 增量没有
解决 turnover economics。LLM 没有冻结 response corpus，保持 fail/count 是正确处置。
