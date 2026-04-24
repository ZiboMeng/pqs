# CLAUDE.md Phase-E History Archive

Detail blocks moved out of `CLAUDE.md` during Phase E-post R8
(2026-04-24) to keep CLAUDE.md under 800 lines and focused on active
execution context. Each section below was the full "Current TODO"
entry in CLAUDE.md at the time of archiving.

For the Phase B / C history see
`docs/20260422-claude_md_phase_bc_history.md`.
For per-round 11-part Chinese reports see
`docs/20260420-ralph_loop_log.md`.

---

## Deep Mining 50-round (2026-04-22 COMPLETE)

See `docs/20260422-deep_mining_50round_final_synthesis.md`. 7 tracks
× 50 rounds autonomous execution finished. 5 user decisions were
pending; some resolved via RCMv1 downstream work.

7 tracks:
- daily+ML (R1-R15)
- intraday (R16-R25)
- DSL (R26-R33)
- universe expansion (R34-R41)
- XGBoost rigor (R42-R46)
- transformer hyperparameter (R47-R48)
- final synthesis (R49-R50)

Hard goal: ≥1 spec passes pack v2 all 10 gates and promotes to
status=active.

**Autonomous Decision Rules** (user pre-authorized 2026-04-22):
- **Auto-promote** when pack v2 ALL 10 gates PASS + OOS IR ≥ 0.25 +
  QQQ excess ≥ +2% + max single weight ≤ 0.35
- **R38 universe**: produce proposal doc only, DO NOT edit yaml
- **R7/R10/R14 factor → RESEARCH_FACTORS**: auto-add if funnel +
  deep_check PASS; **→ PRODUCTION_FACTORS**: proposal doc only
- **R30 DSL funcs**: auto-add `ratio/zscore/rank_cs/breakout` with tests
- **R46 XGB**: auto-park as research-only + findings doc
- **R50 final**: promote if anything passed 11.1; else blocker report
- Halt only on §11.8 stop conditions (pytest regression > 5, core
  import failure, disk < 10GB, unexpected config edits, archive
  corruption, 3rd --force promote in one loop)

---

## RCMv1 20-round (2026-04-24 COMPLETE)

Research Composite Miner v1 + 12 orthogonal features. Key deliverables:

- **R15 leakage fix**: `evaluate_composite(lag=1)` default (was 0).
  Pre-fix shared-close[t] IC values were inflated ~10x.
- **R17 converged spec** `{beta_spy_60d, drawup_from_252d_low,
  days_since_52w_high, amihud_20d}` IC_IR +0.50 (formerly +4.77 pre-fix).
- **R18 acceptance PASS** (4/4 walk-forward folds + 6/6 regimes positive).
- **R20 S1 Research Candidate** promotion memo
  `docs/20260424-rcm_v1_s1_candidate_memo.md` (doc-only; does NOT
  touch production_strategy.yaml).
- See `docs/20260424-rcm_v1_final_synthesis.md`.

---

## Codebase Audit 3-Round v1 (2026-04-24 COMPLETE)

PRD `docs/20260424-prd_codebase_audit_3round.md`, lineage
`audit-2026-04-24`. Deliverables:

- R1 core library (27 modules, 0 functional bugs)
- R2 scripts/IO (57 scripts + 13 modules, 0 functional bugs)
- R3 tests + README sync + baseline rebuild

---

## Codebase Audit 3-Round v2 (2026-04-24 COMPLETE)

Same PRD, lineage `audit-2026-04-24-v2`, covers Phase E governance
layer (`core/research/`) + X-1 path migration (`dev/scripts/**/*.py`).

- R1: found/fixed 19 unused imports in core (no functional bugs)
- R2: found/fixed 3 real `--help` bugs in scripts
  (`feat_v1_topk_analysis.py` missing sys.path;
  `build_splits_parquet.py` / `run_multi_tf_backtest.py` missing
  argparse) and cleaned 44 unused imports
- R3: refreshed baseline 1386→1536 tests and synced README

See `docs/20260420-ralph_loop_log.md` §R-audit-v2-round-01/02/03.
Launch: `bash dev/scripts/loop/start_codebase_audit_loop.sh`.

---

## Phase E Research Governance + Paper Layer (2026-04-24 COMPLETE)

