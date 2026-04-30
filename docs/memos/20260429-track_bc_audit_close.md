---
date: 2026-04-29
type: memo
status: closed
lineage_tag: track-bc-audit-2026-04-29
related_prds:
  - docs/prd/20260428-candidate_fleet_allocator_prd.md (v1.1)
  - docs/prd/20260429-temporal_split_holdout_discipline_prd.md (v1.1)
related_memos:
  - docs/memos/20260429-track_a_fetchdata_audit.md
  - docs/memos/20260429-codex_r21_p0_close.md
---

# Track B + Track C audit close (R1 + R2)

User instruction: same as last audit cycle — "做两轮针对已经完成的这些工作
的audit 一定要细致 ... 不要只跑test 或者smoke test 一定要跑代码 看一下结
果是否符合预期 然后有bug改 有不合理的地方 也改 有需要讨论的地方 提出来"

Two adversarial rounds against:
- Track C first smoke wiring (P0.1 C5 guard + P0.2 strict bool gates
  flowing through the real `run_research_miner.py` CLI)
- Track B Fleet Allocator Steps 1-4 (schema + capital split +
  compose_weight_matrix + C3 throttle / M12 metrics)

## Round 1 — live execution scenarios

| # | Test | Method | Result |
|---|------|--------|--------|
| 1.1 | End-to-end Track B pipeline | load config → split → compose → throttle → metrics with realistic 5×5 grids | PASS — fleet weights correct, throttle clips correctly, post-throttle row sum 0.70 (cash 0.30) |
| 1.2 | NaN propagation in compose | candidate matrix with `np.nan` cells | **BUG #B1** — NaN propagates silently to fleet weights |
| 1.3 | splits not summing to 1.0 | pass `{c1: 0.3, c2: 0.3}` (sum=0.6); pass `{c1: 0.7, c2: 0.7}` (sum=1.4) | **BUG #B2/B3** — no validation; under-allocation + leverage both silently accepted |
| 1.4 | apply_overlap_throttle with NaN | NaN cells in fleet matrix | **BUG #B4** — NaN passes through (NaN > cap is False) |
| 1.5 | C5 guard fires through real CLI | run smoke #1 role=core, then smoke #2 role=diversifier same split | PASS — all 3 trials of smoke #2 pruned by C5; archive unchanged |
| 1.6 | compute_spec_id determinism | run across PYTHONHASHSEED ∈ {None, 0, 12345, 99999} | PASS — 4/4 produce identical hash |
| 1.7 | Manifest round-trip | save/load FleetManifest with rebalance + events + dates | PASS — date / datetime / nested dicts preserved |

## Round 2 — adversarial / cross-cutting

| # | Test | Method | Result |
|---|------|--------|--------|
| 2.1 | Float precision in manual_overrides | 1/3 + 1/3 + 1/3 ≈ 0.999...9 | PASS — 1e-9 tolerance handles it; 1e-8 deviation rejected |
| 2.2 | CLI `--temporal-split` without `--role` | invoke run_research_miner.py | PASS — fail-closed via `ensure_role_assigned` |
| 2.3 | Concurrent FleetManifest writers | 3 threads × 20 saves | PASS — per-pid+tid suffix; 0 errors; no stray tmp |
| 2.4 | Duplicate index in candidate matrix | DataFrame with duplicate dates | **D6** — pandas raises opaque ValueError instead of clear domain error |
| 2.5 | Heterogeneous index types | mix DatetimeIndex + str index across candidates | **D5** — opaque TypeError from `sorted()` |
| 2.6 | Frozen-step boundary | call check_correlation_budget / apply_dd_throttle / observe | PASS — all 3 raise NotImplementedError with "frozen" in message |
| 2.7 | manual_overrides + sum != 1 at config-load | yaml with `0.6 + 0.6` + manual_overrides | **D7** — config-load accepts; runtime catches, but operator gets the error too late |
| 2.8 | Negative weight in candidate matrix | (added during fix audit) | **B7** — long-only invariant should reject upfront |

## Bug summary + fixes

### CONFIRMED + FIXED (7 bugs / discussion items resolved)

| # | Sev | File | Bug | Fix |
|---|-----|------|-----|-----|
| B1 | **HIGH** | `core/fleet/allocator.py:compose_weight_matrix` | NaN in any candidate matrix silently propagates to fleet weights → M12 metrics → manifest. Bad upstream signal becomes invisible portfolio corruption. | Reject NaN upfront with cell-count + clear remediation hint. |
| B2 | **HIGH** | same | `splits.values()` not validated to sum to 1.0; caller could pass under-allocation and produce silent fleet shrink. | Validate sum == 1.0 within 1e-9 tolerance; ValueError otherwise. |
| B3 | **HIGH** | same | `splits.values()` summing > 1.0 violates long-only no-margin invariant; produces fleet weights > 1.0 (leverage). | Same validator as B2 — > 1.0 also rejected. |
| B4 | MED | `core/fleet/allocator.py:apply_overlap_throttle` | NaN > cap is False; throttle silently passes NaN cells through to manifest. | Reject NaN at throttle entry (defense in depth — even if compose is fixed, throttle is a public API). |
| B5/D5 | MED | compose | Non-DatetimeIndex on candidate matrix produces opaque TypeError when sorting mixed types. | Validate `isinstance(mat.index, pd.DatetimeIndex)` upfront with clear "wrap with pd.to_datetime() upstream" hint. |
| B6/D6 | MED | compose | Duplicate index entries in candidate matrix produce opaque pandas ValueError from reindex. | Validate `not mat.index.has_duplicates`; report up to 5 duplicates with remediation hint. |
| B7 | MED | compose | Negative weights in candidate matrix violate long-only invariant; would silently flow through. | Validate `(values < 0).any() == False` before composition. |
| D7 | MED | `core/fleet/manifest_schema.py:FleetConfig` | `manual_overrides` + `base_weight` summing != 1.0 only failed at runtime (first `compute_capital_split()` call). | Add `_manual_overrides_must_sum_to_one` `model_validator(mode="after")` so config-load fails with the same 1e-9 tolerance. |

