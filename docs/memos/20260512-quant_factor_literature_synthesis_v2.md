# Quant Factor Literature Synthesis v2 — Actionable Backlog

**Date**: 2026-05-12
**Owner**: resident quant operator
**Status**: 综合资料 + Bucket B 可行性结论（待 directional decision）
**Lineage**: 接 x.txt §"重启后会话" lit review + Bucket B 数据 probe；上一会话 11-主题 WebSearch 信息 fold-in

---

## TL;DR

1. **Bucket A T1 因子（OHLCV）**: 1-2 天即刻可做。Volume-microstructure / consolidation / 4 象限是 PQS 现存最大 factor library gap（cycle04-08 5 个 cycle 几乎没探索）。
2. **Bucket B T5 fundamentals 长历史的关键解锁 = SEC EDGAR companyfacts API**（非 WebFetch、非 stockanalysis、非 macrotrends）。free 官方 endpoint，2009+ 全覆盖，503 us-gaap tags 一次拿全，PIT-clean（含 filed_date）。工程 3-5 天写 ingest + store + factor。
3. **macrotrends / 大多数 free fundamentals scraper 都已 paywall**（HTTP 402），是 2024+ 的新现实。SEC EDGAR 是唯一 robust free 长历史源。
4. **Pairs trading / market-neutral / long-short stat-arb**: 全部违反 long-only invariant → SKIP（无 directional override 时）。
5. **News sentiment LLM (FinBERT / GPT)**: 学术 Sharpe 高（3.05）但需要 news corpus + LLM API → T6 deferred。
6. **Resident-quant 建议执行序**: Bucket A T1 (1-2d) → SEC EDGAR ingest + 第一批 T5 factor (3-5d) → cycle #09 mining w/ 扩展 RESEARCH_FACTORS（前提：cycle04-08 stop rule unfreeze + Trial 9 TD60 evidence）。Signal-confirmation MVP 跟 Bucket A 并行不冲突，跟 Bucket B 不冲突。

---

## 1. Bucket B 数据源可行性结论（2026-05-12 实测）

### 1.1 已测源

| 源 | endpoint | 历史深度 | 字段 | 状态 |
|---|---|---|---|---|
| **SEC EDGAR companyfacts** | `data.sec.gov/api/xbrl/companyfacts/CIK<n>.json` | **2009-2026 (18 年)** | 503 us-gaap tags | ✅ 用 `User-Agent` header 完美工作 |
| SEC EDGAR companyconcept | `.../companyconcept/CIK<n>/us-gaap/<tag>.json` | 同上 | 单 tag | ✅ 同 |
| SEC company_tickers lookup | `www.sec.gov/files/company_tickers.json` | n/a | CIK ↔ ticker 映射 | ✅ 10,376 entries |
| stockanalysis.com quarterly | `/stocks/aapl/financials/?p=quarterly` | 5 年 (20 quarters) | EPS, Revenue, Margins | ⚠️ 历史深度不够；可作 cross-check |
| macrotrends.net PE ratio | `/stocks/charts/AAPL/.../pe-ratio` | n/a | n/a | ❌ HTTP 402 paywall |
| macrotrends.net EPS history | `/stocks/charts/AAPL/.../eps-earnings-per-share-diluted` | n/a | n/a | ❌ HTTP 402 paywall |
| yfinance balance_sheet | `Ticker(s).balance_sheet` | **5 quarters (annual)** | 69 rows | ❌ 太浅 |
| yfinance earnings_dates | `Ticker(s).earnings_dates` | **5-6 年 (25 row hard cap)** | date, actual, consensus, surprise % | ⚠️ 浅但有 consensus（EDGAR 缺）|
| yfinance eps_trend | `Ticker(s).eps_trend` | **~90 天** | consensus revisions | ⚠️ 不能做 historical breadth |

### 1.2 SEC EDGAR coverage 实测（AAPL CIK 0000320193）

