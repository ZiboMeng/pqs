#!/usr/bin/env python3
"""LLM-Round 3 tool: deep check for LLM candidates (OOS walk-forward +
regime + time-quartile stratification).

Implements the validation stages that the standard funnel CLI
(`scripts/llm_factor_propose.py`) does NOT cover:

  - OOS walk-forward: non-overlapping 3-month windows
  - Regime stratification: 6 regime IC per factor
  - Time-quartile stratification (§5.4 reverse review)

This is the tool that moves a candidate from "IC screen passed" to
"NEEDS_HUMAN_REVIEW" (per PRD §5.4). LLM still never makes the final
keep decision — this tool produces structured evidence for a human.

Usage
-----
    python scripts/llm_candidate_deep_check.py \\
        --candidate research/llm_candidates/round_01/drawup_from_252d_low.yaml \\
        --universe-size 30 \\
        --start 2018-01-01

Exit codes: 0 = PASS reverse review, 3 = FAIL, 2 = infra error
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from core.config.loader import load_config
from core.data.market_data_store import MarketDataStore
from core.factors.llm_candidate import load_candidate_from_yaml
from core.logging_setup import get_logger, setup_logging
from core.regime.regime_detector import RegimeDetector

setup_logging()
logger = get_logger("llm_candidate_deep_check")


def _resolve_compute_fn(path: str):
    module_name, func_name = path.split(":", 1)
    mod = importlib.import_module(module_name)
    return getattr(mod, func_name)


def _load_universe_prices(cfg, universe_size: int, start: str) -> pd.DataFrame:
    """Load close prices for top-N universe symbols from start date."""
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))
    uni = cfg.universe
    all_syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs) +
        list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    symbols = [s for s in all_syms
               if s not in uni.blacklist and s not in uni.macro_reference]
    pf = {}
    for s in symbols[:universe_size]:
        df = store.read(s, "1d")
        if df is not None and not df.empty and "close" in df.columns:
            pf[s] = df["close"]
    price_df = pd.DataFrame(pf).sort_index()
    price_df = price_df.loc[price_df.index >= start]
    return price_df


def _load_macro(cfg, index: pd.DatetimeIndex) -> Dict[str, pd.Series]:
    """Load SPY + VIX + TNX for regime classification, reindexed onto
    the factor panel's date index."""
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))
    out = {}
    for sym, key in [("SPY", "spy"), ("^VIX", "vix"), ("^TNX", "tnx")]:
        df = store.read(sym, "1d")
        if df is not None and not df.empty:
            out[key] = df["close"].reindex(index).ffill()
    return out


def _compute_ic_series(
    factor_df: pd.DataFrame, fwd: pd.DataFrame,
) -> pd.Series:
    """Per-date cross-sectional Spearman rank IC of factor vs forward
    21d return. Returns series indexed by date (NaN for dates with <5
    common symbols)."""
    ic_vals = {}
    for date in factor_df.index:
        if date not in fwd.index:
            continue
        c_row = factor_df.loc[date].dropna()
        f_row = fwd.loc[date].dropna()
        common = c_row.index.intersection(f_row.index)
        if len(common) < 5:
            continue
        rho = c_row.loc[common].rank().corr(
            f_row.loc[common].rank(), method="pearson")
        if not np.isnan(rho):
            ic_vals[date] = float(rho)
    return pd.Series(ic_vals).sort_index()


def _walk_forward(ic: pd.Series, window_months: int = 3) -> List[Dict]:
    """Non-overlapping walk-forward: split IC series into windows of
    window_months length; compute per-window mean/std/IR/n."""
    out = []
    if ic.empty:
        return out
    start = ic.index.min()
    end = ic.index.max()
    cur = start
    while cur < end:
        win_end = cur + pd.DateOffset(months=window_months)
        win_ic = ic.loc[cur:win_end]
        win_ic = win_ic.iloc[:-1] if len(win_ic) > 0 else win_ic
        if len(win_ic) >= 10:
            mu = float(win_ic.mean())
            sd = float(win_ic.std(ddof=1)) if len(win_ic) > 1 else 0.0
            ir = mu / sd if sd > 1e-10 else 0.0
            out.append({
                "start": cur.date().isoformat(),
                "end":   win_end.date().isoformat(),
                "n":     int(len(win_ic)),
                "mean":  round(mu, 5),
                "std":   round(sd, 5),
                "ir":    round(ir, 3),
            })
        cur = win_end
    return out


