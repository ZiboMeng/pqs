"""D1 — full data-cleanliness audit (user-directed, 2026-05-16).

The BarStore NaN-volume int-cast bug (surfaced by C3C4 on expanded_v2)
is a red flag: unclean data → unstable conclusions. This audits EVERY
symbol in executable ∪ expanded_v1 ∪ expanded_v2 through the SAME
BarStore.load path the R2.5/R4/C experiments use, classifying:

  - load_exception   : BarStore raises (the NaN-volume bug, etc.)
  - nan_close / nan_volume / inf : non-finite in the loaded frame
  - weekend_rows     : Sat/Sun bars (feedback_bar_level_data_integrity_smoke)
  - n_rows / span

FULL date range (incl. 2026 sealed bars). User 2026-05-16: data
cleanliness is ORTHOGONAL to the temporal split — ALL data must be
clean regardless of train/validation/sealed. Cleaning raw bars is
data hygiene, NOT reading sealed for evidence (sealed integrity is
ledger / partition_for_role-gated, never preserved by leaving the
store dirty). Writes data/audit/ml_redo/d1_cleanliness.json +
d1_dirty_symbols.txt (the backfill worklist).
"""
from __future__ import annotations

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
from core.universe.universe_resolver import resolve_universe  # noqa: E402

_TRAIN_END = pd.Timestamp("2024-12-31")


def main() -> int:
    t0 = time.time()
    cfg = load_config(_PROJ / "config")
    store = BarStore(root=Path(cfg.system.paths.data_dir))
    uni = {}
    for u in ("executable", "expanded_v1", "expanded_v2"):
        try:
            uni[u] = set(resolve_universe(u))
        except Exception as e:
            uni[u] = set()
            print(f"resolve {u} failed: {e}")
    all_syms = sorted(set().union(*uni.values()))
    print(f"auditing {len(all_syms)} symbols (exec∪v1∪v2)")

    rows = []
    for i, s in enumerate(all_syms):
        rec = {"symbol": s,
               "in_exec": s in uni["executable"],
               "in_v1": s in uni["expanded_v1"],
               "in_v2": s in uni["expanded_v2"]}
        try:
            df = store.load(s, freq="1d", adjusted=True, fallback="local")
        except Exception as e:
            rec.update({"status": "load_exception",
                        "error": type(e).__name__ + ": " + str(e)[:120]})
            rows.append(rec)
            continue
        if df is None or df.empty:
            rec["status"] = "empty"
            rows.append(rec)
            continue
        # USER 2026-05-16: data cleanliness is ORTHOGONAL to the
        # temporal split — ALL bars (incl. 2026 sealed) must be clean.
        # Cleaning raw bars is data hygiene, NOT reading sealed for
        # evidence (sealed integrity is ledger/partition_for_role-gated,
        # not preserved by leaving the store dirty). Audit FULL range.
        tr = df
        if tr.empty:
            rec["status"] = "empty"
            rows.append(rec)
            continue
        nan_close = int(tr["close"].isna().sum()) if "close" in tr else -1
        nan_vol = int(tr["volume"].isna().sum()) if "volume" in tr else -1
        inf_any = bool(np.isinf(tr.select_dtypes("number")
                                .to_numpy()).any())
        wknd = int(tr.index.dayofweek.isin([5, 6]).sum())
        dirty = (nan_close > 0 or nan_vol > 0 or inf_any or wknd > 0)
        rec.update({
            "status": "dirty" if dirty else "clean",
            "n_rows": int(len(tr)),
            "nan_close": nan_close, "nan_volume": nan_vol,
            "inf_any": inf_any, "weekend_rows": wknd,
            "start": str(tr.index.min().date()),
            "end": str(tr.index.max().date()),
        })
        rows.append(rec)
        if (i + 1) % 400 == 0:
            print(f"  {i+1}/{len(all_syms)} ({time.time()-t0:.0f}s)")

    by_status = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    dirty = [r for r in rows if r["status"] in
             ("load_exception", "dirty", "empty")]
    # which dirty symbols actually matter (in a used universe)
    dirty_used = [r for r in dirty
                  if r["in_exec"] or r["in_v1"] or r["in_v2"]]

    audit = {
        "audit": "d1_data_cleanliness",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "n_audited": len(all_syms),
        "universe_sizes": {k: len(v) for k, v in uni.items()},
        "by_status": by_status,
        "n_dirty_total": len(dirty),
        "n_dirty_in_used_universe": len(dirty_used),
        "load_exception_symbols": [r["symbol"] for r in rows
                                   if r["status"] == "load_exception"][:200],
        "nan_volume_symbols": [r["symbol"] for r in rows
                               if r.get("nan_volume", 0) > 0][:200],
        "nan_close_symbols": [r["symbol"] for r in rows
                              if r.get("nan_close", 0) > 0][:200],
        "weekend_symbols": [r["symbol"] for r in rows
                            if r.get("weekend_rows", 0) > 0][:200],
        "per_universe_clean_pct": {
            "executable": round(100.0 * sum(
                1 for r in rows if r["status"] == "clean" and r["in_exec"])
                / max(1, len(uni["executable"])), 2),
            "expanded_v1": round(100.0 * sum(
                1 for r in rows if r["status"] == "clean" and r["in_v1"])
                / max(1, len(uni["expanded_v1"])), 2),
            "expanded_v2": round(100.0 * sum(
                1 for r in rows if r["status"] == "clean" and r["in_v2"])
                / max(1, len(uni["expanded_v2"])), 2)},
        "wall_s": round(time.time() - t0, 1),
    }
    out = _PROJ / "data" / "audit" / "ml_redo" / "d1_cleanliness.json"
    out.write_text(json.dumps(audit, indent=2, default=str))
    wl = _PROJ / "data" / "audit" / "ml_redo" / "d1_dirty_symbols.txt"
    wl.write_text("\n".join(sorted(r["symbol"] for r in dirty_used)))
    print(f"D1 -> {out.name}: status={by_status} "
          f"dirty_total={len(dirty)} dirty_in_used={len(dirty_used)} "
          f"({time.time()-t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
