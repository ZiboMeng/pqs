# Chart-structure 输入表征层 —— Phase 1 closeout

**日期**: 2026-05-15
**Lineage**: `chart-structure-input-repr-2026-05-15`
**主 PRD**: `docs/prd/20260515-chart_structure_input_representation_prd.md`
**execution PRD**: `docs/prd/20260515-chart_structure_ralph_loop_execution_prd.md`
**loop log**: `docs/memos/20260515-chart_structure_loop_log.md`(R1/R2/R3 11-part)
**termination promise**: `CHARTSTRUCT-P1-DONE`

---

## §1 Phase 1 做了什么

Phase 1 = swing 段结构 family T。3 个 round:

| Round | 交付 | commit |
|---|---|---|
| P1·R1 | 因果 swing 核心(`SwingPoint`/`SwingStructureConfig`/`detect_raw_swings`/`_collapse_alternating`/`confirmed_swings_asof`)| `adb0c98` |
| P1·R2 | 12 个 swing-structure 特征 + `compute_swing_structure_factors` + `config/swing_structure.yaml` | `893ad98` |
| P1·R3 | registry 接线(RESEARCH_FACTORS 175→187、FAMILIES_V2 19→20、`factor_generator` 接线)+ 增量 collapse 性能修复 + closeout | (本 commit)|

`core/factors/swing_structure.py` —— 一个新 factor family(family T,12 因子),
进 RESEARCH_FACTORS,可被 miner `family_first` 采样。

## §2 两个实现期发现(都已修正并记录)

### §2.1 因果 bug —— filter-then-collapse(R1)

PRD v2 §3.5 原 API `confirmed_swings_asof(bars, cfg, t_idx)` 会诱导
collapse-then-filter 实现 —— **非因果**:§B-B2 的 collapse「连续同 kind 取
更极端」会用一个未来 swing 决定丢弃哪个过去 swing。改为 **filter-then-collapse**:
raw 极值因果(只依赖 `[i-n,i+n]` 窗口),先按 `confirmation_idx ≤ t` 过滤
再 collapse。P1-A2 因果 hard test 验证逐位相等。PRD §3.4/§3.5 已更新。

### §2.2 metric 退化 —— §3.3 特征 1/2/7/8/9(R2,用户批准修正)

confirmed swing 序列严格交替 → 相邻段恒反向、恒共端点。原 draft 的
`impulse_score`(dir_j=dir_{j−1} 恒假→恒 0)、`corrective_score`(相邻段
重叠恒真→恒 1)、`trend_maturity`(consecutive_same_dir_legs ill-defined)
退化;`seg_count_up/down` 近常数。修正:改成隔 2 段/swing 的同向比较
(Elliott「递进 vs 重叠」本质);1/2 替换为 `swing_last_up_seg_len_pct` +
`swing_net_drift_k`。用户 2026-05-15 批准。PRD §3.3 已更新。

## §3 P1·R3 性能修复(本轮新增发现)

R3 把 `compute_swing_structure_factors` 接进 `generate_all_factors` 后,
全量 pytest 从 ~11 min 涨到 ~24 min —— per-symbol per-t 重算
`confirmed_swings_asof`(O(T·E))拖慢了所有调 `generate_all_factors` 的
测试。§B-B7 风险在测试规模就 materialize 了。

**修复**:collapse 是 left-fold → 增量 fold 与批量 collapse 等价。改成
per-symbol 单次 `detect_swing_extrema` + 随 `confirmation_idx` 增量 fold,
全程 O(T+E)。`generate_all_factors` 测试 24min→`0.90s`。增量路径与
reference 路径 bit-identical(`test_compute_factors_matches_reference` 守)。

## §4 Acceptance —— P1-A1..A6 全过

| AC | 判据 | 结果 |
|---|---|---|
| P1-A1 | 12 特征产出、值在定义域、非空 | ✅ `test_swing_structure_ranges` |
| P1-A2 | 因果 hard test 逐位 == | ✅ `test_swing_structure_causal` |
| P1-A3 | reachability `union==RESEARCH_FACTORS`,187/20 | ✅ |
| P1-A4 | family T 可被 `family_first` 采样 | ✅ `test_family_t_sampled`(seed 13,80 trials)|
| P1-A5 | 全量 pytest green | ✅ 3205 passed(见 loop log R3)|
| P1-A6 | 阈值来自 config 无 hardcode | ✅ `test_swing_structure_config_sourced` |

swing_structure 单测 8 个;另含 reachability + registry generation +
sampling。

## §5 剩余风险 / 交接

- `tol` / `maturity_cap` / `K` 是 PLACEHOLDER(PRD §C)—— 无证据基础,
  Phase 2A `K∈{6,8,12}` sweep + `tol`/`maturity_cap` 标定。
- 特征是否有 alpha 由 Phase 2A incremental-IC 裁判 —— Phase 1 不下结论。
- 增量优化已把 §B-B7 的 test-scale 风险解决;expanded universe(Phase 4)
  仍走同一 O(T+E) 路径,规模可控。

## §6 Phase 2 fire 条件

主 PRD §4.6 / execution PRD §4:Phase 2 fire = P1-A1..A6 全过 —— **已满足**。
Phase 2A(incremental-IC 配对检验)可 fire。

**`CHARTSTRUCT-P1-DONE`**.
