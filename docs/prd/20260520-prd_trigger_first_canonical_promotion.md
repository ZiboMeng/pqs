# PRD: Trigger-First Canonical Promotion (M2 Path for Decision Stack)

**Status**: DRAFT v1
**Author**: operator (Claude Opus 4.7), per user request 2026-05-20
**Triggered by**: Task 3 directional block memo
(`docs/memos/20260520-task3_status_flip_directional_block.md`)
**Scope source**: PRD-X v2 implementation loop "remaining 1%" — the
`production_strategy.yaml status: "conservative_default" → "active"`
flip and its multi-cycle prerequisite chain.
**Estimated work**: 2-3 work cycles (each ≈ recent P0/P1/P2 scale).
**Distinct from**: PRD-X v2 implementation loop (DONE).

---

## 1. Goal

Make `status: "active"` flip for the trigger-first decision stack
**structurally possible** by satisfying the M2 promote pydantic
validator gates in
`core/config/production_strategy.py::_active_requires_source_and_validation`:

- `source.mode = "promoted_from_archive"`
- `source.spec_id` / `lineage_tag` / `promoted_at` non-empty
- `validation.{post_fix_validated, passed_oos_gate, passed_qqq_gate,
  passed_paper_backtest_alignment}` all `true`
- `fingerprints.{universe_hash, factor_registry_hash, config_hash}` all non-empty

…AND verify against the §6.4 invariants + §12.0 baseline regression
+ M11 parity matrix on the canonical config's NAV path.

## 2. Out-of-scope

- Real broker / live capital deployment (PRD §13 live gate; separate)
- Replacing MultiFactorStrategy as primary alpha source (the
  trigger-first stack remains a thin overlay; structural rewrite is
  separate alpha-engineering decision)
- New strategy modules (we use the 8 modules already shipped in
  PRD-X v2)

## 3. Phases

### P3.1 — Pick canonical trigger-first config (directional)

| Candidate | Sharpe (2018-2024) | MaxDD | Construction | Notes |
|---|---|---|---|---|
| R5e v2 | 0.50 | -20.95% | RuleBased+Partial+Sidecar(off), monthly, mom_12_1 | Baseline smoke |
| R9 mode='active' | 0.57 | -20.17% | + Partial overlay band 0.02 | turnover -7.9% |
| R10 Path C weak-filter | 0.58 | -18.95% | + Sidecar weak-filter | MaxDD passes §6.4 |
| R12 Path A (cycle06 composite) | 0.58 | -17.32% | cycle06 composite + simple norm-rank | §12.0 apples-to-apples PASS |
| R14 real engine | 0.63 | -17.43% | R10 + BacktestEngine.run T+1 open | Real-fill semantic |
| **R16 Path A** | **1.12** | **-19.10%** | cycle06 composite + weekly + cap_aware | **§12.0 within 0.05 of strict tolerance** |

**Operator recommendation: R16 Path A**

Rationale:
1. Highest Sharpe (1.12) of all candidates
2. MaxDD -19.10% within §6.4 15-20% target
3. Uses the cap_aware_cross_asset harness cycle06 itself uses
   (architectural parity)
4. cycle06 composite (drawup_from_252d_low + trend_tstat_20d +
   ret_2d) is itself a Track-A PASS spec, providing alpha-source
   lineage
5. Within 0.05 Sharpe of the strict full-period baseline minus
   tolerance (1.17), the closest of any candidate

**Directional gate**: user must explicit-go on canonical selection.
Alternative recommendations:
- R14 if T+1 open execution semantic is more important than Sharpe
- R12 Path A if apples-to-apples simplicity is preferred over
  harness complexity

**Decision artifact**: write
`docs/memos/YYYY-MM-DD-canonical_trigger_first_config_decision.md`
with chosen config + rationale + lineage_tag template.

**Deliverable**: a canonical `ResearchCompositeSpec` instance (the
exact features/weights/holding_freq) saved with a deterministic
spec_id (hash) for M2 promote lookup.

**Acceptance criteria (AC)**:
- ✅ canonical config doc committed
- ✅ spec_id deterministic and recorded
- ✅ user explicit-go on canonical selection (directional gate)

