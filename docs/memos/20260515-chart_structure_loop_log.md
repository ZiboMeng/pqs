# Chart-structure 输入表征层 —— ralph-loop 执行日志

**Lineage**: `chart-structure-input-repr-2026-05-15`
**主 PRD**: `docs/prd/20260515-chart_structure_input_representation_prd.md`
**execution PRD**: `docs/prd/20260515-chart_structure_ralph_loop_execution_prd.md`

每 round 追加一份 11-part 报告。

---

## P1·R1 — causal swing core(2026-05-15)

**1. 本轮主题**: Phase 1 / Round 1(build round)。

**2. 本轮目标**: ship `core/factors/swing_structure.py` 的因果 swing-序列
基建 —— `SwingPoint` / `SwingStructureConfig` dataclass、`detect_raw_swings`
(compute-once)、`_collapse_alternating`(§B-B2 规则)、`confirmed_swings_asof`
(因果过滤)。验收门:P1-A2 因果 hard test + §B-B2 collapse 测试 green。

**3. 为什么这轮优先做它**: 12 个特征(R2)全部依赖一个**因果正确**的 swing
序列。因果性是 Phase 1 的核心正确性要求(主 PRD §3.4)——
基建不对,后面所有特征都带 leakage。先把这块锤死。

**4. 做了什么**:
- 实现 `swing_structure.py`(R1 scope):4 个公共符号 + collapse 内部函数。
- **实现时抓到一个因果 bug**:原 PRD §3.5 把 API 写成
  `confirmed_swings_asof(bars, cfg, t_idx)`,若实现成「先 collapse 整条
  序列再按 t filter」——**非因果**。§B-B2 的 collapse 规则是「连续同 kind
  取更极端者」;先 collapse 会用一个**未来**的 swing 决定丢弃哪个过去
  swing,第 t 日 swing 读数被未来污染。改成 **filter-then-collapse**:
  `detect_raw_swings` 返回 raw(未 collapse)极值(raw 极值只依赖
  `[i-n,i+n]` 窗口,本身因果),`confirmed_swings_asof` 先按
  `confirmation_idx ≤ t` 过滤再 collapse。
- 同步修主 PRD §3.4 + §3.5,把因果设计写清楚(commit 同一笔)。
- 退化 bar(同时是 strict swing-high 和 swing-low 的 engulfing bar)的
  确定性处理规则:drop。

**5. 修改了哪些文件**:
- 新增 `core/factors/swing_structure.py`
- 新增 `tests/unit/factors/test_swing_structure.py`(5 测试)
- 改 `docs/prd/20260515-chart_structure_input_representation_prd.md`
  §3.4 + §3.5(API 改为 filter-then-collapse,记录因果理由)

**6. 跑了哪些测试**:
- `test_swing_structure.py` 5 测试:`test_swing_structure_causal`(P1-A2)、
  `test_collapse_alternating_b2`(§B-B2)、`_already_alternating`、
  `_tie_keeps_earlier`、`test_detect_raw_swings_zigzag_nonempty`。
- 全量 `pytest`(G1)。

**7. 结果如何**: 5/5 P1·R1 测试 green;全量 `3202 passed, 1 skipped,
1 xfailed`(R1 前 3197 → +5 新测试,无回归)。**P1-A2 因果 hard test
PASS** —— 截断到 t 的面板算 vs 完整面板算,逐位相等。**§B-B2 collapse
PASS** —— 连续同 kind 取更极端、输出严格交替。

**8. 新问题 / 新机会**: 因果 bug 的发现说明主 PRD §3.5 原 API 签名
(`confirmed_swings_asof(bars,...)`)会诱导非因果实现 —— 已修。R2 实现 12
特征时,`confirmed_swings_asof` 的 per-t 调用会在每个 t 重跑 collapse;
collapse 是 O(已确认极值数),极值数 << bar 数,可接受(§B-B1 的 O(T²)
风险只针对 `detect_swing_extrema`,它已 compute-once)。R2 若要再快可做
增量 collapse,非必须。

**9. 剩余风险**: R2 的 12 特征构造仍是设计占位(`K`/`tol`/`maturity_cap`
是 PLACEHOLDER,§C);特征是否有 alpha 由 Phase 2A 裁判,R1/R2 不下结论。

**10. 下一轮建议方向**: P1·R2 —— 12 个特征 + `compute_swing_structure_factors`
+ `config/swing_structure.yaml`。验收门 P1-A1 ranges + P1-A6 config-sourced。

