# cycle09b Audit Amendment — Self-Audit of My Own Recommendation

**Date**: 2026-05-13 (post-`docs/memos/20260513-cycle09b_audit_amendment.md`)
**Author**: PQS resident-quant operator (self-critique)
**Trigger**: User instruction 2026-05-13 "按照你的推荐 但先审计一下你自己的推荐和结论"

---

## §1 TL;DR — 我推荐里有 4 个 hole，最大的是 R1 漏 fact-checking

我原 amendment memo + summary 给出的 verdict 框架是错的。详细如下：

| Hole | 严重性 | 影响 |
|---|---|---|
| **#1 R1 fact-checking miss**: 我没读 cycle09b yaml 的全部 NAV gates | **CRITICAL** | 我的"yaml-strict vs cycle07a-locked 二元对立"完全是 strawman；yaml 自己 ratified 了 residual gate (G3) |
| #2 cycle07a-locked 当作 ratified standard 来用 | HIGH | cycle07a memo 自承"D.0 gate revision proposal (provisional, NOT ratified)" |
| #3 cycle10 axis 候选 (b) weekly 已被 cycle08 否定过 (我漏了) | MEDIUM | cycle08 0/3 PASS Track A 已经证 weekly 不解决 problem |
| #4 cycle10 axis 候选 (c) multi-horizon = ML Phase 2 axis | LOW | 不是 linear mining axis，不该列在 cycle10 选项 |

修订后正确 verdict: **Trial 1 = REJECT forward-init per cycle09b yaml's OWN G3 orthogonality gate** (不需要 invoke cycle07a-locked 或其他外部 standard)。

---

## §2 Hole #1 — R1 fact-checking 漏洞（最严重）

### §2.1 我原 amendment 怎么说

amendment memo §3.3 "Yaml-strict (raw-only) verdict":
> "Closeout memo §5.1 thresholds: raw < 0.50 → true_diversifier / 0.50-0.70 → partial_diversifier / 0.70-0.85 → warn_label_void / ≥ 0.85 → reject_step5. Trial 1 max raw across 5 anchors = 0.810 < 0.85 → NOT reject_step5. ... → core_alpha eligible per yaml-strict reading."

amendment memo §3.4 "cycle07a-locked (raw + residual) verdict":
> "PQS 2026-05-07 x.txt locked thresholds（Trial 3 forward-init gate 时引入）... Trial 1: max raw 0.810 ... max residual_vs_spy 0.809 ≥ 0.50 → RED."

我把 "yaml-strict (raw-only)" 跟 "cycle07a-locked (raw + residual)" 当作二元对立，**仿佛 yaml 只规定了 raw thresholds**。

### §2.2 实际 cycle09b yaml 内容（grep 验证）

`data/research_candidates/track-c-cycle-2026-05-12-09b_promotion_criteria.yaml` 实际定义了 **三个** NAV-related gates:

```yaml
# Gate 1 (mining-time, line 227-243):
g_anti_sibling_nav:
  enabled: true
  pairwise_raw_pearson_max: 0.85

# r41_informational (informational tier, line 248-257):
r41_informational:
  apply_anchors: [RCMv1, Cand-2, Trial9_v2]
  classification_thresholds:
    pooled_raw_pearson_lt_0_50:    true_diversifier
    pooled_raw_pearson_0_50_0_70:  partial_diversifier
    pooled_raw_pearson_0_70_0_85:  warn_label_void
    pooled_raw_pearson_gte_0_85:   reject_step5

# Gate 3 (forward-readiness, line 262-271):
g3_orthogonality_gate:
  enabled: true
  blend_anchors: [RCMv1, Cand-2, Trial9_v2]
  raw_threshold: 0.70           # softer than G_anti_sibling_nav hard 0.85
  residual_threshold: 0.50      # residual vs SPY + QQQ beta
  n_floor: 30
  required_top_k_under_threshold: 1
```

**Critical**: G3 orthogonality_gate 是 yaml 自己 ratified 的 residual gate。**raw < 0.70 AND residual < 0.50** 在 ≥ 1 of (RCMv1, Cand-2, Trial9_v2) 必须满足。

### §2.3 Trial 1 实际数字 vs G3

| Pair | raw | residual_vs_spy | residual_vs_qqq | G3 raw < 0.70 | G3 residual < 0.50 |
|---|---|---|---|---|---|
| vs RCMv1 | 0.810 | 0.809 | 0.410 | FAIL ✗ | FAIL ✗ |
| vs Cand-2 | 0.781 | 0.778 | 0.284 | FAIL ✗ | FAIL ✗ (vs_spy) |
| vs Trial9_v2 | 0.744 | 0.742 | 0.235 | FAIL ✗ | FAIL ✗ (vs_spy) |

`required_top_k_under_threshold: 1` = at least 1 of 3 pairs must clear BOTH gates. **0/3 satisfy**. → **Trial 1 FAILS yaml G3 orthogonality_gate**.

### §2.4 Verdict correction

正确 cycle09b yaml-strict (含 G3) verdict:
- G_anti_sibling (mining-time): PASS ✓
- r41_informational tier: warn_label_void (informational only, not blocking)
- **G3 orthogonality (forward-readiness): FAIL ✗**
- **整体 yaml-strict verdict: REJECT forward-init**

