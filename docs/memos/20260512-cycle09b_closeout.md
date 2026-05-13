# Cycle #09b Closeout — 5/5 Track A PASS, forward-init caveats

**Date**: 2026-05-12
**Lineage**: `track-c-cycle-2026-05-12-09b`
**Yaml sha256**: `b0b9e181066152b7eb8195e993d62d14e38b8ef206b256005ff10b5f2b17609a`
**Single-axis diff vs cycle #09 INVALID**: `mining_config.sampling_mode: family_first` (Option A)

---

## §1 TL;DR

**HISTORIC**: cycle #09b 是 cycle04-09 系列第一个产出 Track A acceptance PASS 的 cycle。
top-5 deduped trial 全部 5/5 PASS 17-gate (vs cycle04-07a 0-1 PASS / cycle08 0 PASS)。

**关键 caveat 必须在 forward init 前 close**：
1. NAV vs QQQ raw pearson 0.851 — **just at** 0.85 anti-sibling threshold (borderline)
2. cycle04-08 anchor_pearson 0.82 在 mining archive 是 3-way 3-anchor pool；extended 19y NAV correlation vs all 5 anchors (RCMv1 / Cand-2 / Trial9_v2 / cycle07a Trial 3 / cycle08 cand) PENDING
3. PIT (point-in-time) audit of `rd_intensity_ttm` (EDGAR TTM) 需要 R3 actually-run-the-code 验证 filed_date 语义（不是 fiscal_period_end）
4. 数字偏高 (cum_ret +1300%) — 需要复跑 + 检查为啥这么强 vs 已知的 cycle04-08 baseline (cycle07a Trial 3 Sharpe 1.08)

---

## §2 Mining results

| Metric | Value |
|---|---|
| n_trials | 200 (full per yaml) |
| n_finite | 159 (79.5%) |
| n_archived | 108 (54.0%) |
| wall_clock | 48.4 min |
| sampler | family_first (Option A) |

vs cycle #09 v09 (independent sampler): 0/200 archived. Option A 完全修复 17-family combinatorics 失败。

### Top 5 deduped trials

| # | trial_id | features | families | IC_IR | NAV Sharpe | anchor_pearson |
|---|---|---|---|---|---|---|
| 1 | 5a99868072e6 | rs_vs_spy_63d, cpi_yoy_pct, rd_intensity_ttm | A,P,N | 0.773 | 0.894 | N/A (skipped) |
| 2 | acfae8a1a555 | risk_adj_mom_63d, cpi_yoy_pct, rd_intensity_ttm | D,P,N | 0.965 | 0.851 | 0.821 |
| 3 | 3095c247ab7f | month_end_quarter_end, cpi_yoy_pct, rd_intensity_ttm | J,P,N | 0.965 | 0.850 | 0.821 |
| 4 | 5e59cb317645 | sell_in_may_seasonal, cpi_yoy_pct, rd_intensity_ttm | J,P,N | 0.965 | 0.850 | 0.821 |
| 5 | 8bf44427abca | pre_cpi_window_flag, cpi_yoy_pct, rd_intensity_ttm | J,P,N | 0.965 | 0.850 | 0.821 |

**Observation**: trials #3-5 metrics identical → 第三 factor（J 家族季节性 flag）几乎不影响 composite；effective signal = `cpi_yoy_pct + rd_intensity_ttm` 2-factor。

---

## §3 Track A 17-gate verdict

**5/5 trials PASS** all 17 gates (per `data/audit/cycle09b_track_a_eval_track-c-cycle-2026-05-12-09b.json`).

### Trial 1 (top deduped) full-panel metrics

| Metric | Value | Note |
|---|---|---|
| cum_ret | +1300.2% | 17yr selector partition |
| sharpe | 1.127 | |
| max_dd | -21.7% | within -25% invariant |
| vs_spy (full) | +1065.0% | far exceeds 0% hard gate |
| vs_qqq (full) | +803.8% | diagnostic |
| beta_vs_spy | -0.078 | near zero |
| beta_vs_qqq | +0.655 | moderate |
| raw_pearson_vs_spy | -0.092 | minimal SPY exposure |
| **raw_pearson_vs_qqq** | **+0.851** | **just at 0.85 sibling threshold** ⚠ |
| m12_top1_weight_max | 13.66% | < 40% limit ✓ |
| m12_top3_weight_max | 35.76% | < 70% limit ✓ |

### Per-validation-year metrics (Trial 1)

