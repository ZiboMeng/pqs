# docs/ Index

Navigation across 58 docs by category. **Existing files** are kept flat
(no subdirectories) so cross-references stay intact; this index is the
fast path. **New files going forward** land in the per-category subdirs
defined at the bottom of this file. Within each category section,
**newest first**.

If you want chronological order, sort by filename — the
`YYYYMMDD-` prefix makes that trivial.

---

## 1. PRDs (specs, mandates, governing docs) — 21

Prescriptive documents that define what to build / what to constrain.

- [prd/20260429-temporal_split_holdout_discipline_prd.md](prd/20260429-temporal_split_holdout_discipline_prd.md) — **v1.1 SHIPPED 2026-04-29 ✅** Track A — Temporal Split & Holdout Discipline (codex round 19 + 20 PRD-level approved). `config/temporal_split.yaml` alternating-year split (train 2009-2017+2020/2022/2024 / validation 2018/2019/2021/2023/2025 / sealed 2026 single-shot). 9 modifications (M1-M9) + 4 codex R20 boundaries (B1 split-level sealed lock / B2 Track A owns split_sha256 / B3 yaml-swap behavior test / B4 RCMv1/Cand-2 wording). Role-locked gates (core 2025 hard gate; diversifier compensating constraint). M5+B1 sealed-eval ledger. M9 manual + auto regime tag with tiered policy. M4 forward-return label boundary purge. M3 504d factor lookback cap. C5 same-spec-different-role guard. F1/F2 fork criteria locked pre-smoke at `memos/20260429-track_a_f1_f2_fork_criteria.md`. Implementation log `memos/20260429-track_a_implementation_log.md`. 8 commits across 8 modules; 126 unit tests. Lineage `temporal-split-holdout-v1-2026-04-29`.
- [prd/20260428-config_universe_snapshot_hardening_prd.md](prd/20260428-config_universe_snapshot_hardening_prd.md) — **SHIPPED 2026-04-29 ✅ — codex round 19 + 20 closed; F line officially functional**. Codex queue priority **F** — config/universe snapshot hardening (codex round-12 P1 first step). Distinguishes **config drift** from **data revision**: 5 config sources hashed at forward init (S1 universe / S2 factor_registry contract / S3 research_mask / S4 risk / S5 system) → `ConfigSnapshot` pydantic submodel + `ConfigDriftEvent` class (separate from existing `DataRevisionEvent`). Severity policy: universe / factor_registry / risk = halt; research_mask / system = warn. Lazy-migration boundary mirrors v2.1.3 `legacy_unhashed_inputs` (pre-PRD-F TD001/2/3 manifests stay valid; revalidate skips drift detection + INFO-logs once per process per candidate). Opt-in backfill at `dev/scripts/forward/backfill_config_snapshot.py` for current 2 candidates (idempotent without `--force`; `--dry-run` previews). 5-step impl shipped on main: step 1 `1952e44` (schema), step 2 `c28c969` (init wiring), step 3 `368536d` (revalidate + observe wiring), audit fixes `abc4425` (extra=forbid + terminal-status halt), step 4 `ad6491e` (backfill utility + `observe(config_dir=...)` for hermetic-test contract symmetry). Acceptance 13/13 ✅; full unit suite 1850 passed. Lineage tag `config-snapshot-hardening-v1-2026-04-28`.
- [prd/20260428-candidate_fleet_allocator_prd.md](prd/20260428-candidate_fleet_allocator_prd.md) — **v1.1 codex round-14 APPROVED at PRD level** (2026-04-28). Codex round-12 priority #1-missing-macro. Minimum allocator: 6 capabilities (capital split / pairwise corr budget / overlap throttle / core-vs-satellite / DD throttling / removal+parking rules); new `core/fleet/` module + `config/fleet.yaml` + fleet manifest (parallel to forward manifest pattern). NO new alpha source; NO substitute for per-candidate acceptance; NO real-broker; v1 is regime-agnostic. 8-step implementation; 16 acceptance criteria; 4 open questions for codex/user (core role cap consistency under N_core ≥ 2 / benchmark-relative vs absolute DD throttle / daily vs weekly cadence / shadow mode for first 10 TDs). Implementation gated on user explicit-go + codex sign-off. Lineage tag `candidate-fleet-allocator-v1-2026-04-28`.
- [prd/20260428-acceptance_threshold_unification_prd.md](prd/20260428-acceptance_threshold_unification_prd.md) — **v1.1 SHIPPED** (2026-04-28). 4-step implementation done on main: step 1 schema+yaml+loader (`25246fa`), step 2 WindowAnalyzer (`f498649`), step 3 factor_evaluator (`58215d6`), step 4 ValidationConfig delete (next commit). Closes R4 F01 + F02 per codex round-11 priority #2 + round-13 sign-off + round-14/15 GO. `core/config/schemas/acceptance.py::AcceptanceThresholds` with three nested submodels (`TierDThresholds` / `WalkForwardThresholds` / `FactorTierThresholds`); yaml at `config/acceptance.yaml`; loaded as `cfg.acceptance.*`. Dead `ValidationConfig` + `config/backtest.yaml::validation` block removed. `acceptance_pack._THRESHOLDS` intentionally frozen (codex round-13 §"Decision 3"). NO numeric value changes during relocation. Lineage tag `acceptance-threshold-unification-2026-04-28`.
- [prd/20260428-ralph_audit_loop_prd.md](prd/20260428-ralph_audit_loop_prd.md) — 10-round ralph-loop audit (3 deep on forward evidence v2.1.3 + 7 codebase-wide). Hard rules force live e2e execution + reverse-validation + real-data fixtures + doc-vs-code reconciliation + zero-changelog README. Closes the failure modes that let 2 codex Round-10 blockers slip past 2 prior self-audits. Driver: `dev/scripts/loop/start_ralph_audit_loop.sh`. Lineage `ralph-audit-2026-04-28`; promise `RALPHAUDIT10DONE` emitted 2026-04-28 at cycle close.
- [prd/20260427-forward_evidence_hardening_prd.md](prd/20260427-forward_evidence_hardening_prd.md) — **SHIPPED v2.1.3** Forward evidence hardening: 3 input-scope hashes (signal_input / execution_nav / benchmark) + bar_hash rollup, materiality-based E1-E5 escalation (NAV ≥10 bps / checkpoint drift ≥25 bps / raw drift ≥0.50%), TD001 lazy migration boundary, window-scoped source-layer classification, requires_data_review halt contract, per-cell digest + materiality_anchor_values storage. v2.1.3 closes codex Round-10 blockers (real trading-day window resolution + signal-scope empty-digest fail-close).
- [prd/20260426-forward_oos_runner_prd.md](prd/20260426-forward_oos_runner_prd.md) — Forward OOS runner + 10/20/40/60 TD checkpoint pipeline. 5-round execution split. R-fwd-1 shipped; R-fwd-2/3 design now superseded/extended by `prd/20260427-forward_evidence_hardening_prd.md`.
- [prd/20260425-oos_mvp_ralph_loop_execution.md](prd/20260425-oos_mvp_ralph_loop_execution.md) — OOS MVP execution PRD: 7-round split (R1 schema+skeleton, R2 real run, R3 M12 report, R4 watch exposure, R5 forward schema-only, R6 smoke+negative sim, R7 docs+`OOSMVPDONE`) derived from PRD v3; HARD invariants, lineage `oos-mvp-2026-04-25`, ralph-loop launcher at `dev/scripts/loop/start_oos_mvp_loop.sh`
- [prd/20260425-oos_validation_framework_codex_v3.md](prd/20260425-oos_validation_framework_codex_v3.md) — OOS validation framework v3 final pre-MVP review; robustness naming, manual-review concentration tier, evidence_class, data_integrity_snapshot, forward manifest schema
- [prd/20260425-oos_validation_framework_codex_v2.md](prd/20260425-oos_validation_framework_codex_v2.md) — Post-data-integrity OOS validation framework v2; Claude/Codex reviewed, artifact-first MVP, current candidates' historical holdout explicitly pseudo-OOS
- [20260424-prd_phase_e_post_cand2.md](20260424-prd_phase_e_post_cand2.md) — Phase E-post + Candidate-2 cross-regime parallel paper plan
- [20260424-prd_phase_e_execution.md](20260424-prd_phase_e_execution.md) — Phase E execution PRD (governance + paper layer R1-R14)
- [20260424-prd_phase_e_governance_and_paper.md](20260424-prd_phase_e_governance_and_paper.md) — Phase E charter (S0/S1/S2/S5 state machine spec)
- [20260424-prd_research_to_paper_promote_standard.md](20260424-prd_research_to_paper_promote_standard.md) — Research → paper promotion contract
- [20260424-prd_research_composite_miner_v1.md](20260424-prd_research_composite_miner_v1.md) — RCMv1 PRD (orthogonal feature mining)
- [20260424-prd_layered_quant_architecture.md](20260424-prd_layered_quant_architecture.md) — Layered architecture PRD (research / paper / production)
- [20260424-prd_codebase_audit_3round.md](20260424-prd_codebase_audit_3round.md) — Codebase audit PRD (audit-v1 + audit-v2 lineages)
- [20260424-prd_docs_audit_3round.md](20260424-prd_docs_audit_3round.md) — 3-round code + docs audit PRD
- [20260423-prd_research_feature_engineering_and_expanded_mining.md](20260423-prd_research_feature_engineering_and_expanded_mining.md) — Feat-v1 feature engineering + expanded mining PRD
- [20260421-prd_framework_completion.md](20260421-prd_framework_completion.md) — Framework completion PRD (M0-M18 milestones)
- [20260421-prd_deep_mining_50round.md](20260421-prd_deep_mining_50round.md) — Deep Mining 50-round PRD (7 tracks)
- [20260421-prd_universe_expanded_mining.md](20260421-prd_universe_expanded_mining.md) — Universe-expanded mining PRD (R29-R35 phase)
- [20260420-prd_intraday_mining_loop.md](20260420-prd_intraday_mining_loop.md) — Intraday mining loop PRD
- [20260420-prd_llm_factor_mining.md](20260420-prd_llm_factor_mining.md) — LLM factor mining PRD (R1-R28 phase)

