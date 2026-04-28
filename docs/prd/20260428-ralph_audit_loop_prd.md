# PRD: 10-Round Ralph-Loop Audit (forward evidence v2.1.3 + codebase-wide)

**Status**: DRAFT (round 0 of 10)
**Date**: 2026-04-28
**Author**: zibo
**Lineage tag**: `ralph-audit-2026-04-28`
**Completion promise**: `RALPHAUDIT10DONE`
**Authority required**: user explicit (zibo) for the loop start; each round
follows §6 authority matrix
**Parent context**: `forward-evidence-hardening-2026-04-27` (the body of work
this loop is auditing) + the broader codebase

---

## 1. Why this audit

Codex Round 9 + Round 10 review of the v2.1.3 forward evidence hardening
exposed **two real correctness blockers AFTER two self-audit rounds had
declared the implementation production-ready**. Both blockers — BDay vs
NYSE-trading-day calendar (~9-row coverage hole at the 252d horizon),
and signal-scope empty-digest fail-close (under-classifying materially
unsafe revisions as `flagged_only`) — were:

1. Catchable by reading the code carefully against the production data store.
2. **Not** catchable by the existing unit tests, because the test
   fixtures used `pd.bdate_range` panels that share `BDay`'s no-holidays
   calendar — masking the very bug the test should have surfaced.
3. **Not** catchable by skim-level "I read the diff" reviews.

The previous audits missed them because of three concrete failure modes.
This loop's hard rules (§3) target each:

| Failure mode | Why it happened | Hard rule that closes it |
|---|---|---|
| Test fixtures shared the bug's calendar | synthetic `bdate_range` ≡ BDay calendar | §3.3 — real-data fixtures for trading-calendar / production-semantics tests |
| No reverse-validation | "tests pass" doesn't prove the asserted bug would have failed a buggy impl | §3.2 — every fix must reverse-validate (revert → reproduce → re-apply → close) |
| PRD-vs-code mapping too coarse | claim-level wording check misses contract-level holes (e.g. revalidate calling `compute_signal_input_hash` without forwarding `track_per_cell`) | §3.1 — live e2e execution + §4.A1 contract re-derivation |

---

## 2. Scope

**10 rounds total**: 3 deep audit of the v2.1.3 forward-evidence work +
7 codebase-wide audit. Each round is a single ralph-loop iteration. No
round may be skipped; a failing round must be re-run.

### Phase A — current work deep audit (3 rounds)
- **A1** — forward evidence module audit (5 modules, contract re-derivation, ≥4 live e2e runs, reverse-validate v2.1.3 fixes)
- **A2** — adversarial scenario design + regression hardening (≥10 codex-uncovered scenarios, new tests for any gap surfaced)
- **A3** — documentation sync for the forward layer (CLAUDE.md / README.md / `docs/INDEX.md` aligned to v2.1.3 reality; remove README changelog if any)

### Phase B — codebase-wide audit (7 rounds, cumulative redundancy)

**Philosophy.** Each Phase B round is a **complete, thorough audit of
the entire codebase** — NOT a divide-and-conquer slice. Each round
applies a different audit lens, and each subsequent round explicitly
re-checks what prior rounds may have missed or glossed over. The
seven rounds compound; they do not partition.

This deliberately trades coverage breadth-per-round for coverage
depth-by-redundancy. Codex Round 10 caught two blockers two prior
single-pass audits had missed; cumulative-pass design is the
structural answer to that failure mode.

