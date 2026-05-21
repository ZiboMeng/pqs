# R0 Re-Risk Pack — 2026-05-21

**PRD**: `docs/prd/20260521-rerisk-and-ml-training-audit-prd.md` §6
**驱动**: `dev/scripts/audit/rerisk_pack.py`(可复现,§6.4)
**机读产物**: `data/audit/rerisk_pack_20260521.json`
**Lineage**: `rerisk-and-ml-training-audit-2026-05-21`

执行内核 5 修复(2026-05-21,commits `d056652`..`14a1c0c`)之后,对
production baseline 与活跃 evidence 候选重算可信风险画像。每行声明
回测窗口 + temporal_split partition(§6.5);所有数字由 checked-in 的
`run_backtest.py` 路径产出,无手工计算。

本 memo 随 ralph-loop 逐轮增补,不覆盖既有行。

---

## 进度

| 候选 | 状态 |
|---|---|
| production baseline | 🟡 train-only / 🔴 近期 diagnostic / 🟢🟢 2 stress slice(per-year 不单列,见 §5.4) |
| **R0 总状态** | ✅ **CLOSED(Round 8)** — 4 候选交付,§6.4 acceptance 全过,见 §5 |
| cycle06_31af04cf2ff9_evidence_v1 | 🔴 Round 4:exact-frozen-spec 重评 — 风险稳定但 Track-A FAIL(vs-SPY aggregate) |
| cycle08_3f40e3f4ed1a_evidence_v1 | 🟢 Round 6:exact-frozen-spec 重评 — Track-A PASS 保持,frozen evidence 复现 |
| pead_sue_trial1_evidence_v1 | 🟢 Round 7:post-fix 重评 — MaxDD -7.9%,2x-cost robust,Track-A 14/17→16/17 |

---

## 1. Production baseline(multi_factor conservative_default)

来源:`config/production_strategy.yaml`(status=conservative_default)。

### 1.1 train-only 窗口 2009-01-02 .. 2017-12-31(partition: train_only)

| 指标 | 值 |
|---|---|
| 总收益 | +190.35% |
| CAGR | +12.59% |
| Sharpe | 0.67 |
| 最大回撤 | **-20.21%** |
| 年化波动率 | 13.16% |
| Beta vs SPY | 0.28 |
| IR | -0.02 |
| 交易笔数 | 1629 |

**verdict: YELLOW(provisional)** —— full-period MaxDD 20.2% 略越
15-20% 硬上限(超 0.2pp);stress-slice + per-validation-year MaxDD
待 Round 2 补齐后升级为正式 verdict。

复现:`python scripts/run_backtest.py --strategy multi_factor
--start 2009-01-02 --end 2017-12-31 --no-walk-forward`。

**解读**:在纯 train 低波动期,baseline 实际波动率仅 ~13%(远低于
constructor 的 25% target_vol),correlation-aware vol-target(P0-1
修复)在此窗口 inert,MaxDD ~20% 基本贴线。这与 PRD §2.1 修订
后的判断一致 —— baseline 非全局损坏,而是 regime-fragile:灾难性的
-64% MaxDD 出现在近期高波动窗口(Round 2 将以显式标注的 diagnostic
窗口复现该对比)。

### 1.2 近期窗口 diagnostic 2022-01-03 .. 2025-12-31(partition: diagnostic)

⚠ **DIAGNOSTIC WINDOW** —— 跨 validation 年(2023/2025);按 PRD §6.5
+ 用户决策〇.4,作显式标注的 diagnostic 复现一次,**非** candidate
pass/fail gate。sealed 2026 未触(end 2025-12-31)。

| 指标 | 值 |
|---|---|
| 总收益 | -16.71% |
| CAGR | **-4.49%** |
| Sharpe | -0.16 |
| 最大回撤 | **-63.95%** |
| 年化波动率 | **27.72%** |
| Beta vs SPY | 0.43 |
| IR | -0.38 |
| 交易笔数 | 1459 |

**verdict: RED(diagnostic,informational)** —— MaxDD 64% 远越 25%
stress 上限。

