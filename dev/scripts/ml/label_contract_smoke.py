#!/usr/bin/env python
"""P1 label-contract smoke — every canonical label mode is deterministic.

PRD docs/prd/20260521-rerisk-and-ml-training-audit-prd.md §12.3 Package
P1 gate: "all canonical label modes emit deterministic artifacts".

Runs each of the 5 canonical label modes declared in
`config/ml_labeling.yaml::label_modes` twice on a fixed synthetic panel
and records whether the two runs are byte-identical. Also confirms the
config is consumable (each mode's params are read from it).

Output: data/audit/ml_label_contract_smoke_<ts>.json

Usage: python dev/scripts/ml/label_contract_smoke.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from core.ml.labeling import triple_barrier_labels  # noqa: E402
from core.research.ml.labels import (  # noqa: E402
    make_residualized_quantile_labels,
    make_residualized_rank_labels,
)
from core.research.ml.sign_classifier import (  # noqa: E402
    compute_binary_sign_labels,
    compute_cost_aware_binary_labels,
)


def _synthetic_panel(n: int = 400, seed: int = 20260521):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-02", periods=n)
    mkt = rng.normal(0.0004, 0.011, n)
    market = pd.Series(100.0 * np.cumprod(1 + mkt), index=idx, name="MKT")
    cols = {}
    for i in range(8):
        ret = mkt + rng.normal(0.0, 0.006, n)
        cols[f"S{i}"] = 100.0 * np.cumprod(1 + ret)
    return pd.DataFrame(cols, index=idx), market


def _checksum(df: pd.DataFrame) -> float:
    """Order-stable numeric checksum (NaN-safe)."""
    arr = df.to_numpy(dtype=float)
    finite = arr[np.isfinite(arr)]
    return float(np.round(finite.sum(), 8)) if finite.size else 0.0


def _frames_identical(a: pd.DataFrame, b: pd.DataFrame) -> bool:
    return a.equals(b)   # pandas .equals treats NaN == NaN as equal


def main() -> int:
    cfg = yaml.safe_load((PROJ / "config/ml_labeling.yaml").read_text())
    modes = cfg["label_modes"]
    price, market = _synthetic_panel()
    print(f"=== P1 label-contract smoke  panel={price.shape} ===")

    results: dict = {}
    for name, m in modes.items():
        h = int(m["horizon_days"])
        if name == "cross_sectional_residual_rank":
            fn = lambda: make_residualized_rank_labels(price, h, market, beta_window=60)
        elif name == "cross_sectional_residual_quantile":
            qb = int(m["quantile_buckets"])
            fn = lambda qb=qb: make_residualized_quantile_labels(
                price, h, market, beta_window=60, quantile_buckets=qb)
        elif name == "binary_forward_return":
            fn = lambda: compute_binary_sign_labels(price, h)
        elif name == "binary_forward_return_after_cost":
            fn = lambda m=m: compute_cost_aware_binary_labels(
                price, h, cost_hurdle_bps=float(m["cost_hurdle_bps"]),
                min_expected_edge_bps=float(m["min_expected_edge_bps"]))
        elif name == "triple_barrier":
            fn = lambda m=m: triple_barrier_labels(
                price["S0"], h, float(m["pt_mult"]), float(m["sl_mult"]),
                int(m["vol_lookback"]))
        else:
            results[name] = {"error": "unknown mode — not in this smoke"}
            continue

        run1, run2 = fn(), fn()
        deterministic = _frames_identical(run1, run2)
        sub = run1[["label"]] if "label" in getattr(run1, "columns", []) else run1
        n_non_nan = int(np.isfinite(sub.to_numpy(dtype=float)).sum())
        results[name] = {
            "deterministic": bool(deterministic),
            "n_non_nan": n_non_nan,
            "checksum": _checksum(sub),
            "horizon_days": h,
        }
        flag = "OK" if deterministic else "NON-DETERMINISTIC"
        print(f"  {name}: deterministic={deterministic} "
              f"n_non_nan={n_non_nan} [{flag}]")

    all_det = all(r.get("deterministic", False) for r in results.values())
    out = {
        "prd": "docs/prd/20260521-rerisk-and-ml-training-audit-prd.md §12.3 P1",
        "panel_shape": list(price.shape),
        "modes": results,
        "p1_gate_all_modes_deterministic": all_det,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
    }
    ts = out["generated_utc"]
    path = PROJ / f"data/audit/ml_label_contract_smoke_{ts}.json"
    path.write_text(json.dumps(out, indent=2))
    print(f"  P1 gate — all modes deterministic: {all_det}")
    print(f"  → {path}")
    return 0 if all_det else 1


if __name__ == "__main__":
    sys.exit(main())
