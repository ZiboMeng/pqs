"""Phase A.2 — RSI/KDJ/MACD IC screening on partition_for_role(role='miner').

PRD: docs/prd/20260506-cycle07_to_fleet_master_prd.md §4.1 Phase A.2.

Implements 3 candidate oscillators inline (no production code touched),
computes 21d-horizon Spearman IC time-series per factor cross-section,
and computes IC time-series Pearson correlation against all 67
RESEARCH_FACTORS to surface sibling risk before promotion.

Per-factor verdict (PRD §4.1 acceptance):
  - max IC time-series correlation with existing < 0.6  → ELIGIBLE
  - 0.6 ≤ max correlation ≤ 0.7                          → CONDITIONAL
  - max correlation > 0.7                                → REJECT

OOS discipline: panel is partition_for_role(role='miner') (train years
only); validation + sealed years EXCLUDED.

Usage
-----
    python dev/scripts/factor_screening/run_rsi_kdj_macd_ic_screen.py
    python dev/scripts/factor_screening/run_rsi_kdj_macd_ic_screen.py \
        --out-json data/audit/phase_a2_ic_screening.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

import numpy as np
import pandas as pd

from core.config.loader import load_config
from core.data.bar_store import BarStore
from core.factors.factor_generator import (
    compute_forward_returns,
    generate_all_factors,
)
from core.factors.factor_registry import RESEARCH_FACTORS
from core.mining.research_miner import _spearman_ic_per_date
from core.research.risk_cluster_map import CROSS_ASSET_RISK_CLUSTER_MAP
from core.research.temporal_split import (
    load_temporal_split,
    partition_for_role,
)


# ── Inline candidate factor implementations ────────────────────────────


def rsi_14d(close: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    """Wilder's RSI(14) per symbol.

    RS = avg_gain / avg_loss using Wilder's smoothing (EMA equivalent
    with alpha = 1/n). RSI = 100 - 100/(1+RS).

    Returns NaN until n bars of history are available.
    """
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    # Wilder smoothing: ewm with alpha=1/n, adjust=False mirrors the
    # recurrence avg_t = avg_{t-1} * (n-1)/n + x_t / n.
    avg_gain = gain.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    return rsi


def kdj_9d(
    close: pd.DataFrame, high: pd.DataFrame, low: pd.DataFrame,
    n: int = 9,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Stochastic %K(9) + %D(3 SMA of K) + J = 3K - 2D, per symbol.

    raw_k = 100 * (close - rolling_min(low, n)) / (rolling_max(high, n)
                                                   - rolling_min(low, n))
    K = SMA(raw_k, 3)
    D = SMA(K, 3)
    J = 3 * K - 2 * D

    Returns three same-shape DataFrames. We screen the J line because
    it has the widest range (overshoots 0/100), making it the most
    informative single signal for IC ranking. K and D are kept for
    documentation but not screened.
    """
    lo_n = low.rolling(n, min_periods=n).min()
    hi_n = high.rolling(n, min_periods=n).max()
    rng = (hi_n - lo_n).replace(0, np.nan)
    raw_k = 100.0 * (close - lo_n) / rng
    k = raw_k.rolling(3, min_periods=3).mean()
    d = k.rolling(3, min_periods=3).mean()
    j = 3.0 * k - 2.0 * d
    return k, d, j


def macd_12_26_9(close: pd.DataFrame) -> pd.DataFrame:
    """MACD histogram = (EMA(12) - EMA(26)) - signal-line EMA(9).

    The histogram is the screening target — it reflects rate-of-change
    of the MACD line itself, capturing trend-divergence faster than
    raw MACD. Returns NaN until 26-bar EMA settles.
    """
    ema_fast = close.ewm(span=12, adjust=False, min_periods=12).mean()
    ema_slow = close.ewm(span=26, adjust=False, min_periods=26).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=9, adjust=False, min_periods=9).mean()
    hist = macd_line - signal_line
    return hist


# ── Panel loading (mirror cycle06_track_a_eval.py) ─────────────────────


