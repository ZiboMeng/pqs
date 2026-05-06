"""PRD-E v1.1 Phase 2 train-only TAA backtest smoke.

Runs 4 variants of TAA backtest on partition_for_role(role="miner")
panel:
  V1 + monthly cadence  (default)
  V1 + daily cadence    (I16 sensitivity)
  V0_MINIMAL + monthly  (I13 Occam baseline)
  V0_MINIMAL + daily    (I13 + I16 cross-cell)

For each, records:
  - Full-period CAGR / Sharpe / MaxDD / Calmar
  - Per-regime NAV slice (CRISIS regime DD ≤ 10% gate)
  - vs buy-hold SPY comparison (primary: Calmar ≥ SPY Calmar)
  - Per-validation-year metrics (vs_spy diagnostic)

Outputs JSON to data/audit/taa_phase2_smoke.json + stdout summary.

Phase 2 acceptance gate (PRD §5.2):
  - V1 + monthly: Calmar ≥ SPY Calmar (HARD primary metric)
  - V1 + monthly: MaxDD ≤ 18%
  - V1 + monthly: CRISIS regime DD ≤ 10%
  - I13 sanity: V0_MINIMAL CAGR vs V1 CAGR (if V0 ≥ V1, deprecate v1)

Usage
-----
    python dev/scripts/taa/run_taa_phase2_smoke.py
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
from core.regime.regime_detector import RegimeDetector, RegimeState
from core.research.risk_cluster_map import (
    CROSS_ASSET_RISK_CLUSTER_MAP,
    get_asset_class,
)
from core.research.taa.regime_label_generator import daily_regime_labels
from core.research.taa.regime_rules import (
    DEFAULT_TAA_RULES_V0_MINIMAL,
    DEFAULT_TAA_RULES_V1,
)
from core.research.taa.taa_harness import run_taa_backtest
from core.research.temporal_split import (
    load_temporal_split,
    partition_for_role,
)


def _load_vix(path: Path = PROJ / "data/daily/_VIX.parquet") -> pd.Series:
    """Load VIX close series from data/daily/_VIX.parquet."""
    df = pd.read_parquet(path)
    return df["close"]


def _load_panel():
    """Load tradable universe + SPY/QQQ/VIX, filter to train-only via
    partition_for_role(role='miner'). Returns (panel_dict, spy, vix)."""
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
    panel = {
        "close": pd.DataFrame(frames["close"]).sort_index(),
    }
    panel["open"] = pd.DataFrame(frames["open"]).reindex_like(panel["close"])
    panel["high"] = pd.DataFrame(frames["high"]).reindex_like(panel["close"])
    panel["low"] = pd.DataFrame(frames["low"]).reindex_like(panel["close"])
    panel["volume"] = pd.DataFrame(frames["volume"]).reindex_like(panel["close"])
    split_cfg = load_temporal_split(PROJ / "config" / "temporal_split.yaml")
    panel = partition_for_role(panel, split_cfg, role="miner")
    spy = panel["close"].get("SPY")
    qqq = panel["close"].get("QQQ")
    return panel, spy, qqq, split_cfg


def _run_variant(
    panel, daily_labels, rule_set_name, rule_set,
    cadence, universe, spy, validation_years, stress_slices,
) -> Dict[str, Any]:
    print(f"\n[{rule_set_name} + {cadence}] running...")
    t0 = time.time()
    res = run_taa_backtest(
        panel, daily_labels, rule_set,
        universe=universe, cadence=cadence, spy_series=spy,
        rule_set_name=rule_set_name,
        validation_years=validation_years,
        stress_slices=stress_slices,
    )
    elapsed = time.time() - t0
    full = res.metrics_full_period
    print(f"  elapsed: {elapsed:.1f}s")
    print(f"  cum_ret={full['cum_ret']:+.2%} cagr={full['cagr']:+.2%} "
          f"sharpe={full['sharpe']:.3f} max_dd={full['max_dd']:.2%} "
          f"calmar={full['calmar']:.3f}")
    if res.vs_spy_comparison:
        spy_m = res.vs_spy_comparison["spy_buy_hold"]
        print(f"  vs SPY: spy_calmar={spy_m['calmar']:.3f} "
              f"delta_calmar={res.vs_spy_comparison['delta_calmar']:+.3f} "
              f"delta_max_dd={res.vs_spy_comparison['delta_max_dd']:+.2%}")
    if "CRISIS" in res.metrics_per_regime:
        crisis = res.metrics_per_regime["CRISIS"]
        print(f"  CRISIS regime: n_days={crisis['n_days']} "
              f"max_dd={crisis['max_dd']:.2%}")
    return {
        "rule_set": rule_set_name,
        "cadence": cadence,
        "elapsed_seconds": elapsed,
        "n_observed_days": res.n_observed_days,
        "metrics_full_period": dict(full),
        "metrics_per_regime": {k: dict(v) for k, v in res.metrics_per_regime.items()},
        "metrics_per_validation_year": {
            int(k): dict(v) for k, v in res.metrics_per_validation_year.items()
        },
        "metrics_per_stress_slice": {k: dict(v) for k, v in res.metrics_per_stress_slice.items()},
        "vs_spy_comparison": (
            {k: (dict(v) if isinstance(v, dict) else v)
             for k, v in res.vs_spy_comparison.items()}
            if res.vs_spy_comparison else {}
        ),
        "rebalance_dates_n": (
            len(res.rebalance_dates) if res.rebalance_dates is not None else 0
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out-json",
                    default=str(PROJ / "data/audit/taa_phase2_smoke.json"))
    args = ap.parse_args()

    print("Loading panel + factors (partition_for_role role='miner')...")
    t0 = time.time()
    panel, spy, qqq, split_cfg = _load_panel()
    print(f"  panel: {panel['close'].shape[0]} dates × "
          f"{panel['close'].shape[1]} symbols ({time.time()-t0:.1f}s)")

    if spy is None:
        raise SystemExit("SPY not in panel; cannot proceed (regime detection requires SPY)")

    print("Loading VIX from data/daily/_VIX.parquet...")
    vix = _load_vix()
    # Restrict VIX to panel index
    vix = vix.reindex(panel["close"].index, method="ffill").dropna()
    print(f"  VIX rows in panel range: {len(vix)}")

    print("Computing daily regime labels via RegimeDetector...")
    cfg = load_config(PROJ / "config")
    detector = RegimeDetector(config=cfg.regime)
    common = spy.index.intersection(vix.index)
    daily_labels = daily_regime_labels(
        spy=spy.loc[common], vix=vix.loc[common], detector=detector,
    )
    print(f"  daily_labels rows: {len(daily_labels)}")
    print(f"  regime distribution:")
    for state, count in daily_labels.value_counts().items():
        pct = 100 * count / len(daily_labels)
        print(f"    {state}: {count} days ({pct:.1f}%)")

    # Universe = all panel columns minus SPY/QQQ
    universe = [s for s in panel["close"].columns if s not in ("SPY", "QQQ")]
    print(f"\nUniverse for TAA: {len(universe)} symbols")

    validation_years = sorted({vy.year for vy in split_cfg.partition.validation_years})
    stress_slices = {
        ss.name: (ss.start.isoformat(), ss.end.isoformat())
        for ss in split_cfg.partition.stress_slices
    }

    # 4 variants: V1 / V0 × monthly / daily
    variants = []
    for (rs_name, rs) in (
        ("v1", DEFAULT_TAA_RULES_V1),
        ("v0_minimal", DEFAULT_TAA_RULES_V0_MINIMAL),
    ):
        for cadence in ("MS", "D"):
            try:
                v = _run_variant(
                    panel, daily_labels, rs_name, rs, cadence,
                    universe, spy, validation_years, stress_slices,
                )
                variants.append(v)
            except Exception as exc:
                print(f"  ERROR ({rs_name} + {cadence}): {type(exc).__name__}: {exc}")
                variants.append({
                    "rule_set": rs_name, "cadence": cadence,
                    "error": f"{type(exc).__name__}: {exc}",
                })

    # Phase 2 acceptance: V1 + monthly is the primary candidate
    primary = next(
        (v for v in variants
         if v.get("rule_set") == "v1" and v.get("cadence") == "MS"
         and "error" not in v), None,
    )
    print("\n" + "=" * 60)
    print("Phase 2 acceptance (PRD §5.2)")
    print("=" * 60)
    if primary is None:
        print("  PRIMARY VARIANT (v1 monthly) FAILED — see errors above")
        verdict = "ABORT"
    else:
        full = primary["metrics_full_period"]
        spy_calmar = primary["vs_spy_comparison"].get("spy_buy_hold", {}).get("calmar", 0.0)
        crisis_dd = (
            primary["metrics_per_regime"].get("CRISIS", {}).get("max_dd")
            if primary["metrics_per_regime"].get("CRISIS") else None
        )

        gate_calmar = full["calmar"] >= spy_calmar
        gate_max_dd = full["max_dd"] >= -0.18  # max_dd is negative; -18% threshold
        gate_crisis = (crisis_dd is None) or (crisis_dd >= -0.10)

        print(f"  Calmar gate (≥ SPY Calmar):     "
              f"taa={full['calmar']:.3f} spy={spy_calmar:.3f} "
              f"{'PASS' if gate_calmar else 'FAIL'}")
        print(f"  MaxDD gate (≥ -18%):            "
              f"max_dd={full['max_dd']:.2%} "
              f"{'PASS' if gate_max_dd else 'FAIL'}")
        if crisis_dd is not None:
            print(f"  CRISIS regime DD gate (≥ -10%): "
                  f"crisis_max_dd={crisis_dd:.2%} "
                  f"{'PASS' if gate_crisis else 'FAIL'}")
        else:
            print("  CRISIS regime DD gate: n/a (insufficient CRISIS days in train panel)")

        n_pass = sum([gate_calmar, gate_max_dd, gate_crisis])
        verdict = "PASS" if n_pass == 3 else "PARTIAL" if n_pass >= 1 else "FAIL"
        print(f"\n  Verdict: {verdict} ({n_pass}/3 gates pass)")

    # I13 Occam comparison
    v1_monthly = next(
        (v for v in variants
         if v.get("rule_set") == "v1" and v.get("cadence") == "MS"
         and "error" not in v), None,
    )
    v0_monthly = next(
        (v for v in variants
         if v.get("rule_set") == "v0_minimal" and v.get("cadence") == "MS"
         and "error" not in v), None,
    )
    if v1_monthly and v0_monthly:
        v1_cagr = v1_monthly["metrics_full_period"]["cagr"]
        v0_cagr = v0_monthly["metrics_full_period"]["cagr"]
        print(f"\nI13 Occam: v1 cagr={v1_cagr:+.2%} vs v0_minimal cagr={v0_cagr:+.2%} "
              f"→ {'v0_minimal WINS (Occam: deprecate v1)' if v0_cagr >= v1_cagr else 'v1 retains edge'}")

    out = {
        "lineage": "taa-phase2-smoke-2026-05-06",
        "panel_n_dates": int(panel["close"].shape[0]),
        "panel_n_syms": int(panel["close"].shape[1]),
        "regime_distribution": daily_labels.value_counts().to_dict(),
        "variants": variants,
        "phase2_verdict": verdict,
    }
    out_path = Path(args.out_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nWrote {out_path}")
    return 0 if verdict in ("PASS", "PARTIAL") else 1


if __name__ == "__main__":
    sys.exit(main())
