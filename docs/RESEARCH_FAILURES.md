# Existing strategy failure attribution

Status: original legacy attribution frozen before phase-two evaluation; D2R2
development outcomes appended 2026-07-17

Current certified evidence cutoff: D2R2 development ending 2016-12-30

Promotion consequence: none of the existing strategies is eligible for PAPER

## Evidence basis and limitations

Important correction: the legacy comparison table below came from D1. Later
phase-two work proved that D1 mixed short ETF histories and incompatible source
adjustment semantics. Its numerical values are retained for lineage but are no
longer valid evidence for promotion or rejection. The conservative decision to
withhold promotion remains valid because invalid evidence cannot establish
eligibility. Any old implementation-level finding below is a design hypothesis,
not a certified performance claim, until rerun on D2.

| Strategy | CAGR | Sharpe | MaxDD | IR vs SPY | Trades | Disposition |
|---|---:|---:|---:|---:|---:|---|
| dual momentum | 5.70% | 0.22 | -22.05% | -0.33 | 913 | `REDESIGN_HYPOTHESIS` |
| trend following | -1.45% | -1.18 | -30.15% | -0.71 | 7,084 | `RETIRED` |
| cross-asset rotation | 4.19% | 0.05 | -11.12% | -0.43 | 781 | `REDESIGN_HYPOTHESIS` |
| multi-factor | 7.98% | 0.47 | -14.98% | -0.23 | 2,999 | `RETIRED` |
| SPY total-return benchmark | 10.90% | 0.42 | -55.2% | n/a | n/a | benchmark |

## D2R2 phase-two development outcomes

D2R2 used the certified manifest, next-open execution, integer shares, current
base costs and total-return prices. The 41-cell grid was frozen and registered
before data access. Evaluation begins after the 252-session warmup and ends
2016-12-30. These results are in-sample development evidence only.

| Frozen family representative | Cells passing basic gate | CAGR | Sharpe | Sortino | MaxDD | Disposition |
|---|---:|---:|---:|---:|---:|---|
| adaptive core | 1 / 9 | 6.30% | 0.307 | 0.411 | -10.93% | `ADVANCE_VALIDATION` |
| controlled growth | 0 / 12 | 3.23% | -0.075 | -0.089 | -15.46% | `STOP_V1` |
| sector rotation | 3 / 12 | 7.25% | 0.406 | 0.554 | -12.80% | `ADVANCE_VALIDATION` |
| ETF reversion | 0 / 8 | 1.26% | -0.923 | -1.215 | -6.85% | `STOP_V1` |

The adaptive representative uses trend windows 84/168/252 and a 14% volatility
target. Only one of nine cells passed, so its local parameter stability remains
an explicit validation risk. The sector representative uses 20%/30%/50%
multi-horizon weights, top three sectors and a 168-session slow trend; three
cells passed, but it still must clear annual folds, parameter neighbors, 2x
costs, one-session delay and benchmark-improvement gates.

Controlled growth failed all 12 cells. Its best cell remains almost fully
invested through cash ETFs, turns over 6.34x/year and earns only 3.23% CAGR;
under the frozen 4% risk-free convention both Sharpe and Sortino are negative.
Losses in 2011, 2015 and 2016 show that the breadth/TQQQ gate does not create a
reliable growth premium. No v1 cell advances.

ETF reversion failed all eight cells. The best cell turns over 10.97x/year,
incurs 739 fills and produces only 1.26% CAGR, so the low 6.85% drawdown is
mostly a low-return/cash-exposure effect rather than compensated alpha. Negative
risk-adjusted returns reject the v1 oversold trigger; it will not be tuned after
viewing these outcomes.

### D2R2 validation outcome

