# PQS Comprehensive Project Audit — 2026-07-08

**Method**: 4 parallel code-verified sub-audits (data/backtest-leakage · validation-rigor/alpha · risk/drawdown · docs-consistency) + operator online architecture research + operator R3 re-verification of every P0/top-P1 by direct grep/exec. Goal lens throughout = **reliable profitability** (beat SPY long-term + MaxDD 15-20% / 2008-style ≤25% + long-only/no-margin/no-short invariants). Sealed 2026 not read; only existing unit tests run.

**Head SHA**: 219952f… (pre-audit). **Scale**: 25 core modules / 61K LOC / 276 docs / 28 configs / 3167 tests (3165 pass).

---

## 0. Executive verdict (operator judgment)

The project is **infrastructure-rich and discipline-strong**, with **two gaps that jointly threaten "reliable profitability":**

- **(A) ENFORCEMENT GAP — capital preservation is documented, not enforced.** The invariants that protect the *low-drawdown* half of the goal (SQQQ blacklist, TQQQ/SOXL stricter caps, per-symbol position caps, 2008-style MaxDD≤25%) exist in `config/*.yaml` and CLAUDE.md but have **no runtime consumer** on the main paths — many keys are dead, `PortfolioConstructor` uses hardcoded defaults, `StressTester` is orphaned, and SQQQ is reachable via `--universe expanded_v1/v2`. **This is the #1 risk to "reliable."** A wrong universe flag or a leveraged ETF sized at the default 35% cap could blow the drawdown budget with nothing stopping it.

- **(B) EDGE GAP — no demonstrated surviving OOS alpha yet.** The only two active `core_alpha` candidates (cycle06/08) are giving back all excess and now underperform SPY in genuine forward OOS (2026-07-08). This is consistent with the recurring "construction-bound / high-beta reversion / sibling convergence" finding and is logged honestly. The *beat-SPY* half of the goal is **unproven**.

**What is genuinely SOLID** (verified, not assumed): the core backtest path is **leakage-clean** (AST-verified 0 forward-shift in the composite; correct T-close→T+1-open fill; backtest↔paper share fill code; split-cascade math correct; halted/stale marking correct). Temporal-split + sealed-ledger enforcement is genuinely fail-closed (240 tests). López de Prado label-overlap weighting is real and wired. Honest self-correction culture (chart_native leakage caveat, settle-window market result). **The machine is well-built and honest; it just isn't yet (a) guaranteed safe under all config paths, nor (b) proven to have edge.**

Online research corroborates the *frame*: at $10k–$100k, long-only factor harvesting is viable (capacity is an advantage mega-funds lack); naive top-N/equal-weight is OOS-robust (do NOT add mean-variance optimization); factor/regime TIMING for return is "deceptively difficult" (Asness 2017) — regime should be defensive-only; CONDITIONAL (not continuous) vol-targeting is what actually cuts drawdown; CPCV/DSR/PBO is the right overfitting stack (the project has it — but see P1-A on wiring).

---

## 1. Findings — prioritized by impact on RELIABLE PROFITABILITY

Severity: **P0** = threatens a hard invariant / capital preservation / integrity of a go-no-go decision. **P1** = undermines confidence in edge, consistency, or rigor claims. **P2** = minor/diagnostic. Every finding below was re-verified by the operator (file:line + grep/exec), not taken on sub-agent trust; two sub-agent claims were CORRECTED in verification (noted).

