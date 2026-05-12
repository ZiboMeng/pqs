# Bucket A/B/C + Macro + Signal-conf MVP — 2-Week Tactical Schedule

**Date**: 2026-05-12
**Decision authority**: User explicit-go on Q1+Q2+Q3+Q4 全 yes (2026-05-12)
**Source PRD / memo**:
- `docs/memos/20260512-quant_factor_literature_synthesis_v2.md` (37 topic lit review + factor inventory)
- `docs/prd/20260512-signal_confirmation_mvp_prd.md` (PRD v1.1, shipped commit d7697c9)
- `x.txt` (Bucket A/B/C original spec from prior session)

---

## TL;DR

5 stream 并入 PQS：
1. **Bucket A**：28 个 OHLCV factor（5/13-5/15）
2. **Bucket B**：SEC EDGAR ingest + 43 fundamental factor（5/16-5/21）
3. **Bucket C**：sector_map + 5-7 sector-relative factor（5/22）
4. **Macro**：FRED ingest + 5-7 macro factor（5/23）
5. **Signal-conf MVP Phase 1**：3.5 周（5/27 起，跟 Trial 9 TD60 ~8/6 对齐）

**Total engineering**: ~10 trading days new factor library + 3.5 周 MVP Phase 1。
**Total factor expansion**: PQS 现有 64 RESEARCH + 7 PROD = 71 → 加 28 + 43 + 6 + 6 ≈ 154 (+83)。

---

## 1. Day-by-Day Schedule

### Week 1 (5/13 Tue - 5/19 Mon)

| 日期 | Day | 任务 | 输出 | 依赖 |
|---|---|---|---|---|
| 5/13 Tue | D1 | **trial9_002 TD001 first observe** (daily ritual 自动) + **Bucket A T1 batch 1** (volume microstructure 6 factor) | core/factors/factor_generator.py family_g_volume_microstructure + leakage test | 无 |
| 5/14 Wed | D2 | Bucket A T1 batch 2 (4-quadrant 3 + consolidation 6 factor) + daily ritual | family_h_consolidation + 9 factor | 无 |
| 5/15 Thu | D3 | Bucket A T1 batch 3 (52w 3 + reversal 2 + BAB 2 + coskew 3 + calendar 3 + pre-FOMC 4 = 17 factor) | family_i_higher_moments + family_j_calendar + family_k_event_window + Bucket A 全部完成 + commit | 无 |
| 5/16 Fri | D4 | **Bucket B prep**: mkdir + edgar_provider.py skeleton + first 78-sym companyfacts download (~285 MB) | data/fundamentals/edgar_cache/{cik}.json + provenance log | 无 |
| 5/17 Sat | — | (rest) | | |
| 5/18 Sun | — | (rest) | | |
| 5/19 Mon | D5 | Bucket B core: fundamentals_store.py (PIT store w/ filed_date forward-fill) + 5 critical tags resolver (Revenues / GrossProfit / Assets / NetIncomeLoss / CFO) | core/data/fundamentals_store.py + 4 unit tests | D4 |

### Week 2 (5/20 Tue - 5/26 Mon)

| 日期 | Day | 任务 | 输出 | 依赖 |
|---|---|---|---|---|
| 5/20 Tue | D6 | Bucket B factor batch 1: Piotroski F-score (9 boolean + composite + 3 derived = 4 factor) + Magic Formula (3 factor) | fundamental_factors.py family_m_fundamental_rank + 7 factor + leakage test | D5 |
| 5/21 Wed | D7 | Bucket B factor batch 2: Beneish M-score (1 + 8 sub) + Altman Z (1 + 5) = 15 factor | family_n_distress + 15 factor + leakage test | D5 |
| 5/22 Thu | D8 | **Bucket B factor batch 3**: buyback/shareholder yield (4) + FCF yield/profitability (4) + revenue momentum (5) + asset growth (2) + DOL (3) + R&D (3) = 21 factor | family_o_capital_return + family_p_growth + family_q_leverage + 21 factor + Bucket B 完成 | D5 |
| 5/23 Fri | D9 | **Bucket C**: sector_map.yaml + sector_resolver.py + family_l_sector_relative (5-7 factor) | config/sector_map.yaml + 5 factor | 无 (但好把 sector 注册放 Bucket B 后续) |
| 5/24 Sat | — | (rest) | | |
| 5/25 Sun | — | (rest) | | |
| 5/26 Mon | D10 | **Macro**: fred_provider.py + macro_panel.parquet ingest + family_r_macro (5-7 factor) + **All-bucket integration smoke test** | core/data/fred_provider.py + 6 macro factor + integration smoke (Bucket A+B+C+Macro 全部 mining-search-ready) | 全部 |