## 2. Final synthesis docs (terminal stage reports) — 5

End-of-phase wrap-ups. Read these to catch up quickly on a completed phase.

- [20260424-phase_e_post_cand2_final_synthesis.md](20260424-phase_e_post_cand2_final_synthesis.md) — Phase E-post + Candidate-2 8-round wrap-up
- [20260424-phase_e_final_synthesis.md](20260424-phase_e_final_synthesis.md) — Phase E governance + paper layer 14-round wrap-up
- [20260424-rcm_v1_final_synthesis.md](20260424-rcm_v1_final_synthesis.md) — RCMv1 20-round wrap-up
- [20260424-docs_audit_3round_final_synthesis.md](20260424-docs_audit_3round_final_synthesis.md) — 3-round code + docs audit wrap-up
- [20260422-deep_mining_50round_final_synthesis.md](20260422-deep_mining_50round_final_synthesis.md) — Deep Mining 50-round wrap-up

## 3. Parallel paper checkpoint memos — 9

Sequential checkpoint analysis of `rcm_v1_defensive_composite_01` +
`candidate_2_orthogonal_01` paper runs across two market regimes. Read
in order; each builds on the previous.

**2022-H2 bear+recovery window (2022-08-26 → 2022-12-15)**:
- [20260424-parallel_paper_2022h2_checkpoint_75d.md](20260424-parallel_paper_2022h2_checkpoint_75d.md) — TD75 cross-regime synthesis (terminal)
- [20260424-parallel_paper_2022h2_checkpoint_60d.md](20260424-parallel_paper_2022h2_checkpoint_60d.md) — TD60 decision-readiness
- [20260424-parallel_paper_2022h2_checkpoint_40d.md](20260424-parallel_paper_2022h2_checkpoint_40d.md) — TD40 bear-bottom stress
- [20260424-parallel_paper_2022h2_checkpoint_20d.md](20260424-parallel_paper_2022h2_checkpoint_20d.md) — TD20 early behavior
- [20260424-parallel_paper_2022h2_checkpoint_10d.md](20260424-parallel_paper_2022h2_checkpoint_10d.md) — TD10 operational sanity

