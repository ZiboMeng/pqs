# Forward Observation Abort: RCMv1 + Cand-2 (2026-04-30)

- **Date**: 2026-04-30
- **Trigger**: material data revision detected by F-PRD v2.1 §4.4
  revalidate at first observe attempt after 4-day data accumulation
- **Decision authority**: senior operator (Claude) under user explicit-go
  ("同意你的意见好了" 2026-04-30)
- **Status before**: both candidates `requires_data_review`
- **Status after**: both candidates `aborted` (terminal, absorbing)
- **Affected manifests**:
  - `data/research_candidates/rcm_v1_defensive_composite_01_forward_manifest.json`
  - `data/research_candidates/candidate_2_orthogonal_01_forward_manifest.json`

## 1. What triggered the abort

When I ran the forward observation daily ritual today (post-NYSE-close,
operational rule honored — `is_pre_close: false` for all session-log
entries since 2026-04-28), revalidate detected a material data
revision on the existing TD002 + TD003 hashes:

| Metric | Threshold | Detected | Status |
|---|---|---|---|
| E1 NAV impact | 10 bps | **108.38 bps** | EXCEEDED |
| E2/E3 cum_ret drift | 10 bps | **108.38 bps** | EXCEEDED |
| E2/E3 vs_qqq drift | 10 bps | **37.96 bps** | EXCEEDED |
| E2/E3 vs_spy drift | 10 bps | **21.29 bps** | EXCEEDED |
| E5 raw close drift | 0.5% | **2.4165%** | EXCEEDED |

- Affected scopes: signal_input + execution_nav + benchmark (all three).
- materiality_class: `bound_only` (because per_cell_digest is empty
  under track_per_cell=False default; codex Round-10 Blocker 2
  conservative-bound_only fallback).
- Revised symbols (RCMv1, n=13): BKNG, CLX, KLAC, MTUM, MU, QQQ, QUAL,
  SOXL, SPY, TER, TKO, TT, VLUE.
- Revised symbols (Cand-2, n=16): AVGO, CAT, COP, GOOGL, KLAC, LRCX,
  MU, NVDA, PWR, QQQ, SOXL, SPY, TER, TRGP, TXN, UNH.
- policy_decision: `invalidated`.

Root cause: yfinance retroactively revised raw bar values for these
symbols. `data/ref/splits.parquet` mtime is 2026-04-24 17:54
(pre-TD003); no split was added since TD003 (BKNG 1:25 on 2026-04-06,
VGT 1:8 on 2026-04-21, etc. were already in the parquet at TD003 hash
time). So this is yfinance retroactive bar revision, not a split
adjustment artifact.

## 2. Why abort (Option A) over alternatives

The four options considered and the reasoning that selected A:

| Option | Disposition | Why rejected (or selected) |
|---|---|---|
| **A. abort both candidates** | terminal | **Selected.** F-PRD v2.1 §4.4 absorbing-design respected; legacy decay verification value already low; cycle #01 closeout already confirmed construction-collapse; clean operator action. |
| B. completed_fail both | terminal | Same termination effect as A but inaccurate semantics — candidates didn't fail an evaluation criterion, they were invalidated by a data revision. "aborted" is the correct label. |
| C. re-init with new candidate_ids (`_v2`) | reset | Would set a precedent of re-init on every yfinance retroactive revision — not sustainable. Loses 4 days of fwd-obs anyway. |
| D. wait + re-fetch tomorrow | defer | F-PRD design doesn't support "acknowledge revision and continue"; 108 bps drift is too large to be a flicker; deferring just delays Option A. |

### 2.1 Substantive context that made A the right call

1. **Both candidates were already legacy decay verification per priority
   realign** (`docs/memos/20260430-priority_realign_alpha_first.md`):
   > RCMv1 + Cand-2 reclassified as legacy decay verification under
   > Track A — they were nominated pre-G2.A 30% concentration ceiling
   > + pre-M12 weighted thin-data fix; not eligible for new-framework
   > promotion unless re-run through current gates.