### Week 3+ (5/27 Tue onwards) — Signal-conf MVP Phase 1

| 周 | 任务 |
|---|---|
| 5/27-6/2 | MVP Phase 1.1 setup detection layer + confirmation_pattern registry skeleton |
| 6/3-6/9 | MVP Phase 1.2 TTL gate + setup→trigger state machine |
| 6/10-6/16 | MVP Phase 1.3 leakage test + smoke on Bucket A/B/C/Macro factor 全 candidate |
| 6/17-6/23 | MVP Phase 2 prep — depends on Phase 1 acceptance + Trial 9 TD30 (~6/24) interim check |
| 6/24+ | continue per PRD v1.1 |
| **~8/6** | **Trial 9 TD60 verdict** — pivot decision: cycle #09 unfreeze? PRD-E TAA reactivate? MVP Phase 2/3 spec lock-in? |

---

## 2. Dependency Graph

```
trial9_002 (daily ritual, auto)  ───────────────────────────────────────►  TD60 ~8/6
                                                                            │
                                                                            ▼
                                                                       pivot decision
                                                                       (cycle #09 / PRD-E /
                                                                        MVP Phase 2)

Bucket A (5/13-5/15) ──┬──────────────────────────────────────────────────┐
                       │                                                    │
                       │                                                    ▼
                       └──► Bucket B (5/16-5/22) ──┬─────────────────► Signal-conf MVP
                                                    │                       Phase 1 (5/27+)
                                                    ▼
                                              Bucket C (5/23)
                                                    │
                                                    ▼
                                              Macro (5/26)
                                                    │
                                                    ▼
                                              Integration smoke (5/26 EOD)
```

**Critical path**: Bucket A → Bucket B → Signal-conf MVP Phase 1 (~3.5 weeks Phase 1 + Trial 9 TD60 align at 8/6)
**Parallel ok**: Bucket C 跟 Bucket B 完成后顺序做；Macro 独立可调到 Bucket A 后

---

## 3. Daily Ritual (continues unchanged)

- **NYSE close + 15min (post-16:15 ET)**: `scripts/fetch_data.py` (规则升级后 raise if pre-close)
- **trial9_002 observe**: `dev/scripts/oos_mvp/run_forward_observe.py observe --candidate-id trial9_diversifier_002`
- **options paper observe**: `dev/scripts/options/observe_options_forward.py --candidate-id spy_8otm_bull_put_v1`
- **VRP scan**: `dev/scripts/options/cumulative_vrp_scan.py`

SessionStart hook 已配置；daily_freshness_check.py 会提醒。

---

## 4. Trial 9 TD-Aligned Checkpoints

| TD | 日期估算 | 检查 | 影响 schedule |
|---|---|---|---|
| TD001 | 2026-05-13 EOD | first observe + per_cell_digest 非空验证 | 无 (planned) |
| TD010 | 2026-05-27 | attention_check.py 第一轮 | Signal-conf MVP Phase 1 启动同日；时间巧合 |
| TD020 | 2026-06-10 | TD20 milestone — residual NAV corr 60d preview | MVP Phase 1.3 期间 |
| TD030 | 2026-06-24 | storage cost validation (~10 MB 预算) | MVP Phase 2 前 1 周 |
| TD040 | 2026-07-09 | 60-day forward 中点 | |
| TD060 | **2026-08-06** | **GREEN/YELLOW/RED 决定** | **Phase 2 spec lock-in / pivot decision** |

