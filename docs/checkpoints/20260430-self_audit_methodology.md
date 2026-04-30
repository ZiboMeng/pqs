# Self-audit methodology — 4 rounds, runtime-verified

**Effective:** 2026-04-30, forward-only.
**Authority:** user 2026-04-30: "再审两轮吧 不要只读代码 也不要
只跑smoke test 要真正的去跑代码 并且对比结果是否符合预期
不要留下runtime的bug 多考虑边界情况".

This document is the canonical reference for self-audit on this
repo. Any audit phrased as "I checked X" without listing the
4-round output is incomplete by definition.

## When to apply

| Change type | Required rounds |
|-------------|-----------------|
| Schema change (pydantic / yaml / parquet) | R1 + R2 + R3 + R4 |
| Threshold change (acceptance / risk / fleet) | R1 + R2 + R3 + R4 |
| New script / new pipeline stage | R1 + R2 + R3 + R4 |
| Memo with concrete numbers / claims about code state | R1 + R2 + R3 |
| One-line comment / typo / pure prose | R1 |

If unsure, apply all four. R3 is the most-skipped and the
highest-yielding round.

## R1 — Factual correctness

Verify against the live repo, not memory:

- Every file path mentioned: `ls <path>` / `git ls-files <path>`.
- Every class / function / field referenced: grep the actual
  source.
- Every config field referenced: open the yaml and verify line.
- Every commit hash: `git log --oneline | grep <prefix>`.
- Every numerical threshold borrowed from another doc / config:
  read the source location to verify the number, do not quote
  from memory.
- Every yaml / json edited: parse it (`yaml.safe_load(open(path))`
  / `json.loads(open(path).read())`) — syntax is not enough,
  it must round-trip.

R1 output: a table of (claim, verification command, result).

## R2 — Logical / strategic soundness

Independent reasoning, not file-checking:

- Borrowed thresholds: is the number meaningful in THIS domain,
  or was it imported from a neighboring-but-different domain?
  (Worked example: `0.40` is the factor-IC orthogonality
  threshold in `temporal_split.yaml`. NAV-correlation in long-only
  US equity has a higher market-beta floor; reusing 0.40 imports
  a stricter bar than the domain supports.)
- Recommended order: trace each step's blocker — does my order
  match the actual critical path, or did I optimize for "easiest
  first" without regard to "what's needed when"?
- Assumptions: write each load-bearing assumption as one
  sentence. For each, ask "if this is wrong, does the proposal
  still hold?". Mark each as `load_bearing` / `incidental`.
- Effort estimate sanity: nominal effort in MV is the lower
  bound. Realistic with 2 audit-fix cycles is typically 2x
  nominal. Document both.
- "Minimum viable" boundary: is everything labeled MV actually
  the minimum, or have nice-to-haves snuck in?

R2 output: a list of refinements, each with one-sentence
rationale tied to a domain fact.

## R3 — Runtime execution + expectation match

**This is the round most often skipped. Do not skip.**

- For any new script: run it with the actual production input
  (not a fixture / mock). Compare output to manual / independent
  computation.
- For any modified pydantic model: instantiate with realistic
  data and inspect resulting object — pydantic does not catch
  every semantic error.
- For any yaml / json change: load the file via the production
  loader (not just safe_load), verify downstream consumer
  behavior unchanged.
- For any threshold change: simulate two scenarios — one just
  above and one just below the threshold — and verify the
  expected branch fires.
- For any cross-file reference (e.g. "memo X cites file Y at
  line N"): open the file, verify the cited line still says what
  the memo claims.
- For any computed number quoted in a memo: re-run the
  computation in a Python REPL with two-digit precision rounding
  and confirm match.

R3 output: a table of (action, command run, observed, expected,
match Y/N). Failures escalate to immediate fix + re-run.

### R3 anti-patterns (do not count as R3)

- Re-reading the file you just wrote.
- "It compiles" / "yaml.safe_load passes" — that's R1.
- "Tests pass" without examining what those tests actually cover.
- "Looks reasonable" — R3 demands measurement, not vibe.

## R4 — Boundary and failure modes

For each new component, enumerate ≥ 5 corner cases relevant to
the change. For each, write the **expected behavior** before
checking what actually happens:

- Empty input (0 rows / 0 days / 0 files).
- Single-point input (n=1 — any statistic that requires n≥2 must
  raise or return None, never silently zero).
- NaN / inf in critical columns.
- Timezone / calendar boundaries (DST, half-day holidays, weekends).
- Schema drift (extra column, missing column, reordered columns).
- Concurrent write (if a ledger / manifest is involved).
- Process restart mid-write.
- Memory / size boundaries (10K rows vs 10M rows).
- Future-dated input vs past-dated input (esp. forward windows).
- Same spec under different lineage_tag (legitimate vs illegitimate
  combinations).

For each corner case, classify:
- `expected_raise` — code should raise an explicit error, not
  silently coerce.
- `expected_safe_default` — code should produce a documented
  default (e.g. None, empty list) and log at INFO.
- `expected_transparent` — passes through without modification.

R4 output: a table of (corner case, classification, observed
behavior, gap if any).

## Reporting format

Every self-audit output (in commit message, memo, or review log)
follows the structure:

```
### Self-audit Round 1 (factual)
- [V] <claim> — verified by <command>
- [X] <claim> — INCORRECT, see fix in commit <sha> / line <ref>

### Self-audit Round 2 (logical)
- [refinement] <claim> — rationale: <one sentence>

### Self-audit Round 3 (runtime)
- [V] <action> — ran <command>, expected <X>, got <X>, match
- [X] <action> — expected <X>, got <Y>, gap: <fix>

### Self-audit Round 4 (boundary)
- <corner case>: classified <expected_raise|safe_default|transparent>;
  observed <X>; gap: <none|fix>
```

Round-by-round structure makes the audit auditable.

## Anti-pattern: "audit theater"

Listing claims as "verified" without showing the verification
command produces audit theater — looks rigorous, isn't. Every
verified claim needs a paired command or computation. Every
refused claim needs the rejection reason in domain terms.

## When R3 finds runtime bugs

- Stop. Do not commit.
- Fix the bug.
- Re-run R3 to confirm fix.
- Add the corner case that exposed the bug to a regression test
  if it doesn't already exist.
- The audit report records: original symptom, root cause, fix,
  regression test added.

## When R4 finds an unhandled corner case

- Decide: is this case in scope for this change, or out of scope
  but worth flagging?
- In scope: fix the code, re-do R3.
- Out of scope: document explicitly in the memo with a "known
  limitation" section, AND open a tracking item.
- "I'll handle that case if it ever arises" is not acceptable —
  either fix or document.
