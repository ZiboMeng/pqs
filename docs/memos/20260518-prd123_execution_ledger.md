# PRD-1/2/3 执行账本（loop 跨轮持久 SoT — 每轮必读必更）

**用途**: `/loop` 不间断推进的状态锚。loop 每轮开头读此 + 3 PRD + 互审 memo，定位下一最小步；每轮结尾更新此账本并 commit/push。
**锁定执行顺序**（`docs/memos/20260518-prd123_cross_audit_and_execution_order.md` §D）:
`PRD-1 → (PRD-2 ∥ PRD-3-组件A) → PRD-3-组件B(gated 于 PRD-2 P2.3)`

## 进度表（✅ done / 🟡 in-progress / ⬜ todo）

### PRD-1 leakage-correct 地基（必先，全做完才解锁 PRD-2/3）
> **✅ R5 P1.3 RESOLVED — 用户 ratify A + C-lite(2026-05-19)**：grounded scope 接受(仅 chart_native_s1 受 run4 leakage,已 caveat;cycle06/08+pead+options 不受、不重评、不 retire,主线不归零)。C-lite 后台 empirical 背书跑中。loop 恢复推进。
- ✅ P1.1 canonical helper `core/research/label_leakage.py` + 10/10 TDD（commit 5381d83）
- ✅ P1.2 canonical 落地 + 契约化 + bit-identical
  - ✅ P1.2a chart_native L3 原型 → canonical adapter。后台回归 `bi7e15u7s` = **PASS NONE differ**（oos_ic 0.01057/0.01098 verdict FAIL,与 B-verify 一致;数值=原型,SoT 统一无回归）
  - ✅ P1.2b acceptance.yaml `leakage_correct` 契约 surface + `LeakageCorrectPolicy` schema(enabled/suniq/purge/embargo/legacy + effective())+ loader + TDD 9/9 + 121 回归 0 fail
  - **诚实 re-scope（纠我自己 PRD 措辞,`feedback_audit_surfaces_not_thorough`）**:原 P1.2 "接 temporal_split_acceptance" 措辞不准——probe-fit/score-gen 在 caller(chart_native L3 已 canonical;cycle06/08 eval 脚本是 P1.3 payload),§3 明禁把 uniqueness 塞进 cpcv fold 聚合。正解 = canonical helper 作 probe-fit 层 SoT + acceptance.yaml 作契约开关(已交付),**不**在 temporal_split_acceptance 里改 fold 聚合(§3-preserving by design)。P1.2c 折进 P1.2b（契约 surface 即开关）。
- ✅ P1.3 **A + C-lite RATIFIED**（用户 2026-05-19）：grounded scope 确认 —— run4 probe-fit leakage = learned-probe-specific,仅 chart_native_s1 受影响（已 Option A caveat done）;cycle06/08(factor-composite)+ pead(确定性 SUE,R4 grounded)+ options/simple_baseline **不受影响、不重评、不 retire,主线不归零**。C-lite empirical 背书后台跑中（确认 P1.1/P1.2b leakage 机器未扰动 cycle06/08 确定性 verdict;预期 bit-不变,变则 §1 错必 root-cause）。B(未来 factor-composite cpcv uniqueness §3 修订)未触发,仅当用户日后要管未来 cycle 时另起 mini-PRD。
- ✅ P1.4 结论 fold:ledger + scope-correction + clite-finding memo;**CLAUDE.md-fold 已由 2026-05-19 reorg 新「Active State」节满足**(chart_native_s1 leakage caveat + cycle06/08 不受影响 + PRD-1 P1.3✅ 入口可见);被推翻者=仅 chart_native_s1(Option A 保留+caveat 非 retire);cycle06/08/pead/options 不受影响无 retire。**PRD-1 全 ✅。**

