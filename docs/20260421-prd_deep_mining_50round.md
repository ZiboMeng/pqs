# PRD — Deep Mining Phase (50-Round Comprehensive Loop)

**Status**: Draft v1.0 — 2026-04-21
**Prerequisite**: PRD `prd_framework_completion.md` M0-M10, M13, M15, M16 all DONE.
  pytest baseline 1209 passed + 1 skipped (no torch-missing-path), git clean.
**Supersedes**: `prd_universe_expanded_mining.md` (32 轮, pre-framework —
  this is the post-framework continuation at much larger scope)
**Supersedes**: `prd_llm_factor_mining.md`'s 30-round phase
**Owner**: single-maintainer project
**Scope**: 50 rounds, multi-track mining covering **daily + intraday +
  ML + rule-based + DSL + transformer hyperparameter + XGBoost rigor +
  LLM factor proposal (Claude + Gemini/Codex via M15 handoff)**

---

## 0. Context (post-framework)

### 0.1 Framework delivered (2026-04-21, commits `bb90eb6` → `4708481`)

All critical path milestones + follow-ups shipped:
- **M1 single source of truth** (`config/production_strategy.yaml`)
- **M2 acceptance pack v2** (fresh-backtest gate)
- **M3/M13 alignment check** (WARN → FAIL config-driven)
- **M4/M10 cross-ticker DSL** (enabled + wired into production paths)
- **M5 multi-TF execution contract** (runtime enforced)
- **M6 LLM proposal Phase 1** (Claude-in-loop)
- **M7 XGBoost weight research** (research-only tool)
- **M8/M16 transformer Phase 1 findings** (daily scope negative; pivot
  candidates documented)
- **M15 multi-LLM handoff** (Gemini/Codex via `dump_llm_handoff_context.py`)

Current production state: `status: conservative_default` (honest — no
post-fix validated best exists). Framework CAN accept a validated
promote when pack v2 passes; we need mining to generate one.

### 0.2 Open framework items deferred

- **M11** paper-BT consistency gate in pack v3 (P1.5, 1-2d)
- **M12** concentration gate real enforcement (P2, 0.5d)
- **M14** BacktestEngine NaN root-cause fix (conditional blocker)
- **M17** Realtime intraday live-feed (independent PRD)
- **M18** Cross-ticker DSL function expansion (demand-driven)
- **M19** (new, from R1 finding 2026-04-22) MiningEvaluator does NOT invoke
  cross-ticker DSL; production backtest applies DSL to weight matrix but
  mining evaluator searches pure factor space. Options: (a) integrate
  DSL into MiningEvaluator, (b) document intentional DSL-as-post-layer.
  Decision deferred to R49 synthesis. P1.5.

**Rule**: if any of M11/M12/M14 emerges as an actual blocker during this
mining phase, pause mining loop and fix that first. Otherwise defer.

### 0.3 Universe expansion decision (user-approved 2026-04-21)

Mining pool is NOT limited to the current 53-symbol execution universe.
Expanded pool for mining: **S&P 500 constituents (≈500 syms)** with
filter-down to execution universe via admission pipeline (M4 rules +
`universe_admission_screen.py` + `universe_bucket_assign.py`).

---

## 1. Goals

### 1.1 Hard goals (must hit)

1. **≥1 spec_id passes pack v2 all 10 gates** AND gets promoted to
   `config/production_strategy.yaml::status: active`. This is the
   primary deliverable: produce a post-fix validated best.
2. **Expanded universe pool in place**: S&P 500 daily data downloaded +
   admission-filtered to a 100-150 symbol expanded execution universe.
3. **Mining covers all 4 strategy types + 3 rule DSL types + ML
   approaches**: daily, intraday, XGBoost, transformer, LLM proposals,
   cross-ticker rules.
4. **Per-round ralph-loop commit + baseline snapshot + Chinese 11-part
   report** to `docs/20260420-ralph_loop_log.md`.

### 1.2 Outcome goals (expected, not gated)

- New RESEARCH_FACTORS (2-5) promoted from LLM candidates
- Cross-ticker DSL rule set grows from 3 → 8-12 concrete rules
- Transformer Phase 2 decision (kill / intraday pivot / long-horizon
  pivot) documented with findings