**2024 up-tape window (2024-01-02 → 2024-04-19)**:
- [20260424-parallel_paper_checkpoint_60d.md](20260424-parallel_paper_checkpoint_60d.md) — TD60 (note: cutoff was index-day-60 = real TD ~50; kept for historical reference)
- [20260424-parallel_paper_checkpoint_40d.md](20260424-parallel_paper_checkpoint_40d.md) — TD40
- [20260424-parallel_paper_checkpoint_20d.md](20260424-parallel_paper_checkpoint_20d.md) — TD20
- [20260424-parallel_paper_checkpoint_10d.md](20260424-parallel_paper_checkpoint_10d.md) — TD10 (initial)

## 4. Decision / drill / proposal / attribution memos — 18

- [memos/20260429-post_audit_strategic_roadmap.md](memos/20260429-post_audit_strategic_roadmap.md) — **NEW** v3 — Post-audit strategic roadmap. 4-track sequencing (A Temporal Split → C real mining → D first promotion; B Fleet step 1-4 parallel). Synthesizes 2 external auditors + Claude quant judgment + codex round 19 + 20. v1→v2 added M4-M9 discipline modifications (codex/auditor consensus + Claude additions); v2→v3 marks Track A PRD APPROVED + implementation begun. 12-item Track A PRD checklist at §11.
- [memos/20260429-track_a_implementation_log.md](memos/20260429-track_a_implementation_log.md) — **NEW** Track A shipping log (8 commits, 8 modules, 126 tests). Maps PRD §11 acceptance #1-#18 to test files. Lists items intentionally deferred (Track C real mining, F1/F2 PRDs post-smoke, factor registry hook, ConfigSnapshot extension to v2).
- [memos/20260429-track_a_f1_f2_fork_criteria.md](memos/20260429-track_a_f1_f2_fork_criteria.md) — **NEW** F1/F2 fork criteria one-page locked pre-smoke. F1 trigger (IR_p90>0.15 AND ≥20%>0.10) → gate recalibration PRD with floor max(0.10, IR_p75). F2 trigger (IR_p90<0.05 AND IR_p50<-0.05) → new factor family PRD. Else → escalate to user explicit decision. Anti-anchoring discipline: smoke is single-shot, lineage_tag fixed, no narrative override.
- [memos/20260430-rcmv1_cand2_realized_correlation.md](memos/20260430-rcmv1_cand2_realized_correlation.md) — **NEW** Realized NAV correlation finding: pooled Pearson 0.898 over 154 honest post-step3b paper days (Step 5 reject). Residual decomposition: vs SPY 0.609 / vs QQQ 0.579, both residual Sharpes positive. Classification "mixed" — ~30% shared market beta + ~60% shared alpha. Cand-2 "orthogonal" claim retracted at NAV level (still valid at factor-IC level). Fleet-of-two equal-weight does NOT diversify; both candidates reclassified as legacy decay verification only. Track C must find candidate differing on BOTH beta exposure AND residual alpha.
- [memos/20260430-track_c_dry_run_plan.md](memos/20260430-track_c_dry_run_plan.md) — **NEW** Track C controlled mining cycle #01 plan (renamed from "dry-run" per reviewer). Pre-registered immutable criteria yaml, NAV-orthogonality tier (true_diversifier <0.50 / partial 0.50-0.70 / warn_label_void 0.70-0.85 / reject ≥0.85), action map for 0-candidate / partial / clean outcomes. Mining compute can run concurrent with E.MV signoff; nomination gated on E.MV §4.6+§4.7 + B.MV + A.MV.
- [memos/20260430-concerns_abE_proposed_solutions.md](memos/20260430-concerns_abE_proposed_solutions.md) — **NEW** Pre-Track-C concerns A/B/E proposed solutions. **E.MV ✅ shipped** in template v1.1 (commit 01d2950) — §4.6 NAV-orthogonality + §4.7 economic-assumption flags F1-F6. **A.MV proposal**: sealed_eval freeze-date HARD + market_path_preobserved SOFT (replaces lineage_family abstraction per reviewer). **B.MV proposal**: dispatch on `decay_classification.label` for legacy SKIP + beta-adjusted T4 reading nested `estimated_beta_at_freeze.beta_to_spy`. Q12 disposition (operator pushback on raw -10% fallback): SKIP-on-decay architecture, not WRONG_FALLBACK.
- [memos/20260430-bmv_schema_decision.md](memos/20260430-bmv_schema_decision.md) — **NEW** Canonical schema contract for B.MV runner before implementation. Defines `decay_classification` (top-level dict on spec yaml) + `estimated_beta_at_freeze` (nested dict on spec yaml). Eliminates flat-vs-nested + machine-readable-vs-string drift between proposal pseudocode and yaml annotations. Triggered by R35 auditor §2.2-2.3.
- [checkpoints/20260430-self_audit_methodology.md](checkpoints/20260430-self_audit_methodology.md) — **NEW** 4-round self-audit methodology forward-only since 2026-04-30. R1 factual (numbers, paths) / R2 logical (do thresholds/policies make sense) / R3 actually-run-the-code (re-execute, compare output to expected, no runtime bugs) / R4 boundary (n=0/1, zero-variance, missing fields). Required for schema, threshold, new-pipeline, numerical-claim changes. R3 sub-cycle: when a real bug surfaces, fix and verify production output un-regresses in same audit.

