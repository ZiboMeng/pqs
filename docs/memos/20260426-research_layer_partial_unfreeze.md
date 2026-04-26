# Research Layer Partial Unfreeze — Memo (DRAFT)

**Status**: DRAFT — not yet authorized. User review pending; will not
take effect until user commits this memo with their explicit approval.

**Date drafted**: 2026-04-26
**Authority required**: user explicit (zibo)
**Supersedes (when committed)**: the "no new mining round" /
"no Candidate-3" / "no new factor" items in
`docs/memos/20260425-data_integrity_round3_close.md` §"What
remains frozen" — but **only** to the narrow extent specified below.

**Lineage tag (when committed)**: `research-unfreeze-2026-04-26`

---

> **Research unfreezes for stockpiling, not for shipping.**
>
> Mining is allowed to PRODUCE S0/S1 candidates. It is NOT allowed
> to PROMOTE any candidate to S2. The funnel is wide; the bar is
> fixed at pre-registered criteria; the paper-slot door stays
> closed unless the user explicitly opens it.

---

## 1. What is unfrozen

Two and only two things:

- **Mining** (`core/mining/`, TPE/Optuna search over factor
  combinations)
- **Factor research** (`core/factors/`, IC/IR analysis, factor
  candidate generation, LLM-assisted factor exploration)

Both at the **Research Layer level only** — outputs land at
state `S0_PROTOTYPE` or, when the artifact set below is complete,
`S1_RESEARCH_CANDIDATE`. Nothing here grants automatic advancement
to `S2_PAPER_CANDIDATE`.

## 2. What stays frozen (explicit, exhaustive)

Listing each item so future-you and future-Claude can grep for them:

- **Universe extension** — symbol set in `config/universe.yaml`
  remains the post-round-3-step-3b 78-symbol membership (BRK-B
  dropped). No new symbols, no new sectors, no new ETFs added to
  the tradable universe.
- **Candidate-3 direct-to-S2 path** — even if mining produces a
  great candidate, it cannot bypass the funnel into paper.
  Promotion to S2 is gated separately (see §4).
- **Current pair's frozen specs**: `rcm_v1_defensive_composite_01.yaml`
  and `candidate_2_orthogonal_01.yaml` remain immutable. The
  `frozen_spec.py` HARD invariant still holds.
- **Current pair's paper / forward observation track**: existing
  `data/paper_runs/` artifacts and
  `<id>_forward_manifest.json` files are append-only, untouched
  by anything in this unfreeze. The forward observation ritual
  (memory `feedback_forward_observation_ritual.md`) continues
  unchanged.
- **New PRODUCTION_FACTORS** — `core/factors/factor_registry.py
  ::PRODUCTION_FACTORS` remains 7-element. Research factors in
  `RESEARCH_FACTORS` may grow; promotion to PRODUCTION still
  requires a separate user decision.
- **New data tier** — no new intraday timeframe, no new vendor,
  no new data source.
- **`config/*.yaml`** — no edits to any config yaml.
- **`registry.db` schema** — no migration; rows can be added/
  updated within the existing 4-state machine.
- **`requirements*.txt` / `pyproject.toml`** — no new dependencies.

## 3. Research-unfreeze ≠ paper slot opens (the central rule)

This is the most important rule in this memo. State it bluntly:

> **The unfreeze grants permission to PRODUCE S0/S1 candidates.
> It does NOT grant permission to PROMOTE any candidate to S2.**

S2 promotion is gated by a separate condition set (§5 below) that
is **not** automatically satisfied by "mining ran and produced
something". Specifically:

- A new mining round can produce 0 nominees, 1 nominee, or many
  candidates that fail criteria. **0 is a normal outcome** (§6).
- Even when mining produces a valid S1 candidate, that candidate
  enters a **queue** for the next paper slot. The queue may stay
  closed indefinitely — at the discretion of the user reading the
  current pair's forward observation.
- The mere existence of "an unused paper slot capacity" does NOT
  open a slot. The user opens slots; mining does not.

Mental model: research is now allowed to **stockpile ammunition**.
Whether and when to **fire** is a separate decision.

## 4. Guards (G1-G4)

### G1 — Nominee cap

