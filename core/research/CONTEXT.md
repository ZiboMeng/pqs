<!-- PQS module CONTEXT.md — 由 CLAUDE.md 2026-05-19 reorg 拆出。
CLAUDE.md = context 入口,仅留项目级(不变量/纪律/架构/概括)。
本文件 = 本模块的历史/契约细节(content-preserving 搬迁,无删改)。
回指: ../../CLAUDE.md ; 索引见 CLAUDE.md 末「Module CONTEXT.md 索引」。 -->

# core/research/CONTEXT.md — module history / contract detail


## [Track A/B/C/D 基建史 + Concerns A/B/E + NAV orthogonality tier + 4-round self-audit 指针 + Generic NAV runner + Framework Completion PRD + Older TODO]

  unit suite 199/199 PASS.

  **Re-run / deprecation** (Option A.5-A.7, commits `f2997c0` + this):
  - simple_baseline_v1 backtest: UNAFFECTED (script uses yfinance
    direct, not BarStore parquet). CAGR +14.90% / Sharpe 0.82 /
    per-year MaxDD ≤25% confirmed identical. Paper soak continues.
  - trial9_diversifier_002 forward: TD001 (pre-fix init) dropped via
    `--overwrite` re-init; status=not_started; first observe will
    run with clean SPY data on next daily ritual. TD60 ~2026-08-06
    timeline unchanged.
  - cycle04-10 mining: **numerical claims DEPRECATED** (vs_spy
    aggregates, NAV correlation magnitudes, beta_spy_60d factor
    values, IC numbers). **Qualitative findings PRESERVED**:
    sibling-by-NAV is REINFORCED not invalidated (1-day phase shift
    dilutes Pearson, so true correlation > measured 0.85-0.95);
    TC ceiling argument unaffected (pure theory + literature);
    bundle-binding-across-cycles n=5 demonstration structural.
    R7 fail-SPY stop-rule verdicts on cycle10 stand.
  - RCMv1 + Cand-2 forward manifests: numerically deprecated;
    preserved as forensic evidence (both already aborted 2026-04-30
    on unrelated data revision drift).
  - Trial 9 v1 manifest: numerically deprecated; preserved as forensic.
  - K1 ship: UNAFFECTED (synthetic test data, no real SPY).
  - Roadmap v2 strategic decisions (D1 drop / D3 defer / signal seed
    library / K1+T1 path): UNAFFECTED (literature + theoretical).

  **New audit discipline added** (will commit to
  `[[feedback_audit_per_round_methodology]]`): bar-level data
  integrity smoke test (weekend-row scan + cross-symbol date
  intersection check) before every cycle. The off-by-one bug
  persisted across 5 cycles + 4 forward candidates because no test
  covered bar-label correctness; the test that caught it only existed
  AFTER v2.1.3 forward observation rewrite (commits `c3cefc1`..`4abc3c9`).

