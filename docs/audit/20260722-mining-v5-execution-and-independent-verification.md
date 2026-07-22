# Mining V5 执行与独立复核报告

日期：2026-07-22

分支：`codex/governance-and-semantic-strategy-v4`

资格代码提交：`b4a7a856d58d991ce24db30973e5154e3f854d4f`

证据范围：`DEVELOPMENT_ONLY`

## 1. 结论

本轮已按用户批准的标准变更完成治理 schema v3、evaluation contract v2、Qualification V4、canonical
SPY total-return 修复、账户风险分层和 30 行 V5 预注册矩阵，并实际达到退出条件
`MAXIMUM_30_ROUNDS`。

结果为 **0 个 FORMAL_V5_RESEARCH_CANDIDATE**。这不是因为 Balanced Drawdown 过严：11 个可运行的
Track A ETF 构造在 30/60/90bps 下全部通过 D1-D5，但全部未能满足 SPY 收益门和开发稳定性门。其余
18 行按预注册的数据依赖 fail closed，未用临时 sibling 回填。

没有 candidate 获得自动晋升或资本权限；所有失败 candidate 为 `REVIEW_HOLD`，账户证据缺失的通过路径
也只能是 shadow。本轮没有产生可启动正式 PAPER forward 的新策略。

## 2. 标准变更的机器实现

- 活跃治理：`config/research_governance.yaml` schema v3；schema v2 已原样归档。
- candidate hard benchmark：2015-01-02 至 2024-12-31 canonical costless SPY total return；CAGR
  `13.029875%`，全期 MaxDD `-33.699814%`。
- SPY direct total-return 与独立 exact-cash recurrence 最大逐日误差 `2.22e-16`；分红留现金 negative
  control 明确不相等。
- candidate 分别使用 30/60/90bps after-cost path；SPY hard path 不加 candidate 成本。
- D1 全期严格胜出；D2 month-end trailing 36m 至少 60%；D3 SPY-defined 15% episode 全胜；D4 monthly
  downside capture<100%；D5 任一完整年相对伤害不超过 3pp（等于允许）。
- 绝对 15%-20% operating target / path stress<=25% 已下沉到账户部署合同；terminal weighted shock 不能
  冒充 path PASS；证据不完整只允许 shadow，且本阶段 capital=false。
- composite trial universe 绑定旧 30 次与本轮 30 次，Qualification V4 的 binding raw N=`60`。

## 3. 执行完整性

首次执行中，R02-R12 的三条 return path 已完成计算，但 target hash 对 pandas `Timestamp` 直接 JSON
序列化时抛出 `TypeError`。原始失败事件未删除或回写。本次修复后使用同一 content hash 追加
`REPLAY_INTENT`：trial ID 仅增加 corrective-replay 后缀，原 code/data/config/mechanism 均不变，因此
本轮 local raw N 仍为 `30`，而非 41。

最终 ledger：

- event count：104；
- local raw independent N：30；
- incomplete trial：0；
- composite raw independent N：60；
- corrective mode：`CORRECTIVE_SERIALIZATION_REPLAY_NO_NEW_INDEPENDENT_TRIALS`。

## 4. 可运行 Track A 结果

下表均为 base 30bps；canonical SPY CAGR 为 13.03%。所有行 D1-D5 都通过，但没有一行通过 return 与
统计总门。

