---
template: track_c_evidence_pack
version: 1.1
authorized_by: codex_round_27_boundary_memo + user_explicit_go_2026-04-29
revision_history:
  v1.0 (2026-04-29): initial template
  v1.1 (2026-04-30): added §4.6 NAV-orthogonality + §4.7 economic-assumption flags
                     per E.MV (concerns_abE_proposed_solutions.md) and reviewer §3 / §4.3.
                     Added sign-convention callout above §3.1, fixed MaxDD threshold table,
                     re-pointed C5 archive ref to RCMArchive, fixed leak-guard wording.
status: TEMPLATE — copy this file when nominating a controlled-mining candidate
---

# Track C controlled-mining nominee evidence pack — TEMPLATE

> **How to use this template.** Copy to
> `docs/memos/<YYYY-MM-DD>-track_c_<nominee_id>_evidence_pack.md`,
> fill every `<...>` placeholder, replace `[REQUIRED]` / `[OPTIONAL]`
> markers with actual evidence. Submit to codex review on
> `review/claude-collab` before any promotion discussion. **No
> promotion decision can be made on a partially-filled pack.**
>
> **Hard frozen sections under codex round-27 boundary:**
> - 2026 sealed evaluation — DO NOT FILL. Sealed-eval is single-shot
>   and is the LAST gate, not part of nomination.
> - Fleet live wiring / shadow→live — DO NOT FILL. Allocator Step 8
>   + Step 9 are codex-frozen.
> - Manifest mutation — DO NOT pre-write to `fleet_manifest.json` or
>   `forward_oos_manifest.json`. The forward + fleet observation
>   happens after promotion authorization.

---

## 0. Identification

| Field | Value |
|-------|-------|
| Nominee ID (immutable) | `<track_c_NN>` |
| Composite spec | `<factor_a × factor_b × factor_c>` |
| Spec SHA-256 (`compute_spec_id`) | `<hex>` |
| Role | `<core | diversifier>` |
| Track A split version | `alternating_regime_holdout_v1` (immutable until new PRD) |
| Split SHA-256 | `<from temporal_split.yaml SHA>` |
| Lineage tag | `<track-c-cycle-NN-YYYY-MM-DD>` |
| Pre-registered criteria YAML | `data/research_candidates/<lineage_tag>_promotion_criteria.yaml` |
| Pre-registered criteria SHA-256 | `<hex>` |
| Mining commit | `<git sha at time of mining run>` |
| Evidence-pack commit | `<git sha at time of pack submission>` |

---

## 1. Boundary attestation [REQUIRED]

The nominee was generated under all of the following constraints. Tick
each box; any unchecked box invalidates the pack.

- [ ] Mining used **train years only** (2009-2017 + 2020 + 2022 + 2024)
      per `temporal_split.yaml`. No validation-year (2018, 2019, 2021,
      2023, 2025) bars entered the panel during search.
- [ ] Acceptance was evaluated on **validation years only**, gate-by-gate.
- [ ] The 2026 sealed slice was **NOT touched** at any point during
      mining or acceptance.
- [ ] Stress slices (`covid_flash`, `rate_hike_2022`) were used for
      **MaxDD sanity only** (borrowed cells, not for parameter
      selection — Track A leak guard `validate_no_holdout_leakage`
      ran and passed on every mining call; it would raise if
      holdout leakage were present).
- [ ] C5 role-remint guard (`enforce_c5_no_role_remint`) ran during
      every Optuna trial against the **RCM mining archive**
      (default `data/mining/rcm_archive.db`, via
      `RCMArchive.find_studies_by_spec_role(spec_sha256, split_name)`).
      Invariant: no prior trial with the same `spec_sha` exists
      under a **different role** in the same `split_name`.
      Same-`spec_sha` + same-`role` deterministic reruns are
      allowed but MUST be disclosed in §4.2.
- [ ] No fleet manifest, forward manifest, or sealed ledger was
      mutated during the mining or pack-construction process.