- XGBoost weight model ready for optional production pilot
- Master report includes regime-stratified comparison for current
  production vs experimental candidates

### 1.3 Explicit non-goals

- **NOT** resuming Phase 2 LLM API automation (M15 reframed is enough)
- **NOT** building realtime intraday feed (M17 out of scope)
- **NOT** adding new strategy types (multi_factor / dual_momentum /
  trend_following / cross_asset_rotation is the set)
- **NOT** changing PRODUCTION_FACTORS composition without user auth
  (promotion path is M2; factor promotion (add to registry) is separate
  user-auth gate)
- **NOT** touching intraday live-feed infra (M17)
- **NOT** changing benchmark (SPY + QQQ remain)

---

## 2. Topic Menu (50 rounds)

Each round picks ONE topic. Topics are designed to parallelize where
possible (A/C can proceed while D is running data downloads).

### Track A — Daily Factor Mining + ML (15 rounds)

| R# | Topic | Deliverable |
|---|---|---|
| R1-R2 | Baseline re-mining on current universe (post-M10 DSL active) | Establish post-framework baseline; archive with lineage `post-2026-04-22-deep-R<N>` |
| R3-R4 | XGBoost 5-fold time-series CV for factor importance | SHAP values + permutation IC per fold |
| R5 | XGBoost factor interaction discovery (pair mine) | Top 20 interaction terms, novelty vs existing |
| R6 | XGBoost weight model on current universe | per-(date, symbol) score → weight + vs equal-weight comparison |
| R7-R9 | LLM factor proposals via **Claude** (Phase 1) | 3 rounds × 3-5 candidates = 10-15 new YAMLs through funnel |
| R10-R11 | LLM factor proposals via **Gemini/Codex** (M15 handoff) | Dump handoff context, user drops in external YAMLs, Claude funnels |
| R12-R13 | Multi-horizon composite factors (5d+21d+63d blended) | 2-4 new composite candidates |
| R14 | Cross-sectional rank-change factors | 2-3 candidates with incremental IC check |
| R15 | Factor ensemble backtest (all promoted + candidates) | Pick best composite weights, run pack v2 |

### Track B — Intraday Mining (10 rounds)

| R# | Topic | Deliverable |
|---|---|---|
| R16 | Intraday bar-by-bar baseline (60m universe replay) | 6-month window equity + NAV curve |
| R17 | Realized vol + intraday autocorr research | Stable IC check across regimes |
| R18 | Multi-TF timing with new thresholds | `config/risk.yaml::intraday_timing` sweep |
| R19 | 15m/5m timing layer experiments | Holding-path + entry bps sensitivity |
| R20 | Overnight gap + first-last bar factors | Promote 1-2 to RESEARCH if pass |
| R21 | Intraday cost sensitivity (1x / 2x / 3x) | Should promote only if 2x cost survives |
| R22-R23 | Intraday composite strategy via ensemble | Blend of daily MFS + intraday timing |
| R24 | DSL with intraday confirmation rules | 2-3 new `multi_tf_confirmation` rules in yaml |
| R25 | Intraday stress test (crisis periods: Aug 2020 / Feb 2020) | Robustness report |

### Track C — Rule-Based DSL Exploration (8 rounds)

| R# | Topic | Deliverable |
|---|---|---|
| R26 | Benchmark-trigger rule sweep (SPY/QQQ/XLK drivers) | Compare 4-6 variants |
| R27 | Regime-basket optimization (defensive basket membership + weights) | Gridsearch on RISK_OFF basket |
| R28 | Multi-TF confirmation with sector ETFs (XL* family) | 3 new confirmation rules |
| R29 | DSL-enabled vs disabled A/B in backtest | CAGR / MaxDD / QQQ excess comparison |
| R30 | New DSL functions (M18 demand-driven): `ratio(A,B)`, `zscore`, `rank_cs` | 2-3 new funcs + unit tests + 1 rule using each |
| R31 | Cross-ticker rule priority + conflict resolution research | Ordering stress test |
| R32 | Per-regime rule on/off masking | regime_scope richer semantics |
| R33 | DSL rule meta-tuning (enabled per regime vs global) | Findings doc |

### Track D — Universe Expansion (8 rounds)