### P3.2 — OOS walk-forward for trigger-first

Extend `core/backtest/window_analyzer.py::WindowAnalyzer` to support
`--decision-stack trigger-first` path. Run 252-day forward blocks
on the canonical config.

**Acceptance criteria (AC)**:
- ✅ Walk-forward fold-level metrics computed for canonical config
- ✅ Mean OOS IR ≥ 0.20 across folds (M2 gate: `passed_oos_gate`)
- ✅ Strict-chronological discipline preserved (no interleaved
   selector — Track-A R1 leakage discipline)
- ✅ Sealed-2026 never accessed
- 🟡 Non-blanket: if OOS IR < 0.20, record FAIL with root cause; M2
   gate not satisfied → status flip aborted; revert to P3.1
   alternative candidate

**Estimated effort**: 1 cycle (extend WindowAnalyzer + run + verdict).

### P3.3 — Paper-backtest M3 alignment test for trigger-first

Run `scripts/run_paper.py --mode replay --decision-stack trigger-first`
on the canonical config; compare NAV trajectory bit-for-bit to
`scripts/run_backtest.py --decision-stack trigger-first` on same window.

**Acceptance criteria (AC)**:
- ✅ Both paths produce equity_curve series with identical shape
- ✅ Daily NAV deviation < 5 bps (M3 strict_match threshold, same as
   legacy MultiFactor convention)
- ✅ `validation.passed_paper_backtest_alignment = true`
- 🟡 If deviation > 5 bps, root-cause classified (typically
   timing-input drift or rebalance-trigger semantic differences);
   non-blanket failure.

**Estimated effort**: 1 cycle (extend M3 alignment test for
trigger-first + run + verdict).

### P3.4 — QQQ gate (diagnostic, post-2026-05-02)

Per CLAUDE.md QQQ deprecation memo: vs-QQQ is DIAGNOSTIC not HARD
gate. The `passed_qqq_gate` field in
`ProductionStrategyValidation` may need PRD-level revision (set
default=true when QQQ deprecated, OR rename to `passed_spy_gate`
with SPY as hard gate). This is a schema-level decision separate
from this PRD; for now, document the canonical config's vs-SPY +
vs-QQQ numbers and treat `passed_qqq_gate` as a soft check that
passes if vs-SPY hard gate passes.

**Acceptance criteria (AC)**:
- ✅ vs-SPY (hard) > 0 on full period + 2025 holdout
- ✅ vs-QQQ (diagnostic) recorded but not blocking

**Estimated effort**: included in P3.2 walk-forward output.

### P3.5 — Compute fingerprints (universe / factor_registry / config)

Deterministic hash computation for the canonical config's:
- universe (cycle06 universe = `config/universe.yaml` selector +
  drop_symbols)
- factor_registry (RESEARCH_FACTORS in
  `core/factors/factor_registry.py` at promotion time)
- config (canonical config yaml content)

**Acceptance criteria (AC)**:
- ✅ 3 hashes computed and stored in `fingerprints` section of
   yaml
- ✅ M3 alignment-check at runtime can detect drift if these change
   post-promotion

**Estimated effort**: ~0.5 cycle (utility + integration).

### P3.6 — M2 promote_strategy.py extension for trigger-first

The existing `scripts/promote_strategy.py` (M2) builds for
MultiFactorStrategy. Extend to also support trigger-first
decision-stack:
- accept `--decision-stack trigger-first --canonical-spec <hash>`
- write `decision_stack:` section into yaml on promotion
- populate `source`, `validation`, `fingerprints`
- enforce all 4 validation gates true before allowing `--promote`

**Acceptance criteria (AC)**:
- ✅ `python scripts/promote_strategy.py --decision-stack trigger-first
   --canonical-spec <hash> --promote` produces a valid
   `status: "active"` config with all gates filled
- ✅ Pydantic validator accepts the result (no
   `_active_requires_source_and_validation` errors)
- ✅ Runtime check: `load_production_strategy()` reports
   `status=active`

**Estimated effort**: ~1 cycle (extend M2 CLI + acceptance test).

### P3.7 — Status flip + post-flip verification

