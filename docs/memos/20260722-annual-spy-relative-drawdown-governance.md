# 逐年 SPY 相对 MaxDD 治理决策

日期：2026-07-22
权威：用户显式决定
状态：prospective effective

## 决定

自动晋升不再使用 15%/20%/25% 等绝对 MaxDD 硬阈值。策略必须在每个对齐日历年满足：

`abs(strategy_after_cost_max_drawdown) < abs(SPY_max_drawdown)`

该比较必须覆盖 base 成本和每个预先冻结的成本压力情景。任一年、任一情景失败即不能晋升。

## 不变的报告与风险义务

- full-period、calendar-year、Covid/rate-hike 等命名 stress slice 的绝对 MaxDD 继续完整报告；
- 绝对 MaxDD 是人工风险诊断，不得成为隐藏 gate；
- 收益仍须在计入策略成本后跑赢 SPY；DSR/PBO/MinBTL、timing、PAPER/backtest alignment 不变；
- 失败进入 REVIEW_HOLD，不自动删除，也不能改写成 PASS。

## 版本与历史边界

- `config/research_governance.yaml` 的 `pqs-governance-reconciliation-v2` 是当前机器权威；
- 新晋升必须使用 Qualification V3，并绑定 governance、evaluation contract、ledger 和原始收益；
- evaluation contract 必须预先冻结 return-date 索引哈希、覆盖年份和成本压力场景全集；
- 已锁定的 temporal split、Qualification V2 和 campaign artifact 保持历史原样；
- 不能用这次门定义变化重签已经看过结果的候选。

## 对 20260721 campaign 的影响

本轮仍为 0 formal。两个 legacy V2 REVIEW_HOLD 在 base 30bps 的年度比较中均失败：

- `dual_momentum_regime`：仅 2016、2022 优于 SPY；其余 8 年失败；
- `mom_balanced_buffer15`：仅 2022 优于 SPY；其余 9 年失败。

旧 bundle 没有为 60/90bps 保存匹配的 SPY 日收益，因此不能构造完整 V3，状态保持
`REVIEW_HOLD_EXPLORATORY_NOT_FORMAL / paper_eligible=false`。