- **B1** — **static / contract lens** — read every `core/`, `scripts/`, `dev/scripts/` module; re-derive every public function's contract and compare to its docstring; flag undocumented behavior, contract-vs-docstring drift, dead code paths.
- **B2** — **live e2e execution lens** — run every script's smoke path with real production data (not test fixtures); run pipelines end-to-end (fetch → backtest → paper → report); verify hash-determinism, idempotence, repeated-load consistency. Plus: re-engage every B1 PASS claim that involved runtime behavior.
- **B3** — **adversarial / corner-case lens** — construct ≥30 adversarial scenarios across the whole codebase (empty data, NaN/Inf, single-row, delisted, future-date, timezone shifts, race conditions, config edge cases, wrong types, partial state). Plus: stress every B1+B2 PASS claim with the matching adversarial case.
- **B4** — **cross-cutting invariant lens** — verify global invariants hold *across all modules* (long-only, SQQQ blacklist, QQQ outperformance guards, PRODUCTION/RESEARCH factor separation, raw-bars + read-time-splits adjustment semantics, bar_revision pinning across forward/robustness/OOS, Phase E governance gates reachable, kill_switch 3-tier, multi-TF VETO chain direction-only, append-only manifests). Per invariant: enumerate every file that touches it, verify consistency. Plus: cross-check B1-B3 findings for invariant impact.
- **B5** — **determinism / reproducibility lens** — for every "deterministic" claim in the codebase (forward hashes, manifest writes, factor computation, sort-set ordering, mining seeds, baseline snapshots), run the path twice and assert byte-identical output (or document expected drift). Plus: re-run any B1-B4 PASS claim that asserted "stable" / "deterministic" / "idempotent".
- **B6** — **documentation truth lens** — read every doc in `docs/` + README.md + CLAUDE.md; for every concrete claim (file path, count, command, behavior, threshold), VERIFY against current code; remove README changelog (per §3.6); reconcile CLAUDE.md "Confirmed Done" / "Current TODO" against git log + actual code state. Plus: cross-check that fixes shipped in B1-B5 are reflected in the relevant docs.
- **B7** — **meta-audit / consolidation lens** — read all 6 prior round memos; for each finding marked PASS, challenge the verification rigor (was it really tested or just glossed?); for each non-blocker, reconsider elevation; for each docs-only fix, verify the doc change actually landed; cross-check that the three failure modes from §1 (test fixture sharing bug calendar; no reverse-validation; coarse PRD-vs-code mapping) DID NOT recur in any round. Final master issue list with severity normalized; final docs sweep; emit `RALPHAUDIT10DONE`.

---

## 3. Hard rules (apply to **every** round)

1. **Live-code execution required.** Each round MUST run ≥3 end-to-end
   commands against real data (not only `pytest`). Stdout / stderr quoted
   verbatim in the round memo. Examples qualifying as e2e: a
   `BarStore.load(...)` against `data/daily/`, a real `revalidate_manifest`
   on a live forward manifest, a `run_backtest.py --quick`, etc.
2. **Reverse-validation for every fix.** For each shipped fix, prove
   the bug existed: revert the fix temporarily, observe the pre-fix
   failure, re-apply the fix, observe the post-fix pass. Memo records the
   round-trip with hashes / outputs that differ between the two states.
   No fix is "complete" without reverse-validation.
3. **Real-data fixtures.** Synthetic `pd.bdate_range` is **forbidden**
   for any test asserting trading-calendar / production-semantics
   behavior. Use `BarStore.load(...)` or read `data/daily/*.parquet`
   directly. New regression tests added in this loop MUST follow this
   rule. Existing tests covered by the rule's spirit are flagged
   `non-blocker` if not yet migrated.
4. **Findings classified.** Each finding tagged in the memo:
   - `blocker` — correctness gap (silent wrong answer, lost data, hash collision)
   - `non-blocker` — efficiency / hygiene / latent risk
   - `docs-only` — doc drift; no code change needed
   - `cosmetic` — lint / naming / formatting
5. **Doc-vs-code reconciliation.** Each round closes with a CLAUDE.md /
   README.md / `docs/INDEX.md` sweep for the round's scope. Anything
   claimed in those docs about the round's surface MUST reproduce from
   the git tree as it stands at round end.
6. **README contains NO update log / changelog.** README describes the
   system as it stands TODAY. Git history + ralph-loop log + audit memos
   are the changelog. If a round encounters changelog content in
   README, the round REMOVES it (and references the canonical changelog
   sources in its place).
7. **Memo format pinned.** Each round writes
   `docs/audit/20260428-ralph_audit_round_<NN>.md`:
   - frontmatter: `round`, `phase`, `scope`, `status` (`PASS` / `FIX_LANDED` / `BLOCKERS_OPEN`), `blocker_count`, `commits`
   - § what I read (paths + line ranges)
   - § what I ran (commands + verbatim output excerpts)
   - § issues found (classified table)
   - § fixes shipped + reverse-validation evidence
   - § doc-vs-code reconciliation diff
   - § readiness signal: literal `ROUND <NN> CLOSED, NEXT: <next>` (or `RALPHAUDIT10DONE` after R10)
8. **11-part Chinese summary.** Each round also appends a brief
   11-part Chinese block to `docs/20260420-ralph_loop_log.md` under
   `## R-ralph-audit-2026-04-28-round-NN`, ending with a one-line
   pointer to the full English memo path. The memo is the source of
   truth; the log entry is the fast-scan index.
