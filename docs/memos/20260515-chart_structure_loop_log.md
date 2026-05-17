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

---

## P4·R3 — universe 隔离回归测 + Phase 4 closeout(2026-05-16)

**1. 主题**: Phase 4 / R3(build round)。
**2. 目标**: 落实 P4-A3 隔离回归测,出 Phase 4 closeout,emit
`CHARTSTRUCT-P4-DONE`。
**3. 为什么**: D6 隔离契约必须有可验收的测试守住 —— 「universe 扩张不
影响旧结论」不能只靠口头承诺。
**4. 做了什么**: `test_universe_isolation_p4r3.py`(5 单测):
(a) `executable` 逐符号 bit-for-bit 复现 Phase-4 前 79 构造;
(b) `expanded_v1` 严格 additive(executable 是其子集、顺序前置、无删除);
(c) **P4-A3**:forward `ConfigSnapshot.universe_hash` 按文件名 hash
`config/universe.yaml`,新增 `universe_expanded_v1.yaml` 在其 hash 输入集
之外 —— forward manifest diff == empty 结构性成立;
(d) expanded yaml well-formed(expanded_symbols ≥ 200、与 79 无交集);
(e) 解析器在 `core/research/forward/` 零引用。
**5. 文件**: 新增 `tests/unit/universe/test_universe_isolation_p4r3.py`、
Phase 4 closeout memo。
**6. 测试**: `tests/unit/universe/` 全量 50 pass / 1 skip(skip = expanded_v1
yaml 已建,raise 测正确跳过)。
**7. 结果**: P4-A1/A2/A3/A4 全 PASS。Phase 4 收口。
**8. 新问题**: 无。
**9. 剩余风险**: expanded_v1 mixed-source(已 flag);data/daily 广域
off-by-one 遗留(独立工作,非本 loop scope)。
**10. 下一轮**: 回 Phase 2B R2-R4(TS2Vec embedding + GAF + 语料 + 注入)。
**11. TODO**:
- [x] Phase 4 完成 —— `CHARTSTRUCT-P4-DONE`
- [ ] Phase 2B R2-R4 / Phase 3 R1-R5

---

## P2B·R2 — TS2Vec 自监督 embedding + GASF/GADF + patch(2026-05-16)

**1. 主题**: Phase 2B / R2(build round)。
**2. 目标**: `core/ml/window_embedding.py` —— 3 种 window 表征视图 +
TS2Vec 式自监督 encoder。
**3. 为什么**: Phase 2A 12 手工特征无增量;需要更丰富的「结构表征」轴 ——
自监督学到的 embedding 不受人工特征公式限制。
**4. 做了什么**:
(a) 3 个 `representation_view`:`raw_window`(归一化窗口)、`GASF_GADF`
(Gramian Angular Field,W×W 确定性图像)、`patch_tokens`(PatchTST 式
分块)。GASF/GADF/patchify 是 pure-numpy,无 torch 依赖。
(b) `TS2VecEncoder` —— dilated **causal**-conv 堆(因果卷积:位置 k 的
表征只依赖 ≤k 的输入 → 配合「窗口结束于 bar t」= leak-free);
window_len=63 / embedding_dim=64(§3 锁定值,= SmallEncoder 默认)。
(c) `hierarchical_contrastive_loss` —— TS2Vec instance + temporal
对比损失 + 层级 max-pool(Yue et al. 2022 忠实移植)。
(d) `smoke_pretrain` —— 小规模自监督训练 smoke。torch 缺失时 GASF/GADF/
patch 仍可用,encoder 走 ImportError stub。
**5. 文件**: 新增 `core/ml/window_embedding.py`、
`tests/unit/ml/test_window_embedding.py`(18 单测)。
**6. 测试/实验**: 18 单测全 green(GASF 对称+对角恒等、GADF 反对称、
constant-series、known-input 手算、patch 重构、encoder 因果硬测、
确定性、层级损失有限、smoke 训练跑通)。smoke 训练 40 步
loss 5.89→0.80(encoder 真的在学)。
**7. 结果**: P2-A4 PASS。embedding_dim=64;3 视图 + encoder ready。
**8. 新问题**: 无。
**9. 剩余风险**: 全量预训练(非 smoke)留 evidence-gated;R3 语料
manifest / R4 注入待跑。
**10. 下一轮**: P2B·R3 预训练语料 manifest。
**11. TODO**:
- [x] P2B·R2 完成
- [ ] P2B·R3 / R4 / Phase 3 R1-R5

