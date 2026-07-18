# Phase-two PAPER trading

The phase-two runtime is local, simulated and explicitly PAPER-only. It does not
contain broker credentials and cannot authorize LIVE.

## Runtime contract

`core/paper_trading/phase2_runtime.py` implements:

`daily event guard -> causal signal/regime slice -> strategy -> allocator ->`
`kill switch -> independent pre-trade veto -> order lifecycle -> simulated broker ->`
`internal ledger -> reconciliation -> atomic daily report`

- T close data may create a signal; execution uses the next tradable open.
- Missing, stale, duplicate and out-of-order events fail closed.
- Broker cash/positions/fill identities persist in a separate SQLite authority
  from the internal PAPER ledger so restart reconciliation can detect one-sided commits.
- Every order state and rejection reason appears in the daily report.
- Reconciliation mismatch, UNKNOWN order or timeout causes durable global pause.
- Risk-reducing liquidation is permitted only when it reduces an existing breach;
  stale data, manual pause and unreconciled state still block it.

Default files:

- `config/strategies.paper.yaml`
- `config/portfolio.paper.yaml`
- `config/regime.paper.yaml`

All three require `mode: PAPER` and `live_enabled: false`. Only
`dual_index_growth_v1` is enabled. External regime is quality fail-closed only;
the validation ablation rejected an additional risk-on timing gate.

## Reproducible commands

```bash
.venv/bin/python scripts/run_phase2_paper.py replay \
  --state-dir data/paper_trading/phase2_evidence_clean_29a5e61
.venv/bin/python scripts/run_phase2_paper.py status \
  --state-dir data/paper_trading/phase2_evidence_clean_29a5e61
.venv/bin/python scripts/verify_phase2_paper_evidence.py
```

The tracked summaries, not ignored SQLite state, are the review boundary under
`research/results/phase2/paper/`.

## Acceptance evidence

- Interval: 2023-01-03 through 2023-12-29, 250 sessions.
- Orders: 41 total; 35 FILLED, 6 risk REJECTED, 0 unresolved.
- End equity/cash: 112,281.5452 / 5,602.9720.
- Clean/restart/idempotent NAV hash:
  `de162a7596a7817db8dcf0017fcd05a57201ddf8628f2ee68c6d76c448270601`.
- Restart: equity, cash, positions, order counts/states and NAV hash identical.
- Idempotence: all 250 reports reused; no new order created.
- Faults: missing/stale/out-of-order/duplicate events, veto/kill/pause,
  UNKNOWN/timeout/partial/duplicate broker events, reconciliation mismatch,
  database failure and both broker-first/ledger-first crash boundaries passed.
- LIVE remained disabled throughout.

This is operational simulation evidence, not a claim of real-broker execution
quality or future profitability.
