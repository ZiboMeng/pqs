# Phase-two strategy research plan

Status: preregistered before candidate code evaluation

Policy source of truth: `config/strategy_promotion.yaml`

Research objective: one stable core plus one economically distinct growth or
ETF-rotation strategy eligible for PAPER; LIVE remains disabled

## Epistemic boundary and data partitions

The researcher and repository have already seen aggregate performance through
2026-07-17 for older strategy families. Therefore 2024-2026 is not described as
globally pristine. It is locked here as a **phase-two hypothesis-scoped final
holdout**: none of the candidate definitions or parameter choices below may be
changed after their family finalist reads it.

| Role | Dates | Permitted use |
|---|---|---|
| development | 2007-01-03 to 2016-12-30 | coarse parameter comparison and implementation diagnosis |
| validation / anchored walk-forward | 2017-01-03 to 2023-12-29 | one fixed family candidate; annual sequential folds |
| phase-two final holdout | 2024-01-02 to 2026-07-17 | at most one frozen finalist per family; never tune |

Every slice receives 252 prior sessions only as indicator warmup. Warmup PnL is
excluded. A family may submit at most one finalist and the entire phase at most
four. Holdout rejection retires that version; its logic and parameters cannot
be edited and retested against the same holdout as if it remained unseen.

All signals use total-return-adjusted data known at session close and execute at
the next tradable open. SPY and QQQ benchmarks use the same basis. Cash return
is represented by BIL/SHY/SHV holdings; no unreported interest is credited.

## Uniform evaluation

Before a run, the runner appends a `PLANNED` registry entry containing the
experiment ID, family/version, hypothesis, parameters, range, cost model,
benchmark, code commit and random seed. Completion updates the same entry,
including failures. All candidates use current integer-share accounting and
the current commission/slippage/spread proxy.

Reported evidence includes CAGR, total return, volatility, Sharpe, Sortino,
Calmar, IR, drawdown depth/duration/time-under-water, worst day/week/month,
monthly and annual returns, exposure, turnover, trade count, holding-period
proxy, beta/alpha where meaningful, tail loss, cost, capacity proxy, regime and
PnL concentration. Robustness includes 2x costs, one extra signal-session delay,
parameter neighbors, deterministic rerun, missing/stale input and annual
walk-forward folds. Bootstrap confidence intervals and a conservative
multiple-testing haircut are reported; PBO/DSR is only claimed where the
available trial matrix makes it identifiable.

The numerical gates were frozen in `strategy_promotion.yaml` before any new
candidate result. They may be made stricter after red-team review, never looser
to manufacture a pass.

## Family A — adaptive stable core (`adaptive_core_v1`)

- Economic logic: equity risk is compensated over long horizons, but a core
  portfolio should reduce exposure when multiple trend horizons weaken and
  realized volatility rises. Gold, intermediate Treasuries and short Treasury
  ETFs diversify the residual budget.
- Assets: SPY, QQQ, IEF, GLD, BIL, SHY, SHV. No individual stocks and no
  leveraged ETF.
- Data: daily total-return OHLC; at least the maximum trend/volatility warmup.
- Signal: the average of positive price-vs-moving-average and positive
  multi-horizon-return indicators, multiplied by an equity volatility target.
- Earliest trade: next open after a month-end close decision and 252 sessions of
  warmup.
- Entry/exit: gradual equity budget changes; no binary single-MA switch. Lost
  trend/volatility budget moves to the three cash proxies, with fixed bounded
  GLD/IEF sleeves.
- Positioning: fully collateralized, long-only; every symbol <= current 35%
  account cap; portfolio gross <= 1.
- Risk budget: strategy type `stable_core`, MaxDD gate 20%, target equity
  participation >=45%, no TQQQ.
- Target regimes: independent by default; existing regime gating is compared
  but retained only if validation value improves after switching costs.
- Benchmark: SPY total return; simple 200-day SPY/cash trend is an additional
  implementation baseline.
