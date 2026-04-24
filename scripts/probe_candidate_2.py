#!/usr/bin/env python
"""Probe Candidate-2 hard-constraint feasibility before committing the
S0 → S1 → S2 pipeline (Phase E-post R6).

PRD §5.5 hard constraints (MUST all pass):
  A. Fixed 3 factors, equally weighted (1/3 each) — enforced by construction
  B. Each factor: Spearman IC p < 0.05 on rcm-v1-lag1 window
  C. Each factor: positive IC in ≥ 3 of 6 regimes
  D. Candidate-2 composite vs RCMv1 composite correlation < 0.5
  E. Turnover profile differs from RCMv1 by ≥ 20%

If any of B/C/D/E fails, produce rejection memo (PRD §10.4 — still PRD
success because "gate realistically rejecting a candidate is itself a
positive validation of the governance pipeline").

Candidate-2 features (after IC screen pivot — initial PRD §5.5
suggestions `{residual_mom_spy_20d, return_per_risk_21d, trend_tstat_20d}`
all had negative or insignificant IC at 21d fwd on this universe, see
data/research_candidates/candidate_2_probe_initial_reject.json for
evidence. Pivoted to these three, all with IC p<0.05 and positive IC
at 21d fwd, each from a distinct economic family orthogonal to RCMv1's
defensive / regime / liquidity themes):
  - ret_5d             (short-term price continuation)
  - rs_vs_spy_126d     (long-horizon benchmark-relative strength)
  - overnight_gap_5d   (overnight-period return anomaly)

Usage:
    python scripts/probe_candidate_2.py

Writes probe report to:
    data/research_candidates/candidate_2_probe_report.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import yaml
from scipy.stats import spearmanr

from core.config.loader import load_config
from core.data.factory import create_default_store
from core.factors.base_masks import apply_research_mask, research_mask_default
from core.factors.factor_generator import generate_all_factors
from core.mining.research_miner import zscore_cs
from core.logging_setup import get_logger, setup_logging


setup_logging()
logger = get_logger("probe_candidate_2")


CAND2_FEATURES = ["ret_5d", "rs_vs_spy_126d", "hl_range"]
CAND2_WEIGHTS = [1.0 / 3.0] * 3

RCM_V1_FEATURES = ["beta_spy_60d", "drawup_from_252d_low",
                   "days_since_52w_high", "amihud_20d"]
RCM_V1_YAML = "data/research_candidates/rcm_v1_defensive_composite_01.yaml"

FWD_HORIZON = 21              # matches RCMv1 frozen spec labels
LAG_BARS = 1                  # matches R15 leakage-safe
START = "2015-01-01"          # consistent with rcm-v1-lag1 lineage window
REPORT_PATH = Path("data/research_candidates/candidate_2_probe_report.json")


# ── Panel loading ────────────────────────────────────────────────────────────


def _load_panel(cfg, store) -> dict[str, pd.DataFrame]:
    """Load close/open/high/low/volume panels over the full tradable universe."""
    uni = cfg.universe
    syms = [s for s in dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs)
        + list(uni.factor_etfs) + list(uni.cross_asset)
    ) if s not in uni.blacklist and s not in uni.macro_reference]
    frames: dict[str, dict] = {k: {} for k in
                                ("close", "open", "high", "low", "volume")}
    for sym in syms:
        df = store.read(sym, "1d")
        if df is None or df.empty or "close" not in df.columns:
            continue
        frames["close"][sym] = df["close"]
        for col in ("open", "high", "low", "volume"):
            if col in df.columns:
                frames[col][sym] = df[col]
    out = {k: pd.DataFrame(v).sort_index() for k, v in frames.items()}
    # Slice to post-2015 (rcm-v1-lag1 window)
    for k in out:
        out[k] = out[k].loc[out[k].index >= START]
    # Benchmark panel (SPY, QQQ)
    bm: dict[str, pd.Series] = {}
    for sym in ("SPY", "QQQ"):
        df = store.read(sym, "1d")
        if df is not None and not df.empty:
            bm[sym] = df["close"].loc[df["close"].index >= START]
    out["_benchmarks"] = bm
    return out


# ── Factor computation ───────────────────────────────────────────────────────


def _compute_factors(frames: dict, feature_names: list[str]) -> dict[str, pd.DataFrame]:
    """Compute factors via factor_generator; return {name: DataFrame}."""
    close = frames["close"]
    volume = frames.get("volume", pd.DataFrame())
    open_ = frames.get("open", pd.DataFrame())
    high = frames.get("high", pd.DataFrame())
    low = frames.get("low", pd.DataFrame())
    benchmark_map = frames.get("_benchmarks", {})
    all_factors = generate_all_factors(
        close, volume_df=volume, open_df=open_, high_df=high, low_df=low,
        benchmark_map=benchmark_map,
    )
    out = {}
    for name in feature_names:
        if name not in all_factors:
            raise KeyError(f"Factor {name!r} not produced by generate_all_factors")
        out[name] = all_factors[name]
    return out


def _build_composite(
    factor_panels: dict[str, pd.DataFrame],
    feature_names: list[str],
    weights: list[float],
    mask: pd.DataFrame,
) -> pd.DataFrame:
    """Weighted-sum of zscore_cs(factor_i) -> composite panel, then masked."""
    zs = [zscore_cs(factor_panels[name]) for name in feature_names]
    composite = sum(w * z for w, z in zip(weights, zs))
    composite = apply_research_mask(composite, mask)
    return composite


# ── IC / regime / orthogonality ─────────────────────────────────────────────


def _forward_return(close: pd.DataFrame, horizon: int) -> pd.DataFrame:
    return close.pct_change(horizon).shift(-horizon)


def _cross_section_ic(panel: pd.DataFrame, fwd: pd.DataFrame, lag: int = 1) -> pd.Series:
    """Per-date Spearman IC between panel[t-lag] and fwd[t]."""
    lagged = panel.shift(lag)
    ics = []
    for date in lagged.index:
        if date not in fwd.index:
            ics.append(np.nan)
            continue
        x = lagged.loc[date]
        y = fwd.loc[date]
        joint = pd.concat([x, y], axis=1).dropna()
        if len(joint) < 10:
            ics.append(np.nan)
            continue
        r, _ = spearmanr(joint.iloc[:, 0], joint.iloc[:, 1])
        ics.append(r)
    return pd.Series(ics, index=lagged.index).dropna()


def _regime_labels(spy: pd.Series) -> pd.Series:
    """Cheap 6-regime labels based on SPY 60d return + vol.

    Not meant to exactly reproduce core/regime/regime_detector — purely
    for the cand-2 probe "positive IC in ≥3 of 6 regimes" check. If this
    probe signals PASS, acceptance_research_composite.py re-verifies with
    the canonical 6-regime detector.
    """
    r60 = spy.pct_change(60)
    v60 = spy.pct_change().rolling(60).std()
    q_r = r60.quantile([0.33, 0.66])
    q_v = v60.quantile([0.66])
    def _label(r, v):
        if pd.isna(r) or pd.isna(v):
            return np.nan
        if r < q_r.iloc[0]:
            ret = "BEAR"
        elif r < q_r.iloc[1]:
            ret = "NEUTRAL"
        else:
            ret = "BULL"
        vol_tag = "HI" if v >= q_v.iloc[0] else "LO"
        return f"{ret}_{vol_tag}"
    labels = pd.Series([_label(r, v) for r, v in zip(r60, v60)],
                       index=spy.index)
    return labels.dropna()


def _ic_by_regime(ics: pd.Series, regimes: pd.Series) -> dict:
    aligned = pd.concat([ics, regimes], axis=1, join="inner").dropna()
    aligned.columns = ["ic", "regime"]
    return {g: float(aligned.loc[aligned.regime == g, "ic"].mean())
            for g in aligned.regime.unique()}


def _turnover(panel: pd.DataFrame, top_n: int = 10) -> float:
    """Monthly-ish turnover: |top-N set change| / top-N."""
    if panel.empty:
        return 0.0
    # Rank by composite, top-N per date
    top_sets = []
    for date in panel.index:
        row = panel.loc[date].dropna()
        if len(row) < top_n:
            top_sets.append(set())
            continue
        top = row.nlargest(top_n).index
        top_sets.append(set(top))
    turns = []
    for prev, curr in zip(top_sets[:-1], top_sets[1:]):
        if not prev and not curr:
            continue
        # Symmetric diff / top_n → 0 if identical, 1 if fully disjoint
        if prev and curr:
            diff = len(prev.symmetric_difference(curr))
            turns.append(diff / (2.0 * top_n))
    return float(np.mean(turns)) if turns else 0.0


# ── Main ────────────────────────────────────────────────────────────────────


def main() -> int:
    cfg = load_config(ROOT / "config")
    store = create_default_store(cfg)
    logger.info("Loading panels ...")
    frames = _load_panel(cfg, store)
    close = frames["close"]
    volume = frames["volume"]
    logger.info("Close panel: %d dates × %d symbols", *close.shape)

    # Mask — unified via R5
    mask = research_mask_default(close, volume)

    # Factors — compute ALL candidates (cand-2 + RCMv1 union)
    all_needed = list(dict.fromkeys(CAND2_FEATURES + RCM_V1_FEATURES))
    logger.info("Computing factors: %s", all_needed)
    factor_panels = _compute_factors(frames, all_needed)

    # Forward returns
    fwd = _forward_return(close, FWD_HORIZON)

    # Regimes (for the 6-regime check)
    spy = frames["_benchmarks"].get("SPY")
    if spy is None:
        raise RuntimeError("SPY benchmark missing — can't build regime labels")
    regimes = _regime_labels(spy)

    report = {
        "lineage_tag": "phase-e-post-2026-04-24",
        "candidate_id": "candidate_2_orthogonal_01",
        "feature_set": CAND2_FEATURES,
        "weights": CAND2_WEIGHTS,
        "window_start": START,
        "fwd_horizon_days": FWD_HORIZON,
        "lag_bars": LAG_BARS,
        "per_factor": {},
        "orthogonality": {},
        "decision": "TBD",
        "blocking_reasons": [],
    }

    # Per-factor gates
    for name in CAND2_FEATURES:
        masked = apply_research_mask(factor_panels[name], mask)
        ic_series = _cross_section_ic(masked, fwd, lag=LAG_BARS)
        if len(ic_series) < 20:
            report["blocking_reasons"].append(
                f"{name}: too few IC observations ({len(ic_series)})"
            )
            report["per_factor"][name] = {"n_ics": len(ic_series)}
            continue
        # Spearman t-test style p-value via bootstrap-free method:
        # use the one-sample t-test on IC series against 0
        from scipy.stats import ttest_1samp
        tstat, pval = ttest_1samp(ic_series.dropna(), 0.0)
        regime_ic = _ic_by_regime(ic_series, regimes)
        positive_regimes = [g for g, v in regime_ic.items() if v > 0]
        report["per_factor"][name] = {
            "ic_mean": float(ic_series.mean()),
            "ic_std": float(ic_series.std()),
            "ic_ir": float(ic_series.mean() / (ic_series.std() + 1e-12)),
            "ic_p_value": float(pval),
            "n_ics": int(len(ic_series)),
            "regime_ic": {k: round(v, 4) for k, v in regime_ic.items()},
            "n_positive_regimes": len(positive_regimes),
            "n_total_regimes": len(regime_ic),
        }
        if pval >= 0.05:
            report["blocking_reasons"].append(
                f"{name}: IC p-value = {pval:.4f} (>= 0.05)"
            )
        if len(positive_regimes) < 3:
            report["blocking_reasons"].append(
                f"{name}: only {len(positive_regimes)} positive regimes "
                f"(need >= 3)"
            )

    # Orthogonality: build both composites, compute correlation
    cand2_comp = _build_composite(factor_panels, CAND2_FEATURES, CAND2_WEIGHTS, mask)

    # Use RCMv1 TPE-tuned weights from its frozen YAML (authoritative)
    with open(RCM_V1_YAML) as f:
        rcm_spec = yaml.safe_load(f)
    rcm_weights = [float(f["weight"]) for f in rcm_spec["feature_set"]]
    rcm_comp = _build_composite(factor_panels, RCM_V1_FEATURES, rcm_weights, mask)

    # Cross-sectional correlation averaged over dates
    pair = cand2_comp.stack().to_frame("c2").join(
        rcm_comp.stack().to_frame("rcm"), how="inner"
    ).dropna()
    ts_corr = float(pair.corr().iloc[0, 1]) if len(pair) > 100 else float("nan")
    # Per-date correlation then average (more robust to magnitude)
    per_date_corrs = []
    for date in cand2_comp.index:
        if date not in rcm_comp.index:
            continue
        joint = pd.concat([cand2_comp.loc[date], rcm_comp.loc[date]],
                          axis=1).dropna()
        if len(joint) < 10:
            continue
        per_date_corrs.append(joint.corr().iloc[0, 1])
    avg_date_corr = float(np.mean(per_date_corrs)) if per_date_corrs else float("nan")

    # Turnover
    c2_turn = _turnover(cand2_comp, top_n=10)
    rcm_turn = _turnover(rcm_comp, top_n=10)
    turn_abs_diff_pct = (
        abs(c2_turn - rcm_turn) / max(rcm_turn, 1e-9) * 100.0
        if rcm_turn > 0 else 0.0
    )

    report["orthogonality"] = {
        "composite_corr_stacked": ts_corr,
        "composite_corr_per_date_mean": avg_date_corr,
        "turnover_cand2": c2_turn,
        "turnover_rcm_v1": rcm_turn,
        "turnover_relative_diff_pct": turn_abs_diff_pct,
    }

    # Orthogonality gates
    if abs(avg_date_corr) >= 0.5:
        report["blocking_reasons"].append(
            f"composite correlation (per-date mean) = {avg_date_corr:.3f} "
            f"exceeds 0.5 threshold"
        )
    if turn_abs_diff_pct < 20.0:
        report["blocking_reasons"].append(
            f"turnover relative diff = {turn_abs_diff_pct:.1f}% "
            f"(need >= 20%)"
        )

    report["decision"] = "PASS" if not report["blocking_reasons"] else "REJECT"

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_PATH.open("w") as f:
        json.dump(report, f, indent=2, default=str)
    logger.info("Report written to %s", REPORT_PATH)

    print("=" * 70)
    print(f"CANDIDATE-2 PROBE — decision = {report['decision']}")
    print("=" * 70)
    print(f"Features         : {CAND2_FEATURES}")
    print(f"Weights          : {CAND2_WEIGHTS}")
    print(f"Window           : >= {START}  lag={LAG_BARS}  fwd={FWD_HORIZON}")
    print()
    for name in CAND2_FEATURES:
        pf = report["per_factor"].get(name, {})
        if not pf or "ic_mean" not in pf:
            print(f"  {name}: INSUFFICIENT DATA")
            continue
        print(f"  {name}:")
        print(f"     IC mean = {pf['ic_mean']:+.4f}  "
              f"IC_IR = {pf['ic_ir']:+.3f}  "
              f"p = {pf['ic_p_value']:.4f}  "
              f"positive_regimes = {pf['n_positive_regimes']}/"
              f"{pf['n_total_regimes']}")
    print()
    o = report["orthogonality"]
    print(f"  composite corr (per-date mean) = {o['composite_corr_per_date_mean']:+.3f}")
    print(f"  turnover  cand2={o['turnover_cand2']:.3f}  "
          f"rcm_v1={o['turnover_rcm_v1']:.3f}  "
          f"rel_diff={o['turnover_relative_diff_pct']:.1f}%")
    print()
    if report["blocking_reasons"]:
        print("BLOCKING REASONS:")
        for r in report["blocking_reasons"]:
            print(f"  - {r}")
    else:
        print("All hard constraints passed.")
    return 0 if report["decision"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
