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

### Phase B — codebase-wide audit (7 rounds)
- **B1** — data layer (`core/data/*` + ingest scripts)
- **B2** — research framework (`core/research/*` excl. forward, which A1-A3 covered)
- **B3** — backtest + paper trading parity (`core/backtest/*` + `core/paper_trading/*`)
- **B4** — factor pipeline + mining (`core/factors/*` + `core/mining/*`)
- **B5** — strategy + execution layer (`core/signals/*` + `core/risk/*` + `core/intraday/*`)
- **B6** — reporting + diagnostics (`core/reporting/*` + `core/diagnostics/*`)
- **B7** — scripts / CLI / final integration consolidation (every `scripts/*` + `scripts/run_all.sh` + master issue list across B1-B6)

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

### Round 4 (B1) — data layer
**Files.** `core/data/{bar_store, daily_aggregator, market_data_store, validator, calendar, yfinance_provider, source_boundary_registry}.py`. Scripts: `scripts/{fetch_data, build_bars_parquet, build_splits_parquet, aggregate_bars, build_catalog, validate_vs_yfinance}.py`.

**Live runs (≥3).** `BarStore.load` 5 real symbols at daily / 60m / 30m; verify splits.parquet idempotent; provenance sidecar consistency cross-checked vs source-boundary registry; `validate_vs_yfinance` smoke on 1 ticker.

**Acceptance.** Hash-determinism on a clean store snapshot (load twice → identical content); no silent re-fetch; splits applied identically across two loads; provenance reflects expected source_type for the test tickers.

### Round 5 (B2) — research framework (excl. forward, covered in A1-A3)
**Files.** `core/research/{robustness, concentration, frozen_spec, candidate_registry, drift_metrics}.py` + `core/research/oos/`.

**Live runs (≥3).** Robustness eval on 1 candidate (RCMv1 or Cand-2, NOT a full mining cycle); concentration metrics on a recent backtest result; revalidate live RCMv1 + Cand-2 manifests as a cross-link with A1 (must remain green).

**Acceptance.** M12 enforcement reachable via `acceptance_pack` Gate 7; watchlist gate fires correctly on a synthetically-constructed failing case; concentration thin-data weighted gate matches PRD v2.1.

### Round 6 (B3) — backtest + paper trading parity
**Files.** `core/backtest/*` + `core/paper_trading/*` + `scripts/run_backtest.py` + `scripts/run_paper_candidate.py`.

**Live runs (≥3).** `run_backtest --quick` on 1 candidate; `run_paper_candidate` on the same candidate, same window; compute drift; M14 NaN-equity sanity check via 4 paper cells.

**Acceptance.** Drift ≤ 1 bps/day, ≤ 5 bps cumulative (M11a/b parity contract); zero NaN-equity rows (M14); deterministic ordering under fixed PYTHONHASHSEED.

### Round 7 (B4) — factor pipeline + mining
**Files.** `core/factors/*` + `core/mining/*` + `scripts/run_factor_screen.py` + `scripts/run_xgb_importance.py` + `scripts/run_research_miner.py` (smoke only — no real mining cycle).

**Live runs (≥3).** `run_factor_screen` on 7 production factors; `run_xgb_importance` on the same set; `MultiFactorSpace` startup assertion fires on synthetic deviation from `_TUNED_FACTORS`.

**Acceptance.** PRODUCTION_FACTORS / RESEARCH_FACTORS separation enforced (unknown name in `MultiFactorStrategy.factor_weights` → WARNING + DROP); `factor_guard` masks volume on `trades_backfill`-provenance tickers; `MultiFactorSpace._TUNED_FACTORS` consistency assertion fires.

### Round 8 (B5) — strategy + execution layer
**Files.** `core/signals/strategies/*` + `core/signals/left_side.py` + `core/risk/{kill_switch, failure_detector, stress_tester}.py` + `core/intraday/multi_timescale.py`.

**Live runs (≥3).** Backtest with `MultiFactorStrategy` on 1 candidate; `kill_switch` 3-tier auto-recovery test on a synthetic crash trace; `multi_timescale.decide_timing` dispatch on a real intraday context.

**Acceptance.** Long-only invariant held under stress; kill switch 3-tier auto-recovery green; multi-TF VETO chain works (60m can scale to 0; 30m penalty applies; 15m / 5m never flip direction).

### Round 9 (B6) — reporting + diagnostics
**Files.** `core/reporting/{master_report, master_report_builder, intraday_report}.py` + `core/diagnostics/detectors.py`.

**Live runs (≥3).** Generate master report on a real backtest result; verify report contains: vs-QQQ column, watch_exposure section, M12 concentration metrics, regime-stratified table, source-layer breakdown.

**Acceptance.** Report matches PRD reporting requirements; Phase E governance gates surfaced; no silent NaN cells.

### Round 10 (B7) — scripts / CLI + final consolidation
**Files.** Every `scripts/*.py` + `scripts/run_all.sh`.

**Live runs.** `--help` smoke on every script (must exit 0 — earlier audit-v2 rounds caught 3 `--help` regressions); `bash scripts/run_all.sh research --dry-run` (or whatever path applies — script may not have a dry-run flag, then `bash -n scripts/run_all.sh` for syntax check); `bash scripts/run_all.sh` paths visually traced.

**Final consolidation.** Memo lists all issues found across B1-B6 grouped by severity, cross-referenced to round memos. CLAUDE.md global drift sweep one more time.

**Acceptance.** Every CLI script exits 0 on `--help`; `run_all.sh` paths reachable; final memo cross-references every memo from B1-B6 by issue ID; CLAUDE.md / README.md / INDEX.md reconciled.

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

**10-round ralph-loop audit (3 deep on forward evidence v2.1.3 + 7
codebase-wide), with hard rules requiring live e2e execution + reverse-
validation + real-data fixtures + doc-vs-code reconciliation + a
zero-changelog README contract — designed to close the failure modes
that let two correctness blockers slip past two prior self-audit
rounds.**
