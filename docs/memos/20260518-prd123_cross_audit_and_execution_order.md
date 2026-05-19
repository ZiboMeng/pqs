# PRD-1/2/3 互审 + 执行顺序（user step-1 交付）

**日期**: 2026-05-18 · **纪律**: `feedback_audit_surfaces_not_thorough`（暴露没做透 + 纠自己 PRD 的 gap，不 hand-wave）、`feedback_self_audit_methodology`、`feedback_dependency_rigor_before_kickoff`。
**审计对象**: `prd/20260518-prd1_leakage_correct_foundation.md` / `prd2_construction_dof_tiered.md` / `prd3_signal_layer_ml_arms.md`。

---

## A. 细节可实现性

- **PRD-1 P1.1/P1.2 可实现**：`_avg_uniqueness_weights`/`_purge_embargo_mask` 已在 `dev/scripts/chart_native_l3/run_chart_native_l3_track_a.py:103/131` 原型验证（run4 实跑过）→ 抽进 `core/research/` 为 canonical + TDD。可行。
- **PRD-1 P1.3 重评 = 后台长跑**（cycle06/08 Track-A 重评 ≈ L3 量级 ~30-50min/run，串行）。可行但非单次秒级；按 background 串行。
- **PRD-2 P2.1/P2.2 可实现**（`long_short_config.py` schema 在、`universe_priority5.yaml` 1× 反向在、K1 cadence 在）；**P2.3 multi-TF intraday 构建 = 数周量级**（最大单块），correctly gated。**P2.4 真 short execution = 不实现（TODO）**。
- **PRD-3 A1/A2 可实现**（XGBoost 3.2.0 + Family T/drawup 在；ROCKET 未装 → sklearn 随机卷积代，PRD 已注）；**A4 iTransformer SSL / B2 intraday 深度 = GPU 4GB 重活，串行后置**。

## B. 验收指标明确性

- **PRD-1 §4 明确**（helper 单测 / legacy bit-identical / 重评对照表 / sealed 未读）—— measurable，OK。
- **PRD-2 §7 不够明确（自审 gap，须修）**：原文"leakage-correct Track-A + 成本敏感 + 风险不变量 + Path-1"过于 generic，**缺 per-phase 可量化 AC**。修正：见下 §D 已 fold 进 PRD-2 §7（P2.1 给定量 hedge-DD-reduction + cost-on 仍正 等）。
- **PRD-3 §4 基本明确**（frozen-OOS IC pooled+on-tradeable / 对 momentum-reversal-Amihud 残差正交 / DLinear 基线 / PRD-2 构建 NAV / Path-1）—— research-arm 级足够。

## C. 跨 PRD 耦合（关键 finding）

1. **§3 契约调和（最重要,防实现错）**：`cpcv_acceptance` §3 明文"唯一允许 sample-SIZE fold 加权,禁 recency/regime（额外 researcher DOF 加重过拟合)"。PRD-1 的 average-uniqueness **不违反 §3**——它是**probe-fit loss 的 per-sample 训练权重 + label 构造偏差修正**,**不是 fold 聚合权重**;§3 禁的是 fold 聚合层的**自由裁量** recency/regime 加权。uniqueness 是**原则性偏差修正(减虚高)**,与 §3 担心的"裁量 DOF(增过拟合)"**范畴不同,§3 rationale 不适用**。→ 已 fold 进 PRD-1 §2（实现者：uniqueness 只入 probe-fit/样本层,**不得**改 cpcv fold 聚合的 size 加权;两层正交)。
2. **依赖链清晰**：PRD-1 是 PRD-2/PRD-3 评估可信的前置;PRD-3 组件 B gated 于 PRD-2 P2.3;PRD-3 组件 A 只依赖 PRD-1（**不依赖 PRD-2** → 可与 PRD-2 并行,见 §D）。
3. **配合 OK**：sealed-consumed/Path-1/新 mining 走 PRD-2 主轴 等后果三 PRD 一致,无矛盾。

## D. 执行顺序（user step-2，锁定）

```
PRD-1（地基,必先）
  └─ 完成后并行：
       ├─ PRD-2 P2.1→P2.2→P2.3（construction 脊梁；P2.4 永久 TODO）
       └─ PRD-3 组件 A（A1→A2→A3→A4；只需 PRD-1）
            └─ PRD-3 组件 B（intraday-ML）gated 于 PRD-2 P2.3 完成 + A 跑通方法论
```
理由：PRD-1 不修则 PRD-2/3 所有 Track-A 实验又虚高（run4 陷阱重演）;PRD-3-A 与 PRD-2 互不依赖可并行;B 自欺风险最高排最后。**cheap-first 是 sequencing 非砍 scope（全 roadmap 仍在 scope）。**

## E. 已据审计修正的 PRD（留痕）

- PRD-1 §2：加 §3 调和句（uniqueness=probe-fit/样本层,不动 cpcv fold size 加权,两层正交）。
- PRD-2 §7：per-phase 可量化 AC（替换 generic 表述）。
- 本 memo = 执行顺序 SoT。

关联 [[project-backtest-robustness-ml-redo-2026-05]] [[feedback_audit_surfaces_not_thorough]];源 3 PRD + `docs/memos/20260518-l3_deconfound_correctness_verdict.md`。
