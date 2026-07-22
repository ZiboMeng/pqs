# 30 轮多样化策略挖掘最终审计

日期：2026-07-21（运行完成时间为 UTC 2026-07-22）

状态：**COMPLETE — MAXIMUM_30_ROUNDS；0 个正式冻结候选；不放宽门槛**

> **2026-07-22 治理补充（覆盖本文的 near-miss 表述，不改写历史机器证据）：**
> 用户将 prospective MaxDD 硬门改为“每个对齐日历年、每个冻结成本情景均严格优于同年
> SPY”，不设绝对 MaxDD 硬阈值。两个候选的“仅 DSR 失败”只描述 legacy Qualification
> V2；按当前年度相对门，二者 base 情景也均失败，故已降级为探索性 REVIEW_HOLD。
> 此外，最终 2015–2024 corrective replay 与预注册的 2020–2024 common qualification
> start 不一致，只能作为可复算的 corrected development analysis，不能冒充严格预注册证据。

权威机器报告：
`research/results/mining_campaign_20260721_v1_authoritative/campaign_report.json`
（SHA-256 `85016714484f2fd03b8d940e295d2f73232f730eeb12c870ded9804d1d4e3f43`）。

## 1. 先给结论

- 已按预注册顺序执行 30 轮；退出条件是“5 个正式候选或最多 30 轮”，本次由 30 轮上限触发；
- ledger 为 118 events、raw independent N=30、29 个 outcome、1 个 counted failure、0 incomplete；
- 27 个 long development result 中，10 个通过 primary pre-screen 进入完整 Qualification V2，17 个在预筛拒绝；
- 10 个完整资格均可从 raw returns、SPY returns、trial matrix 和 ledger 独立重算，但没有一个通过全部 canonical gates；
- 正式候选数为 0，未创建 `FROZEN_FORWARD_CANDIDATE`，也没有新候选获得 PAPER/LIVE 权限；
- 两个在 legacy V2 中仅失败一个 DSR gate 的候选保留为探索性 `REVIEW_HOLD`；它们不计入正式策略数，也不具备 PAPER 权限。

这不是“没有挖到收益”。多条动量策略的开发期相对收益很强；零正式候选的原因是将 30 次搜索的选择偏差
如实放进 DSR，而不是只按漂亮 CAGR 晋级。

## 2. 运行前完成的治理与 short 基础设施

本轮正式搜索前已完成：

1. append-only hash-chain trial ledger：计算前 fsync intent，记录 STARTED/OUTCOME/FAILED/ARTIFACT_BOUND，
   重复 content hash 不增加 raw N；
2. Qualification Artifact V2：promotion 不再相信手填 DSR/PBO/MinBTL/CPCV，而是从绑定的原始收益和 ledger
   独立重算；binding return basis 为 after-cost `candidate - SPY` active returns；
3. 隔离 short PAPER accounting：signed positions、restricted proceeds、locate、margin、borrow/dividend、split、
   Rule 201、recall/forced cover、reconciliation 与 restart idempotency；现有 long-only 生产路径没有被打开 short；
4. exact-cash v6、daily causal eligibility、T+1 execution 与 prefix/future-mutation preflight；历史 current-company
   pool 的 survivorship 边界仍明确为 `DEVELOPMENT_ONLY`。

## 3. 两次自审纠错与结果谱系

第一次 30 轮执行后没有直接接受结果，而是逐项对账，发现 round metric 含 2007–2014 pre-activation cash，
qualification 又被 SEC candidate 截短至 2020–2024。原报告的绩效与资格字段因此失效，但 30 个 hypothesis、
ledger 和 ledger-bound round artifacts 仍有效。

第一次 corrective replay 修正了窗口，却暴露出第二个问题：primary pre-screen 未通过者仍被完整 qualification，
随后又追加一条 prescreen rejection，造成同一候选两条结论。修复后增加了 fail-closed 集合分区断言：每个成功
long candidate 必须且只能走一个路径。

最终在 clean commit `d7e0192d6176d3c1cc56b322af0323561573ed42` 上再次执行同一 30 个 frozen specs，
不向 ledger 写入任何新 trial。权威报告显示 `execution_mode=CORRECTIVE_REPLAY_NO_NEW_TRIALS`、
`mining_rounds_added=0`。完整谱系与失效报告哈希见
`research/results/governance/diverse_mining_v1_result_lineage.json`。

## 4. Legacy V2 中数值最强的候选（非当前 near-pass）

| 候选 | after-cost CAGR excess vs SPY | active Sharpe | 252d 滚动胜率 | 基准/最坏成本 DD÷SPY | PBO | CPCV 正 split | MinBTL 要求/实际 | DSR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `dual_momentum_regime` | +16.22pp | 0.918 | 91.96% | 1.146 / 1.152 | 1.19% | 100% | 8.06 / 9.98 年 | **0.387 FAIL** |
| `mom_balanced_buffer15` | +13.71pp | 0.838 | 80.65% | 1.141 / 1.147 | 1.19% | 100% | 9.70 / 9.98 年 | **0.294 FAIL** |

两者的 Newey-West active mean 95% CI 下界均为正，beta-adjusted alpha 95% CI 下界也为正；在 legacy V2
的相对 full-period 门套件中，唯一失败项是 DSR 必须达到 0.95。DSR 数值是“Sharpe 超过多重试验调整后
`sr0`”的 PSR statistic，不是“真实 Sharpe 大于零”的后验概率；CPCV split 也只是同一 development
样本的稳定性诊断，不是 OOS。

按 2026-07-22 当前年度相对 MaxDD 规则，`dual_momentum_regime` 仅 2016/2022 优于 SPY，其他 8 年
失败；`mom_balanced_buffer15` 仅 2022 优于 SPY，其他 9 年失败。旧输入又没有每个成本情景匹配的
SPY 日收益，不能补签完整 V3。因此二者不是“只差 DSR”的当前候选。

