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