14-round ralph-loop ship. Execution PRD
`docs/20260424-prd_phase_e_execution.md` + charter
`docs/20260424-prd_phase_e_governance_and_paper.md` + final synthesis
`docs/20260424-phase_e_final_synthesis.md`. Deliverables:

- **E-0 foundation**: `core/research/candidate_registry.py` (S0/S1/S2/S5
  state machine in `data/research_candidates/registry.db`) +
  pyarrow.parquet decouple from paper layer +
  `scripts/revoke_candidate.py`
- **E-1 promote**: `core/research/frozen_spec.py` (8 mandatory fields) +
  `scripts/freeze_research_candidate.py` + `scripts/research_promote.py`
  (S0→S1 gate; hard invariant: never writes
  `config/production_strategy.yaml`) +
  `core/research/acceptance_helpers.py`
- **E-2 paper**: `scripts/run_paper_candidate.py` (reads frozen spec,
  not production config) + `core/research/paper_artifacts.py` +
  `scripts/paper_drift_report.py` (50 bps informational threshold) +
  `scripts/paper_enter.py` (S1→S2; S3 → NotImplementedError)
- RCMv1 `rcm_v1_defensive_composite_01` traversed S0→S1→S2 via new
  tooling. Registry holds at S2_paper_candidate.

Launch: `bash dev/scripts/loop/start_phase_e_loop.sh`.

---

## Phase E-post + Candidate-2 8-round (2026-04-24 COMPLETE)

PRD `docs/20260424-prd_phase_e_post_cand2.md`, lineage
`phase-e-post-2026-04-24`, completion promise `EPOST_CAND2_DONE`.

Deliverables per round:

| Round | Scope | Commit | Artifact |
|-------|-------|--------|----------|
| R1 | E-post-3 deps | `f395a24` | +scipy/requests/tqdm/pyzipper; README 5.1 canonical |
| R2 | E-post-5A migration hermetic | `9a59631` | `--archive-db` CLI + 4 hermetic tests |
| R3 | E-post-4 revoke drill (clone) | `2efddf2` | 3 revoke paths drilled on rcm_v1 clones; real rcm_v1 bit-stable |
| R4 | E-post-1 paper decouple | `50a48b9` | `core/data/factory.py` PriceStore Protocol + factory; 6 tests |
| R5 | E-post-2 research mask unify | `d40e1e7` | `config/research_mask.yaml` + 9 script migrations; 10 tests incl. real-universe bit-identical |
| R6 | Candidate-2 S0→S1→S2 | `cbd5f50` | `candidate_2_orthogonal_01` {ret_5d, rs_vs_spy_126d, hl_range}, equal weight, registry @ S2_paper_candidate |
| R7 | Exhaustive audit | `29127c6` | 0 real bugs; 3 unused imports cleaned |
| R8 | Docs sync + final synthesis | (this round) | README v1.4 + CLAUDE.md slim + final_synthesis doc + EPOST_CAND2_DONE |

Final synthesis doc: `docs/20260424-phase_e_post_cand2_final_synthesis.md`.

Test baseline progression: audit-v2 R3 (1536) → R1 (1536) → R2 (1540)
→ R3 (1540) → R4 (1546) → R5 (1556) → R6 (1556) → R7 (1556) → R8 (1556).

Registry state after R8: 2 S2_paper_candidate rows
(`rcm_v1_defensive_composite_01` unchanged since Phase E R11;
`candidate_2_orthogonal_01` new @ R6).

---

## Framework Completion PRD — full milestone table (archived 2026-04-24)

PRD `docs/20260421-prd_framework_completion.md` v1.2.
Only **open** milestones (M11, M12, M14, M17, M18) remain in CLAUDE.md.
Full table (shipped + open) reprinted below for audit.

### Shipped (M0-M8, M10, M13, M15, M16)

- [x] **M0** research baseline snapshot
  (`dev/scripts/baseline/build_research_baseline_snapshot.py`)
- [x] **M1** `config/production_strategy.yaml` single source of truth
  (21 unit + 7 integration tests)
- [x] **M2** promote CLI + acceptance pack v2 (18 unit tests;
  `scripts/acceptance_pack.py` + `scripts/promote_strategy.py` +
  `docs/20260421-promotion_flow.md`). v2 added
  `full_period_fresh_backtest` gate after first promote attempt
  caught quick-eval-vs-full-period CAGR gap (`6d15b735a64c` was
  rolled back; pack now re-runs fresh backtest by default)