**11. TODO**:
- [x] P1·R1 causal swing core
- [ ] P1·R2 12 特征 + config
- [ ] P1·R3 registry 接线 + Phase 1 closeout

---

## P1·R2 — 12 swing-structure features(2026-05-15)

**1. 本轮主题**: Phase 1 / Round 2(build round)。

**2. 本轮目标**: ship family T 的 12 个特征 —— `compute_swing_structure_factors`
+ 12 feature 算子 + `FEATURE_REGISTRY` + `SWING_STRUCTURE_FEATURES` +
`config/swing_structure.yaml`。验收门:P1-A1 ranges + P1-A6 config-sourced。

**3. 为什么这轮优先做它**: R1 已铺好因果 swing 基建,R2 是 family T 的实质
内容 —— 没有特征,Phase 2A 无从检验。

**4. 做了什么**:
- **实现前发现 §3.3 的 metric bug** —— v2 draft 的特征 1/2/7/8/9 在严格
  交替 swing 序列里**退化**:相邻段恒反向 → `impulse_score` 的「dir_j =
  dir_{j−1}」恒假 → 恒 0;相邻段恒共端点 → `corrective_score` 的相邻段
  重叠恒真 → 恒 1;`trend_maturity` 的「consecutive_same_dir_legs」在交替
  序列 ill-defined;`seg_count_up/down` 恒近相等(差≤1),近常数无信息。
  **已上报用户,用户批准按 operator 修正方案走**。
- 修正:Elliott 的「递进 vs 重叠」本质是**隔 2 段/隔 2 swing 的同向比较**
  (浪 3 vs 浪 1)。`impulse_score` → 同 kind swing 对 (S[i],S[i−2]) 方向
  一致度;`corrective_score` → 隔一段同向段对重叠占比;`trend_maturity`
  → 连续同向同 kind 对 run;`seg_count_up/down` 替换为
  `swing_last_up_seg_len_pct` + `swing_net_drift_k`(有信息)。
- 实现 12 个 feature 算子(全部因果 —— 只用 `confirmed_swings_asof`)+
  `_Seg` / `_Ctx` 内部结构 + `FEATURE_REGISTRY`(D4 扩展开口)。
- swing 在 **close 序列**上检测(PRD §3.2);`config/swing_structure.yaml`
  + `load_swing_structure_config`。
- 同步修主 PRD §3.3(12 特征修正后定义 + 修正说明)。

**5. 修改了哪些文件**:
- 改 `core/factors/swing_structure.py`(+R2:12 特征 + compute fn + loader)
- 改 `tests/unit/factors/test_swing_structure.py`(+2:ranges、config-sourced)
- 新增 `config/swing_structure.yaml`
- 改主 PRD §3.3(12 特征修正定义)

**6. 跑了哪些测试**: `test_swing_structure_ranges`(P1-A1)、
`test_swing_structure_config_sourced`(P1-A6)+ R1 的 5 个;全量 `pytest`。

**7. 结果如何**: 7/7 swing_structure 测试 green;全量 `3204 passed,
1 skipped, 1 xfailed`(R2 前 3202 → +2,无回归)。**P1-A1**:12 特征全
产出、非 NaN 值全在定义域内([0,1] / 非负 / 有符号有限)、非空。
**P1-A6**:`config/swing_structure.yaml` 加载正确;K=8 vs K=4 输出有差异,
证明 K 来自 cfg 非 hardcode。

**8. 新问题 / 新机会**: 退化 metric 的发现说明 —— v2 PRD §3.3 的特征
公式是「写得快、没逐个在交替序列里验」的产物。已全部修正并写进 loop log
+ PRD。`tol`/`maturity_cap` 仍是 PLACEHOLDER,值待 Phase 2A 标定。

**9. 剩余风险**: `compute_swing_structure_factors` 是 per-symbol × per-t
Python 循环;79-universe 可接受,expanded universe(Phase 4)需关注耗时
(§B-B7 已登记)。特征是否有 alpha 由 Phase 2A 裁判。

**10. 下一轮建议方向**: P1·R3 —— registry 接线(family T → RESEARCH_FACTORS
175→187、FAMILIES_V2 19→20)+ factor_generator 接线 + 计数 tripwire +
Phase 1 closeout。

**11. TODO**:
- [x] P1·R1 causal swing core
- [x] P1·R2 12 特征 + config
- [ ] P1·R3 registry 接线 + Phase 1 closeout

---

## P1·R3 — registry wiring + Phase 1 closeout(2026-05-15)

**1. 本轮主题**: Phase 1 / Round 3(build round + Phase 1 closeout)。