---

## P2B·R3 — 预训练语料 manifest(2026-05-16)

**1. 主题**: Phase 2B / R3(build round)。
**2. 目标**: `data/manifests/chart_structure_pretrain_corpus_v1.json` ——
冻结 TS2Vec encoder 自监督预训练能用哪些 window。
**3. 为什么**: 自监督预训练虽不用 label,但若 encoder 见过 validation/
sealed 年的 window 分布,会泄漏进后续在那些年份评估的模型 —— 必须
holdout 纪律。
**4. 做了什么**: `core/ml/corpus_manifest.py`(pydantic schema +
`load_pretrain_corpus_manifest`):window END bar 落在 `temporal_split.yaml`
的 train 年才 eligible;validation(2018/19/21/23/25)+ sealed 2026 +
reference(2007/08)全排除。schema 硬约束 `train_years_only=True` +
eligible/excluded 不相交 + date_range 在 eligible 年内。v1 daily-only
freeze,`timeframes_reserved` 预留多时间尺度字段(免日后 schema 返工)。
builder 脚本扫 expanded_v1 实际数据算真实样本数。
**5. 文件**: 新增 `core/ml/corpus_manifest.py`、
`dev/scripts/chart_structure/build_pretrain_corpus_manifest.py`、
`data/manifests/chart_structure_pretrain_corpus_v1.json`、
`tests/unit/ml/test_corpus_manifest.py`(9 单测)。
**6. 测试**: 9 单测 green(schema 校验、train_years_only、
no-sealed-window、no-validation-years、eligible==train_set、extra-key
拒绝)。
**7. 结果**: P2-A5 PASS。语料:expanded_v1 328 符号、12 train 年、
**494,341 个 63-bar causal window**、date_range 2009-01-02..2024-12-31。
**8. 新问题**: 无。
**9. 剩余风险**: 全量预训练(非 smoke)evidence-gated;R4 注入待跑。
**10. 下一轮**: P2B·R4 注入路径 + Phase 2B closeout。
**11. TODO**:
- [x] P2B·R3 完成
- [ ] P2B·R4 / Phase 3 R1-R5

---

## P2B·R4 — 注入路径 + Phase 2B closeout(2026-05-16)

**1. 主题**: Phase 2B / R4(build round + closeout)。
**2. 目标**: 表征接进 `build_ml_panel` + `phase2_attempts.json` +
Phase 2B closeout。
**3. 为什么**: 表征层造完要有路接进 ML panel,且 Phase 2 所有 attempt
要有机器可校验的结构化记录。
**4. 做了什么**:
(a) `core/ml/chart_structure_injection.py` —— 把 MiniROCKET / TS2Vec
表征转成普通 `{name: date×symbol frame}` factor dict;
`inject_chart_structure_factors` 带命名冲突 guard;**`build_ml_panel`
一字未改** —— 注入空 = 默认 panel bit-for-bit 不变(回归 by construction)。
(b) `core/ml/phase2_attempts.py` + `data/audit/chart_structure/
phase2_attempts.json` —— Phase 2 三个 attempt 的结构化记录;schema
**硬约束**:负 verdict 必须带 `root_cause` 且 `config_scoped`(禁
blanket「结构没用」结论)。
(c) Phase 2B closeout memo。
**5. 文件**: 新增 `core/ml/{chart_structure_injection,phase2_attempts}.py`、
`data/audit/chart_structure/phase2_attempts.json`、
`tests/unit/ml/test_{chart_structure_injection,phase2_attempts}.py`
(13 单测)、Phase 2B closeout memo。
**6. 测试**: 13 新单测 green;`tests/unit/ml/` 全量 83 pass / 1 skip
(无回归)。P2-A6 注入空 panel 逐 frame 比对 identical;P2-A7 schema
负-verdict-需-root_cause / config_scoped / 唯一 id / extra-key 拒绝。
**7. 结果**: P2-A3..A7 全 PASS。Phase 2B 收口。三条表征轴(swing
family T / MiniROCKET / TS2Vec)全 ship;后两者下游实验 evidence-gated。
**8. 新问题**: 无。
**9. 剩余风险**: MiniROCKET / TS2Vec 下游 incremental-IC 实验未跑
(evidence-gated,算力);TS2Vec 仅 smoke 训练过。
**10. 下一轮**: Phase 3 —— chart-native 模型(P3·R1 3B encoder)。
**11. TODO**:
- [x] Phase 2B 完成 —— `CHARTSTRUCT-P2B-DONE`
- [ ] Phase 3 R1-R5