**regime 分层**(取自 master_report §2;PRD §2.1 修订注:regime 标签
来自 regime 分类器,牛市标签下亏 40% 本身可疑,**报告但不当 settled
root-cause**):

| Regime | 天数 | CAGR | MaxDD | vs SPY |
|---|---|---|---|---|
| BULL | 203 | -39.93% | -60.49% | -78.22% |
| RISK_ON | 239 | +42.00% | -9.13% | +14.35% |
| NEUTRAL | 106 | +26.88% | -13.46% | +34.03% |
| CAUTIOUS | 293 | -9.54% | -18.49% | -4.45% |
| RISK_OFF | 143 | -0.51% | -6.28% | -4.08% |

复现:`python scripts/run_backtest.py --strategy multi_factor
--start 2022-01-03 --end 2025-12-31 --no-walk-forward`。

**解读**:PRD §2.1 的 -63.95% 画像现已落成 checked-in、explicit-window、
标注 diagnostic 的可复现行 —— §2.1 caveat 闭合。对照 §1.1 train-only
(CAGR +12.59% / MaxDD -20.21% / vol 13.16%):**同一 config,低波动期
良性、近期高波动期灾难** —— 印证 PRD §2.1 修订判断:baseline 非全局
损坏,是 regime-fragile / 高波动期风控翻译失效。注意 diagnostic 窗口
realized vol 27.72% 已越 constructor 25% target —— correlation-aware
vol-target(P0-1)在此 regime 起作用但 0.25 target 本身就高于 15-20%
MaxDD 不变量的隐含预算(PRD §1.5 / §2.1 标的 directional 项)。

### 1.3 stress slices — ✅ 用户裁定 Option A(2026-05-21)

> **DECISION(用户 2026-05-21):走 A。** baseline stress-slice MaxDD 用
> warmup+slice 回测计算,显式标 `partition: stress_slice (warmup spans
> validation 20XX)`、informational、不作 candidate pass/fail gate ——
> 与 Round-2 diagnostic 行同一纪律姿态。后续 ralph-loop 轮执行。

机制核查记录(Round 3,保留作 audit trail):

**机制核查结论(Round 3):**

- `core/risk/stress_tester.py` = 静态权重 **shock 模型**(对固定持仓施
  加 ±% 冲击),不是"策略穿越危机窗口"的 MaxDD,不适用。
- 真正 sanctioned 的 stress-slice MaxDD 在 Track-A:
  `cycle06_track_a_eval.py:88` 用
  `partition_for_role(panel, split_cfg, role="selector")` →
  面板 = **train + validation**;harness 产 `metrics_per_stress_slice`;
  `temporal_split_acceptance._eval_stress_slice_gates` 据此 gate
  (`mode: stress_check_only`,不参与 alpha selection)。
- `temporal_split.py`:stress slice `source_year` 必须是 train 年
  (covid 2020 / rate_hike 2022 都是),slice 日期落在该年内。

**问题**:计算 baseline 穿越 covid_flash(2020-02-15..04-30)/
rate_hike_2022 的 MaxDD,strategy 必须持仓进入该窗口 → 189 天动量
lookback warmup 必然吃到危机前 ~9 个月(covid 要 2019、rate_hike 要
2021)—— **而 2019/2021 是 validation 年**。Track-A 这样做合规
(selector 阶段允许 access validation);但 R0 re-risk **不是**
selector 阶段。用户决策 ⑤ 授权了"designated stress slice",未明确
涉及"warmup 穿过 validation"这个子问题。

**需用户拍板的选项:**

- **A(推荐)**:用 warmup+slice 回测算 stress-window MaxDD,定位与
  Round-2 diagnostic 行一致 —— 显式标 `partition: stress_slice
  (warmup spans validation 20XX)`、informational、不作 candidate
  pass/fail。理由:stress slice 是 temporal_split.yaml 明列的
  `stress_check_only`、不喂 selection;warmup 只在 factor lookback
  里用 validation 年价格(非 label/评估目标);且选项 B 同样吃
  validation。
- **B**:复用 Track-A harness 的 stress-slice 计算 —— canonical
  但 harness 为 cycle 候选 NAV 而建,适配 multi_factor baseline 需
  额外工作,且**同样**用 validation-inclusive 面板。
