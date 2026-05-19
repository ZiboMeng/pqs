<!-- PQS module CONTEXT.md — 由 CLAUDE.md 2026-05-19 reorg 拆出。
CLAUDE.md = context 入口,仅留项目级(不变量/纪律/架构/概括)。
本文件 = 本模块的历史/契约细节(content-preserving 搬迁,无删改)。
回指: ../../CLAUDE.md ; 索引见 CLAUDE.md 末「Module CONTEXT.md 索引」。 -->

# core/options/CONTEXT.md — module history / contract detail


## [Options Research Track 全细节+史]

## Options Research Track

**Status (2026-05-04)**: Phase 1 free-path research COMPLETE (D→A→C→B→E
sweep on `pqs-options-v1-2026-05-02` branch, merged to main 2026-05-03
commit `b32fad6`); Path 2 paper-trading layer SHIPPED (commit `25e7613`);
first paper candidate `spy_8otm_bull_put_v1` initialized 2026-05-04
(`n_observe_days=0` at init; first observe = 2026-05-04 EOD); cumulative
single-name VRP scanner SHIPPED (commit `2645bb9`, N=3 snapshots so far,
COIN +11.7 ± 2.7 / NVDA +9.4 ± 1.3 / AMD +3.1 ± 5.9 ranks unchanged).

**Phase 1 verified numbers** (Sharpe / MaxDD grep'd from
`spread_backtest_summary_otm8_realistic.json` + `wheel_backtest_summary.json`):
- SPY 8% OTM bull put under realistic asymmetric skew (put 1.30 / call
  0.75 × VIX): Sharpe **0.62** (clears PRD §6 acceptance >0.60), CAGR
  **+0.99%/yr**, MaxDD -2.96%, 92% win rate, 388 trades. **Honest
  winner BUT synthetic** — 33-yr backtest uses VIX as IV proxy + skew
  factors calibrated to one yfinance live chain; paper-observe required
  to validate Sharpe estimate is not optimistic.
- Wheel (CSP→CC) **REJECTED**: MaxDD **-32.72%** > 25% PRD §1.4 ceiling.
  Long-only no-margin invariant amplifies loss when CC assigns at
  lower spot. Don't revisit.
- Single-name VRP 2-3× SPY VRP confirmed by snapshot
  (NVDA 2.0× / AMD 1.8× / COIN 2.7×) — magnitude exists but
  snapshot-only without paid historical chain data.
- Path D fleet correlation: options sleeve cuts 2022 H2 bear DD from
  -14.5% → -7.1% (alpha angle is correlation, not standalone CAGR).

**Key file locations**:
- Scripts: `dev/scripts/options/` (10 files: VRP scan + 4 backtests +
  paper init/observe + skew validation + fleet correlation)
- Core: `core/options/{paper,pricing,strategies}/` — `paper/runner.py`
  + `paper/spec.py` are load-bearing; `risk/`/`data/`/`execution/` are
  Phase 3+ placeholders (intentional, not orphan).
- Tests: `tests/unit/options/` (51 tests; isolation contract test is
  HARD merge gate).
- Data: `data/options/{analysis,backtest,snapshots,paper_runs}/`.
  Paper run state at `data/options/paper_runs/spy_8otm_bull_put_v1/`
  (spec.yaml + manifest.json).
- PRD: `docs/prd/20260502-pqs_options_v1_free_path_prd.md`
- Synthesis: `docs/memos/20260502-options_v1_phase_1_final_synthesis.md`
- Viability / paid-data deferral: `docs/memos/20260502-options_v1_phase_1_viability_memo.md`

**Daily ritual** (post-NYSE 16:30 ET):
```
python dev/scripts/options/observe_options_forward.py --candidate-id spy_8otm_bull_put_v1
python dev/scripts/options/cumulative_vrp_scan.py
```
SessionStart hook (commit `44916b1`) flags staleness on next-session
open via `dev/scripts/daily_freshness_check.py`.

**Decision point ~2026-07-30** (Trial 9 TD60 + options paper TD60
align in same window):
- Both GREEN → authorize paid options chain data spend (ORATS or
  Polygon options tier ~$50-200/mo) + single-name expansion
  (NVDA/AMD priority per Path B Tier 1) + capital scale-up.
- Options paper RED (Sharpe < 0.4 OR capital-sized DD > 15%) → halt
  options workstream, redirect to stock fleet.
- Both RED → strategic reassessment per PRD F5 (objective / data /
  frequency / tools / strategy-type changes).

**Anti-patterns** (do NOT without explicit user-go):
- Do NOT add capital to active paper run mid-cycle (changes
  `spec_hash`, breaks observation continuity).
- Do NOT validate wheel further (rejected for structural long-only
  reasons; more data won't move verdict).
- Do NOT add new Path A-Z sweep (Phase 1 saturated; new free-path
  Path = zero increment without paid data).
- Do NOT pay for chain data before Trial 9 TD60 + paper TD60 verdicts.
- Do NOT integrate options into MultiFactorStrategy or production
  candidate registry (options is a SEPARATE sleeve, not a factor).

**Capital sizing reality check**: $10K paper NAV uses 12% risk/trade
vs PRD §2 default 2% — oversized workaround for min-capital
constraint (one SPY 8% OTM bull put = $1000 max loss = 10% of $10K).
Production deployment requires $50-100K+ for proper sizing. Current
paper data validates **mechanism** (state machine, idempotency,
overlay closes), NOT real-Sharpe estimate.

**Free-path retests on deferred queue** (per Phase 1.4 viability memo
§R1-R3, gated on user explicit-go):
- R1 skew sensitivity sweep — re-run spreads with `skew_factor`
  ∈ [0.20, 0.50] (free, ~1 day eng)
- R2 single-name historical chain — requires paid data, gated on
  Trial 9 TD60 GREEN
- R3 wheel revisit with relaxed CC arm — optional, low expected
  value (rejection is structural)
