# 回测稳健性补全 PRD (Backtest Robustness Completion)

**日期**: 2026-05-17
**lineage**: `backtest-robustness-completion-2026-05-17`
**状态**: DRAFT — 待用户 explicit-go 后才进入实现
**触发**: 用户问"backtest 是否需要接成熟框架/怎么避免过拟合假阳性/
不同 window 要不要 weighting/失效怎么判断"。operator 实查代码 + 4 篇
方法论 websearch(非市场数据,符合 `feedback_websearch_sealed_data_discipline`)
后得出:**骨架已是文献级,但有 5 处"做出来了没做透"**。
**纪律**: `feedback_audit_surfaces_not_thorough`(audit=暴露没做透+纠正
overclaim)、`feedback_no_blanket_failure_verdict`、
`feedback_self_audit_methodology`、`feedback_no_over_conservative_scoping`
(5 项全进 scope,排序≠砍 scope)、`feedback_pre_post_audit_must_smoke_observe`、
`feedback_temporal_split_discipline`。

---

## §0 一句话(大白话)

不换回测框架(自研引擎窄而专、且一致性不变量是项目命根子,换=推倒
重挣信任)。**改为补全 5 处文献标准没做透的地方**,且**几乎全是"用
已存档数据重算 + 诚实重述",不是重跑**;唯一可能烧算力的回溯项
(CPCV 历史验收)**主动设成 new-cycle-only 不做回溯**。

---

## §1 背景:已有什么 vs 文献标准 vs 没做透(审计对照表)

**先纠正 operator 自己上一轮的 overclaim**(诚实留痕,Phase 2A 先例):
之前跟用户说 ML-redo landmark "DSR≈1 = 几乎肯定不是运气"——**夸大了**。
`core/research/overfit_metrics.deflated_sharpe_ratio` 被调用时
`n_trials` 在 ML-redo 脚本里硬编码 3(`run_c3c4` / `run_d4`)或
`len(arms)`,**不是真实 mining trial 数**。Bailey & López de Prado
反复强调:DSR 最关键输入就是真实 trial 数;N 低估 → DSR 偏乐观。
landmark 的 IC 符号+幅度结论不依赖 DSR(仍成立),但"DSR≈1 所以不是
运气"在 N 修对前站不住。

| 用户问题 | 现状(实查) | 文献标准 | 没做透 gap | PRD 项 |
|---|---|---|---|---|
| 避免过拟合/假阳性 | DSR 已算 | DSR 的 N 须为真实 trial 数或 ONC 有效独立 N | N=placeholder → DSR 全线偏乐观 | **G1** |
| 同上 | `probability_backtest_overfitting` 函数写好 | PBO/CSCV 应在每次 mining sweep 跑 | **零 call site**(available-not-wired) | **G2** |
| 更准确 | 单路径 `walk_forward` | 单路径方差大易假发现;须有最小回测长度守卫 | 无 Min Backtest Length 守卫 | **G3** |
| 更准确 | `walk_forward` 单路径 + CPCV 各自独立 | 验收应吃 CPCV 分布而非单路径 | 验收链仍用单路径 | **G4** |
| 不同 window 要 weighting 吗 | 无 weighting | 见 §3 决策 | —— | **§3 决策(不加)** |
| 机制失效怎么判断 | forward 用阈值(Sharpe<0.4=RED)+drift+regime | CUSUM/backward-CUSUM/Page-Hinkley 变点 + rolling-PSR 退化 + IC 自相关 | 无任何变点/结构断点检测器,阈值=烂了才发现 | **G5** |

---

## §2 不换框架的依据(决策记录,不重复展开)

自研引擎 ~3000 行,窄而专,匹配 long-only/no-margin/no-short/日线+
日内执行层/单账户模拟的约束。换 vectorbt/backtrader/zipline/LEAN 的
代价由"重新挣回一致性不变量(M11a/M11b bit-for-bit parity、forward
4-scope 哈希、sealed fail-closed 全建立在引擎精确语义上)"主导,LOW
benefit / HIGH risk。**真正值得接外部库的不是替换引擎**,而是(a)算力
瓶颈时加向量化粗筛层喂回同一 canonical 引擎,(b)期权线定价/greeks
库——两者均非本 PRD 范围,等真成瓶颈再单独立项。

---

## §3 设计决策:不同 window 要不要 weighting?——**不加(operator 独立判断)**

**决策:不给 acceptance score 按 recency/regime 加权。** 依据(文献+
操作经验一致):按窗口加权本身是一个新增"研究者自由度",会反向加重
过拟合(等于偷偷挑哪个窗口算数)。文献正解相反 = 用 CPCV 生成**分布**
看整体 mean/方差/PBO/DSR,而非给单路径窗口加权。per-regime **分开
报告**(已有 per-year + stress slice)是对的;**加权合成单一分数**
不是标准做法且危险。唯一站得住的"加权"是 IC 聚合按**样本量**加权
(观测多权重大),非时间近因——此项纳入 G4 的 CPCV 聚合实现细节。

