---
reviewer: codex
date: 2026-04-28
scope: P0-P5 priority status after Claude progress check
status: REVIEWED_WITH_ACTIONS
---

# Codex Round 12 — P0-P5 status and next priorities

This note answers the user's direct question: after Claude's latest
progress, where do the previously flagged macro priorities stand now?

Reference queue from earlier codex reviews:

- P0: Forward evidence hardening
- P1: true PIT data dimension
- P2: candidate-fleet allocator
- P3: universe expansion
- P4: execution realism
- P5: CLAUDE.md / status hygiene

## Executive summary

Claude has now clearly moved on **P0** and the first half of **governance cleanup**:

- **P0 forward evidence hardening** is no longer just "shipped in code" — it has crossed into **first real forward evidence accumulation**. This is meaningful progress.
- **Acceptance Threshold Unification PRD** is drafted, which is the right near-term answer to the governance drift behind F01/F02.

But the queue is still **unbalanced** in a way that matters for real-money research:

- **P2 candidate-fleet allocator** is still not started, even though there are now two live forward candidates.
- **P1 true PIT data dimension** is still mostly at the concept / sidecar / provenance layer, not at the "new alpha-bearing PIT data stack" layer.
- **P4 execution realism** has strong correctness foundations (M11a/M11b/M14, T+1 open, parity, cost model), but not yet the fuller capacity / liquidity / slippage realism that matters for capital deployment.
- **P5 status hygiene** is mostly good, but there is already one stale forward-status sentence in `CLAUDE.md` that should be fixed immediately.

## Status by priority

## P0 — Forward evidence hardening

### Current status

**DONE at the engineering-contract level; ACTIVE at the evidence-accumulation level.**

Evidence:

- `docs/prd/20260427-forward_evidence_hardening_prd.md` = SHIPPED v2.1.3
- main commit `bcfbc0f` = first real `forward observe`
- `docs/memos/20260428-forward_observe_first_real_after_v2_1_3.md`
- both manifests now moved from TD001-only to TD003

Observed live state:

- `rcm_v1_defensive_composite_01`: TD001 legacy + TD002 + TD003
- `candidate_2_orthogonal_01`: TD001 legacy + TD002 + TD003

### My judgment

This is the **most important completed move since the audit cycle ended**.

Why: before this, the system had hardening and audit confidence but not
enough real post-baseline evidence. Now the framework has started to
collect actual forward observations under the hardened contract.

### What is still left under P0

P0 is not "over"; it has changed phase:

- from **build the guardrail**
- to **run the daily ritual and accumulate evidence**

Next concrete targets:

1. keep daily/append-only observe cadence running
2. reach **TD010** for both candidates
3. produce the first decision-grade checkpoint pack
4. decide whether both candidates deserve to stay in the live research queue

### Priority class

- **Short-term**: very high
- **Long-term**: medium (because once the ritual is stable, the priority shifts upward to allocator / data / realism)

## P1 — True PIT data dimension

### Current status

**Mostly NOT done** in the sense that matters for new alpha and stronger historical honesty.

Important distinction:

- there is already some PIT-aware infrastructure and discipline:
  - `UniverseManager(as_of=...)`
  - PIT universe rebalance path
  - `bar_provenance.parquet`
  - polygon-canonical vs yfinance-frontier separation
  - forward source-layer surfacing
- but this is **not yet the same thing** as a true new PIT data layer

What is still missing:

- point-in-time sector / industry history
- point-in-time shares outstanding / float
- point-in-time fundamentals / earnings metadata
- a clean separation of **config drift** vs **data revision**

### My judgment

This remains strategically important because it is one of the few ways to
unlock genuinely new signal families and improve the honesty of historical
research at the same time.

But it is **not** the next thing to implement before allocator / forward
evidence accumulation.

### Priority class

- **Short-term**: medium-low
- **Long-term**: very high

### Recommended next step

Do **not** implement a big PIT pipeline yet. First draft the scoped PRD for:

- config/universe snapshot hardening in forward manifests
- then, separately, true PIT metadata / fundamentals vendor requirements

## P2 — Candidate-fleet allocator

### Current status

**NOT started.**

Claude's own forward observe memo still marks it "not started".

### My judgment

This is now the **highest-value missing macro component**.

Reason:

- there are already **two** live forward candidates
- they were intentionally built to be different
- once both are collecting forward evidence, the right unit of decision
  is no longer only "single candidate pass/fail"
  but also "what is the best portfolio of candidates?"

Without an allocator layer, the framework can keep producing interesting
single-strategy evidence while still failing the actual PM problem:

- how much capital to give each
- how to handle overlap
- how to budget correlation and drawdown
- how to scale down when both are weak

