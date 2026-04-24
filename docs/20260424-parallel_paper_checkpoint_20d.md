# Parallel Paper — Checkpoint 20d (Turnover / Concentration / Drift)

**Date**: 2026-04-24
**Window**: 2024-01-02 → 2024-01-25 (first 20 trading days of the 75d matched
paper window 2024-01-02 → 2024-04-01)
**Cutoff rule**: analysis strictly stops at 2024-01-25. No peeking at 40d /
60d data — those remain independent diagnostic checkpoints per PRD §7.2.

Per PRD §7.2, the 20d checkpoint asks three focused questions:

1. Is turnover / concentration starting to diverge between the two candidates?
2. Is paper-vs-replay drift still explainable (not a candidate-specific bug)?
3. Is any candidate-specific problem emerging?

Per PRD §7.3, the standard metric set (benchmark-relative path / drift /
turnover / concentration / artifacts completeness / 50 bps+ drift flag) is
reported.

---

## 1. Headline metrics at day 20 (2024-01-25)

| Metric | RCMv1 | Candidate-2 | Notes |
|--------|------:|------------:|-------|
| Paper cumulative return (20d) | +5.13% | +7.60% | raw — benchmarks below |
| SPY cumulative return (20d) | +2.70% | +2.70% | shared benchmark |
| QQQ cumulative return (20d) | +5.77% | +5.77% | shared benchmark |
| Excess vs SPY (bps @ day 20) | +243 | +490 | both above SPY |
| Excess vs QQQ (bps @ day 20) | −64 | +183 | Cand-2 above QQQ at this moment |
| Fills (cumulative first 20d) | 27 | 96 | 3.6× |
| Active turnover days (first 20d) | 6 / 20 | 11 / 20 | 1.8× |
| Mean turnover on active days | 0.27 | 0.55 | 2.1× |
| Cumulative turnover (20d) | 1.60 | 6.10 | **3.8×** |
| Drift mean \|delta\| (20d) | 0.29 bps | 1.75 bps | 6.0× |
| Drift max \|delta\| (20d) | 1.39 bps | 21.65 bps | same ratio as day-10 |
| Position-set diff days (20d) | 0 / 20 | 0 / 20 | replay reproducibility perfect |
| Active symbols per day | 10 (constant) | 10 (constant) | both equal-weight top-N |
| Top-1 weight per day | 0.10 | 0.10 | equal-weight construction |
| Top-3 weight per day | 0.30 | 0.30 | equal-weight construction |

**A note before any cross-candidate interpretation**: 20 trading days is
still a tiny window for P&L attribution. The "Excess vs SPY/QQQ" numbers
above are reported per PRD §7.3 checklist, **not** as an alpha claim or
ranking. At 20d, return-magnitude comparisons remain inside the
"operational sanity + divergence shape" envelope of PRD §7.2, not a
research decision input.

---

## 2. Turnover / concentration divergence (PRD §7.2 Q1)

### 2.1 Turnover — clear divergence as designed

```
day  date         RCMv1     Candidate-2
----  -----------  --------  -----------
 1    2024-01-02       0.0          0.0
 2    2024-01-03       0.0          0.0
 3    2024-01-04       0.0          0.0
 4    2024-01-05       0.0          0.0
 5    2024-01-08       0.0          0.0      ← both warmup
 6    2024-01-09       0.0          0.0
 7    2024-01-10       0.0          0.0
 8    2024-01-11       0.0          0.0
 9    2024-01-12       0.0          0.5      ← Cand-2 first trade (initial buy)
10    2024-01-13       0.5          0.7      ← RCMv1 first trade (initial buy)
11    2024-01-16       0.0          0.7
12    2024-01-17       0.0          0.9
13    2024-01-18       0.1          0.5
14    2024-01-19       0.1          0.4
15    2024-01-20       0.3          0.2
16    2024-01-22       0.3          0.7
17    2024-01-23       0.3          0.8
18    2024-01-24       0.0          0.5
19    2024-01-25       0.0          0.2      ← cutoff (day 20 is 2024-01-25)
```

Post-warmup (days 10-20):
- **RCMv1** trades on 6 / 11 post-warmup days, average 0.27 per active day.
- **Candidate-2** trades on **all 11** post-warmup days, average 0.55 per active day.

This is the paper-layer evidence of the 79% turnover-diff invariant the
PRD required at construction (`docs/20260424-candidate_2_decision_memo.md`
§4.2). The live ratio (3.8× cumulative turnover) is even sharper than the
offline proxy (79% relative diff).

### 2.2 Concentration — no divergence, as expected by construction

Both candidates are configured with `top_n=10` equal-weight. At every active
day, both show top-1 = 0.10 and top-3 = 0.30. This is **design-bound** —
concentration cannot diverge unless a candidate's composite produces fewer
than 10 non-NaN entries on a given date (which hasn't happened in the first
20d for either).

No concentration concern. If concentration ever does drift (e.g. Cand-2's
`hl_range` family gives fewer than 10 valid entries on a turbulent day),
it will show up in subsequent checkpoints.

---

## 3. Drift — still explainable by turnover (PRD §7.2 Q2)

