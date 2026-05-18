# track-c-cycle-2026-05-18-13 — INVALID (preflight contract violation)

**Date**: 2026-05-18
**Status**: **INVALID MINING RUN** — NOT a 0-nominee verdict.
**Class**: same as cycle09 INVALID (CLAUDE.md) — A++ panel-availability
contract fail-closed, sampler-vs-panel mismatch, 0 backtest evals.

## What happened
cycle13 launched on the sha256-locked criteria yaml (`da92193…`).
A++ patch (2026-04-30) panel-availability contract fired:
- `factor_registry_pool=RESEARCH_FACTORS` sampler can reach **187**
  factors across 20 families.
- Panel pipeline produced **184**.
- **3 unreachable** (missing panel, unmet daily-mining data
  dependency): `intraday_autocorr_21d`, `intraday_vol_ratio_21d`,
  `realized_vol_60m_21d` — these need 60m/intraday panels not built
  in the daily mining path.
- Contract fail-closed (correctly — the project's own guard). **0
  archived trials.**

## Why INVALID, not 0-nominee
Per yaml.stop_rule_post_cycle, "0 nominee" means "searched but found
no alpha". This is "did NOT search" (preflight abort) — INVALID, same
as cycle09 (CLAUDE.md INVALID precedent).

## Immutability honored
The cycle13 criteria yaml is sha256-locked + committed (`87693a1`).
Per its IMMUTABILITY CONTRACT it is **NOT retro-edited** ("wrong-in-
hindsight → next cycle, never retroactive softening"). The error
message's prescribed resolution (b) — declare the 3 intraday factors
under `mining_config.explicit_exclusions` with a documented data-
dependency reason — is applied in a NEW pre-registered lineage
**track-c-cycle-2026-05-18-13b** (same single-axis, corrected yaml),
mirroring the cycle-2026-05-01-01 → -02 INVALID→corrected precedent.

## Operator self-audit note
Caught by the A++ guard at launch (operator, not user). The cycle13
yaml inherited cycle12's pool declaration but did not carry forward
the intraday explicit_exclusions that a RESEARCH_FACTORS daily-mining
run requires. Forensic artifacts (yaml + this marker + cycle13_mining.
log) preserved per immutability. No sealed data read (panel max date
2024-12-31, verified in log).
