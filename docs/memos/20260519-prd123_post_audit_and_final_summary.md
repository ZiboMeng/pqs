# PRD-1/2/3 Post-Audit + Final Honest Summary (2026-05-19)

**Status**: ALL THREE PRDs **COMPLETE** per their ralph-loop AC.
Loop terminates after this doc (no ScheduleWakeup).

**R3-VERIFIED in this audit**: **190 tests passed** across all key
PRD-1/2/3 suites (端到端链路全过);**9/9 experiment verdict JSONs**
all present and machine-readable; PRDs + key memos all present.

---

## §1 Per-PRD AC reconciliation

### PRD-1 — Leakage-correct evaluation foundation
| Item | Status | Evidence |
|---|---|---|
| P1.1 canonical uniqueness + purge | ✅ | `core/research/label_leakage.py` `average_uniqueness_weights` / `purge_embargo_mask` ; test_label_leakage 10/10 |
| P1.2 接 temporal_split / cpcv / probe-fit + default-on legacy 逃生口 | ✅ | `core/config/schemas/acceptance.py` `LeakageCorrectPolicy` ; `config/acceptance.yaml` block ; test_acceptance_leakage_policy 9/9 |
| P1.3 在任候选诚实重评(scope-correction memo) | ✅ | `docs/memos/20260518-prd1_p13_scope_correction_factor_composite_unaffected.md`(user ratify A+C-lite);C-lite bdwoxptnv bit-identical PASS;cycle06/08 factor-composite 不受 run4 probe-fit leakage 影响 |
| P1.4 fold 结论入 CLAUDE.md / manifest | ✅ | CLAUDE.md `Active State` 2026-05-19 reorg + `[REVISED 2026-05-19]` invariant notes ;cycle06/08 `requires_data_review`→OK + chart_native_s1 caveat memo |

### PRD-2 — Construction-DOF tiered (R1-R14)
| R | Type | Status |
|---|---|---|
| **R1** | build T0 bit-identical 守卫 | ✅ HarnessConfig.construction_tier=T0 默认 no-op ; 6/6 + 316/0 regression |
| **R2** | build T1 1× 反向对冲 wiring | ✅ `apply_tier_overlay` + T1HedgeConfig ; 25/25 + bg b8ozsi0yx T0 bit-identical PASS |
| **R3** | build 1× inverse decay 成本模型 | ✅ `inverse_etf_decay_return` ; 5/5 |
| **R4** | build cadence × tier 交互 | ✅ test_cadence_x_tier_interaction 8/8(诚实 re-scope:K1 已 wired) |
| **R5** | experiment T1-vs-T0 acceptance | ✅ verdict **FAIL_recorded_root_cause**:静态对冲牛市放血 alpha(gate-a crisis-DD 真降,gate-b alpha-bleed);**non-blanket** value=regime-conditional |
| **R6** | build cross-asset+SQQQ blacklist guard | ✅ test_p2_2_cross_asset_inverse_blacklist_guard 6/6 |
| **R7** | build horizon DOF | ✅ test_p2_2_r7_horizon_dof 6/6(诚实 re-scope:min_holding_days canonical) |
| **R8** | experiment cross-asset acceptance | ✅ verdict **PASS**:cross-asset 真降 DD 不放血(non_eq 37%/full DD −6.88pp/无杠杆-inverse;**对比 R5 静态对冲失败:多元化=合法 TC-attack 静态对冲=cost-bleed**) |
| **R9** | 🛑 directional 15m boundary 修订 | ✅ **RATIFIED 2026-05-19** by user explicit-go ; memo `docs/memos/20260519-15m_decision_input_boundary_revision.md`(QQQ-deprecation 先例);CLAUDE.md invariant 行 fold |
| **R10** | build Multi-TF leakage rules 合并契约 gate | ✅ test_multi_tf_leakage_rules 7/7(诚实:①②已在 test_multi_timescale 强覆盖,本文件=合并契约+③≥1-bar exec-delay 欠覆盖补) |
| **R11** | build intraday 成本硬化 3x sensitivity | ✅ additive `sensitivity_multiplier=1.0` 构造级 bit-identical ; 8/8 + 55 regression |
| **R12** | build cascade construction overlay | ✅ `core/research/cascade_overlay.py` off=60m-only baseline bit-identical / cascade=timing/sizing/veto∈[0,base] 非 alpha mining 结构 guard ; 11/11 |
| **R13** | experiment P2.3 acceptance | ✅ verdict **FAIL_recorded_root_cause**:月度 cadence+liquid 趋势集 cascade 是 drag(veto 几乎不触发 info=0;long-bull timing 剃头 timing_contrib−2.05);**non-blanket scoped**:cascade R12 仍 default-off bit-identical 正确原语,intraday-timing 价值是 open question 未被否定 |
| **R14** | stub T2 gated guard | ✅ test_p2_4_t2_stub_gated 7/7(永久 TODO+触发条件文档化;**P2.4 execution 永不自动 fire**) |