- [ ] Pre-registered criteria YAML was committed BEFORE the first
      mining trial; SHA-256 in §0 matches the commit's blob hash.

**If any box is unchecked, do not submit. Re-run mining under the
correct boundary and re-write this pack from scratch.**

---

## 2. Train-period diagnostics [REQUIRED]

Train years only (2009-2017 + 2020 + 2022 + 2024). These are
**diagnostic** numbers for sanity, not gates — Track A explicitly
forbids in-sample acceptance gates.

| Metric | Value | Notes |
|--------|-------|-------|
| Composite IC (full train) | `<float>` | |
| Composite IC IR (full train) | `<float>` | |
| Walk-forward folds | `<n_folds>` | |
| Walk-forward fold-level IC sign agreement | `<n_positive / n_folds>` | |
| Walk-forward mean IC | `<float>` | |
| Walk-forward stdev | `<float>` | |
| Train CAGR | `<float>` | |
| Train MaxDD | `<float>` | |

Provide `dev/scripts/<lineage>/train_diagnostics_run.py` (or
embedded jupyter notebook export) producing these numbers from
the same commit as §0.

---

## 3. Validation-year acceptance (Track A 17-gate evaluator) [REQUIRED]

Run `temporal_split_acceptance.evaluate(...)` against the
validation set. Paste the full `summary_line()` output verbatim,
then paste the per-gate `as_dict()` for every gate (no
filtering, no summarization).

```
<paste summary_line() output here>
```

> **Sign convention.** MaxDD is reported as a positive drawdown
> magnitude in Track A metrics (e.g. a 14% drawdown is `0.14`,
> not `-0.14`). All MaxDD ceilings below are upper bounds on the
> positive magnitude; lower is better.

### 3.1 Per-validation-year MaxDD gates

| Gate | Required | Observed | PASS/FAIL |
|------|----------|----------|-----------|
| `validation_year_2018_maxdd` | ≤ 0.20 | `<float>` | `<status>` |
| `validation_year_2019_maxdd` | ≤ 0.20 | `<float>` | `<status>` |
| `validation_year_2021_maxdd` | ≤ 0.20 | `<float>` | `<status>` |
| `validation_year_2023_maxdd` | ≤ 0.20 | `<float>` | `<status>` |
| `validation_year_2025_maxdd` | ≤ 0.20 (`core`); ≤ 0.18 (`diversifier`, HARD) | `<float>` | `<status>` |

### 3.2 Validation-aggregate excess gates (QQQ Outperformance Rule)

| Gate | Required | Observed | PASS/FAIL |
|------|----------|----------|-----------|
| `validation_aggregate_excess_vs_spy` | > 0 | `<float>` | `<status>` |
| `validation_aggregate_excess_vs_qqq` | > 0 (CLAUDE.md hard) | `<float>` | `<status>` |

### 3.3 Stress slice MaxDD (sanity only — borrowed cells)

| Gate | Required | Observed | PASS/FAIL |
|------|----------|----------|-----------|
| `stress_slice_covid_flash_maxdd` | ≤ 0.25 | `<float>` | `<status>` |
| `stress_slice_rate_hike_2022_maxdd` | ≤ 0.25 | `<float>` | `<status>` |

### 3.4 Concentration / leverage gates

| Gate | Required | Observed | PASS/FAIL |
|------|----------|----------|-----------|
| `concentration_top1` | < 0.40 (M12 PRD) | `<float>` | `<status>` |
| `concentration_top3` | < 0.70 (M12 PRD) | `<float>` | `<status>` |
| `concentration_no_leveraged_etf` | TQQQ/SOXL share < threshold | `<float>` | `<status>` |
| `concentration_watchlist_total_share` | ≤ 0.30 (G2.A ceiling) | `<float>` | `<status>` |

### 3.5 Beta / cost / role gates

| Gate | Required | Observed | PASS/FAIL |
|------|----------|----------|-----------|
| `beta_to_qqq` | within configured band | `<float>` | `<status>` |
| `cost_robustness_2x` | CAGR / Sharpe degradation < threshold | `<float / float>` | `<status>` |
| `role_<core|diversifier>_eligibility` | role-specific | `<value>` | `<status>` |