**Pre-existing state (discovered 2026-04-21)**: `data/daily/` already
contains **25,340 parquets** (basically full US market from prior polygon
batch ingest). Of current S&P 500 constituents: **511/513 accessible**
via MarketDataStore (BF-B + BRK-B added via yfinance this session; MBIA
+ SCANA are delisted). Freshness: most non-universe symbols at 2026-04-18
(3 days behind current universe). R34 is therefore a LIGHT sync, not a
full download.

| R# | Topic | Deliverable |
|---|---|---|
| R34 | S&P 500 incremental freshness sync via `scripts/fetch_sp500_pool.py` (5-10 min; picks up missing bars post-2026-04-18) | `data/sp500_tickers_latest.txt` + all 511 sync'd to today |
| R35 | Universe alpha/beta audit on S&P 500 pool | `universe_alpha_diagnostic.py --symbols data/sp500_tickers_latest.txt` — categorize |
| R36 | Admission screening on pool (v2.2 Layer 1 objective criteria) | `universe_admission_screen.py` produces CORE/EXTENDED list |
| R37 | Risk labels + bucket assignment | `universe_risk_labels.py` + `universe_bucket_assign.py` |
| R38 | User review + manual curation down to expanded 100-150 syms | User checkpoint; commit `config/universe.yaml` update |
| R39-R40 | Re-mining on expanded universe (multi_factor + dual_momentum) | Lineage `post-2026-04-22-deep-R39-expanded`; fresh best candidates |
| R41 | Validation: verify QQQ gate still passable with wider universe | Don't降标准; if not passing, archive and re-evaluate |

### Track E — XGBoost Rigor (5 rounds)

| R# | Topic | Deliverable |
|---|---|---|
| R42 | XGBoost CV with TimeSeriesSplit (5-fold) | Per-fold OOS R²; stability report |
| R43 | SHAP attribution production-ready | `data/ml/xgb_shap_<tag>/` full artifact per fold |
| R44 | XGBoost as production WEIGHT model (research-to-prod pilot) | `run_xgb_weight_model.py` → archive (not yet config-active; evaluate vs MFS on fresh backtest) |
| R45 | Ensemble: MFS + XGBoost weight blend (50/50, 30/70, 70/30) | Compare vs pure MFS |
| R46 | Final XGBoost evaluation decision: promote or park | Findings doc + recommendation to user |

### Track F — Transformer Hyperparameter (2 rounds)

| R# | Topic | Deliverable |
|---|---|---|
| R47 | Transformer seq_len sweep (21 / 63 / 126 / 252) + epochs (5/10/20) + d_model (32/64/128) | Phase 2 findings: does any config beat Ridge? |
| R48 | Intraday sequence transformer pivot experiment (60m bars, shorter seq) | Phase 3 pivot decision |

### Track G — Final Synthesis + Promote Attempt (2 rounds)

| R# | Topic | Deliverable |
|---|---|---|
| R49 | Comprehensive acceptance pack run on ALL lineage top specs | Pack v2 verdicts table |
| R50 | Select best spec → promote (if passes) + master report | `config/production_strategy.yaml` updated OR honest "no validated best yet" conclusion with next-phase plan |

---

## 3. Per-round Protocol

Each round must:

1. **Pre-flight**
   - `python scripts/build_research_baseline_snapshot.py` (record state)
   - Git clean check
   - `python scripts/fetch_data.py --daily-only` (if last update > 2 days ago)

2. **Execute topic per above menu**
   - Lineage tag pattern: `post-2026-04-22-deep-R<NN>` (zero-padded)
   - Archive writes automatic

3. **Acceptance pack** (only if a promote candidate emerges)
   - `python scripts/acceptance_pack.py --spec-id <id> --verbose`
   - If all 10 gates pass → user notification + `--dry-run` of promote
   - User must authorize before actual promote write

4. **Per-round 11-part Chinese report** to `docs/20260420-ralph_loop_log.md`:
   1. 本轮主题 (track + topic)
   2. 本轮目标
   3. 为什么优先
   4. 做了什么
   5. 修改了哪些文件
   6. 跑了哪些测试/实验
   7. 结果如何
   8. 新问题/新机会
   9. 剩余风险
   10. 下一轮建议
   11. Commit 哈希

5. **Commit**: one round = one commit (or small commit chain if multi-file)