Adaptive core completed all six registered validation/robustness runs and
passed every frozen research gate on 2017–2023: CAGR 9.04%, Sharpe 0.606,
Sortino 0.766, MaxDD -14.75%, 5/7 positive annual folds, both parameter
neighbors passing, 2x-cost Sharpe 0.597 and delayed-signal Sharpe 0.635. Its
stationary-bootstrap CAGR interval is 2.70% to 15.84%. It becomes a frozen
holdout finalist, not yet a PAPER strategy.

Sector rotation v1 failed closed before performance evaluation. In validation,
a date with only one eligible positive-momentum sector made the v1 allocator
attempt a 70% single-symbol target, violating the 35% hard cap. The base run is
`FAILED`; its six dependent robustness experiments are also retained as
`FAILED`. V1 is ineligible. A safety-corrected v2 may be preregistered as a new
version with one fixed development cell and unchanged gates; because v1 exposed
the validation period, v2 validation reuse is explicitly non-pristine and only
the still-unaccessed final holdout can provide new final evidence.

Sector rotation v2's single preregistered D2R3 development cell passed with the
expected v1-equivalent metrics (7.25% CAGR, 0.406 Sharpe, 0.554 Sortino,
-12.80% MaxDD). No alternative v2 development parameter was run or selected.
The fixed repair may proceed to the disclosed validation reuse.

All seven D2R3 v2 validation/robustness experiments then passed: 7.39% CAGR,
0.383 Sharpe, 0.486 Sortino, -11.13% MaxDD, 5/7 positive annual folds, all
three neighbors passing, 2x-cost Sharpe 0.355 and delayed-signal Sharpe 0.439.
The bootstrap CAGR interval is 1.20% to 13.42%. Despite the non-pristine reused
validation interval, the unchanged v2 now qualifies as a frozen finalist for
one access to the still-unread phase-two final holdout.

### Final holdout decisions

Both finalist accesses were registered and committed before any 2024–2026
candidate data was loaded. Neither passed, so neither may enter PAPER:

- Adaptive core returned 15.80% CAGR with 1.039 Sharpe and -9.37% MaxDD, but
  SPY's -18.76% holdout drawdown meant the improvement was 9.39 percentage
  points, below the frozen 10-point requirement. It failed exactly that gate.
- Sector rotation v2 returned 4.36% CAGR with 0.076 Sharpe and -10.36% MaxDD.
  It failed Sharpe, Sortino, single-year positive-PnL concentration and Calmar
  improvement versus SPY. Its 2026 partial-year return was -6.03%.

The thresholds are not relaxed. Both versions are final-rejected, and their
logic/parameters will not be edited and retested on this holdout. Two of the
four preregistered finalist slots remain available only to genuinely new,
economically distinct hypotheses.

## Legacy D1 design notes (performance numbers invalidated)

The subsections below preserve the original D1 attribution. Every performance
number in them is historical, invalidated lineage; only code/design observations
and the fail-closed no-promotion decision remain actionable.

The apparently good SPY drawdown is not the relevant stable-core target: a
stable strategy must reduce it materially while retaining a reasonable CAGR and
improving risk-adjusted return. Conversely, a low drawdown alone does not rescue
the rotation strategy's near-zero net Sharpe.

## Dual momentum — `REDESIGN_HYPOTHESIS`

The implementation applies one 12-month absolute/relative momentum rule to a
large heterogeneous equity universe and selects three names. The absolute
threshold is calculated as a one-month rate but compared with a 12-month
return; at the default zero rate this does not change selection, but it makes
non-zero configurations dimensionally wrong. The monthly decision is made on
the first session of each month and executed at the following open, adding an
unintended extra session relative to a month-end decision.

Failure attribution:

- Return source: concentrated equity beta and cross-sectional momentum, not a
  capital-protection sleeve. It trails SPY by 5.2 percentage points annualized.
- Drawdown source: selection remains fully exposed whenever three names have
  positive trailing returns; there is no portfolio volatility target or
  drawdown-aware equity budget.
- Period dependence: the full result spans several regimes yet still has
  negative IR. The 913 trades are sufficient to reject an “insufficient event
  count” explanation.