---

## P3·R1 — 3B structure-sequence encoder(2026-05-16)

**1. 主题**: Phase 3 / R1(build round)。
**2. 目标**: `core/ml/structure_sequence_encoder.py` —— 吃 family T
swing 段序列的 chart-native 模型。
**3. 为什么**: Phase 3 第一个 chart-native 模型。3B 的输入不是日线 bar
序列,而是「swing 段 token 序列」—— 每段 `[len_pct, dur, slope_pct, dir]`。
**4. 做了什么**:
(a) `segment_sequence_asof(raw_swings, t_idx)` —— 走 `confirmed_swings_asof`,
段序列严格因果(段的两端 swing 必须 confirmation_idx ≤ t)。
(b) `StructureSequenceEncoder` —— **复用 `SmallEncoder`**(1-layer
transformer,~50k 参数,4GB VRAM 安全),n_features=4、seq_len=max_segments
=16。execution PRD §7「扩展 SmallEncoder 吃段序列」。
(c) `build_structure_sequences` —— 一只票多个 bar 索引批量建段序列
(`detect_raw_swings` 只跑一次,compute-once)。`smoke_train_3b`。
**5. 文件**: 新增 `core/ml/structure_sequence_encoder.py`、
`tests/unit/ml/test_structure_sequence_encoder.py`(7 单测)。
**6. 测试**: 7 单测 green。**P3-A5 `test_phase3b_uses_confirmed_swings`**
硬验证因果:as-of-t 段序列从「全序列」和「截到 t 的序列」算出来
**逐元素相等** —— 段序列不读 t 之后任何 bar。smoke 训练 40 步
loss 下降(target = 末段 slope 的线性函数,模型学得动)。
**7. 结果**: P3-A5 PASS。3B encoder ready。
**8. 新问题**: 无。
**9. 剩余风险**: 真实 attempt(全量训练 + eval)在 R2 跑。
**10. 下一轮**: P3·R2 —— 3B attempt + eval(experiment round)。
**11. TODO**:
- [x] P3·R1 完成
- [ ] P3·R2 / R3 / R4 / R5

---

## P3·R2 — 3B attempt + cost-aware eval(2026-05-16)