**Aggregate verdict:** `<all_pass | one_or_more_fail>`. If any HARD
gate fails, the nominee is not eligible — do not proceed to §4.

---

## 4. Cross-cutting checks [REQUIRED]

### 4.1 Concentration M12 weighted thin-data share

Per the post-2026-04-25 weighted-gate fix:
- `m12_top1_weight_max` over the validation period: `<float>`
- `m12_top3_weight_max` over the validation period: `<float>`
- `weighted_thin_data_share` = `Σ share[s] × thin_data_pct[s]`: `<float>`
  - PASS if < 0.10 (extreme tier)
  - WARN tier if 0.05 ≤ x < 0.10
  - PASS-tier if x < 0.05

### 4.2 C5 role-remint guard

- `compute_spec_id(spec)`: `<hex>`
- RCM archive path queried: `<data/mining/rcm_archive.db | other>`
- `enforce_c5_no_role_remint(archive, spec_sha, split_name, role)` result:
  `<no_existing_peer | same_role_rerun_disclosed | RaisedValueError>`
- If `same_role_rerun_disclosed`, list prior runs:
  `<study_id list with timestamps>` and explain why a deterministic
  rerun is being submitted (e.g. evidence-pack regeneration after
  template fix).
- Archive lineage tag: `<lineage_tag>`

### 4.3 Cost-model attestation

- `cost_model.yaml` SHA-256 at mining time: `<hex>`
- 2x cost sensitivity: CAGR `<float>` → `<float>`; Sharpe `<float>` → `<float>`

### 4.4 Robustness (across all 5 validation years)

For each validation year, paste:
- CAGR
- Sharpe
- MaxDD
- vs SPY excess
- vs QQQ excess

| Year | CAGR | Sharpe | MaxDD | vs SPY | vs QQQ |
|------|------|--------|-------|--------|--------|
| 2018 | | | | | |
| 2019 | | | | | |
| 2021 | | | | | |
| 2023 | | | | | |
| 2025 | | | | | |

### 4.5 Pre-registered criteria reconciliation

For each criterion in
`data/research_candidates/<lineage_tag>_promotion_criteria.yaml`:

| Criterion key | Threshold | Observed | PASS/FAIL |
|---------------|-----------|----------|-----------|
| `<key>` | `<value>` | `<value>` | `<status>` |

Any criterion that fails → nominee fails immutability rule (no
retroactive softening; cycle closes 0-nominee). Reference:
`docs/memos/20260426-research-cycle-2026-04-26-01_close.md` for the
precedent.

**Lineage rule.** Any edit to the pre-registered criteria YAML
after the first mining trial starts a **new lineage** (new
`lineage_tag` + new YAML SHA-256 + new evidence pack); it does
not amend the current cycle. The current cycle still closes
under its original criteria.

### 4.6 NAV-level orthogonality vs every active candidate [REQUIRED]

> Added 2026-04-30 (E.MV per
> `docs/memos/20260430-concerns_abE_proposed_solutions.md` §E.MV +
> external-reviewer §3 / §4.3 2026-04-30).

Source script:
`dev/scripts/correlation/rcmv1_cand2_realized_nav_correlation.py`
(adapt for nominee × every active candidate).

#### 4.6.1 Raw NAV correlation — pooled Pearson

For each active candidate (e.g. RCMv1, Cand-2, any later live
candidates), report:

| Active candidate | Pooled n_days | Raw Pearson | Tier | Diversifier-eligible? |
|-----------------:|--------------:|------------:|------|----------------------:|
| `<id_a>` | `<n>` | `<float>` | `<true_diversifier | partial_diversifier | warn_label_void | reject_step5>` | `<Y/N>` |
| `<id_b>` | `<n>` | `<float>` | `...` | `...` |

Tier definitions (mirrors Step 5 fleet correlation budget +
`temporal_split.yaml::diversifier eligibility` after the audit-R2
revision):

