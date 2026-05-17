"""R3 — FULL self-supervised pretraining (supplementary PRD §6, R3-A2).

Corrects Phase 2B's gap: TS2Vec was only 40-step smoke-trained and the
representations' downstream IC was never run. This does a FULL pretrain
(not smoke) of the MAE (segment-mask) on the train-only corpus
(`chart_structure_pretrain_corpus_v1`, train_years_only=True → sealed
2026 + validation never seen by the encoder), writes a checkpoint +
`data/audit/ml_redo/pretrain_mae.json` with **is_full_pretrain:true**,
n_steps, loss curve, convergence judgment, corpus_manifest_id.

Downstream (R2.5-b / R4) fail-closes on is_full_pretrain != true (G11).

Usage:
  python dev/scripts/ml_redo/run_full_pretrain.py [--steps N] [--smoke]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

_PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJ))

from core.config.loader import load_config  # noqa: E402
from core.data.bar_store import BarStore  # noqa: E402
from core.ml.ssl_pretrain import pretrain_mae  # noqa: E402
from core.ml.window_embedding import WINDOW_LEN  # noqa: E402
from core.research.temporal_split import (  # noqa: E402
    load_temporal_split,
    partition_for_role,
    train_year_set,
    validate_no_holdout_leakage,
)
from core.universe.universe_resolver import resolve_universe  # noqa: E402

_FULL_MIN_STEPS = 3000   # >> Phase2B 40-step smoke; "full" threshold
_CONV_TOL = 0.02         # last-10% mean loss within tol of best = converged


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--steps", type=int, default=5000)
    ap.add_argument("--smoke", action="store_true",
                    help="40-step smoke (is_full_pretrain=false) for CI only")
    ap.add_argument("--universe", choices=["executable", "expanded_v1",
                                           "expanded_v2"],
                    default="expanded_v1",
                    help="corpus universe (manifest default expanded_v1)")
    args = ap.parse_args()
    steps = 40 if args.smoke else args.steps

    t0 = time.time()
    cfg = load_config(_PROJ / "config")
    store = BarStore(root=Path(cfg.system.paths.data_dir))
    split = load_temporal_split(_PROJ / "config" / "temporal_split.yaml")
    train_years = train_year_set(split)
    syms = [s for s in resolve_universe(args.universe)
            if s not in ("SPY", "QQQ")]

    # build train-only causal 63-bar windows (corpus contract)
    close = {}
    for s in syms:
        df = store.load(s, freq="1d", adjusted=True, fallback="local")
        if df is not None and not df.empty and "close" in df.columns:
            close[s] = df["close"]
    close_df = pd.DataFrame(close).sort_index()
    mining_panel = partition_for_role({"close": close_df}, split, role="miner")
    close_df = mining_panel["close"]
    validate_no_holdout_leakage(mining_panel, split)  # sealed/val fail-closed

    wins = []
    for s in close_df.columns:
        v = close_df[s].to_numpy(float)
        yrs = close_df.index.year.to_numpy()
        for i in range(WINDOW_LEN - 1, len(v)):
            if yrs[i] not in train_years:
                continue
            w = v[i - WINDOW_LEN + 1: i + 1]
            if np.isfinite(w).all() and w[0] > 0:
                wins.append(w / w[0] - 1.0)   # window-relative return shape
    W = np.asarray(wins, np.float32)
    print(f"train-only windows: {W.shape} ({time.time()-t0:.1f}s)")

    model, traj = pretrain_mae(W, steps=steps, full=not args.smoke)
    best = float(np.min(traj))
    tail = float(np.mean(traj[-max(1, len(traj) // 10):]))
    converged = abs(tail - best) <= _CONV_TOL * max(abs(best), 1e-6) or \
        tail <= best * 1.05
    is_full = (not args.smoke) and steps >= _FULL_MIN_STEPS

    art = {
        "encoder": "MAE_segment_mask",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "is_full_pretrain": bool(is_full),
        "n_steps": int(steps),
        "full_min_steps": _FULL_MIN_STEPS,
        "corpus_manifest_id": "chart_structure_pretrain_corpus_v1",
        "universe": args.universe,
        "n_windows": int(W.shape[0]),
        "train_years_only": True,
        "sealed_validation_seen": False,
        "loss_first_last_best": [round(traj[0], 6), round(traj[-1], 6),
                                 round(best, 6)],
        "converged": bool(converged),
        "wall_s": round(time.time() - t0, 1),
    }
    out = _PROJ / "data" / "audit" / "ml_redo" / "pretrain_mae.json"
    out.write_text(json.dumps(art, indent=2))
    print(f"pretrain -> {out.name}: is_full={is_full} steps={steps} "
          f"loss {traj[0]:.4f}->{traj[-1]:.4f} (best {best:.4f}) "
          f"converged={converged}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
