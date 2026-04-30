# Priority realign: alpha-first, not guard-first

**Date**: 2026-04-30
**Status**: SHIPPED (this memo + CLAUDE.md TODO realign).
**Triggered by**: external auditor R36 strategic critique (see
`docs/claude_review_loop.md` Round 37 for verbatim disposition).
**Authority**: operator decision after independent evaluation;
auditor concurred on direction.

---

## TL;DR

**Stop continuing to build governance/runner/ledger code.
Resume building only when there is a Track C candidate to defend.**

The project has crossed the "防止自己被系统骗" threshold and is now
risking the opposite failure: governance layers thicken while alpha
remains unproven under the new framework. The governance work shipped
in commits `c720e71` + `847f3fc` is good and stays. The work that was
queued AFTER it — A.MV implementation, B.MV implementation, Fleet
Step 6+, more memo iteration — is reordered or paused.

The single highest-value question in this stage is:

> **Does the new framework (Track A acceptance + temporal split +
> M12 weighted thin + G2.A 30% concentration ceiling + Step 5
> correlation budget) admit any alpha at all?**

Until cycle #01 answers that, more guard infrastructure has zero
operational consumer.

---

## What changes vs the R36 todo

### Demoted

| Task | Old priority | New priority | Reason |
|------|-------------:|-------------:|--------|
| A.MV implementation (sealed-eval freeze-date HARD + market-path SOFT) | P0 internal | **P2 — gated on candidate** | Blocks 2026 sealed eval; that's at least forward-soak away. Implementing now while there is no candidate = working on a downstream guard with no upstream consumer. Schema decision (Q11) recorded; full impl waits. |
| B.MV implementation (early-attention triggers, dispatch on `decay_classification`) | P0 internal | **P2 — gated on candidate** | Blocks forward init; no nominee exists. Schema contract locked in `bmv_schema_decision.md`. Full impl waits until cycle #01 produces a nominee. |
| Fleet Step 6+ (DD throttle / role caps / observe / shadow→live) | parked | **HARD PAUSE** | RCMv1+Cand-2 retracted; no fleet candidate. Continuing allocator downstream is empty plumbing. Resume only after a real fleet candidate exists. |

### Promoted / new

| Task | Priority | Why |
|------|---------:|-----|
| Cycle #01 pre-registered immutable criteria yaml | **P0 internal** | Criteria immutability requires pre-registration BEFORE any trial runs. Same model as `research-cycle-2026-04-26-01_promotion_criteria.yaml` (sha256 in commit). Does not depend on E.MV signoff. |
| Generic NAV pair diagnostic runner (refactor `rcmv1_cand2_realized_nav_correlation.py`) | **P1** | Evidence pack §4.6 needs candidate × every active candidate when cycle #01 produces a nominee. Manual script edit at that point = audit risk. Refactor 80% now (legacy run still works); fill candidate IDs at nominee time. |
| Track A acceptance auto-stamp `estimated_beta_at_freeze` | **P1 (minimal-scope only)** | NOT full A.MV. Just the β computation + nested block write. Cost ~half day. Avoids "candidate frozen → B.MV implementation later requires `raise ValueError` rework" rebound. Specifically: when Track A acceptance promotes, compute β-SPY + β-QQQ on `train+validation` window, write nested block with `source=track_a_acceptance` and `used_by_b_mv=true`. |

### Held (no change)

| Task | Status |
|------|--------|
| Forward observation daily ritual on RCMv1+Cand-2 | Active, observation-mode (legacy decay verification only). Does not block, is not blocked. Continues. |
| E.MV §4.6+§4.7 reviewer signoff | External dependency; outside operator control. |
| Concerns memo + bmv_schema_decision.md | Already shipped. Frozen. No more iteration on memos as substitute for cycle compute. |

---

## What this memo does NOT change

- Pricing semantics, raw-vs-adjusted rules, T+1 open execution, etc.
- Track A acceptance gates / temporal_split discipline / M12 weighted thin / G2.A 30% ceiling.
- Step 5 correlation budget (warn 0.70 / reject 0.85).
- Any frozen invariant in CLAUDE.md.
- The Q12 disposition (SKIP-on-decay; raw -10% fallback rejected).

---

## Strategic observations (auditor R36 § + my additions)

### 1. Portfolio construction is the suspected bottleneck, not factor zoo

RCMv1 and Cand-2 use **factor-disjoint** composites:

| | RCMv1 | Cand-2 |
|---|---|---|
| Factors | beta_spy_60d, drawup_from_252d_low, days_since_52w_high, amihud_20d | ret_5d, rs_vs_spy_126d, hl_range |
| Factor IC corr | — | 0.40 (PASS factor-IC orthogonality 0.5 threshold) |
| Realized NAV pooled Pearson | 0.898 | (Step 5 reject) |
| Residual NAV vs SPY | 0.609 | (still high after beta strip) |
| Residual NAV vs QQQ | 0.579 | (still high after beta strip) |