---

## §4 五项规格 + machine-checkable 验收

### G1 — DSR 真实 trial 数 + ONC 有效独立 N
- **G1-A1**: `deflated_sharpe_ratio` 所有生产 call site 传**真实 trial
  数**(mining 链=该 study 的 archived/attempted trial 计数;ML/eval
  脚本=该实验真实配置数)。禁止硬编码常数。
- **G1-A2**: 新增 `effective_n_trials_onc(returns_matrix)`(López de
  Prado ONC 聚类求有效独立 N);**仅 forward-only**(过去 cycle 无
  per-trial 收益矩阵落盘——见 §6 限制),未来 cycle mining 内联调用。
- **G1-A3**: 提供 `recompute_dsr` 工具,对已存档候选/landmark 的
  **已存权益曲线**用保守真实 N 重算 DSR,产出诚实修订表(ML-redo
  R4/C2/C3/D3/D4 + cycle06/08 验收期 DSR)。结论(IC 类)不改,仅
  数字重述。
- **G1-A4**: ≥6 单测(N 传递正确性 / 硬编码回归防护 / ONC 退化 /
  recompute 与旧值差异方向 = DSR 下降或持平)。

### G2 — PBO 接入 mining sweep
- **G2-A1**: mining sweep 结束时构造 per-trial × per-CSCV-split
  perf_matrix → 调 `probability_backtest_overfitting` → 持久化进
  study artifact + Track A 报告。
- **G2-A2**: 过去 cycle **forward-only**(archive 仅标量,无 per-split
  矩阵,见 §6);**不为补 PBO 重跑任何历史 mining**。
- **G2-A3**: PBO > 0.5 在 Track A 报告标 red-flag(诊断,不自动
  kill,留人判定;阈值 config 化)。
- **G2-A4**: ≥4 单测(perf_matrix 形状 / PBO∈[0,1] / 全噪声→PBO≈0.5 /
  报告字段存在)。

### G3 — Minimum Backtest Length 守卫
- **G3-A1**: 实现 `minimum_backtest_length(observed_sr, n_trials,
  target_confidence)`(Bailey MinBTL/MinTRL),在 Track A 验收增加
  gate:回测长度 < MinBTL → fail-closed(可配置阈值)。
- **G3-A2**: 对已 forward 的 cycle06/08 **只重评估不重跑**(读已有
  权益长度 vs 夏普);若不达 MinBTL,产出**诚实证据质量注脚**,
  **不撤销其 forward 观察、不动 manifest/spec_hash**。
- **G3-A3**: ≥4 单测(MinBTL 单调性 / 边界 / fail-closed 触发 /
  retro-eval 只读不改 manifest)。

### G4 — 验收链 walk_forward 单路径 → CPCV 分布
- **G4-A1**: Track A 验收评估器从单路径 `walk_forward` 切到 CPCV
  分布(mean / 方差 / 分位 / 配合 G1 DSR + G2 PBO)。IC 聚合按样本量
  加权(§3 唯一允许的加权)。
- **G4-A2**: **new-cycle-only**。已 forward 的 cycle06/08 **不回溯
  重跑 CPCV 验收**——理由:它们已在真实 forward 观察(更强证据),
  回头补历史 CPCV 边际价值低。如用户日后明确要历史数字 → opt-in、
  限定范围、仅在无重活在飞时排期。
- **G4-A3**: 单路径 `walk_forward` 保留为诊断 API(不删,back-compat);
  仅"验收判定依据"切换。
- **G4-A4**: ≥6 单测(CPCV 分布字段 / 样本量加权正确 / 单路径 API
  保留 / new-cycle-only 不触历史候选 / 退化数据 fail-closed)。

### G5 — 机制失效早警检测器
- **G5-A1**: 新增 `core/research/decay_detector.py`:backward-CUSUM +
  Page-Hinkley 变点 + rolling-PSR 退化 + rolling-IC 自相关。纯计算,
  无副作用。
- **G5-A2**: 在 backtest 权益曲线(诊断)与 forward NAV(喂 TD
  verdict)上可调用。**喂 forward verdict 的部分锁死**:
  - 纯增量字段(manifest schema lazy-migration 兼容,`extra=forbid`
    新模型,旧 manifest 加载 = None)
  - **只作用于新 TD**,**不回溯重判已记录 TD**
  - 改 forward runner 前后**必须对全部活跃候选跑 `observe --dry-run`
    smoke**,验证 raw/canonical hash 无 drift、不误 fail-closed
    (`feedback_pre_post_audit_must_smoke_observe`)
  - 一次性 backfill 现有 manifest TD NAV 仅作**基线**(便宜、只读)
- **G5-A3**: 检测器输出并入 forward attention_report 的 GREEN/
  YELLOW/RED 作为**早警信号**(与现有阈值并存,不替换;触发=YELLOW
  提示而非自动终止,留人判定)。
