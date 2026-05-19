<!-- PQS module CONTEXT.md — 由 CLAUDE.md 2026-05-19 reorg 拆出。
CLAUDE.md = context 入口,仅留项目级(不变量/纪律/架构/概括)。
本文件 = 本模块的历史/契约细节(content-preserving 搬迁,无删改)。
回指: ../../CLAUDE.md ; 索引见 CLAUDE.md 末「Module CONTEXT.md 索引」。 -->

# core/research/forward/CONTEXT.md — module history / contract detail


## [Forward OOS workstream 史(R-fwd-1/2/3 / F PRD)+ RCMv1/Cand-2 terminated + Trial9 全审计 + trial9_002 + chart_native_s1 forward 细节]

**Forward OOS workstream (infrastructure history + active state)**:
Infrastructure (R-fwd-1 / R-fwd-2 / R-fwd-3 / F) shipped 2026-04-26
through 2026-04-29 + R8 DST fix; legacy candidates RCMv1 + Cand-2
forward-observed 2026-04-24 through 2026-04-28 then **aborted
2026-04-30** under v2.1 fail-closed gate (see "Forward observation
history" entry below). **Active forward candidates as of 2026-05-15**:
- `cycle08_3f40e3f4ed1a_evidence_v1` (core_alpha role, evidence stance,
  TD001 @ 2026-05-15, TD60 ~2026-08-14) — passed Track A post-MaxDD-fix
  + sealed 2026 (2/2). main core/research/forward runner.
- `cycle06_31af04cf2ff9_evidence_v1` (core_alpha role, evidence stance,
  TD001 @ 2026-05-15, TD60 ~2026-08-14) — same; vs_qqq diagnostic-only.
- `trial9_diversifier_002` (diversifier role) — **RETIRED 2026-05-15,
  status=completed_fail**. Halted first on requires_data_review (v2.1
  revalidate detected the P0.b/P0.b.4 data repair on ~15 held symbols'
  2024 bars feeding the factor lookback windows). Track A re-eval under
  the fixed MaxDD gate (source trial 6c745c601a47, repaired data)
  then FAILED: 2018 MaxDD -24.65%, 2025 -21.33%, covid_flash -35.75%
  — all over the 20%/25% ceilings. Original cycle05 acceptance used
  the dead MaxDD gate; vs_spy positive every year (alpha fine) but
  drawdown discipline fails — same pattern as cycle08_8ac6bcc +
  cycle12 candidates. The trial9 diversifier line (001 + 002) ends.
- `pead_sue_trial1_evidence_v1` (evidence-only role, TD001 @ 2026-05-15,
  TD60 ~2026-08-13) — standalone observation track
  (dev/scripts/pead/observe_pead_evidence.py), does NOT use main
  runner (event-driven SUE signal doesn't fit factor-composite schema)
- `spy_8otm_bull_put_v1` (options sleeve, TD007 @ 2026-05-15, TD60
  verdict ~ 2026-07-30) — options paper-trading layer, separate path
- `chart_native_s1_evidence_v1` (evidence_only_observation role,
  TD000 baseline @ 2026-05-18, start 2026-05-19, TD60 ~2026-08-13) —
  standalone observation track for the chart-native learned probe
  (GAF63 → frozen ResNet18 IMAGENET1K_V1 → train-only ridge β,
  FROZEN never refit forward; spec_hash d035c184…, beta_sha
  439ee31e…). Does NOT use main composite runner (learned probe ≠
  ResearchCompositeSpec; pead/simple_baseline precedent). Does NOT
  enter fleet. Evidence-grounded forward-init per
  feedback_promotion_only_falsification_evidence_gated: original
  PASSED Track-A all 17 gates; 4 falsification attempts (neg-control
  / no-overlap / survivorship n=8 confound / survivorship 70-name
  meaningful PASS) yielded ZERO strategy-self flaw evidence; pre-2015
  true-PIT survivorship structurally untestable (C5) is exactly what
  forward soak tests. **⚠ LEAKAGE CAVEAT (2026-05-18): the original
  17/17 Track-A PASS is leakage-inflated — leakage-correct re-eval
  (López de Prado average-uniqueness + purge/embargo, run4) →
  Track-A FAIL (validation_aggregate_excess_vs_spy + 2025 vs_spy),
  IC-on-59 0.0146→0.0110 (−25%). Decision A (user 2026-05-18) = KEEP
  as evidence_only + documented caveat, β NOT refit (frozen contract;
  refit=new candidate). EVERY forward judgment / TD60 (~2026-08-13)
  MUST cite this caveat; do NOT use 17/17 PASS as health baseline.
  See `data/research_candidates/chart_native_s1_evidence_v1_CAVEAT.md`
  + `docs/memos/20260518-chart_native_s1_evidence_leakage_caveat_decision.md`
  + `docs/memos/20260518-l3_deconfound_correctness_verdict.md` §5.**
  Closeout:
  `docs/memos/20260518-chart_native_s1_evidence_forward_init.md`.
  init: `dev/scripts/chart_native_l3/init_chart_native_evidence.py`.
  daily-ritual observe script = follow-up (mirrors pead pattern).
Forward fleet anti-sibling: cycle06/cycle08/trial9 pairwise raw NAV
0.704-0.825 (all < 0.85). Daily ritual log: docs/forward_observation_log.md.
- **R-fwd-1 done** — forward runner minimum closed loop (init /
  status / observe / decide / readiness) + source-boundary sidecar
  + `source_mix` flag on ForwardRun. PRD:
  `docs/prd/20260426-forward_oos_runner_prd.md`. Both candidates
  (RCMv1 / Cand-2) have first real forward TD entries:
  ```
  RCMv1   start_date=2026-04-24  TD001 / 2026-04-24 / source_mix=True
  Cand-2  start_date=2026-04-24  TD001 / 2026-04-24 / source_mix=True
  ```
  source_mix=True because forward observes yfinance frontier bars
  while candidates were constructed on polygon canonical (different
  adjustment semantics, surfaced honestly).
- **R-fwd-2 / R-fwd-3 evidence-hardening SHIPPED v2.1.3 (2026-04-28 ✅)** —
  per `docs/prd/20260427-forward_evidence_hardening_prd.md`. Five
  layered commits on `main`:
  1. **v2.1 base** (`c3cefc1` → `5cd51f3`, codex Round 6→9): schema
     models + factor input contract resolver + 3 per-scope hashers
     (signal_input / execution_nav / benchmark) + bar_hash rollup +
     materiality_anchor_values 10-day ring + per_cell_digest +
     window-scoped source-layer classifier + revalidate E1-E5
     materiality policy + runner integration with legacy_unhashed_inputs
     marker on pre-v2 TD001.
  2. **v2.1.1 audit round 1** (`fd24285`): 4 self-audit fixes
     (storage budget pinned via `track_per_cell=False` default;
     revalidate moved to TOP of observe; `requires_data_review`
     halt guard; epsilon tolerance on E1/E2/E3/E5 thresholds + E4
     symmetric drift check).
  3. **v2.1.2 audit round 2** (`7c7f860`, `e942ab9`): Bug 5 fix
     (flagged_only events lost on no-new-bar return path, now
     persisted via `manifest_dirty_from_revalidate` flag).
  4. **v2.1.3 codex Round-10 blocker fixes** (`4abc3c9`, `051d869`):
     - Blocker 1: `compute_signal_input_hash` window resolution
       changed from `pd.tseries.offsets.BDay(lookback)` to true
       trading-day rows from panel index. Pre-fix BDay(252) landed
       ~9-13 trading rows short of the true 252nd prior trading
       day on the NYSE calendar (BDay = Mon-Fri only, no holidays).
     - Blocker 2: empty `signal_input.per_cell_digest` (production
       default) now ALWAYS fail-closes to bound_only when the
       rolling hash differs, regardless of execution_nav scope
       state. Pre-fix optimistically gated on exec_nav and could
       under-classify dual-scope revisions as flagged_only.
     - Adjacent: revalidate now passes matching `track_per_cell` to
       `compute_signal_input_hash` recompute (was silently producing
       spurious 821-cell diffs in opt-in test mode).
  Forward slice: 51 → 102 tests (+2 R8 DST regressions); full unit
  suite 1838 passed.
- **F (config / universe snapshot hardening) SHIPPED (2026-04-29 ✅)** —
  per `docs/prd/20260428-config_universe_snapshot_hardening_prd.md`.
  Five-step layered shipping on `main`:
  1. **Step 1** (`1952e44`): `ConfigSnapshot` + `ConfigDriftEvent`
     pydantic models in `manifest_schema.py`; `ForwardRunManifest.config_snapshot`
     and `ForwardRun.config_drift_event` Optional fields. Lazy-migration
     compatible — pre-PRD-F manifests load with both fields = None.
  2. **Step 2** (`c28c969`): `_canonical_yaml_sha`
     (sorts dict keys recursively, **preserves list order** —
     conservative fail-closed) + `_factor_registry_contract_sha`
     (hashes the contract not the file bytes; refactor-stable) +
     `_build_config_snapshot()` helper. `init(config_dir=...)`
     wiring stamps the snapshot at forward-init time.
  3. **Step 3** (`368536d`): `revalidate_manifest(current_config_snapshot=...)`
     + `RevalidationSummary.config_drift_event` slot (kept separate
     from data_revision events per codex round-11 §B3). Severity
     policy: `universe_hash` / `factor_registry_hash` / `risk_config_hash`
     → halt (flips `current_status` to `requires_data_review`);
     `research_mask_hash` / `system_config_hash` → warn. `observe()`
     wiring builds a fresh snapshot, attaches event to latest TD,
     INFO-logs once per process per candidate when manifest is
     pre-PRD-F (lazy-migration boundary).
  4. **Audit fixes** (`abc4425`): `extra="forbid"` on F-PRD models
     (typo-key bug); docstring fix on `_canonical_yaml_sha`;
     terminal-status halt on `observe()` (decided candidates can't
     be silently overwritten).
  5. **Step 4 backfill** (`ad6491e`): `dev/scripts/forward/backfill_config_snapshot.py`
     opt-in CLI for pre-PRD-F manifests. Stamps `migration_note=
     "backfilled_<date>_assumed_unchanged_since_init"`. Idempotent
     without `--force`; `--dry-run` previews byte-identical. 8 tests
     in `tests/unit/research/test_backfill_config_snapshot.py`.
     Plus codex round-18 follow-up `observe(config_dir=...)` kwarg
     for hermetic-test contract symmetry with `init()`.
  Forward slice today: 146 tests (24 added since v2.1.3 baseline:
  10 F step-3 drift + 5 audit-round 1+2 fixes + 8 step-4 backfill +
  1 R18 §1 config_dir-kwarg regression). Full unit suite 1850 passed.
  **Operational rule established (audit reverse-validate finding)**:
  forward `fetchdata` MUST run post-NYSE-16:00-ET close. Earlier
  intraday fetches put a partial-day "close" on disk; the next
  observe()'s v2.1 revalidate correctly fail-closes (NAV impact
  exceeds E1=10 bps; raw drift exceeds E5=0.5%). **2026-05-12
  strengthening**: `scripts/fetch_data.py` main() now raises
  `SystemExit` if called pre-close (was warn-and-cap until 2026-05-12);
  `--allow-pre-close-today` remains as emergency override. Programmatic
  callers (importing download_daily / download_intraday) still get
  the original warn-and-cap as defense-in-depth.
  **Status**: F PRD §6 acceptance 13/13 ✅; codex round 19 + 20 closed;
  F line officially functional (no pending sign-off). RCMv1 + Cand-2
  production manifests still pre-PRD-F (config_snapshot=None); user
  has not yet run the opt-in backfill — drift detection on those two
  will activate when backfill is run. **Operational rule**: forward
  `fetchdata` must run after NYSE 16:15-16:30 ET (codex R20 operational
  note tightening earlier "post-NYSE-16:00 ET" rule).
- **Forward observation history (RCMv1 + Cand-2, TERMINATED 2026-04-30)**.
  First real `forward observe` since v2.1.3 + R8 DST fix ran 2026-04-28
  (commit `bcfbc0f`):
  - rcm_v1_defensive_composite_01: TD001 (legacy) + TD002 + TD003 (last 2026-04-28)
  - candidate_2_orthogonal_01:     TD001 (legacy) + TD002 + TD003 (last 2026-04-28)
  TD001 carries `legacy_unhashed_inputs=True` (no retroactive hash
  backfill); TD002 + TD003 carry full v2.1.3 4-scope hashes
  (signal_input + execution_nav + benchmark + bar_hash rollup).
  Cross-candidate benchmark_hash invariant verified live (same SPY+
  QQQ panel → same hash on same TD). Evidence note:
  `docs/memos/20260428-forward_observe_first_real_after_v2_1_3.md`.

  **Status: BOTH ABORTED 2026-04-30** via `decide --status aborted` —
  material data revision detected: **108 bps NAV drift + 2.42% raw
  drift across 13 (RCMv1) / 16 (Cand-2) held-eligible symbols
  including SPY+QQQ** → F-PRD v2.1 §4.4 fail-closed. The legacy
  candidates were nominated pre-G2.A 30% concentration ceiling +
  pre-M12 weighted thin-data fix and were already classified as
  `legacy_decay_verification` role per 2026-04-29 reclassification;
  abort closes their forward TD60 observation entirely. They will
  NOT enter fleet, will NOT calibrate new-framework gates, and the
  daily ritual no longer touches them (terminal status absorbs further
  observe() calls).

  **Current PQS active forward state**: as of 2026-05-14, 3 active
  forward candidates: `trial9_diversifier_002` (TD001 starts 2026-05-13,
  diversifier role, main runner), `pead_sue_trial1_evidence_v1` (TD001
  starts 2026-05-15, evidence-only role, standalone PEAD track), and
  `spy_8otm_bull_put_v1` (options paper, TD started 2026-05-04). RCMv1
  + Cand-2 manifests preserved at:
  - `data/research_candidates/rcm_v1_defensive_composite_01_forward_manifest.json`
  - `data/research_candidates/candidate_2_orthogonal_01_forward_manifest.json`
  Both retain 3 TDs + 1 DECIDE entry each as forensic evidence of
  their April 2026 forward trajectory + the fail-closed abort event.

- **Trial 9 (2026-05-01 ✅, A+D Phase C-PRD-1 SHIPPED commit `7dcdf50`)** —
  first **diversifier-role** forward observation candidate. PRD:
  `docs/prd/20260501-two_stage_allocation_architecture_prd.md`. Decision
  memo: `docs/memos/20260501-diversifier_role_decision.md`. User
  explicit-go 2026-05-01 + D10c compromise (soft-warn at 18% / hard-fail
  at 20% per-year max_dd + TD60 self-clearing). Source: cycle #05 trial
  `6c745c601a47` (`beta_spy_60d + max_dd_126d + ret_1d`).
  - candidate_id: `trial9_diversifier_001`
  - candidate_role: `diversifier` (first non-legacy role assigned in PQS)
  - spec_hash: `8f58d40d2ef579a7c1b0fee53cd29da23763f336dd91a4b4db2c97eb2acec5a6`
  - start_date: 2026-05-04 (Mon, next trading day)
  - soft_warn_flags: `['diversifier_2025_maxdd_18_20pct']`
  - frozen spec: `data/research_candidates/trial9_diversifier_001.yaml`
  - manifest: `data/research_candidates/trial9_diversifier_001_forward_manifest.json`
  - init script: `dev/scripts/forward/init_trial9_diversifier.py`

  **Phase C-PRD-1 deliverables** (all in commit `7dcdf50`):
  - `CandidateRole` enum (4 values) in `core/research/forward/manifest_schema.py`
  - `ForwardRunManifest.candidate_role + soft_warn_flags` (lazy migration)
  - `CandidateRecord.role` + idempotent `ALTER TABLE` migration
  - `runner.init(candidate_role=..., soft_warn_flags=...)` kwargs
  - `config/temporal_split_v2.yaml` (split_name v1→v2 per locked-after-first-use
    C4 policy; partition UNCHANGED; only diversifier role thresholds updated to
    PRD §6.2 evidence-derived values)
  - CLAUDE.md QQQ Outperformance Rule diversifier exception (waives ONLY
    OOS walk-forward window-mean rule for role=diversifier; all other gates
    unchanged; STRICTER for diversifier on NAV correlation + factor overlap
    + non-equity exposure)
  - `dev/scripts/forward/backfill_candidate_role.py` (legacy candidates
    explicitly tagged role=legacy_decay_verification; idempotent)
  - 32 new tests (`test_diversifier_role_phase_c_prd_1.py`) + 138 existing
    forward+registry+temporal_split tests pass (no regression)

  **Post-ship gap fix #1 — v2 dispatch (commit `60e0dfe`)**: v2 yaml was
  created at ship but the loader (`core/research/temporal_split.py:_DEFAULT_PATH`)
  defaulted to v1; v2 was only consumed by the 32 unit tests, NOT by
  acceptance pipeline / future cycle #06 mining. Closed via
  `resolve_split_path(role, freeze_date)` dispatch helper +
  `run_split_acceptance(freeze_date=...)` threading + extended `GateRule`
  schema for `action: soft_warn` (with `soft_warn_label` /
  `soft_warn_clear_condition` / `soft_warn_unclear_action` fields
  required iff soft_warn). Dispatch rule: `role=diversifier AND
  freeze_date >= 2026-05-01 → v2`; everything else → v1 (legacy contract;
  immutability for cycle04+05 archived trials + RCMv1+Cand-2). 20 new
  dispatch tests.

  **Post-ship gap fix #2 — forward attention check automation (commit
  pending)**: TD20/TD40/TD60 milestones need automated derived metrics
  beyond what `observe()` captures (residual NAV correlation, combo NAV,
  rolling 60d MaxDD, non-equity exposure drift, soft_warn self-clearing
  status, PRD §7.1 GREEN/YELLOW/RED verdict). Shipped pure-compute
  module `core/research/forward/attention_report.py` + CLI driver
  `dev/scripts/forward/attention_check.py`. Outputs JSON to
  `data/ml/forward_attention/` + stdout markdown. Gracefully handles
  empty manifests (trial 9 currently 0 runs; full report computable
  TD60+). 31 unit tests covering: NAV series derivation, multi-candidate
  combo, rolling MaxDD, residual corr (regress out benchmark beta),
  asset-class classification, PRD §7.1 verdict logic, end-to-end
  graceful degradation. Full unit suite 2323 passed (no regression).

  **TD60 decision point pre-committed** (~2026-07-30):
  - GREEN: residual NAV corr 60d <0.4 + per-regime BULL vs_qqq 60d > -3% +
    portfolio combo positive + soft_warn_flag self-cleared (60d rolling
    max_dd ≤ 15%) → authorize Phase C-PRD-2 (sleeve abstraction)
  - YELLOW: 0.4-0.6 residual OR BULL vs_qqq 60d in [-10%, -3%] → continue
    to TD90
  - RED: residual >0.6 OR BULL vs_qqq 60d <-10% OR portfolio combo
    negative → stop trial 9 forward; do NOT build C architecture for it

  **Phase C-PRD-2/3/4 NOT authorized** (deferred per PRD §8 evidence-gated
  triggers). D3b regime-aware mining objective DEFERRED + absorbed into
  Phase C-PRD-3 Stage 1 allocation. Track B Step 6+ ABSORBED into
  Phase C-PRD-3/4 (Steps 1-5 already shipped; reused unchanged as Stage 3
  inputs).

  **Operational contract**: forward `fetchdata` MUST run post-NYSE 16:15-16:30
  ET close (codex R20 operational note). Trial 9 first observe = 2026-05-04
  EOD; produces TD001 entry.

  **Trial 9 forward state (2026-05-05 EOD)**: TD001 (2026-05-04, cum_ret=0.0)
  + TD002 (2026-05-05, cum_ret +3.60%, vs_spy +2.80%, vs_qqq +2.31%, max_dd
  0.00%); status=in_progress. TD002 only after PRD 20260505 E4 near-zero
  exemption + `recover` CLI (see Phase E shipped list). TD001 carries 1
  PolicyRecoveryEvent in `policy_recovery_log` (audit trail; original
  data_revision_event downgraded `invalidated → flagged_only`).

  **Trial 9 forward state at closeout (2026-05-12)**: 4 TDs observed
  before halt. TD003 (2026-05-06) cum_ret +8.02% / vs_spy +5.82% /
  vs_qqq +4.62% / max_dd 0.00%. TD004 (2026-05-07) cum_ret +5.04% /
  vs_spy +3.15% / vs_qqq +1.76% / max_dd -2.75%. 2026-05-12 daily-ritual
  `observe()` revalidate detected retroactive yfinance refresh on all
  4 TDs; TD001-TD003 classified `flagged_only`/`in_ring` (sub-bps NAV
  impact); **TD004 classified `invalidated`/`bound_only`** with trigger
  `bound_only (signal_input scope diff with empty per_cell_digest
  (track_per_cell=False) — cannot prove diff is subset of execution_nav-
  anchored cells; conservative bound_only per PRD §4.4 (codex Round-10
  Blocker 2))`. Manifest flipped to `requires_data_review`. 4-round
  self-audit on 2026-05-12 verified: (a) 18 held syms × 10 anchor-ring
  dates × close anchor values vs current panel = 0 diff revealed, (b)
  re-hash of signal_input with `track_per_cell=True` against current
  panel still differs from stored, (c) therefore revised close cell
  is OUTSIDE execution_nav anchor coverage (i.e., non-held sym OR date
  older than 4/24 ring start). No retroactive reconstruction path
  exists (stored signal_input `per_cell_digest` was empty per production
  `track_per_cell=False` default). `recover` halts because policy
  re-eval produces same bound_only verdict. **Considered + rejected**:
  A1 magnitude-bounded exemption (post-hoc TD004 fit, breaks codex R10
  Blocker 2 intent); A1.c synthetic anchor reconstruction (infeasible —
  revised cell outside anchor coverage). **Shipped fix**: A4+A2 path
  per PRD `docs/prd/20260512-per_candidate_track_signal_input_per_cell_prd.md`
  + closeout memo `docs/memos/20260512-trial9_diversifier_001_closeout.md`
  + commit `16de8dd`. `trial9_diversifier_001` status =
  `completed_fail` (DECIDE entry recorded). 4 TDs preserved as forensic
  evidence in manifest.