- [x] **M3** runtime alignment check WARN mode (12 unit tests;
  `core/alignment/alignment_check.py`; integrated in `run_backtest.py`
  + `run_paper.py`)
- [x] **M4** cross-ticker YAML DSL (24 unit tests;
  `core/signals/cross_ticker_rules.py` + `config/cross_ticker_rules.yaml`;
  3 rule types; safe expression eval, no Python `eval`)
- [x] **M5** multi-TF execution contract runtime assert (4 integration
  tests; `IntradayBacktestEngine.run_multi_day` clips + WARN on negative
  timing_provider weights)
- [x] **M6** LLM proposal Phase 1 (3 markdown docs:
  `docs/20260421-llm_proposal_prompt_template.md`,
  `docs/20260421-llm_proposal_seed_context.md`,
  `docs/20260421-llm_funnel_checklist.md`; process formalization, no
  code change)
- [x] **M7** XGBoost weight research model
  (`scripts/run_xgb_weight_model.py`; research-only; not wired to
  production)
- [x] **M8** Transformer research Phase 1 **findings shipped** —
  `docs/20260421-transformer_research_phase1_findings.md`. OOS R²:
  Ridge +0.012 / XGBoost -0.110 / **Transformer -0.207** (most
  overfit). Honest negative finding: daily 21d forecasting scope
  unsuitable for transformer; recommend parking or pivot to intraday /
  cross-sectional / longer-horizon setup.
- [x] **M10** cross-ticker DSL production wiring
  (`core/signals/cross_ticker_wrapper.py` + `run_backtest.py` /
  `run_paper.py` integration; 9 unit tests; `--no-cross-ticker-rules`
  CLI flag to disable per-run)
- [x] **M13** alignment FAIL mode config-driven rollout
  (`config/system.yaml::alignment::{mode, live_only_fail}`; defaults
  WARN + live_only_fail=true; operator flip without code change)
- [x] **M15** LLM Proposal multi-LLM context pack (see
  `docs/20260421-llm_external_llm_handoff.md`). Reframed from
  "Anthropic API call" to "provide context doc that user feeds to
  Gemini/Codex; those LLMs produce YAML candidates; user manually
  places in `research/llm_candidates/round_NN/`; Claude funnel picks
  up." Fully automated Phase 2 (API) is NOT planned.
- [x] **M16** Transformer Phase 1 findings (done, see M8 above)

### Open (M11, M12, M14, M17, M18) — reprinted for reference

- [ ] **M11** paper-BT consistency gate in pack v3 (P1.5, 1-2d). New
  gate: replay spec over recent 126d window, diff equity vs fresh
  backtest, fail if > 10 bps drift. Currently skip-PASS; M1
  single-source already covers constructor layer but engine-level
  drift not verified.
- [ ] **M12** concentration gate real enforcement (P2, 0.5d). Currently
  skip-PASS; runtime `soft_cap_max_single` + `PortfolioConstructor`
  hard cap cover production. M12 would inspect fresh-backtest weight
  matrix for per-date top-1/top-3 concentration and reject if >
  threshold (e.g. top-1 > 0.40 or top-3 > 0.70).
- [ ] **M14** BacktestEngine NaN root-cause fix (P2, 1d; conditional).
  Ghost-cleanup + NaN last-price can produce NaN as equity last bar.
  Pack v2 workaround uses `.dropna()` before CAGR. Fix: skip
  ghost-liquidation when last_close is NaN, or fillna last-valid in
  equity aggregation. Promote to blocker if user complains about NaN
  in `reports/backtests/.../equity_curve.csv`.
- [ ] **M17** Realtime intraday live-feed infra. Out of framework PRD
  scope; independent PRD `prd_live_feed.md` when needed. Gate: do not
  start until validated best strategy exists and is stable (no point
  live-tracking a provisional strategy).
- [ ] **M18** Cross-ticker DSL function expansion (P3, 0.3d per
  function). Candidate new funcs: `ratio(sym_a, sym_b)`,
  `zscore(col, N)`, `rank_cs(col)`, `breakout(N)`. Add ONLY when a
  specific rule yaml demands them; don't pre-add.