One-off, candidate-specific or feature-specific decision documents.

- [memos/20260425-m12_review_decision.md](memos/20260425-m12_review_decision.md) — **NEW** Post-MVP M12 audit fix: thin-data gate redefined from binary (any-thin-history × full weight) to weighted (Σ share[s] × thin_data_pct[s]). Cand-2 unfrozen (binary 28.48% / weighted 5.19% → warning); RCMv1 still frozen (binary 56.86% / weighted 14.97% — real signal). 4 new regression tests (A divergence / B Cand-2 demote / C RCMv1 keep / percent-scale). Closeout memo §3 numbers reflect pre-fix state; this memo supersedes them.
- [memos/20260426-research_layer_partial_unfreeze.md](memos/20260426-research_layer_partial_unfreeze.md) — **NEW** Partial unfreeze authorization for Research Layer (mining + factor research ONLY). Tagline: "Research unfreezes for stockpiling, not for shipping." 4 guards: G1 ≤1 nominee per mining lineage / G2 pre-registered promotion_criteria.yaml split into hard (must-pass) + report-only / G3 current pair displacement guard (no auto-replacement rights) / G4 panel cutoff ≤ 2024-12-31 HARD. 0-nominee is a valid outcome. Paper slot opening requires either 10TD checkpoint OR a committed authorization memo (chat-only NOT sufficient). Valid for ONE research cycle; auto re-freeze on cycle end (nominee promoted OR pipeline rejected/archived). Universe / Candidate-3-direct-S2 / current pair frozen specs / new PRODUCTION_FACTORS / new data tier / config edits all stay frozen.
- [memos/20260426-research-cycle-2026-04-26-01_close.md](memos/20260426-research-cycle-2026-04-26-01_close.md) — **NEW** Research cycle 2026-04-26 #01 closeout: **0 nominee**. 200-trial TPE mining (78 syms × 2007-2023, panel cutoff 2023-12-31, BRK-B dropped) produced top trial `62445bdc62ae` = `beta_spy_60d × amihud_20d × mom_126d` with IC_IR=1.04 + 4/4 walk-forward folds positive, but FAILED G2.A on `watchlist_total_share=39.50% > 30% ceiling` (gate worked as intended — exactly the failure mode the strict ceiling was designed to prevent). Per criteria immutability, no retroactive softening: cycle closes 0-nominee. Surfaces a realized-β anomaly (composite naming `beta_spy_60d` lands portfolio at β≈1.8, NOT defensive — feature-sign-convention question for next cycle). 2024 pseudo-OOS: +28% / Sharpe 0.89 / **MaxDD −29%** (violates 15-20% target). Research-mining workstream auto re-frozen at this boundary; forward-OOS observation of RCMv1 + Cand-2 unaffected.
- [memos/20260426-oos_parking_lot.md](memos/20260426-oos_parking_lot.md) — OOS framework parking lot: items considered and explicitly deferred during the workstream. P-001: pre-registered historical holdout reconstruction (proposal: re-construct candidates on ≤2024 data, test on 2024-2026 as synthetic forward; deferred 2026-04-26 because still pseudo-OOS not real OOS, and current R2+M12+watch discipline stack is sufficient historical layer; re-trigger at post-10TD or next-batch candidate construction with true pre-registration).
- [memos/20260425-oos_mvp_close.md](memos/20260425-oos_mvp_close.md) — OOS MVP R1-R7 closeout: pseudo-OOS robustness eval done, NOT OOS validated (per PRD v3 §1.1+§1.3 framing). Both candidates produced full artifact set; pre-audit M12 numbers say both frozen due to thin_data_share extreme (superseded by m12_review_decision memo above for Cand-2). R5 forward manifest schema shipped, NO runner per PRD v3 §B. 63 regression tests across 6 commits, pytest 1617 → 1680 (drift fully explained). OOS-framework workstream auto re-frozen at OOSMVPDONE.
- [memos/20260425-oos_framework_unfreeze.md](memos/20260425-oos_framework_unfreeze.md) — Explicit unfreeze of OOS-framework workstream for MVP scope only (R1-R7 per execution PRD); narrows round-3 close freeze item "No OOS-framework work"; lists authorized write paths + unchanged frozen items + halt/reauth conditions + auto re-freeze at `OOSMVPDONE`
- [memos/20260425-data_integrity_round3_close.md](memos/20260425-data_integrity_round3_close.md) — Round-3 closeout: 6 steps shipped, NAV magnitude shifts table per cell, parking-lot follow-ups (TJX split-cross audit, universe hardcode→config, factor IR refresh, watch-list integration, xpass stability), standing freeze list (universe / mining / Candidate-3 / OOS / spec changes) — OOS item subsequently narrowed by unfreeze memo above
- [memos/20260425-data_integrity_round3_step4_complete.md](memos/20260425-data_integrity_round3_step4_complete.md) — Step 4: pytest 1617 pass / baseline refreshed / 4 paper cells re-run on rebuilt store (drift=0 bps × 4 cells, M11 parity holds); NAVs −4.9% / −18.0% / −14.7% / **−40.7%** vs pre-step3b (largest single re-baseline this round); +1d offset Sat pad rows + mixed-scale alternation eliminated; QQQ test fix (rebuild union 4 yaml fields + BRK-B stale parquet quarantine cleanup)
- [memos/20260425-data_integrity_round3_step3b_complete.md](memos/20260425-data_integrity_round3_step3b_complete.md) — **NEW** Step 3b: full universe daily parquet rebuild from polygon 1m (78 written + 1 BRK-B drop); 3 sidecars persisted (manifest / incomplete_days / data_quality_watch); +1d offset bug eliminated; 18 sym watch list flagged (BKNG/CMG/TKO/TT/SOXL/BRK-B + 12 auto); known issue: TJX polygon 1m at 2017-04-05 split missing one adjustment, documented as out-of-scope
- [memos/20260425-data_integrity_round3_step3a_rev_delta.md](memos/20260425-data_integrity_round3_step3a_rev_delta.md) — Step 3a-rev: two-tier N_min (350/300) + BRK-B drop. Quarantine 9.84% → 5.57% (-43.4%); thin_data tier recovers 6,748 rows; 2022-H2 q_pct 7.31→4.59%, 2024 q_pct 13.36→7.30%
- [memos/20260425-data_integrity_round3_step3a_audit.md](memos/20260425-data_integrity_round3_step3a_audit.md) — Step 3a: read-only dry run audit, 8-group analysis, 6 stop signals surfaced (BRK-B no-1m / N_min too strict / BKNG/CMG/TKO/TT chronic / SOXL anomaly / 2024 window 13% q / partial count low)
- [memos/20260425-data_integrity_round3_implementation_note.md](memos/20260425-data_integrity_round3_implementation_note.md) — Round-3 implementation contract (1-page checklist): canonical source = polygon 1m, daily aggregation contract (label = real ET trading day, close = 15:59 ET 1m close, OHLCV regular session only, raw stored + read-time cascade), incomplete-1m day policy (partial-day whitelist + non-whitelist quarantine, NO silent fallback), splits.parquet sub-tasks same-batch ship, post-fix rerun + headline-4 + all-repo date-reference sweep, 3 regression assertions, freeze unchanged
- [memos/20260425-data_integrity_round2_diagnosis.md](memos/20260425-data_integrity_round2_diagnosis.md) — Round-2 diagnosis: collapses round-1's "two sub-issues" into ONE root cause (multi-source ingest cascade, A=yfinance auto_adjust=True / label real-date vs B=polygon 1m / label real+1day, never reconciled). 97% of BS daily rows classify into A or B−1d. §2.4 polygon 1m verified clean → **E recommended**; B fallback only
- [memos/20260425-data_integrity_scoping.md](memos/20260425-data_integrity_scoping.md) — Round-1 scoping for the data-integrity workstream; splits into split-adjustment consistency (3 systemic + 5 episodic affected symbols, 16 clean / 24 universe) + date-label integrity (24/24 universe symbols Monday→Saturday systemic shift, ~50/yr); 4 hypotheses + 5/4 repair options each; 6 decisions deferred to user. **Partially superseded by round-2 diagnosis above (single root cause unification).**
- [memos/20260424-m11_paper_engine_parity_fix.md](memos/20260424-m11_paper_engine_parity_fix.md) — M11a (set-iteration hash-randomization in BacktestEngine) + M11b (run_day_daily prev/exec/eod-close + signal_date semantics) fixed; post-fix paper-vs-replay drift = 0 bps across all 4 cells; retracts M14 memo §5.1 Saturday-row claim (misdated Monday data, deferred to BarStore workstream)
- [memos/20260424-m14_nan_equity_fix.md](memos/20260424-m14_nan_equity_fix.md) — M14 root-cause (`price_row.get` NaN-vs-default bug) + fix + pre/post across 4 paper cells (NaN-equity days → 0) + 10-30% unblocked rebalances + residual paper-vs-replay execution-state drift attribution
- [memos/20260424-cand2_drift_attribution.md](memos/20260424-cand2_drift_attribution.md) — Cand-2 paper-vs-replay drift structurally attributed to M14 NaN, not execution noise; overturns TD60/TD75 narrative; M14 fix promoted to first-priority blocker
- [20260424-rcmv1_clone_revoke_drill_memo.md](20260424-rcmv1_clone_revoke_drill_memo.md) — Phase E-post R3 revoke drill on rcm_v1 clones (3 paths exercised)
- [20260424-candidate_2_decision_memo.md](20260424-candidate_2_decision_memo.md) — Candidate-2 construction + S0→S1 decision rationale
- [20260424-rcm_v1_s1_candidate_memo.md](20260424-rcm_v1_s1_candidate_memo.md) — RCMv1 S1 candidate promotion memo
- [20260422-universe_expansion_proposal_v3.md](20260422-universe_expansion_proposal_v3.md) — R38 universe extension proposal (deep-mining output)
- [20260422-production_factor_promote_proposal_weak_market_and_gated_mom.md](20260422-production_factor_promote_proposal_weak_market_and_gated_mom.md) — R7/R10 factor promotion proposal

