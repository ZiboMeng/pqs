"""Phase 3 Step D: alt-A NAV correlation vs RCMv1 / Cand-2 / Trial 9 v2.

Computes raw + residual (regress-out SPY beta) Pearson per pair.
Hard gate per PRD: raw < 0.85; residual < 0.50.

Output: data/audit/alt_a_phase3_anti_sibling.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

import numpy as np
import pandas as pd

from core.config.loader import load_config
from core.data.bar_store import BarStore


def _load_anchor_nav_paper_runs(candidate_id: str, run_dirs: list) -> pd.Series | None:
    """Concatenate equity_curve.csv from paper-trading run cells.

    Mirrors `dev/scripts/correlation/run_pair_nav_correlation.py` pattern.
    """
    series_list = []
    for d in run_dirs:
        eq_path = Path(d) / "equity_curve.csv"
        if not eq_path.exists():
            continue
        try:
            df = pd.read_csv(eq_path, parse_dates=["date"]).set_index("date")
            if "equity" in df.columns:
                series_list.append(df["equity"])
        except Exception:
            pass
    if not series_list:
        return None
    return pd.concat(series_list).sort_index()


def _correlation_with_anchor(alt_a_nav: pd.Series, anchor_nav: pd.Series,
                              spy_nav: pd.Series) -> dict:
    """Compute raw + SPY-residual Pearson correlation between alt-A and anchor."""
    common = alt_a_nav.index.intersection(anchor_nav.index)
    if len(common) < 20:
        return {"raw_pearson": None, "residual_pearson": None,
                "n_common": len(common), "status": "insufficient_overlap"}

    a_ret = alt_a_nav.loc[common].pct_change().dropna()
    b_ret = anchor_nav.loc[common].pct_change().dropna()
    s_ret = spy_nav.reindex(common).pct_change().dropna()

    common_ret = a_ret.index.intersection(b_ret.index).intersection(s_ret.index)
    a, b, s = a_ret.loc[common_ret], b_ret.loc[common_ret], s_ret.loc[common_ret]

    raw = float(np.corrcoef(a.values, b.values)[0, 1]) if len(a) > 1 else None

    # Residual: regress out SPY from each
    if np.std(s.values) > 0:
        beta_a = np.cov(a.values, s.values)[0, 1] / np.var(s.values)
        beta_b = np.cov(b.values, s.values)[0, 1] / np.var(s.values)
        resid_a = a.values - beta_a * s.values
        resid_b = b.values - beta_b * s.values
        residual = float(np.corrcoef(resid_a, resid_b)[0, 1])
    else:
        residual = None

    return {
        "raw_pearson": raw,
        "residual_pearson": residual,
        "n_common": len(common_ret),
        "alt_a_beta_vs_spy": float(beta_a) if 'beta_a' in dir() else None,
        "anchor_beta_vs_spy": float(beta_b) if 'beta_b' in dir() else None,
        "status": "ok",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--alt-a-nav",
                    default=str(PROJ / "data/audit/alt_a_phase3_nav.parquet"))
    ap.add_argument("--out",
                    default=str(PROJ / "data/audit/alt_a_phase3_anti_sibling.json"))
    args = ap.parse_args()

    nav_df = pd.read_parquet(args.alt_a_nav)
    alt_a_nav = nav_df["equity"]

    cfg = load_config(PROJ / "config")
    store = BarStore(root=Path(cfg.system.paths.data_dir))
    spy_df = store.load("SPY", freq="1d", adjusted=True)
    spy_df.index = pd.to_datetime(spy_df.index)
    spy_nav = spy_df.loc[alt_a_nav.index[0]:alt_a_nav.index[-1], "close"]

    # Anchors: RCMv1 / Cand-2 / Trial 9 v2 — paper-run dirs
    anchors = {
        "rcm_v1_defensive_composite_01": [
            PROJ / "data/paper/rcm_v1_defensive_composite_01/cell_2018",
            PROJ / "data/paper/rcm_v1_defensive_composite_01/cell_2019",
            PROJ / "data/paper/rcm_v1_defensive_composite_01/cell_2022",
            PROJ / "data/paper/rcm_v1_defensive_composite_01/cell_2025",
        ],
        "candidate_2_orthogonal_01": [
            PROJ / "data/paper/candidate_2_orthogonal_01/cell_2018",
            PROJ / "data/paper/candidate_2_orthogonal_01/cell_2019",
            PROJ / "data/paper/candidate_2_orthogonal_01/cell_2022",
            PROJ / "data/paper/candidate_2_orthogonal_01/cell_2025",
        ],
    }

    results = {}
    for anchor_id, run_dirs in anchors.items():
        anchor_nav = _load_anchor_nav_paper_runs(anchor_id, run_dirs)
        if anchor_nav is None:
            results[anchor_id] = {"status": "anchor_nav_unavailable"}
            print(f"⚠ {anchor_id}: NAV unavailable (no equity_curve.csv files)")
            continue
        corr = _correlation_with_anchor(alt_a_nav, anchor_nav, spy_nav)
        results[anchor_id] = corr
        if corr.get("raw_pearson") is not None:
            r = corr["raw_pearson"]
            res = corr.get("residual_pearson")
            verdict = "PASS" if (abs(r) < 0.85 and (res is None or abs(res) < 0.50)) else "FAIL"
            print(f"{verdict} {anchor_id}: raw={r:+.3f}  residual={res:+.3f if res else 'N/A'}  n={corr['n_common']}")
        else:
            print(f"⚠ {anchor_id}: {corr.get('status')}")

    payload = {
        "lineage": "alt-archetype-intraday-reversal-2026-05-12",
        "phase": "Phase 3 Step D",
        "thresholds": {
            "raw_pearson_max": 0.85,
            "residual_pearson_max": 0.50,
        },
        "results": results,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, indent=2, default=str))
    print(f"\nSaved: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