Once P3.1-P3.6 all pass, the M2 promote produces the flipped yaml.
Add an acceptance test that:
- Loads the flipped yaml
- Runs `run_backtest.py` with default args (no `--decision-stack`)
- Verifies the active production path now uses trigger-first
- Verifies M11 parity is preserved (engine.run kernel untouched)
- §6.4 invariants verified end-to-end

**Acceptance criteria (AC)**:
- ✅ flipped yaml loads without validator error
- ✅ default `run_backtest` invocation produces trigger-first NAV
- ✅ NAV matches the canonical config's expected output
   (regression seam)
- ✅ all §6.4 invariants honored

**Estimated effort**: ~0.5 cycle (acceptance test + final docs).

## 4. Dependencies

- PRD-X v2 implementation loop ✅ (already done; modules + main entries
  + config schema all shipped through R0-R17)
- WindowAnalyzer (existing) — needs trigger-first extension (P3.2)
- M3 strict_match infra (existing for MultiFactor) — extend to
  trigger-first (P3.3)
- M2 promote_strategy.py (existing for MultiFactor) — extend (P3.6)
- Canonical config selection (P3.1) — user explicit-go

## 5. Risks

1. **Canonical config decision lock-in**: Once promoted, switching
   canonical requires another M2 cycle. Mitigated by `lineage_tag`
   and version-controlled config history.
2. **OOS WF FAIL at P3.2**: canonical config might fail OOS gate
   (Sharpe full-period ≠ Sharpe per-fold). Mitigation: P3.1 already
   selected R16 Path A which has highest full-period Sharpe; fall
   back to R14 if P3.2 fails.
3. **Paper-backtest deviation > 5 bps at P3.3**: surfaces a hidden
   execution-semantic bug. Mitigation: this is exactly what M3 was
   designed to catch — non-blanket failure recorded with root cause.
4. **§6.4 invariant violation found late**: if MaxDD on a specific
   fold exceeds 20% target, fold-level review per
   per_validation_year_max_dd discipline.

## 6. Anti-goals (explicit)

- NOT a research alpha tune (R5f-style optimization is separate)
- NOT a new strategy module
- NOT a live broker integration (§13 live gate)
- NOT a `MultiFactorStrategy` replacement (overlay pattern preserved)
- NOT a §12.0 strict full-period 1.37 baseline PASS attempt (R16
  Path A is within reach of tolerance but not strictly above; PRD
  accepts apples-to-apples PASS as sufficient for promote)

## 7. Estimated total work

**2-3 work cycles**, each commensurate with recent P0/P1/P2 cycles:
- P3.1: 0.5 cycle (user-gated)
- P3.2: 1 cycle
- P3.3: 1 cycle
- P3.4: 0 (folded into P3.2)
- P3.5: 0.5 cycle
- P3.6: 1 cycle
- P3.7: 0.5 cycle

Total ≈ 4.5 cycles of operator work + 1 user directional gate (P3.1)
+ continuous user availability for M2 promote authorization (P3.6).

If P3.2 OOS FAIL → may need P3.1 redo → +1 cycle.

## 8. References

- Task 3 block memo:
  `docs/memos/20260520-task3_status_flip_directional_block.md`
- PRD-X v2 main:
  `docs/prd/20260519-trigger_threshold_first_rebalance_architecture.md`
- PRD-X v2 final summary + R16 acceptance numbers:
  `docs/memos/20260519-prdx_v2_final_summary.md`
- M2 framework: `docs/20260421-prd_framework_completion.md` §M2
- M3 alignment discipline: `docs/20260421-prd_framework_completion.md` §M3
- QQQ deprecation memo:
  `docs/memos/20260502-qqq_benchmark_deprecation.md`
- CLAUDE.md §"Benchmark Outperformance Rule"

## 9. DONE condition

When P3.1-P3.7 all PASS:
- `config/production_strategy.yaml status: "active"` ✓
- pydantic validator accepts ✓
- runtime path uses trigger-first canonical config by default ✓
- M11 parity verified end-to-end ✓
- §6.4 + §12.0 invariants verified ✓
- M3 alignment continuously enforced ✓

At that point the trigger-first decision-stack is production-active
and the "remaining 1%" of PRD-X v2 is closed.
