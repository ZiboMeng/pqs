#!/usr/bin/env python3
"""R37 — Layer 2 + Layer 3: risk profile + priority buckets.

Consumes:
  - R35/R37 alpha diagnostic (category column)
  - R36 admission screen (tier column)

Produces per-ticker profile with:
  - beta_bucket: LOW (<0.7) / MID (0.7-1.3) / HIGH (>1.3)
  - alpha_label: from diagnostic category
  - sharpe_tier: POOR (<0.3) / FAIR (0.3-0.6) / GOOD (0.6-1.0) / STRONG (>1.0)
  - maxdd_tier: MILD (>-0.3) / MODERATE (-0.3 to -0.5) / SEVERE (<-0.5)
  - admission_tier: CORE / EXTENDED / WATCH / REJECT
  - priority_bucket: CORE_ALPHA / SATELLITE_ALPHA / DIVERSIFIER / REVIEW / EXCLUDE

Writes data/ml/universe_risk_profile_<tag>.csv

Does NOT modify config/universe.yaml. Per section 11.2 the R38 round
produces a proposal; user authorizes universe change.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from core.logging_setup import get_logger, setup_logging

setup_logging()
logger = get_logger("universe_risk_profile")


def _beta_bucket(beta: float) -> str:
    if pd.isna(beta):
        return "UNKNOWN"
    if beta < 0.7:
        return "LOW"
    if beta <= 1.3:
        return "MID"
    return "HIGH"


def _sharpe_tier(sharpe: float) -> str:
    if pd.isna(sharpe):
        return "UNKNOWN"
    if sharpe < 0.3:
        return "POOR"
    if sharpe < 0.6:
        return "FAIR"
    if sharpe < 1.0:
        return "GOOD"
    return "STRONG"


def _maxdd_tier(dd: float) -> str:
    if pd.isna(dd):
        return "UNKNOWN"
    if dd > -0.30:
        return "MILD"
    if dd > -0.50:
        return "MODERATE"
    return "SEVERE"


def _priority_bucket(row) -> str:
    """Layer 3 assignment using admission + alpha category + risk tiers."""
    adm = row.get("admission_tier", "REJECT")
    cat = row.get("category", "UNKNOWN")
    sharpe_t = row.get("sharpe_tier", "UNKNOWN")
    dd_t = row.get("maxdd_tier", "UNKNOWN")

    if adm in ("REJECT",):
        return "EXCLUDE"
    if adm == "WATCH":
        return "REVIEW"
    if cat == "PURE_BETA":
        return "EXCLUDE"
    if cat == "UNKNOWN":
        return "REVIEW"
    if cat in ("ALPHA_GENERATOR", "BETA_PLUS_ALPHA"):
        # Strong alpha + acceptable risk → CORE_ALPHA; weaker → SATELLITE_ALPHA
        if sharpe_t in ("GOOD", "STRONG") and dd_t in ("MILD", "MODERATE"):
            return "CORE_ALPHA"
        return "SATELLITE_ALPHA"
    if cat == "DIVERSIFIER":
        if sharpe_t in ("GOOD", "STRONG"):
            return "DIVERSIFIER_PREMIUM"
        return "DIVERSIFIER_BASIC"
    # MARKET_LIKE
    return "REVIEW"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--alpha-csv", required=True,
                        help="Path to R35/R37 alpha diagnostic CSV")
    parser.add_argument("--admission-csv", required=True,
                        help="Path to R36 admission CSV")
    parser.add_argument("--out-tag", default="R37")
    parser.add_argument("--out-dir", default="data/ml")
    args = parser.parse_args()

    alpha = pd.read_csv(args.alpha_csv)
    admission = pd.read_csv(args.admission_csv)

    logger.info("Alpha rows: %d", len(alpha))
    logger.info("Admission rows: %d", len(admission))

    # Merge on symbol
    admission_lean = admission[["symbol", "tier", "adv60_usd", "liq_persist",
                                "n_days", "reasons"]].rename(columns={
        "tier": "admission_tier",
        "reasons": "admission_reasons",
    })
    df = alpha.merge(admission_lean, on="symbol", how="outer",
                     suffixes=("_alpha", "_adm"))

    # Derive risk labels
    df["beta_bucket"] = df["beta"].apply(_beta_bucket)
    df["sharpe_tier"] = df["sharpe"].apply(_sharpe_tier)
    df["maxdd_tier"] = df["max_dd"].apply(_maxdd_tier)
    df["priority_bucket"] = df.apply(_priority_bucket, axis=1)

    # Core analytics
    bucket_counts = df["priority_bucket"].value_counts()
    category_by_bucket = pd.crosstab(
        df["priority_bucket"], df["category"], margins=True,
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = out_dir / f"universe_risk_profile_{args.out_tag}.csv"
    df.sort_values(["priority_bucket", "symbol"]).to_csv(out_csv, index=False)

    summary = {
        "n_total": int(len(df)),
        "bucket_counts": bucket_counts.to_dict(),
        "core_alpha_symbols": df[df["priority_bucket"] == "CORE_ALPHA"]
            ["symbol"].tolist(),
        "satellite_alpha_symbols": df[df["priority_bucket"] == "SATELLITE_ALPHA"]
            ["symbol"].tolist(),
        "diversifier_premium_symbols": df[
            df["priority_bucket"] == "DIVERSIFIER_PREMIUM"]["symbol"].tolist(),
    }
    (out_dir / f"universe_risk_profile_{args.out_tag}_summary.json"
     ).write_text(json.dumps(summary, indent=2))

    print()
    print("=" * 76)
    print(f"Universe Risk Profile — {args.out_tag}")
    print("=" * 76)
    print(f"Total n: {len(df)}")
    print()
    print("Priority bucket distribution:")
    print(bucket_counts.to_string())
    print()
    print("Cross-tab priority_bucket × alpha category:")
    print(category_by_bucket.to_string())
    print()
    print(f"CORE_ALPHA n={len(summary['core_alpha_symbols'])}")
    core = summary["core_alpha_symbols"]
    if core:
        print(f"  first 25: {core[:25]}")
    print()
    print(f"Artifacts: {out_csv}")
    print(f"           {out_dir}/universe_risk_profile_{args.out_tag}_summary.json")


if __name__ == "__main__":
    main()
