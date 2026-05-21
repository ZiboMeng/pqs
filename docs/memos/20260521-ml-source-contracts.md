# ML Source Contracts — Package P0

**PRD**: `docs/prd/20260521-rerisk-and-ml-training-audit-prd.md` §4.5 / §4.6 / §12.3 P0
**Config SoT**: `config/ml_sources.yaml`
**Env floor**: `data/audit/ml_env_floor_20260521.json`
**Lineage**: `rerisk-and-ml-training-audit-2026-05-21`
**Created**: 2026-05-21 (ralph-loop Round 10)

P0 establishes the source-tier + point-in-time (PIT) contract that every
downstream ML training / acceptance driver must obey. It is a spec
package — no model is trained here.

---

## 1. Environment floor

`data/audit/ml_env_floor_20260521.json` records the research environment:

| module | version |
|---|---|
| python | 3.14.4 |
| xgboost | 3.2.0 |
| lightgbm | 4.6.0 |
| numpy | 2.4.4 |
| pandas | 3.0.2 |
| scikit-learn | 1.8.0 |
| scipy | 1.17.1 |

Both `xgboost` and `lightgbm` import cleanly → the P0 environment gate
is satisfied. LightGBM availability means the PRD §1.4 dependency
blocker is gone; the PRD §12.6 LightGBM-parity path is wiring, not a
dependency question.

## 2. Source tiers (PRD §4.5)

Six mandatory tiers + one optional, defined in `config/ml_sources.yaml`:

| tier | mandatory | status | one-line |
|---|---|---|---|
| A market_data | yes | present | daily adjusted OHLCV, benchmarks, sector/factor/macro ETFs |
| B fundamentals | yes | partial | PIT financial statements; quality/leverage/accrual/... |
| C macro | yes | partial | macro series, regime state, rates, vol, credit proxies |
| D event_calendar | yes | partial | earnings dates, macro-event windows, corp actions |
| E execution_liquidity | yes | partial | ADV/$volume, spread proxy, participation constraints |
| F portfolio_state | yes | partial | holdings, exposures, drawdown state, fill quality |
| G enrichment | no | optional | text/news/filings, options surface, alt-data, intraday |

Every mandatory tier has a declared contract (status / canonical
source ids / pit_rules / freshness / gaps) → the P0 "declared
contract" gate is satisfied.

## 3. Point-in-time rules (PRD §4.6)

Global PIT rules (apply to every tier; verbatim in `ml_sources.yaml`):

- every record attributable to a source id + timestamp;
- every feature reproducible from frozen raw inputs;
- no post-publication revisions without explicit vintage handling;
- no sector/benchmark/membership metadata using future composition
  knowledge (membership itself must be point-in-time);
- all event features use the first tradeable timestamp AFTER public
  availability.

Tier-specific: filings → SEC EDGAR PIT availability; macro →
FRED/ALFRED release/vintage model; news/text → publication timestamp +
ticker-mapping provenance + dedup; options → chain timestamp + contract
metadata + liquidity/stale-quote filters; intraday → exchange-calendar
alignment + regular-session policy + missing-bar handling.

## 4. Gap table (tiers needing closure before production use)

| tier | gap | must close before |
|---|---|---|
| B fundamentals | PIT filing-availability gating not enforced end-to-end | tier-B features enter a production training panel |
| C macro | release/vintage awareness only partial | tier-C features depend on publication timing |
| D event_calendar | unified event-calendar contract not centralized | tier-D event features used beyond PEAD |
| E execution_liquidity | present as scattered inputs, not first-class | E becomes an allocation input (P3) |
| F portfolio_state | present in exec/rebalance stack, not in ML acceptance | F wired into ML acceptance (P4) |

Tier A is the only `present` tier; the ranking baseline (P2) therefore
starts on tier A and adds B–F as their gaps close. This is consistent
with PRD §12.5's first-slice scope.

## 5. Training-driver contract

`ml_sources.yaml::driver_contract`: every ML training / walk-forward
driver must record a `source_tiers` list (the tier ids it consumed) in
its artifact metadata; a missing or empty `source_tiers` fails closed.
This is enforced from Package P2 onward (the first package that builds
ML training drivers). No ML training driver exists yet, so there is
nothing non-compliant today — the contract is established ahead of the
drivers, by design.

## 6. P0 gate verification (PRD §12.3)

| gate | status |
|---|---|
| every mandatory source tier has a declared contract | ✅ 6/6 (A–F in ml_sources.yaml) |
| environment can import xgboost and lightgbm | ✅ env floor json, both import |
| no training driver remains source-agnostic in artifact metadata | ✅ contract established (`driver_contract`); enforced from P2 — no ML training driver exists yet to violate it |

**P0 CLOSED.** Next: Package P1 — canonical labels + split discipline.