- **PEAD bundle Phase 1 — dual-track free-path SHIPPED**
  (2026-05-14 ✅, commits `7c23fc5` + `faae8f1`) — **first event-driven
  non-parametric signal in PQS history that clears Sharpe > 1.0 + MaxDD
  < 10%**. PRD `docs/prd/20260514-pead_bundle_phase1_prd.md`; closeout
  `docs/memos/20260514-pead_bundle_phase1_close.md`. Dual-track A/B
  hypothesis pre-registered.

  **Modules shipped**: `core/research/pead/{earnings_dates,
  sue_calculator, price_jump_signal}` + 53 unit tests (100% pass).
  Earnings-date extractor handles two non-obvious EDGAR PIT artifacts:
  (a) **comparative-data restatement** — same period_end re-appears
  under later fy values (filed 1 year later, gap=398d) so MUST groupby
  period_end + take MIN(filed_date), not just `get_chain_facts` latest;
  (b) **YTD-cumulative vs standalone-Q** — same (fy, fp, form) reports
  both YTD-cum EPS and standalone-Q EPS, separated only by `start` →
  `end` duration (60-100d for Q, 300-380d for FY). FY rows dropped for
  SUE to prevent lag-4 mismatch (full-year EPS compared against
  standalone-Q 4 rows back inflates SUE to 11σ false positive).

  **Path 1 SUE (fundamental surprise)** — 8/9 smoke trials beat SPY
  Sharpe 0.76 at 30bp realistic cost. Top trial 1 (SUE≥1.5σ hold=21
  top_n=10): Sharpe 1.055, CAGR 5.48%, MaxDD **-7.64%** (best-in-PQS
  for >1.0 Sharpe). Top trial 6 (hold=60): Sharpe 1.063, CAGR 10.39%,
  MaxDD -24%. Signal robust across threshold 1.0-2.0σ, hold 21-60d,
  top_n 5-20 (NOT a knife-edge hyperparameter).

  **Path 2 price-jump (AR proxy)** — 0/9 beat SPY. Top Sharpe 0.717.
  Confirms pre-registered hypothesis: AR alone too confounded
  (guidance / sector co-move / macro). Fundamental SUE captures real
  information-diffusion alpha; price-reaction alone is noise.

  **Track A acceptance 14/17** — all per-year MaxDD < 25%, all stress
  slices < 10%, 2x cost robust ($13965 final at 60bp), concentration
  / beta / no-leveraged-ETF all PASS. **NAV daily-return Pearson
  vs anchors**: alt-A +0.09 (very low), T1b +0.38, cycle11 Donchian
  +0.37 — all well below 0.85 sibling threshold. **Genuine
  differentiated alpha source.** Fails 3 gates: `validation_aggregate_
  excess_vs_spy/qqq` + `2025 vs_qqq`. Failing gates are CAGR-based,
  NOT signal-quality. PEAD alpha shape = defensive (low DD, lower
  CAGR than SPY in 2025 BULL year +13%).

  **Forward-init as evidence-only** (user explicit-go 2026-05-14)
  — candidate `pead_sue_trial1_evidence_v1`, role
  `evidence_only_observation` (NOT fleet), spec_hash
  `9a2ef503a241f407d2cf43c6b5a2ab3b12cdc2d16bcd35963e694000a8ca9d30`.
  start_date 2026-05-15. Standalone observation track (does NOT use
  main `core/research/forward` runner because event-driven SUE doesn't
  fit factor-composite schema; precedent = simple_baseline_v1).
  Init / observe scripts at `dev/scripts/pead/{init,observe}_pead_
  evidence.py`. TD000 baseline locked: Sharpe 1.056, CAGR 5.51%,
  MaxDD -7.64% (2017-01 to 2026-05-14, $16522 final equity, 287
  signals, 477 trades).

  **TD60 decision point ~2026-08-13** (1 week after Trial 9 v2 TD60
  on ~08-06):
  - GREEN: realized Sharpe > 0.8, MaxDD < 15%, NAV daily-return
    Pearson vs T1b < 0.70 → Phase 2 (paid 8-K real-announce-date
    feed ~$50-100/mo) eligible
  - YELLOW: Sharpe 0.4-0.8 or MaxDD 15-25% → continue TD90
  - RED: Sharpe < 0.4 or MaxDD > 25% → close evidence track

  **Known limitations** (PRD §7): filed_date is 10-Q submission date
  (typically 7-14d AFTER actual 8-K earnings call); 0-10d strongest
  drift portion partially missed. Phase 2 paid 8-K feed unlocks this.
  FY rows dropped for SUE → lose Q4 events (25% of earnings
  opportunities). 54-stock universe restricted to EDGAR cache.

  **Strategic implication**: PEAD is NOT a standalone-alpha winner
  (CAGR < SPY); it's a **defensive sleeve candidate for fleet
  allocation** (Phase C-PRD-2, deferred). Forward soak validates
  whether Bernard-Thomas 1989 signal hold in 2026 real-time data
  before justifying paid-data Phase 2 OR fleet-architecture build.