- Coarse development grid: three preregistered trend triplets
  `(42,126,210)`, `(63,126,252)`, `(84,168,252)` crossed with volatility targets
  `10%, 12%, 14%` = 9 attempts. Other logic is fixed.
- Expected failures: bond/equity correlation shock, cash drag in vertical bull
  markets, slow crash response, concentration in a defensive sleeve.
- Promotion: common gates plus stable-core gates; nearby grid cells must form a
  plateau. Only one development winner enters validation and at most one frozen
  finalist enters holdout.

This single hypothesis covers the requested SPY volatility target,
multi-timescale trend, equity/short-bond switching, drawdown-aware core exposure
and combined trend-plus-volatility design without treating each minor variation
as a separate strategy.

## Family B — controlled Nasdaq growth (`controlled_growth_v1`)

- Economic logic: persistent Nasdaq trends can justify a bounded growth sleeve;
  leveraged exposure has value only during broad, strong and non-stressed
  trends. Volatility decay makes permanent TQQQ exposure unacceptable.
- Assets: QQQ, SPY, TQQQ, nine long-lived sector ETFs for breadth, and
  BIL/SHY/SHV collateral.
- Signal: QQQ multi-horizon trend strength, fraction of sectors above their
  long trend, QQQ realized volatility and a fast drawdown exit.
- Earliest trade: next open after close; weekly decisions; 252-session warmup.
- Entry: QQQ/SPY risk rises gradually with trend strength. TQQQ is permitted
  only when trend and breadth thresholds pass and volatility scaling leaves a
  positive allocation.
- Exit/cooldown: loss of fast trend or an 8% rolling QQQ drawdown removes TQQQ
  immediately and starts a fixed cooldown. Risk assets reduce as slow trend
  weakens.
- Positioning: QQQ <=30%, SPY <=35%, TQQQ <=10%, gross <=1, no margin.
- Risk budget: strategy type `growth_engine`, MaxDD gate 23%; separate TQQQ
  cap and gap/decay reporting.
- Target regimes: mapped strong-bull/risk-on only for TQQQ; UNKNOWN, stressed
  and defensive states fail closed. Independent trend logic is the control.
- Benchmark: QQQ total return and a fixed 30% QQQ/70% T-bill control.
- Coarse development grid: slow trend `168/210/252`, breadth threshold
  `55%/65%`, QQQ annualized-vol ceiling `22%/28%` = 12 attempts. Fast exit,
  10-session cooldown and TQQQ cap are not tuned.
- Expected failures: gap through exit, whipsaw, leverage decay, high
  correlation with stable core, and failure to add Calmar versus QQQ.
- Promotion: common plus growth gates, including QQQ-relative Calmar, beta,
  cooldown/risk-on tests and capped TQQQ stress behavior.

## Family C — sector ETF rotation (`sector_rotation_v1`)

- Economic logic: persistent leadership across liquid US sectors may be
  harvested with slow, diversified rotation; volatility-normalized ranks avoid
  mechanically preferring the highest-beta sector.
- Assets: XLK, XLF, XLE, XLV, XLI, XLY, XLP, XLU, XLB plus SPY, IEF, GLD,
  BIL and SHY. XLC/XLRE are excluded because their shorter histories would
  change the candidate set inside the test period.
- Signal: weighted 3/6/12-month momentum excluding the most recent month,
  divided by 63-day volatility, plus an absolute SPY/sector trend filter.
- Earliest trade: next open after month-end close; 252-session warmup.
- Entry/exit: hold the top two or three positive/trending sectors until the
  next month-end; unused budget goes to T-bills. Broad risk-off sends the
  portfolio to predefined IEF/GLD/T-bill weights, not the unconstrained
  “best defensive” asset.
- Positioning: selected sector <=35%; selected-sector gross <=70%; gross <=1.
- Risk budget: strategy type `etf_rotation`, MaxDD gate 23%, at most 12 risky
  assets by policy (nine used).
