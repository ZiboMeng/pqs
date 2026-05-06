# SR defer evidence update — train-only re-run + caveat 升级

**Date**: 2026-05-05  
**Operator**: zibomeng (Claude Opus 4.7)  
**Context**: 用户 2026-05-05 提醒 `config/temporal_split.yaml` 严格定义
train/validation/sealed 隔离纪律，老 P2 backtest range (2018-2025) 跨过
5 个 validation years + 3 个 train years 边界，违反 access_rules。

## 老 P2 evidence 重新定位

`docs/memos/20260505-sr_defer_step5b_rth_fixed_3spec.md` (commit `16e229c`)
报告的 SR defer 3-spec lift（trial9 +0.07 / RCMv1 +0.05 / Cand-2 +0.08
Sharpe）是在 **2018-01-01 → 2025-12-31** 范围跑的。该范围**全部包含**：

- validation_years: 2018, 2019, 2021, 2023, 2025 (5 years)
- train_years: 2020, 2022, 2024 (3 years)

→ 5 个 validation years 的 SR defer P&L 已被"看过"，evidence 类型**降级**
为 "diagnostic only — validation already consumed, NOT pre-promotion
eligible"。

## 新 train-only re-run

跑 **2009-01-01 → 2017-12-31** 连续 9 年段（全部 train_years，0 validation
/ sealed 消耗）。同样 6 个 backtest (3 spec × 2 arm)。

| Spec | Arm A Sharpe | Arm D Sharpe | ΔSharpe | ΔCAGR | ΔMaxDD | Defers |
|---|---|---|---|---|---|---|
| trial9 | 0.3228 | 0.3546 | +0.0318 | +0.20 pp | +1.18 pp | 576 |
| RCMv1 | 0.1917 | 0.2588 | **+0.0671** | +0.66 pp | **+2.85 pp** | 650 |
| Cand-2 | 0.4241 | 0.4438 | +0.0197 | -0.02 pp | **+2.96 pp** | 582 |

## 老 vs 新对比

| 指标 | 老 P2 (mixed 2018-2025) | 新 P2 (train-only 2009-2017) |
|---|---|---|
| Cross-spec Sharpe lift | +0.05/+0.07/+0.08 (**3/3** cross +0.05 gate) | +0.03/+0.07/+0.02 (**1/3** cross +0.05 gate) |
| Cross-spec CAGR lift | +1.67/+2.58/+2.26 pp (一致) | +0.20/+0.66/-0.02 pp (不一致 + Cand-2 略 negative) |
| Cross-spec MaxDD 改善 | +0.05/+2.16/+4.03 pp | +1.18/+2.85/+2.96 pp |
| Baseline Sharpe 水平 | 0.67-0.98 | 0.19-0.42 |
| Defer activation rate | 4.90/5.50/5.58% | 5.85/6.61/5.92% (~1pp higher) |

## 解读

### 1. Baseline Sharpe 大幅下降（0.81 平均 → 0.32 平均）

3 个 spec 在 2009-2017 段 baseline Sharpe 比 2018-2025 段低 ~50 bps。
这反映 **3 个 spec 的 high Sharpe 来源是 post-2018 specific-regime fit**
（2018 rate-hike-bear / 2019 normal-bull / 2020 covid V / 2021 liquidity
mania / 2023 AI narrow / 2025 current）而非 universal alpha。

trial9 (`beta_spy_60d × max_dd_126d × ret_1d`) 在 2009-2017 段表现仅
Sharpe 0.32 因为：
- 2009-2010 GFC 复苏期 max_dd_126d feature 拒绝持仓 → miss V 形大反弹
- 2014 oil crash + 2015-2016 China devaluation + Fed rate hike 系列
  small drawdowns 触发 max_dd 信号 → 频繁洗仓

而 2018-2025 段 trial9 Sharpe 0.78 因为：
- 2020 covid 触发 max_dd 但 V 形快速恢复 → max_dd 反而提供 rotation
  signal
- 2023 AI narrow rally + 2025 current 属于 trial9 喜欢的 low-vol
  uptrend regime

→ trial9 / RCMv1 / Cand-2 的 cycle04/05 mining 出来 Sharpe IS partly
**post-2018 regime-overfit** even though IC 计算严格 train-only。Mining
objective 是 IC_IR，IC 只反映 ranking quality 不反映 regime alignment。

### 2. SR defer lift cross-spec robustness 减弱

train-only 上 Sharpe lift 只 RCMv1 跨过 +0.05 gate (+0.067)，
trial9 (+0.032) 和 Cand-2 (+0.020) 都未跨。这意味着：

- 老 P2 的 "3/3 cross-spec robustness" claim **不成立** under train-only
  evidence
- SR defer 在 trial9 上的 alpha lift 主要来自 **post-2018 regime**，可能
  是 covid / rate-hike / AI rally 期间 60m-RTH-close-near-resistance
  状态特别多 (60m volatility regime shift)

### 3. MaxDD 改善 robust

train-only 上 3/3 spec MaxDD 改善 +1-3 pp。这是 SR defer 的**真正
generalize 能力**：在 swing 高点附近避免新 entry → 减少 drawdown
风险，机制不依赖 specific regime。

### 4. Defer activation rate 略升

