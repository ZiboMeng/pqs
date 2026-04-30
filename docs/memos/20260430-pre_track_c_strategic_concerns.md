# Pre-Track-C strategic concerns (1-page)

**Date:** 2026-04-30
**Status:** Concern note. Items here do **not** block the Track C
controlled-mining dry run, but they DO block: forward init for any
Track C nominee, 2026 sealed eval, fleet live wiring, real-money
deployment.
**Owner:** Claude (per external reviewer prompt 2026-04-30)
**Lineage:** companion to
`docs/memos/20260430-rcmv1_cand2_realized_correlation.md`.

The hard line per external reviewer 2026-04-30:

> Track C dry run can run; any candidate it produces cannot enter
> forward init / sealed eval / fleet wiring / real money until each
> of the three concerns below has an explicit guard in code or PRD.

---

## Concern A — 2026 sealed-eval / forward-observation double-dip

**Risk.** RCMv1 + Cand-2 are forward-observing 2026 daily bars
since 2026-04-24 (TD003 as of 2026-04-30). When/if a Track C
candidate clears Track A acceptance and enters 2026 sealed eval,
sealed eval runs over a 2026 window that overlaps with what RCMv1
+ Cand-2 already saw. The same calendar interval gets used twice
— once for legacy decay verification, once as clean sealed-eval
holdout. The sealed_ledger today defends against
`(split_name, candidate_spec_sha256)` repetition, but does not
defend against forward observation having already touched the
same 2026 calendar interval.

**Why it matters.** Holdout windows are the scarcest research
asset for a personal quant. 2026 cannot be infinite. Every dollar
of "I observed this period" reduces the credibility of "I tested
on this period blind".

**Guard required (before any Track C candidate enters sealed eval).**

- Sealed ledger schema must record `eval_start_date` /
  `eval_end_date` for every sealed eval run.
- A new sealed-eval pre-flight check: reject the run if
  `[eval_start_date, eval_end_date]` overlaps with any forward-run
  observed interval for ANY candidate of the same lineage family
  (or be explicit about the deliberate decision to accept
  "tainted" sealed data with a memo).
- Legacy candidates' 2026-04+ forward observation reclassified as
  "legacy_forward_evidence", NOT clean sealed evidence. (CLAUDE.md
  already captures this as "legacy decay verification" — needs to
  flow into ledger semantics.)

**Status this is allowed to defer to.** Track C dry run does not
touch 2026. Track C acceptance evaluates on
2018/2019/2021/2023/2025. So the dry run can proceed without
this guard. The guard MUST exist before any sealed-eval call.

---

## Concern B — Forward TD60-fixed cadence vs risk management

**Risk.** Forward OOS PRD designs 10/20/40/60 TD checkpoints as
report-only and `decision-pack at TD60`. Operationally this means
that if a candidate is at -8% by TD15, -12% by TD25, -18% by TD40,
the protocol still says "keep observing until TD60". That binds
risk management to a fixed administrative window and conflicts
with basic drawdown discipline. In a paper / observation context
this is tolerable. For pre-promotion candidates being soaked
toward live wiring, it is not.

**Two-tier guard required.**

Tier 1 — early-attention flag (now, before any Track C nominee
enters forward init):

- Add a non-status-changing `early_attention_required` flag to
  forward run records, surfaced in the daily observe log.
- Trigger when ANY of:
  - forward MaxDD ≥ 75% of validation-year MaxDD pass threshold
    (i.e. ≥ 0.15 against the 0.20 ceiling for core role);
  - forward MaxDD ≥ 95th percentile of candidate's historical
    rolling-60d DD;
  - cumulative TD return ≤ -8%;
  - vs SPY AND vs QQQ both deteriorate beyond market beta
    explanation;
  - data drift event AND PnL deterioration co-occur on same TD.

Tier 2 — hard kill / reduce / park (before live wiring, NOT now):

- Status-changing transition (`active` → `parked` / `removed`).
- Co-design with Fleet Step 6 DD-throttle and KillSwitch state
  machine. Separate PRD when Step 6 unfreezes.

**Status this is allowed to defer to.** Track C dry run produces
candidates that go to acceptance, then potentially to
nomination memo. None of that touches forward init. Track C dry
run does not require Tier 1.

---

## Concern C — Economic-invariant test gap

**Risk.** Repo currently has ~1850 unit tests, but external reviews
(codex R28-R30, prior rounds) keep finding bugs. Almost all are at
the level of "code did what the author intended, but the
author's economic assumption was wrong" rather than
"code-correctness". Examples from this round alone:

- M11a paper-vs-replay drift: code worked; assumption that
  `set()` iteration is deterministic was wrong.
- M14 NaN equity: code worked; assumption that `.get(sym, 0)` on
  a column with NaN returns 0 was wrong.
- Cand-2 "orthogonal": code computed factor-IC correlation; the
  unstated assumption that factor-IC orthogonality implies NAV
  orthogonality was wrong.

**Guard required (start in Track C evidence pack — minimum
viable, not a framework).**

Three categories, embed minimum in every Track C nomination:

1. **Trading-accounting invariants (HARD FAIL):**
   - long-only weight ≥ 0 at every layer;
   - row-sum weight ≤ 1.0 + epsilon;
   - cash = 1 - invested_weight;
   - signal_date < execution_date strictly;
   - stale/halted symbol mark-at-last-price preserved in NAV.

2. **Risk-statistics invariants (HARD FAIL):**
   - MaxDD reported as positive magnitude (already in template
     post-codex-R30 fix);
   - rolling MaxDD monotone-non-decreasing within a window;
   - Sharpe annualization formula consistent across reports;
   - benchmark excess sign convention consistent;
   - stress slice not pooled into validation aggregate.

3. **Economic-assumption invariants (FLAG, not fail):**
   - factor-IC correlation vs realized-NAV correlation, gap > 0.30
     → attention;
   - "low beta" / "defensive" claim vs realized β > 1.0 → attention
     (RCMv1 + Cand-2 both fail this — both run β-SPY 1.3-1.6);
   - "diversifier" claim vs realized NAV pooled Pearson ≥ 0.40 →
     attention;
   - QQQ excess attributable to ≤ 3 names or to TQQQ/SOXL → attention;
   - acceptance pass on 2025 but fail on 2023 → regime-dependency note.

**Status this is allowed to defer to.** Don't build a framework.
Just include the matrix in the Track C evidence pack template
under a new §4.6 (NAV-level orthogonality) and §4.7 (economic
assumption flags). External reviewer agreed on minimum-viable
embed. Full invariant suite in code is post-Track-C.

---

## What this enables

| Workstream | Allowed | Blocked |
|------------|---------|---------|
| Track C controlled-mining dry run | yes | — |
| Track C evidence-pack template improvements (add §4.6 + §4.7) | yes | — |
| Track C candidate nomination | yes | — |
| Forward init for Track C candidate | — | until Concern B Tier 1 ships |
| 2026 sealed eval for Track C candidate | — | until Concern A guard ships |
| Fleet wiring with Track C candidate | — | until Concern B Tier 2 + economic-invariant flags ship |
| Real-money deployment | — | all three concerns + invariant suite |

## What I am NOT doing in this memo

- Not opening a new PRD per concern (each is a future PRD when
  triggered, not now);
- Not modifying sealed_ledger, forward runner, or invariant test
  framework (all deferred per "minimum-viable, no framework
  building" rule);
- Not changing existing acceptance gates;
- Not pausing Track C.
