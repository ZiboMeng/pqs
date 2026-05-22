#!/usr/bin/env python
"""P3 score-to-weight smoke (PRD 20260521 §12.3 Package P3 gate).

Runs each mapping mode in `config/ml_allocation.yaml` twice on a fixed
synthetic score panel and records, per mode:
  - deterministic   : the two runs are byte-identical
  - long_only       : every weight >= 0
  - cap_respected   : max single-name weight <= the configured cap
                      (no path silently bypasses a risk cap)
  - max_gross       : largest per-bar gross (<= 1.0 = no leverage)

Output: data/audit/score_to_weight_smoke_<ts>.json

Usage: python dev/scripts/ml/score_to_weight_smoke.py
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

from core.research.allocation.score_to_weight import (  # noqa: E402
    score_panel_to_weights,
)


def _synthetic(n: int = 40, k: int = 30, seed: int = 20260521):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2022-01-03", periods=n)
    syms = [f"S{i:02d}" for i in range(k)]
    score = pd.DataFrame(rng.random((n, k)), index=idx, columns=syms)
    vol = pd.DataFrame(rng.uniform(0.10, 0.45, (n, k)),
                       index=idx, columns=syms)
    return score, vol


def main() -> int:
    cfg = yaml.safe_load((PROJ / "config/ml_allocation.yaml").read_text())
    modes = cfg["mapping_modes"]
    cap = float(cfg["constraints"]["max_single_name_weight"])
    score, vol = _synthetic()
    print(f"=== P3 score-to-weight smoke  panel={score.shape}  cap={cap} ===")

    results: dict = {}
    for name, m in modes.items():
        top_k = int(m["top_k"])
        kw = dict(mode=name, top_k=top_k, max_single_weight=cap)
        if name == "score_vol_scaled":
            kw["vol_df"] = vol

        run1 = score_panel_to_weights(score, **kw)
        run2 = score_panel_to_weights(score, **kw)
        deterministic = run1.equals(run2)

        vals = run1.to_numpy()
        long_only = bool((vals >= -1e-12).all())
        max_w = float(np.nanmax(vals)) if vals.size else 0.0
        cap_respected = bool(max_w <= cap + 1e-9)
        max_gross = float(run1.sum(axis=1).max())

        results[name] = {
            "deterministic": deterministic,
            "long_only": long_only,
            "cap_respected": cap_respected,
            "max_single_weight": round(max_w, 6),
            "max_gross": round(max_gross, 6),
        }
        ok = deterministic and long_only and cap_respected
        print(f"  {name}: deterministic={deterministic} long_only={long_only}"
              f" cap_respected={cap_respected} max_w={max_w:.4f} "
              f"[{'OK' if ok else 'FAIL'}]")

    all_ok = all(r["deterministic"] and r["long_only"] and r["cap_respected"]
                 for r in results.values())
    out = {
        "prd": "docs/prd/20260521-rerisk-and-ml-training-audit-prd.md §12.3 P3",
        "allocation_config": "config/ml_allocation.yaml",
        "panel_shape": list(score.shape),
        "single_name_cap": cap,
        "modes": results,
        "p3_gate_all_modes_deterministic_and_cap_safe": all_ok,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
    }
    ts = out["generated_utc"]
    path = PROJ / f"data/audit/score_to_weight_smoke_{ts}.json"
    path.write_text(json.dumps(out, indent=2))
    print(f"  P3 gate — all modes deterministic + cap-safe: {all_ok}")
    print(f"  → {path}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
