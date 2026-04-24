# Path + Naming Conventions Proposal (2026-04-24)

> **Status**: Proposal. Evaluates two historical legacies and proposes
> forward-only rules. Per user instruction (2026-04-24): "定好规则 之
> 后再执行 历史的东西就先这样" — set the rules, leave history, apply
> to new artifacts.

## 1. Problem statement

### 1.1 Artifact paths are scattered

As of 2026-04-24 the repo has research artifacts across:

```
data/baseline/              snapshot.json (gitignored)
data/daily/                 raw bars
data/intraday/              raw bars
data/factor_candidates/     1 YAML + README (early factor candidate)
data/mining/                archive.db + rcm_archive.db + optuna.db
data/ml/                    57 files/dirs — the big soup
  research_miner/           RCMv1 trial outputs + top-K (keep)
  llm_candidates/           LLM-proposed factors
  llm_composite_backtests/  LLM composite replays
  llm_deep_checks/          LLM factor deep-check outputs
  llm_factor_backtests/     LLM factor single-backtests
  llm_orthog/               orthogonalization reports
  llm_sidecar_r10/..r26/    per-round LLM funnel artifacts
  transformer/              R47-R48 transformer research
  xgb_cv/, xgb_weights/     R46 XGBoost research
  r33_grid/                 R33 weight grid search
  factor_interactions/      Round 8 cross-TF feature training
  <top-level .csv / .parquet / .json> — standalone diagnostic outputs
data/paper_runs/            per-run paper artifacts (gitignored, R10+)
data/paper_trading/         old paper_trading.db
data/ref/                   splits.parquet + bar_provenance.parquet
data/research_candidates/   Phase E governance (new 2026-04-24)
  rcm_v1_defensive_composite_01.yaml   frozen spec
  registry.db                          (gitignored)

docs/                       39 markdown files: PRDs + memos + findings
                            + round logs + synthesis + proposals, all
                            mixed with date prefixes as the only sort

reports/
  backtests/                per-backtest output
  consolidate_sanity/       data-consolidation QA
  known_data_issues/        ZTST sentinel, etc.
  post_processing/          trades-scanner QA
  trades_backfill_qa/       trades backfill QA
```

### 1.2 Concrete pain point from Phase E

To find all artifacts related to RCMv1 `rcm_v1_defensive_composite_01`:

| Artifact | Current location |
|---|---|
| Frozen spec YAML | `data/research_candidates/rcm_v1_defensive_composite_01.yaml` |
| Decision memo | `docs/20260424-rcm_v1_s1_candidate_memo.md` |
| Registry row | `data/research_candidates/registry.db` |
| Source trial | `data/mining/rcm_archive.db::rcm_trials[f24aefecc91a]` |
| Acceptance JSON | `data/ml/research_miner/rcm-v1-run-02-lag1/acceptance/acceptance_f24aefecc91a.json` |
| Diagnostic CSV | `data/ml/research_miner/rcm-v1-run-02-lag1/diagnostics/*.csv` |
| Paper run artifacts | `data/paper_runs/rcm_v1_defensive_composite_01/<ts>/*` |
| Drift reports | `data/paper_runs/rcm_v1_defensive_composite_01/<ts>/drift_report_*.md` |
| Synthesis doc | `docs/20260424-rcm_v1_final_synthesis.md` |
| Promotion memo | `docs/20260424-rcm_v1_s1_candidate_memo.md` (same as decision memo) |

Finding all these for an audit requires knowing 5+ different paths.
When paper layer actually gets used in production, auditors will
hate it.

### 1.3 scripts/ directory mixes concerns

`scripts/` has 64 `.py` + 7 `.sh` files serving three different purposes:

- **Quant ops** (what user expects scripts/ to hold): fetch_data,
  run_backtest, run_paper, run_mining, run_xgb_*, research_promote,
  freeze_research_candidate, paper_enter, etc. → 50+ files