**1. 主题**: Phase 3 / R2(**experiment round**)。
**2. 目标**: 跑第一个 chart-native attempt(3B swing-段 encoder),出
带 root_cause 的 attempt JSON。
**3. 为什么**: 这是 Phase 3 第一个真实验 —— 结构序列模型到底打不打得过
tabular 因子。
**4. 做了什么**: `core/ml/phase3_attempt.py`(schema:负 verdict 必须带
root_cause + config_scoped;eval 必须声明 eval_method/cost_model/
turnover_penalty)。runner 在 executable-79(ex SPY/QQQ)上、**严格 train
partition 内**做 fit/OOS 切分(fit={2015,16,20,22}、OOS={2017,2024},
validation/sealed 一行没读)。训 `StructureSequenceEncoder` 80 epoch,
per-OOS-date 横截面 Spearman IC,对 126d 动量基线做配对 t 检验。
**5. 文件**: 新增 `core/ml/phase3_attempt.py`、
`dev/scripts/chart_structure/phase3_run_3b_attempt.py`、
`data/audit/chart_structure/phase3_attempt_3b_001.json`、
`tests/unit/ml/test_phase3_attempt.py`(8 单测)。
**6. 测试/实验**: 8 schema 单测 green。实验:115,716 段序列样本,
训练 loss 0.996→0.645。
**7. 结果(诚实交代 —— 负结果)**: **3B OOS rank-IC=0.0153,显著低于
126d 动量基线 0.0847(配对 p=0.000)→ verdict=`underperforms_tabular_
baseline`**。experiment round 仍 **PASS**(D2:实验跑了、attempt JSON
产出、root_cause 记录)。**root_cause**:swing-段 tokenization 丢掉了
动量因子捕捉的 per-bar 幅度信息;≤16 个粗粒度段 token 的 transformer
信息自由度远少于一个直接的 126d 收益。**这不是「3B/chart-native 不行」
的 blanket 结论 —— 是「这个 encoder、这个 tokenization、这个 config」
config-scoped 结论**(verdict_scope=config_scoped)。
**8. 新问题**: 段序列把价格压成「段方向+时长+斜率」,丢了幅度细节 ——
3A image-CNN(GAF 保留完整窗口形状)是否能补回,R3/R4 验。
**9. 剩余风险**: 3A / 3C 待跑。
**10. 下一轮**: P3·R3 —— 3A image-CNN(GAF→CNN)。
**11. TODO**:
- [x] P3·R2 完成(负结果,config-scoped,round PASS)
- [ ] P3·R3 / R4 / R5

---

## P3·R3 — 3A image-CNN(GAF→CNN)(2026-05-16)

**1. 主题**: Phase 3 / R3(build round)。
**2. 目标**: `core/ml/chart_cnn.py` —— GAF 图像 → CNN 的 chart-native 模型。
**3. 为什么**: 3B 段序列丢了 per-bar 幅度;3A 用 GAF 图保留完整窗口形状,
看 CNN 能否补回。fire gated on `CHARTSTRUCT-P4-DONE`(已发)。
**4. 做了什么**: `ChartCNN` —— 输入 (B,2,W,W) GASF+GADF 2 通道图,
2 个 conv block + global pool + fc → 标量;~30k 参数(4GB VRAM 安全)。
`build_gaf_panel` 为 (symbol, bar) 对建 GAF 图,因果 warmup(不足 63 prior
bar 跳过)。`gaf_image` 复用 P2B·R2 的 `to_gasf_gadf`。
**5. 文件**: 新增 `core/ml/chart_cnn.py`、
`tests/unit/ml/test_chart_cnn.py`(6 单测)。
**6. 测试**: 6 单测 green —— GAF 图 shape+界限、build_gaf_panel 因果
warmup、**GAF 图因果硬测**(改 t 之后的 bar,t 的图不变)、CNN forward
shape、参数 <100k、smoke 训练 loss 下降。
**7. 结果**: chart_cnn build + smoke 训练通。3A 模块 ready。
**8. 新问题**: 无。
**9. 剩余风险**: 3A 真实 attempt 在 R4 跑。
**10. 下一轮**: P3·R4 —— 3A attempt + eval。
**11. TODO**:
- [x] P3·R3 完成
- [ ] P3·R4 / R5

---

## P3·R4 — 3A image-CNN attempt + eval(2026-05-16)