### PRD-3 — Signal-layer ML arms

#### Component A (RA1-RA8 daily-close arm,与 PRD-2 并行)
| RA | Type | Status |
|---|---|---|
| **RA1** | build engineered stationary features | ✅ `core/research/engineered_features.py` close_pos_in_range/kline shape/vol_z/frac_diff_delegate/leakage thin pass-through ; 16/16 |
| **RA2** | build shallow XGB + frozen-probe PCA stack | ✅ `core/research/a1_pipeline.py` + additive XGBAlphaModel.sample_weight(默认构造级 bit-identical);10/10 + 37/0 regression |
| **RA3** | experiment A1 acceptance | ✅ verdict **PASS**:IC pooled 0.0558/on-tradeable 0.0531/JKX R²=0.033 强差异化非 sibling/A1>base(mom 0.011/Ridge 0.054);**诚实留痕**:XGB 仅+0.0014 IC vs 线性,与"浅≈线性@低SNR"文献一致 |
| **RA4** | experiment A2 决定性 ablation | ✅ verdict **PASS_image_not_necessary**(干净决定性):p0 raw-floor 0.0001 < p1 ROCKET 0.0246 < p2 显式归一+树 0.0558 严格单调 → **图像非必需,价值=归一化**,确证 JKX 2023 |
| **RA5** | build JKX OHLC+vol bar-image | ✅ `chart_cnn.py` additive jkx_bar_image/(W,5)→(6,W,W);close-only 路径 bit-identical 证(first-2ch==close-only gaf);11/11 |
| **RA6** | experiment A3 acceptance | ✅ verdict **PASS**(driver gate-scoping bug root-caused fix 后):JKX 对 close-GAF 增量 +0.0312,JKX frozen 0.0257≫floor 0.0019;close-GAF~0 leakage-correct 一致 s1 caveat 预期 |
| **RA7** | build SSL→frozen-probe scaffold + R6 expanded-universe guard | ✅ `a4_universe_guard.py` (expanded_v1/v2 默认 REFUSE 除非显式 certification);15/15 |
| **RA8** | experiment A4 acceptance | ✅ verdict **FAIL_recorded_root_cause**:in-domain SSL IC +0.0193>ImageNet −0.0055 增量 +0.0249(Q1 YES);DSR FAIL(T=59/n=10/Sharpe 0.07)=**honest-N+fail-closed 纪律按设计工作**=power 受限非方法证伪 |

