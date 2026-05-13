# Z1 Factor Diagnostics — STRICT TRAIN-ONLY (corrected)

**Date**: 2026-05-12
**Status**: 严格遵守 train/validation/sealed 分离 — 验证年 (2018/2019/2021/2023/2025) 和 sealed (2026) 完全没碰
**Lineage**: `track-c-cycle-2026-XX-XX-09-prep-strict`
**Supersedes**: `20260512-z1_factor_diagnostics_synthesis.md`（错误的混合版本）

---

## TL;DR — 人话版

我之前犯了**一个方法论错误**：第一版 Z1 用了 2014-2024 的混合数据跑因子排名，里头包了 validation 年份（2018/2019/2021/2023/2025）。

**这是错的** — 即使我说"只是 diagnostic ranking 不是 acceptance"，因为 ranking 结果会影响 cycle #09 选哪个因子做 anchor，**等于隐性消耗了 validation OOS 真实性**。

修正后**严格只用 train years**（2009-2017 + 2020 + 2022 + 2024）重新跑 IC table。结果验证了"数据消耗有真实危害"这个论断 —— 严格 train-only 的因子排名跟混合数据的排名**显著不同**，有些因子的方向甚至反转。

---

## §1 方法学（严格 OOS 分离）

| 数据集 | 年份 | 怎么用 |
|---|---|---|
| **Train (训练)** | 2009-2017 + 2020 + 2022 + 2024 | ✅ 这次 Z1 IC 计算用 |
| **Validation (验证)** | 2018, 2019, 2021, 2023, 2025 | ❌ **绝对不读** |
| **Sealed (封存 OOS)** | 2026 | ❌ **绝对不读 — 一次性资源** |

计算细节：
- IC = Information Coefficient = 每天对所有股票按因子打分排队，跟未来 21 天涨跌做 Spearman 相关。0 = 无用，越大越准。**这次只在 train 日历上计算**。
- IR = Information Ratio = mean_IC / std_IC × √252（年化）。**IR > 2 通常算"质量很好"**；IR > 3 是"罕见好"；IR > 4 几乎是 model fit 嫌疑。
- 总 train 交易日：3131 天（占 2009-2024 全期 75%）
- 154 个因子里 135 个产生 valid IC

---

## §2 严格 train-only 的 TOP 20 因子（这是真正可信赖的 ranking）

| 排名 | 因子名 | Family | Mean IC | **IR** | 通俗解释 |
|---|---|---|---|---|---|
| 1 | beneish_aqi | L (distress) | -0.089 | **-5.83** | Beneish 资产质量指数恶化 → 未来反而涨（mean reversion）|
| 2 | sales_acceleration | N (growth) | -0.071 | **-5.16** | 营收增长**加速** → 未来反而跌（增长拐点 = 见顶信号）|
| 3 | piotroski_no_dilution | K (quality) | -0.069 | **-4.67** | 不发股票（看似好）→ 未来反而跌（可能是错误信号）|
| 4 | rd_intensity_ttm | N (growth) | +0.096 | **+4.64** | R&D 强度高 → 未来涨（创新型公司持续 outperform）|
| 5 | mom_126d / rs_vs_spy_126d | A (legacy) | +0.084 | +4.38 | 6 个月动量 — 经典动量因子 |
| 6 | altman_ebit_to_assets | L | -0.056 | **-4.29** | EBIT / 资产高（看似好）→ 未来反而跌 |
| 7 | spy_trend_gated_mom_63d | A | +0.078 | +4.23 | SPY 上升趋势期间的动量 |
| 8 | magic_roic_ttm | K | -0.053 | **-4.08** | ROIC 高 → 未来反而跌（拥挤交易）|
| 9 | sector_dispersion_std_20d | O (sector) | +0.081 | **+4.03** | 板块内股票分化大 → 未来涨（alpha 机会多）|
| 10 | ohlson_nitwo | L | +0.069 | +3.99 | Ohlson 连续两年亏损标志 — 困境反转候选 |
| 11 | drawup_from_252d_low | B (legacy) | +0.074 | +3.99 | 距 252 天低点的反弹幅度（已知 cycle04-08 anchor）|
| 12 | piotroski_current_ratio_yoy_improving | K | +0.050 | +3.79 | 流动比率改善 — 财务健康度提升 |
| 13 | beneish_depi | L | -0.054 | -3.74 | Beneish 折旧率指标 |
| 14 | altman_sales_to_assets | L | +0.052 | +3.69 | 营收 / 资产（周转率）|
| 15 | buyback_yield_ttm | M | -0.049 | **-3.65** | 回购收益率高 → 未来反而跌（拥挤交易典型反转）|

**粗体 = PRD 20260512 新加的 factor**（11 / 15 是新的）

---

## §3 重要发现：严格 train vs 混合数据 → 排名差别很大