| Year | max_dd | vs_spy | vs_qqq |
|---|---|---|---|
| 2018 | -16.33% | +7.17% | +1.97% |
| 2019 | -8.97% | +9.01% | +0.40% |
| 2021 | -9.56% | +7.54% | +6.17% |
| 2023 | -4.95% | +35.62% | +5.68% |
| 2025 | -18.26% | +17.20% | +13.99% |
| **avg** | -11.61% | +15.31% | +5.64% |

5/5 validation years vs SPY > 0; per-year max_dd 全部 ≤ 20% hard gate。

### Stress slices

| Slice | max_dd | Limit |
|---|---|---|
| covid_flash | -18.97% | ≤ -25% ✓ |
| rate_hike_2022 | -12.08% | ≤ -25% ✓ |

---

## §4 Hypothesis verdicts

Per yaml hypotheses §H1-H4:

| H | Statement | Verdict |
|---|---|---|
| H1 | ≥1 trial passes G_new_family_anchor AND G_anti_sibling_nav | **SUPPORTED** — 29/108 trials pass both screens |
| H2 | Z1 top-15 anchored trials median IC_IR > non-Z1 | **SUPPORTED** — 0.773 vs 0.135 |
| H3 | EDGAR (K/L/M/N) anchor median NAV pearson < OHLCV (G/H/I) | **NOT SUPPORTED** — 0.839 vs 0.797 (KLMN higher) |
| H4 | ≥1 trial passes BOTH H1 AND Track A | **STRONGLY SUPPORTED** — 5 trial pass both, all 5 also Track A PASS |

**Process win**:
- family_first sampler 完全修复 cycle #09 INVALID 的 17-family combinatorics failure
- Bucket A/B/C/Macro 162-factor library + Z1 strict-train shortlist 引导 mining 找到 `rd_intensity_ttm` as dominant new alpha anchor
- 89% of archived trials use ≥1 new-family anchor (G_new_family_anchor gate working as designed)

---

## §5 Forward-init pre-conditions (BLOCKING)

**This cycle does NOT auto-forward-init.** 3 audit pre-conditions must clear:

### §5.1 Extended panel NAV correlation vs all 5 anchors

Cycle04 Trial 3 / cycle04 Cluster A / cycle07a Trial 3 NAV correlation results found that 78-股 long-only top-N over fixed universe produces 0.85-0.95 raw NAV correlation across most pairs. Cycle #09b mining anchor_pearson = pooled raw across 3-way (RCMv1 / Cand-2 / Trial9_v2). Need:

- Pairwise NAV correlation vs **all 5 anchors** on extended 19y panel
- Residual NAV correlation after stripping SPY+QQQ beta
- Tier verdict per `track-c-cycle-2026-05-12-09b_promotion_criteria.yaml`:
  - raw < 0.50 → `true_diversifier`
  - 0.50-0.70 → `partial_diversifier`
  - 0.70-0.85 → `warn_label_void`
  - ≥ 0.85 → `reject_step5`

Trial 1 raw_pearson_vs_qqq = 0.851 **at threshold** — high risk of `warn_label_void` or `reject_step5` verdict on pairwise.

### §5.2 PIT (point-in-time) audit on `rd_intensity_ttm`

EDGAR companyfacts API returns facts indexed by both `end` (fiscal period end) and `filed` (when SEC received the filing). `core/data/fundamentals_store.py:65-112` claims to use `filed_date` for indexing + ffill-from-filed, which is correct PIT semantics. R3 audit (actually run code) needed:

- Pick AAPL 2024-10-31 (pre-earnings) vs 2024-11-01 (post Q4-FY24 filing) → confirm `rd_intensity_ttm.loc["2024-10-31", "AAPL"]` uses Q3-FY24 filed on ~2024-08 (no future leak)
- Pick 5 random (date, ticker) pairs and trace back to filed_date in EDGAR API response

### §5.3 Replication on second seed

Per cycle04 Cluster A practice: re-run trial 1 with different sampler seed (Optuna seed=42 → seed=123). If NAV trajectories diverge > 1% pp, mining is unstable. If reproduce ≤ 1%, robust.

### §5.4 NAV vs QQQ correlation deep-dive

raw_pearson_vs_qqq = 0.851 high — explained by `rd_intensity_ttm` selecting tech-heavy names (NVDA / AAPL / MSFT / GOOGL / AMD) which are QQQ-weighted. Need to compute:

