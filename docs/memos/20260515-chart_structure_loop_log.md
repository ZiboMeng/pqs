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