**2. 本轮目标**: family T 进 registry —— RESEARCH_FACTORS 175→187、
FAMILIES_V2 19→20、`factor_generator` 接线、计数 tripwire、P1-A4 采样测试。
验收门:P1-A3 reachability + P1-A4 + P1-A5 全量 green。

**3. 为什么这轮优先做它**: R1/R2 造好了 module + 特征,但没进 registry
就不可被 mining 漏斗用。R3 收口 Phase 1。

**4. 做了什么**:
- `factor_registry.py`:RESEARCH_FACTORS +12 个 `swing_*` 名(Family T 注释块)。
- `research_miner.py`:`FAMILY_T_SWING_STRUCTURE` FamilyConfig → `FAMILIES_V2_EXTENDED`。
- `factor_generator.py`:import + `generate_all_factors` 接线
  `compute_swing_structure_factors`。
- `test_research_miner.py`:计数 tripwire 175→187 / 19→20;新增
  `test_family_t_sampled`(P1-A4,seed 13,80 family_first trials)。
- **性能修复(本轮新发现)**:接进 `generate_all_factors` 后全量 pytest
  ~11min→~24min —— per-t 重算 `confirmed_swings_asof` 是 O(T·E)。collapse
  是 left-fold → 增量 fold 等价批量。改 `compute_swing_structure_factors`
  为单次 detect + 随 confirmation_idx 增量 fold,O(T+E)。
  `generate_all_factors` 单测 24min 段→0.90s。新增
  `test_compute_factors_matches_reference` 守增量路径 bit-identical。

**5. 修改了哪些文件**:
- `core/factors/factor_registry.py`、`core/mining/research_miner.py`、
  `core/factors/factor_generator.py`、`core/factors/swing_structure.py`
- `tests/unit/mining/test_research_miner.py`、
  `tests/unit/factors/test_swing_structure.py`
- 新增 `docs/memos/20260515-chart_structure_phase1_closeout.md`

**6. 跑了哪些测试**: reachability(P1-A3,187/20)、`test_family_t_sampled`
(P1-A4)、registry generation、`test_compute_factors_matches_reference`、
swing 8 测试;全量 `pytest`。

**7. 结果如何**: 全量 `3206 passed, 1 skipped, 1 xfailed`(R3 前 3204 →
+2,无回归)。P1-A3/A4/A5/A6 全过。**残留**:全量 pytest 21.5min vs R2
基线 ~11min —— 增量优化解决了算法级 O(T·E),残留 ~2× 是 per-(symbol,date)
Python feature loop 的固有线性成本(12 个结构特征、变长 swing 窗口,难
向量化)。已更新 §B-B7。

**8. 新问题 / 新机会**: §B-B7 perf 风险在 test 规模就 materialize 了
(不止 expanded universe)。增量 collapse 已修算法级;feature loop 的
向量化是后续可选优化(变长窗口难向量化,非阻塞)。

**9. 剩余风险**: 全量 suite ~21min(可接受未阻塞);`tol`/`maturity_cap`/`K`
仍 PLACEHOLDER。

**10. 下一轮建议方向**: Phase 1 收口 → `CHARTSTRUCT-P1-DONE`。Phase 2A
fire(incremental-IC 配对检验)。

**11. TODO**:
- [x] P1·R1 / P1·R2 / P1·R3 —— Phase 1 全部完成
- [ ] Phase 2A:incremental-IC 配对检验
- [ ] Phase 2B / Phase 4 / Phase 3

---

## P2A·R1 — incremental-IC harness(2026-05-15)

**1. 主题**: Phase 2A / R1(build round)。
**2. 目标**: 建 `phase2a_incremental_ic.py` —— 配对检验 harness。
**3. 为什么**: Phase 1 family T 已 ship,要回答「结构输入有没有新增信息」
必须有配对检验工具。
**4. 做了什么**: harness:对照=RESEARCH_FACTORS−12 swing;实验=+family T;
同 fold/seed/`colsample_bytree=1.0`(B3);per-year Rank IC + 配对 t 检验;
K∈{6,8,12} 扫。3 个 pure-helper 单测。
**5. 文件**: 新增 `dev/scripts/chart_structure/phase2a_incremental_ic.py`、
`tests/unit/chart_structure/{__init__,test_phase2a_helpers}.py`。
**6. 测试**: 3 helper 单测 green;harness import 校验。
**7. 结果**: harness ready。commit `ec535dd`。
**8. 新问题**: 无。
**9. 剩余风险**: 实验结果未知(R2 跑)。
**10. 下一轮**: P2A·R2 跑实验。
**11. TODO**: R2 跑 incremental-IC。

