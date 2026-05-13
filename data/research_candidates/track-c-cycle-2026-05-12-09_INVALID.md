# cycle #09 INVALID marker

**Lineage**: `track-c-cycle-2026-05-12-09`
**Invalidated**: 2026-05-12
**Yaml sha256 (preserved)**: `351e6e2ce004ef5a96a92ebe85f394ee193467dab78b60e4deb94c14ec0c424f`

## Why INVALID

Mining run produced 200/200 PRUNED trials in 2.1 min wall-clock. 0 trials
reached backtest evaluation due to sampler-architecture mismatch with
17-family RESEARCH_FACTORS expansion (PRD 20260512).

Combinatorics:
- 17 families × suggest_int(0, 2) → expected total ≈ 17 features
- yaml `composite_cardinality: 3` → 0.0005% hit rate (100k Monte Carlo confirmed 0 hits)
- cycle04-08 had 6 families × max=2 → 2.74% hit rate → ~5.5 archived per 200 trials

## NOT 0-nominee verdict

yaml.stop_rule_post_cycle.if_zero_nominee assumes "searched but didn't find alpha".
This is "didn't actually search" — sampler PRUNED every spec before evaluation.

## Forensic evidence preserved (NOT deleted)

- yaml (sha256 locked):
  `data/research_candidates/track-c-cycle-2026-05-12-09_promotion_criteria.yaml`
- launcher:
  `dev/scripts/cycle09/run_cycle09_mining.py`
- closeout script:
  `dev/scripts/cycle09/cycle09_closeout_analysis.py`
- mining log:
  `data/ml/research_miner/track-c-cycle-2026-05-12-09/mining_stdout.log`
- postmortem:
  `docs/memos/20260512-cycle_09_sampler_architecture_postmortem.md`

## Re-fire authorization

cycle #09 can be re-fired with same yaml (same sha256) ONLY after
**Option A sampler refactor** ships:
- `core/mining/research_miner.py::suggest_composite_spec` adds
  `sampling_mode: family_first` (or equivalent) that gives P(valid spec) ≈ 100%
- cycle04-08 regression check passes (bit-for-bit archive reproducibility
  on at least cycle08's top trial)
- this INVALID marker can then be removed; yaml stays sha256-locked

## Operator decision (2026-05-12)

Per user explicit-go 2026-05-12 "同意 A和C同时跑":
- Option A (sampler refactor) starts immediately
- Option C (alt-archetype A intraday reversal Phase 1) starts in parallel
- cycle #09 yaml stays marked INVALID until A ships + regression check passes
