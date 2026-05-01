# Step 0 Retro Sanity Check + C-3 → C-1 Pivot

- **Date**: 2026-04-30
- **Author**: Claude (operator) under user explicit-go
  ("按照你的建议走" 2026-04-30)
- **Triggers**:
  - Cycle #01 closeout `docs/memos/20260430-track_c_cycle_2026-04-30-01_close.md`
  - Auditor pasted Round-cycle review (priority C-3 → C-1 → C-4 → C-2)
  - My counter-recommendation after Step 0 evidence
- **Outcome**: Cycle #02 axis pivoted from **C-3 beta-controlled
  construction** to **C-1 weekly cadence**.

## 1. Step 0 plan

The auditor recommended:
1. Step 0 retro NAV-level beta-cap sanity check on RCMv1 paper NAV
   (~0.5-1 day)
2. Step 1 per-trial composite-spec → paper NAV harness (~2-3 days)
3. Step 2 Cycle #02 criteria yaml: C-3b portfolio beta cap = 0.75
4. Step 3 Cycle #02 mining + evaluation

I added Step 0 as a cheap upper-bound check **before** committing to
2-3 days of Step 1 + cycle setup, to avoid the failure mode where
Step 1 harness ships and Cycle #02 then turns out to address only a
small fraction of the actual sibling-collapse mechanism.

## 2. What Step 0 actually showed

### 2.1 Original goal (BLOCKED by data quality issue)

The original Step 0 plan was:
1. For each day with active RCMv1 weights, compute portfolio_beta
   from rolling 60d per-symbol betas × paper-run weights
2. Apply hindsight cap: if portfolio_beta > 0.75, scale weights
3. Recompute hindsight-capped daily returns + cumulative NAV
4. Compare (capped NAV vs SPY) correlation to (unconstrained NAV
   vs SPY) correlation

This produced numerically broken cum_ret (+2994% on 2022 cell, +1.3M%
on 2024 cell) because the **raw `data/daily/*.parquet` files have
heterogeneous split adjustment** — symbols like LRCX, NVDA, TQQQ,
XLK alternate between two scales (e.g., LRCX 2022-08-30 close=442.92
vs 2022-08-31=4.21 vs 2022-09-09=45.10). This is a bar-level cross-
source merging artifact (polygon canonical + yfinance fallback +
trades_backfill paths producing inconsistent split state).

`BarStore.load(adjusted=True)` does not fix this — the splits.parquet
cascade applies a single global adjustment, but the underlying RAW
bars themselves have inconsistent state across dates within the same
symbol. Recomputing per-symbol returns from the parquets directly is
unreliable.

Per-trial harness (Step 1) will reuse `BacktestEngine` which does
produce sane numbers in paper runs, so this isn't a blocker for
Step 1 — it's only a blocker for the original Step 0 hindsight
recomputation.

### 2.2 Reliable measurement path (used PAPER engine NAV directly)

Bypassed the broken raw-parquet path by using RCMv1's actual paper-
engine `live_like_pnl.csv` (which DID handle whatever bar-data
inconsistency was there at paper-run time):

| Cell | Period | RCMv1 cum_ret | SPY cum_ret | daily corr(RCMv1, SPY) | **realized β(RCMv1, SPY)** |
|---|---|---|---|---|---|
| 2022 | 2022-08-26 → 2022-12-15 (78d) | +5.51% | −6.74% | 0.468 | **0.314** |
| 2024 | 2024-01-02 → 2024-04-19 (76d) | +4.44% | +1.69% | 0.169 | **0.143** |

Realized β computed as OLS slope of RCMv1 daily returns regressed on
SPY daily returns over the cell window. n=78 + n=76 separate cells.

### 2.3 Substantive finding

**RCMv1's actual realized portfolio_beta_to_spy is 0.14 (bull regime)
to 0.31 (bear regime).** Both well below the auditor's proposed 0.75
cap. **A 0.75 cap would essentially never bind on RCMv1-style
construction.**

This contradicts my initial broken-data calculation that said
24-32% of days had port_beta > 0.75. That was an artifact of the
heterogeneous bar data inflating individual symbol betas. The
realized β computed from paper-engine NAV is the truthful measure
because it uses the same return computation path that produced the
NAV.

## 3. Why this changes the strategic priority

### 3.1 Cross-checking with existing NAV correlation evidence

`docs/memos/20260430-rcmv1_cand2_realized_correlation.md` already
documented:
- Raw RCMv1 vs Cand-2 NAV Pearson: **0.898** over 154d post-step3b
- Residual vs SPY Pearson: **0.609** (drop ~0.29)
- Residual vs QQQ Pearson: **0.579** (drop ~0.32)

Interpreting the drop magnitudes:
- ~30% of raw NAV correlation is explained by **shared market beta
  exposure** (the SPY/QQQ residual stripping captures this)
- ~60% is **residual alpha overlap** at the holdings/sleeve level