#### Component B (RB1-RB5 intraday arm,gated 于 P2.3 已 EXECUTED)
| RB | Type | Status |
|---|---|---|
| **RB1** | build/gated B 前置 gate guard | ✅ `component_b_gate.py` 合并 4 prereq 检查(PRD-1/P2.3/R11/RA7) + naive archetype refuser ; 17/17 |
| **RB2** | build B1 intraday 工程特征 + 浅 XGB | ✅ `b1_intraday_features.py` 4 NEW 标量(open-range/VWAP-dev/realized-vol/vol-z) + train_b1 RB1-gate-routed-first ; 12/12 |
| **RB3** | experiment B1 acceptance | ✅ verdict **PASS**:val_ic+0.084/p2 thin not-worse(+0.044/+0.003)/3x cost positive;**A/B 诚实分解**:info_contrib−0.099(sign 无信息)/timing_contrib+0.143(magnitude 才有价值)→B1 价值在 pred 量值非 sign |
| **RB4** | build B2 deep scaffold + **MANDATORY DLinear** | ✅ `b2_intraday_deep_scaffold.py` dlinear_baseline(Zeng2023 attributed)+ multi-TF channel stack + b2_ssl_frozen_probe(RA7 delegate);11/11 |
| **RB5** | experiment B2 acceptance(verdict MOST strict) | ✅ verdict **FAIL_recorded_root_cause**:IC DLinear−0.056/Shallow+0.087/Deep−0.089;deep≥shallow=False;DSR(shallow,honest_n=15,T=59)=**0.538>0.5 survives**;PBO 0.119 不 red-flag;**MOST-strict gate-stack 正确拒 PASS,shallow 是 PASS-worthy non-promotion finding within FAIL framing**;A/B FORCED 揭示 deep/DLinear 量值校准毒 |

---

## §2 End-to-end chain verification

数据 → leakage helpers → engineered features → ML arms → IC/NAV → verdicts → ledger,每一环 R3 实测:

```
config/cost_model.yaml + universe.yaml + temporal_split.yaml
  → core/data/bar_store.py (BarStore adjusted cascade,P0-A fix)
    → cycle06/08 _load_panel (selector=train+val, sealed 2026 NEVER read)
      → core/research/label_leakage (PRD-1 canonical)
        → core/research/engineered_features (RA1 stationary)
          → core/research/a1_pipeline (RA2 shallow XGB+frozen-probe PCA)
          → core/research/cascade_overlay (R12 timing/sizing/veto)
          → core/research/b1_intraday_features (RB2 4 intraday scalars)
          → core/research/b2_intraday_deep_scaffold (RB4 SSL+DLinear)
            → core/research/component_b_gate (RB1 4-prereq guard)
              → 9 experiment drivers (R5/R8/R13/RA3/RA4/RA6/RA8/RB3/RB5)
                → 9 verdict JSON in data/audit/ml_redo/
                  → docs/memos/20260518-prd123_execution_ledger.md (SoT)
```

每节点 R3-VERIFIED via 190-test smoke + 9 JSONs 全在。

---

## §3 Dependency-order check

| Constraint | Status | Evidence |
|---|---|---|
| PRD-1 全做完 → PRD-2 ∥ PRD-3-A | ✅ | PRD-1 R6-final closed 2026-05-19 BEFORE R7 PRD-2 ralph-loop subPRD 写 + R8 PRD-3-A subPRD 写 + R9 P2.1 R1 start |
| PRD-3-B gated 于 P2.3 EXECUTED | ✅ | P2.3 R13 EXECUTED R32 2026-05-19 BEFORE RB1 build R43 — RB1 guard 跑时 P2.3 已 EXECUTED ✓ |
| RA7 R6 expanded-universe guard 硬前置 | ✅ | RA7 build R39 完成 ; RB1 4-prereq guard 显式检查 ra7_r6_expanded_guard ✓ |
| Directional 停等 honored | ✅ | (a) cycle06/08 重评 FAIL → 主线归零? **未触发**(P1.3 scope-correction proven factor-composite 不受 run4 leakage 影响,user ratify A+C-lite);(b) true-short P2.4 execution **永不实现**(R14 stub guard test asserts refuse + no exec wiring grep-verified);(c) 15m boundary **RATIFIED 2026-05-19** by user explicit-go(non-silent memo + invariant fold) |