## 5. Reports / findings / baselines — 8

Snapshot evidence: blocker reports, performance findings, baseline runs.

- [20260423-feat_v1_expanded_final_report.md](20260423-feat_v1_expanded_final_report.md) — Feat-v1 expanded mining final report
- [20260423-feat_v1_r39_blocker.md](20260423-feat_v1_r39_blocker.md) — Feat-v1 R39 blocker write-up
- [20260423-feat_v1_panel_sanity.md](20260423-feat_v1_panel_sanity.md) — Feat-v1 panel sanity check
- [20260422-xgboost_weight_model_R46_findings.md](20260422-xgboost_weight_model_R46_findings.md) — Track E XGB weight-model PARK verdict
- [20260421-transformer_research_phase1_findings.md](20260421-transformer_research_phase1_findings.md) — M8 Transformer Phase 1 findings (negative result)
- [20260421-llm_phase_blocker_report.md](20260421-llm_phase_blocker_report.md) — LLM phase decisive blocker report
- [20260421-ralph_loop_universe_mining_state_reconstructed.md](20260421-ralph_loop_universe_mining_state_reconstructed.md) — R29-R35 universe-mining state recovery (loop pause/resume)
- [20260421-universe_mining_r0_baseline.md](20260421-universe_mining_r0_baseline.md) — Universe-mining R0 baseline run