- **P0 governance + foundation fixes + cycle06/08 sealed-pass + priority
  1-9 ship** (2026-05-15 ✅) — large multi-part session driven by a
  codex audit. Key items:

  **P0.a — QQQ governance unification** (commit `966e177`): CLAUDE.md
  deprecated QQQ 2026-05-02 but config files still applied HARD QQQ
  gate. New `config/evaluation_policy.yaml` + `core/research/
  evaluation_policy.py` runtime-override layer demotes all QQQ
  kill_candidate gates to diagnostic_only (v1/v2/v3 yaml preserved
  verbatim under immutability). `temporal_split_acceptance` +
  `mining/evaluator` read the policy.

  **P0.b + P0.b.4 — full-universe data repair**: completeness gate
  `core/data/data_completeness_gate.py` + `core/data/data_repair.py`
  (yfinance split-aware reverse-adjust). Repaired 12 priority symbols
  then 12 more (A/APD/AXP/BKNG/DG/KLAC/LRCX/SCHD/SOXL/TKO/TRGP/USMV);
  META wrong-ticker purge+refetch (was META Financial Group pre-
  2022-06-09, not Meta Platforms). Post-repair 81/81 universe
  completeness PASS. 1675+ rows filled.

  **P0 CRITICAL — MaxDD acceptance gate sign bug** (commit `1e0d81e`):
  `temporal_split_acceptance` MaxDD gates compared a NEGATIVE-stored
  maxdd against a POSITIVE threshold with `<=` → always True → the
  gate (per-year + stress-slice + role) NEVER fired. Every Track A
  "PASS" 2026-05-14/15 had a dead MaxDD gate. Fixed: `abs(maxdd)`
  comparison at 3 sites + 4 regression tests. Re-eval ALL candidates:
  cycle06 1/3, cycle07a 0/3, cycle08 1/3, cycle12 0/3 PASS.

  **executable_universe.yaml SoT** (commit `[B]`): cycle yamls'
  `universe_extension` blocks were stale-copy from cycle08 (claimed
  59; actual mining universe = 79). New `config/executable_universe.yaml`
  is the canonical 79-symbol executable-universe declaration + drop
  reasons; separates "data-store completeness (81/81)" from
  "executable mining universe (79)".

  **Sealed 2026 single-shot test — 2/2 PASS** (commit `60de4ee`):
  per corrected pipeline ordering (sealed gate BEFORE forward
  observation — a gate must precede what it gates). cycle08_3f40e3f4ed1a
  (sealed vs_spy +14.83%, Sharpe 4.10, MaxDD -7.66%) + cycle06_31af04cf2ff9
  (vs_spy +24.55%, Sharpe 4.00, MaxDD -6.62%). Window 2026-01-01..05-14.
  **The 2026 single-shot holdout for split `alternating_regime_holdout_v1`
  is now CONSUMED** — re-testing improved candidates needs split_name
  bump. Sharpe ~4 is a 4.5-month short-window figure (noisy/optimistic
  — not steady-state). Ledger has cycle08 as the event marker (script
  looped record_eval; B1 correctly blocked the 2nd; cycle06 result in
  the memo + sealed_2026_eval.json as part of the same single event).

  **Priority 1-9 shipped**: Family R chart-pattern factors (10, commit
  `f4a46a1`) + Family S regime-ML factors (3) → RESEARCH_FACTORS
  162→175; multi-TF cascade decision module (`core/research/
  multi_tf_cascade.py`); 130/30 long-short config schema
  (`core/research/long_short_config.py`, schema-only — execution
  wiring deferred, user explicit-go for the invariant relaxation);
  universe extension yaml + inverse-ETF cap grid; cycle12 mining
  (200 trials, 93 archived, Family R golden_cross_score in top-1 —
  but 0/3 Track A post-MaxDD-fix); PEAD cost sensitivity (Trial 1
  ROBUST at 60bp); LLM mining framework (`core/research/llm_mining.py`,
  framework-only). cycle12 used FAMILIES_OHLCV_ONLY (12 families) —
  fundamental/sector/macro families need separate compute paths.