9. **Push memo to `review/claude-collab`** at round end so codex /
   peer reviewers can read it. Code / doc fixes commit on `main`.
10. **Cross-round meta-check (Phase B only).** Each Phase B round
    after the first MUST read every prior B-round memo and:
    - Re-engage every `PASS` claim that touches the current round's
      lens (e.g. B2's live-execution lens re-runs B1's contract
      claims that involved runtime behavior; B5's determinism lens
      re-runs anything B1-B4 called "stable" / "idempotent" /
      "deterministic").
    - For every prior `non-blocker` finding, reconsider whether the
      current round's evidence elevates it.
    - Append a `cross-round meta-check` section to the current
      round's memo listing what was re-engaged + outcome
      (CONFIRMED / CHALLENGED / ELEVATED).
    Phase B is cumulative: each round's memo becomes input to all
    subsequent rounds. Late rounds get progressively more skeptical.

---

## 4. Per-round briefs

### Round 1 (A1) — forward evidence module audit
**Read.** `core/research/forward/{bar_hash,revalidate,runner,source_layer,manifest_schema}.py` (5 modules, full re-read).

**Re-derive every public-function contract** (preconditions / postconditions / exceptions / determinism guarantees) and compare to PRD `docs/prd/20260427-forward_evidence_hardening_prd.md` v2.1.3 changelog blocks. Flag any contract-level mismatch.

**Live e2e runs (≥4).** Each on the real RCMv1 manifest + live `data/daily/*.parquet`:
1. clean revalidate (no revisions expected → 0 events)
2. simulated sub-threshold revision → `flagged_only` event persisted across the no-new-bar return path
3. simulated true-252nd-prior trading-day revision → `signal_input_hash` flips (Blocker-1 verification)
4. simulated empty-digest + dual-scope diff → `invalidated` (Blocker-2 verification)

**Reverse-validate v2.1.3 fixes.** For each of Blocker 1 (BDay swap) and Blocker 2 (empty-digest gate), revert the fix, reproduce the original bug end-to-end, re-apply, observe close. Memo records hashes / output before vs after.

**Acceptance.** Zero new blocker findings, OR if new blockers found, fix shipped + reverse-validated within the round.

### Round 2 (A2) — adversarial scenarios + regression hardening
**Design ≥10 scenarios codex did NOT cover.** Suggested catalog (pick + extend):
- delisted symbol mid-forward-window (NaN bars on the held name)
- `bar_revision` field change → hash diff (already covered? verify)
- `lookback > panel.length` → `window_start = panel.earliest`
- all-NaN bar in window → deterministic hash, no crash
- same symbol in held + universe + benchmark
- `cost_assumptions` change → must NOT trigger bar revision (separate scope)
- 0-weight position + revision (E1 NAV impact = 0; E5 raw drift fires?)
- `dry_run=True` + revision detected → NO save
- source_layer mixed / canonical / frontier classification edge cases
- manifest with only TD001 baseline + first revalidate (legacy boundary)
- 2-candidate concurrent observe (file-lock / race condition)
- timezone / DST boundary on `as_of_date`

**Each scenario.** Predict expected behavior; run end-to-end; record actual; if a gap is found, add a regression test (real-data fixture per §3.3) and fix.

**Acceptance.** Every designed scenario covered with verbatim output; every gap test-pinned.

### Round 3 (A3) — forward documentation sync
**CLAUDE.md sections to verify against current code.** "Forward OOS active workstream", "R-fwd-1 / R-fwd-2 / R-fwd-3 evidence-hardening done", "Framework Completion PRD" M11a/b/M12/M14 status hygiene, "Factor Pipeline Contract", "Multi-TF Timing Contract", "Data Provenance Sidecar", "1m Bar Pipeline", "Trades Backfill". Every sentence must reproduce from current code.

**README.md.** Locate, audit, **remove update log / changelog if any** (per §3.6). Verify every script name, every config name, every feature count claim; fix drift.

**`docs/INDEX.md`.** Confirm new audit memos + this PRD entered. Update count in section headers.

**`data/baseline/latest.json`.** Regenerate via `python dev/scripts/baseline/build_research_baseline_snapshot.py` if test count drift detected.

**Acceptance.** CLAUDE.md / README.md / INDEX.md all reproducible from git HEAD; baseline refreshed; README contains zero changelog content.

