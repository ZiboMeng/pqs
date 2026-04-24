# CLAUDE.md Phase-E History Archive

Detail blocks moved out of `CLAUDE.md` during Phase E-post R8
(2026-04-24) to keep CLAUDE.md under 800 lines and focused on active
execution context. Each section below was the full "Current TODO"
entry in CLAUDE.md at the time of archiving.

For the Phase B / C history see
`docs/20260422-claude_md_phase_bc_history.md`.
For per-round 11-part Chinese reports see
`docs/20260420-ralph_loop_log.md`.

---

## Deep Mining 50-round (2026-04-22 COMPLETE)

See `docs/20260422-deep_mining_50round_final_synthesis.md`. 7 tracks
× 50 rounds autonomous execution finished. 5 user decisions were
pending; some resolved via RCMv1 downstream work.

7 tracks:
- daily+ML (R1-R15)
- intraday (R16-R25)
- DSL (R26-R33)
- universe expansion (R34-R41)
- XGBoost rigor (R42-R46)
- transformer hyperparameter (R47-R48)
- final synthesis (R49-R50)

Hard goal: ≥1 spec passes pack v2 all 10 gates and promotes to
status=active.

**Autonomous Decision Rules** (user pre-authorized 2026-04-22):
- **Auto-promote** when pack v2 ALL 10 gates PASS + OOS IR ≥ 0.25 +
  QQQ excess ≥ +2% + max single weight ≤ 0.35
- **R38 universe**: produce proposal doc only, DO NOT edit yaml
- **R7/R10/R14 factor → RESEARCH_FACTORS**: auto-add if funnel +
  deep_check PASS; **→ PRODUCTION_FACTORS**: proposal doc only
- **R30 DSL funcs**: auto-add `ratio/zscore/rank_cs/breakout` with tests
- **R46 XGB**: auto-park as research-only + findings doc
- **R50 final**: promote if anything passed 11.1; else blocker report
- Halt only on §11.8 stop conditions (pytest regression > 5, core
  import failure, disk < 10GB, unexpected config edits, archive
  corruption, 3rd --force promote in one loop)

---

## RCMv1 20-round (2026-04-24 COMPLETE)

Research Composite Miner v1 + 12 orthogonal features. Key deliverables:

- **R15 leakage fix**: `evaluate_composite(lag=1)` default (was 0).
  Pre-fix shared-close[t] IC values were inflated ~10x.
- **R17 converged spec** `{beta_spy_60d, drawup_from_252d_low,
  days_since_52w_high, amihud_20d}` IC_IR +0.50 (formerly +4.77 pre-fix).
- **R18 acceptance PASS** (4/4 walk-forward folds + 6/6 regimes positive).
- **R20 S1 Research Candidate** promotion memo
  `docs/20260424-rcm_v1_s1_candidate_memo.md` (doc-only; does NOT
  touch production_strategy.yaml).
- See `docs/20260424-rcm_v1_final_synthesis.md`.

---

## Codebase Audit 3-Round v1 (2026-04-24 COMPLETE)

PRD `docs/20260424-prd_codebase_audit_3round.md`, lineage
`audit-2026-04-24`. Deliverables:

- R1 core library (27 modules, 0 functional bugs)
- R2 scripts/IO (57 scripts + 13 modules, 0 functional bugs)
- R3 tests + README sync + baseline rebuild

---

## Codebase Audit 3-Round v2 (2026-04-24 COMPLETE)

Same PRD, lineage `audit-2026-04-24-v2`, covers Phase E governance
layer (`core/research/`) + X-1 path migration (`dev/scripts/**/*.py`).

- R1: found/fixed 19 unused imports in core (no functional bugs)
- R2: found/fixed 3 real `--help` bugs in scripts
  (`feat_v1_topk_analysis.py` missing sys.path;
  `build_splits_parquet.py` / `run_multi_tf_backtest.py` missing
  argparse) and cleaned 44 unused imports
- R3: refreshed baseline 1386→1536 tests and synced README

See `docs/20260420-ralph_loop_log.md` §R-audit-v2-round-01/02/03.
Launch: `bash dev/scripts/loop/start_codebase_audit_loop.sh`.

---

## Phase E Research Governance + Paper Layer (2026-04-24 COMPLETE)