- Target regimes: sideways/risk-on participation with independent absolute
  trend control. Existing regime gating is a validation comparison only.
- Benchmark: SPY total return and equal-weight sector ETF buy-and-hold.
- Coarse development grid: three fixed momentum mixes
  `(0.2,0.3,0.5)`, `(0.3,0.4,0.3)`, `(0.4,0.3,0.3)` for 3/6/12 months,
  top-N `2/3`, slow trend `168/252` = 12 attempts.
- Expected failures: momentum crash, synchronized sector selloff, leadership
  reversal, and residual equity beta.
- Promotion: common plus rotation gates and complementarity with any selected
  stable core. One finalist maximum.

## Family D — liquid ETF close-to-next-open mean reversion (`etf_reversion_v1`)

- Economic logic: short-lived liquidity overshoots can rebound in otherwise
  healthy trends; falling knives in structural downtrends are excluded.
- Assets: SPY, QQQ and the same nine long-lived sector ETFs; BIL/SHY/SHV hold
  unused capital.
- Signal: preregistered multi-day loss plus RSI(2) oversold condition while
  price remains above its 200-session trend and portfolio volatility is below a
  fixed stress ceiling.
- Earliest trade: next open after the oversold close. Exit after a fixed holding
  period or mean recovery; never same-close execution.
- Positioning: at most three concurrent ETFs, <=20% each; the rest T-bills.
- Risk budget: strategy type `daily_mean_reversion`, MaxDD gate 18% and annual
  turnover gate 12x.
- Benchmark: SPY and an always-cash proxy.
- Coarse grid: loss threshold `-2.5%/-3.5%`, RSI cutoff `5/10`, hold `2/4`
  sessions = 8 attempts.
- Expected failures: persistent selloffs, overnight gaps, high turnover and
  cost sensitivity. Failure retires the family; thresholds will not be expanded.

## Family E — individual-stock cross-section (`stock_cross_section_v1`)

This is preregistered as **not promotion eligible and not run**. The local data
has current constituents and first-trade dates but not point-in-time universe
membership, delisted constituents or point-in-time fundamentals. Existing
multi-factor evidence already shows 65 Tier-D variants with zero OOS passes.
Running another stock selector would add survivorship and multiple-testing debt,
so ETF families receive the formal promotion budget.

## Iteration C2 — sector rotation safety repair (`sector_rotation_v2`)

Status: preregistered after the v1 validation execution failure and before v2
implementation/evaluation. The 2017–2023 validation interval is no longer
pristine for this family; the 2024–2026 final holdout remains unaccessed.

V1 attempted to allocate the full 70% risky budget to one symbol when only one
sector had a positive eligible score. V2 changes only the allocation invariant:
for `k` selected sectors, risky gross is `min(70%, 35% × k)`, split equally;
the exact residual is split equally between BIL and SHY. Thus one sector gets
35% plus 32.5%/32.5% defensive weights, two sectors get 35% each plus 15%/15%,
and three sectors retain v1's 23.33% each plus 15%/15%.

No signal, rank, universe, rebalance timing, cost, execution, benchmark or gate
changes are permitted. There is exactly one development cell: momentum weights
`(0.2,0.3,0.5)`, top-N `3`, slow trend `168`, the representative frozen before
the v1 validation read. Development must still clear the original basic gate.
If it does, validation registers the same base/2x-cost/delay/determinism suite
and the same three adjacent parameter checks solely as robustness evidence; no
neighbor may replace the fixed representative. V2 failure retires this repair.

## Final selection and non-negotiable stop rules

Development ranks by a preregistered composite of gate margin, not headline
CAGR. Validation sees only the selected parameter cell. A family failing the
common validation gates does not access holdout. Holdout access is logged before
the read. No family can use a successful holdout to retune or a failed holdout
to try neighboring parameters.

Two PAPER strategies must come from different families, pass the
complementarity/aggregate portfolio gates and survive paper-style daily replay,
fault injection and restart reconciliation. Otherwise they remain rejected,
even if that delays the requested count.