| Tag | n rows | earliest filed | latest filed |
|---|---|---|---|
| EarningsPerShareDiluted | 334 | 2009-10-27 | 2026-05-01 |
| GrossProfit | 334 | 2009-10-27 | 2026-05-01 |
| Assets | 144 | 2009-07-22 | 2026-05-01 |
| AccountsReceivableNetCurrent | 142 | 2009-07-22 | 2026-05-01 |
| NetIncomeLoss | 334 | 2009-10-27 | 2026-05-01 |
| CashAndCashEquivalentsAtCarryingValue | 226 | 2009-10-27 | 2026-05-01 |
| NetCashProvidedByUsedInOperatingActivities | 132 | 2009-10-27 | 2026-05-01 |
| StockholdersEquity | 258 | 2009-10-27 | 2026-05-01 |

8/8 通过。一次 companyfacts 请求拿 503 tag = 3.66 MB/公司。78-sym universe ≈ 285 MB 一次性 download。

### 1.3 SEC EDGAR 的局限（诚实标注）

| 局限 | 影响 | 缓解 |
|---|---|---|
| **只有 actuals, 没有 consensus** | 不能做 surprise factor 不能做 revision breadth | yfinance earnings_dates 5-6 年 partial fill 后续 cycle / 接 IBES (paid) |
| us-gaap taxonomy 不统一（同概念多 tag）| `Revenues` vs `RevenueFromContractWithCustomerExcludingAssessedTax` vs `SalesRevenueNet` 取决于 filer 偏好 | 写 tag-fallback chain 处理（已知 Quantopian Zipline / openBB 都这么做）|
| 季频 (10-Q) + 年频 (10-K) 不是日频 | PIT factor 在 filed_date 后 forward-fill 到 next filed_date | 已是 PIT-correct 做法 |
| 个别 small-cap fail | rate limit < 10 req/sec; PQS universe = 78 大中盘 | 非问题 |
| 旧公司 CIK history 复杂（M&A）| 78 sym 大多稳定（TSLA / GOOGL 是 reclassification 不是 CIK 改变）| sector_map.yaml 类似 manual curation |

### 1.4 替代 free 源（备份）

- **OpenBB** (Python, free): wraps SEC EDGAR + yfinance + FRED + 多个 free APIs；可作 ingest 加速器（不引入新依赖时手写 wrapper 即可）
- **FRED** (St Louis Fed): 宏观因子（CPI / fed_funds / 10Y / DXY） — 已计划，但跟 Bucket B 独立
- **Google Trends API (pytrends)**: investor attention proxy — 可补 PEAD × attention factor (Lan-Xie 2024)

---

## 2. Tier 重排的完整 factor candidate inventory

按 PQS 现有数据基础能否立刻接重排。所有 factor 名字遵循 PQS 命名习惯（snake_case，带 lookback 后缀）。

### 2.1 T1：现有 OHLCV 立刻可做（Bucket A）

**A.1 Volume-price microstructure**

| 因子名 | 公式 | 经济含义 | 文献来源 |
|---|---|---|---|
| obv_norm_20d | OBV / 20d std | 累计动量 | StockCharts / Kavout 2024 |
| chaikin_money_flow_20d | Σ((C-L)-(H-C))/(H-L) × V | accumulation/distribution 强度 | Chaikin / Kavout 2024 |
| accum_dist_line_zscore_60d | A/D line 的 60d zscore | "悄悄吸筹" | 经典 + x.txt §A.1 |
| vol_price_corr_20d | corr(volume, return) over 20d | 量价同步度（高 = healthy trend）| 经典 |
| volume_surge_when_flat | vol_zscore × (1 - \|ret_20d\| > τ) | 量增价不动盘整 | x.txt §A.1 |
| klinger_oscillator | Klinger volume-force divergence | 量价背离 | Klinger 1997 |

**A.2 Volume-confirmed 4 象限**

| 因子名 | 公式 |
|---|---|
| up_vol_ratio_20d | Σ(vol_i × 1{ret_i>0}) / Σ vol_i 过去 20d |
| down_vol_ratio_20d | 同上但 ret_i < 0 |
| vol_weighted_ret_20d | Σ(ret_i × vol_i) / Σ vol_i |

**A.3 Consolidation / box-pattern / breakout precursor**