6. **Notification** (optional): `python scripts/send_round_summary.py`
   via wecom_bot if `PQS_WECOM_WEBHOOK_URL` set

---

## 4. Hard Invariants

Taken from `CLAUDE.md` and framework PRDs — **non-negotiable**:

1. **R17 "不降标准"**: if a gate threshold feels too strict, the answer
   is to improve the strategy, not lower the gate
2. **QQQ rule** (CLAUDE.md §Phase C): full period + holdout + OOS avg
   must all beat QQQ
3. **MaxDD hard floor**: -25% absolute, 1.5× SPY relative
4. **Long-only + no-margin**: (cross-ticker DSL long-only invariant)
5. **M1 single source**: production_strategy.yaml is THE truth
6. **M3 alignment**: any hash drift triggers WARN (or FAIL per yaml)
7. **Pack v2 required**: no promote without passing all 10 gates
   (including the v2 `full_period_fresh_backtest`)
8. **No auto-promote**: `promote_strategy.py --promote` is manual user
   action after reviewing diff
9. **Intraday terminology**: `cached-runtime` vs `realtime live-feed`
   (this PRD uses only cached-runtime; realtime is M17)
10. **LLM role**: LLM proposes; user + funnel decides; verdict=KEEP
    never exists

---

## 5. Stop Conditions

Pause loop if any of:

1. **Pytest regression**: full suite collected drops > 5 or passed rate
   drops below 99%
2. **Framework invariant broken**: M1/M2/M3 contracts violated by any
   round's changes
3. **Universe config changed without user auth**: R38 is the only
   authorized universe-touching round
4. **PRODUCTION_FACTORS set modified**: only user auth can add factors
   to `core/factors/factor_registry.py::PRODUCTION_FACTORS`
5. **Archive DB corrupted** or > 10GB (currently 276 trials; growing to
   ~1000 trials in 50 rounds is fine)
6. **Disk space < 10GB** on data volume
7. **Pack v2 fresh-backtest consistently NaN**: means M14 is a real
   blocker now; pause and fix root cause before continuing
8. **User explicit stop**

---

## 6. Success Scenarios

### A. Best case (optimistic)

- 1-3 specs pass pack v2 all 10 gates
- ≥1 promoted to `status: active`
- 2-5 new RESEARCH_FACTORS from LLM/XGBoost/DSL rounds
- Cross-ticker DSL ruleset expanded 3 → 8-10
- Transformer Phase 2 pivoted or formally parked with documentation
- XGBoost weight model has clear promote / park recommendation
- Master report shows meaningful improvement vs conservative_default

### B. Realistic case (most likely)

- 0-1 specs pass pack v2 but 3-5 get VERY CLOSE (9/10 gates)
- Master report documents "best so far" with gap-to-target
- New RESEARCH_FACTORS promoted to registry (user-auth separate)
- Honest blocker report for any remaining gap (factor space / universe
  / data frequency)
- DSL + XGBoost + transformer all produce negative / neutral findings
  that are DOCUMENTED rather than swept under

### C. Pessimistic case (still valuable)

- 0 promotes possible
- Thorough evidence accumulated that current universe + factor space
  does not support a post-fix validated best
- Blocker report points at specific 2-3 next-phase directions (more
  data frequency / different asset class / longer lookback / etc.)
- Framework tooling stays clean + tested

---

## 7. Deliverables

Per-round:
- Commit with lineage-tagged archive entries
- 11-part Chinese report in `docs/20260420-ralph_loop_log.md`
- Any new YAMLs / configs / scripts

Phase-final (after R50):
- `docs/deep_mining_phase_final_report.md` — comprehensive summary
- Updated `config/production_strategy.yaml` (active or
  conservative_default with documented reasoning)
- `docs/20260420-ralph_loop_log.md` updated through R50
- Master report generated with final state
- Updated `config/universe.yaml` (if R38 gave expanded set)

---

## 8. Launch Mechanics

Ralph-loop invocation:

```bash
# Print launch command (updates after any change to pre-flight)
bash scripts/start_universe_mining_loop.sh   # existing (will be updated for 50 rounds)
```

A new launcher script will be written for this phase:

```bash
# Planned: scripts/start_deep_mining_loop.sh (to be created before R1)
```

Launch format (single-line ASCII per CLAUDE.md rule):