train-only 段 (2009-2017) defer activation 5.85-6.61% vs mixed (2018-
2025) 4.90-5.58%。早期 9 年波动性高（含 GFC 余震），swing pattern 更
密集 → defer 更频繁。机制 sensible.

## 修正后的 SR defer evidence 定位

**Pre-promotion eligible evidence (train-only, 2009-2017)**:

- Sharpe lift: average +0.04, range +0.02 to +0.07 (1/3 cross +0.05 gate)
- CAGR lift: average +0.28 pp (range -0.02 to +0.66)
- **MaxDD 改善: average +2.3 pp (range +1.18 to +2.96), 3/3 cross-spec
  consistent** — 这是 robust 的 risk-management 价值
- Defer activation rate: 5-7% across specs (consistent)

**结论**: SR defer 不能 claim alpha-additive；可以 claim **risk-management
additive**。

**Diagnostic only (mixed 2018-2025) — validation already seen**:

- 老 P2 数字保留作为 "regime sensitivity" 诊断信息
- **不能** 作为 pre-promotion evidence
- **不能** 用来支持 "enable_sr_defer=true on next nominee" 决策

## 对 cycle #06 + 6.1-min Step 5+ 的影响

### 选项 A — 启动 cycle #06 SR family mining (alpha bet)

3 个 SR factors (`dist_to_swing_high_20d` / `dist_to_swing_low_20d` /
`sr_range_compression_20d`) 进 RESEARCH_FACTORS pool。Mining objective
是 IC_IR + walk-forward + cross-corr — 跟 SR defer (Path A) 不是同一回
事。SR factor IC 是否有 alpha 是 **独立假设**，未证实。

**风险**：cycle #04/#05 已经显示 cap_aware_cross_asset construction 在
33-61 factor 扩展下没产生 nominee。SR factor 加进去能否突破不确定。

### 选项 B — 6.1-min Step 5+ ship enable_sr_defer on next nominee (risk-mgmt bet)

基于 train-only MaxDD 改善 +2.3 pp average evidence，把
`execution_policy.enable_sr_defer=true` 作为 risk-management overlay
ship 在 future nominee 的 frozen yaml 上。**不 claim alpha lift**，
claim DD reduction.

**Pro**: train-only evidence 支持 (3/3 cross-spec MaxDD 改善 robust)；
plumbing 已 ship；激活成本几乎 zero。

**Con**: 没有 active nominee 等着 promote (RCMv1+Cand-2 aborted, trial9
forward observation in progress 不能改 spec)，需要 wait for 下一个
mining round。

### 选项 C — 都不做 (hold)

5.4 起严格 OOS 纪律 + train-only evidence 偏弱 (1/3 Sharpe gate)，
让 trial9 forward TD60 (~2026-07-30) 决定下一步。SR plumbing 已 ship
+ test 充分 + 0 maintenance burden — hold 0 风险.

## Operator 推荐

**C → 当 trial9 TD60 出 verdict 时再决定 A/B**:
- TD60 GREEN: 信号"low-vol diversifier 假设 hold"，激活 cycle #06 SR
  family mining 看是否有 SR-anchored alpha 补强 trial9
- TD60 YELLOW/RED: 重新审视 trial9 spec assumptions，cycle #06 也未必
  解决问题，可能需要 strategic pivot (per cycle #05 stop rule)

**当前不动作**(B 选项 B 不是错误，只是 premature without nominee)。

## OOS discipline 修正记录

老 P2 evidence (2018-2025 mixed range) 已 push 到 main commit `16e229c`，
不 retroactive 删除（git history audit trail 一部分），但本 memo 是
**evidence-type 降级 official record**：

> 老 P2 (`docs/memos/20260505-sr_defer_step5b_rth_fixed_3spec.md`) 的
> Sharpe lift +0.05~+0.08 数字是 mixed train+validation backtest，
> validation already consumed，不能 cite 为 pre-promotion evidence。
> Pre-promotion eligible evidence in this memo (train-only 2009-2017):
> Sharpe lift +0.02~+0.07 (1/3 cross +0.05 gate); MaxDD +1-3 pp (3/3).

未来 reference SR defer evidence 时**默认引用本 memo (train-only) 而非
老 P2 (mixed)**.

## Files

```
data/sr_validation/
  trial9_diversifier_TRAIN_ONLY_arm_baseline_metrics.json
  trial9_diversifier_TRAIN_ONLY_arm_baseline_nav.parquet
  trial9_diversifier_TRAIN_ONLY_arm_sr_defer_metrics.json
  trial9_diversifier_TRAIN_ONLY_arm_sr_defer_nav.parquet
  rcm_v1_defensive_composite_TRAIN_ONLY_arm_baseline_metrics.json
  rcm_v1_defensive_composite_TRAIN_ONLY_arm_baseline_nav.parquet
  rcm_v1_defensive_composite_TRAIN_ONLY_arm_sr_defer_metrics.json
  rcm_v1_defensive_composite_TRAIN_ONLY_arm_sr_defer_nav.parquet
  candidate_2_orthogonal_TRAIN_ONLY_arm_baseline_metrics.json
  candidate_2_orthogonal_TRAIN_ONLY_arm_baseline_nav.parquet
  candidate_2_orthogonal_TRAIN_ONLY_arm_sr_defer_metrics.json
  candidate_2_orthogonal_TRAIN_ONLY_arm_sr_defer_nav.parquet
```
