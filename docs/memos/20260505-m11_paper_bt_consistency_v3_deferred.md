# M11 paper-BT consistency gate (pack v3) — DEFERRED with ad-hoc CLI shipped

**Status**: DEFERRED at acceptance_pack integration layer
(2026-05-05). Ad-hoc replay-diff CLI SHIPPED at
`dev/scripts/audit/replay_equity_diff.py`. Operators can run
consistency check on any candidate manually.

**Authority**: priority realign memo
`docs/memos/20260430-priority_realign_alpha_first.md`
("pre-emptive guard work is over until evidence justifies");
resident-quant principle (CLAUDE.md system prompt §Doing tasks
"Don't add features beyond what the task requires").

---

## Background

Framework completion TODO M11 (P1.5 in original PRD). After M11a +
M11b shipped 2026-04-24:

- **M11a** (`docs/memos/20260424-m11_paper_engine_parity_fix.md`):
  fixed `set(...)` iteration order non-determinism in
  `_generate_orders` → 0 bps drift across cross-process paper runs.
- **M11b** (same memo §2.1+§6): fixed PaperTradingEngine vs
  BacktestEngine semantic gaps (EOD equity using prev-day close;
  signal_date off-by-one).

What remains for "pack v3 gate":

> New gate: replay spec over recent 126d window, diff equity vs fresh
> backtest, fail if > 10 bps drift. Currently skip-PASS; M1
> single-source already covers constructor layer but engine-level
> drift not verified.
> (`docs/20260424-claude_md_phase_e_history.md` §M11)

i.e. wire the replay-vs-stored consistency check into
`core/mining/acceptance_pack.py` as a new `GateResult` with the 10
bps threshold and skip-PASS fallback for archive-only acceptance runs.

---

## Why deferred (acceptance_pack wiring)

1. **0 immediate consumer**:
   - No active mining run (Track C cycle #06+ pending user authorization;
     5.4 OOS-only discipline holds).
   - No active promote flow (RCMv1 + Cand-2 aborted; trial9 in
     observation, TD60 ~2026-07-30).
   - First gate consumer = the next mining candidate that survives
     Track A acceptance — earliest plausible date depends on user
     unfreezing research workstream after Trial 9 TD60.

2. **Plumbing-without-consumer rule**: per priority realign +
   `bmv_schema_decision.md` precedent, schema/wiring locked before
   consumer exists is dead code that decays. Acceptance_pack is one
   of the most consumer-sensitive surfaces (codex round-13 frozen
   contract); changing it without a candidate to validate against
   risks breaking gates without realizing.

3. **Existing M11a + M11b verification is adequate today**: 0 bps
   drift across 2451 bars of trial9 replay (verified 2026-05-05 via
   the CLI shipped this commit). The bug class M11 was designed to
   detect (cross-process replay drift) is empirically NOT present in
   the current engine. M11 gate would catch FUTURE regression,
   which has zero probability when no engine code is being modified.

---

## What WAS shipped (non-deferred ad-hoc CLI)

`dev/scripts/audit/replay_equity_diff.py` — standalone diagnostic:

```bash
python dev/scripts/audit/replay_equity_diff.py \
  --candidate-spec-yaml data/research_candidates/<spec>.yaml \
  --stored-nav-parquet <path>.parquet \
  --start YYYY-MM-DD --end YYYY-MM-DD \
  --top-n 10 --initial-capital 10000 \
  --max-drift-bps 10 \
  --output-json <out>.json
```

Behavior:
- Replays spec via BacktestEngine (real T+1 open + cost model from yaml)
- Aligns to stored NAV; computes per-bar bps drift
- Reports max abs / mean abs / last-bar drift + total-return drift
- Exit 0 if max abs drift ≤ threshold; exit 1 otherwise; exit 2 on
  input/replay error
- Optional `--output-json` for downstream consumption

Verified live 2026-05-05 on trial9 (Arm A baseline NAV from P2
Step 5b run): **0.0 bps drift** across 2451 bars. Confirms M11a/M11b
fixes hold regression-stable.

Operators can now run consistency check ad-hoc on any candidate
without acceptance_pack rearchitecture.

---

## Activation triggers (clear path to un-defer)

Implement acceptance_pack Gate 8 (`paper_bt_consistency`) when:

- **Trigger A**: a Track C cycle (#06+) produces a candidate that
  passes Track A acceptance + reaches `S2_paper_candidate` stage.
  Stored paper-layer NAV exists; gate adds value as regression
  detector against future engine changes.

- **Trigger B**: BacktestEngine code is modified for any reason
  (performance, bug fix, new feature) and the maintainer wants
  fleet-wide regression coverage. Gate then catches drift across
  ALL frozen candidates simultaneously.

Either trigger justifies the wiring cost. Without one, gate is
plumbing for plumbing's sake.

---

## Implementation sketch (when activated, ~2h)

1. Add `GateResult` named `paper_bt_consistency` to
   `core/mining/acceptance_pack.py`. Position: after Gate 7 (M12
   concentration) since both consume `fresh_check`.

2. Threading:
   - `fresh_check["replay_max_abs_drift_bps"]` — added by the caller
     when replay-vs-stored is meaningful (i.e. paper layer has stored
     NAV)
   - skip-PASS when `replay_max_abs_drift_bps is None` (archive-only
     run with no paper output)
   - PASS when `<= 10.0`; FAIL otherwise

3. Threshold source: extend `core/config/schemas/acceptance.py`
   `AcceptanceThresholds` with new `m11_max_abs_drift_bps: float =
   10.0` field. Wire through cfg.acceptance.m11_*.

4. Caller integration: producers of `fresh_check` (today: dev
   scripts that pre-compute fresh metrics) call the same
   `_compute_drift_stats` helper from `replay_equity_diff.py` (ideally
   factored out into `core/research/consistency.py` first).

5. Tests: 4 cases — drift 0, drift 5 bps (PASS), drift 15 bps (FAIL),
   skip-PASS when fresh_check has no replay key.

Estimated effort: 2h (with the CLI in this commit covering most of
the algorithm).

---

## Reversibility

If acceptance_pack Gate 8 is shipped and later proves over-strict /
flaky:
- Set `m11_max_abs_drift_bps` in yaml to a permissive value (e.g.
  100 bps) → gate becomes effectively informational
- Or revert the GateResult append; pack continues with 7 gates as today
- The ad-hoc CLI in `dev/scripts/audit/` remains usable regardless

No data destruction, no manifest mutation — Gate 8 is purely a
verdict producer, not a state mutator.

---

## OOS discipline

CLI replay range is operator-supplied; default callers (P2 verification
2026-05-05) used 2018-2025. No 2026-05-04+ data needed for this
diagnostic. When future trigger fires, gate can validate against
stored NAV that includes 2026+ TDs without violating OOS — the
replay/stored comparison consumes the same data on both sides
(symmetric, not training).

---

## Files

- `dev/scripts/audit/replay_equity_diff.py` — ad-hoc CLI (this commit)
- `data/audit/trial9_replay_consistency.json` — reference verification
  output (0.0 bps drift)
- `docs/memos/20260424-m11_paper_engine_parity_fix.md` — M11a + M11b
  fixes (already shipped)

## What is NOT shipped (intentionally deferred)

- `core/mining/acceptance_pack.py` Gate 8 wiring
- `core/research/consistency.py` shared helper module
- `core/config/schemas/acceptance.py::AcceptanceThresholds.m11_*`
  threshold field
- Acceptance_pack regression tests for the new gate