### P0-1 · Capital-preservation invariants are declarative, not enforced (cluster)
Root cause (cross-cutting): `config/risk.yaml` + invariant-quant configs are largely **dead keys**; the two real enforcement points read hardcoded defaults or aren't wired.
- **SQQQ blacklist BYPASSABLE** — `core/universe/universe_resolver.py:85-100` appends `expanded_symbols` without the blacklist filter; `resolve_universe("expanded_v1")` → **contains SQQQ, SOXL, SOXS, TQQQ** (operator-verified: n=328); `expanded_v2` → **SQQQ, SPXL, SPXU, TZA, UPRO…** (n=1006). `scripts/run_backtest.py:574` only excludes `["TQQQ","SOXL"]` by name → SQQQ + other 3× inverse/leveraged flow into `risk_syms` and become allocatable. **Violates a hard invariant** ("SQQQ blacklisted").
- **Per-symbol / leverage-ETF caps unenforced** — `PortfolioConstructor` never reads `config/risk.yaml`; `core/config/schemas/risk.py:51 cap_for()` has **zero runtime callers** (operator-verified grep empty). Every `PortfolioConstructor(...)` uses hardcoded `max_single_pos=0.35, target_vol=0.25`. TQQQ/SOXL get the same 0.35 cap as SPY. Violates "TQQQ/SOXL stricter thresholds" + "all thresholds configurable, never hardcoded".
- **2008-style MaxDD≤25% NOT enforced** — `max_crisis_drawdown_abs:0.25` / `single_crisis_drawdown_cap:0.25` have no gate reading them (grep empty); `StressTester` has no runtime consumer AND computes a terminal return, not a drawdown path (couldn't produce a MaxDD even if called). The Black Swan Quantification invariant is unbacked at runtime.
- **Fix**: (a) apply `uni.blacklist` filter inside `resolve_universe` (single choke point) + derive leveraged-ETF exclusion from config not hardcoded names; (b) thread `cfg.risk.position_limits.symbol_caps` into `PortfolioConstructor.build()` per-symbol cap; (c) add an acceptance/robustness gate that runs stress slices and asserts per-slice MaxDD ≤ `max_crisis_drawdown_abs`, and make StressTester emit a DD path (or reuse robustness runner per-slice `max_dd`).

### P0-2 · QQQ deprecation is half-implemented — still a HARD gate on 3 code paths
CLAUDE.md invariant (2026-05-02): QQQ = diagnostic, NOT a hard gate. But QQQ still hard-blocks promotion on:
- `core/config/production_strategy.py:54-59` — `all_passed` ANDs `passed_qqq_gate` (consumed at :169 `if not all_passed: raise`). Operator-verified.
- `core/reporting/master_report.py:212` — QQQ excess row labeled `"≥ 0% (hard gate)"`. Operator-verified; definitely live (reports generated).
- `core/mining/evaluator.py:971` — `if not r.passed_qqq_gate: return "D"` (legacy miner tier-kill, comment still cites pre-deprecation "P0.4"). Operator-verified.
- The NEW Track-A/two-stage path (`temporal_split_acceptance.py` + `evaluation_policy.py:109 should_demote_qqq_gate`) DOES correctly demote QQQ — so the deprecation is done on the new path, un-done on legacy + reporting. Textbook 做出来≠做彻底.
- **Impact**: a strategy that beats SPY but not QQQ (the exact case the memo calls an *active bet, not a gate*) is blocked from promotion / mistiered D / mislabeled failed — a WRONG no-go. **Fix**: drop `passed_qqq_gate` from `all_passed`; relabel master-report row diagnostic; route `evaluator.py` QQQ through `should_demote_qqq_gate`.

### P0-3 · Robustness / pseudo-OOS selection evidence reads RAW unadjusted prices
- `core/research/robustness/runner.py:_load_panel` default `adjusted=False`; callers at `:505,:518` use the default → `store.read` (no split cascade). Operator-verified. 13 default-universe symbols split since 2024 (NVDA 10:1, AVGO, WMT, CMG, TQQQ, XLK/E/B/U/Y…); a window spanning a split date injects a fake −50~−90% return → corrupts cross-sectional z-scores + NAV in the evidence numbers consumers read to RANK/SELECT candidates.
- **Scope**: biases selection/ranking, NOT already-promoted candidates (Track-A re-validates on `BarStore adjusted=True` — backstop). Last un-migrated instance of the P0-A raw-price root cause (memory `project_grand_audit_2026_05_18_two_p0`).
- **Fix**: switch `:505,:518` to `adjusted=True, adjusted_total_return=True` (match forward); add a split-in-window smoke that flags raw-path windows containing a split.

### P1-A · SOTA overfit gates (DSR/PBO/CPCV/MinBTL) not applied to the active fleet
- Correctly implemented (`overfit_metrics.py`, `cpcv_acceptance.py`, `mining_pbo.py`) and **wired into the LATEST cycle harness** (`dev/scripts/cycle13b/cycle13b_track_a_eval.py:175,204` populate `overfit_inputs`/`cpcv_inputs` — operator-verified; CORRECTS the sub-agent's "only in tests" claim, which missed `dev/scripts/`). BUT the currently-active candidates (cycle06/08) were promoted via the older `cycle06_track_a_eval` per-year gates and **never went through DSR/PBO/CPCV**. So "SOTA anti-overfit protects the fleet" is true for *new* cycles, aspirational for the *live* fleet. **Fix**: re-run cycle06/08 (or their successors) through the cycle13b-style harness before any capital commitment; or document that the live fleet predates the SOTA panel.

### P1-B · No demonstrated surviving OOS alpha (honest strategic finding, not a bug)
- cycle06/08 (only active core_alpha): forward TD034 2026-07-08 cycle06 +0.06% (vs SPY **−1.54%**), cycle08 −0.18% (vs SPY **−1.77%**), after peaking +4.6/+6.2% vs SPY late June. In-sample Track-A edge not surviving forward. Consistent with construction-bound/high-beta-reversion. **No fix** — this is the honest data; **do not promote on peak readings, let TD60 stand.** Strategically the most important line in this audit: the *beat-SPY* goal has no proven vehicle yet.

### P1-C · Benchmark-basis inconsistency + nondeterminism in forward reports
- `core/research/forward/attention_report.py:458` loads benchmark with `fallback="auto"` (inherits `BarStore.load` default) → SPY/QQQ can be tail-filled from yfinance on a **different adjustment basis** than the strategy NAV (`_load_panel fallback="local"`), and silently hits the network during a forward observe (nondeterminism; adjacent to sealed-data hygiene). `bar_store.py:236` also concats local-cascade + yfinance-internal-adjusted at the seam (`_load_yfinance` bypasses `_apply_forward_splits/_distributions`). **Fix**: pass `fallback="local"` at attention_report:458; consider flipping `BarStore.load` default to `local` (audit callers first); fetch yfinance RAW and run it through the same cascade, + a seam-continuity regression test.

### P1-D · Documented risk ladders / fleet throttles are orphaned
- `config/risk.yaml:7-13` 4-tier DD ladder (reduce/defensive/warning) has **no consumers**; runtime uses a different KillSwitch 3-tier (DEGRADE −17.5%, SUSPEND −25%) driven only by `halt_pct`. Fleet `apply_dd_throttle`/`apply_role_caps`/`apply_removal_rules` are `NotImplementedError("frozen")` (acceptable while single-candidate; MUST ship before a live multi-candidate fleet — no fleet-level DD throttle or top3≤70% today, though mining acceptance_pack DOES enforce top1/top3 for candidates). **Fix**: reconcile the ladder into KillSwitch thresholds or delete the dead keys; ship fleet C5 DD-throttle before multi-candidate go-live.

### P1-E · DSR fed fold-IC array, not a returns series
- `core/research/cpcv_acceptance.py:82-85` computes "deflated_sharpe" on 15 fold-IC values (T=n_folds), not a per-period return series — a mislabeled information-ratio with meaningless skew/kurtosis. Not gated on (binding gate is `ic_sample_weighted`), so P1 (misleads humans reading the CPCV summary). **Fix**: pass per-period strategy returns (as `temporal_split_acceptance.py:732` does) or rename the field + drop DSR framing here.

### P1-F · Documentation staleness cluster (misleads operator state)
- Factor count: code **187 RESEARCH / 7 PRODUCTION, families A-T** (operator-verified import) vs CLAUDE.md "143 / A-P" vs README "175 / A-S". · CLAUDE.md Active State (2026-05-19) presents cycle06/08 as clean positives, omits 4 re-inits + settle-window + current SPY-underperformance. · docs/INDEX.md claims "~138 docs" (actual 276+), "PRDs 38" (48), links ~69 of 168 memos — ~99 unindexed incl. the sealed-window-leak postmortem + PRD-123 execution ledger. · CLAUDE.md pricing table says "dividends deferred" but the forward path now applies total-return (this session's 6a8448a). **Fix**: point counts at registry/baseline SoT; refresh Active State; regenerate INDEX; sync pricing table (3 coexisting bases: forward=split+div, robustness=raw, xgb=split-only).

### P2 (minor)
- `evaluator.py:313/966` — NaN `oos_is_sharpe_ratio` **skips** the overfit gate (fail-OPEN); should tier D. · Split configs `embargo_days:0` (purge-only; de Prado recommends small nonzero embargo for serial correlation). · `execution_simulator.py:194` `fill_date=signal_date+BDay(1)` is holiday-unaware → wrong fill_date LABEL on Good Friday/Jul-4 (price + NAV correct; only report attribution). · KillSwitch SUSPENDED→DEGRADED recovery blocked while DD sits mid-band (`kill_switch.py:198-225`). · 1-day cash-drag ramp-in makes vs-SPY slightly conservative (acceptable). · No explicit `tgt_w>=0` assert on order-gen (backtest clamps to flat anyway — safe).

---

## 2. Architecture soundness + gaps (online research, sealed-safe)

- **Frame is sound at individual scale.** Long-only factor harvesting nets positive alpha in ~half of anomalies (value/momentum/liquidity); capacity limits bind mega-funds (momentum ~$65B) but not a $10-100k account → concentration mega-funds can't hold is available here; realistic retail cost < academic 0.63% models. **Scale is an edge, not a handicap.**
- **Construction is right — do NOT add optimization.** DeMiguel et al: across 14 optimizers, none beat 1/N OOS (estimation error). PQS cap-aware top-N is OOS-robust; mean-variance would likely *hurt*. Validates current design.
- **Regime/factor TIMING for return is weak (Asness 2017 "deceptively difficult").** Recommendation: keep the regime module strictly **defensive/de-risk**, never alpha-timing.
- **Vol-targeting: use CONDITIONAL, not continuous.** Continuous vol-targeting can worsen equity drawdowns + adds turnover; conditional (extreme-state-only) cuts DD with low turnover (Financial Analysts Journal). PQS `target_vol=0.25` should be regime-gated to extreme states.
- **Overfitting stack (CPCV/DSR/PBO) is best-practice** — but see P1-A (apply it to the live fleet) + P1-E (feed DSR correctly).
- **Standard-architecture gap check**: PQS has data/alpha/construction/exec-sim/post-trade/alerting/risk. Under-built: model lifecycle/versioning formalization; live execution layer (blueprint only — acknowledged this-phase); **data-vendor determinism/redundancy** (single yfinance frontier that revises — the settle-window + P1-C benchmark auto-fetch are symptoms of this single-source fragility).

---

## 3. Prioritized action backlog (by impact on reliable profitability)

| # | Action | Type | Sev | Effort | Why it matters to profit |
|---|--------|------|-----|--------|--------------------------|
| 1 | Enforce SQQQ blacklist inside `resolve_universe`; derive leveraged-ETF exclusion from config | fix | P0 | S | Hard invariant currently bypassable → uncontrolled leverage/inverse risk |
| 2 | Thread `risk.yaml symbol_caps`+leverage caps into `PortfolioConstructor`; kill hardcoded 0.35 | fix | P0 | M | Drawdown budget unprotected per-name; "configurable not hardcoded" invariant |
| 3 | Wire a stress-slice MaxDD≤25% acceptance gate; make StressTester emit a DD path | add | P0 | M | The 2008 Black-Swan invariant is currently unbacked at runtime |
| 4 | Finish QQQ deprecation: drop from `all_passed`, relabel master-report, route evaluator via `should_demote_qqq_gate` | fix | P0 | S | Prevents wrong no-go on a SPY-beating strategy |
| 5 | Converge robustness/pseudo-OOS path to `adjusted=True(+TR)`; split-in-window smoke | fix | P0 | S | Selection evidence corrupted on split windows |
| 6 | Run cycle06/08 (or successors) through the cycle13b SOTA-overfit harness before any capital | process | P1 | M | Live fleet never passed DSR/PBO/CPCV |
| 7 | `attention_report` benchmark `fallback="local"`; audit `BarStore.load` default→local | fix | P1 | S | Honest, deterministic vs-SPY in forward judgment |
| 8 | Doc sync: factor count→187/A-T (registry SoT), CLAUDE.md Active State, INDEX regen, pricing table | doc | P1 | S | Operator reads correct state; go-no-go integrity |
| 9 | Regime module = defensive-only; make vol-target CONDITIONAL (extreme-state-gated) | design | P1 | M | Aligns with evidence (timing weak; conditional vol-target cuts DD) |
| 10 | Reconcile risk.yaml DD ladder vs KillSwitch; ship fleet C5 DD-throttle before multi-candidate | fix | P1 | M | Staged de-risking is documented but not what runs |
| 11 | DSR fed returns not fold-IC; evaluator NaN→fail-closed; nonzero embargo; fill_date holiday-aware | fix | P1/P2 | S | Correctness of reported rigor + gates fail-closed |

**Strategic recommendation (operator):** sequence **1-5 (P0 enforcement + QQQ + selection-integrity) FIRST** — they make the system *safe and honest* regardless of alpha. Then **6 + 9** (apply rigor to the live fleet; align regime/vol-target to evidence). The **edge gap (P1-B) is the real project risk**: given cycle06/08's OOS fade + the literature (thin long-only edge, timing weak), the highest-EV research direction is *cheap harvesting of well-established factor premia + strict conditional drawdown control*, rather than continuing to chase a bespoke alpha that keeps failing OOS (sibling convergence). Do NOT add portfolio optimization.

---

## 4. Coverage & honesty (what this audit did NOT cover)

- Deep+verified: data/pricing/backtest-leakage core, temporal-split/sealed/CPCV enforcement, risk/kill-switch/portfolio/fleet/universe wiring, QQQ code paths, factor-count, settle-window. 4 sub-audits each ran existing unit tests (120 + 257 + 368 + docs greps) — no failures beyond expected QQQ xfail.
- NOT reached: options sleeve risk internals; intraday timing-veto risk interaction; ML label-alignment vs training split (`core/research/ml/labels.py shift(-horizon)` seen, not verified); ~99 unindexed memos' contents; 30+ PRD "DONE" labels beyond 4 spot-checks; full factor-by-factor lookahead beyond the AST-verified composite path (composite is clean; individual research-only factors not each traced).
- Sub-agent claims CORRECTED by operator R3: (a) SOTA gates "only in tests" → actually wired in cycle13b harness; (b) QQQ "single path" → confirmed across 3 paths. No blanket verdicts issued; each failure scoped to a file:line + condition.

**Highest-value next audit scope**: the 30+ 2026-05→07 PRD "DONE/SHIPPED" labels vs code (spot-checks found the QQQ half-done; likely more), and the options/ML sleeves.