| 因子名 | 公式 | 文献来源 |
|---|---|---|
| bb_squeeze_20d | (BB_upper - BB_lower) / SMA20 的 20d 分位 | Bollinger / StockDataAnalytics 2024 |
| atr_compression_20d | ATR20 / ATR60 | 经典 |
| range_position_pct_60d | (close - 60d_min) / (60d_max - 60d_min) | 经典 |
| consolidation_days_count | 连续 N 天 close 在 ±X% 范围 | x.txt §A.3 |
| adx_low_trend_flag | ADX < 20 持续天数 | Wilder |
| pre_breakout_volume_decay | 整理期 volume trend negative | 教科书 |

**A.4 52-week 锚（已有 drawup_from_252d_low 但缺其他锚）**

| 因子名 | 公式 | 文献来源 |
|---|---|---|
| nearness_to_52w_high | close / 52w_max | George-Hwang 2004（已成经典；近 52w high 优于过去 returns）|
| pull_from_52w_low | (close - 52w_min) / (52w_max - 52w_min) | 同 |
| price_anchor_dispersion | std(nearness_to_52w_high) cross-sectionally | George-Hwang extension |

**A.5 Short-term reversal（条件化版）**

| 因子名 | 公式 | 文献来源 |
|---|---|---|
| weekly_reversal_signal | -ret_5d × turnover_5d_zscore | Lehmann 1990 +/-30bps；2024 momentum 28% 反转预期 |
| overnight_daytime_persistence_reversal | conditional on 持续 overnight_pos + daytime_neg → t+1 reversal | Akbas-Boehmer-Jiang-Koch 2022 |

**A.6 Low-vol / BAB style（PQS 已有 idiosyncratic_vol_60d / beta_spy_60d 单因子；可加 ranking-style）**

| 因子名 | 公式 | 文献来源 |
|---|---|---|
| bab_score_60d | -beta_60d / idiovol_60d | BAB (Frazzini-Pedersen 2014) |
| betting_against_bad_beta | bad_beta_decomp from Campbell-Vuolteenaho ICAPM | Betting Against Bad Beta 2025 (Q. Finance) |

**T1 总计：~18-22 新 factor**（实现工程量 1-2 天，每个 30-60 分钟 + leakage test + 注册）

### 2.2 T3：sector classification + manual curate（Bucket C，半天 yaml + 1-2 天 code）

| 因子名 | 公式 | 备注 |
|---|---|---|
| sector_rel_mom_20d | sym 20d return - sector_median_20d return | 需 sector_map.yaml |
| sector_neutral_drawup | drawup_from_252d_low - sector_median_drawup | |
| sector_leader_rank | sym 在 sector 内的 12-1 mom rank | |
| sector_breadth_pct | % stocks in same sector w/ ret_5d > 0 | |
| sector_dispersion_20d | std of sym returns within sector 20d | |

**T3 总计：5-7 sector-relative factors**（依赖 78-sym sector_map.yaml）

### 2.3 T5：SEC EDGAR fundamentals（Bucket B，3-5 天）

按 actionable priority 排序：

**T5-Tier-1: 头号实证支持（Novy-Marx 2025 subsume 全部 quality）**

| 因子名 | 公式 | 文献来源 |
|---|---|---|
| gross_profitability | GrossProfit_q / Assets_q | Novy-Marx 2013 + 2025 NBER |
| gross_margin | GrossProfit_q / Revenues_q | 同 |
| gross_profitability_change_4q | GP_q / Assets_q - GP_{q-4} / Assets_{q-4} | Mulvey-Asness extensions |

**T5-Tier-2: 经典文献仍 alive (with cost regression)**

| 因子名 | 公式 | 文献来源 |
|---|---|---|
| sloan_accruals | (NI_q - CFO_q) / TotalAssets_q | Sloan 1996; weakened post-2002 但 cross-sectional 仍 alpha |
| operating_accruals_lag_4q | Acc_q - Acc_{q-4} | 同 |
| roa_q | NetIncomeLoss_q / Assets_q | Fama-French 5 profitability |
| roe_q | NetIncomeLoss_q / StockholdersEquity_q | 同 |
| asset_turnover_q | Revenues_q / Assets_q | DuPont decomposition |