不需要 invoke cycle07a-locked / cycle07a-provisional thresholds. cycle09b yaml itself has the answer.

### §2.5 How I missed it

R1 fact-checking 用 grep 时仅搜了 `tier|classify|warn_label_void|reject_step5`，匹配上了 r41_informational 的 raw-only tier，没继续看 yaml 还有什么 gates。Should have searched `gate` 或 `g3` 或 `orthogonality` — but didn't.

**Lesson** (写入 [[feedback_audit_per_round_methodology]]): R1 在 yaml-based judgments 上必须 **enumerate all gates** 在 yaml 里，不只匹配 keyword 命中的几个 sections。

---

## §3 Hole #2 — cycle07a-locked 当作 ratified standard

### §3.1 我原 amendment 怎么说

amendment §3.4: 把 "PQS 2026-05-07 x.txt locked thresholds" 当 binding standard 用在 cycle09b 判断上。

### §3.2 cycle07a 自承

`docs/memos/20260507-cycle07a_trial3_red_verdict_evidence_only.md` (R3 grep verified):

> "D.0 fleet allocator gate revision proposal (provisional, NOT ratified): D.0 (a) currently requires ≥ 2 Track A acceptance nominees; **proposed tightening** to ≥ 2 nominees AND pairwise raw NAV Pearson < 0.85 across all fleet members on cycle04-canonical 16y extended panel."

关键词: **"provisional, NOT ratified"** + **"proposed tightening"**.

cycle07a-locked 不是 forward-going canonical standard, 仅 Trial 3 forward-init gate 的 ad-hoc tightening + 后续提议但未 ratify 的 fleet allocator change.

### §3.3 Verdict correction

invoking cycle07a-locked 在 cycle09b 判断上是 **over-tightening + ratification-bypass**。

实际上不需要：cycle09b yaml 自己有 G3 (§2.4)，足够 reject Trial 1.

---

## §4 Hole #3 — cycle10 axis (b) weekly 已被 cycle08 否定

### §4.1 我原推荐说

summary §"待你决策的 2 个 directional 问题" Q2 cycle10 axis 候选:
> "(b) cycle10 weekly cadence"

### §4.2 事实

cycle08 (track-c-cycle-2026-05-08-01) yaml 中 `holding_freq_choices: [monthly, weekly, daily]`。Mining 40-trial smoke 产出 11 archived。Track A 17-gate evaluator on top-3: 0/3 PASS (closeout §post-fix 9-trial re-eval).

cycle08 top-1 (`8ac6bccbeed1` = `max_dd_126d + mom_252d + reversal_21d`, **weekly**, cap_aware_cross_asset) 已经测过了。Failed validation_aggregate_excess_vs_spy.

### §4.3 Verdict correction

cycle10 axis (b) "weekly cadence" 是 **重复 cycle08 已 fail 的 axis**。不该作为 cycle10 新 axis 候选。

实际可行 axis：
- ban 特定 factor cluster (e.g. cycle05 ban drawup+amihud, cycle10 ban G3-low-orthogonality factors)
- construction-DOF expansion **新维度**（e.g. multi-horizon ensemble within linear composite — 不是 ML — 即每个 stock 同时 score on 21d AND 63d AND 252d combined into single composite weight）
- universe扩展（78 → 200+ stocks，需要 data + universe expansion eng）
- short-relax violates invariant → user-go required

---

## §5 Hole #4 — cycle10 axis (c) multi-horizon = ML axis not linear

### §5.1 我原推荐说

summary Q2 (c): "cycle10 multi-horizon ensemble"

### §5.2 事实

PRD `docs/prd/20260512-ml_mining_pipeline_prd.md` §4 explicitly defines "**Phase 2: Multi-horizon Regression**" — ML pipeline 的 Phase 2 axis (XGBoost multi-output)。

Linear mining "multi-horizon ensemble" 在 PQS 没明确定义 — 现有 mining harness 是 single-horizon (PRD 20260512 ml-pipeline §3.2 spec "21d forward cross-sectional rank return")。

### §5.3 Verdict correction

multi-horizon 是 ML Phase 2 axis,**不是 cycle10 linear mining axis**。Mixing two workstreams is confusing.

correct cycle10 axes (post-Trial-1-REJECT):
- (i) factor-pool refinement (G3-aware mining objective, mining-time residual minimization)
- (ii) construction-mode 新维度 (除了 cap_aware_cross_asset 的 alternative; e.g. risk-parity weight scheme + monthly + top-N)
- (iii) universe expansion (data + screening pipeline; non-trivial eng)

---

## §6 Strategic re-recommendation (修订后)

### §6.1 cycle09b Trial 1 forward-init verdict (修订)

**Per cycle09b yaml's own G3 orthogonality gate: REJECT** ✗

- G_anti_sibling: PASS (mining acceptance)
- r41_informational: warn_label_void (informational)
- G3 orthogonality: FAIL (all 3 yaml-anchored pairs fail BOTH raw < 0.70 AND residual < 0.50 simultaneously)