def _load_panel_miner():
    """Load full universe daily panel + restrict to role='miner' (train
    years only; validation + sealed EXCLUDED per OOS discipline)."""
    cfg = load_config(PROJ / "config")
    store = BarStore(root=Path(cfg.system.paths.data_dir))
    uni = cfg.universe
    syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs)
        + list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    drop = {"BRK-B", "USO", "SLV"}  # cycle06 yaml drop_symbols
    syms = [s for s in syms if s not in uni.blacklist
            and s not in uni.macro_reference and s not in drop]
    for b in ("SPY", "QQQ"):
        if b not in syms:
            syms.append(b)
    cross_asset_set = set(CROSS_ASSET_RISK_CLUSTER_MAP.keys())
    frames = {k: {} for k in ("close", "open", "high", "low", "volume")}
    for sym in syms:
        atr = sym in cross_asset_set
        df = store.load(sym, freq="1d", adjusted=True,
                        adjusted_total_return=atr, fallback="local")
        if df is None or df.empty or "close" not in df.columns:
            continue
        frames["close"][sym] = df["close"]
        for col in ("open", "high", "low", "volume"):
            if col in df.columns:
                frames[col][sym] = df[col]
    panel = {"close": pd.DataFrame(frames["close"]).sort_index()}
    panel["open"] = pd.DataFrame(frames["open"]).reindex_like(panel["close"])
    panel["high"] = pd.DataFrame(frames["high"]).reindex_like(panel["close"])
    panel["low"] = pd.DataFrame(frames["low"]).reindex_like(panel["close"])
    panel["volume"] = pd.DataFrame(frames["volume"]).reindex_like(panel["close"])
    # Drop weekend dates that bleed in from non-equity sources (e.g. crypto
    # cross-listings). pandas rolling(N, min_periods=N).min() fails to
    # produce values when windows contain NaN, so weekend rows would mask
    # KDJ output for the entire equity universe.
    weekday_mask = panel["close"].index.day_of_week < 5
    for k in panel:
        panel[k] = panel[k].loc[weekday_mask]
    split_cfg = load_temporal_split(PROJ / "config" / "temporal_split.yaml")
    panel = partition_for_role(panel, split_cfg, role="miner")
    return panel, split_cfg


# ── IC computation + pairwise correlation ─────────────────────────────


def _ic_series_for_factor(
    factor_panel: pd.DataFrame, fwd_returns: pd.DataFrame,
) -> pd.Series:
    """Wrapper: per-date Spearman IC on (factor, fwd_returns) cross-section."""
    return _spearman_ic_per_date(factor_panel, fwd_returns)


