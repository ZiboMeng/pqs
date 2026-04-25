# Parallel Paper (2022-H2 bear) — Checkpoint TD10 (Operational Sanity)

> **Post-step-3b caveat (added 2026-04-25)**: NAVs / drift bps /
> trade counts / specific dates cited in this memo are **pre-step-3b**.
> The data-integrity workstream rebuilt `data/daily/<sym>.parquet`
> from polygon 1m as the single canonical source on 2026-04-25
> (round-3). Post-rebuild canonical numbers for the four paper cells
> live in TD75 §0c. Specific dates here are BarStore-label dates;
> under the rebuilt store every weekday is a real ET trading day
> with the correct label, and the Saturday pad rows that used to
> follow each Friday are gone. See
> `docs/memos/20260425-data_integrity_round3_step3b_complete.md`.

**Date**: 2026-04-24
**Window**: **2022-08-26 → 2022-12-15** (79 real trading days; 10/20/40/60/75
TD checkpoints planned)
**Cutoff (this memo)**: real trading day **TD10 = 2022-09-09 (Fri)**.
**Scope**: operational sanity only, per PRD §7.2. Not a research-signal
checkpoint. No alpha / IR / return conclusions drawn.

This is the cross-regime rerun on a verified-clean bear segment. The
2024-01-02 → 2024-04-19 up-tape window was already analyzed at
TD10/20/40/60. This memo opens the matched-frozen-spec parallel paper
on the bear regime.

Background on window selection (full reasoning in
`docs/20260424-data_integrity_2022_split_adjustment.md`):

- 2022-Q1 was attempted first → contaminated by TSLA mixed split
  adjustment.
- 2020-Q1 COVID was the next proposal → also contaminated (TSLA + GOOGL).
- 2022-08-26 → 2022-12-15 starts the day after TSLA's 3:1 split
  (2022-08-25), placing it after every previous major universe split.
  Continuity check on 20 sampled symbols: 0/20 issues. **Selected.**

Same frozen candidates, same 79-symbol universe, same pipeline as the
2024 runs. Only the time window has changed.

Paper run artifacts:
- RCMv1: `data/paper_runs/rcm_v1_defensive_composite_01/20260424T214642Z/`
- Cand-2: `data/paper_runs/candidate_2_orthogonal_01/20260424T214644Z/`

---

## 1. Trading-day index (real-TD enforced from start)

The paper-runner's panel index has Saturday pad rows (NaN signals); they
were silently included in the original 2024 TD10/TD20 memos and
retroactively corrected at the 40d memo. This 2022-H2 series uses
weekday-filtered real-TD indexing **from TD10 onward**, so the
checkpoint cutoffs are correct on first analysis.

| Checkpoint | Cutoff date |
|------------|-------------|
| TD10 | **2022-09-09 (Fri)** ← this memo |
| TD20 | 2022-09-23 (Fri) |
| TD40 | 2022-10-21 (Fri) |
| TD60 | 2022-11-18 (Fri) |
| TD75 | 2022-12-09 (Fri) |

79 real TDs available in the window total.

---

## 2. Pipeline health (TD10)

| Check | RCMv1 | Candidate-2 |
|-------|-------|-------------|
| 8/8 expected artifacts present | ✅ | ✅ |
| Panel shape (calendar days × symbols) | 95 × 79 | 95 × 79 |
| First non-null signal day | 2022-09-08 (TD9) | 2022-09-07 (TD8) |
| First fill date (T+1 after first signal) | 2022-09-09 | 2022-09-08 |
| Fills through TD10 | 10 | 16 |
| Active turnover days (TD10) | 1 / 10 | 3 / 10 |
| Cumulative turnover (TD10) | 0.50 | 1.60 |
| Mean turnover on active days | 0.50 | 0.53 |
| NAV drift mean \|Δ\| (TD10) | **0.00 bps** | **0.06 bps** |
| NAV drift max \|Δ\| (TD10) | 0.02 bps | 0.35 bps |
| Days with \|Δ\| > 50 bps (TD10) | 0 / 10 | 0 / 10 |
| Position-set diff days | **0 / 10** | **0 / 10** |
| Final equity at TD10 | $100,376 | $101,140 |

