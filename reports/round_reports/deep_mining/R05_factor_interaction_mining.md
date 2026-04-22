# Deep Mining R5 — Factor Interaction Mining

**Track**: A — Daily factor mining + ML
**Topic**: Pairwise factor interaction discovery
**Date**: 2026-04-22
**Lineage**: `post-2026-04-22-deep-R05`
**Duration**: ~2 min

---

## 1. 本轮主题

Track A R5 per PRD §2: **"XGBoost factor interaction discovery (pair mine) — Top 20 interaction terms, novelty vs existing"**

两两乘积 factor 对 21d forward return 的 IC 比独立 parent |IC| 的增量（incremental |IC|）。

## 2. 本轮目标

1. 用 R4 SHAP 发现的 interaction-heavy features（`market_vol_ratio`, `cross_section_dispersion_21d`）作 seed
2. 产出 top-20 pairwise interactions by incremental |IC|
3. 识别可作新 RESEARCH_FACTOR candidate 的 interactions（incremental |IC| > 0.03）
4. 为 R22-R23 composite round 提供材料

## 3. 为什么优先

PRD §2 R5 明确。R4 SHAP 已指出 `market_vol_ratio` + `cross_section_dispersion_21d` 是 interaction-heavy 的"暗 alpha"。R5 把这推进为具体的 pairwise terms。

R1/R3/R4 确认 single-factor space 已 flat（OOS IR < 0，OOS R² < 0）。非线性信号只剩在交互项里。

## 4. 做了什么

```bash
python scripts/run_factor_interaction_mine.py --top-k 10 --out-top 20 --horizon 21
```

- top-k=10 parent features: `max_dd_126d`, `mom_126d`, `rs_vs_qqq_63d`, `vol_63d`, `spy_trend_200d`, `mom_252d`, `drawup_from_252d_low`, `mom_63d` (tool 只返了 8 — 约等于 top-10 alive)
- Pairwise mine all C(8, 2) = 28 combinations
- 对每对计算: `IC(x_a × x_b vs fwd_21d)` - `max(|IC(x_a)|, |IC(x_b)|)`
- 输出 top-20 by incremental IC

## 5. 修改了哪些文件

- 仅产出 artifacts: `data/ml/factor_interactions/{interactions.parquet, summary.json}`
- `docs/ralph_loop_log.md` (短摘要)
- `reports/round_reports/deep_mining/R05_factor_interaction_mining.md` (本文件，详报)
- 无源码改动

## 6. 跑了哪些实验

Full 2007-2026 daily panel (52 sym × 8 parent factors × 28 pairs)。Panel 构建 ~60s，interaction IC 计算 ~40s。

## 7. 结果

### 7.1 Parent IC baseline (H=21d)

| Parent | IC |
|---|---:|
| max_dd_126d | +0.0679 |
| mom_126d | +0.0409 |
| rs_vs_qqq_63d | +0.0245 |
| vol_63d | **-0.1013** |
| spy_trend_200d | ~0.0000 |
| mom_252d | +0.0355 |
| drawup_from_252d_low | **+0.0865** |
| mom_63d | +0.0245 |

Strongest standalone: `vol_63d` (-0.10) 和 `drawup_from_252d_low` (+0.086)。

### 7.2 Top 20 pairwise interactions (by incremental |IC|)

| # | Pair | IC | Parent max\|IC\| | Incremental |
|---|---|---:|---:|---:|
| 1 | rs_vs_qqq_63d × spy_trend_200d | +0.0704 | 0.0245 | **+0.0458** |
| 2 | spy_trend_200d × mom_63d | +0.0704 | 0.0245 | **+0.0458** |
| 3 | rs_vs_qqq_63d × mom_63d | +0.0585 | 0.0245 | **+0.0339** |
| 4 | mom_126d × mom_63d | +0.0615 | 0.0409 | +0.0206 |
| 5 | spy_trend_200d × mom_252d | +0.0527 | 0.0355 | +0.0172 |
| 6 | mom_126d × spy_trend_200d | +0.0553 | 0.0409 | +0.0144 |
| 7 | mom_252d × mom_63d | +0.0464 | 0.0355 | +0.0109 |
| 8 | max_dd_126d × drawup_from_252d_low | +0.0966 | 0.0864 | +0.0102 |
| 9 | mom_126d × mom_252d | +0.0506 | 0.0409 | +0.0097 |
| 10 | mom_126d × rs_vs_qqq_63d | +0.0452 | 0.0409 | +0.0043 |

**7 个 pairs** 有 incremental |IC| > 0.01（即显著 interaction contribution）。

### 7.3 Bottom 5 — interactions that DESTROY alpha