**T5-Tier-3: 估值类（trailing PE 类，因 EDGAR 不含 forward consensus）**

| 因子名 | 公式 | 备注 |
|---|---|---|
| trailing_pe_at_filed | close_at_filed_date / TTM_EPS | PIT 在 filed_date 当天可知 |
| pb_ratio_at_filed | market_cap_at_filed / StockholdersEquity | |
| ev_ebitda_at_filed | (market_cap + total_debt - cash) / EBITDA_ttm | |
| earnings_yield_inverse_pe | TTM_EPS / close | E/P (Cakici et al SSRN 4141663 — ML 模型最常 select 之一) |
| trailing_pe_zscore_sector | 上面除以 sector median | requires Bucket C T3 |

**T5-Tier-4: Forward PE / consensus revisions（需要 IBES / Refinitiv paid OR yfinance 5-6 年 partial fill）**

| 因子名 | 公式 | 备注 |
|---|---|---|
| forward_pe_change_30d | forward_pe_t - forward_pe_{t-30} | 高速下降 = consensus 下调 |
| eps_revision_breadth_30d | (upgrades - downgrades) / total over 30d | FactSet style；alphaarchitect 2024 |

→ 仅 yfinance 5-6 年深度可做，不入 Bucket B 主线

**T5-Tier-5: PEAD（earnings_dates 提供 5-6 年 partial）**

| 因子名 | 公式 |
|---|---|
| days_to_earnings | 距下次财报天数 |
| days_since_earnings | 距上次财报天数 |
| earnings_window_flag | t-2 ≤ next_ed ≤ t+2 |
| eps_surprise_pct_last | 上次 surprise (yfinance 5-6 年) |
| pead_drift_5d / pead_drift_20d | 上次财报后 NAV drift (与 SPY 比) |

**T5 总计：18-22 fundamental factor**（其中 ~12 立刻可做 from EDGAR only; ~10 需要 IBES partial fill）

### 2.4 T6：Alt-data / options / sentiment（deferred / paid path）

| 因子族 | 数据需求 | 状态 |
|---|---|---|
| News sentiment FinBERT / GPT | news corpus + LLM API | Bond 2023 / arxiv 2410.01987；Sharpe 3.05 学术但需 ~$50-200/mo |
| Form 4 insider trading | SEC Form 4 ingest | Ozlen-Batumoglu 2026 SSRN：70-80% alpha 在 filing 前 dissipate；retail-grade 弱；可 "buy not-sold post-sale" 4.8% alpha |
| 13F institutional holdings | SEC 13F | 季频 only; 慢 signal |
| Options IV term structure | option chain history (paid) | Jones-Wang USC：~7%/月 straddle spread；T6 直接 deferred |
| Implied vol surface deep learning | option chain (paid) | FoFI 2024 Teng-Xu |
| Investor attention (Google Trends) | pytrends (free) | Lan-Xie 2024：attention × PEAD 6.78% excess/quarter |

### 2.5 T7：未走过的方向（Out of scope / 违反 invariant）

| 方向 | 状态 |
|---|---|
| Pairs trading (cointegration) | long-short → 违反 long-only invariant；ETF pairs 2024 paper 显示 low-vol → few opps |
| BAB long-short | 同 |
| Volatility risk premium harvesting (short straddle / put-write) | 短期 vol → 违反 no-short |
| Size premium SMB direct | "dead" since 1982 (Morningstar / Russell 2024)；考虑 size × low-vol 交互作 long-only |
| Index inclusion event factor | 2025 复活但 quarterly 4 events × universe inside SP500 ~ 已含 → n_observations 太少 |

---

## 3. 实施推荐顺序（resident-quant view）

**注意：不是 directional 决策，是按 ROI + 现有约束的建议。最后 directional 决策需要用户。**

### 3.1 当前 PQS 限制

