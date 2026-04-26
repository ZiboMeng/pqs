# Forward OOS Observation Log

Per-day record of the forward observation ritual triggered by user
signal "new daily data has arrived". Append-only, one entry per
day per ritual run. The manifest files
(`data/research_candidates/<id>_forward_manifest.json`) are the
canonical record of TD entries; this log is the human-readable
heartbeat showing **when** observations were attempted, what state
the data was in, and what got appended.

Workflow: `docs/prd/20260426-forward_oos_runner_prd.md` + memory
`feedback_forward_observation_ritual.md`.

Entry format:

```
## YYYY-MM-DD (UTC)
- data_state: <SPY latest date / how many syms behind>
- RCMv1: <can_append? appended N TDs (latest TD<NNN> @ date) or no-op>
- Cand-2: <same>
- notes: <source_mix changes / readiness flags / anomalies>
```

---

## 2026-04-26 (UTC) — initial state pre-ritual

State at end of R-fwd-1 setup + post-MVP audit fixes (commit
`3aa3866` and prior). NOT a ritual run — recorded here as the
baseline before daily observation begins:

- data_state: SPY latest 2026-04-24; all 78 universe syms at 2026-04-24
- RCMv1: TD001 @ 2026-04-24 / cum_ret=0.00% / source_mix=True
  (start_date=2026-04-24, n_runs=1, status=in_progress)
- Cand-2: TD001 @ 2026-04-24 / cum_ret=0.00% / source_mix=True
  (start_date=2026-04-24, n_runs=1, status=in_progress)
- notes: both candidates entered observation mode after timestamp-aware
  start_date fix (commit `04e89b5`); next ritual triggers on user
  signaling new data (expected next trading day = Mon 2026-04-27 close)

---