14-round ralph-loop ship. Execution PRD
`docs/20260424-prd_phase_e_execution.md` + charter
`docs/20260424-prd_phase_e_governance_and_paper.md` + final synthesis
`docs/20260424-phase_e_final_synthesis.md`. Deliverables:

- **E-0 foundation**: `core/research/candidate_registry.py` (S0/S1/S2/S5
  state machine in `data/research_candidates/registry.db`) +
  pyarrow.parquet decouple from paper layer +
  `scripts/revoke_candidate.py`
- **E-1 promote**: `core/research/frozen_spec.py` (8 mandatory fields) +
  `scripts/freeze_research_candidate.py` + `scripts/research_promote.py`
  (S0→S1 gate; hard invariant: never writes
  `config/production_strategy.yaml`) +
  `core/research/acceptance_helpers.py`
- **E-2 paper**: `scripts/run_paper_candidate.py` (reads frozen spec,
  not production config) + `core/research/paper_artifacts.py` +
  `scripts/paper_drift_report.py` (50 bps informational threshold) +
  `scripts/paper_enter.py` (S1→S2; S3 → NotImplementedError)
- RCMv1 `rcm_v1_defensive_composite_01` traversed S0→S1→S2 via new
  tooling. Registry holds at S2_paper_candidate.

Launch: `bash dev/scripts/loop/start_phase_e_loop.sh`.

---

## Phase E-post + Candidate-2 8-round (2026-04-24 COMPLETE)

PRD `docs/20260424-prd_phase_e_post_cand2.md`, lineage
`phase-e-post-2026-04-24`, completion promise `EPOST_CAND2_DONE`.

Deliverables per round:

| Round | Scope | Commit | Artifact |
|-------|-------|--------|----------|
| R1 | E-post-3 deps | `f395a24` | +scipy/requests/tqdm/pyzipper; README 5.1 canonical |
| R2 | E-post-5A migration hermetic | `9a59631` | `--archive-db` CLI + 4 hermetic tests |
| R3 | E-post-4 revoke drill (clone) | `2efddf2` | 3 revoke paths drilled on rcm_v1 clones; real rcm_v1 bit-stable |
| R4 | E-post-1 paper decouple | `50a48b9` | `core/data/factory.py` PriceStore Protocol + factory; 6 tests |
| R5 | E-post-2 research mask unify | `d40e1e7` | `config/research_mask.yaml` + 9 script migrations; 10 tests incl. real-universe bit-identical |
| R6 | Candidate-2 S0→S1→S2 | `cbd5f50` | `candidate_2_orthogonal_01` {ret_5d, rs_vs_spy_126d, hl_range}, equal weight, registry @ S2_paper_candidate |
| R7 | Exhaustive audit | `29127c6` | 0 real bugs; 3 unused imports cleaned |
| R8 | Docs sync + final synthesis | (this round) | README v1.4 + CLAUDE.md slim + final_synthesis doc + EPOST_CAND2_DONE |

Final synthesis doc: `docs/20260424-phase_e_post_cand2_final_synthesis.md`.

Test baseline progression: audit-v2 R3 (1536) → R1 (1536) → R2 (1540)
→ R3 (1540) → R4 (1546) → R5 (1556) → R6 (1556) → R7 (1556) → R8 (1556).

Registry state after R8: 2 S2_paper_candidate rows
(`rcm_v1_defensive_composite_01` unchanged since Phase E R11;
`candidate_2_orthogonal_01` new @ R6).

---

## Framework Completion PRD — full milestone table (archived 2026-04-24)

PRD `docs/20260421-prd_framework_completion.md` v1.2.
Only **open** milestones (M11, M12, M14, M17, M18) remain in CLAUDE.md.
Full table (shipped + open) reprinted below for audit.

### Shipped (M0-M8, M10, M13, M15, M16)

- [x] **M0** research baseline snapshot
  (`dev/scripts/baseline/build_research_baseline_snapshot.py`)
- [x] **M1** `config/production_strategy.yaml` single source of truth
  (21 unit + 7 integration tests)
- [x] **M2** promote CLI + acceptance pack v2 (18 unit tests;
  `scripts/acceptance_pack.py` + `scripts/promote_strategy.py` +
  `docs/20260421-promotion_flow.md`). v2 added
  `full_period_fresh_backtest` gate after first promote attempt
  caught quick-eval-vs-full-period CAGR gap (`6d15b735a64c` was
  rolled back; pack now re-runs fresh backtest by default)
