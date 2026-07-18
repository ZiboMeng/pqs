# Codex audit and hardening progress

Last updated: 2026-07-17 (candidate implementation ready)

## Current phase

Strategy Phase 2 — audit, certification, failure attribution, preregistration and candidate
implementation are complete. Development experiments are next; no candidate result has been
read and no strategy is promoted.

## Completed

- Read the complete audit/refactor/implementation mandate supplied with this task.
- Verified that `main` was clean and synchronized with `origin/main` at
  `a68694ba3ea751c137c56885d87a5d375d178762`.
- Created and pushed annotated rollback tag `codex-pre-takeover-20260717`.
- Created and pushed working branch `codex/quant-system-audit-and-hardening`.
- Began tracked-source inventory (1,702 tracked files; approximately 82 MiB) separately
  from the roughly 140 GiB local workspace dominated by untracked/ignored market data,
  caches, environments, and artifacts.
- Mapped the implemented data, regime, strategy, portfolio, execution, paper, options,
  persistence, and reporting paths and their dependency hotspots.
- Wrote the audit, current/target architecture, gap analysis, roadmap, decisions,
  assumptions, risk policy, operations runbook, and cloud-migration design.
- Verified configuration loading, the backtest and paper CLI parsers, and the installed
  environment (`pip check` passes).
- Captured static-analysis debt: Ruff reports 1,236 findings (674 auto-fixable) and mypy
  reports 127 errors in `core`.
- Reproduced an options-accounting defect that double-counts the opening credit in NAV.
- Implemented the completed-session freshness watermark and explicit BACKTEST/PAPER/LIVE
  authorization; LIVE requires two independent gates and remains disabled.
- Added an independent pre-trade veto, durable order IDs/idempotency/event ledger, explicit
  lifecycle, restart quarantine, and paper-runtime integration before fill simulation.
- Corrected options collateral/liability NAV accounting and made options observations
  lock-protected, atomic, and crash-idempotent.
- Added quality-aware regime confidence/UNKNOWN handling and a paper-live low-confidence veto.
- Removed the developer-specific BarStore root and cleared all 10 Ruff F821 findings.
- Raised vulnerable dependency floors: `pip-audit` moved from 16 findings in 4 packages to
  zero known vulnerabilities; `pip check` remains clean.
- Added CI, a non-root container definition, a read-only JSON health check, and task targets.
- Added durable global/strategy/symbol pause controls and an audited operator CLI; legacy
  options manifests are explicitly invalidated rather than mixed with corrected NAV.
- Added strict option contract/quote/chain provider boundaries, defined-risk combo and
  partial/legging models, portfolio Greeks/max-loss vetoes, and mismatch-triggered
  reconciliation pauses.
- Corrected backtest reporting so an unavailable live kill-switch state is shown as `N/A`,
  rather than the operationally misleading `normal`.
- Captured the first complete baseline: 4 failed, 4,077 passed, 21 skipped, 1 xfailed in
  1,938.15 seconds. All four failures were the missing declared LightGBM research extra;
  installing it made the focused 7-test module pass.
- Created and pushed rollback tag `codex-pre-strategy-research-20260717` and branch
  `codex/strategy-research-and-paper-v2` from `9ffc1ce`.
- Re-read all first-round governing documents and completed the dependency-traced cleanup,
  price/accounting, temporal-isolation, PAPER persistence, and regime audit in
  `docs/SECOND_ROUND_AUDIT.md`.
- Confirmed no historical document/code family is safely deletable: historical failures,
  temporal split versions, sealed ledgers, package boundaries, options safety code, and raw
  storage all have active runtime or evidence-lineage roles. Only a zero-byte untracked
  `.codex` placeholder was removed so the mandated state directory could exist.
- Reproduced raw-price contamination and a gap-down liquidation that sells roughly twice the
  held shares and creates cash. Also identified stale batch-risk snapshots and non-atomic
  FILLED-vs-account persistence in PAPER.
