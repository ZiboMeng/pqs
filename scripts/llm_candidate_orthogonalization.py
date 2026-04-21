#!/usr/bin/env python3
"""LLM-Round 10 tool: orthogonalization gate for LLM candidates
(PRD §9 LLM-6, §5.1 incremental-value test).

Closes the methodology gap left by the dedup-heuristic in
`core/factors/llm_candidate.py::dedup_check`. The existing dedup
flags candidates with Spearman rank correlation > 0.7 to any
existing factor, triggering mandatory review (per PRD §5.1) but
NOT quantifying incremental value. This tool answers:

  "After projecting the candidate onto the span of existing
   factors and extracting residuals, does the residual still
   carry predictive IC?"

Methodology:
  1. Compute candidate factor values on universe
  2. Select a control set of existing factors (RESEARCH_FACTORS
     or subset specified via --controls)
  3. At each date, run cross-sectional OLS:
        candidate[t,:] = alpha_t + beta_t @ controls[t,:] + residual[t,:]
  4. Stack residuals into a per-(date, symbol) panel
  5. Compute IC of residuals vs 21d forward return
  6. Verdict: residual IC mean + IR compared to raw candidate IC

Per PRD §5.1: "correlation > 0.7 triggers mandatory review (not
auto-reject); candidate must demonstrate incremental value".
This tool's output IS the demonstration — a positive residual IC
means incremental value exists; near-zero means the candidate is
fully explained by existing factors.

Does NOT promote candidates. LLM never final judge (§2.2). Human
interprets residual IC + decides.

Usage
-----
    # Orthogonalize against all RESEARCH_FACTORS
    python scripts/llm_candidate_orthogonalization.py \\
        --candidate research/llm_candidates/round_01/rs_vs_qqq_63d.yaml

    # Control against a specific subset
    python scripts/llm_candidate_orthogonalization.py \\
        --candidate research/llm_candidates/round_04/rs_vs_equal_weight_63d.yaml \\
        --controls rs_vs_spy_63d,xsection_rank_63d
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
from core.factors.factor_generator import generate_all_factors
from core.factors.llm_candidate import load_candidate_from_yaml
from core.logging_setup import get_logger, setup_logging

setup_logging()
logger = get_logger("llm_candidate_orthogonalization")


def _resolve_compute_fn(path: str):
    module_name, func_name = path.split(":", 1)
    return getattr(importlib.import_module(module_name), func_name)


def _load_panel(cfg, universe_size: int, start: str):
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))
    uni = cfg.universe
    all_syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs) +
        list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    symbols = [s for s in all_syms
               if s not in uni.blacklist and s not in uni.macro_reference]
    pf, vf = {}, {}
    for s in symbols[:universe_size]:
        df = store.read(s, "1d")
        if df is not None and not df.empty:
            if "close" in df.columns:
                pf[s] = df["close"]
            if "volume" in df.columns:
                vf[s] = df["volume"]
    price_df = pd.DataFrame(pf).sort_index()
    vol_df = pd.DataFrame(vf).sort_index() if vf else None
    price_df = price_df.loc[price_df.index >= start]
    if vol_df is not None:
        vol_df = vol_df.loc[vol_df.index >= start]
    return price_df, vol_df


def _orthogonalize_cs(
    candidate: pd.DataFrame, controls: Dict[str, pd.DataFrame],
    min_controls_per_date: int = 3,
    min_symbols_per_regression: int = 5,
) -> pd.DataFrame:
    """Per-date cross-sectional OLS residualization of candidate on
    controls. Returns residual DataFrame (same shape as candidate).

    Sparse-controls handling (Round 11 fix): for each date, use only
    the subset of controls that have non-NaN coverage. A date is
    processed if:
      - at least `min_controls_per_date` controls have data
      - at least `min_symbols_per_regression` symbols have simultaneous
        non-NaN values on the candidate AND all chosen controls
    This avoids the Round 10 bug where 32 controls with long warmups
    (126d / 252d / volume-dependent) nearly guaranteed empty intersection.
    """
    residuals = pd.DataFrame(
        np.nan, index=candidate.index, columns=candidate.columns, dtype=float,
    )
    control_names = list(controls.keys())

    dates_processed = 0
    for date in candidate.index:
        y = candidate.loc[date]
        valid_syms = y.dropna().index
        if len(valid_syms) < min_symbols_per_regression:
            continue

        # Step 1: per-date, select controls with enough coverage
        usable_controls = []
        ctrl_rows_per_name: Dict[str, pd.Series] = {}
        for ctrl_name in control_names:
            ctrl = controls[ctrl_name]
            if date not in ctrl.index:
                continue
            ctrl_row = ctrl.loc[date].reindex(valid_syms)
            n_valid = ctrl_row.notna().sum()
            if n_valid >= min_symbols_per_regression:
                ctrl_rows_per_name[ctrl_name] = ctrl_row
                usable_controls.append(ctrl_name)

        if len(usable_controls) < min_controls_per_date:
            continue

        # Step 2: common symbols with y + all usable controls non-NaN
        X_df = pd.concat(
            {n: ctrl_rows_per_name[n] for n in usable_controls}, axis=1,
        )
        y_row = y.reindex(X_df.index)
        both_ok = y_row.notna() & X_df.notna().all(axis=1)
        if both_ok.sum() < max(min_symbols_per_regression,
                               len(usable_controls) + 2):
            continue

        syms = X_df.index[both_ok].tolist()
        X = X_df.loc[syms].astype(float).values
        y_vals = y_row.loc[syms].astype(float).values

        X_intercept = np.column_stack([np.ones(len(y_vals)), X])
        try:
            beta, *_ = np.linalg.lstsq(X_intercept, y_vals, rcond=None)
        except np.linalg.LinAlgError:
            continue
        resid = y_vals - X_intercept @ beta
        dates_processed += 1
        residuals.loc[date, syms] = resid
    return residuals


def _compute_ic(factor: pd.DataFrame, fwd: pd.DataFrame) -> Dict:
    ic_vals = []
    for date in factor.index:
        if date not in fwd.index:
            continue
        c_row = factor.loc[date].dropna()
        f_row = fwd.loc[date].dropna()
        common = c_row.index.intersection(f_row.index)
        if len(common) < 5:
            continue
        rho = c_row.loc[common].rank().corr(
            f_row.loc[common].rank(), method="pearson")
        if not np.isnan(rho):
            ic_vals.append(float(rho))
    if not ic_vals:
        return {"n": 0, "mean": None, "std": None, "ir": None}
    return {
        "n":    int(len(ic_vals)),
        "mean": round(float(np.mean(ic_vals)), 5),
        "std":  round(float(np.std(ic_vals, ddof=1)), 5),
        "ir":   round(float(np.mean(ic_vals) / np.std(ic_vals, ddof=1)), 3)
                if np.std(ic_vals, ddof=1) > 1e-10 else 0.0,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--universe-size", type=int, default=30)
    parser.add_argument("--start", default="2018-01-01")
    parser.add_argument("--controls", default="",
                        help="Comma-separated list of control factor names. "
                             "Empty = use ALL RESEARCH_FACTORS from generate_all_factors.")
    parser.add_argument("--horizon", type=int, default=21)
    parser.add_argument("--out-dir", default="data/ml/llm_orthog")
    args = parser.parse_args()

    cand = load_candidate_from_yaml(args.candidate)
    compute_fn = _resolve_compute_fn(cand.compute_fn_path)
    logger.info("Candidate: %s", cand.factor_name)

    cfg = load_config(Path(args.config_dir))
    price_df, vol_df = _load_panel(cfg, args.universe_size, args.start)
    logger.info("Price panel: %s", price_df.shape)

    # Candidate values
    cand_df = compute_fn(price_df)
    if cand_df.empty:
        logger.error("compute_fn returned empty DataFrame")
        sys.exit(2)

    # Controls
    all_factors = generate_all_factors(price_df, vol_df)
    if args.controls:
        control_names = [n.strip() for n in args.controls.split(",")]
        missing = [n for n in control_names if n not in all_factors]
        if missing:
            logger.error("Missing control factors: %s", missing)
            sys.exit(2)
        controls = {n: all_factors[n] for n in control_names}
    else:
        # Use all research factors, but DROP the candidate itself if it
        # shadows a research name (defensive; shouldn't happen by schema)
        controls = {n: f for n, f in all_factors.items() if n != cand.factor_name}
    logger.info("Controls: %d factors", len(controls))

    # Forward return
    fwd = price_df.pct_change(args.horizon).shift(-args.horizon)

    # Raw IC (candidate alone)
    raw_ic = _compute_ic(cand_df, fwd)
    logger.info("Raw IC: mean=%s IR=%s n=%s",
                raw_ic["mean"], raw_ic["ir"], raw_ic["n"])

    # Orthogonalize
    logger.info("Running cross-sectional OLS residualization...")
    resid_df = _orthogonalize_cs(cand_df, controls)

    # Residual IC
    resid_ic = _compute_ic(resid_df, fwd)
    logger.info("Residual IC: mean=%s IR=%s n=%s",
                resid_ic["mean"], resid_ic["ir"], resid_ic["n"])

    # Verdict
    raw_m = raw_ic.get("mean") or 0.0
    resid_m = resid_ic.get("mean") or 0.0
    raw_ir = raw_ic.get("ir") or 0.0
    resid_ir = resid_ic.get("ir") or 0.0

    ic_retention = abs(resid_m) / abs(raw_m) if abs(raw_m) > 1e-6 else 0.0
    residual_meaningful = abs(resid_m) >= 0.02 and abs(resid_ir) >= 0.15
    ic_retention_threshold = 0.3  # retains ≥ 30% of raw IC after orthogonalization

    # Overall verdict:
    # - HIGH: residual IC significant (mean >= 0.03, IR >= 0.2) — strong
    #        independent signal, incremental value clear
    # - MEDIUM: residual IC meaningful (mean >= 0.02, IR >= 0.15) AND
    #          retains >= 30% of raw IC — modest incremental value
    # - LOW: residual IC weak — factor is mostly explained by controls
    verdict = "HIGH" if (abs(resid_m) >= 0.03 and abs(resid_ir) >= 0.2) else \
              ("MEDIUM" if (residual_meaningful and ic_retention >= ic_retention_threshold) else "LOW")

    out_dir = Path(args.out_dir) / cand.factor_name
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "candidate":      cand.factor_name,
        "universe_size":  args.universe_size,
        "horizon":        args.horizon,
        "n_controls":     len(controls),
        "controls":       list(controls.keys()),
        "raw_ic":         raw_ic,
        "residual_ic":    resid_ic,
        "ic_retention":   round(ic_retention, 3),
        "verdict":        verdict,
    }
    (out_dir / "orthog_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False)
    )

    # Pretty print
    print()
    print("=" * 72)
    print(f"Candidate: {cand.factor_name}")
    print(f"Controls: {len(controls)} factors | "
          f"Universe: {args.universe_size} | Start: {args.start}")
    print("-" * 72)
    print(f"Raw IC:      mean={raw_m:+.5f}  IR={raw_ir:+.3f}  "
          f"n={raw_ic['n']}")
    print(f"Residual IC: mean={resid_m:+.5f}  IR={resid_ir:+.3f}  "
          f"n={resid_ic['n']}")
    print(f"IC retention: {ic_retention:.1%}  "
          f"(|resid_mean| / |raw_mean|)")
    print()
    print(f"Verdict: {verdict}")
    if verdict == "HIGH":
        print("  → Strong independent signal. Candidate adds clear incremental "
              "value to existing factor set. PRD §5.1 review argument: CLEAR.")
    elif verdict == "MEDIUM":
        print("  → Modest incremental value. Candidate has residual IC after "
              "projection but weaker than raw. Worth human review.")
    else:
        print("  → Weak/no incremental value. Candidate mostly explained by "
              "controls; archive.")
    print("=" * 72)
    print(f"Artifacts: {out_dir}")


if __name__ == "__main__":
    main()
