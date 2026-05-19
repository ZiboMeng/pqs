# PRD-3 ralph-loop 执行拆解(round 列 + machine-checkable AC)

**日期**: 2026-05-19 · **lineage**: `prd3-signal-ml-arms-exec-2026-05-19`
**源**: `docs/prd/20260518-prd3_signal_layer_ml_arms.md`(主 PRD)+ `docs/memos/20260518-chart_native_architecture_literature_synthesis.md`(5 收敛结论)。
**前置**: PRD-1 全 ✅(leakage-correct 地基);锁定顺序 = PRD-2 ∥ **PRD-3-组件A**(只依赖 PRD-1) → **PRD-3-组件B gated 于 PRD-2 P2.3**。
**round 两类**: **build**=确定性 AC(测试 GREEN / 文件属性 / bit-identical);**experiment**=AC 是"跑了+记录+若负 ROOT CAUSE",**非"成功"**;负结果不终止 loop(config-scoped abort)。
**铁律(贯穿所有 round)**: 全评估走 PRD-1 leakage-correct(`core/research/label_leakage`,default-on);**信号非 binding,单独非进步**——每个 experiment 的 verdict 必含"是否差异化非 sibling(JKX ≤12% 残差正交测)"+ "走 PRD-2 构建的 NAV Track-A,不在 IC 层宣布胜利";sealed 2026 永不读;DSR 真-N 禁 placeholder overclaim;每深度实验必带 DLinear/动量基线。

---

## 组件 A — 日线-close 信号 arm(与 PRD-2 并行,只依赖 PRD-1)

| R | 类型 | 目标 | machine-checkable AC |
|---|---|---|---|
| **RA1** | build | A1 工程化平稳特征模块:JKX 归一化几何(`close_pos_in_range` 多窗)+ 距滚动极值 S/R proxy + K线 body/wick/gap + 量 z + 分数差分价 + Family T swing-structure(registry 已在),全月度截面 rank | TDD:每特征手算样例单测(无 look-ahead / 平稳 / 截面 rank 正确)GREEN;sample-uniqueness+purge 经 `core/research/label_leakage` 接入 eval(回归 GREEN) |
| **RA2** | build | A1 浅 XGBoost(depth 2-4+早停)+ stack frozen-probe embedding(PCA 16-32 维额外列) | TDD:固定 seed → 训练管线可复现单测 GREEN;leakage-correct 样本权重已施(断言) |
| **RA3** | experiment | A1 acceptance | 跑+记:leakage-correct frozen-OOS IC(pooled + on-tradeable)+ 对 momentum/reversal/Amihud 残差正交(JKX ≤12% sibling 测)+ DLinear/动量基线对照;**verdict:差异化非 sibling? IC>基线?**;负 → ROOT CAUSE(不终止) |
| **RA4** | experiment | A2 决定性 ablation:1D/ROCKET + 显式 per-name 归一化 vs 图像 | 跑+记:IC-on-tradeable 单调曲线(三点曲线法)→ **"图像必不必要"verdict**(显式归一化 1D/树 是否追平图像);ROCKET 未装用 sklearn 随机卷积代;负 → root-cause |
| **RA5** | build | A3 JKX-style OHLC+vol bar 图 builder + frozen-vs-from-scratch JKX-CNN harness(复用 chart_native L3 canonical/leakage-correct 路径) | bar-image builder 单测 GREEN;**close-only 既有路径 bit-identical 回归 GREEN**(additive,default 不变) |
| **RA6** | experiment | A3 acceptance:JKX-bar vs close-GAF;frozen vs from-scratch | 跑+记+verdict(OHLC/量 是否加增量;frozen 是否仍 > from-scratch)+ root-cause |
| **RA7** | build | A4 iTransformer/PatchTST + 域内 masked-patch SSL → 冻结探针 脚手架(GPU 4GB 串行) | SSL 预训练+冻结探针管线单测 GREEN;**expanded-universe guard 单测**:若 A4 用 >curated universe → 断言 bulk expanded_v2 weekend-row 已修(R6 finding 硬前置)否则 refuse |
| **RA8** | experiment | A4 acceptance:域内 SSL vs ImageNet 域外迁移 | 跑+记+verdict(域内增量幅度,**禁 vision 量级 overclaim**)+ DSR 真-N + root-cause |