---

## Reference sections archived from CLAUDE.md (2026-04-24 R3)

The following reference sections were compressed to short summaries
in CLAUDE.md on 2026-04-24 during the docs-audit R3 round; their full
original content is preserved below as-is.


---

### 1m Bar Pipeline [NEW 2026-04-18]

**Source locations (heterogeneous):**
- 2015-2023: `~/Documents/projects/Data/1m/YYYY/YYYYMM/YYYYMMDD.gz`
  Polygon flat: `ticker,volume,open,close,high,low,window_start(ns UTC),transactions`
  Full market including ETFs (~10,679 tickers/day)
- 2024-01 to 2025-11: `~/Documents/projects/Data/1m/YYYY/YYYYMM/YYYYMMDD/<SYMBOL>.csv`
  Schema: `exchange,symbol,open,high,low,close,amount,volume,bob,eob,type`
  **⚠ Stocks only, NO ETFs** (~4,598 tickers/day; only 7/32 universe present:
  AAPL/MSFT/GOOGL/AMZN/META/NVDA/TSLA)
- 2025-12 + 2026: `/mnt/c/Users/Admin/Documents/projects/output/{2025,20260M}/...`
  Same schema as 2024-01 (stocks only)

**Output layout:**
```
pqs/data/
  intraday/1m/<SYMBOL>.parquet     # RAW (unadjusted) DatetimeIndex tz-naive ET
  intraday/5m/<SYMBOL>.parquet
  intraday/15m/<SYMBOL>.parquet
  intraday/30m/<SYMBOL>.parquet
  intraday/60m/<SYMBOL>.parquet
  daily/<SYMBOL>.parquet           # RTH-only aggregate, date index
  ref/splits.parquet               # canonical splits (symbol, date, from, to)
  .yf_cache/                       # BarStore yfinance fallback cache (1d TTL)
  _catalog.parquet                 # coverage per (symbol, freq)
```

**Schema (unified across sources):** `open/high/low/close` float32, `volume` int64,
`amount` float64 (dollar volume; NaN for 2015-2023). Index = `timestamp`/`date`.

**Splits:** table at `ref/splits.parquet` (4959 rows, 2821 tickers, 1978-2026).
Applied forward at READ TIME by `BarStore`:
```
adj_factor(t) = Π (from_i / to_i) over splits i where date_i > t
adj_price = raw_price * factor; adj_volume = raw_volume / factor
```
(Note: `美股复权计算方法.md` in source describes backward-adjust despite calling
it 前复权; we use standard forward adjust to match quant convention / yfinance.)

**BarStore API (`core/data/bar_store.py`):**
```python
store = BarStore()
df = store.load("SPY", freq="1m", adjusted=True)              # local + yfinance tail-fill
df = store.load("SPY", freq="60m", fallback="local")          # local only
df = store.load("SPY", freq="daily", fallback="yfinance")     # yfinance only (cached)
raw = store.load("AAPL", freq="1m", adjusted=False)           # pre-split RAW
```

**ETF gap & yfinance fallback:** Because 2024+ source has stocks only, ETF 1m
bars stop at 2023-12-31 locally. `BarStore.load(..., fallback="auto")` (default)
auto-fills the tail from yfinance. yfinance coverage:
- 1m: last 59 days only
- 5m/15m/30m/60m: last 720 days
- daily: full history

**Validated reliability (2015-01 window, apples-to-apples split-only):**
- Open/High/Low median error: **0.000%** across all 8 test symbols
- Close median error: 0.000–0.067% (max 0.134%)
- Tiny close diffs = closing auction (16:00) vs last 15:59 1m bar; not a data bug

**Scripts:**
```bash
python scripts/build_splits_parquet.py            # refresh splits.parquet
python scripts/build_bars_parquet.py --phase all --workers 6   # full ingest + consolidate
python scripts/build_bars_parquet.py --month-only 202401 --workers 6  # single month
python scripts/aggregate_bars.py                  # 1m → 5m/15m/30m/60m/daily
python scripts/aggregate_bars.py --symbols SPY AAPL   # filter to symbols
python scripts/build_catalog.py                   # build _catalog.parquet
python scripts/validate_vs_yfinance.py --freq daily --mode split --symbols SPY AAPL
python scripts/validate_vs_yfinance.py --freq 1m --symbols AAPL  # needs 2026-02+ ingested
```

