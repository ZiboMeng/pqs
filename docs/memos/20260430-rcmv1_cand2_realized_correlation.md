# RCMv1 + Cand-2 historical NAV correlation diagnostic

**Date:** 2026-04-30
**Author:** Claude (per external reviewer prompt 2026-04-30)
**Status:** Evidence note. Triggers immediate fleet-design retraction.
**Lineage:** Step 5 C2 correlation budget shipped 2026-04-29 makes this
diagnostic finally computable on realized portfolio returns.
**Machine-readable result:** `data/memos/20260430_rcmv1_cand2_realized_correlation.json`

---

## TL;DR

The "orthogonal" label on `candidate_2_orthogonal_01` does **not hold**
at the realized-NAV level. Pooled Pearson over 154 honest post-step3b
trading days = **0.898**, which exceeds Step 5's reject threshold (0.85).
On a per-cell basis, the 2022-H2 cell pairs at **0.937** (well above
reject); the 2024-Q1 cell pairs at **0.795** (above warn 0.70, just
below reject 0.85). Both cells run concurrent drawdowns on >64% of
days and share 4/10 of their top-10 holdings on the 2022 final cut.

**Concrete next-step consequences (decided in this note):**

1. The diversifier hypothesis behind the two-candidate fleet is
   dead. Cand-2 is **not** a diversifier sleeve relative to RCMv1.
2. Fleet `split_policy: equal_weight` across these two candidates
   does not produce risk diversification — it produces a slightly
   smoothed clone of one underlying strategy.
3. This **does not** invalidate either candidate individually as a
   long-only US-equity strategy; it invalidates the "fleet of two"
   composition assumption.
4. Track C should **not** assume that mining one more candidate is
   automatically additive. Any new candidate must show NAV-level
   orthogonality (this same diagnostic) against BOTH RCMv1 and Cand-2
   before being labeled diversifier.

This is exactly the failure mode the external reviewer flagged on
2026-04-30: "factor-IC orthogonal" claims, in 2020-onwards US equities,
routinely collapse at the portfolio-NAV level into the same trade
(QQQ-beta / Mag7 concentration / risk-on liquidity / rates sensitivity).

---

## 1. What the experiment measured

Inputs: the **post-step3b honest re-runs** of two paper-cell windows
that exist for both candidates:

| Cell | Window | n_days | Run dirs |
|------|--------|-------:|----------|
| `2022_h2` | 2022-08-26 → 2022-12-15 | 78 | RCMv1 `20260425T041403Z` / Cand-2 `20260425T041405Z` |
| `2024_q1` | 2024-01-02 → 2024-04-19 | 76 | RCMv1 `20260425T041358Z` / Cand-2 `20260425T041400Z` |

Both cells are post-data-integrity-round-3 (2026-04-25), i.e. they
use polygon-canonical bars + splits-at-read-time, so NAVs are
honest in the sense the round-3 closeout memo defines.

For each cell the script (`dev/scripts/correlation/rcmv1_cand2_realized_nav_correlation.py`)
computes:

- Pearson + Spearman on daily returns.
- Conditional correlation on down days (SPY daily ret < -0.5%) and
  up days (SPY daily ret > +0.5%).
- Rolling 30-day Pearson, summarized as min / max / mean.
- Drawdown overlap: % of days where both candidates are in DD
  from cell-start peak.
- Top-10 holdings overlap on the cell's final date, plus average
  Jaccard of all-positive-weight holdings across all common dates.
- Beta to SPY and beta to QQQ for each candidate.

Pooled across both cells (154 days, ignoring the time gap as a
discontinuity), Pearson and Spearman are also reported.

---

## 2. Findings

### 2.1 Headline correlations

| Scope | n_days | Pearson | Spearman | Step 5 label |
|-------|-------:|--------:|---------:|--------------|
| `2022_h2` cell | 78 | **0.937** | 0.936 | `reject` (≥ 0.85) |
| `2024_q1` cell | 76 | **0.795** | 0.768 | `warn` (≥ 0.70) — borderline reject |
| Pooled (both cells) | 154 | **0.898** | 0.875 | `reject` (≥ 0.85) |