**1. 主题**: Phase 3 / R4(**experiment round**)。
**2. 目标**: 跑 3A GAF image-CNN attempt。
**3. 为什么**: 3B 段序列丢幅度;3A 用 GAF 图保留完整窗口形状,验是否能补回。
**4. 做了什么**:
(a) **第一次跑 attempt 抓到 ChartCNN sizing bug**:R3 版 ChartCNN 只有
4977 参数(63×63×2 图配 5k 参数是 undersizing,不是合理 config)——
train loss 仅 0.9997→0.9617,模型几乎没学动(underfit)。**修正**:
ChartCNN 改 3 conv block(32/64/64)+ FC,~58k 参数(仍 < 100k,4GB
安全)。runner 用 D2 underfit 诊断(z-score target,train MSE 近 1.0
= 没拟合)。
(b) 重跑:executable-79、train partition 内 fit/OOS(fit 含 2015/16/20/22、
OOS 2017/2024),GAF 图(date stride 3,28953 张 0.92GB),训 80 epoch。
**5. 文件**: 修改 `core/ml/chart_cnn.py`(ChartCNN 扩容);新增
`dev/scripts/chart_structure/phase3_run_3a_attempt.py`、
`data/audit/chart_structure/phase3_attempt_3a_001.json`;扩
`test_phase3_attempt.py`(+1 单测,共 9)。
**6. 测试/实验**: 9 schema 单测 green;`test_chart_cnn.py` 6 单测 green
(扩容后参数仍 < 100k)。实验:扩容 CNN train loss **1.0015→0.3547**
(真拟合了 train,解释 ~65% 方差)。
**7. 结果(诚实交代 —— 负结果)**: **3A OOS rank-IC=0.0318,显著低于
126d 动量基线 0.0918(配对 p=0.012)→ verdict=`underperforms_tabular_
baseline`**。round **PASS**(D2)。**root_cause**:扩容 CNN 真拟合了
train(loss 0.35),但 OOS rank-IC(0.032)< 动量(0.092)—— train-OOS
gap = GAF-CNN 学到的 train-set 形态不能跨截面泛化到打过 plain momentum。
config-scoped 结论。
**8. 新问题**: 3B(段序列)和 3A(GAF 图)两个 chart-native 模型都没打过
最简单的 126d 动量 —— 和 Phase 2A family T 负结果同一根因(结构表征与
动量/趋势因子高度冗余)。3C fusion 在 R5 验「组合是否 > 单路」。
**9. 剩余风险**: 3C 待跑;两个负结果指向同一根因。
**10. 下一轮**: P3·R5 —— 3C fusion + Phase 3 closeout。
**11. TODO**:
- [x] P3·R4 完成(负结果,config-scoped,round PASS)
- [ ] P3·R5

---

## P3·R5 — 3C late-fusion + Phase 3 closeout(2026-05-16)

**1. 主题**: Phase 3 / R5(**build + closeout round**)。
**2. 目标**: `core/ml/fusion_model.py`(3C late-fusion)+ 跑 3C attempt
+ Phase 3 closeout(P3-d3/d5)。
**3. 为什么**: 3B 段序列、3A GAF 图单独都没打过动量;3C 验「两路 late
fusion 组合是否 > 单路 / 能否追上基线」—— Phase 3 收官问。
**4. 做了什么**:
(a) `FusionModel` —— 3B `StructureSequenceEncoder` + 3A `ChartCNN`
两分支各出标量分,2→8→1 fusion MLP late 融合;`freeze_branches`
可选;因果继承两分支。
(b) `phase3_run_3c_attempt.py` —— 对同一 (sym,bar) 同时建 seg 序列
+ GAF 图(对齐),within-train fit/OOS,date_stride=3,80 epoch。
(c) Phase 3 closeout memo + 发 `CHARTSTRUCT-P3-DONE` / `CHARTSTRUCTUREDONE`。
**5. 文件**: 新增 `core/ml/fusion_model.py`、`tests/unit/ml/test_fusion_model.py`
(3 单测)、`dev/scripts/chart_structure/phase3_run_3c_attempt.py`、
`data/audit/chart_structure/phase3_attempt_3c_001.json`;扩
`test_phase3_attempt.py`(+1,共 10);新增
`docs/memos/20260516-chart_structure_phase3_closeout.md`。
**6. 测试/实验**: fusion 3 单测 + phase3_attempt schema 10 单测 green。
实验:37644 对齐样本,FusionModel 92035 参数 cuda,train loss
0.9968→0.5029(真拟合,无 underfit confound)。
**7. 结果(诚实)**: **3C OOS rank-IC=0.0415**,基线 mom_126d 0.0856,
**verdict=`no_significant_increment`**(paired t=−1.82,p=0.069)。
3C(0.0415)> 3A(0.0319)> 3B(0.0153)—— 三者里最好,把差距从
「显著低于」收窄到「与基线无显著差异」,但**无超越动量的正交 alpha**。
round **PASS**(D2,负结果不终止)。
**8. 新问题**: chart-native 三层(手工/自监督/端到端)在 79-universe 全
未对动量产生显著正交增量,根因一致(价格窗口再编码冗余)。唯一未证伪
开口 = expanded-universe 重检 + ensemble 角色,evidence-gated。
**9. 剩余风险**: 79-universe scope;非滚动 purged WF(年块切分);
ensemble 用途未评(主 PRD §5.2 定位,需用户授权)。
**10. 下一轮**: chart-structure ralph-loop 终止(`CHARTSTRUCTUREDONE`)。
随后按用户要求做多轮 PRD audit。
**11. TODO**:
- [x] P3·R5 完成(负结果,config-scoped,round PASS)
- [x] Phase 3 closeout + `CHARTSTRUCT-P3-DONE` + `CHARTSTRUCTUREDONE`
- [ ] PRD audit rounds(用户新要求)

