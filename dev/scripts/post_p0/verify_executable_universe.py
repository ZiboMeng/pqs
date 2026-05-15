"""Verify config/executable_universe.yaml against live universe.yaml.

P0 governance cleanup (auditor direction #2). Confirms the SoT
executable-universe list is consistent with what the cycle launcher
actually derives, and re-runs data completeness on exactly that set.

Run:
    python dev/scripts/post_p0/verify_executable_universe.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import yaml

PROJ = Path("/home/zibo/Documents/projects/pqs")
sys.path.insert(0, str(PROJ))

from core.config.loader import load_config
from core.data.bar_store import BarStore
from core.data.data_completeness_gate import check_panel_completeness


def main() -> int:
    sot = yaml.safe_load((PROJ / "config/executable_universe.yaml").read_text())
    sot_universe = set(sot["executable_universe"])
    sot_count = sot["derivation"]["executable_count"]

    # Re-derive executable universe from live universe.yaml (launcher logic)
    cfg = load_config(PROJ / "config")
    uni = cfg.universe
    union = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs)
        + list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    drop = {"BRK-B", "USO", "SLV"}
    derived = sorted(
        s for s in union
        if s not in uni.blacklist and s not in uni.macro_reference
        and s not in drop
    )

    print(f"SoT executable_universe: {len(sot_universe)} symbols")
    print(f"Re-derived from universe.yaml: {len(derived)} symbols")

    ok = True
    if len(derived) != sot_count:
        print(f"  ✗ COUNT MISMATCH: SoT says {sot_count}, derived {len(derived)}")
        ok = False
    missing_in_sot = set(derived) - sot_universe
    extra_in_sot = sot_universe - set(derived)
    if missing_in_sot:
        print(f"  ✗ in derived but NOT in SoT: {sorted(missing_in_sot)}")
        ok = False
    if extra_in_sot:
        print(f"  ✗ in SoT but NOT derived: {sorted(extra_in_sot)}")
        ok = False
    if ok:
        print("  ✓ SoT matches live universe.yaml derivation exactly")

    # Re-run data completeness on the executable universe
    store = BarStore(root=Path(cfg.system.paths.data_dir))
    frames = {}
    for sym in derived:
        df = store.load(sym, freq="1d", adjusted=True, fallback="local")
        if df is not None and not df.empty and "close" in df.columns:
            frames[sym] = df["close"]
    panel = pd.DataFrame(frames).sort_index()
    ftd_map = dict(getattr(uni, "first_trade_dates", {}) or {})
    ftd_str = {k: (v.strftime("%Y-%m-%d") if hasattr(v, "strftime") else str(v))
               for k, v in ftd_map.items()}
    report = check_panel_completeness(panel, derived,
                                      first_trade_dates=ftd_str,
                                      max_consecutive_missing_bd=5)
    print(f"\nData completeness on executable universe: "
          f"{report.n_pass}/{report.universe_size} PASS")
    if report.failed_symbols:
        print(f"  ✗ FAILED: {report.failed_symbols}")
        ok = False
    else:
        print("  ✓ all executable-universe symbols data-complete")

    print(f"\n{'VERIFY PASS' if ok else 'VERIFY FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
