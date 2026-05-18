"""Quantify the adjusted-Track-A-gate backstop strength vs raw-price
mining SEARCH (grand audit §1.A.q).

Question: mining ranks trials by raw-price IC_IR; the Track A gate
re-evaluates the nominee on ADJUSTED prices. How much does the
raw-basis factor ranking diverge from the adjusted-basis ranking?
- High Spearman rank-corr  → raw selection ≈ adjusted selection →
  backstop rarely needs to catch anything + low false-negative risk.
- Low rank-corr / sign flips → raw selection near-random wrt adjusted
  → backstop carries the load (many raw false-positives) AND we miss
  many adjusted-good composites (high false-negative risk).

Discipline: TRAIN-ONLY (config/temporal_split.yaml train_years; sealed
2026 + validation NEVER read), config-scoped, no market websearch.
Single-factor cross-sectional IC on the split-sensitive factor set
(momentum/reversal/vol — exactly what raw splits corrupt) computed on
BOTH bases over the SAME executable universe + train window.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import sys

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.config.loader import load_config  # noqa: E402
from core.data.bar_store import BarStore
from core.data.market_data_store import MarketDataStore
from core.research.temporal_split import load_temporal_split, train_year_set
from core.universe.universe_resolver import resolve_universe

_H = 21


def _panel(loader, syms, train_years):
    cols = {}
    for s in syms:
        try:
            df = loader(s)
        except Exception:
            continue
        if df is None or df.empty or "close" not in df.columns:
            continue
        c = df["close"]
        c = c[[ts.year in train_years for ts in c.index]]
        if len(c) > 252:
            cols[s] = c
    return pd.DataFrame(cols).sort_index()


def _factors(close: pd.DataFrame) -> dict:
    r1 = close.pct_change()
    return {
        "mom_252d": close.pct_change(252),
        "mom_126d": close.pct_change(126),
        "mom_63d": close.pct_change(63),
        "mom_21d": close.pct_change(21),
        "ret_5d": close.pct_change(5),
        "ret_1d": r1,
        "rev_5d": -close.pct_change(5),
        "vol_21d": r1.rolling(21).std(),
        "vol_63d": r1.rolling(63).std(),
        "drawup_252d": close / close.rolling(252).min() - 1.0,
    }


def _ic_stats(fac: pd.DataFrame, fwd: pd.DataFrame) -> tuple[float, float]:
    ics = []
    for dt in fac.index:
        if dt not in fwd.index:
            continue
        x = fac.loc[dt]
        y = fwd.loc[dt]
        m = x.notna() & y.notna()
        if m.sum() < 10:
            continue
        ic = spearmanr(x[m], y[m]).correlation
        if np.isfinite(ic):
            ics.append(ic)
    if len(ics) < 20:
        return float("nan"), float("nan")
    a = np.array(ics)
    ir = a.mean() / a.std() * np.sqrt(252.0 / _H) if a.std() > 0 else 0.0
    return float(a.mean()), float(ir)


def main() -> int:
    cfg = load_config(Path("config"))
    split = load_temporal_split(Path("config/temporal_split.yaml"))
    ty = train_year_set(split)
    syms = [s for s in resolve_universe("executable") if s not in ("SPY", "QQQ")]

    ms = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))
    bs = BarStore(root=Path(cfg.system.paths.data_dir))
    raw_close = _panel(lambda s: ms.read(s, "1d"), syms, ty)
    adj_close = _panel(lambda s: bs.load(s, freq="1d", adjusted=True,
                                         fallback="local"), syms, ty)
    common = raw_close.columns.intersection(adj_close.columns)
    idx = raw_close.index.intersection(adj_close.index)
    raw_close = raw_close.loc[idx, common]
    adj_close = adj_close.loc[idx, common]

    raw_fwd = raw_close.pct_change(_H).shift(-_H)
    adj_fwd = adj_close.pct_change(_H).shift(-_H)
    rf, af = _factors(raw_close), _factors(adj_close)

    rows = []
    for name in rf:
        r_ic, r_ir = _ic_stats(rf[name], raw_fwd)
        a_ic, a_ir = _ic_stats(af[name], adj_fwd)
        rows.append({"factor": name,
                     "raw_ic": round(r_ic, 5), "adj_ic": round(a_ic, 5),
                     "raw_ic_ir": round(r_ir, 4), "adj_ic_ir": round(a_ir, 4),
                     "sign_flip": bool(np.isfinite(r_ic) and np.isfinite(a_ic)
                                       and np.sign(r_ic) != np.sign(a_ic))})
    rir = np.array([x["raw_ic_ir"] for x in rows], float)
    air = np.array([x["adj_ic_ir"] for x in rows], float)
    mask = np.isfinite(rir) & np.isfinite(air)
    sp = spearmanr(rir[mask], air[mask]).correlation if mask.sum() >= 3 else float("nan")
    # top-K overlap (mining selects best by IC_IR)
    order_r = [rows[i]["factor"] for i in np.argsort(-rir)]
    order_a = [rows[i]["factor"] for i in np.argsort(-air)]
    k = 3
    ovl = len(set(order_r[:k]) & set(order_a[:k])) / k
    n_flip = sum(x["sign_flip"] for x in rows)

    out = {
        "audit": "adjusted_gate_backstop_strength",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "split_name": split.split_name,
        "train_years_only": sorted(ty),
        "sealed_2026_read": False,
        "n_symbols": int(len(common)),
        "n_dates_train": int(len(idx)),
        "per_factor": rows,
        "spearman_rank_corr_raw_vs_adj_ic_ir": (
            None if not np.isfinite(sp) else round(float(sp), 4)),
        "top3_overlap_raw_vs_adj": ovl,
        "n_sign_flips": int(n_flip),
        "n_factors": len(rows),
        "interpretation": (
            "high spearman + high overlap + 0 flips → raw selection ≈ "
            "adjusted; backstop light, low false-negative. low spearman "
            "/ flips → raw ranking scrambled; gate carries load + high "
            "false-negative (good composites missed by raw search)."),
    }
    p = Path("data/audit/adjusted_gate_backstop_quant.json")
    p.write_text(json.dumps(out, indent=2, default=str))
    print(f"symbols={len(common)} dates={len(idx)} (train-only)")
    for x in rows:
        print(f"  {x['factor']:13s} raw_ir={x['raw_ic_ir']:+.3f} "
              f"adj_ir={x['adj_ic_ir']:+.3f} flip={x['sign_flip']}")
    print(f"Spearman(raw_ir, adj_ir)={out['spearman_rank_corr_raw_vs_adj_ic_ir']} "
          f"top3_overlap={ovl} sign_flips={n_flip}/{len(rows)}")
    print(f"-> {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