**At most 1 nominee per mining lineage_tag.** A mining run is one
"lineage" — one TPE study, one factor-search session, one
research_miner invocation. Across that lineage, only the single
candidate that scores highest against the pre-registered criteria
(§G2) is allowed to be nominated. **All other candidates from the
same lineage are demoted to dead silver — they may inform future
zero-shot exploration but never themselves become S2.**

This bounds the multiple-comparison problem at the lineage level.

### G2 — Pre-registered promotion criteria

**Before any mining begins**, the user (or Claude on user's behalf)
must:

1. Write `data/research_candidates/<lineage_tag>_promotion_criteria.yaml`
2. Compute its sha256 and record in commit message
3. Commit it BEFORE the mining script runs

The yaml has TWO sections with different semantics:

#### G2.A — Hard requirements (must-pass; gate the nomination)

A candidate that fails ANY of these is **not eligible** to be the
mining lineage's nominee. These are binary numeric thresholds.

- `min_ic_ir_full_period`: e.g. ≥ 0.30
- `min_walk_forward_folds_positive`: e.g. ≥ 3 of 4 folds positive
- `m12_concentration_tier_ceiling`: e.g. `warning` (so candidates
  hitting `manual_review_required` are NOT eligible)
- `watchlist_total_share_ceiling`: e.g. ≤ 0.30
- `thin_data_weighted_share_ceiling`: e.g. ≤ 0.10 (matches PRD v3
  §C extreme threshold; weighted not binary, per M12 audit fix)
- `panel_cutoff_max_date`: must be ≤ 2024-12-31 (G4 hard-locked)
- `universe_panel_mask_spec`: full panel/universe/mask declaration
  (immutable for this lineage)

Failing any ⇒ candidate cannot be nominated. Period.

#### G2.B — Report-only / interpretive fields (must-report; do NOT gate)

These must be present in the criteria yaml AND in the candidate's
S1 artifact set. They inform interpretation but do NOT singly
gate promotion. Reviewers use them to form qualitative judgement
on whether a hard-pass nominee should actually advance.

- `regime_stability_per_regime_ir`: per-regime IR breakdown
  (BULL / BEAR / RISK_ON / RISK_OFF / CRISIS / SIDEWAYS); just
  reported, no per-regime threshold
- `benchmark_beta_statistics`: portfolio-weighted mean β /
  std β / max |per-symbol β|; reported only
- `pseudo_oos_robustness_window_summary`: cum_ret / sharpe /
  max_dd / vs_spy / vs_qqq over the pseudo-OOS window; reported
- `turnover_proxy`: monthly turnover estimate; reported
- `correlation_vs_existing_pair`: composite-vs-RCMv1 and
  composite-vs-Cand-2 correlations; reported (high correlation =
  poor diversification, but not a hard reject because
  diversification value is context-dependent)

Once committed, **both sections** of the criteria are immutable
for that lineage. If criteria turn out to be too lax or too
strict in hindsight, the next lineage gets new criteria; the
current lineage's bar does not move.

### G3 — Current pair displacement guard

While `rcm_v1_defensive_composite_01` or `candidate_2_orthogonal_01`
have `current_status: in_progress` in their forward manifest, the
following are forbidden:

- Promoting a new candidate to S2 with the explicit or implicit
  intent of "replacing" the current pair
- Modifying any field in the current pair's paper run dirs or
  forward manifests under the rationale "the new candidate is
  better"
- Demoting (`S5_DEPRECATED`) the current pair before its 60TD
  decision checkpoint completes

A new candidate may co-exist at S2 alongside the current pair, but
co-existence is **additive, not replacement**. The current pair's
forward observation runs to its decision point regardless of new
candidate behavior.

**Explicit corollary**: the emergence of a new nominee does NOT
constitute automatic displacement rights over the current pair.
"We have a better candidate now" is not, by itself, a valid
argument to short-circuit RCMv1 or Cand-2's forward window. The
current pair earns its decision-point conclusion regardless of
how good or bad the next batch looks.

### G4 — Mining/research data cutoff (HARD)

**New candidates' research, mining, factor evaluation, and
backtest construction may use only data with date ≤ 2024-12-31.**

Calendar-year boundary chosen deliberately:

- it is more conservative than `< 2026-04-23` (the current pair's
  frozen-date), which would expose 2025-2026 to mining-time
  hindsight
- it is calendar-clean (one date, easy to enforce)
- it gives a 2025-01-01 → present holdout zone for testing the
  new candidate's pseudo-OOS — a real holdout because the data
  beyond 2024-12-31 was NOT used in construction (the user's
  hindsight contamination notwithstanding, the **construction
  process itself** is data-isolated)

Implementation: G4 is enforced by **memo + commit discipline only**.
Every commit that lands a new candidate's spec yaml or a mining
config must include the panel cutoff explicitly visible in the
diff; the reviewer (user / Claude) checks against ≤ 2024-12-31
before approving the commit.

Code-level enforcement (regression test, schema validator,
pre-commit hook) is **NOT** part of this unfreeze. If discipline
fails in practice — i.e., a commit makes it through with a wrong
cutoff — we'll add code-level guards then, not preemptively.

## 5. How a new candidate gets to a paper slot

Slot eligibility requires **all** of:

1. The candidate has a complete S1 artifact set:
   - `<id>.yaml` (frozen spec)
   - `<id>_promotion_criteria.yaml` (with hash matching pre-mining commit)
   - `<id>_robustness_window.yaml` + `<id>_robustness_eval.{json,md}`
   - `<id>_concentration_report.{json,md}` (passes promotion_criteria
     M12 ceiling)
2. The candidate's panel cutoff is ≤ 2024-12-31 (G4)
3. The candidate was the unique nominee from its mining lineage (G1)
4. **Either** of:
   - the current pair has reached its first decision checkpoint
     (10TD or beyond), AND R-fwd-2/3 are shipped or explicitly
     deferred again, OR
   - the user explicitly authorizes opening a paper slot
     independent of forward progress, **AND** the authorization
     is captured as a short decision memo committed to
     `docs/memos/<date>-<reason>.md`. A chat-only "go ahead" is
     **NOT** sufficient: the authorization must be persistent,
     reviewable, and grep-able in `docs/memos/`. Without the
     memo, the slot stays closed regardless of what was said in
     conversation.
5. No active "frozen" status on the user's side (i.e., user is
   not currently dealing with a higher-priority workstream that
   would compete for review attention)

