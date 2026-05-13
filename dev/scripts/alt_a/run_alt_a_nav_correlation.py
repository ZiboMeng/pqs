"""Phase 3 Step D: alt-A NAV correlation vs RCMv1 / Cand-2 / Trial 9 v2.

Reconstructs anchor NAVs (RCMv1, Cand-2, Trial 9) using their frozen
composite specs via evaluate_composite_spec on the alt-A 53-stock ×
2018-2025 panel. Then correlates each pair against alt-A NAV.

Anchor specs (per trial3_nav_correlation.py + frozen yaml files):
  RCMv1   : beta_spy_60d / drawup_from_252d_low / days_since_52w_high /
            amihud_20d (4 features, equal-weight, global_top_n, monthly)
  Cand-2  : ret_5d / rs_vs_spy_126d / hl_range (equal-weight,
            global_top_n, monthly)
  Trial 9 : beta_spy_60d / max_dd_126d / ret_1d (equal-weight, cap_aware,
            monthly) — v1 is completed_fail, v2 is active forward
            with same composite per docs/memos/20260512-trial9_diversifier_001_closeout.md

Hard gates per PRD: pairwise raw Pearson < 0.85; residual (vs SPY) < 0.50.
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
from core.factors.factor_generator import generate_all_factors
from core.mining.research_miner import ResearchCompositeSpec
from core.research.harness import HarnessConfig, evaluate_composite_spec
from core.research.risk_cluster_map import STOCK_RISK_CLUSTER_MAP


ANCHOR_SPECS = {
    "rcm_v1_defensive_composite_01": {
        "features": ["beta_spy_60d", "drawup_from_252d_low",
                     "days_since_52w_high", "amihud_20d"],
        "weights": (0.25, 0.25, 0.25, 0.25),  # equal-weight per spec yaml
        "construction_mode": "global_top_n",
    },
    "candidate_2_orthogonal_01": {
        "features": ["ret_5d", "rs_vs_spy_126d", "hl_range"],
        "weights": (1/3, 1/3, 1/3),
        "construction_mode": "global_top_n",
    },
    "trial9_diversifier_002": {
        "features": ["beta_spy_60d", "max_dd_126d", "ret_1d"],
        "weights": (1/3, 1/3, 1/3),
        "construction_mode": "cap_aware",
    },
}

ALT_A_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "PWR", "WMT", "GILD",
    "JNJ", "VZ", "OXY", "GIS", "WEC", "EA", "ED", "DG", "CLX", "GS", "MS", "C",
    "LRCX", "KLAC", "CAT", "MU", "AVGO", "TER", "TJX", "TKO", "TRGP", "TRV",
    "TSN", "TT", "TXN", "UNP", "VICI", "COST", "AXP", "BKNG", "APD", "ABT",
    "CMG", "COP", "UNH", "LLY", "ISRG", "NEE", "MCK", "CME", "TMO", "A", "ACGL",
]


def _residual_corr(a: pd.Series, b: pd.Series, bench: pd.Series) -> dict:
    """Raw + bench-residual Pearson correlation of daily returns."""
    common = a.index.intersection(b.index)
    if len(common) < 20:
        return {"raw": None, "residual": None, "n_overlap": len(common)}
    a_ret = a.loc[common].pct_change().dropna()
    b_ret = b.loc[common].pct_change().dropna()
    s_ret = bench.reindex(common).pct_change().dropna()
    common2 = a_ret.index.intersection(b_ret.index).intersection(s_ret.index)
    if len(common2) < 20:
        return {"raw": None, "residual": None, "n_overlap": len(common2)}
    av, bv, sv = a_ret.loc[common2].values, b_ret.loc[common2].values, s_ret.loc[common2].values
    raw = float(np.corrcoef(av, bv)[0, 1])
    if np.std(sv) > 0:
        ba = np.cov(av, sv)[0, 1] / np.var(sv)
        bb = np.cov(bv, sv)[0, 1] / np.var(sv)
        ra = av - ba * sv
        rb = bv - bb * sv
        residual = float(np.corrcoef(ra, rb)[0, 1])
    else:
        residual = None
    return {"raw": raw, "residual": residual, "n_overlap": len(common2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--alt-a-nav",
                    default=str(PROJ / "data/audit/alt_a_phase3_nav.parquet"))
    ap.add_argument("--out",
                    default=str(PROJ / "data/audit/alt_a_phase3_anti_sibling.json"))
    args = ap.parse_args()

    # Load alt-A NAV
    nav_df = pd.read_parquet(args.alt_a_nav)
    alt_a_nav = nav_df["equity"]
    print(f"alt-A NAV: {len(alt_a_nav)} bars")
    start = alt_a_nav.index[0].strftime("%Y-%m-%d")
    end = alt_a_nav.index[-1].strftime("%Y-%m-%d")

    # Load panel for anchor NAV reconstruction (need warmup for factor computation)
    cfg = load_config(PROJ / "config")
    store = BarStore(root=Path(cfg.system.paths.data_dir))
    warmup = (pd.Timestamp(start) - pd.Timedelta(days=400)).strftime("%Y-%m-%d")

    # Add SPY/QQQ to universe for harness benchmarks
    syms = list(ALT_A_UNIVERSE) + ["SPY", "QQQ"]
    daily_close, daily_vol, daily_open, daily_high, daily_low = {}, {}, {}, {}, {}
    for sym in syms:
        try:
            df = store.load(sym, freq="1d", adjusted=True)
        except Exception:
            continue
        if df is None or df.empty:
            continue
        df.index = pd.to_datetime(df.index)
        df = df[(df.index >= warmup) & (df.index <= end)]
        daily_close[sym] = df["close"]
        daily_vol[sym] = df.get("volume", pd.Series(0, index=df.index))
        daily_open[sym] = df.get("open", df["close"])
        daily_high[sym] = df.get("high", df["close"])
        daily_low[sym] = df.get("low", df["close"])
    close = pd.DataFrame(daily_close).sort_index()
    vol = pd.DataFrame(daily_vol).reindex(close.index)
    opn = pd.DataFrame(daily_open).reindex(close.index)
    high = pd.DataFrame(daily_high).reindex(close.index)
    low = pd.DataFrame(daily_low).reindex(close.index)
    print(f"Panel: {close.shape}")

    spy = close.get("SPY"); qqq = close.get("QQQ")

    print("Computing factors for anchor reconstruction...")
    factors = generate_all_factors(close, volume_df=vol, open_df=opn,
                                    high_df=high, low_df=low)
    print(f"  {len(factors)} factors generated")

    # Reconstruct each anchor NAV
    results = {}
    for anchor_id, spec_info in ANCHOR_SPECS.items():
        feats = spec_info["features"]
        weights = spec_info["weights"]
        mode = spec_info["construction_mode"]
        missing = [f for f in feats if f not in factors]
        if missing:
            print(f"⚠ {anchor_id}: missing factors {missing} — skipping")
            results[anchor_id] = {"status": "missing_factors", "missing": missing}
            continue

        panel_map = {f: factors[f] for f in feats}

        # Build HarnessConfig per anchor's mode
        if mode == "cap_aware":
            hc = HarnessConfig(
                construction_mode="cap_aware",
                rebalance_cadence="monthly",
                top_n=10, cluster_cap=0.20, max_single_weight=0.10,
                horizon_days=21,
                cluster_map=STOCK_RISK_CLUSTER_MAP,
            )
        else:
            hc = HarnessConfig(
                construction_mode="global_top_n",
                rebalance_cadence="monthly",
                top_n=10, horizon_days=21,
            )

        spec = ResearchCompositeSpec(
            features=tuple(feats), weights=weights,
            family_counts={"X": len(feats)},
        )

        print(f"Building {anchor_id} NAV (mode={mode})...")
        try:
            res = evaluate_composite_spec(
                spec=spec, factor_panel_map=panel_map,
                price_df=close, open_df=opn,
                spy_series=spy, qqq_series=qqq, config=hc,
            )
            anchor_nav = res.nav
        except Exception as e:
            print(f"  ⚠ {anchor_id}: evaluate_composite_spec failed: {e}")
            results[anchor_id] = {"status": "eval_failed", "error": str(e)}
            continue

        # Restrict to alt-A NAV window for fair correlation
        anchor_nav = anchor_nav.loc[alt_a_nav.index[0]:alt_a_nav.index[-1]]
        print(f"  Anchor NAV: n={len(anchor_nav)}, range {anchor_nav.index[0]} → {anchor_nav.index[-1]}")

        # Correlation
        corr = _residual_corr(alt_a_nav, anchor_nav, spy)
        r = corr["raw"]; res_p = corr["residual"]
        if r is not None:
            verdict = "PASS" if (abs(r) < 0.85 and (res_p is None or abs(res_p) < 0.50)) else "FAIL"
            res_str = f"{res_p:+.3f}" if res_p is not None else "N/A"
            print(f"  {verdict}: raw={r:+.3f}  residual_vs_spy={res_str}  n={corr['n_overlap']}")
        else:
            print(f"  ⚠ insufficient overlap: n={corr.get('n_overlap')}")
            verdict = "INSUFFICIENT_DATA"

        results[anchor_id] = {
            "status": "ok",
            "verdict": verdict,
            "raw_pearson": r,
            "residual_pearson_vs_spy": res_p,
            "n_overlap_days": corr.get("n_overlap"),
            "spec": {
                "features": feats,
                "weights": list(weights),
                "construction_mode": mode,
            },
        }

    # Verdict logic
    fail_anchors = [k for k, v in results.items() if v.get("verdict") == "FAIL"]
    pass_anchors = [k for k, v in results.items() if v.get("verdict") == "PASS"]
    overall = "PASS" if not fail_anchors and pass_anchors else "FAIL"
    print(f"\n=== Step D Verdict: {overall} ===")
    print(f"  Pass: {pass_anchors}")
    print(f"  Fail: {fail_anchors}")

    payload = {
        "lineage": "alt-archetype-intraday-reversal-2026-05-12",
        "phase": "Phase 3 Step D",
        "alt_a_nav_window": [start, end],
        "thresholds": {"raw_pearson_max": 0.85, "residual_pearson_max": 0.50},
        "overall_verdict": overall,
        "results": results,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, indent=2, default=str))
    print(f"\nSaved: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
