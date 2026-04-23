# feat-v1 Expanded-Mining Ralph-Loop — Final Report

**Date**: 2026-04-23
**PRD**: `docs/20260423-prd_research_feature_engineering_and_expanded_mining.md`
**Ralph-loop range**: 17 rounds executed (spec max 16; stop-hook continued). R01-R11 core PRD execution; R12-R17 buffer rounds added incremental tooling fixes, pool scans, and deeper regime analysis.
**Lineage tag**: `post-2026-04-23-feat-v1-expanded`
**Completion status**: Step 1-4 + 6-7 COMPLETE; Step 5 BLOCKED per §15.3 halt condition 7 (awaits user decision)
**Commit range**: `06cc07a..829d56b`

---

## 0. Executive summary

| PRD step | Status | Evidence |
|---|---|---|
| 1. Feature engineering | ✅ COMPLETE | R01-R05: 11 new factors + 3 masks + cc/oc/oo labels; 1215 → 1262 tests (+47, 0 regression) |
| 2. Panel build sanity | ✅ COMPLETE | R06: 79-sym × 3460-bar panel; all factors finite; aliases identity-verified |
| 3. R39 fresh baseline mining | ✅ COMPLETE (result negative) | R07+R08: 80 trials / 65 archived / 0 OOS pass |
| 4. Top-K structural analysis | ✅ COMPLETE | R08: analyzer script + cross-lineage comparison |
| 5. R40 regime / R41 acceptance | ⛔ BLOCKED | §15.3 condition 7 triggered: n_oos_pass == 0 AND all oos_ir < 0 |
| 6. DSL fast-exit ablation | ✅ COMPLETE | R09: +0.91pt CAGR on feat-v1 best spec (consistent with pre-PRD) |
| 7. LLM sidecar | ✅ COMPLETE | R10: 5 candidates funneled, 0 KEEP (strongest IR +0.25) |

**Bottom line**: Feature-engineering deliverables all landed cleanly.
R39 mining on expanded universe produced **strictly worse** OOS results
than pre-PRD sampling of the same MultiFactorSpace, triggering the
designed halt. Root cause is **Optuna sampling variance over an
unchanged 7-PRODUCTION-FACTOR space** — new R01-R05 research factors
cannot enter the mining sampler without modifying `PRODUCTION_FACTORS`
(PRD §4 forbidden) or extending `MultiFactorSpace` (PRD §15.4 forbidden
autonomously).

---

## 1. Ralph-loop round-by-round summary

| Round | Commit | Step | Delta |
|---|---|---|---|
| R01 | `2e5acf6` | 1 | Returns family: `base_returns.py` + 4 factors (ret_1d, ret_2d, overnight_ret_1d, intraday_ret_1d) + 8 tests |
| R02 | `47fa0e4` | 1 | Volatility/Range: `base_volatility.py` + hl_range + dollar_vol_20d + 2 aliases (vol_20d, volume_ratio_20d) + 9 tests |
| R03 | `822b114` | 1 | Relative/Position: `base_relative.py` + ret_5d + dist_52w_high + rel_spy_5d + 10 tests |
| R04 | `cefc76f` | 1 | `compute_forward_returns` mode extension (cc/oc/oo) + 11 tests |
| R05 | `4eea421` | 1 | `base_masks.py` + price_floor_mask + tradable_mask_dollar_vol + research_mask + 9 tests |
| R06 | `75ba4b1` | 2 | 79-sym panel sanity + IC_5d smoke; `feat_v1_panel_sanity.md` |
| R07 | `30afdb5` | 3 | Mining launched (background) + `feat_v1_topk_analysis.py` |
| R08 | `e194b1d` | 3-4 | Mining finished; halt condition 7 triggered; blocker doc |
| R09 | `ef94686` | 6 | DSL ablation on df22a253dda6: +0.91pt CAGR, -0.51pt MaxDD |
| R10 | `829d56b` | 7 | LLM sidecar on 5 candidates; regime_selectivity_spread_63d strongest |
| R11 | `7d0043c` | 15.6 | Final report (this file) |
| R12 | `c7ca965` | 7.fix | Leakage heuristic: +`rolling_` / `cumsum` / `cumprod` / `ewm(` / `.ewm` lag keywords; +3 tests |
| R13 | `40d3469` | 1.fix | `factor_engine.make_forward_returns` cc/oc/oo symmetric with R04 (evaluator-internal); +6 tests |
| R14 | `1f2f01a` | doc | Final report refresh for R12-R13 |
| R15 | `208d8a0` | 7.scan | 97-pool R12-heuristic flip scan: 5 flip, 1 new NEEDS_HUMAN_REVIEW (regime_adjusted_quality_63d_gemini) |
| R16 | `4a66c27` | 7.fix | Funnel CLI passes OHLCV to compute_fns; 2 of 3 previously-blocked candidates now properly evaluated |
| R17 | `0855d8f` | 6.deep | Regime-stratified IC on R01-R05: reversal direction stable across 6 regimes, amplified 30-50% in CRISIS / RISK_OFF |

