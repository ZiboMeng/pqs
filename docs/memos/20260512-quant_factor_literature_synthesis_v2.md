# Quant Factor Literature Synthesis v2 — Actionable Backlog

**Date**: 2026-05-12
**Owner**: resident quant operator
**Status**: 综合资料 + Bucket B 可行性结论（待 directional decision）
**Lineage**: 接 x.txt §"重启后会话" lit review + Bucket B 数据 probe；上一会话 11-主题 WebSearch 信息 fold-in

---

## TL;DR

**See §7 for expanded batch 2 + 3 coverage (37 topics total; +15 new directions per user 2026-05-12)**.

1. **Bucket A T1 因子（OHLCV）**: 1-2 天即刻可做。Volume-microstructure / consolidation / 4 象限是 PQS 现存最大 factor library gap（cycle04-08 5 个 cycle 几乎没探索）。Batch 2+3 加 coskew + cokurt + calendar timing + pre-FOMC window → 现 ~28 factor.
2. **Bucket B T5 fundamentals 长历史的关键解锁 = SEC EDGAR companyfacts API**（非 WebFetch、非 stockanalysis、非 macrotrends）。free 官方 endpoint，2009+ 全覆盖，503 us-gaap tags 一次拿全，PIT-clean（含 filed_date）。**Batch 2+3 加 Piotroski F-score (9 boolean) + Beneish M-score (8 sub-ratios) + Altman Z-score (5) + Magic Formula + buyback/shareholder yield + FCF yield + FCF profitability + revenue momentum + asset growth (FF5 CMA) + operating leverage + R&D intensity → 现 ~43 factor**, 工程量 3-5 天 → 5-8 天.
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

---

## 7. Batch 2 + 3 expansion — 15 additional topic directions (2026-05-12 same session)

Per user 2026-05-12 12:00 ET 指令"美股量化的 literature 都要读 不要限定方向"，扩展从 22 → 37 主题。Batch 2 (10 topic) + Batch 3 (5 topic) 全部经 WebSearch 实证。

### 7.1 Fundamental composite ranking (T5, EDGAR-implementable)

**Piotroski F-score** (9 boolean accounting tests; Piotroski 2000; Schwartz-Hanauer 2024 ✓)

| 因子名 | 公式 | 数据需求 |
|---|---|---|
| piotroski_f_score | 9 个 boolean 之和 (0-9) | EDGAR: NetIncomeLoss / NetCashProvidedByUsedInOperatingActivities / Assets / LongTermDebt / CurrentAssets / CurrentLiabilities / CommonStockSharesIssued / GrossProfit / Revenues |
| f_score_high_filter | f_score ≥ 7 → 1 else 0 | 同 |
| f_score_low_warning | f_score ≤ 3 → -1 else 0 | 同 |

