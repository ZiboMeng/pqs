<!-- PQS module CONTEXT.md — 由 CLAUDE.md 2026-05-19 reorg 拆出。
CLAUDE.md = context 入口,仅留项目级(不变量/纪律/架构/概括)。
本文件 = 本模块的历史/契约细节(content-preserving 搬迁,无删改)。
回指: ../../CLAUDE.md ; 索引见 CLAUDE.md 末「Module CONTEXT.md 索引」。 -->

# core/mining/CONTEXT.md — module history / contract detail


## [研究/挖矿/Phase 完成史 + Track C cycle #01-#09 + PRD-E/Bucket/Post-cycle10/SPY-bug/PEAD/P0-gov/ML-redo (原 CLAUDE.md Current TODO Checklist 上半)]

### Current TODO Checklist

**Completed phases** (one-line summaries; full tables moved to
`docs/20260424-claude_md_phase_e_history.md` on 2026-04-24):

- **Deep Mining 50-round** (2026-04-22 ✅) — 7 tracks × 50 rounds;
  synthesis `docs/20260422-deep_mining_50round_final_synthesis.md`
- **RCMv1 20-round** (2026-04-24 ✅) — R17 converged spec + R18
  acceptance PASS + R20 S1 candidate memo;
  `docs/20260424-rcm_v1_final_synthesis.md`
- **Codebase Audit v1** (2026-04-24 ✅) — 3 rounds, 0 functional bugs
- **Codebase Audit v2** (2026-04-24 ✅) — 3 rounds, 3 `--help` bugs +
  63 unused imports fixed; baseline 1386→1536 tests
- **Phase E Governance + Paper Layer** (2026-04-24 ✅) — 14 rounds;
  `candidate_registry` + `frozen_spec` + paper CLI pipeline;
  RCMv1 @ S2_paper_candidate; `docs/20260424-phase_e_final_synthesis.md`
- **Phase E-post + Candidate-2** (2026-04-24 ✅) — 8 rounds; 5 E-post
  gaps + Candidate-2 `{ret_5d, rs_vs_spy_126d, hl_range}` equal-weight
  @ S2_paper_candidate; `docs/20260424-phase_e_post_cand2_final_synthesis.md`
- **Data-integrity round-3** (2026-04-25 ✅) — 6 steps. Single
  canonical source = polygon 1m → daily, label = real ET trading
  day, two-tier N_min (350/300), incomplete-day quarantine policy,
  splits.parquet TJX+GOOGL fixes. `data/daily/*.parquet` rebuilt
  for 78 syms (BRK-B drop). 4 paper cells re-run drift = 0 bps but
  NAVs −5 to −71 pp vs pre-step3b (largest: 2022 Cand-2 +74.57% →
  +3.47% honest). Headline-4 docs refreshed; full caveat sweep done.
  Standing freeze (universe / mining / Candidate-3 / OOS / spec
  changes) remains. `docs/memos/20260425-data_integrity_round3_close.md`

- **OOS Framework MVP R1-R7** (2026-04-25 ✅) — 7-round ralph-loop
  per `docs/prd/20260425-oos_mvp_ralph_loop_execution.md` derived
  from PRD v3 `docs/prd/20260425-oos_validation_framework_codex_v3.md`.
  Lineage `oos-mvp-2026-04-25`. Shipped: `core/research/robustness/`
  (window schema + runner) + `core/research/concentration/` (M12
  warning + extreme tier, report-only) + watch_exposure section in
  master + drift reports + `core/research/forward/` (manifest schema
  ONLY, no runner per PRD v3 §B) + integration smoke + negative
  simulation. R2 numbers (+62.76% / +191.57%) are **pseudo-OOS
  robustness only, NOT deployable OOS** (PRD v3 §1.1+§1.3). Closeout:
  `docs/memos/20260425-oos_mvp_close.md`. OOS-framework workstream
  auto re-frozen at OOSMVPDONE; reopening forward execution
  requires a new PRD round.
- **OOS MVP audit fix — M12 weighted thin gate** (2026-04-25 ✅) —
  per `docs/memos/20260425-m12_review_decision.md`. Replaced the
  pre-fix binary thin-data gate with a weight-day-weighted share
  (Σ share[s] × thin_data_pct[s]) which is the PRD-§C-thresholds gate
  going forward. Old binary share kept as `thin_data_binary_share`
  diagnostic only. **Cand-2 unfrozen** (weighted 5.19% → warning,
  narrative_permission: allowed); **RCMv1 still frozen** (weighted
  14.97% > 10% extreme — real, not implementation artifact). pytest
  1681 → 1685 (+4 audit regression tests A/B/C + percent-scale).

- **Research cycle 2026-04-26 #01** (2026-04-26 ✅, **0 nominee**) —
  partial unfreeze authorized in
  `docs/memos/20260426-research_layer_partial_unfreeze.md`. Pre-
  registered immutable criteria yaml at
  `data/research_candidates/research-cycle-2026-04-26-01_promotion_criteria.yaml`
  (sha256 `5e88d0c…d03ad28` recorded in commit `4100f7b`). 200-trial
  TPE mining on the 78-symbol × 2007-2023 panel produced top trial
  `62445bdc62ae` with composite `beta_spy_60d × amihud_20d × mom_126d`
  (IC_IR=1.04 full-period, 4/4 walk-forward folds positive). FAILED
  G2.A on `watchlist_total_share=39.50% > 30% ceiling` — exactly the
  failure mode the strict ceiling was designed to prevent. Per
  criteria immutability, no retroactive softening: cycle closes
  0-nominee. Closeout memo:
  `docs/memos/20260426-research-cycle-2026-04-26-01_close.md`.
  Research-mining workstream auto re-frozen at this boundary;
  forward-OOS observation of RCMv1 + Cand-2 unaffected.