---

## 5. Stop Rules / Risk Triggers

1. **Trial 9 forward RED (TD60 不达标)**：
   - Signal-conf MVP Phase 1 仍 proceed（独立项目，因子库扩展不依赖 Trial 9）
   - cycle #09 mining 仍 frozen 直到用户 directional
   - PRD-E TAA reactivation 撤销
   - Pivot decision: 是否在新因子库上做 cycle #09，或重新设计实验

2. **Bucket A 实测 ROI 弱（leakage test 中 60% 因子 IC|<0.005|)**：
   - 减速；批 2-3 整合到 batch 1，先看 batch 1 结果再决定
   - 但仍 ship 进 RESEARCH_FACTORS（library expansion 不 require IC 阈值；mining 时再筛）

3. **Bucket B SEC EDGAR 实测 universe 覆盖 < 70/78**：
   - 检查 ADR (ASML / TSM) ifrs-full taxonomy；ETF (TLT / GLD / SHV / BIL / etc) 本来就没 EDGAR
   - ETF 部分用 NaN + factor-guard (跟现有 trades_backfill volume-sensitive guard 一致)
   - Universe-side 决定哪些 ETF 跳过 fundamental factor

4. **Macro 实测 FRED rate limit or 缺关键 series**：
   - Fallback to yfinance (^TNX, ^VIX, DXY=X, CL=F)；已有 ingest 路径

5. **Signal-conf MVP Phase 1 工程超期 > 4 周**：
   - 拆 Phase 1 为 1a + 1b，1a (setup detection only) ship；1b TTL gate 后续
   - 不影响 8/6 pivot decision

---

## 6. R1+R2 自审

**Dependencies verified at planning time (2026-05-12 16:00 local)**:
- ✅ `core/factors/factor_generator.py` exists (line counts OK)
- ✅ `core/factors/factor_registry.py` exists (PRODUCTION + RESEARCH 分离)
- ✅ `core/data/bar_store.py` exists (Bucket B 不依赖此但 sector resolver 可能需要 daily close for market_cap)
- ❌ `data/fundamentals/` → 需 mkdir
- ❌ `dev/scripts/fundamentals/` → 需 mkdir
- ❌ `core/data/edgar_provider.py` → new file
- ❌ `core/data/fundamentals_store.py` → new file
- ❌ `core/factors/fundamental_factors.py` → new file
- ❌ `config/sector_map.yaml` → new file
- ❌ `core/data/sector_resolver.py` → new file
- ❌ `core/data/fred_provider.py` → new file
- ❌ `core/factors/macro_factors.py` → new file

**Logical consistency**:
- ✅ Bucket A 不依赖 Bucket B/C/Macro 数据（纯 OHLCV）
- ✅ Bucket B 不依赖 Bucket A factor（独立数据 ingest），但 Bucket B fundamental_factors registry 应紧跟 Bucket A 注册（避免 factor_registry.py 双 PR / merge conflict）
- ✅ Bucket C sector_resolver 依赖 close × shares for market_cap (Altman Z + Magic Formula 使用)，但 sector_relative factor 本身只需 OHLCV + sector_map.yaml；C 可独立于 B (但顺序上 B 先 ship 让 sector cross-check 有 fundamental data)
- ✅ Macro 完全独立 (FRED is non-equity data; no factor cross-dependency)
- ✅ Signal-conf MVP 用 expanded RESEARCH_FACTORS — 需 Bucket A 至少 batch 1 ship；Bucket B+C+Macro nice-to-have but Phase 1 not blocking
- ✅ Trial 9 forward 100% independent — daily ritual

**No invariant breakage**:
- ✅ long-only / no-short / no-margin 全部维持 (Bucket A/B/C/Macro 都是 cross-sectional rank factor 加进现有 long-only top-N selector)
- ✅ Benchmark rule (SPY hard, QQQ diagnostic) 维持
- ✅ Pricing semantics (adjusted close / T+1 open execution) 维持
- ✅ Stop rule for cycle04-08 maintained — 新因子库扩展是 library expansion 不是 mining cycle 启动