- **trial9_diversifier_002 (2026-05-12 ✅, A4+A2 SHIPPED commit `16de8dd`)** —
  successor to `trial9_diversifier_001` under PRD 20260512 per-candidate
  `track_signal_input_per_cell` opt-in. Composite + construction +
  universe IDENTICAL to v1; only material diff = `evidence_config:
  {track_signal_input_per_cell: true}` in frozen yaml, which causes
  forward runner (line 1041 of `core/research/forward/runner.py`) to
  pass `track_per_cell=True` to `compute_signal_input_hash` at TD-write
  time. Resulting non-empty `per_cell_digest` lets v2.1 revalidate do
  real cell-level diff (revalidate.py:429-444) so bound_only-with-empty-
  digest failure mode cannot recur on this candidate.
  - candidate_id: `trial9_diversifier_002`
  - candidate_role: `diversifier`
  - spec_hash: `44870b91073aa5440dfa5d8ccc07b1f43dcc25235ce9139e2ca0352559e8f985`
  - start_date: 2026-05-13 (Wed, next trading day after closeout)
  - soft_warn_flags: `['diversifier_2025_maxdd_18_20pct']` (mirrored from v1)
  - frozen spec: `data/research_candidates/trial9_diversifier_002.yaml`
  - manifest: `data/research_candidates/trial9_diversifier_002_forward_manifest.json`
  - init script: `dev/scripts/forward/init_trial9_diversifier_002.py`

  **PRD 20260512 deliverables** (commit `16de8dd`):
  - `FrozenStrategySpec.evidence_config: Optional[dict] = None` field
    (mirrors `execution_policy` precedent from PRD 20260505)
  - `runner.py:1041` reads `spec.evidence_config` to resolve
    `track_per_cell` kwarg
  - 9 new tests `tests/unit/research/test_forward_evidence_config.py`
    (legacy preservation / opt-in PASS / opt-in False explicit /
    rolling hash invariant across flag / yaml round-trip / from_dict
    missing field / from_dict explicit field / extras separation)
  - 893 research-tests-suite passes (no regression on RCMv1 / Cand-2 /
    trial9_001 legacy paths)

  **Storage cost** (close-only signal_input attr for diversifier with
  this composite): ~163 KB / TD → ~10 MB / 60-TD soak / candidate.
  Operator monitoring at TD030 (~2026-06-25) + TD060 to validate
  estimate (PRD 20260512 §5 / closeout memo §"What the operator owes
  future-self").

  **TD60 decision point pre-committed**: ~2026-08-06 (1-week slip from
  v1's ~2026-07-30 baseline; acceptable per resident-quant judgment to
  preserve diversifier-role evidence chain over restart cleanliness).
  Same GREEN/YELLOW/RED verdict criteria as v1 (residual NAV corr 60d
  + per-regime BULL vs_qqq 60d + portfolio combo + soft_warn self-clearing).

  **What the operator owes future-self**: first observe on 2026-05-13
  EOD (post-NYSE 16:15 ET fetch) will produce TD001 with NON-EMPTY
  `bar_hash_inputs.signal_input.per_cell_digest` — this is the
  load-bearing behavior change that prevents v1's failure mode from
  recurring.

**Track A — Temporal Split & Holdout Discipline (SHIPPED 2026-04-29)**

PRD `docs/prd/20260429-temporal_split_holdout_discipline_prd.md` v1.1
(codex round 19 + 20 PRD-level approved). Roadmap
`docs/memos/20260429-post_audit_strategic_roadmap.md` v3. Implementation
log `docs/memos/20260429-track_a_implementation_log.md`. F1/F2 fork
criteria locked pre-smoke at `docs/memos/20260429-track_a_f1_f2_fork_criteria.md`.

Shipped infra (no real mining yet):
- `config/temporal_split.yaml`: alternating_regime_holdout_v1 — train
  2009-2017+2020/2022/2024; validation 2018/2019/2021/2023/2025
  (2025 hard gate on core role); 2 stress slices (covid_flash +
  rate_hike_2022) borrowed for MaxDD sanity only; 2026 sealed
  single-shot.
- `core/research/temporal_split.py`: pydantic loader + train/validation/
  sealed sets + restrict_frames_to_train + validate_no_holdout_leakage +
  compute_panel_max_date + ensure_role_assigned + purge_labels_at_boundary
  (M4) + validate_factor_lookback (M3 cap) + enforce_c5_no_role_remint.
- `core/research/temporal_split_acceptance.py`: 17-gate evaluator (per
  validation year + stress slice + role + concentration + beta + cost);
  separate from acceptance_pack (codex round 13 frozen contract).
- `core/research/sealed_ledger.py`: M5 fail_closed_on_repeat + codex
  R20 B1 fail_closed_on_split_failure parquet ledger.
- `core/research/regime_classifier.py`: M9 manual + auto regime tag with
  tiered disagreement policy (memo / user-go / hard error).
- `core/mining/rcm_archive.py`: 7 new columns; idempotent ALTER;
  find_studies_by_spec_role for C5 lookup.
- `scripts/run_research_miner.py`: --temporal-split + --role flags;
  panel restrict + leak guard + summary metadata.

Track A test surface: 126 unit tests covering all 18 PRD §11 acceptance
criteria. Combined repo unit suite: full pre-Track-A 419 research
tests preserved + 126 Track A tests = 545 in research module.

What's still open:
- **PRIORITY REALIGN (2026-04-30, audit R36)** — see
  `docs/memos/20260430-priority_realign_alpha_first.md`. Project
  has crossed governance-saturation threshold; alpha not yet
  proven under new framework. Until cycle #01 produces a candidate,
  guard infrastructure has zero operational consumer. **Order is
  now alpha-first**: cycle #01 preflight (P0) + E.MV signoff
  (external) + generic NAV pair runner refactor (P1) + Track A
  acceptance β-stamp minimal extension (P1). **A.MV/B.MV full
  implementation DEMOTED to P2 candidate-gated; Fleet Step 6+
  HARD PAUSED.** Pre-emptive guard work is over until candidate
  evidence justifies it.
- **Track B** Fleet Allocator: **Steps 1-5 SHIPPED** (2026-04-29
  Step 5 = C2 correlation budget, codex R30 accepted code-level).
  Step 6+ (DD throttle / role caps / fleet observe / shadow→live):
  **HARD PAUSED until ≥2 candidates exist that BOTH pass Track A
  acceptance AND have realized-NAV pair correlation < 0.85.** Per
  R36 priority realign: continuing allocator downstream while no
  fleet candidate exists is empty plumbing. PRD
  `docs/prd/20260428-candidate_fleet_allocator_prd.md` v1.1 codex
  round-14 approved (frozen at this state).
- **Track C real mining: cycle #01 ALPHA-FIRST PRIORITY** (2026-04-30,
  `docs/memos/20260430-track_c_dry_run_plan.md` — renamed from
  "dry-run" per external reviewer §7 to reflect formal-cycle
  discipline). **Pre-registered immutable criteria yaml is P0
  internal to write before any trial runs** (does not depend on
  E.MV signoff; criteria immutability requires pre-registration
  same as cycle 2026-04-26 #01). Compute itself unblocks on E.MV
  §4.6 (NAV-orthogonality tier landed in template v1.1 at `01d2950`) +
  §4.7 (economic-assumption flags F1-F6) reviewer signoff (external
  dependency). **Cycle #01 closeout MUST classify candidate against
  auditor R36 §4 alpha-source taxonomy** (intraday reversal /
  event-calendar / cross-asset / volatility / different cadence /
  beta-controlled construction); a candidate that passes gates
  but is structurally a RCMv1/Cand-2 sibling does NOT enter
  nominee status — that's the anti-sibling discipline.
- **Forward-observation NAV correlation finding (2026-04-30)**:
  RCMv1 + Cand-2 pooled raw NAV Pearson **0.898** (Step 5 reject
  threshold 0.85). Residual decomposition: vs SPY 0.609 (drop 0.29) /
  vs QQQ 0.579 (drop 0.32). Both candidates' residual annualized
  Sharpe positive (vs QQQ: RCMv1 +2.08, Cand-2 +2.77). Classification:
  `mixed` — ~30% raw correlation is shared market beta, ~60% is
  shared alpha. Cand-2 "orthogonal" claim retracted at NAV level
  (still valid at factor-IC level only). Fleet-of-two equal-weight
  composition does NOT produce risk diversification — both candidates
  re-classified as legacy decay verification only. Track C must find
  a candidate that differs on BOTH beta AND residual alpha — a
  low-beta defensive candidate alone fixes only ~30% of the problem.
  Evidence: `docs/memos/20260430-rcmv1_cand2_realized_correlation.md`.
- **Concerns A/B/E (Track C downstream guards)** — proposed in
  `docs/memos/20260430-concerns_abE_proposed_solutions.md`. **E.MV
  shipped in template v1.1** (commit `01d2950`); reviewer signoff
  pending. **B.MV + A.MV implementation: DEMOTED to P2
  candidate-gated per priority realign 2026-04-30**:
  - B.MV reactivates when cycle #01 produces a candidate that
    passes Track A acceptance + evidence pack §4.6+§4.7 + is
    approved for forward init. Schema contract locked at
    `docs/memos/20260430-bmv_schema_decision.md` (no further
    iteration before consumer exists).
  - A.MV reactivates when that candidate completes forward soak
    (≥ TD60 healthy + no early-attention triggers) AND sealed eval
    is the next gate. Until then, manual sealed-eval discipline
    rule applies (clean window starts strictly after candidate
    `freeze_date` AND after `panel_max_date_at_freeze`).
  - **Minimal Track A acceptance β-stamp extension (NOT full
    A.MV) SHIPPED prep** commit `812a14f` (2026-04-30):
    `core/research/acceptance_helpers.py` adds
    `compute_beta_to_benchmark` + `build_estimated_beta_at_freeze`
    canonical-block builder per `bmv_schema_decision.md`
    §`estimated_beta_at_freeze` (8 unit tests).
    Schema invariant enforced: `used_by_b_mv=False` requires
    `reason_unused`. Defaults: `window=train_plus_validation`,
    `source=track_a_acceptance`, `used_by_b_mv=True`.
    **Pipeline wiring** (call site at the actual promotion path) is
    intentionally deferred to first cycle #06+ candidate that
    survives Track A acceptance — wiring with no consumer is dead
    code. Verified live 2026-05-02: 8 tests PASS, builder importable
    from `core.research.acceptance_helpers`. When wiring lands,
    promotion code calls
    `build_estimated_beta_at_freeze(strat_ret_d=..., spy_ret_d=...,
    qqq_ret_d=..., n_obs=..., computed_at=YYYY-MM-DD,
    computed_by="core/research/temporal_split_acceptance.py")` and
    writes returned dict under top-level `estimated_beta_at_freeze`
    key in candidate spec yaml.
- **NAV orthogonality tier** (single source of truth across script /
  dry-run plan / correlation memo / template, per audit-R2 + reviewer
  §3): `< 0.50` = `true_diversifier`; `0.50-0.70` = `partial_diversifier`;
  `0.70-0.85` = `warn_label_void` (cannot claim diversifier role);
  `≥ 0.85` = `reject_step5` (Step 5 reject). Mirrors Step 5 fleet
  correlation budget with one extra gate at 0.50; replaces the older
  flat 0.40 (factor-IC config) as structurally over-strict for
  long-only US-equity NAV correlation.
- **4-round self-audit methodology** (2026-04-30, forward-only):
  R1 factual / R2 logical / R3 actually-run-the-code / R4 boundary.
  Required for schema / threshold / new-pipeline / numerical-claim
  changes. Codified at `docs/checkpoints/20260430-self_audit_methodology.md`.
- **Generic NAV pair diagnostic runner** SHIPPED (2026-04-30 commit
  `4eb75bd`). `dev/scripts/correlation/run_pair_nav_correlation.py`
  takes any pair via `--candidate-a-id / --candidate-a-run-dirs /
  --candidate-b-id / --candidate-b-run-dirs / [--cell-labels] /
  [--min-overlap 60] / [--output-json]`. Legacy
  `rcmv1_cand2_realized_nav_correlation.py` reduced to thin wrapper
  preserving canonical
  `data/memos/20260430_rcmv1_cand2_realized_correlation.json` path.
  R3 numerical equivalence: 11/11 PASS vs pre-refactor snapshot
  (pooled pearson 0.898 / residual vs SPY 0.609 / vs QQQ 0.579 /
  reject_step5 — all identical to bit). R4 boundary: missing-bench-col
  / zero-var-bench / perfect-beta / n=0 / overlap < min all handled.
  **Design note**: pre-refactor CLAUDE.md spec listed
  `--benchmark-source` flag; R3 audit caught that a global benchmark
  source dir produces a cross-cell-benchmark regression (cell N's
  benchmark loaded from cell 0's window → zero overlap → false
  empty_diagnostic). Per-cell benchmark loading from each cell's own
  `benchmark_relative_paper.csv` is the correct architecture; no
  global flag needed. Verified live 2026-05-02 (legacy wrapper +
  generic CLI both reproduce headline numbers identically).
  Smoke pre-flight (2026-05-02): cycle #06+ candidate evidence pack
  §4.6 ready; manual script-edit at nominee time is no longer audit
  risk.
- **Track D** forward + first promotion: triggered when Track C
  produces a candidate that passes the new-framework acceptance + 2026
  sealed test (single-shot, gated on A.MV freeze-date rule).
- M17 / M18 unchanged.

**Framework Completion PRD** (`docs/20260421-prd_framework_completion.md`
v1.2) — shipped M0-M8 + M10 + M13 + M15 + M16 (see archive); open:

- [x] **M11a** paper-BT artifact-vs-replay consistency **(2026-04-24)**.
  Root cause: `_generate_orders` iterated `set(...)` whose order depends
  on per-process hash randomization (PYTHONHASHSEED). Cross-process
  runs of run_paper_candidate produced different fills under
  integer-share + binding cash → 18-65 bps monotone-signed drift
  (2022 RCMv1 78+/0−). Fix: `sorted(set(...))`. Post-fix drift = 0 bps
  across all 4 paper cells × 91-95 days. See
  `docs/memos/20260424-m11_paper_engine_parity_fix.md`.
- [x] **M11b** PaperTradingEngine vs BacktestEngine parity **(2026-04-24)**.
  Two semantic bugs in `run_day_daily`: (a) EOD equity used prev-day
  close instead of exec-day close (1-day stale), (b) signal_date was
  exec_date instead of exec_date−1BDay (fill_date off by +1 BDay).
  Fix: refactor signature into explicit `prev_close / exec_open /
  eod_close` dicts; correct signal_date. New tests for parity (1bps/day,
  5bps cumulative), fill_date contract, hash determinism. See same
  memo §2.1 + §6 for legacy-vs-new artifact semantics.
- [x] **M12** concentration gate real enforcement **(2026-04-27)**.
  Two-layer split per codex Round-5 audit (no default raise in
  BacktestEngine; metric exposure universal, enforcement opt-in):
  (a) `core/backtest/concentration_metrics.py` exposes
  `compute_concentration_metrics(weights_df)` and pure
  `validate_concentration(...)`; `BacktestEngine.run()` always
  populates `m12_top1_weight_max` / `m12_top3_weight_max` /
  `m12_n_dates_with_weights` in `BacktestResult.metrics`.
  (b) `acceptance_pack` Gate 7 enforces 0.40 / 0.70 ceilings when
  fresh backtest is available; skip-PASS only when no fresh backtest;
  fail-closed when fresh metrics unexpectedly missing. 20 regression
  tests across 3 files. See review log Round 5 + 6.
- [x] **M14** BacktestEngine NaN root-cause fix **(2026-04-24)**.
  Root cause: `price_row.get(sym, 0)` returns NaN (not default 0) when
  column exists with NaN value — panel union-merge across symbols with
  non-aligned calendars produces held-symbol NaN close days. Fix:
  fall back to `last_valid_close` (mirrors ghost-cleanup pattern).
  Eliminated all NaN-equity rows across 4 paper cells + unblocked
  10-30% previously-suppressed rebalance activity (+9.6% final NAV
  2022 Cand-2). 5 regression tests in `test_m14_nan_equity.py`. See
  `docs/memos/20260424-m14_nan_equity_fix.md` for root-cause / pre-post
  / residual.
- [x] **F01 + F02** acceptance threshold unification **(2026-04-28)**.
  Implemented per `docs/prd/20260428-acceptance_threshold_unification_prd.md`
  v1.1 (codex round-13 sign-off + round-14/15 GO + user explicit-go).
  Single source of truth = `core/config/schemas/acceptance.py`
  (`AcceptanceThresholds` with three nested submodels: `TierDThresholds`
  / `WalkForwardThresholds` / `FactorTierThresholds`); yaml at
  `config/acceptance.yaml`; loaded as `cfg.acceptance.*`. Step 1: schema
  + yaml + loader (commit 25246fa). Step 2: WindowAnalyzer wires
  `tier_d` (commit f498649) — class-level `TIER_D_*` constants removed.
  Step 3: factor_evaluator `_auto_tier` wires `factor_tiers` (commit
  58215d6) — 4 hardcoded IR cuts replaced. Step 4: dead `ValidationConfig`
  + `config/backtest.yaml::validation` block deleted. `acceptance_pack._THRESHOLDS`
  remains intentionally frozen per codex round-13 §"Decision 3" (no
  auto-sync; future divergence requires explicit versioned recalibration
  PRD).
- [ ] **M17** Realtime intraday live-feed infra — independent PRD
  `prd_live_feed.md` when validated best strategy exists.
- [ ] **M18** Cross-ticker DSL function expansion (P3, 0.3d each).
  Add `ratio / zscore / rank_cs / breakout` ONLY when a specific
  rule yaml demands them.

**Older TODO (data / intraday / research)**:
- [x] Provenance sidecar (trades_scanner + migration + BarStore API)
- [x] Factor guard (data_sensitivity config + apply_data_sensitivity_mask)
- [x] Notify module (base + wecom_bot + server_chan + stdout)
- [DEFERRED] Master report / diagnostics: show per-ticker data-epoch
      contribution (护栏 3 downstream — BarStore.attrs["provenance"]
      ready). Display layer NOT shipped per resident-quant decision
      2026-05-02: 0 immediate consumer (Trial 9 = 100% yfinance frontier),
      forward soak window not the time to change reporting surfaces.
      Activation triggers + ~2-hour impl sketch:
      `docs/memos/20260502-master_report_provenance_display_deferred.md`.
- [ ] fetch_data.py equivalent for universe + macro: currently one-off
      yfinance fetch in `scripts/`; productionize as part of pipeline
- [ ] validate_vs_yfinance 1m batching (yfinance 1m API limits 8d/req)
- [ ] Multi-timescale data contract (60m+30m formal, 15m+5m prototype)
- [ ] Multi-timescale signal protocol implementation
- [ ] Cross-TF validation / confirmation logic
- [ ] Execution scheduler (trade on lower TF triggers, not just 60m boundary)
- [ ] Multi-timescale leakage tests
- [ ] Per-timeframe IC analysis
- [ ] Combined vs single-TF performance comparison
- [ ] Multi-timescale intraday report
- [ ] Cost sensitivity at higher trading frequency
- [ ] Factor mining continued (new families, LLM candidates)
- [ ] Mining performance optimization

---
