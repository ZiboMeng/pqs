# PRD-2 — 分层 Construction-DOF 框架（攻 binding constraint 的脊梁）

**日期**: 2026-05-18 · **lineage**: `construction-dof-2026-05-18`
**性质**: 攻已证 binding constraint（long-only 月度 cap_aware top-N）的主杠杆。含 invariant-adjacent 修订（1× 反向对冲 = TQQQ 先例；真 short = schema+gate，execution 单独 explicit-go；15m 决策输入 = research-boundary 修订）。
**纪律**: `feedback_no_over_conservative_scoping`（全 roadmap 进 scope，cheap-first 是 sequencing）、`feedback_no_blanket_failure_verdict`、`feedback_promotion_only_falsification_evidence_gated`、`feedback_temporal_split_discipline`。
**源证据**: Clarke-de Silva-Thorley 2002 FAJ 58(5)（long-only TC≈0.3-0.5;TC=0.3→仅 9% 业绩来自信号）；Lo-Patel 2008（130/30 拿全无约束 ~90% 增益，borrow~0.75%/yr，运营风险"可能反吃收益"）；cycle04-10 sibling-by-NAV + L3 de-confound（construction binding）。

---

## §1 核心论点

四方一致：binding constraint = 构建层，非信号/universe。relax long-only 是全项目最高杠杆（TC 天花板的直接攻击）。但 relax 不是免费：借券成本/拥挤/反向 ETF decay 会侵蚀 premium → **当 funnel 假设，不当既定解**。

## §2 三治理分层（Q1 用户接受）

| Tier | 不变量性质 | 成本/风险模型 | 治理 |
|---|---|---|---|
| **T0 long-only**（default） | 不变 | 0；复现 cycle04-10 bit-identical | 无需 |
| **T1 1× 反向 ETF 对冲**（SH/PSQ/DOG，`universe_priority5.yaml` 已有） | **不破 no-short/no-margin**（买 long 工具，损失有界） | **1× 每日重置路径依赖 decay 必须建模**（月跌 5% ≠ +5%）；只对冲 beta | **TQQQ/SOXL 先例**："允许+更严阈值"，**不需不变量修订**；SQQQ 永久 blacklist |
| **T2 真 short** | **真破不变量** | borrow~0.75%/yr+难借尾部 / 保证金 / 逼空无限损失 / locate-SSR；`long_short_config.py` schema 已在（per-sym 0.05<long 0.10 不对称） | **本 PRD 只写 schema+gate+成本模型设计；execution wiring 不授权（Q2 用户决）→ §6 TODO，单独 decision memo + explicit-go 才启用** |

**风险不变量不随 flag 放松**（硬绑，所有 tier）：`allow_margin:false`（T0/T1）、DD 15-20%、2008-≤25%、crisis cap 0.25、halt 0.25、max_dd_vs_bench 1.5×。flag 改构建 DOF，**不改风险天花板**。

## §3 Phased Ladder（全 scope，分步执行，cheapest-safest-first）

- **P2.1**：T0/T1 flag（建 `long_short_config` execution wiring 的 T1 部分 + cadence 日/周，K1 `signal_driven_runner` 已有 mask）。最便宜、直接攻 TC。
- **P2.2**：cross-asset done right（`universe_priority5` 网格）+ 非 intraday horizon 变化。
- **P2.3 多 TF intraday 构建/执行 DOF**：60m/30m + 日线（甚至月线）cascade（`multi_tf_cascade.py`/`decide_timing` 已有脚手架）、日内 cadence、日内进出场时机。**15m 当决策输入 = research-boundary 修订**（原"15m research only / 60m-30m primary"不变量）→ 本 PRD §5 显式文档化（QQQ-deprecation 先例:decision memo + CLAUDE.md 注记）。**框架边界钉死**：intraday 在此是 **timing/执行/构建 DOF**，非 intraday-alpha-mining（CLAUDE.md Multi-TF Timing Contract:naive bar-方向投票严格输 60m-only — 但该负结论 scope 在 naive voting，非 blanket "intraday 无信号"；intraday 信号在 PRD-3）。**gated**:P2.1/P2.2 在 leakage-correct(PRD-1)+Path-1 跑通 + intraday cost/leakage 模型硬化后启用。
- **P2.4 真 short execution wiring** = §6 TODO（Q2，单独 explicit-go）。

## §4 跨 PRD 依赖

- 全 ladder 评估走 PRD-1 leakage-correct + Path-1 forward（不重开 2026 sealed）。
- PRD-3 的 intraday 信号组件 **gated 于 P2.3**（无日内构建能力，日内信号无法诚实评）+ 强制 **A/B 去混淆**（信息贡献 vs timing 贡献分离，沿用 chart_native 三点曲线方法论）。
- 新 mining（Q5）走本 PRD construction-DOF 主轴，**非重跑老 factor-composite TPE**（那是弃用老路子）。

## §5 Research-Boundary 修订文档化（必做，不静默）

15m 由"research only"→"可作决策输入"：本 PRD ship 时附 `docs/memos/YYYY-MM-DD-15m_decision_input_boundary_revision.md` + CLAUDE.md Invariant/Multi-TF 段注记（QQQ-deprecation 先例）。`SQQQ blacklist` / `no-margin`(T0/T1) / 60m-30m 主验证层 不变。

## §6 Out / Deferred / TODO

- **TODO-Q2（真 short execution）**：触发 = T1+cadence 在 leakage-correct+forward 跑出正证据 + 用户 explicit-go + borrow/margin/squeeze/SSR 模型 + 风险不变量回归。**未授权前 T2 仅 schema+gate**。
- 不动 risk.yaml 风险天花板；不动 sealed/partition。

## §7 验收（per phase）

每 phase：leakage-correct Track-A + 成本敏感性（2x/3x，intraday 更严）+ 风险不变量全过 + Path-1 forward init（非 IC 层宣布胜利）；P2.3 额外:Multi-TF Leakage Rules（bar-completion/无未来高 TF/执行延迟）+ A/B 去混淆。

## §8 R1-R4 自审

- R1：preflight 实证 `long_short_config.py`/`universe_priority5.yaml`/K1 cadence/risk.yaml 硬约束存在。
- R2：T1（买 long 工具）不破 no-short 与 T2（真破）治理分层逻辑自洽；intraday 双层（此 PRD 构建 / PRD-3 信号）耦合+去混淆逻辑成立。
- R3：经济学数字（TC=0.3→9%、130/30~90%、borrow 0.75%）来自 round-2 primary（Clarke-de Silva-Thorley / Lo-Patel）。
- R4：风险不变量硬绑非随 flag 放松、真 short execution gated、15m boundary 显式修订、naive-intraday-mining 老路子用 scoped 纪律挡（非 blanket）。
