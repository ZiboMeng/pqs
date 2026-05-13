"""cycle #09 closeout analysis: 95-factor diversified-anchor search verdict.

Reads top trials from rcm_archive.db (lineage track-c-cycle-2026-05-12-09)
and emits the deliverables required by yaml.hypotheses + hard_blockers
+ stop_rule_post_cycle:

  H1: ≥1 archived trial passes BOTH G_new_family_anchor (≥1 factor from
      G/I/K/L/M/N/O/P) AND G_anti_sibling_nav (raw NAV Pearson < 0.85
      vs RCMv1 / Cand-2 / Trial9_v2 3-way).

  H2: Trials anchored on Z1 strict-train top-15 names produce higher
      median IC_IR than trials anchored outside this set.

  H3: Trials anchored on family K/L/M/N (EDGAR fundamentals) produce
      lower median raw NAV Pearson vs anchors than trials anchored on
      family G/H/I (OHLCV-derived).

  H4: Track A acceptance: among trials passing H1, ≥1 PASS Track A
      (per-validation-year vs SPY ≥ 4/5; per-year max_dd ≤ 20%;
      2025 holdout hard; stress slices ≤ 25%; concentration; beta
      to QQQ ≤ 0.85 diagnostic).

Output: data/audit/cycle09_closeout_analysis.json + stdout summary.

Usage
-----
    python dev/scripts/cycle09/cycle09_closeout_analysis.py
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

import numpy as np
import pandas as pd


LINEAGE = "track-c-cycle-2026-05-12-09"


# Z1 strict-train top-15 by absolute IR (from
# docs/memos/20260512-z1_factor_diagnostics_synthesis_strict.md §2):
Z1_STRICT_TOP_15: Set[str] = {
    "beneish_aqi", "sales_acceleration", "piotroski_no_dilution",
    "rd_intensity_ttm", "mom_126d", "rs_vs_spy_126d",
    "altman_ebit_to_assets", "spy_trend_gated_mom_63d", "magic_roic_ttm",
    "sector_dispersion_std_20d", "ohlson_nitwo", "drawup_from_252d_low",
    "piotroski_current_ratio_yoy_improving", "beneish_depi",
    "altman_sales_to_assets", "buyback_yield_ttm",
}

# Qualifying new-family anchor families per yaml g_new_family_anchor:
QUALIFYING_FAMILIES: Set[str] = {"G", "I", "K", "L", "M", "N", "O", "P"}

# Family membership mapping (from research_miner FAMILIES_V2):
def _build_family_map() -> Dict[str, str]:
    """Return dict[factor_name → family_letter]."""
    from core.mining.research_miner import FAMILIES_V2
    out = {}
    for fam in FAMILIES_V2:
        for fac in fam.factors:
            out[fac] = fam.name
    return out


def _load_archived(archive_db: Path, lineage: str) -> pd.DataFrame:
    conn = sqlite3.connect(archive_db)
    cur = conn.execute(
        """
        SELECT trial_id, ic_ir, objective, n_dates,
               turnover_proxy, corr_concentration,
               nav_sharpe, nav_max_dd,
               nav_correlation_vs_anchor_pooled_raw,
               nav_vs_qqq_excess_full_period,
               benchmark_excess, regime_stddev, spec_json
        FROM rcm_trials
        WHERE lineage_tag=? AND objective IS NOT NULL
        ORDER BY objective DESC
        """,
        (lineage,),
    )
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    conn.close()
    df = pd.DataFrame(rows, columns=cols)
    if df.empty:
        return df
    df["spec_dict"] = df["spec_json"].apply(json.loads)
    df["features"] = df["spec_dict"].apply(lambda d: tuple(d["features"]))
    df["features_str"] = df["features"].apply(lambda f: ",".join(f))
    return df


def _new_family_anchor_check(features: tuple, family_map: Dict[str, str]) -> Dict[str, Any]:
    """Check G_new_family_anchor: ≥1 factor from G/I/K/L/M/N/O/P."""
    factor_families = {f: family_map.get(f, "?") for f in features}
    qualifying_factors = [
        f for f, fam in factor_families.items() if fam in QUALIFYING_FAMILIES
    ]
    return {
        "qualifies": len(qualifying_factors) >= 1,
        "qualifying_factors": qualifying_factors,
        "factor_families": factor_families,
    }


def _z1_anchor_check(features: tuple) -> Dict[str, Any]:
    """Check whether any factor is in Z1 strict-train top-15."""
    z1_factors = [f for f in features if f in Z1_STRICT_TOP_15]
    return {
        "any_z1_top_15": len(z1_factors) >= 1,
        "z1_top_15_factors": z1_factors,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--archive-db", default=str(PROJ / "data/mining/rcm_archive.db"),
    )
    ap.add_argument("--lineage", default=LINEAGE)
    ap.add_argument(
        "--out-json", default=str(PROJ / "data/audit/cycle09_closeout_analysis.json"),
    )
    args = ap.parse_args()

    print(f"Loading archived trials (lineage={args.lineage!r})...")
    df = _load_archived(Path(args.archive_db), args.lineage)
    if df.empty:
        print(f"No archived trials for lineage {args.lineage!r}")
        print("(Possible reasons: mining didn't archive any finite objective; "
              "lineage tag misspelled; mining still running.)")
        return 1

    print(f"  total archived: {len(df)}")

    family_map = _build_family_map()

    # ── H1: G_new_family_anchor presence ──────────────────────────────
    df["nfa"] = df["features"].apply(lambda f: _new_family_anchor_check(f, family_map))
    df["nfa_qualifies"] = df["nfa"].apply(lambda d: d["qualifies"])
    n_nfa_qualifying = int(df["nfa_qualifies"].sum())
    print(f"\nH1 G_new_family_anchor check: {n_nfa_qualifying}/{len(df)} trials qualify")

    # ── Z1 anchor distribution ───────────────────────────────────────
    df["z1"] = df["features"].apply(_z1_anchor_check)
    df["z1_anchored"] = df["z1"].apply(lambda d: d["any_z1_top_15"])
    n_z1 = int(df["z1_anchored"].sum())
    print(f"\nH2 Z1-anchored: {n_z1}/{len(df)} trials include ≥1 Z1 top-15 factor")

    # ── H2: Median IC_IR Z1-anchored vs not ──────────────────────────
    z1_median_ic_ir = df.loc[df["z1_anchored"], "ic_ir"].median() if n_z1 else float("nan")
    nonz1_median_ic_ir = df.loc[~df["z1_anchored"], "ic_ir"].median() if len(df) - n_z1 else float("nan")
    print(f"  Z1-anchored median IC_IR: {z1_median_ic_ir:.4f}")
    print(f"  non-Z1   median IC_IR: {nonz1_median_ic_ir:.4f}")
    h2_supported = (
        not np.isnan(z1_median_ic_ir)
        and not np.isnan(nonz1_median_ic_ir)
        and z1_median_ic_ir > nonz1_median_ic_ir
    )
    print(f"  H2 SUPPORTED: {h2_supported}")

    # ── H3: NAV correlation by anchor family (K/L/M/N vs G/H/I) ──────
    df["anchor_family_class"] = df["nfa"].apply(
        lambda d: (
            "edgar_KLMN" if any(d["factor_families"].get(f) in {"K", "L", "M", "N"} for f in d["qualifying_factors"])
            else "ohlcv_GHI" if any(d["factor_families"].get(f) in {"G", "H", "I"} for f in d["qualifying_factors"])
            else "other"
        )
    )
    klmn_median_corr = df.loc[df["anchor_family_class"] == "edgar_KLMN", "nav_correlation_vs_anchor_pooled_raw"].median()
    ghi_median_corr = df.loc[df["anchor_family_class"] == "ohlcv_GHI", "nav_correlation_vs_anchor_pooled_raw"].median()
    print(f"\nH3 KLMN median anchor pearson: {klmn_median_corr if pd.notna(klmn_median_corr) else 'N/A'}")
    print(f"   GHI  median anchor pearson: {ghi_median_corr if pd.notna(ghi_median_corr) else 'N/A'}")
    h3_supported = (
        pd.notna(klmn_median_corr) and pd.notna(ghi_median_corr)
        and float(klmn_median_corr) < float(ghi_median_corr)
    )
    print(f"   H3 SUPPORTED: {h3_supported}")

    # ── G_anti_sibling_nav rough screening ───────────────────────────
    # (Pooled raw < 0.85 indicates structural NAV diversity from anchors.)
    df["anti_sibling_passes"] = df["nav_correlation_vs_anchor_pooled_raw"].apply(
        lambda v: pd.notna(v) and float(v) < 0.85
    )
    n_anti_sibling = int(df["anti_sibling_passes"].sum())
    print(f"\nG_anti_sibling_nav screen: {n_anti_sibling}/{len(df)} trials pooled-raw < 0.85")

    # ── Combined gate: NFA AND anti-sibling ──────────────────────────
    df["both_gates"] = df["nfa_qualifies"] & df["anti_sibling_passes"]
    n_both = int(df["both_gates"].sum())
    print(f"\nH1+G_anti_sibling combined: {n_both}/{len(df)} trials pass both")

    # ── Top-10 detail ────────────────────────────────────────────────
    print(f"\nTop-10 by objective:")
    top10 = df.head(10)
    for i, (_, r) in enumerate(top10.iterrows(), start=1):
        nfa = r["nfa"]
        fam_letters = [nfa["factor_families"].get(f, "?") for f in r["features"]]
        z1_factors = r["z1"]["z1_top_15_factors"]
        corr = r["nav_correlation_vs_anchor_pooled_raw"]
        print(f"  #{i} obj={r['objective']:+.4f} IR={r['ic_ir']:+.3f} "
              f"sharpe={r['nav_sharpe'] if r['nav_sharpe'] else 'N/A'} "
              f"anchor_pearson={corr if pd.notna(corr) else 'N/A'} "
              f"families={','.join(fam_letters)} "
              f"feats={r['features_str']}"
              + (f" Z1={z1_factors}" if z1_factors else "")
              + (" ✓NFA" if nfa["qualifies"] else " ✗NFA")
              + (" ✓anti-sib" if r["anti_sibling_passes"] else " ✗anti-sib"))

    # ── Verdict per stop_rule_post_cycle ──────────────────────────────
    if n_both == 0:
        verdict = "0_nominee_h1_h4_failed"
        verdict_text = (
            "0 NOMINEE. cycle #09 did not produce a trial passing BOTH "
            "G_new_family_anchor AND G_anti_sibling_nav. SECOND consecutive "
            "0-nominee with broad factor library (cycle08 + cycle09). Per "
            "yaml.stop_rule_post_cycle.if_zero_nominee: pivot to alt-archetype "
            "(intraday reversal / event-driven / cross-asset systematic — PRDs "
            "at docs/prd/20260512-alt_archetype_*.md)."
        )
    else:
        # Need Track A acceptance to declare nominee. Currently scope:
        # script flags candidate trials; Track A evaluator runs separately.
        verdict = "candidate_trials_pending_track_a"
        verdict_text = (
            f"{n_both} candidate trials pass H1 + G_anti_sibling_nav screen. "
            f"Run Track A acceptance evaluator on these trials to declare "
            f"final nominee. Until acceptance confirmed, status = "
            f"'candidates pending evaluation', NOT 'nominee'."
        )

    summary = {
        "lineage": args.lineage,
        "total_archived": len(df),
        "h1_g_new_family_anchor": {
            "qualifying": n_nfa_qualifying,
            "total": len(df),
            "rate": n_nfa_qualifying / len(df) if len(df) else 0.0,
        },
        "g_anti_sibling_nav_screen": {
            "passing": n_anti_sibling,
            "total": len(df),
            "rate": n_anti_sibling / len(df) if len(df) else 0.0,
        },
        "h1_combined_gates": {
            "passing": n_both,
            "total": len(df),
            "rate": n_both / len(df) if len(df) else 0.0,
        },
        "h2_z1_anchored": {
            "z1_anchored_count": n_z1,
            "z1_median_ic_ir": float(z1_median_ic_ir) if pd.notna(z1_median_ic_ir) else None,
            "nonz1_median_ic_ir": float(nonz1_median_ic_ir) if pd.notna(nonz1_median_ic_ir) else None,
            "h2_supported": bool(h2_supported),
        },
        "h3_anchor_family_class": {
            "klmn_median_corr": float(klmn_median_corr) if pd.notna(klmn_median_corr) else None,
            "ghi_median_corr": float(ghi_median_corr) if pd.notna(ghi_median_corr) else None,
            "h3_supported": bool(h3_supported),
        },
        "top10": [
            {
                "trial_id": str(r["trial_id"]),
                "objective": float(r["objective"]),
                "ic_ir": float(r["ic_ir"]) if pd.notna(r["ic_ir"]) else None,
                "nav_sharpe": float(r["nav_sharpe"]) if pd.notna(r["nav_sharpe"]) else None,
                "nav_correlation_vs_anchor_pooled_raw": (
                    float(r["nav_correlation_vs_anchor_pooled_raw"])
                    if pd.notna(r["nav_correlation_vs_anchor_pooled_raw"]) else None
                ),
                "features": list(r["features"]),
                "factor_families": r["nfa"]["factor_families"],
                "nfa_qualifies": bool(r["nfa_qualifies"]),
                "anti_sibling_passes": bool(r["anti_sibling_passes"]),
                "both_gates": bool(r["both_gates"]),
                "z1_factors": r["z1"]["z1_top_15_factors"],
            }
            for _, r in top10.iterrows()
        ],
        "verdict": verdict,
        "verdict_text": verdict_text,
    }

    out_path = Path(args.out_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2))
    print(f"\nWrote: {out_path}")
    print(f"\nVerdict: {verdict}")
    print(f"  {verdict_text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
