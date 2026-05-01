# Cycle #04 cross-asset PREFLIGHT — 不直接开 mining

**Date**: 2026-05-01 (晚, post cycle #03 closeout)
**Authority**: 资深 quant collaborator 2026-05-01 建议（"先做 C-4 preflight，不直接开 200 trials"）+ user 2026-05-01 explicit-go ("你自己去判断需要take的step 和需要注意的边界条件 然后可以开做")
**Trigger**: cycle #03-02 0-nominee close (`docs/memos/20260501-track_c_cycle_2026-05-01-02_close.md`)

## TL;DR

**3 个 hard blocker**：在 cycle #04 跑 mining 之前必须先决策处理：

1. **Distribution adjustment missing**: bond/cash ETF total return 系统性低 2-3 pp/yr。
2. **2015 起始 vs 2009 train**: cross-asset universe daily panel 仅 2015-01 起，Track A train 始于 2009 — **6 年缺口**。
3. **Source mix**: 7 个候选 ETF 中 4 个 (TLT/IEF/SHY/GLD) daily 来自 `yfinance_daily`，3 个 (BIL/SHV/USO) 来自 canonical pipeline → **重现 Task #49 修过的 heterogeneous-source 风险**。

**1 个 soft blocker（mining objective）**: 即使数据都修好，**full-period composite IC 这个 mining objective 在结构上偏向选 equity**，因为 bond/commodity 的价值是 regime-specific 的，full-period averaging 会稀释 crisis-only 信号。这是 collaborator §"regime allocation, not just selection" 的具体落点。

**1 个机械性正面信号**: naive {SPY, TLT, GLD} 1/3-1/3-1/3 basket 与 SPY raw Pearson = **0.545**, 与 QQQ = **0.541**（vs cycle #03 candidates 的 0.85-0.95）。**Cross-asset 机械性能突破 universe-bound NAV correlation floor**，所以方向对，只是 path 比"扩 universe + 重跑 miner"复杂得多。

## Preflight 6 个问题的答案

### 1. 7 个候选 ETF 是否有 daily panel？

| Sym | n_rows | First | Last | source_type (1d) | CAGR (price-only) |
|---|---|---|---|---|---|
| TLT | 2838 | 2015-01-02 | 2026-04-16 | **yfinance_daily** | -3.34% |
| IEF | 2791 | 2015-01-02 | 2026-04-16 | **yfinance_daily** | -0.96% |
| SHY | 2280 | 2015-01-07 | 2026-04-13 | **yfinance_daily** | -0.23% |
| GLD | 2838 | 2015-01-02 | 2026-04-16 | **yfinance_daily** | +12.71% |
| USO | 2838 | 2015-01-03 | 2026-04-17 | canonical (polygon_gz/stocks_csv) | -2.07% |
| BIL | 2838 | 2015-01-03 | 2026-04-17 | canonical | +0.00% |
| SHV | 2838 | 2015-01-03 | 2026-04-17 | canonical | +0.00% |

**全部 2015-01 起始**。Track A train range = 2009-2017+2020/2022/2024 → cross-asset universe 在 train 的 2009-2014 6 年完全没数据。

### 2. Distribution / total-return 一致性？

```
ETF   price_only_CAGR   total_return_CAGR   gap     div_total_15y
BIL   +0.00%            +1.89% (yfin TR)    -1.89   $19.23
SHV   -0.00%            +1.95%              -1.95   $24.01
TLT   -3.34%            -0.68%              -2.66   $34.78
IEF   -0.96%            +1.25%              -2.21   $25.28
GLD   +12.75%           +12.75%              0.00    $0.00
```

**Bonds + cash ETF 的真实 total return 大部分（≈100% for BIL/SHV）来自 distribution，price-only adjustment 把它们的真实 alpha 抹掉了。**

后果：在 cycle #04 IC mining 里，BIL/SHV 的 ret_5d / mom_12_1 / drawup_from_252d_low 等 price-based 因子会全部 ~0，IC 排名永远在 stocks 后面 → selector 永远不会选 bonds → cross-asset universe 名存实亡。

### 3. 2009-2025 覆盖？

**否**。2015-01 起始，覆盖率 = ~58% of Track A train range。

3 个修复选项：
- (a) Backfill 2009-2014 via yfinance long-history（1 天工程，但引入更多 yfinance vs canonical 源的混合）
- (b) Cycle #04 改 panel = 2015-2025（牺牲 2009-2014 train，损失 GFC + 欧债危机 + 2014-15 Fed taper 等关键 regime）
- (c) 部分 backfill：仅 GLD/TLT 等关键 sym backfill，SHY/BIL/SHV 接受 2015 起始

### 4. RESEARCH_FACTORS 在跨资产 sym 上能否生成？

61 个 RESEARCH_FACTORS 中：

| Sym | cov ≥ 50% factors | cov ≥ 80% factors |
|---|---|---|
| TLT | 42 | 17 |
| IEF | 42 | 14 |
| SHY | 18 | **4** |
| GLD | 42 | 17 |
| USO | 33 | 14 |
| BIL | 32 | 14 |
| SHV | 32 | 14 |

18 个因子在 ETF 上 0 数据（要 SPY-relative + research_mask + ETF 自身 lookback 都满足）。**SHY 仅 4 个因子 cov ≥ 80%** — 太薄。

### 5. cap_aware selector 加 cross-asset 是否真的会选 non-equity？

**未直接测试**，但根据 §2 + §4 推断：**不会**。
- BIL/SHV 在 price-only 下 IC 永远接近 0
- SHY 仅 4 因子可用
- TLT/IEF 价格趋势负，普通 mom/drawup 因子排名垫底

需要先解决 §2 distribution gap，selector 测试才有意义。

### 6. naive cross-asset basket 与 RCMv1 reference 的 raw Pearson 是否机械下降？

**是，显著下降**。Naive {SPY, TLT, GLD} 1/3-1/3-1/3 basket 与 SPY 的 raw Pearson = **0.545**（cycle #03 candidates 与 SPY 的 raw Pearson = 0.82-0.85）。这证明 cross-asset 方向对：**只要 basket 真的有 33%+ non-equity, NAV 与 equity benchmark 的 raw 相关会从 0.85+ 跌到 ~0.55**。

但前提是 selector 真的会选 non-equity（§5 的问题）。

## USO 单独提示

USO daily 数据 2 个 single-day jump > 50% — 一次是 2020-04 oil price collapse（真实事件）+ 一次可能是 2020 reverse-split 或 roll structure 异常。USO 由于 futures-roll yield structurally 不同于 spot oil，**建议 cycle #04 排除 USO**，commodity 仅用 GLD。

## Cycle #04 真正的设计问题（不是"扩 universe"）

按照 collaborator §"regime allocation, not just selection"：

**当前 mining objective 是 full-period composite IC**。这个 objective 对 cross-asset diversifier 是 wrong objective：

- 一个理想的 bond sleeve：在 equity drawdown regime（占总日期 ~15%）正回报，在 risk-on regime（~70%）负回报或低正回报
- Full-period IC = 全期均值 — 这个 sleeve 平均 IC 接近 0
- 但它的实际投资价值是 crisis-conditional payoff — 完全没被 objective 捕获

**所以即使数据修好，IC mining 也找不到 bond/commodity diversifier**。要找到，需要：

(option A) Mining objective 加 regime-conditional 项（e.g., `min(IC_full_period, IC_in_equity_drawdown_regime)`）
(option B) 不做 mining，cycle #04 = 手动 regime-allocation strategy（e.g., 60/40 + tactical equity stock selection on the equity sleeve）
(option C) Mining 仍跑 IC，但 closeout 用 regime diagnostics 评判 nominee — closeout 标准更严

## 我的 operator 推荐路径

按 collaborator "如果你让我二选一：先授权 C-4 preflight + YAML design？我选第二个" 我也认同。但 **preflight 已经发现的 3 个 hard blocker + 1 个 soft blocker，要用户先决策**：

### 决策 D1: 数据路径（hard blocker §2 + §3）

- (D1a) **Distribution sidecar 工程**：建 `data/ref/distributions.parquet`（与 splits.parquet 同结构），BarStore.load(adjusted_total_return=True) 应用。**1-2 天工程**。这是干净路径但延后 cycle #04 启动 1-2 天。
- (D1b) **接受 yfinance auto_adjust**：bond/commodity ETF 全用 yfinance auto_adjust=True；接受 source-semantic mix（与 stock canonical 不同 cascade），在 closeout 里 flag。**1 小时工程** 但留下 known-mixed-adjustment 风险。
- (D1c) **Cycle #04 推迟**：等 distribution sidecar + 2009-2014 backfill 完成。最干净但拖到下一周。

**Operator 倾向 D1a**，理由：刚做完 Task #49 修了 heterogeneous-source 风险，不应该立刻在 cycle #04 又引入同类风险。1-2 天工程 < 在 mining 跑出 0-nominee 后才发现数据问题的代价。

### 决策 D2: Panel 起点（hard blocker §3）

- (D2a) Backfill 2009-2014 via yfinance long-history → train 完整
- (D2b) Cycle #04 改 panel = 2015-2025 → 损失 GFC/欧债 regime（这两个 regime 恰好是 bond diversifier 最有效的时期，损失它们等于 cycle #04 自我设限）
- (D2c) 留 stocks panel 2009 起 + cross-asset 2015 起 → mining 必须处理 ragged panel；temporal_split + research_mask 都需要扩展

**Operator 倾向 D2a**（与 D1a 同期做完）。

### 决策 D3: Mining objective（soft blocker）

- (D3a) Cycle #04 跑 standard composite IC mining + closeout 加 regime-conditional diagnostics → 最快但 likely 0 nominee with same root cause
- (D3b) 改 mining objective 为 regime-aware（多 objective）→ mining_evaluator + research_miner 都要改，1 周工程
- (D3c) Cycle #04 不跑 mining，直接做 manual regime-allocation 策略候选 → 跳过 IC 漏斗的好处但失去 mining 的探索价值

**Operator 倾向 D3a**（先用现有 objective + 严格 closeout 评判），理由：先验证"数据修好后 selector 会不会选 non-equity"这个机械问题；如果 D1+D2 修好后 selector 仍只选 stocks，再升级到 D3b（这才是真正需要 regime-aware objective 的证据）。

### 决策 D4: Role（collaborator §1）

- core_alpha：QQQ hard gate 仍生效；cross-asset 是 risk-control 手段
- diversifier：role-specific gates，QQQ excess 不硬杀

**Operator 倾向 core_alpha**（与 collaborator 同），理由：还没第一个 working core；过早转 diversifier 会拿到一个低相关但不赚钱的东西；但 closeout 同时 report B-style metrics（raw/residual corr, beta, non-equity weight, regime returns）确保未来转 diversifier 评判可比。

### 决策 D5: Asset class caps（collaborator §3）

预设 yaml block（pending D1+D2）：

```yaml
construction:
  mode: cap_aware_cross_asset
  top_n: 10
  max_single_weight: 0.10
  cluster_cap: 0.20
  asset_class_caps:
    equities_max: 0.70
    bonds_max:    0.40
    commodities_max: 0.20
    cash_anchor_max: 0.30
  asset_class_min_report_only:
    non_equity_weight_avg_min_report: 0.15  # NOT enforced
```

risk_cluster_map 扩展（pending D1+D2）：

- bond_long_duration: TLT
- bond_intermediate_duration: IEF
- bond_short_duration: SHY
- commodity_metals: GLD
- cash_anchor: BIL, SHV

5 个新 cluster，total → 22。stock 17 cluster + cross-asset 5 cluster。Cap_aware selector 用 cluster_cap=0.20 自然会强制 ≥ 5 cluster 贡献 → 必有 cross-asset 分配（如果数据 + factor 信号允许）。

USO 排除（§USO 单独提示）。

## Cycle #05 stop rule（按 collaborator §"如果 C-4 仍然 0 nominee"）

**操作员承诺**：如果 cycle #04 在数据全修好（D1a + D2a）+ mining 跑完 + 严格 closeout 后仍 0 nominee，**不开 cycle #05 mining**。改做战略转向 — 认真讨论:
- 改目标：从 beat QQQ 转到 lower drawdown / smoother compounding
- 改数据：fundamentals / earnings / news / event
- 改频率：true intraday / overnight，不是 21d IC proxy
- 改工具：options / hedges / inverse ETFs（破 long-only 约束需要 user explicit-go）
- 改策略：regime allocation / tactical asset allocation 替代 stock selection

写在这里是因为如果 cycle #04 失败，这个 stop rule 应该是已 pre-committed 的，不能事后软化。

## 待办下一步（pending user 5 个 D 决策）

| ID | 内容 | 估时 | Pending |
|---|---|---|---|
| P0a | Distribution sidecar (D1a) | 1-2 天 | D1 |
| P0b | 2009-2014 bond ETF backfill (D2a) | 1 天 | D2 |
| P0c | risk_cluster_map 扩展 (5 cross-asset cluster) | 0.5 天 | D5 |
| P0d | composite_evaluator cap_aware 加 asset_class_caps 第二层 cap | 0.5 天 | D5 |
| P0e | 跨资产 universe.yaml 配置 / cycle #04 yaml 内嵌 universe | 0.25 天 | D5 |
| P1 | Cycle #04 yaml 预 register (sha256 写到 commit message) | 0.25 天 | All Ds |
| P2 | Cycle #04 mining (200 trials TPE) | ~2-3h | After P1 |
| P3 | Cycle #04 evaluation (extends current eval pipeline + regime diagnostics) | 0.5 天 | After P2 |
| P4 | Cycle #04 closeout memo + commit | 0.5 天 | After P3 |

**总工程时间从 cycle #03 单日完成跳到 ~5 天**。这是 collaborator preflight 揭示的真实复杂度。

## R1+R2+R3+R4 self-audit (本份 preflight)

- **R1**: 7 ETF 数据 / source / CAGR 全部直接 grep `data/daily/*.parquet` + `data/ref/bar_provenance.parquet`，不是从 cache。
- **R2**: distribution gap 通过 yfinance `auto_adjust=True` vs `auto_adjust=False` 双跑得到，差异 = sum of dividends per period — 数学闭环。
- **R3**: naive {SPY, TLT, GLD} basket 实际跑出来 Pearson 0.545 (vs SPY) — 不是估算，是真值；用 yfinance TR TLT 重跑后变化 < 0.001（说明结论对 distribution gap 不敏感）。
- **R4 boundary**:
  - SHV 仅 4 个 factor cov ≥ 80% — 如果 cycle #04 universe 包含 SHV 但 SHV 拿不到任何因子分，selector 会怎么处理？需要 §4-corner-case 测试，但当前 cap_aware selector line 201-206 会把 NaN-composite 行直接丢掉（safe fail）。
  - SHY 起始 2015-01-07 比 SPY 晚 5 trading day — temporal_split 是否会把 SHY 的 2015 头 5 天处理成 NaN？需要测试。
  - 2009-2014 bond data 在 yfinance 是否真的 backfill 干净？没验证；P0b 依赖。
  - **未测**: 在 D1a 修完 distribution 之后 selector 是否真的会选 non-equity。这是 mining 真正会不会成功的关键，**应该在跑 200 trials 前用 5-10 trial smoke test 验证**。加到 P2 前的 P1.5 smoke。

## Files

- 本 preflight: `docs/memos/20260501-cycle04_cross_asset_preflight.md`
- 候选 ETF daily panels: `data/daily/{TLT,IEF,SHY,GLD,USO,BIL,SHV}.parquet`
- 候选 ETF provenance: `data/ref/bar_provenance.parquet`
- 候选 cluster map 扩展位: `core/research/risk_cluster_map.py` (待 P0c)
- 候选 yaml 模板位: `data/research_candidates/track-c-cycle-2026-05-XX-XX_promotion_criteria.yaml` (待 P1)
