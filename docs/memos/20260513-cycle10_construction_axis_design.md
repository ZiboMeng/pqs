# cycle10 Construction-Axis Design — C10-2-A

**Date**: 2026-05-13
**Lineage**: `cycle10-construction-axis-v1`
**Authority**: User explicit-go 2026-05-13 (ML-1 + C10-2 combined approval)
**Parent**: cycle09b §5.3 strategic finding (`docs/memos/20260513-cycle09b_audit_amendment.md` §9.5)
**Pre-audit baseline**: `data/audit/preflight_baseline_20260513.json` (git HEAD 08fc66c)

---

## §1 TL;DR — 人话版

cycle04-09b 在 NAV 层 sibling-by-construction 的 root cause 已经被 §5.3
empirically confirmed = 不是 factor pool，是 cap_aware_cross_asset + monthly +
top10 + 79-sym universe 的 construction 本身。

C10-2-A 在 harness 加 1 个新 construction mode，不动其他 4 个（global_top_n,
cap_aware, cap_aware_cross_asset, ML 用的内部 paths）。目标：**测试
weighting scheme 是不是 binding axis**。

新增 mode：**`cap_aware_risk_parity`** —— 选股逻辑跟 `cap_aware_cross_asset`
一样（cluster_cap + asset_class_caps binding），但 **权重 ∝ 1/vol_60d** 而
不是 equal-weight。

---

## §2 Why risk-parity weighting

cycle04-09b 的 sibling-by-construction 病灶有几层：

| 层 | Binding? | Test in cycle10? |
|---|---|---|
| Universe (79 syms) | binding (§5.3 0/3 factor overlap → NAV 0.761) | C10-2-B (multi-universe) |
| Top-N selection (top10) | unknown | Future cycle11+ (top-20? top-5?) |
| **Weighting (equal)** | **unknown — never tested** | **C10-2-A (this memo)** |
| Cadence (monthly) | partially tested by cycle08 weekly (also failed) | Future cycle |

equal-weight 是 cycle04-09b 所有候选用的 default。改成 vol-weighted 让低波动
名字（bonds, gold ETF）获得更高权重，理论上：
- **打破 sibling**: 不同 candidates 选不同股 → 不同 vol → 不同 weight 分布
  → NAV 轨迹 sensitivity 增加
- **降 portfolio vol**: vol-weighted by inverse-vol = risk-parity allocation
- **可能减弱 alpha**: equal-weight 给每个 selected name equal expected return
  share; risk-parity 倾向 low-vol = low-expected-return 也许？

**Operator 假设**: cycle04-09 sibling-by-construction 中，equal-weight 是
让 portfolio NAV 由"全 top10 名字 average return" 主导的关键设计决策。改成
inverse-vol weighting 让 portfolio NAV 更依赖低 vol 名字的 contribution，可能
打破 NAV-by-universe-floor 等价类。

---

## §3 Design — `cap_aware_risk_parity` construction mode

### §3.1 Selection (unchanged from cap_aware_cross_asset)

每次 rebalance:
1. 按 composite score 排序所有 mask-passing 名字
2. 贪心选 top-N（target_n=10）
3. 受 cluster_cap=0.20 + asset_class_caps + max_single_weight=0.10 约束
4. 同 cap_aware_cross_asset，停在 N=10 picks 或 caps binding

### §3.2 Weighting (NEW — replaces equal weight)

对选中的 top-N 名字 (假设 K ≤ 10 名)：

1. 对每个名字 i，计算过去 60 day 的 daily return volatility `σ_i`
   (excludes selected date itself; uses [t-60, t-1] window)
2. Raw weight `w_i_raw = 1 / σ_i`
3. Normalize: `w_i = w_i_raw / sum(w_raw)` so `sum(w_i) = 1`
4. **Cap clipping**: 若 `w_i > max_single_weight`，clip 到 max_single_weight
   再 redistribute residual to remaining names proportionally to 1/σ
5. **Cluster cap re-check**: cluster_cap 仍 enforced（如果 risk-parity weight
   推 cluster 总和超 0.20，则 redistribute）

### §3.3 Edge cases

- **σ_i = 0 或 NaN**: 给 default weight `1/median(σ_top_N)`（避免除 0 引爆）
- **<60 day history**: 用 max(available_days, 20) 算 vol；< 20 → fall back equal-weight
- **Cluster cap binding under risk-parity**: 先 cap clipping for single names，
  再 redistribute by 1/σ within each cluster；若 cluster cap still binding，
  proportional reduce across the cluster

### §3.4 Construction parity invariant

`construction_mode='cap_aware_risk_parity'` 跟 `cap_aware_cross_asset` 在
**selection** 阶段产生 identical picks。only **weights** differ。

→ Forensic comparison: same composite_spec on same date → same top-N names
  → only weight column differs。

---