## 组件 B — intraday 信号 arm(**gated**:PRD-2 P2.3 完成 + 组件 A 方法论跑通 + intraday cost/leakage 模型硬化[PRD-2 R11] + 强制 A/B 去混淆 + 若 >curated 则 bulk weekend-row 已修)

| R | 类型 | 目标 | AC |
|---|---|---|---|
| **RB1** | build / **🛑 gated** | B-前置 guard:断言 PRD-2 P2.3 完成 + PRD-1 leakage-correct + intraday cost/leakage 模型硬化 + (若 >curated)bulk weekend-row 已修 | guard 单测:前置未满足时 B impl 路径 **refuse/raise**(gated-off 证据);**loop 在前置未满足前不启动 RB2+**;前置状态显式上报(上游 P2.3/15m-ratify 是 directional,不在 B 内自决) |
| **RB2** | build | B1 intraday 工程特征(日内反转/开盘区间/VWAP 偏离/已实现波动/量分布)+ 浅 XGBoost;archetype 限 differentiated 非 naive | TDD 特征单测 GREEN + **guard 单测拒绝 naive bar-方向投票 config**(老路子防呆) |
| **RB3** | experiment | B1 acceptance | 跑+记:leakage-correct + intraday 3x 成本 + **A/B 去混淆(信息 vs timing 分离)** + **不劣于 60m-only**(否则按 naive-voting 先例淘汰记 root-cause);verdict |
| **RB4** | build | B2 intraday 深度(TCN Bai2018 / iTransformer / PatchTST;15m/30m/60m 当 channel/variate + masked SSL→冻结探针) | 深度管线单测 GREEN;**DLinear 基线强制**接入(无之结果不可信) |
| **RB5** | experiment | B2 acceptance(intraday-ML = 全 program 自欺风险最高,verdict 最严) | 跑+记:深 vs 浅 vs DLinear + DSR 真-N + PBO + A/B 去混淆**强制** + 不劣 60m-only;verdict;负 → root-cause(非 blanket) |

## 终止 / DONE

组件 A RA1-RA8 + 组件 B RB1-RB5:build round AC GREEN + experiment round 跑了+记录+verdict(pass 或诚实 fail+root-cause)→ **PRD-3 执行拆解完成**。组件 B 在 RB1 前置 gate 满足前**不启动**。负 experiment 结果**不终止 loop**(config-scoped,禁 blanket "X 不行")。**全程不晋升/不入 fleet**(除非走完 PRD-1+PRD-2 funnel + 证伪 evidence-gated)。

## Gate / 停等点

- **RB1**:组件 B 前置 gate —— 其上游(PRD-2 P2.3 完成、15m boundary ratify)是 directional,B 不自决;RB1 仅 guard + 上报状态,前置不满足则 loop 跳过 B 继续 A / 其他可做项。
- **A4/B expanded-universe**:若用 >curated universe,bulk expanded_v2 weekend-row 修复(R6 finding)是硬前置 —— 该修复本身重活+off-critical-path,触发时作为 tactical 前置(非 loop 内自动重 fetch 1000 名,需显式安排)。
- PRD-3 本身不动不变量/评估准则(research signal,config-scoped,非可部署,走 funnel)→ 无新 directional;停等点全在上游 PRD-2(R9 15m / R14 真short)。

## R1-R4 自审(本拆解 doc)

- R1:RA1-RA8/RB1-RB5 与主 PRD §2 组件 A/B 逐条对应;AC 取自主 PRD §4 验收(IC pooled+on-tradeable / JKX ≤12% / DLinear 基线 / PRD-2 NAV / DSR 真-N)。
- R2:build/experiment 语义同 PRD-2 拆解;组件 B gated 于 P2.3(与主 PRD §3 + cross-audit §D 一致);RB1 guard 不自决上游 directional。
- R3:本轮 doc;每 experiment round 强制"真跑+对比期望(IC/基线/de-confound)";A2/RA4 = 三点曲线法(已在 chart_native 用过,R3 可复用验证)。
- R4:边界——信号非 binding 单独非进步(每 verdict 必接 PRD-2 NAV)、bulk-1k weekend 硬前置、intraday-ML 自欺风险最高排最后 gate 最硬、负不终止非 blanket、不晋升不入 fleet。

关联 `docs/prd/20260519-prd2_ralph_loop_execution.md`(并行)、`docs/memos/20260519-clite_pass_plus_weekend_row_finding.md`(bulk-1k 前置);SoT ledger = `docs/memos/20260518-prd123_execution_ledger.md`。
