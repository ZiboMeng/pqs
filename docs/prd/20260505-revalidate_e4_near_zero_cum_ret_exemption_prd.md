# PRD — Revalidate E4 near-zero cum_ret exemption + policy recovery path

**Authors**: operator (zibomeng@), with Claude Code assist
**Date**: 2026-05-05
**Status**: SHIPPED 2026-05-05 (single-round operator-driven; user explicit-go for scope, no codex round)
**Triggered by**: trial9_diversifier_001 false-positive halt 2026-05-05 21:40 UTC

---

## §1 Background

`trial9_diversifier_001` first forward observation on 2026-05-04 produced
TD001 with `cum_ret = 0.0` (single-day, near-zero return is normal).

On 2026-05-05 (today's daily ritual), `observe()` triggered v2.1
`revalidate_manifest`. yfinance returned 2026-05-04 daily bars for 4
held symbols (LRCX / META / SOXL / XLK) with **3.8 ppm** of close-price
revision (yfinance's known T+0 vs T+1 round-trip behavior). Recorded
event:

```
estimated_nav_impact_bps  = 0.0962    # ≪ E1 threshold (10 bps)
raw_max_close_drift_pct   = 3.8e-5    # ≪ E5 threshold (0.5%)
estimated_cum_ret_drift_bps = 0.0962
decision_sign_flip = True             # E4 fired
policy_decision = "invalidated"       # halts manifest
```

E4's logic (`revalidate.py:480-487`):

```python
stored_cum = entry.cum_ret              # = 0.0 on TD001
drift_magnitude = abs(cum_ret_drift_bps) / 10000.0
if drift_magnitude >= abs(stored_cum):  # 0.000010 >= 0.0 → True
    decision_sign_flip = True
```

When `stored_cum = 0.0`, **any** non-zero drift trips E4 because zero
has no preserved sign. This is a known edge-case in the v2.1 design,
not an integrity problem with the data.

## §2 Root cause

E4 (cum_ret sign flip) was designed to catch decision-meaningful
direction changes, e.g., "candidate's TD60 cum_ret was +120 bps under
old data, +80 bps under new data — direction preserved" vs
"+5 bps → -5 bps — direction flipped". The latter changes a
checkpoint-level decision; the former does not.

But when `|stored_cum|` is below the noise floor of the revalidation
system itself, sign-flip is meaningless — the stored sign was already
random within noise, and "flipping" it conveys no decision-relevant
information.

E1 already encodes a noise floor for NAV impact (`NAV_IMPACT_BPS_THRESHOLD =
10 bps`). By symmetry, when the absolute baseline `|stored_cum|` is below
the same floor, the baseline's sign is itself sub-noise; sign-flip
events on it should not invalidate.

## §3 Fix — E4 near-zero exemption

Add a precondition to the existing E4 sign-flip rule:

```python
MIN_STORED_CUM_FOR_SIGN_FLIP_BPS = 10.0  # equal to NAV_IMPACT_BPS_THRESHOLD

# E4 is meaningful only if the stored cum_ret has a magnitude that
# would itself be decision-relevant. Below the noise floor, the
# stored sign is already noise; "flipping" it conveys no signal.
stored_cum_magnitude_bps = abs(stored_cum or 0.0) * 10000.0
stored_cum_above_noise = stored_cum_magnitude_bps >= MIN_STORED_CUM_FOR_SIGN_FLIP_BPS

if (stored_cum is not None and cum_ret_drift_bps is not None
        and abs(cum_ret_drift_bps) > 0
        and stored_cum_above_noise):                    # NEW gate
    drift_magnitude = abs(cum_ret_drift_bps) / 10000.0
    if drift_magnitude >= abs(stored_cum):
        decision_sign_flip = True
```

Threshold rationale:

| `|stored_cum|` regime | Old behavior | New behavior | Rationale |
|---|---|---|---|
| 0 bps (TD001) | E4 fires on any drift > 0 | exempt | sign of 0 is meaningless |
| < 10 bps | E4 fires on tiny drift | exempt | sub-E1 noise floor |
| ≥ 10 bps | E4 fires only if drift ≥ stored | unchanged | sign-flip is decision-relevant |

The threshold is tied to (the value of, not the symbol of)
`NAV_IMPACT_BPS_THRESHOLD` so the two noise floors are aligned but
independently revisable.

Other E1/E2/E3/E5 thresholds are NOT changed — they already operate
correctly. E4 is the only rule that uses `|stored_cum|` as the
denominator and therefore needs a noise-floor gate.

## §4 Recovery mechanism — `recover` CLI

`requires_data_review` is an absorbing state by design (codex round 19).
The existing CLI `decide` only mutates to terminal statuses
(success/fail/aborted), so a manifest halted by an E4 false-positive
under prior policy has no way back to `in_progress` without aborting +
re-init (loses TD001).

This PRD adds a `recover` subcommand that:

1. Loads the manifest, asserts `current_status == requires_data_review`.
2. Re-runs `revalidate_manifest` under the **current** policy code.
3. If the re-evaluation no longer escalates to `requires_data_review`
   (i.e., the original event downgrades from `invalidated` to
   `flagged_only`):
   - Update affected runs' `data_revision_event` with the new (less
     severe) event.
   - Append a new `PolicyRecoveryEvent` to a new `policy_recovery_log`
     field on the manifest (audit trail; lazy-migration compatible).
   - Flip `current_status` back to `in_progress`.
   - Save manifest.
4. If the re-evaluation still escalates to `requires_data_review`,
   raise `ForwardHaltError` with the current triggers — the operator
   must either revise policy further or `decide --status aborted`.

`recover` does NOT bypass any genuine drift — it only succeeds when
the same drift, under updated policy code, would not have halted
in the first place.

`PolicyRecoveryEvent` schema:

| field | type | purpose |
|---|---|---|
| `detected_at_utc` | datetime | when recover was invoked |
| `recovered_run_label` | str (e.g., "TD001") | which TD's event was re-evaluated |
| `prior_policy_decision` | "invalidated" | precondition |
| `new_policy_decision` | "flagged_only" | guaranteed by success branch |
| `prior_triggers` | list[str] | e.g., ["E4 cum_ret sign flip"] |
| `new_triggers` | list[str] | empty / non-invalidating |
| `prd_reference` | str | this PRD |
| `operator_note` | Optional[str] | freeform audit |

`extra='forbid'` per codex round-13/14 strict-schema convention.

## §5 Acceptance

| Gate | Test |
|---|---|
| **A1 E4 exempt at TD001** | `stored_cum=0.0 + drift=1bps` → `decision_sign_flip=False` |
| **A2 E4 exempt below 10 bps** | `stored_cum=±5bps + drift=±5bps` → `decision_sign_flip=False` |
| **A3 E4 still fires above floor** | `stored_cum=+50bps + drift=60bps` → `decision_sign_flip=True` |
| **A4 E4 boundary at exactly 10 bps** | `stored_cum=10bps + drift=11bps` → `decision_sign_flip=True` (above floor) |
| **A5 E1/E2/E3/E5 unaffected** | unrelated drifts retain prior behavior |
| **A6 recover() flips status** | manifest with TD001 invalidated by E4 alone → recover succeeds → status=in_progress + audit |
| **A7 recover() refuses on still-invalidated** | E1 invalidation (≥ 10 bps NAV) → recover raises ForwardHaltError |
| **A8 recover() refuses on non-halted** | status=in_progress → recover raises ForwardHaltError |
| **A9 PolicyRecoveryEvent persisted** | manifest reload after recover shows audit entry |
| **A10 trial9 actual recovery** | manual recover trial9_diversifier_001 → status flips → next observe produces TD002 |

## §6 Reversibility

- Revoke E4 exemption: revert revalidate.py change; re-run trial9
  observe — status will halt again on next near-zero cum_ret day.
  Manifests recovered under this PRD continue to function (event is
  just a frozen audit record); next revalidate under the reverted
  policy may re-halt.
- Revoke `recover` CLI: remove subcommand + helper. Existing
  `policy_recovery_log` entries remain on disk as audit (extra fields
  silently ignored).
- Adjust threshold: change `MIN_STORED_CUM_FOR_SIGN_FLIP_BPS` constant.

## §7 Out of scope

- ConfigDriftEvent halt recovery (different policy class; not
  addressed here).
- Auto-recovery on next observe (intentionally requires explicit
  `recover` invocation per audit-trail principle).
- Schema-level versioning (this is a code-policy change, not a
  schema change beyond the additive `policy_recovery_log` field).

## §8 4-layer self-audit (per memory `feedback_self_audit_methodology.md`)

- **R1 (factual)**: today's trial9 manifest + revalidate code reviewed
  at lines 480-487; root cause confirmed = E4 unconditionally fires
  when |stored_cum| ≤ drift, including when stored=0.
- **R2 (logical)**: threshold tied to E1's existing noise floor
  (10 bps). Below the floor, baseline sign is itself noise; above,
  E4 retains its decision-protection role.
- **R3 (run code)**: post-implement, run unit tests + run actual
  recover on trial9 + run subsequent observe → produces TD002.
- **R4 (boundary)**: stored_cum=10bps exactly (above floor); negative
  cum_ret with positive drift; multi-TD manifest where some entries
  are above floor; status set by config_drift_event (out of scope —
  errors); recover idempotency (re-run no-op).