## 6. Specs (legacy non-PRD) — 2

Standalone specs predating the `prd_*` naming convention.

- [20260421-universe_expansion_spec_v2_2.md](20260421-universe_expansion_spec_v2_2.md) — Universe expansion v2.2 (32 → 53 symbols, Stage 2)
- [20260421-universe_expansion_spec_v2_1.md](20260421-universe_expansion_spec_v2_1.md) — Universe expansion v2.1 (precursor)

## 7. Reference / contracts / conventions — 5

How-to specs, schemas, and stable contracts.

- [20260424-paper_artifact_schema.md](20260424-paper_artifact_schema.md) — Paper run artifact format (5 CSV + 1 JSON)
- [20260424-path_naming_conventions_proposal.md](20260424-path_naming_conventions_proposal.md) — X-1 path/naming proposal (quant vs dev split)
- [20260423-feature_data_tier_classification.md](20260423-feature_data_tier_classification.md) — Feature data-tier classification (T0-T3)
- [20260421-promotion_flow.md](20260421-promotion_flow.md) — Mining → production promotion flow (M2 contract)
- [20260420-ralph_loop_prompt.md](20260420-ralph_loop_prompt.md) — Saved ralph-loop prompt template

## 7.4 Templates — 1

Markdown templates that downstream artifacts must be derived from
(copy-and-fill, not edited in place).

- [templates/track_c_evidence_pack_template.md](templates/track_c_evidence_pack_template.md) — Track C controlled-mining nominee evidence pack template (codex round-27 boundary). Required sections: boundary attestation, train diagnostics, validation-year acceptance gates, cross-cutting checks (M12 weighted thin-data, C5 role-remint, cost-model), forward soak plan, risks, reverse-validation. 2026 sealed evaluation explicitly frozen. Copy → `docs/memos/<YYYY-MM-DD>-track_c_<nominee>_evidence_pack.md` for each nominee.

## 7.5 Audit cycle memos — 10 (cycle complete) + 1 cycle summary

**Cycle-level codex review handoff**: [audit/20260428-ralph_audit_cycle_summary_for_codex_review.md](audit/20260428-ralph_audit_cycle_summary_for_codex_review.md) — single-doc digest of the 10-round ralph-audit-2026-04-28 cycle for codex round-11 review. Includes: why the cycle ran, per-round status table, full findings ledger (closed/deferred/wontfix), cumulative-pass design evidence (R3 PASS elevated twice; R01.1 DST closed in R8 after 5 rounds carry-forward), PRD §1 failure-mode recurrence check (none recurred), 5 specific review asks for codex.


Per-round memos for ralph-audit-2026-04-28 (10-round audit cycle: 3
deep on forward evidence v2.1.3 + 7 cumulative-pass codebase-wide).

