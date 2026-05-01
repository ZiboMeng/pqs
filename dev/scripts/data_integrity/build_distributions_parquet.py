"""Build data/ref/distributions.parquet for cross-asset cycle #04 preflight.

Schema (mirrors data/ref/splits.parquet structure):
  symbol             str   (ticker, e.g., TLT)
  ex_date            date  (NYSE trading date the ex-dividend is applied)
  cash_amount        float (cash dividend in $/share, post-split units)
  ref_close_pre_ex   float (close on the trading day BEFORE ex_date, in
                            split-adjusted units at fetch time)
  factor             float (= 1.0 - cash_amount / ref_close_pre_ex; the
                            multiplicative adjustment applied to all closes
                            at t < ex_date to convert price-only to total
                            return)
  source             str   (e.g., "yfinance_dividends_2026_05")
  pulled_at          str   (UTC timestamp when fetched, ISO8601)
  splits_table_sha   str   (sha256[:16] of data/ref/splits.parquet at build
                            time — invariant tracker; if splits.parquet
                            changes, distributions sidecar must rebuild)

Source rationale:
  - yfinance Dividends column is the primary source. For 7 mainstream ETFs
    (TLT/IEF/SHY/GLD/USO/BIL/SHV) yfinance back-data quality is acceptable.
  - Convention: factor = 1 - X/close_pre_ex matches yfinance's own
    auto_adjust=True cascade. This makes BarStore.load(adjusted_total_return=
    True) numerically reproducible against `yf.Ticker(...).history(
    auto_adjust=True).Close` within float tolerance.
  - Production pipeline upgrade path: when paid feed (Refinitiv / Bloomberg)
    is licensed, replace `source` with that provider; the schema is stable.

Composition with splits.parquet (R4 boundary):
  - cash_amount + ref_close_pre_ex are stamped at fetch time, in the split-
    adjusted units the BarStore exposes via load(adjusted=True).
  - If splits.parquet later updates (new split filed), the cash_amount and
    ref_close_pre_ex stamped here become stale relative to the new split-
    adjusted basis. splits_table_sha enforces invariant: BarStore.load()
    fail-closes if splits.parquet sha != stamped sha (TODO in BarStore).

Usage:
  python dev/scripts/data_integrity/build_distributions_parquet.py \\
    --symbols TLT IEF SHY GLD USO BIL SHV \\
    --start 2002-01-01 \\
    --output data/ref/distributions.parquet

  # dry-run preview (won't write):
  python dev/scripts/data_integrity/build_distributions_parquet.py \\
    --symbols TLT --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

PROJ = Path("/home/zibo/Documents/projects/pqs")
DEFAULT_OUTPUT = PROJ / "data" / "ref" / "distributions.parquet"
SPLITS_PATH = PROJ / "data" / "ref" / "splits.parquet"

DEFAULT_SOURCE_TAG = "yfinance_dividends_2026_05"


def _splits_table_sha() -> str:
    """sha256[:16] of splits.parquet bytes — invariant tracker."""
    if not SPLITS_PATH.exists():
        return "no_splits_table"
    return hashlib.sha256(SPLITS_PATH.read_bytes()).hexdigest()[:16]


def _fetch_distributions_yfinance(
    symbol: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> pd.DataFrame:
    """Fetch one symbol's dividend history + the close on the trading day
    BEFORE each ex-date. Returns DataFrame ready for sidecar write.

    Implementation notes:
      - yfinance Ticker.dividends returns a DatetimeIndex Series with
        TZ-aware ex-dates. Normalize to NYSE date (no time, no tz).
      - For each ex-date d, ref_close_pre_ex = close on trading day BEFORE d.
        We get this from yfinance's full history (auto_adjust=False) so the
        close is in raw $ units (will be split-adjusted on load via splits
        cascade — see composition note in module docstring).
        Actually, for the factor math to compose cleanly with the splits
        cascade, we need ref_close_pre_ex in the SAME basis as the bars
        at load time. BarStore.load(adjusted=True) returns split-adjusted
        bars. So ref_close_pre_ex MUST be split-adjusted too.
        yfinance's auto_adjust=False gives raw (non-split-adjusted) close;
        we apply splits.parquet ourselves to get split-adjusted reference.
      - Skip dividends with cash_amount = 0 or NaN (no-op).
      - Skip dividends where ref_close_pre_ex is missing (early data gap).
    """
    import yfinance as yf  # lazy import

    sys.path.insert(0, str(PROJ))
    from core.data.bar_store import BarStore

    store = BarStore(root=PROJ / "data")
    ticker = yf.Ticker(symbol)

    divs = ticker.dividends
    if divs is None or len(divs) == 0:
        return pd.DataFrame(columns=[
            "symbol", "ex_date", "cash_amount", "ref_close_pre_ex",
            "factor", "source", "pulled_at", "splits_table_sha",
        ])

    # Normalize ex_date to NYSE date (drop time + tz)
    divs = divs.copy()
    if hasattr(divs.index, "tz") and divs.index.tz is not None:
        divs.index = divs.index.tz_convert("America/New_York").tz_localize(None)
    divs.index = divs.index.normalize()

    # Apply optional date range
    if start is not None:
        divs = divs[divs.index >= pd.Timestamp(start)]
    if end is not None:
        divs = divs[divs.index <= pd.Timestamp(end)]

    # Drop zero / NaN dividends
    divs = divs[(divs > 0) & divs.notna()]
    if len(divs) == 0:
        return pd.DataFrame(columns=[
            "symbol", "ex_date", "cash_amount", "ref_close_pre_ex",
            "factor", "source", "pulled_at", "splits_table_sha",
        ])

    # Load split-adjusted daily close from BarStore (so reference is in same
    # basis as load-time bars)
    bars = store.load(symbol, freq="1d", adjusted=True, fallback="local")
    if bars is None or bars.empty or "close" not in bars.columns:
        # Fall back to yfinance auto_adjust=False close (no splits applied)
        # — caller should be aware splits cascade may diverge.
        hist = ticker.history(start="1990-01-01", auto_adjust=False)
        if hist.empty:
            return pd.DataFrame(columns=[
                "symbol", "ex_date", "cash_amount", "ref_close_pre_ex",
                "factor", "source", "pulled_at", "splits_table_sha",
            ])
        if hasattr(hist.index, "tz") and hist.index.tz is not None:
            hist.index = hist.index.tz_convert("America/New_York").tz_localize(None)
        hist.index = hist.index.normalize()
        close_series = hist["Close"]
    else:
        close_series = bars["close"].copy()
        if hasattr(close_series.index, "tz") and close_series.index.tz is not None:
            close_series.index = (
                close_series.index.tz_convert("America/New_York").tz_localize(None)
            )
        close_series.index = close_series.index.normalize()

    # Build sidecar rows
    pulled_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sha = _splits_table_sha()
    rows = []
    for ex_date, cash_amount in divs.items():
        # Find prior trading day close. We use close_series index — find
        # the largest date strictly BEFORE ex_date.
        prior_idx = close_series.index[close_series.index < ex_date]
        if len(prior_idx) == 0:
            continue  # ex-date predates our data; skip
        prior_date = prior_idx.max()
        ref = float(close_series.loc[prior_date])
        if not np.isfinite(ref) or ref <= 0:
            continue
        cash = float(cash_amount)
        factor = 1.0 - cash / ref
        if not (0 < factor <= 1.0001):
            # sanity: factor must be in (0, 1] modulo float epsilon
            print(
                f"  WARN {symbol} ex_date={ex_date.date()}: factor={factor:.6f} "
                f"out of (0,1]; cash={cash:.4f} ref={ref:.4f}; SKIPPED"
            )
            continue
        rows.append({
            "symbol": symbol,
            "ex_date": ex_date.date(),
            "cash_amount": cash,
            "ref_close_pre_ex": ref,
            "factor": factor,
            "source": DEFAULT_SOURCE_TAG,
            "pulled_at": pulled_at,
            "splits_table_sha": sha,
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df["ex_date"] = pd.to_datetime(df["ex_date"])
    return df


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--symbols", nargs="+", required=True,
                    help="Tickers to fetch (e.g., TLT IEF SHY GLD USO BIL SHV)")
    ap.add_argument("--start", default=None,
                    help="Earliest ex_date (default: all history)")
    ap.add_argument("--end", default=None,
                    help="Latest ex_date (default: all history)")
    ap.add_argument("--output", default=str(DEFAULT_OUTPUT),
                    help=f"Output parquet (default: {DEFAULT_OUTPUT})")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print summary without writing parquet")
    ap.add_argument("--append", action="store_true",
                    help="If output exists, merge (replace by symbol)")
    args = ap.parse_args()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[distributions builder] sha(splits.parquet)={_splits_table_sha()}")
    print(f"[distributions builder] symbols: {args.symbols}")
    print(f"[distributions builder] range: {args.start or 'all'} → {args.end or 'all'}")

    all_rows = []
    for sym in args.symbols:
        print(f"  fetching {sym}...")
        df = _fetch_distributions_yfinance(sym, start=args.start, end=args.end)
        print(f"    {len(df)} dividend events")
        if not df.empty:
            print(f"    range: {df['ex_date'].min().date()} → "
                  f"{df['ex_date'].max().date()}; "
                  f"total cash = ${df['cash_amount'].sum():.2f}")
        all_rows.append(df)

    new_df = pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame()
    if new_df.empty:
        print("[distributions builder] no events fetched; nothing to write")
        return 0

    if args.dry_run:
        print(f"\n[distributions builder] DRY-RUN: would write {len(new_df)} rows to {out_path}")
        print(new_df.groupby("symbol").size().to_string())
        return 0

    # Merge with existing if requested
    if args.append and out_path.exists():
        existing = pd.read_parquet(out_path)
        # Drop existing rows for symbols we're rewriting
        keep_mask = ~existing["symbol"].isin(new_df["symbol"].unique())
        existing = existing[keep_mask]
        out_df = pd.concat([existing, new_df], ignore_index=True)
    else:
        out_df = new_df

    out_df = out_df.sort_values(["symbol", "ex_date"]).reset_index(drop=True)
    out_df.to_parquet(out_path, index=False)
    print(f"\n[distributions builder] wrote {len(out_df)} rows to {out_path}")
    print(f"  per-symbol counts:\n{out_df.groupby('symbol').size().to_string()}")

    # Provenance write to bar_provenance.parquet
    prov_path = PROJ / "data" / "ref" / "bar_provenance.parquet"
    if prov_path.exists():
        prov = pd.read_parquet(prov_path)
        prov_rows = []
        for sym in new_df["symbol"].unique():
            sym_df = new_df[new_df["symbol"] == sym]
            prov_rows.append({
                "symbol": sym, "freq": "distributions",
                "source_type": DEFAULT_SOURCE_TAG,
                "rule_version": "factor_eq_1_minus_X_over_prior_close",
                "first_bar_ts": sym_df["ex_date"].min(),
                "last_bar_ts": sym_df["ex_date"].max(),
                "n_bars_added": len(sym_df),
                "updated_at": pd.Timestamp.now(),
            })
        prov_new = pd.DataFrame(prov_rows)
        # Drop existing distribution rows for these symbols
        keep_mask = ~(
            (prov["symbol"].isin(new_df["symbol"].unique()))
            & (prov["freq"] == "distributions")
        )
        prov = prov[keep_mask]
        prov_out = pd.concat([prov, prov_new], ignore_index=True)
        prov_out.to_parquet(prov_path, index=False)
        print(f"[distributions builder] provenance updated: "
              f"+{len(prov_new)} rows in {prov_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
