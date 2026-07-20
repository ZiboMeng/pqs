# 2026-07-20 research and PAPER governance reconciliation

Status: active governance overlay

Machine policy: `config/research_governance.yaml`

## Decision

The Phase 2 promotion record for `dual_index_growth_v1` remains immutable
historical evidence. Its current effective status is
`PAPER_OBSERVATION_ONLY`, with `REVIEW_HOLD`, no automatic-promotion
eligibility and no capital eligibility. Frozen simulated PAPER observation may
continue; this decision does not authorize LIVE or broker writes.

This is a reconciliation, not a claim that the old record was fabricated. The
Phase 2 evaluator correctly applied its frozen `phase2-paper-promotion-v1`
policy. That policy's `growth_engine` branch required QQQ-relative Calmar and
beta limits, but did not require positive return excess versus the project's
primary SPY benchmark.

## Independent evidence check

The final Phase 2 holdout (`2024-01-02` through `2026-07-17`) reports:

| Metric | dual-index strategy | SPY benchmark | Interpretation |
|---|---:|---:|---|
| CAGR | 15.31% | 24.79% | strategy trails by 9.48 percentage points/year |
| total return | 43.36% | 75.03% | strategy trails by 31.68 percentage points |
| MaxDD | -9.43% | -22.77% | materially better drawdown |
| information ratio | -0.672 | n/a | negative benchmark-relative efficiency |

The low drawdown is genuinely useful evidence, but this is not a near-miss on
return. Under the user's explicit benchmark objective, it cannot inherit an
automatic investability conclusion.

The same calendar interval was opened by three successive project finalists
(`d2r2`, `d2r3`, `d2r5`). Each access was preregistered for a separate family,
but after the first result the interval was no longer globally pristine to the
research program. New names, hashes or split identifiers cannot restore that
novelty. Existing results remain valid historical/pseudo-OOS diagnostics; they
are not reminted as new sealed evidence.

## Benchmark rule

- SPY total return, measured on the same price basis and after strategy costs,
  is the sole automatic-promotion return benchmark.
- QQQ remains diagnostic only.
- Failure to beat SPY does not cause automatic retirement. It causes
  `REVIEW_HOLD`.
- A manual near-miss review must also compare a risk-matched passive portfolio
  and examine DSR/PBO/CPCV and forward evidence. Any exception needs explicit
  user approval and must remain labelled as an exception, not as a gate pass.

## Runtime authority and unresolved operational blocker

`core/paper_trading/forward_runtime.py` is the execution authority. Legacy
`core/research/forward/` outputs remain evidence only.

The current Phase 3 CLI accepts a caller-provided source-batch hash but has not
yet proved that it is bound to a trusted collector batch. More importantly, a
post-close Yahoo daily download cannot by itself support a causal next-session
open action: the open is already in the past by the time the complete daily bar
is available. Therefore no real forward session is authorized until a trusted,
time-causal source contract and source-batch verification bridge exist. Offline
replay must stay explicitly labelled replay.

## Supersession map

- `docs/STRATEGY_PROMOTION.md` and `docs/SECOND_ROUND_FINAL_REPORT.md` remain
  authoritative for what Phase 2 did, but not for current effective status.
- `docs/PHASE3_FINAL_REPORT.md` remains authoritative for its delivery snapshot,
  but its approved-artifact language is superseded by the observation artifact.
- Historical `v1.json` and `phase3_forward_v1.json` are retained unchanged for
  audit and rollback. New effective artifacts use separate paths.