- Closed the three certification P0s: canonical total-return price access, 81-symbol
  distribution coverage/split-hash validation, and share-conserving gap execution.
- Closed actual-fill-bar and walk-forward-open drift, then made PAPER batch risk sequential and
  fill/order/account/checkpoint persistence atomic with safe VALIDATED retry after rollback.
- Passed 653 tests / 1 expected xfail and daily+intraday crash failure injection; generated
  `BACKTEST_CERTIFICATION.md` and a hash-stamped corrected baseline manifest.
- Classified dual momentum and cross-asset rotation as redesign hypotheses, retired the legacy
  daily trend and multi-factor promotion paths, and retained every failed artifact. The archive
  contains 65 multi-factor trials, all Tier D, with zero OOS or holdout passes.
- Preregistered four economically distinct ETF candidates, 41 bounded development cells in
  total, hypothesis-scoped development/validation/holdout dates, finalist access limits, and
  fixed numeric PAPER gates in `config/strategy_promotion.yaml` before candidate evaluation.
- Implemented adaptive stable core, capped/cooldown Nasdaq growth, long-lived sector ETF
  rotation, and daily ETF mean reversion with weight-contract and missing-input tests.
- Added an atomic experiment registry, common detailed-metrics/robustness runner, executable
  type-specific promotion policy, limited holdout access ledger, and deterministic bootstrap.
- Added an eight-state regime adapter with confidence, hysteresis, minimum duration, cooldown,
  UNKNOWN fail-close and switching/confusion statistics. Added per-strategy risk budgets,
  conflict resolution, aggregate symbol/gross caps, and a final fail-closed portfolio veto.
- Passed 17 new tests and scoped Ruff. Scoped mypy reports no errors in new code; its only output
  is two pre-existing imported-module errors in `source_boundaries.py` and `logging_setup.py`.

## In progress

- Commit and push the tested implementation, then preregister all development runs against the
  exact clean commit before loading their evaluation data.

## Next

1. Commit the clean implementation, preregister every development run, then evaluate development.
2. Freeze one winner per family using the predeclared score and commit all failures/results.
3. Validate only family winners on annual forward folds, 2x cost, delay and neighbor checks.
4. Admit only qualifying frozen finalists to the limited holdout and PAPER replay.

## Unresolved issues

- Top-level documentation explicitly describes the system as research and internal
  simulation, not a real broker-connected trading system; the requested LIVE boundary and
  production safety controls must be assessed against that actual scope.
- The durable paper order lifecycle is now enforced before simulation, but a real external
  broker is still absent and the adapter is not yet the authoritative cash/position source.
- Options now have strict quote quality, combo, Greeks, and max-loss boundaries, but still use
  synthetic Black-Scholes marks and have no historical real-chain evidence; corrected NAV makes
  prior options paper artifacts methodologically obsolete.
- Full-repository Ruff/mypy debt remains beyond the cleared F821 and new safety packages.
- The old 2026 sealed interval has already been consumed and cannot be reused as pristine
  evidence. Phase-two final validation must be preregistered, narrowly accessed, and described
  honestly rather than relabeling old data.
- Dividend coverage has been refreshed and fail-closed validated for all 81 executable symbols
  through the applicable source cutoff. Rebuilding it still depends on external upstream data,
  but the committed manifest hashes make the current certification reproducible.

## External blockers

- None for audit and local implementation.
- Real broker credentials, commercial point-in-time options data, a cloud account, and live
  capital authorization are intentionally outside the current local implementation scope.

## Latest test result

Phase-two focused baseline: 601 passed, 1 xfailed, 0 failed in 165.64 seconds across
backtest, execution, PAPER, order/risk, price semantics, regime, temporal split, and
backtest/PAPER integration. The earlier quick safety gate also remains green at 195 passed,
2 skipped plus config, Fatal Ruff, F821, and focused mypy. These baselines describe existing
behavior; the newly recorded counterexamples cover invariants the suite did not previously test.