def _verdict(max_abs_corr: float) -> str:
    if max_abs_corr < 0.6:
        return "ELIGIBLE"
    if max_abs_corr <= 0.7:
        return "CONDITIONAL"
    return "REJECT"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out-json",
                    default=str(PROJ / "data/audit/phase_a2_ic_screening.json"))
    ap.add_argument("--horizon", type=int, default=21,
                    help="forward-return horizon in trading days")
    args = ap.parse_args()

    print("Loading miner panel (partition_for_role role='miner')...")
    t0 = time.time()
    panel, split_cfg = _load_panel_miner()
    print(f"  panel: {panel['close'].shape[0]} dates × "
          f"{panel['close'].shape[1]} symbols ({time.time()-t0:.1f}s)")
    train_start = panel["close"].index.min()
    train_end = panel["close"].index.max()
    print(f"  train range: {train_start.date()} → {train_end.date()}")

    print(f"\nComputing forward returns (horizon={args.horizon}d, mode=cc)...")
    fwd_dict = compute_forward_returns(
        panel["close"], horizons=[args.horizon], mode="cc",
    )
    fwd = fwd_dict[args.horizon]
    print(f"  fwd panel: {fwd.shape[0]} dates × {fwd.shape[1]} symbols")

    # Compute candidate factor panels
    print("\nComputing candidate factors (RSI/KDJ-J/MACD-hist)...")
    t0 = time.time()
    rsi = rsi_14d(panel["close"], n=14)
    _k, _d, kdj_j = kdj_9d(panel["close"], panel["high"], panel["low"], n=9)
    macd_hist = macd_12_26_9(panel["close"])
    print(f"  candidates computed in {time.time()-t0:.1f}s; non-NaN bars per "
          f"factor: rsi={rsi.notna().sum().sum()}, kdj_j={kdj_j.notna().sum().sum()}, "
          f"macd_hist={macd_hist.notna().sum().sum()}")

    # Compute existing factors
    print("\nComputing 67 RESEARCH_FACTORS via generate_all_factors...")
    t0 = time.time()
    bench = {b: panel["close"][b] for b in ("SPY", "QQQ")
             if b in panel["close"].columns}
    existing = generate_all_factors(
        panel["close"], volume_df=panel["volume"],
        open_df=panel["open"], high_df=panel["high"], low_df=panel["low"],
        benchmark_map=bench,
    )
    # Keep only RESEARCH_FACTORS names
    existing = {n: existing[n] for n in RESEARCH_FACTORS if n in existing}
    print(f"  existing panels: {len(existing)} ({time.time()-t0:.1f}s)")
    if len(existing) != 67:
        print(f"  WARN: expected 67 existing factor panels, got {len(existing)}")

    # Compute IC time-series per factor (3 candidates + 67 existing)
    print(f"\nComputing IC time-series (horizon={args.horizon}d) per factor...")
    t0 = time.time()
    candidates: Dict[str, pd.DataFrame] = {
        "rsi_14d": rsi, "kdj_j_9d": kdj_j, "macd_hist_12_26_9": macd_hist,
    }
    ics: Dict[str, pd.Series] = {}
    for name, panel_df in candidates.items():
        ics[name] = _ic_series_for_factor(panel_df, fwd)
    for name, panel_df in existing.items():
        ics[name] = _ic_series_for_factor(panel_df, fwd)
    print(f"  IC series computed in {time.time()-t0:.1f}s")

    # Per-factor IC summary stats
    ic_stats: Dict[str, Dict[str, float]] = {}
    for name, s in ics.items():
        ic_stats[name] = {
            "mean_ic": float(s.mean()) if len(s) else float("nan"),
            "std_ic": float(s.std()) if len(s) > 1 else float("nan"),
            "ir": float(s.mean() / s.std()) if (len(s) > 1 and s.std() > 1e-12)
            else float("nan"),
            "n_obs": int(len(s)),
        }

    # Pairwise IC time-series correlation: 3 candidates × 67 existing
    print("\nComputing IC time-series Pearson correlation matrix...")
    t0 = time.time()
    cand_names = list(candidates.keys())
    ex_names = list(existing.keys())
    cor_matrix: Dict[str, Dict[str, float]] = {c: {} for c in cand_names}
    for c in cand_names:
        for e in ex_names:
            joint = pd.concat([ics[c], ics[e]], axis=1, join="inner").dropna()
            if len(joint) < 30:
                cor_matrix[c][e] = float("nan")
                continue
            corr = float(joint.iloc[:, 0].corr(joint.iloc[:, 1]))
            cor_matrix[c][e] = corr
    print(f"  cor matrix computed in {time.time()-t0:.1f}s "
          f"({len(cand_names)} × {len(ex_names)} = "
          f"{len(cand_names)*len(ex_names)} pairs)")

    # Per-candidate verdict + top-5 most correlated existing factors
    verdicts: Dict[str, Dict] = {}
    for c in cand_names:
        cors_sorted = sorted(
            ((e, abs(cor_matrix[c][e])) for e in ex_names if pd.notna(cor_matrix[c][e])),
            key=lambda kv: kv[1], reverse=True,
        )
        if not cors_sorted:
            top5 = []
            max_abs = float("nan")
            verdict = "REJECT"
        else:
            top5 = [
                {"factor": e, "abs_corr": abs_c,
                 "signed_corr": cor_matrix[c][e]}
                for e, abs_c in cors_sorted[:5]
            ]
            max_abs = float(cors_sorted[0][1])
            verdict = _verdict(max_abs)
        verdicts[c] = {
            "max_abs_cor_with_existing": max_abs,
            "max_cor_partner": cors_sorted[0][0] if cors_sorted else None,
            "top5_correlated_existing": top5,
            "verdict": verdict,
            "ic_stats": ic_stats[c],
        }

    # Write JSON
    out = {
        "lineage_tag": "cycle07-to-fleet-master-2026-05-06",
        "phase": "A.2",
        "horizon_days": args.horizon,
        "panel_role": "miner",
        "panel_shape": {
            "n_dates": int(panel["close"].shape[0]),
            "n_symbols": int(panel["close"].shape[1]),
            "train_start": str(train_start.date()),
            "train_end": str(train_end.date()),
        },
        "candidates": list(candidates.keys()),
        "n_existing_factors": len(existing),
        "verdicts": verdicts,
        "ic_stats_existing": {n: ic_stats[n] for n in ex_names},
    }
    out_path = Path(args.out_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nWrote {out_path}")

    # Stdout summary
    print("\n" + "=" * 70)
    print("Per-candidate verdict:")
    print("=" * 70)
    for c, v in verdicts.items():
        print(f"\n  {c}:")
        print(f"    mean_IC={v['ic_stats']['mean_ic']:+.4f}  "
              f"IR={v['ic_stats']['ir']:+.3f}  "
              f"n_obs={v['ic_stats']['n_obs']}")
        print(f"    max |cor| with existing = {v['max_abs_cor_with_existing']:.3f}  "
              f"({v['max_cor_partner']})")
        print(f"    VERDICT: {v['verdict']}")
        print(f"    top-5 most correlated existing:")
        for entry in v["top5_correlated_existing"]:
            print(f"      {entry['factor']:35s}  "
                  f"|cor|={entry['abs_corr']:.3f}  "
                  f"signed={entry['signed_corr']:+.3f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
