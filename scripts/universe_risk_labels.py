#!/usr/bin/env python3
"""LLM-Round 23 tool: Layer 2 risk exposure labels (per v2.1 spec §3).

Computes per-symbol risk metadata WITHOUT filtering/admission logic.
Output is a labeled CSV that portfolio construction (Layer 3) consumes.

Per v2.1 §3, this tool computes:

  - risk_estimation_ready / _stable flags (from SPY+QQQ overlap)
  - beta_spy / beta_qqq (252d + 504d rolling means)
  - r2_spy / r2_qqq
  - downside_beta_spy (conditional on SPY < -1σ)
  - alpha_252d / alpha_504d (annualized)
  - alpha_t_stat
  - alpha_positive_rate_rolling (PRIMARY metric — consistency-first
    per user v2.1 §3.3)
  - alpha_subperiod_consistency (sign agreement across 252d subperiods)
  - max_dd_rolling_3y / _5y
  - tail_correlation_to_spy (corr on SPY < -2σ days)
  - spread_hl_proxy_bps (high-low range proxy for bid-ask)
  - gics_sector (if available via config)

Does NOT run admission — assumes input is a pre-admitted list (e.g.,
output of universe_admission_screen.py). Strictly Layer 2.

Usage
-----
    # From admission tool's output
    python scripts/universe_risk_labels.py \\
        --admission-csv data/ml/universe_admission_r22_test.csv \\
        --out-tag r22_test_labels

    # From a symbol list file (skips admission, treats all as admitted)
    python scripts/universe_risk_labels.py \\
        --input-symbols symbols.txt \\
        --out-tag custom_labels
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from core.config.loader import load_config
from core.data.market_data_store import MarketDataStore
from core.logging_setup import get_logger, setup_logging

setup_logging()
logger = get_logger("universe_risk_labels")


def _ols_beta_alpha(
    symbol_ret: np.ndarray, bench_ret: np.ndarray,
) -> Tuple[float, float, float]:
    """OLS: symbol_ret = α + β * bench_ret + ε. Returns (α_daily, β, r2).
    α_daily is NOT annualized."""
    if len(symbol_ret) < 30 or len(bench_ret) != len(symbol_ret):
        return (float("nan"), float("nan"), float("nan"))
    X = np.column_stack([np.ones(len(bench_ret)), bench_ret])
    try:
        coef, *_ = np.linalg.lstsq(X, symbol_ret, rcond=None)
    except np.linalg.LinAlgError:
        return (float("nan"), float("nan"), float("nan"))
    alpha_d, beta = float(coef[0]), float(coef[1])
    pred = X @ coef
    ss_res = np.sum((symbol_ret - pred) ** 2)
    ss_tot = np.sum((symbol_ret - symbol_ret.mean()) ** 2)
    r2 = float(1 - ss_res / ss_tot) if ss_tot > 1e-12 else 0.0
    return (alpha_d, beta, r2)


def _alpha_positive_rate(
    symbol_ret: pd.Series, bench_ret: pd.Series,
    window: int = 63, step: int = 5,
) -> float:
    """Fraction of rolling `window`-day windows (stepping by `step`)
    where OLS alpha > 0. PRIMARY metric per v2.1 §3.3.
    """
    common = symbol_ret.index.intersection(bench_ret.index)
    s = symbol_ret.loc[common].values
    m = bench_ret.loc[common].values
    if len(s) < window + step:
        return float("nan")
    alphas = []
    for start in range(0, len(s) - window, step):
        end = start + window
        a, _, _ = _ols_beta_alpha(s[start:end], m[start:end])
        if not np.isnan(a):
            alphas.append(a)
    if not alphas:
        return float("nan")
    return float(np.mean(np.array(alphas) > 0))


def _alpha_subperiod_consistency(
    symbol_ret: pd.Series, bench_ret: pd.Series,
    subperiod_days: int = 252,
) -> Dict:
    """Sign distribution of OLS alpha across non-overlapping
    `subperiod_days` subperiods. Returns dict with raw counts so
    downstream can pick ALL / majority / fraction threshold.

    Returns:
      n_subperiods     : int total subperiods evaluated
      n_positive       : int count of α > 0 subperiods
      n_negative       : int count of α < 0
      all_same_sign    : bool (strict v2.2 interpretation)
      positive_fraction: float n_positive / n_subperiods
      majority_sign    : +1 / -1 / 0
    """
    common = symbol_ret.index.intersection(bench_ret.index)
    s = symbol_ret.loc[common].values
    m = bench_ret.loc[common].values
    n_sub = len(s) // subperiod_days
    if n_sub < 2:
        return {"n_subperiods": n_sub, "n_positive": 0, "n_negative": 0,
                "all_same_sign": False, "positive_fraction": float("nan"),
                "majority_sign": 0}
    signs = []
    for i in range(n_sub):
        a, _, _ = _ols_beta_alpha(
            s[i * subperiod_days:(i + 1) * subperiod_days],
            m[i * subperiod_days:(i + 1) * subperiod_days],
        )
        if not np.isnan(a):
            signs.append(np.sign(a))
    if not signs:
        return {"n_subperiods": 0, "n_positive": 0, "n_negative": 0,
                "all_same_sign": False, "positive_fraction": float("nan"),
                "majority_sign": 0}
    n_pos = int(sum(1 for x in signs if x > 0))
    n_neg = int(sum(1 for x in signs if x < 0))
    total = len(signs)
    pos_frac = n_pos / total
    majority = 1 if n_pos > n_neg else (-1 if n_neg > n_pos else 0)
    return {
        "n_subperiods":     total,
        "n_positive":       n_pos,
        "n_negative":       n_neg,
        "all_same_sign":    (n_pos == total or n_neg == total),
        "positive_fraction": round(pos_frac, 3),
        "majority_sign":    majority,
    }


def _downside_beta(symbol_ret: pd.Series, spy_ret: pd.Series) -> float:
    """Beta conditional on SPY returns < -1σ."""
    common = symbol_ret.index.intersection(spy_ret.index)
    s = symbol_ret.loc[common].dropna()
    m = spy_ret.loc[common].dropna()
    common = s.index.intersection(m.index)
    s, m = s.loc[common].values, m.loc[common].values
    threshold = -np.std(m)
    mask = m < threshold
    if mask.sum() < 20:
        return float("nan")
    _, beta, _ = _ols_beta_alpha(s[mask], m[mask])
    return beta


def _tail_correlation(symbol_ret: pd.Series, spy_ret: pd.Series) -> float:
    """Correlation on SPY return < -2σ days."""
    common = symbol_ret.index.intersection(spy_ret.index)
    s = symbol_ret.loc[common].dropna()
    m = spy_ret.loc[common].dropna()
    common = s.index.intersection(m.index)
    s, m = s.loc[common], m.loc[common]
    threshold = -2 * m.std()
    mask = m < threshold
    if mask.sum() < 10:
        return float("nan")
    return float(s[mask].corr(m[mask]))


def _max_dd(prices: pd.Series) -> float:
    if len(prices) < 20:
        return float("nan")
    nav = prices / prices.iloc[0]
    roll_max = nav.cummax()
    return float(((nav - roll_max) / roll_max).min())


def _spread_hl_proxy_bps(df: pd.DataFrame) -> float:
    """High-low range as bps proxy for bid-ask (rough; good for relative
    comparison)."""
    if "high" not in df.columns or "low" not in df.columns or df.empty:
        return float("nan")
    recent = df.tail(60)
    hl = (recent["high"] - recent["low"]) / recent["close"].replace(0, np.nan)
    return float(hl.median() * 10000)  # to bps


def _label_symbol(
    symbol: str, store: MarketDataStore, spy_close: pd.Series,
    qqq_close: pd.Series, start: str,
) -> Dict:
    df = store.read(symbol, "1d")
    if df is None or df.empty or "close" not in df.columns:
        return {"symbol": symbol, "ok": False, "reason": "no_data"}
    df = df.loc[df.index >= start]
    if len(df) < 100:
        return {"symbol": symbol, "ok": False, "reason": "short_history"}

    close = df["close"]
    sym_ret = close.pct_change().dropna()
    spy_ret = spy_close.pct_change().dropna()
    qqq_ret = qqq_close.pct_change().dropna()

    # Overlap flags
    overlap_spy = len(sym_ret.index.intersection(spy_ret.index))
    overlap_qqq = len(sym_ret.index.intersection(qqq_ret.index))
    risk_ready = overlap_spy >= 252 and overlap_qqq >= 252
    risk_stable = overlap_spy >= 504 and overlap_qqq >= 504

    if not risk_ready:
        return {
            "symbol":                symbol,
            "ok":                    True,
            "risk_estimation_ready": False,
            "risk_estimation_stable": False,
            "n_days":                len(df),
            "overlap_spy":           overlap_spy,
            "overlap_qqq":           overlap_qqq,
        }

    # Betas (252d tail)
    common_s = sym_ret.index.intersection(spy_ret.index)
    common_q = sym_ret.index.intersection(qqq_ret.index)
    s_aligned_s = sym_ret.loc[common_s].tail(252).values
    m_aligned_s = spy_ret.loc[common_s].tail(252).values
    s_aligned_q = sym_ret.loc[common_q].tail(252).values
    m_aligned_q = qqq_ret.loc[common_q].tail(252).values

    alpha_d_spy_252, beta_spy_252, r2_spy_252 = _ols_beta_alpha(s_aligned_s, m_aligned_s)
    alpha_d_qqq_252, beta_qqq_252, r2_qqq_252 = _ols_beta_alpha(s_aligned_q, m_aligned_q)

    # 504d (full-stability sample)
    if risk_stable:
        s_504 = sym_ret.loc[common_s].tail(504).values
        m_504 = spy_ret.loc[common_s].tail(504).values
        alpha_d_504, beta_spy_504, r2_spy_504 = _ols_beta_alpha(s_504, m_504)
    else:
        alpha_d_504 = beta_spy_504 = r2_spy_504 = float("nan")

    # Annualize alpha
    alpha_annual_spy_252 = alpha_d_spy_252 * 252 if not np.isnan(alpha_d_spy_252) else float("nan")
    alpha_annual_504 = alpha_d_504 * 252 if not np.isnan(alpha_d_504) else float("nan")

    # Alpha t-stat (rough — t = α / (residual_std / sqrt(n)))
    if not np.isnan(alpha_d_spy_252) and len(s_aligned_s) > 2:
        X = np.column_stack([np.ones(len(m_aligned_s)), m_aligned_s])
        coef = np.array([alpha_d_spy_252, beta_spy_252])
        resid = s_aligned_s - X @ coef
        s_resid = np.std(resid, ddof=2)
        if s_resid > 1e-10:
            alpha_t_stat = float(alpha_d_spy_252 / (s_resid / np.sqrt(len(s_aligned_s))))
        else:
            alpha_t_stat = float("nan")
    else:
        alpha_t_stat = float("nan")

    # PRIMARY metric: alpha_positive_rate_rolling
    pos_rate = _alpha_positive_rate(
        sym_ret.loc[common_s].tail(504),
        spy_ret.loc[common_s].tail(504),
        window=63, step=5,
    )

    # Subperiod consistency — now returns detailed counts so downstream
    # can pick threshold (all_same_sign / ≥75% / ≥2/3)
    sub = _alpha_subperiod_consistency(
        sym_ret.loc[common_s], spy_ret.loc[common_s], subperiod_days=252,
    )

    # Downside beta + tail correlation
    dbeta = _downside_beta(sym_ret, spy_ret)
    tail_corr = _tail_correlation(sym_ret, spy_ret)

    # Max DD rolling 3y / 5y
    max_dd_3y = _max_dd(close.tail(252 * 3))
    max_dd_5y = _max_dd(close.tail(252 * 5))

    # Spread proxy
    spread = _spread_hl_proxy_bps(df)

    r2_max = max(
        [x for x in [r2_spy_252, r2_qqq_252] if not np.isnan(x)],
        default=float("nan"),
    )

    return {
        "symbol":                 symbol,
        "ok":                     True,
        "n_days":                 len(df),
        "risk_estimation_ready":  bool(risk_ready),
        "risk_estimation_stable": bool(risk_stable),
        "overlap_spy":            overlap_spy,
        "overlap_qqq":            overlap_qqq,
        "beta_spy_252d":          round(beta_spy_252, 3) if not np.isnan(beta_spy_252) else None,
        "beta_qqq_252d":          round(beta_qqq_252, 3) if not np.isnan(beta_qqq_252) else None,
        "beta_spy_504d":          round(beta_spy_504, 3) if not np.isnan(beta_spy_504) else None,
        "r2_spy_252d":            round(r2_spy_252, 3) if not np.isnan(r2_spy_252) else None,
        "r2_qqq_252d":            round(r2_qqq_252, 3) if not np.isnan(r2_qqq_252) else None,
        "r2_max":                 round(r2_max, 3) if not np.isnan(r2_max) else None,
        "alpha_annual_spy_252":   round(alpha_annual_spy_252, 4) if not np.isnan(alpha_annual_spy_252) else None,
        "alpha_annual_spy_504":   round(alpha_annual_504, 4) if not np.isnan(alpha_annual_504) else None,
        "alpha_t_stat_252":       round(alpha_t_stat, 3) if not np.isnan(alpha_t_stat) else None,
        "alpha_positive_rate":    round(pos_rate, 3) if not np.isnan(pos_rate) else None,
        "alpha_subperiod_all_same_sign":  bool(sub["all_same_sign"]),
        "alpha_subperiod_positive_frac":  sub["positive_fraction"],
        "alpha_subperiod_n_positive":     sub["n_positive"],
        "alpha_subperiod_n_negative":     sub["n_negative"],
        "alpha_subperiod_majority_sign":  sub["majority_sign"],
        "n_subperiods":           sub["n_subperiods"],
        "downside_beta_spy":      round(dbeta, 3) if not np.isnan(dbeta) else None,
        "tail_correlation_spy":   round(tail_corr, 3) if not np.isnan(tail_corr) else None,
        "max_dd_3y":              round(max_dd_3y, 4) if not np.isnan(max_dd_3y) else None,
        "max_dd_5y":              round(max_dd_5y, 4) if not np.isnan(max_dd_5y) else None,
        "spread_hl_proxy_bps":    round(spread, 1) if not np.isnan(spread) else None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--admission-csv", default=None,
                        help="CSV from universe_admission_screen.py; "
                             "labels only symbols with tier CORE/EXTENDED")
    parser.add_argument("--input-symbols", default=None,
                        help="Alt: newline-separated symbol list file")
    parser.add_argument("--start", default="2018-01-01")
    parser.add_argument("--out-tag", default="risk_labels")
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--out-dir", default="data/ml")
    args = parser.parse_args()

    cfg = load_config(Path(args.config_dir))
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))

    # Symbols
    if args.admission_csv:
        adm = pd.read_csv(args.admission_csv)
        if "tier" not in adm.columns:
            logger.error("admission CSV lacks 'tier' column")
            sys.exit(2)
        symbols = adm.loc[adm["tier"].isin(["CORE", "EXTENDED"]), "symbol"].tolist()
        logger.info("Admission CSV: %d CORE+EXTENDED symbols", len(symbols))
    elif args.input_symbols:
        syms_text = Path(args.input_symbols).read_text()
        symbols = [line.strip().upper() for line in syms_text.splitlines()
                   if line.strip() and not line.strip().startswith("#")]
        logger.info("Input-symbols: %d", len(symbols))
    else:
        # default: current config universe (excluding macro references)
        uni = cfg.universe
        all_syms = list(dict.fromkeys(
            list(uni.seed_pool) + list(uni.sector_etfs) +
            list(uni.factor_etfs) + list(uni.cross_asset)
        ))
        symbols = [s for s in all_syms
                   if s not in uni.blacklist and s not in uni.macro_reference]
        logger.info("Config universe: %d symbols", len(symbols))

    # Benchmarks
    spy_df = store.read("SPY", "1d")
    qqq_df = store.read("QQQ", "1d")
    if spy_df is None or qqq_df is None:
        logger.error("SPY or QQQ data unavailable")
        sys.exit(2)
    spy_close = spy_df["close"].loc[spy_df.index >= args.start]
    qqq_close = qqq_df["close"].loc[qqq_df.index >= args.start]

    rows = []
    n_total = len(symbols)
    for i, sym in enumerate(symbols, 1):
        if i % 100 == 0:
            logger.info("  %d/%d", i, n_total)
        rows.append(_label_symbol(sym, store, spy_close, qqq_close, args.start))

    df = pd.DataFrame(rows).sort_values(
        "alpha_positive_rate", ascending=False, na_position="last",
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"universe_risk_labels_{args.out_tag}.csv"
    df.to_csv(csv_path, index=False)
    summary = {
        "n_symbols":             n_total,
        "start":                 args.start,
        "n_risk_ready":          int(df["risk_estimation_ready"].sum()) if "risk_estimation_ready" in df else 0,
        "n_risk_stable":         int(df["risk_estimation_stable"].sum()) if "risk_estimation_stable" in df else 0,
    }
    (out_dir / f"universe_risk_labels_{args.out_tag}_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False)
    )

    # Print summary (top 20 by alpha_positive_rate)
    print()
    print("=" * 120)
    print(f"Universe Risk Labels (Layer 2) — {args.out_tag}")
    print(f"  N={n_total} symbols | Start {args.start}")
    print("=" * 120)
    # Pretty-print top 15 by alpha_positive_rate
    cols = ["symbol", "beta_spy_252d", "beta_qqq_252d", "r2_max",
            "alpha_annual_spy_252", "alpha_positive_rate",
            "alpha_subperiod_positive_frac", "alpha_subperiod_all_same_sign",
            "downside_beta_spy",
            "tail_correlation_spy", "max_dd_3y"]
    print()
    print("TOP 15 by alpha_positive_rate:")
    print(df.head(15)[cols].to_string(index=False))
    print()
    print(f"Artifacts: {csv_path}")


if __name__ == "__main__":
    main()
