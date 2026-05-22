#!/usr/bin/env python
"""P5 — freeze an ML candidate / check a frozen bundle for drift.

Build mode (default): hash the 6 dependency layers of a validated ML
candidate into one reproducible bundle and write it to
`data/ml/freeze/ml_freeze_bundle_<id>.json`. Only succeeds when the
referenced P4 acceptance artifact has verdict PASS + §9.6 overfit
control (governance memo §2).

Check mode (`--check <bundle.json>`): re-hash the layers and report any
drift flag (governance memo §3).

Usage:
  python dev/scripts/ml/freeze_ml_bundle.py
  python dev/scripts/ml/freeze_ml_bundle.py --check data/ml/freeze/<x>.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

from core.research.ml.freeze_bundle import (  # noqa: E402
    build_freeze_bundle,
    check_drift,
)

CYCLE06 = ("drawup_from_252d_low", "trend_tstat_20d", "ret_2d")


def _latest_acceptance() -> Path:
    cands = sorted((PROJ / "data/audit").glob(
        "ml_rank_portfolio_acceptance_*.json"))
    if not cands:
        raise FileNotFoundError("no P4 acceptance artifact under data/audit")
    return cands[-1]


def main() -> int:
    ap = argparse.ArgumentParser(description="P5 ML freeze bundle")
    ap.add_argument("--acceptance", default=None,
                    help="P4 acceptance json (default = latest)")
    ap.add_argument("--feature-set", default="cycle06")
    ap.add_argument("--model-artifact", default=None,
                    help="path to the trained model .pkl to pin into the "
                         "bundle (S7 M9 — required for build mode; a "
                         "freeze that does not hash the model is not "
                         "reproducible)")
    ap.add_argument("--check", default=None,
                    help="drift-check an existing bundle json instead of "
                         "building a new one")
    args = ap.parse_args()

    if args.check:
        bundle = json.loads(Path(args.check).read_text())
        flags = check_drift(bundle, PROJ, factor_names=CYCLE06)
        print(f"=== drift check: {Path(args.check).name} "
              f"(bundle_id={bundle.get('bundle_id')}) ===")
        if not flags:
            print("  no drift — frozen spec reproduces exactly")
        else:
            for f in flags:
                print(f"  DRIFT [{f['drift_class']}] {f['field']}")
        return 0

    acc = Path(args.acceptance) if args.acceptance else _latest_acceptance()
    if not args.model_artifact:
        print("error: --model-artifact is required for build mode "
              "(S7 M9 — the bundle must hash the trained model).",
              file=sys.stderr)
        return 2
    print(f"=== freeze ML bundle  acceptance={acc.name} ===")
    bundle = build_freeze_bundle(
        PROJ, acc, args.feature_set, CYCLE06,
        model_artifact_path=Path(args.model_artifact))
    # data/audit is version-controlled — a freeze bundle is a durable
    # promotion record and must be tracked (data/ml is gitignored).
    out_dir = PROJ / "data/audit"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"ml_freeze_bundle_{bundle['bundle_id']}.json"
    out_path.write_text(json.dumps(bundle, indent=2))
    print(f"  bundle_id={bundle['bundle_id']}  verdict={bundle['acceptance_verdict']}")
    print(f"  feature_set={bundle['feature_set']['name']}  "
          f"layers hashed: source/label/allocation/split/feature")
    print(f"  → {out_path}")
    # immediate self-check — a just-built bundle must show zero drift
    flags = check_drift(bundle, PROJ, factor_names=CYCLE06)
    print(f"  self-check drift flags: {len(flags)} "
          f"({'OK' if not flags else 'UNEXPECTED'})")
    return 0 if not flags else 1


if __name__ == "__main__":
    sys.exit(main())