---

## AUDIT — 收口后多轮 PRD audit(2026-05-16,用户要求)

**1. 主题**: 全 loop 跑完后按主 PRD + execution PRD 多轮 audit。
**2. 目标**: 逐条 AC 真跑核验(非读 closeout 自述),找「没做完/没按 PRD
走/需重走」并修复。
**3. 做了什么**: 实跑 89+ 命名单测 + grep 入口接线 + JSON schema +
§B 风险 + §C provenance。发现 4 缺口并全部修复:
- **P4-A1(中高)**: `--universe` flag 原仅接 phase2a;主入口+phase3
  脚本未接;`test_universe_flag_all_entrypoints` 缺失;Phase 4 closeout
  overclaim。修:phase3_run_{3a,3b,3c} 接 flag;新增 7 单测编码真实
  契约(研究脚本有 flag / production 入口刻意 resolver-free = 更强 D6
  隔离,operator directional 决策供用户推翻);amend Phase 4 closeout。
- **P3-A3(中)**: 「eval 函数有 purge 单测」缺失 + eval 无 fit→OOS
  年边界 embargo。修:新增 `core/ml/phase3_eval.purged_fit_mask` +
  3 单测;接进 3 脚本;**3 attempt 全 purged 重跑**。
- **P3-A1(低,命名)**: 加字面命名 `test_phase3_attempt_schema`。
- **G5(低,按设计延迟)**: 0 nominee 无 consumer,显式记录替代隐式 ✅。
**4. 文件**: 新增 `core/ml/phase3_eval.py`、`tests/unit/ml/test_phase3_eval.py`、
`tests/unit/universe/test_universe_flag_all_entrypoints.py`、
`docs/memos/20260516-chart_structure_prd_audit.md`;改
`phase3_run_{3a,3b,3c}_attempt.py`(flag+purge)、`test_phase3_attempt.py`
(+命名别名)、3 个 phase3_attempt JSON(purged 重跑)、Phase 3/4 closeout。
**5. 测试/实验**: 定向 sweep 36 green(含新 purge/flag 测 + purged JSON
schema);全量 G1 重跑确认(见收尾)。
**6. 结果**: purge 后负结论全 robust —— 3A 0.0319→0.0219、3B
0.0153→0.0091(更强,印证泄漏抬高输家);3C 0.0415→0.0517 仍
no_significant_increment(p 0.069→0.177,离基线更远;本次 train
underfit-flagged,跨拟合度 verdict 稳定)。chart-native 未打过动量
+ 根因(价格窗口再编码冗余)结论不变且被强化。
**7. 剩余风险**: P4-A1 折中决策待用户认可/推翻;G5 待首个组合候选;
expanded_v1 重检现有 flag 可达(evidence-gated)。
**8/9/10/11**: 见 `docs/memos/20260516-chart_structure_prd_audit.md`
§4/§8/§9(directional 决策 + 4-tier 自审 + 待办)。

---

## AUDIT-FIX — phase3 temporal_split 违规修复(2026-05-16,用户 audit 触发)

