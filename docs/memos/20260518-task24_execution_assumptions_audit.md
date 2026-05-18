# task#24 — 执行层假设 vs 文献 audit(websearch fuzzy→primary)

**日期**: 2026-05-18
**触发**: 用户 2026-05-18 "websearch 执行层策略/经验,看我们 fill/
成本假设是否合理"。
**关系**: **接 grand-audit A4 finding(不重做)**——A4 已定性成本
模型 NAIVE-GAP 但"小 AUM 大体 justified、scale-gated";本 audit
深挖 + primary 文献坐实 + 给 scale-gated 处置。
**纪律**: `[[feedback_websearch_fuzzy_to_primary_depth]]`(fuzzy→
primary)+ `[[feedback_websearch_sealed_data_discipline]]`(只查
方法论非市场数据,合规)+ `[[feedback_no_blanket_failure_verdict]]`
+ 按项目 $10K→$100K + long-only 不变量判合理与否。

---

## §1 实查:我们真实的执行假设(R3,非记忆)

- **成交点**:`execution_simulator` 日线级,**信号 T → 成交 T+1
  调整后开盘价 ± 固定 slippage**(无 size/ADV 依赖)。
- **成本**:`CostModelConfig` `mode=bps_based` —— per-symbol-tier
  的 `commission_bps + slippage_interday/intraday_bps`(常数 bps);
  **VIX≥30 → ×2.5 binary cliff**(`vix_stress_threshold=30`,
  `stress_slippage_multiplier=2.5`)。
- **`CapacityModelConfig`(`impact_bps_per_100k=1.0`)schema 存在但
  dead**(A4 实证:`get_total_cost_bps` 不读它)。
- 项目**有 2x/3x 成本 robustness gate**(CLAUDE.md)。

## §2 primary 文献(fuzzy→真关键词→原文)

- **市场冲击平方根律**:metaorder 大小 Q 的冲击 ∝ **√(Q/ADV)**,
  "surprisingly universal"(资产类/时段/执行风格无关)。primary =
  Tóth et al. 2011(arXiv 1105.1694)/ Almgren et al. 2005 / Bouchaud
  学派。
- **linear→sqrt crossover**:**小 order size 下冲击是 LINEAR**,
  √ 区间在更大 participation 才启动(Bucci et al., hal-02323405 /
  arXiv 1811.05230);更大尺度 log 拟合更好(Bucci/Bouchaud)。
- **固定 slippage = 公认 anti-pattern**;SOTA = variable
  (size/volume/spread);realistic slippage 削 0.5-3%/yr。

## §3 对照表(我们 ↔ 文献 SOTA ↔ 当前 AUM 合理? ↔ scale-gated)

| 假设 | 文献 SOTA | 当前 $10K-100K 合理? | scale-gated 风险 |
|---|---|---|---|
| 成交 = T+1 调整开盘 ± 固定 | T+1-open 是保守 no-lookahead 惯例(vs VWAP/close) | **合理**(保守,非 gap) | 无 |
| slippage = 常数 tier bps | variable / √-law | **合理且保守**:$10K-100K 在 SPY/大盘/流动 ETF 上 participation≈0% ADV → 落 **linear 微区间**,固定小 bps **≥ 真实冲击**(crossover 文献直接支持) | **真 gap @ $100K+ + 偏薄票**:无 size/ADV/√ 冲击 |
| VIX≥30 ×2.5 binary | 连续 spread~vol | 小 AUM 影响小,但 **binary 比连续粗**(真软点) | 偏薄票时更明显;便宜可改连续 |
| CapacityModelConfig dead | √-law 该住这 | 当前 AUM 不 binding | **latent foot-gun @ scale**:未接线;且 schema 是 linear 项,比 √-law 弱 |
| 2x/3x 成本 stress gate | 低 AUM 结构模型的合理替代 | **加分**(文献认可的小 AUM 替代) | scale 时 stress 不能完全替结构模型 |

## §4 verdict(诚实,no-blanket,按不变量)

**执行/成本假设在当前 $10K-$100K AUM 下 = 合理且保守**:
participation≈0 → linear 微区间 → 固定 bps ≥ 真实冲击;T+1-open
保守;2x/3x 成本 stress 替代结构模型(文献认可)。**不是"执行坏了"
——A4 + 本 audit + primary 三方一致:adequate at tiny AUM。**

**真正软点全部 scale-gated(精确点名,不夸)**:(a) 固定 bps 无
size/ADV/√ 冲击;(b) VIX binary cliff 粗于连续;(c) CapacityModelConfig
dead 且其 linear 项弱于 √-law。

## §5 处置(scale-gated,非现在改)

- **现在不改**:当前 AUM 下 invariant-justified;改了是 over-engineer
  无收益(A4 同结论)。
- **推向 $100K+ / 引入非 SPY-非大盘票 之前**(触发条件):
  (1) 接线 `CapacityModelConfig` 并**升级为 √-law 冲击**(Tóth/
  Almgren,participation-aware),不止 schema 的 linear 项;
  (2) VIX→成本改**连续**(spread~vol)替 binary cliff;
  (3) 加测试断言 capacity model 在 $100K target 下激活(防 dead
  config foot-gun 复发)。
- 记为 scale-gated to-do(非 operator 单方现在启;触发=AUM/universe
  扩张决策)。

## §6 来源(均方法论/微结构,非市场数据)
- Tóth et al. 2011, anomalous price impact / √-law — arXiv 1105.1694
- Almgren, Thum, Hauptmann, Li 2005, equity market impact — (Almgren √-law)
- Bucci et al., linear→√ crossover — hal-02323405 / arXiv 1811.05230
- (执行 best-practice 综述:固定 slippage anti-pattern / variable model)
