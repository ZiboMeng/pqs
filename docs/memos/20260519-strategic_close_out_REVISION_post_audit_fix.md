# Strategic Close-out — REVISION post-audit-fix (2026-05-19)

**Status**: 修订 supersedes specific sections of
`docs/memos/20260519-strategic_close_out_prd123_track_a.md` (the
original is preserved as historical record per non-deletion
discipline). User option-D close-out memo was written BEFORE the
external auditor flagged 3 code bugs that distorted multiple
intraday-ML findings. This revision integrates the post-fix
verdicts (RB3 / Track-A / RB5 all rerun) and corrects the
specific claims that were artifacts of the dead-feature bug.

**Trigger**: external auditor's R3-verified findings, all 3
auditor-flagged bugs confirmed at code level (`intraday_volume_z`
mathematically identically zero / Track-A `top1_max` key MISSING
silently false-PASS / `assert_component_b_prerequisites` falsely
gating A1-only runs).

---

## §R1 — Original §1 (技术 takeaway) corrections

### S1 — single-signal-can't-beat-SPY claim: SCOPE narrows further

Original claim: "in long-only + cap-aware + monthly + no cascade
timing scope". Auditor + post-fix data tighten the scope:

> **AT** long-only + cap-aware + walk-forward monthly cadence + no
> cascade overlay + **continuous-weighted prediction usage** (i.e.
> the model output used as a continuous size weight), single ML
> signal mathematically cannot beat SPY. **The SIGN-only
> extraction path (use prediction sign as include/veto, not as
> continuous weight) has NOT been tested at NAV layer**. RB3+RB5
> post-fix A/B FORCED data shows sign carries +0.08 IC across all
> 3 model classes while magnitude universally degrades — sign-only
> is the more promising extraction.

### S4 — 4 FAIL row REVISIONS (one row retracted, two rows clarified)

| FAIL | Original framing | REVISED framing |
|---|---|---|
| P2.1 R5 | regime-conditional value (crisis-DD真降,牛市 bleed) | UNCHANGED — verified |
| P2.3 R13 | config-scoped(月度+趋势集 cascade = haircut) | UNCHANGED — verified |
| RA8 | statistical-power-scoped (T=59 honest-N) | UNCHANGED — verified |
| RB5 | **shallow's own DSR 0.538>0.5 survives → defensible non-promotion finding within FAIL framing** | **RETRACTED** — that claim was a dead-feature artifact. Post-fix DSR(shallow, honest_n=15, T=59, Sharpe 0.09) = **0.147 << 0.5,统计上不可与 null 区分**. The shallow arm is **NOT** a within-FAIL PASS-worthy finding under leakage-correct + dead-feature-fixed eval. RB5 FAIL is now a CLEANER FAIL — no "but shallow survives" silver lining. |

### NEW UNIVERSAL FINDING (post-fix only — wasn't visible pre-fix)

Across all 3 model classes evaluated in RB5 (DLinear / shallow
XGB / deep SSL+probe), the A/B FORCED de-confound shows the same
pattern:

| Arm | info(sign-only) IC | full IC | timing(magnitude) contrib |
|---|---|---|---|
| DLinear | +0.091 | -0.079 | **-0.170** |
| Shallow | +0.080 | +0.034 | -0.046 |
| Deep | +0.076 | -0.091 | **-0.166** |

**Universal pattern**: SIGN of the prediction carries useful
cross-sectional signal (+0.076..+0.091); CONTINUOUS MAGNITUDE
universally degrades or inverts (timing contribution is NEGATIVE
for all 3 model classes). This is NOT a model-class problem (it
holds across linear/tree/deep) — it's a SIGNAL-REPRESENTATION
problem. The engineered intraday features carry directional info
but their continuous magnitudes are noise-dominated at this T.

---

## §R2 — Original §2 (战略路径) corrections / strengthening

### P1 — Ensemble redesign:**must use SIGN-VOTE, not continuous-weighted**

Original P1 said "ensemble of A1+B1+cross-asset overlay". The
post-fix RB5 finding tightens this:

- The ensemble's component signals (RA1+RA2 A1, RB2+train_b1 B1,
  legacy cycle06 factor-composite) should be combined via
  **sign-vote / rank-vote / include-veto** (long-only Lo-Patel
  pattern), **NOT** via continuous-weighted average of predictions.
- This is **fully aligned with the auditor's broader strategic
  framing**: "ML 更适合做 trade/no-trade decision + partial
  rebalance size + urgency/exit probability,**不**让 ML 直接
  无约束决定全仓位切换". The post-fix RB5 data now SHOWS WHY:
  the only signal in the predictions is direction; magnitudes
  are universally mis-calibrated noise.

### Aligning with academia / industry rebalancing literature

- AQR 2015/2025 *Portfolio Rebalancing, Common Misconceptions*:
  rebalancing frequency is an active decision, not mechanical
  fixed cadence.