```
/ralph-loop:ralph-loop "Execute one round per docs/20260421-prd_deep_mining_50round.md section 2 track menu. lineage_tag=post-2026-04-22-deep-R<NN>. Write 11-part Chinese report per round. Halt on section 5 stop conditions. Do NOT modify PRODUCTION_FACTORS or config/universe.yaml outside R38 without explicit user auth." --max-iterations 50 --completion-promise DEEPDONE
```

Completion promise: `DEEPDONE` (output only when genuinely complete or
stop condition hit).

---

## 9. Risk Register

| Risk | Mitigation |
|---|---|
| 50 rounds is too long / budget overruns | `--max-iterations 50` caps; stop conditions watch progress |
| Data download (S&P 500) hits yfinance rate limits | R34 uses batched download with backoff |
| Universe expansion breaks existing MFS calibration | Pack v2 fresh-backtest guards; if fail, revert universe change (R38 rollback path) |
| Transformer experiments overfit on GPU | 30-min training cap per run; OOS temporal split strict |
| LLM candidates flood funnel | Funnel rate-limits by design; each candidate is ~30s processing |
| Archive DB lock contention | Mining uses single-process Optuna (no parallel conflict) |
| Cross-ticker DSL changes break run_backtest | M10 wrapper has NO-OP path; integration tests guard |
| K-like delisted tickers in expanded pool | R34 download catches 404s; auto-skip + log, don't crash |
| `--from-date` / date window drift between rounds | Baseline snapshot locks state per round |

---

## 10. Relationship to Prior PRDs

- **Supersedes**: `prd_universe_expanded_mining.md` (32-round pre-framework
  phase; was paused at R35). This PRD covers more topics + more rounds
  + all post-framework tooling.
- **Supersedes at factor level**: `prd_llm_factor_mining.md`
- **Depends on**: `prd_framework_completion.md` v1.2 (M0-M16 delivered)
- **Defers to**: `prd_live_feed.md` (future, when realtime needed)

---

## 11. Autonomous Decision Rules (user pre-authorized 2026-04-22)

User cannot respond during loop ("已经休息了"). All 7 decision points are
pre-resolved per the rules below. Loop MUST follow these exactly. If an
edge case falls outside these rules, **park with doc** rather than ask.

### 11.1 Promote a spec_id (any round)

**Rule**: Auto-promote via `scripts/promote_strategy.py --promote` IFF
all of:
  - pack v2 ALL 10 gates PASS (including `full_period_fresh_backtest`)
  - OOS IR ≥ **0.25** (safety margin above the 0.20 gate floor)
  - fresh backtest excess vs QQQ ≥ **+2%** (safety margin above 0% gate)
  - max single-symbol weight ≤ 0.35
  - post-promote pytest full suite still passes (if regression → git revert the yaml)

Promote is a SEPARATE commit (reviewable). Write rationale into
`source.rationale` citing OOS IR / excess / gate passes. Continue the
loop after promote; do not pause.

### 11.2 R38 universe.yaml change

**Rule**: DO NOT auto-edit `config/universe.yaml`. R38 produces a
PROPOSAL document `docs/universe_expansion_proposal_R38_<ts>.md` with:
  - Current 52 symbols diff vs admission-screen output
  - Bucket assignment table (Alpha Core / Diversifier / Tactical / ...)
  - Risk labels summary
  - Recommended seed_pool addition list (max 30 new symbols)
  - Explicit disclaimer: "USER MUST REVIEW before executing git add/commit"

R39-R41 use `run_mining.py --extra-symbols <proposal.txt>` to mine with
proposed universe **without** modifying the yaml. This exercises the
expanded universe in archive but leaves production yaml intact until
user approves post-loop.

### 11.3 R7 / R10 / R14 new factor → RESEARCH_FACTORS

**Rule**: Auto-add to `core/factors/factor_registry.py::RESEARCH_FACTORS`
IFF:
  - Funnel passes: `llm_factor_propose.py` → NEEDS_HUMAN_REVIEW (never
    REJECT/ARCHIVE)
  - `llm_candidate_deep_check.py` PASS (OOS IR ≥ 0.30, regime 4/6+ correct
    sign, quartile stable)
  - Optional: `llm_candidate_factor_backtest.py` 5-gate (cost/QQQ/MaxDD)
    best-effort (not required for RESEARCH_FACTORS — only for PRODUCTION)
  - Unit test added verifying the factor produces finite non-NaN values
  - `core/factors/factor_generator.py::generate_all_factors` includes it