---

## 7. Open Risks / Audit Targets

1. **EDGAR rate limit**: SEC documented < 10 req/sec。78 sym × 1 companyfacts call ≈ 8 seconds with safe spacing。**实测 D4 后确认**。
2. **EDGAR ADR coverage** (TSM / ASML): may use ifrs-full not us-gaap。**实测 D4 后 fallback strategy**。
3. **EDGAR ETF coverage**: TLT / GLD / SHV / BIL / IEF — 应该 EDGAR 不覆盖 (无 us-gaap filings)。**Bucket B factor for ETF = NaN + factor-guard mask**。
4. **Sector reclassification**: 78-sym universe 中 known reclassification (TSLA 2020-12-21 / META 2022 etc) — 手动 curate 时 cover；**D9 sector_resolver.py PIT logic test critical**.
5. **Macro data revision**: FRED revises CPI / GDP historical — 跟 EDGAR PIT 一样需要 filed_date / revised_date 处理。**D10 fred_provider PIT 测试**。
6. **Storage**: data/fundamentals/edgar_cache/ ~285 MB + macro_panel ~10 MB + Bucket A 因子计算物（runtime）≈ 300 MB 新增。可接受。
7. **PRD-E TAA reactivation**: macro factor ship 后 TAA framework 可 reactivate (per CLAUDE.md PRD-E v1.1 Phase 2 PASS 5/7 gates)。Decision 留到 Trial 9 TD60 GREEN。

---

## 8. Commit + Push Discipline

**Per workstream commit cadence**:
- Bucket A: 1 commit per batch (3 commits total, 5/13 / 5/14 / 5/15)
- Bucket B: 4 commits (prep 5/16 / store 5/19 / fundamental rank 5/20 / distress 5/21 / capital return 5/22)
- Bucket C: 1 commit (5/23)
- Macro: 1 commit (5/26)
- Integration smoke: 1 commit (5/26 EOD)
- Total: ~11 commits over 2 weeks

**Branch strategy**: ALL on main (per CLAUDE.md no feature branch policy; small-step verifiable patch).

**Test discipline**: 每 commit 必跟 unit test (per factor leakage test + per provider PIT test)。

**Self-audit**: 每 commit 跟 R1+R2 (R3+R4 全 stream 完成时一次性，per [feedback_self_audit_methodology.md] 4 层 R3 永不跳过)。

---

## 9. Acceptance — 全 stream done 时

| 指标 | 目标 |
|---|---|
| Bucket A factor count | 28 (实际可能 25-30) |
| Bucket B factor count | 43 (实际可能 35-45 depending on EDGAR universe coverage) |
| Bucket C factor count | 5-7 |
| Macro factor count | 5-7 |
| RESEARCH_FACTORS total | 71 → 71+~80 ≈ 150 (前后比较) |
| pytest pass count (新增 leakage tests) | ~80+ new unit tests |
| Integration smoke | mining-search-ready (run_research_miner.py 可 sample 全部 family) |
| Daily ritual 不中断 | Trial 9 + options paper continue |
| Trial 9 TD60 alignment | 5/27 起 MVP Phase 1 → 8/6 verdict |

---

## 10. References

- 决策来源 user message 2026-05-12 ~17:30 local: "用这个组合 Q1+Q2+q3+q4 yes"
- 上游 lit review: `docs/memos/20260512-quant_factor_literature_synthesis_v2.md`
- Signal-conf PRD: `docs/prd/20260512-signal_confirmation_mvp_prd.md`
- Trial 9 forward state: CLAUDE.md §"trial9_diversifier_002" + `data/research_candidates/trial9_diversifier_002_forward_manifest.json`
- Options paper state: CLAUDE.md §"Options Research Track" + `data/options/paper_runs/spy_8otm_bull_put_v1/`
- Factor 文献 inventory: 上游 lit synthesis §2 + §7 (37 topic ~50 paper)