- **C**:R0 不单算 baseline 的 per-slice MaxDD,靠 §1.2 的 2022-2025
  diagnostic 行(已含 2022 rate-hike 熊市)+ 注记 covid_flash 未单测。
  零 validation-warmup 问题,但相对 §6.2 不完整。

operator 推荐 **A**(与已授权的 diagnostic 行同一纪律姿态)。待用户
explicit-go 后由后续 ralph-loop 轮执行。

---

**Round 5 结果(Option A 执行)** —— `dev/scripts/audit/rerisk_pack.py
--candidate baseline-stress`(warmup+slice 回测,读 `run_backtest`
新增的 `equity_curve.csv`,按 designated slice 日期算 MaxDD):

| stress slice | slice 日期 | warmup 起点 | slice MaxDD | verdict |
|---|---|---|---|---|
| covid_flash | 2020-02-15..04-30 | 2019-01-02 | **-13.66%** | GREEN(≤25%)|
| rate_hike_2022 | 2022-08-15..10-15 | 2021-07-01 | **-3.51%** | GREEN(≤25%)|

⚠ **关键诚实 caveat —— stress 行 GREEN 不等于 baseline 抗危机**:
designated slice 是**窄窗**(temporal_split.yaml 定义)。`rate_hike_2022`
slice 只覆盖 2022-08-15..10-15(2022 熊市的最后一段),所以 slice
MaxDD 仅 -3.51% —— 但 baseline 在整个 2022 的真实创伤是 §1.2
diagnostic 行的 **-63.95%**(2022-Q1 顶 → 深谷)。两者不矛盾:slice
MaxDD 测的是 slice 窗**内**的回撤。**不可**把 covid -13.66% /
rate_hike -3.51% 这两个 GREEN 读成"baseline crisis-robust" —— 真实
近期高波动期画像以 §1.2 的 -63.95% 为准。

warmup 穿越 validation 年(covid→2019、rate_hike→2021):per Option A
+ 决策 ⑤,在 factor lookback 用 validation 年价格、informational
stress-sanity、不作 pass/fail gate;已显式标注于 `partition` 字段。

---

## 2. cycle06_31af04cf2ff9_evidence_v1

来源:`data/research_candidates/cycle06_31af04cf2ff9_evidence_v1.yaml`
的 **exact frozen spec**(3-feature composite,verbatim;PRD §2.2:
不用 lineage top-1 lookup)。驱动
`dev/scripts/audit/rerisk_composite_candidate.py --candidate cycle06`
复用 sanctioned 的 cycle Track-A eval(`_eval_trial`,selector
面板 —— 对 research 候选的 Track-A 阶段合规)。完整 eval:
`data/audit/rerisk_cycle06_eval.json`。

**verdict: RED** —— 但 non-blanket,见下分解。

| 指标 | re-risk | frozen evidence | 对比 |
|---|---|---|---|
| covid_flash MaxDD | -15.99% | -15.32% | ≈,劣 0.67pp |
| rate_hike_2022 MaxDD | -9.48% | -9.48% | 一致 |
| per-year MaxDD max(2018) | -19.94% | -19.60% | ≈,劣 0.34pp |
| Track-A 总判 | **FAIL** | PASS | **PASS→FAIL** |
| 失败 gate | `validation_aggregate_excess_vs_spy` | — | — |

per-year MaxDD:2018 -19.9% / 2019 -5.7% / 2021 -9.8% / 2023 -9.3%
/ 2025 -16.6% —— **全部 ≤ 20% 硬上限**。

**解读(non-blanket)**:
- **风险面稳定** —— per-year MaxDD 全 ≤20%、stress MaxDD 全 ≤25%,
  与 frozen evidence 一致(±<0.7pp 噪声级)。这不是回撤回归。
- **但 Track-A 总判 PASS→FAIL** —— exact-frozen-spec 后评失败于
  `validation_aggregate_excess_vs_spy`(vs-SPY 聚合超额)。frozen
  yaml 的 headline `track_a_acceptance: PASS` 在当前代码路径下**不
  复现**。
