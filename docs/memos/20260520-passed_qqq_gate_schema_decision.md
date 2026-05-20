# Decision memo: passed_qqq_gate schema vs PRD diagnostic stance

**Date**: 2026-05-20
**Author**: operator (Claude Opus 4.7)
**Triggered by**: auditor 2nd-round F6 finding — schema-vs-PRD drift
**Status**: DRAFT (directional — user explicit-go required)

---

## Conflict

| Source | Treatment of `passed_qqq_gate` |
|---|---|
| `core/config/production_strategy.py:46-60` (`ProductionStrategyValidation`) | HARD gate: required true in `all_passed` property |
| `core/config/production_strategy.py:108-130` (`_active_requires_source_and_validation`) | If `all_passed=False`, refuses status=active |
| `docs/memos/20260502-qqq_benchmark_deprecation.md` | QQQ deprecated as hard gate; diagnostic only |
| `CLAUDE.md §"Benchmark Outperformance Rule"` | "QQQ 作为 diagnostic reference,非 hard outperformance gate" |
| PRD #3 canonical promotion (this PRD) | Treats `passed_qqq_gate` as diagnostic per CLAUDE.md |
| PRD #4 rank-first ML | Implicitly assumes qqq-deprecated stance |

**Drift**: pydantic validator is the old (pre-2026-05-02) stance; PRDs
+ CLAUDE.md + decision memo are the post-deprecation stance.

## Options

### Option A: harden schema to match PRD (recommended by operator)

Modify `core/config/production_strategy.py`:
1. Remove `passed_qqq_gate` from `all_passed` property
2. Add field default `True` so legacy configs don't fail on load
3. Add docstring noting QQQ deprecated 2026-05-02; field retained for
   audit-trail/diagnostic value but not gated

Pros:
- Schema reflects current invariants
- M2 promote can succeed without forcing qqq-beat (which the
  diagnostic memo + 8-angle analysis already showed is
  infeasible-with-MaxDD-cap)
- Aligns with CLAUDE.md QQQ deprecation memo

Cons:
- Schema change is invariant adjacent — needs user explicit-go per
  CLAUDE.md "MUST PAUSE for confirmation: Changing core constraints"
- Existing tests asserting `passed_qqq_gate=True` may need updates

### Option B: keep schema strict, force PRDs to defer to it

Modify PRD #3 + PRD #4 to require `passed_qqq_gate=true`. This means
trigger-first candidate must beat QQQ (the deprecated hard gate).

Pros:
- No schema change required
- Backward-compatible with pre-deprecation flow

Cons:
- Directly contradicts CLAUDE.md QQQ deprecation memo
- Per 8-angle analysis at
  `docs/memos/20260502-qqq_benchmark_deprecation.md` §"Long-only beat-QQQ
  requires beta>1 → MaxDD>QQQ → DIRECTLY violates 15-20% MaxDD invariant",
  this gate is structurally incompatible with §6.4 MaxDD invariant for
  long-only strategies
- Promotes "fix the doc to match stale code" rather than "fix the code
  to match decided direction"

### Option C: leave drift, document as known-conflict, defer

Add a comment in `ProductionStrategyValidation` noting the drift; PRD
authors set `passed_qqq_gate=True` trivially without actually checking
QQQ. The schema serves as audit field; PRD owner decides actual
behavior.

Pros:
- No code change
- Minimal disruption

Cons:
- Lying-by-checkbox pattern (audit signal devalued)
- Future readers will be confused about which to trust
- Phase-2A-style "做出来不算做透" inversion

## Operator recommendation

**Option A** — harden schema to match the existing direction (CLAUDE.md
QQQ deprecation 2026-05-02 + 8-angle infeasibility memo). This is the
honest path: code follows already-decided invariant direction. **But
it's directional** per CLAUDE.md MUST-PAUSE rule for core constraint
changes.

Suggested implementation (post user explicit-go):

```python
# core/config/production_strategy.py
class ProductionStrategyValidation(BaseModel):
    post_fix_validated: bool = False
    passed_oos_gate: bool = False
    passed_qqq_gate: bool = True  # default True per QQQ deprecation
                                   # 2026-05-02; retained for
                                   # audit-trail/diagnostic value
    passed_paper_backtest_alignment: bool = False
    notes: str = ""

    @property
    def all_passed(self) -> bool:
        # QQQ gate removed from hard validation 2026-05-20 per
        # docs/memos/20260502-qqq_benchmark_deprecation.md +
        # 20260520-passed_qqq_gate_schema_decision.md
        return (
            self.post_fix_validated
            and self.passed_oos_gate
            # passed_qqq_gate intentionally NOT in this list
            and self.passed_paper_backtest_alignment
        )
```

## Effect on PRDs

- PRD #3 (canonical promotion): P3.4 already says "QQQ diagnostic
  recorded but not blocking" — schema option A aligns
- PRD #4 (rank-first ML): no direct dependency

## Anti-goal (not in scope)

This decision is ONLY about the validator schema. The actual question
"should trigger-first beat QQQ to be promote-worthy" is separate. The
CLAUDE.md QQQ deprecation already decided that question (no, only SPY
is hard). This memo just aligns the code with that decision.

## Outstanding directional ask

User must explicit-go on which option (A/B/C). Recommended: A. If user
picks A, operator can implement schema change in 1 commit (with tests
updated). If user picks B, PRDs need revision. If user picks C, status
quo + comment-only.