Log entries: per-round 11-part Chinese reports in `docs/20260420-ralph_loop_log.md::R-feat-v1-round-NN`.

---

## 2. Deliverables vs PRD §10 success criteria

### §10.1 Feature Engineering (target: check all)

| Criterion | Status | Evidence |
|---|---|---|
| 10 research features 补齐 | ✅ +11 net | ret_1d, ret_2d, overnight_ret_1d, intraday_ret_1d, hl_range, dollar_vol_20d, ret_5d, dist_52w_high, rel_spy_5d, vol_20d (alias), volume_ratio_20d (alias) |
| compute_forward_returns cc/oc/oo | ✅ | 11 tests verify each mode + shape + NaN semantics |
| per-date-per-symbol mask | ✅ 3 masks | price_floor_mask / tradable_mask_dollar_vol / research_mask |
| 15+ 单测 | ✅ +47 | Target 15; actual 47 |
| 不改 PRODUCTION_FACTORS | ✅ | 7 unchanged throughout 11 rounds |

### §10.2 Mining (target: improved top-K)

| Criterion | Status | Evidence |
|---|---|---|
| unique spec 数量上升 | ❌ | 65 archived vs pre-PRD 70 |
| top-K 突破旧因子簇 | ❌ | family distribution identical (quality / relative / mom dominate both runs) |
| 1-3 improved 候选 | ❌ | 0 OOS pass vs pre-PRD 1 |
| 足够进 R40/R41 | ❌ | halt condition 7 triggered → Step 5 blocked |

### §10.3 研究价值 (target: direction signals)

| Signal | Status |
|---|---|
| Expanded universe 打开搜索空间? | Inconclusive — sampling variance dominates; same 7-factor space means "expanded universe" alone doesn't create new signal without new factors in sampler |
| 新 feature family 进 top specs? | No — research factors aren't in sampler; by PRD design |
| DSL 仍正贡献? | ✅ +0.91pt CAGR (consistent across 2 specs) |
| 方向更清晰? | ✅ Very — blocker doc §4 lists 4 concrete paths (A/B/C/D) for user decision |

---

## 3. Halt trigger details

§15.3 condition 7: "Step 3 R39 fresh mining 跑完后，若 n_oos_pass == 0
AND 所有 trial 的 OOS IR 均 < 0（严格劣于 pre-PRD 旧结果），halt 并
写入 blocker 文档，等用户确认是否进 Step 5 或重新设计".

Both clauses true. Pre-PRD `post-2026-04-22-deep-R38-stage12` (commit-
time state before R39 C+ rerun): 1 OOS pass, best oos_ir +0.343. This
feat-v1 R39: 0 OOS pass, best oos_ir -0.119.

Details in `docs/20260423-feat_v1_r39_blocker.md`.

---

## 4. User-decision items (Step 5 gated)

Per blocker doc §4, 4 paths forward:

- **A**: Extend `MultiFactorSpace.suggest()` to sample R01-R05
  research factors. Highest information gain. Requires new user
  authorization (modifies PRODUCTION_FACTORS flow).
- **B**: Rerun R39 with larger trial budget (300-500) to beat Bernoulli
  pass-rate variance. Cheap; does not extend space.
- **C**: Add Stage 3 universe (10 BETA_PLUS_ALPHA). Requires
  `config/universe.yaml` edit authorization.
- **D**: Accept as direction confirmation; close feat-v1 PRD; pivot
  to microstructure / new data (synthesis §Priority C).