| 因子 | 混合 train+val IR | **严格 train only IR** | 差距 |
|---|---|---|---|
| beneish_aqi | n/a (不在 top 20) | **-5.83** ⭐ 新 #1 | 完全没注意到 |
| sales_acceleration | n/a | **-5.16** ⭐ 新 #2 | 完全没注意到 |
| rd_intensity_ttm | +4.86 (#1) | **+4.64** (#4) | 排名降，符号一致 |
| sector_dispersion_std_20d | +4.11 (#2) | **+4.03** (#9) | 一致 |
| ohlson_wc_to_ta | +3.99 (#3) | +3.24 (#20+) | 显著下降 |
| **magic_roic_ttm** | +3.97 正 | **-4.08 负** ⚠️ | **方向反转！** |
| fcf_yield_ttm | +3.87 (#6) | (掉出 top 20) | 显著下降 |

**这是为什么严格 OOS 分离方法论重要**：用混合数据评估 factor，validation 年份的市场状态会污染排名。`magic_roic_ttm` 在混合数据上看着是正向 alpha，严格 train-only 反而是负向（meaning ROIC 高的股票未来反而 underperform，可能是 crowded-trade 反转）。

如果我按错误的混合 ranking 选 cycle #09 anchor，结果会跟 train-only sample 的真实预期反着来。

---

## §4 cycle #09 archetype（修正版）

基于严格 train-only ranking，cycle #09 应该 anchor 这三个独立维度：

### Archetype A "三维强 alpha"（我推荐这个）
1. **rd_intensity_ttm** (IR +4.64) — R&D 强度，growth 方向
2. **sales_acceleration** (IR -5.16, **反向用**) — 营收加速度，反转方向
3. **beneish_aqi** (IR -5.83, **反向用**) — 资产质量恶化（用反向 = 资产质量好 → 涨）

**为什么这三个一起好**：
- 三个分别属于 N family (growth) / N family (growth-momentum) / L family (distress) — 同 K family 但风格各异
- 跟 cycle04-08 的 drawup + amihud anchor archetype **完全无重叠**
- 反向用 sales_acceleration 和 beneish_aqi 是 "mean reversion in growth/quality" 故事，跟 momentum 反着走
- 全是 fundamental 数据驱动（不像 cycle04-08 全靠价格 path-shape）

### Archetype B "经典动量 + 板块分化"（备选）
- mom_126d (IR +4.38) — 6 个月动量
- sector_dispersion_std_20d (IR +4.03) — 板块分化度
- spy_trend_gated_mom_63d (IR +4.23) — SPY 趋势条件下的 3 个月动量

### Archetype C "困境反转主题"（深度备选）
- ohlson_nitwo (IR +3.99) — 连续两年亏损（candidates for turnaround）
- piotroski_current_ratio_yoy_improving (IR +3.79) — 流动性改善
- buyback_yield_ttm (IR -3.65, **反向用**) — 没回购的反而涨

---

## §5 cluster 发现（masked duplicates）

train-only 上发现 159 个 |r| ≥ 0.7 的高相关对（比混合数据 140 个更多 — 因为 train 集中更长，因子稳定性更显眼）。

**真正同公式的"假名字"对**：
- ret_5d ↔ reversal_5d：r = -1.00 — 完全符号反转
- dist_52w_high ↔ nearness_to_52w_high：r = +1.00 — 同公式不同名
- volume_surge_20d ↔ volume_ratio_20d：r = +1.00 — 历史 alias
- **beneish_sgi ↔ revenue_growth_yoy**：r = +1.00 — 我自己的 dupe（应该删一个）
- **altman_wc_to_assets ↔ ohlson_wc_to_ta**：r = +1.00 — 我自己的 dupe（同公式不同 family）
- mom_21d ↔ reversal_21d：r = -1.00 — 完全反转

**后续 action**: cycle #09 mining 应该把这些当作"同因子"处理 — 否则 mining 可能在同个 composite 里 sample 两个本质相同的因子，violation `max_per_family=2` 的精神。

---

## §6 IR > 5 是不是太高？— 警告

beneish_aqi IR = -5.83 和 sales_acceleration IR = -5.16 都偏高得不寻常。

**可能解释**:
1. **可能是真的**：fundamental factor 在 train years 上确实有强 alpha（财务数据 yoy 周期性强）
2. **可能是 train sample bias**：train years 2009-2017 + 2020 + 2022 + 2024 这个组合（不是连续 16 年，而是 12 年挑出来的）可能产生 spurious 高 IR
3. **可能是 selection bias**：30 sym × 12 yr 比传统 panel 小，cross-sectional rank 稳定性虚高

**保守解读**: cycle #09 yaml 不要单押 IR > 5 的 factor 作为 anchor。组合多个 IR ∈ [3, 5] 的 factor 比单押"超高 IR"更 robust。

---

## §7 关键操作要点（写给未来自己）

1. **任何因子排名 / 评估都严格只用 train years** — 写进所有 diagnostic 脚本默认行为
2. **validation years 只用于 Track A acceptance 那 17 项关卡** —— 用一次消耗一次（5 个 validation year × N 次 mining）
3. **Sealed year 2026 只用一次** — 真正的 OOS 测试
4. **混用 train + validation 就等于隐性消耗 OOS 信息**，即使不叫"acceptance"也算

---

## §8 输出文件

- `data/audit/factor_diagnostics_20260512_strict_train/ic_table_train_only.csv` (135 因子完整 ranking)
- `data/audit/factor_diagnostics_20260512_strict_train/cluster_pairs_train_only.csv` (159 高相关对)
- 旧的混合数据版本 `data/audit/factor_diagnostics_20260512/` 保留**仅作错误对照**，不能用于决策
