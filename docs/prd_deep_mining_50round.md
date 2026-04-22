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
   report** to `docs/ralph_loop_log.md`.

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

| R# | Topic | Deliverable |
|---|---|---|
| R34 | S&P 500 constituent list + yfinance daily download (~500 syms) | `data/daily/sp500_<ts>.parquet` bulk; catalog per-symbol freshness |
| R35 | Universe alpha/beta audit on S&P 500 pool | `universe_alpha_diagnostic.py --symbols sp500.txt` — categorize |
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

4. **Per-round 11-part Chinese report** to `docs/ralph_loop_log.md`:
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
- 11-part Chinese report in `docs/ralph_loop_log.md`
- Any new YAMLs / configs / scripts

Phase-final (after R50):
- `docs/deep_mining_phase_final_report.md` — comprehensive summary
- Updated `config/production_strategy.yaml` (active or
  conservative_default with documented reasoning)
- `docs/ralph_loop_log.md` updated through R50
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
/ralph-loop:ralph-loop "Execute one round per docs/prd_deep_mining_50round.md section 2 track menu. lineage_tag=post-2026-04-22-deep-R<NN>. Write 11-part Chinese report per round. Halt on section 5 stop conditions. Do NOT modify PRODUCTION_FACTORS or config/universe.yaml outside R38 without explicit user auth." --max-iterations 50 --completion-promise DEEPDONE
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

## 11. Decision Points for User

These are explicitly flagged for USER approval during the loop (not
automatic):

| Round | Decision |
|---|---|
| After any round | Promote a specific spec_id to production (must see acceptance pack output + dry-run diff first) |
| R38 | Approve universe.yaml change (expanded seed_pool from admission screen) |
| R7 / R10 / R14 | Approve any new factor to `RESEARCH_FACTORS` (after funnel pass) |
| R7 / R10 / R14 (rare) | Approve any new factor to `PRODUCTION_FACTORS` (after second funnel pass + composite integration) |
| R30 | Approve new DSL functions (`ratio`, `zscore`, `rank_cs`) addition to whitelist |
| R46 | Approve XGBoost weight model promote / park |
| R50 | Final promote or park decision |

---

*PRD v1.0 — 2026-04-22, author: Claude; post-framework comprehensive
50-round mining plan. Covers daily + intraday + ML + rule-based +
DSL + transformer hyperparameter + XGBoost rigor + LLM handoff.*