### Round 4 (B1) — full codebase under static / contract lens
**Surface.** Every module under `core/`, `scripts/`, `dev/scripts/`. The full codebase, not a slice.

**Audit method.**
- Read every module systematically. Build a global contract index: for each public function / class, record (signature → preconditions → postconditions → exceptions → determinism guarantees).
- Compare each contract to the module's own docstrings + any claim in `docs/` or CLAUDE.md.
- Flag: undocumented behavior, contract-vs-docstring drift, dead code paths, type-hint vs runtime mismatch, silent except-pass, shadowed builtins, magic-number thresholds without config-source.
- Cross-reference cousin modules (e.g. `core/research/robustness/runner.py` vs `core/research/forward/runner.py` — should the bar_revision pin reach both?).

**Live runs (≥3).** Even though this round's lens is static, ≥3 e2e runs are still required per §3.1. Suggested: import smoke (`python -c "import core; import scripts"` style sweep), one full pipeline run (`run_backtest --quick`), one cross-module path that touches ≥4 packages.

**Acceptance.** Global contract index produced (memo §; can be a CSV / table); every public symbol classified; every drift / undocumented finding logged with severity.

### Round 5 (B2) — full codebase under live e2e execution lens
**Surface.** Same — everything. New angle.

**Audit method.**
- Run every script's smoke path with **real production data** (not test fixtures). Goal: reach the longest happy path of each major code path at least once.
- Pipelines: data fetch → factor screen → mining → backtest → paper → report. Run end-to-end where feasible; document the exact commands and verbatim output.
- Determinism spot-checks: run the same path twice on cold cache; check byte-equal where claimed; document drift if any.
- **Cross-round meta-check (per §3.10):** re-engage every B1 PASS claim that involved runtime behavior. If B1 said "this function is idempotent" without running it twice, run it twice now.

**Live runs (≥6).** Roughly: 3 full pipeline e2e + 3 idempotence spot-checks. More if the codebase has more independent paths.

**Acceptance.** Every major code path exercised on production data; outputs verified against expectations; B1's runtime-claim PASS list cross-confirmed.

### Round 6 (B3) — full codebase under adversarial / corner-case lens
**Surface.** Same — everything. New angle.

**Audit method.**
- Construct ≥30 adversarial scenarios spanning the codebase. Suggested categories:
  - empty inputs (empty df, empty list, empty manifest)
  - NaN / Inf / mixed-type cells
  - single-row / single-symbol / single-date corner cases
  - delisted / pre-IPO / split-day boundary cases
  - future-date / past-the-store / before-baseline cases
  - timezone / DST / leap-year boundary cases
  - race conditions (concurrent observe, concurrent miner)
  - config edge cases (zero weight, weight summing to non-1, missing factor)
  - wrong types passed (float where int expected, str where path expected)
  - partial state (half-written file, mid-revalidate manifest)
- For each scenario: predict expected behavior, run, record actual, predict-vs-actual delta, decide fix vs document-as-known.
- **Cross-round meta-check (per §3.10):** stress every B1+B2 PASS claim with the matching adversarial case. If B1 said "function handles missing data gracefully", construct the missing-data scenario and verify.

**Live runs (≥30 scenarios).** Each scenario counts; not every needs separate process invocation.

**Acceptance.** Every designed scenario has predicted+actual recorded; gap → fix or test (real-data fixture per §3.3); B1+B2 adversarial gaps surfaced.

### Round 7 (B4) — full codebase under cross-cutting invariant lens
**Surface.** Same — everything. New angle.

**Audit method.**
- Enumerate every invariant the system depends on. Anchor list (extend if you find more):
  - long-only (no short, no margin)
  - SQQQ blacklist; TQQQ/SOXL stricter risk thresholds
  - QQQ Outperformance Rule (full-period + holdout + mean-OOS)
  - PRODUCTION_FACTORS / RESEARCH_FACTORS strict separation
  - Pricing semantics (raw bars + read-time splits.parquet adjustment; no dividends yet)
  - bar_revision pinning (`DAILY_STORE_REBUILD_COMMIT`) consistent across forward / robustness / OOS
  - Phase E governance gates reachable from acceptance_pack
  - kill_switch 3-tier auto-recovery
  - multi-TF VETO chain direction-only (lower TF can defer but not flip)
  - append-only manifest contract (forward + frozen_spec)
  - 7-factor production set + factor_guard
  - Chinese reporting / English code naming convention