2024 Schwartz-Hanauer 综合 4 公式 (F-score / Magic / Acquirer's / Conservative) over 1963-2022 — all generate alpha via 标准 factor exposure，no single dominates；F-score ≥7 filter + Magic Formula 减小 drawdown。

**Greenblatt Magic Formula** (composite: earnings yield × ROIC)

| 因子名 | 公式 |
|---|---|
| magic_formula_rank | rank_pct(EarningsYield) + rank_pct(ROIC); 取 sum 后 cross-section rank |
| earnings_yield_ebit_ev | EBIT_ttm / EnterpriseValue |
| roic_invested_capital | EBIT_ttm × (1 - tax_rate) / (TotalAssets - CurrentLiabilities) |

**Beneish M-score** (8-ratio earnings manipulation; > -2.22 = likely manipulator; 2024 G7 + 2025 Borsa Istanbul random-forest ✓)

| 因子名 | 公式 | EDGAR tag |
|---|---|---|
| beneish_m_score | -4.84 + 0.92×DSRI + 0.528×GMI + 0.404×AQI + 0.892×SGI + 0.115×DEPI - 0.172×SGAI + 4.679×TATA - 0.327×LVGI | 8 ratios below |
| dsri | (AR_t / Sales_t) / (AR_{t-1} / Sales_{t-1}) | AccountsReceivableNetCurrent / Revenues |
| gmi | GM_{t-1} / GM_t (gross margin) | GrossProfit / Revenues |
| aqi | (1 - (CA + PPE) / Assets) ratio | CurrentAssets / PropertyPlantAndEquipmentNet / Assets |
| sgi | Sales_t / Sales_{t-1} | Revenues |
| depi | dep_rate_{t-1} / dep_rate_t | DepreciationDepletionAndAmortization / PropertyPlantAndEquipmentNet |
| sgai | (SGA_t / Sales_t) / (SGA_{t-1} / Sales_{t-1}) | SellingGeneralAndAdministrativeExpense / Revenues |
| tata | (NI - CFO) / Assets | NetIncomeLoss / NetCashProvidedByUsedInOperatingActivities / Assets |
| lvgi | (Debt_t / Assets_t) / (Debt_{t-1} / Assets_{t-1}) | TotalDebt / Assets |

**Altman Z-score** (5-ratio credit distress; 2025 仍 valid per recent reviews)

| 因子名 | 公式 | EDGAR tag |
|---|---|---|
| altman_z_score | 1.2A + 1.4B + 3.3C + 0.6D + 1.0E | 5 ratios below |
| z_working_cap_to_assets | (CA - CL) / Assets | CurrentAssets - CurrentLiabilities |
| z_retained_earn_to_assets | RetainedEarnings / Assets | RetainedEarningsAccumulatedDeficit |
| z_ebit_to_assets | EBIT_ttm / Assets | OperatingIncomeLoss |
| z_equity_to_liab | MarketCap / TotalLiabilities | close × shares / Liabilities |
| z_sales_to_assets | Revenues / Assets | Revenues / Assets |

**Ohlson O-score** (9 variable distress; 含 market cap → 更 dynamic; Z-score + BM 交互在 high-distress 放大 2× spread)

→ implementable via EDGAR + close × shares 但 9 个 component 复杂；建议先 implement Z-score；O-score Phase 2

### 7.2 Capital return factor (T5, EDGAR-implementable)

**Buyback yield / shareholder yield** (Boston Partners 2024 / Morningstar yield risk factor ✓; 2024 S&P 500 buyback $942.5B record)

| 因子名 | 公式 | 备注 |
|---|---|---|
| buyback_yield_ttm | (shares_{t-4q} - shares_t) × close / market_cap | Net repurchase yield；CommonStockSharesOutstanding |
| dividend_yield_ttm | DividendsCommonStockCash_ttm / market_cap | EDGAR DividendsCash 或 DividendsCommonStockCash |
| shareholder_yield_ttm | buyback_yield_ttm + dividend_yield_ttm | 复合 |
| conservative_issuer_flag | shares_change_yoy ≤ -1% → 1 (积极回购), shares_change_yoy ≥ +2% → -1 (diluter) | |

### 7.3 Free cash flow factor (T5, EDGAR-implementable)

**FCF yield + FCF profitability** (LSEG / VictoryShares VFLO 2024 +22%; FCF Profitability Sharpe 0.62 > FCFY 0.50 — 又一个 profitability subsume story)

| 因子名 | 公式 | EDGAR tag |
|---|---|---|
| fcf_yield_ttm | FCF_ttm / market_cap | NetCashProvidedByUsedInOperatingActivities - PaymentsToAcquirePropertyPlantAndEquipment |
| fcf_to_assets_ttm | FCF_ttm / Assets | 同上 / Assets (FCF Profitability) |
| fcf_margin_ttm | FCF_ttm / Revenues | 同上 / Revenues |
| fcf_growth_3y | 3-yr CAGR of FCF_ttm | 同上，3 年 vs 当前 |

### 7.4 Sales / revenue momentum (T5, EDGAR-implementable)

Russell Q4 2024 Factor Report: Momentum +623bps；3-yr Cash Flow Growth +11.5%；Growth + Momentum 2024 leadership return.

| 因子名 | 公式 | EDGAR tag |
|---|---|---|
| revenue_growth_yoy | (Revenues_q - Revenues_{q-4}) / Revenues_{q-4} | Revenues |
| revenue_growth_qoq | (Revenues_q - Revenues_{q-1}) / Revenues_{q-1} | Revenues |
| revenue_growth_3y_cagr | 3-yr CAGR | 同 |
| sales_acceleration | revenue_growth_yoy - revenue_growth_yoy_{q-1} | momentum on momentum |
| gross_profit_growth_yoy | (GP_q - GP_{q-4}) / GP_{q-4} | GrossProfit |

### 7.5 Investment / asset growth factor (T5, EDGAR-implementable; less robust per Fama-French 2008)

Fama-French CMA — 4%/yr pre-2004, dissipated thereafter. RMW (profitability) consistently outperforms CMA. → implement 但诚实标注 weak.

| 因子名 | 公式 | EDGAR tag |
|---|---|---|
| asset_growth_yoy | (Assets_q - Assets_{q-4}) / Assets_{q-4} | Assets — *inverse signal*: low asset growth → higher returns |
| investment_intensity | (PPE_q - PPE_{q-4} + Δinventory) / Assets_{q-1} | PropertyPlantAndEquipmentNet / InventoryNet |

### 7.6 Operating leverage (T5, EDGAR-implementable)

DOL = %ΔEBIT / %ΔSales; 高 fixed cost ratio → 高 sales sensitivity. 可作 risk indicator + 杠杆 timing 因子.

| 因子名 | 公式 | EDGAR tag |
|---|---|---|
| dol_4q_window | (EBIT_q / EBIT_{q-4} - 1) / (Revenues_q / Revenues_{q-4} - 1) | OperatingIncomeLoss / Revenues |
| fixed_cost_ratio | (OperatingExpenses - COGS) / Revenues | CostOfGoodsSold + OperatingExpenses |
| dol_zscore_sector | dol 在 sector 内 zscore | requires Bucket C T3 |

### 7.7 R&D / innovation (T5, EDGAR-implementable, 但 alpha 弱)

Goyal-Wahal April 2024: high R&D 大盘 1.63%/yr alpha；high-zero R&D spread 3.86%；**R&D capitalize as asset → alpha → 0** (alpha 来自 accounting expense treatment 不是 innovation real pricing).

| 因子名 | 公式 | EDGAR tag |
|---|---|---|
| rd_intensity | ResearchAndDevelopmentExpense / Revenues | ResearchAndDevelopmentExpense (NOT all sym 有) |
| rd_intensity_yoy_change | rd_intensity_q - rd_intensity_{q-4} | 同 |
| rd_per_employee | RD / Employees | (Employees 需要 separate filing) |

**注**: 仅在 universe 中 有 R&D 报告的 stocks (e.g., GOOGL/AAPL/MSFT yes; XOM/JPM no); cross-sectional rank 需 handle missing.

### 7.8 Higher moments — co-skewness / co-kurtosis (T1, OHLCV-implementable)

Harvey-Siddique 2000: cross-sectional coskew premium 0.27%/月 (1959-2011, US)；Bressan 2024 RFE: time-varying coskew-return relationship in banking. **可纯 OHLCV 实现**：

| 因子名 | 公式 |
|---|---|
| coskew_60d_spy | E[(r_i - μ_i)² (r_m - μ_m)] / (σ_i² × σ_m) 用 SPY 60d window |
| cokurt_60d_spy | E[(r_i - μ_i)³ (r_m - μ_m)] / (σ_i³ × σ_m) 同 |
| coskew_60d_qqq | 同 with QQQ |
| idiosyncratic_skew_60d | skewness(residual_i) 后 60d window |

**注**: 把 coskew 加到 PQS 是补 idiovol 因子族的"二阶矩"维度；与 lottery MAX 不同但相关（MAX 是 right-tail extreme，skew 是 distribution shape）.

### 7.9 Calendar timing (T1, NO OHLCV needed, pure date-based)

Sell-in-May 仍 persist (Nov-Apr SEC filings -17% than May-Oct → fundamental info flow seasonal); turn-of-month +10bps; Jan effect since 1987 declined.

| 因子名 | 公式 |
|---|---|
| turn_of_month_flag | 月末 4 个交易日 + 月初 3 个交易日 → 1 else 0 |
| sell_in_may_seasonal | Nov-Apr → +1, May-Oct → -1 |
| jan_effect_flag | Jan 第一周 → 1 else 0 (weakened post-1987) |
| monday_friday_flag | Mon → -1, Fri → +1 (Monday effect) |
| month_end_quarter_end | Mar/Jun/Sep/Dec 月末 → +1 (institutional rebalance) |

**注**: 这些是 timing / scaling factor 不是 stock-selection factor — 不进入 cross-sectional rank 但可作 regime-conditional modifier.

### 7.10 Macro event drift (T1, requires events.yaml expansion)

Pre-FOMC drift = ~50% of post-1994 excess returns; CPI / NFP attention drift also documented.

| 因子名 | 公式 |
|---|---|
| pre_fomc_window_flag | FOMC -2 trading days to FOMC day → 1 |
| post_fomc_window_flag | FOMC +1 to FOMC +3 → 1 |
| pre_cpi_window_flag | CPI release -1 day → 1 |
| pre_nfp_window_flag | NFP release -1 day → 1 |
| macro_event_density_5d | count(events) in next 5 days |

**数据需求**: 已有 `config/events.yaml` (generic) — 需扩展 FOMC / CPI / NFP 真实日历 (可手动 curate 2009-2026 一次性 + 季度 update)，约 200 events × 16 yr.

### 7.11 Forecast dispersion / analyst disagreement (T6 — paid)

Diether-Malloy-Scherbina 2002: 高 dispersion → 低 future returns；2024 study: institutional trade dispersion 替代后 analyst dispersion → 不显著. → 需要 IBES / institutional flow paid path. **T6 deferred**.

### 7.12 ESG / climate (NOT recommended for current PQS)

主要是 risk management framework；缺乏明确 cross-sectional alpha；80% investors 考虑；但 PQS 78-sym universe 是 大中盘 active strategy，ESG tilt 不是 alpha 来源 — 是 mandate constraint. → **SKIP unless 用户加 mandate**.

### 7.13 Reddit / WSB sentiment (T6 — niche)

WSB attention 高时 8.5% return 反转 (contra signal)；75% retail in meme stocks lose money；某些 papers: WSB returns 部分 outperform bank analysts. → **需要 Reddit API + scraping + NLP pipeline**；T6 deferred (low ROI 直到 PQS universe 含 GME-style names).

---

## 7.X. 推荐扩展 (revised after batch 2+3)

新增 T1 batch:
- coskew_60d + cokurt_60d + idiosyncratic_skew_60d (3 个)
- turn_of_month_flag + sell_in_may_seasonal + month_end_quarter_end (3 个)
- pre_fomc_window_flag (×4 events) (4 个)

**Bucket A T1 总计修正：~18 → ~28 factor**（仍 1-2 天工程）

新增 T5 batch (EDGAR-implementable):
- Piotroski F-score + 3 derived (4 个)
- Magic Formula composite + 2 component (3 个)
- Beneish M-score + 8 sub-ratios (9 个)
- Altman Z-score + 5 components (6 个)
- Buyback / dividend / shareholder yield (4 个)
- FCF yield + FCF profitability + 2 derived (4 个)
- Revenue growth × 4 horizons (5 个)
- Asset growth + investment intensity (2 个)
- Operating leverage (3 个)
- R&D intensity (3 个)

**Bucket B T5 总计修正：~15 → ~43 factor**（工程量从 3-5 天 → 5-8 天，主要 Beneish 8 ratios + Altman 5 + Piotroski 9 + Magic Formula composite 需个体测试 + leakage 验证）

---

## 8. Sources (batch 2 + 3 addition)

### Fundamental ranking
- [Schwartz-Hanauer Dec 2024 — 4-formula comparison](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=...)
- [Piotroski F-Score wikipedia + Old School Value](https://en.wikipedia.org/wiki/Piotroski_F-score)
- [Alpha Architect — Investment Factor dissection](https://alphaarchitect.com/dissecting-the-investment-factor/)
- [Quant-investing — F-Score Complete Guide](https://www.quant-investing.com/blog/piotroski-f-score-complete-guide)

### Buyback / shareholder yield
- [Boston Partners May 2024 — Power of Stock Buybacks](https://www.bostonpartners.com/uploads/2024/05/c4ab9e6f6438ed367f02a81230d3c9fc/may-2024-power-of-stock-buybacks-wp.pdf)
- [S&P DJ Indices — Examining Share Repurchases](https://www.spglobal.com/spdji/en/documents/research/research-sp-examining-share-repurchases-and-the-sp-buyback-indices.pdf)
- [WisdomTree — A Force for Returns: Shareholder Yield](https://www.wisdomtree.com/-/media/us-media-files/documents/resource-library/market-insights/weniger-commentary/a_force_for_returns_shareholder_yield.pdf)

### CMA / asset growth
- [Robeco Oct 2024 — Fama-French 5-factor concerns](https://www.robeco.com/en-int/insights/2024/10/fama-french-5-factor-model-five-major-concerns)
- [Long Term Trends — Fama-French 5 Factor](https://www.longtermtrends.com/fama-and-french-5-factor-model/)
- [Alpha Architect — Investment Factor dissection](https://alphaarchitect.com/dissecting-the-investment-factor/)

### Forecast dispersion
- [Diether-Malloy-Scherbina 2002 — Differences of Opinion](https://www.hbs.edu/faculty/Pages/item.aspx?num=31704)
- [Johnson 2004 JF — Forecast Dispersion](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2004.00688.x)
- [2024 SD ScienceDirect — Institutional Trade Dispersion](https://www.sciencedirect.com/science/article/abs/pii/S0378426624002486)

### Operating leverage
- [WallStreetPrep — DOL](https://www.wallstreetprep.com/knowledge/operating-leverage/)
- [Corporate Finance Institute — DOL](https://corporatefinanceinstitute.com/resources/accounting/degree-of-operating-leverage/)

### Calendar anomalies
- [Springer 2024 — Calendar anomalies + dividend announcements](https://link.springer.com/article/10.1007/s11156-024-01321-0)
- [MDPI 2025 — Sell in May Regulatory Disclosures puzzle](https://www.mdpi.com/2227-7072/13/4/208)
- [ScienceDirect 2024 — Sector-specific calendar anomalies US](https://www.sciencedirect.com/science/article/abs/pii/S1057521924002795)
- [Harbourfront 2024 — Do Calendar Anomalies Still Exist](https://harbourfrontquant.substack.com/p/do-calendar-anomalies-still-exist)

### Co-skewness / higher moments
- [Bressan 2024 RFE — Time-Varying Coskew Banking](https://onlinelibrary.wiley.com/doi/full/10.1002/rfe.1178)
- [Harvey-Siddique 2000 — Conditional Skewness](https://people.duke.edu/~charvey/Research/Published_Papers/P56_Conditional_skewness_in.pdf)
- [ScienceDirect — Comoment Risk and Stock Returns](https://www.sciencedirect.com/science/article/pii/S0927539813000492)

### Beneish M-score
- [2025 Tandfonline Cogent — M-score G7 Cash Holdings](https://www.tandfonline.com/doi/full/10.1080/23311975.2025.2502542)
- [Çiğdem Özari et al 2025 — Z + M Random Forest Borsa Istanbul](https://journals.sagepub.com/doi/10.1177/21582440251386174)
- [Beneish M-score Wikipedia](https://en.wikipedia.org/wiki/Beneish_M-score)

### Pre-FOMC / macro event drift
- [NY Fed Pre-FOMC Drift sr512](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr512.pdf)
- [NBER w25817 — Explaining Pre-Announcement Returns](https://www.nber.org/system/files/working_papers/w25817/revisions/w25817.rev2.pdf)
- [Fed 2025-022 — How Markets Process Macro News](https://www.federalreserve.gov/econres/feds/files/2025022pap.pdf)
- [BIS Working Paper 1079 — Volume dynamics around FOMC](https://www.bis.org/publ/work1079.pdf)

### WSB / Reddit sentiment
- [ScienceDirect 2024 IPbs — WSB social media attention retail](https://www.sciencedirect.com/science/article/pii/S1057521924006537)
- [Tandfonline 2024 — Democratisation of Retail WSB vs Analysts](https://www.tandfonline.com/doi/full/10.1080/2573234X.2024.2354191)
- [ScienceDirect 2025 — Dumb money? Social network attention herding](https://www.sciencedirect.com/science/article/pii/S2405918825000212)

### Sales / revenue momentum
- [Russell Q4 2024 Equity Factor Report](https://russellinvestments.com/content/ri/us/en/insights/russell-research/2025/01/equity-factor-report---q4-2024-growth-and-momentum-take-back-lea.html)
- [Confluence Q4 2024 Factor Performance](https://www.confluence.com/q4-2024-factor-performance-analysis/)

### R&D / innovation
- [Goyal-Wahal April 2024 — Markets Efficiently Value R&D](https://www.wealthmanagement.com/investing-strategies/does-the-market-know-how-to-price-r-d-and-innovation-)
- [Bloomberg Innovation Factor whitepaper 2024](https://assets.bbhub.io/professional/sites/27/Bloomberg-Indices-The-Innovation-Whitepaper.pdf)
- [NASDAQ NQIPL International Patent Leaders Index](https://www.nasdaq.com/articles/nasdaq-international-patent-leaders-index-tracking-top-innovators-outside-the-us)

### ESG / climate
- [Skadden 2025 — ESG Review 2024 + 2025 Trends](https://www.skadden.com/insights/publications/2025/01/esg-a-review-of-2024-and-key-trends-to-look-for-in-2025)
- [JPMorgan AM 2025 Global Climate Report](https://am.jpmorgan.com/content/dam/jpm-am-aem/global/en/sustainable-investing/tcfd-report.pdf)

### FCF yield
- [LSEG FTSE Russell — FCF All-Weather Strategy](https://www.lseg.com/en/insights/ftse-russell/free-cash-flow-an-all-weather-equity-strategy)
- [Abacus FCF July 2025 — Profitability vs Yield](https://abacusfcf.com/wp-content/uploads/2025/09/Revisiting-Free-Cash-Flow-Investing_Investing-Profitability-or-Yield.docx.pdf)
- [Pace ETF — FCFY & FCFM](https://www.paceretfs.com/media/why_fcfy_fcfm.pdf)

### Altman Z / Ohlson O
- [MDPI 2025 — Altman Z-Score + ML Corporate Failure](https://www.mdpi.com/1911-8074/18/8/465)
- [Wikipedia Altman Z-score](https://en.wikipedia.org/wiki/Altman_Z-score)
- [Wikipedia Ohlson O-score](https://en.wikipedia.org/wiki/Ohlson_O-score)
- [Nature Humanities 2024 — Quality Portfolios via Score Models](https://www.nature.com/articles/s41599-024-03888-4)