Slot opening is a **user decision**, not a runner decision.

## 6. 0-nominee is a normal, valid outcome

Worth its own section because of how strong the temptation will
be to "just promote one" after a mining run.

A mining lineage that produces zero candidates passing pre-registered
criteria is:

- not wasted research — it negatively confirms current criteria
  + universe + factor space
- a meaningful "negative result" that informs the next round
- explicitly OK to commit the lineage with a closeout note saying
  "0 nominees; criteria intact; next round will explore X"

Under no circumstance is "we mined 200 trials and have to nominate
the best of them" acceptable. The criteria define the bar; if
nothing clears the bar, nothing clears the bar.

## 7. Forbidden cross-references

To prevent forward observation from leaking into new candidate
design via the user / Claude:

- Commit messages, memos, and `<id>_promotion_criteria.yaml` may
  NOT cite specific TD numbers from the current pair's forward
  manifests as design rationale.
- Phrases like "since RCMv1 underperformed in TD003-TD007, the new
  candidate adds defensive overlay X" are **forbidden**.
- The new candidate's design rationale must be derivable solely
  from data ≤ 2024-12-31 (G4) plus the static, pre-2025 academic
  / factor literature.
- This rule is enforced by **user discipline only** for now. No
  pre-commit hook, no greppy CI check — those are listed in
  Appendix A as future hardening ideas, NOT shipped with this
  unfreeze.

## 8. Re-freeze conditions

**This partial unfreeze is valid for ONE research cycle.**

A research cycle = one or more mining lineages governed by this
memo's authorization. The cycle ends when EITHER:

- the active nominee pipeline (one or more candidates produced
  during this cycle) has been **promoted to a paper slot** per §5
  conditions, OR
- the active nominee pipeline has been **explicitly rejected /
  archived** — either no candidate met G2.A criteria across all
  lineages this cycle, or all candidates were demoted /
  abandoned. Document the rejection / archive decision as a short
  closeout memo (per §9).

