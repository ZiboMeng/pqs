# OOS Framework — Parking Lot

Decisions that were considered and explicitly **deferred** during the
OOS framework workstream. Not "rejected" — parked, with a clear
re-trigger condition and the original reasoning preserved so future-you
(or future-Claude) can revisit without re-deriving.

---

## P-001 — Pre-registered historical holdout reconstruction

**Surfaced**: 2026-04-26 (user question: "难道不能 holdback 一部分数据
吗 为什么一定要等未来数据 比如把到今年为止的数据全都 holdback 做 oos
数据不行吗")

**The proposal (technically valid)**: re-construct candidates using
only data ≤ 2024-01-01, then test on 2024-2026 as synthetic-forward
holdout. This is stricter than the current R2 robustness eval
(which uses a 252TD window that's INSIDE the candidates'
construction panel).

**Why it was considered as a possible main line**:
- Faster than waiting 60+ TD of real forward (≈3-4 months)
- Stricter than current R2 pseudo-OOS (which is in-sample replay
  on a holdout-shaped window)
- Methodologically standard ("holdout testing")

**Why it was DEFERRED (user 2026-04-26 拍板)**:

1. Even a clean reconstruction is **still pseudo-OOS, not real OOS**.
   The designer (the human) has lived through 2024-2026 — they
   know what AI rally / rate cycle / regime shifts looked like.
   Even with strict procedural separation, factor selection is
   biased by lived knowledge of the holdout period.
2. Current discipline stack is sufficient as the **historical**
   layer: pseudo-OOS robustness (R2) + M12 weighted thin gate +
   sector + beta + watch-list exposure. Adding more historical
   slicing buys diminishing marginal evidence.
3. The actually-scarce resource right now is **post-frozen-date
   real forward bars**, not more ways to slice the past.
4. Doing the reconstruction would require unfreezing the mining
   workstream + the Candidate-3 path, both of which the user has
   repeatedly directed should remain frozen until forward
   evidence accumulates first.

**Re-trigger condition**: post-10TD real forward observation, OR
when designing the NEXT batch of candidates from scratch (where
"pre-registered historical holdout" can be defined ahead of any
construction iteration — true pre-registration semantics, not
retroactive reconstruction).

**At that point this becomes a real PRD draft scope**:
- Spec the holdout window + universe + masks BEFORE any candidate
  search begins (write the spec, hash it, commit it)
- Mining iterates only on pre-holdout data
- All candidates submitted to the holdout get evaluated AS A SET,
  with the multiple-comparison correction baked in
- Holdout outcome doesn't itself drive promotion — it gates entry
  to a forward run, which still has to clear its own bar

This is structurally different from "do holdback now on the two
existing frozen candidates" — the difference matters and is the
reason this is parked, not done.

**NOT to do as part of this parked item**:
- Re-running mining on the existing candidates with a holdout
  carve-out (would just be ad-hoc retro-fit)
- Calling 2024-2026 holdout results "OOS evidence" if/when the
  PRD eventually ships — they remain pseudo-OOS, just
  pre-registered
- Conflating pre-registered holdout results with deployable OOS
  in any memo or report (PRD v3 §1.1 / §1.3 trap)

---

## How to use this file

When a future decision matches the pattern "user considered X,
explicitly chose to defer", add a new entry P-NNN with: surfaced
date, proposal, why considered, why deferred, re-trigger condition,
explicit anti-patterns to avoid when re-considering.

Append-only. Items only get **closed** (moved to a closeout memo)
when the re-trigger condition fires AND a real PRD/decision lands
that supersedes the parked state.
