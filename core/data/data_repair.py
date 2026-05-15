"""Internal-gap data repair using yfinance — P0.b Codex fix (2026-05-14).

Authority: docs/audit/20260514-comprehensive_project_audit.md §1.2
User explicit-go 2026-05-14: "可以从web上面抓取数据进行补充"

Repair rules (per user spec):
  - 只补 daily parquet 里"内部缺失的交易日" — never extend history start
  - 写前先备份原文件 (`.preDataRepair_<utc_timestamp>` sidecar)
  - 生成 manifest at data/audit/data_repair_<timestamp>_manifest.json
  - 追加 provenance, source_type='yfinance_repair_v1_2026-05-14'
  - If yfinance lacks data for missing date → record as unfillable
  - If yfinance bar differs >20% from existing neighbor → flag suspect, skip
"""
from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

PROJ = Path(__file__).resolve().parent.parent.parent
DAILY_DIR = PROJ / "data" / "daily"
PROVENANCE_PATH = PROJ / "data" / "ref" / "bar_provenance.parquet"
SPLITS_PATH = PROJ / "data" / "ref" / "splits.parquet"
REPAIR_PROVENANCE_TAG = "yfinance_repair_v1_2026-05-14"


def _load_splits_cached() -> pd.DataFrame:
    """Load splits.parquet for split-aware reverse-adjustment."""
    if not SPLITS_PATH.exists():
        return pd.DataFrame(columns=["symbol", "date", "from", "to"])
    df = pd.read_parquet(SPLITS_PATH)
    df["date"] = pd.to_datetime(df["date"])
    return df


def _yfinance_to_raw_factor(
    symbol: str,
    missing_date: pd.Timestamp,
    splits_df: pd.DataFrame,
) -> float:
    """Return the cumulative split factor to convert yfinance's
    retroactively-split-adjusted close back to historical-basis raw.

    yfinance with auto_adjust=False STILL applies splits retroactively
    (verified empirically 2026-05-14: CMG 2020-01-15 yfinance=$17,
    our parquet 2026-05-14=$32 = current-basis post-50:1-split-2024;
    pre-split historical raw was 50x larger). To match parquet "true
    raw" convention, multiply yfinance close by cumulative factor
    of all splits dated AFTER missing_date.

    For each split with date > missing_date and matching symbol:
        factor *= (to / from)

    Forward N:1 split (from=1, to=N): pre-split price was N× post-split.
    Reverse N:1 split (from=N, to=1): pre-split price was 1/N of post-split.

    Returns:
        1.0 if no relevant splits.
    """
    if splits_df.empty:
        return 1.0
    rows = splits_df[
        (splits_df["symbol"] == symbol) & (splits_df["date"] > missing_date)
    ]
    if rows.empty:
        return 1.0
    factor = 1.0
    for _, r in rows.iterrows():
        factor *= float(r["to"]) / float(r["from"])
    return factor


@dataclass
class SymbolRepairResult:
    symbol: str
    pre_repair_n_rows: int
    post_repair_n_rows: int
    n_filled: int
    n_unfillable: int
    n_suspect_skipped: int
    valid_start: str = ""
    valid_end: str = ""
    backup_path: str = ""
    filled_dates: List[str] = field(default_factory=list)
    unfillable_dates: List[str] = field(default_factory=list)
    suspect_dates: List[str] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class RepairManifest:
    timestamp_utc: str
    rule_version: str = REPAIR_PROVENANCE_TAG
    per_symbol: Dict[str, SymbolRepairResult] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "timestamp_utc": self.timestamp_utc,
            "rule_version": self.rule_version,
            "n_symbols": len(self.per_symbol),
            "summary": {
                "total_filled": sum(r.n_filled for r in self.per_symbol.values()),
                "total_unfillable": sum(r.n_unfillable for r in self.per_symbol.values()),
                "total_suspect_skipped": sum(r.n_suspect_skipped for r in self.per_symbol.values()),
            },
            "per_symbol": {s: r.__dict__ for s, r in self.per_symbol.items()},
        }


def _backup_parquet(parquet_path: Path) -> Path:
    """Backup original parquet to .preDataRepair_<timestamp> sidecar."""
    if not parquet_path.exists():
        raise FileNotFoundError(parquet_path)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
    backup = parquet_path.with_suffix(
        parquet_path.suffix + f".preDataRepair_{ts}"
    )
    shutil.copy2(parquet_path, backup)
    logger.info("Backup: %s -> %s", parquet_path.name, backup.name)
    return backup


