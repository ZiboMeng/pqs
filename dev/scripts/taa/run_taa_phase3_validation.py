"""PRD-E v1.1 Phase 3 validation acceptance run.

Loads partition_for_role(role="selector") panel (train + validation,
sealed excluded), runs TAA backtest with V1 + monthly cadence (the
PRD-E primary candidate spec), evaluates against PRD-E §5.3 hard gates
G1-G7 via taa_acceptance.evaluate_taa_acceptance.

Outputs:
  - data/audit/taa_phase3_validation.json (structured)
  - stdout summary with per-gate verdict

Phase 3 verdict logic (PRD §5.2 + §10):
  - All gates PASS → candidate ELIGIBLE for forward observation freeze;
    PRD-E2 separate scope must wire forward runner integration before
    actual freeze
  - Any HARD gate FAIL → close PRD-E with rejection memo (per PRD §10
    reversibility); not viable

Usage
-----
    python dev/scripts/taa/run_taa_phase3_validation.py
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

import numpy as np
import pandas as pd

from core.config.loader import load_config
from core.data.bar_store import BarStore
from core.regime.regime_detector import RegimeDetector
from core.research.risk_cluster_map import CROSS_ASSET_RISK_CLUSTER_MAP
from core.research.taa.regime_label_generator import daily_regime_labels
from core.research.taa.regime_rules import DEFAULT_TAA_RULES_V1
from core.research.taa.taa_acceptance import evaluate_taa_acceptance
from core.research.taa.taa_harness import run_taa_backtest
from core.research.temporal_split import (
    load_temporal_split,
    partition_for_role,
)


def _load_vix(path: Path = PROJ / "data/daily/_VIX.parquet") -> pd.Series:
    df = pd.read_parquet(path)
    return df["close"]


def _load_panel_selector():
    """Load full universe + filter to partition_for_role(role='selector')
    (train + validation; sealed excluded)."""
    cfg = load_config(PROJ / "config")
    store = BarStore(root=Path(cfg.system.paths.data_dir))
    uni = cfg.universe
    syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs)
        + list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    drop = {"BRK-B", "USO", "SLV"}
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
    split_cfg = load_temporal_split(PROJ / "config" / "temporal_split.yaml")
    panel = partition_for_role(panel, split_cfg, role="selector")
    return panel, split_cfg


def _spy_buy_hold_metrics(spy: pd.Series) -> Dict[str, float]:
    """Compute buy-and-hold SPY metrics (cum_ret/cagr/sharpe/max_dd/calmar)
    over the same window as the TAA backtest."""
    if spy is None or len(spy) < 2:
        return {}
    daily = spy.pct_change().fillna(0.0)
    cum_ret = float(spy.iloc[-1] / spy.iloc[0] - 1)
    n_years = (spy.index[-1] - spy.index[0]).days / 365.25
    cagr = float((spy.iloc[-1] / spy.iloc[0]) ** (1 / n_years) - 1) if n_years > 0 else 0.0
    sharpe = float(daily.mean() / daily.std() * np.sqrt(252)) if daily.std() > 1e-12 else 0.0
    peak = spy.cummax()
    max_dd = float(((spy - peak) / peak).min())
    calmar = cagr / abs(max_dd) if abs(max_dd) > 1e-9 else 0.0
    return {
        "cum_ret": cum_ret, "cagr": cagr, "sharpe": sharpe,
        "max_dd": max_dd, "calmar": calmar,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out-json",
                    default=str(PROJ / "data/audit/taa_phase3_validation.json"))
    args = ap.parse_args()

    print("Loading panel (partition_for_role role='selector')...")
    t0 = time.time()
    panel, split_cfg = _load_panel_selector()
    print(f"  panel: {panel['close'].shape[0]} dates × "
          f"{panel['close'].shape[1]} symbols ({time.time()-t0:.1f}s)")

    spy = panel["close"].get("SPY")
    qqq = panel["close"].get("QQQ")
    if spy is None:
        raise SystemExit("SPY missing from panel; cannot proceed")

    print("Loading VIX + classifying daily regimes...")
    vix = _load_vix()
    vix = vix.reindex(panel["close"].index, method="ffill").dropna()
    cfg = load_config(PROJ / "config")
    detector = RegimeDetector(config=cfg.regime)
    common = spy.index.intersection(vix.index)
    daily_labels = daily_regime_labels(
        spy=spy.loc[common], vix=vix.loc[common], detector=detector,
    )
    print(f"  daily_labels: {len(daily_labels)} rows")
    print(f"  regime distribution:")
    for state, count in daily_labels.value_counts().items():
        pct = 100 * count / len(daily_labels)
        print(f"    {state}: {count} ({pct:.1f}%)")

    universe = [s for s in panel["close"].columns if s not in ("SPY", "QQQ")]
    print(f"\nUniverse for TAA: {len(universe)} symbols")

    validation_years = sorted({vy.year for vy in split_cfg.partition.validation_years})
    stress_slices = {
        ss.name: (ss.start.isoformat(), ss.end.isoformat())
        for ss in split_cfg.partition.stress_slices
    }

    # Run V1 + monthly (PRD-E primary candidate spec)
    print("\n[V1 + monthly] running TAA backtest on selector panel...")
    t0 = time.time()
    result = run_taa_backtest(
        panel, daily_labels, DEFAULT_TAA_RULES_V1,
        universe=universe, cadence="MS", spy_series=spy,
        rule_set_name="v1",
        validation_years=validation_years, stress_slices=stress_slices,
    )
    print(f"  elapsed: {time.time()-t0:.1f}s")
    full = result.metrics_full_period
    print(f"  full period: cum_ret={full['cum_ret']:+.2%} "
          f"cagr={full['cagr']:+.2%} sharpe={full['sharpe']:.3f} "
          f"max_dd={full['max_dd']:.2%} calmar={full['calmar']:.3f}")
    print(f"  per-validation-year:")
    for y in sorted(result.metrics_per_validation_year.keys()):
        m = result.metrics_per_validation_year[y]
        print(f"    {y}: cum_ret={m.get('cum_ret', 0):+.2%} "
              f"vs_spy={m.get('vs_spy', 0):+.2%} "
              f"max_dd={m.get('max_dd', 0):.2%}")
    print(f"  stress slices:")
    for sname, sm in result.metrics_per_stress_slice.items():
        print(f"    {sname}: max_dd={sm.get('max_dd', 0):.2%}")
    print(f"  per-regime:")
    for state, rm in result.metrics_per_regime.items():
        print(f"    {state}: n_days={rm['n_days']} "
              f"max_dd={rm['max_dd']:.2%}")

    # Compute SPY buy-hold metrics over the SAME window as TAA NAV
    spy_aligned = spy.reindex(result.nav.index, method="ffill").dropna()
    spy_metrics = _spy_buy_hold_metrics(spy_aligned)
    print(f"\nSPY buy-hold (same window):")
    print(f"  cagr={spy_metrics['cagr']:+.2%} max_dd={spy_metrics['max_dd']:.2%} "
          f"calmar={spy_metrics['calmar']:.3f}")

    # Acceptance evaluation
    print("\n" + "=" * 60)
    print("PRD-E §5.3 Phase 3 acceptance gates")
    print("=" * 60)
    spy_returns = spy_aligned.pct_change().fillna(0.0)
    verdict = evaluate_taa_acceptance(
        result,
        spy_metrics_full_period=spy_metrics,
        spy_daily_returns=spy_returns,
        daily_regime_labels=daily_labels,
    )
    for g in verdict.gates:
        status = "PASS" if g.passed else "FAIL"
        val_str = ", ".join(f"{k}={v}" for k, v in g.values.items()
                            if not isinstance(v, list))
        print(f"  {g.name}: {status}")
        if val_str and len(val_str) < 200:
            print(f"      values: {val_str}")
        if not g.passed:
            print(f"      threshold: {g.threshold}")
            if g.notes:
                print(f"      notes: {g.notes}")

    print(f"\nOverall: {'PASS' if verdict.overall_passed else 'FAIL'} "
          f"({verdict.n_passed}/{verdict.n_total} gates)")
    if verdict.failed_gates:
        print(f"Failed gates: {verdict.failed_gates}")

    # Persist structured result
    out = {
        "lineage": "taa-phase3-validation-2026-05-06",
        "panel_n_dates": int(panel["close"].shape[0]),
        "panel_n_syms": int(panel["close"].shape[1]),
        "regime_distribution": daily_labels.value_counts().to_dict(),
        "spy_buy_hold_metrics": spy_metrics,
        "taa_metrics_full_period": dict(result.metrics_full_period),
        "taa_metrics_per_validation_year": {
            int(y): dict(m) for y, m in result.metrics_per_validation_year.items()
        },
        "taa_metrics_per_stress_slice": {
            k: dict(v) for k, v in result.metrics_per_stress_slice.items()
        },
        "taa_metrics_per_regime": {
            k: dict(v) for k, v in result.metrics_per_regime.items()
        },
        "rule_set": "v1",
        "cadence": "MS",
        "n_observed_days": result.n_observed_days,
        "acceptance": {
            "overall_passed": verdict.overall_passed,
            "n_passed": verdict.n_passed,
            "n_total": verdict.n_total,
            "failed_gates": verdict.failed_gates,
            "gates": [
                {"name": g.name, "passed": g.passed,
                 "values": g.values, "threshold": g.threshold,
                 "notes": g.notes}
                for g in verdict.gates
            ],
        },
    }
    out_path = Path(args.out_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nWrote {out_path}")
    return 0 if verdict.overall_passed else 1


if __name__ == "__main__":
    sys.exit(main())
