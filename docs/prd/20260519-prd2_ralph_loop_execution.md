# PRD-2 ralph-loop 执行拆解(round 列 + machine-checkable AC)

**日期**: 2026-05-19 · **lineage**: `prd2-construction-dof-exec-2026-05-19`
**源**: `docs/prd/20260518-prd2_construction_dof_tiered.md`(主 PRD)+ `docs/memos/20260518-prd123_cross_audit_and_execution_order.md`(§D 顺序)。
**前置**: PRD-1 全 ✅(leakage-correct 地基 + C-lite 双确认)。
**round 两类**(chart_structure 17-round 先例):**build** = 确定性 AC(测试 GREEN / 文件存在且属性 X / bit-identical);**experiment** = AC 是"跑了+记录了+若负有 ROOT CAUSE",**不是"成功"**;负结果**不终止 loop**,config-scoped abort。
**纪律**: 风险不变量硬绑不随 flag 放松;真 short execution 永不在本拆解内实现(R14 stub);15m boundary 仅产 memo 标待 ratify(R9 = directional 停等点)。

---

## Phase P2.1 — T0/T1 flag + cadence(最便宜,直接攻 TC)

| R | 类型 | 目标 | machine-checkable AC |
|---|---|---|---|
| **R1** | build | T0 复现守卫:harness `construction_tier=T0`(default)= 现 cap_aware 路径 | 新增 `test_construction_tier_t0_bit_identical`:T0 输出 vs 记录 cycle-style baseline **bit-identical**;GREEN |
| **R2** | build | T1 1× 反向对冲 execution wiring(SH/PSQ/DOG ← `universe_priority5.yaml`)接 `long_short_config`,flag `construction_tier=T1` | TDD:T1 权重构建单测 + 风险不变量 guard 单测(`allow_margin:false`/DD cap 仍强绑)GREEN;**T0 default 仍 bit-identical**(回归) |
| **R3** | build | 1× 反向 ETF 每日重置路径依赖 decay 成本模型(非 −1×index;含 compounding decay + expense) | TDD 手算 decay 例(月跌 5% ≠ +5%)GREEN;输出**同时报"无 decay 乐观版 vs 有 decay 版"**(禁只报乐观)的单测 |
| **R4** | build | cadence 日/周 wiring(K1 `signal_driven_runner.rebalance_mask` 接 harness) | cadence 单测(monthly/weekly/daily mask)GREEN;**monthly default 不变**回归 GREEN |
| **R5** | experiment | T1 vs T0 同 spec 在 PRD-1 leakage-correct Track-A + 成本模型 ON 下跑 | 跑了+记录:§7 P2.1 量化门 —— (a) 2022-bear/covid maxdd 绝对降 ≥3pp?(b) full-period vs_spy 净成本后 ≥ T0−1pp?(c) decay 乐观-vs-建模差异显式报?cadence 2x/3x 成本仍 >SPY?**verdict pass/fail;fail 则 ROOT CAUSE**(负不终止) |

## Phase P2.2 — cross-asset done right + 非 intraday horizon

| R | 类型 | 目标 | AC |
|---|---|---|---|
| **R6** | build | cross-asset universe(`universe_priority5` 网格)接 `cap_aware_cross_asset` | wiring 单测 GREEN + **SQQQ-blacklist 回归 guard 单测**(不得引入 leveraged-inverse)GREEN |
| **R7** | build | 非-intraday horizon DOF(如 5d/63d 持有变体)wiring | horizon 参数单测 GREEN;默认 21d 不变回归 GREEN |
| **R8** | experiment | P2.2 acceptance | 跑了+记录:non-equity 利用率 + DD 改善量化报告;无 leveraged-inverse 引入;**verdict;fail root-cause** |

## Phase P2.3 — multi-TF intraday 构建/执行 DOF(gated:P2.1+P2.2 在 leakage-correct+Path-1 跑通 + intraday cost/leakage 模型硬化后)

