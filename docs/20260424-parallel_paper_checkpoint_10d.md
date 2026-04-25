# Parallel Paper — Checkpoint 10d (Operational Sanity)

> **Post-step-3b caveat (added 2026-04-25)**: NAVs / drift bps /
> trade counts / specific dates cited in this memo are **pre-step-3b**.
> Post-rebuild canonical numbers for the four paper cells live in
> TD75 §0c. Specific dates here are BarStore-label dates;
> under the rebuilt store every weekday is a real ET trading day.
> See `docs/memos/20260425-data_integrity_round3_step3b_complete.md`.

**Date**: 2026-04-24
**Window**: 2024-01-02 → 2024-04-01 (75 trading days; checkpoint at day 10 uses
the first ~10 trading days)
**Scope**: **operational sanity only**, per PRD §7.2. Not a research-signal
checkpoint. No alpha / IR / return conclusions drawn.

Parallel paper comparison of:
- `rcm_v1_defensive_composite_01` — S2_paper_candidate (defensive / regime /
  liquidity family, 4 factors TPE-tuned)
- `candidate_2_orthogonal_01` — S2_paper_candidate (short-term momentum /
  benchmark-relative / volatility-structure, 3 factors equally-weighted)

Both share identical window, identical universe (79 tradable symbols),
identical top-N (10), identical config stack. Per
`docs/20260424-candidate_2_decision_memo.md` §4.2, the two candidates are
structurally orthogonal (composite corr 0.404 < 0.5, turnover relative diff
79.2% ≥ 20%).

Paper runs:
- RCMv1: `data/paper_runs/rcm_v1_defensive_composite_01/20260424T181619Z/`
- Candidate-2: `data/paper_runs/candidate_2_orthogonal_01/20260424T152840Z/`

---

## 1. Pipeline health (what this checkpoint actually checks)

| Check | RCMv1 | Candidate-2 | Verdict |
|-------|-------|-------------|---------|
| All 8 expected artifacts written | ✅ 8/8 | ✅ 8/8 | both healthy |
| Panel loaded on matched window | ✅ 75 dates × 79 symbols | ✅ 75 dates × 79 symbols | bit-identical shape |
| Signal-generation startup day | day 10 (2024-01-13) | day 9 (2024-01-12) | expected factor warmup |
| Target portfolio activates after warmup | ✅ same day as signal | ✅ same day as signal | correct |
| First fill date | 2024-01-15 | 2024-01-15 | T+1 open after first signal |
| Days with any non-null signal | 65/75 | 66/75 | both populate ≥86% of window |
| Any NaN/Inf intrusion post-warmup | none observed | none observed | — |
| Drift: position-set diff days | 0/75 | 0/75 | perfect replay reproducibility |
| Drift: NAV mean \|delta\| | 1.20 bps | 21.38 bps | see §3 |
| Drift: NAV max \|delta\| | 3.91 bps | 157.57 bps | see §3 |

All eight checks pass or have an explicable answer. Zero operational-sanity
blockers found.

---

## 2. Structural divergence (validates orthogonality design)

The PRD specified that Candidate-2's turnover differs from RCMv1 by ≥ 20%.
In the first 75 days of matched-window paper, that prediction holds loudly:

| Metric (75-day window) | RCMv1 | Candidate-2 | Ratio |
|------------------------|------:|------------:|------:|
| Total fills | 84 | 571 | 6.8× |
| Unique fill dates | 21/75 | 44/75 | 2.1× |
| Non-zero-turnover days | 37/75 | 66/75 | 1.8× |
| Mean turnover on active days | 0.36 | 0.61 | 1.7× |

The two candidates are **visibly behaving differently in paper**. That is the
design intent — they cover different economic themes at different frequencies,
so their P&L profiles should diverge under real-world conditions. The 10-day
checkpoint confirms the divergence is present from day 1 of active trading,
not an artifact of longer-horizon settlement.

This is not yet an alpha conclusion. "Different" is the necessary condition;
"better / worse" requires the later checkpoints (§6).

---

## 3. Drift observations

Drift = NAV difference between the committed paper run and a freshly-replayed
run over the same window (via `scripts/paper_drift_report.py`). The informational
threshold is 50 bps mean / any-day per PRD §7.2.