Reasoning: monthly rebalance + top-N selection + long-only + same
78-symbol universe collapses factor signals into "rank tickers by
recent winner-ness" almost regardless of factor identity. That is
a portfolio-construction degree-of-freedom loss, not a factor-zoo
exhaustion problem.

### 2. Track C alpha-source guidance (nominee evaluation lens)

If cycle #01 produces a candidate that scores high on acceptance
gates but is structurally similar to RCMv1+Cand-2 (long-only ×
monthly × top-N × momentum/quality/relative-strength), it is a
sibling, not a diversifier. Auditor's specific list (worth
preserving for cycle #01 closeout):

- short-horizon reversal / intraday mean reversion
- event/calendar features
- sector / cross-asset / rates-sensitive sleeve
- volatility / dispersion / drawdown recovery features
- different cadence (weekly rebalance, intraday timing overlay)
- explicitly beta-controlled portfolio construction (not just factor selection)

Cycle #01 closeout MUST classify any candidate against this list.
"Pass gates" alone is insufficient evidence to enter nominee status.

### 3. Sealed eval must be defined as post-freeze unseen window

Today is 2026-04-30. Any candidate frozen today onwards CANNOT use
2026-Q1 + April as clean OOS — the panel was visible at freeze. The
A.MV freeze-date HARD rule (Q11 disposition) addresses this; until
A.MV ships, **manual discipline at sealed-eval time is required**:

> Clean sealed eval window starts strictly after candidate
> `freeze_date` AND after `panel_max_date_at_freeze`.

This rule is recorded here because Track C cycle #01 cannot rely on
A.MV being implemented when it eventually reaches sealed eval.

### 4. Most scarce resource: unseen forward time

Unseen trading days cannot be backfilled. Code modules can. Every
day waiting on memo iteration / governance signoff / docstring
polishing is a day spent draining future OOS power. This memo is
itself a candidate for the very critique it documents: pause memo
iteration, run cycle compute.

---

## Resume conditions (when paused work re-activates)

### A.MV full implementation re-activates when:

- Track C cycle #01 (or later cycle) produces a candidate that
  passes Track A acceptance + evidence pack §4.6+§4.7
- That candidate enters forward soak
- Forward soak completes successfully (≥ TD60 healthy + no early-attention triggers)
- Sealed eval is the next gate

Before that point, A.MV is unused infrastructure.

### B.MV full implementation re-activates when:

- Track C cycle #01 (or later cycle) produces a candidate that
  passes Track A acceptance + evidence pack §4.6+§4.7
- That candidate is approved for forward init

Before that point, B.MV is unused infrastructure.
(`decay_classification.label` dispatch on legacy is the only B.MV
decision; it is doc-only until a runner exists. Legacy candidates
do not need B.MV — they are observation-mode only.)

### Fleet Step 6+ re-activates when:

- ≥ 2 candidates exist that BOTH pass Track A acceptance AND have
  realized-NAV pair correlation < 0.70 (warn) and < 0.85 (reject)
  per Step 5.
- AND first candidate has completed forward soak.

Before that point, Step 6+ is unused infrastructure.

---

## What I will do next (concrete, dated)

| When | Action |
|------|--------|
| Now (this commit) | Memo + CLAUDE.md TODO realign + INDEX.md update + R37 review entry |
| Next session, no E.MV signoff yet | Write cycle #01 pre-registered criteria yaml (P0); refactor `rcmv1_cand2_realized_nav_correlation.py` → generic pair runner (P1); minimal Track A acceptance β-stamp extension (P1) |
| When E.MV signoff arrives | Run cycle #01 mining compute |
| Cycle #01 = 0 candidate | Per criteria immutability, cycle closes 0-nominee. Reassess: what about Track C is wrong (gates too strict, factor zoo exhausted, portfolio construction dominant)? Re-plan based on evidence, not pre-emptive memo iteration. |
| Cycle #01 = candidate passes gates AND is structurally different | Generic NAV pair diagnostic vs RCMv1+Cand-2; if low residual correlation, candidate enters evidence pack §4.6+§4.7 review; B.MV implementation begins (now justified by upstream consumer); A.MV implementation begins after forward soak. |
| Cycle #01 = candidate passes gates BUT is RCMv1/Cand-2 sibling | DO NOT promote. Cycle closes "0 useful nominees". Trigger investigation into portfolio construction / cadence / universe alternatives. This is the auditor's anti-sibling discipline. |

---

## Appendix: alignment with operator memory

This memo aligns with three memory items already enforced for this
project (operator memory, not project state):

- "资深美股量化操作员角色定位" — push back on reviewer/auditor only with reasons; accept when reasons are sound. Auditor's strategic critique here is sound.
- "自审 4 层方法论" — the act of pausing for strategic re-evaluation is itself an R2 (logical) audit at the project-priority layer, not just commit-by-commit.
- "每轮收尾必做两件事" — self-audit + todo with dependencies. This memo's dated action table is the dependency view; CLAUDE.md TODO is the canonical task list.