Also update `RESEARCH_TO_PRODUCTION_MAP` with placeholder entry if the
factor shadows an existing production factor.

### 11.4 R7 / R10 / R14 new factor → PRODUCTION_FACTORS

**Rule**: DO NOT auto-add to `PRODUCTION_FACTORS`. This touches
`MultiFactorStrategy.generate()` inline composite. Instead produce
`docs/production_factor_promote_proposal_<name>_<ts>.md` with:
  - Full funnel evidence (all 5 gates cost/QQQ/holdout/MaxDD/dup)
  - Composite integration test results
  - Post-loop user will review + explicitly authorize (R15 drawup pattern)

### 11.5 R30 new DSL functions

**Rule**: Auto-add `ratio(sym_a, sym_b)`, `zscore(col, N)`, `rank_cs(col)`,
`breakout(N)` to `core/signals/cross_ticker_rules.py` whitelist IFF:
  - Each function has ≥ 2 unit tests (valid behavior + eval-inject rejection)
  - Evaluator `_eval_expression` correctly routes the new funcs
  - Commit regression passes (full pytest)
  - Add 1 example rule using each new func to
    `config/cross_ticker_rules.yaml` (commented, `enabled: false` for that
    rule only via a disabled flag or just not added to live `rules:` block)

Per-function unit test template already in
`tests/unit/signals/test_cross_ticker_rules.py`; follow the pattern.

### 11.6 R46 XGBoost weight model decision

**Rule**: Auto-park as research-only. Write
`docs/20260422-xgboost_weight_model_R46_findings.md` with:
  - Fresh vs Ridge vs equal-weight CAGR / Sharpe / MaxDD comparison
  - Per-fold CV stability (R42 data)
  - SHAP top factors (R43 data)
  - Ensemble blend findings (R45 data)
  - Recommendation: **promote to production-candidate** ONLY if XGB
    CAGR > conservative_default CAGR AND MaxDD ≤ -25% AND OOS IR > 0.30
    (these are HIGH bars and unlikely to be cleared in 50-round research;
    default is "park + document" per historical M7/M8 experience)

### 11.7 R50 final promote / park

**Rule**:
  - If any spec passed 11.1 rules during R1-R49: ensure it's promoted +
    noted in final report
  - If no spec passed: write comprehensive blocker report
    `docs/deep_mining_phase_final_report.md` covering:
    - Lineage-level statistics (all `post-2026-04-22-deep-R*` rounds)
    - Best-of-the-best candidates and why they fell short
    - Factor / universe / data-frequency gap analysis
    - Next-phase recommendation (intraday focus / new data source / etc)
  - Final state summary with:
    - `config/production_strategy.yaml::status`
    - New RESEARCH_FACTORS added (count + names)
    - New DSL rules added (count)
    - Universe proposal for user (R38 doc pointer)
    - Test count + regression status

### 11.8 Stop conditions that REQUIRE loop halt (not auto-resolve)

Even under autonomous mode, the loop MUST halt on:
  - pytest regression > 5 tests (investigate before continuing)
  - Any `core/` module import failure (framework broken)
  - Disk space < 10GB
  - `config/universe.yaml` or `config/production_strategy.yaml` unexpectedly
    modified outside authorized rounds (implies bug or race)
  - Archive DB corruption
  - Third `--force` promote attempt in a single loop (means
    auto-promote logic is broken; investigate before more rounds)

On halt: write `docs/deep_mining_halt_R<N>_<reason>.md` explaining state
+ next-action recommendation, then output completion promise `DEEPDONE`
with status note.

---

*PRD v1.0 — 2026-04-22, author: Claude; post-framework comprehensive
50-round mining plan. Covers daily + intraday + ML + rule-based +
DSL + transformer hyperparameter + XGBoost rigor + LLM handoff.*

*PRD v1.1 — 2026-04-22, author: Claude; §11 rewritten as "Autonomous
Decision Rules" — user pre-authorized all 7 decision points so loop can
run unattended. §11.8 stop-only conditions added.*
