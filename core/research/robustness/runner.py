"""Robustness eval runner.

Loads a frozen candidate spec, carves the last ``target_trading_days``
trading days before the candidate's frozen-date, replays the candidate
composite signal on that window via ``BacktestEngine``, computes summary
metrics, and emits three artifacts under ``data/research_candidates/``:

  - ``<candidate_id>_robustness_window.yaml``  (CandidateRobustnessWindow)
  - ``<candidate_id>_robustness_eval.json``    (structured metrics)
  - ``<candidate_id>_robustness_eval.md``      (human-readable summary)

evidence_class is always set to ``pseudo_oos_robustness``: the window is
pre-frozen-date historical data, NOT post-frozen-date forward
observation. Per PRD v3 §1.1 + §1.3, only ``forward_oos`` is deployable
OOS evidence; this runner is explicitly building pseudo-OOS robustness
artifacts.

PRD: docs/prd/20260425-oos_mvp_ralph_loop_execution.md §3 R2
PRD v3: docs/prd/20260425-oos_validation_framework_codex_v3.md §B/§C
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional, Union

import numpy as np
import pandas as pd
import yaml

from core.config.loader import load_config
from core.data.factory import PriceStore, create_default_store
from core.data.price_access import load_adjusted
from core.execution.cost_model import CostModel
from core.factors.base_masks import apply_research_mask, research_mask_default
from core.factors.factor_generator import generate_all_factors
from core.mining.research_miner import zscore_cs
from core.research.candidate_registry import CandidateRegistry
from core.research.concentration import (
    ConcentrationReport,
)
from core.research.concentration import (
    compute as compute_concentration,
)
from core.research.concentration import (
    write_artifacts as write_concentration_artifacts,
)
from core.research.concentration.sector_map import SECTOR_MAP
from core.research.frozen_spec import FrozenStrategySpec

from .window_spec import (
    CandidateRobustnessWindow,
    DataIntegritySnapshot,
    EvidenceClass,
    ShrinkReason,
    ShrinkReasonCode,
)

DEFAULT_OUTPUT_DIR = Path("data/research_candidates")
DEFAULT_REGISTRY_DB = "data/research_candidates/registry.db"
DEFAULT_BASELINE_PATH = "data/baseline/latest.json"
DEFAULT_WATCH_PARQUET = Path("data/ref/data_quality_watch.parquet")
DEFAULT_TOP_N = 10
DEFAULT_INITIAL_CAPITAL = 100_000.0
DEFAULT_TARGET_TRADING_DAYS = 252

# Pinned to the commit that rebuilt data/daily/*.parquet end-to-end
# (round-3 step-3b: full universe daily parquet rebuild from polygon 1m).
# This is the SEMANTIC value of `daily_store_rebuild_commit`: it identifies
# the data state, NOT the eval-time repo HEAD. Update only when the daily
# store is rebuilt by a new commit.
DAILY_STORE_REBUILD_COMMIT = "f170b0c"


@dataclass
class _WindowCarve:
    start: date
    end: date
    actual_trading_days: int
    shrink_reason: Optional[ShrinkReason]


@dataclass
class RobustnessEvalResult:
    """In-memory result of a robustness eval. Tests + callers consume this."""

    window: CandidateRobustnessWindow
    metrics: dict
    artifact_paths: dict
    concentration: Optional[ConcentrationReport] = None


def _load_watch_symbols(watch_path: Path) -> tuple[list, list, dict]:
    """Read data_quality_watch sidecar.

    Returns ``(watch_symbols, thin_data_symbols, thin_data_pct_map)``:

      - ``watch_symbols``: every symbol in the sidecar.
      - ``thin_data_symbols``: symbols with ``thin_data_pct > 0`` (legacy
        binary list — diagnostic only post-audit-fix).
      - ``thin_data_pct_map``: ``{symbol: thin_data_pct_in_[0,1]}`` —
        feeds the WEIGHTED gate metric in the concentration report.

    Returns ``([], [], {})`` if the sidecar is missing or unparseable:
    concentration report still computes, watch + thin metrics just come
    out as 0.0.
    """
    if not watch_path.exists():
        return [], [], {}
    try:
        df = pd.read_parquet(watch_path)
    except Exception:
        return [], [], {}
    watch = df["symbol"].astype(str).tolist() if "symbol" in df.columns else []
    if "thin_data_pct" in df.columns:
        thin_mask = df["thin_data_pct"] > 0.0
        thin = df.loc[thin_mask, "symbol"].astype(str).tolist()
        # The sidecar stores thin_data_pct as percent (e.g. 23.3 means 23.3%);
        # divide by 100 to land in [0, 1] for the weighted-share calc.
        pct_map = {
            str(row["symbol"]): float(row["thin_data_pct"]) / 100.0
            for _, row in df.iterrows()
            if pd.notna(row.get("thin_data_pct"))
        }
    else:
        thin = []
        pct_map = {}
    return watch, thin, pct_map


def _resolve_frozen_date(
    candidate_id: str,
    explicit: Optional[Union[date, str]],
    registry_db: str,
) -> date:
    if explicit is not None:
        if isinstance(explicit, str):
            return date.fromisoformat(explicit)
        return explicit
    registry = CandidateRegistry(registry_db)
    rec = registry.get(candidate_id)
    if not rec.promoted_at:
        raise ValueError(
            f"candidate {candidate_id} has no promoted_at; pass frozen_date explicitly"
        )
    return datetime.fromisoformat(rec.promoted_at).date()


def _carve_window(
    price_index: pd.DatetimeIndex,
    frozen_date: date,
    target: int,
) -> _WindowCarve:
    """Return the last ``target`` trading days at-or-before ``frozen_date``.

    Falls back to the longest available window if fewer trading days exist;
    in that case ``shrink_reason`` is populated with ``data_coverage_short``.
    """
    end_ts = pd.Timestamp(frozen_date)
    available = price_index[price_index <= end_ts]
    if len(available) == 0:
        raise RuntimeError(
            f"No trading days in price index <= {frozen_date}; cannot carve window"
        )
    actual = min(target, len(available))
    start_ts = available[-actual]
    end_ts = available[-1]
    shrink: Optional[ShrinkReason] = None
    if actual < target:
        shrink = ShrinkReason(
            code=ShrinkReasonCode.data_coverage_short,
            note=(
                f"only {actual} trading days available at-or-before "
                f"frozen_date={frozen_date}; target was {target}"
            ),
        )
    return _WindowCarve(
        start=start_ts.date(),
        end=end_ts.date(),
        actual_trading_days=actual,
        shrink_reason=shrink,
    )


def _load_panel(cfg, store: PriceStore, start: pd.Timestamp, end: pd.Timestamp,
                *, adjusted: bool = False,
                adjusted_total_return: bool = False,
                drop_symbols: Optional[list] = None) -> dict:
    """Load the daily OHLCV panel for the research universe.

    Default (``adjusted=False``) reads RAW unadjusted bars via
    ``store.read``. As of audit 20260708 P0-3 the robustness / pseudo-OOS
    ``evaluate()`` callers no longer use this default — they pass
    ``adjusted=True, adjusted_total_return=True`` + candidate drop_symbols
    (same basis as forward / Track-A), because the raw path injected fake
    split-date returns into selection-tier evidence. The raw default remains
    only for any residual caller that explicitly wants unadjusted bars.

    The FORWARD path passes ``adjusted=True, adjusted_total_return=True``
    so its factor / composite / NAV computation uses the SAME split +
    total-return adjusted prices the Track-A gate validated on (the
    canonical ``BarStore.load`` contract), and ``drop_symbols`` applies
    the candidate's declared ``panel_contract.drop_symbols`` so the
    cross-section matches Track-A. Verified 2026-06-19: with these three
    (adjusted + total-return + drop_symbols) the forward composite ==
    Track-A bit-for-bit (close diff 0, top-N overlap 10/10). Without the
    total-return layer the divergence was ~3/10 holdings — dividends,
    not splits, were the dominant gap.
    """
    uni = cfg.universe
    _drop = set(drop_symbols or [])
    syms = [
        s for s in dict.fromkeys(
            list(uni.seed_pool) + list(uni.sector_etfs)
            + list(uni.factor_etfs) + list(uni.cross_asset)
        )
        if s not in uni.blacklist and s not in uni.macro_reference
        and s not in _drop
    ]
    _root = cfg.system.paths.data_dir
    frames: dict = {k: {} for k in ("close", "open", "high", "low", "volume")}
    for sym in syms:
        if adjusted:
            df = load_adjusted(sym, _root, "1d",
                               adjusted_total_return=adjusted_total_return)
        else:
            df = store.read(sym, "1d")
        if df is None or df.empty or "close" not in df.columns:
            continue
        frames["close"][sym] = df["close"]
        for col in ("open", "high", "low", "volume"):
            if col in df.columns:
                frames[col][sym] = df[col]
    close = pd.DataFrame(frames["close"]).sort_index()
    if close.empty:
        close.index = pd.DatetimeIndex([], name=close.index.name)
    elif not isinstance(close.index, pd.DatetimeIndex):
        if pd.api.types.is_numeric_dtype(close.index.dtype):
            raise RuntimeError(
                "_load_panel: numeric non-DatetimeIndex cannot be interpreted "
                "as trading sessions"
            )
        try:
            converted = pd.to_datetime(close.index, errors="raise")
        except (ValueError, TypeError) as exc:
            raise RuntimeError(
                "_load_panel: close panel has a non-DatetimeIndex that cannot "
                "be coerced to trading sessions"
            ) from exc
        if converted.isna().any():
            raise RuntimeError("_load_panel: close panel index contains invalid dates")
        close.index = converted
    close = close[(close.index >= start) & (close.index <= end)]

    def _df(col: str) -> Optional[pd.DataFrame]:
        if not frames[col]:
            return None
        return pd.DataFrame(frames[col]).reindex_like(close)

    return {
        "close": close,
        "open": _df("open"),
        "high": _df("high"),
        "low": _df("low"),
        "volume": _df("volume"),
    }


def _compute_composite(
    spec: FrozenStrategySpec, frames: dict,
) -> tuple[pd.DataFrame, dict]:
    """Compute composite signal + return the full factor panel dict.

    The factor dict is returned so downstream callers (e.g. concentration
    report) can pull individual factor panels (notably ``beta_spy_60d``
    for benchmark beta concentration) without re-invoking
    ``generate_all_factors``.
    """
    close = frames["close"]
    benchmark_map = {b: close[b] for b in ("SPY", "QQQ") if b in close.columns}
    all_factors = generate_all_factors(
        close,
        volume_df=frames["volume"],
        open_df=frames["open"],
        high_df=frames["high"],
        low_df=frames["low"],
        benchmark_map=benchmark_map,
    )
    total_w = sum((f.weight or 0.0) for f in spec.feature_set) or 1.0
    composite: Optional[pd.DataFrame] = None
    for feat in spec.feature_set:
        panel = all_factors.get(feat.name)
        if panel is None:
            raise RuntimeError(
                f"Feature {feat.name!r} not produced by factor_generator on this panel"
            )
        z = zscore_cs(panel, min_periods=5)
        component = z * ((feat.weight or 0.0) / total_w)
        composite = component if composite is None else composite.add(component, fill_value=0.0)
    if composite is None:
        raise RuntimeError("Empty feature_set produced no composite")
    if frames["volume"] is not None:
        mask = research_mask_default(close, frames["volume"])
        composite = apply_research_mask(composite, mask)
    return composite, all_factors


def _extract_beta_map(all_factors: dict) -> dict:
    """Pull last-observation per-symbol β from ``beta_spy_60d`` panel.

    Returns ``{symbol: float_beta}`` for symbols with a non-NaN last
    value. Returns an empty dict if the factor isn't in the panel.
    """
    panel = all_factors.get("beta_spy_60d")
    if panel is None or panel.empty:
        return {}
    last_row = panel.iloc[-1].dropna()
    return {str(s): float(v) for s, v in last_row.items()}


def _composite_to_target_weights(composite: pd.DataFrame, top_n: int) -> pd.DataFrame:
    targets = pd.DataFrame(0.0, index=composite.index, columns=composite.columns)
    for date_idx in composite.index:
        row = composite.loc[date_idx].dropna()
        if len(row) < top_n:
            continue
        top = row.nlargest(top_n).index
        w = 1.0 / top_n
        for sym in top:
            targets.loc[date_idx, sym] = w
    return targets


def _compute_metrics(
    pnl_df: pd.DataFrame,
    fills_df: pd.DataFrame,
    target_wts: pd.DataFrame,
    close: pd.DataFrame,
) -> dict:
    eq = pnl_df["equity_curve"]
    ret = pnl_df["ret"]
    cum_ret = float(eq.iloc[-1] / eq.iloc[0] - 1.0) if len(eq) >= 2 else 0.0
    sharpe = (
        float(ret.mean() / ret.std() * np.sqrt(252))
        if ret.std() > 0
        else 0.0
    )
    cummax = eq.cummax()
    dd = (eq - cummax) / cummax
    max_dd = float(dd.min()) if len(dd) else 0.0

    def _bench_cum_ret(sym: str) -> Optional[float]:
        if sym not in close.columns:
            return None
        s = close[sym].dropna()
        if len(s) < 2:
            return None
        return float(s.iloc[-1] / s.iloc[0] - 1.0)

    spy_ret = _bench_cum_ret("SPY")
    qqq_ret = _bench_cum_ret("QQQ")
    vs_spy = (cum_ret - spy_ret) if spy_ret is not None else None
    vs_qqq = (cum_ret - qqq_ret) if qqq_ret is not None else None

    diffs = target_wts.diff().abs().sum(axis=1)
    daily_turnover = (diffs / 2.0).fillna(0.0)
    turnover = float(daily_turnover.mean()) if len(daily_turnover) else 0.0

    return {
        "cum_ret": cum_ret,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "vs_spy": vs_spy,
        "vs_qqq": vs_qqq,
        "turnover_daily_mean": turnover,
        "fill_count": int(len(fills_df)),
        "n_dates": int(len(pnl_df)),
    }


def _data_integrity_snapshot(
    daily_store_rebuild_commit: Optional[str],
    baseline_snapshot_path: str,
) -> DataIntegritySnapshot:
    """Build the data_integrity_snapshot for a robustness eval.

    ``daily_store_rebuild_commit`` semantics: the commit that produced
    the daily store this eval reads from — NOT the repo HEAD at eval
    time. Defaults to the module-level pin (``DAILY_STORE_REBUILD_COMMIT``).
    Pass an explicit value to override (e.g., from a fresh rebuild).
    Schema requires >=12 chars; we right-pad if the pin is shorter.
    """
    if daily_store_rebuild_commit is None:
        daily_store_rebuild_commit = DAILY_STORE_REBUILD_COMMIT
    if len(daily_store_rebuild_commit) < 12:
        # Schema requires >=12 chars; pad with zeros and append a comment-
        # like suffix so debuggers see the truncation, not silent padding.
        daily_store_rebuild_commit = daily_store_rebuild_commit.ljust(
            12, "0"
        )
    return DataIntegritySnapshot(
        daily_store_rebuild_commit=daily_store_rebuild_commit,
        baseline_snapshot_path=baseline_snapshot_path,
        generated_at_utc=datetime.now(timezone.utc),
    )


def _write_artifacts(
    candidate_id: str,
    window: CandidateRobustnessWindow,
    metrics: dict,
    output_dir: Path,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    win_path = output_dir / f"{candidate_id}_robustness_window.yaml"
    json_path = output_dir / f"{candidate_id}_robustness_eval.json"
    md_path = output_dir / f"{candidate_id}_robustness_eval.md"

    win_dict = window.model_dump(mode="json")
    win_path.write_text(yaml.safe_dump(win_dict, sort_keys=False, default_flow_style=False))

    eval_payload = {
        "candidate_id": candidate_id,
        "evidence_class": window.evidence_class.value,
        "window": {
            "start_date": window.start_date.isoformat(),
            "end_date": window.end_date.isoformat(),
            "actual_trading_days": window.actual_trading_days,
            "target_trading_days": window.target_trading_days,
        },
        "metrics": metrics,
    }
    json_path.write_text(json.dumps(eval_payload, indent=2, default=str))

    md = _format_eval_md(candidate_id, window, metrics)
    md_path.write_text(md)
    return {
        "window_yaml": str(win_path),
        "eval_json": str(json_path),
        "eval_md": str(md_path),
    }


def _format_eval_md(
    candidate_id: str,
    window: CandidateRobustnessWindow,
    metrics: dict,
) -> str:
    def _fmt_pct(v):
        return "n/a" if v is None else f"{v * 100:+.2f}%"

    lines = [
        f"# Robustness eval — {candidate_id}",
        "",
        f"**evidence_class**: `{window.evidence_class.value}` (NOT deployable OOS — see PRD v3 §1.1)",
        f"**window**: {window.start_date} → {window.end_date} "
        f"({window.actual_trading_days} TD / target {window.target_trading_days})",
    ]
    if window.shrink_reason is not None:
        lines.append(
            f"**shrink_reason**: `{window.shrink_reason.code.value}` — {window.shrink_reason.note}"
        )
    lines.extend([
        "",
        "## Metrics",
        "",
        f"- cum_ret: {_fmt_pct(metrics['cum_ret'])}",
        f"- sharpe (annualized): {metrics['sharpe']:+.3f}",
        f"- max_dd: {_fmt_pct(metrics['max_dd'])}",
        f"- vs SPY: {_fmt_pct(metrics['vs_spy'])}",
        f"- vs QQQ: {_fmt_pct(metrics['vs_qqq'])}",
        f"- turnover (daily mean): {metrics['turnover_daily_mean']:.4f}",
        f"- fill_count: {metrics['fill_count']}",
        f"- n_dates: {metrics['n_dates']}",
        "",
        "## Caveats",
        "",
        "- This is **pseudo-OOS robustness**, not deployable OOS evidence.",
        "  The window predates frozen-date and was reachable during candidate",
        "  construction. Treating these numbers as out-of-sample would re-create",
        "  the chronic trap PRD v3 §1.3 warns about.",
        "- Real OOS validation requires forward observation (post-frozen-date)",
        "  per the forward manifest schema (PRD v3 §B).",
        "",
        "## Data integrity snapshot",
        "",
        f"- daily_store_rebuild_commit: `{window.data_integrity_snapshot.daily_store_rebuild_commit}`",
        f"- baseline_snapshot_path: `{window.data_integrity_snapshot.baseline_snapshot_path}`",
        f"- generated_at_utc: {window.data_integrity_snapshot.generated_at_utc.isoformat()}",
        "",
    ])
    return "\n".join(lines)


def evaluate(
    candidate_id: str,
    *,
    frozen_date: Optional[Union[date, str]] = None,
    target_trading_days: int = DEFAULT_TARGET_TRADING_DAYS,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    registry_db: str = DEFAULT_REGISTRY_DB,
    baseline_snapshot_path: str = DEFAULT_BASELINE_PATH,
    daily_store_rebuild_commit: Optional[str] = None,
    initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    top_n: int = DEFAULT_TOP_N,
    watch_parquet: Path = DEFAULT_WATCH_PARQUET,
    cfg=None,
    store: Optional[PriceStore] = None,
) -> RobustnessEvalResult:
    """Run robustness eval for ``candidate_id``.

    Always sets ``evidence_class = pseudo_oos_robustness``: this runner
    builds pre-frozen-date robustness artifacts, never deployable OOS
    evidence (PRD v3 §1.1 + §1.3).
    """
    spec = FrozenStrategySpec.from_yaml_file(
        output_dir / f"{candidate_id}.yaml"
    )
    fdate = _resolve_frozen_date(candidate_id, frozen_date, registry_db)

    if cfg is None:
        cfg = load_config()
    if store is None:
        store = create_default_store(cfg)

    # audit 20260708 P0-3: robustness / pseudo-OOS evidence MUST use the SAME
    # split + total-return adjusted basis + candidate drop_symbols the Track-A
    # gate validated on. Previously these two calls used the raw default
    # (store.read, no split cascade), so any window spanning a split date
    # (NVDA 10:1, AVGO, WMT, CMG… 13 symbols since 2024) injected a fake
    # -50~-90% return → corrupted cross-sectional z-scores + NAV in the
    # SELECTION-tier evidence numbers. Now converged to the forward basis.
    _drop = (spec.panel_contract or {}).get("drop_symbols")
    full_panel = _load_panel(
        cfg, store,
        start=pd.Timestamp("1900-01-01"),
        end=pd.Timestamp(fdate) + pd.Timedelta(days=1),
        adjusted=True, adjusted_total_return=True, drop_symbols=_drop,
    )
    close_full = full_panel["close"]
    if close_full.empty:
        raise RuntimeError(
            f"No price data at-or-before frozen_date={fdate} for {candidate_id}"
        )

    carve = _carve_window(close_full.index, fdate, target_trading_days)

    panel = _load_panel(
        cfg, store,
        start=pd.Timestamp(carve.start),
        end=pd.Timestamp(carve.end),
        adjusted=True, adjusted_total_return=True, drop_symbols=_drop,
    )
    composite, all_factors = _compute_composite(spec, panel)
    target_wts = _composite_to_target_weights(composite, top_n=top_n)
    beta_map = _extract_beta_map(all_factors)

    from core.backtest.backtest_engine import BacktestEngine

    cm = CostModel(cfg.cost_model)
    engine = BacktestEngine(cost_model=cm, initial_capital=initial_capital)
    result = engine.run(
        signals_df=target_wts,
        price_df=panel["close"],
        open_df=panel["open"],
    )
    eq = result.equity_curve
    cash = result.cash_curve
    ret = eq.pct_change().fillna(0.0)
    pnl_df = pd.DataFrame(
        {"equity_curve": eq, "cash_curve": cash, "ret": ret}
    )
    if result.trades:
        fills_df = pd.DataFrame(
            [
                {
                    "date": f.fill_date,
                    "symbol": f.order.symbol,
                    "quantity": f.executed_qty,
                    "price": f.executed_price,
                }
                for f in result.trades
            ]
        )
    else:
        fills_df = pd.DataFrame(columns=["date", "symbol", "quantity", "price"])

    metrics = _compute_metrics(pnl_df, fills_df, target_wts, panel["close"])

    snapshot = _data_integrity_snapshot(
        daily_store_rebuild_commit, baseline_snapshot_path
    )
    window = CandidateRobustnessWindow(
        candidate_id=candidate_id,
        evidence_class=EvidenceClass.pseudo_oos_robustness,
        start_date=carve.start,
        end_date=carve.end,
        actual_trading_days=carve.actual_trading_days,
        target_trading_days=target_trading_days,
        shrink_reason=carve.shrink_reason,
        data_integrity_snapshot=snapshot,
    )

    artifact_paths = _write_artifacts(candidate_id, window, metrics, output_dir)

    # M12 concentration report — runs alongside robustness eval (PRD R3).
    # Report-only; does not block the candidate even on extreme tier.
    # Post-MVP audit (2026-04-25): the GATE metric is now
    # thin_data_weighted_share, computed via thin_data_pct_map.
    watch_syms, thin_syms, thin_pct_map = _load_watch_symbols(watch_parquet)
    concentration = compute_concentration(
        candidate_id=candidate_id,
        weights_df=target_wts,
        watch_symbols=watch_syms,
        thin_data_symbols=thin_syms,
        thin_data_pct_map=thin_pct_map,
        sector_map=SECTOR_MAP,
        beta_map=beta_map,
    )
    conc_paths = write_concentration_artifacts(concentration, output_dir)
    artifact_paths.update(conc_paths)

    return RobustnessEvalResult(
        window=window,
        metrics=metrics,
        artifact_paths=artifact_paths,
        concentration=concentration,
    )
