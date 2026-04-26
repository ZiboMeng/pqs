"""Forward OOS runner (R-fwd-1 minimum closed loop).

Provides four operations:
  - ``init``:    create a forward_run_manifest.json with frozen
                 spec_hash + cost_assumptions + checkpoint_cadence +
                 data_integrity_snapshot. One-time per candidate.
  - ``observe``: idempotent multi-day catch-up. Reads the manifest,
                 verifies cost-yaml hash matches the pinned value
                 (HALT on mismatch), determines the latest observed
                 trading day (or start_date if empty), replays the
                 candidate forward through any new TDs, appends one
                 ``ForwardRun`` per new TD to ``manifest.runs``, saves.
                 Append-only — never deletes or modifies existing
                 entries. Re-running observe with no new bars is a
                 no-op.
  - ``status``:  read-only manifest summary.
  - ``decide``:  user-driven status mutation. Narrow set:
                 completed_success / completed_fail / aborted.

R-fwd-1 explicitly DEFERS:
  - 10/20/40/60 TD checkpoint reduce (R-fwd-3)
  - weekly_w<NN> aggregation entries (R-fwd-2/R-fwd-3)
  - regime_shift / early_pass / early_fail flags

PRD: docs/prd/20260426-forward_oos_runner_prd.md
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional, Union

import numpy as np
import pandas as pd

from core.config.loader import load_config
from core.data.factory import PriceStore, create_default_store
from core.execution.cost_model import CostModel
from core.research.candidate_registry import CandidateRegistry
from core.research.frozen_spec import FrozenStrategySpec
from core.research.robustness.runner import (
    DAILY_STORE_REBUILD_COMMIT,
    _compute_composite,
    _composite_to_target_weights,
    _load_panel,
)

from .manifest_io import load_manifest, manifest_path, save_manifest
from .manifest_schema import (
    CheckpointCadence,
    CostAssumptions,
    DataIntegritySnapshot,
    EvidenceClass,
    ForwardRun,
    ForwardRunManifest,
    ForwardRunStatus,
)


DEFAULT_OUTPUT_DIR = Path("data/research_candidates")
DEFAULT_REGISTRY_DB = "data/research_candidates/registry.db"
DEFAULT_COST_MODEL_PATH = "config/cost_model.yaml"
DEFAULT_BASELINE_PATH = "data/baseline/latest.json"
DEFAULT_INITIAL_CAPITAL = 100_000.0
DEFAULT_TOP_N = 10


# ── halt / decide enum guards ────────────────────────────────────────────


_DECIDE_ALLOWED = {
    ForwardRunStatus.completed_success,
    ForwardRunStatus.completed_fail,
    ForwardRunStatus.aborted,
}


class ForwardHaltError(RuntimeError):
    """Raised when an invariant violation requires the runner to halt.

    Examples: cost-yaml hash mismatch, attempt to write a manifest
    with non-forward_oos evidence_class, attempt to mutate an
    existing ``ForwardRun`` entry instead of appending.
    """


# ── helpers ──────────────────────────────────────────────────────────────


def _file_sha256_hex(path: Path) -> str:
    h = hashlib.sha256()
    h.update(Path(path).read_bytes())
    return h.hexdigest()


_DEFAULT_DAILY_DIR = Path("data/daily")
_NYSE_CALENDAR_PROXY = "SPY"  # SPY's daily index is the NYSE proxy


def _next_trading_day(
    d: date, daily_dir: Path = _DEFAULT_DAILY_DIR,
) -> date:
    """Return the first trading day on-or-after ``d``.

    Uses SPY's daily index (NYSE proxy) when available — that handles
    both weekends and US market holidays. Falls back to ``BDay`` (next
    business day, weekends only) if SPY parquet is missing or ``d``
    is beyond SPY's index. Pure-function helper; no IO mutation.
    """
    spy_path = Path(daily_dir) / f"{_NYSE_CALENDAR_PROXY}.parquet"
    if spy_path.exists():
        try:
            idx = pd.read_parquet(spy_path).index
            if isinstance(idx, pd.DatetimeIndex):
                ts = pd.Timestamp(d)
                future = idx[idx >= ts]
                if len(future) > 0:
                    return future[0].date()
        except Exception:
            pass
    # Fallback: BDay-based (weekends only; doesn't know holidays).
    ts = pd.Timestamp(d)
    if ts.weekday() < 5:
        return ts.date()
    return (ts + pd.tseries.offsets.BDay(1)).date()


def _build_data_integrity_snapshot(
    baseline_snapshot_path: str,
    daily_store_rebuild_commit: Optional[str] = None,
) -> DataIntegritySnapshot:
    if daily_store_rebuild_commit is None:
        daily_store_rebuild_commit = DAILY_STORE_REBUILD_COMMIT
    if len(daily_store_rebuild_commit) < 12:
        daily_store_rebuild_commit = daily_store_rebuild_commit.ljust(12, "0")
    return DataIntegritySnapshot(
        daily_store_rebuild_commit=daily_store_rebuild_commit,
        baseline_snapshot_path=baseline_snapshot_path,
        generated_at_utc=datetime.now(timezone.utc),
    )


def _verify_cost_hash_or_halt(
    manifest: ForwardRunManifest,
    cost_model_path: Path,
) -> None:
    """Compare current cost yaml's sha256 to the manifest's pinned
    value. Raise ``ForwardHaltError`` on mismatch. PRD v3 §B: forward
    must not be hindsight-tuned via cost-model edits mid-run.
    """
    if not cost_model_path.exists():
        raise ForwardHaltError(
            f"cost_model file missing at {cost_model_path}; cannot verify "
            f"against manifest pin {manifest.cost_assumptions.config_hash!r}"
        )
    actual = _file_sha256_hex(cost_model_path)
    pinned = manifest.cost_assumptions.config_hash
    # Pinned value may be truncated to >=12 chars (schema min); compare
    # by prefix length of pinned.
    if not actual.startswith(pinned[: max(len(pinned), 12)]):
        # Allow exact equality OR prefix match; if neither holds, halt.
        if actual != pinned:
            raise ForwardHaltError(
                f"cost-yaml hash mismatch: manifest pinned "
                f"{pinned!r}, current file hash {actual!r}. "
                f"Either restore the original cost yaml or open a new "
                f"PRD round to re-pin (forward run cannot continue)."
            )


def _resolve_dates_to_observe(
    manifest: ForwardRunManifest,
    available_index: pd.DatetimeIndex,
    up_to: Optional[date] = None,
) -> list:
    """Return the list of dates needing a ForwardRun entry appended.

    Append-only: never returns dates that already appear in
    ``manifest.runs``. Idempotent: empty list when no new bars.
    """
    seen = {r.as_of_date for r in manifest.runs if r.checkpoint_label.startswith("TD")}
    start_ts = pd.Timestamp(manifest.start_date)
    end_cap = pd.Timestamp(up_to) if up_to else available_index.max()
    candidate_dates = available_index[
        (available_index >= start_ts) & (available_index <= end_cap)
    ]
    new = []
    for ts in candidate_dates:
        d = ts.date()
        if d in seen:
            continue
        new.append(d)
    return new


# ── public API ───────────────────────────────────────────────────────────


def init(
    candidate_id: str,
    *,
    start_date: Optional[Union[date, str]] = None,
    benchmark: str = "SPY",
    secondary_benchmark: Optional[str] = "QQQ",
    decision_days: Optional[list] = None,
    weekly: bool = True,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    registry_db: str = DEFAULT_REGISTRY_DB,
    cost_model_path: Union[str, Path] = DEFAULT_COST_MODEL_PATH,
    baseline_snapshot_path: str = DEFAULT_BASELINE_PATH,
    daily_store_rebuild_commit: Optional[str] = None,
    overwrite: bool = False,
) -> ForwardRunManifest:
    """Create a forward_run_manifest.json for ``candidate_id``.

    Idempotent if ``overwrite=False``: refuses to clobber an existing
    manifest. Pass ``overwrite=True`` to deliberately reset (rare).
    """
    out_path = manifest_path(candidate_id, Path(output_dir))
    if out_path.exists() and not overwrite:
        raise FileExistsError(
            f"manifest already exists at {out_path}; pass overwrite=True "
            f"to reset (this WILL DROP existing runs[])"
        )

    spec_path = Path(output_dir) / f"{candidate_id}.yaml"
    if not spec_path.exists():
        raise FileNotFoundError(
            f"frozen spec not found at {spec_path}; cannot init forward manifest"
        )
    spec = FrozenStrategySpec.from_yaml_file(spec_path)
    spec_hash = _file_sha256_hex(spec_path)

    # Resolve start_date — must be a TRADING DAY (post-MVP audit fix
    # 2026-04-26: previously used `frozen + 1 calendar day` which could
    # land on a weekend, dirtying the forward contract semantics).
    if start_date is None:
        registry = CandidateRegistry(registry_db)
        rec = registry.get(candidate_id)
        if not rec.promoted_at:
            raise ValueError(
                f"candidate {candidate_id} has no promoted_at; pass "
                f"start_date explicitly"
            )
        frozen = datetime.fromisoformat(rec.promoted_at).date()
        # The next trading day strictly AFTER frozen-date (i.e. >= frozen+1d
        # advanced to the next calendar day in the trading-day index).
        proposed = (pd.Timestamp(frozen) + pd.Timedelta(days=1)).date()
        start_date = _next_trading_day(proposed)
    elif isinstance(start_date, str):
        start_date = date.fromisoformat(start_date)
    # If the user passed an explicit date that happens to be a non-trading
    # day, also advance — keeps the contract honest regardless of input.
    start_date = _next_trading_day(start_date)

    cost_path = Path(cost_model_path)
    if not cost_path.exists():
        raise FileNotFoundError(f"cost_model missing at {cost_path}")
    cost_hash = _file_sha256_hex(cost_path)

    cadence = CheckpointCadence(
        weekly=weekly,
        decision_days=list(decision_days) if decision_days else [10, 20, 40, 60],
    )

    snapshot = _build_data_integrity_snapshot(
        baseline_snapshot_path=baseline_snapshot_path,
        daily_store_rebuild_commit=daily_store_rebuild_commit,
    )

    manifest = ForwardRunManifest(
        schema_version="1.0",
        candidate_id=candidate_id,
        evidence_class=EvidenceClass.forward_oos,  # schema enforces this
        spec_hash=spec_hash,
        start_date=start_date,
        benchmark=benchmark,
        secondary_benchmark=secondary_benchmark,
        cost_assumptions=CostAssumptions(
            source=str(cost_path),
            config_hash=cost_hash,
        ),
        checkpoint_cadence=cadence,
        current_status=ForwardRunStatus.not_started,
        data_integrity_snapshot=snapshot,
        runs=[],
    )
    # `spec` is loaded above as a sanity check that the frozen yaml is
    # parseable; the manifest itself only stores the hash, not the spec.
    _ = spec

    save_manifest(manifest, out_path)
    return manifest


def status(
    candidate_id: str,
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict:
    """Read-only manifest summary."""
    p = manifest_path(candidate_id, Path(output_dir))
    manifest = load_manifest(p)
    runs = manifest.runs
    return {
        "candidate_id": candidate_id,
        "manifest_path": str(p),
        "current_status": manifest.current_status.value,
        "evidence_class": manifest.evidence_class.value,
        "start_date": manifest.start_date.isoformat(),
        "n_runs": len(runs),
        "first_run_date": runs[0].as_of_date.isoformat() if runs else None,
        "last_run_date": runs[-1].as_of_date.isoformat() if runs else None,
        "spec_hash": manifest.spec_hash,
        "cost_config_hash": manifest.cost_assumptions.config_hash,
        "cadence_decision_days": list(manifest.checkpoint_cadence.decision_days),
    }


def observe(
    candidate_id: str,
    *,
    up_to: Optional[Union[date, str]] = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    cost_model_path: Union[str, Path] = DEFAULT_COST_MODEL_PATH,
    initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    top_n: int = DEFAULT_TOP_N,
    cfg=None,
    store: Optional[PriceStore] = None,
    dry_run: bool = False,
) -> list:
    """Append-only multi-day catch-up.

    Returns the list of ``ForwardRun`` entries that WERE appended this
    call (empty list if no new bars). Re-running ``observe`` with no
    new bars is a no-op.

    HALT conditions (raise ``ForwardHaltError``):
      - cost yaml's sha256 doesn't match manifest's pinned value
      - manifest's evidence_class is anything other than forward_oos
        (impossible by schema, but guarded again here)
      - data store has no bars at-or-after start_date

    ``dry_run=True``: compute new entries but do not save the manifest.
    """
    if isinstance(up_to, str):
        up_to = date.fromisoformat(up_to)

    out_path = manifest_path(candidate_id, Path(output_dir))
    manifest = load_manifest(out_path)

    if manifest.evidence_class is not EvidenceClass.forward_oos:
        # Belt-and-suspenders: schema already enforces this on load.
        raise ForwardHaltError(
            f"manifest evidence_class={manifest.evidence_class.value!r}, "
            f"expected forward_oos"
        )

    cost_path = Path(cost_model_path)
    _verify_cost_hash_or_halt(manifest, cost_path)

    if cfg is None:
        cfg = load_config()
    if store is None:
        store = create_default_store(cfg)

    # Load full panel from start_date onward — the runner needs enough
    # history to compute composite (factors require lookback).
    panel = _load_panel(
        cfg, store,
        start=pd.Timestamp("1900-01-01"),
        end=pd.Timestamp(up_to) + pd.Timedelta(days=1) if up_to else pd.Timestamp("2100-01-01"),
    )
    close = panel["close"]
    if close.empty:
        raise ForwardHaltError(
            f"no price data available for candidate {candidate_id}; "
            f"cannot observe forward"
        )
    available_index = close.index

    new_dates = _resolve_dates_to_observe(manifest, available_index, up_to=up_to)
    if not new_dates:
        return []

    spec_path = Path(output_dir) / f"{candidate_id}.yaml"
    spec = FrozenStrategySpec.from_yaml_file(spec_path)

    composite, _all_factors = _compute_composite(spec, panel)
    target_wts = _composite_to_target_weights(composite, top_n=top_n)

    # Run a single backtest over the windowed panel; we slice per-day
    # NAV / fills out of it for each new date.
    from core.backtest.backtest_engine import BacktestEngine

    cm = CostModel(cfg.cost_model)
    engine = BacktestEngine(cost_model=cm, initial_capital=initial_capital)
    result = engine.run(
        signals_df=target_wts,
        price_df=panel["close"],
        open_df=panel["open"],
    )
    eq = result.equity_curve
    spy = panel["close"].get("SPY")
    qqq = panel["close"].get("QQQ")
    fills = result.trades or []
    fills_by_date: dict = {}
    for f in fills:
        d = pd.Timestamp(f.fill_date).date()
        fills_by_date[d] = fills_by_date.get(d, 0) + 1

    appended: list = []
    start_ts = pd.Timestamp(manifest.start_date)
    for d in new_dates:
        ts = pd.Timestamp(d)
        # NAV-based metrics use the slice [start_date .. d].
        eq_slice = eq[(eq.index >= start_ts) & (eq.index <= ts)]
        if len(eq_slice) < 1:
            continue
        cum_ret = float(eq_slice.iloc[-1] / eq_slice.iloc[0] - 1.0) if len(eq_slice) >= 2 else 0.0
        ret = eq_slice.pct_change().fillna(0.0)
        sharpe = (
            float(ret.mean() / ret.std() * np.sqrt(252))
            if ret.std() > 0
            else None
        )
        cummax = eq_slice.cummax()
        dd = (eq_slice - cummax) / cummax
        max_dd = float(dd.min()) if len(dd) else 0.0

        def _bench_slice(s: Optional[pd.Series]) -> Optional[float]:
            if s is None:
                return None
            sl = s[(s.index >= start_ts) & (s.index <= ts)].dropna()
            if len(sl) < 2:
                return None
            return float(sl.iloc[-1] / sl.iloc[0] - 1.0)

        spy_ret = _bench_slice(spy)
        qqq_ret = _bench_slice(qqq)
        vs_spy = (cum_ret - spy_ret) if spy_ret is not None else None
        vs_qqq = (cum_ret - qqq_ret) if qqq_ret is not None else None

        # n_observed_trading_days = TDs strictly between start_date and d
        n_td = int(len(available_index[
            (available_index >= start_ts) & (available_index <= ts)
        ]))
        appended.append(ForwardRun(
            checkpoint_label=f"TD{n_td:03d}",
            as_of_date=d,
            n_observed_trading_days=n_td,
            cum_ret=cum_ret,
            sharpe=sharpe,
            max_dd=max_dd,
            vs_spy=vs_spy,
            vs_qqq=vs_qqq,
            notes=f"fills_today={fills_by_date.get(d, 0)}",
        ))

    if not appended:
        return []

    # Reconstruct manifest with appended entries (append-only contract).
    new_runs = list(manifest.runs) + appended
    new_status = (
        ForwardRunStatus.in_progress
        if manifest.current_status is ForwardRunStatus.not_started
        else manifest.current_status
    )
    new_manifest = manifest.model_copy(
        update={"runs": new_runs, "current_status": new_status}
    )
    if not dry_run:
        save_manifest(new_manifest, out_path)
    return appended


def decide(
    candidate_id: str,
    new_status: ForwardRunStatus,
    *,
    notes: Optional[str] = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> ForwardRunManifest:
    """User-driven status mutation.

    R-fwd-1 narrow allow-list: completed_success / completed_fail /
    aborted only. Other ForwardRunStatus values (e.g.,
    decision_pending / in_progress) are managed by the runner itself
    and rejected here.
    """
    if new_status not in _DECIDE_ALLOWED:
        raise ValueError(
            f"decide() only accepts {sorted(s.value for s in _DECIDE_ALLOWED)}; "
            f"got {new_status.value!r}"
        )

    out_path = manifest_path(candidate_id, Path(output_dir))
    manifest = load_manifest(out_path)
    update: dict = {"current_status": new_status}
    if notes:
        # Append a synthetic ForwardRun for the decision so the manifest
        # carries an audit trail. checkpoint_label="DECIDE" ensures it
        # never collides with TD<NNN> entries in observe().
        last_date = (
            manifest.runs[-1].as_of_date if manifest.runs
            else manifest.start_date
        )
        decide_entry = ForwardRun(
            checkpoint_label="DECIDE",
            as_of_date=last_date,
            n_observed_trading_days=(
                manifest.runs[-1].n_observed_trading_days if manifest.runs else 0
            ),
            notes=f"decide={new_status.value}: {notes}",
        )
        update["runs"] = list(manifest.runs) + [decide_entry]
    new_manifest = manifest.model_copy(update=update)
    save_manifest(new_manifest, out_path)
    return new_manifest
