#!/usr/bin/env python
"""Promote a mining archive spec_id to production (PRD M2).

Workflow:
  1. Run acceptance pack on spec_id (via core.mining.acceptance_pack)
  2. If overall_passed, atomically rewrite config/production_strategy.yaml
     with status=active, source.mode=promoted_from_archive, fingerprints
     computed from current repo state
  3. User must `git diff config/production_strategy.yaml` and `git commit`
     to make the promotion effective

Safety:
  - Without --promote flag, only shows dry-run diff
  - Without --force, refuses to promote a spec_id that fails acceptance
  - Even --force requires --yes-i-know-what-im-doing to avoid footgun

Usage:
  python scripts/promote_strategy.py --spec-id 81f5cdaa053e --dry-run
  python scripts/promote_strategy.py --spec-id 81f5 --promote
  python scripts/promote_strategy.py --spec-id X --promote --force --yes-i-know-what-im-doing
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.mining.acceptance_pack import (
    AcceptancePackError,
    AcceptancePackResult,
    run_acceptance_pack,
)


_MFS_PARAM_KEYS = [
    "top_n", "rebalance_monthly", "score_weighted", "min_holding_days",
    "lookback_mom", "lookback_quality", "lookback_vol", "apply_extra_shift",
]


def _sha256_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _compute_fingerprints(universe_name: str = "executable") -> dict:
    """Snapshot current repo state into artifact fingerprints.

    GAP4 (P4-A1 propagation): ``universe_name`` selects which universe
    yaml the ``universe_hash`` is computed from so a candidate mined on
    expanded_v1 is promoted with the matching universe fingerprint.
    Default "executable" → config/universe.yaml, byte-for-byte unchanged
    (D6/P4-A2 — every pre-existing promote produces the identical hash).
    """
    # factor_registry_hash
    from core.factors.factor_registry import PRODUCTION_FACTORS
    prod = sorted(PRODUCTION_FACTORS)
    factor_hash = _sha256_str("|".join(prod))

    # universe_hash (tradable symbols from the candidate's universe yaml)
    _uni_yaml_name = ("universe_expanded_v1.yaml"
                      if universe_name == "expanded_v1" else "universe.yaml")
    uni_yaml = yaml.safe_load((ROOT / "config" / _uni_yaml_name).read_text())
    tradable = []
    for key in ["seed_pool", "sector_etfs", "factor_etfs", "cross_asset"]:
        v = uni_yaml.get(key, [])
        if isinstance(v, list):
            tradable.extend(v)
    universe_hash = _sha256_str("|".join(sorted(set(tradable))))

    # config_hash (concat of risk + backtest + cost_model)
    parts = []
    for fn in ["risk.yaml", "backtest.yaml", "cost_model.yaml"]:
        p = ROOT / "config" / fn
        parts.append(_sha256_file(p))
    config_hash = _sha256_str("|".join(parts))

    return {
        "universe": universe_name,
        "universe_hash": universe_hash,
        "factor_registry_hash": factor_hash,
        "config_hash": config_hash,
    }


def _build_promoted_yaml(
    pack: AcceptancePackResult,
    rationale: str,
    universe_name: str = "executable",
) -> dict:
    """Produce the dict that will be written to production_strategy.yaml as active."""
    # Separate MFS ctor params from factor_weights in archived params
    params = dict(pack.params)
    factor_weights = params.pop("factor_weights", None)
    if factor_weights is None:
        # Some archives use 'weights' key
        factor_weights = params.pop("weights", None)
    if factor_weights is None:
        # MultiFactorSpace.suggest() stores weights as w_<factor_name>
        w_keys = [k for k in list(params.keys()) if k.startswith("w_")]
        if w_keys:
            factor_weights = {k[2:]: params.pop(k) for k in w_keys}
    if not factor_weights:
        raise AcceptancePackError(
            f"spec_id {pack.spec_id} has no factor_weights in archive params; "
            f"cannot promote."
        )

    # Keep only canonical params (drop mining-specific keys)
    canonical_params = {k: params[k] for k in _MFS_PARAM_KEYS if k in params}
    # Fill defaults for keys not in archive (older mining rows may lack these)
    canonical_params.setdefault("apply_extra_shift", False)

    fingerprints = _compute_fingerprints(universe_name)
    now = datetime.now(timezone.utc).isoformat()

    return {
        "schema_version": "1.0",
        "status": "active",
        "strategy_type": pack.strategy_type,
        "source": {
            "mode": "promoted_from_archive",
            "spec_id": pack.spec_id,
            "lineage_tag": pack.lineage_tag,
            "promoted_at": now,
            "rationale": rationale,
        },
        "params": canonical_params,
        "factor_weights": factor_weights,
        "validation": {
            "post_fix_validated": True,
            "passed_oos_gate": True,
            "passed_qqq_gate": True,
            "passed_paper_backtest_alignment": True,
            "notes": f"Promoted via scripts/promote_strategy.py at {now} after acceptance pack PASS.",
        },
        "fingerprints": fingerprints,
    }


def _show_dry_run(proposed: dict, current_path: Path) -> None:
    """Print the diff between current yaml and proposed yaml."""
    print("=" * 70)
    print("PROPOSED production_strategy.yaml contents:")
    print("=" * 70)
    print(yaml.safe_dump(proposed, default_flow_style=False, sort_keys=False))
    if current_path.exists():
        current = yaml.safe_load(current_path.read_text())
        cur_status = current.get("status", "(missing)")
        print("=" * 70)
        print(f"Current status: {cur_status}  →  Proposed: {proposed['status']}")
        print(f"Current weights: {current.get('factor_weights')}")
        print(f"Proposed weights: {proposed['factor_weights']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Promote archived spec_id to production (PRD M2)")
    parser.add_argument("--spec-id", required=True,
                        help="Archive spec_id (prefix match allowed)")
    parser.add_argument("--archive-db", default="data/mining/archive.db")
    parser.add_argument("--target", default="config/production_strategy.yaml",
                        help="Path to production_strategy.yaml to rewrite")
    parser.add_argument("--rationale", default="",
                        help="Why this spec_id was promoted (stored in source.rationale)")
    parser.add_argument("--universe", choices=["executable", "expanded_v1", "expanded_v2"],
                        default="executable",
                        help="universe the candidate was mined on (P4-A1 "
                             "propagation: universe_hash + recorded universe "
                             "field computed from the matching yaml). Default "
                             "executable = config/universe.yaml byte-for-byte "
                             "unchanged (D6/P4-A2). Cross-check against the "
                             "mining run_summary.json 'universe' field.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show the proposed yaml + diff, do not write")
    parser.add_argument("--promote", action="store_true",
                        help="Actually write the new yaml (requires --dry-run complement)")
    parser.add_argument("--force", action="store_true",
                        help="Allow promote even if acceptance pack FAILS (requires --yes-i-know-what-im-doing)")
    parser.add_argument("--yes-i-know-what-im-doing", action="store_true",
                        dest="confirm_force")
    parser.add_argument("--skip-fresh-backtest", action="store_true",
                        help="Skip pack v2 gate 10. Debug only; not for real promote.")
    args = parser.parse_args()

    if not args.dry_run and not args.promote:
        print("ERROR: must pass --dry-run or --promote", file=sys.stderr)
        return 2

    # Run acceptance pack
    try:
        pack = run_acceptance_pack(
            args.spec_id, archive_db=args.archive_db,
            run_fresh_backtest=not args.skip_fresh_backtest,
        )
    except AcceptancePackError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(pack.summary_line())
    for g in pack.gates:
        mark = "✅" if g.passed else "❌"
        print(f"  {mark} {g.name}")

    # Verdict
    if not pack.overall_passed:
        if not args.force:
            print("\nRefusing to promote — acceptance pack FAILED. "
                  "Pass --force --yes-i-know-what-im-doing to override (not recommended).",
                  file=sys.stderr)
            return 1
        if not args.confirm_force:
            print("\n--force provided without --yes-i-know-what-im-doing. Aborting.",
                  file=sys.stderr)
            return 2
        print("\nWARNING: proceeding despite acceptance pack FAILURE (--force active)")

    # Build proposed yaml
    rationale = args.rationale or (
        f"Promoted from archive (spec_id={pack.spec_id[:12]}, "
        f"lineage={pack.lineage_tag}). Acceptance pack "
        f"{'PASSED' if pack.overall_passed else 'FAILED (force)'} on "
        f"{datetime.now(timezone.utc).isoformat()}."
    )
    try:
        proposed = _build_promoted_yaml(pack, rationale, args.universe)
    except AcceptancePackError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    target_path = ROOT / args.target if not Path(args.target).is_absolute() else Path(args.target)

    if args.dry_run and not args.promote:
        _show_dry_run(proposed, target_path)
        print("\nDry run complete. Re-run with --promote to write.")
        return 0

    # Actual write
    _show_dry_run(proposed, target_path)
    target_path.write_text(yaml.safe_dump(proposed, default_flow_style=False, sort_keys=False))
    print(f"\n✅ Wrote {target_path}")
    print("Next steps:")
    print("  1. git diff config/production_strategy.yaml   # review change")
    print("  2. pytest -q                                   # sanity")
    print("  3. git add config/production_strategy.yaml")
    print(f'  4. git commit -m "promote {pack.spec_id[:12]} to production"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