Step 5's `corr_min_overlap_days = 60` is satisfied on every line.

### 2.2 Conditional correlation (regime stratified)

| Cell | Down days (n) | Down corr | Up days (n) | Up corr |
|------|--------------:|----------:|------------:|--------:|
| 2022_h2 | 35 | 0.749 | 27 | 0.942 |
| 2024_q1 | 16 | 0.747 | 23 | 0.655 |

Down-market correlation drops modestly (0.94 → 0.75 in 2022_h2)
but stays well above the 0.40 diversifier threshold from
`temporal_split.yaml`. So even in stress, these two candidates
move together.

### 2.3 Rolling 30-day Pearson

| Cell | Min | Max | Mean |
|------|----:|----:|-----:|
| 2022_h2 | 0.803 | 0.985 | 0.925 |
| 2024_q1 | 0.687 | 0.914 | 0.828 |

Even the worst 30-day window in 2024_q1 (0.687) is ~3× the
diversifier ceiling. There is no temporal regime within the sample
where these candidates were not already highly correlated.

### 2.4 Drawdown overlap

| Cell | RCMv1 max DD | Cand-2 max DD | % days both in DD |
|------|------------:|--------------:|------------------:|
| 2022_h2 | -13.31% | -15.80% | 75.6% |
| 2024_q1 | -11.45% | -5.65% | 64.5% |

In 2022_h2, both candidates were drawing down on three out of every
four days. This is the operational definition of "not diversified".

### 2.5 Holdings overlap

| Cell | Avg Jaccard (full universe) | Top-10 overlap (final date) |
|------|---------------------------:|----------------------------:|
| 2022_h2 | 0.159 | 4 / 10 |
| 2024_q1 | 0.156 | 2 / 10 |

Average Jaccard ~16% looks low in raw count, but the symbols they
DO share are heavily weighted (top-10 overlap 4/10 in 2022). High
correlation comes from concentrated overlap on a few large names
plus shared SPY/QQQ-beta exposure on the rest.

### 2.6 Equity beta

| Cell | RCMv1 β-SPY | Cand-2 β-SPY | RCMv1 β-QQQ | Cand-2 β-QQQ |
|------|------------:|-------------:|------------:|-------------:|
| 2022_h2 | 1.38 | 1.57 | 1.13 | 1.32 |
| 2024_q1 | 1.53 | 1.26 | 1.13 | 0.99 |

Both candidates run β-SPY ≥ 1.25 in every cell. RCMv1 was nominated
as a "defensive composite" and Cand-2 as a value-tilted orthogonal,
but in realized returns **neither is defensive** — both are
high-equity-beta long-only portfolios. The "defensive composite"
naming is also called into question (separate diagnostic, out of
scope for this note).

---

## 3. Interpretation — operator view

### Why factor-IC orthogonality wasn't enough

Cand-2's nomination basis was a factor-IC orthogonal composite:
{`ret_5d`, `rs_vs_spy_126d`, `hl_range`}. These factors have low
**factor-level** IC correlation with RCMv1's factors. But factor IC
correlation is computed on cross-sectional rankings; portfolio NAV
correlation is computed on dollar-weighted realized returns.

The composition step — `top_n` selection, equal-weight or
weight-by-score, integer-share rounding, T+1 open fill, the same
universe of 78 symbols — collapses the factor-rank diversity into
similar position lists. By the time you reach NAV, both portfolios
are tilted toward the same handful of large QQQ-beta names because:

- Same universe (78 symbols, same monthly rebalance);
- Same top_n (likely ~10);
- Same execution cadence;
- Both factors fundamentally correlate with momentum or trend at
  multi-month horizons — `ret_5d` and `rs_vs_spy_126d` both reward
  recent winners; momentum + trend factors in 2022-2024 US equity
  panels both pick Mag7 and AI narrative names;
- Same long-only constraint forces both to express positive views
  by buying, which converges on the highest-momentum names.