def _regime_ic(
    ic: pd.Series, regime_series: pd.Series,
) -> Dict[str, Dict]:
    """Per-regime IC mean + n."""
    out = {}
    for reg, idx in regime_series.groupby(regime_series).groups.items():
        reg_ic = ic.reindex(idx).dropna()
        if len(reg_ic) < 10:
            out[str(reg)] = {"n": int(len(reg_ic)), "mean": None}
            continue
        mu = float(reg_ic.mean())
        sd = float(reg_ic.std(ddof=1)) if len(reg_ic) > 1 else 0.0
        out[str(reg)] = {
            "n":    int(len(reg_ic)),
            "mean": round(mu, 5),
            "std":  round(sd, 5),
            "ir":   round(mu / sd, 3) if sd > 1e-10 else 0.0,
        }
    return out


def _quartile_ic(ic: pd.Series) -> Dict[str, Dict]:
    """Time-quartile IC (§5.4: >60% IC not from single quartile)."""
    if ic.empty:
        return {}
    n = len(ic)
    q_edges = [0, n // 4, n // 2, 3 * n // 4, n]
    out = {}
    for i, (a, b) in enumerate(zip(q_edges[:-1], q_edges[1:])):
        window = ic.iloc[a:b]
        mu = float(window.mean())
        out[f"Q{i+1}"] = {
            "n":    int(len(window)),
            "start": window.index.min().date().isoformat() if len(window) else None,
            "end":   window.index.max().date().isoformat() if len(window) else None,
            "mean": round(mu, 5),
        }
    return out


def _reverse_review(
    full_ic_stats: Dict, wf: List[Dict], reg_ic: Dict,
    q_ic: Dict, sign_tolerant: bool = True,
) -> Dict:
    """§5.4 reverse review. Returns dict with pass/fail per criterion.

    sign_tolerant=True means |mean IC| and positive-rate checks consider
    absolute values — a stable negative-IC factor (e.g., a mean-reverter)
    is treated equivalently to a stable positive-IC factor since composite
    can invert sign.
    """
    check = {}
    # 1. OOS IR stable: mean of per-window IR has correct sign and |mean|>0.3
    ir_list = [w["ir"] for w in wf]
    oos_mean_ir = float(np.mean(ir_list)) if ir_list else 0.0
    check["oos_walk_forward_mean_ir"] = round(oos_mean_ir, 3)
    check["oos_walk_forward_pass"] = abs(oos_mean_ir) >= 0.3

    # 2. Regime robustness: IC correct sign in ≥3 of 6 regimes
    sign_target = np.sign(full_ic_stats["mean"])
    regime_hits = 0
    regime_total = 0
    for r, s in reg_ic.items():
        if s.get("mean") is None:
            continue
        regime_total += 1
        if sign_target == 0 or np.sign(s["mean"]) == sign_target:
            regime_hits += 1
    check["regime_correct_sign_count"] = f"{regime_hits}/{regime_total}"
    check["regime_pass"] = regime_hits >= 3

    # 3. Time quartile stability: no single quartile contributes >60% of abs IC
    if q_ic and full_ic_stats["mean"] != 0:
        abs_total = sum(abs(q["mean"]) for q in q_ic.values())
        if abs_total > 0:
            max_frac = max(abs(q["mean"]) / abs_total for q in q_ic.values())
            check["quartile_max_contribution"] = round(max_frac, 3)
            check["quartile_pass"] = max_frac < 0.6
        else:
            check["quartile_max_contribution"] = None
            check["quartile_pass"] = False
    else:
        check["quartile_max_contribution"] = None
        check["quartile_pass"] = False

    # Overall: all three must pass
    check["overall_pass"] = (
        check["oos_walk_forward_pass"]
        and check["regime_pass"] and check["quartile_pass"]
    )
    return check


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True,
                        help="Path to candidate YAML")
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--universe-size", type=int, default=30)
    parser.add_argument("--start", default="2018-01-01",
                        help="Start date for price panel")
    parser.add_argument("--forward-days", type=int, default=21)
    parser.add_argument("--out-dir", default="data/ml/llm_deep_checks")
    args = parser.parse_args()

    # Load candidate
    cand = load_candidate_from_yaml(args.candidate)
    logger.info("Candidate: %s", cand.factor_name)
    if not cand.compute_fn_path:
        logger.error("Candidate has no compute_fn_path — cannot deep check")
        sys.exit(2)
    compute_fn = _resolve_compute_fn(cand.compute_fn_path)

    # Load data
    cfg = load_config(Path(args.config_dir))
    price_df = _load_universe_prices(cfg, args.universe_size, args.start)
    logger.info("Price panel: %s", price_df.shape)

    # Compute factor + forward return
    factor_df = compute_fn(price_df)
    if factor_df.empty:
        logger.error("compute_fn returned empty DataFrame")
        sys.exit(2)
    fwd = price_df.pct_change(args.forward_days).shift(-args.forward_days)

    # Full-period IC
    full_ic = _compute_ic_series(factor_df, fwd)
    if full_ic.empty:
        logger.error("IC series empty — cannot validate")
        sys.exit(2)
    full_ic_stats = {
        "n":     int(len(full_ic)),
        "mean":  float(full_ic.mean()),
        "std":   float(full_ic.std(ddof=1)) if len(full_ic) > 1 else 0.0,
        "ir":    float(full_ic.mean() / full_ic.std(ddof=1))
                 if full_ic.std(ddof=1) > 1e-10 else 0.0,
        "start": full_ic.index.min().date().isoformat(),
        "end":   full_ic.index.max().date().isoformat(),
    }
    for k in ("mean", "std", "ir"):
        full_ic_stats[k] = round(full_ic_stats[k], 5)

    # Walk-forward
    wf = _walk_forward(full_ic, window_months=3)
    logger.info("Walk-forward windows: %d", len(wf))

    # Regime classification
    macro = _load_macro(cfg, price_df.index)
    detector = RegimeDetector(cfg.regime)
    regime_series = detector.classify_series(
        macro["spy"], macro["vix"], macro.get("tnx"),
    )
    reg_ic = _regime_ic(full_ic, regime_series.reindex(full_ic.index).ffill())
    logger.info("Regimes found: %s", list(reg_ic.keys()))

    # Quartile
    q_ic = _quartile_ic(full_ic)

    # Reverse review
    review = _reverse_review(full_ic_stats, wf, reg_ic, q_ic)

    # Persist artifacts
    out_dir = Path(args.out_dir) / cand.factor_name
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "factor_name":      cand.factor_name,
        "universe_size":    args.universe_size,
        "start":            args.start,
        "forward_days":     args.forward_days,
        "full_ic":          full_ic_stats,
        "walk_forward":     wf,
        "regime_ic":        reg_ic,
        "quartile_ic":      q_ic,
        "reverse_review":   review,
        "candidate":        asdict(cand),
    }
    (out_dir / "deep_check.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False)
    )

    # Pretty print
    print()
    print("=" * 74)
    print(f"Factor: {cand.factor_name}")
    print(f"Universe: {args.universe_size} symbols | "
          f"{full_ic_stats['start']} → {full_ic_stats['end']} | "
          f"N_dates={full_ic_stats['n']}")
    print(f"Full IC: mean={full_ic_stats['mean']:+.4f}  "
          f"IR={full_ic_stats['ir']:+.3f}")
    print()
    print(f"Walk-forward ({len(wf)} windows, 3mo each):")
    for w in wf:
        print(f"  {w['start']} .. {w['end']}  n={w['n']:>3}  "
              f"mean={w['mean']:+.4f}  IR={w['ir']:+.2f}")
    print()
    print("Regime IC:")
    for reg, s in reg_ic.items():
        if s.get("mean") is None:
            print(f"  {reg:<10}  n={s['n']:>3}  (insufficient)")
        else:
            print(f"  {reg:<10}  n={s['n']:>3}  mean={s['mean']:+.4f}  "
                  f"IR={s['ir']:+.2f}")
    print()
    print("Time quartile IC:")
    for q, s in q_ic.items():
        print(f"  {q}: {s['start']} → {s['end']}  mean={s['mean']:+.4f}")
    print()
    print("─" * 74)
    print("§5.4 Reverse review:")
    print(f"  OOS walk-forward mean IR : {review['oos_walk_forward_mean_ir']:+.3f}  "
          f"→ {'PASS' if review['oos_walk_forward_pass'] else 'FAIL'}")
    print(f"  Regime correct-sign count: {review['regime_correct_sign_count']}  "
          f"→ {'PASS' if review['regime_pass'] else 'FAIL'}")
    print(f"  Quartile max contribution: "
          f"{review['quartile_max_contribution']}  "
          f"→ {'PASS' if review['quartile_pass'] else 'FAIL'}")
    print(f"  OVERALL                  : "
          f"{'PASS (NEEDS_HUMAN_REVIEW)' if review['overall_pass'] else 'FAIL (ARCHIVE)'}")
    print("=" * 74)
    print(f"Artifacts: {out_dir}")

    sys.exit(0 if review["overall_pass"] else 3)


if __name__ == "__main__":
    main()