- **cycle04-08 stop rule**: cycle #06 (post-Track-A) 已经 0 nominee；cycle04 stop rule 说 "if cycle #06 也 0 nominee, 不 auto-fire #07; 战略 pivot" — 当前正是 pivot 状态
- **Trial 9 forward 进行中**: trial9_diversifier_001 已 ABORT 2026-05-12（completed_fail）；trial9_diversifier_002 starts 2026-05-13；TD60 ~2026-08-06
- **Signal-confirmation MVP PRD v1.1 已 ship**（待 Phase 1 kickoff）
- **资源**: 单人 solo dev；alpha-first realign 已生效（auditor R36 priority）

### 3.2 推荐序

```
Day 1-2  : Bucket A T1 因子（18-22 factor，1-2 天）
            → 注册到 RESEARCH_FACTORS
            → 跑 leakage test
            → 不立刻 mining，先 ship 进 library

Day 3-7  : Bucket B SEC EDGAR ingest + T5-Tier-1+2 因子（12-15 factor，3-5 天）
            → core/data/edgar_provider.py
            → core/data/fundamentals_store.py (PIT store)
            → core/factors/fundamental_factors.py
            → core/factors/factor_registry.py 注册
            → Bucket B 跑 leakage test

Day 5-7  : 平行启动 Signal-Confirmation MVP Phase 1
            (Bucket A T1 已 ship; Bucket A 因子可作 confirmation_pattern)

Week 2+  : 战略 pivot decision point (取决于 Trial 9 TD60 + cycle04-08 stop rule unfreeze)
            options:
              - cycle #09 mining w/ 扩展 RESEARCH_FACTORS (Bucket A + B)
              - 或 signal-conf MVP Phase 2+
              - 或 Bucket C sector + T3 因子（如果 cycle #09 需要 sector-relative）
              - 或 OpenBB / FRED macro ingest（PRD-E TAA dormant → 激活路径）
```

### 3.3 跟现有 workstream 的 interaction

| Workstream | Conflict / Interaction |
|---|---|
| trial9_diversifier_002 forward (TD60 ~2026-08-06) | 无 conflict；Bucket A/B 因子库 expand 不影响 forward 观察 |
| Cycle04-08 stop rule | cycle #09 mining 仍冻结直到 user-go；Bucket A/B 是 library expansion 不是 cycle 启动 |
| Signal-conf MVP PRD v1.1 | Bucket A T1 因子可作 confirmation_pattern 候选 → MVP Phase 1 ROI 提升 |
| PRD-E TAA dormant | 跟 Bucket B 独立；OpenBB / FRED macro 是 PRD-E reactivation 路径 |
| Options paper (spy_8otm_bull_put_v1) | 完全独立 sleeve |

### 3.4 不做（resident-quant 拒绝清单）

- 不做 Pairs trading（违反 long-only invariant）
- 不做 paid options chain ingest（gated on Trial 9 TD60 GREEN per CLAUDE.md Options Research Track）
- 不做 LLM news sentiment ingest（gated on TD60 + paper paper TD60 align）
- 不直接抓 stockanalysis.com long-history scrape（5 年深度不够 + scrape 不稳；SEC EDGAR 更好）
- 不写 forward PE / consensus revisions factor 进 RESEARCH_FACTORS（数据深度不够；等 IBES paid path）

---

## 4. 直接 actionable next-step（待 confirm）

要按下面执行吗？

```
Tomorrow morning (5/13):
  1. trial9_002 TD001 first observe (daily ritual; 不冲突)
  2. Bucket A T1 因子 batch 1 (volume microstructure 6 factor)
     - obv_norm_20d / chaikin_money_flow_20d / accum_dist_line_zscore_60d
     - vol_price_corr_20d / volume_surge_when_flat / klinger_oscillator
     - 实现 → 注册 → leakage test → commit

Day 3-4 (5/14-15):
  3. Bucket A batch 2 (4-quadrant + consolidation + 52w + reversal + BAB) 12-14 factor
  4. Bucket A 全部 leakage test green → push

Day 5-9 (5/16-20):
  5. Bucket B SEC EDGAR ingest:
     - dev/scripts/fundamentals/build_edgar_cache.py (download 78 sym × companyfacts)
     - core/data/edgar_provider.py (raw cache reader)
     - core/data/fundamentals_store.py (PIT store with filed_date forward-fill)
     - core/factors/fundamental_factors.py (T5-Tier-1+2 12 factors)
     - core/factors/factor_registry.py 注册
     - leakage test + lookahead check

Day 10+ (Week 3):
  6. Signal-conf MVP Phase 1 kickoff（Bucket A 因子可参与 confirmation 库）
     OR
     战略 directional decision: 是否解冻 cycle #09 mining
```