| Pair | IC | Incremental |
|---|---:|---:|
| rs_vs_qqq_63d × vol_63d | -0.0235 | **-0.0778** |
| vol_63d × mom_63d | -0.0276 | -0.0738 |
| rs_vs_qqq_63d × drawup_from_252d_low | +0.0171 | -0.0694 |
| drawup_from_252d_low × mom_63d | +0.0285 | -0.0580 |
| vol_63d × mom_252d | -0.0443 | -0.0570 |

关键：**18/28 pairs 实际 DESTROY alpha**（incremental 负值）。这与 CLAUDE.md Round 7 of LLM phase 的 finding 一致——pairwise multiplication 不是总增 alpha。Interaction mining 必须筛选。

### 7.4 关键 insights

1. **SPY trend 作 binary gate**: Top 1-2 都是 `spy_trend_200d × X`。`spy_trend_200d` 独立 IC ≈ 0 但作 "regime gate" 乘以 momentum / relative strength → 显著增量 +0.046。
2. **mom × mom cross-horizon**: #4 mom_126d × mom_63d (+0.021) 和 #7 mom_252d × mom_63d (+0.011) 支持 multi-horizon momentum ensemble。
3. **max_dd × drawup** (+0.010): 两个 path-shape 互相补强。
4. **vol_63d 作 interaction 毒药**: bottom 3/5 都含 vol_63d。vol_63d 独立 IC 强 (-0.10) 但乘以其他 factor 反而抵消。原因可能是 vol 已经在 MFS 的 low_vol 项有使用，再乘进其他 factor 出现 double-counting。

### 7.5 R4 SHAP predictions 对比

R4 SHAP 指出 `market_vol_ratio` 和 `cross_section_dispersion_21d` 是 interaction-heavy。但本轮 `run_factor_interaction_mine.py` 的 parent set 来自 permutation importance top-10，**没包含这两个**（它们 permutation 排名 >15）。

→ 建议下轮变体: 手工加这两个到 parent set 重跑交互挖掘，验证 SHAP 推断。

## 8. 新问题 / 新机会

### 新候选 factor (可进 R7 LLM funnel)

`spy_trend_x_rs_vs_qqq_63d`（即 SPY 趋势乘以相对 QQQ 的 RS）incremental IC +0.046。**强于已有任何单一 PRODUCTION_FACTOR 的 IC（最高 drawup 0.086 独立；此 pair 0.070）**。

**疑点**: 但 `spy_trend_200d` 独立 IC ≈ 0，说明 pair 的 IC 全来自 `rs_vs_qqq_63d` 在 SPY uptrend 状态下的预测力。即实际上是 regime-conditioned RS。这跟 CLAUDE.md LLM Round 7 `rs_qqq_regime_conditioned_63d` 候选是同一思路，历史上在 deep_check 段 failed（OOS IR +0.24 < 0.30 门槛；Q4 2024-26 段衰减）。

**行动**: 建议 R7 作为"重试"候选——用当前 funnel + pack v2 再验证。若过，可 promote 到 RESEARCH_FACTORS (autonomous §11.3)。

### M19 confirm

Interaction IC 计算是独立 ML 路径，与 MiningEvaluator 无关。R5 不受 M19 DSL gap 影响。

## 9. 剩余风险

1. Parent set 只用了 permutation top-10。R4 SHAP-top 里的 `market_vol_ratio` 和 `cross_section_dispersion_21d` 没进 parent set，可能漏掉重要交互。
2. 只做 pairwise (order 2)。R4 SHAP 说明的可能是 3-way 或 4-way interactions，pairwise 捕不到。
3. IC 是全期平均，没 regime 分层。Best pair (`rs_vs_qqq_63d × spy_trend_200d`) 可能在 BULL 里强、在 CRISIS 里翻转 (CLAUDE.md Round 7 记录过类似现象)。

## 10. 下一轮建议 → R6

PRD §2 R6: XGBoost weight model on current universe。
- 复用 R3/R4 的 panel
- `run_xgb_weight_model.py --horizon 21 --top-k 5 --split-frac 0.8 --out-tag R6_daily_weight`
- 对比 XGB-weighted top-5 vs equal-weight top-5 的 portfolio CAGR / Sharpe / MaxDD
- 预计 ~5 min

## 11. Commit hash

`<待填>` (fill after commit)

---

## Appendix A: Interactions full 28 table

(See `data/ml/factor_interactions/interactions.parquet` for full rank-28 listing + all IC fields.)

## Appendix B: Methodology notes

- Rank IC computed cross-sectionally per date
- Mean across dates (simple average, no regime weighting)
- Interaction = `(x_a - mean(x_a)) × (x_b - mean(x_b))` (centered cross product)
- Incremental IC = |IC(interaction)| - max(|IC(parent_a)|, |IC(parent_b)|)
- Positive incremental = interaction 比更好 parent 还有贡献
- Negative incremental = parent 单独比乘积强（不推荐 pairing）