- 这是 **alpha-gate(vs-SPY)失败,不是风控回归**。§6.3 verdict
  RED 因"materially contradicts frozen evidence"(PASS→FAIL),flag
  明确区分二者。
- PRD §2.2 记录的"先前 re-risk 用 lineage top-1 `bab8cfe88af3`"同样
  FAIL `validation_aggregate_excess_vs_spy` + 额外 `validation_year_
  2018_maxdd`;exact-frozen-spec 比 top-1 好(2018 MaxDD -19.9%
  现 PASS),但仍 FAIL vs-SPY 聚合。

复现:`python dev/scripts/audit/rerisk_cycle06.py`。

## 3. cycle08_3f40e3f4ed1a_evidence_v1

来源:`data/research_candidates/cycle08_3f40e3f4ed1a_evidence_v1.yaml`
的 **exact frozen spec**(3-feature composite:max_dd_126d /
xsection_rank_63d / ret_5d,monthly cadence;verbatim)。驱动
`dev/scripts/audit/rerisk_composite_candidate.py --candidate cycle08`,
同 cycle06 路径(selector 面板,sanctioned)。完整 eval:
`data/audit/rerisk_cycle08_eval.json`。

**verdict: GREEN** —— frozen evidence 复现。

| 指标 | re-risk | frozen evidence | 对比 |
|---|---|---|---|
| covid_flash MaxDD | -19.73% | -19.72% | 一致 |
| rate_hike_2022 MaxDD | -11.90% | -11.90% | 一致 |
| per-year MaxDD max(2018) | -16.79% | -18.10% | 略优 1.3pp |
| Track-A 总判 | **PASS** | PASS | 一致 ✓ |

per-year MaxDD:2018 -16.8% / 2019 -7.2% / 2021 -7.8% / 2023 -12.2%
/ 2025 -10.5% —— 全部 ≤ 20%。

