"""Top-K structural analysis for feat-v1 mining run (PRD §7.2 Phase C).

Reads the mining archive for a given lineage and reports:
  1. Lineage summary stats (from archive.lineage_summary)
  2. Top-K by composite_score with full spec + params
  3. Factor-weight family distribution in top-K (which factor families
     dominate post-feat-v1 new registry?)
  4. New-vs-old factor presence: do R01-R05 factors (ret_1d, hl_range
     etc.) actually get non-trivial weights in top specs?
  5. Gate pass/fail tallies: quick / oos / holdout / qqq / robustness
  6. New-vs-old baseline comparison: best trial composite score vs
     archive median

Answers the PRD §7.2 Phase B core questions:
  - unique spec count ↑?
  - top specs break out of old-factor cluster?
  - full-period perf > conservative_default?
  - holdout / OOS alive?

Usage:
  python scripts/feat_v1_topk_analysis.py [--k 10] [--lineage TAG]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.mining.archive import MiningArchive


# ── Factor classification (PRD R01-R05 new vs pre-existing) ──────────────────

NEW_FACTORS_R01_R05 = {
    "ret_1d", "ret_2d", "overnight_ret_1d", "intraday_ret_1d",  # R01
    "hl_range", "dollar_vol_20d",                                # R02
    "vol_20d", "volume_ratio_20d",                               # R02 aliases
    "ret_5d", "dist_52w_high", "rel_spy_5d",                     # R03
}

# Factor family tags — by economic intent
FACTOR_FAMILY = {
    # Production
    "low_vol":              "vol",
    "momentum":             "mom",
    "quality":              "quality",
    "pv_div":               "volume",
    "rel_strength":         "relative",
    "market_trend":         "regime",
    "drawup_from_252d_low": "position",
    # (MultiFactorStrategy uses these names in factor_weights dict)
}


def classify_weight_dict(weights: dict) -> dict:
    """Aggregate weight → factor family sums."""
    family_sum = defaultdict(float)
    for k, w in weights.items():
        fam = FACTOR_FAMILY.get(k, "other")
        family_sum[fam] += abs(w)
    return dict(family_sum)


def parse_factor_weights(params: dict) -> dict:
    """Extract factor_weights dict from trial params (MultiFactorSpace
    emits w_<factor> keys; strip prefix for readability)."""
    out = {}
    for k, v in params.items():
        if k.startswith("w_"):
            # Use removeprefix to avoid bug where replace eats both w_ occurrences
            out[k.removeprefix("w_")] = v
    return out


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, default=10,
                        help="Top-K to analyze (default 10)")
    parser.add_argument("--lineage", default="post-2026-04-23-feat-v1-expanded",
                        help="lineage_tag to filter on")
    parser.add_argument("--archive-db", default="data/mining/archive.db")
    args = parser.parse_args()

    arch = MiningArchive(args.archive_db)
    print("=== Lineage summary ===")
    summary = arch.lineage_summary()
    lin_row = summary[summary["lineage_tag"] == args.lineage]
    if lin_row.empty:
        print(f"NO TRIALS for lineage {args.lineage}")
        print(f"Available lineages:")
        for tag in summary["lineage_tag"].tolist():
            print(f"  {tag}")
        return 1
    print(lin_row.to_string(index=False))

    # Pull top-K
    conn = arch._connect()
    rows = conn.execute("""
        SELECT spec_id, tier, composite_score,
               quick_sharpe, quick_cagr, quick_max_dd,
               oos_ir, oos_pass_rate, oos_sharpe, oos_excess_return,
               passed_quick, passed_oos, passed_holdout, passed_qqq_gate,
               regime_robust, cost_robust, param_robust, stress_passed,
               qqq_full_period_excess, qqq_holdout_excess, qqq_oos_avg_excess,
               params_json
        FROM trials
        WHERE lineage_tag = ?
        ORDER BY composite_score DESC
        LIMIT ?
    """, (args.lineage, args.k)).fetchall()
    conn.close()

    if not rows:
        print(f"No trials in top-K for lineage {args.lineage}")
        return 1

    # ── Gate pass tallies ─────────────────────────────────────────────────
    print(f"\n=== Gate pass tallies (top {args.k}) ===")
    n = len(rows)
    gate_names = [
        "passed_quick", "passed_oos", "passed_holdout", "passed_qqq_gate",
        "regime_robust", "cost_robust", "param_robust", "stress_passed",
    ]
    gate_cols = {g: i for i, g in enumerate(
        ["spec_id", "tier", "composite_score",
         "quick_sharpe", "quick_cagr", "quick_max_dd",
         "oos_ir", "oos_pass_rate", "oos_sharpe", "oos_excess_return",
         "passed_quick", "passed_oos", "passed_holdout", "passed_qqq_gate",
         "regime_robust", "cost_robust", "param_robust", "stress_passed",
         "qqq_full_period_excess", "qqq_holdout_excess", "qqq_oos_avg_excess",
         "params_json"]
    )}
    for g in gate_names:
        passed = sum(1 for r in rows if r[gate_cols[g]] == 1)
        print(f"  {g:<18}: {passed}/{n}")

    # ── Top row details ───────────────────────────────────────────────────
    print(f"\n=== Top {min(5, args.k)} detailed ===")
    for i, r in enumerate(rows[:5]):
        print(f"\n--- #{i+1}  {r[0]} (tier {r[1]}) ---")
        print(f"  composite_score: {r[2]:.3f}")
        print(f"  quick: sharpe={r[3]:.3f} cagr={r[4]:.3%} mdd={r[5]:.3%}")
        print(f"  oos:   ir={r[6]:.3f} pass_rate={r[7]:.3f} sharpe={r[8]:.3f} excess={r[9]:.3%}")
        print(f"  passed: q={r[10]} oos={r[11]} holdout={r[12]} qqq={r[13]}")
        print(f"  robust: regime={r[14]} cost={r[15]} param={r[16]} stress={r[17]}")
        qfull = r[18] if r[18] is not None else float("nan")
        qhold = r[19] if r[19] is not None else float("nan")
        qoos = r[20] if r[20] is not None else float("nan")
        print(f"  qqq excess: full={qfull:+.2%} hold={qhold:+.2%} oos_avg={qoos:+.2%}")
        params = json.loads(r[21])
        fw = parse_factor_weights(params)
        print(f"  factor_weights: {fw}")
        meta = {k: v for k, v in params.items() if not k.startswith("w_")}
        print(f"  meta: {meta}")

    # ── Family distribution across top-K ──────────────────────────────────
    print(f"\n=== Factor-family weight share (top {args.k}, mean across trials) ===")
    family_totals = defaultdict(list)
    for r in rows:
        params = json.loads(r[21])
        fw = parse_factor_weights(params)
        fam = classify_weight_dict(fw)
        total_mass = sum(fam.values())
        if total_mass == 0:
            continue
        for family, weight in fam.items():
            family_totals[family].append(weight / total_mass)
    print(f"  {'family':<15} {'mean_share':>12} {'trials':>8}")
    for family in sorted(family_totals, key=lambda f: -sum(family_totals[f]) / len(family_totals[f])):
        shares = family_totals[family]
        print(f"  {family:<15} {sum(shares)/len(shares):>12.3f} {len(shares):>8}")

    # ── New-factor presence in top-K ─────────────────────────────────────
    # NB: MultiFactorStrategy currently only supports PRODUCTION_FACTORS as
    # factor_weights keys. New R01-R05 factors are RESEARCH-only — they don't
    # appear in mining factor_weights. This section is forward-looking (for
    # future rounds where new factors are promoted).
    print(f"\n=== R01-R05 new-factor presence (forward-looking) ===")
    print("  (MultiFactorStrategy currently only accepts PRODUCTION_FACTORS")
    print("   in factor_weights; R01-R05 are RESEARCH-only. Presence here is")
    print("   expected to be 0 until a new factor is promoted per")
    print("   docs/20260421-promotion_flow.md.)")
    new_weight_count = defaultdict(int)
    for r in rows:
        params = json.loads(r[21])
        fw = parse_factor_weights(params)
        for nf in NEW_FACTORS_R01_R05:
            if fw.get(nf, 0) != 0:
                new_weight_count[nf] += 1
    if new_weight_count:
        for nf, c in new_weight_count.items():
            print(f"    {nf}: {c}/{n} trials")
    else:
        print(f"    (no R01-R05 factors in any top-{args.k} spec, as expected)")

    # ── Pre-PRD comparison ───────────────────────────────────────────────
    print(f"\n=== Compare vs pre-PRD lineages ===")
    conn = arch._connect()
    other_lins = conn.execute("""
        SELECT DISTINCT lineage_tag FROM trials
        WHERE lineage_tag != ? AND lineage_tag LIKE 'post-2026%'
        ORDER BY lineage_tag
    """, (args.lineage,)).fetchall()
    for (lin,) in other_lins:
        row = conn.execute("""
            SELECT COUNT(*), AVG(composite_score), MAX(composite_score),
                   SUM(CASE WHEN passed_oos=1 THEN 1 ELSE 0 END)
            FROM trials WHERE lineage_tag = ?
        """, (lin,)).fetchone()
        n_t, avg_s, max_s, n_oos = row
        print(f"  {lin:<45} n={n_t:>3}  avg={avg_s or 0:>+9.3f}  "
              f"max={max_s or 0:>+9.3f}  oos_pass={n_oos}")
    conn.close()

    print("\n=== DONE ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