- **Track C cycle 2026-04-30 #01** (2026-04-30 ✅, **0 nominee**,
  Tier 2 sibling-by-construction-and-factor-overlap) — first
  controlled-mining cycle under post-Track-A alternating-regime
  temporal split + post-A++ pool reachability contract. Pre-
  registered immutable criteria yaml at
  `data/research_candidates/track-c-cycle-2026-04-30-01_promotion_criteria.yaml`.
  TWO mining runs under same lineage:
  (a) **Pre-A++ run** (commit `f770d05`, sha256 `95027106…`): 49
      archived trials with FAMILIES_V1's 33 factors. INVALIDATED
      because search space did not satisfy yaml's
      `factor_registry_pool: RESEARCH_FACTORS` declaration (Cand-2
      anchors `ret_5d`/`hl_range` unreachable; `mom_12_1` unreachable).
      Pre-A++ artifacts preserved at
      `data/ml/research_miner/track-c-cycle-2026-04-30-01.preAplusplus/`.
  (b) **Post-A++ run** (commit `da036da`, sha256
      `edda90b4…d05a`): A++ patch ships FAMILIES_V2 (6 families, 64
      reachable), pool→family selector, layered reachability + panel-
      availability assertions, sampler-time exclusion filter, +
      `mining_config.explicit_exclusions` for 3 intraday-dependent
      factors with unmet daily-mining data dependency. Mining: 200
      trials / 146 finite / 60 archived. Best IC_IR 0.6562 on top
      trial `beta_spy_60d × mom_12_1 × volume_ratio_20d` — STILL
      shares `beta_spy_60d` with RCMv1 verbatim, family-tuple (A,B,C)
      identical to RCMv1, same long-only × monthly × top-N
      construction.
  **Construction-collapse hypothesis empirically confirmed**: 33→61
  factor expansion (with 17 newly-reachable intraday/microstructure/
  short-reversal factors) produced zero archived trials in Family E
  or F at 21d horizon; TPE convergence is on construction not factor
  zoo. 2026 sealed window NOT consumed. Closeout:
  `docs/memos/20260430-track_c_cycle_2026-04-30-01_close.md`. Cycle
  #02 design (when authorized) should prioritize construction-DOF
  expansion (C-3 beta-controlled / C-1 weekly cadence / C-4 cross-
  asset / C-2 long/short), not further factor-zoo expansion.
  Research-mining workstream auto re-frozen at this boundary.

- **Track C cycle 2026-04-30 #02** (2026-04-30, ARCHIVED 2026-05-01,
  **numerical results NOT reliable**) — second controlled-mining
  cycle; single-variable diff vs #01 = +C-1 weekly cadence. Mining
  produced top-1 IC_IR=1.0592 on `beta_spy_60d × mom_12_1 ×
  volume_ratio_20d` — IDENTICAL composite to cycle #01's top-1 (3-of-3
  factor identical). C-1 horizon hypothesis fully refuted at the IC
  level (weekly + global top-N produces same sibling as monthly +
  global top-N). **ARCHIVED post-execution** (Task #49 / heterogeneous
  split-adjustment fix on 2026-05-01) — the daily price panel cycle
  #02 mined on had inconsistent split scaling for 13/78 universe
  symbols (LRCX 2015-04 alternating $72/$7 day-to-day etc.); the
  numeric IC_IR=1.0592 / NAV trajectories / Pearson correlations are
  not reproducible. Factor identity verdict (cycle #02 = cycle #01
  sibling) survives the data corruption (verified by post-fix harness
  re-run on top-1 spec). Yaml + archive marker preserved per
  immutability contract:
  `data/research_candidates/track-c-cycle-2026-04-30-02_ARCHIVED.md`.

- **Track C cycle 2026-05-01 #01** (2026-05-01, INVALID, do not cite) —
  yaml typo `mining_config.trials: 200` instead of canonical
  `n_trials: 200` caused miner CLI yaml→cli mapping to silently fall
  back to default 50 trials; only 3 archived. Yaml sha256 `5df2c305…`
  preserved. **Superseded by `track-c-cycle-2026-05-01-02`** (same
  axis, corrected yaml). Operator self-audit caught (not user); first
  example of why the "依赖捋清楚" rigor matters at yaml field level.

- **Track C cycle 2026-05-01 #02** (2026-05-01 ✅, **0 nominee**,
  10/10 trials Tier 2 sibling-by-NAV) — first cap-aware-construction
  cycle. Yaml sha256
  `9fa478f0ffad33dc2d40eff8ec63b2e86799404b06695b2626390970f169ff23`
  (commit `1edc42b`). Cap-aware = cluster_cap=0.20 + max_single=0.10
  over `core/research/risk_cluster_map.STOCK_RISK_CLUSTER_MAP` (17
  single-layer trade-level clusters, 54 stocks, 25 ETFs excluded) at
  top_n=10 monthly 21d horizon, full RESEARCH_FACTORS pool. Mining
  200 TPE trials, 58 archived. Best IC_IR=1.187 on `rs_vs_spy_126d ×
  drawup_from_252d_low × market_vol_ratio` — DIFFERENT from cycle
  #01/#02 sibling (sibling factors `beta_spy_60d` / `mom_12_1` appear
  at most once each in top-10; 13 unique factors across 30 top-10
  slots). **However**: cap-aware harness eval over top-10 + RCMv1 +
  Cand-2 reference NAVs found 100% (20/20) of pooled-raw-Pearson
  pairs ≥ 0.85 reject threshold (median 0.902, range 0.852-0.947).
  Residual after stripping shared SPY+QQQ beta: median 0.64; only
  1/20 above the 0.70 warn threshold. **Headline finding**: ~85% of
  NAV correlation is structural shared market beta of any long-only
  top-N portfolio over a 54-stock universe; cluster_cap construction
  does NOT break it because the universe itself is the binding
  constraint. Cluster_concentration_max ~0.30 vs cap_aware target
  0.20 is intra-month price drift between monthly rebalances, not a
  selector bug. Closeout:
  `docs/memos/20260501-track_c_cycle_2026-05-01-02_close.md`. Eval
  artifact:
  `data/ml/cycle03_evaluation/track-c-cycle-2026-05-01-02/evaluation_summary.json`.
  Research-mining workstream auto re-frozen. **Next-axis
  recommendation: C-4 cross-asset** (universe expansion to bonds +
  commodities + cash anchor) — directly attacks the structural cause
  this cycle exposed. C-1 weekly cap_aware secondary; C-2 long-short
  violates `no-short` invariant (out of scope).

