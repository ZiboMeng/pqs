#!/usr/bin/env python3
"""
trades_scanner.py — Watch trades zip directory, decrypt, aggregate to 1m bars,
write ETF backfill data (Strategy B), then delete zip to free disk.

Design:
  - Password = sha256(basename + "vvtr123!@#qwe") hex
  - Strategy B: skip any ticker already present in .staging/*/*.parquet
    (stocks-only + gz sources); only write *new* tickers (primarily ETFs).
  - Writes to data/intraday/1m/.staging_trades/<YYYY-MM>/<SYM>.parquet.
    Separate dir from .staging/ so we can distinguish provenance later.
  - Updates data/ref/bar_provenance.parquet sidecar (symbol, freq, source_type,
    rule_version, first_bar_ts, last_bar_ts, n_bars, updated_at).
  - State file data/trades_scanner_state.json — resume after crash.
  - Logs to logs/trades_scanner_YYYYMMDD.log + stdout.
  - QA report per zip: reports/trades_backfill_qa/<date>.json.
  - Delete zip only after successful write + state flush (atomic swap).

Run modes:
  --once                Scan once and exit (default)
  --watch               Poll forever (60s interval) for new zips
  --trades-root PATH    Override trades root (default /mnt/c/.../trades)
  --dry-run             Do not write parquet or delete zip
  --no-delete           Write bars but do not delete zip
  --only-zip FILE       Process a single zip file (useful for testing)
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv
import pyzipper

# =============================================================================
# Configuration
# =============================================================================

TRADES_ROOT_DEFAULT = Path("/mnt/c/Users/Admin/Documents/projects/trades")
PQS_ROOT = Path(os.path.expanduser("~/Documents/projects/pqs"))
STAGING = PQS_ROOT / "data" / "intraday" / "1m" / ".staging"
STAGING_TRADES = PQS_ROOT / "data" / "intraday" / "1m" / ".staging_trades"
PROVENANCE_FILE = PQS_ROOT / "data" / "ref" / "bar_provenance.parquet"
DEFAULT_STATE_FILE = PQS_ROOT / "data" / "trades_scanner_state.json"
LOGS_DIR = PQS_ROOT / "logs"
QA_DIR = PQS_ROOT / "reports" / "trades_backfill_qa"

SALT = "vvtr123!@#qwe"
ET = "America/New_York"
BLOCK_THRESH = 10_000
RULE_VERSION = "trades_v2_late_report_dedup_2026-04-19"
SOURCE_TYPE = "trades_backfill"

# Vendor's condition codes (NOT Polygon standard — from vendor docs):
#   14,16,18,19,20,22 — various late-reported trades (duplicates of real trades)
#   29,31,32,33,34     — delayed block / delayed bunched
#   38,39              — corrected close (by listing market) — late re-report
#   42,43,45,47,48     — delayed exempt / special / temporary
#   49,50,51,54,55,56,57,58 — delayed regular/sell/premarket/intraday/benchmark
# All of these duplicate earlier first-report trades at the tick level.
# Condition 8 = "placeholder reserved for future" — ambiguous; keep for now.
# Condition 59 = Rule 611 exempt placeholder — also ambiguous; keep for now.
LATE_REPORT_CONDS = frozenset({
    14, 16, 18, 19, 20, 22,
    29, 31, 32, 33, 34,
    38, 39,
    42, 43, 45, 47, 48,
    49, 50, 51, 54, 55, 56, 57, 58,
})
# FINRA Alternative Display Facility — OTC TRF reports that duplicate
# exchange-reported trades; drop.
DROP_EXCHANGES = frozenset({4})

ZIP_PATTERN = re.compile(r"^(\d{8})\.zip$")
DOWNLOADING_SUFFIXES = (".baiduyun.p.downloading", ".part", ".tmp", ".download", ".crdownload")
MIN_FILE_AGE_SECONDS = 30
POLL_INTERVAL_SECONDS = 60

# Default temp file for decrypt → parse handoff. CLI --decrypt-tmp overrides
# (must be unique per scanner instance when running multiple in parallel).
DEFAULT_DECRYPT_TMP = Path("/tmp/trades_scanner_decrypt.csv")

# Cross-process lock file. Scanners serialize through here for the parse +
# filter + aggregate phase (peak memory ~5-8GB). Decrypt and write happen
# outside the lock so I/O still parallelises. Default path on /tmp is safe
# for fcntl.flock (local fs).
PEAK_LOCK_FILE = Path("/tmp/trades_scanner_peak.lock")


# =============================================================================
# Logging
# =============================================================================

def setup_logging(log_file: Path) -> logging.Logger:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("trades_scanner")
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt)
    for h in list(logger.handlers):
        logger.removeHandler(h)
    logger.addHandler(fh)
    logger.addHandler(sh)
    logger.propagate = False
    return logger


# =============================================================================
# Utilities
# =============================================================================

def safe_symbol(s: str) -> str:
    return s.replace("^", "_").replace("-", "_")


def make_password(zip_path: Path) -> str:
    return hashlib.sha256(f"{zip_path.name}{SALT}".encode("utf-8")).hexdigest()


def is_downloading_temp(p: Path) -> bool:
    for suf in DOWNLOADING_SUFFIXES:
        if p.name.endswith(suf):
            return True
    for suf in DOWNLOADING_SUFFIXES:
        sib = p.parent / f"{p.name}{suf}"
        if sib.exists():
            return True
    return False


def _parse_date_from_zip(p: Path) -> str:
    m = ZIP_PATTERN.match(p.name)
    if not m:
        raise ValueError(f"cannot parse date from {p.name}")
    d = m.group(1)
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"


# =============================================================================
# State file
# =============================================================================

def load_state(state_file: Path = DEFAULT_STATE_FILE) -> dict:
    if state_file.exists():
        try:
            return json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"processed": {}, "failed": {}, "last_scan_at": None}


def save_state(state: dict, state_file: Path = DEFAULT_STATE_FILE) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    tmp.replace(state_file)


# =============================================================================
# Strategy B: existing ticker snapshot
# =============================================================================

def build_existing_tickers_per_month() -> dict[str, set[str]]:
    """Return {month_tag -> set(safe_symbol present in .staging/<month>/*.parquet)}.
    Strategy B skips a ticker for a given zip's month iff the ticker is already
    populated in .staging for THAT month (from stocks-only or gz sources).
    Per-month rather than global — ETFs exist in 2015-2023 gz but NOT in 2024+
    stocks-only, so we must backfill 2024+ zip even for tickers that show up in
    older staging months.
    """
    per_month: dict[str, set[str]] = {}
    if not STAGING.exists():
        return per_month
    for month in STAGING.iterdir():
        if not month.is_dir():
            continue
        per_month[month.name] = {f.stem for f in month.glob("*.parquet")}
    return per_month


# =============================================================================
# Zip discovery
# =============================================================================

def list_new_zips(trades_root: Path, state: dict,
                  year_filters: tuple[str, ...] = ()) -> list[Path]:
    """Return sorted list of unprocessed zips under trades_root.
    If year_filters is non-empty, only zips whose filename starts with any
    listed prefix (e.g. '2024') are returned — used for parallel scanners
    where each instance owns a year subset.
    """
    if not trades_root.exists():
        return []
    out: list[Path] = []
    now = time.time()
    processed = state.get("processed", {})
    for p in trades_root.rglob("*.zip"):
        if not ZIP_PATTERN.match(p.name):
            continue
        if year_filters and not any(p.name.startswith(y) for y in year_filters):
            continue
        if is_downloading_temp(p):
            continue
        try:
            st = p.stat()
        except FileNotFoundError:
            continue
        if now - st.st_mtime < MIN_FILE_AGE_SECONDS:
            continue
        key = str(p)
        rec = processed.get(key)
        if rec and rec.get("status") == "done":
            continue
        out.append(p)
    return sorted(out)


# =============================================================================
# Aggregation
# =============================================================================

@contextmanager
def peak_memory_lock(logger: logging.Logger, lock_file: Path = PEAK_LOCK_FILE):
    """Cross-process exclusive lock around the parse + filter + aggregate
    phase. Multiple scanner instances share this file via fcntl.LOCK_EX so
    only one holds the heavy memory phase at a time. Decrypt (CPU+I/O) and
    parquet write (I/O) happen outside the lock and remain parallel.
    """
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with open(lock_file, "w") as lockf:
        fcntl.flock(lockf, fcntl.LOCK_EX)
        wait_dt = time.time() - t0
        if wait_dt > 1.0:
            logger.info(f"  acquired peak lock after {wait_dt:.1f}s wait")
        try:
            yield wait_dt
        finally:
            pass  # lock auto-released when lockf closes


def _has_late_report_cond(cond_str: str) -> bool:
    """Return True if any code in the comma-separated conditions string is a
    late-report duplicate we want to drop."""
    if not cond_str or cond_str == "<NA>":
        return False
    for c in cond_str.split(","):
        c = c.strip()
        if not c:
            continue
        try:
            if int(c) in LATE_REPORT_CONDS:
                return True
        except ValueError:
            continue
    return False


def aggregate_zip(zip_path: Path, password: str, skip_tickers: set[str],
                  logger: logging.Logger,
                  decrypt_tmp: Path = DEFAULT_DECRYPT_TMP,
                  ) -> tuple[dict[str, pd.DataFrame], dict]:
    """Stream-decrypt zip and aggregate 1m bars.
    Returns (ticker → day_bars_df, stats).
    Only tickers NOT in skip_tickers are included.

    Filter chain per trade:
      - Strategy B: ticker not in skip_tickers (per-month snapshot)
      - correction < 1 (drop corrected/cancelled)
      - exchange not in DROP_EXCHANGES (drop FINRA ADF OTC duplicate prints)
      - conditions does not contain any LATE_REPORT_CONDS code
    """
    t0 = time.time()
    lock_wait_dt = 0.0
    try:
        # Phase 1: decrypt zip → temp CSV (parallel-safe: I/O + AES, no shared
        # heavy memory). Multiple scanners can decrypt simultaneously.
        with pyzipper.AESZipFile(zip_path) as z:
            z.setpassword(password.encode("utf-8"))
            names = z.namelist()
            # Some 2025-03+ zips include both 'trades_*.csv' and
            # 'minute_aggs_v1_*.csv' (pre-built minute bars we don't need).
            # Pick the trades CSV; fail only if no trades CSV present.
            csv_names = [n for n in names if n.endswith(".csv")]
            trades_csv = [n for n in csv_names if "trades" in n.lower()]
            if not trades_csv:
                raise RuntimeError(f"no trades csv found in zip: {names}")
            inner = trades_csv[0]
            if len(names) > 1:
                other = [n for n in names if n != inner]
                logger.info(f"  multi-file zip, ignoring {other}, using {inner}")
            logger.info(f"  decrypting {inner} "
                        f"({z.getinfo(inner).file_size/1e9:.2f}GB) → {decrypt_tmp}")
            decrypt_tmp.parent.mkdir(parents=True, exist_ok=True)
            with z.open(inner) as src, open(decrypt_tmp, "wb") as dst:
                shutil.copyfileobj(src, dst, length=8 * 1024 * 1024)
        decrypt_dt = time.time() - t0

        # Phase 2: parse + filter + aggregate under cross-process lock. Peak
        # memory ~5-8GB; only one scanner instance holds the lock at a time
        # to avoid OOM. Decrypt above and parquet write later are NOT under
        # the lock so I/O still parallelises.
        with peak_memory_lock(logger) as lock_wait_dt:
            t1 = time.time()
            read_opts = pacsv.ReadOptions(use_threads=True,
                                          block_size=64 * 1024 * 1024)
            conv_opts = pacsv.ConvertOptions(
                include_columns=["ticker", "conditions", "correction", "exchange",
                                 "price", "sip_timestamp", "size"],
                column_types={
                    "ticker": pa.string(),
                    "conditions": pa.string(),
                    "correction": pa.int32(),
                    "exchange": pa.int32(),
                    "price": pa.float64(),
                    "sip_timestamp": pa.int64(),
                    # size: float64 not int64 — 2026 data occasionally formats
                    # integer share counts as "10.000000" which would fail int64
                    # parse. We cast to int64 after to_pandas (below).
                    "size": pa.float64(),
                },
                null_values=[""],
                strings_can_be_null=True,
            )
            table = pacsv.read_csv(decrypt_tmp, read_options=read_opts,
                                   convert_options=conv_opts)
            parse_dt = time.time() - t1
            n_rows_total = table.num_rows

            # decrypt_tmp no longer needed — free disk early
            try:
                decrypt_tmp.unlink()
            except Exception:
                pass

            # Vectorised filters in pyarrow.
            # null handling mirrors pandas: null ticker/exchange → kept,
            # null correction → treated as 0.
            t2 = time.time()
            skip_arr = pa.array(list(skip_tickers), type=pa.string())
            in_skip = pc.fill_null(
                pc.is_in(table["ticker"], value_set=skip_arr), False
            )
            mask = pc.invert(in_skip)
            corr = pc.fill_null(table["correction"], 0)
            mask = pc.and_kleene(mask, pc.less(corr, 1))
            drop_exch_arr = pa.array(list(DROP_EXCHANGES), type=pa.int32())
            in_drop_exch = pc.fill_null(
                pc.is_in(table["exchange"], value_set=drop_exch_arr), False
            )
            mask = pc.and_kleene(mask, pc.invert(in_drop_exch))
            table = table.filter(mask)

            df = table.to_pandas()
            del table
            cond_mask = df["conditions"].fillna("").astype(str).map(_has_late_report_cond)
            df = df[~cond_mask]
            df = df.dropna(subset=["sip_timestamp", "price", "size"])
            # Cast size float64 → int64 after dropna (see note at column_types).
            df["size"] = df["size"].astype("int64")
            df = df.drop(columns=["conditions"])
            filter_dt = time.time() - t2
            n_rows_kept = len(df)

            load_dt = time.time() - t0
            logger.info(f"  decrypt {decrypt_dt:.1f}s | "
                        f"lock_wait {lock_wait_dt:.1f}s | "
                        f"parse {parse_dt:.1f}s | filter {filter_dt:.1f}s | "
                        f"kept {n_rows_kept:,} / {n_rows_total:,} rows "
                        f"in {load_dt:.1f}s")
            if df.empty:
                return {}, {"n_rows_total": int(n_rows_total),
                            "n_rows_kept": 0, "n_tickers": 0,
                            "load_seconds": round(load_dt, 2),
                            "decrypt_seconds": round(decrypt_dt, 2),
                            "lock_wait_seconds": round(lock_wait_dt, 2),
                            "parse_seconds": round(parse_dt, 2),
                            "filter_seconds": round(filter_dt, 2),
                            "agg_seconds": 0.0}

            # Aggregate (still under lock — moderate but non-trivial memory)
            agg_t0 = time.time()
            ts = pd.to_datetime(df["sip_timestamp"], unit="ns", utc=True
                                ).dt.tz_convert(ET).dt.tz_localize(None)
            df["bar"] = ts.dt.floor("1min")
            df["amount_each"] = df["price"] * df["size"]
            df["is_block"] = df["size"] >= BLOCK_THRESH

            g_tb = df.groupby(["ticker", "bar"], sort=True)
            core = g_tb.agg(
                open=("price", "first"),
                high=("price", "max"),
                low=("price", "min"),
                close=("price", "last"),
                volume=("size", "sum"),
                amount=("amount_each", "sum"),
                n_trades=("price", "size"),
            )
            # Top exchange share
            ev = df.groupby(["ticker", "bar", "exchange"], sort=False)["size"].sum()
            top1 = ev.groupby(level=[0, 1]).max().rename("top1_vol")
            core = core.join(top1)
            core["exch_top1_volume_share"] = (
                core["top1_vol"] / core["volume"].astype("float64")
            ).fillna(1.0).clip(upper=1.0).astype("float32")
            core = core.drop(columns=["top1_vol"])

            # Conditional aggregations
            if df["is_block"].any():
                block_g = df[df["is_block"]].groupby(["ticker", "bar"], sort=False)
                core = core.join(block_g["size"].sum().rename("large_trade_volume"))
                core = core.join(block_g.size().rename("block_n"))
            core["large_trade_volume"] = core.get("large_trade_volume", 0).fillna(0).astype("int64")
            core["block_n"] = core.get("block_n", 0).fillna(0).astype("int32")

            # Buy/sell proxies using bar mid
            mid = (core["high"] + core["low"]) / 2.0
            df = df.join(mid.rename("mid"), on=["ticker", "bar"])
            df["buy_side"] = df["price"] >= df["mid"]
            buy_g = df[df["buy_side"]].groupby(["ticker", "bar"], sort=False)["size"].sum().rename("buy_volume_proxy")
            sell_g = df[~df["buy_side"]].groupby(["ticker", "bar"], sort=False)["size"].sum().rename("sell_volume_proxy")
            core = core.join(buy_g).join(sell_g)
            core["buy_volume_proxy"] = core["buy_volume_proxy"].fillna(0).astype("int64")
            core["sell_volume_proxy"] = core["sell_volume_proxy"].fillna(0).astype("int64")

            core["vwap"] = (
                core["amount"] / core["volume"].astype("float64")
            ).astype("float32")
            core["avg_trade_size"] = (
                core["volume"].astype("float64") / core["n_trades"].astype("float64")
            ).astype("float32")

            core = core.astype({
                "open": "float32", "high": "float32", "low": "float32", "close": "float32",
                "volume": "int64", "amount": "float64", "n_trades": "int32",
            })
            core["source_type"] = SOURCE_TYPE
            core["ingestion_rule_version"] = RULE_VERSION

            col_order = ["open", "high", "low", "close", "volume", "amount", "n_trades",
                         "vwap", "avg_trade_size", "large_trade_volume", "block_n",
                         "buy_volume_proxy", "sell_volume_proxy", "exch_top1_volume_share",
                         "source_type", "ingestion_rule_version"]
            core = core[col_order]

            # Split per ticker (returned dict; downstream writes outside lock)
            out: dict[str, pd.DataFrame] = {}
            for tkr, sub in core.groupby(level=0):
                sub = sub.droplevel(0)
                sub.index.name = "timestamp"
                out[str(tkr)] = sub

            agg_dt = time.time() - agg_t0
            logger.info(f"  aggregated {len(out)} tickers × "
                        f"~{len(core)//max(1, len(out))} bars in {agg_dt:.1f}s")
            return out, {
                "n_rows_total": int(n_rows_total),
                "n_rows_kept": int(n_rows_kept),
                "n_tickers": len(out),
                "load_seconds": round(load_dt, 2),
                "decrypt_seconds": round(decrypt_dt, 2),
                "lock_wait_seconds": round(lock_wait_dt, 2),
                "parse_seconds": round(parse_dt, 2),
                "filter_seconds": round(filter_dt, 2),
                "agg_seconds": round(agg_dt, 2),
            }
    finally:
        if decrypt_tmp.exists():
            try:
                decrypt_tmp.unlink()
            except Exception:
                pass


# =============================================================================
# Writer
# =============================================================================

def write_ticker_day(sym: str, day_df: pd.DataFrame, month_tag: str,
                     dry_run: bool = False) -> int:
    """Append one day's bars to .staging_trades/<YYYY-MM>/<SYM>.parquet.
    Returns number of bars written.

    Atomic write: new data goes to <SYM>.parquet.tmp then os.replace → <SYM>.parquet.
    If the process crashes mid-write, only .tmp is corrupt; the main file stays intact.
    """
    if dry_run:
        return len(day_df)
    d = STAGING_TRADES / month_tag
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{safe_symbol(sym)}.parquet"
    tmp = f.with_suffix(".parquet.tmp")
    if f.exists():
        existing = pd.read_parquet(f)
        combined = pd.concat([existing, day_df])
        combined = combined[~combined.index.duplicated(keep="last")]
        combined = combined.sort_index()
    else:
        combined = day_df.sort_index()
    combined.to_parquet(tmp, compression="snappy")
    tmp.replace(f)  # atomic
    return len(day_df)


def cleanup_stale_tmp_files(logger: logging.Logger,
                            year_filters: tuple[str, ...] = ()) -> int:
    """Remove orphaned *.parquet.tmp files from .staging_trades.
    Called at scanner startup to recover from interrupted writes.

    With year_filters, only clean tmp files in months matching those years
    (so a parallel sibling scanner's mid-write tmp files are preserved).
    """
    if not STAGING_TRADES.exists():
        return 0
    n = 0
    for f in STAGING_TRADES.rglob("*.parquet.tmp"):
        if year_filters:
            month_dir = f.parent.name  # e.g. "2024-01"
            year = month_dir[:4]
            if year not in year_filters:
                continue
        try:
            f.unlink()
            logger.warning(f"  cleaned up orphaned tmp file: {f}")
            n += 1
        except Exception:
            pass
    return n


# =============================================================================
# Provenance sidecar
# =============================================================================

def update_provenance(tickers_written: dict[str, pd.DataFrame], freq: str = "1m") -> None:
    """Upsert rows in data/ref/bar_provenance.parquet for each written ticker.

    Uses fcntl.LOCK_EX on a sibling .lock file to serialize concurrent updates
    from parallel scanner instances (read-modify-write would otherwise race
    and lose rows from whichever process committed first).
    """
    if not tickers_written:
        return
    PROVENANCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    now = pd.Timestamp.now(tz="UTC").tz_localize(None)
    rows = []
    for sym, df in tickers_written.items():
        rows.append({
            "symbol": safe_symbol(sym),
            "freq": freq,
            "source_type": SOURCE_TYPE,
            "rule_version": RULE_VERSION,
            "first_bar_ts": df.index.min(),
            "last_bar_ts": df.index.max(),
            "n_bars_added": len(df),
            "updated_at": now,
        })
    new_rows = pd.DataFrame(rows)
    lock_path = PROVENANCE_FILE.with_suffix(".lock")
    with open(lock_path, "w") as lockf:
        fcntl.flock(lockf, fcntl.LOCK_EX)
        if PROVENANCE_FILE.exists():
            existing = pd.read_parquet(PROVENANCE_FILE)
            combined = pd.concat([existing, new_rows], ignore_index=True)
        else:
            combined = new_rows
        tmp = PROVENANCE_FILE.with_suffix(".parquet.tmp")
        combined.to_parquet(tmp, compression="snappy")
        tmp.replace(PROVENANCE_FILE)


# =============================================================================
# QA report
# =============================================================================

def write_qa_report(zip_path: Path, date_str: str, tickers: dict[str, pd.DataFrame],
                    stats: dict) -> Path:
    QA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = QA_DIR / f"{date_str}.json"
    per_ticker = {}
    for sym, df in tickers.items():
        # QA metrics per ticker for one day
        n_bars = len(df)
        vol = df["volume"].astype("float64")
        amt = df["amount"].astype("float64")
        price = df["close"].astype("float64")
        per_ticker[safe_symbol(sym)] = {
            "n_bars": int(n_bars),
            "first_bar": str(df.index.min()),
            "last_bar": str(df.index.max()),
            "zero_vol_bars": int((df["volume"] == 0).sum()),
            "vol_p50": int(vol.median()) if n_bars else 0,
            "vol_p99": int(vol.quantile(0.99)) if n_bars else 0,
            "vol_max": int(vol.max()) if n_bars else 0,
            "amount_sum_usd": float(amt.sum()),
            "block_n_total": int(df["block_n"].sum()),
            "large_trade_vol_total": int(df["large_trade_volume"].sum()),
            "price_p50": float(price.median()) if n_bars else 0,
            "price_nan_bars": int(df[["open","high","low","close"]].isna().any(axis=1).sum()),
            "has_0930_bar": bool(any(pd.Timestamp(f"{date_str} 09:30:00") == t for t in df.index)),
            "has_1600_bar": bool(any(pd.Timestamp(f"{date_str} 16:00:00") == t for t in df.index)),
            "ohlc_consistency_fail": int(
                ((df["high"] < df["low"]) |
                 (df["high"] < df["open"]) | (df["high"] < df["close"]) |
                 (df["low"] > df["open"]) | (df["low"] > df["close"])).sum()
            ),
        }
    doc = {
        "date": date_str,
        "zip_path": str(zip_path),
        "source_type": SOURCE_TYPE,
        "rule_version": RULE_VERSION,
        "stats": stats,
        "n_tickers_written": len(tickers),
        "per_ticker": per_ticker,
    }
    out_path.write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")
    return out_path


# =============================================================================
# Process one zip
# =============================================================================

def process_zip(zip_path: Path, existing_per_month: dict[str, set[str]],
                state: dict, state_file: Path, logger: logging.Logger,
                *, dry_run: bool = False, no_delete: bool = False,
                decrypt_tmp: Path = DEFAULT_DECRYPT_TMP) -> dict:
    date_str = _parse_date_from_zip(zip_path)
    y, m = date_str[:4], date_str[5:7]
    month_tag = f"{y}-{m}"
    skip_tickers = existing_per_month.get(month_tag, set())
    logger.info(f"  skip_tickers for {month_tag}: {len(skip_tickers)}")

    t0 = time.time()
    logger.info(f"START {zip_path.name} ({zip_path.stat().st_size/1e9:.2f}GB)")

    rec = {
        "date": date_str,
        "status": "in_progress",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "month_tag": month_tag,
    }
    state["processed"][str(zip_path)] = rec
    save_state(state, state_file)

    try:
        password = make_password(zip_path)
        tickers, stats = aggregate_zip(zip_path, password, skip_tickers,
                                       logger, decrypt_tmp=decrypt_tmp)

        t_w = time.time()
        n_bars_total = 0
        for sym, day_df in tickers.items():
            n_bars_total += write_ticker_day(sym, day_df, month_tag, dry_run=dry_run)
        write_dt = time.time() - t_w
        stats["write_seconds"] = round(write_dt, 2)
        stats["n_bars_total"] = int(n_bars_total)

        if not dry_run:
            update_provenance(tickers, freq="1m")
            write_qa_report(zip_path, date_str, tickers, stats)

        total_dt = time.time() - t0
        rec.update({
            "status": "done",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round(total_dt, 2),
            "n_tickers_written": len(tickers),
            "n_bars_total": n_bars_total,
            "stats": stats,
            "zip_size_bytes": zip_path.stat().st_size,
        })
        save_state(state, state_file)

        if not dry_run and not no_delete:
            try:
                zip_path.unlink()
                rec["zip_deleted"] = True
                logger.info(f"  deleted {zip_path}")
            except Exception as e:
                rec["zip_deleted"] = False
                rec["delete_error"] = str(e)
                logger.warning(f"  failed to delete {zip_path}: {e}")
            save_state(state, state_file)

        logger.info(f"DONE  {zip_path.name} — {len(tickers)} tickers, "
                    f"{n_bars_total:,} bars, {total_dt:.1f}s")
        return rec

    except Exception as e:
        logger.exception(f"FAIL  {zip_path.name}: {e}")
        rec.update({
            "status": "failed",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "error": repr(e),
        })
        state.setdefault("failed", {})[str(zip_path)] = rec
        save_state(state, state_file)
        return rec


# =============================================================================
# Main loop
# =============================================================================

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trades-root", type=Path, default=TRADES_ROOT_DEFAULT)
    ap.add_argument("--once", action="store_true", default=True, help="default")
    ap.add_argument("--watch", action="store_true", help="poll every 60s")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-delete", action="store_true")
    ap.add_argument("--only-zip", type=Path, help="process a single zip and exit")
    ap.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE,
                    help="per-instance state JSON. Use distinct paths when "
                         "running multiple scanners in parallel.")
    ap.add_argument("--decrypt-tmp", type=Path, default=DEFAULT_DECRYPT_TMP,
                    help="per-instance temp CSV path for decrypt. Distinct "
                         "paths required for parallel scanners.")
    ap.add_argument("--year-include", type=str, default=None,
                    help="comma-separated 4-digit year prefixes to include "
                         "(e.g. '2024,2025'). Default: all years.")
    args = ap.parse_args()

    year_filters: tuple[str, ...] = tuple()
    if args.year_include:
        year_filters = tuple(y.strip() for y in args.year_include.split(",") if y.strip())

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    state_tag = args.state_file.stem.replace("trades_scanner_state", "scanner")
    log_file = LOGS_DIR / f"trades_scanner_{state_tag}_{ts}.log"
    logger = setup_logging(log_file)
    logger.info(f"trades_scanner start, log={log_file}")
    logger.info(f"trades_root={args.trades_root}, dry_run={args.dry_run}, "
                f"watch={args.watch}, no_delete={args.no_delete}")
    logger.info(f"state_file={args.state_file}, decrypt_tmp={args.decrypt_tmp}, "
                f"year_filters={year_filters or 'ALL'}")

    # Recover from any interrupted writes before scanning.
    # When running multiple scanners, only clean tmp files in months we own
    # (year_filters), so we don't trample another instance's mid-write tmp.
    n_cleaned = cleanup_stale_tmp_files(logger, year_filters=year_filters)
    if n_cleaned:
        logger.info(f"cleaned up {n_cleaned} orphaned .tmp files")

    # Strategy B snapshot — per-month map of existing tickers to skip
    existing_per_month = build_existing_tickers_per_month()
    n_months = len(existing_per_month)
    n_total = sum(len(s) for s in existing_per_month.values())
    logger.info(f"Strategy B: {n_months} months in staging, "
                f"{n_total:,} (month,ticker) pairs to skip")

    state = load_state(args.state_file)

    if args.only_zip:
        if not args.only_zip.exists():
            logger.error(f"--only-zip not found: {args.only_zip}")
            sys.exit(1)
        process_zip(args.only_zip, existing_per_month, state, args.state_file,
                    logger, dry_run=args.dry_run, no_delete=args.no_delete,
                    decrypt_tmp=args.decrypt_tmp)
        return

    while True:
        state["last_scan_at"] = datetime.now(timezone.utc).isoformat()
        zips = list_new_zips(args.trades_root, state, year_filters=year_filters)
        logger.info(f"scan: {len(zips)} new zips to process")
        for zp in zips:
            process_zip(zp, existing_per_month, state, args.state_file,
                        logger, dry_run=args.dry_run, no_delete=args.no_delete,
                        decrypt_tmp=args.decrypt_tmp)
        save_state(state, args.state_file)
        if not args.watch:
            break
        logger.info(f"sleep {POLL_INTERVAL_SECONDS}s before next scan")
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
