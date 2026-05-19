# Strategic Close-out — PRD-1/2/3 + Track-A research arc

**Date**: 2026-05-19 · **Lineage**: `strategic-closeout-2026-05-19`
**Trigger**: user "走 D"(选项 D = 收尾,把战略 takeaway 落成 memo,封盘)
**Inputs**:
  - `docs/memos/20260518-prd123_execution_ledger.md` (执行 SoT)
  - `docs/memos/20260519-prd123_post_audit_and_final_summary.md` (技术 audit)
  - `data/audit/ml_redo/*.json` (9 个 PRD experiment + Track-A 双 FAIL)
  - `data/audit/ml_redo/a1_b1_nav_track_a_INVALID_temporal_leakage.{json,log}` (leakage 留痕)

本 memo 不重复技术 audit(那已在 post_audit_and_final_summary 里)。
本 memo 写的是**经过整套 funnel 实跑之后,operator 作为独立量化
得出的 strategic conclusion** —— 给未来的自己和合作者看。

---

## §1 这一轮真正学到了什么(非技术,战略)

### S1 — long-only + cap-aware + monthly 是真 binding constraint(不是说说而已)

PRD-2 的核心 Clarke-de Silva-Thorley 2002 论点("long-only TC ≈
0.3-0.5,signal 只能转化 30-50% 到 NAV")在 **Track-A** 真跑里
**得到经验证伪不了的证据**:

- **RA3 IC=0.0558**(月度横截面 rank corr)是真显著、非 sibling
  (JKX R²=0.033 高度正交)、非 inflated。**signal 层这条腿是好的**。
- **A1 NAV Track-A**(同一信号、leakage-correct year-by-year
  rolling walk-forward 评出):cum +281%、Sharpe 0.73、17 年
  **跑输 SPY −353pp**。
- 用 Grinold-Kahn 公式反向 sanity-check:IR ≈ IC × √N、N=5 vals×
  12mo × 10 syms ≈ 600 月度截面 obs → annualized Sharpe **预期
  0.6-0.8 区间**。**实测 0.73 严丝合缝**。
- 也就是说:这套约束下,IC=0.06 的 single ML signal 数学上**不
  可能**给出 Sharpe > 1 的 NAV。要打过 SPY(17 年 Sharpe ≈
  0.6-0.7 + 6× cumulative)需要 IR > 1.0,**单信号在 IC 这个量级
  做不到**,不是数据问题、不是算法问题、是 transfer coefficient
  数学问题。

这是本轮**最 actionable 的发现**。

### S2 — RA4 决定性结论:representation value = NORMALIZATION,not 图像 / not 深度

3-point curve 严格单调:
- 原始 63d 窗(不归一化)→ IC ≈ 0(没信号)
- ROCKET-essence 随机卷积(隐式归一)→ IC 0.025(恢复一半)
- 显式 per-name 归一 + 浅 XGB → IC 0.056(满信号)

**JKX 2023 论点验证**:所谓 chart-image 的"价值"几乎全部
是 implicit per-name scaling。**显式归一化 + 工程化特征 + 浅模型
跟图像+预训练 CNN 同等水平,甚至更高**。

战略含义:**不该把研究算力砸在更深的 CNN / transformer / 大模型
pretrain 上**(本轮 RA8 in-domain SSL 也是 power-scoped FAIL,RB5
deep<shallow);**该把算力砸在 differentiated archetype
(intraday reversal / event / microstructure)+ ensemble +
cross-asset overlay 上**。

### S3 — cross-asset diversification 是真降 DD 不放血 alpha(唯一 PRD-2 NAV-PASS)

R8 实验:cap_aware_cross_asset(股 + 债 + 商品 + 现金等价物)vs
equities-only:**non-equity 利用率 37% / full DD 改善 6.88pp /
covid 12pp / rate_hike_2022 2.77pp**。

对比 R5 静态 1x 反向对冲 → cost-bleed 长牛 alpha:**只多元化 ✓,
只对冲 ✗**。

这跟 S1 合起来给出明确战略路径:**单 ML 信号 standalone 死路;
ML 信号 ensemble + cross-asset overlay 才是 NAV-binding-gate
能过的方向**(R8 已证多元化是合法 TC-attack lever)。

### S4 — 4 个 FAIL_recorded_root_cause 都是 funnel discipline 正确工作的证据

| FAIL | 真相 |
|---|---|
| P2.1 R5(静态对冲) | 不是策略坏,是 *static-always-on* 对冲在牛市 cost-bleed;regime-conditional 才有用 |
| P2.3 R13(月度 cascade) | 不是 cascade 坏,是把日内 timing 工具用作月度仓位剃头;default-off 仍是正确原语 |
| RA8(in-domain SSL) | 不是 SSL 坏,是 T=59 + n_trials=10 honest-N 的 power 不足;DSR fail-closed 按设计工作 |
| RB5(deep intraday) | 不是 deep 坏,是此 T/encoder/feature panel 下 shallow 吃透了;A/B FORCED 揭示 deep+DLinear sign 载 info 但量值校准毒 |
| **Track-A A1+B1** | **不是 ML 坏,是 single signal 在 binding constraint 下数学上转不出 NAV-pass** —— S1 已证 |

**没一个是 blanket 失败,全是 scoped + root-caused + non-blanket**。
funnel 没 promote 任何东西到 fleet —— **这正是 funnel 设计目的**。

---

## §2 战略路径 forward(operator 独立判断,**非 commitment**,等用户拍)

按优先级:

### P1 — Ensemble + Cross-asset Overlay(高 ROI,需新 PRD)

具体:
1. 取 A1 / B1 / 既有 cycle06 factor-composite 做 IC-orthogonal 检查
   (本轮 RA3 已经做过 A1 的 JKX R²=0.033 vs 标准因子,需要再做
   inter-arm 正交)
2. 等权重或 Ridge-meta-stack 组合后,**叠加 R8 cross-asset cap
   overlay**(股 70% / 债 40% / 商品 20% / 现金 30%)
3. 重跑 NAV Track-A binding-gate

**预期**:IR 不能凭空提升,但 cross-asset overlay 的 DD 改善
6.88pp + 多元化路径可能把 vs-SPY 拉回正区间。如果 still FAIL,
那 long-only + cap-aware + monthly **真的就是天花板**,需要 P2。

**这是 NEW PRD 不是 loop 续**(scope-creep 不可)。

### P2 — 放宽 binding constraint(directional,需用户 explicit-go)

可选(由便宜到贵):
- 调 cap-aware:top-N 从 10 放到 5(更集中,beta 更高,但破不变量
  top1 ≤40%)— **需 explicit-go**
- 调 cadence:月度 → 周度(更高 turnover,需 R11 sensitivity cost
  sweep 跑通才确认 IR 提升 > 成本)— 不破不变量,**可做**
- 真 short P2.4 execution — **永不实现除非用户 explicit-go**(永久
  TODO,本轮 R14 stub 已封)

### P3 — 不做但记录(scope creep 防呆)

- 不再扩 CNN/transformer 深度模型(RA4/RA8/RB5 已证 ROI 不值)
- 不再尝试 single-signal standalone promotion(Track-A 已证不行)
- 不再 try 静态对冲(R5 已证 cost-bleed)
- intraday-ML 暂封(RB5 deep<shallow,T 不够;等真有更大数据/更细
  archetype 再说)

---

## §3 本轮成果 inventory(可重用 artifacts)

新模块全部经 TDD + leakage-correct + bit-identical regression:

| 模块 | 用途 | 后续 ensemble PRD 可直接复用 |
|---|---|---|
| `core/research/label_leakage.py` | canonical leakage-correct helpers | ✓ |
| `core/research/engineered_features.py` | JKX 归一化+kline+vol_z+frac_diff | ✓ |
| `core/research/a1_pipeline.py` | shallow XGB+frozen-probe PCA | ✓ |
| `core/research/cascade_overlay.py` | timing/sizing/veto overlay(default-off) | ✓ |
| `core/research/construction_tiers.py` | T0/T1/T2 schema+gates | ✓(T1 用于 ensemble 测) |
| `core/research/b1_intraday_features.py` | 4 intraday scalar features+train_b1 | ✓ |
| `core/research/b2_intraday_deep_scaffold.py` | mandatory DLinear baseline+SSL probe | ✓(DLinear) |
| `core/research/component_b_gate.py` | naive-archetype refuser+前置 gate | ✓ |
| `core/research/a4_universe_guard.py` | R6 expanded-universe hard precondition | ✓ |
| `dev/scripts/track_a/a1_b1_nav_track_a.py` | year-rolling walk-forward NAV evaluator | ✓ |

CostModel R11 sensitivity_multiplier、HarnessConfig
construction_tier 都是 additive default-bit-identical 加法,不影响
既有 cycle06/08 任何评估。

---

## §4 留痕 / honest 不删

- `a1_b1_nav_track_a_INVALID_temporal_leakage.{json,log}` — R1 driver
  bug 的 leakage 伪结果(Sharpe 2.0 / cum +5617%),**保留为证据**
  以便未来读到这段历史的人能学到"interleaved selector partition
  + parameter-learning ML = looking-forward leakage"这个陷阱
- chart_native_s1 caveat memo(`docs/memos/20260518-chart_native_s1_
  evidence_leakage_caveat_decision.md`)—— 原 17/17 PASS 是
  leakage-inflated,leakage-correct 后 FAIL,**Option A 保留+caveat
  不重做**,β 不 refit
- ZERO sealed-2026 reads across all 9 experiments + Track-A
- ZERO silent invariant changes(QQQ-deprecation 2026-05-02 +
  15m-decision-input 2026-05-19 是唯二 explicit ratify)
- 真做空 P2.4 execution 永远 TODO,**grep-verified zero execution
  wiring**(R14 stub guard 7/7 + core/backtest+execution+
  paper_trading 全无 short order routing)

---

## §5 给未来的自己一句话

> **在 long-only + cap-aware + monthly 的 binding constraint
> 下,IC=0.05 量级的 single ML signal 数学上转不出能打过
> SPY 的 NAV。这不是数据问题、不是算法问题、是 transfer
> coefficient 的天花板。继续 push 单信号 IC 是浪费,该 push 的是
> ensemble + cross-asset overlay(R8 唯一 PASS 的合法 TC-attack
> lever)+ 真 directional 信号(差异化非 sibling 的 intraday
> reversal / event / microstructure,non-naive),不是更深/更花式
> 的 ML。如果 ensemble 仍打不过,那就直面 binding constraint
> 本身的 directional 决策(放宽 cap-aware / 调 cadence /
> 极端情况下真 short — 须 explicit-go)。**

---

**Loop terminates here.** PRD-1/2/3 + Track-A 全部技术工作 + 战略
总结全部 captured。Funnel discipline 严守,zero silent promotion,
zero invariant breach。剩下都是 directional / new-PRD scope,等用户
拍板。