First-round full-suite history follows and is retained for provenance.

Baseline: 4 failed, 4,077 passed, 21 skipped, 1 xfailed in 32:18. The four failures were
`ModuleNotFoundError: lightgbm`; the README-prescribed `.[dev,research]` environment resolves
them and the focused module is 7/7 green.

Second full suite after installing the declared research extra: 4,115 passed, 23 skipped,
1 xfailed, 0 failed, 53 warnings in 2,076.92 seconds (34:36). Because this run collected
before the final controls/options/reporting tests were added, a consolidated focused acceptance
also ran: options 65 passed/2 skipped and the remaining safety/reporting/operations set 130/130
passed. Fatal Ruff/F821 pass; mypy passes across 24 trading/runtime/options modules; config,
`pip check`, `pip-audit`, and read-only health check pass.

This host does not provide `docker` or `make`, so the Docker image build and Makefile wrapper
could not be executed locally; CI definitions, Dockerfile semantics, and the underlying commands
were inspected/tested, but an actual container build remains an environment-level verification gap.

## Latest backtest result

Corrected phase-two diagnostic (total-return basis, real T+1 open, current costs, 2007-01-03 to
2026-07-17): dual momentum CAGR 5.7% / IR -0.33 / MaxDD -22.0%; trend following -1.5% /
-0.71 / -30.2%; cross-asset rotation 4.2% / -0.43 / -11.1%; multi-factor 8.0% / -0.23 /
-15.0%; SPY CAGR 10.9%. No strategy qualifies. See `BACKTEST_CERTIFICATION.md`.

The phase-one diagnostic numbers below are retained as historical output, but are not valid
promotion evidence because that runner used raw prices and non-conserving SELL sizing.

Paper status smoke passes at $100,000 cash/equity and no positions. Mining leaderboard loads
65 historical trials; every candidate is Tier D and none passed OOS or was promoted.

Fresh no-walk-forward run on 4,915 dates × 81 symbols (2007-01-03 through 2026-07-17):

- dual momentum: CAGR 4.6%, Sharpe 0.10, MaxDD -35.7%, IR -0.27;
- trend following: CAGR -0.2%, Sharpe -0.81, MaxDD -17.5%, IR -0.57;
- cross-asset rotation: CAGR 2.8%, Sharpe -0.15, MaxDD -13.2%, IR -0.39;
- multi-factor: CAGR 2.8%, Sharpe -0.02, MaxDD -55.2%, IR -0.33;
- SPY benchmark: CAGR 8.9%, Sharpe 0.33, MaxDD -56.5%.

No strategy is promotion-ready: every IR is negative, and dual-momentum/multi-factor breach
the configured 25% halt drawdown. This run intentionally skipped walk-forward and is diagnostic,
not OOS evidence.

## Key file changes

- Audit docs plus runtime, trading, risk, reconciliation, options domains, regime, security,
  data portability, CI, container, health-check, and operator controls are committed through
  `6d8e444`; documentation updates are this final close-out commit.

## Acceptance checklist

- [x] Evidence-based audit and accurate architecture/data-flow diagrams
- [x] Every P0/P1 finding fixed locally or supported by explicit external-blocker evidence
- [x] Reproducible `.[dev,research]` install, fatal lint, safety-package type-check, and full tests
- [ ] Shared, time-correct BACKTEST/PAPER business logic
- [x] Independent fail-closed risk veto and tested kill switches
- [ ] Durable idempotent order lifecycle and recovery are complete; external-broker authority blocked
- [ ] Cost/slippage-aware OOS and walk-forward backtest evidence
- [ ] Stable base, risk-on core, capped growth engine, and defined-risk options candidate
- [ ] End-to-end paper flow including failure, partial fill, restart, and report evidence
- [x] Operations runbook, health check, CI/container baseline, and cloud migration design
- [x] LIVE remains disabled until explicit human authorization and configuration