When the cycle ends:

- mining + factor research return to **frozen** state
- the next research cycle requires **fresh authorization**: a
  new partial-unfreeze memo (it can reuse this template but is
  a separate authorization event)

**Hard re-freeze triggers** (override the cycle definition; immediate
return to frozen state regardless of cycle progress):

- Detection of any G1-G4 violation in committed work
- User explicit re-freeze decision (committed memo)

## 9. Mining lineage commit hygiene

For each new mining lineage, the user / Claude must commit:

1. `<lineage_tag>_promotion_criteria.yaml` (BEFORE mining)
2. The mining run command / config
3. The mining run's output summary (number of trials, top scores,
   nominee or no-nominee status)
4. If a nominee: the full S1 artifact set
5. A closeout note in `docs/memos/<date>-<lineage_tag>_close.md`
   recording outcome + decision (queue for paper / 0-nominee /
   etc.)

The closeout memo is mandatory regardless of nominee status.

## 10. What this memo is NOT

- Not authorization to extend universe
- Not authorization to migrate the registry schema
- Not authorization to add new PRODUCTION_FACTORS
- Not authorization to modify cost_model.yaml or any config
- Not authorization to skip the S0 → S1 promotion gate
- Not authorization to open paper slot for any specific candidate
  yet — paper slot opening is a separate decision per §5.4

## 11. Forward observation ritual continues unchanged

The current pair's daily ritual (per memory
`feedback_forward_observation_ritual.md`) is the highest-priority
workflow and must not be deprioritized. New mining work is
strictly background to the forward observation foreground.

If the daily forward ritual and a mining run conflict for time /
attention, the daily forward ritual wins.

## 12. References

- Parking-lot P-001:
  `docs/memos/20260426-oos_parking_lot.md` (this memo's G4 implements
  the right-way reconstruction P-001 anticipated)
- Round-3 close (frozen items list this narrows):
  `docs/memos/20260425-data_integrity_round3_close.md`
- OOS MVP closeout (re-freeze status referenced):
  `docs/memos/20260425-oos_mvp_close.md`
- Forward runner PRD (current pair's protected workstream):
  `docs/prd/20260426-forward_oos_runner_prd.md`
- M12 audit decision (concentration gate that promotion criteria
  must call):
  `docs/memos/20260425-m12_review_decision.md`
- Forward observation ritual:
  `~/.claude/projects/-home-zibo-Documents-projects-pqs/memory/feedback_forward_observation_ritual.md`

## 13. One-line summary

**Mining unfreezes for stockpiling, not for shipping. The funnel
is wide, the bar is fixed at pre-registered criteria, and the
paper-slot door stays closed unless the user opens it.**

---

**Awaiting user review.** Once approved, commit this memo with
message `research: partial unfreeze (mining + factor research only,
G1-G4 + paper slot gating)` and the unfreeze takes effect.

---

## Appendix A — Future hardening ideas (NOT shipped with this unfreeze)

Listed here so they're not lost; explicitly **out of scope** for
the current authorization. Add to a future unfreeze (or a
separate hardening PRD) only if discipline-only enforcement is
seen failing in practice.

- **G4 code-level enforcement**: regression test
  `test_new_candidate_panel_cutoff_2024_12_31` that loads any
  new frozen yaml under `data/research_candidates/` and asserts
  `panel_contract.evaluation_window_end <= 2024-12-31`; schema
  validator on the mining script's date range arg.
- **G7 pre-commit hook for forbidden TD-references**: a
  pre-commit grep over staged research-side commit messages and
  diffs flagging substrings like `TD\d{3}`, `forward.*cum_ret`,
  or quoting numbers from `<id>_forward_manifest.json`.
- **Promotion-criteria yaml validator**: pydantic schema for
  `<lineage_tag>_promotion_criteria.yaml` enforcing the §G2.A /
  §G2.B split + that hashes match commit-time hashes.
- **Registry `nominee_for_paper_slot: bool` column**: schema
  migration to track nominee state in registry.db rather than
  filesystem-only; rejected for current unfreeze because it
  would touch registry schema (frozen item).