---

## §4 Honest scoping notes(诚实记录,非 blanket)

跨 PRD-1/2/3 共 4 个 experiment 出 **FAIL_recorded_root_cause**;每个都按 `feedback_no_blanket_failure_verdict` 纪律 root-caused 且**非方法证伪**:

| Experiment | FAIL 性质(scoped) | Root-cause |
|---|---|---|
| P2.1 R5 T1-vs-T0 | **regime-conditional value**(crisis-DD 真降但牛市 alpha-bleed) | static always-on 1x inverse hedge cost-bleed at trending regime |
| P2.3 R13 cascade acceptance | **配置 scoped**(月度 cadence+liquid 趋势集 cascade=position 剃头) | veto 几乎不触发(info=0)+ long-bull timing-scale<1 减仓丢收益;与既有 CLAUDE.md Multi-TF naive cross-TF 输 60m-only + Phase-D 负 bar-IC 一致;cascade R12 default-off 仍 bit-identical 正确原语 |
| RA8 A4 acceptance | **statistical power-scoped** 非方法证伪 | in-domain SSL IC+0.019 击败 ImageNet domain-transfer(实质 Q1=YES),但 T=59+n_trials=10 honest-N+fail-closed DSR=power 不足;**纪律按设计工作** |
| RB5 B2 acceptance | **gate-stack 正确工作**(MOST-strict 拒 deep>shallow) | shallow(0.087)>deep(−0.089)at this T/encoder/feature panel;A/B FORCED 揭示 deep/DLinear sign 载 info 但量值校准毒;**与 4-agent 文献「engineered+shallow>deep@低SNR」一致**;shallow 自身 DSR 0.538>0.5 survives 是 non-promotion finding within FAIL framing |

5 个 PASS:P2.2 R8(cross-asset done right)/ RA3 A1(IC 0.056 + JKX 强差异化)/ RA4(干净决定性图像非必需)/ RA6(JKX>close-GAF;frozen>floor on signal-bearing arm)/ RB3(B1 shallow thin not-worse)。

**ZERO sealed 2026 reads** verified across all 9 experiments(`sealed_2026_read: False` in every JSON;`year < 2026` filter on intraday paths;cycle06 selector partition 强制 train+val)。

**ZERO core invariant changes除以下显式 RATIFIED**:① QQQ-deprecation(2026-05-02 user explicit-go,先例)② 15m-decision-input boundary(2026-05-19 user explicit-go,本轮)。其余:long-only/no-margin/SQQQ blacklist/MaxDD 15-20%/2008-≤25% 全部**未动**。

**真 short(P2.4)execution 永不自动 fire**:R14 stub guard test(7/7)+ grep 证 `core/backtest/`+`core/execution/`+`core/paper_trading/` 全无 true-short execution wiring。

---

## §5 文件清单(关键 deliverables)

**新代码模块** (12):
- `core/research/label_leakage.py`(P1.1)
- `core/research/construction_tiers.py`(R2/R3)
- `core/research/cascade_overlay.py`(R12)
- `core/research/engineered_features.py`(RA1)
- `core/research/a1_pipeline.py`(RA2)
- `core/research/a4_universe_guard.py`(RA7 + R6 guard)
- `core/research/component_b_gate.py`(RB1)
- `core/research/b1_intraday_features.py`(RB2)
- `core/research/b2_intraday_deep_scaffold.py`(RB4 含 mandatory DLinear)
- `core/ml/chart_cnn.py` additive `jkx_bar_image`(RA5)
- `core/config/schemas/cost_model.py` additive `sensitivity_multiplier`(R11)
- `core/ml/xgb_alpha.py` additive `sample_weight`(RA2)

**测试套件** (15+ new files, 190 passing in audit smoke)。

**Experiment drivers** (9): `dev/scripts/prd2/p2_1_r5*` / `p2_2_r8*` / `p2_3_r13*` ; `dev/scripts/prd3/ra3*` / `ra4*` / `ra6*` / `ra8*` / `rb3*` / `rb5*`。

