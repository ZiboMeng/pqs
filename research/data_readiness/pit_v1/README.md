# PIT Data Readiness v1

This directory contains compact, reviewable Phase A evidence. It does **not**
contain raw vendor data, SEC response bodies, market returns, labels, signals, or
backtest results.

Artifacts:

- `source_inventory.json`: read-only inventory of the pre-existing local data.
- `prospective_latest.json`: manifest for the latest free prospective official-source capture.
- `readiness.json`: hash-bound G1-G12 decision and Phase B eligibility state.

The current state is intentionally fail-closed. Implemented schemas and passing
unit tests are not treated as evidence that the required historical data exists.

Reproduce the compact inventory and gate decision from the worktree:

```bash
python scripts/inventory_pit_sources.py \
  --contract config/pit_data_v1.yaml \
  --source-root /path/to/pqs \
  --output research/data_readiness/pit_v1/source_inventory.json

python scripts/build_pit_readiness.py \
  --contract config/pit_data_v1.yaml \
  --source-inventory research/data_readiness/pit_v1/source_inventory.json \
  --prospective-manifest research/data_readiness/pit_v1/prospective_latest.json \
  --output research/data_readiness/pit_v1/readiness.json

python scripts/verify_pit_data_readiness.py \
  --contract config/pit_data_v1.yaml \
  --readiness research/data_readiness/pit_v1/readiness.json
```

Raw prospective captures and their append-only ledger are kept under
`data/pit/` and intentionally ignored by Git. Preserve that directory as local
evidence; deleting it makes the compact manifest non-replayable.