- **Track C cycle 2026-05-01 #04 cross-asset** (2026-05-01 ✅,
  **0 nominee**, 10/10 Tier 2 by R41 v2 with NAV correlation) —
  first cap_aware_cross_asset cycle (53 stocks + 6 cross-asset ETFs:
  TLT/IEF/SHY/GLD/BIL/SHV; USO/SLV excluded). Yaml sha256
  `b07ece9c9b8c82325d48a0376a871e100f934cab79da98c227dca431fbdd9efc`
  (commit `56457f3`). Construction: cluster_cap=0.20 +
  max_single=0.10 + asset_class_caps={equities=0.70 / bonds=0.40 /
  commodities=0.20 / cash_anchor=0.30}, 22-cluster unified map (17
  stock + 5 cross-asset). 200 TPE trials, 62 archived. P0a-P0d prep
  shipped commit `cc582a2`: distribution sidecar
  `data/ref/distributions.parquet` + `BarStore.load(adjusted_total_return=
  True)` (CAGR parity vs yfinance auto_adjust ≤ 0.01% on 6/6 ETF) +
  P0b 2009-2014 backfill (9054 new daily rows; BIL phantom-split
  handled via yfinance-split-undo) + P0c risk_cluster_map cross-asset
  extension + P0d composite_evaluator cap_aware_cross_asset mode.
  P0e shipped commit `56457f3`: cycle #04 yaml + universe.yaml
  extension + eval pipeline. Closeout shipped commit `dac4176`:
  closeout memo + cross_cycle_nav_correlation post-eval.

  Two character clusters in top-10:
  (a) **Cluster A** (4 trials, drawup+amihud anchored): pooled raw
      NAV corr **0.66-0.70** vs RCMv1/Cand-2/Cycle03-top — first
      cycle ever achieving < 0.85 raw (PARTIAL DIVERSIFIER per yaml).
      Max_dd -16% to -18% (vs cycle03's -27%). Tier 2 by
      factor-overlap=2 with RCMv1.
  (b) **Cluster B** (6 trials, vol-anchored): pooled raw 0.91-0.94
      (NAV reject); max_dd -27% (similar to cycle03); 2025 vs_qqq
      +9.8% to +10.6% (8/10 trials pass hard gate; trial 8 best at
      +10.5% with -19% DD vs QQQ -22.86%). Tier 2 by NAV.

  **Empirical headline**: cap_aware_cross_asset DOES break NAV
  correlation for some mining outcomes (Cluster A first <0.85), but
  mining objective converges on RCMv1-anchor factors (drawup +
  amihud) → factor-overlap rule disqualifies the NAV-diverse trials.
  Breaking mechanism = asymmetric factor coverage on bonds (amihud
  doesn't compute on cash → composite NaN → selector defaults).

  **Process bug + fix**: cycle04 eval shipped with empty
  nav_correlation_vs_existing_pair → R41 v1 verdict was
  factor-overlap-only and incorrectly reported 5 Tier-1 nominees.
  Caught in self-audit; fixed via
  `dev/scripts/cycle04/cross_cycle_nav_correlation.py` post-eval.
  R41 v1 → v2 verdict shift: 5 false-positive Tier 1 → all Tier 2.
  Pipeline lesson: cross-cycle correlation must be in main eval for
  cycle #05+, not deferred to post-eval.

  Sealed 2026 panel NEVER read. Research-mining workstream auto
  re-frozen. **Next-cycle hypothesis (NOT pre-registered, awaits
  user authorization)**: cycle #05 should ban
  `drawup_from_252d_low + amihud_20d` in
  `mining_config.explicit_exclusions`; force factor diversity past
  RCMv1 anchors. Same construction + thresholds.

  **Operator-added enhancements (validated)**: smoke-abort gate
  (cycle03-top1 spec smoked at 34% non-equity → mining authorized);
  2025 QQQ soft-miss trade-off pre-registration (informational only;
  trial 2 partially triggered).

  **Cycle #06 stop rule pre-committed**: if cycle #05 also 0
  nominee, no cycle #06 mining; pivot strategically per collaborator
  §"更宏观的判断" (objective / data / frequency / tools / strategy
  type changes — long-only relaxation requires user explicit-go).
  Closeout:
  `docs/memos/20260501-track_c_cycle_2026-05-01-04_close.md`.

- **Track C cycle 2026-05-01 #05 anchor-sensitivity diagnostic**
  (2026-05-01 ✅, **0 nominee under strict CLAUDE.md QQQ rule**, 7 Tier 1
  R41 verdicts but only trial 9 passes yaml hard blockers, fails project
  invariant on OOS walk-forward window-mean) — first cycle to produce ANY
  Tier 1 R41 classification. Yaml sha256
  `ce559a0ac97a7eb36243de7494c44650ea0779839ec70bc159b94da06a2cbaf7`
  (commit `5110266`). Single-axis diff vs cycle #04 = ban
  `drawup_from_252d_low + amihud_20d` in `mining_config.explicit_exclusions`.
  Mining 200 trials, 149 finite, 44 archived. Best IC_IR=+0.5483 (down 54%
  from cycle04 +1.1991). Top-1: `rs_vs_spy_126d, max_dd_126d, ret_2d`.
  Top-10 R41: 7 Tier 1, 3 Tier 2 (NO Tier 1-conditional, NO Tier 5).

  **Trial 9 (`6c745c601a47`) deep audit** — passes yaml hard blockers BUT
  fails CLAUDE.md project invariant:
  - Spec: `beta_spy_60d (1/3) + max_dd_126d (1/3) + ret_1d (1/3)` (A/B/F)
  - cum_ret 502.6% / sharpe 0.78 / full max_dd -24.5% / vs_qqq full +6.3%
  - Per-year max_dd: 2018=-15.2%, 2019=-6.8%, 2021=-6.0%, 2023=-9.3%,
    **2025=-18.2%** (all > -20% ✓)
  - Per-year vs_qqq: 2018=+3.7%, 2019=-13.2%, 2021=-3.3%, 2023=-19.8%,
    2025=+9.6% → **5-window mean = -4.59% < 0** (CLAUDE.md QQQ Rule
    HARD constraint FAILS)
  - Stress slices: covid_flash max_dd=-13.3%, rate_hike_2022=-15.8% (both
    > -25% ✓)
  - NAV: raw 0.54-0.69 vs all 5 anchors (`partial_diversifier` band);
    residual 0.07-0.36; factor_overlap_max=1 (only beta_spy_60d shared)
  - Asset-class: equity 28.5% / bond 15.4% / commodity 6.3% / cash 10.4%
    / non_equity_avg 32.1% (HIGHER than cycle04 trial 8 ~24%)

  **Hypothesis verdict**: H1 (anchor-specific) SUPPORTED — mining found
  Tier 1 with overlap=0/1 with RCMv1; max_dd_126d substitutes drawup in
  Family B for 4/7 Tier 1 trials. H3 (drawup+amihud binding at IC) PARTIAL
  — IC_IR drop 54% confirms IC anchoring. H2 (low-vol attractor universal)
  PARTIAL — trial 9 has low-vol character (max_dd_126d) but mixed with
  short-momentum + market beta.

  **Strategic review options pre-authored, NOT pre-selected** (yaml
  pre-commit table didn't exactly fit Tier-1-but-fails-invariant outcome
  shape):
  - Option A: User softens CLAUDE.md OOS walk-forward window-mean rule
    for `diversifier` role (NOT `core_alpha`). Directional decision
    required.
  - Option B: D3b regime-aware mining objective (~1 week eng).
  - Option C: Two-stage allocation architecture (4-6 week PRD).
  - Option D: Lightweight diversifier role tag (1-2 day eng; pairs with A).
  - Option E: Hold + observe (default if user authorizes nothing).
  - Option F: Universe expansion (cycle #06 candidate IF A+D fails forward).

  Operator's recommended sequence (NOT user-locked): A+D → forward observe
  trial 9 as diversifier → if forward unhealthy, consider B; if forward
  healthy + multi-candidate, consider C as architecture pivot.

  **Methodology findings (R4 boundary)**:
  - smoke_abort_clause's "5-10 trial smoke" wording is misleading — at
    min_families=3 + cardinality=3 + max_per_family=2, prior probability
    of valid spec ~2.7%/trial → 80% of all-fail in 8 trials normal
    sampling. Cycle04 actually ran fixed-spec smoke. Yaml clause needs
    rewording for cycle #06+ if used.
  - Anchor max_dd full-period contains 2008-2009 (-44% to -48%), making
    Tier 1-conditional c3 lenient. Future cycles with overlap=2 candidates
    must use shared-window max_dd.
  - CLAUDE.md QQQ Rule "OOS walk-forward (average)" wording ambiguous —
    interpreted as Track A per-validation-year mean for cycle #05; if user
    interprets as rolling-window walk-forward (separate framework), trial
    9 standing changes.

  Sealed 2026 panel NEVER read. Research-mining workstream auto re-frozen
  at this boundary. Cycle #06 NOT auto-fired per pre-committed stop rule.
  Closeout: `docs/memos/20260501-track_c_cycle_2026-05-01-05_close.md`.

- **PRD-AC v1.1 implementation + Track C cycle 2026-05-06 #01** (2026-05-06 ✅,
  **0 nominee** per Track A acceptance + 4 strategic findings) — first
  v2_nav_based mining cycle. PRD: `docs/prd/20260505-mining_objective_nav_based_plus_execution_policy_prd.md`
  (v1.1 post-critique). 6 implementation commits (`f2b6059..3fec344`):
  Phase 1 schema + ObjectiveWeights extension; Phase 2 round 1 NAV
  evaluator gate + SPY-residual anchor + I20 detector; Phase 2 round 2
  I9 boundary mask fix + wall-clock benchmark (median 19.36s/trial);
  Phase 3 round 1 holding_freq end-to-end + sr_defer sampling stub
  (round 2 SR-defer full integration deferred); Phase 4 prep + cycle06
  yaml + analysis script. Yaml sha256
  `7b3e20dd8485900c0307c0ef89adc0228ccfb42964d54447550a52184a1bc1df`.
  Mining: 200 trials / 149 finite / 66 archived; top-1 trial
  `bab8cfe88af3` features `drawup_from_252d_low + trend_tstat_20d + ret_2d`
  (sibling pattern with cycle04/05 continues). Hypothesis tests:
  H1 Spearman v2/v1 = 0.89 (FAIL — too IR-heavy at 0.7/0.15 weights);
  H2 holding_freq monthly=49/weekly=10/daily=7 (FAIL by archived count;
  process finding: H2 should test SAMPLED not ARCHIVED); H3 v2 top-1
  nav_sharpe 0.565 < v1 top-1 0.664 (FAIL — Pareto regression);
  H4 anchor_corr 100% < 0.50 (PASS — Option β viable but suspiciously
  clean). Track A acceptance evaluator on top-3 trials: 0/3 pass; all
  fail validation_aggregate_excess_vs_spy/qqq + beta_to_qqq. Cycle
  stop rule fires per cycle04 close memo; strategic pivot to PRD-E
  (TAA) authorized. Closeout:
  `docs/memos/20260506-cycle06_closeout.md`. Phase 3 round 2 (SR-defer
  full mining integration) + cycle07 reweight authorization deferred
  pending forward observation evidence. Research-mining workstream
  auto re-frozen at this boundary.

- **cycle07-to-fleet master ralph-loop + Track C cycle 2026-05-07 (cycle07a)
  + 2026-05-08 (cycle08) + Trial 3 NAV-correlation Red verdict** (2026-05-06
  through 2026-05-07 ✅, **0 forward init**, 1 Track A nominee post-P0-fix
  but Red NAV verdict → evidence-only) — 13-round ralph-loop bundling
  cycle07a + cycle08 mining + 4 audit memos + retroactive Track A re-eval
  fix. Master PRD `docs/prd/20260424-cycle07_to_fleet_master_prd.md`.

  **cycle07a (2026-05-07)** — single-axis diff vs cycle06 = factor reweight
  (drawup_from_252d_low + 短动量 anchor 强化). Yaml sha256
  `1295911ab8949194c3eebf48...` (commit `2fc5198`). Mining 200 trials /
  finite ~149 / 30 archived; top-3 Track A original verdict 0/3 PASS.

  **cycle08 (2026-05-08)** — single-axis diff vs cycle07a = ObjectiveWeightsV3
  regime-conditional weights (BEAR-IC / NEUTRAL-IC / BULL-IC scoped composite
  evaluator). Yaml sha256 part of cycle07-fleet R7 prep (commit `d0b1c4c`).
  Mining 40-trial smoke (NOT full 200) / 11 archived. Track A original
  verdict 0/3 PASS. Smoke caveat preserves yaml integrity (yaml=200, runner
  override --n-trials 40 per R7 prep).

  **P0 wiring bug discovery + fix (2026-05-07)** — R12 audit reverse-validate
  caught suspicious "16 of 17 gates correlated FAIL with beta=present" pattern
  across 9 trials. Root cause: `dev/scripts/cycle{06,07a,08}/cycle*_track_a_eval.py`
  built `metrics["beta_to_qqq"]` (top-level scalar) but
  `core/research/temporal_split_acceptance.py:_eval_beta_gate` resolves
  nested `metrics["beta"]["beta_to_qqq"]` (mirroring yaml schema). Pre-fix
  gate fail-closed silently → all 9 trials had false-negative beta gate
  FAIL despite actual betas well below 0.85 cap. Fix shipped commits
  `5873653` + `9cacab3` (evaluator scripts + 6 regression tests
  `tests/unit/research/test_beta_metric_path_canonical.py`). Postmortem:
  `docs/audit/20260507-beta_metric_path_bug_postmortem.md`.

  **Post-fix 9-trial Track A re-eval (2026-05-07)**:
  - cycle06 (`bab8cfe88af3` / `31af04cf2ff9` / `a9e39c21feed`): 0/3 PASS,
    all fail `validation_aggregate_excess_vs_spy` (vs_spy aggregate is the
    real binding gate; not beta).
  - cycle07a (`81cfb5f4c4f5` / `f133a18d1495` / `1e771580f486`): **1/3 PASS**.
    Trial 3 `1e771580f486` (drawup_from_252d_low + mom_63d + ret_1d, monthly,
    cap_aware) is sole survivor — 17/17 gates PASS, 17yr cum_ret +1016.75%
    vs SPY +231.94% / QQQ +496.38%, sharpe 1.08, full max_dd -20.0%, beta
    0.534, top1 14.5% / top3 36.6%, 2025 holdout +25.1% (+8.4% vs SPY),
    covid_flash +3.6% (vs SPY -13.8%), rate_hike_2022 -7.3% (vs SPY -16.6%).
  - cycle08 (`8ac6bccbeed1` / `60998346d975` / `3f40e3f4ed1a`): 0/3 PASS,
    same vs_spy aggregate failure shape.
  Amendment memo: `docs/memos/20260507-cycle06_07a_08_track_a_post_fix_amendment.md`
  (cycle06+08 verdict UNCHANGED with revised gate-attribution; cycle07a
  Trial 3 = sole nominee).

  **Trial 3 NAV correlation pre-init gate (x.txt 2026-05-07 locked spec)**
  — pre-forward-init authorization required raw < 0.85 + residual < 0.50
  for all 3 pairs vs anchors. Harness:
  `dev/scripts/cycle07a/trial3_nav_correlation.py` (cycle04 cross-cycle
  template + cap_aware STOCK_RISK_CLUSTER_MAP). 16-year extended panel
  (cycle07a selector partition, 2009-2024). Output:
  `data/audit/cycle07a_trial3_nav_correlation.json`.

  | Pair | raw | residual_vs_spy | residual_vs_qqq |
  |---|---|---|---|
  | Trial 3 vs RCMv1 | **0.874** | 0.603 | 0.613 |
  | Trial 3 vs Cand-2 | **0.892** | 0.688 | 0.699 |
  | Trial 3 vs Trial 9 | 0.783 | 0.319 | 0.381 |

  **Verdict: RED** (raw ≥ 0.85 in 2 pairs; residual ≥ 0.50 in 4 of 6
  measurements). **Trial 3 NOT forward-init'd**; evidence-only memo
  records the structural finding:
  `docs/memos/20260507-cycle07a_trial3_red_verdict_evidence_only.md`.

  **Three structural findings (sibling-by-NAV root cause)**:
  - **Finding 1: drawup-anchor + monthly + top-N is the binding sibling
    geometry**. Trial 3 shares ONLY `drawup_from_252d_low` factor with
    RCMv1 (1 of 4) yet raw 0.874. Banning the FACTOR (cycle05) doesn't
    break the sibling pattern; banning the CONSTRUCTION does.
  - **Finding 2: Cand-2 sibling-by-NAV tighter than RCMv1**. Trial 3
    shares 0 of 3 factors with Cand-2 yet raw 0.892. Long-only top-10
    over 78-stock universe = MARKET-COVERAGE binding geometry; disjoint
    factors with same construction pick ~30-50% identical names monthly.
  - **Finding 3: Trial 9 (max_dd_126d) is structurally distinct**. Both
    use cap_aware monthly top-N yet raw 0.783 + residual 0.32-0.38. First
    cycle04-08 candidate where Family-B anchor swap (drawup → max_dd_126d)
    produces NAV-distinct behavior. Empirical confirmation that drawup vs
    max_dd is a real sibling boundary.

  **D.0 fleet allocator gate revision proposal (provisional, NOT
  ratified)**: D.0 (a) currently requires ≥ 2 Track A acceptance nominees;
  proposed tightening to ≥ 2 nominees AND pairwise raw NAV Pearson < 0.85
  across all fleet members on cycle04-canonical 16y extended panel.
  Under proposed rule, Trial 3 counts toward Track A nominee total (1 of 2)
  but does NOT count toward "additive fleet member" — D.0 (a) requires a
  next candidate that is BOTH Track A accept AND raw < 0.85 vs RCMv1 AND
  Cand-2 AND now Trial 3 (3-way constraint).

  **Cycle direction implication**: cycle04-08 + Trial 3 collectively
  demonstrate that cap_aware monthly top-10 over 78-stock universe CANNOT
  break sibling geometry by factor swap alone. Future cycle direction
  options (NOT pre-registered, awaiting user-go): construction DOF
  expansion (weekly / cross-asset / multi-horizon ensemble); universe
  expansion (78 → 200+ stocks OR add bonds/commodities permanently);
  strategy-type pivot (options sleeve in progress; intraday reversal /
  event-calendar untested); gate revision (relax 78-stock universe OR
  long-only invariant — requires user explicit-go).

  **Sealed 2026 panel NEVER read**. Research-mining workstream auto
  re-frozen. Cycle #09 NOT auto-fired per cycle04 stop rule + post-Trial-3-Red
  D.0 gate revision proposal. Closeouts:
  `docs/memos/20260520-cycle08_closeout.md` (cycle08 closeout, pre-fix);
  `docs/memos/20260506-cycle07_to_fleet_final_synthesis.md` (R13 final
  synthesis); `docs/audit/20260506-cycle07_fleet_audit_final_2.md` (R12
  audit, cycle07a R9 line retracted by amendment memo).

- **PRD-E v1.1 implementation (TAA / regime allocation)** (2026-05-06 ✅,
  **5/7 hard gates PASS — defensive sleeve confirmed, standalone alpha
  rejected**) — first non-mining strategy framework in PQS. PRD:
  `docs/prd/20260505-taa_regime_allocation_framework_prd.md` v1.1
  (post-critique). 3 phases shipped over 3 commits (`4bc85ab`,
  `288c3c0`, `281729b`):
  Phase 1 = regime_rules (V1 + V0_MINIMAL) + regime_label_generator
  (daily/monthly cadence + KL/Hamming) + asset_class_builder (universe
  → equal-weight target_wts). Phase 2 = taa_harness.run_taa_backtest
  + train-only smoke (4 variants V1/V0_MINIMAL × monthly/daily on
  partition_for_role(miner) panel). Phase 3 = taa_acceptance G1-G7
  evaluator + selector-panel validation run.

  **Phase 3 verdict (V1 + monthly + selector panel)**:
  - PASS: G1 2018 vs SPY +8.08% (BEAR year defensive value confirmed);
    G3 stress slices (covid_flash -4.73% / rate_hike_2022 -5.04%);
    G4 per-validation-year MaxDD ≤ 20% (max -4.42% in 2021);
    G5 BULL beta to SPY 0.008 (essentially zero); G7 full MaxDD
    -16.04% vs SPY -34.23% (half SPY's drawdown).
  - FAIL: G2 2025 vs SPY -11.20% (CLAUDE.md core role HARD; BULL year
    underperformance per PRD §7 acknowledged risk); G6 Calmar 0.073
    vs SPY 0.337 (HARD primary risk-adjusted; SPY's 10x CAGR offsets
    its 2.1x deeper drawdown).
  - Per-regime DD: BULL -4.89% / CRISIS -5.11% / NEUTRAL -10.26%
    (worst). CRISIS DD < 10% PRD-E target threshold ✓.
  - Standalone alpha verdict: NON-VIABLE (G2 + G6 fail). Defensive
    sleeve verdict: STRONG (5 of 5 defensive gates pass).

  **User directional decision 2026-05-06 = Option B**: close PRD-E1
  standalone path + PRESERVE TAA modules dormant for future fleet
  integration (PRD-E2 / Phase C-PRD-3). No alpha-first cost (modules
  don't run unless caller invokes); audit trail preserved. PRD-E2
  (forward observation runner integration) gated on user explicit-go
  + Trial 9 TD60 evidence (~2026-07-30).

  **Preserved (dormant)**: `core/research/taa/` (6 modules) +
  `tests/unit/research/taa/` (62 tests) + `dev/scripts/taa/`
  (2 dev scripts) + `data/audit/taa_phase{2,3}*.json`.
  Closeout: `docs/memos/20260506-prd_e_phase3_closeout.md`.

- **Bucket A + B + C + Macro factor library expansion + Signal-conf
  MVP Phase 1 skeleton** (2026-05-12 ✅, **+76 factors / 16 mining
  families / mining-search-ready**) — per
  `docs/memos/20260512-quant_factor_literature_synthesis_v2.md` (37
  topic literature review) +
  `docs/memos/20260512-bucket_abc_macro_mvp_schedule.md` (2-week
  schedule). User explicit-go Q1+Q2+Q3+Q4 = all yes 2026-05-12.

  Shipped across 18 commits in one session:
  - **Bucket A (24 OHLCV factors, families G/H/I/J)**: 6 volume
    microstructure + 3 4-quadrant + 6 consolidation + 3 higher
    moments + 3 anchor/reversal/BAB + 3 calendar timing
  - **Bucket B (41 fundamental factors, families K/L/M/N)**: SEC
    EDGAR companyfacts API ingest (210 MB cache, 52/59 stocks
    downloaded, ETFs skipped) + `core/data/{edgar_provider,
    fundamentals_store}.py` + 12 Piotroski + 3 Magic Formula +
    9 Beneish + 6 Altman + 5 capital return + 6 growth/leverage
  - **Bucket C (5 sector factors, family O)**:
    `config/sector_map.yaml` (59-sym manual GICS + 3 historical
    reclassifications incl. META/GOOGL 2018-09-28 Tech →
    Communication) + `core/data/sector_resolver.py` (PIT-aware)
  - **Macro (6 FRED factors, family P)**: 8-series FRED CSV cache
    (no API key needed; CPIAUCNS/FEDFUNDS/DGS10/DGS2/DTWEXBGS/
    DCOILWTICO/VIXCLS/UNRATE) + `core/data/fred_provider.py`
  - **Signal-conf MVP Phase 1 kernel**: `core/signals/signal_state.py`
    state machine (ARMED → CONFIRMED|EXPIRED with TTL); strategy
    class + multi-bar factors + ConfirmationPatternSpace + deferred-
    execution backtest deferred (~3-week follow-up scope)

  **Audit findings (R1-R3 live runs)**: 3 critical bugs caught + fixed:
    1. TTM cumulative double-counting (AAPL CFO TTM 283B vs real 118B,
       2.4×) — SEC EDGAR reports both standalone-Q and YTD-cumulative
       under same tag; fixed by duration-filter (60-100 days
       standalone Q only feed rolling-4 sum)
    2. Strict NaN propagation killed Piotroski for retailers/
       financials (WMT/CAT/GS/JNJ all NaN) — fixed via
       `sum(c.fillna(0))` + nan_mask only when ALL TTM flow inputs NaN
    3. Mask included balance-sheet (non-NaN earlier than TTM) leak
       composite=0 into pre-TTM window — fixed by dropping assets
       from mask logic

  **Post-fix AAPL 2024-12-31 sanity**: piotroski_f_score=8, magic
  earnings yield=3.08%, magic ROIC=47.2%, beneish M-score=-2.67,
  altman Z=10.97, buyback yield=2.80%, fcf yield=2.92%, fcf-to-assets=
  33.6%, revenue YoY=+7.8%, R&D intensity=6.66%. All within 1-6% of
  authoritative references.

  **Mining wiring (Round A)**: 10 new families G-P added to
  `core/mining/research_miner.py::FAMILIES_V2`; `scripts/
  run_research_miner.py::_build_factor_panel_map` extended to merge
  4 compute paths (OHLCV / fundamental / sector / macro) into single
  panel_map. Family-union contract enforced (143 reachable).

  **Round B smoke**: end-to-end miner CLI 3-trial random sampler
  against `--factor-registry-pool RESEARCH_FACTORS` PASS — all 10
  new families sampled from in trials (e.g. trial #2 drew
  {G:2,H:2,I:1,K:1,L:2,M:1,N:1,O:2,P:1}). Pipeline ready for cycle
  #09 when authorized.

  Test surface: 553 unit tests PASS (factors + data + signals +
  mining). Lineage `bucket-abcmacrosig-2026-05-12`.

- **Track C cycle 2026-05-12 #09** (2026-05-12, **INVALID MINING RUN**,
  sampler-architecture mismatch — NOT 0-nominee verdict) — first
  cycle on post-PRD-20260512 162-factor RESEARCH_FACTORS pool. Yaml
  sha256 `351e6e2ce004ef5a96a92ebe85f394ee193467dab78b60e4deb94c14ec0c424f`
  (commit `46ec4cd`, fix `fb81bbb`, final `3894af0`). Single-axis diff
  vs cycle08: factor_registry_pool=RESEARCH_FACTORS (162 not 67) +
  G_new_family_anchor HARD (≥1 anchor from G/I/K/L/M/N/O/P) +
  G_anti_sibling_nav 3-way (raw NAV Pearson < 0.85 vs RCMv1 / Cand-2 /
  Trial 9 v2) + drawup_from_252d_low + amihud_20d banned + 7 masked-dup
  banned per Z1 strict-train cluster r ≥ |0.99| (commit `aa0182e`) +
  v2_nav_based objective + monthly + cap_aware_cross_asset.

  Mining: 200 trials → **100% PRUNED at sampler stage, 0 backtest
  evaluations, 2.1 min wall-clock**. Root cause (R4 postmortem):
  `suggest_composite_spec` independent-family-sampling architecture
  was designed for cycle04-08's 4-6 families (P(valid spec)=2.74%).
  Today's 17-family expansion (Bucket A/B/C/Macro added G-Q) drops
  P(valid spec) to 0.0005% (100k Monte Carlo confirmed 0 hits).

  **NOT 0-nominee verdict** per yaml.stop_rule_post_cycle (which
  assumes "searched but didn't find alpha"). This is "didn't actually
  search" — INVALID mining run. yaml + launcher + closeout script
  preserved as forensic evidence; marker file
  `data/research_candidates/track-c-cycle-2026-05-12-09_INVALID.md`
  fail-closes the launcher. Postmortem:
  `docs/memos/20260512-cycle_09_sampler_architecture_postmortem.md`.

  **Operator R3+R4 audit failure analysis**: preflight R1+R2 missed
  the combinatorics check; 16-trial smoke ran but 0 archived was
  rationalized as "smoke too small". R4 should have asked "why did
  cycle08 work with same yaml params but cycle #09 doesn't?" Lesson
  added to [[feedback_audit_per_round_methodology]]: cycle-config
  changes crossing order-of-magnitude (family count / cardinality /
  universe size) must include numerical combinatorics sanity check.

  User explicit-go 2026-05-12 "同意 A 和 C 同时跑". Both Option A
  (sampler refactor) + Option C (alt-archetype A intraday reversal)
  shipped today:
  - **Option A**: `sampling_mode: family_first` added to
    `suggest_composite_spec` (commit `f41c7e5`). Default
    "independent" preserves cycle04-08 bit-for-bit. family_first
    architecture: pick k families first → pick 1 factor per family.
    P(valid spec) ≈ 100% by construction. yaml CLI plumbing:
    `mining_config.sampling_mode: family_first`. 10 new tests + 215
    regression PASS.
  - **Option C Phase 1**: `IntradayReversalStrategy` skeleton +
    config (commit `d7e48ed`). 13 unit tests PASS. Phase 2 (deferred-
    execution × BacktestEngine integration, ~1 week) + Phase 3
    (Track A acceptance) DEFERRED. PRD §11 4 directional questions
    PENDING user explicit-go before Phase 2 implementation.

  **cycle #09 re-fire** authorization: same sha256-locked yaml +
  Option A sampler refactor + `--bypass-invalid-marker` launcher
  flag. Decision NOT auto-triggered; user-go required.

- **Post-cycle10 strategic roadmap + K1 deferred-execution wrapper**
  (2026-05-13 ✅) — cycle10 closed 0-nominee (R7 fail-SPY risk
  realized per NAV-residualized objective). Roadmap memo v1 → v1.1 →
  v2 FINAL (commits `10838c5` → `a6aa4f0` → `7b12d85`): TC ceiling
  (Clarke-de Silva-Thorley 2002 FAJ, long-only TC=0.45-0.55) reframes
  bundle binding — legitimate attacks = horizon change (intraday) +
  cadence change (signal-driven) + cross-asset done RIGHT; universe
  expansion + LLM mining DON'T attack TC. D1 (200+ stocks) dropped
  with TC-ceiling reason replacing weak cycle04 n=1. D3 (LLM
  mining) DROP → DEFER until K1+T1 produces working construction.
  Signal seed library: 6 evidence-strong seeds (Faber 200-SMA /
  Connors RSI(2) / Donchian 20/55 / HY OAS / Zweig breadth thrust /
  GKM abnormal volume) + 3 orthogonal archetypes (trend /
  mean-reversion / cross-asset risk gate) for T1b + T2a. User 8/8
  explicit-go locked v2: T1a first then T1b∥T1c, PEAD+FOMC bundle,
  cycle11 3 objectives all-try, ML Phase 2 coupled with T2, F1+F2+F3
  all-do, K1 strict TDD, unified observe runner, seed library
  full-collect.

  **K1 ship (2026-05-13 evening)**: `SignalDrivenBacktest` wrapper at
  `core/backtest/signal_driven_runner.py` (212 lines) + 30-test TDD
  suite at `tests/unit/backtest/test_signal_driven_runner.py`. K1.1
  design audit `docs/audit/20260513-k1_deferred_exec_design.md`;
  K1.4 regression report `docs/audit/20260513-k1_regression_report.md`;
  K1.5 closeout `docs/memos/20260513-k1_deferred_exec_ship.md`.
  Commits: `37417ab` design / `7ee24f3` 27-RED+3-GREEN tests stub /
  `47ca31f` impl 30-GREEN.

  **Architectural choice**: wrapper pattern, NOT `BacktestEngine.run`
  modification. `core/backtest/backtest_engine.py` byte-identical to
  pre-K1 `main` — M11a/M11b parity bit-for-bit guaranteed by
  construction. Wrapper drives existing kernel (`SignalStateMachine`
  + `DeferredExecutionSchedule`) per bar → builds (date × symbol)
  weight panel → delegates to `BacktestEngine.run(signals_df=panel)`.
  T1a/T1b/T1c/T2a/T2c all consume this wrapper identically to a
  hypothetical engine extension. If T1b reveals need for state-aware
  cost models (e.g., mid-bar cost change), additive engine
  extension can land then.

  Test surface delta: +30 tests (1.3% of 2323 baseline). All 30
  GREEN; full `tests/unit/backtest/` 199/199 PASS (no regression
  on M11a/M11b parity / NaN-equity / concentration metrics /
  intraday paths / ghost cleanup / cap_aware).

  **Status**: T1a (alt-A `IntradayReversalStrategy` Phase 2-3)
  unblocked; estimated 3-5 days as first real consumer.

- **SPY/BIL/SHV off-by-one date label bug + Option A fix** (2026-05-13
  evening ✅) — surfaced during K1 ship-close broader regression run
  (3 pre-existing forward bar_hash test failures investigated).
  Postmortem: `docs/memos/20260513-spy_off_by_one_date_label_postmortem.md`.
  Closeout: `docs/memos/20260513-option_a_closeout.md`. User explicit-go
  Option A 2026-05-13.

  **Bug**: `core/data/calendar.py::align_daily_index` did
  `tz_localize(None)` without `tz_convert(_ET)` first. For yfinance
  data that occasionally returned UTC-tz-aware index, UTC-midnight bars
  rolled forward +1 calendar day (Mon trading → Tue label, Fri → Sat
  label) producing ~569 fake Saturday rows per affected symbol.

  **Affected PQS active universe**: 3/81 symbols — **SPY, BIL, SHV**
  (yfinance-fetched). Initial scan suggested 10+ but JPM/V/PG/HD/BAC/
  XOM/CVX are NOT in `config/universe.yaml` (leftover data files only).

  **Fix** (commit `2898be8`): `align_daily_index` now `tz_convert(_ET)`
  before `tz_localize(None)`. Pure correctness; tz-naive data (common
  case) bit-for-bit unchanged. Rebuild script
  `dev/scripts/data_fix/rebuild_off_by_one_symbols.py` re-fetched
  SPY/BIL/SHV via fixed path; old parquet preserved as
  `.preFix_2026-05-13` sidecars (gitignored).

  **Validation**: post-fix 81-symbol universe scan = 0 affected;
  3 previously-failing forward bar_hash tests = 3/3 PASS; backtest
