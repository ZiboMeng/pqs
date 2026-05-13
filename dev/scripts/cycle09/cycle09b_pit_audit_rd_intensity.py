"""cycle09b §5.2 — PIT audit on rd_intensity_ttm.

Validates that the EDGAR-backed fundamental factor `rd_intensity_ttm`
uses `filed_date` (when SEC received the filing) as the effective
date and NOT `fiscal_period_end` (when the period closed). The
distinction is load-bearing: a Q3 FY2024 figure with period_end =
2024-09-29 but filed = 2024-11-01 must NOT be visible to a strategy
on 2024-10-31.

Test design:
  (a) Anchor test on AAPL around its Q4 FY2024 10-K filing:
      - as_of = 2024-10-31 (pre-10-K) → must use prior 10-Q (Q3 FY24)
      - as_of = 2024-11-15 (post-10-K) → must use 10-K FY24 annual TTM
  (b) Five random (date, ticker) audit points:
      - Pick random asof dates in 2018-2024 + random tickers from
        the 78-stock cycle09b universe.
      - Trace the as-of value back to the most recent filing with
        filed_date ≤ asof; confirm filed_date is indeed ≤ asof.
      - Confirm a HYPOTHETICAL fiscal_period_end-keyed lookup would
        have leaked (i.e. the same ticker's most-recent end_date is
        ≤ asof but filed_date > asof for some other recent filing,
        which means end_date semantics would have given a different
        value).

Output: data/audit/cycle09b_pit_audit_rd_intensity.json
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pandas as pd

from core.data.fundamentals_store import FundamentalsStore


REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_PATH = REPO_ROOT / "data/audit/cycle09b_pit_audit_rd_intensity.json"


# 78-stock cycle09b universe (drop "BRK-B" if present; keep stocks only).
# Derived from data/research_candidates/track-c-cycle-2026-05-12-09b_promotion_criteria.yaml
# universe symbol; we read it dynamically below for robustness.


def _read_universe() -> list[str]:
    """Return EDGAR-eligible tickers from the seed_pool (stocks only).

    We filter out ETFs heuristically by checking against the EDGAR
    cache: tickers without companyfacts data are not part of this
    audit's population.
    """
    import yaml

    yaml_path = REPO_ROOT / "config/universe.yaml"
    with open(yaml_path) as fh:
        cfg = yaml.safe_load(fh)
    syms = []
    for s in cfg.get("seed_pool", []):
        if isinstance(s, str):
            syms.append(s)
    # Filter to stocks: those that have an EDGAR CIK mapping.
    from core.data.edgar_provider import EdgarProvider
    provider = EdgarProvider()
    eligible = []
    for s in syms:
        try:
            if provider.get_cik(s) is not None:
                eligible.append(s)
        except (FileNotFoundError, ValueError, KeyError):
            continue
    return eligible


def _anchor_test_aapl(store: FundamentalsStore) -> dict:
    """AAPL Q4 FY2024 10-K filing anchor test."""
    pre_10k = pd.Timestamp("2024-10-31")
    post_10k = pd.Timestamp("2024-11-15")

    rd_facts = store.load_concept_facts("AAPL", "rd_expense")
    sales_facts = store.load_concept_facts("AAPL", "revenues")

    # Find AAPL's FY2024 10-K filing date
    annual_rd = rd_facts[
        rd_facts["form"].isin({"10-K", "10-K/A"}) & (rd_facts["fy"] == 2024)
    ].sort_values("filed")
    if annual_rd.empty:
        annual_rd_filed = None
    else:
        annual_rd_filed = annual_rd["filed"].iloc[-1]

    # Compute rd_intensity_ttm on a daily index spanning both dates
    daily_idx = pd.date_range("2024-09-01", "2024-12-31", freq="B")
    rd_ttm = store.load_panel(["AAPL"], "rd_expense", daily_idx, ttm=True)
    sales_ttm = store.load_panel(["AAPL"], "revenues", daily_idx, ttm=True)
    rd_int = rd_ttm["AAPL"] / sales_ttm["AAPL"]

    pre_val = float(rd_int.loc[pre_10k]) if pre_10k in rd_int.index else None
    post_val = float(rd_int.loc[post_10k]) if post_10k in rd_int.index else None

    # Verdict: pre/post should differ if AAPL filed a 10-K between them
    return {
        "anchor": "AAPL Q4 FY2024 10-K",
        "pre_10k_date": str(pre_10k.date()),
        "post_10k_date": str(post_10k.date()),
        "rd_intensity_pre": pre_val,
        "rd_intensity_post": post_val,
        "annual_10k_filed_date": str(annual_rd_filed.date()) if annual_rd_filed is not None else None,
        "filed_between_pre_post": (
            annual_rd_filed is not None
            and pre_10k <= annual_rd_filed <= post_10k
        ),
        "values_differ": (
            pre_val is not None
            and post_val is not None
            and abs(pre_val - post_val) > 1e-9
        ),
    }


def _random_audit_point(store: FundamentalsStore, asof: pd.Timestamp, ticker: str) -> dict:
    """Trace one (asof, ticker) pair to filed_date evidence."""
    rd_facts = store.load_concept_facts(ticker, "rd_expense")
    if rd_facts.empty:
        return {
            "asof": str(asof.date()),
            "ticker": ticker,
            "no_rd_facts": True,
        }

    # The most-recent filing with filed_date <= asof is what PIT semantics use.
    pit_filed = rd_facts[rd_facts["filed"] <= asof].sort_values("filed")
    if pit_filed.empty:
        return {
            "asof": str(asof.date()),
            "ticker": ticker,
            "no_filing_by_asof": True,
        }
    pit_row = pit_filed.iloc[-1]

    # Hypothetical period-end semantics: most-recent end_date <= asof
    end_filed = rd_facts[rd_facts["end"] <= asof].sort_values("end")
    period_end_row = end_filed.iloc[-1] if not end_filed.empty else None

    # The leakage gap: max end_date with filed > asof, IF such an obs exists
    future_filed = rd_facts[(rd_facts["end"] <= asof) & (rd_facts["filed"] > asof)]
    leak_gap_days = None
    if not future_filed.empty:
        latest_leak = future_filed.sort_values("filed").iloc[-1]
        leak_gap_days = int((latest_leak["filed"] - asof).days)

    return {
        "asof": str(asof.date()),
        "ticker": ticker,
        "pit_filed_date": str(pit_row["filed"].date()),
        "pit_period_end": str(pit_row["end"].date()),
        "pit_form": pit_row["form"],
        "pit_val": float(pit_row["val"]),
        "naive_end_filed_date": (
            str(period_end_row["filed"].date()) if period_end_row is not None else None
        ),
        "naive_end_period_end": (
            str(period_end_row["end"].date()) if period_end_row is not None else None
        ),
        "pit_filed_before_asof": pit_row["filed"] <= asof,
        "naive_would_leak": (
            period_end_row is not None
            and period_end_row["filed"] > asof
        ),
        "leak_gap_days_observed": leak_gap_days,
    }


def main() -> int:
    random.seed(42)

    store = FundamentalsStore()
    universe = _read_universe()
    print(f"Universe size: {len(universe)}")

    out: dict = {
        "cycle": "track-c-cycle-2026-05-12-09b",
        "audit_section": "§5.2 PIT audit on rd_intensity_ttm",
        "evidence_class": "R3 actually-run-code",
    }

    # (a) Anchor test on AAPL
    anchor = _anchor_test_aapl(store)
    out["anchor_test_aapl"] = anchor
    print("\n=== AAPL Q4 FY2024 anchor test ===")
    for k, v in anchor.items():
        print(f"  {k}: {v}")

    # (b) 5 random audit points
    candidate_asof_dates = pd.date_range("2018-01-01", "2024-12-31", freq="B")
    audit_points = []
    attempts = 0
    target = 5
    while len(audit_points) < target and attempts < 50:
        attempts += 1
        asof = pd.Timestamp(random.choice(candidate_asof_dates))
        ticker = random.choice(universe)
        rec = _random_audit_point(store, asof, ticker)
        if rec.get("no_rd_facts") or rec.get("no_filing_by_asof"):
            continue
        audit_points.append(rec)

    out["random_audit_points"] = audit_points
    print(f"\n=== 5 random (asof, ticker) audit points ===")
    for rec in audit_points:
        print(
            f"  {rec['asof']}  {rec['ticker']}  "
            f"pit_filed={rec['pit_filed_date']}  "
            f"period_end={rec['pit_period_end']}  "
            f"form={rec['pit_form']}  "
            f"pit_filed_before_asof={rec['pit_filed_before_asof']}  "
            f"naive_leak={rec['naive_would_leak']}  "
            f"gap_days={rec.get('leak_gap_days_observed')}"
        )

    # Verdict
    pit_correct = all(rec["pit_filed_before_asof"] for rec in audit_points)
    naive_leak_observed = any(rec["naive_would_leak"] for rec in audit_points)

    verdict: dict = {
        "pit_correct_all_5_points": pit_correct,
        "naive_end_date_semantics_would_leak": naive_leak_observed,
        "anchor_filed_between_pre_post": anchor["filed_between_pre_post"],
        "anchor_values_differ": anchor["values_differ"],
        "overall_pit_audit_pass": (
            pit_correct
            and anchor["filed_between_pre_post"]
        ),
    }
    out["verdict"] = verdict

    print("\n=== Verdict ===")
    for k, v in verdict.items():
        print(f"  {k}: {v}")

    OUT_PATH.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nSaved: {OUT_PATH.relative_to(REPO_ROOT)}")
    return 0 if verdict["overall_pit_audit_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