- Per invariant: enumerate every file that touches it (grep + read); verify consistency across all touch points; flag any drift.
- **Cross-round meta-check (per §3.10):** for every B1-B3 finding, ask "does this finding affect any invariant?" If yes, the finding's severity is reconsidered.

**Live runs (≥3).** Suggested: a backtest that would VIOLATE an invariant if guard absent (synthetic SQQQ in universe → must be filtered); a kill_switch 3-tier dry-run; a synthesized factor_weights with unknown factor name (must WARN + DROP).

**Acceptance.** Each invariant has a "touched-by" file list + verification status (HOLDS / VIOLATED-AND-FIXED / OPEN-BLOCKER) + cross-round impact assessment.

### Round 8 (B5) — full codebase under determinism / reproducibility lens
**Surface.** Same — everything. New angle.

**Audit method.**
- Identify every "deterministic / stable / idempotent / reproducible" claim in the code or docs. Anchor list:
  - forward `signal_input_hash` / `execution_nav_hash` / `benchmark_hash` / `bar_hash` rollup
  - `compute_factor_value` deterministic across calls
  - `BarStore.load` deterministic (same bytes from same revision)
  - `frozen_spec` SHA pin
  - `acceptance_pack` Gate ordering
  - sort-set ordering in `_generate_orders` (M11a fix lineage)
  - mining seed handling
  - baseline snapshot reproducibility
  - manifest writes append-only
- Per claim: run the path twice (cold), assert byte-equal output (or document expected drift). For non-byte-equal cases (timestamps, e.g.), assert structural-equal modulo the documented field set.
- Cross-platform considerations (Linux only for now — local-only assertion).
- **Cross-round meta-check (per §3.10):** re-run any B1-B4 PASS claim that asserted "stable" / "deterministic" / "idempotent" with a run-twice protocol.

**Live runs (≥3 paired byte-equal checks).**

**Acceptance.** Every determinism claim test-pinned (regression test added if not already); B1-B4 stability claims byte-confirmed.

### Round 9 (B6) — full codebase under documentation truth lens
**Surface.** Every doc file: README.md, CLAUDE.md, every file in `docs/`. Plus every docstring in `core/` and `scripts/` for high-traffic public functions.

**Audit method.**
- For every concrete claim (file path, count, command, behavior, threshold, "shipped" / "done" / "deferred" status), VERIFY against current code:
  - file path → `ls`
  - count → grep + count
  - command → run it
  - behavior → trace the code or run an e2e
  - threshold → grep config + grep code
  - status → check git log + check the actual file content
- README.md: locate, audit, **REMOVE update log / changelog if any** (per §3.6). README describes the system as it stands TODAY.
- CLAUDE.md: reconcile "Confirmed Done" / "Current TODO" against git log + actual code state. Especially the Forward OOS workstream + Framework Completion PRD M-numbered milestones.
- `docs/INDEX.md`: confirm every doc has an entry; counts in section headers correct.
- **Cross-round meta-check (per §3.10):** for every fix shipped in B1-B5, verify the relevant doc reflects the fix.

**Live runs (≥3).** Suggested: every claimed `python scripts/...` command executed; every claimed config path read; every claimed test count compared to `pytest --collect-only` output.

**Acceptance.** Every doc reproducible from git HEAD; README clean of changelog; CLAUDE.md TODO synced; INDEX.md complete.

### Round 10 (B7) — meta-audit + final consolidation
**Surface.** All 6 prior round memos + the codebase as it stands at this round's start.

**Audit method.**
- **Meta-challenge.** Read every prior round memo. For each finding marked PASS, challenge:
  - Was the verification rigor commensurate with the finding's risk?
  - Was the e2e command a real production path or a synthetic toy?
  - Did the round actually reverse-validate any fixes, or just assert tests pass?
- **Severity normalization.** Every prior `non-blocker` reconsidered: does the cumulative evidence (all 6 rounds) elevate it? Every prior `docs-only`: did the doc fix actually land?
- **Failure-mode recurrence check.** Cross-check that the three failure modes from §1 (test fixture sharing bug calendar; no reverse-validation; coarse PRD-vs-code mapping) DID NOT recur in any round. If a recurrence is found, the round that produced it is RE-RUN.
- **Final master issue list.** Every finding from B1-B6 + this round, severity-normalized, cross-referenced to its round memo by issue ID (R<NN>.<idx>), grouped by severity.
- **Final docs sweep.** CLAUDE.md / README.md / `docs/INDEX.md` one more time, after all B1-B6 fixes have landed.
- `data/baseline/latest.json` regenerated.