我不建议把 DSR 改成 0.5 或用 ONC effective N=12 替换 raw N=30 来制造 PASS。30 是这次实际登记的搜索数；
effective N 只作诊断。两个候选因此仅作为探索性失败样本保留在
`research/results/governance/diverse_mining_v1_review_hold.json`，等待人工讨论或真正的未来数据增加统计功效，
但当前不具备 PAPER 资格，也不能用本次 post-run 治理变更重签为 V3。

另外三条开发期 CAGR excess 更高的 active 策略没有进入完整资格：
`multihorizon_consensus_active` +18.15pp，但 30/60/90 bps DD 比为 1.264/1.270/1.275；
`mom_12_1_active` +16.47pp，DD 比为 1.381/1.461/1.536；
`mom_balanced_active` +16.31pp，90 bps DD 比升至 1.375。它们违反 1.25 stress-DD 预筛，不能仅按收益晋级。

## 5. ML、语义、LLM 与 short 结果

- OOF rule/linear/XGB 的 CAGR excess 分别约 +4.37pp/+5.04pp/+1.86pp；但既有 prediction artifacts 没有完成
  本候选的 prefix replay、future mutation 和 deterministic replay，因此 timing evidence fail-closed；XGB 还失败
  stress drawdown。rule+linear ensemble 为 -0.21pp。没有证据说明 ML 超越强动量基线；
- SEC structured+lexical event 为 -10.08pp CAGR excess，30 bps 下仍产生 12,641 trades，60/90 bps 成本更差。
  这说明当前文本/事件增量没有覆盖 turnover economics；
- LLM 轮没有预先冻结 provider/model/prompt/schema/response corpus，按预注册 blocker 记为 1 个真实失败。
  未用临时在线回答污染历史回测；
- synthetic long/short momentum 在 30/60/90 bps 下累计约 -7.18%/-32.98%/-51.65%；residual short 为
  -54.39%/-68.94%/-78.87%。更关键的是没有历史 PIT locate/quantity/fee/recall，所以两轮均保持
  `RESEARCH_INCOMPLETE`，不进入资格或正式计数。

## 6. 证据复核

- ledger SHA-256：`a2215c21d17280a3d867a20999cd2a92d33bc4d397cc40b443ff6790efbe1de1`；
- ledger head：`d056cbee3a5d276855c72c78f71c70fda273eef02ffb3d222750d0a087d6a276`；
- 29 个 ARTIFACT_BOUND 路径全部存在且 SHA-256 匹配；
- 10 个 Qualification V2 artifact 全部从原始输入重新计算成功，且没有 input、ledger、commit、computed digest
  tamper；
- 27 条资格结论有 27 个唯一 candidate ID，10 条 full qualification + 17 条 prescreen rejection，交集为空；
- 最终资格共同区间为 2015-01-02 至 2024-12-31，共 2,516 sessions；
- 报告仍明确 `automatic_promotion_eligible=false`、`historical_oos_claim_allowed=false`。

## 7. 回归与额外审计发现

最终相关全域测试结果为 `1814 passed, 8 skipped, 0 failed`（1,822 collected，18:56）。另外执行了 31 项
真实数据 forward/PAPER 补跑、40 项本轮边界/治理针对性回归，以及所有改动文件的 ruff 与 `git diff --check`。

完整回归首次在隔离 worktree 运行时发现 `data/daily` 没有挂载：它被 `.gitignore` 排除，loader 收到空 panel 后
在空 `RangeIndex` 上做 Timestamp 比较。挂载主项目真实日线后原 14 个 PAPER/forward 失败全部通过，但异常形态本身
仍暴露了真实边界缺口。因此同时修复 robustness 与 manual PAPER loader：空源返回空 `DatetimeIndex` 并由上层给出
“no price data”，整数 index 明确拒绝，禁止被 pandas 静默解释为 1970 epoch 纳秒。

另有 6 个 sealed evaluator 测试被旧
`research/registries/strategy_artifacts/dual_index_growth_v1/observation_v1.json` 的
`core/data/price_access.py` component drift 提前拒绝。生产拒绝是正确行为；旧 evidence 没有被重签。测试改为在临时
repo 构造绑定当前组件的独立 PAPER artifact，因此既保留 fail-closed，又恢复 worker、budget、late registration 与
timeout 路径的实际覆盖。修复后 sealed 测试 16/16 通过。

测试用 `data/daily` 绝对路径符号链接已在回归后移入系统回收站，没有进入提交。

## 8. 当前边界和下一步

本 campaign 已到用户指定的 30 轮出口，不能在看过结果后追加第 31 个 sibling，也不能调低 DSR 制造 PASS。
新的年度相对 MaxDD 规则只向前适用，不重开或重签本轮。当前正确状态是：**0 formal、2 个探索性
REVIEW_HOLD、short/LLM 均未伪装完成**。

下一步不应立即继续历史搜索。优先级应是：

1. 建立 trusted future source-batch bridge，保证未来候选数据的 observed/available/hash 能进入 PAPER consumer；
2. 若决定观察两个 REVIEW_HOLD，必须先单独批准“非正式 shadow observation”协议，且结果不得反馈本 miner；
3. short 从未来 broker borrow batch 开始采集 locate/quantity/fee/recall，再谈冻结 short PAPER candidate；
4. 下一次独立 mining campaign 必须新建 preregistration 与 ledger，等新增数据或真正不同的经济机制后再开始，
   不能围绕本次赢家做局部参数追逐。

因此本轮没有启动新候选 PAPER：不是流程没做完，而是没有候选取得这项权限。