- **G5-A4**: ≥8 单测(CUSUM 变点检出 / Page-Hinkley 灵敏度 /
  rolling-PSR 退化 / 新-TD-only 不回溯 / lazy-migration 旧 manifest /
  smoke-observe 契约 / 无变点时不误报 / 退化输入 graceful)。

---

## §5 对在跑工作的影响(Q1/Q2 确认结论,写入 PRD)

| 对象 | 影响 |
|---|---|
| cycle06 / cycle08 / pead forward 观察 | **G1-G4:零行为影响**(forward 链实测不消费 DSR/PBO/CPCV/MinBTL;spec_hash/manifest immutable),仅 G1/G3 诚实回溯重报验收期证据质量。**G5:设计上喂 TD verdict → 已锁增量+只作用新TD+smoke门** |
| trial9_001/002(completed_fail)、rcm_v1/cand_2(aborted) | 终态吸收,不受影响 |
| pead 独立 track / options sleeve | 独立路径;G5 仅在选择接入时影响,默认不接 |
| **D4(现在在跑)** | 起草/实现都不影响 D4(D4 远早于任何实现完成)。D4 自身用 N=3 placeholder DSR=G1 要修的同一处;D4 结论(from-scratch 输,IC 比较)不依赖 DSR,稳;报数时明确加 N=3 caveat |

**实现排期硬规则**:任何 G1-G5 代码改动**不在 D4 或任何重跑在飞时
落地**(串行纪律);G5 动 forward runner 部分落地前必须过 smoke-observe
门才允许作用活跃候选。

---

## §6 限制与诚实记录(不藏到实现阶段)

- **G1 effective-N(ONC)/ G2 PBO 过去 cycle = forward-only**:
  `rcm_trials` 表实查只存**标量汇总**(objective/nav_sharpe/
  nav_max_dd/nav_corr…),**无 per-trial 每日收益序列、无 per-split
  perf 矩阵**。ONC 要收益相关矩阵、PBO/CSCV 要 per-split 矩阵——均
  未落盘。**明确不为补这两项重跑任何历史 200-trial mining**;过去
  cycle 标 `not_retroactively_available_forward_only`,如实记录不假装。
  未来 cycle mining 内联产出(用本来就在跑的 trial,零额外算力)。
- **G4 不回溯**:cycle06/08 历史 CPCV 验收 new-cycle-only。
- **G3 retro 只读**:对已 forward 候选仅产证据质量注脚,不撤观察。
- 全 PRD config-scoped 阈值化(MinBTL 置信度 / PBO 红旗阈值 /
  CUSUM 灵敏度 / DSR 阈值均 config,不硬编码)。
- sealed 2026 全程不读(本 PRD 不涉 sealed 评估)。

---

## §7 非目标 / deferred

- 不换回测框架(§2)。
- 不实现向量化粗筛层 / 期权定价库(等真成瓶颈单独立项)。
- 不对 cycle06/08 回溯重跑 CPCV / 重跑历史 mining 补 PBO/effective-N
  (§4 G2-A2 / G4-A2 / §6)。
- 不改 long-only/no-margin/no-short/QQQ rule/pricing semantics。
- window weighting 不加(§3,记录为明确否决,非 deferred)。

---

## §8 实现排序(sequencing,非 scope-limiting;5 项全进 scope)

1. G1(纯重算+自我修正,无 forward 风险,先落把 overclaim 修掉)
2. G2(增量报告,无 forward 风险)
3. G3(增量 gate,retro 只读)
4. G4(验收链切换,new-cycle-only)
5. G5(动 forward runner,最后做,smoke-observe 门为硬前置)

每项独立 commit + 单测 + 11-part 报告;G5 落地前置 smoke-observe gate。
实现需用户在本 PRD explicit-go 后启动;遵 D4/重活串行规则。

---

## §9 验收口径

- 全 5 项 machine-checkable AC(§4)+ §5 影响矩阵兑现 + §6 限制如实
  落 artifact + G5 smoke-observe 契约测试通过 = PRD 完成门。
- operator 自我 overclaim 修正(§1 DSR-N)在 G1 完成时同步回填
  ML-redo closeout / plain-summary / CLAUDE.md 对应行,诚实留痕。
- 4-tier 自审(R1 事实/R2 逻辑/R3 真跑对比期望/R4 边界)+ 禁 blanket
  verdict。

---

## §10 参考(均方法论,非市场数据)

- Bailey & López de Prado, *The Deflated Sharpe Ratio*
  (davidhbailey.com/dhbpapers/deflated-sharpe.pdf)
- Bailey, Borwein, López de Prado, Zhu, *The Probability of Backtest
  Overfitting* (SSRN 2326253)
- QuantInsti, *Cross-validation in finance: purging/embargo/
  combinatorial*
- *Backward CUSUM for monitoring structural change* (arXiv 2003.02682)
- VertoxQuant, *Strategy Decay Detection — alpha erosion warning system*