- **ML methodology supplementary-PRD redo + D1-D3 data-cleanliness**
  (2026-05-16 → 2026-05-17 ✅, **4 landmarks — Phase 2/3 ML negative
  conclusions were largely methodological false negatives; all
  config-scoped research signals, NOT deployable**) — lineage
  `ml-method-redo-2026-05-16`. PRD
  `docs/prd/20260516-ml_methodology_supplementary_prd.md`; SoT
  `docs/memos/20260516-ml_methodology_literature_review.md`; closeout
  `docs/memos/20260516-ml_methodology_redo_closeout.md` (§7 = D3).
  Driven by user suspicion that prior Phase 2/3 "chart-structure ML
  is useless" verdicts were methodological false negatives. Rebuilt
  the full ML pipeline on literature-proven protocol; 8 R-phases +
  C1-C5 closeout + D1-D3 data fixes. G1 3326/0. Commits `2727da8`
  (R0-R3+R5 build) → `783a905` (R2.5 landmark) → `1d7ddc0` (R4
  real-weight + audit-fix) → `e1c820e` (C1-C5 closeout) → `9f2c8d4`
  (D1+D2 cleanliness + BarStore NaN-vol fix) → `09e1ce6` (D3 clean
  re-run).
  - **Landmark① R2.5**: structure-as-factor has positive increment;
    ΔIC +0.006, anti-autocorrelation clean p=0.0004 (C1) —
    directionally OVERTURNS P2A "no increment" false negative.
  - **Landmark② R4**: SSL-pretrain chart representation beats single
    momentum factor (OOS IC 0.050 > 0.038) — but ONLY with REAL
    pretrained weights; audit caught a fresh-init "phantom pretrain"
    that flipped the verdict, fixed by persisting `pretrain_mae.pt`.
  - **Landmark③ C2**: chart-native members are additive in ensemble
    (stack IC 0.083 >> single-momentum 0.045).
  - **Landmark④ C3 (re-validated by D3)**: on ~1000-symbol universe
    chart-native beats momentum baseline. Dirty-data headline (gaf
    IC +0.128 / vs_mom +0.165, n=5,977) was a thin-sample artifact;
    D3 clean re-run (n=116,820, ~20×) corrects to gaf IC 0.045 /
    vs_mom +0.055, mae IC 0.048 / vs_mom +0.058 (DSR placeholder-N →
    optimistic, NOT an evidence anchor; robust = vs-momentum IC
    positive — see docs/memos/20260517-dsr_placeholder_n_boundary_memo.md).
    **Direction survives, magnitude was dirty-data inflation — honestly
    downscaled.**
  - **BarStore core fix (D2)**: `_apply_forward_splits` volume cast
    made NaN-safe (clean data bit-identical, zero regression;
    NaN-vol symbol keeps float64 instead of IntCastingNaNError).
  - **Data cleanliness (D1+D2)**: expanded_v2 was 32% clean →
    audited + yfinance-backfilled all 1015 symbols to 100% clean.
    Honest finding: Stooq free CSV now apikey/captcha-gated; 60
    delisted names unfillable by survivor-biased free sources
    (consistent with C5 survivorship).
  - **Audit discipline validated 4×**: caught + honestly corrected
    P2A overclaim, R4 fresh-init phantom, R2.5 exact-zero (factor
    not actually added), BarStore NaN bug. closeout §6
    `pending_data_cleanliness_validation` marker CLEARed by D3.
  - **Scope/caveats (no overclaim)**: ALL config-scoped (this factor
    set / this prep / 21d / this universe / stride-10); research
    signal-quality conclusions, NOT deployable candidates (Track A /
    sealed / forward funnel NOT walked); from-scratch CNN loses to
    pretrain→probe (stable across dirty/clean); gaf_tree standalone
    still config-scoped. **sealed 2026 NEVER read** throughout.
    Deferred (need user explicit-go): R5 real-base end-to-end eval,
    from-scratch full retrain, survivorship as-of reconstruction
    (structurally infeasible — no delisting/historical-constituent
    DB; honestly recorded, not faked).