## §4 Implementation plan

### §4.1 Code changes (additive only)

1. **`core/research/harness/composite_evaluator.py`**:
   - Add `"cap_aware_risk_parity"` to `_VALID_CONSTRUCTION_MODES`
   - Add new dispatch branch in `evaluate_composite_spec` (line ~620)
   - Calls existing `topn_signals_with_caps` for SELECTION
   - Calls NEW `reweight_inverse_vol` for WEIGHTING

2. **`core/research/topn_signals.py` (or new module `core/research/risk_parity_weighting.py`)**:
   - New function `reweight_inverse_vol(signals_df, price_df, lookback=60, max_single_weight=0.10, cluster_map=None, cluster_cap=0.20)`
   - Returns DataFrame with same shape as input, weights replaced by 1/vol-normalized

3. **`tests/unit/research/test_cap_aware_risk_parity.py`** (NEW):
   - 6 tests covering: basic 1/vol weight assignment / cap clipping /
     cluster cap re-check / NaN vol handling / short history fallback /
     parity with cap_aware_cross_asset on selection

### §4.2 Code NOT changed

- ❌ NOT modifying any existing construction mode logic
- ❌ NOT modifying any existing test
- ❌ NOT modifying cycle04-09b mining scripts (they use cap_aware* explicitly)
- ❌ NOT modifying Trial 9 v2 manifest (uses cap_aware in forward observation)

### §4.3 Pre-flight check (before implementation)

- `data/audit/preflight_baseline_20260513.json` already locked all critical
  hashes
- New mode `cap_aware_risk_parity` is OPT-IN — existing yaml files don't
  reference it, so existing behavior reproduces exactly

### §4.4 Post-audit check (after implementation)

- Re-run `cycle09b_trial1_extended_nav_correlation.py` (uses 6 NAVs with
  cap_aware_cross_asset + global_top_n + cap_aware) → verify identical
  numbers (5.1 audit pairs match preflight_baseline) → if MATCH = additive
  change confirmed non-disruptive
- Run all 33 ML unit tests → still pass
- Run subset of research harness tests → still pass

---

## §5 Once implemented: cycle10 mining yaml

After C10-2-A code lands, cycle10 mining yaml will be drafted (separate
memo). Yaml hypothesis test:

| Hypothesis | If TRUE → expect |
|---|---|
| Equal-weight is binding axis | Risk-parity candidates have raw NAV < 0.70 vs cycle04-09 anchors (G3 PASS) |
| Universe is binding axis (not weighting) | Risk-parity candidates still raw NAV ≥ 0.70 vs anchors (G3 FAIL) → need C10-2-B universe expansion |

Cycle10 mining will use same 5-anchor reference (RCMv1 / Cand-2 / Trial 9 v2 /
cycle07a Trial 3 / cycle08 top-1) on cycle09b's extended 16y selector panel.

---

## §6 Self-audit (4-tier per CLAUDE.md)

**R1 fact-check**:
- Current `_VALID_CONSTRUCTION_MODES = ("global_top_n", "cap_aware", "cap_aware_cross_asset")` (composite_evaluator.py line 376) — confirmed via grep
- `topn_signals_with_caps` already supports cluster_cap + asset_class_caps + max_single_weight — confirmed via grep
- Phase 1.5 + 1.6 + cycle04-09 NONE use `cap_aware_risk_parity` (doesn't exist yet) — no naming conflict

**R2 logical**:
- Adding new construction mode is fully additive
- Default behavior of all existing yamls + manifests unchanged (none reference new mode)
- New mode is reachable only via explicit yaml opt-in or direct HarnessConfig param

**R3 actually-run-code** (DEFERRED until ML 1.6 sweep finishes; CPU contention safety):
- Will implement after ML 1.6 sweep completes
- Will run 6 unit tests + verify §4.4 post-audit checks

**R4 boundary**:
- σ_i = 0 / NaN / short-history: design covered §3.3
- Cluster-cap-binding under inverse-vol weight: design covered §3.3 (redistribute proportionally)
- cycle04-09 archived results: not affected (different mode)
- Trial 9 v2 forward observation: not affected (still cap_aware, doesn't reference new mode)
- Concentration metrics: top1/top3 thresholds (M12 0.40/0.70) still apply → if inverse-vol pushes a low-vol name's weight too high, will fail concentration gate organically

---

## §7 Implementation order (post-ML-1.6-sweep)

1. (DONE) Pre-flight baseline snapshot
2. (DONE) Phase 1.6 module + sweep driver + smoke
3. (ACTIVE) Phase 1.6 full sweep result
4. **NEXT**: Implement `cap_aware_risk_parity` per §4.1
5. Run §4.4 post-audit regression
6. Commit + push
7. Then C10-2-B multi-universe loader

This memo is design-only; implementation deferred to step 4 above.