- `< 0.50` → `true_diversifier` (eligible for diversifier role)
- `0.50 - 0.70` → `partial_diversifier` (warning; pack must justify
  diversifier role per §4.6.4)
- `0.70 - 0.85` → `warn_label_void` (cannot claim diversifier role;
  may claim core-additive)
- `≥ 0.85` → `reject_step5` (Step 5 reject; not eligible for fleet
  entry at all)

`pooled_min_overlap_days` = 60. Below 60, status = `insufficient_data`.

#### 4.6.2 Residual NAV correlation (beta-stripped) — same tiers

Compute per-candidate beta to SPY and to QQQ, take residuals,
correlate residuals. Report against each active candidate:

| Active candidate | β-SPY (nominee) | β-SPY (active) | Residual Pearson vs SPY | Residual tier vs SPY | Residual Pearson vs QQQ | Residual tier vs QQQ |
|-----------------:|----------------:|---------------:|------------------------:|----------------------|------------------------:|----------------------|
| `<id_a>` | `<float>` | `<float>` | `<float>` | `<tier>` | `<float>` | `<tier>` |

#### 4.6.3 Adjacent diagnostics (FLAG only, not gates)

| Diagnostic | Threshold for "clean" | Action if violated |
|------------|-----------------------:|--------------------|
| Down-market (SPY day < -0.5%) Pearson vs each active | < 0.50 | warning (residual stress test) |
| Drawdown overlap (% days both in DD) | < 50% | warning (regime co-movement) |
| Top-10 holdings overlap on cell-final date | ≤ 4/10 | warning (concentrated overlap) |
| Rolling 30d Pearson worst-case | < 0.65 | warning (regime-dependent corr spike) |

#### 4.6.4 Diversifier-role eligibility decision

A candidate claiming `role: diversifier` must:

- Raw Pearson `true_diversifier` (< 0.50) vs **every** active candidate; AND
- Residual Pearson `true_diversifier` (< 0.50) vs SPY OR vs QQQ; AND
- All adjacent diagnostics clean OR each violation explicitly
  justified in pack.

If the candidate falls into `partial_diversifier` (0.50-0.70) on
either raw OR residual, the pack must include a "partial-diversifier
justification" subsection answering:

- Why is partial diversification economically meaningful? (e.g.
  drawdown-overlap < 30%, even though raw corr ~ 0.55)
- What's the residual-correlation root cause classification —
  `shared_market_beta_dominant` / `shared_alpha_dominant` / `mixed`?
- What unique exposure does the candidate add at the portfolio
  level despite the partial correlation?

A candidate in `warn_label_void` (0.70-0.85) cannot claim the
diversifier role; can only claim `core` (additive alpha).

A candidate in `reject_step5` (≥ 0.85) is not eligible for fleet
entry under the new framework.

### 4.7 Economic-assumption flags [REQUIRED — flag-only, not gates]

> Added 2026-04-30 (E.MV per
> `docs/memos/20260430-concerns_abE_proposed_solutions.md` §E.MV).

Each flag tells you "the candidate's CLAIM does not match what the
realized data SHOWS". A flag does NOT auto-reject; it requires one
sentence of explanation in the pack. Multiple flags with poor
justifications → reviewer rejects on procedural grounds.