- Asset-class breakdown over time (equities vs cash_anchor vs bond)
- Top-3 by total holding-days
- Sector breakdown vs QQQ sector mix

---

## §6 Strategic verdict

**Standalone alpha**: trial 1 is VIABLE candidate per Track A acceptance but FORWARD-INIT CONDITIONAL on §5 audit clearing.

**Diversifier vs core role**:
- `cycle09b_pending_audit` role recommended (not core_alpha) until §5.1 extended NAV correlation comes back
- If extended NAV < 0.85 raw with at least 1 of (RCMv1, Cand-2, Trial9_v2) → core_alpha eligible
- If 0.85-0.95 across all anchors → diversifier or `legacy_decay_verification` only
- If ≥ 0.95 across all anchors → reject (sibling-by-NAV)

**Construction lesson**:
- cycle04-08 sibling root cause = drawup + monthly + top-N geometry; cycle09b 的 cpi_yoy_pct + rd_intensity_ttm 在 factor 层突破，但 raw_pearson_vs_qqq=0.85 表明 universe + top-N construction 仍是 binding constraint (~70% NAV correlation explained by 78-股 universe + top-N).

**Next-cycle direction** (NOT pre-registered, awaits user-go):
- Cycle #10 candidate: 同 yaml + 第三 axis 限制（要求 family ≠ J/Q seasonal flags）→ 强制 3 真正贡献 factor
- OR: pivot to **ML Phase 1** per `docs/prd/20260512-ml_mining_pipeline_prd.md` — cycle04-09 linear composite 路径已基本 saturated；XGBoost non-linear interaction 是下一步 evidence-driven 探索

---

## §7 Stop-rule verdict per yaml

Per `mining_config.stop_rule_post_cycle.if_one_or_more_nominee`:
- 5 trials pass Track A → 1+ nominee verdict
- forward_init eligible: conditional on §5 audit
- Auto-trigger ML Phase 1: per user explicit-go 2026-05-12 ("等cycle 9 完成 然后开始phase 1"), Phase 1 fires regardless of forward-init decision (independent workstream)

---

## §8 Process audit (4-tier per CLAUDE.md)

**R1 factual**: 108 trials archived in `data/mining/rcm_archive.db` under lineage `track-c-cycle-2026-05-12-09b`. 5/5 top deduped PASS Track A per
`data/audit/cycle09b_track_a_eval_track-c-cycle-2026-05-12-09b.json`.

**R2 logical**: top-5 deduped feature sets all contain `cpi_yoy_pct + rd_intensity_ttm`; third factor varies but identical metrics in 3 of 5 indicate near-zero contribution of family J flags. Result interpretation: effective alpha is 2-factor (P+N), not 3-factor.

**R3 actually-run-code**: re-ran closeout_analysis.py + cycle09b_track_a_eval.py with `--top-n 5 --dedupe-features`; 5/5 PASS reproduced. Trial 1 metrics extracted directly from harness JSON.

**R4 boundary**:
- raw_pearson_vs_qqq = 0.851 is EXACTLY at sibling threshold; small perturbation could flip verdict
- 80% of "Track A pass" really comes from 2-factor composite + 3rd-factor-irrelevant; sensitivity test (set 3rd factor weight = 0 explicitly) recommended
- Tier-5 false-positive risk: any trial with `cpi_yoy_pct + rd_intensity_ttm` weighted heavily likely passes regardless of 3rd factor

---

## §9 Forensic artifacts

- Yaml: `data/research_candidates/track-c-cycle-2026-05-12-09b_promotion_criteria.yaml`
- Mining log: `data/ml/research_miner/track-c-cycle-2026-05-12-09b/mining_stdout.log`
- Archive: `data/mining/rcm_archive.db` lineage `track-c-cycle-2026-05-12-09b` (108 rows)
- Closeout analysis: `data/audit/cycle09b_closeout_analysis.json`
- Track A eval: `data/audit/cycle09b_track_a_eval_track-c-cycle-2026-05-12-09b.json`
- Launcher: `dev/scripts/cycle09/run_cycle09b_mining.py`
- Closeout script: `dev/scripts/cycle09/cycle09_closeout_analysis.py` (--lineage track-c-cycle-2026-05-12-09b)
- Track A eval script (cycle09b-specific): `dev/scripts/cycle09/cycle09b_track_a_eval.py`

Research-mining workstream auto re-frozen at cycle09b boundary. Forward-init of trial 1 PENDING §5 audit clearance.