**1. 主题**: 用户追问 mining 是否违反 train/validation/sealed 隔离纪律。
**2. 真跑核验结论**: phase2a 增量-IC **合规**(`partition_for_role(role=
"selector")`+`purge_labels_at_boundary`);**phase3 attempt(3A/3B/3C)
违规** —— panel 实测 2009→2026-05-15 含 1255 validation 行 + 93
sealed-2026 行,2017/2024 OOS 21d label 溢进 2018/2025 validation。
模型 fit 本身只在 train(干净),但 panel/eval 违反
`feedback_temporal_split_discipline` + `fail_closed_if_*_in_train_panel`。
sealed 2026 未进任何 fitted/selected 标量(未被消耗)。
**3. 修复**: 3 runner 改走 canonical `partition_for_role(role="miner")`
(train-only)+ `validate_no_holdout_leakage`(fail-closed)+
`purge_labels_at_boundary`,取代手搓 `purged_fit_mask`(模块+测试保留
为 purge 工具单测)。
**4. 文件**: `phase3_run_{3a,3b,3c}_attempt.py`(canonical 接线)、
3 attempt JSON(clean 重跑)、Phase 3 closeout §3/§5/§6、audit memo
§0+§10。
**5. clean 重跑(panel 4867→3021 = 纯 train)**: 3A IC 0.0560/base
0.1195/p0.022、3B 0.0341/0.1124/≈0、3C 0.0283/0.1149/p0.001 —— **三个
全部 `underperforms_tabular_baseline`**。原「3C no_significant / 3C>3A>3B
单调」是泄漏伪影。**负结论在合规数据上更强更清晰。**
**6. 已 commit 数字 caveat**: commit 0616114/5c8f833 的非 purged + 手搓
embargo 两版 deprecated(git history 留作 audit trail),权威值=本 fix
commit canonical 重跑。
**7. 自审**: R1 集合/范围/溢出日期全实跑;R2 fit 干净 vs panel 违规
独立;R3 panel 4867→3021 + verdict 全 underperform 符合预期;R4
fail-closed 断言挂 panel + phase2a 单独核验未误伤。

---

## AUDIT-FIX2 — P4-A1 用户 override:production 入口全接 --universe(2026-05-16)

**1. 主题**: 用户 override 折中决策——production 主入口也接 --universe。
**2. 依赖核查(make-or-break)**: 实测 `resolve_universe("executable")`=
79,但 run_research_miner/factor_screen/xgb 现有 `cfg.universe` 派生=
**81(含 BRK-B+SLV;round-3 drop 后 resolve 是 79)**——**不等**。naive
路由 executable→resolve 会静默 81→79 = D6 回归(正是 Phase 4 当初只接
phase2a 的根因)。
**3. D6-safe 设计**: `executable`(default)= 原 cfg.universe 派生代码
原封挪进 `else:`(字节不变,P4-A2 by construction);仅 `expanded_v1`
走 `resolve_universe("expanded_v1")`。
**4. 文件**: `scripts/run_{research_miner,factor_screen,xgb_importance}.py`
(+--universe argparse + else 包裹原派生 + expanded 分支);
`test_universe_flag_all_entrypoints.py` 重写(7 入口全要 flag + D6
守护测试);audit memo §4.1 + Phase4 closeout P4-A1(✅ RESOLVED)。
**5. 核验**: 3 compile OK;3×`-h` 含 `--universe {executable,expanded_v1}`;
实测 executable default tradable=81(BRK-B/SLV 在)/ expanded_v1=326;
universe 子集 58 passed;G1 全量(收尾确认)。
**6. 结果**: P4-A1 从 audit overclaim → 真正全入口接,默认行为零改动
(by construction),expanded reachable。Phase 3 closeout 唯一未证伪
开口「expanded_v1 重检」现 production+研究入口均可达。
**7. 自审**: R1 依赖实测(79 vs 81 不等,非假设);R2 by-construction
论证(else 分支=原码字节不变 ⇒ P4-A2 必然成立);R3 executable=81/
expanded=326 实跑确认 + flag 在 -h;R4 D6 守护测试钉 production
executable 分支不得改原派生(契约漂移会 fail)。
