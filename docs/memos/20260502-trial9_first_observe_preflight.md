# Trial 9 First-Observe Pre-Flight Verification — 2026-05-02

**Status**: ALL GREEN with 2 operational caveats. Trial 9 first `forward
observe` Monday 2026-05-04 EOD is cleared to proceed.

**Owner**: operator self-driven (90-day soak window 档1-1 task per
`docs/memos/20260501-tomorrow_morning_summary.md` follow-up + user
explicit-go "就按你的建议走" 2026-05-02).

**Why pre-flight**: Trial 9 is the first **diversifier-role** forward
candidate ever (Phase C-PRD-1, commit `7dcdf50`). It carries a new
candidate_role enum value, new soft_warn_flags semantics, new v1↔v2
temporal_split dispatch (commit `60e0dfe`), and new attention_check
automation (commit `7dbae10`). Discovering an integration bug Monday
EOD costs more than a Saturday verification round.

---

## 1. Verification matrix (all dry-run / read-only)

| Check | Command | Result |
|---|---|---|
| Manifest loads | `forward status --candidate-id trial9_diversifier_001` | ✅ `not_started`, n_runs=0, config_snapshot=present |
| Readiness | `forward readiness --candidate-id trial9_diversifier_001` | ✅ `can_append_now=False`, `n_potential_new_tds=0` (data ends 2026-05-01, start 2026-05-04) |
| Dry-run observe | `forward observe --candidate-id trial9_diversifier_001 --dry-run` | ✅ idempotent no-op |
| Attention check (0 runs) | `attention_check.py --candidate trial9_diversifier_001 --no-json` | ✅ TD000 graceful degrade — residual_corrs="insufficient data", combo uses 2 anchors only, soft_warn=`pending_insufficient_data`, no TD60 verdict |
| Manifest fields | (json inspect) | ✅ `candidate_role=diversifier`, `soft_warn_flags=['diversifier_2025_maxdd_18_20pct']`, `decision_days=[10,20,40,60]`, spec_hash + cost_hash present |
| Forward+attention test suite | `pytest tests/unit/research/test_forward_runner.py + test_diversifier_role_phase_c_prd_1 + forward/test_attention_report.py` | ✅ 85 + 31 = 116 passed, 1.10s |
| Temporal split dispatch | `pytest tests/unit/research/test_temporal_split*.py` (5 files) | ✅ 137 passed, 4.02s |

**Total**: 253 unit tests covering active forward + attention + dispatch
code paths all green; no skipped tests.

---

## 2. Operational caveats (NOT pre-flight failures, but Monday-impacting)

### Caveat A — SHV + BIL data lag 14 days

Both readiness reports (Trial 9 + RCMv1) flag:
```
SHV: last_date=2026-04-17, lag_days=14
BIL: last_date=2026-04-17, lag_days=14
```

SHV + BIL = `cash_anchor` cluster members
(`core/research/risk_cluster_map.py:299-300`). Trial 9 spec is NOT
cap_aware_cross_asset (it's `beta_spy_60d + max_dd_126d + ret_1d`,
cycle #05 winner) but its harness historical NAV reported
`cash_anchor_weight=10.4%` per CLAUDE.md cycle #05 closeout,
implying the selector legitimately picks BIL/SHV when the composite
factor selects them.

**Risk if not refreshed before Monday**: observe will mark BIL/SHV
positions stale (per CLAUDE.md "Halted / Stale / Missing Data
Valuation" — last valid price marker, no new orders, NAV continues
at stale price + diagnostic flag). NAV will be slightly biased but
attribution will flag stale_pct. NOT a halt.

**Recommendation**: re-fetch ETF daily data before Monday EOD observe.
Specifically `BIL`, `SHV`, and ideally the full universe to verify
no other lags.

### Caveat B — RCMv1 + Cand-2 are aborted (terminal status)

Confirmed via direct status check:
- `rcm_v1_defensive_composite_01`: current_status=`aborted`
- `candidate_2_orthogonal_01`: current_status=`aborted`

Both decided 2026-04-30 per commit `f5fd487` (material data revision
detected by F-PRD v2.1 revalidate; both already legacy_decay_verification
per priority_realign_alpha_first.md).

**Implication**: the daily ritual `forward observe` for two candidates
that I had memorized in `feedback_forward_observation_ritual.md` is
stale. Going forward (post-2026-05-04), the ritual is **Trial 9 only**.
RCMv1 + Cand-2 manifests are still consulted by attention_check as
**NAV anchors** (their TD003-frozen NAV history is valid input; aborted
status only blocks further `observe` mutations, not read-only
NAV-history consumption).

Memory file `feedback_forward_observation_ritual.md` updated this
session.

---

## 3. What was NOT verified (intentionally deferred to Monday)

- **Real `observe` write path on Trial 9**: cannot simulate without
  contaminating production manifest. Trust 24 forward_runner unit tests
  + 32 Phase C-PRD-1 unit tests covering all observe-with-role paths.
- **Real revalidate hash recompute on a non-empty manifest**: same
  reason. Trust 31 attention_report tests + 137 dispatch tests.

These are unavoidable: the only way to fully verify is the actual
Monday observe. Pre-flight is about *preventing* failure modes that
*can* be detected without real data.

---

## 4. Monday 2026-05-04 operational sequence (predicted)

1. User: data fetch for full universe (especially BIL + SHV) post-close
2. User: "数据来了" trigger phrase
3. Me: run readiness on Trial 9 (expect `can_append_now=True`,
   `n_potential_new_tds=1`, `next_expected_td=2026-05-04`)
4. Me: run `forward observe --candidate-id trial9_diversifier_001`
   (expect TD001 appended; source_mix=True since panel mixes polygon
   canonical + yfinance frontier; first hash set computed across all
   4 scopes)
5. Me: write daily ritual log entry
6. Me: commit + push

**Expected first observe output shape**:
```
[forward] observe: appended 1 entries
  TD001 2026-05-04 cum_ret=+X.XX% vs_spy=±X.XX% vs_qqq=±X.XX% max_dd=X.XX%
```

If the output deviates (HALT, exception, multiple entries, missing
hashes), pause and triage before next-day repeat.

---

## 5. References

- Phase C-PRD-1 ship: commit `7dcdf50` + post-ship gaps `60e0dfe` (v1↔v2
  dispatch) + `7dbae10` (attention check)
- Trial 9 source spec: cycle #05 trial `6c745c601a47`
  (`docs/memos/20260501-track_c_cycle_2026-05-01-05_close.md`)
- Diversifier role decision: `docs/memos/20260501-diversifier_role_decision.md`
- Two-stage allocation PRD: `docs/prd/20260501-two_stage_allocation_architecture_prd.md`
- F-PRD operational rule: codex R20 — observe MUST run post-NYSE
  16:15-16:30 ET close
- Forward abort decision: commit `f5fd487` + memo
  `docs/memos/20260430-forward_observation_abort_rcmv1_cand2.md`