**Verdict JSONs** (9 in `data/audit/ml_redo/`).

**PRDs/memos** (9 new): `docs/prd/20260518-prd{1,2,3}_*.md` / `docs/prd/20260519-prd{2,3}_ralph_loop_execution.md` / `docs/prd/20260519-phase_d_iterative_loop_and_multi_tf_framework.md`(CLAUDE.md reorg)/ `docs/memos/20260519-15m_decision_input_boundary_revision.md` / `docs/memos/20260518-prd123_execution_ledger.md`(SoT) / 本 post-audit。

**ZERO `git add -A`** used across the entire execution(每 commit 显式 file list per memory feedback)。

**ZERO bg double-backgrounding** (run_in_background 直跑 + no nohup/&, R16 discipline)。

**Filesystem cleanup** (rm/mv done by user, verified clean): root `renamed` / `sqlite:` 壳(cycle10 optuna 唯一副本归位 data/mining/) / root `artifacts/`(并入 dev/artifacts/ + acceptance_pack.py 默认改向同步)。

---

## §6 Final honest summary(plain language)

**做完了什么(诚实)**:
- **3 个 PRD 全 27 个 round 全完**:PRD-1 P1.1-1.4 + PRD-2 R1-R14 + PRD-3-A RA1-RA8 + PRD-3-B RB1-RB5。
- **9 个 experiment 全跑+verdict+root-cause**:5 PASS + 4 FAIL_recorded_root_cause(全 scoped + 非 blanket + 多个是「gate-stack 正确工作」的 informative 负面)。
- **190 tests passed** in the audit smoke;所有 build-round AC GREEN,所有 experiment-round AC = ran+recorded+verdict+root-cause 满足。
- **核心不变量 0 静默变更**;2 个显式 ratify(QQQ-deprecation 2026-05-02 / 15m boundary 2026-05-19);真 short P2.4 execution 永不自动 fire 已写死 + grep 证。
- **Sealed 2026 0 次读取**(9/9 实验 sealed_2026_read=False R3 实证)。

**没做的(诚实留痕)**:
- 这是 IC 层 + construction-overlay 层的研究+评估完成;**没有 promote 任何 alpha**(PRD-3 funnel 纪律,binding gate=PRD-2 NAV Track-A,需走 §6.2/forward observation 流程,**不在本 loop scope**)。
- 真 short P2.4 execution 永久 TODO(触发须用户 explicit-go memo + borrow/SSR/squeeze model + 风险不变量回归)。
- bulk expanded_v2 ~1000-symbol weekend-row + 2026-stale 修复(C-lite finding §2):off-critical-path;若未来 A4/B 想用 >curated universe,RA7 R6 guard 会强制要求显式 certification + 修复。

**操作员独立判断(quant 角度)**:
- 战略上,**RA4 的「图像非必需,价值=归一化」+ RB3/RB5 的「engineered+shallow 在低 SNR 实质上是 ROI 之王」+ R8 的「cross-asset done right 真降 DD 不放血」** —— 这 3 条是本轮最大的可操作 insight。
- RA8 in-domain SSL > ImageNet domain-transfer 是 directional insight(in-domain prior 真的重要),但 power 不足 → 后续需要更大 T(更多年/更多名)或更有效的 model-selection 节流来过 DSR honest-N gate。
- R5 静态对冲 vs R8 cross-asset 的对比是 PRD-2 最核心的 actionable conclusion:**多元化(cross-asset)是合法 TC-attack;静态always-on 对冲是 cost-bleed**。
- intraday-ML(RB5)在此 T/feature/encoder 下 deep<shallow,但 shallow 自身 DSR survives — 是 honest non-promotion finding 非「intraday-ML 无用」。

**Loop terminates here.** PRD-1/2/3 ralph-loop execution complete. 没有 ScheduleWakeup。