This is the textbook trap the reviewer warned about.

### What changes operationally

1. **Fleet allocator step 5 (C2 correlation budget) would now
   reject this composition if applied to live data** (pooled corr
   0.898 > 0.85). The Step 5 implementation we just landed is
   working as designed. The candidates predate it, which is why
   the composition was approved earlier.

2. **The two-candidate forward observation continues** as
   "legacy decay verification" (per CLAUDE.md classification done
   2026-04-29). It still tells us how a single-strategy proxy
   behaves under live data; it does not validate fleet design.

3. **Track C must produce a candidate that is NAV-orthogonal to
   RCMv1, not merely factor-IC-orthogonal.** This adds a hard
   diagnostic to the Track C evidence pack — see action item §5.

4. **Fleet config in `config/fleet.yaml` should not be
   interpreted as an active fleet.** It's a schema example with
   the two legacy candidates wired in. Until a NAV-orthogonal
   diversifier exists, equal-weight composition adds no
   diversification.

---

## 4. Caveats / what this note does NOT prove

- **Sample size 154 days, two non-contiguous windows.** This is
  enough to invalidate the "orthogonal" claim with high confidence
  but not enough to characterize the joint distribution under all
  market regimes. In particular, no >2σ stress event is in this
  sample (2022-08 to 2022-12 is a moderate sell-off; 2024-Q1 is a
  bull rally).
- **Both windows are in-sample for the candidates' own training
  panel.** This is a diagnostic of the realized portfolio under
  near-train conditions, not an OOS test.
- **Forward observation TD003 is too short** to recompute the
  correlation on truly OOS data. Per Step 5's
  `corr_min_overlap_days=60`, forward NAV correlation can only be
  asserted starting around TD060.
- **Holdings overlap figures use `target_portfolio_daily`,** which
  is pre-execution targets, not realized fills. Realized overlap
  via `fills.csv` is likely higher because both candidates trade
  the same liquid US large-caps.

---

## 5. Action items (decided in this note)

| # | Action | Owner | Trigger |
|--:|--------|-------|---------|
| 1 | Mark `candidate_2_orthogonal_01` as **NAV-correlation-failed-diversifier** in `data/research_candidates/candidate_2_orthogonal_01.yaml` (add `realized_nav_correlation_status` field referencing this memo) | Claude | Immediate |
| 2 | Add a **NAV-correlation gate** to the Track C evidence-pack template (§4 or new §4.6): any new candidate must report Pearson / down-market / drawdown-overlap / top-10 holdings overlap against EVERY active fleet candidate. Diversifier-role candidate must show pooled Pearson < 0.40 over ≥60 day overlap | Claude | Before next Track C cycle |
| 3 | Update `config/fleet.yaml` candidates section comment to reflect the legacy/decay-verification status and the failed orthogonality finding | Claude | Same commit as this memo |
| 4 | Forward TD60 decision-pack template (when written) must include this same NAV-correlation diagnostic computed over the forward observation window | Claude | Before TD60 |
| 5 | When Track C nominates a candidate, run this same diagnostic against RCMv1 + Cand-2 BEFORE the candidate is added to fleet | Claude | At Track C nomination time |

---

## 6. References

- External reviewer's 2026-04-30 response (the prompt for this experiment).
- Step 5 C2 correlation budget: `core/research/fleet/correlation_budget.py`,
  `config/fleet.yaml`.
- `core/research/temporal_split.py` diversifier eligibility constraint
  `vs_existing_core_correlation < 0.40`.
- Round-3 data integrity closeout: `docs/memos/20260425-data_integrity_round3_close.md`.
- Cand-2 nomination basis: `docs/20260424-phase_e_post_cand2_final_synthesis.md`.

---

## 7. One-line judgement

The fleet experiment was a clone, not a diversifier. Step 5 caught
it (would have caught it earlier if shipped earlier). Track C must
deliver something that demonstrates NAV-level orthogonality, not
factor-rank orthogonality, before any new fleet wiring is allowed.
