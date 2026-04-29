# PRD — Candidate Fleet Allocator (minimum version)

**Status**: Draft v1.0 — 2026-04-28
**Author**: zibo (drafted by Claude based on codex round-11 priority #3 + round-12 elevated to #1-missing-macro)
**Authority required**: user explicit (zibo) — implementation is **not** authorized by this PRD; this is design + acceptance-criteria draft only
**Lineage tag (when committed)**: `candidate-fleet-allocator-v1-2026-04-28`
**Parent context**:
- Codex round-12 (`docs/audit/20260428-codex_round_12_priority_status.md`) — "P2 candidate-fleet allocator is now the highest-value missing macro component"
- Codex round-11 review (`docs/audit/20260428-codex_round_11_review.md`) §B1 — "下一个大收益点不是再多挖一个 feature，而是定义两个候选如何一起上场"
- Forward observe evidence note (`docs/memos/20260428-forward_observe_first_real_after_v2_1_3.md`) — both candidates now collecting forward evidence in parallel; allocator becomes the operational unit of decision

---

## 1. Why this PRD

### 1.1 The real PM problem

Today the framework has **two live forward candidates** (`rcm_v1_defensive_composite_01` and `candidate_2_orthogonal_01`), both at TD003, both intentionally constructed to be different (composite correlation 0.404 < 0.5 per Phase E-post R6). The unit of decision is **no longer "single candidate pass/fail"**; it is "what is the best portfolio of candidates over the live forward window?"

Codex round-11:
> 这时候继续单策略视角，会错过组合层最大的 alpha-retention 机会。从真钱角度，下一个大收益点不是再多挖一个 feature，而是定义两个候选如何一起上场。这一层不补，未来就算两个单策略都不错，合起来也可能只是更复杂地做错事。

Codex round-12:
> Without an allocator layer, the framework can keep producing interesting single-strategy evidence while still failing the actual PM problem: how much capital to give each / how to handle overlap / how to budget correlation and drawdown / how to scale down when both are weak.

### 1.2 What "minimum version" means

Codex specifically requested **minimum allocator** — not full-featured PM stack. The bar is:

- can answer "how much capital to candidate A vs B today?" deterministically from inputs
- can **enforce** safety constraints (DD throttling, kill-switch interaction)
- can be tested in isolation without re-running mining or paper backfill
- is **explicit** about what it does NOT do (single-period optimization, dynamic risk parity, regime-conditional allocation)

This is fleet **v1**. Future v2/v3 can add adaptive weighting, regime-switching, etc. — those require their own PRDs.

### 1.3 What this PRD is NOT

- **Not a new alpha source**: allocator does not generate new factor signals. It composes existing candidate weight matrices.
- **Not a substitute for candidate-level acceptance**: each candidate must still pass its own promotion criteria (`acceptance_pack`, forward decision pack at TD010, etc.) before entering the fleet.
- **Not a real-broker integration**: lives entirely inside the paper / forward layer. PRD M17 (live-feed infra) is the separate gate.
- **Not a regime-conditional allocator**: v1 is regime-agnostic at the allocator layer (regime-conditional risk scaling already happens inside each candidate's `MultiFactorStrategy.regime_scale`). Adding regime-conditional capital tilts is a v2 concern.
- **Not a numeric-recalibration vehicle**: any threshold / parameter exposed by the allocator gets a sensible default; tuning is a follow-up exercise after live evidence.

### 1.4 Relationship to other open PRDs

- **Acceptance Threshold Unification PRD** (`prd/20260428-acceptance_threshold_unification_prd.md`): independent. Allocator does not touch acceptance thresholds; it consumes already-promoted candidates.
- **Forward evidence v2.1.3** (`prd/20260427-forward_evidence_hardening_prd.md`): allocator reads from forward manifests but does not mutate them. The fleet's daily decision is a **separate artifact** from per-candidate forward observations.
- **Future config/universe snapshot hardening PRD**: allocator MUST snapshot the fleet composition + capital split at every rebalance into a fleet manifest (parallel to forward manifest pattern).

---

## 2. Constraints

### 2.1 Hard constraints (cannot violate)

- **Long-only / no-margin / no-short** (CLAUDE.md): fleet weight matrix sums to ≤1.0 and every element ≥0.
- **SQQQ blacklist + leveraged-ETF stricter limits** (CLAUDE.md): allocator inherits per-candidate risk constraints; blacklist stays at the universe layer.
- **SPY+QQQ benchmark dual rule** (CLAUDE.md QQQ Outperformance Rule): fleet performance is reported vs **both**; allocator may NOT silently shift to a single benchmark.
- **Drawdown target 15-20%, not worse than SPY in crisis** (CLAUDE.md): fleet-level DD must be evaluated against this; allocator must have a DD throttle path.
- **Kill-switch hierarchy preservation**: existing 3-tier `KillSwitch` operates at portfolio-NAV level. Allocator-induced rebalances must NOT bypass kill-switch state.
- **Append-only fleet manifest**: same contract as forward manifest. No retro-mutation of past allocator decisions.
- **No promotion bypass**: a candidate cannot enter the fleet without having passed promotion gate (`acceptance_pack` PASS + forward TD010+ decision pack PASS, at minimum).

### 2.2 Reverse-validation requirement

Per ralph-audit cycle PRD §3.2: every fix must reverse-validate. For an allocator that ships, regression tests pin: (a) hard constraint compliance under adversarial weight matrices; (b) DD throttle fires at the right level; (c) overlap throttle reduces overlap when present.

### 2.3 No half-finished implementation

If implementation lands, all 6 minimum capabilities (per §4) are addressed in the same change-set. No "ship capital split first, leave DD throttle for later" — that creates unsafe operational gaps.

---

## 3. State today (input to design)

### 3.1 Live candidates

| Candidate | Spec | Status | Forward state | Composite correlation w/ peer |
|---|---|---|---|---|
| `rcm_v1_defensive_composite_01` | RCMv1 4-feature defensive composite (lag=1) | S2_paper_candidate | TD003 / 2026-04-28 | 0.404 vs cand2 |
| `candidate_2_orthogonal_01` | `{ret_5d, rs_vs_spy_126d, hl_range}` equal-weight 1/3 each | S2_paper_candidate | TD003 / 2026-04-28 | 0.404 vs rcm_v1 |

Both are below the live decision pack threshold (TD010); allocator is built to operate on whichever candidates are live and pass-promoted, not these two specifically.

### 3.2 What already exists in code

| Capability | Where | Notes |
|---|---|---|
| Per-candidate `MultiFactorStrategy.generate(price_df, regime, volume_df)` | `core/signals/strategies/multi_factor.py` | emits weight matrix per (date, symbol) |
| Per-candidate forward observation | `core/research/forward/runner.py::observe` | TD-by-TD append |
| Concentration metrics | `core/backtest/concentration_metrics.py` | top-1 / top-3 weight max + N-dates |
| Kill switch | `core/risk/kill_switch.py` | 3-tier with auto-recover |
| Cost model | `core/execution/cost_model.py::CostModel` | applied at fill time |
| Candidate registry | `core/research/candidate_registry.py::CandidateRegistry` | sqlite of S0/S1/S2/S5 state |

### 3.3 What does NOT exist

- A "fleet" abstraction that owns a list of candidates + a capital allocation policy
- A fleet weight matrix (composition of per-candidate weight matrices)
- A fleet forward manifest (parallel to per-candidate)
- A fleet-level kill-switch interaction (currently kill-switch operates on a single portfolio NAV)
- Any PR-tested regression for "two candidates running at once with overlap"

---

## 4. Minimum scope (6 capabilities)

The allocator v1 must answer 6 concrete questions:

### 4.1 C1 — Capital split rule

Given a list of N currently-active candidates, return a capital split vector $(w_1, w_2, ..., w_N)$ with $\sum w_i \leq 1.0$ and $w_i \geq 0$.

**v1 default**: equal-weight across active candidates (`w_i = 1/N` for all i; cash residual = 0). This is the simplest deterministic rule. Any non-equal allocation policy is a v2+ concern.

**Configurable**: `config/fleet.yaml::default_split: equal_weight | manual_overrides`. Manual override path lets a user pin `w_rcm_v1=0.7, w_cand2=0.3` for a specific epoch (used for capital tilts, never auto-tuned).

### 4.2 C2 — Pairwise correlation budget

Reject (or warn) a fleet composition where any pairwise candidate-return correlation over a recent window exceeds a `max_pairwise_corr` budget.

**v1 default**: `max_pairwise_corr = 0.70` over rolling 252-day window of per-candidate daily returns. Above 0.70 → log WARNING + emit event in fleet manifest; above 0.85 → reject the composition and require manual override.

**Rationale**: highly-correlated candidates collapse fleet variance reduction. The 0.70/0.85 split mirrors `MiningEvaluator.diversity_max_corr=0.70` (existing reference).

### 4.3 C3 — Overlap throttle on shared names

When two candidates both want to hold symbol $s$ on day $t$, the **fleet-level** holding in $s$ must not exceed a per-symbol cap.

**v1 default**: `max_fleet_symbol_weight = 0.20`. If candidate weights would compose to a fleet weight in $s$ above 0.20, the excess is **proportionally trimmed across the contributing candidates** (not just clipped at the sum) — this preserves the relative exposure intent of each candidate.

**Sanity guard**: M12 concentration metrics still apply at the fleet level. If post-trim fleet `top1_weight_max` still > 0.40 → fleet enters `manual_review_required` (analogous to current candidate-level M12 contract).

### 4.4 C4 — Core vs satellite role

Each candidate carries a role label: `core` | `satellite`.

- `core`: minimum capital floor of 60% (configurable), tighter DD throttle.
- `satellite`: maximum capital ceiling of 40% (configurable), can be parked / removed without fleet halt.

**v1 default**: roles are **assigned manually** at fleet configuration time, NOT auto-derived. (Auto-derivation is a v2 concern requiring forward-window evidence the system doesn't yet have.) Both current candidates would default to `core` until forward-evidence-based role assignment is justified.

### 4.5 C5 — Drawdown-based throttling

If fleet-level rolling drawdown breaches a threshold, **scale all candidate weights by a throttle factor** before computing the fleet weight matrix.

**v1 contract**:
- Trigger 1: fleet rolling 60-day MaxDD > -10% → throttle factor 0.7 (warning state).
- Trigger 2: fleet rolling 60-day MaxDD > -15% → throttle factor 0.5 (defensive state).
- Trigger 3: fleet rolling 60-day MaxDD > -20% → throttle factor 0.0 (halt; NO fleet exposure; cash only) — this hits the CLAUDE.md MaxDD ceiling.
- Recovery: 5 consecutive positive daily fleet returns → throttle factor moves up one tier.

**Interaction with existing per-portfolio kill switch**: if `KillSwitch` says DEFENSIVE/HALT at portfolio level, allocator *also* halts (whichever fires first wins). Allocator does NOT lift kill-switch halts.

### 4.6 C6 — Removal / parking rule

A candidate is **removed** from the fleet if any of:

- Forward decision pack at TD010 / TD020 / TD040 / TD060 fails (per forward PRD checkpoint cadence);
- Pairwise correlation with peer rises above 0.95 over rolling 252 days (degenerate diversification);
- Concentration gate (M12) flips to `manual_review_required` and stays for 5 consecutive observation days.

A candidate is **parked** (capital → 0, but not removed; can be reactivated) if:

- M12 weighted thin-data share > extreme threshold (10%) — current Cand-2 vs RCMv1 logic.
- User explicit-pause command issued.

Removal is recorded in fleet manifest with `removal_reason` + `removal_date` + `evidence_pointer`.

---

## 5. Proposed design (architecture only — no code)

### 5.1 New module: `core/fleet/`

```
core/fleet/
├── __init__.py
├── allocator.py          # FleetAllocator class (capital split + composition)
├── manifest_schema.py    # FleetManifest pydantic model (parallel to ForwardRunManifest)
├── manifest_io.py        # load_fleet_manifest / save_fleet_manifest (atomic write)
├── throttle.py           # DD throttle + kill-switch interaction
└── evidence.py           # daily fleet observation (parallel to forward observe)
```

### 5.2 New config: `config/fleet.yaml`

```yaml
# config/fleet.yaml — fleet allocator v1
candidates:
  - candidate_id: rcm_v1_defensive_composite_01
    role: core
    base_weight: 0.5
  - candidate_id: candidate_2_orthogonal_01
    role: core
    base_weight: 0.5

split_policy: equal_weight    # equal_weight | manual_overrides

# C2 correlation budget
max_pairwise_corr_warn: 0.70
max_pairwise_corr_reject: 0.85
corr_lookback_days: 252

# C3 overlap throttle
max_fleet_symbol_weight: 0.20

# C4 role caps
core_min_capital_pct: 0.60
satellite_max_capital_pct: 0.40

# C5 DD throttle
dd_throttle:
  warning_pct: 0.10      # → 0.7 throttle
  defensive_pct: 0.15    # → 0.5 throttle
  halt_pct: 0.20         # → 0.0 throttle (cash only)
  recovery_consecutive_days: 5
  rolling_window_days: 60

# C6 removal rules
removal_rules:
  forward_decision_fail: true
  pairwise_corr_above: 0.95
  m12_manual_review_streak_days: 5
parking_rules:
  m12_thin_data_extreme: 0.10
```

### 5.3 New manifest: `data/fleet_runs/fleet_manifest.json`

Parallel to forward manifests. Append-only. Records every fleet rebalance + every throttle/removal event.

```json
{
  "fleet_id": "fleet_v1_2026-04-28",
  "schema_version": "1.0",
  "candidates": [
    {"candidate_id": "...", "role": "core", "base_weight": 0.5}
  ],
  "rebalances": [
    {
      "rebalance_date": "2026-04-29",
      "candidate_weights": {"rcm_v1_defensive_composite_01": 0.5, "candidate_2_orthogonal_01": 0.5},
      "fleet_weight_matrix_hash": "...",
      "throttle_factor": 1.0,
      "throttle_reason": null,
      "concentration_metrics": {"m12_top1_weight_max": 0.18, "m12_top3_weight_max": 0.42},
      "events": [],
      "fleet_nav": 100000.00,
      "fleet_dd_60d": -0.012,
      "vs_spy": 0.003,
      "vs_qqq": 0.001
    }
  ]
}
```

### 5.4 Public API (minimum)

```python
from core.fleet import FleetAllocator, load_fleet_config

cfg = load_fleet_config("config/fleet.yaml")
alloc = FleetAllocator(cfg)

# C1 — capital split
splits = alloc.compute_capital_split(active_candidates=[...])  # → dict[candidate_id, float]

# C2 — corr budget check (pure-functional)
corr_status = alloc.check_correlation_budget(returns_df)  # → CorrStatus(level, pairs_violating)

# Compose fleet weight matrix from per-candidate weights
fleet_weights = alloc.compose_weight_matrix(
    candidate_weight_matrices={cid: per_candidate_weight_df},
    splits=splits,
)
# C3 + C4 + C5 enforced inside compose_weight_matrix

# Daily fleet observe (writes to fleet_manifest.json)
alloc.observe(as_of_date=...)
```

### 5.5 Integration touchpoints

- **Backtest**: `BacktestEngine.run(fleet=alloc, ...)` — optional new arg. If passed, engine drives fleet-level rebalances; if not, falls back to single-strategy mode.
- **Paper engine**: `PaperTradingEngine.run_day_daily(fleet=alloc, ...)` — same pattern.
- **Forward layer**: separate fleet observation (`alloc.observe`) writes its own manifest. Per-candidate forward observation continues independently — fleet observation is the **composition layer**, not a replacement.
- **Master report**: new section "Fleet" appended; SPY/QQQ excess shown at fleet level (CLAUDE.md QQQ Rule applies to fleet).

---

## 6. Acceptance criteria

A change-set passes this PRD if and only if all of the following hold:

1. `core/fleet/` module exists with the 5 files listed in §5.1.
2. `config/fleet.yaml` exists with the 11 sections per §5.2; `load_fleet_config` validates against pydantic schema.
3. `FleetAllocator` exposes the 4 public methods per §5.4.
4. **C1** (capital split): equal-weight default + manual override path tested.
5. **C2** (corr budget): warn at 0.70, reject at 0.85, both events recorded in fleet manifest.
6. **C3** (overlap throttle): when two candidates compose to fleet weight in symbol $s$ > 0.20, proportional trim is applied; M12 fleet-level concentration computed post-trim.
7. **C4** (core/satellite): `core_min_capital_pct=0.60` enforced; `satellite_max_capital_pct=0.40` enforced; both core candidates default at equal weight (0.5/0.5) is consistent with `core_min ≤ each w_core` only when N_core ≤ 1; design clarification needed for 2-core case (see open question Q1).
8. **C5** (DD throttle): 3 trigger levels + 5-day recovery rule, halt state interacts with `KillSwitch` (whichever fires first wins).
9. **C6** (removal/parking): all 3 removal rules + 2 parking rules implemented + fleet manifest records reasoned events.
10. **Hard constraint compliance** under regression test: long-only / sum ≤ 1.0 / SQQQ blacklist / kill-switch preservation.
11. **No-mutation invariant on forward manifests**: allocator reads forward manifests but never writes to them.
12. **Fleet manifest atomicity**: write is atomic (tmp file + rename); concurrent allocator runs fail with descriptive lock error rather than corrupting manifest.
13. **Reverse-validation tests**: (a) DD throttle: simulate fleet returns going to -16% rolling 60d; verify throttle_factor flips to 0.5. Reverse: revert throttle code; verify throttle_factor stays 1.0 (the fix would have been silent without the test). (b) Overlap throttle: construct two candidates both at 70% in AAPL; verify post-composition fleet AAPL ≤ 0.20.
14. **Full pytest green** including 12+ new tests in `tests/unit/fleet/`.
15. **Forward evidence note** when allocator is first run live, parallel to the per-candidate evidence note pattern.
16. **Doc updates**: README §1.4 mention; CLAUDE.md add "Fleet allocator" section; INDEX.md.

---

## 7. Implementation steps (when authorized)

8 commits:

1. **Step 1**: schema (`config/fleet.yaml` validators + `FleetManifest` pydantic) + empty allocator skeleton + 0 wires. Reversible.
2. **Step 2**: C1 capital split (equal_weight + manual_overrides) + 4 unit tests.
3. **Step 3**: compose_weight_matrix returning unconstrained fleet weights + 3 unit tests.
4. **Step 4**: C3 overlap throttle (proportional trim) + M12 fleet metrics + 4 unit tests.
5. **Step 5**: C2 correlation budget + manifest event recording + 3 unit tests.
6. **Step 6**: C5 DD throttle + KillSwitch interaction + 4 unit tests (including reverse-validation pair from §6.13).
7. **Step 7**: C4 role caps + C6 removal/parking rules + 4 unit tests + manifest reason recording.
8. **Step 8**: backtest / paper / report integration touchpoints + first live fleet observation + evidence note + docs.

Each step has its own commit. Reverting at any step leaves the previous step's behavior intact.

---

## 8. Risk

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Fleet allocator silently bypasses per-candidate kill-switch | low | severe | C5 §6.8 explicitly tests "whichever fires first wins" |
| Equal-weight is wrong default for two highly correlated candidates | medium | medium | C2 corr budget catches; reject at 0.85 |
| DD throttle false-fires during normal volatility | medium | low (research-only) | warning level (10%) is conservative; tunable |
| Fleet manifest gets corrupted by concurrent runs | low | severe | atomic tmp-file rename; lock file |
| Two-core overlap creates `core_min × N_core > 1.0` infeasible | high | low | Q1 design decision; either cap N_core=1 OR rescale core_min by N_core |
| Researcher hand-edits fleet weights and bypasses removal rules | medium | high | manual override path requires explicit `manual_overrides` policy + audit log entry |
| Fleet observation lags per-candidate observation | medium | low | separate `alloc.observe` call; daily ritual extension |

---

## 9. Out of scope (explicit)

- **Optimal allocation** (mean-variance / risk parity / hierarchical risk parity): v2+. v1 is equal-weight + manual override.
- **Regime-conditional allocation**: v2+. Each candidate already has its own internal `regime_scale`; fleet-level regime tilts add a separate optimization layer.
- **Live broker integration**: gated behind PRD M17.
- **Cross-fleet analytics** (multi-fleet portfolio): YAGNI. Single fleet supports current 2 candidates and scales linearly to 3-5 candidates.
- **Capacity / liquidity / slippage realism upgrades**: separate PRD per codex round-12 P4 line.
- **PIT data plumbing**: separate PRD per codex round-12 P1 line.

---

## 10. Open questions (for codex / user)

### Q1 — Core role cap consistency under N_core ≥ 2

If `core_min_capital_pct = 0.60` and we have 2 core candidates at equal weight, each gets 0.5, which is **below** core_min=0.6. Two reconciliation options:
- **Option A**: enforce `core_min_capital_pct` only for the **single highest-weighted core candidate**. Other core candidates can drop below core_min.
- **Option B**: rescale core_min by N_core, so for N_core=2 the effective floor per-core = 0.3.

PRD currently leans Option B (rescale) because it keeps fleet semantics consistent across N_core values. Codex / user input welcome.

### Q2 — Should v1 expose a benchmark-relative DD throttle (vs SPY) instead of absolute?

CLAUDE.md MaxDD rule is "not worse than SPY in crisis". An absolute -20% halt may misfire when SPY itself is at -25% (e.g. 2008/2020 crisis). PRD currently uses absolute thresholds for v1 simplicity; adding a benchmark-relative track would require fleet-level rolling SPY return tracking. Defer to v2 or include in v1?

### Q3 — Fleet manifest cadence: daily or weekly?

Per-candidate forward observation is daily. Fleet observation could be (a) daily (matches candidate cadence; manifest grows fast) or (b) weekly (smaller manifest; aggregates intra-week candidate changes). PRD currently leans daily for parity with candidate forward; codex / user input welcome.

### Q4 — Should allocator support a "shadow" mode?

Run allocator in compute-but-don't-act mode: produce fleet weight matrix + manifest but mark it as `shadow=True`. Lets us observe fleet-level evidence in parallel to live single-candidate paper before committing capital. Strong recommendation for v1; codex / user confirm?

---

## 11. Sequencing (when this lands)

Codex round-12 priority queue places this at #1-missing-macro after the now-completed first-real-forward-observe and active Acceptance Threshold Unification PRD. Suggested sequencing:

- **Now**: PRD draft committed and pushed to `review/claude-collab` for codex sign-off.
- **In parallel**: Acceptance Threshold Unification PRD continues review independently.
- **After codex sign-off**: implementation in 8-step sequence per §7, single change-set per step.
- **Before implementation**: pause for user explicit-go (CLAUDE.md "MUST PAUSE: changing core constraints" — adding a fleet layer changes the operational unit of decision; warrants user authorization).
- **First live run**: shadow mode (Q4) for at least 10 trading days before the fleet manifest can drive paper / forward decisions.

---

## 12. Pointer summary

- **Codex round-11** (origin priority): `docs/audit/20260428-codex_round_11_review.md` §B1
- **Codex round-12** (elevated to #1): `docs/audit/20260428-codex_round_12_priority_status.md` §"P2 candidate-fleet allocator"
- **Forward observe evidence** (parallel pattern reference): `docs/memos/20260428-forward_observe_first_real_after_v2_1_3.md`
- **Per-candidate forward PRD** (sister artifact): `docs/prd/20260427-forward_evidence_hardening_prd.md`
- **Concentration M12 contract** (consumed at fleet level): `docs/audit/20260428-ralph_audit_round_07.md` INV5

End of PRD draft.