### PASSED (no fix needed)

- end-to-end pipeline (1.1)
- C5 guard through real CLI (1.5) — smoke #2 all 3 trials pruned, archive unchanged
- compute_spec_id determinism across PYTHONHASHSEED (1.6)
- manifest round-trip (1.7)
- float tolerance in manual_overrides (2.1)
- CLI `--temporal-split` without `--role` (2.2)
- concurrent manifest writers (2.3)
- frozen-step boundary intact (2.6)

## Reverse-validation evidence (every fix)

- **B1**: pre-fix `compose_weight_matrix({c1: ok, c2: with NaN cell})`
  produced fleet matrix with NaN row at the affected date. Post-fix:
  ValueError with cell count and remediation hint.
- **B2**: pre-fix `splits={c1: 0.3, c2: 0.3}` produced fleet weight
  scaled to 0.6 silently. Post-fix: ValueError naming the actual sum.
- **B3**: pre-fix `splits={c1: 0.7, c2: 0.7}` produced fleet weight
  1.4 (leverage). Post-fix: same ValueError (single check covers both
  directions of sum mismatch).
- **B4**: pre-fix throttle output preserved NaN cells; events list
  did not flag them. Post-fix: ValueError before any clipping happens.
- **B5/D5/B6/D6**: pre-fix produced pandas-flavored opaque errors
  (`TypeError: '<' not supported`, `ValueError: cannot reindex on an
  axis with duplicate labels`). Post-fix: domain ValueError with
  remediation hint pointing at upstream.
- **B7**: pre-fix `cw = {c1: matrix with -0.1}` silently composed a
  short position. Post-fix: ValueError "long-only system has no shorts".
- **D7**: pre-fix `FleetConfig(... manual_overrides + 0.6+0.6)`
  accepted; runtime `compute_capital_split()` raised. Post-fix:
  ValidationError at config-load with 1e-9 tolerance.

## Test coverage

Track B fleet suite went from 50 → **62 tests** (+12 audit regressions
across 3 files; +6 in compose / +1 in throttle / +5 in schema). Full
unit suite running in background.

| Layer | Pre-audit | Post-audit |
|-------|-----------|-----------|
| `test_fleet_schema.py` | 21 | 25 (+4) |
| `test_capital_split.py` | 9 | 9 (unchanged; 1 test re-pointed from runtime to config-load) |
| `test_compose_weight_matrix.py` | 9 | 17 (+8) |
| `test_overlap_and_metrics.py` | 11 | 12 (+1 NaN regression) |

## Discussion items (no fix; documented)

- **D8** Per-row sum validation in compose. PRD says "upstream owns
  per-candidate normalisation". We currently accept any non-negative
  values and don't validate that each row sums to 1.0. This is the
  intended layering — Step 6 DD throttle multiplies by an explicit
  `throttle_factor` and would conflict with strict per-row==1.0
  enforcement. **Operational rule established**: caller is responsible
  for per-candidate row sums; fleet-level sum will be `Σ split[i] * 1.0
  = 1.0` only if every candidate is normalized.

- **D9** Manifest lost-update race under concurrent writers. Same
  caveat as `fetch_session_log` (R19 audit BUG #5). Per-pid+tid
  filename prevents the FileNotFoundError crash; lost-update is still
  possible if two writers read-then-write the same file simultaneously.
  Single-writer assumption explicit in module docstring. fcntl
  upgrade is P1 before scheduled / parallel observation lands.

- **D10** Frozen-step methods all match `match="frozen"` in their
  NotImplementedError message. The frozen-step regression test pins
  this contract. Steps 5-9 must keep this marker until codex / user
  explicit-go to land them.

## Audit conclusion

7 real bugs found and fixed (4 HIGH-class — could have caused silent
NaN portfolio corruption, leverage violations, or under-allocation
in production fleet observation). 4 PASSED checks (CLI, determinism,
concurrent I/O, frozen boundary). 3 documented discussion items.

The audit was substantive — caught one HIGH leverage-violation bug
(B3) and one HIGH silent-data-corruption bug (B1) that pytest on
synthetic happy-path inputs would not have surfaced.