- [x] **M3** runtime alignment check WARN mode (12 unit tests;
  `core/alignment/alignment_check.py`; integrated in `run_backtest.py`
  + `run_paper.py`)
- [x] **M4** cross-ticker YAML DSL (24 unit tests;
  `core/signals/cross_ticker_rules.py` + `config/cross_ticker_rules.yaml`;
  3 rule types; safe expression eval, no Python `eval`)
- [x] **M5** multi-TF execution contract runtime assert (4 integration
  tests; `IntradayBacktestEngine.run_multi_day` clips + WARN on negative
  timing_provider weights)
- [x] **M6** LLM proposal Phase 1 (3 markdown docs:
  `docs/20260421-llm_proposal_prompt_template.md`,
  `docs/20260421-llm_proposal_seed_context.md`,
  `docs/20260421-llm_funnel_checklist.md`; process formalization, no
  code change)
- [x] **M7** XGBoost weight research model
  (`scripts/run_xgb_weight_model.py`; research-only; not wired to
  production)
- [x] **M8** Transformer research Phase 1 **findings shipped** —
  `docs/20260421-transformer_research_phase1_findings.md`. OOS R²:
  Ridge +0.012 / XGBoost -0.110 / **Transformer -0.207** (most
  overfit). Honest negative finding: daily 21d forecasting scope
  unsuitable for transformer; recommend parking or pivot to intraday /
  cross-sectional / longer-horizon setup.
- [x] **M10** cross-ticker DSL production wiring
  (`core/signals/cross_ticker_wrapper.py` + `run_backtest.py` /
  `run_paper.py` integration; 9 unit tests; `--no-cross-ticker-rules`
  CLI flag to disable per-run)
- [x] **M13** alignment FAIL mode config-driven rollout
  (`config/system.yaml::alignment::{mode, live_only_fail}`; defaults
  WARN + live_only_fail=true; operator flip without code change)
- [x] **M15** LLM Proposal multi-LLM context pack (see
  `docs/20260421-llm_external_llm_handoff.md`). Reframed from
  "Anthropic API call" to "provide context doc that user feeds to
  Gemini/Codex; those LLMs produce YAML candidates; user manually
  places in `research/llm_candidates/round_NN/`; Claude funnel picks
  up." Fully automated Phase 2 (API) is NOT planned.
- [x] **M16** Transformer Phase 1 findings (done, see M8 above)

### Open (M11, M12, M14, M17, M18) — reprinted for reference

- [ ] **M11** paper-BT consistency gate in pack v3 (P1.5, 1-2d). New
  gate: replay spec over recent 126d window, diff equity vs fresh
  backtest, fail if > 10 bps drift. Currently skip-PASS; M1
  single-source already covers constructor layer but engine-level
  drift not verified.
- [ ] **M12** concentration gate real enforcement (P2, 0.5d). Currently
  skip-PASS; runtime `soft_cap_max_single` + `PortfolioConstructor`
  hard cap cover production. M12 would inspect fresh-backtest weight
  matrix for per-date top-1/top-3 concentration and reject if >
  threshold (e.g. top-1 > 0.40 or top-3 > 0.70).
- [ ] **M14** BacktestEngine NaN root-cause fix (P2, 1d; conditional).
  Ghost-cleanup + NaN last-price can produce NaN as equity last bar.
  Pack v2 workaround uses `.dropna()` before CAGR. Fix: skip
  ghost-liquidation when last_close is NaN, or fillna last-valid in
  equity aggregation. Promote to blocker if user complains about NaN
  in `reports/backtests/.../equity_curve.csv`.
- [ ] **M17** Realtime intraday live-feed infra. Out of framework PRD
  scope; independent PRD `prd_live_feed.md` when needed. Gate: do not
  start until validated best strategy exists and is stable (no point
  live-tracking a provisional strategy).
- [ ] **M18** Cross-ticker DSL function expansion (P3, 0.3d per
  function). Candidate new funcs: `ratio(sym_a, sym_b)`,
  `zscore(col, N)`, `rank_cs(col)`, `breakout(N)`. Add ONLY when a
  specific rule yaml demands them; don't pre-add.
