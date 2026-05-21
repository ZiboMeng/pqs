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
| production baseline | 🟡 Round 2:train-only + 近期 diagnostic 行已出;stress slice 待后续轮 |
| cycle06_31af04cf2ff9_evidence_v1 | ⬜ 待后续轮(exact frozen spec replay) |
| cycle08_3f40e3f4ed1a_evidence_v1 | ⬜ 待后续轮 |
| pead_sue_trial1_evidence_v1 | ⬜ 待后续轮 |

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

### 1.3 stress slices

⬜ 待后续轮。covid_flash 2020-Q1 / rate_hike 2022-Q3 作 MaxDD
sanity。**注**:stress-slice MaxDD 需 strategy 持仓进入 slice(动量
lookback warmup),实现方式需先查项目既有 stress harness
(`core/risk/stress_tester.py` / Track-A eval 的 stress-slice 路径),
避免重造或误触 holdout —— 该轮先做机制核查。

---

## 2-4. cycle06 / cycle08 / PEAD

⬜ 待后续 ralph-loop 轮。cycle06/cycle08 必须按 **exact frozen
spec** replay(PRD §2.2:不用 lineage top-1 lookup);sealed 2026
不在 R0 范围内单发。