- Parameter sensitivity risk: lookback is effectively the only economic
  parameter. Rescuing it by searching many windows/top-N combinations after
  seeing 2026 would be unconstrained data mining.
- Duplicate risk: it overlaps the relative-strength and momentum components of
  the retired multi-factor family.

No-go region: do not tune the legacy all-stock universe. A replacement must
use a deliberately small ETF set, dimensionally consistent horizons, explicit
cash/short-bond handling and volatility/risk budgets.

## Trend following — `RETIRED`

The same daily EMA condition is independently applied to almost every risk
asset, then equal weighted. It was designed as an execution baseline, not as a
portfolio hypothesis.

Failure attribution:

- It loses money after 7,084 trades, with Sharpe -1.18 and a -30.15% drawdown.
  This rejects “more samples will fix it.”
- Daily crossings of fast and slow EMA conditions cause threshold oscillation,
  turnover and costs. There is no hysteresis, minimum holding period or
  volatility scaling.
- Applying identical absolute trend rules to stocks, sectors and ETFs produces
  unstable breadth and implicit survivorship/current-universe exposure.
- The result is not merely low beta: negative CAGR and negative IR show that
  the implementation destroys value after costs.

No-go region: no fine-grained EMA search and no revival under a new name. A new
stable-core hypothesis may use multi-timescale trend as one component, provided
it also has volatility targeting, bounded turnover and explicit defensive
allocation.

## Cross-asset rotation — `REDESIGN_HYPOTHESIS`

The implementation ranks a broad risk pool using one skipped 12-month momentum
window. Remaining budget is always allocated to the strongest defensive asset,
even when its own momentum is negative. Regime scaling also changes the risk
budget before the defensive residual is filled, so the model often replaces
risk rather than holding cash.

Failure attribution:

- Capital protection works partially (MaxDD -11.12%), but CAGR 4.19%, Sharpe
  0.05 and IR -0.43 show inadequate compensation after costs and the configured
  4% risk-free assumption.
- The “best defensive” rule can concentrate duration or gold risk and is not an
  absolute safety test.
- A single horizon makes the rank vulnerable to endpoint effects. The strategy
  does not normalize momentum by asset volatility.
- Its 781 trades are not a small-sample artefact. The economic design, not the
  implementation plumbing, is the failure.

No-go region: do not search the legacy 81-symbol pool. A replacement rotation
candidate is limited to long-lived liquid sector ETFs, multi-horizon
risk-adjusted momentum, a fixed maximum of three selected sectors and explicit
T-bill fallback.

## Multi-factor — `RETIRED`

The invalidated D1 baseline has the strongest old headline metrics but still trails
SPY materially and has IR -0.23. More importantly, the archive contains 65
historical trials on lineage `post-2026-04-23-feat-v1-expanded`: 32 passed the
quick screen, zero passed OOS, zero passed holdout and zero were promoted. The
best archived OOS IR is -0.119 and the worst is -0.815; every trial is Tier D.

Failure attribution:

- The current-stock universe lacks historical point-in-time membership and
  delisted constituents, so apparent cross-sectional alpha is exposed to
  survivorship and selection bias.
- Several factors are correlated forms of trend/relative strength. The broad
  search history creates substantial multiple-testing debt.
- 2,999 trades and 65 registered variants provide ample evidence against
  treating the failure as a single unlucky parameter setting.
- Positive absolute performance is largely long-equity beta; negative IR and
  zero OOS passes reject promotion.

No-go region: no further promotion-oriented stock factor mining in phase two.
The implementation remains for reproducibility, but any future stock research
is experimental until point-in-time membership and delisting data exist.

## Historical candidate records

All prior failed experiment files, temporal split versions, mining databases
and result manifests are retained. They are evidence of search count and data
consumption, not clutter. No losing year, trial or trade was deleted during the
cleanup.
