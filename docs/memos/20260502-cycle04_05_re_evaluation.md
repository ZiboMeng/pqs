# Cycle #04 + #05 archived trials — v3 re-evaluation

**Status**: Trial 9 (cycle #05 winner) re-evaluated MANUALLY using
data in CLAUDE.md / cycle #05 closeout memo. Full automated re-evaluation
of all 30+ archived trials DEFERRED — requires backtest pipeline run
across validation years + stress slices that current `data/ml/research_miner/*/top_20.csv`
artifacts don't contain.

**Authority**: Phase 3 of branch `invariant-revision-2026-05-02`.
Decision memo `docs/memos/20260502-qqq_benchmark_deprecation.md` §
"Mining + acceptance pipeline impact".

---

## Trial 9 (`6c745c601a47`) manual re-evaluation under v3 gate

**Source data**: cycle #05 closeout
`docs/memos/20260501-track_c_cycle_2026-05-01-05_close.md` + CLAUDE.md
inventory entry for cycle #05.

**Spec**: `beta_spy_60d (1/3) + max_dd_126d (1/3) + ret_1d (1/3)`
(Family A + B + F, equal weight)

**Pre-v3 acceptance status**: Tier 1 by R41 ritual (passes yaml hard
blockers under v2) BUT failed CLAUDE.md QQQ Outperformance Rule HARD
constraint (5-window mean vs_qqq = -4.59% < 0). Forced into
diversifier role per D10c compromise rather than core_alpha.

### v3 gate evaluation (per `config/temporal_split_v3.yaml`)

#### Core role gate evaluation

| Gate | Action | Trial 9 actual | Pass? |
|---|---|---|---|
| `validation.2025.excess_vs_spy > 0` | kill_candidate (NEW v3) | unknown — not in closeout (must compute) | **TBD** |
| `validation.2025.excess_vs_qqq > 0` | diagnostic_only (v3 change) | +9.6% | actual_passed=True / gate_passed=True (diag) |
| `validation.2025.maxdd <= 0.20` | kill_candidate | -18.2% | True (within tier; 18-20% would warn for diversifier role) |

#### Per-year aggregate (validation_year_pass)

Per CLAUDE.md cycle #05 inventory:
- 2018: vs_qqq=+3.7%, max_dd=-15.2%
- 2019: vs_qqq=-13.2%, max_dd=-6.8%
- 2021: vs_qqq=-3.3%, max_dd=-6.0%
- 2023: vs_qqq=-19.8%, max_dd=-9.3%
- 2025: vs_qqq=+9.6%, max_dd=-18.2%

| Aggregate | Threshold | Trial 9 actual | Pass under v3? |
|---|---|---|---|
| `excess_vs_qqq_positive_min: 3` | 3 / 5 years positive | 2 (2018, 2025) | gate_passed=True (diagnostic_only); actual_passed=False |
| `excess_vs_spy_positive_min: 4` | 4 / 5 years positive | unknown (not in closeout) — must compute | **TBD** |
| `maxdd_per_year_max: 0.20` | all ≤ 20% | max=-18.2% (2025) | True ✓ |

#### Stress slices

| Slice | Threshold | Trial 9 actual | Pass? |
|---|---|---|---|
| covid_flash | maxdd ≤ 25% | -13.3% | True ✓ |
| rate_hike_2022 | maxdd ≤ 25% | -15.8% | True ✓ |

#### Concentration / beta / cost

Per cycle #05 closeout: passes (Trial 9 was Tier 1 under R41 v2).

#### Diversifier-specific rules (if remaining as diversifier)

- raw NAV correlation: 0.54-0.69 vs all 5 anchors (`partial_diversifier` band ✓)
- residual NAV correlation: 0.07-0.36 (< 0.50 ✓)
- factor_overlap_max=1 (only `beta_spy_60d` shared with anchors; for
  diversifier role required `factor_overlap_with_active_core = 0`)
  — **fails diversifier eligibility if RCMv1 is "active core"**, but RCMv1
  is `legacy_decay_verification` not active core, so this gate vacuously
  passes
- non_equity_avg=32.1% (≥ 15% ✓)

### Verdict under v3 gate

**Conditional on `validation.2025.excess_vs_spy > 0` AND
`excess_vs_spy_positive_min` aggregate**:

- IF Trial 9 has positive vs_spy in 2025 AND ≥4 of 5 years positive vs_spy
  → **PASSES v3 acceptance for core role** (no diversifier exception needed)
  → could be re-classified core_alpha
- IF Trial 9 fails 2025 vs_spy or aggregate vs_spy
  → fails v3 hard regardless of QQQ deprecation
  → status TBD pending data

**Action required to confirm**: run a backtest on Trial 9 spec on
2025 validation year and 2018/2019/2021/2023/2025 to compute per-year
`excess_vs_spy`. Estimate: 30 minutes if existing pipeline supports.

**Operator decision DEFERRED**:
- Even if Trial 9 passes v3 core_alpha, **do NOT auto-mutate manifest** to
  re-classify Trial 9 from `diversifier` → `core_alpha` mid-forward.
  Trial 9 forward observation is in flight (TD001 pending Mon 2026-05-04);
  changing role mid-flight pollutes the candidate's audit trail.
- Forward observation continues as diversifier role.
- IF TD60 GREEN (~2026-07-30), revisit role classification at promotion
  time using v3 gate.

---

## Cycle #04 archived trials (top-10) — v3 evaluation hypothesis

**Pre-v3 status**: 0 nominee, 10/10 Tier 2 by R41 v2 (NAV correlation
verified). Two clusters:
- Cluster A (4 trials, drawup+amihud anchored): pooled raw NAV corr
  0.66-0.70 vs anchors → first cycle ever <0.85 raw → **partial_diversifier**
  band but factor_overlap=2 with RCMv1 (drawup + amihud both shared)
- Cluster B (6 trials, vol-anchored): raw 0.91-0.94 → reject by NAV gate
  remains; max_dd -27% similar to cycle03

### Hypothesis: under v3 gate

| Cluster | NAV gate | Factor overlap (diversifier req=0) | vs_qqq (now diag) | Likely v3 verdict |
|---|---|---|---|---|
| A (4 trials) | Pass partial_diversifier band (raw 0.66-0.70 < 0.70 ✓) | Fail (overlap=2 vs RCMv1) | diag | **Still 0 nominee** (factor overlap bind) |
| B (6 trials) | Fail raw NAV gate (≥ 0.85) | Variable | diag | **Still 0 nominee** (NAV gate bind) |

**v3 doesn't help cycle #04 — bind constraints are NAV correlation +
factor overlap, not QQQ outperformance**.

But note: these trials currently have `diversifier` role assumption.
Under v3 they could potentially be evaluated as `core_alpha` role
(no factor-overlap requirement, no NAV-correlation requirement). In
that case:
- Cluster A: vs_spy / maxdd / stress all unknown for these 4 trials
  (closeout focused on NAV finding, not full acceptance metrics)
- Cluster B: similarly unknown

**Action required to confirm**: run backtest pipeline on cycle #04
top-10 to compute v3 core acceptance metrics. **DEFERRED** — same
reason as Trial 9 deferral above (no off-the-shelf script).

---

## Cycle #05 archived trials (top-10 incl. Trial 9) — v3 evaluation hypothesis

**Pre-v3 status**: 7 Tier 1 by R41 + 3 Tier 2. Trial 9 is one of the
7 Tier 1.

**Hypothesis**: the other 6 Tier-1-by-R41 trials follow same path as
Trial 9 — passed yaml hard blockers but failed CLAUDE.md QQQ rule.
Under v3 (QQQ diagnostic), they MAY pass core_alpha gate IF vs_spy
metrics are positive.

**Cycle #05 closeout memo lists only Trial 9's per-year metrics in
detail**; other 6 Tier-1 trials' per-year vs_spy / vs_qqq / maxdd
data not surfaced. Same data gap as cycle #04.

**Operator decision**: same as Trial 9 — DO NOT auto-promote any of
the 6. They were rejected at cycle #05 close for the QQQ rule reason
that v3 deprecates; the pre-v3 closeout decision DOES need revisiting,
but only after backtest data computed under v3 acceptance.

---

## Full re-evaluation deferral

**Triggers** (any of) for committing to full automated re-evaluation:

- **Trigger A**: Trial 9 forward TD60 verdict (~2026-07-30) lands GREEN
  AND user wants to evaluate cycle04/05 trials as second-candidate
  pool for fleet expansion under v3 gate.
- **Trigger B**: User explicit-go to spend ~1-2 days building automated
  v3-acceptance-evaluation script (specifies `(spec, role, freeze_date)`
  → backtest validation years + stress slices → `run_split_acceptance(metrics)`).
- **Trigger C**: External auditor / reviewer requests cycle04/05
  re-eval as part of QQQ deprecation acceptance.

Until trigger: cycle04/05 archived trials retain pre-v3 status
(Trial 9 = diversifier in forward; others = no nominee). v3 applies to
**FUTURE** mining (cycle #06+ when authorized) per branch decision.

---

## Operational summary for branch merge

**v3 gate effects observed in this re-evaluation**:

1. ✅ Trial 9 demonstrates the deprecation works as intended:
   per-year vs_qqq mean -4.59% would be diagnostic only; core_alpha
   role becomes feasible IF vs_spy metrics positive (TBD).

2. ✅ Cycle #04 / #05 backlog evaluation does NOT change without
   computing fresh validation-year backtest metrics — appropriate
   deferral.

3. ✅ Trial 9 forward observation NOT auto-mutated. Forward role
   remains `diversifier` for 90 days; revisit at TD60 GREEN.

4. ✅ Future mining (cycle #06+) routes through v3 yaml automatically
   via dispatch (freeze_date >= 2026-05-02 + role IN core/diversifier).

**No data pollution**:
- Trial 9 manifest unchanged
- Forward observation runs unchanged on main
- No cycle04/05 archive files mutated

---

## References

- Decision memo: `docs/memos/20260502-qqq_benchmark_deprecation.md`
- Checkpoint: `docs/checkpoints/20260502-invariant_revision.md`
- Cycle #04 closeout: `docs/memos/20260501-track_c_cycle_2026-05-01-04_close.md`
- Cycle #05 closeout: `docs/memos/20260501-track_c_cycle_2026-05-01-05_close.md`
- Trial 9 spec: `data/research_candidates/trial9_diversifier_001.yaml`
- v3 yaml: `config/temporal_split_v3.yaml`
