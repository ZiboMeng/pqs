"""P0-A F3 — 143-factor IC library recompute on ADJUSTED prices,
train-only, with honest raw→adjusted restate.

PRD docs/prd/20260518-p0a_loader_barstore_fix_prd.md §2 F3.

SEALED RED-LINE: `scripts/run_factor_screen.py` has only a start cut
and NO end/train-only/sealed exclusion → running it un-capped reads
the 2026 sealed window (irreversible pollution). This script does NOT
run that path. It recomputes the SAME factor library
(`generate_all_factors`) but restricted to config/temporal_split.yaml
TRAIN years only, on BOTH price bases (raw MarketDataStore vs adjusted
via price_access/BarStore), and asserts max date is within the train
window before computing anything.

Output: data/audit/f3_factor_ic_library_restate.json + a markdown
restate the operator folds into docs/audit/.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.config.loader import load_config  # noqa: E402
from core.data.market_data_store import MarketDataStore  # noqa: E402
from core.data.price_access import load_adjusted_panel  # noqa: E402
from core.factors.factor_engine import FactorEngine  # noqa: E402
from core.factors.factor_generator import (  # noqa: E402
    compute_forward_returns,
    generate_all_factors,
)
from core.research.temporal_split import (  # noqa: E402
    load_temporal_split,
    train_year_set,
)
from core.universe.universe_resolver import resolve_universe  # noqa: E402

_H = 21


def _raw_panel(syms, root, train_years):
    ms = MarketDataStore(data_dir=Path(root))
    c, v = {}, {}
    for s in syms:
        df = ms.read(s, "1d")
        if df is None or df.empty or "close" not in df.columns:
            continue
        m = [ts.year in train_years for ts in df.index]
        c[s] = df["close"][m]
        if "volume" in df.columns:
            v[s] = df["volume"][m]
    return (pd.DataFrame(c).sort_index(),
            pd.DataFrame(v).sort_index() if v else None)


def _adj_panel(syms, root, train_years):
    out = load_adjusted_panel(syms, root, "1d")
    cl = out["close"]
    m = [ts.year in train_years for ts in cl.index]
    cl = cl[m]
    vol = out["volume"].loc[cl.index] if out["volume"] is not None else None
    return cl, vol


def _ic_table(price_df, vol_df, label):
    fac = generate_all_factors(price_df, vol_df)
    fwd = compute_forward_returns(price_df, [_H])
    eng = FactorEngine()
    stats = {}
    n_fail = 0
    first_err = None
    for fn, fdf in fac.items():
        for h, rdf in fwd.items():
            try:
                ic = eng.compute_rank_ic(fdf, rdf)
                st = eng.compute_factor_stats(ic, factor_name=fn, horizon=h)
                mi, ir = st.mean_ic, st.ir
                if mi is None or (isinstance(mi, float) and np.isnan(mi)):
                    continue  # genuinely undefined IC (constant factor)
                stats[(fn, h)] = (round(float(mi), 5), round(float(ir), 4))
            except Exception as e:  # do NOT silently zero — record it
                n_fail += 1
                if first_err is None:
                    first_err = f"{type(e).__name__}: {e}"
    print(f"  [{label}] {len(fac)} factors, {len(stats)} stats, "
          f"{n_fail} failed (first_err={first_err})")
    # fail-closed: a near-total failure must NOT pass as a clean 0
    if len(stats) == 0:
        raise SystemExit(
            f"[{label}] 0 stats from {len(fac)} factors — systematic "
            f"failure, NOT a clean result. first_err={first_err}")
    return stats


def main() -> int:
    cfg = load_config(Path("config"))
    split = load_temporal_split(Path("config/temporal_split.yaml"))
    ty = train_year_set(split)
    root = cfg.system.paths.data_dir
    uni = cfg.universe
    syms = [s for s in (list(uni.seed_pool) + list(uni.sector_etfs)
                        + list(uni.factor_etfs) + list(uni.cross_asset))
            if s not in uni.blacklist and s not in uni.macro_reference]
    syms = list(dict.fromkeys(syms))

    raw_c, raw_v = _raw_panel(syms, root, ty)
    adj_c, adj_v = _adj_panel(syms, root, ty)

    # SEALED ASSERT — fail-closed if any non-train year leaked in
    for nm, df in (("raw", raw_c), ("adj", adj_c)):
        yrs = {ts.year for ts in df.index}
        bad = yrs - ty
        if bad:
            raise SystemExit(f"SEALED GUARD: {nm} panel has non-train "
                             f"years {sorted(bad)} — abort (no pollution)")
    max_year = max(ty)
    assert raw_c.index.max().year <= max_year
    assert adj_c.index.max().year <= max_year

    raw_s = _ic_table(raw_c, raw_v, "raw")
    adj_s = _ic_table(adj_c, adj_v, "adjusted")

    common = sorted(set(raw_s) & set(adj_s))
    rows = []
    for k in common:
        r_ic, r_ir = raw_s[k]
        a_ic, a_ir = adj_s[k]
        rows.append({"factor": k[0], "h": k[1],
                     "raw_ic": r_ic, "adj_ic": a_ic,
                     "raw_ir": r_ir, "adj_ir": a_ir,
                     "sign_flip": bool(np.sign(r_ic) != np.sign(a_ic)),
                     "abs_ir_delta": round(abs(a_ir) - abs(r_ir), 4)})
    rir = np.array([x["raw_ir"] for x in rows], float)
    air = np.array([x["adj_ir"] for x in rows], float)
    msk = np.isfinite(rir) & np.isfinite(air)
    from scipy.stats import spearmanr
    sp = (round(float(spearmanr(rir[msk], air[msk]).correlation), 4)
          if msk.sum() >= 3 else None)
    n_flip = sum(x["sign_flip"] for x in rows)
    # top-20 by |IR| overlap (factor-screen --top default 20)
    order_r = [rows[i]["factor"] for i in np.argsort(-np.abs(rir))][:20]
    order_a = [rows[i]["factor"] for i in np.argsort(-np.abs(air))][:20]
    ovl20 = len(set(order_r) & set(order_a)) / 20.0
    big_flip = [x for x in rows
                if x["sign_flip"] and (abs(x["raw_ir"]) > 0.3
                                       or abs(x["adj_ir"]) > 0.3)]

    out = {
        "audit": "f3_factor_ic_library_adjusted_restate",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "split_name": split.split_name,
        "train_years_only": sorted(ty), "sealed_2026_read": False,
        "n_symbols": int(raw_c.shape[1]),
        "n_factor_horizon_pairs": len(rows),
        "spearman_raw_vs_adj_ir": sp,
        "top20_absir_overlap": ovl20,
        "n_sign_flips": int(n_flip),
        "n_material_sign_flips_absir_gt_0p3": len(big_flip),
        "material_sign_flips": big_flip[:40],
        "rows": rows,
    }
    p = Path("data/audit/f3_factor_ic_library_restate.json")
    p.write_text(json.dumps(out, indent=2, default=str))
    print(f"n={len(rows)} spearman(raw_ir,adj_ir)={sp} "
          f"top20_overlap={ovl20} sign_flips={n_flip} "
          f"material_flips(|IR|>0.3)={len(big_flip)} -> {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