### Priority class

- **Short-term**: very high
- **Long-term**: very high

### Recommended next step

This should be Claude's **next design item after threshold-unification sign-off**.

Minimum allocator PRD should define:

1. capital split rule
2. max pairwise corr budget
3. overlap throttle on shared names
4. core vs satellite role
5. drawdown-based throttling
6. candidate removal / parking rule after bad forward evidence

## P3 — Universe expansion

### Current status

**Partially done historically, not active now.**

What already exists:

- 79-symbol tradable universe is live
- prior expanded-universe mining work exists
- 513-name S&P500 pool sync / admission-screen artifacts exist

What is **not** active:

- a new, authorized, broader re-mining or production migration step

### My judgment

This item is easy to overvalue too early.

Universe expansion is useful when:

- the current alpha family is real but capacity/opportunity set is too narrow
- or the current universe is clearly choking candidate diversity

Right now, the framework's tighter bottleneck is **decision governance +
portfolio composition**, not raw symbol count.

So I would not put P3 ahead of P2 or the near-term P0 ritual.

### Priority class

- **Short-term**: medium
- **Long-term**: high

### Recommended next step

Keep P3 warm, but do not make it the next implementation line unless:

- current two-candidate forward evidence looks encouraging
- and allocator design says the framework wants more uncorrelated sleeves

## P4 — Execution realism

### Current status

**Partially done.**

Already done well:

- T+1 open-fill semantics
- paper/backtest parity hardening (M11a/M11b)
- M14 NaN / ghost-position fix
- concentration metrics/gate (M12)
- cost-model plumbing and cost-robustness checks

Not yet done in the broader "real deployment realism" sense:

- capacity / ADV participation realism
- spread/open-gap stress by symbol class
- clustered rebalance stress
- liquidity asymmetry between ETFs and single names
- richer slippage realism than the current cost-model abstraction

### My judgment

Important distinction:

- **execution correctness** is now in good shape
- **execution realism** is still incomplete

That means P4 is not a fire, but it is still one of the most important
longer-run items before trusting the system with larger capital.

### Priority class

- **Short-term**: medium
- **Long-term**: very high

### Recommended next step

Do not turn this into a giant rewrite. Instead, open it as a staged line:

1. capacity/liquidity realism PRD
2. ADV participation caps
3. slippage stress by liquidity tier
4. open-gap stress / clustered rebalance stress

## P5 — CLAUDE.md / status hygiene

### Current status

**Mostly done, but not fully done.**

Good progress:

- M11/M12/M14 status cleanup happened
- framework-completion PRD got its v1.2 status header
- README status surface is much cleaner than before

But there is now a fresh stale line:

- `CLAUDE.md:631-634` still says existing manifests are "not yet mutated"
- that was true before `bcfbc0f`
- it is no longer true after the real forward observe wrote TD002 + TD003

### My judgment

This is low-cost and should be fixed immediately.

Status hygiene has diminishing strategic value, but stale state in
`CLAUDE.md` is exactly how future review loops start to drift again.

### Priority class

- **Short-term**: high because it is cheap and should be cleaned now
- **Long-term**: low

## My updated ordering

If I re-rank the queue after Claude's latest progress:

1. **P0 follow-through** — keep daily forward observe cadence and drive to TD010
2. **Acceptance Threshold Unification** — get codex sign-off, then implement when user authorizes
3. **P2 candidate-fleet allocator** — this is now the biggest missing macro capability
4. **P5 status hygiene** — immediate small cleanup in `CLAUDE.md`
5. **P4 execution realism** — next serious infrastructure line after allocator
6. **P1 true PIT data dimension** — strategically major, but not next on the critical path
7. **P3 universe expansion** — valuable, but after allocator/governance/forward evidence are more mature

## What I recommend Claude do next

### Immediate

1. Patch the stale `CLAUDE.md` forward-status lines.
2. Keep the forward ritual running; do not let P0 stall after the first real append.
3. Wait for codex/user sign-off on `docs/prd/20260428-acceptance_threshold_unification_prd.md`.

### Next design line

4. Draft **candidate-fleet allocator PRD**.

### After that

5. Draft **execution realism / capacity-liquidity PRD**.
6. Draft **config/universe snapshot hardening PRD** (as the bridge into the broader PIT agenda).

## Bottom line

Claude has made real progress on the right things.  
The biggest shift since the last check-in is:

- **P0 has moved from "framework hardening" to "real evidence accumulation"**

The biggest thing still missing is:

- **P2 candidate-fleet allocator**

And the one cheap fix that should happen right now is:

- **P5 CLAUDE.md stale forward-status cleanup**
