#!/usr/bin/env python
"""Research-cycle closeout evaluator.

Given a pre-registered criteria yaml + a frozen S1-nominee candidate
spec, compute the full G2.A hard-requirements decision table + the
G2.B report-only fields, and write the artifacts the unfreeze memo §9
+ criteria yaml require for closeout:

  - candidate <id>_robustness_window.yaml
  - candidate <id>_robustness_eval.{json,md}
  - candidate <id>_concentration_report.{json,md}
  - candidate <id>_walk_forward.json
  - candidate <id>_pseudo_oos_2024.json
  - candidate <id>_regime_breakdown.json
  - candidate <id>_corr_vs_existing_pair.json
  - cycle <lineage>_closeout_eval.json (the decision table)

The closeout MEMO is written by hand using these JSONs; this script
only produces the numeric artifacts.

CLI:
    python dev/scripts/research_cycle/run_close_eval.py \\
        --criteria data/research_candidates/research-cycle-2026-04-26-01_promotion_criteria.yaml \\
        --candidate research-cycle-2026-04-26-01_top_trial_rejected_at_g2a
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from core.config.loader import load_config  # noqa: E402
from core.data.market_data_store import MarketDataStore  # noqa: E402
from core.factors.base_masks import (  # noqa: E402
    apply_research_mask,
    research_mask_default,
)
from core.factors.factor_generator import (  # noqa: E402
    compute_forward_returns,
    generate_all_factors,
)
from core.mining.research_miner import zscore_cs  # noqa: E402
from core.research.acceptance_helpers import (  # noqa: E402
    summarize_ic,
    walkforward_ic,
)
from core.research.concentration import (  # noqa: E402
    compute as compute_concentration,
    write_artifacts as write_concentration_artifacts,
)
from core.research.concentration.sector_map import SECTOR_MAP  # noqa: E402
from core.research.frozen_spec import FrozenStrategySpec  # noqa: E402
from core.research.robustness.runner import (  # noqa: E402
    DAILY_STORE_REBUILD_COMMIT,
    _data_integrity_snapshot,
    _format_eval_md,
)
from core.research.robustness.window_spec import (  # noqa: E402
    CandidateRobustnessWindow,
    EvidenceClass,
)


CANDIDATE_DIR = Path("data/research_candidates")
WATCH_PARQUET = Path("data/ref/data_quality_watch.parquet")

EXISTING_PAIR = [
    "rcm_v1_defensive_composite_01",
    "candidate_2_orthogonal_01",
]


# ── helpers ──────────────────────────────────────────────────────────


def _load_panel(cfg, store, end_ts: pd.Timestamp, drop_symbols=None):
    """Return {close, open, high, low, volume} for the universe at-or-before end_ts."""
    uni = cfg.universe
    syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs)
        + list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    tradable = [s for s in syms
                if s not in uni.blacklist and s not in uni.macro_reference]
    if drop_symbols:
        drop_set = set(drop_symbols)
        tradable = [s for s in tradable if s not in drop_set]
    frames = {k: {} for k in ("close", "open", "high", "low", "volume")}
    for sym in tradable:
        df = store.read(sym, "1d")
        if df is None or df.empty or "close" not in df.columns:
            continue
        frames["close"][sym] = df["close"]
        for col in ("open", "high", "low", "volume"):
            if col in df.columns:
                frames[col][sym] = df[col]
    out = {"close": pd.DataFrame(frames["close"]).sort_index()}
    for col in ("open", "high", "low", "volume"):
        if frames[col]:
            out[col] = pd.DataFrame(frames[col]).reindex_like(out["close"])
        else:
            out[col] = None
    if not out["close"].empty:
        mask = out["close"].index <= end_ts
        out["close"] = out["close"][mask]
        for col in ("open", "high", "low", "volume"):
            if out[col] is not None:
                out[col] = out[col].reindex(out["close"].index)
    return out, tradable


def _build_composite(spec: FrozenStrategySpec, frames: dict):
    close = frames["close"]
    benchmark_map = {b: close[b] for b in ("SPY", "QQQ") if b in close.columns}
    all_factors = generate_all_factors(
        close,
        volume_df=frames["volume"],
        open_df=frames["open"],
        high_df=frames["high"],
        low_df=frames["low"],
        benchmark_map=benchmark_map,
    )
    total_w = sum((f.weight or 0.0) for f in spec.feature_set) or 1.0
    composite = None
    for feat in spec.feature_set:
        panel = all_factors.get(feat.name)
        if panel is None:
            raise RuntimeError(f"Feature {feat.name} not produced by factor_generator")
        z = zscore_cs(panel, min_periods=5)
        comp = z * ((feat.weight or 0.0) / total_w)
        composite = comp if composite is None else composite.add(comp, fill_value=0.0)
    if frames["volume"] is not None:
        mask = research_mask_default(close, frames["volume"])
        composite = apply_research_mask(composite, mask)
    return composite, all_factors


def _ic_series(composite: pd.DataFrame, fwd: pd.DataFrame, lag: int = 1) -> pd.Series:
    """Per-date Spearman rank IC of lagged composite vs forward returns.

    `lag=1` shifts the composite forward so the IC at date T evaluates
    composite[T-1] vs fwd_return[T..T+H], preventing shared-close
    leakage (R15 semantics).
    """
    sig = composite.shift(lag)
    common_idx = sig.index.intersection(fwd.index)
    common_cols = sig.columns.intersection(fwd.columns)
    sig = sig.loc[common_idx, common_cols]
    fwd_a = fwd.loc[common_idx, common_cols]
    out = {}
    for d in common_idx:
        s = sig.loc[d].dropna()
        f = fwd_a.loc[d].dropna()
        shared = s.index.intersection(f.index)
        if len(shared) < 10:
            continue
        sr = s.loc[shared].rank()
        fr = f.loc[shared].rank()
        if sr.std() == 0 or fr.std() == 0:
            continue
        c = sr.corr(fr)
        if pd.notna(c):
            out[d] = float(c)
    return pd.Series(out, name="ic").sort_index()


def _composite_to_target_weights(composite: pd.DataFrame, top_n: int) -> pd.DataFrame:
    targets = pd.DataFrame(0.0, index=composite.index, columns=composite.columns)
    for d in composite.index:
        row = composite.loc[d].dropna()
        if len(row) < top_n:
            continue
        top = row.nlargest(top_n).index
        w = 1.0 / top_n
        for sym in top:
            targets.loc[d, sym] = w
    return targets


def _extract_beta_map(all_factors: dict) -> dict:
    panel = all_factors.get("beta_spy_60d")
    if panel is None or panel.empty:
        return {}
    last = panel.iloc[-1].dropna()
    return {str(s): float(v) for s, v in last.items()}


def _load_watch_symbols(watch_path: Path):
    if not watch_path.exists():
        return [], [], {}
    try:
        df = pd.read_parquet(watch_path)
    except Exception:
        return [], [], {}
    watch = df["symbol"].astype(str).tolist() if "symbol" in df.columns else []
    if "thin_data_pct" in df.columns:
        thin_mask = df["thin_data_pct"] > 0.0
        thin = df.loc[thin_mask, "symbol"].astype(str).tolist()
        pct = {
            str(r["symbol"]): float(r["thin_data_pct"]) / 100.0
            for _, r in df.iterrows()
            if pd.notna(r.get("thin_data_pct"))
        }
    else:
        thin, pct = [], {}
    return watch, thin, pct


def gate_check(name: str, measured, op: str, threshold) -> dict:
    """Evaluate a single G2.A hard gate against its measured value.

    Returns ``{gate, measured, op, threshold, passed}``. Public so the
    closeout decision table is unit-testable without running the full
    backtest pipeline.

    `op` values: ``"ge"``, ``"le"``, ``"in_set"``. Other ops raise.
    A ``None`` measured value never passes ``ge`` / ``le`` (we treat
    "no measurement" as a hard fail rather than silently passing).
    """
    if op == "ge":
        passed = (measured is not None) and (measured >= threshold)
    elif op == "le":
        passed = (measured is not None) and (measured <= threshold)
    elif op == "in_set":
        passed = measured in threshold
    else:
        raise ValueError(f"unknown gate op: {op!r}")
    return {
        "gate": name,
        "measured": measured,
        "op": op,
        "threshold": threshold,
        "passed": bool(passed),
    }


def build_decision_table(
    *,
    hard: dict,
    ic_ir_full_period,
    folds_positive: int,
    concentration_dict: dict,
) -> list:
    """Build the 7-row G2.A decision table for a candidate.

    Pure function — no I/O. Tests can construct synthetic inputs and
    assert pass/fail on each row without invoking the full eval
    pipeline.
    """
    rows = []
    rows.append(gate_check(
        "min_ic_ir_full_period",
        ic_ir_full_period,
        "ge",
        hard["min_ic_ir_full_period"],
    ))
    rows.append(gate_check(
        "min_walk_forward_folds_positive",
        folds_positive,
        "ge",
        hard["min_walk_forward_folds_positive"],
    ))
    rows.append(gate_check(
        "m12_concentration_tier",
        concentration_dict.get("tier"),
        "in_set",
        ["pass", "warning"]
        if hard["m12_concentration_tier_ceiling"] == "warning"
        else ["pass"],
    ))
    rows.append(gate_check(
        "watchlist_total_share",
        concentration_dict.get("watchlist_total_share"),
        "le",
        hard["watchlist_total_share_ceiling"],
    ))
    rows.append(gate_check(
        "thin_data_weighted_share",
        concentration_dict.get("thin_data_weighted_share"),
        "le",
        hard["thin_data_weighted_share_ceiling"],
    ))
    rows.append(gate_check(
        "top1_weight_max",
        concentration_dict.get("top1_weight_max"),
        "le",
        hard["top1_weight_max_ceiling"],
    ))
    rows.append(gate_check(
        "top3_weight_max",
        concentration_dict.get("top3_weight_max"),
        "le",
        hard["top3_weight_max_ceiling"],
    ))
    return rows


def _regime_for_date_index(idx: pd.DatetimeIndex, spy_close: pd.Series) -> pd.Series:
    """Lightweight 6-regime label series mapping each date to one of
    {BULL, BEAR, RISK_ON, RISK_OFF, CRISIS, SIDEWAYS}.

    Logic (post-2026-04-26 audit-light, criteria-aligned):
      - 60d SPY return r60, 60d daily-return std v60
      - DD = SPY.cummax() drawdown
      - DD ≤ -0.20 → CRISIS
      - r60 < q33 & v60 ≥ q66 → BEAR
      - r60 > q66 & v60 ≥ q66 → RISK_ON
      - r60 < q33 & v60 < q66 → RISK_OFF
      - r60 > q66 & v60 < q66 → BULL
      - otherwise → SIDEWAYS
    """
    if spy_close is None or len(spy_close) == 0:
        return pd.Series("SIDEWAYS", index=idx)
    r60 = spy_close.pct_change(60)
    v60 = spy_close.pct_change().rolling(60).std()
    cum = spy_close.cummax()
    dd = (spy_close - cum) / cum
    q_r = r60.quantile([0.33, 0.66])
    q_v = v60.quantile([0.66])
    labels = []
    for d in idx:
        r = r60.get(d, np.nan)
        v = v60.get(d, np.nan)
        ddv = dd.get(d, 0.0)
        if pd.isna(r) or pd.isna(v):
            labels.append("SIDEWAYS")
            continue
        if ddv <= -0.20:
            labels.append("CRISIS")
        elif r < q_r.iloc[0] and v >= q_v.iloc[0]:
            labels.append("BEAR")
        elif r > q_r.iloc[1] and v >= q_v.iloc[0]:
            labels.append("RISK_ON")
        elif r < q_r.iloc[0] and v < q_v.iloc[0]:
            labels.append("RISK_OFF")
        elif r > q_r.iloc[1] and v < q_v.iloc[0]:
            labels.append("BULL")
        else:
            labels.append("SIDEWAYS")
    return pd.Series(labels, index=idx)


def _composite_corr(composite_a: pd.DataFrame, composite_b: pd.DataFrame) -> float:
    """Cross-section average of per-date Pearson correlation between two composites."""
    common_idx = composite_a.index.intersection(composite_b.index)
    common_cols = composite_a.columns.intersection(composite_b.columns)
    a = composite_a.loc[common_idx, common_cols]
    b = composite_b.loc[common_idx, common_cols]
    corrs = []
    for d in common_idx:
        sa = a.loc[d].dropna()
        sb = b.loc[d].dropna()
        shared = sa.index.intersection(sb.index)
        if len(shared) < 10:
            continue
        c = sa.loc[shared].corr(sb.loc[shared])
        if pd.notna(c):
            corrs.append(c)
    return float(np.mean(corrs)) if corrs else float("nan")


def _sha256_of_file(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


# ── main pipeline ────────────────────────────────────────────────────


def run_close_eval(
    criteria_path: Path,
    candidate_id: str,
    output_dir: Path = CANDIDATE_DIR,
    horizon: int = 21,
    lag: int = 1,
    top_n: int = 10,
) -> dict:
    criteria = yaml.safe_load(criteria_path.read_text())
    lineage = criteria["lineage_tag"]
    panel_end = criteria["hard_requirements"]["panel_cutoff_max_date"]
    drop_symbols = criteria["hard_requirements"]["universe_panel_mask_spec"].get(
        "drop_symbols", []
    )
    pseudo_window = criteria["report_only"]["pseudo_oos_robustness_window"]
    pseudo_start = pseudo_window["window_start_target"]
    pseudo_end = pseudo_window["window_end_target"]

    spec_path = output_dir / f"{candidate_id}.yaml"
    spec = FrozenStrategySpec.from_yaml_file(spec_path)

    cfg = load_config()
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))

    # ── Construction window: 2007-01-02 → panel_end (G4) ─────────────
    print(f"[close-eval] loading construction panel ≤ {panel_end} ...", flush=True)
    cons_frames, _ = _load_panel(
        cfg, store, end_ts=pd.Timestamp(panel_end), drop_symbols=drop_symbols,
    )
    cons_close = cons_frames["close"]
    print(f"[close-eval]   panel: {cons_close.shape[0]} dates × {cons_close.shape[1]} symbols")

    # ── Construction-window composite + IC + walk-forward ────────────
    print("[close-eval] building composite + IC series ...", flush=True)
    cons_comp, cons_factors = _build_composite(spec, cons_frames)
    fwd_panel = compute_forward_returns(cons_close, horizons=[horizon], mode="cc")
    fwd = fwd_panel[horizon]
    ic_full = _ic_series(cons_comp, fwd, lag=lag)
    full_summary = summarize_ic(ic_full, horizon=horizon)
    walk = walkforward_ic(ic_full, horizon=horizon, n_folds=4, min_per_fold=50)
    folds_positive = sum(1 for f in walk if (f.get("ic_ir") or 0) > 0)
    walk_payload = {
        "candidate_id": candidate_id,
        "n_folds": len(walk),
        "folds_positive": folds_positive,
        "horizon": horizon,
        "lag": lag,
        "ic_full_period": full_summary,
        "folds": walk,
    }
    (output_dir / f"{candidate_id}_walk_forward.json").write_text(
        json.dumps(walk_payload, indent=2, default=str)
    )

    # ── Construction-window weights → concentration / watch / sector ──
    print("[close-eval] building target weights + concentration report ...", flush=True)
    target_wts = _composite_to_target_weights(cons_comp, top_n=top_n)
    beta_map = _extract_beta_map(cons_factors)
    watch_syms, thin_syms, thin_pct = _load_watch_symbols(WATCH_PARQUET)
    concentration = compute_concentration(
        candidate_id=candidate_id,
        weights_df=target_wts,
        watch_symbols=watch_syms,
        thin_data_symbols=thin_syms,
        thin_data_pct_map=thin_pct,
        sector_map=SECTOR_MAP,
        beta_map=beta_map,
    )
    write_concentration_artifacts(concentration, output_dir)

    # ── Robustness window artifact (label semantics) ─────────────────
    # The "robustness_window" yaml documents the window semantics. For
    # this candidate the meaningful window is the 2024 pseudo-OOS
    # holdout (G2.B). We write it as the pseudo_oos_robustness window.
    print("[close-eval] running pseudo-OOS 2024 holdout backtest ...", flush=True)
    pseudo_frames, _ = _load_panel(
        cfg, store, end_ts=pd.Timestamp(pseudo_end) + pd.Timedelta(days=2),
        drop_symbols=drop_symbols,
    )
    pseudo_close = pseudo_frames["close"]
    # Carve to exact 2024 window
    in_win = (pseudo_close.index >= pd.Timestamp(pseudo_start)) & (
        pseudo_close.index <= pd.Timestamp(pseudo_end)
    )
    win_idx = pseudo_close.index[in_win]
    if len(win_idx) == 0:
        raise RuntimeError(f"No trading days in {pseudo_start} → {pseudo_end}")
    actual_td = int(len(win_idx))
    pseudo_comp, _ = _build_composite(spec, pseudo_frames)
    pseudo_wts = _composite_to_target_weights(pseudo_comp, top_n=top_n)
    pseudo_wts = pseudo_wts.loc[(pseudo_wts.index >= pd.Timestamp(pseudo_start))
                                & (pseudo_wts.index <= pd.Timestamp(pseudo_end))]
    pseudo_close_win = pseudo_close.loc[(pseudo_close.index >= pd.Timestamp(pseudo_start))
                                        & (pseudo_close.index <= pd.Timestamp(pseudo_end))]
    pseudo_open = pseudo_frames["open"]
    pseudo_open_win = pseudo_open.loc[pseudo_close_win.index] if pseudo_open is not None else None

    from core.backtest.backtest_engine import BacktestEngine
    from core.execution.cost_model import CostModel
    cm = CostModel(cfg.cost_model)
    engine = BacktestEngine(cost_model=cm, initial_capital=100_000.0)
    res = engine.run(signals_df=pseudo_wts, price_df=pseudo_close_win, open_df=pseudo_open_win)

    eq = res.equity_curve
    ret = eq.pct_change().fillna(0.0)
    cum_ret = float(eq.iloc[-1] / eq.iloc[0] - 1.0) if len(eq) >= 2 else 0.0
    sharpe = float(ret.mean() / ret.std() * np.sqrt(252)) if ret.std() > 0 else 0.0
    cummax = eq.cummax()
    dd = (eq - cummax) / cummax
    max_dd = float(dd.min()) if len(dd) else 0.0

    def _bench_cum(sym: str):
        if sym not in pseudo_close_win.columns:
            return None
        s = pseudo_close_win[sym].dropna()
        if len(s) < 2:
            return None
        return float(s.iloc[-1] / s.iloc[0] - 1.0)

    spy_ret = _bench_cum("SPY")
    qqq_ret = _bench_cum("QQQ")
    diffs = pseudo_wts.diff().abs().sum(axis=1)
    turnover = float((diffs / 2.0).fillna(0.0).mean()) if len(diffs) else 0.0
    pseudo_metrics = {
        "cum_ret": cum_ret,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "vs_spy": (cum_ret - spy_ret) if spy_ret is not None else None,
        "vs_qqq": (cum_ret - qqq_ret) if qqq_ret is not None else None,
        "turnover_daily_mean": turnover,
        "fill_count": int(len(res.trades)) if res.trades else 0,
        "n_dates": int(len(eq)),
    }
    pseudo_payload = {
        "candidate_id": candidate_id,
        "evidence_class": "pseudo_oos_robustness",
        "window": {
            "start_date": pseudo_start,
            "end_date": pseudo_end,
            "actual_trading_days": actual_td,
            "target_trading_days": 252,
        },
        "metrics": pseudo_metrics,
        "note": (
            "2024 calendar year is genuinely OUTSIDE the construction window "
            "(panel_cutoff_max_date=2023-12-31). Still pseudo-OOS, NOT "
            "deployable OOS, per PRD v3 §1.1+§1.3."
        ),
    }
    (output_dir / f"{candidate_id}_pseudo_oos_2024.json").write_text(
        json.dumps(pseudo_payload, indent=2, default=str)
    )

    # Also emit the canonical robustness_window.yaml + .json + .md
    snapshot = _data_integrity_snapshot(None, "data/baseline/latest.json")
    win_obj = CandidateRobustnessWindow(
        candidate_id=candidate_id,
        evidence_class=EvidenceClass.pseudo_oos_robustness,
        start_date=date.fromisoformat(pseudo_start),
        end_date=date.fromisoformat(pseudo_end),
        actual_trading_days=actual_td,
        target_trading_days=252,
        shrink_reason=None,
        data_integrity_snapshot=snapshot,
    )
    (output_dir / f"{candidate_id}_robustness_window.yaml").write_text(
        yaml.safe_dump(win_obj.model_dump(mode="json"), sort_keys=False)
    )
    (output_dir / f"{candidate_id}_robustness_eval.json").write_text(
        json.dumps({
            "candidate_id": candidate_id,
            "evidence_class": win_obj.evidence_class.value,
            "window": {
                "start_date": pseudo_start,
                "end_date": pseudo_end,
                "actual_trading_days": actual_td,
                "target_trading_days": 252,
            },
            "metrics": pseudo_metrics,
        }, indent=2, default=str)
    )
    (output_dir / f"{candidate_id}_robustness_eval.md").write_text(
        _format_eval_md(candidate_id, win_obj, pseudo_metrics)
    )

    # ── Per-regime IR breakdown ──────────────────────────────────────
    print("[close-eval] computing per-regime IR breakdown ...", flush=True)
    spy_for_regime = cons_close["SPY"] if "SPY" in cons_close.columns else None
    regimes = _regime_for_date_index(ic_full.index, spy_for_regime)
    regime_break = {}
    for reg in ["BULL", "BEAR", "RISK_ON", "RISK_OFF", "CRISIS", "SIDEWAYS"]:
        sub = ic_full[regimes == reg]
        regime_break[reg] = summarize_ic(sub, horizon=horizon)
    (output_dir / f"{candidate_id}_regime_breakdown.json").write_text(
        json.dumps({"candidate_id": candidate_id, "regimes": regime_break}, indent=2, default=str)
    )

    # ── Correlation vs existing pair ─────────────────────────────────
    print("[close-eval] computing correlation vs existing pair ...", flush=True)
    corr_payload = {"candidate_id": candidate_id, "corr_vs": {}}
    for other_id in EXISTING_PAIR:
        try:
            other_spec = FrozenStrategySpec.from_yaml_file(output_dir / f"{other_id}.yaml")
            other_comp, _ = _build_composite(other_spec, cons_frames)
            corr_payload["corr_vs"][other_id] = _composite_corr(cons_comp, other_comp)
        except Exception as e:
            corr_payload["corr_vs"][other_id] = f"error: {e}"
    (output_dir / f"{candidate_id}_corr_vs_existing_pair.json").write_text(
        json.dumps(corr_payload, indent=2, default=str)
    )

    # ── Beta statistics ──────────────────────────────────────────────
    last_betas = pd.Series(beta_map)
    # portfolio-weighted: average of last-row weights × beta
    last_wts = target_wts.iloc[-1]
    pw_mean = float(((last_wts * last_betas).sum()) / max(last_wts.sum(), 1e-12))
    pw_var = float(((last_wts * (last_betas - pw_mean) ** 2).sum())
                   / max(last_wts.sum(), 1e-12))
    pw_std = float(np.sqrt(pw_var))
    beta_stats = {
        "portfolio_weighted_mean_beta": pw_mean,
        "portfolio_weighted_std_beta": pw_std,
        "max_abs_per_symbol_beta": float(last_betas.abs().max()) if len(last_betas) else None,
        "n_symbols_with_beta": int(len(last_betas.dropna())),
    }

    # ── Cycle-level closeout decision table ──────────────────────────
    hard = criteria["hard_requirements"]
    conc_dict = concentration.to_dict()
    # Map concentration_gate_status enum value -> tier string for the gate.
    conc_dict["tier"] = conc_dict.get("concentration_gate_status")

    decision_rows = build_decision_table(
        hard=hard,
        ic_ir_full_period=full_summary.get("ic_ir"),
        folds_positive=folds_positive,
        concentration_dict=conc_dict,
    )
    all_pass = all(r["passed"] for r in decision_rows)

    closeout_payload = {
        "lineage_tag": lineage,
        "candidate_id": candidate_id,
        "criteria_path": str(criteria_path),
        "criteria_sha256": _sha256_of_file(criteria_path),
        "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
        "horizon": horizon,
        "lag": lag,
        "top_n_basket": top_n,
        "construction_panel": {
            "start_date": "2007-01-02",
            "end_date": panel_end,
            "n_dates": int(cons_close.shape[0]),
            "n_symbols": int(cons_close.shape[1]),
            "drop_symbols": list(drop_symbols),
        },
        "g2_a_decision_table": decision_rows,
        "g2_a_overall_pass": all_pass,
        "g2_b_report_only": {
            "regime_breakdown": regime_break,
            "benchmark_beta_statistics": beta_stats,
            "pseudo_oos_2024": pseudo_metrics,
            "turnover_full_period": float(target_wts.diff().abs().sum(axis=1).div(2.0).fillna(0).mean()),
            "correlation_vs_existing_pair": corr_payload["corr_vs"],
        },
        "concentration_report_summary": conc_dict,
    }
    out_close = output_dir / f"{lineage}_closeout_eval.json"
    out_close.write_text(json.dumps(closeout_payload, indent=2, default=str))
    print(f"\n[close-eval] G2.A overall pass: {all_pass}")
    for row in decision_rows:
        print(f"  {row['gate']:35s} measured={row['measured']!r:25s} {row['op']} {row['threshold']!r}: pass={row['passed']}")
    print(f"\n[close-eval] artifacts written to {output_dir}")
    print(f"[close-eval] closeout decision table: {out_close}")
    return closeout_payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--criteria", required=True, type=Path)
    parser.add_argument("--candidate", required=True, help="candidate_id")
    parser.add_argument("--horizon", type=int, default=21)
    parser.add_argument("--lag", type=int, default=1)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--output-dir", type=Path, default=CANDIDATE_DIR)
    args = parser.parse_args()
    run_close_eval(
        criteria_path=args.criteria,
        candidate_id=args.candidate,
        output_dir=args.output_dir,
        horizon=args.horizon,
        lag=args.lag,
        top_n=args.top_n,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