- MSCI factor index methodologies (incl. momentum 2023): buffer
  rules, turnover budget, staggered rebalance, spread rebalance,
  trigger-based ad-hoc rebalance.
- BlackRock *Time to Tilt*: dynamic factor timing with
  regime/valuation/sentiment indicators.
- Lynch-Balduzzi and Leland: transaction-cost-aware no-trade
  region is the standard academic baseline, not fixed cadences.

Concretely, the **production-grade abstraction**:
1. **signal refresh frequency** (how often features re-compute)
2. **decision checkpoint** (how often the system asks "trade?")
3. **no-trade band / turnover budget** (Lynch-Balduzzi)
4. **event / factor-triggered entry** (MSCI ad-hoc trigger pattern)
5. **exit factor / risk-triggered exit**
6. **execution scheduler** (urgency / partial fills)

are SIX DECOUPLED parameters, not one fixed "monthly/weekly/daily"
cadence knob. **The Track-A v1 evaluated only #1 conflated with
#2 at monthly**. A v2 production-grade design would have all
6 as independent levers, with ML predictions feeding into #2
(checkpoint decision) and #4 (event-triggered entry size) rather
than mechanical full-position switching.

---

## §R3 — Original §4 留痕 — additional honest evidence trail

Beyond the prior R1-INVALID temporal-leakage留痕, this revision
adds:

1. `core/research/b1_intraday_features.py` intraday_volume_z()
   docstring has the bug post-mortem inline (math: identically 0
   for any input; fix: replaced with skew = third moment).
   Regression test added: front-loaded volume must yield
   |skew| > 0.1 — guards against the dead-feature bug recurring.

2. `dev/scripts/track_a/a1_b1_nav_track_a.py` concentration key
   fix has inline comment pointing to the stale-docstring root
   cause at `composite_evaluator.py:545`. The driver now reads
   `m12_top1_weight_max` / `m12_top3_weight_max` (real keys).

3. B-gate decouple comment inline noting the false-coupling root
   cause.

4. All 3 post-fix verdicts (RB3 / Track-A / RB5) committed under
   audit T1.a / T1.b / T1.c. Pre-fix verdicts preserved in git
   history (no deletion).

---

## §R4 — Outstanding production-grade gaps (auditor's 4 critical points I hadn't surfaced)

These are NOT covered by the post-fix and remain real gaps:

1. **Dividends not in price adjustment** (CLAUDE.md acknowledges
   "deferred"). Long-term vs SPY/QQQ comparisons systematically
   underestimate strategy excess (or correctly track total-return
   benchmarks if those are also dividend-adjusted — needs check).
   Concrete impact: 17-yr SPY total return with reinvested
   dividends is ~10x not 6x; my Track-A "vs SPY -353pp" framing
   used non-dividend-adjusted SPY series, so the actual gap
   could be slightly different. Material correction needed for
   any future production-claim numbers.

2. **production_strategy.yaml status="conservative_default"** —
   no post-fix-validated active production candidate exists.

3. **Portfolio construction lacks cost-aware optimizer /
   no-trade region / partial rebalance** — still fixed-cadence
   research harness, not production-grade.

4. **Live broker/feed/ops layer absent** ("research +
   paper/shadow ready" at best, per the auditor's framing). The
   CLAUDE.md invariants explicitly defer this ("No real
   broker/API integration this phase") — so this is by-design
   for the current phase, NOT a regression. But it's a real
   gap for "可以 live 跑并且有较高胜率盈利".

---

## §R5 — Net judgment (operator independent, post-audit)

The auditor's overall framing is correct and I endorse it:

> 这套系统现在适合的定位是 **research-grade + strong audit
> discipline + paper/shadow candidate**. 离 "可以 live 跑并且有
> 较高胜率盈利" 的差距,**主要不在再挖几个新因子**,而在:
> 1. 修最近 loop 的证据缺口并重跑关键实验。**[已做:T0+T1.a/b/c]**
> 2. 把调仓从 "固定 cadence" 升级成 "阈值/事件/风险触发 +
>    partial rebalance"。**[NEW PRD 范畴,未做]**
> 3. 补齐 dividends、active production candidate、live execution
>    seam。**[Phase 边界外,未做]**

What I added on top of auditor's framing (post-fix data-driven):
> 4. The ENSEMBLE design that prior P1 envisioned should
>    use SIGN-VOTE, not continuous-weighted predictions —
>    because the post-fix A/B FORCED data shows magnitude is
>    universally noise across all model classes. This is the
>    biggest STRATEGIC insight from the audit fix.

---

**Loop / Track-A / Audit cycle terminates here.** Original
close-out memo header line "Loop terminates here" still holds
strictly; this revision adds corrections, no new pending work,
no ScheduleWakeup. Next strategic step (ensemble PRD with
sign-vote design + event-triggered rebalance + dividend fix +
active production candidate) is NEW user-directional scope.