| Candidate | CAGR | Full MaxDD | 36m DD win | Downside capture | 36m excess win | 结论 |
|---|---:|---:|---:|---:|---:|---|
| 70% SPY + 30% Q/M/LV，无 overlay | 11.81% | -31.56% | 100.0% | 92.56% | 12.94% | 最接近收益门，但仍落后 1.22pp，回撤改善不惊艳 |
| 80% SPY + 20% BIL negative control | 10.50% | -27.32% | 100.0% | 84.25% | 0.00% | 正确证明 cash dilution 不能过收益门 |
| SPY vol-only | 9.75% | -25.46% | 91.76% | 85.45% | 18.82% | 防御有效，收益损耗过大 |
| SPY trend-only | 9.36% | -18.63% | 90.59% | 81.90% | 5.88% | 防御有效，收益损耗过大 |
| SPY vol+trend | 8.56% | -17.58% | 90.59% | 76.95% | 2.35% | 防御更强，但 return gate 明确失败 |
| 70% SPY + 30% Q/M/LV + risk | 8.41% | -17.48% | 90.59% | 74.80% | 1.18% | alpha sleeve 未补回去风险损耗 |
| 70% SPY + 30% Q/M + risk | 8.64% | -17.52% | 90.59% | 76.10% | 1.18% | 同上 |
| 70% SPY + 30% Q/LV + risk | 8.24% | -17.43% | 90.59% | 74.80% | 1.18% | 同上 |
| 70% SPY + 30% M/LV + risk | 8.35% | -17.49% | 90.59% | 73.48% | 1.18% | 同上 |
| 60% SPY + 40% Q/M/LV + risk | 8.36% | -17.45% | 90.59% | 74.08% | 1.18% | 增加 sleeve 未产生足够 alpha |
| Q/M/LV + conditional BIL/IEF/GLD | 9.04% | -17.92% | 90.59% | 74.20% | 2.35% | 多资产 defense 有改善，仍远低于收益门 |

所有 11 行还共同失败：DSR>=0.95、MinBTL、CPCV positive-active stability；PBO 为 0.0833，单独通过。
这些统计失败与 active return 长期为负一致，不是 DSR/PBO 实现误杀。

## 5. Blocked 行处置

- R13-R19：缺少真正历史 PIT universe 与 PIT fundamental panel，状态
  `BLOCKED_NO_TRUE_HISTORICAL_PIT_UNIVERSE_AND_PIT_FUNDAMENTAL_PANEL`。
- R20-R29：缺少符合 PRD 的 10-K/10-Q acceptance-bound corpus 与 outer-train-only 表征证据，状态
  `BLOCKED_NO_PRD_COMPLIANT_10K_10Q_ACCEPTANCE_BOUND_CORPUS`。
- R30：缺少 pinned/replayable LLM extraction 与人工双审 QA，状态
  `BLOCKED_NO_PINNED_REPLAYABLE_EXTRACTION_AND_HUMAN_QA_ARTIFACT`。

这些行全部消费预注册 slot。没有用既有 survivor-biased pool 或 8-K 五日 event 结果冒充合规输入。

## 6. 独立判断

本轮证据否定了“用简单防御 overlay + 当前 broad factor ETF sleeve 就能同时跑赢 SPY 并显著降低回撤”这条
完整假设。它没有否定防御层的风险价值；相反 D1-D5 全通过说明防御有效，但其收益机会成本太大。继续在
15% vol target、126/252 SMA、60/40 或 ETF 权重附近做局部搜索，极易成为对同一历史的参数拟合，不建议
在本 campaign 后追加第 31 个 sibling。

最有信息量的后续工作不是放松 return gate，而是先解决 Track B 的真实 PIT 数据基础，再判断 company-level
quality/momentum/low-risk 与低频 filing representation 是否能提供足够 alpha 支付防御成本。在 PIT universe、
PIT fundamentals 和 acceptance-bound corpus 完成前，不应继续训练更大的 XGBoost 或接入 LLM 预测收益。

## 7. 可复核入口

- campaign report：`research/results/mining_v5_balanced_20260722_v1/campaign_report.json`
- append-only ledger：`research/results/mining_v5_balanced_20260722_v1/trial_ledger.jsonl`
- Qualification V4 artifacts：`research/results/mining_v5_balanced_20260722_v1/qualifications/`
- raw bound inputs：`research/results/mining_v5_balanced_20260722_v1/qualification_inputs/`
- independent verifier：`scripts/verify_mining_v5_results.py`

验证器要求每个 artifact 的 input/governance/evaluation/benchmark/ledger/composite digest 全部可重算；
“canonical gate failed”是允许的研究结论，任何额外 integrity failure 都会令验证器失败。