2. **Cycle #01 closeout** (`docs/memos/20260430-track_c_cycle_2026-04-30-01_close.md`)
   confirmed the construction-collapse hypothesis empirically: V1→V2
   factor expansion (33 → 61 reachable factors, including 17 newly-
   reachable intraday/microstructure/short-reversal factors) did NOT
   change the converged structural family of the top trial. RCMv1 +
   Cand-2 are sibling-collapsed at construction level and no further
   forward observation will change that.

3. **NAV-level fleet diversification finding** (`docs/memos/20260430-rcmv1_cand2_realized_correlation.md`):
   raw NAV Pearson 0.898 over 154d post-step3b paper sample. Cand-2's
   "orthogonal" label was retracted at NAV level (still valid only at
   factor-IC level). Fleet-of-two does NOT produce risk diversification.

4. **4-day forward observation has no decisive evaluation value** for
   legacy decay verification when the framework itself has already
   moved past these candidates. Continuing to record their NAV daily
   adds noise, not signal.

### 2.2 What this does NOT close

- It does NOT close the RCMv1 + Cand-2 *historical* paper backtest
  evidence. Their pre-mining records, in-sample IC_IR, robustness
  reports, concentration reports, etc. all remain in
  `data/research_candidates/` for archival reference.
- It does NOT prevent re-using the same factor set under a new
  candidate_id if the framework changes (a new lineage tag with new
  pre-registered criteria yaml could re-open them).
- It does NOT auto-trigger Cycle #02 design — that remains
  user-explicit-go gated per priority realign.

## 3. Audit trail

- decide() invocation:
  ```
  forward decide --candidate-id rcm_v1_defensive_composite_01 --status aborted
  forward decide --candidate-id candidate_2_orthogonal_01 --status aborted
  ```
- Both calls returned exit 0; manifests verified post-decision: both
  show `current_status: aborted`.
- Operational rule honored: forward `fetchdata` ran post-NYSE-close
  (16:56 PT = 19:56 ET = post-close-buffer-15-min). The data revision
  was detected by revalidate, not caused by a pre-close fetch.

## 4. Operational follow-ups

### 4.1 Forward observation workstream now empty

There are zero candidates currently under active forward observation.
This is consistent with the post-priority-realign + cycle-#01-closeout
state. Any future forward observation requires:
- A candidate that passes Track A acceptance under the current
  alternating-regime split AND
- Anti-sibling discipline clearance (raw + residual NAV correlation
  diagnostic) AND
- User explicit-go to open a new lineage / candidate_id.

Cycle #01 produced no such candidate. Cycle #02 design awaits user
explicit-go.

### 4.2 Forward observation daily ritual: paused

Per memory `feedback_forward_observation_ritual.md`, when the user
says "数据来了" / similar, I auto-run readiness + observe + log +
commit. With both candidates in terminal `aborted` status, the
ritual has no work to do. I will continue to expect data-fetch
trigger messages but will respond by reporting "no active forward
candidates" rather than running observe (which would fail-closed on
terminal status anyway).

### 4.3 No backfill / no opt-in re-init

The pre-A++ run's invalidation (cycle #01 closeout §7.1) and these
forward aborts together close the cleanest possible boundary on the
pre-Track-A / pre-A++ candidate generation. No backfill / re-init
is in scope. Future candidates start clean under the new framework.

## 5. Closeout statement

The two candidates that have been forward-observed since 2026-04-24
are now terminal-aborted. F-PRD v2.1 §4.4 absorbing design respected.
Operational rule honored throughout (post-close fetches, no pre-close
data on disk). The data revision that triggered the abort was
yfinance retroactive — a real, post-close, multi-symbol revision that
the revalidate guard correctly fail-closed on. Forward observation
workstream has zero active candidates pending a Cycle #02 candidate
that survives the new framework's gates.

— 2026-04-30, Claude (operator) under user explicit-go.