**Live runs (≥3).** Suggested: one full pipeline e2e top-to-bottom; `pytest tests/` full run; `bash scripts/run_all.sh` syntax check.

**Acceptance.** Zero open blocker; every prior round's claims meta-verified; CLAUDE.md / README / INDEX synced; baseline refreshed; emit `RALPHAUDIT10DONE`.

---

## 5. Halt conditions

Any **one** triggers halt + user surface (no autonomous continue):

1. 10 rounds completed (ceiling — emit `RALPHAUDIT10DONE`).
2. Test count drops by > 10 vs round-0 baseline.
3. Core import breaks (`python -c "from core.research.forward import compute_signal_input_hash"`).
4. A finding requires a schema migration (manifest, frozen_spec, etc.) or a new PRD to resolve.
5. Reverse-validation fails (claimed fix doesn't actually close the bug → fix is incorrect; deeper analysis needed).
6. CLAUDE.md / README.md drift cannot be fixed without code changes outside the round's scope (escalate; cross-cutting issues warrant their own round).
7. Disk free < 10 GB.

---

## 6. Authority matrix

### Authorized autonomously
- Bug fixes inside existing files (incl. tests).
- Docstring + comment corrections.
- Adding regression tests for discovered bugs (real-data fixtures per §3.3).
- README / CLAUDE.md / `docs/INDEX.md` edits.
- Baseline snapshot regeneration (`data/baseline/latest.json`).
- Memo + log writes.

### Pause for user
- Schema changes (`ForwardRunManifest`, `FrozenStrategySpec`, etc.).
- Public function / class deletions referenced elsewhere.
- Changes to `PRODUCTION_FACTORS` / `config/universe.yaml` / `config/production_strategy.yaml` unless concrete bug + fix stays inside documented schema.
- Dependency additions (`requirements.txt` / `pyproject.toml`).
- Changes to invariant constraints in CLAUDE.md (long-only, no-margin, QQQ rule, pricing semantics, etc.).
- Re-running production observe (`forward observe`) — this loop does NOT touch live RCMv1 / Cand-2 manifests except read-only.

---

## 7. Memo template (per round)

```markdown
---
round: <NN>
phase: <A|B>
scope: <one-line>
status: PASS | FIX_LANDED | BLOCKERS_OPEN
blocker_count: <int>
non_blocker_count: <int>
docs_only_count: <int>
cosmetic_count: <int>
commits: <main hashes>
review_commit: <review/claude-collab hash>
parent_round: <round-(N-1) memo path or "none">
---

## What I read
- <path>:<line range> — <short note on contract / claim>
- ...

## What I ran (live e2e + tests)
1. `<cmd>` →
   ```
   <verbatim output excerpt>
   ```
2. ...

## Issues found

| ID | Severity | File:Line | Description | Fix? |
|----|----------|-----------|-------------|------|
| R<NN>.1 | blocker | path:line | ... | shipped @ commit |
| R<NN>.2 | docs-only | docs/X.md:L | ... | shipped @ commit |
| ... |

## Fixes shipped + reverse-validation
- **R<NN>.1** — <description>
  - Pre-fix repro: `<cmd>` → `<output proving bug exists>`
  - Fix commit: `<hash>`
  - Post-fix repro: `<same cmd>` → `<output proving bug closed>`

## Doc-vs-code reconciliation
- CLAUDE.md: <changes>
- README.md: <changes; explicitly note any update-log removals>
- docs/INDEX.md: <changes>

## Readiness signal
ROUND <NN> CLOSED, NEXT: <NN+1>   # or RALPHAUDIT10DONE after R10
```

---

## 8. Lineage

- Parent: `forward-evidence-hardening-2026-04-27` (the body of work this loop's Phase A audits)
- This loop: `ralph-audit-2026-04-28`

---

## 9. One-sentence summary

**10-round ralph-loop audit: 3 deep rounds on forward evidence v2.1.3,
then 7 cumulative-pass full-codebase rounds (each round audits the
entire codebase under a different lens — static / live-e2e /
adversarial / cross-cutting-invariant / determinism / documentation /
meta-consolidation — with each later round explicitly re-engaging
prior rounds' PASS claims), under hard rules requiring live e2e
execution + reverse-validation + real-data fixtures + doc-vs-code
reconciliation + a zero-changelog README — designed to close the
failure modes that let two correctness blockers slip past two prior
self-audit rounds.**