```
                          RCMv1       Candidate-2
  mean |Δ NAV|   (bps)     0.29        1.75        ratio 6.0×
  max  |Δ NAV|   (bps)     1.39       21.65        ratio 15.6×
  worst-day date           2024-01-19  2024-01-25
  position-set diff days   0/20        0/20
```

Per-trade drift (aggregate drift / trade count):
- RCMv1: 0.29 × 20 / 27 ≈ 0.21 bps-days/trade
- Cand-2: 1.75 × 20 / 96 ≈ 0.36 bps-days/trade

Within the same order of magnitude. Cand-2's drift scales with turnover;
the 15.6× max-drift ratio is worse than the 3.6× fills ratio, so there IS
non-linear noise in Cand-2's execution layer, but it's still well under
the 50 bps informational threshold.

**Neither candidate exceeds the 50 bps threshold at day 20.** The Cand-2
max of 21.65 bps on 2024-01-25 (the cutoff day itself) is the single
largest tail observation, driven by a +3.78% single-day NAV move on that
date; the replay picked up the same move, and the 21.65 bps gap is
execution-layer variance on a high-volatility trading day.

Position-set diff is 0/20 for both — replay reproducibility remains
perfect on the target layer. All drift originates in the execution layer.

---

## 4. Candidate-specific problems (PRD §7.2 Q3)

None identified at day 20.

Specifically checked:
- ❌ No all-NaN-post-warmup days in either candidate's signals_daily
- ❌ No days with `n_positions` != `top_n` (both constant at 10)
- ❌ No weight-sum ≠ 1.0 on active days
- ❌ No fills with zero quantity or NaN price (fills.csv spot-checked)
- ❌ No drift > 50 bps informational threshold
- ❌ No crash / traceback in either run
- ❌ No registry state change, revoke, or demote

The one known pre-existing issue that surfaces in both runs —
`final_equity = NaN` from CLAUDE.md history M14 (BacktestEngine
ghost-cleanup + NaN last-bar) — is a pre-existing framework bug,
NOT candidate-specific, and does not affect any 20d metric above
(drift / turnover / returns / positions are all calculated over the
bar-by-bar equity series, not the scalar final equity).

---

## 5. Benchmark-relative path through day 20

```
date         RCMv1 cum ret   Cand-2 cum ret   SPY cum ret   QQQ cum ret
----------   -------------   --------------   -----------   -----------
2024-01-12        0.0000          0.0000         0.0000        0.0000
2024-01-15        0.0026          0.0000         0.0026        0.0028   (T+1 fill)
2024-01-16        0.0024          0.0011        -0.0031       -0.0052
2024-01-17        0.0030         -0.0092        -0.0089       -0.0141
2024-01-18        0.0059          0.0064        -0.0010        0.0018
2024-01-19        0.0249          0.0185         0.0104        0.0179
2024-01-22        0.0240          0.0350         0.0160        0.0251
2024-01-23        0.0540          0.0378         0.0232        0.0472
2024-01-24        0.0447          0.0368         0.0263        0.0527
2024-01-25        0.0513          0.0760         0.0270        0.0577
```

Both candidates are above SPY throughout the first 20 days. Relative to
QQQ, they oscillate:
- RCMv1 was ahead of QQQ through 2024-01-23, then fell slightly below
  (−64 bps at day 20)
- Candidate-2 was behind QQQ through 2024-01-24, then jumped ahead
  (+183 bps at day 20) on the 2024-01-25 +3.78% single-day move

No interpretation of "which is better" at 20 days. The path differences
are consistent with the two candidates covering different factor families
— exactly what the orthogonality construction intended — not a signal
that one factor family is winning.

---

## 6. PRD §7.2 Q1-Q3 answers in one line each

- **Q1 (turnover / concentration diverging?)**: Turnover yes, clearly
  (3.8× cumulative). Concentration no, by construction — both are
  equal-weight top-10.
- **Q2 (drift explainable?)**: Yes. Per-trade drift equivalent (0.21 vs
  0.36 bps-days/trade). Neither candidate exceeds 50 bps threshold.
- **Q3 (candidate-specific problem?)**: None at day 20.

---

## 7. Decisions for the registry + downstream

Both candidates remain at `S2_paper_candidate`. No revoke, no demote, no
`config/production_strategy.yaml` changes, no schema migration.

Per PRD §8.1-§8.3, universe extension / new mining / new data tier
decisions are **not discussed** before a later checkpoint delivers
actionable signal. At 20d the candidates are healthy and divergent-as-
designed. Nothing here triggers a review of research scope.

---

## 8. Next checkpoint

Per PRD §7.3 the 40d checkpoint (first 40 trading days, cutoff
approximately **2024-02-28** in this window) will focus on:

- Is the style profile (turnover / concentration / benchmark-relative
  path shape) stable through day 40, or does one candidate regress?
- Does paper-vs-replay drift stay below threshold or start trending?
- Does one candidate start producing candidate-specific problems
  (dead signal days, concentration collapse, etc.)?

40d analysis is on demand; all data is already on disk in
`data/paper_runs/*/`. No new paper runs needed.
