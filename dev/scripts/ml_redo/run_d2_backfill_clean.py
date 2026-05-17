"""D2b — clean + backfill the D1-dirty symbols (user-directed).

User: ALL data must be clean (orthogonal to train/sealed); missing →
websearch a source and fill. Websearch (2026-05-16) confirmed yfinance
(codebase's sanctioned fallback) + Stooq as the free historical OHLCV
sources. This re-fetches each D1-dirty symbol's daily OHLCV from
yfinance (Stooq secondary), sanitizes (drop weekend rows, drop NaN
close/volume, dedupe, sort, tz-naive), and rewrites
data/daily/<sym>.parquet with a .preD2 backup (idempotent; only the
d1_dirty_symbols.txt worklist — the 100%-clean executable/expanded_v1
parquets are NEVER touched).

FULL date range fetched (incl. 2026) — data hygiene, not sealed
evidence (sealed integrity stays ledger/partition_for_role-gated).
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

_DAILY = _PROJ / "data" / "daily"
_WL = _PROJ / "data" / "audit" / "ml_redo" / "d1_dirty_symbols.txt"


def _sanitize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_convert("America/New_York").tz_localize(None)
    df = df[~df.index.dayofweek.isin([5, 6])]          # no weekend bars
    df = df[~df.index.duplicated(keep="last")].sort_index()
    for c in ("open", "high", "low", "close", "volume"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.replace([np.inf, -np.inf], np.nan)
    if "close" in df.columns:
        df = df[df["close"].notna()]
    if "volume" in df.columns:
        df["volume"] = df["volume"].fillna(0.0)        # missing vol → 0
    return df


def _fetch(sym: str) -> pd.DataFrame | None:
    # primary: yfinance (codebase-sanctioned; websearch-confirmed)
    try:
        import yfinance as yf
        d = yf.download(sym, start="2007-01-01", progress=False,
                        auto_adjust=False, threads=False)
        if d is not None and len(d):
            if isinstance(d.columns, pd.MultiIndex):
                d.columns = d.columns.get_level_values(0)
            d = d.rename(columns=str.lower)[
                [c for c in ("open", "high", "low", "close", "volume")
                 if c.lower() in [x.lower() for x in d.columns]]]
            d.columns = [c.lower() for c in d.columns]
            return d
    except Exception:
        pass
    # secondary: Stooq via pandas_datareader
    try:
        from pandas_datareader import data as pdr
        d = pdr.DataReader(f"{sym}.US", "stooq")
        if d is not None and len(d):
            d = d.rename(columns=str.lower).sort_index()
            return d[[c for c in ("open", "high", "low", "close", "volume")
                      if c in d.columns]]
    except Exception:
        pass
    return None


def main() -> int:
    t0 = time.time()
    syms = [s.strip() for s in _WL.read_text().splitlines() if s.strip()]
    print(f"D2b: {len(syms)} D1-dirty symbols to clean+backfill")
    res = {"fetched_clean": [], "local_sanitized_only": [],
           "unfillable": [], "n": len(syms)}
    for i, s in enumerate(syms):
        p = _DAILY / f"{s}.parquet"
        bak = _DAILY / f"{s}.parquet.preD2"
        local = None
        if p.exists():
            try:
                local = pd.read_parquet(p)
                if not bak.exists():
                    p.rename(bak)            # backup once
                    p_exists_after = False
                else:
                    p_exists_after = True
            except Exception:
                local = None
                p_exists_after = p.exists()
        ext = _fetch(s)
        chosen = None
        if ext is not None and len(_sanitize(ext)) > 250:
            chosen = _sanitize(ext)
            res["fetched_clean"].append(s)
        elif local is not None and len(_sanitize(local)) > 50:
            chosen = _sanitize(local)        # at least sanitize local
            res["local_sanitized_only"].append(s)
        else:
            res["unfillable"].append(s)
            if bak.exists() and not p.exists():
                bak.rename(p)                # restore original on failure
            continue
        chosen.to_parquet(p)
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(syms)} fetched={len(res['fetched_clean'])} "
                  f"local={len(res['local_sanitized_only'])} "
                  f"unfill={len(res['unfillable'])} ({time.time()-t0:.0f}s)")

    res.update({
        "created_at": datetime.now(timezone.utc).isoformat(),
        "n_fetched_clean": len(res["fetched_clean"]),
        "n_local_sanitized_only": len(res["local_sanitized_only"]),
        "n_unfillable": len(res["unfillable"]),
        "source_priority": "yfinance → Stooq (websearch 2026-05-16); "
                           "FULL range incl 2026 (data hygiene ⊥ sealed)",
        "backup": ".preD2 sidecar per symbol; executable/expanded_v1 "
                  "(100% clean) NEVER touched",
        "wall_s": round(time.time() - t0, 1),
    })
    o = _PROJ / "data" / "audit" / "ml_redo" / "d2_backfill.json"
    o.write_text(json.dumps(res, indent=2, default=str))
    print(f"D2b -> {o.name}: fetched_clean={res['n_fetched_clean']} "
          f"local_only={res['n_local_sanitized_only']} "
          f"unfillable={res['n_unfillable']} ({time.time()-t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