| # | Flag | How to compute | Threshold for FLAG | Notes |
|--:|------|----------------|--------------------|-------|
| F1 | factor_ic vs nav_corr gap | `\|factor_IC_corr_vs_active − realized_NAV_corr_vs_active\|` | gap ≥ 0.30 | Cand-2 case: factor IC corr 0.40 vs NAV corr 0.898 → gap 0.50 → would flag |
| F2 | "defensive" claim vs realized β-SPY | If candidate description / spec contains "defensive", verify realized β-SPY < 1.0 | β-SPY ≥ 1.0 | RCMv1 case: nominated as "defensive composite", realized β-SPY 1.38 → would flag |
| F3 | diversifier claim vs realized NAV corr | If `role: diversifier`, raw NAV pearson must be in `true_diversifier` tier (§4.6) | any active raw ≥ 0.50 | Hard requirement at §4.6.4; here as redundant flag |
| F4 | QQQ excess concentration | % of `excess_vs_qqq` cumulative attributable to top-3 names + TQQQ + SOXL | ≥ 50% | If yes, the alpha is concentration-driven, not strategy-driven |
| F5 | regime-dependent acceptance | Pass 2025 hard gate but fail 2023 OR 2018 OR 2019 OR 2021 individually | any single year fail with 2025 pass | Suggests the strategy benefits from a specific regime not robust to others |
| F6 | residual root cause | `classify_residual()` returns `shared_alpha_dominant` (residual ≥ 0.70 vs any active) | always flag if true | Means new candidate's alpha sleeve is the same as an existing one — not just shared market beta |

Pack content for each flag: F# / observed value / threshold / FLAG_YES / explanation_one_sentence.

A pack with all flags clean is "economically clean". A pack with
≥ 3 flags + weak explanations → reviewer rejection.

---

## 5. Forward soak plan [REQUIRED — no execution yet]

The fleet allocator will not run live for this nominee until:
- forward observation collects ≥ 60 trading days post-promotion
- M12 + C2 + C5 evidence holds across the soak window
- Allocator Step 8 (manifest wiring) is unfrozen by the user

For this pack, declare the soak parameters that **would** apply if
the nominee is authorized for forward promotion:

| Parameter | Value |
|-----------|-------|
| Forward run id | `<track_c_NN_forward_01>` |
| Source-mix expected (yfinance frontier vs polygon-canonical at construction)? | `<True | False>` |
| Initial forward TD | `TD000` (init) |
| Decision-pack TD | `TD060` (60 trading days post-init) |
| Sealed-eval ledger entry expected | `<True | False>` (False until 2026 sealed eval is unfrozen) |
| Materiality anchors expected | E1=10bps NAV / E2=1% benchmark / E3=2% raw / E4=symmetric drift / E5=0.5% raw |

**No forward run is initiated by submitting this pack.** Forward
init requires:
1. Codex review of the pack on `review/claude-collab`
2. User explicit-go on the review thread
3. Separate forward-init commit referencing this pack

---

## 6. Risks / known limitations [REQUIRED]

| Risk | Severity | Mitigation |
|------|----------|------------|
| `<e.g. concentration brushes against 0.40 cap on 5 dates>` | `<low|med|high>` | `<plan>` |

If no risks identified, write "None identified — surface in codex
review" rather than skipping (an empty risks table is a red flag).

---

## 7. Reverse-validation [REQUIRED]

Pre-registered criterion YAML had a sentinel test designed to FAIL.
What is it, and did it fail as expected?

| Sentinel | Pre-fix (would have passed?) | Post-fix (does fail?) | Evidence |
|----------|------------------------------|----------------------|----------|
| `<sentinel name>` | `<yes/no>` | `<yes/no>` | `<commit / log / artifact>` |

Track A's leak guard, C5 role-remint, and the pre-registered
criteria YAML are the existing reverse-validation hooks. Any new
sentinel introduced for this nominee MUST be reverse-validated in
the same way.

---

## 8. References

- Track A PRD: `docs/prd/20260429-temporal_split_holdout_discipline_prd.md` v1.1
- Track B PRD: `docs/prd/20260428-candidate_fleet_allocator_prd.md` v1.1
- M12 weighted gate decision: `docs/memos/20260425-m12_review_decision.md`
- Codex round-27 boundary memo: `<commit reference>`
- Pre-registered criteria immutability precedent: `docs/memos/20260426-research-cycle-2026-04-26-01_close.md`
- Forward observation runner PRD: `docs/prd/20260426-forward_oos_runner_prd.md`
- Forward evidence v2.1.3 hardening PRD:
  `docs/prd/20260427-forward_evidence_hardening_prd.md`

---

## 9. Codex review block [LEAVE EMPTY — codex fills]

```
<codex round / sign-off / corrections / explicit-go status>
```