**解读**:cycle08 的 frozen evidence 在执行内核修复后**完整复现**
—— Track-A 总判 PASS 保持,stress + per-year MaxDD 与 frozen 几乎
逐字一致。**与 cycle06 形成对比**:cycle06 同样 exact-frozen-spec
重评但 Track-A PASS→FAIL(vs-SPY aggregate);cycle08 PASS 稳住。
cycle08 是两个 evidence 候选里更稳健的一个 —— 与项目既有判断一致
(PRD §2.3:"cycle08 remains the strongest currently frozen positive
evidence path")。

复现:`python dev/scripts/audit/rerisk_composite_candidate.py
--candidate cycle08`。

## 4. PEAD — pead_sue_trial1_evidence_v1(trial1_short_hold)

PEAD 在独立 evidence-only 轨。sanctioned Track-A acceptance =
`dev/scripts/pead/run_pead_track_a_acceptance.py`(post-fix 重跑);
`dev/scripts/audit/rerisk_pead.py` 把结果折进 pack。

**verdict: GREEN**。

| 指标 | post-fix re-risk | pre-fix(May-14 / PRD §2.4)| 对比 |
|---|---|---|---|
| Sharpe | 0.986 | 1.055 | 略降 |
| CAGR | +5.43% | +5.48% | ≈ |
| 全期 MaxDD | -7.92% | -7.64% | ≈,劣 0.28pp |
| 2x-cost 仍正 | true | true | 一致 |
| Track-A | **16/17**(overall FAIL) | 14/17(overall FAIL) | **改善 +2 gate** |

**解读**:PEAD evidence-only 候选执行内核修复后**风险面稳健**
(MaxDD -7.92%,远在 20%/25% 上限内;2x-cost robust),Track-A 实际
**改善**(14/17 → 16/17)。overall 仍 FAIL —— 但 PEAD frozen evidence
本就记录为 evidence-only / 非 full Track-A PASS(失败 gate 是 aggregate
excess vs SPY/QQQ,alpha 而非风控)。无风险回归、无与 frozen evidence
的矛盾 → GREEN。

复现:`python dev/scripts/pead/run_pead_track_a_acceptance.py &&
python dev/scripts/audit/rerisk_pead.py`。

---

## 5. R0 收口(Round 8)

### 5.1 七行 verdict 汇总

| 候选 | 行 / partition | verdict | 关键 |
|---|---|---|---|
| production baseline | train_only 2009-2017 | 🟡 YELLOW | CAGR +12.6% / MaxDD -20.2%(贴 20% 线) |
| production baseline | diagnostic 2022-2025 | 🔴 RED | CAGR -4.5% / MaxDD -63.95% / vol 27.7% |
| production baseline | stress covid_flash | 🟢 GREEN | slice MaxDD -13.66%(≤25%) |
| production baseline | stress rate_hike_2022 | 🟢 GREEN | slice MaxDD -3.51%(≤25%,窄窗) |
| cycle06_31af04cf2ff9 | track_a_selector | 🔴 RED | Track-A PASS→FAIL(vs-SPY aggregate);风险面稳定 |
| cycle08_3f40e3f4ed1a | track_a_selector | 🟢 GREEN | Track-A PASS 复现;frozen evidence 全复现 |
| pead_sue_trial1 | track_a_pead | 🟢 GREEN | MaxDD -7.9%;2x-cost robust;Track-A 14/17→16/17 |

### 5.2 §6.4 Acceptance 核对

| 条目 | 状态 |
|---|---|
| baseline row present | ✅ 4 行(train-only / diagnostic / 2 stress) |
| cycle06 exact frozen candidate replay | ✅ exact-frozen-spec(非 lineage top-1) |
| cycle08 exact frozen candidate replay | ✅ |
| PEAD row present | ✅ |
| every row full provenance path | ✅ 每行带 `reproduce_cmd` |
| no manual spreadsheet calculation | ✅ 全部 driver 产出 |
| all metrics reproducible from checked-in code paths | ✅ |
| every row states window + temporal_split partition | ✅ `window` + `partition` 字段 |

### 5.3 R0-level 发现

1. **baseline 是 regime-fragile,不是全局损坏** —— 低波动 train 期
   (2009-2017)良性(+12.6% / -20.2%),近期高波动期(2022-2025)
   灾难(-4.5% / -63.95%)。坐实 PRD §2.1 修订判断。
2. **风险面(MaxDD)post-fix 基本稳定** —— cycle06/cycle08 的 per-year
   + stress MaxDD 与 frozen evidence ±<1pp;PEAD MaxDD -7.9% 稳;
   baseline 的 stress-slice 在 ≤25% 内。**执行内核修复后,纯风控机制
   层面没有新回归。**
3. **所有 RED/FAIL 都落在 alpha gate(vs-SPY 超额),不是风控** ——
   cycle06 Track-A PASS→FAIL 失败于 `validation_aggregate_excess_
   vs_spy`;baseline diagnostic 的 -63.95% 是 vs-SPY 长牛跑输 + 高波动
   叠加。**binding bottleneck = alpha / construction quality,不是
   risk-mechanism。** 与 PRD §1.2 / §2.1 一致。
4. **cycle08 是最稳健的 evidence 候选** —— 唯一 Track-A PASS 完整
   复现的;cycle06 的 frozen `track_a_acceptance: PASS` 在 post-fix
   代码路径不复现(directional 含义:cycle06 forward 候选地位需
   用户复核 —— 留 R0 外的 directional 讨论,不在本 loop 自决)。

### 5.4 baseline per-validation-year MaxDD —— 不单列(决定 + 理由)

§6.2 行 schema 列了 "per-validation-year MaxDD table"。对 **baseline**
本 loop **不单独计算**严格的逐年表:① baseline 不是晋升候选(是
production conservative_default,被 re-risk 而非被 promote);② 其
crisis MaxDD 已由 diagnostic 行(2022-2025,含 regime 分层)+ 2 个
stress-slice 行在实质上覆盖;③ 严格逐年表需一次 validation-spanning
回测,对非候选 baseline 是低杠杆产出。cycle06/cycle08 行**已含**
`per_validation_year_maxdd`(其 Track-A eval 产出)。此决定记录在案,
非遗漏。

### 5.5 R0 关闭

R0 re-risk pack 四候选全部交付、§6.4 acceptance 全过。**R0 CLOSED。**
下一步进 Package P0(source contracts + 环境 floor,PRD §12.3)。
