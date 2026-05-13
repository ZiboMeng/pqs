# PRD — ML Mining Pipeline Integration

**Date**: 2026-05-12
**Status**: DRAFT — awaiting user explicit-go for Phase 1
**Lineage**: `ml-mining-pipeline-2026-05-12`
**Authority**: User explicit-go 2026-05-12 ("同步准备ML的prd"); resident-quant strategic recommendation in alt-A Phase 3 closeout discussion
**Predecessors**:
- cycle04-08 stop-rule pivot ([[cycle04 closeout]])
- cycle #09 sampler postmortem ([[20260512-cycle_09_sampler_architecture_postmortem]])
- alt-A Phase 3 closeout ([[20260512-alt_a_phase_3_closeout]])
- 162-factor library expansion (PRD 20260512 Bucket A/B/C/Macro)

---

## §1 TL;DR — 大白话

**PQS 现在 mining 是线性的**：Optuna TPE 在 factor 组合空间搜索 + 线性加权 composite。**ML 工具完全没用到**（除了 TPE 本身和 XGBoost importance diagnostic）。

cycle04-08 全部 sibling，cycle #09 重 fire 中，alt-A Phase 3 REJECT。**线性 composite 路径已基本探索透**。

**这个 PRD 规划 4 个阶段把 ML 引入 PQS mining loop**:

| Phase | 方法 | 工程量 | 复杂度 |
|---|---|---|---|
| 1 | XGBoost return prediction | 2-3 天 | 低 |
| 2 | Multi-horizon regression | 1 周 | 中 |
| 3 | Cross-sectional Transformer | 2-3 周 | 高 |
| 4 | RL position sizing | 4-8 周 | 战略级 |

**核心原则**:
- 每个 phase 独立 ship, 独立 verdict
- Track A 17-gate guardrail 100% 保留（NAV-level acceptance 不会破）
- 162-factor library 不重新设计, 当作 ML 输入
- Sealed 2026 panel 一次性, 全 phase 共享
- 线性 baseline 一直保留作对比（cycle04-08 + cycle #09b nominee 作 reference）

**Pre-commitment**:
- 如果 Phase 1 XGBoost 没显著超过线性 baseline → 暂停 Phase 2+（说明 PQS 数据/universe 不适合 ML）
- 如果 Phase 1 显著超过 → 启动 Phase 2 探索 multi-horizon
- 各 phase 之间是 evidence-driven, 不是预先承诺全部做

---

## §2 Background — 为什么现在上 ML

### 2.1 PQS 现有 ML 渗透度

| 工具 | 用了吗 | 在哪 |
|---|---|---|
| Optuna TPE | ✅ | mining sampler (factor combo + weight search) |
| XGBoost feature importance | ⚠️ diagnostic only | `scripts/run_xgb_importance.py` |
| SHAP | ⚠️ diagnostic only | `core/diagnostics/detectors.py` |
| XGBoost return regression | ❌ | — |
| Random Forest / GBM | ❌ | — |
| Neural networks (any) | ❌ | — |
| LSTM / GRU sequence | ❌ | — |
| Transformer / Attention | ❌ | — |
| Reinforcement Learning | ❌ | — |

**mining objective 一直线性**: v1 IR-side, v2 NAV-based, v3 regime-conditional — 全都是 weighted sum + threshold gates. **没有非线性 model 介入 factor → return mapping**.

### 2.2 cycle04-09 + alt-A 暴露的 5 个 binding constraints

