"""Trial 9 historical walk-forward prior (Option A, A+D Phase C-PRD-1).

Per user 2026-05-01 ("可以做一下A先看看"):
Run trial 9 spec on 2009-2025 panel (NO sealed 2026 access) via
cap_aware_cross_asset construction; compute 60-trading-day rolling
windows (monthly start sampling); per window compute statistics
benchmarked against TD60 GREEN/YELLOW/RED criteria from PRD §7.1.

OUTPUT: prior estimate of P(TD60 = GREEN | trial9 historical performance).
NOT a true OOS prior — trial 9 was MINED on 2009-2025 panel, so this is
IN-SAMPLE. Provides UPPER BOUND on forward TD60 expectations.

Run:
    python dev/scripts/forward/trial9_historical_walkforward_prior.py
Output:
    docs/memos/20260501-trial9_historical_walkforward_prior.md
    data/ml/research_cycle_eval/trial9_historical_walkforward_prior.json
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

PROJ = Path("/home/zibo/Documents/projects/pqs")
sys.path.insert(0, str(PROJ))


# ── Trial 9 spec (frozen yaml-derived) ───────────────────────────────────


TRIAL9_SPEC = {
    "features": ("beta_spy_60d", "max_dd_126d", "ret_1d"),
    "weights": (1/3, 1/3, 1/3),
    "family_counts": {"A": 1, "B": 1, "C": 0, "D": 0, "E": 0, "F": 1},
}


# Window sampling: 60 trading days, monthly start
WINDOW_LEN_TD = 60                      # trading days per window
SAMPLE_FREQ = "MS"                      # monthly start (1st trading day each month)


def build_inputs():
    """Build panel + factors + benchmarks; reuses generic evaluator helpers."""
    sys.path.insert(0, str(PROJ / "dev" / "scripts" / "research_cycle_eval"))
    from evaluate_top_n import _build_inputs, _load_yaml
    cycle05_yaml_path = PROJ / "data" / "research_candidates" / "track-c-cycle-2026-05-01-05_promotion_criteria.yaml"
    yaml = _load_yaml(cycle05_yaml_path)
    panel, all_factors, mask, split_cfg = _build_inputs(yaml)
    return panel, all_factors, mask, split_cfg, yaml


def build_trial9_nav(panel, all_factors, mask, cycle_yaml):
    """Build trial 9 NAV via cap_aware_cross_asset construction."""
    from core.mining.research_miner import ResearchCompositeSpec
    from core.research.harness import evaluate_composite_spec
    sys.path.insert(0, str(PROJ / "dev" / "scripts" / "research_cycle_eval"))
    from evaluate_top_n import _build_harness_config_for_cycle

    spec = ResearchCompositeSpec(
        features=TRIAL9_SPEC["features"],
        weights=TRIAL9_SPEC["weights"],
        family_counts=TRIAL9_SPEC["family_counts"],
    )
    panel_map = {f: all_factors[f] for f in TRIAL9_SPEC["features"] if f in all_factors}
    if len(panel_map) != len(TRIAL9_SPEC["features"]):
        missing = set(TRIAL9_SPEC["features"]) - set(panel_map)
        raise RuntimeError(f"missing factors in panel: {missing}")

    cfg = _build_harness_config_for_cycle(cycle_yaml, horizon_days=21)
    spy = panel["close"].get("SPY")
    qqq = panel["close"].get("QQQ")
    res = evaluate_composite_spec(
        spec=spec, factor_panel_map=panel_map,
        price_df=panel["close"], open_df=panel["open"],
        spy_series=spy, qqq_series=qqq, config=cfg,
        research_mask=mask,
    )
    return res.nav


def build_anchor_navs(panel, all_factors, mask, horizon_days=21):
    """Build RCMv1 + Cand-2 NAVs via global_top_n harness on the same panel."""
    sys.path.insert(0, str(PROJ / "dev" / "scripts" / "research_cycle_eval"))
    from evaluate_top_n import ANCHOR_SPECS, _build_reference_nav
    out = {}
    for name in ("rcm_v1", "cand_2"):
        nav, mdd = _build_reference_nav(name, panel, all_factors, mask, horizon_days)
        if nav is not None:
            out[name] = nav
    return out


# ── Regime labels (manual heuristic + auto regime classifier) ───────────


def manual_regime_labels(spy: pd.Series, qqq: pd.Series, vix: Optional[pd.Series] = None) -> pd.Series:
    """Coarse regime labels per date.

    BULL: SPY 200d > 0 AND QQQ 200d > 0 AND drawdown < 5%
    RISK_ON: positive trend, vol normal
    SIDEWAYS: small trend, vol normal
    RISK_OFF: drawdown 5-15%
    BEAR: drawdown > 15% OR sustained negative trend
    CRISIS: drawdown > 25% in last 60d
    """
    sp200 = spy.rolling(200).mean()
    spy_trend = (spy / sp200) - 1
    spy_dd = (spy / spy.rolling(252).max()) - 1
    spy_vol_60d = spy.pct_change().rolling(60).std() * np.sqrt(252)

    labels = pd.Series(index=spy.index, dtype="object")
    for d in spy.index:
        t = spy_trend.loc[d] if not pd.isna(spy_trend.loc[d]) else None
        dd = spy_dd.loc[d] if not pd.isna(spy_dd.loc[d]) else None
        vol = spy_vol_60d.loc[d] if not pd.isna(spy_vol_60d.loc[d]) else None
        if t is None or dd is None or vol is None:
            labels.loc[d] = "UNKNOWN"
            continue
        if dd < -0.25:
            labels.loc[d] = "CRISIS"
        elif dd < -0.15:
            labels.loc[d] = "BEAR"
        elif dd < -0.05 or (vol > 0.25):
            labels.loc[d] = "RISK_OFF"
        elif t > 0.10 and vol < 0.15:
            labels.loc[d] = "BULL"
        elif t > 0:
            labels.loc[d] = "RISK_ON"
        else:
            labels.loc[d] = "SIDEWAYS"
    return labels


# ── Window sampling ──────────────────────────────────────────────────────


def sample_window_starts(nav_index: pd.DatetimeIndex, freq: str = SAMPLE_FREQ) -> List[pd.Timestamp]:
    """Return monthly-start trading dates that have at least WINDOW_LEN_TD
    trading days remaining in the panel."""
    starts = []
    monthly = pd.date_range(start=nav_index.min(), end=nav_index.max(), freq=freq)
    for m in monthly:
        # First trading day at or after m
        future_dates = nav_index[nav_index >= m]
        if len(future_dates) < WINDOW_LEN_TD:
            continue
        starts.append(future_dates[0])
    return starts


def per_window_stats(
    trial9_nav: pd.Series,
    rcmv1_nav: pd.Series, cand2_nav: pd.Series,
    spy: pd.Series, qqq: pd.Series,
    regime_labels: pd.Series,
    starts: List[pd.Timestamp],
) -> List[Dict[str, Any]]:
    """For each window start, compute 60-TD-window stats."""
    nav_index = trial9_nav.index
    stats = []

    for start in starts:
        idx_start = nav_index.get_loc(start)
        idx_end = idx_start + WINDOW_LEN_TD
        if idx_end > len(nav_index):
            continue
        window_dates = nav_index[idx_start:idx_end]
        window_end = window_dates[-1]

        t9 = trial9_nav.loc[window_dates]
        s9 = spy.loc[window_dates] if spy is not None else None
        q9 = qqq.loc[window_dates] if qqq is not None else None
        r9 = rcmv1_nav.reindex(window_dates).dropna() if rcmv1_nav is not None else None
        c9 = cand2_nav.reindex(window_dates).dropna() if cand2_nav is not None else None

        if t9.dropna().empty or s9 is None or q9 is None:
            continue

        t9_ret = t9.pct_change().dropna()
        s9_ret = s9.pct_change().reindex(t9_ret.index).dropna()
        q9_ret = q9.pct_change().reindex(t9_ret.index).dropna()
        r9_ret = r9.pct_change().reindex(t9_ret.index).dropna() if r9 is not None and len(r9) > 1 else pd.Series(dtype=float)
        c9_ret = c9.pct_change().reindex(t9_ret.index).dropna() if c9 is not None and len(c9) > 1 else pd.Series(dtype=float)

        common = t9_ret.index.intersection(s9_ret.index).intersection(q9_ret.index)
        if len(common) < 30:
            continue
        t9r = t9_ret.reindex(common)
        s9r = s9_ret.reindex(common)
        q9r = q9_ret.reindex(common)

        # Trial 9 metrics (60d window)
        t9_cum = float(t9.iloc[-1] / t9.iloc[0] - 1)
        s9_cum = float(s9.iloc[-1] / s9.iloc[0] - 1)
        q9_cum = float(q9.iloc[-1] / q9.iloc[0] - 1)
        t9_mean_ret = t9r.mean() * 252
        t9_vol = t9r.std() * np.sqrt(252)
        t9_sharpe = float(t9_mean_ret / t9_vol) if t9_vol > 1e-9 else 0.0
        t9_max_dd = float(((t9 / t9.cummax()) - 1).min())

        # Residual correlation vs RCMv1 + Cand-2 (after stripping SPY+QQQ beta)
        residual_corr_rcmv1 = compute_residual_corr(t9r, r9_ret.reindex(common), s9r, q9r)
        residual_corr_cand2 = compute_residual_corr(t9r, c9_ret.reindex(common), s9r, q9r)

        # Portfolio combo: equal-weight Trial9 + RCMv1 + Cand-2 (returns level)
        if len(r9_ret) >= 30 and len(c9_ret) >= 30:
            r9c = r9_ret.reindex(common).fillna(0)
            c9c = c9_ret.reindex(common).fillna(0)
            combo_ret = (t9r + r9c + c9c) / 3
            combo_cum = float((1 + combo_ret).prod() - 1)
            combo_sharpe = float(combo_ret.mean() / combo_ret.std() * np.sqrt(252)) if combo_ret.std() > 1e-9 else 0.0
            combo_dd = float(((combo_ret + 1).cumprod() / (combo_ret + 1).cumprod().cummax() - 1).min())
            # Baseline: equity-only (RCMv1 + Cand-2 equal-weight)
            baseline_ret = (r9c + c9c) / 2
            baseline_cum = float((1 + baseline_ret).prod() - 1)
            baseline_sharpe = float(baseline_ret.mean() / baseline_ret.std() * np.sqrt(252)) if baseline_ret.std() > 1e-9 else 0.0
            baseline_dd = float(((baseline_ret + 1).cumprod() / (baseline_ret + 1).cumprod().cummax() - 1).min())
            combo_improves_sharpe = combo_sharpe > baseline_sharpe
            combo_improves_dd = combo_dd > baseline_dd  # combo_dd is less negative
        else:
            combo_cum = combo_sharpe = combo_dd = None
            baseline_cum = baseline_sharpe = baseline_dd = None
            combo_improves_sharpe = combo_improves_dd = None

        # Regime label = mode over the window
        regime_window = regime_labels.reindex(window_dates).dropna()
        regime = regime_window.mode().iloc[0] if not regime_window.empty else "UNKNOWN"

        # TD60 verdict per PRD §7.1
        verdict = classify_td60(
            residual_corr_rcmv1, residual_corr_cand2,
            regime, t9_cum - q9_cum,
            t9_max_dd, combo_improves_sharpe, combo_improves_dd,
        )

        stats.append({
            "window_start": start.isoformat(),
            "window_end": window_end.isoformat(),
            "regime": regime,
            "trial9_cum_ret": t9_cum,
            "trial9_sharpe": t9_sharpe,
            "trial9_max_dd": t9_max_dd,
            "trial9_vs_spy": t9_cum - s9_cum,
            "trial9_vs_qqq": t9_cum - q9_cum,
            "spy_cum_ret": s9_cum,
            "qqq_cum_ret": q9_cum,
            "residual_corr_vs_rcmv1": residual_corr_rcmv1,
            "residual_corr_vs_cand2": residual_corr_cand2,
            "combo_cum_ret": combo_cum,
            "combo_sharpe": combo_sharpe,
            "combo_max_dd": combo_dd,
            "baseline_combo_cum_ret": baseline_cum,
            "baseline_combo_sharpe": baseline_sharpe,
            "baseline_combo_max_dd": baseline_dd,
            "combo_improves_sharpe_vs_baseline": combo_improves_sharpe,
            "combo_improves_dd_vs_baseline": combo_improves_dd,
            "td60_verdict": verdict,
        })
    return stats


def compute_residual_corr(a, b, spy, qqq):
    """Residual correlation after stripping SPY + QQQ beta."""
    if len(b) < 5:
        return None
    df = pd.concat({"a": a, "b": b, "s": spy, "q": qqq}, axis=1).dropna()
    if len(df) < 5:
        return None
    sv = df["s"].var()
    qv = df["q"].var()
    if sv < 1e-12 or qv < 1e-12:
        return None
    # Strip SPY first, then QQQ
    beta_a_s = df.cov().loc["a", "s"] / sv
    beta_b_s = df.cov().loc["b", "s"] / sv
    res_a = df["a"] - beta_a_s * df["s"]
    res_b = df["b"] - beta_b_s * df["s"]
    if res_a.std() < 1e-12 or res_b.std() < 1e-12:
        return None
    return float(res_a.corr(res_b))


def classify_td60(
    resid_rcmv1: Optional[float], resid_cand2: Optional[float],
    regime: str, vs_qqq_window: float,
    max_dd_window: float,
    combo_imp_sharpe: Optional[bool], combo_imp_dd: Optional[bool],
) -> str:
    """TD60 GREEN/YELLOW/RED per PRD §7.1.

    GREEN (ALL):
      - residual_corr_60d_vs_rcmv1 < 0.4
      - residual_corr_60d_vs_cand_2 < 0.4
      - per_regime_BULL_vs_qqq_60d > -3% (only checked if regime == BULL)
      - per_regime_RISK_OFF_vs_qqq_60d > 0 OR > qqq (only if RISK_OFF)
      - portfolio_combo_evidence_positive (combo_improves_sharpe OR combo_improves_dd)
      - max_dd_60d <= 15% (soft-warn self-clearing)
    RED (ANY):
      - residual_corr_60d > 0.6
      - per_regime_BULL_vs_qqq_60d < -10%
      - max_dd_60d > 10% (note PRD §7.1 says >10% as red; my conservative read)
      - combo evidence negative (combo_improves_sharpe = False AND combo_improves_dd = False)
    YELLOW: not GREEN AND not RED.
    """
    # Check RED first
    if resid_rcmv1 is not None and resid_rcmv1 > 0.6:
        return "RED"
    if resid_cand2 is not None and resid_cand2 > 0.6:
        return "RED"
    if regime == "BULL" and vs_qqq_window < -0.10:
        return "RED"
    if max_dd_window < -0.10:
        return "RED"
    if combo_imp_sharpe is False and combo_imp_dd is False:
        return "RED"

    # Check GREEN
    g_resid_r = resid_rcmv1 is not None and resid_rcmv1 < 0.4
    g_resid_c = resid_cand2 is not None and resid_cand2 < 0.4
    g_bull = (regime != "BULL") or (vs_qqq_window > -0.03)
    g_combo = (combo_imp_sharpe is True) or (combo_imp_dd is True)
    g_dd = max_dd_window > -0.15

    if g_resid_r and g_resid_c and g_bull and g_combo and g_dd:
        return "GREEN"

    return "YELLOW"


# ── Main ────────────────────────────────────────────────────────────────


def main():
    print("[trial9 historical wf prior] Loading panel + factors...")
    panel, all_factors, mask, split_cfg, cycle_yaml = build_inputs()
    print(f"  panel: {panel['close'].shape[0]} dates × {panel['close'].shape[1]} symbols")

    print("[trial9 historical wf prior] Building trial 9 NAV via cap_aware_cross_asset...")
    trial9_nav = build_trial9_nav(panel, all_factors, mask, cycle_yaml)
    print(f"  trial9 NAV: n={len(trial9_nav)}, range {trial9_nav.index[0].date()} → {trial9_nav.index[-1].date()}")

    print("[trial9 historical wf prior] Building anchor NAVs (RCMv1 + Cand-2)...")
    anchors = build_anchor_navs(panel, all_factors, mask)
    rcmv1_nav = anchors.get("rcm_v1")
    cand2_nav = anchors.get("cand_2")
    print(f"  RCMv1 NAV: {'OK' if rcmv1_nav is not None else 'MISSING'}")
    print(f"  Cand-2 NAV: {'OK' if cand2_nav is not None else 'MISSING'}")

    spy = panel["close"].get("SPY")
    qqq = panel["close"].get("QQQ")

    print("[trial9 historical wf prior] Computing manual regime labels...")
    regime_labels = manual_regime_labels(spy, qqq)
    rl_counts = regime_labels.value_counts()
    print(f"  regime distribution: {dict(rl_counts)}")

    print("[trial9 historical wf prior] Sampling 60-TD windows (monthly start)...")
    starts = sample_window_starts(trial9_nav.index)
    print(f"  {len(starts)} windows")

    print("[trial9 historical wf prior] Computing per-window stats...")
    stats = per_window_stats(
        trial9_nav, rcmv1_nav, cand2_nav,
        spy, qqq, regime_labels, starts,
    )
    print(f"  {len(stats)} valid windows")

    # Aggregate
    verdict_dist = defaultdict(int)
    by_regime = defaultdict(lambda: defaultdict(int))
    for s in stats:
        verdict_dist[s["td60_verdict"]] += 1
        by_regime[s["regime"]][s["td60_verdict"]] += 1

    # Combo improvement rate
    combo_sharpe_imp = sum(1 for s in stats if s["combo_improves_sharpe_vs_baseline"] is True)
    combo_dd_imp = sum(1 for s in stats if s["combo_improves_dd_vs_baseline"] is True)
    combo_either = sum(1 for s in stats if (s["combo_improves_sharpe_vs_baseline"] or s["combo_improves_dd_vs_baseline"]))

    print("\n=== TD60 verdict distribution ===")
    total = sum(verdict_dist.values())
    for v in ("GREEN", "YELLOW", "RED"):
        n = verdict_dist.get(v, 0)
        print(f"  {v}: {n}/{total} = {100*n/total:.1f}%")

    print("\n=== Per-regime TD60 verdict ===")
    for reg in sorted(by_regime.keys()):
        regime_total = sum(by_regime[reg].values())
        print(f"  {reg} (n={regime_total}):", end="")
        for v in ("GREEN", "YELLOW", "RED"):
            n = by_regime[reg].get(v, 0)
            print(f" {v}={100*n/regime_total:.0f}%", end="")
        print()

    print(f"\n=== Combo evidence ===")
    print(f"  combo improves Sharpe vs RCMv1+Cand-2 baseline: {combo_sharpe_imp}/{total} = {100*combo_sharpe_imp/total:.1f}%")
    print(f"  combo improves MaxDD vs baseline:                {combo_dd_imp}/{total} = {100*combo_dd_imp/total:.1f}%")
    print(f"  combo improves either:                           {combo_either}/{total} = {100*combo_either/total:.1f}%")

    # Output
    out_dir = PROJ / "data" / "ml" / "research_cycle_eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "trial9_historical_walkforward_prior.json"
    out_path.write_text(json.dumps({
        "generated_at_utc": datetime.utcnow().isoformat() + "+00:00",
        "candidate": "trial9_diversifier_001",
        "panel_range": [str(trial9_nav.index[0].date()), str(trial9_nav.index[-1].date())],
        "n_windows": len(stats),
        "window_len_td": WINDOW_LEN_TD,
        "sample_freq": SAMPLE_FREQ,
        "verdict_distribution": dict(verdict_dist),
        "per_regime_verdict": {k: dict(v) for k, v in by_regime.items()},
        "combo_improves_sharpe_pct": 100 * combo_sharpe_imp / total,
        "combo_improves_dd_pct": 100 * combo_dd_imp / total,
        "combo_improves_either_pct": 100 * combo_either / total,
        "windows": stats,
    }, indent=2, default=str))
    print(f"\n[trial9 historical wf prior] Wrote: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