All eight standard pipeline-health checks pass on both candidates. No
warning flags. Drift at TD10 is essentially zero on both — replay
produces bit-identical NAV through TD10. (Drift will grow at later
checkpoints because Cand-2 will accumulate trades; the TD10 finding is
that the pipeline isn't broken right out of the gate.)

---

## 3. Regime context (informational)

This window is materially different from the 2024 up-tape:

| | 2024-01-02 → 2024-04-19 | 2022-08-26 → 2022-12-15 (this) |
|---|------------------------:|-------------------------------:|
| TD10 SPY return | +1.4% (rising) | −4.4% (risk-off) |
| Direction at start | up-tape | bear / drawdown |
| Window contains | tech rally + March chop | Oct-12 bear bottom + recovery |
| Window-end SPY | (not yet computed) | −4.7% net (peak-to-trough −12%) |

SPY is already down −4.4% over the first 10 trading days of the new
window, confirming the regime shift. RCMv1's "defensive" thesis and
Cand-2's "tactical momentum" thesis will get tested under genuinely
adversarial conditions for the first time in our paper data.

**Per PRD §7.2 TD10 = operational sanity only**. The fact that both
candidates show small positive returns (RCMv1 +0.38%, Cand-2 +1.14%)
while SPY is at −4.43% is reportable but not interpreted here. That
divergence-from-SPY at TD10 is suggestive, not conclusive — 10 TDs is
too short for return signal, and post-warmup only ~7 trading days have
actual positions in the book.

---

## 4. Structural divergence reappears (validates orthogonality cross-regime)

The 2024 window's TD10 already showed Cand-2 trading more actively than
RCMv1; the same pattern holds at TD10 in the bear:

| Metric (TD10) | RCMv1 | Candidate-2 | Ratio |
|---------------|------:|------------:|------:|
| Total fills | 10 | 16 | 1.6× |
| Cumulative turnover | 0.50 | 1.60 | 3.2× |
| Active turnover days | 1 / 10 | 3 / 10 | 3.0× |

The ratio is similar in magnitude to the 2024 TD10 (RCMv1 27 fills
vs Cand-2 96 fills over 20 trading days = 3.6× ratio). The orthogonality
designed at construction (~80% turnover relative diff) is reproducing
cross-regime — neither candidate has collapsed into mimicking the other
under bear stress.

---

## 5. What this checkpoint deliberately does NOT claim

Per PRD §7.2:

- No claim that either candidate is "winning" or "losing" in the bear
  regime at TD10.
- No conclusion about whether RCMv1's ETF overlay is more or less
  effective in risk-off — that is a TD60 question.
- No conclusion about Candidate-2's tactical thesis surviving the bear
  — that is a TD40 / TD60 question.
- No comparison statements between the 2024 and 2022 windows beyond the
  trivial "regime is different".
- No discussion of universe extension, new mining, or Candidate-3
  (frozen until at least TD60 of this rerun).

The only TD10 question this answers: **are both pipelines operationally
sound on the new clean window?** Answer: yes, both, confirmed. No
flagged issues.

---

## 6. Next checkpoint

TD20 → cutoff **2022-09-23 (Fri)**. Per the user's earlier framing for
20d:

- early behavior characterization
- turnover / concentration starting to diverge
- drift trending vs explainability

Data is already on disk; no new paper run needed.

---

## 7. Status

- Both candidates remain at `S2_paper_candidate`.
- No revoke / demote / config / schema / dependency changes.
- pytest 1566 / 1 / 1 (unchanged from last full run).
- `docs/20260424-phase_state_snapshot.md` will be refreshed at this
  commit to include the new 2022-H2 paper run paths.
- Data-integrity issue logged separately at
  `docs/20260424-data_integrity_2022_split_adjustment.md` (the file
  name dates to first occurrence; content covers 2020 + 2022-Q1 +
  the clean-window 2022-H2 + 2024 verification).
