# PRD-1/2/3 执行账本（loop 跨轮持久 SoT — 每轮必读必更）

**用途**: `/loop` 不间断推进的状态锚。loop 每轮开头读此 + 3 PRD + 互审 memo，定位下一最小步；每轮结尾更新此账本并 commit/push。
**锁定执行顺序**（`docs/memos/20260518-prd123_cross_audit_and_execution_order.md` §D）:
`PRD-1 → (PRD-2 ∥ PRD-3-组件A) → PRD-3-组件B(gated 于 PRD-2 P2.3)`

## 进度表（✅ done / 🟡 in-progress / ⬜ todo）

### PRD-1 leakage-correct 地基（必先，全做完才解锁 PRD-2/3）
- ✅ P1.1 canonical helper `core/research/label_leakage.py` + 10/10 TDD（commit 5381d83）
- 🟡 P1.2 接入 `temporal_split_acceptance` + 重构 chart_native L3 用 canonical（替原型）+ bit-identical 后台回归
  - ✅ P1.2a chart_native L3 原型 → canonical adapter（keys 签名保留,call site 不动,bit-identical by construction）。后台回归 `bi7e15u7s` 跑中(~32min,结果下轮判)
  - ⬜ P1.2b 接 `temporal_split_acceptance`（§3 调和:仅样本/probe-fit 层,不动 cpcv fold size 加权）+ tests
  - ⬜ P1.2c acceptance.yaml `leakage_correct` 开关 + legacy 逃生口契约化
- ⬜ P1.3 cycle06/08 + pead/options 独立轨 leakage-correct 重评（后台串行；逐候选"修正前/后+哪门翻+root cause"对照表，全 retire 可接受但 evidence-gated 非一刀切）
- ⬜ P1.4 重评结论 fold 进 manifest/CLAUDE.md，被推翻者按 evidence retire 留 forensic

### PRD-2 construction-DOF（PRD-1 完成后；P2.4 不实现）
- ⬜ P2.0 先写 PRD-2 ralph-loop 执行拆解子 PRD（round 列 + machine-checkable AC，仿 chart_structure 17-round）
- ⬜ P2.1 T0/T1(1× 反向对冲 execution wiring on long_short_config)+ cadence 日/周
- ⬜ P2.2 cross-asset done right + 非 intraday horizon
- ⬜ P2.3 multi-TF intraday 构建/执行 DOF + 15m boundary 修订 memo（草拟，标"待用户 ratify",不静默当已批）
- ⬜ P2.4 真 short execution = **不实现**（permanent TODO，触发须用户 explicit-go）

### PRD-3 信号 ML arms（组件 A 与 PRD-2 并行；组件 B gated 于 P2.3）
- ⬜ P3.0 先写 PRD-3 ralph-loop 执行拆解子 PRD
- ⬜ 组件 A1 工程特征+XGBoost+stack frozen-probe → A2 1D/ROCKET vs 图像 ablation → A3 JKX-bar → A4 iTransformer 域内 SSL
- ⬜ 组件 B1 intraday 工程特征+XGBoost → B2 intraday 深度（gate 最硬，gated 于 P2.3 + A 跑通 + A/B 去混淆）

## 本轮要更新此节（loop 每轮追加，最新在上）
- 2026-05-18 R0：账本建立；P1.1 已 ✅。下一步 = P1.2。
- 2026-05-18 R1：P1.2a chart_native L3 原型→canonical adapter 重构（call site byte-unchanged）;py_compile OK;label_leakage 10/10 复跑 GREEN;bit-identical 后台回归 `bi7e15u7s` 跑中(~32min)。下一步 = 待 `bi7e15u7s` 出 PASS → P1.2b 接 temporal_split_acceptance（若 FAIL → root-cause adapter 数值偏差,不 hand-wave）。