This verdict is decisive WITHOUT needing to invoke cycle07a-provisional thresholds.

Classification: `legacy_decay_verification` only (not core_alpha, not diversifier, not fleet member).

### §6.2 §5.3 seed=123 result interpretation (post-修订)

§5.3 stability test is **informational, NOT veto-power**:
- Even if seed=123 PASSes (top-1 reproducible) → Trial 1 still REJECT per G3
- Even if seed=123 FAILs (unstable) → adds further evidence for REJECT
- Stability test outcome is informational about cycle09b mining quality, not Trial 1 forward-init eligibility

### §6.3 Next-step strategic options (修订后)

**Recommended sequence**:

1. **Trial 1 closes as `legacy_decay_verification`** in candidate_registry per yaml G3 verdict. No forward init.
2. **Wait Trial 9 v2 TD60 verdict** (~2026-08-06) — currently only diversifier-role candidate; TD60 evidence informs whether diversifier role architecture is viable.
3. **ML Phase 1.5 hyperparameter sweep proceeds in parallel** (user authorized; independent workstream).
4. **cycle10 design DEFERRED until** either (a) Trial 9 v2 TD60 verdict in, OR (b) ML Phase 1.5 results in (~1-2 days). Whichever lands first; pick cycle10 axis informed by that evidence.

**Alternative (not recommended): override G3 gate**:
- Some operators may argue G3's raw<0.70 + residual<0.50 is over-strict; cycle09b 5/5 Track A PASS deserves more weight
- Counter-argument: yaml is the source of truth; if you don't trust G3, change the yaml in NEXT cycle (not retroactive override)
- Override path requires explicit user-go + amendment to immutability_contract

### §6.4 What changes for user Q1 (yaml-strict vs cycle07a-locked)

The original Q1 was based on hole #1 strawman. **No longer relevant** — yaml itself has the answer (G3 says REJECT). cycle07a-locked is not needed.

If user prefers, can re-frame Q1 as: "Override G3 gate (yes/no)" with default = no override.

---

## §7 Was the underlying audit work (§5.1+§5.2+§5.4 scripts + JSONs) correct?

YES. Audit data + scripts + JSON files are correct. The numbers in §3.3 of original amendment are correct. The only error is in **interpretation** — I read the audit data through a 错的 yaml model.

§5.2 (PIT audit) PASS still stands.
§5.1 (5-anchor NAV correlation) raw numbers + residual numbers correct.
§5.4 (QQQ deep-dive) findings about defensive 29.2% non-equity correct.

**Just the synthesis (§3.3+§3.4+§6 in amendment) needs correcting via this self-audit.**

---

## §8 What changes vs original recommendation

| Item | Original | Revised |
|---|---|---|
| cycle09b Trial 1 forward-init | Hybrid (defer + cycle10 design) | REJECT per yaml G3 |
| Why | "yaml-strict eligible vs cycle07a-locked RED tension" | yaml G3 itself FAILS Trial 1 (no tension; clear) |
| seed=123 verdict role | Forward-init decision input | Informational only (mining stability) |
| cycle10 design | "wait §5.3 + design ban-bonds yaml" | Deferred until ML 1.5 OR Trial 9 v2 TD60 |
| Q1 (which thresholds) | Open question | Resolved (yaml's own G3 is authoritative) |
| Q2 (cycle10 axes) | 4 candidates with (b) (c) (d) flawed | 3 candidates: factor-pool refine / construction-mode new / universe expansion |

---

## §9 Self-audit of this self-audit (recursive R4)

**R1**: yaml content quoted directly from grep verified output. Trial 1 numbers from §5.1 audit JSON.

**R2**: G3 gate's `required_top_k_under_threshold: 1` interpreted as "at least 1 of 3 anchors must clear BOTH raw<0.70 AND residual<0.50". Verified by re-reading yaml — no alternative reading.

**R3**: did not re-run any code; relies on existing audit JSON + yaml + cycle07a memo grep.

**R4 boundary**:
- Could G3 gate be misinterpreted? `required_top_k_under_threshold: 1` is ambiguous (top-K candidates from mining, or top-K anchors)? Look at the gate's `blend_anchors` field (3 anchors) — interpret as 1 of 3 anchors. Same as cycle07a's logic.
- Could the gate be informational/diagnostic only? It's under `g3_orthogonality_gate.enabled: true` — explicitly enabled. Not informational.
- Could cycle09b yaml have an "exception for Trial 1" override? No — yaml is per-cycle frozen + immutability_contract. No per-trial override.

→ Self-audit verdict robust.

---

## §10 Action items

1. Commit this self-audit memo as separate file (does NOT modify original amendment)
2. Report revised verdict to user
3. Await user reaction:
   - If user accepts revised G3 verdict → proceed Trial 1 = `legacy_decay_verification` + ML Phase 1.5 continues
   - If user wants override G3 → require explicit-go + reasoning + amendment to immutability_contract

Amendment memo §6 already says "Operator strategic recommendation (NOT pre-locked, awaits §5.3 + user input)". This self-audit updates that recommendation IN PLACE via this separate doc; original amendment kept as forensic.