**Invariant:** Bars stored RAW (unadjusted). Adjustment is applied only at read
time by `BarStore.load(adjusted=True)` using splits.parquet. This keeps the
storage vendor-agnostic — swapping 2024+ source (adding ETFs) requires only
re-running `build_bars_parquet.py`, not reprocessing splits or downstream code.


---

### Trades Backfill Pipeline [NEW 2026-04-20]

**Problem:** Upstream 2024-2025/11 source (per-ticker CSV in
`~/Documents/projects/Data/1m/`) is stocks-only — no ETFs. This created a
major data gap for SPY/QQQ/XL*/GLD/TLT/etc. 2024+ bars.

**Solution:** separate ingestion pipeline consuming tick-level trade data
from encrypted zips (`trades_v1_YYYY-MM-DD.csv.gz` / `.csv`):

- Source: `/mnt/c/Users/Admin/Documents/projects/trades/**/YYYYMMDD.zip`
  (one zip per trading day, ~1.7-4GB, AES-encrypted)
- Password: `sha256(basename + "vvtr123!@#qwe")` — per-zip dynamic
- Schema: `ticker,conditions,correction,exchange,id,participant_timestamp,`
  `price,sequence_number,sip_timestamp,size,tape,trf_id,trf_timestamp`
- Aggregation: tick-level → 1m bars with extras (n_trades, vwap,
  buy/sell_volume_proxy, large_trade_volume, block_n, exch_top1_share)

**Strategy B (chosen merge policy):**
  Trades scanner only writes tickers NOT already present in
  `.staging/<month>/`. This preserves existing stocks_csv bars unchanged
  while filling ETF gaps. Avoids volume semantics conflicts between
  sources.

