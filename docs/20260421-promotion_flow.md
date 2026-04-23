# Strategy Promotion Flow (PRD M2)

This document describes how a mining archive trial becomes the active
production strategy. It is the authoritative procedure — no other path
(manual yaml edit, archive promote without acceptance, etc.) is allowed.

## Overview

```
Mining archive  ──spec_id──▶  acceptance_pack.py  ──gate results──▶  promote_strategy.py  ──yaml write──▶  git commit
```

## Steps

### 1. Identify candidate spec_id

```bash
python scripts/run_mining.py --leaderboard --lineage-filter 'my_tag'
# Pick a spec_id that looks best; prefix is enough for CLI convenience
```

### 2. Run acceptance pack (standalone, read-only)

```bash
python scripts/acceptance_pack.py --spec-id 81f5cdaa --verbose
```

Output: 9 boolean gates + JSON artifact written to
`artifacts/acceptance_packs/acceptance_<id>_<ts>.json`.

The 9 gates:
1. `quick` — full-period Sharpe ≥ 0.30, MaxDD ≤ 40%, CAGR ≥ 2%
2. `oos_walk_forward` — IR ≥ 0.20, pass_rate ≥ 0.55, excess ≥ 2%
3. `robustness` — regime + cost + param + stress all true
4. `diversity` — correlation ≤ 0.70 with existing promoted
5. `holdout` — last-252d forward-block passes
6. `max_drawdown` — absolute ≥ -25%
7. `concentration` — runtime soft-cap (skip-pass in pack v1)
8. `paper_backtest_alignment` — M1 contract (skip-pass in pack v1)
9. `qqq_hard_gate` — CAGR > QQQ on full + holdout + OOS avg

### 3. Promote (dry-run first)

```bash
python scripts/promote_strategy.py --spec-id 81f5cdaa --dry-run
```

Shows the proposed `config/production_strategy.yaml` and the diff vs
current. Nothing is written.

### 4. Promote (actually write)

```bash
python scripts/promote_strategy.py --spec-id 81f5cdaa --promote
```

This:
- Re-runs the acceptance pack (must PASS)
- Rewrites `config/production_strategy.yaml` with:
  - `status: "active"`
  - `source.mode: "promoted_from_archive"`
  - `source.spec_id / lineage_tag / promoted_at`
  - `validation.*` all true
  - `fingerprints.*` computed from current repo state
- Does NOT commit — you must review + commit manually

### 5. Review & commit

```bash
git diff config/production_strategy.yaml
pytest tests/unit/config/test_production_strategy.py tests/integration/test_single_source_of_truth.py
git add config/production_strategy.yaml
git commit -m "promote 81f5cdaa to production"
```

## Force mode (emergency only)

If a specific spec_id must be promoted despite acceptance pack failure
(e.g., a known false-positive failure in one gate that has been manually
verified safe), use:

```bash
python scripts/promote_strategy.py --spec-id X --promote --force --yes-i-know-what-im-doing
```

The `--yes-i-know-what-im-doing` flag is a deliberate footgun guard. Do
NOT script around it. Document the rationale in the commit message.

## Returning to a safe state

If a promoted strategy misbehaves in live paper, revert by:

```bash
# Option A: git revert the promote commit
git revert <sha>

# Option B: explicitly set status back to conservative_default
# Edit config/production_strategy.yaml manually:
#   status: "conservative_default"
#   source.mode: "manual"
#   (clear spec_id / lineage_tag / promoted_at / fingerprints)
#   validation.*: all false

# Option C: set status to no_validated_best (hard block)
# This forces users to promote a new spec_id before live paper can run.
```

All three are valid; choose based on urgency.

## Runtime alignment (M3, forthcoming)

When M3 lands, every `run_backtest.py` / `run_paper.py` startup will
compare current repo fingerprints (universe hash / factor registry hash /
config hash) against the yaml's `fingerprints.*`. Mismatches will WARN
(phase 1) or FAIL live paper (phase 2). If you change factor registry or
universe after promoting, re-run the promote flow.

## Acceptance pack v2 (2026-04-21 — post first-promote rollback)

**History**: v1 trusted archive row as authoritative evidence. A real
promote attempt on `6d15b735a64c` showed the archive's `quick_cagr`
(25.6%) and `qqq_full_period_excess` (+6.17%) came from the **quick
70% data fraction**, not full-period. When the production test ran a
fresh backtest it showed CAGR 14.0% < QQQ 17.6% (-3.6% excess). The
yaml was reverted and pack v1 upgraded to v2.

**v2 additions**:
- New gate 10 `full_period_fresh_backtest` — re-runs MultiFactorStrategy
  with spec params on current full price panel, computes actual CAGR vs
  QQQ, fails if excess ≤ 0
- `run_acceptance_pack(..., run_fresh_backtest=True)` by default
- CLI `--skip-fresh-backtest` for debug only

**Still skip-pass in v2** (enforced elsewhere):
- `concentration` — runtime `soft_cap_max_single` in risk.yaml
- `paper_backtest_alignment` — M1 single-source-of-truth by construction

**v3 roadmap** (still open):
- Run paper-BT consistency check during promote (daily + intraday replay diff)
- Multi-horizon stress test (cost × 3, regime × single-sector)
- Per-regime CAGR vs QQQ (diagnostic, not hard gate)

For highest-confidence promotion, supplement v2 with manual:

```bash
python scripts/run_backtest.py --strategy multi_factor
python scripts/run_paper.py --mode replay --from-date 2024-01-02 --to-date 2024-06-30
```

See PRD `docs/20260421-prd_framework_completion.md` §M2 for roadmap.