| R | 类型 | 目标 | AC |
|---|---|---|---|
| **R9** | build / **🛑 directional** | 15m research-boundary 修订:产 `docs/memos/2026MMDD-15m_decision_input_boundary_revision.md` **标"待 ratify"** + CLAUDE.md 注记**草稿(不落)** | memo 存在且含"待用户 ratify"标记;CLAUDE.md **未改**(held);**loop 在此停等用户 ratify**(协议 directional 停等清单),不自决 |
| **R10** | build | Multi-TF leakage rules 单测(bar-completion / 无未来高 TF / ≥1-bar 执行延迟)on `multi_tf_cascade`/`decide_timing` | leakage 单测全 GREEN |
| **R11** | build | intraday 成本模型硬化(日内 slippage/turnover;3x 敏感) | intraday 成本模型单测 GREEN(含 3x 档) |
| **R12** | build | multi-TF cascade 构建 wiring(60m/30m + 日/月 cascade 作 timing/sizing/veto,**非 intraday alpha mining**) | cascade wiring 单测 GREEN;**60m-only baseline 可复现**回归 GREEN |
| **R13** | experiment | P2.3 acceptance | 跑了+记录:**A/B 去混淆数值**(信息 vs timing 贡献分离,三点曲线法)+ intraday 3x 成本仍正 + **不劣于 60m-only**(否则按 naive-voting 先例淘汰,记 root-cause);**verdict** |

## Phase P2.4 — 真 short execution(**不实现**)

| R | 类型 | 目标 | AC |
|---|---|---|---|
| **R14** | stub / **🛑 directional** | T2 仅 schema+gate+成本模型 DESIGN(`long_short_config.py` schema 已在);execution wiring = **永久 TODO** | guard 单测:T2 execution 路径在无 `--explicit-go-true-short` 时**拒绝/raise**(gated-off 证据);**无 execution wiring**;触发条件文档化(T1+cadence 正证据 + 用户 explicit-go + borrow/margin/squeeze/SSR 模型 + 风险不变量回归)。**loop 永不自动 fire P2.4 execution** |

## 终止 / DONE 条件

P2.1+P2.2+P2.3 的 experiment round(R5/R8/R13)**跑了+记录+verdict(pass 或诚实 fail+root-cause)** + R1-R4/R6-R7/R10-R12 build round AC GREEN + R14 stub guard 就位 + R9 memo 产出(ratify 与否不阻塞 PRD-2 标"执行完成",但 P2.3 实跑 gated 于 ratify)→ **PRD-2 执行拆解完成**。P2.4 execution 永不自动 fire。

## Directional 停等点(loop 不自决,写选项+建议停等用户)

- **R9**:15m boundary ratify(评估边界/不变量-adjacent)。
- **R14 / P2.4**:真 short execution(破不变量,永需 explicit-go)。
- 任何 experiment round 若结论触及"主线去留/评估准则定义/repo 结构"→ 停等。

## R1-R4 自审(本拆解 doc)

- R1:round 映射 P2.1-P2.4 与主 PRD §3/§7 逐条对应;AC 取自主 PRD §7 量化门。
- R2:build/experiment 两类语义与 chart_structure 先例一致;directional round(R9/R14)显式标停等,与协议停等清单一致;gating(P2.3 gated 于 P2.1/P2.2)与 §4 跨 PRD 依赖一致。
- R3:本轮为 doc 拆解,无代码;实现 round 各自带"真跑+对比期望"AC(R3 在每 experiment round 强制)。
- R4:风险不变量硬绑、真 short 永不自动 fire、15m 仅 memo 待 ratify、负结果不终止 loop(config-scoped abort)—— 边界全显式。

关联 [[project-backtest-robustness-ml-redo-2026-05]];SoT ledger = `docs/memos/20260518-prd123_execution_ledger.md`。