---

## P2A·R2 — run incremental-IC + Phase 2A closeout(2026-05-15)

**1. 主题**: Phase 2A / R2(experiment round)。
**2. 目标**: 跑 K∈{6,8,12} incremental-IC,出 verdict + Phase 2A closeout。
**3. 为什么**: 这是 Phase 2A 的核心实验 —— 结构输入到底有没有用。
**4. 做了什么**: 在真实 79-symbol × 4276-day 面板上跑了配对实验
(对照 101 因子 / 实验 113 因子,rank:ndcg,17 年 LOTYO)。
**5. 文件**: 新增报告 `data/audit/chart_structure/phase2a_incremental_ic.json`、
`tests/unit/chart_structure/test_phase2a_report.py`、Phase 2A closeout memo。
**6. 测试/实验**: incremental-IC 实验(414s);report schema 单测。
**7. 结果**: **family T 无显著正增量 IC** —— K=6 平均 ΔIC=+0.0075/p=0.078
(最接近)、K=8 p=0.54、K=12 p=0.38。三个 K 全 p>0.05。verdict
config-scoped。这是 experiment round 的负结果 —— **round 仍 PASS**(实验
跑了、报告产出、verdict 记录),loop 不终止。
**8. 新问题**: root-cause = family T 与对照组已有的 Family R 图形 + Family D
趋势 + 动量因子**高度冗余**,在已富的 101-factor baseline 上增量信号弱。
K=6(短窗口)最接近显著 → 结构信号 faint 存在、偏短周期。
**9. 剩余风险**: family T alpha 弱(但未废弃,留漏斗);`tol`/`maturity_cap`
仍 PLACEHOLDER。Phase 2B 是独立表示轴,负结果不预判它。
**10. 下一轮**: Phase 2B(bridge + embedding)。
**11. TODO**:
- [x] Phase 2A 完成(family T 无显著增量,config-scoped)
- [ ] Phase 2B / Phase 4 / Phase 3

---

## P2B·R1 — MiniROCKET bridge 表示层(2026-05-15)

**1. 主题**: Phase 2B / R1(build round)。
**2. 目标**: 建「手工特征 → 深度 CNN」之间的中间表示层。
**3. 为什么**: Phase 2A 负结果后,需要一个比 12 手工特征更丰富、但比 CNN
便宜的表示轴去独立检验「结构输入」。MiniROCKET 是文献证据强的随机卷积
基线(Dempster 2021)。
**4. 做了什么**: `core/ml/subsequence_transforms.py` —— numpy 自实现的
MiniROCKET 式变换:84 个固定 length-9 卷积核(权重 {-1,2},每核三个 +2,
mean-zero)+ dilation + PPV 池化;`rolling_minirocket_ppv_mean` 严格因果。
**5. 文件**: 新增 `core/ml/subsequence_transforms.py`、
`tests/unit/ml/test_subsequence_transforms.py`(5 单测)。
**6. 测试**: 5 单测 green(84 核校验、PPV∈[0,1]、短序列全 NaN、因果硬测)。
**7. 结果**: bridge 层 ready。commit `a4f1d1a`。
**8. 新问题**: 无。
**9. 剩余风险**: TS2Vec / GAF(R2-R4)还没接;注入实验后续。
**10. 下一轮**: 用户决策 option A —— 先跑 Phase 4 universe 扩张。
**11. TODO**: Phase 4 → 再回 Phase 2B R2-R4。

---

## P4·R1 — universe resolver + --universe flag(2026-05-15)

**1. 主题**: Phase 4 / R1(build round)。
**2. 目标**: 建 universe 解析单一入口,落实 D6 隔离契约。
**3. 为什么**: universe 扩张绝不能回溯影响任何旧结论 —— 必须有 flag 指定
用哪个 universe,且默认 `executable` 必须 bit-for-bit 复现 Phase-4 之前的
79-symbol 构造。
**4. 做了什么**: `core/universe/universe_resolver.py` ——
`resolve_universe(name="executable"|"expanded_v1")`;`executable` 复现
`union(seed+sector+factor+cross_asset)` 减 blacklist/macro/cycle-drop 再
补 SPY/QQQ,**逐符号、顺序一致**;`expanded_v1` 读
`config/universe_expanded_v1.yaml`(未建时 clean FileNotFoundError)。
`phase2a_incremental_ic.py` 接 `--universe` flag。
**5. 文件**: 新增 `core/universe/universe_resolver.py`、
`tests/unit/universe/test_universe_resolver.py`(6 单测)。
**6. 测试**: 6 单测(含 bit-for-bit 构造测、unknown-name raise)。
**7. 结果**: `resolve_universe("executable")` = 79 符号,与
`config/executable_universe.yaml` 完全一致。commit `c7fe737`。
**8. 新问题**: 无。
**9. 剩余风险**: expanded_v1 yaml 还没建(R2)。
**10. 下一轮**: P4·R2 建 expanded universe + ingest。
**11. TODO**: P4·R2 / P4·R3。

