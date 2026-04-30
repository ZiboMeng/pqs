# Proposed solutions for Concerns A / B / E

**Date:** 2026-04-30
**Status:** Proposal. Not implemented. **Awaits external-reviewer
alignment** before code lands. Once aligned, these become
implementation specs.
**Owner:** Claude (per user 2026-04-30 — codex unavailable; user
will discuss with external reviewer; consensus → start)
**Companion to:**
- `docs/memos/20260430-pre_track_c_strategic_concerns.md` (problem
  statements);
- `docs/memos/20260430-rcmv1_cand2_realized_correlation.md`
  (evidence).

For each concern I give:
1. **Minimum viable** version (just-enough to clear the boundary).
2. **Full** version (what we'd want long-term).
3. **Migration / legacy compatibility** path.
4. **Test plan** outline.
5. **Risks / edge cases**.
6. **Effort estimate**.

Reviewer should pick MV vs Full per concern, or counter-propose.

---

## Self-audit summary (4 rounds, per `docs/checkpoints/20260430-self_audit_methodology.md`)

This proposal went through 4 audit rounds before being submitted
for reviewer alignment. Findings + fixes applied:

| Round | Findings | Severity | Fix |
|------:|----------|----------|-----|
| R1 (factual) | `evidence_class` field collision: `ForwardRunManifest` enforces `evidence_class == EvidenceClass.forward_oos` (line 437), so re-using that field for legacy reclassification fails schema validation | **BLOCKER** | §A.MV rewritten to use a NEW `decay_classification` field (sibling of `evidence_class`), not override |
| R1 | RCMv1 yaml lacked `realized_nav_correlation_status` block; only Cand-2 had it. Asymmetric labeling on a finding that's symmetric by definition | **BLOCKER** | Added matching block to `data/research_candidates/rcm_v1_defensive_composite_01.yaml` (this round, not deferred) |
| R1 | `early_attention_first_triggered_td` was a redundant stored field | minor | Removed; derive at read time |
| R1 | `historical_dd_distribution` reference handwaved data shape | minor | Specified pd.Series of MaxDD positive magnitudes from rolling-60d windows over candidate paper history |
| R2 (logical) | NAV orthogonality threshold imported `0.40` from factor-IC config; realized NAV in long-only US equity has higher market-beta correlation floor — 0.40 is structurally over-strict | **important** | Revised to tiered: < 0.50 true / 0.50-0.70 partial / 0.70-0.85 warn / ≥ 0.85 reject (mirrors Step 5 with extra 0.50 gate) |
| R2 | Order "E → A+B parallel" — was wrong critical-path reading. A is the FARTHEST blocker (sealed eval is months out), not parallel-with B | **important** | Revised to "E → B → A" with critical-path diagram |
| R2 | 4.5-day effort estimate was nominal MV only | medium | Added realistic 2x multiplier (~9 days) based on this round's empirical audit-fix yield |
| R3 (runtime) | All 7 numerical claims in NAV correlation memo verified against JSON artifact (4-decimal match) | clean | — |
| R3 | Independent numpy path computation matched script pearson to 6 decimal places | clean | — |
| R3 | `FleetConfig` + `FrozenStrategySpec.from_yaml_file` + `ForwardRunManifest` all parse modified yaml/json files | clean | — |
| R3 | `FleetAllocator.check_correlation_budget` exercised with synthetic 0.898 input → correctly classifies `reject` (matches Step 5 enforcement) | clean | — |
| R4 (boundary) | Empty input → `AttributeError: 'float' has no attribute 'date'` (try `.date()` on NaN min) | **BLOCKER (runtime bug in script)** | Added `_empty_diagnostic` helper + early-return for n=0 / n<2 / non-finite pearson |
| R4 | n=1 → silent NaN pearson (mathematically undefined) | important | Same fix as above; explicit `status=insufficient_data` with reason |
| R4 | Zero-variance constant series → silent NaN + RuntimeWarnings | important | `np.errstate` + `warnings.catch_warnings` suppression; `np.isfinite` guard returning insufficient_data |
| R4 | json.dumps default `allow_nan=True` could let NaN through | medium | Set `allow_nan=False` to fail loud if any NaN slips past structured guards |
| R4 | NaN injection (10/80) handled correctly via `dropna` | clean | — |
| R4 | Missing benchmark file raises `FileNotFoundError` | clean | — |

The diagnostic script (`dev/scripts/correlation/rcmv1_cand2_realized_nav_correlation.py`)
is now corner-case-hardened. Production data still produces the
same 0.898 pooled / `reject_step5` classification.

The proposals themselves (A.MV / B.MV / E.MV) are unchanged in
substance after R3+R4 — those rounds caught script bugs, not
proposal logic gaps.

---

## Concern A — 2026 sealed-eval double-dip guard

**Problem.** `sealed_ledger.SealedLedgerEntry` records
`panel_max_date` but not the eval window. A future Track C nominee
could go through 2026 sealed eval whose calendar window overlaps
forward-observed 2026 windows of RCMv1 / Cand-2 (or any earlier
candidate). The 2026 holdout would be partially "tainted" without
the ledger noticing.

### A.MV — Minimum viable (recommended for first ship)

**Scope.** Schema extension + pre-flight overlap check + legacy
backfill helper.

**Schema additions to `SealedLedgerEntry`** (backwards compatible —
new fields default-empty for legacy rows):

```python
@dataclass
class SealedLedgerEntry:
    # Existing fields...
    split_name: str
    split_sha256: str
    candidate_spec_sha256: str
    role: str
    git_sha: str
    panel_max_date: str
    evaluation_timestamp_utc: str
    result_metrics_sha256: str
    extra_json: str = ""

    # NEW (PRD-A 2026-04-30)
    eval_start_date: str = ""        # YYYY-MM-DD; "" for legacy rows
    eval_end_date: str = ""          # YYYY-MM-DD; "" for legacy rows
    evidence_class: str = "sealed"   # "sealed" | "legacy_forward_evidence" | "legacy_pre_prd_a"
```

**Pre-flight `check_eligibility` extension** (revised per reviewer
§5.3 2026-04-30 — replaces the lineage_family-only formulation
which was the wrong abstraction). Two layered rules:

```
RULE 1 — fail_closed_on_freeze_date_violation (HARD):
  Given (spec_sha256, split_name, role, eval_start_date,
         eval_end_date, candidate_freeze_date,
         panel_max_date_recorded_at_freeze):
    Required:
      eval_start_date > candidate_freeze_date
      eval_start_date > panel_max_date_recorded_at_freeze
    Otherwise → SealedEvalDeniedError(
        rule="sealed_eval_window_overlaps_known_panel",
        details=[freeze_date, panel_max_date])

RULE 2 — flag_market_path_preobserved (SOFT, NOT a hard fail):
  For every forward run on ANY candidate (regardless of lineage)
  whose observed dates overlap [eval_start_date, eval_end_date]:
    Stamp the resulting sealed entry with:
      market_path_preobserved = True
      preobserving_candidates = [list of candidate_ids]
      preobserving_runs = [list of forward_run pointers]
    Stamp does not block; it labels evidence_class for audit:
      evidence_class = "partially_tainted_sealed" (vs "clean_sealed")
```

**Why this replaces lineage_family:**

- The old "lineage_family" abstraction tried to scope contamination
  to "same family" candidates. But contamination is broader: as a
  human, observing a 2026 market window biases my research direction
  even if I select a structurally different candidate next.
- The freeze-date rule is the operational invariant: a candidate
  cannot be sealed-eval'd over a window that ended before it was
  defined. This catches the most common error path — looking back.
- The market-path-preobserved flag captures the softer truth that
  any 2026 window already observed by humans on ANY active forward
  is partially tainted as "clean OOS" — without preventing reasonable
  use, but documenting it explicitly so audit can weigh it.

**Operational consequence (today, 2026-04-30):** any Track C
candidate that freezes today CANNOT use 2026-Q1 + April 2026 as a
clean sealed window. The reachable clean window starts 2026-05-01
at earliest (and only if no human-research uses 2026-Q2 data
between now and freeze). The operational unit is "remaining
unseen window after freeze", NOT "2026 calendar year".

**Legacy backfill helper.**
`dev/scripts/sealed_ledger/backfill_eval_windows.py` — opt-in CLI
that walks existing ledger rows and stamps:

```
evidence_class = "legacy_pre_prd_a"
migration_note = "backfilled_2026-04-30_assumed_unchanged"
```

Pre-PRD-A rows do not get retroactive eval_start/end_date —
they're marked legacy and skipped by the new overlap check
(matches PRD-F lazy-migration pattern).

**Forward manifest reclassification.** Two existing
`*_forward_manifest.json` files (RCMv1 + Cand-2) gain a top-level
**new field** (NOT a change to `evidence_class` — that field is
schema-locked to `forward_oos` per `core/research/robustness/window_spec.py`
EvidenceClass enum and `ForwardRunManifest._check_evidence_class`):

```json
"decay_classification": {
  "label": "legacy_decay_verification",
  "reclassified_at_utc": "2026-04-30T...",
  "reason": "pre-Track-A nomination; pre-G2.A 30% concentration ceiling; pre-M12 weighted thin-data fix; NAV-correlation 0.898 confirmed risk-clone of fleet partner",
  "evidence_memo": "docs/memos/20260430-rcmv1_cand2_realized_correlation.md"
}
```

The new field is a sibling of `evidence_class` (which stays
`forward_oos` per schema), pydantic-additive (extends
ForwardRunManifest with `decay_classification: Optional[DecayClassification] = None`).
Set ONCE, immutable thereafter (any change requires explicit
user-go).

For Cand-2 the corresponding `realized_nav_correlation_status`
block shipped on `data/research_candidates/candidate_2_orthogonal_01.yaml`
at commit `ffd4793`. The symmetric block on
`rcm_v1_defensive_composite_01.yaml` shipped at `main 8f46bc4`
(R1 audit caught the asymmetric labeling and fixed it in the same
audit cycle).

### A.Full — what we'd want long-term

- Ledger overlap check generalizes to ANY holdout window, not just
  2026 sealed.
- Audit log of every sealed-eval pre-flight rejection (per-
  rejection memo template).
- A "sealed budget" concept: the holdout calendar interval has a
  total budget (e.g. "2026 has 252 trading days; we will permit
  at most N of those days to be observed by any candidate before
  the 2026 sealed window is considered globally tainted and the
  framework must move to a 2027 sealed window").

A.Full is overkill for MV. Recommend ship A.MV; revisit A.Full
post-Track-C cycle.

### A — Migration

- Existing ledger rows: 0 (sealed eval has not run yet — verified
  by `ls data/research_candidates/sealed_eval_ledger.parquet`
  showing no file). So MV migration is trivial: new columns get
  added on first write.
- RCMv1 + Cand-2 forward manifests: opt-in reclassification script
  per-candidate (not auto-run).

### A — Test plan

| Test | Expected |
|------|----------|
| First sealed eval write — schema gains new fields | Ledger has `eval_start_date` / `eval_end_date` / `candidate_freeze_date` / `panel_max_date_recorded_at_freeze` / `evidence_class` columns |
| `check_eligibility` with `eval_start_date > candidate_freeze_date` AND no forward overlap | Allowed; evidence_class = `clean_sealed` |
| `check_eligibility` with `eval_start_date <= candidate_freeze_date` | `SealedEvalDeniedError(rule="sealed_eval_window_overlaps_known_panel")` raised, details list freeze and panel-max dates |
| `check_eligibility` with valid freeze date BUT forward observation overlap (any lineage) | Allowed; evidence_class = `partially_tainted_sealed`; preobserving_candidates field populated |
| `check_eligibility` with valid freeze date AND no forward overlap | Allowed; evidence_class = `clean_sealed` |
| Legacy-only ledger (pre-PRD-A rows + new entry) | New rules do not double-trip on legacy rows (lazy-migration) |
| Backfill script idempotency | Re-running produces no additional rows |

### A — Risks / edge cases

- **`candidate_freeze_date` field stamping:** new field on candidate
  spec yaml stamped at freeze time. Must be recorded by `init`-time
  flow; cannot be backdated. Stamping logic lives next to existing
  `frozen_at` / `panel_max_date` resolution in `frozen_spec.py`.
- **Forward observation can extend after sealed eval is recorded.**
  Need `check_eligibility` to look forward in time, not just
  backward. Solution: forward manifest reclassification (above) pins
  the observed interval at reclassification time; new TDs after
  reclassification cannot extend.
- **Market-path-preobserved by humans not in any manifest:** a human
  may observe market paths informally (e.g. reading news during 2026)
  without that being in any forward manifest. The SOFT rule only
  catches pre-observation captured in forward runs. This is a known
  audit gap; for a personal-quant repo (single user, honest research
  posture) it's acceptable. Multi-user / regulated context would need
  a separate human-attestation log.
- **`evidence_class` and `decay_classification` are not crypto-locked.**
  A motivated user could re-edit. Personal-quant repo; acceptable.

### A — Effort

| Step | Effort |
|------|--------|
| Schema extension (sealed ledger + spec yaml) + write/read paths | 0.5 day |
| Pre-flight rule 1 (HARD freeze-date) + rule 2 (SOFT market-path) | 0.5 day |
| Legacy backfill script + forward manifest reclassification helpers | 0.5 day |
| Tests (~12 cases per the plan) | 0.5 day |
| **Total** | **~2 days** (nominal MV); ~4 days realistic with audit-fix cycles |

---

## Concern B — Forward TD60 cadence vs risk management (Tier 1 only)

**Problem.** Forward runner protocol is daily observe + TD60
decision pack. There is no early-attention signal at TD15-TD40 even
when MaxDD is materially deteriorating. Suitable for paper /
observation; unsafe for any pre-promotion candidate that might
enter live wiring.

### B.MV — Tier 1 only (recommended for first ship)

**Scope.** Add a `early_attention_required` flag to forward run
records. Report-only. **Does NOT change `current_status`.**

**Schema additions to `ForwardRun` model:**

```python
class ForwardRun(BaseModel):
    # Existing fields...
    early_attention_required: bool = False
    early_attention_reasons: List[str] = []  # list of trigger names
```

(`early_attention_first_triggered_td` is intentionally NOT a stored
field — derive at read time as `next(r.checkpoint_label for r in
manifest.runs if r.early_attention_required)`. Avoids a redundant
field that could drift from `runs[].early_attention_required`.)

**Trigger evaluator** — pure function called inside `observe()`
after the new TD is appended:

```python
def evaluate_early_attention(
    *,
    runs: List[ForwardRun],
    candidate_spec: dict,
    historical_dd_distribution: Optional[pd.Series] = None,
) -> Tuple[bool, List[str]]:
    """Returns (should_flag, list_of_trigger_names).

    All triggers OR'd together. Any one trigger sets the flag.

    DISPATCH: legacy candidates (decay_classification ==
    "legacy_decay_verification" per A.MV) skip B.MV entirely.
    They're observation-only; their early-attention signal would
    never trigger an action. This is cleaner than carrying a
    "T4_legacy fallback" code path which is the same failure
    mode reviewer §6 originally flagged (raw vs_benchmark
    underperformance is structurally beta-explained for high-β
    strategies).
    """
    decay_class = (candidate_spec.get("decay_classification") or {}).get("label")
    if decay_class == "legacy_decay_verification":
        return (False, [])  # SKIP — see dispatch comment above

    triggers = []

    last = runs[-1]
    n_tds = len(runs)

    # T1: forward MaxDD ≥ 75% of validation-year MaxDD ceiling
    val_max_dd_ceiling = candidate_spec.get("validation_max_dd_ceiling", 0.20)
    if last.max_dd >= 0.75 * val_max_dd_ceiling:
        triggers.append("forward_maxdd_above_75pct_validation_ceiling")

    # T2: forward MaxDD ≥ 95th percentile of historical 60d rolling DD.
    # historical_dd_distribution is a pd.Series of float MaxDD values
    # (positive magnitudes), one per rolling 60-trading-day window over
    # the candidate's pre-forward paper / backtest history. Source for
    # Track C nominees: rolling MaxDD computed from train-period
    # acceptance evaluator's per-fold NAV series. For RCMv1 / Cand-2
    # legacy: rolling MaxDD from concatenated paper-cell pnl_daily.csv
    # (the same source the NAV correlation script uses). When the
    # series has fewer than 30 windows (rare; only relevant for
    # candidates with very thin paper history), T2 is skipped silently
    # — the candidate isn't yet stable enough to baseline.
    if historical_dd_distribution is not None and len(historical_dd_distribution) >= 30:
        p95 = float(historical_dd_distribution.quantile(0.95))
        if last.max_dd >= p95:
            triggers.append("forward_maxdd_above_95p_historical_60d")

    # T3: cumulative TD return ≤ -8%
    if last.cum_ret <= -0.08:
        triggers.append("cum_return_below_minus_8pct")

    # T4: beta-adjusted residual underperformance (per reviewer §6
    # 2026-04-30). Raw `vs_spy < -0.05 and vs_qqq < -0.05` was too
    # crude — high-beta strategies (β-SPY 1.3-1.6 like RCMv1+Cand-2)
    # naturally show large negative vs_spy in market drawdowns even
    # when alpha is intact. The relevant signal is whether the
    # strategy underperforms WHAT BETA WOULD PREDICT.
    #
    # estimated_beta_to_spy: stamped at candidate freeze time by
    # Track A acceptance, computed from train+validation NAV vs SPY.
    # Required field for new candidates. Legacy candidates with
    # decay_classification="legacy_decay_verification" already
    # short-circuited B.MV at function entry above. Any new candidate
    # missing this field is a Track A acceptance bug, not a fall-
    # through case — fail loud rather than silently downgrade gate.
    if candidate_spec.get("estimated_beta_to_spy") is None:
        raise ValueError(
            f"candidate {candidate_spec.get('candidate_id')!r} missing "
            f"estimated_beta_to_spy; B.MV trigger T4 requires this stamped "
            f"by Track A acceptance at freeze. (Legacy candidates with "
            f"decay_classification='legacy_decay_verification' should have "
            f"been short-circuited at function entry.)"
        )
    if last.vs_spy is not None and last.cum_ret is not None:
        beta = candidate_spec["estimated_beta_to_spy"]
        spy_cum = last.spy_cum_ret if hasattr(last, "spy_cum_ret") else None
        if spy_cum is not None:
            beta_explained = beta * spy_cum
            residual = last.cum_ret - beta_explained
            if residual < -0.05:
                triggers.append(
                    "beta_adjusted_residual_underperformance_below_minus_5pct"
                )

    # T5: data drift event AND PnL deterioration co-occur on same TD
    if last.data_revision_event is not None and last.cum_ret < runs[-2].cum_ret if len(runs) >= 2 else False:
        triggers.append("data_drift_event_with_pnl_deterioration")

    return (len(triggers) > 0, triggers)
```

**Surfacing.**
- Daily observe log INFO line: `early_attention_required=True
  reasons=[...]` when set.
- Forward manifest record persists the flag.
- Notify module `info()` call when first triggered — wechat_bot
  channel default-on if configured, otherwise stdout.
- README forward-observation section gets a one-paragraph note
  about what early-attention means.

### B.Full — Tier 2 (deferred, for live wiring)

- `current_status` transitions: `active` → `parked` (auto on T2/T3
  trigger thresholds) → `removed` (manual user-go).
- Co-design with Fleet Step 6 DD-throttle and KillSwitch state
  machine.
- Per-trigger configurable thresholds in `config/forward.yaml`.
- Multi-trigger AND-mode (require ≥ 2 triggers within N TDs) for
  reduced false-positive rate at status-change level.

B.Full is the "before live money" version. NOT this round.

### B — Migration

- 2 existing forward manifests (RCMv1 + Cand-2): on first
  PRD-B-aware `observe()` call, lazy-migrate by setting
  `early_attention_required=False` on existing runs (no
  retroactive flag inference).
- Historical DD distribution: source from cell-level
  `pnl_daily.csv`. Rolling 60d DD computable from existing
  artifacts; no schema change there.

### B — Test plan

| Test | Expected |
|------|----------|
| New TD with no triggers | flag=False, reasons=[] |
| Each individual trigger T1-T5 | flag=True, reasons contains expected name |
| Multi-trigger TD | flag=True, reasons contains all matched |
| Lazy migration on legacy manifest | new TDs get evaluated; old TDs untouched |
| Notify integration | one info call on first trigger, no duplicate calls on repeated triggers |
| Idempotency | re-running observe with no new bar produces no new flags |

### B — Risks / edge cases

- **T5 data-drift trigger** uses `data_revision_event` from PRD F+
  v2.1.3 hardening; works only when manifest is post-PRD-F. Legacy
  pre-PRD-F manifests skip T5 silently (logged at DEBUG). User
  has not yet run the PRD-F backfill on RCMv1 + Cand-2 (per
  CLAUDE.md note); T5 will activate post-backfill.
- **T2 historical_dd_distribution** requires the candidate to have
  ≥ 30 days of historical paper data. New Track C candidates would
  have train+validation panel data (~10 years), so this trigger is
  always available for them.
- **False positive rate** unknown. Expectation: T3 (cum return ≤
  -8%) is the conservative trigger; T1/T2 are the ones we expect to
  fire most. Reviewer may argue thresholds are too strict (early-
  attention spam) or too loose (real DD slipping through). I lean
  to start strict + relax if false-positive volume is high.

### B — Effort

| Step | Effort |
|------|--------|
| Schema extension on ForwardRun + lazy migration path | 0.5 day |
| `evaluate_early_attention` + tests | 0.5 day |
| Notify integration | 0.25 day |
| README + observe-log surfacing | 0.25 day |
| **Total** | **~1.5 days** |

---

## Concern E — Economic-invariant test gap

**Problem.** ~1850 unit tests cover code-correctness but not
economic-assumption correctness. Track C nominee evidence packs
should embed the minimum-viable invariant matrix without building a
new framework.

### E.MV — Embed in Track C evidence pack template (recommended)

**Scope.** Two new sections in
`docs/templates/track_c_evidence_pack_template.md`:

**§4.6 NAV-level orthogonality (REQUIRED for any non-first-fleet
candidate).** Re-uses the diagnostic from
`dev/scripts/correlation/rcmv1_cand2_realized_nav_correlation.py`.

**Threshold methodology revision (audit Round 2):** The original
draft used 0.40 (matching `temporal_split.yaml` line 111
`vs_existing_core_correlation`). That config field is for
**factor-IC** correlation, where 0.40 is a reasonable
orthogonality bar. **At the realized-NAV level in long-only US
equity, all strategies share a market-beta baseline that floors
realized correlation around 0.30-0.50 even for genuinely
orthogonal alpha sources.** Reusing 0.40 for NAV would push
candidates into a band where the threshold cannot be passed by
construction (a long-only momentum and a long-only value will
both correlate at ~0.4-0.6 simply because they're both
long-the-market-on-net). Adopt Step 5's tiered structure:

| Metric | Pooled Pearson tier | Action |
|--------|---------------------|--------|
| < 0.50 | true_diversifier | proceed |
| 0.50 - 0.70 | partial_diversifier | warning; reviewer judgment; require explicit role-justification in pack |
| 0.70 - 0.85 | warn | label_void (cannot claim diversifier role); pack must justify why this candidate adds value despite high correlation |
| ≥ 0.85 | reject | matches Step 5 reject; nominee not eligible for fleet entry |

Adjacent diagnostics (FLAG only, not gates):

| Metric | Threshold for "clean" | Action if violated |
|--------|--------------------------|--------------------|
| Down-market (SPY < -0.5%) Pearson | < 0.50 | warning |
| Drawdown overlap (% days both in DD) | < 50% | warning |
| Top-10 holdings overlap on cell-final date | ≤ 4/10 | warning |
| Rolling 30d Pearson worst-case | < 0.65 | warning |

The pooled-Pearson tier is the **gate**; the adjacent diagnostics
are **flags** requiring justification per flag, not auto-rejection.

A nominee that lands in `partial_diversifier` (0.50-0.70) is NOT
auto-rejected — it can still be claimed as a diversifier IF the
pack carries explicit justification (e.g. down-market corr <
0.30, drawdown overlap < 30%). A nominee in the `warn` tier
(0.70-0.85) cannot claim diversifier role at all, only
core-additive role.

**§4.7 Economic-assumption flags (REQUIRED, FLAG-only).** Track C
evidence pack must have a table:

| Flag | Method | Track C nominee value |
|------|--------|----------------------:|
| factor_ic vs nav_corr gap | Compute factor-level IC corr vs realized NAV corr against same RCMv1 panel | `<float>` |
| defensive claim vs realized β-SPY | If "defensive" appears in nominee description, β-SPY must be < 1.0 | `<float>` |
| diversifier claim vs pooled NAV corr | If role=diversifier, pooled NAV corr vs every active core must be < 0.50 (true_diversifier tier per §4.6 audit-Round-2 revision) | `<float>` |
| QQQ excess concentration | % of vs-QQQ excess attributable to top 3 names + TQQQ + SOXL | `<float>` |
| 2025 hard pass + 2023 fail | If 2025 acceptance passes but 2023 fails, mark regime-dependent | `<bool>` |

These are **flags, not gates**. Each row that flags requires one
sentence of explanation in the pack. A nominee with all flags
clear is "economically clean"; a nominee with multiple flags is not
auto-rejected but must justify each.

### E.Full — invariant test framework in code (deferred)

- A `tests/economic/` test directory with three categories:
  - `tests/economic/accounting/` (HARD FAIL): long-only ≥ 0,
    row-sum ≤ 1.0, cash consistency, signal-before-execution,
    stale-price preservation;
  - `tests/economic/risk_stats/` (HARD FAIL): MaxDD non-negative
    + monotone, Sharpe formula consistent, benchmark sign
    consistency, stress-not-pooled;
  - `tests/economic/assumptions/` (FLAG): all the §4.7 flags but
    runnable across the full repo, not just per-evidence-pack.
- pytest mark `economic_invariant` so they can run separately.
- CI hook (low priority for personal repo).

E.Full is post-Track-C-cycle work. NOT this round.

### E — Migration

- No migration. New template sections are additive. Existing pack
  template (post-R30 fixes) absorbs §4.6 and §4.7 without
  affecting §1-§4.5.
- Existing candidates (RCMv1 + Cand-2) do NOT need retroactive
  evidence packs (they were nominated pre-Track-A and are now
  legacy decay verification).

### E — Test plan

- Template syntax check (markdown, headings, table rendering).
- A mock evidence pack filled out for a hypothetical nominee
  passes / fails sentinel rows correctly.
- §4.6 + §4.7 reference the same script paths
  (`dev/scripts/correlation/rcmv1_cand2_realized_nav_correlation.py`)
  to ensure single-source-of-truth.

### E — Risks / edge cases

- **Template inflation.** Adding two more sections to an already-
  long template raises completion friction. Mitigation: §4.6 + §4.7
  share most of their inputs with the NAV-correlation script
  output JSON, so a Track C nominee can populate both sections from
  a single script run.
- **Threshold drift.** §4.6 / §4.7 thresholds will probably need
  recalibration after the first Track C cycle observes real
  numbers. Plan for that explicitly: any threshold tightening or
  loosening must bump the pack template version field
  (`version: 1.0` → `1.1`) and reference a memo.
- **Reviewer fatigue.** Each new section adds reviewer load. Reviewer
  may want a "skip §4.7 if all factor IC < 0.05" shortcut.
  Counter: §4.7 is exactly when low-IC composites become NAV-
  correlated through universe / weighting. Skipping it on low-IC
  compositions is the failure mode we're trying to catch.

### E — Effort

| Step | Effort |
|------|--------|
| Draft §4.6 + §4.7 sections | 0.5 day |
| Update NAV correlation script to emit pack-ready table format | 0.25 day |
| Adjust evidence-pack version stamp | 0.1 day |
| Mock-pack walkthrough + reviewer sanity check | 0.25 day |
| **Total** | **~1 day** |

---

## Cross-concern integration

**Order revised audit Round 2:** trace each blocker by critical path
distance from "now":

```
Track C dry run starts
  ↓
nominee passes acceptance (no guard needed)
  ↓
evidence pack drafted          ← E.MV blocks here (closest)
  ↓
external review of pack
  ↓
forward init for nominee       ← B.MV blocks here (medium)
  ↓
TD60 decision pack
  ↓
... weeks later ...
  ↓
2026 sealed eval               ← A.MV blocks here (farthest)
  ↓
fleet wiring expansion         ← B.Full + E.Full block here
  ↓
real-money deployment          ← all three blocks here
```

| Order | Concern | Distance from now | Why this order |
|-------|---------|-------------------|----------------|
| 1 | E.MV (template §4.6 + §4.7) | T+0 (drafted concurrently with dry run) | Cheapest; first blocker; can be shipped while dry run is computing |
| 2 | B.MV (early-attention flag) | T+1 to T+2 weeks (forward init) | Second blocker; needed before any nominee starts forward observation |
| 3 | A.MV (sealed ledger overlap guard) | T+3 months (forward TD60+ → sealed eval consideration) | Farthest blocker; sealed eval is many weeks downstream of forward init |
| 4 | A.Full / B.Full / E.Full | Post-first-Track-C-cycle | After we have real evidence about what guards actually matter |

(Original draft had A and B in parallel after E. R2 audit corrected
to "E → B → A": A is the FARTHEST blocker on the critical path;
parallel shipping with B was over-eager.)

**Effort estimates — nominal vs realistic:**

| Concern | Nominal MV effort | Realistic with audit-fix cycles (2x) | Realistic wall clock |
|---------|------------------:|--------------------------------------:|---------------------:|
| E.MV | 1 day | 2 days | 2-3 days |
| B.MV | 1.5 days | 3 days | 3-4 days |
| A.MV | 2 days | 4 days | 4-5 days |
| **Total** | **4.5 days** | **9 days** | **~2 weeks if sequenced; ~1 week if E + B can overlap with separate sub-tasks** |

The 2x audit-fix multiplier is empirical (from this round: my own
proposals memo R1 found 2 BLOCKERs + 2 minors; R3 found 0 bugs in
production data path but R4 found 3 runtime bugs in the diagnostic
script — pattern is "first cut works on happy path, real
robustness needs ~1 cycle of corner-case fixes").

**Track C cycle compute is NOT blocked on E.MV / B.MV / A.MV; but
nomination IS blocked on E.MV** (per reviewer §5.1 sharper boundary,
2026-04-30):

> Mining compute can run concurrent with E.MV drafting. But until
> §4.6 NAV-orthogonality + §4.7 economic-flag sections are in the
> Track C evidence pack template, any candidate that passes
> acceptance is "candidate pending economic-invariant pack" — NOT
> a "nominee". Nomination requires the pack to be filled; pack
> requires §4.6 + §4.7 to be defined.

This rephrasing is operationally cheaper than "wait for E.MV to ship
before mining": it lets the compute step happen in parallel with
template work without losing nomination discipline.

---

## Decisions taken from Q&A with reviewers (originally "open questions")

> Update 2026-04-30 R3: most original "open questions" now have
> explicit answers. Each entry shows status (decided / open) +
> rationale. Items still open are reviewer-blocking; decided
> items are recorded for audit, not for further debate.

### Q1 (decided) — A.MV scoping abstraction

**Decision**: replace lineage_family with two-rule freeze-date HARD
+ market-path-preobserved SOFT structure.

**Rationale**: lineage_family was the wrong abstraction (per reviewer
§5.3, 2026-04-30). Sealed-eval contamination is broader than same-
candidate observation; the operational invariant is "candidate cannot
sealed-eval over a window that ended before it was defined".
Implementation in §A.MV.

### Q2 (decided) — B.MV trigger thresholds

**Decision**: keep strict thresholds at MV ship: T3 = -8% cum,
T1 = 75% of validation-year ceiling. T4 = beta-adjusted residual
underperformance < -5%.

**Rationale**: high-beta strategies (RCMv1+Cand-2 β-SPY 1.3-1.6)
need beta accounting before "underperformance" is alpha-meaningful.
Strict-then-relax-on-evidence is the right cycle order; loosening
without observation history is premature.

### Q3 (decided) — NAV orthogonality threshold structure

**Decision**: tiered 0.50 / 0.70 / 0.85 mirroring Step 5 with one
extra 0.50 gate.

**Rationale**: long-only US equity has a market-beta correlation
floor that makes flat 0.40 (factor-IC config) structurally over-
strict at NAV level. Tier structure verified by R3+R4 audit on the
diagnostic script. Reviewer §3 (2026-04-30) confirmed.

### Q4 (decided) — Order of ship

**Decision**: E → B → A by critical-path distance.

**Rationale**: A.MV is the FARTHEST blocker (sealed eval is
months out). B.MV is needed at forward init (~T+1-2w). E.MV is
concurrent with mining compute. Reviewer §5.2 (2026-04-30) confirmed.

### Q5 (decided) — Effort scheduling

**Decision**: 4.5 days nominal MV; ~9 days realistic with audit-fix
cycles (2x multiplier observed in this round). Accept the realistic
estimate; do not cut scope.

**Rationale**: the MV scope is genuinely minimum (no nice-to-have
sneak-in). A 2x multiplier is empirical, not pessimistic; subsequent
rounds should still aim for 1x but plan for 2x.

### Q11 (decided) — `panel_max_date_recorded_at_freeze` field design

**Decision**: NEW field, separate from `SealedLedgerEntry.panel_max_date`.

**Rationale**: the two values represent different audit moments:
- `panel_max_date_at_freeze`: data boundary visible to candidate at freeze
- `panel_max_date_at_eval`: data boundary at sealed-eval execution

Re-using a single field would conflate two semantics and structurally
weaken the freeze-date HARD rule (because eval-time panel max is
later than freeze-time, the constraint `eval_start > eval-time
panel max` is structurally weaker and may not catch the issue).

**Recommended naming** (final):
- spec yaml: `panel_max_date_at_freeze` + `candidate_freeze_date`
- ledger row: `eval_start_date` + `eval_end_date` + `panel_max_date_at_eval` (existing) + new `candidate_freeze_date_recorded_from_spec`

Hard rule:
```
eval_start_date > candidate_freeze_date
eval_start_date > panel_max_date_at_freeze
```

### Q12 (decided, with explicit pushback on auditor) — `estimated_beta_to_spy` legacy handling

**Decision**: SKIP B.MV entirely on `decay_classification: legacy_decay_verification` candidates; do NOT keep T4_legacy fallback in code; for new candidates, Track A acceptance auto-stamps `estimated_beta_to_spy` at freeze; backfill on legacy yamls is OPTIONAL spec-completeness hygiene (~30 sec, since betas already in NAV correlation JSON), not a B.MV operational requirement.

**Why this differs from the auditor's prescription**:

The auditor proposed: "legacy uses fallback raw -10%; no mandatory backfill". I disagree on the fallback path.

1. Raw -10% is the same failure mode reviewer §6 originally flagged
   ("high-beta strategies show large negative vs_benchmark in market
   drawdowns even when alpha is intact"). Tightening from -5% to -10%
   reduces false-positive rate but doesn't fix the structural problem
   (β-1.5 candidate hits -10.5% vs SPY on a SPY -7% day, purely from
   beta).
2. Keeping a known-wrong gate as fallback is a footgun: a future
   reader sees `T4_legacy` in code and treats it as the "safe
   default" for cases where beta isn't stamped — and might apply it
   to new candidates that fail to stamp due to a separate bug.
3. The cleaner architecture is *dispatch* on `decay_classification`,
   not *fallback* to a worse gate. Legacy candidates are
   observation-only; they're not getting promoted; their early-
   attention signals would never trigger an action. SKIP B.MV
   entirely on them.
4. The auditor's pragmatic point ("don't waste engineering on
   legacy") is correct as a principle but the implementation should
   be SKIP, not WRONG_FALLBACK. Both are zero-engineering-effort;
   one is structurally clean and one carries footgun risk.

**Concrete plan**:

- `B.MV` runner top of function: if `candidate.decay_classification == "legacy_decay_verification"`: return `(False, [])` (skip entirely).
- `T4_legacy` codepath: removed.
- `Track A` acceptance: when stamping spec yaml at freeze, compute β to SPY and β to QQQ from train+validation NAV vs benchmark, stamp `estimated_beta_to_spy` and `estimated_beta_to_qqq`.
- Legacy backfill on RCMv1+Cand-2: ✅ DONE 2026-04-30 (commit pending) as spec-completeness hygiene only — `estimated_beta_at_freeze` block added to both yamls with `used_by_b_mv: false` because B.MV short-circuits on `decay_classification=legacy_decay_verification`. Values pulled from `data/memos/20260430_rcmv1_cand2_realized_correlation.json` (RCMv1 β-SPY 1.41 / β-QQQ 1.13, Cand-2 β-SPY 1.50 / β-QQQ 1.23).

**B.Full upgrade path** (post-MV, pre-live-money): rolling beta
re-estimation from forward TDs once n_TDs ≥ 30; alert if rolling
beta deviates from freeze-time by ≥ 0.5; gate on this for any
status-change trigger.

### Items still open for reviewer

The above 7 items are decided. **Nothing in this proposal is
currently blocking on a reviewer answer.** Reviewer may still
challenge any of them; that's normal. But the proposal does not
pause for an answer.

---

## What I am NOT proposing

- New PRDs (these proposals fold into existing PRDs as v-bumps).
- Changes to acceptance gates / Track A split / Step 5 budget
  thresholds.
- Behavioral changes to RCMv1 / Cand-2 spec yamls beyond the
  NAV-correlation status block + the spec-completeness
  `estimated_beta_at_freeze` block (both shipped 2026-04-30,
  neither alters operational behavior — B.MV short-circuits on
  decay_classification).
- Pre-emptive Step 6+ work.
- A separate invariant-test framework directory under `tests/`
  (deferred to E.Full).

---

## My recommendation

E.MV ✅ shipped 2026-04-30 in template v1.1 (commit
`01d2950`); reviewer signoff pending. **A.MV + B.MV** still to
implement (~2 days each, can be parallelized). Track C cycle
#01 plan written and pre-registered criteria yaml drafted; real
mining compute starts post reviewer signoff on E.MV. Wall clock
from green-light on A.MV + B.MV: ~2-3 days to all three guards
landed; Track C cycle #01 result follows from there.

If reviewer disagrees on any of the four open questions, this
estimate adjusts but the structure does not.
