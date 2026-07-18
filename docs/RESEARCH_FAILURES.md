# Existing strategy failure attribution

Status: frozen before phase-two candidate evaluation

Evidence cutoff: corrected total-return diagnostic ending 2026-07-17

Promotion consequence: none of the existing strategies is eligible for PAPER

## Evidence basis and limitations

The comparison uses the certified next-open engine, current base costs, integer
shares, the 81-symbol executable universe and the total-return sidecar validated
in `docs/BACKTEST_CERTIFICATION.md`. The common range is 2007-01-03 through
2026-07-17. This is a diagnostic full-history comparison, not new OOS evidence:
the repository's former rolling holdout and its old 2026 sealed interval have
both been viewed repeatedly.

| Strategy | CAGR | Sharpe | MaxDD | IR vs SPY | Trades | Disposition |
|---|---:|---:|---:|---:|---:|---|
| dual momentum | 5.70% | 0.22 | -22.05% | -0.33 | 913 | `REDESIGN_HYPOTHESIS` |
| trend following | -1.45% | -1.18 | -30.15% | -0.71 | 7,084 | `RETIRED` |
| cross-asset rotation | 4.19% | 0.05 | -11.12% | -0.43 | 781 | `REDESIGN_HYPOTHESIS` |
| multi-factor | 7.98% | 0.47 | -14.98% | -0.23 | 2,999 | `RETIRED` |
| SPY total-return benchmark | 10.90% | 0.42 | -55.2% | n/a | n/a | benchmark |

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

The certified baseline has the strongest old headline metrics but still trails
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