---

## P4·R2 — expanded universe build + ingest + 数据多轮 audit(2026-05-16)

**1. 主题**: Phase 4 / R2(build round)。
**2. 目标**: 建 `config/universe_expanded_v1.yaml`、ingest 数据、过 P4-A4。
**3. 为什么**: Phase 2A 负结果根因之一是「79-universe 太小 + 老因子已饱
和」;扩 universe 是在更大样本上重检验结构输入的数据前提,也直接攻
sibling-by-construction 根因。
**4. 做了什么**:
(a) 覆盖度 audit(`phase4_universe_audit.py`)扫 25344 个
`data/daily/*.parquet` —— **发现 store 重大问题:3357 个长覆盖 ticker
带 weekend-row(off-by-one 日期标签 bug 的规模化版本),只有 82 个干净**。
(b) 按 252-bar 中位美元成交额排名,选 top 非-79 流动性符号;**240 个 corrupt
符号经 fixed `YFinanceProvider(auto_adjust=True)` 重新 ingest**(split+div
调整连续序列,适配 chart-structure 特征研究),11 个本就干净的 polygon
符号保留;同步写 `bar_provenance.parquet`。
(c) **应用户「数据一定要干净、多做几轮 audit」要求,跑 4 轮数据 audit**
(`phase4_data_audit.py`):R1 索引卫生 / R2 OHLC 有效性 / R3 动态(完整度
+ 跳变)/ R4 边界(跨源字节稳定 + D6 隔离)。
(d) audit 抓到 2 个真问题并修掉:**DOW/SE** —— IPO 晚于 2015(DOW Inc
2019-03-20、Sea 2017-10-20),yfinance 批量下载把它们 NaN-pad 回 2015 起点;
parquet 裁到真实首日、从 expanded_v1 剔除。R3 gap 检测把美股假期误算成
缺口的 false-positive 修掉(改为 defer 到权威
`data_completeness_gate`)。
**5. 文件**: 新增 `config/universe_expanded_v1.yaml`(249 expanded_symbols)、
`dev/scripts/chart_structure/phase4_{universe_audit,ingest_expanded,data_audit}.py`、
`data/audit/chart_structure/phase4_{universe_audit,data_audit}.json`。
**6. 测试/实验**: 240 符号重 ingest(0 失败);4 轮数据 audit;resolver 6
单测(5 pass / 1 skip —— expanded_v1 yaml 已建,raise 测正确 skip)。
**7. 结果**: **expanded_v1 = 79 base + 249 added = 328 符号**。数据 audit
**4 轮全 PASS**:R1 索引 328/328;R2 OHLC 0 fail / 1 benign warn(XLI base-79
末 bar high<open 0.04%);R3 完整度 gate 328/328 + 7 个 added 符号真实事件
跳变(AMD 2016 财报、INSM/ALNY 生物科技 Phase 3、PG&E 破产、DHR 分拆)
+ 21 个 base-79 raw-store split 跳变(预期 —— raw 存储,read-time 调整);
R4 跨源字节稳定 + 0 D6 泄漏。**249 个 added 符号:0 weekend、0 缺失
session、0 OHLC 违规、0 NaN**。P4-A4 PASS。
**8. 新问题**: data/daily store 里 3357 个 ticker 带 off-by-one weekend-row
—— 这是已知 bug 的规模化遗留,executable-79 不受影响(早已修),但 store
广域未重建。本轮只重建了选入 expanded_v1 的部分。
**9. 剩余风险**: expanded_v1 是 mixed-source(79 polygon raw + 249 yfinance
auto_adjust),已在 yaml + artifact flag;research-only、D6 隔离、不碰
execution,rank-IC 研究可接受。
**10. 下一轮**: P4·R3 —— universe 隔离回归测 + Phase 4 closeout。
**11. TODO**:
- [x] P4·R1 resolver / P4·R2 build+ingest+数据 audit 完成
- [ ] P4·R3(隔离回归测 + closeout)/ Phase 2B R2-R4 / Phase 3
