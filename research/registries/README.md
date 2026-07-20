# Phase 3 research registries

This tree contains Phase 3 immutable strategy artifacts and future submission
registries. It does not replace the Phase 2 decision records under
`research/registry/`; those remain authoritative historical evidence.

`strategy_artifacts/<strategy_id>/<version>.json` files are canonical JSON,
content-addressed by `artifact_root_sha256`, created atomically, and made
read-only. They must be verified with:

```bash
.venv/bin/python scripts/freeze_phase3_strategy.py verify
```

An artifact conflict or component drift is a stop condition. Never edit an
artifact in place; create a new unapproved strategy version instead.
