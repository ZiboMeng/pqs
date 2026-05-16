"""P4·R2 — ingest the expanded-universe symbols via the FIXED yfinance path.

Per chart-structure ralph-loop execution PRD §8 round P4·R2 (P4-d1 ingest
+ P4-d3 integrity smoke). Reads ``/tmp/p4_sel.json`` (produced by the
audit step: {selected, corrupt, clean}) and re-fetches the ``corrupt``
symbols — the 240 long-coverage tickers carrying weekend-row date-label
corruption (the SPY off-by-one bug class, see
``docs/memos/20260513-spy_off_by_one_date_label_postmortem.md``) — using
``YFinanceProvider(auto_adjust=True)`` which routes through the fixed
``align_daily_index``.

auto_adjust=True (split + dividend adjusted continuous series) is the
deliberate choice for expanded_v1: it is a D6-isolated RESEARCH universe,
never touches execution, and chart-structure features need a continuous
price series free of split discontinuities. The executable 79 are
untouched (resolver builds the base from config — bit-for-bit).

Each re-fetch is validated (0 weekend rows, 2015 start, recent end,
monotonic, no dupes); the pre-existing corrupt parquet is preserved as a
``.preP4Expand_<ts>`` sidecar; ``bar_provenance.parquet`` is updated
synchronously (CLAUDE.md hard rule).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

_PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJ))

from core.data.yfinance_provider import YFinanceProvider  # noqa: E402

_DAILY = _PROJ / "data" / "daily"
_PROV = _PROJ / "data" / "ref" / "bar_provenance.parquet"
_SEL = Path("/tmp/p4_sel.json")
_START = "2015-01-01"
_END = "2026-05-16"
_BATCH = 40
_RULE = "p4_expanded_v1_2026-05-16"


def _validate(df: pd.DataFrame, sym: str) -> str:
    if df is None or df.empty:
        return "empty"
    idx = df.index
    if ((idx.dayofweek == 5) | (idx.dayofweek == 6)).any():
        return "weekend_rows"
    if not idx.is_monotonic_increasing:
        return "not_sorted"
    if idx.duplicated().any():
        return "dup_dates"
    if idx[0] > pd.Timestamp("2015-02-01"):
        return f"late_start:{idx[0].date()}"
    if idx[-1] < pd.Timestamp("2026-04-01"):
        return f"stale_end:{idx[-1].date()}"
    if len(df) < 2500:
        return f"short:{len(df)}"
    return ""


def main() -> int:
    sel = json.loads(_SEL.read_text())
    to_fetch = sel["corrupt"]
    print(f"re-fetching {len(to_fetch)} corrupt symbols in batches of {_BATCH}")
    prov = YFinanceProvider(auto_adjust=True, progress=False)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")

    ok: list[str] = []
    failed: dict[str, str] = {}
    prov_rows: list[dict] = []

    for i in range(0, len(to_fetch), _BATCH):
        batch = to_fetch[i:i + _BATCH]
        print(f"  batch {i // _BATCH + 1}: {batch[0]}..{batch[-1]}", flush=True)
        try:
            res = prov.fetch_daily(batch, start=_START, end=_END)
        except Exception as e:  # noqa: BLE001
            for s in batch:
                failed[s] = f"batch_error:{e}"
            continue
        for sym in batch:
            if sym not in res:
                failed[sym] = "no_data"
                continue
            df = res[sym].df
            need = ["open", "high", "low", "close", "volume"]
            if df is None or any(c not in df.columns for c in need):
                failed[sym] = "missing_cols"
                continue
            df = df[need].copy()
            df["amount"] = 0.0
            reason = _validate(df, sym)
            if reason:
                failed[sym] = reason
                continue
            path = _DAILY / f"{sym}.parquet"
            if path.exists():
                path.rename(_DAILY / f"{sym}.parquet.preP4Expand_{ts}")
            df.to_parquet(path)
            ok.append(sym)
            prov_rows.append({
                "symbol": sym, "freq": "1d", "source_type": "yfinance_daily",
                "rule_version": _RULE,
                "first_bar_ts": df.index[0], "last_bar_ts": df.index[-1],
                "n_bars_added": float(len(df)),
                "updated_at": pd.Timestamp.utcnow().tz_localize(None),
            })

    if prov_rows:
        prov_df = pd.read_parquet(_PROV)
        prov_df = pd.concat([prov_df, pd.DataFrame(prov_rows)], ignore_index=True)
        prov_df.to_parquet(_PROV)
        print(f"bar_provenance.parquet: +{len(prov_rows)} rows")

    print(f"\nOK={len(ok)}  FAILED={len(failed)}")
    for s, r in sorted(failed.items()):
        print(f"  FAIL {s}: {r}")
    json.dump({"ok": ok, "failed": failed}, open("/tmp/p4_ingest_result.json", "w"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