---

## 5. Artifacts inventory (what user can inspect)

### Code (git-tracked)

| Path | Purpose |
|---|---|
| `core/factors/base_returns.py` | Returns family primitives |
| `core/factors/base_volatility.py` | hl_range + dollar_volume_ma |
| `core/factors/base_relative.py` | dist_from_rolling_max + relative_return |
| `core/factors/base_masks.py` | Per-date masks |
| `core/factors/factor_generator.py` | Hooks: `_baseline_return_factors`, `_baseline_range_factors`, `_baseline_relative_factors`, `_apply_research_aliases` + `compute_forward_returns(mode=)` |
| `core/factors/factor_registry.py` | +11 new RESEARCH_FACTORS entries |
| `tests/unit/factors/test_base_returns.py` | 8 tests |
| `tests/unit/factors/test_base_volatility.py` | 9 tests |
| `tests/unit/factors/test_base_relative.py` | 10 tests |
| `tests/unit/factors/test_base_masks.py` | 9 tests |
| `tests/unit/factors/test_forward_returns_modes.py` | 11 tests |
| `scripts/feat_v1_topk_analysis.py` | Top-K mining analyzer |

### Docs (git-tracked)

| Path | Purpose |
|---|---|
| `docs/20260423-prd_research_feature_engineering_and_expanded_mining.md` | Source PRD |
| `docs/20260423-feat_v1_panel_sanity.md` | Step 2 Phase A sanity report |
| `docs/20260423-feat_v1_r39_blocker.md` | Step 3-4 blocker doc (§15.3 halt condition 7) |
| `docs/20260423-feat_v1_expanded_final_report.md` | This file |
| `docs/20260420-ralph_loop_log.md` | R01-R10 11-part Chinese round logs |

### Runtime state (gitignored)

| Path | Note |
|---|---|
| `data/mining/archive.db` | 65 trials, lineage `post-2026-04-23-feat-v1-expanded` |
| `data/mining/optuna.db` | Fresh study post-R07 C+ |
| `data/mining/archive.db.bak.20260422_233325` | pre-R07 backup (pre-PRD R39 state) |
| `data/mining/optuna.db.bak.20260422_233325` | same |
| `data/ml/llm_sidecar_r10/*/` | 5 candidate funnel outputs |
| `logs/mining/R39_feat_v1_1776926011.log` | Full mining trace |

### Test state

- **1271 passed, 1 skipped, 1 xfailed** (from 1215 baseline pre-feat-v1, +56 new)
- 0 regression
- Pre-existing xfail (`TestQQQOutperformance::test_full_period_cagr_beats_qqq`) unchanged

---

## 6. Recommended next user action

**Tier 1 (minutes)**: Read `docs/20260423-feat_v1_r39_blocker.md` §4
options. Pick A / B / C / D.

**Tier 2 (if A)**: Draft PRD addendum authorizing MultiFactorSpace
extension. Define which subset of R01-R05 research factors enters
mining (leakage check + promotion flow implications).

**Tier 2 (if B)**: 
```bash
# Append more trials to same lineage (no fresh study — keep current)
python scripts/run_mining.py --trials 300 --budget 10800 \
  --type multi_factor \
  --lineage-tag post-2026-04-23-feat-v1-expanded-b-extended
```
~3 hours runtime. Cheap hedge.

**Tier 2 (if C)**: Review R38 proposal doc Stage 3 (10 BETA_PLUS_ALPHA)
and edit `config/universe.yaml`.

**Tier 2 (if D)**: Close feat-v1 PRD. Author microstructure PRD per
deep-mining R50 synthesis §Priority C.

---

## 7. Loop honest assessment

Every PRD-scoped autonomous step that can be done WITHOUT user
intervention has been done. Halt-condition 7 is specifically designed
to pause for user input rather than have the loop make a strategic
decision beyond its authority. No action in R12-R16 can advance the
top-level goal (close PRD §10.2 mining success criteria) without user
input. The loop has reached its legitimate stopping point.

Feature-engineering deliverables are solid; mining is empirically
stuck in the same place deep-mining R50 concluded. The path forward
is a human decision, not more iterations.

---

*Final report v1.0. Ralph-loop exits via FEATV1DONE promise.*