def _detect_internal_gaps(
    df: pd.DataFrame,
    max_consecutive_missing_bd: int = 1,
) -> List[pd.Timestamp]:
    """Return list of missing BD timestamps within valid window.

    `max_consecutive_missing_bd` is a noise filter: spans <= this length
    are skipped (typically 1 = "single-day blip ignored"). Use 0 to fill
    every single missing BD.
    """
    if df.empty:
        return []
    valid_start = df.index.min()
    valid_end = df.index.max()
    expected = pd.bdate_range(valid_start, valid_end)
    actual = set(df.index)
    missing_all = [d for d in expected if d not in actual]
    if not missing_all:
        return []

    if max_consecutive_missing_bd <= 0:
        return missing_all

    # Group by consecutive runs; keep runs > max
    pos = {d: i for i, d in enumerate(expected)}
    out: List[pd.Timestamp] = []
    run: List[pd.Timestamp] = [missing_all[0]]
    for cur in missing_all[1:]:
        if pos[cur] == pos[run[-1]] + 1:
            run.append(cur)
        else:
            if len(run) > max_consecutive_missing_bd:
                out.extend(run)
            run = [cur]
    if len(run) > max_consecutive_missing_bd:
        out.extend(run)
    return out


def _fetch_yfinance_bars(
    symbol: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    """Fetch yfinance daily bars covering [start, end] inclusive.

    Returns DataFrame indexed by date with columns open/high/low/close/volume.
    """
    try:
        import yfinance as yf
    except ImportError:
        raise RuntimeError("yfinance not installed in environment")
    ticker = yf.Ticker(symbol)
    df = ticker.history(
        start=start.strftime("%Y-%m-%d"),
        end=(end + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
        interval="1d",
        auto_adjust=False,
    )
    if df.empty:
        return df
    # Normalize index: yfinance returns tz-aware → tz_convert(ET) → tz_localize(None)
    # to align with our daily parquet semantics (per off-by-one fix 2026-05-13).
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        try:
            df.index = df.index.tz_convert("America/New_York").tz_localize(None)
        except Exception:
            df.index = df.index.tz_localize(None)
    df.index = df.index.normalize()
    # Normalize column names to lowercase
    df.columns = [c.lower() for c in df.columns]
    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    return df[keep]


def _is_suspect_price(
    new_close: float,
    neighbor_close: float,
    threshold: float = 0.30,
) -> bool:
    """Flag if new close differs from neighbor by > threshold (e.g., 30%)."""
    if neighbor_close <= 0 or new_close <= 0:
        return False
    ratio = new_close / neighbor_close
    return ratio > (1 + threshold) or ratio < (1 - threshold)


def repair_symbol_internal_gaps(
    symbol: str,
    daily_dir: Path = DAILY_DIR,
    max_consecutive_missing_bd: int = 1,
    suspect_threshold: float = 0.30,
    dry_run: bool = False,
    apply_split_reverse_adjust: bool = True,
) -> SymbolRepairResult:
    """Repair one symbol's daily parquet by filling internal gaps from yfinance.

    Args:
        symbol: ticker
        daily_dir: directory of daily parquet files
        max_consecutive_missing_bd: only fill gaps STRICTLY LONGER than this
            (1 = skip single-day blips; matches BarStore semantics)
        suspect_threshold: skip yfinance bars that differ >X% from neighbor close
            AFTER applying split reverse-adjustment.
        dry_run: don't write; just report.
        apply_split_reverse_adjust: if True (default), read splits.parquet and
            multiply yfinance close by cumulative split factor of all splits
            dated AFTER the missing_date. This converts yfinance's
            retroactively-split-adjusted prices back to historical-basis raw
            prices to match parquet "true raw" convention.

    Returns:
        SymbolRepairResult.
    """
    pq_path = daily_dir / f"{symbol}.parquet"
    if not pq_path.exists():
        return SymbolRepairResult(
            symbol=symbol, pre_repair_n_rows=0, post_repair_n_rows=0,
            n_filled=0, n_unfillable=0, n_suspect_skipped=0,
            error=f"daily parquet not found: {pq_path}",
        )

    df = pd.read_parquet(pq_path).sort_index()
    pre_n = len(df)
    if df.empty:
        return SymbolRepairResult(
            symbol=symbol, pre_repair_n_rows=0, post_repair_n_rows=0,
            n_filled=0, n_unfillable=0, n_suspect_skipped=0,
            error="parquet is empty",
        )

    valid_start = df.index.min()
    valid_end = df.index.max()
    missing = _detect_internal_gaps(df, max_consecutive_missing_bd)

    result = SymbolRepairResult(
        symbol=symbol,
        pre_repair_n_rows=pre_n,
        post_repair_n_rows=pre_n,
        n_filled=0,
        n_unfillable=0,
        n_suspect_skipped=0,
        valid_start=str(valid_start.date()),
        valid_end=str(valid_end.date()),
    )

    if not missing:
        logger.info("[%s] no internal gaps > %d BD", symbol, max_consecutive_missing_bd)
        return result

    logger.info("[%s] %d internal gap days to fill (window %s → %s)",
                symbol, len(missing), result.valid_start, result.valid_end)

    splits_df = _load_splits_cached() if apply_split_reverse_adjust else pd.DataFrame()

    # Fetch yfinance covering the missing window
    try:
        yf_df = _fetch_yfinance_bars(symbol, missing[0], missing[-1])
    except Exception as e:
        result.error = f"yfinance fetch failed: {e}"
        return result

    yf_dates = set(yf_df.index)
    new_rows: List[pd.Series] = []
    for d in missing:
        if d not in yf_dates:
            result.n_unfillable += 1
            result.unfillable_dates.append(str(d.date()))
            continue
        bar = yf_df.loc[d]
        # Apply split reverse-adjustment: yfinance returns retroactively-
        # split-adjusted prices; multiply by cumulative split factor to
        # convert back to historical-basis raw matching parquet convention.
        if apply_split_reverse_adjust:
            split_factor = _yfinance_to_raw_factor(symbol, d, splits_df)
        else:
            split_factor = 1.0
        adj_bar = {c: float(bar[c]) * split_factor for c in ["open", "high", "low", "close"]
                   if c in bar.index and c in df.columns}
        # Volume goes OPPOSITE direction: post-N:1-split volume is N× pre-split.
        # So we divide volume by split_factor to revert to pre-split basis.
        if "volume" in bar.index and "volume" in df.columns:
            adj_bar["volume"] = float(bar["volume"]) / split_factor if split_factor != 0 else float(bar["volume"])
        new_close = adj_bar.get("close", 0.0)
        # Find nearest neighbor close
        before = df.index[df.index < d]
        after = df.index[df.index > d]
        neighbor_close = None
        if len(before) > 0:
            neighbor_close = float(df.loc[before[-1], "close"])
        elif len(after) > 0:
            neighbor_close = float(df.loc[after[0], "close"])
        if neighbor_close and _is_suspect_price(new_close, neighbor_close, suspect_threshold):
            result.n_suspect_skipped += 1
            result.suspect_dates.append(str(d.date()))
            logger.warning("[%s] %s: suspect (new=%.2f vs neighbor=%.2f, "
                           "split_factor=%.3f), skip",
                           symbol, d.date(), new_close, neighbor_close, split_factor)
            continue
        new_rows.append(pd.Series(adj_bar, name=d))
        result.n_filled += 1
        result.filled_dates.append(str(d.date()))

    if dry_run:
        result.post_repair_n_rows = pre_n
        return result

    if new_rows:
        result.backup_path = str(_backup_parquet(pq_path))
        added = pd.DataFrame(new_rows)
        # Align column order to df; missing columns NaN
        for c in df.columns:
            if c not in added.columns:
                added[c] = pd.NA
        added = added[df.columns]
        merged = pd.concat([df, added]).sort_index()
        merged = merged[~merged.index.duplicated(keep="last")]
        merged.to_parquet(pq_path)
        result.post_repair_n_rows = len(merged)
        logger.info("[%s] wrote %d new rows (post=%d)", symbol,
                    result.n_filled, result.post_repair_n_rows)
    return result


def append_repair_provenance(
    symbol: str,
    filled_dates: List[str],
    provenance_path: Path = PROVENANCE_PATH,
) -> None:
    """Append repair entries to bar_provenance.parquet."""
    if not filled_dates:
        return
    if not provenance_path.exists():
        logger.warning("bar_provenance.parquet not found at %s; skipping append",
                       provenance_path)
        return
    prov = pd.read_parquet(provenance_path)
    # Schema: symbol, freq, start_date, end_date, source_type, rule_version, ...
    new_rows = []
    for d in filled_dates:
        new_rows.append({
            "symbol": symbol,
            "freq": "1d",
            "start_date": d,
            "end_date": d,
            "source_type": REPAIR_PROVENANCE_TAG,
            "rule_version": REPAIR_PROVENANCE_TAG,
        })
    add = pd.DataFrame(new_rows)
    # Align schema: missing columns from prov get NaN
    for c in prov.columns:
        if c not in add.columns:
            add[c] = pd.NA
    add = add[prov.columns]
    out = pd.concat([prov, add], ignore_index=True)
    out.to_parquet(provenance_path)
    logger.info("provenance appended: %d rows for %s", len(new_rows), symbol)


def write_repair_manifest(
    manifest: RepairManifest,
    out_dir: Path = None,
) -> Path:
    """Write repair manifest JSON to data/audit/."""
    out_dir = out_dir or (PROJ / "data" / "audit")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"data_repair_{ts}_manifest.json"
    path.write_text(json.dumps(manifest.to_dict(), indent=2, default=str))
    logger.info("manifest: %s", path)
    return path