### PRD-2 construction-DOF（PRD-1 完成后；P2.4 不实现）
- ✅ P2.0 PRD-2 ralph-loop 执行拆解子 PRD = `docs/prd/20260519-prd2_ralph_loop_execution.md`（R1-R14;P2.1 R1-R5 / P2.2 R6-R8 / P2.3 R9-R13 / P2.4 R14-stub;R9 15m-boundary + R14 真short = directional 停等点）
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
- 2026-05-19 R7：PRD-1 全 ✅ → 进 PRD-2 入口。写 PRD-2 ralph-loop 执行拆解 `docs/prd/20260519-prd2_ralph_loop_execution.md`(14 round:build=确定性 AC / experiment=跑了+记录+负 root-cause;R9 15m-boundary、R14 真short = directional 停等)。下一步=R8 写 PRD-3-A ralph-loop 拆解(锁定顺序 PRD-2 ∥ PRD-3-A,两子 PRD 先写齐再逐 round);之后 P2.1 R1(T0 bit-identical 守卫,TDD)。
- 2026-05-19 R6-final：用户 CLAUDE.md reorg 已批准+立即执行(交错于本轮)：CLAUDE.md 2155→498 行(−77%),8 模块 CONTEXT.md content-preserving(线数守恒 470+1686=2156 零丢失),R3 验 13/13 不变量/纪律锚点全在。**P1.4 CLAUDE.md-fold 现已由 reorg 新「Active State」节满足 → PRD-1 全 ✅**。下一步=PRD-2 ∥ PRD-3-A 入口(各先写 ralph-loop 执行拆解子 PRD,再逐 round)。loop 续(无 directional;PRD-2 P2.4 真 short / 15m ratify 仍是后续停等点)。
- 2026-05-19 R6：C-lite `bdwoxptnv` = **cycle06/08 VERDICT BIT-IDENTICAL — NONE differ** vs postP0maxdd → grounded §1 经验证实,**A grounded+empirical 双确认,PRD-1 P1.3 正式闭**。smoke 报 81/90 weekend 行 → R3 blast-radius:curated/active/cycle06-08/forward 全干净;仅 ~1000 bulk expanded_v2 污染+stale(SPY off-by-one fix 未覆盖 bulk;chart_native 1k 实验那批数据有此 confound,已 caveat/已闭/off-critical-path)。finding memo `docs/memos/20260519-clite_pass_plus_weekend_row_finding.md`。**P1.4 CLAUDE.md-fold 暂缓**(用户 reorg 进行中,避免冲突;已 fold ledger+memo)。PRD-1:P1.1✅P1.2✅P1.3✅,P1.4 仅 CLAUDE.md 尾巴 entangled reorg。下一步=PRD-2∥PRD-3-A 入口(各先写 ralph-loop 拆解子 PRD)。
- 2026-05-19 R5：用户 ratify **A + C-lite**。ratify A 落 doc（PRD-1 P1.3 + ledger:scope 接受,cycle06/08/pead/options 不重评不 retire,主线不归零;chart_native 已 caveat）。启 C-lite 后台 `bdwoxptnv`（bar-integrity smoke → cycle06/08 各 top-3 重评于当前 HEAD[含 P1.1/P1.2b leakage 机器] → diff vs postP0maxdd baseline:n_passed+per-trial verdict/failed/mfp）。预期 bit-不变（确定性 composite 无 probe-fit 作用面)；DIFF 则 §1 grounded 错必 ROOT CAUSE。下一步 = bg 完成判读:PASS → P1.3 闭 + P1.4 收尾 → PRD-1 DONE → 解锁 PRD-2 ∥ PRD-3-A;DIFF → root-cause。
- 2026-05-18 R4：bare /loop 重触发但 A/B/C 未答 → 按纪律不当默许。推进唯一非-directional tactical = pead grounded 实读(scope-memo §4 自列)。结果:pead = 确定性 SUE 阈值信号,无 probe/fit/重叠标签 IC 向量 → 与 cycle06/08 同类,probe-fit leakage 无作用面。**决策包补全:run4 leakage = learned-probe-specific,仅 chart_native_s1(已 caveat);cycle06/08+pead+options 全 grounded 无作用面**。A/B/C fully-informed 但仍未 ratify → 重新呈递并继续停等(无 ScheduleWakeup)。无更多非-directional 前置可推。
- 2026-05-18 R3：P1.3 grounded 分析 —— 实读 `cycle06_track_a_eval.py` 确认 factor-composite(ResearchCompositeSpec/evaluate_composite_spec,无 ridge probe、无 cpcv_inputs 重叠标签向量)→ run4 probe-fit leakage 机制对 cycle06/08 **无作用面**。诚实纠 PRD-1 P1.3 对 factor-composite 的 overclaim。**directional STOP-for-user**(评估准则 scope + 主线去留 + "之前结论真实性"):写 scope-correction memo §5 选项 A(建议:ratify,事实如此)/B(§3 契约修订须独立 mini-PRD)/C(实证背书后台重跑预期不变)。本轮按协议停等,**不 ScheduleWakeup**,loop 暂停待用户。下一步=用户 ratify 后据选择续 P1.3 / 起 PRD-2(若 A:主线未崩,PRD-1 P1.4 收尾后进 PRD-2∥PRD-3A)。
- 2026-05-18 R2：`bi7e15u7s` = **bit-identical PASS NONE differ**（P1.2a 确认数值=原型,SoT 统一）。P1.2b 交付 acceptance.yaml `leakage_correct` 契约 surface + LeakageCorrectPolicy schema + loader,TDD 9/9 + 121 回归 0 fail。诚实 re-scope 了原 PRD "接 temporal_split_acceptance" 措辞(§3 明禁 fold 聚合改;正解=probe-fit caller SoT + yaml 开关,已交付)。**P1.2 ✅ 完成**。下一步 = P1.3 cycle06/08(+pead/options 独立轨) leakage-correct 重评 payload（wire eval 脚本走 canonical + 后台串行重跑 + 逐候选对照表）。**注意 directional 停等点**:若重评 FAIL→主线归零,是否 fire 新 mining 须停等用户。
  - **R2 process bug + ROOT CAUSE + fix**(不 hand-wave):commit `e4ada31` message body 被吞 token。根因 = `git commit -m "..."` 双引号内反引号触发 bash command-substitution。代码/文件提交无误,仅 message 退化(cosmetic)。R4 判定:不 force-push 改已 push 历史(代价>收益)。**Convention fix(后续所有 loop round 强制)**:commit message 用单引号包裹或彻底不用反引号。