A beta-cap construction (C-3) by design **only changes shared market
beta exposure**. It scales position weights down + adds cash; it does
NOT change which symbols are held or in what relative ratios.
Therefore C-3 beta cap addresses ~30% of the sibling-correlation
problem, not the 60% residual overlap.

### 3.2 What sibling-collapse actually IS

Cycle #01 closeout §5.1 + this Step 0 evidence + the existing
correlation memo all triangulate the same mechanism:

> Sibling collapse is NOT high market beta. RCMv1 + Cand-2 are both
> already low-beta defensive composites. Sibling collapse comes from
> **shared holdings on shared defensive/quality factor tilts** —
> long-only × monthly × top-N × same 78-symbol universe forces any
> "rank stocks by defensive winner-ness" composite into the same
> sleeve, regardless of which specific factors compose the score.

A beta cap doesn't change this mechanism. It just rescales the
already-shared sleeve.

### 3.3 What WOULD change the mechanism

| Construction lever | What it changes | Mechanism it addresses |
|---|---|---|
| Beta cap (C-3) | Scale weights + cash | Shared market beta (~30% of corr) |
| **Weekly cadence (C-1)** | **Which factors win at shorter horizon** | **Re-opens Family E/F (intraday/microstructure/reversal); different winners → different holdings** |
| Cross-asset universe (C-4) | Adds TLT/GLD/IEF outside equity universe | Direct holdings divergence |
| Long-short (C-2) | Sign-symmetric alpha | Different alpha space |

**C-1 directly tests cycle #01 closeout §3.3 hypothesis** that "21d
forward-return target combined with monthly long-only top-N
construction kills the IC of fast-decaying reversal/microstructure
alpha". If shorter horizon (5d or weekly forward) makes Family E/F
factors win in the mining search, holdings will fundamentally
differ from RCMv1's defensive sleeve.

## 4. Pivot decision

| Original (auditor) | New (post-Step-0) | Reason |
|---|---|---|
| **C-3** beta cap (#1) | C-3 beta cap (#3) | Only addresses 30% of corr; cap=0.75 doesn't even bind on RCMv1 |
| C-1 weekly cadence (#2) | **C-1 weekly cadence (#1)** | Directly tests Family E/F horizon hypothesis; high-ROI on un-tested DOF |
| C-4 cross-asset (#3) | C-4 cross-asset (#2) | Direct universe divergence; promoted to second |
| C-2 long-short (#4) | C-2 long-short (#4) | Unchanged — conflicts with no-margin/no-short |

If Cycle #02 (C-1) shows weekly cadence still produces sibling-collapse,
proceed to C-4 cross-asset. If C-4 also collapses, then either C-3
beta cap with much-tighter parameters or revisit fundamental
assumptions.

If C-1 produces a non-sibling candidate, that's a real Track-A
candidate — proceed to evidence pack §4.6/§4.7 + sealed eval prep.

## 5. Implications for Step 1 harness scope

The auditor's Step 1 spec (per-trial composite-spec → paper NAV
harness) is largely unchanged but with **one critical addition**:

> The harness MUST support a configurable rebalance cadence
> (daily / weekly / monthly), not just monthly.

`MultiFactorStrategy.generate()` currently supports a `rebalance_freq`
parameter (default monthly). The harness needs to pass this through
from criteria yaml's `construction.rebalance_cadence` field. This is
a small addition (one field threaded through the connector), not a
structural change.

## 6. What this Step 0 produced

1. **Reliable finding**: RCMv1 realized β = 0.14 (bull) to 0.31
   (bear). 0.75 cap is too soft; would essentially never bind.
2. **Strategic insight**: ~30% of RCMv1+Cand-2 raw correlation is
   shared beta; ~60% is shared holdings/sleeve. Beta cap addresses
   only the 30%.
3. **Axis pivot**: Cycle #02 primary axis = **C-1 weekly cadence**,
   not C-3 beta cap.
4. **Step 1 harness scope**: must include configurable rebalance
   cadence; otherwise unchanged.
5. **Data-quality finding**: raw `data/daily/*.parquet` for some
   symbols has heterogeneous split adjustment; the canonical read
   path (`BarStore.load(adjusted=True)`) does not fix this. The
   per-trial harness must use the paper-engine return path, NOT
   recompute returns from raw parquets directly. Existing
   `BacktestEngine` does this correctly (paper run NAVs are sane);
   the harness reuses it.

## 7. Audit trail

Step 0 script committed at:
`dev/scripts/correlation/step0_rcmv1_beta_cap_retro.py`

Step 0 invocation (run on 2026-04-30 ~17:00 PT):
```
python dev/scripts/correlation/step0_rcmv1_beta_cap_retro.py
```

Output captured in this memo §2.2 (reliable measurements). The
broken hindsight-capped cum_ret numbers (+2994%, +1.3M%) are NOT
to be cited as evidence — they are bar-data artifacts that this
memo specifically diagnoses and rules out.

— 2026-04-30, Claude (operator) under user explicit-go.