---

## 5. Open directional questions（need user-go）

1. **Bucket B 启动？** SEC EDGAR ingest 工程 3-5 天；当前没有"立刻消费者"（cycle #09 暂未 auth）但是为下一波 mining 提前铺路。同意？
2. **Signal-conf MVP Phase 1 vs Bucket B 并行？** 并行可行但 work-in-flight 2 个 PRD（已有 trial9_002 forward 在跑 + options paper）；4-stream 是否过载？
3. **Bucket C sector_map.yaml 优先级**：低 ROI / 半天 yaml + 1-2 天 code；要现在做还是等 cycle #09 需要 sector-neutral 因子时再启动？
4. **OpenBB / FRED macro ingest** (PRD-E TAA reactivation 路径)：依赖 Trial 9 TD60 outcome；不动？

---

## 6. Sources

### Quality / profitability
- [Novy-Marx & Medhat 2025 NBER w33601](https://www.nber.org/system/files/working_papers/w33601/w33601.pdf) — profitability subsumes all quality
- [Novy-Marx 2013 — The Other Side of Value](https://mysimon.rochester.edu/novy-marx/research/QDoVI.pdf)
- [MSCI Quality Time](https://www.msci.com/documents/10199/4c5bd381-5b29-453e-ad73-6df24290a172)

### Cross-sectional ML factors
- [Cakici et al SSRN 4141663 — ML Goes Global](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4141663) — 46 markets, ML 模型最常 select: price ratios + short-term reversal + E/P
- [Blitz SSRN 4441376 — Cross-Section of Factor Returns](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4441376)

### Quality / 52-week high
- [George & Hwang 2004 — The 52-Week High and Momentum Investing](https://www.bauer.uh.edu/tgeorge/papers/gh4-paper.pdf)
- [Marquette epublications — Momentum Crashes and the 52-Week High](https://epublications.marquette.edu/cgi/viewcontent.cgi?article=1168&context=fin_fac)

### Accruals
- [Sloan 1996 — Information in Accruals about Earnings Quality (Quantpedia summary)](https://quantpedia.com/strategies/accrual-anomaly)
- [TRV — Sloan Ratio](https://trvanalyzer.com/sloan-ratio-why-investors-should-care-about-accruals-earnings-quality/)

### Short-term reversal + Lehmann
- [Lehmann 1990 reproduced — Alpha Architect](https://alphaarchitect.com/quantitative-momentum-research-short-term-return-reversal/)
- [Subrahmanyam 2024 UCR — Short-Term Reversals and Longer-Term Momentum](https://business.ucr.edu/sites/default/files/2024-05/subra-momentum-reversal.pdf)
- [Morgan Stanley — Momentum Ruled in 2024, Reversal Likely 2025](https://www.morganstanley.com/im/en-us/individual-investor/insights/articles/momentum-ruled-in-2024.html)

### Low-vol / BAB
- [Betting Against (Bad) Beta — Quantitative Finance 2025](https://www.tandfonline.com/doi/full/10.1080/14697688.2025.2517270)
- [Quantpedia — BAB Factor](https://quantpedia.com/strategies/betting-against-beta-factor-in-stocks)
- [Frazzini-Pedersen 2014 — Betting Against Beta](https://www.sciencedirect.com/science/article/pii/S0304405X13002675)

### Earnings revisions
- [Guerard FactSet symposium — Earnings Forecasts and Revisions](https://go.factset.com/hubfs/Symposium%20Images/Guerard_EARNINGS%20FORECASTS%20AND%20REVISIONS,%20PRICE%20MOMENTUM,%20AND%20FUNDAMENTAL%20DATA.pdf?hsLang=en)
- [Zacks ZRank methodology](https://www.zacks.com/upload_education/zrank.pdf)

### Lottery / MAX
- [Wang 2025 EFM — Factor MAX in Chinese Market](https://onlinelibrary.wiley.com/doi/full/...) (prior session)
- [Bali-Cakici-Whitelaw 2011 JFE — Maxing Out: Stocks as Lotteries](https://www.sciencedirect.com/science/article/pii/S0304405X10002126)

### Volume microstructure
- [StockCharts — Chaikin Money Flow](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/chaikin-money-flow-cmf)
- [Kavout 2024 — CMF Volume-Weighted Edge](https://www.kavout.com/blog/mastering-chaikin-money-flow-the-volume-weighted-edge)

### Volatility compression
- [StockDataAnalytics 2024 — Volatility Compression Breakout](https://stockdataanalytics.com/p/volatility-compression-breakout-pattern)

### Sentiment / LLM
- [Bond et al 2023 — ChatGPT market sentiment](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4412788) (prior session)
- [arxiv 2410.01987 — FinBERT vs LLM Financial Sentiment 2024](https://arxiv.org/abs/2410.01987)
- [Frontiers AI 2025 — LLMs in Equity Markets survey](https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2025.1608365/full)
- [arxiv 2508.07408 — Event-Aware LLM-Augmented Tweets](https://arxiv.org/abs/2508.07408) (prior session)
- [StockTime / TRR 2024 LLM papers] (prior session)

### Insider trading Form 4
- [Ozlen-Batumoglu SSRN 5966834 2026 — Death of Insider Trading Alpha](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5966834)
- [Alpha Architect — Form 3/4 Alpha](https://alphaarchitect.com/following-what-insiders-dont-trade/)

### S&P 500 inclusion
- [ETF Trends 2025 — Retail Revival Fuels Comeback](https://www.etftrends.com/retail-revival-fuels-comeback-sp-500-index-inclusion-effect/)
- [HBS Greenwood 23-025 — The Disappearing Index Effect](https://www.hbs.edu/ris/Publication%20Files/23-025_563e45c6-df92-4d9c-ae05-608d4d0acab1.pdf)

### Vol risk premium / vol-of-vol
- [Robot Wealth 2025 — VRP in Tumultuous Market](https://robotwealth.com/the-volatility-risk-premium-in-a-tumultuous-market/)
- [SSE 50 ETF Options 2024 — VRP good vs bad volatility](https://www.sciencedirect.com/science/article/abs/pii/S1062940824001311)

### Pairs / cointegration (SKIP per long-only)
- [Springer JAM 2025 — Cointegration-based Pairs ETFs](https://link.springer.com/article/10.1057/s41260-025-00416-0)

### Size effect
- [Morningstar — What Happened to the Size Premium](https://www.morningstar.com/alternative-investments/what-happened-size-premium)
- [Russell 2024 — Is Small Cap Exposure Still a Good Idea](https://russellinvestments.com/content/ri/us/en/insights/russell-research/2024/06/-is-small-cap-exposure-still-a-good-idea-asking-for-a-friend--.html)

### Regime / Dynamic factor allocation
- [Mulvey 2024 SSRN 4960484 — Dynamic Factor Allocation w/ Regime-Switching](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4960484) (prior session)

### Amihud illiquidity refined
- [Pacific-Basin Finance 2024 — Time-Weighted Daytime Amihud](https://www.sciencedirect.com/science/article/pii/S0927538X24000581) (prior session)

### PEAD
- [Garfinkel-Hribar-Hsiao 2024 — SUE PEAD Updated](https://www.sciencedirect.com/...) (prior session)
- [UCLA Anderson 2024 — Is PEAD a Thing? Again?](https://anderson-review.ucla.edu/) (prior session)
- [CFA Institute 2025 — Can GenAI Disrupt PEAD?](https://blogs.cfainstitute.org/) (prior session)

### SEC EDGAR official docs
- [SEC EDGAR XBRL companyfacts API](https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany)
- [SEC EDGAR API user agent rules](https://www.sec.gov/os/accessing-edgar-data)