- [audit/20260428-ralph_audit_round_01.md](audit/20260428-ralph_audit_round_01.md) — R1 (A1) — forward evidence module audit: 5 modules contract re-derivation + 4 live e2e (clean/sub-threshold/Blocker-1/Blocker-2) + 2 reverse-validation (BDay logic reproduce hash collision; empty-digest gate reproduce flagged_only under-classification). 0 blocker / 1 non-blocker (DST UTC-hour) / 2 docs-only (1 fixed: CLAUDE.md sync v2.1 → v2.1.3) / 1 cosmetic (`_signed_drift` dead code). Status: FIX_LANDED.
- [audit/20260428-ralph_audit_round_02.md](audit/20260428-ralph_audit_round_02.md) — R2 (A2) — adversarial scenario hardening: 15 scenarios (PRD 12 + 3 extensions) / 26 assertions all PASS against real BarStore panel. Lifted 4 most-valuable to durable regression tests (test_revalidate_does_not_mutate_input_manifest / test_revalidate_thread_safe_concurrent_calls / test_revalidate_zero_weight_held_revision_invalidates / test_revalidate_backward_window_deterministic). Forward revalidate suite 11 → 15 passed. Cross-round meta-check confirmed R01 PASS claims. Status: PASS.
- [audit/20260428-ralph_audit_round_03.md](audit/20260428-ralph_audit_round_03.md) — R3 (A3) — forward documentation sync: README §17 chronological phase list removed (PRD §3.6 changelog rule); 5 cross-refs redirected; INDEX.md §7.5 added; baseline regenerated (1838 collected / 1836 passed). 0 blocker / 0 non-blocker / 4 docs-only (all fixed). Phase A closed at R3. Status: FIX_LANDED.
- [audit/20260428-ralph_audit_round_04.md](audit/20260428-ralph_audit_round_04.md) — R4 (B1) — full-codebase static / contract lens (cumulative-pass round 1 of 7): global contract index built (15 module rows); 4 live e2e (18-pkg import smoke / 744-test research+backtest+factors slice / forward runner status / factor registry contract). 0 blocker / 3 non-blocker (WindowAnalyzer Tier_D drift, MiningEvaluator threshold drift, F-stack carry from R1) / 1 docs-only (CLAUDE.md "strict separation" wording tightened: PRODUCTION ∩ RESEARCH = {drawup_from_252d_low} is intentional) / 4 cosmetic. Cross-round meta-check ELEVATED R03 PASS (R3 missed CLAUDE.md wording imprecision; B-round cumulative pass surfaced it). Status: FIX_LANDED.
- [audit/20260428-ralph_audit_round_05.md](audit/20260428-ralph_audit_round_05.md) — R5 (B2) — full-codebase live e2e execution lens (cumulative-pass round 2 of 7): 5 long-chain e2e — BarStore split cascade verified on 5 high-split syms (factors 4×/15×/40×/20×/2× match splits.parquet); BacktestEngine.run() 832-row real-data e2e with M12 metrics live; paper drift report on rcm_v1 live artifact = 0.00 bps mean/max NAV drift, 0/78 position-set diff (M11a/M11b parity holds live); 5-script argparse health (build_catalog.py confirmed NO-ARGPARSE cosmetic). 0 blocker / 0 non-blocker / 0 docs-only / 1 cosmetic. Cross-round meta-check 8 prior PASS claims all CONFIRMED, none ELEVATED. Status: PASS.
- [audit/20260428-ralph_audit_round_06.md](audit/20260428-ralph_audit_round_06.md) — R6 (B3) — full-codebase adversarial corner-case lens (cumulative-pass round 3 of 7): 40 adversarial scenarios across 8 corner categories (data / signal / backtest / concentration / forward / config / concurrency / extreme), 40/40 PASS. Harness `dev/audit/r6_b3_codebase_adversarial.py` checked in for re-run. Verified live: M14 NaN-price-hole fallback / M12 metrics universal / PRODUCTION_FACTORS frozenset immutable / MFS warn-and-drop AND strict-raise / forward hash determinism + thread-safety + non-mutating revalidate / R4 F03 OVERLAP={drawup_from_252d_low}. 0 blocker / 0 non-blocker / 0 docs-only / 0 cosmetic. Cross-round meta-check 11 prior claims all CONFIRMED or CARRY-FORWARD-CONFIRMED. Status: PASS.
- [audit/20260428-ralph_audit_round_07.md](audit/20260428-ralph_audit_round_07.md) — R7 (B4) — full-codebase cross-cutting invariant lens (cumulative-pass round 4 of 7): 13 invariants verified live across config + schema + runtime + data layers (long-only / SPY+QQQ benchmark consistency / strict_mode propagation / BarStore adjustment cascade / SQQQ blacklist / T+1 open-fill / MFS signal shift / kill_switch 3-tier / production_strategy.yaml SoT / cost_model 38 fields / P0.1 apply_extra_shift=False default). Layered-defense (config+schema+runtime) confirmed for INV1/INV5/INV8 hard constraints. 0 blocker / 0 non-blocker / 0 docs-only / 0 cosmetic. Cross-round meta-check 12 prior claims all CONFIRMED. Status: PASS.
- [audit/20260428-ralph_audit_round_08.md](audit/20260428-ralph_audit_round_08.md) — R8 (B5) — full-codebase determinism / reproducibility lens (cumulative-pass round 5 of 7): R01.1 DST UTC-hour carry-forward CLOSED — `_NYSE_CLOSE_UTC_HOUR=20` heuristic was off by 1 hour during EST/winter; replaced with zoneinfo America/New_York comparison; 7-case reverse-validation sweep all PASS; 2 EST regression tests pinned; forward runner suite 29 → 31 passed. PYTHONHASHSEED 0 vs 12345 → identical hash; M11a sorted(set()) fix preserved. 0 blocker / 1 non-blocker FIXED / 0 docs-only / 0 cosmetic. Cross-round meta-check 11 prior claims CONFIRMED + R01.1 ELEVATED-and-CLOSED. Status: FIX_LANDED.
- [audit/20260428-ralph_audit_round_09.md](audit/20260428-ralph_audit_round_09.md) — R9 (B6) — full-codebase documentation truth lens (cumulative-pass round 6 of 7): 4 live e2e (forward evidence v2.1.3 ship verification — 7 commits + 5 module paths / OOS MVP modules / 3 milestone memos exist / baseline rebuild). F10 docs-only fix landed: framework_completion PRD §11 read as "open" while CLAUDE.md showed M11a/M11b/M12/M14 SHIPPED — added v1.2 status header redirecting to CLAUDE.md as authoritative. Baseline refreshed (1840 collected / 1838 passed; gained 2 from R8 DST regression tests). 0 blocker / 0 non-blocker / 1 docs-only FIXED / 0 cosmetic. Cross-round meta-check 11 prior claims CONFIRMED + R3 ELEVATED-AND-FIXED (2nd time). Status: FIX_LANDED.
- [audit/20260428-ralph_audit_round_10.md](audit/20260428-ralph_audit_round_10.md) — **NEW** R10 (B7) — meta-audit + final consolidation (cumulative-pass round 7 of 7, **cycle complete**). Closed all carry-forward findings: R01.4 `_signed_drift` dead code REMOVED; F08 build_catalog.py argparse FIXED; F01 / F02 threshold drift DEFERRED with explicit memo `memos/20260428-r10_threshold_drift_deferral.md`. Final pytest: 1838 passed / 0 failed / 1 skipped / 1 xfailed / 474.25s. PRD §1 three failure modes (test fixture calendar / no reverse-validation / coarse PRD-vs-code mapping) verified did NOT recur in any of 10 rounds. Final cumulative meta-check ledger across all 9 prior rounds: 13 prior claims all CONFIRMED, 2 ELEVATED-and-FIXED, 0 CHALLENGED. RALPHAUDIT10DONE conditions all met. Status: FIX_LANDED.