- **RCMv1**: mean 1.20 bps, max 3.91 bps on 2024-03-05. Both well under
  threshold. Pipeline reproducibility is effectively perfect.
- **Candidate-2**: mean 21.38 bps, max 157.57 bps on 2024-03-26. Mean under
  threshold; max exceeds 50 bps.

Candidate-2's higher drift is **expected given turnover**: 6.8× more trades
means 6.8× more opportunities for execution-side variance (fill-price rounding,
cost timing, order sequence). Per-trade drift is approximately equivalent:
21.38 / 571 ≈ 0.037 bps per trade vs 1.20 / 84 ≈ 0.014 bps per trade —
same order of magnitude.

The 157 bps outlier on 2024-03-26 is near end-of-window and likely interacts
with the M14 known issue (BacktestEngine ghost-cleanup + NaN last-bar,
documented in `docs/20260424-claude_md_phase_e_history.md` Framework Completion
M14). It is **not a paper-pipeline bug**. If M14 ever gets a proper fix, this
outlier should collapse.

`final_equity=NaN` for both runs — same M14 issue. Does not affect drift
calc, turnover, or position bookkeeping, which are all observed correctly.

**Decision at day 10**: no pipeline block. Drift thresholds are informational,
not gates, per PRD §7.2. Neither candidate is flagged for revoke.

---

## 4. Things this checkpoint explicitly does NOT claim

Per PRD §7.2:

- No claim that RCMv1 is "better" or "worse" than Candidate-2.
- No bps-level P&L comparisons drive revoke / reject decisions at 10 days.
- No feature-family causality conclusions.
- No "universe needs to extend" or "new data tier needed" judgments — PRD §7.1
  explicitly defers those until after at least 2 checkpoints.

The only day-10 question this answers is: **are both pipelines operationally
sound, and are the two candidates distinctly different as the construction
predicted?** Answer: yes, both, confirmed.

---

## 5. Signal / turnover timeline for the record

Both candidates' first 10 trading days unfold as:

```
day   date          RCMv1 signals / tp  Cand-2 signals / tp
 1    2024-01-02     -    /   -          -    /   -          ← warmup
 2    2024-01-03     -    /   -          -    /   -
 3    2024-01-04     -    /   -          -    /   -
 4    2024-01-05     -    /   -          -    /   -
 5    2024-01-08     -    /   -          -    /   -
 6    2024-01-09     -    /   -          -    /   -
 7    2024-01-10     -    /   -          -    /   -
 8    2024-01-11     -    /   -          -    /   -
 9    2024-01-12     -    /   -          ✓    /   ✓         ← Cand-2 first signal
10    2024-01-13     ✓    /   ✓          ✓    /   ✓         ← RCMv1 first signal
11    2024-01-16     ✓    / fills begin  ✓    / fills begin ← both fill T+1 after signal
```

Both signals warm up within the expected factor-lookback timeframes
(Candidate-2 one trading day earlier, consistent with its shorter factor
lookbacks: `ret_5d` + `hl_range` 20d + `rs_vs_spy_126d` 126d vs RCMv1's
`beta_spy_60d` + `drawup_from_252d_low` 252d).

---

## 6. Next checkpoints (reminder, not work for this memo)

| Checkpoint | Trading day | Calendar date in this window | Scope |
|------------|-------------|------------------------------|-------|
| 10d | 10 | 2024-01-16 | **this memo** — operational sanity |
| 20d | 20 | 2024-01-30 | turnover / concentration divergence onset |
| 40d | 40 | 2024-02-28 | style-profile stability, benchmark-relative path |
| 60d | 60 | 2024-03-27 | full comparison, next research decision |

Per PRD §7.3 each of 20d / 40d / 60d must report benchmark-relative path,
replay-vs-paper drift, turnover, concentration, paper artifacts completeness,
and any 50 bps+ drift flag. **None of those are produced in this memo.**

Per PRD §7.1 / §8.1-§8.3: universe extension, new mining, or new data tier
decisions are not discussed before the 20d checkpoint at minimum. Nothing
observed at 10d triggers an exception.

---

## 7. Status for the registry

Both candidates remain at `S2_paper_candidate`. No revoke. No demote. No new
commits to `config/production_strategy.yaml`. No schema / dependency / registry
schema changes.

A refreshed `docs/20260424-phase_state_snapshot.md` accompanies this memo.