- **Dev / meta / loop orchestration** (shouldn't be here):
  - 6 `start_*_loop.sh` ralph-loop launchers
  - `run_all.sh` convenience wrapper
  - `build_research_baseline_snapshot.py` (dev baseline tool)
  - `send_round_summary.py` (wecom notification from loop)
  - `dump_llm_handoff_context.py` (LLM context dump)
  - `demo_cross_ticker_rules.py` (tutorial/demo, not a real run)
  - `disk_guard.py` (ops guardrail daemon)
  - `migrate_provenance.py` (one-time data migration)
  - `migrate_rcm_v1_memo_to_registry.py` (one-time R3 migration)

## 2. Forward-only rules

### 2.1 Rule A — Candidate-bundle principle

Every artifact keyed on a `candidate_id` (Phase E S0+) SHALL live under
a single directory:

```
data/research_candidates/<candidate_id>/
    frozen_spec.yaml            # the only canonical spec file
    decision_memo.md            # primary memo (research_promote input)
    revoke_memo_<ts>.md         # one per revocation (if any)
    acceptance_<trial_id>.json  # copy / symlink from data/ml/
    paper_runs/<ts>/            # per-run artifacts, per-candidate
        signals_daily.csv
        pnl_daily.csv
        drift_report_<ts>.md
        (etc. per paper_artifact_schema.md)
```

Rationale: one grep, one cd, one audit. This replaces the current
split where `frozen_spec` lives in `data/research_candidates/` but
`decision_memo.md` lives in `docs/` and `paper_runs` live in `data/paper_runs/`.

**Going forward**: any NEW candidate goes into `data/research_candidates/<id>/`
with ALL its artifacts bundled. Existing RCMv1 stays bundled across
existing paths; R11 test (`test_rcmv1_candidate_in_s2_after_r11`)
pins the current state.

**Registry** stays at `data/research_candidates/registry.db` as the
index; it already records `frozen_spec_path` + `decision_memo_path`
which are the canonical references.

### 2.2 Rule B — docs/ should be cross-cutting, not per-artifact

New `docs/` contents go into one of:

| subdir | content |
|---|---|
| `docs/prds/` | PRDs + charter docs (no artifacts, only planning) |
| `docs/synthesis/` | Cross-round or phase synthesis reports |
| `docs/reference/` | Schemas, conventions (like this doc), API contracts |
| `docs/archive/` | Historical / superseded docs |
| `docs/` (root) | Active cross-cutting — ralph_loop_log.md, this convention doc |

**Per-candidate artifacts** (memos, spec YAMLs, acceptance JSONs) go
into `data/research_candidates/<id>/`, NOT `docs/`.

**Per-round reports** stay in `docs/20260420-ralph_loop_log.md`
append-only (not one file per round — that's the current working
model, keep it).

### 2.3 Rule C — **Hard split: quant substance vs dev process**

Per user (2026-04-24): "开发和美股量化本身结果分开" — separate the
**quantitative substance** (what this project does: analyze US
equities, run strategies, find alpha) from the **dev process**
(how the codebase is built and maintained: ralph-loop orchestration,
code audits, migration tooling, infra PRDs).

Proposed top-level layout:

```
# quantitative substance (the product)
core/                   quant library (unchanged)
scripts/                quant ops — anything that runs a strategy,
                        fetches data, mines, papers, promotes, reports
config/                 quant config (unchanged)
data/                   quant data + candidates + paper runs + archives
reports/                quant run output (unchanged)

docs/                   quant research docs:
                          - research findings / synthesis
                          - per-candidate memos and proposals
                          - ralph_loop_log.md (round-level quant logs)
                          - quant research plans (feature engineering,
                            mining methodology, feature tier classification)
                          - feature data tier classification
                          - paper_artifact_schema.md (quant contract)

# dev process (the meta)
dev/                    NEW top-level directory
  docs/                 dev PRDs:
                          - codebase_audit_3round
                          - phase_e_execution / phase_e_governance
                          - layered_quant_architecture
                          - research_to_paper_promote_standard
                          - path_naming_conventions (this doc)
                          - framework_completion
                          - ralph_loop_prompt
                          - promotion_flow
  scripts/              dev tooling:
                          - loop/              ralph-loop launchers
                          - migrations/        one-time data migrations
                          - baseline/          baseline snapshot builder
                          - notify/            wecom bot sender
                          - llm_handoff/       LLM context dump
                          - demo/              tutorials / examples
                          - ops/               disk_guard
  artifacts/            dev artifacts (gitignored):
                          - baseline snapshots
                          - test coverage reports
```

**Scope of split**:

| Existing item | Stay / Move |
|---|---|
| `core/*` | STAY (quant library) |
| `config/*` | STAY (quant config) |
| `data/*` | STAY (quant data) |
| `reports/*` | STAY (quant run output) |
| **Quant PRDs / findings / memos in `docs/`** | STAY |
| **Dev PRDs in `docs/`** (codebase_audit, phase_e_*, layered_arch, etc.) | → `dev/docs/` |
| `scripts/run_*.py / fetch_*.py / research_promote / freeze / paper_enter / revoke / acceptance_* / promote_strategy / generate_report / validate_* / universe_* / llm_* / analyze_research_miner_run / compare_multi_factor_shift / r33_weight_grid_search / weight_sensitivity_research_composite / feat_v1_topk_analysis` | STAY |
| `scripts/start_*_loop.sh` | → `dev/scripts/loop/` |
| `scripts/run_all.sh` | STAY (quant convenience wrapper) |
| `scripts/migrate_*.py` | → `dev/scripts/migrations/` |
| `scripts/build_research_baseline_snapshot.py` | → `dev/scripts/baseline/` |
| `scripts/send_round_summary.py` | → `dev/scripts/notify/` |
| `scripts/dump_llm_handoff_context.py` | → `dev/scripts/llm_handoff/` |
| `scripts/demo_cross_ticker_rules.py` | → `dev/scripts/demo/` |
| `scripts/disk_guard.py` | → `dev/scripts/ops/` |

### 2.4 Rule D — Classify each `docs/*.md` at write time

Every new markdown dropped under `docs/` or `dev/docs/` must match
one category:

| Category | Home | Examples |
|---|---|---|
| Dev process PRD / architecture | `dev/docs/` | codebase audit PRD, phase-e execution, layered architecture |
| Quant research PRD | `docs/` | RCMv1 PRD, deep-mining PRD, feature-engineering PRD |
| Quant research finding / synthesis | `docs/` | RCMv1 final synthesis, R46 XGBoost findings, transformer phase 1 findings |
| Per-candidate memo | `data/research_candidates/<id>/` | RCMv1 S1 memo (future) |
| Quant contract / schema | `docs/` | paper_artifact_schema.md, feature data tier classification |
| Per-round log | `docs/20260420-ralph_loop_log.md` (single file append-only) | all round reports |
| One-off LLM handoff / prompt | `dev/docs/` | llm_proposal_prompt_template, llm_external_llm_handoff |

### 2.5 Rule E — Naming

Going forward:

- Files: `snake_case.py` / `snake_case.md`
- Docs with dates: `YYYYMMDD-<topic>.md` (existing convention; keep)
- Candidate IDs: `<source>_v<N>_<trait>_<NN>` e.g. `rcm_v1_defensive_composite_01`
- Paper-run directory timestamp: `YYYYMMDDTHHMMSSZ` (existing)
- Lineage tags: `post-<date>-<project>-<variant>` e.g. `post-2026-04-24-rcm-v1-lag1`

## 3. Migration scope proposal

Three explicit phases. Execute per user direction; do NOT assume all
three run automatically.

### 3.1 Phase X-0 — Create `dev/` top-level + migrate shell launchers

(~30 min, zero behavior-risk, highest visibility benefit)

- `mkdir dev dev/docs dev/scripts dev/scripts/{loop,migrations,baseline,notify,llm_handoff,demo,ops} dev/artifacts`
- `git mv scripts/start_*_loop.sh dev/scripts/loop/` (6 files)
- Update internal `PRD_PATH=` relative paths in each launcher
  (they reference `docs/20260424-prd_*.md` which are still reachable)
- Update README + CLAUDE.md references: `bash scripts/start_X.sh`
  → `bash dev/scripts/loop/start_X.sh`
- `.gitignore`: add `dev/artifacts/`

### 3.2 Phase X-1 — Migrate dev Python tooling

(~45 min, low-risk)

| From | To |
|---|---|
| `scripts/migrate_provenance.py` | `dev/scripts/migrations/` |
| `scripts/migrate_rcm_v1_memo_to_registry.py` | `dev/scripts/migrations/` |
| `scripts/build_research_baseline_snapshot.py` | `dev/scripts/baseline/` |
| `scripts/send_round_summary.py` | `dev/scripts/notify/` |
| `scripts/dump_llm_handoff_context.py` | `dev/scripts/llm_handoff/` |
| `scripts/demo_cross_ticker_rules.py` | `dev/scripts/demo/` |
| `scripts/disk_guard.py` | `dev/scripts/ops/` |

- `git mv` each, update imports if needed
- Grep refs: `scripts/build_research_baseline_snapshot`,
  `scripts/disk_guard`, etc. in CLAUDE.md / README / per-round logs /
  launcher shells
- Keep script entry points runnable (they're `sys.path.insert` scripts
  so location-agnostic; just update docs)

**Net `scripts/` delta**: 64 .py + 7 .sh → ~50 .py + 1 .sh (run_all.sh).
Clean quant-ops only.

### 3.3 Phase X-2 — Migrate dev docs from `docs/` to `dev/docs/`

(~30 min, MEDIUM-risk — lots of cross-references)

| From | To |
|---|---|
| `docs/20260424-prd_codebase_audit_3round.md` | `dev/docs/` |
| `docs/20260424-prd_phase_e_execution.md` | `dev/docs/` |
| `docs/20260424-prd_phase_e_governance_and_paper.md` | `dev/docs/` |
| `docs/20260424-prd_layered_quant_architecture.md` | `dev/docs/` |
| `docs/20260424-prd_research_to_paper_promote_standard.md` | `dev/docs/` |
| `docs/20260424-path_naming_conventions_proposal.md` | `dev/docs/` (this file) |
| `docs/20260424-phase_e_final_synthesis.md` | `dev/docs/` (Phase E is dev process, not quant finding) |
| `docs/20260421-promotion_flow.md` | `dev/docs/` |
| `docs/20260421-prd_framework_completion.md` | `dev/docs/` |
| `docs/20260420-ralph_loop_prompt.md` | `dev/docs/` |
| `docs/20260421-llm_proposal_prompt_template.md` | `dev/docs/` |
| `docs/20260421-llm_proposal_seed_context.md` | `dev/docs/` |
| `docs/20260421-llm_funnel_checklist.md` | `dev/docs/` |
| `docs/20260421-llm_external_llm_handoff.md` | `dev/docs/` |
| `docs/20260422-claude_md_phase_bc_history.md` | `dev/docs/` |
| `docs/llm_handoff_seed_*` | `dev/docs/` |

Quant-research docs that STAY in `docs/`:
- All `docs/*deep_mining*`, `docs/*research_composite_miner*`,
  `docs/*feat_v1*`, `docs/*feature_data_tier*`, `docs/*universe_*`,
  `docs/*xgboost*`, `docs/*transformer*`, `docs/*factor_promote*`,
  `docs/*rcm_v1_*`, `docs/*paper_artifact_schema*`,
  `docs/20260420-ralph_loop_log.md`, `docs/20260420-prd_intraday_mining_loop.md`,
  `docs/20260420-prd_llm_factor_mining.md`

Risk: MEDIUM because:
- ~200 cross-references inside `ralph_loop_log.md` (stays in docs/)
  point at dev/quant docs mixed
- Git history preservation via `git mv` is fine
- Must update each launcher shell's `PRD_PATH=docs/...` to new path

Recommendation: Execute X-2 only AFTER X-0 + X-1 prove no regressions.

### 3.4 What NOT to migrate (even after X-0/X-1/X-2)

- **Existing `data/ml/*`** (57 files) — active research inventory.
  A reorg would break CLI scripts that write there. Apply §2.1 bundle
  rule only to NEW candidates post-Phase E.

- **RCMv1 memo currently at `docs/20260424-rcm_v1_s1_candidate_memo.md`**
  — this is a quant artifact, stays in `docs/`. Registry correctly
  records `decision_memo_path` pointing at it. Future memos go under
  `data/research_candidates/<id>/` per §2.1.

- **`reports/*`** (quant run output) — already separated from dev
  process; no change needed.

- **`tests/*`** — test code sits next to the code it tests, standard
  Python layout. No split.

- **Existing `scripts/*.py`** that run quant ops — stay. ~50 files.

## 4. Recommendation

### 4.1 Rules

Adopt §2.1-§2.5 rules as **going-forward only**. Every new artifact
must classify cleanly as quant-substance or dev-process at creation
time. The hard split in §2.3 becomes the default layout.

### 4.2 Execution

- **Execute X-0 + X-1 now** (6 shells + 7 Python dev tools → `dev/`):
  low-risk, immediate visibility win. ~1 round.
- **X-2 (docs split) only after X-0/X-1 ship cleanly**: medium-risk,
  needs ralph_loop_log.md ref-update sweep. Consider as a second round.
- **X-3 (candidate bundling, retroactive)**: defer until a NEW
  candidate is produced that exercises the bundle convention. RCMv1
  stays split across current paths.

Total cost: ~2 rounds of ralph-loop or manual migration.

## 5. Non-goals

- Not renaming `data/` subdirectories (too many consumers)
- Not removing `docs/20260424-*.md` prefixes (date-prefix convention
  works; existing files stay)
- Not introducing a heavy doc-generation system
- Not changing candidate-ID format (current `<source>_v<N>_<trait>_<NN>`
  works)

## 6. One-sentence summary

**Hard split: quant substance (`core/`, `scripts/` quant-ops,
`config/`, `data/`, `reports/`, quant `docs/`) vs dev process
(`dev/docs/`, `dev/scripts/` orchestration, `dev/artifacts/`) — with
forward-only rules for new artifacts and a staged migration of
~15 files (shells + Python dev tools) plus a deferred docs split.**