**Filter rules (`trades_v2_late_report_dedup_2026-04-19`):**
  - `correction < 1` (drop corrected/cancelled)
  - Drop trades in `DROP_EXCHANGES = {4}` (FINRA ADF OTC duplicate prints)
  - Drop trades whose `conditions` include any `LATE_REPORT_CONDS = {14,
    16, 18, 19, 20, 22, 29, 31, 32, 33, 34, 38, 39, 42, 43, 45, 47-51,
    54-58}` (late/delayed duplicate reports per vendor's condition table)

**Resilience:**
  - Atomic parquet writes via tmp + rename (interrupted process leaves
    clean main file)
  - Peak memory lock (`/tmp/trades_scanner_peak.lock`, `fcntl.LOCK_EX`)
    serializes parse+filter+aggregate across parallel scanner instances
    to prevent OOM on 15GB system
  - Per-instance state file (`data/trades_scanner_state_<year>.json`) and
    per-instance `/tmp/scanner_<label>_decrypt.csv` support multi-scanner
    orchestration
  - `disk_guard.py` watches `/mnt/c` free space; kills Baidu Netdisk
    processes if < 30GB to prevent disk fill

**Scripts:**
```bash
python scripts/trades_scanner.py --watch [--year-include 2024] \
    [--state-file ...] [--decrypt-tmp /tmp/...]           # main ingester
python scripts/scanner_sequential_2026_2025.py --a-pid ... # 2026→2025 chain
python scripts/scanner_terminator.py --pid ... --year 2025 \
    --completion-date 20251231                             # year-end gate
python dev/scripts/ops/disk_guard.py                              # C: drive guard
python scripts/consolidate_trades.py                      # .staging_trades → root
python scripts/consolidate_sanity_check.py                # cross-source price sanity
python scripts/post_processing_pipeline.py [--skip-wait]  # end-to-end orch
```

**Final state after 2024+2025+2026 ingest (2026-04-20):**
  - 25,355 symbols across 1m/5m/15m/30m/60m; 25,329 daily
  - 1m: 4.03B rows, 84.6GB on disk
  - 0 failed zips after retries
  - Universe tickers (37) refreshed from yfinance canonical daily (covers
    2015 polygon_gz gaps on low-volume ETFs like VLUE)
  - Macro reference (^VIX, ^TNX, DX-Y.NYB) fetched from yfinance
  - Known issues: ZTST has 2 sentinel bars at $12345 on 2025-11-28 and
    2025-12-24 (vendor source bug; not systemic — see
    `reports/known_data_issues/ztst_sentinel.md`)

**Hard rule for future data ingestion:** any new ingestion script MUST
synchronously write `data/ref/bar_provenance.parquet` rows using the same
schema as `trades_scanner.update_provenance()` (symbol, freq, source_type,
rule_version, first_bar_ts, last_bar_ts, n_bars_added, updated_at). This
keeps the provenance sidecar in sync without migration scripts.

---


---

### Data Provenance Sidecar [NEW 2026-04-20]

Every (symbol, freq) has explicit source metadata in
`data/ref/bar_provenance.parquet`. Consumers use this to:
  - detect cross-source merge artifacts (sanity check)
  - mask volume-sensitive factors for `trades_backfill` tickers (factor
    guard — see `DataSensitivityConfig`)
  - attribute strategy performance by data epoch in reports

**Source types:**
  - `polygon_gz` — 2015-2023 Polygon flat files (full market)
  - `stocks_csv` — 2024-01 to 2025-11 per-ticker CSV (stocks only)
  - `stocks_csv_c_drive` — 2025-12+ per-ticker CSV (stocks only, C: drive)
  - `trades_backfill` — 2024+ tick-level trades (ETF + stocks not in csv)
  - `yfinance_daily` — universe ETFs + macro refs (canonical adjusted daily)
  - `yfinance_fallback` — on-the-fly yfinance fill when BarStore detects
    a tail gap (fallback='auto')

**API:**
```python
from core.data.bar_store import BarStore
store = BarStore()
df = store.load("SPY", freq="1m", fallback="auto")
print(df.attrs["provenance"])  # list of rows
print(store.get_provenance("SPY", "1m"))
```

**Factor guard:**
```yaml
# config/universe.yaml
data_sensitivity:
  volume_sensitive_factors: [volume_surge_20d, price_volume_div, ...]
```
```python
from core.factors.factor_generator import generate_all_factors
factors = generate_all_factors(price_df, volume_df,
                               backfill_tickers=backfill_set)
# volume-sensitive factors get NaN for backfill tickers
```

---


---

### Factor Pipeline Contract [NEW 2026-04-20, 约束 2]

Single source of truth: `core/factors/factor_registry.py`

| Registry | Contents | Role |
|----------|----------|------|
| `PRODUCTION_FACTORS` | 6 names (low_vol, momentum, quality, pv_div, rel_strength, market_trend) | Accepted by `MultiFactorStrategy.factor_weights`; tuned by `MultiFactorSpace.suggest()` |
| `RESEARCH_FACTORS` | 35 names from `factor_generator.generate_all_factors` | Available for IC / OOS / regime research only |
| `RESEARCH_TO_PRODUCTION_MAP` | dict: research name → production name | Documents which research factor is already represented by which production factor |

**Gate behavior:**
- `MultiFactorStrategy.__init__` calls `check_execution_factor_names(weights)`; unknown names logged at WARNING and **dropped** from composite computation — prevents research names (e.g. `price_volume_div`) silently appearing in execution
- `MultiFactorSpace.__init__` asserts `_TUNED_FACTORS == PRODUCTION_FACTORS` — if registry changes without updating the space, mining fails fast

**Promotion flow (manual, one-way: research → production):**
```
1. Add candidate to factor_generator.generate_all_factors + RESEARCH_FACTORS
2. Run scripts/run_factor_screen.py  → IC + significance
3. Run scripts/run_xgb_importance.py → OOS attribution
4. If funnel passes:
   a. Add inline computation block to MultiFactorStrategy.generate()
   b. Add name to PRODUCTION_FACTORS + production_factor_names()
   c. Add weight slot + range to MultiFactorSpace.suggest() and
      MultiFactorSpace._TUNED_FACTORS
   d. Add entry to RESEARCH_TO_PRODUCTION_MAP if it shadows a research name
   e. Re-run full suite (test_factor_registry enforces consistency)
```

**Research-only vs shadowed-research** (at current registry state):
- Shadowed (10 factors): e.g. `vol_63d` ↔ `low_vol`; research form kept for granular analysis, production form kept for execution stability
- Research-only (25 factors): e.g. `reversal_5d`, `overnight_gap_21d`, `advance_ratio_10d`, `rs_acceleration` etc. — available in research but cannot drive execution until promoted

This ends the previous "dual-track, unclear relationship" state. Tests:
`tests/unit/factors/test_factor_registry.py` (10 tests).

---


---

### Multi-TF Timing Contract [NEW 2026-04-20, 约束 3]

The multi-timescale framework is **NOT** a standalone alpha system. The
iter #9/#10/#11 validation sprint proved the naive bar-direction voting
approach produces strictly lower Sharpe than a 60m-only baseline and
fails cost-stress at even 0.1× base cost. Multi-TF is repositioned as a
TIMING / EXECUTION / RISK layer on top of daily MFS.

**Role by TF:**

| TF | Role | Authority |
|----|------|-----------|
| 60m | Primary context / regime / direction check | Can VETO a daily target (scale → 0 if contradicts strongly) |
| 30m | Secondary confirmation / risk state | Confidence penalty on timing_scale |
| 15m | Execution trigger / timing | DEFER only — cannot flip direction |
| 5m | Fine execution trigger | DEFER only — cannot flip direction |

**Canonical API:**
```python
from core.intraday.multi_timescale import build_context, decide_timing

ctx = build_context(multi_bars, symbol, bar_ts)
decision = decide_timing(ctx, symbol, base_weight=0.3, daily_side=1)
# decision.execute         : bool — route orders this bar?
# decision.timing_scale    : float [0,1] — scale of base_weight
# decision.effective_weight: base_weight × timing_scale if execute else 0
# decision.higher_tf_vote  : per-TF {confirm / contradict / neutral / absent}
# decision.reason          : confirmed / soft_contradict / deferred / ...
```

**Contract invariants (enforced by `tests/unit/intraday/test_timing_decision.py`):**
- Lower TF (15m/5m) adverse → `execute=False` (defer), **never** flip
- `effective_weight ≥ 0` for any TF combo (long-only)
- No higher context → pass-through (`execute=True, timing_scale=1.0`)
- Short side (`daily_side=-1`) → `execute=False` (system is long-only)
- `base_weight=0` → `execute=False` (nothing to time)

**Validation approach (replaces "does multi-TF beat 60m on CAGR?"):**
`scripts/validate_timing_value.py` measures timing-relevant metrics:
  - Entry bps vs day mean (timed vs naive first-bar-open execution)
  - Defer rate (what % of days timing deferred past first bar, to EOD)
  - Average applied timing_scale

Initial run (5 symbols × 2871 daily events, 2024-01 to current):
  - naive  entry: mean +0.25 bps vs day mean (median -4.22 bps)
  - timed  entry: mean -0.33 bps vs day mean (median -3.12 bps)
  - deferred ≥1 bar: 34.3% of days
  - deferred to EOD: 0.0% (1/2871)
  - avg timing_scale: 0.717

Interpretation: timing is approximately a wash on entry bps. Real value
(if any) must come from compounding over full position path + downstream
slippage — the current simple "mean vs day close" proxy is too coarse.
The script is a placeholder that keeps the right questions in view; a
more sophisticated validation (holding-period tracking, turnover delta)
is future work.

**Legacy `evaluate_cross_tf_signal` / `CrossTFSignal`:** kept as a back-
compat shim — do not remove; existing scripts (run_multi_tf_backtest,
validate_combo_tfs, etc.) still consume it. New code should use
`decide_timing` / `TimingDecision`.

---


---

### Notify Module [NEW 2026-04-20]

Channel-agnostic notifier for paper trading alerts, kill-switch events,
daily PnL summaries.

Backends:
  - `wecom_bot` — WeChat Work group-bot webhook (recommended, no rate limit)
  - `server_chan` — Server 酱 Turbo (5/day free; keep for criticals)
  - `stdout` — dev / testing
  - `null` — disabled (default)

API:
```python
from core.notify import get_notifier
n = get_notifier()  # reads config/notify.yaml
n.info("Daily summary", f"NAV={nav:,.0f}, PnL={pnl:+.0f}")
n.error("Kill switch stage 2", f"drawdown={dd:.2%}")
```

All sends return `SendResult` (never raises on transport failure). Rate
limit + min_level gating built-in. Credentials via env var expansion
(`${PQS_WECOM_WEBHOOK_URL}`) — never commit secrets.

---

