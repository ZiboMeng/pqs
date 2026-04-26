"""Forward data readiness / freshness guard (R-fwd-1.5 P1).

Answers a small set of operational questions BEFORE running observe:

  - what's the latest trading day available in the daily store?
  - has it caught up past the candidate's start_date?
  - can ``observe`` append at least one new TD entry right now?
  - what's the source layer of the data window we'd observe over —
    canonical / frontier / mixed?
  - which held-symbol-eligible names have ETF/source lag holding back
    forward append?

This is a thin wrapper on top of the daily store + boundary sidecar +
manifest. It does not invoke ``observe`` or BacktestEngine; it's
read-only and cheap.

PRD: docs/prd/20260426-forward_oos_runner_prd.md (post-R-fwd-1
audit, user direction "P1: forward data readiness / freshness
guard").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

from core.data.source_boundaries import (
    DEFAULT_BOUNDARIES_PATH,
    DEFAULT_DAILY_DIR,
    get_boundary,
    load_boundaries,
)

from .manifest_io import load_manifest, manifest_path
from .manifest_schema import ForwardRunManifest  # schema-bypass guard contract


_BENCHMARKS = ("SPY", "QQQ")


@dataclass
class ReadinessReport:
    candidate_id: str
    start_date: date
    n_existing_runs: int
    last_observed_date: Optional[date]
    latest_data_date: Optional[date]
    next_expected_td: Optional[date]
    can_append_now: bool
    n_potential_new_tds: int
    source_layer_status: str  # 'canonical_only' / 'frontier_only' /
                              # 'mixed' / 'unknown'
    benchmark_lag: dict = field(default_factory=dict)  # {sym: last_date}
    universe_lag_summary: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "start_date": self.start_date.isoformat(),
            "n_existing_runs": self.n_existing_runs,
            "last_observed_date": (
                self.last_observed_date.isoformat()
                if self.last_observed_date else None
            ),
            "latest_data_date": (
                self.latest_data_date.isoformat()
                if self.latest_data_date else None
            ),
            "next_expected_td": (
                self.next_expected_td.isoformat()
                if self.next_expected_td else None
            ),
            "can_append_now": self.can_append_now,
            "n_potential_new_tds": self.n_potential_new_tds,
            "source_layer_status": self.source_layer_status,
            "benchmark_lag": {
                k: (v.isoformat() if v else None)
                for k, v in self.benchmark_lag.items()
            },
            "universe_lag_summary": self.universe_lag_summary,
            "notes": list(self.notes),
        }


def _last_trading_date(parquet: Path) -> Optional[date]:
    if not parquet.exists():
        return None
    try:
        df = pd.read_parquet(parquet)
    except Exception:
        return None
    if df.empty or not isinstance(df.index, pd.DatetimeIndex):
        return None
    return df.index.max().date()


def _benchmark_lags(daily_dir: Path) -> dict:
    out: dict = {}
    for sym in _BENCHMARKS:
        out[sym] = _last_trading_date(daily_dir / f"{sym}.parquet")
    return out


def _classify_source_layer(
    held_symbols: list,
    start_date: date,
    end_date: Optional[date],
    boundaries: pd.DataFrame,
) -> str:
    """Return one of canonical_only / frontier_only / mixed / unknown."""
    if not held_symbols or end_date is None:
        return "unknown"
    has_canonical = False
    has_frontier = False
    for sym in held_symbols:
        if sym not in boundaries.index:
            continue
        canonical_end = boundaries.loc[sym, "canonical_end_date"]
        frontier_start = boundaries.loc[sym, "frontier_start_date"]
        ce = pd.Timestamp(canonical_end).date() if pd.notna(canonical_end) else None
        fs = pd.Timestamp(frontier_start).date() if pd.notna(frontier_start) else None
        # Window [start_date, end_date] vs canonical_end / frontier_start
        if ce is not None and start_date <= ce:
            has_canonical = True
        if fs is not None and end_date >= fs:
            has_frontier = True
    if has_canonical and has_frontier:
        return "mixed"
    if has_frontier:
        return "frontier_only"
    if has_canonical:
        return "canonical_only"
    return "unknown"


def check_readiness(
    candidate_id: str,
    *,
    output_dir: Path = Path("data/research_candidates"),
    daily_dir: Path = DEFAULT_DAILY_DIR,
    boundaries_path: Path = DEFAULT_BOUNDARIES_PATH,
    benchmark_max_lag_days: int = 3,
) -> ReadinessReport:
    """Compute a readiness report for a candidate's forward run.

    Read-only: does NOT mutate the manifest, does NOT invoke observe().
    The manifest is loaded via ``load_manifest`` which round-trips
    through ``ForwardRunManifest.model_validate``, preserving the
    schema-bypass guard contract.
    """
    manifest: ForwardRunManifest = load_manifest(
        manifest_path(candidate_id, output_dir)
    )
    runs = manifest.runs
    last_observed = (
        max((r.as_of_date for r in runs if r.checkpoint_label.startswith("TD")), default=None)
    )

    # Latest available data date — use SPY as the calendar proxy.
    spy_path = Path(daily_dir) / "SPY.parquet"
    latest = _last_trading_date(spy_path)

    # Benchmark lag check.
    bench_lag = _benchmark_lags(Path(daily_dir))

    # Compute potential new TDs that observe() would append.
    n_potential = 0
    next_expected: Optional[date] = None
    if latest is not None:
        spy = pd.read_parquet(spy_path)
        idx = spy.index
        ts_start = pd.Timestamp(manifest.start_date)
        ts_last = pd.Timestamp(last_observed) if last_observed else None
        candidate_dates = idx[idx >= ts_start]
        if ts_last is not None:
            candidate_dates = candidate_dates[candidate_dates > ts_last]
        n_potential = int(len(candidate_dates))
        if n_potential > 0:
            next_expected = candidate_dates[0].date()

    can_append = n_potential > 0

    # Source layer classification — use universe symbols held by this
    # candidate's frozen spec as a proxy for "potentially-held" syms.
    boundaries = load_boundaries(boundaries_path)
    spec_path = Path(output_dir) / f"{candidate_id}.yaml"
    held_proxy = []
    if spec_path.exists():
        try:
            from core.research.frozen_spec import FrozenStrategySpec
            spec = FrozenStrategySpec.from_yaml_file(spec_path)
            # Use the candidate's full panel universe as an upper bound
            # — top-N selection is content-dependent so we don't try to
            # be precise here.
            import yaml as _yaml
            uni_cfg = _yaml.safe_load(open("config/universe.yaml"))
            uni = list(set(
                uni_cfg["seed_pool"] + uni_cfg["sector_etfs"]
                + uni_cfg["factor_etfs"] + uni_cfg["cross_asset"]
            ))
            uni = [s for s in uni if s not in uni_cfg.get("blacklist", [])
                   and s not in uni_cfg.get("macro_reference", [])]
            held_proxy = uni
            _ = spec  # suppress unused var
        except Exception:
            pass
    source_layer = _classify_source_layer(
        held_proxy, manifest.start_date, latest, boundaries,
    )

    # Universe-level lag summary: how many syms ended >=2 trading days
    # behind SPY?
    universe_lag: dict = {"latest_spy": latest, "lagging_symbols": []}
    if latest is not None:
        for sym in held_proxy:
            p = Path(daily_dir) / f"{sym.replace('-', '_')}.parquet"
            sym_last = _last_trading_date(p)
            if sym_last is None:
                continue
            lag = (
                pd.Timestamp(latest) - pd.Timestamp(sym_last)
            ).days
            if lag > benchmark_max_lag_days:
                universe_lag["lagging_symbols"].append(
                    {"symbol": sym, "last_date": sym_last.isoformat(), "lag_days": lag}
                )

    notes: list = []
    if not can_append:
        if latest is None:
            notes.append("no SPY parquet found — daily store may be uninitialized")
        elif latest < manifest.start_date:
            notes.append(
                f"daily data ends {latest}, candidate forward window starts "
                f"{manifest.start_date} — wait for ingest to catch up"
            )
        else:
            notes.append("no new bars since last observed TD; observe() is a no-op")
    if source_layer == "frontier_only":
        notes.append(
            "all candidate-eligible symbols are post-canonical (yfinance "
            "frontier). Forward NAV uses different adjustment semantics than "
            "the candidate's construction-layer (polygon canonical, splits at "
            "read, no dividend baked-in). Forward TDs will be marked source_mix=True."
        )
    elif source_layer == "mixed":
        notes.append(
            "observation window crosses the polygon→yfinance source boundary "
            "for at least one held-eligible symbol; forward TDs spanning the "
            "boundary will be marked source_mix=True."
        )

    return ReadinessReport(
        candidate_id=candidate_id,
        start_date=manifest.start_date,
        n_existing_runs=len([
            r for r in runs if r.checkpoint_label.startswith("TD")
        ]),
        last_observed_date=last_observed,
        latest_data_date=latest,
        next_expected_td=next_expected,
        can_append_now=can_append,
        n_potential_new_tds=n_potential,
        source_layer_status=source_layer,
        benchmark_lag=bench_lag,
        universe_lag_summary=universe_lag,
        notes=notes,
    )