## 8. History archives (extracted from CLAUDE.md) — 2

Slim-out targets for CLAUDE.md. Detail preserved here, summaries point
back from CLAUDE.md.

- [20260424-claude_md_phase_e_history.md](20260424-claude_md_phase_e_history.md) — Phase E + audit + reference-section archive
- [20260422-claude_md_phase_bc_history.md](20260422-claude_md_phase_bc_history.md) — Phase B + Phase C history archive

## 9. Data integrity notes — 1

Data-layer issues parked off the main line.

- [20260424-data_integrity_2022_split_adjustment.md](20260424-data_integrity_2022_split_adjustment.md) — BarStore split-adjustment inconsistency in pre-Aug-2022 windows; verified clean / contaminated window list

## 10. State snapshot (regenerable, latest only) — 1

Current point-in-time view. Regenerated by
`dev/scripts/export/dump_phase_state_snapshot.py`. Each commit
overwrites in place; older snapshots live in git history.

- [20260424-phase_state_snapshot.md](20260424-phase_state_snapshot.md) — Candidate registry + paper run inventory (auto-generated)

## 11. LLM handoff materials — 6

External-LLM (Gemini / Codex / etc.) prompt context + funnel
documentation. Not standalone — used as inputs to manual LLM sessions
that produce candidate YAMLs.

- [llm_handoff_seed_20260422T002627Z.md](llm_handoff_seed_20260422T002627Z.md) — Auto-dumped LLM seed context (gitignored regenerable; this one tracked as exemplar)
- [20260421-llm_external_llm_handoff.md](20260421-llm_external_llm_handoff.md) — How-to for handing off to external LLMs (M15)
- [20260421-llm_funnel_checklist.md](20260421-llm_funnel_checklist.md) — Mandatory reverse-review checklist for LLM-generated factors
- [20260421-llm_proposal_prompt_template.md](20260421-llm_proposal_prompt_template.md) — Prompt template for factor proposals
- [20260421-llm_proposal_seed_context.md](20260421-llm_proposal_seed_context.md) — Seed context block for LLM sessions

## 12. Logs — 1

The single ever-growing append-only research log. Every research /
audit / parallel-paper / loop round writes its 11-part Chinese report
here.

- [20260420-ralph_loop_log.md](20260420-ralph_loop_log.md) — Cumulative ralph-loop log (15k+ lines)

---

## Reading guides for common tasks

**"What's the current state of the project?"** Read in this order:
1. `../README.md` (`§1.4` current-state bullets)
2. `20260424-phase_state_snapshot.md` (registry + paper runs)
3. The most recent synthesis docs in §2 above

**"What's the latest research conclusion?"**:
1. `20260424-parallel_paper_2022h2_checkpoint_75d.md` (cross-regime terminal memo)
2. Walk back through prior checkpoints if you want the journey.

**"What governs the parallel paper exercise?"**:
1. `20260424-prd_phase_e_post_cand2.md` (originating PRD)
2. `20260424-prd_phase_e_governance_and_paper.md` (governance contract)
3. `20260424-prd_research_to_paper_promote_standard.md` (promote contract)

**"What's currently broken / parked?"**:
- `20260424-data_integrity_2022_split_adjustment.md` (BarStore split issue)
- §11 of the most recent synthesis docs lists open follow-ups.

---

## Convention for new docs (effective 2026-04-24, forward-only)

The 58 files above stay where they are — moving them would break
cross-references in README / CLAUDE.md / commit messages / inter-doc
links. **New documents** land in per-category subdirs:

```
docs/
├── INDEX.md                      ← navigation (this file)
├── prd/                          ← new PRDs go here
├── synthesis/                    ← phase / loop wrap-up docs
├── checkpoints/                  ← per-checkpoint analysis memos
├── memos/                        ← decision / drill / proposal memos
├── reports/                      ← findings, blockers, baselines
├── reference/                    ← schemas, contracts, conventions
├── history/                      ← archived from CLAUDE.md
├── data_integrity/               ← data-layer issue notes
├── state/                        ← state snapshots (latest only)
├── llm_handoff/                  ← LLM external handoff materials
└── 20260424-*.md (legacy flat)   ← existing files, do not move
```

Subdirs are created lazily — when the first new doc of a category
lands, create the subdir then. No empty directories.

**Rule for naming**: keep the `YYYYMMDD-` prefix. Subdir replaces the
implicit category-from-name pattern but the date prefix stays, so
chronological sort still works.

**Update INDEX.md** when adding a new doc: each entry under the right
section, link the path including the subdir.

**Migration of legacy files**: NOT now. If a future doc-audit round
explicitly takes that scope, the migration would touch ~50 files +
~50-100 cross-references, with one mass commit per category. Until
then, INDEX.md is the navigation and the flat layout is the storage.