1. **78-股 universe 是 binding** (cycle04-05 verdict; long-only top-N over fixed universe → sibling baseline)
2. **monthly cap_aware top-N construction 是 binding** (cycle07a Trial 3 verdict; 仅换 anchor factor 不破 sibling)
3. **17-family sampler combinatorics 是 binding** (cycle #09 verdict; independent mode 0.0005% archive rate at 17 families)
4. **162-factor 库扩到极限但仍 linear mapping** (PRD 20260512; 线性 composite 找不到 non-linear factor interaction)
5. **intraday reversal 真实 alpha 但太弱不能 standalone** (alt-A Phase 3 verdict; 仅 25%/8yr vs SPY 156%)

**ML 可能解锁的 axis**:
- (a) **非线性 factor interaction**: linear composite 找不到的 "X 高且 Y 低且 Z 中位" 这种 conditional alpha
- (b) **Multi-horizon ensemble**: 1d / 5d / 21d / 63d 不同时间尺度的 alpha 加权
- (c) **Cross-stock attention**: 学 "在 high VIX regime 下 AAPL 跟 NVDA 的 conditional probability"
- (d) **Adaptive sizing**: 不只是选股, 而是 conditional 加仓 / 减仓 / 等待

### 2.3 ML 不能解决的问题（诚实交代）

- **78-股 universe binding**: ML 也只能在这个 universe 里搜，universe 扩张是独立工程
- **Long-only no-margin invariant**: 限制 ML 解空间 → Sharpe 理论上限存在
- **Sample size**: 8 年 × 252 天 × 50-100 股 ≈ 100-200k 样本。**深度模型临界够用，但容易过拟合**
- **Track A 17-gate guardrail**: 每个 ML model 都要过这个关，不会因为是 ML 就放松

---

## §3 Phase 1: XGBoost Return Prediction (低门槛)

### 3.1 Hypothesis

**线性 composite 找不到的 non-linear factor interaction 存在**。XGBoost 是非线性 ensemble model，理论上能 capture conditional structure。

### 3.2 Architecture

```
Input layer:
  cross-sectional rank of 162 factors per (date, stock)
  = (162-dim) feature vector per sample

Target:
  21d forward cross-sectional rank return per stock
  (1 = best returns, 0 = worst returns next 21d)

Model:
  XGBoost regression: predict rank return
  n_estimators: 100-500
  max_depth: 4-6 (shallow → less overfit)
  learning_rate: 0.03-0.1
  subsample: 0.8
  colsample_bytree: 0.7
  early_stopping on validation IC

Output:
  per-(date, stock) ML score → cross-sectional rank
  → top-N selection (top 10 stocks per rebalance)
```

### 3.3 Training discipline

- **Train**: 2009-2017 + 2020 + 2022 + 2024 (strict, per [[feedback_temporal_split_discipline]])
- **Validation**: 2018, 2019, 2021, 2023, 2025 (one-shot per fold)
- **Sealed**: 2026 (one-shot, post-forward-soak only)
- **Cross-validation**: walk-forward 4-fold on train years (no validation leak)
- **Early stopping**: on cross-sectional IC on hold-out train slice

### 3.4 Track A acceptance integration

XGBoost top-N portfolio → BacktestEngine.run() → NAV series → existing `run_split_acceptance(role="core")` 17-gate evaluator. **No new evaluator infrastructure needed**.

### 3.5 Anti-sibling check

XGBoost portfolio NAV vs RCMv1 / Cand-2 / Trial 9 v2 / cycle #09b nominee. Same threshold raw < 0.85 / residual < 0.50.

### 3.6 Deliverables

- `core/ml/xgb_alpha.py` — model definition + train/predict
- `core/ml/feature_panel_builder.py` — 162-factor → cross-sectional rank panel
- `scripts/run_xgb_alpha_mining.py` — train + predict + BacktestEngine + Track A
- `tests/unit/ml/` — 15-20 unit tests
- `docs/memos/2026MMDD-xgb_alpha_phase_1_closeout.md` — verdict

### 3.7 Engineering estimate

| Step | 工时 |
|---|---|
| Panel builder + ranking infra | 0.5 day |
| XGBoost training loop + CV | 1 day |
| BT integration + Track A wiring | 0.5 day |
| Tests | 0.5 day |
| Train 4-fold + Track A + closeout | 0.5 day |
| **Total** | **3 days** |

### 3.8 Fire trigger

- cycle #09b verdict 出来后启动（不阻塞）
- 用户 explicit-go

### 3.9 Abort condition (pre-committed)

- Phase 1 XGBoost 8-yr vs SPY excess < cycle04-08 linear baseline excess → ML 不优于 linear → **暂停 Phase 2+**
- Track A FAIL on the XGB nominee → 跟 cycle04-08 / alt-A 相同处理（candidate-level fail, but ML approach still viable for diversifier-role with anti-sibling 验证）

---

## §4 Phase 2: Multi-horizon Regression (中级)

### 4.1 Hypothesis

不同时间尺度（1d / 5d / 21d / 63d / 252d）有不同 alpha 特性。Phase 1 单 21d 目标限制了模型学到的 alpha 结构。Multi-horizon model 学**每个时间尺度的 alpha 强度 + 它们之间的 conditional relationship**。

### 4.2 Architecture

```
Input: 162-factor cross-sectional rank panel (same as Phase 1)

Model: Multi-output XGBoost OR shared-trunk neural network
  - 5 output heads: rank_return_1d, _5d, _21d, _63d, _252d
  - Shared bottom layers, separate head per horizon
  - Joint loss: weighted sum of per-horizon RankIC loss

Output:
  per-(date, stock, horizon) ML score → ensemble:
  final_score = w1 * score_1d + w5 * score_5d + ...
  (w_i learned via Track A acceptance over validation)
```

### 4.3 Why multi-horizon

- 1d / 5d 信号 = intraday mean-reversion + short-term momentum
- 21d / 63d = standard medium-term momentum / value
- 252d = long-term reversion / fundamental
- **Linear composite 不能 jointly optimize 多 horizon → 学不到** "1d signal weak but 21d strong → trust 21d" 这种 conditional

### 4.4 Deliverables

- `core/ml/multi_horizon_model.py`
- multi-horizon CV harness (extends Phase 1)
- ensemble weight optimizer
- Track A walking per horizon weight selection (carefully avoid validation overfit)
- closeout memo

### 4.5 Engineering estimate

| Step | 工时 |
|---|---|
| Multi-horizon dataset builder | 1 day |
| Multi-output XGBoost (skl interface) | 1 day |
| Or neural variant (shared trunk + 5 heads) | 2 days |
| Horizon weight optimization | 1 day |
| Track A + closeout | 1 day |
| **Total** | **6-7 days** |

### 4.6 Fire trigger

- Phase 1 XGBoost 显著超过线性 baseline
- 用户 explicit-go

### 4.7 Abort condition

- Multi-horizon ensemble 没有显著超过 single-21d Phase 1 → 时间尺度差异化不存在 → 不推进 Phase 3

---

## §5 Phase 3: Cross-sectional Transformer (高级)

### 5.1 Hypothesis

Phase 1+2 都是 per-stock independent prediction (model 不知道其他股票). 实际上 stocks 之间有 conditional relationship:
- VIX 高时, AAPL 跟 NVDA 同向 outperform low-beta defensive 股票
- 板块旋转: 当 TLT 上涨, 利率敏感型 stocks 反应不同

Cross-sectional Transformer 用 attention 学 stock-stock conditional pattern.

### 5.2 Architecture

```
Input:
  Per-date matrix (N_stocks × 162-factor features)
  Optionally augment with regime indicators (VIX, SPY trend, sector)

Model:
  TabTransformer-style: factor embedding + multi-head self-attention across stocks
  - Embedding dim: 32-64
  - n_heads: 4-8
  - n_layers: 2-4
  - Dropout: 0.2-0.3

Loss:
  Listwise rank loss across stocks per date
  (treats each date as a ranking problem)

Output:
  Per-(date, stock) ML score (incorporates other-stock-conditional info)
```

### 5.3 Why cross-sectional Transformer

- Linear composite 不知道 "AAPL high mom_252d 但 NVDA 也 high → 二者 likely correlated, hedge bet by spreading weight"
- XGBoost (Phase 1/2) 是 per-stock independent → 同样限制
- Transformer 通过 attention 在 date 维度上学 conditional rank

### 5.4 数据规模 sanity check

- 8-yr train × 252 days = 2016 train dates
- 53-100 stocks per date
- 162-dim features per stock per date
- ~32k samples (date-level) × 53-100 stock embeddings each

**Modest 数据量, 但 Transformer 在 financial setting 已经有实证 ~2010 paper 起**.

### 5.5 Anti-overfit measures

- Heavy dropout (0.3+) + weight decay
- Bayesian optimization of hyperparameters via Optuna (~50-100 trials)
- Cross-validation on rolling 1-year windows (not random fold)
- Lottery-ticket pruning if model > 10M params (PQS 数据不支持那么大)

### 5.6 Engineering estimate

| Step | 工时 |
|---|---|
| Cross-sectional dataset builder | 1 day |
| TabTransformer 实现 (PyTorch or JAX) | 4 days |
| 训练 loop + early-stopping + checkpoint | 1 day |
| Track A 集成 + 评估 harness | 1 day |
| Walk-forward training (5 folds × 1 hr each) | 1 day |
| Closeout + Track A verdict | 1 day |
| **Total** | **9 days (~2 weeks)** |

### 5.7 Fire trigger

- Phase 2 multi-horizon 表现超过 Phase 1 single-horizon
- 用户 explicit-go (Phase 3 是 PQS 第一次 deep learning，需要 directional commitment)

### 5.8 Abort condition

- Transformer training collapses (loss NaN, sharpe < 0 walk-forward) → revert to Phase 2 + reassess
- Transformer Sharpe 不超过 Phase 2 → attention 没 add value → 撤回 Phase 2

---

## §6 Phase 4: Reinforcement Learning Position Sizing (战略级)

### 6.1 Hypothesis

Phase 1-3 都是 factor side (选股). Phase 4 处理 portfolio side (位置 / 加仓 / 减仓 / 现金 / 等待).

PQS 当前 portfolio 是 simple top-N equal-weight. RL agent 可以学:
- "在 VIX > 30 时，把 top-N 减到 5, 加 cash anchor 0.5"
- "drawdown > -10% 时, 暂停 rebalance + 等 7 天"
- "regime shift 检测到 → 重 sizing"

### 6.2 Architecture

```
State (observation):
  - Current portfolio weights (per stock)
  - Per-stock ML alpha score (from Phase 1/2/3)
  - Regime indicators (VIX, SPY trend, sector)
  - Recent NAV trajectory (last 21d returns)

Action space:
  - Discrete: {hold, rebalance, partial-hedge, full-cash}
  - Continuous (alternative): per-stock weight adjustment

Reward:
  Sharpe-after-cost over forward 21d window
  - Penalty for excessive turnover
  - Bonus for drawdown avoidance

Algorithm:
  PPO or DDPG (continuous-action) — both proven in finance RL papers
  Replay buffer: 1-3 yr historical
```

### 6.3 Anti-overfit + reproducibility

- Episode = 21 trading days. Train on multiple non-overlapping episodes.
- Walk-forward validation: train on past windows, test on next.
- Ensemble: train 5-10 agents with different seeds, take mean action.

### 6.4 Engineering estimate

| Step | 工时 |
|---|---|
| RL environment (gym wrapper around BT) | 5 days |
| State representation + reward shaping | 3 days |
| PPO/DDPG implementation + tune | 7 days |
| Training infrastructure (multi-GPU OR multi-core CPU) | 3 days |
| Walk-forward evaluation + Track A | 3 days |
| Closeout + verdict | 1 day |
| **Total** | **22 days (~4 weeks)** |

### 6.5 Fire trigger

- Phase 3 Transformer 表现超过 Phase 2
- ML mining demonstrated > linear baseline alpha
- 用户 explicit-go (Phase 4 是 PQS 第一次 RL，需要 commit infra + time investment)

### 6.6 Abort condition

- RL training divergence (policy collapse, reward NaN) → revert to Phase 3 best agent
- RL doesn't improve over Phase 3 + greedy rebalance → action space too constrained → 停 Phase 4

---

## §7 Common Infrastructure

### 7.1 panel construction

`core/ml/feature_panel_builder.py`:
- 加载 162 RESEARCH_FACTORS (existing factor_generator + Bucket B/C/Macro/Event/Signal-conf compute paths)
- Cross-sectional rank per (date) — normalize to [0, 1]
- Forward-fill missing (≤ 5 days) + drop rows with > 5 days missing
- Save per-date snapshot to parquet for caching

### 7.2 Target labeling

`core/ml/target_labels.py`:
- `compute_forward_rank_return(close_panel, horizon=21)` —
  cross-sectional rank of forward 21d return
- Multi-horizon variant for Phase 2

### 7.3 Train/val/sealed discipline

Reuse existing `core/research/temporal_split.py` + `temporal_split.yaml`:
- Train years: 2009-2017 + 2020 + 2022 + 2024
- Validation years: 2018, 2019, 2021, 2023, 2025
- Sealed: 2026

**所有 ML phase 共用同一 split**. Sealed 一次性, 全 ML phase 之间也是一次性 (用过就 burnt).

### 7.4 Reproducibility

- Random seed pinned per training run
- Model checkpoints saved with sha256 of training config yaml
- TensorBoard / Weights & Biases logging optional

### 7.5 Track A acceptance integration

Each ML phase:
1. Train model on train years
2. Predict on validation years → top-N portfolio per rebalance
3. Run BacktestEngine.run() → NAV
4. Pass NAV to `run_split_acceptance(role="core")` 17-gate
5. **Sealed 2026 reserve** until forward-soak healthy

### 7.6 Anti-sibling check

For each ML candidate that passes Track A:
- Compare NAV vs RCMv1 / Cand-2 / Trial 9 v2 / (cycle #09b nominee if exists)
- Same threshold: raw < 0.85, residual < 0.50
- Use `dev/scripts/alt_a/run_alt_a_nav_correlation.py` pattern

### 7.7 Model versioning

`data/ml_models/<phase>/<version>/model.pkl` + `config.yaml` + `train_metrics.json`. sha256-locked.

---

## §8 Pre-committed Stop Rules

### 8.1 Per-phase abort

Each Phase has its own abort condition (§3.9 / §4.7 / §5.8 / §6.6).

### 8.2 Cross-phase stop rule

**If Phase 1 + Phase 2 both fail to超 cycle04-08 linear baseline by > 30% (Sharpe)**:
- Conclusion: PQS 数据 / universe 不适合 ML mining
- Pivot: focus on **universe expansion** (78 → 200+ stocks) OR **alternative alpha sources** (event-driven, news, options surface)
- 不强推 Phase 3+

### 8.3 Sample size monitor

Each phase reports actual sample count + per-sample noise level. If model parameters > 5× sample count → flag overfit risk + skip to next phase.

### 8.4 Forward observation gate

Any ML nominee that passes Track A + anti-sibling → must complete TD60 forward-soak before sealed 2026 eval. Sealed is single-shot.

---

## §9 Open Directional Questions

1. **Phase 1 启动时机**:
   - (a) cycle #09b verdict 出来后立即启动？
   - (b) 等 Trial 9 v2 TD60 verdict (~2026-08-06) 之后再启动？
   - (c) 现在就启动并行 with cycle #09b smoke？

2. **第一个 ML 实验范围**:
   - (a) 仅 162-factor → 21d return (最小, Phase 1 完整 scope)
   - (b) 加 sector + macro indicator (162 + ~10 regime features)
   - (c) 加 60m intraday feature (162 + alt-A inputs) — 拓展但增 overfit 风险

3. **抽样规模**:
   - (a) 78-股 cycle04+ universe (consistent with cycle04-08)
   - (b) 53-股 alt-A universe (smaller, cleaner stocks-only)
   - (c) 100+ 股 universe expansion (preserves more samples but needs 1m bar coverage validation)

4. **Track A guardrail strictness**:
   - (a) 跟 cycle04-08 / alt-A 一样 17-gate hard (推荐)
   - (b) 给 ML 一个 leniency (validation vs SPY 3/5 vs 4/5)
   - 不推荐 (b) — overfit 反过来咬手

5. **Sealed 2026 panel 共享方式**:
   - (a) Phase 1 用完之后不再给 Phase 2 用 (single-shot per ML phase, conservative)
   - (b) 全 ML phase 共享 sealed (any ML 用过, 整个 ML 通道 sealed)
   - 推荐 (b) — sealed 是 PQS 整体一次性资源, 不是 per-experiment

6. **Engineering 主导 vs 渐进**:
   - (a) 一次性 ship Phase 1 + 2 + 3 共享 infra (~3 周)
   - (b) Phase 1 ship 完 + verdict → 决定 Phase 2 (~推荐)

---

## §10 Authorization

- **Phase 1 fire**: 需要 user explicit-go + cycle #09b verdict (smoke OR full result)
- **Phase 2-4**: 各自 fire 需要前 phase pass abort condition + user explicit-go
- **No auto-escalation**: 每个 phase 独立, 不预先承诺全部做

---

## §11 Predecessors + Authority

PQS 已有 ML-adjacent 基础设施 (供 Phase 1 复用):
- `scripts/run_xgb_importance.py` — XGBoost 训练 + importance score
- `core/diagnostics/detectors.py` — SHAP integration
- `core/factors/factor_generator.py` — 162-factor library
- `core/research/temporal_split.py` — train/val/sealed
- `core/research/temporal_split_acceptance.py` — Track A 17-gate
- `core/backtest/backtest_engine.py` — Phase 2 D2 加了 execution_freq kwarg
- `core/backtest/intraday_reversal_bridge.py` — alt-A pattern (信号 → signals_df → BT)

Phase 1 实施可以**最大化复用现有 infrastructure** — XGBoost 部分只需替换 importance → regression target.

---

*End of ML mining pipeline PRD. Pending user directional decisions in §9 + cycle #09b verdict.*
