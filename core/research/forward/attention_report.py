"""Forward attention check — derived metrics from forward observation manifests.

Phase C-PRD-1 follow-up. Produces per-checkpoint diagnostic reports for
TD20/TD40/TD60 milestones (and any intermediate TD if requested) on a
target candidate vs anchors. At TD60, classifies GREEN/YELLOW/RED per
PRD `docs/prd/20260501-two_stage_allocation_architecture_prd.md` §7.1.

Pure-compute module — reads forward manifests + BarStore daily prices,
emits structured `AttentionReport` dict. NO observe() side effects, NO
verdict-driven mutations. The attention check is a *diagnostic*, not a
state transition.

Public API:
  - load_nav_series(manifest)             → NAV time series + daily returns
  - compute_combo_nav(manifests, weights) → portfolio NAV from N candidates
  - compute_rolling_max_drawdown(nav, w)  → rolling-window MaxDD series
  - compute_residual_corr(...)            → residual NAV Pearson on shared window
  - compute_non_equity_exposure(manifest) → equity vs non-equity weight series
  - classify_td60_verdict(report)         → 'GREEN'/'YELLOW'/'RED'/'INSUFFICIENT'
  - generate_attention_report(...)        → top-level driver

Why pure-compute and not embedded in runner.observe():
  observe() must remain hermetic + idempotent (PRD F + R20 contract).
  Adding cross-candidate or rolling-window analysis there would bloat
  observe and entangle multi-candidate assumptions with single-candidate
  state. Attention check is OUTSIDE the observe loop.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timezone, datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# Hard runtime deps live behind a thin facade so this module is testable
# without pandas/numpy in trivial paths.
try:
    import numpy as np
    import pandas as pd
except ImportError as exc:  # pragma: no cover - hard dep
    raise ImportError(
        "core.research.forward.attention_report requires numpy + pandas; "
        "install via `pip install numpy pandas` or use the pqs conda env."
    ) from exc

from core.research.forward.manifest_schema import ForwardRunManifest


# ---------------------------------------------------------------------------
# NAV series extraction
# ---------------------------------------------------------------------------


def load_nav_series(manifest: ForwardRunManifest) -> "pd.DataFrame":
    """Build a daily NAV+return DataFrame from manifest.runs[].

    Returns a DataFrame indexed by `as_of_date` with columns:
      - cum_ret (raw from ForwardRun)
      - nav     = 1.0 + cum_ret  (NAV starting at 1.0)
      - daily_ret = nav.pct_change()  (NaN on first row)

    Skips DECIDE entries (synthetic, no NAV). Rows with cum_ret==None
    are dropped (incomplete observations). Output is sorted by date
    ascending and de-duplicated on date (last entry wins on conflict).
    """
    rows = []
    for r in manifest.runs:
        if r.cum_ret is None:
            continue
        if r.checkpoint_label == "DECIDE":
            continue
        rows.append({
            "as_of_date": r.as_of_date,
            "cum_ret": float(r.cum_ret),
            "checkpoint_label": r.checkpoint_label,
        })
    if not rows:
        return pd.DataFrame(columns=["cum_ret", "nav", "daily_ret"])
    df = pd.DataFrame(rows)
    df["as_of_date"] = pd.to_datetime(df["as_of_date"])
    df = df.sort_values("as_of_date").drop_duplicates("as_of_date", keep="last")
    df = df.set_index("as_of_date")
    df["nav"] = 1.0 + df["cum_ret"]
    df["daily_ret"] = df["nav"].pct_change()
    return df[["cum_ret", "nav", "daily_ret"]]


# ---------------------------------------------------------------------------
# Combo NAV (multi-candidate portfolio)
# ---------------------------------------------------------------------------


def compute_combo_nav(
    candidate_navs: Dict[str, "pd.DataFrame"],
    weights: Dict[str, float],
) -> "pd.DataFrame":
    """Build a weighted portfolio NAV over the intersection of candidate dates.

    Parameters
    ----------
    candidate_navs : dict[candidate_id → DataFrame from load_nav_series]
    weights : dict[candidate_id → weight]
        Must sum to 1.0 (within 1e-6). All candidate_ids in candidate_navs
        must be in weights.

    Returns
    -------
    DataFrame with same shape as load_nav_series output (indexed by date,
    columns: cum_ret / nav / daily_ret) but for the combo. Returns empty
    DataFrame if intersection of candidate date indices is empty.

    Raises
    ------
    ValueError if weights don't sum to 1.0 or candidate_ids mismatch.
    """
    if set(candidate_navs.keys()) != set(weights.keys()):
        raise ValueError(
            f"candidate_ids in nav dict {sorted(candidate_navs.keys())} "
            f"differ from weights dict {sorted(weights.keys())}"
        )
    w_sum = sum(weights.values())
    if not math.isclose(w_sum, 1.0, abs_tol=1e-6):
        raise ValueError(f"weights sum to {w_sum}, must be 1.0 (±1e-6)")
    # Align all NAVs on the intersection of dates
    rets = pd.DataFrame({cid: df["daily_ret"] for cid, df in candidate_navs.items()})
    rets = rets.dropna()  # require observation on all candidates that day
    if rets.empty:
        return pd.DataFrame(columns=["cum_ret", "nav", "daily_ret"])
    # Weighted daily return
    combo_ret = pd.Series(0.0, index=rets.index)
    for cid, w in weights.items():
        combo_ret = combo_ret + w * rets[cid]
    out = pd.DataFrame({"daily_ret": combo_ret})
    out["nav"] = (1.0 + combo_ret).cumprod()
    out["cum_ret"] = out["nav"] - 1.0
    return out[["cum_ret", "nav", "daily_ret"]]


# ---------------------------------------------------------------------------
# Rolling MaxDD (PRD §7.1 self-clearing condition)
# ---------------------------------------------------------------------------


def compute_rolling_max_drawdown(
    nav_series: "pd.Series",
    window: int,
) -> "pd.Series":
    """Compute rolling-window MaxDD over `window` trading days.

    For each day t, looks back [t-window+1, t] and computes:
      max_dd_t = min(NAV[i] / max(NAV[t-window+1..i]) - 1) for i in window

    Returns a Series of negative values (drawdown ≤ 0). NaN where the
    lookback window is incomplete.

    Used for D10c soft-warn self-clearing check: passes (clears) iff
    min(rolling_60d_maxdd) over last K days >= -0.15 (configurable).
    """
    if window < 2:
        raise ValueError(f"window must be >= 2; got {window}")
    if not isinstance(nav_series, pd.Series):
        nav_series = pd.Series(nav_series)
    out = pd.Series(index=nav_series.index, dtype=float)

    nav_arr = nav_series.values
    n = len(nav_arr)
    for t in range(window - 1, n):
        seg = nav_arr[t - window + 1: t + 1]
        running_max = np.maximum.accumulate(seg)
        dd = seg / running_max - 1.0
        out.iloc[t] = float(dd.min())
    return out


# ---------------------------------------------------------------------------
# Residual NAV correlation (regress out shared market beta)
# ---------------------------------------------------------------------------


def compute_residual_corr(
    candidate_returns: "pd.Series",
    anchor_returns: "pd.Series",
    benchmark_returns: "pd.Series",
) -> Optional[float]:
    """Pearson correlation of candidate vs anchor *after* regressing out benchmark.

    Steps:
      1. Align all 3 series on intersection of dates (drop NaN).
      2. For candidate and anchor independently, fit OLS:
           ret = α + β × benchmark + ε
      3. Compute Pearson(ε_candidate, ε_anchor).

    Returns None if fewer than 10 overlapping observations
    (insufficient for stable correlation estimate).

    Why residual instead of raw: long-only US-equity NAVs share market
    beta (~30% of correlation per cycle04 evidence). Residual strips
    this and exposes the *alpha-source* correlation that diversifier
    role actually cares about.
    """
    df = pd.DataFrame({
        "cand": candidate_returns,
        "anchor": anchor_returns,
        "bench": benchmark_returns,
    }).dropna()
    if len(df) < 10:
        return None

    def _residualize(y: "pd.Series", x: "pd.Series") -> "pd.Series":
        # y = a + b*x + ε ; return ε.
        # Closed-form OLS for 1 regressor.
        x_mean = x.mean()
        y_mean = y.mean()
        cov_xy = ((x - x_mean) * (y - y_mean)).sum()
        var_x = ((x - x_mean) ** 2).sum()
        if var_x == 0:
            # benchmark is constant — residual = y - mean(y)
            return y - y_mean
        beta = cov_xy / var_x
        alpha = y_mean - beta * x_mean
        return y - (alpha + beta * x)

    eps_cand = _residualize(df["cand"], df["bench"])
    eps_anchor = _residualize(df["anchor"], df["bench"])
    return float(eps_cand.corr(eps_anchor))


# ---------------------------------------------------------------------------
# Non-equity exposure (diversifier eligibility check)
# ---------------------------------------------------------------------------


def compute_non_equity_exposure(manifest: ForwardRunManifest) -> "pd.DataFrame":
    """Per-day equity vs non-equity weight breakdown from held_today_weights.

    Uses `core.research.risk_cluster_map.make_unified_cluster_map(include_cross_asset=True)`
    + `ASSET_CLASS_BY_CLUSTER`. Symbols not in the unified map are
    silently classified as 'unknown' (would never happen for trial 9
    spec which uses cap_aware_cross_asset).

    Returns DataFrame indexed by as_of_date with columns:
      - equity_weight, bond_weight, commodity_weight, cash_anchor_weight
      - non_equity_weight (= bond + commodity + cash_anchor)
      - unknown_weight   (NaN-flagged symbols; should be 0 in normal use)
    """
    from core.research.risk_cluster_map import (
        make_unified_cluster_map,
        ASSET_CLASS_BY_CLUSTER,
    )
    sym_to_cluster = make_unified_cluster_map(include_cross_asset=True)

    rows = []
    for r in manifest.runs:
        if r.checkpoint_label == "DECIDE":
            continue
        if not r.held_today_weights:
            continue
        bucket = {"equities": 0.0, "bonds": 0.0, "commodities": 0.0,
                  "cash_anchor": 0.0, "unknown": 0.0}
        for sym, w in r.held_today_weights.items():
            cluster = sym_to_cluster.get(sym)
            if cluster is None:
                bucket["unknown"] += float(w)
                continue
            asset_class = ASSET_CLASS_BY_CLUSTER.get(cluster, "unknown")
            bucket[asset_class] = bucket.get(asset_class, 0.0) + float(w)
        rows.append({
            "as_of_date": r.as_of_date,
            "equity_weight": bucket["equities"],
            "bond_weight": bucket["bonds"],
            "commodity_weight": bucket["commodities"],
            "cash_anchor_weight": bucket["cash_anchor"],
            "non_equity_weight": bucket["bonds"] + bucket["commodities"] + bucket["cash_anchor"],
            "unknown_weight": bucket["unknown"],
        })
    if not rows:
        cols = ["equity_weight", "bond_weight", "commodity_weight",
                "cash_anchor_weight", "non_equity_weight", "unknown_weight"]
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(rows)
    df["as_of_date"] = pd.to_datetime(df["as_of_date"])
    return df.set_index("as_of_date").sort_index()


# ---------------------------------------------------------------------------
# Verdict classifier
# ---------------------------------------------------------------------------


@dataclass
class TD60Verdict:
    """PRD §7.1 GREEN/YELLOW/RED verdict + reasoning.

    `label` = 'GREEN' / 'YELLOW' / 'RED' / 'INSUFFICIENT'
    `reasons` = list of strings describing which criteria triggered.
    `triggers` = dict mapping criterion → 'pass' / 'soft_fail' / 'hard_fail'
    """
    label: str
    reasons: List[str] = field(default_factory=list)
    triggers: Dict[str, str] = field(default_factory=dict)


def classify_td60_verdict(
    *,
    n_observed: int,
    residual_corr_max_vs_anchors: Optional[float],
    bull_vs_qqq_60d: Optional[float],
    portfolio_combo_positive: Optional[bool],
    soft_warn_cleared: Optional[bool],
    require_td_min: int = 60,
) -> TD60Verdict:
    """PRD §7.1 verdict classification.

    Hard rules (any RED → RED; else any YELLOW → YELLOW; else GREEN):

    GREEN  = residual_corr_max < 0.4
           AND bull_vs_qqq_60d > -0.03 (-3%)
           AND portfolio_combo_positive
           AND soft_warn_cleared

    YELLOW = residual in [0.4, 0.6]
           OR bull_vs_qqq_60d in [-0.10, -0.03]

    RED    = residual > 0.6
           OR bull_vs_qqq_60d < -0.10
           OR portfolio_combo_positive == False

    INSUFFICIENT = n_observed < require_td_min OR any required input is None
    """
    if n_observed < require_td_min:
        return TD60Verdict(
            label="INSUFFICIENT",
            reasons=[f"n_observed={n_observed} < require_td_min={require_td_min}"],
            triggers={},
        )
    missing = [
        name for name, val in (
            ("residual_corr_max_vs_anchors", residual_corr_max_vs_anchors),
            ("portfolio_combo_positive", portfolio_combo_positive),
            ("soft_warn_cleared", soft_warn_cleared),
        ) if val is None
    ]
    # bull_vs_qqq_60d may legitimately be None if no BULL window observed
    # in the TD60 sample — defer to YELLOW for missing regime evidence.
    if missing:
        return TD60Verdict(
            label="INSUFFICIENT",
            reasons=[f"missing inputs: {missing}"],
            triggers={},
        )

    triggers: Dict[str, str] = {}

    # Residual correlation
    if residual_corr_max_vs_anchors > 0.6:
        triggers["residual_corr"] = "hard_fail"
    elif residual_corr_max_vs_anchors >= 0.4:
        triggers["residual_corr"] = "soft_fail"
    else:
        triggers["residual_corr"] = "pass"

    # BULL vs QQQ
    if bull_vs_qqq_60d is None:
        triggers["bull_vs_qqq"] = "missing_regime"
    elif bull_vs_qqq_60d < -0.10:
        triggers["bull_vs_qqq"] = "hard_fail"
    elif bull_vs_qqq_60d <= -0.03:
        triggers["bull_vs_qqq"] = "soft_fail"
    else:
        triggers["bull_vs_qqq"] = "pass"

    # Portfolio combo
    triggers["portfolio_combo"] = "pass" if portfolio_combo_positive else "hard_fail"

    # Soft-warn self-clearing
    triggers["soft_warn_cleared"] = "pass" if soft_warn_cleared else "hard_fail"

    has_hard = any(v == "hard_fail" for v in triggers.values())
    has_soft = any(v == "soft_fail" for v in triggers.values())
    has_missing_regime = triggers.get("bull_vs_qqq") == "missing_regime"

    if has_hard:
        label = "RED"
    elif has_soft or has_missing_regime:
        label = "YELLOW"
    else:
        label = "GREEN"

    reasons = [f"{k}={v}" for k, v in sorted(triggers.items())]
    return TD60Verdict(label=label, reasons=reasons, triggers=triggers)


# ---------------------------------------------------------------------------
# Top-level driver
# ---------------------------------------------------------------------------


@dataclass
class AttentionReport:
    """Top-level structured report for a forward attention check.

    Fields:
      - generated_at_utc, candidate_id, anchor_ids
      - td_label (e.g. 'TD20'), n_observed
      - candidate_metrics: cum_ret / sharpe / max_dd / vs_spy / vs_qqq /
        rolling_60d_max_dd_min
      - residual_corrs: dict[anchor_id → residual Pearson]
      - non_equity_exposure: latest day breakdown + drift
      - combo_metrics: cum_ret / sharpe / max_dd of equal-weight combo
      - soft_warn_status: dict[label → cleared/active]
      - td60_verdict: TD60Verdict (only meaningful when n_observed >= 60)
      - notes: list of str diagnostic messages
    """
    generated_at_utc: str
    candidate_id: str
    anchor_ids: List[str]
    td_label: str
    n_observed: int
    candidate_metrics: Dict = field(default_factory=dict)
    residual_corrs: Dict[str, Optional[float]] = field(default_factory=dict)
    non_equity_exposure: Dict = field(default_factory=dict)
    combo_metrics: Dict = field(default_factory=dict)
    soft_warn_status: Dict[str, str] = field(default_factory=dict)
    td60_verdict: Optional[Dict] = None
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        d = {
            "generated_at_utc": self.generated_at_utc,
            "candidate_id": self.candidate_id,
            "anchor_ids": self.anchor_ids,
            "td_label": self.td_label,
            "n_observed": self.n_observed,
            "candidate_metrics": self.candidate_metrics,
            "residual_corrs": self.residual_corrs,
            "non_equity_exposure": self.non_equity_exposure,
            "combo_metrics": self.combo_metrics,
            "soft_warn_status": self.soft_warn_status,
            "td60_verdict": self.td60_verdict,
            "notes": self.notes,
        }
        return d


def _benchmark_daily_returns(
    benchmark_symbol: str,
    start_date,
    end_date,
) -> "pd.Series":
    """Load benchmark daily returns from BarStore over [start, end].

    Uses adjusted_total_return=True for like-with-like comparison
    against forward NAVs (which include splits + reinvested dividends).
    """
    from core.data.bar_store import BarStore
    bs = BarStore()
    bars = bs.load(benchmark_symbol, "1d", adjusted=True, adjusted_total_return=True)
    if not isinstance(bars.index, pd.DatetimeIndex):
        bars = bars.set_index(pd.to_datetime(bars.index))
    bars = bars.loc[(bars.index >= pd.Timestamp(start_date)) &
                    (bars.index <= pd.Timestamp(end_date))]
    bars = bars.sort_index()
    return bars["close"].astype(float).pct_change()


def generate_attention_report(
    *,
    candidate_manifest: ForwardRunManifest,
    anchor_manifests: Dict[str, ForwardRunManifest],
    td_label: Optional[str] = None,
    combo_weights: Optional[Dict[str, float]] = None,
    benchmark_symbol: str = "QQQ",
    soft_warn_clear_window: int = 60,
    soft_warn_clear_maxdd_threshold: float = -0.15,
) -> AttentionReport:
    """Top-level driver: builds full attention report.

    Parameters
    ----------
    candidate_manifest : the target candidate (e.g. trial 9)
    anchor_manifests : dict[anchor_id → ForwardRunManifest] (e.g.
        {RCMv1, Cand-2})
    td_label : optional override; default = derived from latest run's
        checkpoint_label, or 'TD0' if no runs yet
    combo_weights : default = equal weight across candidate + anchors
    benchmark_symbol : 'QQQ' (default) or 'SPY'; used for residual corr
        regression and BULL-window comparison
    soft_warn_clear_window / threshold : trial 9 D10c contract — 60d
        rolling max_dd ≤ 15% (= -0.15) clears the soft warn flag.

    Returns AttentionReport. Gracefully handles:
      - empty candidate manifest (n_observed=0, all metrics empty)
      - missing anchor data (residual_corr=None)
      - <60 TDs observed (verdict=INSUFFICIENT)
    """
    notes: List[str] = []
    cand_id = candidate_manifest.candidate_id
    anchor_ids = sorted(anchor_manifests.keys())

    # Step 1: NAV series
    cand_nav = load_nav_series(candidate_manifest)
    anchor_navs = {aid: load_nav_series(m) for aid, m in anchor_manifests.items()}

    n_observed = len(cand_nav)
    if td_label is None:
        td_label = f"TD{n_observed:03d}" if n_observed > 0 else "TD000"

    # Step 2: latest candidate metrics
    cand_metrics: Dict = {}
    if n_observed > 0:
        latest_run = max(
            (r for r in candidate_manifest.runs if r.cum_ret is not None),
            key=lambda r: r.as_of_date,
            default=None,
        )
        if latest_run is not None:
            cand_metrics = {
                "as_of_date": latest_run.as_of_date.isoformat(),
                "cum_ret": latest_run.cum_ret,
                "sharpe": latest_run.sharpe,
                "max_dd": latest_run.max_dd,
                "vs_spy": latest_run.vs_spy,
                "vs_qqq": latest_run.vs_qqq,
            }
        # Rolling 60d MaxDD min over last 60 obs
        if n_observed >= 60:
            r_dd = compute_rolling_max_drawdown(cand_nav["nav"], window=60)
            cand_metrics["rolling_60d_max_dd_min"] = float(r_dd.dropna().min())
        else:
            cand_metrics["rolling_60d_max_dd_min"] = None
            notes.append(
                f"n_observed={n_observed} < 60 — rolling_60d_max_dd not yet "
                f"computable; need {60 - n_observed} more TDs."
            )

    # Step 3: residual corr vs each anchor (uses benchmark for residualization)
    residual_corrs: Dict[str, Optional[float]] = {}
    if n_observed >= 10 and anchor_navs:
        bench_start = cand_nav.index.min()
        bench_end = cand_nav.index.max()
        try:
            bench_rets = _benchmark_daily_returns(benchmark_symbol, bench_start, bench_end)
        except Exception as exc:
            bench_rets = None
            notes.append(f"benchmark load failed: {exc}")
        if bench_rets is not None:
            for aid, anchor_df in anchor_navs.items():
                if anchor_df.empty or len(anchor_df) < 10:
                    residual_corrs[aid] = None
                    continue
                residual_corrs[aid] = compute_residual_corr(
                    cand_nav["daily_ret"],
                    anchor_df["daily_ret"],
                    bench_rets,
                )
    else:
        for aid in anchor_ids:
            residual_corrs[aid] = None
        if n_observed > 0:
            notes.append(
                f"n_observed={n_observed} < 10 — residual_corr not stable yet."
            )

    # Step 4: non-equity exposure
    nonequity_df = compute_non_equity_exposure(candidate_manifest)
    nonequity: Dict = {}
    if not nonequity_df.empty:
        latest = nonequity_df.iloc[-1]
        nonequity = {
            "as_of_date": nonequity_df.index[-1].date().isoformat(),
            "equity_weight": float(latest["equity_weight"]),
            "non_equity_weight": float(latest["non_equity_weight"]),
            "bond_weight": float(latest["bond_weight"]),
            "commodity_weight": float(latest["commodity_weight"]),
            "cash_anchor_weight": float(latest["cash_anchor_weight"]),
            "unknown_weight": float(latest["unknown_weight"]),
            "non_equity_weight_avg": float(nonequity_df["non_equity_weight"].mean()),
        }

    # Step 5: combo NAV (equal-weight default)
    combo: Dict = {}
    if combo_weights is None:
        all_ids = [cand_id] + anchor_ids
        combo_weights = {cid: 1.0 / len(all_ids) for cid in all_ids}
    all_navs = {cand_id: cand_nav, **anchor_navs}
    # Filter to candidates with any data
    all_navs = {cid: df for cid, df in all_navs.items() if not df.empty}
    valid_weights = {
        cid: combo_weights.get(cid, 0.0)
        for cid in all_navs.keys()
    }
    valid_sum = sum(valid_weights.values())
    if valid_sum > 0 and len(all_navs) >= 2:
        # Renormalize over candidates with data
        valid_weights = {cid: w / valid_sum for cid, w in valid_weights.items()}
        try:
            combo_df = compute_combo_nav(all_navs, valid_weights)
            if not combo_df.empty:
                combo = {
                    "weights": valid_weights,
                    "n_observed": len(combo_df),
                    "cum_ret_latest": float(combo_df["cum_ret"].iloc[-1]),
                    "max_dd_latest": float(
                        (combo_df["nav"] / combo_df["nav"].cummax() - 1.0).min()
                    ),
                }
        except ValueError as exc:
            notes.append(f"combo_nav failed: {exc}")

    # Step 6: soft-warn status check
    soft_warn_status: Dict[str, str] = {}
    for flag in candidate_manifest.soft_warn_flags:
        if flag == "diversifier_2025_maxdd_18_20pct":
            # D10c contract: 60d rolling max_dd ≤ -0.15 clears
            if (n_observed >= soft_warn_clear_window and
                cand_metrics.get("rolling_60d_max_dd_min") is not None and
                cand_metrics["rolling_60d_max_dd_min"] >= soft_warn_clear_maxdd_threshold):
                soft_warn_status[flag] = "cleared"
            elif n_observed >= soft_warn_clear_window:
                soft_warn_status[flag] = "active_uncleared"
            else:
                soft_warn_status[flag] = "pending_insufficient_data"
        else:
            soft_warn_status[flag] = "active_unknown_clear_rule"

    # Step 7: TD60 verdict (only meaningful at TD60+; otherwise INSUFFICIENT)
    verdict_dict = None
    if n_observed > 0:
        residual_max = None
        valid_residuals = [v for v in residual_corrs.values() if v is not None]
        if valid_residuals:
            residual_max = max(valid_residuals)
        portfolio_combo_positive = (
            combo.get("cum_ret_latest") is not None
            and combo["cum_ret_latest"] > 0
        ) if combo else None
        soft_warn_cleared = all(
            s == "cleared" for s in soft_warn_status.values()
        ) if soft_warn_status else True
        # bull_vs_qqq_60d: requires regime classification; deferred to
        # explicit caller. Pass None for now — verdict will treat as
        # missing_regime → YELLOW unless other hard fails dominate.
        verdict = classify_td60_verdict(
            n_observed=n_observed,
            residual_corr_max_vs_anchors=residual_max,
            bull_vs_qqq_60d=None,
            portfolio_combo_positive=portfolio_combo_positive,
            soft_warn_cleared=soft_warn_cleared,
        )
        verdict_dict = {
            "label": verdict.label,
            "reasons": verdict.reasons,
            "triggers": verdict.triggers,
        }

    return AttentionReport(
        generated_at_utc=datetime.now(timezone.utc).isoformat(),
        candidate_id=cand_id,
        anchor_ids=anchor_ids,
        td_label=td_label,
        n_observed=n_observed,
        candidate_metrics=cand_metrics,
        residual_corrs=residual_corrs,
        non_equity_exposure=nonequity,
        combo_metrics=combo,
        soft_warn_status=soft_warn_status,
        td60_verdict=verdict_dict,
        notes=notes,
    )
