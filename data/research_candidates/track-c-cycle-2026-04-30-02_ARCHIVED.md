# Cycle #02 ARCHIVE STATUS — RESULTS NOT RELIABLE

**Archived**: 2026-05-01 by operator under user direction
**Lineage**: `track-c-cycle-2026-04-30-02`
**Yaml sha256**: `492a72b115d661f5a08caddbb2d57c643abbcd30d836ed1e22ec5ea49105c42c` (FROZEN; do NOT modify the yaml — it would break the archive's audit chain)

---

## Why this cycle is archived

Cycle #02 mining ran on `data/daily/<sym>.parquet` that contained **heterogeneous split-adjustment corruption** in 13 of 78 universe symbols (NVDA, TSLA, META, GOOGL, AMZN, AVGO, LRCX, SOXL, TQQQ, BKNG, CMG, ISRG, NEE). Same-symbol bars on consecutive days alternated between two split-adjustment scales — e.g. LRCX 2015-04-22 = $6.72, 2015-04-23 = $77.07, 2015-04-24 = $6.57.

The corruption was discovered post-cycle when the Step 1 harness (`core/research/harness/composite_evaluator.py`) was invoked on production prices and produced 10^200-magnitude NAV explosions. Investigation confirmed the issue is in the daily aggregation step of `data/daily/<sym>.parquet`, not in the harness or upstream 1m bars.

Detail: `docs/memos/20260430-heterogeneous_split_audit_scope.md`
Fix:    `docs/memos/20260501-heterogeneous_split_fix_executed.md`

## What is and isn't reliable from this cycle

| Aspect of cycle #02 outcome | Reliability |
|---|---|
| Top-1 composite: `beta_spy_60d + mom_12_1 + volume_ratio_20d` | ✅ DIRECTIONALLY VALID — Same composite emerged in cycle #01 (different horizon, different mining run) → cross-validates the factor selection independent of corruption. Mining IC objective is rank-based and partially robust to scale jumps. |
| Exact IC_IR = 1.0592 | ⚠️ NOT NUMERICALLY REPRODUCIBLE — fresh mining on canonical post-rebuild data WILL produce a different number. Pre-rebuild panel had 3021 rows; post-rebuild 1511 rows for full intersection. |
| Family E/F census = 0/60 | ✅ DIRECTIONALLY VALID — these factors did not appear in mining at all; corruption affected price scale not factor reachability. The C-1 horizon hypothesis (5d → E/F competitive) is robustly refuted. |
| Realized-NAV (cum_ret, sharpe, maxdd, vs_spy, vs_qqq) | ❌ NOT RELIABLE — harness was broken on this data |
| Composite cross-sectional Pearson vs RCMv1/Cand-2 (0.357/0.286) | ⚠️ COMPUTED ON CORRUPTED DATA — directional ordering likely valid (still moderate) but exact values not reproducible |
| R41 Tier-2 sibling-by-construction classification | ✅ VALID — based on factor-level overlap (3-of-3 with cycle #01 top, 1-of-4 with RCMv1), invariant to panel composition |

## What survives as evidence

- **Construction-collapse hypothesis confirmation**: the factor selection emerging at TWO different horizons (cycle #01 21d, cycle #02 5d) on similar-but-corrupted data is the strongest argument for the hypothesis. This is robust to the corruption.
- **Family E/F absence at TWO horizons**: 0/60 archived in both cycles → C-1 horizon-shift hypothesis empirically refuted.
- **Sealed 2026 window UNCONSUMED**: cycle #02 ran on train+validation only; sealed budget intact for future Tier-1 candidate.

## What does NOT survive

- Any "promote-able" candidate from cycle #02 — the realized-NAV gates couldn't be evaluated, so even if the IC_IR=1.0592 trial wasn't a sibling-by-construction it couldn't have been promoted.
- Any cross-cycle correlation or NAV-level diagnostic computed against this cycle's NAV.

## Cycle #03 begins on canonical data

Cycle #03 (`track-c-cycle-2026-05-01-01`) is being launched 2026-05-01 with:
- Canonical post-rebuild `data/daily/<sym>.parquet` (78/78 verified clean)
- Construction axis change: sector-relative top-N (NOT factor pool axis — already exhausted at cycles #01+#02)
- Same temporal split + same factor pool + same anti-sibling discipline

Closeout memo: `docs/memos/20260430-track_c_cycle_2026-04-30-02_close.md` (still authoritative on factor-level outcome; numerical numbers carry the caveat above).

— operator, 2026-05-01
