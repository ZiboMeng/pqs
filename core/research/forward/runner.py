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
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Optional, Union

import numpy as np
import pandas as pd

from core.config.loader import load_config
from core.data.factory import PriceStore, create_default_store
from core.data.source_boundaries import get_boundary
from core.execution.cost_model import CostModel
from core.research.candidate_registry import CandidateRegistry
from core.research.frozen_spec import FrozenStrategySpec
from core.research.robustness.runner import (
    DAILY_STORE_REBUILD_COMMIT,
    _compute_composite,
    _composite_to_target_weights,
    _load_panel,
)

from .bar_hash import (
    DEFAULT_BAR_REVISION,
    compute_bar_hash_rollup,
    compute_benchmark_hash,
    compute_execution_nav_hash,
    compute_signal_input_hash,
)
from .manifest_io import load_manifest, manifest_path, save_manifest
from .manifest_schema import (
    BarHashInputs,
    CheckpointCadence,
    ConfigDriftEvent,
    ConfigSnapshot,
    CostAssumptions,
    DataIntegritySnapshot,
    EvidenceClass,
    ForwardRun,
    ForwardRunManifest,
    ForwardRunStatus,
    SourceLayerBreakdown,
    SourceLayerView,
)
from .revalidate import revalidate_manifest
from .source_layer import classify_as_of, classify_window


_log = logging.getLogger(__name__)

# PRD F step 3 lazy-migration log throttle: track which candidates have
# already been notified this process about a missing config_snapshot, so
# we don't spam the daily forward-observe ritual with the same INFO line.
_F_LEGACY_LOGGED: set[str] = set()


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


# Statuses that observe() must never overwrite — these reflect a
# user-driven terminal decision and re-running observe() against the
# manifest must be a no-op for the status field.
TERMINAL_FORWARD_STATUSES = frozenset({
    ForwardRunStatus.completed_success,
    ForwardRunStatus.completed_fail,
    ForwardRunStatus.aborted,
})


def _next_status_after_observe(
    *,
    current_status: ForwardRunStatus,
    new_runs: list,
    decision_days: list,
) -> ForwardRunStatus:
    """Compute the manifest status after an ``observe()`` call.

    Status-machine rules (PRD §4 + codex Round-4 audit):
      - terminal statuses (``completed_success`` / ``completed_fail`` /
        ``aborted``) and ``decision_pending`` are never overwritten
        here; only ``decide()`` may move them.
      - ``not_started`` / ``in_progress`` transition to
        ``decision_pending`` once the largest observed TD count has
        reached the largest configured ``decision_days`` checkpoint.
      - ``not_started`` transitions to ``in_progress`` on the first
        successful observation when the terminal day has not yet been
        crossed.

    The TD count is taken from each ``ForwardRun.n_observed_trading_days``
    over entries whose ``checkpoint_label`` starts with ``"TD"``. Non-TD
    audit entries (e.g. ``DECIDE``) and future checkpoint / weekly
    entries are intentionally ignored so a future schema extension that
    adds non-TD rows cannot accidentally trip this gate.
    """
    if current_status in TERMINAL_FORWARD_STATUSES:
        return current_status
    if current_status is ForwardRunStatus.decision_pending:
        return ForwardRunStatus.decision_pending
    max_observed_td = max(
        (
            r.n_observed_trading_days
            for r in new_runs
            if r.checkpoint_label.startswith("TD")
        ),
        default=0,
    )
    terminal_day = max(decision_days) if decision_days else 0
    if terminal_day > 0 and max_observed_td >= terminal_day:
        return ForwardRunStatus.decision_pending
    if current_status is ForwardRunStatus.not_started:
        return ForwardRunStatus.in_progress
    return current_status


def _file_sha256_hex(path: Path) -> str:
    h = hashlib.sha256()
    h.update(Path(path).read_bytes())
    return h.hexdigest()


_DEFAULT_DAILY_DIR = Path("data/daily")
_NYSE_CALENDAR_PROXY = "SPY"  # SPY's daily index is the NYSE proxy
# NYSE regular-session close = 16:00 America/New_York (ET).
# In UTC: 20:00 during EDT (Mar–Nov) and 21:00 during EST (Nov–Mar).
# Use ZoneInfo for the comparison so the DST boundary is exact.
_NYSE_TZ = ZoneInfo("America/New_York")


def _next_trading_day(
    d: date, daily_dir: Path = _DEFAULT_DAILY_DIR,
) -> date:
    """Return the first trading day on-or-after ``d``.

    Uses SPY's daily index (NYSE proxy) when available — handles both
    weekends and US market holidays. Falls back to ``BDay`` (weekends
    only) if SPY parquet is missing or ``d`` is beyond SPY's index.
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
    ts = pd.Timestamp(d)
    if ts.weekday() < 5:
        return ts.date()
    return (ts + pd.tseries.offsets.BDay(1)).date()


def _first_post_freeze_trading_day(
    frozen_at_utc: datetime, daily_dir: Path = _DEFAULT_DAILY_DIR,
) -> date:
    """Return the first trading day whose 16:00 ET close is strictly
    AFTER ``frozen_at_utc``.

    Why this matters: a candidate frozen at, say, 15:28 UTC on a
    trading day has its construction-window's last data point at the
    PREVIOUS day's close. The current day's 20:00 UTC close hasn't
    occurred yet, so that close is genuinely post-freeze and SHOULD
    be the first forward-observable bar.

    Pre-fix, ``init()`` used ``frozen_date + 1 calendar day → next
    trading day`` which conservatively skipped the frozen-date itself
    even when the freeze occurred BEFORE that day's market close. For
    a Friday-mid-day freeze that pushed start_date all the way to the
    following Monday, losing a legitimate forward observation day.

    DST-correct logic (R8 fix, replacing the prior 20:00 UTC heuristic
    that was off by 1 hour during EST/winter):

      - Convert ``frozen_at_utc`` to America/New_York via zoneinfo.
      - Compare the ET-local time to 16:00 ET (NYSE regular-session
        close) on the SAME ET date.
      - If ET-local time is strictly before that close: today's close
        is genuinely post-freeze → candidate = ET date.
      - Otherwise: today's close has happened or is happening at the
        freeze instant → candidate = next ET calendar day.

    The ET conversion correctly handles EDT (UTC-4) and EST (UTC-5)
    automatically.
    """
    if frozen_at_utc.tzinfo is None:
        frozen_at_utc = frozen_at_utc.replace(tzinfo=timezone.utc)
    frozen_et = frozen_at_utc.astimezone(_NYSE_TZ)
    et_date = frozen_et.date()
    nyse_close_et = datetime.combine(et_date, time(16, 0), tzinfo=_NYSE_TZ)
    if frozen_et < nyse_close_et:
        candidate = et_date
    else:
        candidate = (pd.Timestamp(et_date) + pd.Timedelta(days=1)).date()
    return _next_trading_day(candidate, daily_dir=daily_dir)


# ── PRD F: config snapshot helpers ───────────────────────────────────


_DEFAULT_CONFIG_DIR = Path("config")
_F_CONFIG_SOURCES: dict[str, str] = {
    # Map of ConfigSnapshot field name → human-readable source path,
    # used both for hashing and for the audit-trail `sources` map.
    "universe_hash": "config/universe.yaml",
    # factor_registry uses a code-level contract (frozensets + map) so
    # cosmetic refactors of the .py file do not false-trigger drift.
    "factor_registry_hash": "core/factors/factor_registry.py::PRODUCTION+RESEARCH+MAP",
    "research_mask_hash": "config/research_mask.yaml",
    "risk_config_hash": "config/risk.yaml",
    "system_config_hash": "config/system.yaml",
}


def _canonical_yaml_sha(path: Path) -> str:
    """Return a content hash of a YAML file canonical to its semantic body.

    Strips comments + normalizes whitespace + sorts dict keys (recursively).
    List ORDER is preserved deliberately — a permutation of a list value
    (e.g. ``seed_pool: [SPY, QQQ]`` → ``seed_pool: [QQQ, SPY]``) DOES
    flip the hash. Many list-shaped config knobs encode meaningful
    order (priority pillars, fallback chains), and even where order is
    semantically irrelevant the conservative position is to fail
    closed: a drift event flags the change, the user inspects, and a
    no-op revert clears the flag instantly.

    Intent: a researcher who re-orders the same dict keys in
    ``config/universe.yaml`` does NOT produce a config-drift event;
    only meaningful semantic changes do (audit round 2 finding —
    docstring previously claimed list values were sorted, which the
    code does not do).
    """
    import hashlib as _hashlib
    import yaml as _yaml

    if not path.exists():
        # Missing config file is itself a drift signal — surface as
        # "missing" so downstream comparison can detect appearance /
        # disappearance.
        return "missing-" + _hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:18]

    raw = path.read_bytes()
    parsed = _yaml.safe_load(raw)

    def _canon(obj):
        if isinstance(obj, dict):
            return {k: _canon(obj[k]) for k in sorted(obj.keys())}
        if isinstance(obj, list):
            return [_canon(x) for x in obj]
        return obj

    canonical = _canon(parsed)
    rendered = _yaml.safe_dump(canonical, sort_keys=True, default_flow_style=False).encode("utf-8")
    return _hashlib.sha256(rendered).hexdigest()


def _factor_registry_contract_sha() -> str:
    """Hash the factor-registry public contract.

    Hashes the canonicalized {(name, scope)} pairs from PRODUCTION_FACTORS
    + RESEARCH_FACTORS + the RESEARCH_TO_PRODUCTION_MAP items. We
    deliberately do NOT hash the .py file bytes — cosmetic refactors of
    factor_registry.py (comments, type hints, formatting) would
    otherwise flip the hash and false-trigger config drift on every
    ralph-audit cycle.

    F PRD §5.5 + codex round-14 §"Fleet Q1" (re factor_registry being
    treated as a code-level contract not a yaml).
    """
    import hashlib as _hashlib
    from core.factors.factor_registry import (
        PRODUCTION_FACTORS,
        RESEARCH_FACTORS,
        RESEARCH_TO_PRODUCTION_MAP,
    )
    parts = []
    for name in sorted(PRODUCTION_FACTORS):
        parts.append(f"P:{name}")
    for name in sorted(RESEARCH_FACTORS):
        parts.append(f"R:{name}")
    for k in sorted(RESEARCH_TO_PRODUCTION_MAP):
        parts.append(f"M:{k}->{RESEARCH_TO_PRODUCTION_MAP[k]}")
    blob = "\n".join(parts).encode("utf-8")
    return _hashlib.sha256(blob).hexdigest()


def _build_config_snapshot(
    config_dir: Path = _DEFAULT_CONFIG_DIR,
) -> ConfigSnapshot:
    """Build a fresh ``ConfigSnapshot`` from the live config tree.

    Called by ``init()`` so the manifest pins the config state that was
    in effect when the candidate's forward window began. The same
    function is also used by ``revalidate`` (step 3) and the opt-in
    backfill utility (step 4) to recompute the current snapshot for
    drift comparison.
    """
    return ConfigSnapshot(
        universe_hash=_canonical_yaml_sha(config_dir / "universe.yaml"),
        factor_registry_hash=_factor_registry_contract_sha(),
        research_mask_hash=_canonical_yaml_sha(config_dir / "research_mask.yaml"),
        risk_config_hash=_canonical_yaml_sha(config_dir / "risk.yaml"),
        system_config_hash=_canonical_yaml_sha(config_dir / "system.yaml"),
        snapshot_at_utc=datetime.now(timezone.utc),
        sources=dict(_F_CONFIG_SOURCES),
    )


def _attach_drift_to_latest_td(
    runs: list, drift: "ConfigDriftEvent",
) -> list:
    """Place ``drift`` on the latest TD entry; no-op if none exists.

    Used to persist a single ``ConfigDriftEvent`` per observe() call:
      - halt path → latest existing TD (no new TDs were appended)
      - no-new-dates path → latest existing TD (nothing changed)
      - normal path → latest newly-appended TD (the observation point
        whose as_of_date matches when drift was detected)

    Idempotent: re-running observe() with the same drift state will
    overwrite the same slot (model_copy via update={...}). The non-TD
    audit entry ``DECIDE`` is intentionally skipped — drift events
    belong on observation points, not user decisions.
    """
    out = list(runs)
    for i in range(len(out) - 1, -1, -1):
        if out[i].checkpoint_label.startswith("TD"):
            out[i] = out[i].model_copy(update={"config_drift_event": drift})
            break
    return out


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
    config_dir: Path = _DEFAULT_CONFIG_DIR,
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

    # Resolve start_date — first trading day whose CLOSE is strictly
    # post-freeze. Uses ``promoted_at`` timestamp (not just date) so a
    # mid-day freeze correctly identifies that trading day's close as
    # post-freeze. (Two audit fixes layered:
    #   2026-04-26 P0: advance non-trading inputs to next trading day
    #   2026-04-26 P0v2: timestamp-aware close comparison vs
    #                    calendar-day arithmetic — fixes Cand-2 case
    #                    where frozen_at=15:28 UTC was incorrectly
    #                    pushing start_date 3 days forward to Mon
    #                    instead of correctly observing same-day close)
    if start_date is None:
        registry = CandidateRegistry(registry_db)
        rec = registry.get(candidate_id)
        if not rec.promoted_at:
            raise ValueError(
                f"candidate {candidate_id} has no promoted_at; pass "
                f"start_date explicitly"
            )
        frozen_dt = datetime.fromisoformat(rec.promoted_at)
        start_date = _first_post_freeze_trading_day(frozen_dt)
    elif isinstance(start_date, str):
        start_date = date.fromisoformat(start_date)
        start_date = _next_trading_day(start_date)
    else:
        # date object passed — still advance non-trading days
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

    # PRD F: pin a config snapshot at init so revalidate (step 3) can
    # detect mid-run config drift distinctly from data-tier revisions.
    config_snapshot = _build_config_snapshot(Path(config_dir))

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
        config_snapshot=config_snapshot,
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
      - manifest's current_status is ``requires_data_review`` (PRD v2.1 §4.4):
        revalidate previously surfaced a material data revision; user
        must clear via ``decide()`` before further observe() runs.
      - manifest's current_status is terminal (``completed_success`` /
        ``completed_fail`` / ``aborted``): the candidate has already
        been decided. Continuing observe() would let a downstream v2.1
        DataRevisionEvent or PRD-F ConfigDriftEvent silently overwrite
        the terminal status to ``requires_data_review``, losing the
        decision signal. Audit round 2 finding (2026-04-29).

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

    # PRD v2.1 §4.4: when revalidate has previously surfaced a
    # material revision and flipped the manifest into
    # ``requires_data_review``, observe() refuses to do anything until
    # the user clears it via decide(). Otherwise we'd silently overwrite
    # the data_revision_event events on the next pass.
    if manifest.current_status is ForwardRunStatus.requires_data_review:
        raise ForwardHaltError(
            f"candidate {candidate_id} is in requires_data_review "
            f"status; revalidate previously detected a material data "
            f"revision. User must call decide() (e.g. completed_fail "
            f"or aborted) to acknowledge before further observe() "
            f"runs are permitted."
        )

    # Audit round 2 finding (2026-04-29): also halt on terminal
    # statuses so revalidate cannot silently overwrite a decided
    # candidate with ``requires_data_review``. The asymmetry
    # (requires_data_review halt only) was a gap.
    if manifest.current_status in TERMINAL_FORWARD_STATUSES:
        raise ForwardHaltError(
            f"candidate {candidate_id} is in terminal status "
            f"{manifest.current_status.value!r}; observe() is not "
            f"permitted on a decided candidate. Continuing would let a "
            f"downstream data revision or config drift overwrite the "
            f"decision signal. If you need to re-open the candidate, "
            f"start a new candidate_id; the v2.1 / PRD-F evidence "
            f"contracts intentionally make terminal states absorbing."
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

    spec_path = Path(output_dir) / f"{candidate_id}.yaml"
    spec = FrozenStrategySpec.from_yaml_file(spec_path)

    # ── PRD v2.1 §4.6: revalidate runs FIRST, regardless of whether ─
    # any new TD bars are available. This catches retroactive yfinance
    # revisions that land on existing TDs even on days where no new
    # bar arrives (e.g. weekends, holidays, or just before the close
    # of a trading day). Behavior:
    #   - Pre-v2 entries (TD001 with no bar_hash + no legacy marker)
    #     are silently skipped; they get the legacy marker further down.
    #   - v2 entries: all three input-scope hashes are recomputed; any
    #     mismatch becomes a DataRevisionEvent on that entry.
    #   - If any event escalates to invalidated, we persist + flip
    #     status to requires_data_review + return [] without appending
    #     any new TDs. The next observe() call halts above until
    #     decide() clears the state.
    v2_universe_for_reval: list = sorted(panel["close"].columns.tolist())
    bench_syms_for_reval: list = sorted({manifest.benchmark} | (
        {manifest.secondary_benchmark} if manifest.secondary_benchmark else set()
    ))
    # PRD F step 3: build a fresh config snapshot for drift detection.
    # Always built (cheap: 5 file hashes); revalidate_manifest skips
    # detection itself when the manifest pre-dates F (lazy migration).
    current_config_snapshot = _build_config_snapshot(_DEFAULT_CONFIG_DIR)
    reval = revalidate_manifest(
        manifest,
        spec=spec,
        universe=v2_universe_for_reval,
        panel=panel,
        benchmark_symbols=bench_syms_for_reval,
        detected_by_run_label=(
            f"observe@{datetime.now(timezone.utc).isoformat(timespec='seconds')}"
        ),
        current_config_snapshot=current_config_snapshot,
    )
    # PRD F lazy-migration boundary: pre-PRD-F manifests have
    # config_snapshot=None. Log once per process per candidate so
    # operators see it without flooding the daily ritual logs.
    if reval.config_drift_skipped_legacy and candidate_id not in _F_LEGACY_LOGGED:
        _F_LEGACY_LOGGED.add(candidate_id)
        _log.info(
            "PRD F lazy-migration: candidate %s has no config_snapshot; "
            "drift detection skipped. Run dev/scripts/forward/"
            "backfill_config_snapshot.py to opt in.",
            candidate_id,
        )
    # Track whether revalidate produced events that need persisting,
    # so the no-new-dates early return below can still flush them.
    # Pre-fix: flagged_only events on a no-new-bar day were rebuilt
    # in-memory but lost on early return because save_manifest was
    # only at the bottom of the new-TDs path.
    manifest_dirty_from_revalidate = False
    revalidated_runs: list = list(manifest.runs)

    # 1. Persist data revision events on affected entries.
    if reval.events:
        affected_id_to_event = {id(e): ev for (e, ev) in reval.events}
        revalidated_runs = []
        for entry in manifest.runs:
            ev = affected_id_to_event.get(id(entry))
            if ev is not None:
                revalidated_runs.append(
                    entry.model_copy(update={"data_revision_event": ev})
                )
            else:
                revalidated_runs.append(entry)
        manifest_dirty_from_revalidate = True

    # 2. PRD F step 3: persist config_drift_event on the latest TD when
    # the drift is HALT-class. Halt path returns before append, so the
    # natural anchor is whichever TD already exists. Warn-class drift
    # is deferred to post-append (latest new TD is the right home —
    # observation point matches detection point).
    if reval.config_drift_event is not None and reval.requires_data_review:
        revalidated_runs = _attach_drift_to_latest_td(
            revalidated_runs, reval.config_drift_event,
        )
        manifest_dirty_from_revalidate = True

    if manifest_dirty_from_revalidate or reval.requires_data_review:
        update: dict = {"runs": revalidated_runs}
        if reval.requires_data_review:
            update["current_status"] = ForwardRunStatus.requires_data_review
        manifest = manifest.model_copy(update=update)
        manifest_dirty_from_revalidate = True

    if reval.requires_data_review:
        # Halt — save the events + flipped status, then return without
        # appending. Next observe() call will halt at the top-of-function
        # status guard until decide() clears it. Halt is triggered by
        # EITHER an invalidated DataRevisionEvent OR a halt-class
        # ConfigDriftEvent.
        if not dry_run:
            save_manifest(manifest, out_path)
        return []
    # Non-invalidated events (flagged_only) + warn-class config drift
    # both stay on the rebound `manifest` variable. They get persisted
    # by either the no-new-dates path below OR the bottom save_manifest
    # (when new TDs append).

    new_dates = _resolve_dates_to_observe(manifest, available_index, up_to=up_to)
    if not new_dates:
        # No new bars to append. Persist any deferred warn-class config
        # drift event on the latest existing TD (no new TD anchor exists).
        if reval.config_drift_event is not None:
            new_runs_with_drift = _attach_drift_to_latest_td(
                list(manifest.runs), reval.config_drift_event,
            )
            manifest = manifest.model_copy(update={"runs": new_runs_with_drift})
            manifest_dirty_from_revalidate = True
        if manifest_dirty_from_revalidate and not dry_run:
            save_manifest(manifest, out_path)
        return []

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

    # ── v2.1 evidence-hardening prep ────────────────────────────────
    # Reuse v2_universe + bench_syms already computed for the top-of-
    # function revalidate pass. Held-or-traded set is per-window so
    # it's still computed here.
    v2_universe = v2_universe_for_reval
    bench_syms  = bench_syms_for_reval
    # Held-or-traded set for execution_nav scope = union of all
    # symbols with non-zero weight on any date inside
    # [start_date..max(new_dates)]. This stays anchored at start_date
    # per PRD §G6.
    last_new_ts = pd.Timestamp(max(new_dates))
    in_window = target_wts[(target_wts.index >= start_ts)
                           & (target_wts.index <= last_new_ts)]
    held_or_traded: list = sorted(
        s for s in in_window.columns if (in_window[s].abs() > 0).any()
    )

    # Pre-cache per-symbol canonical_end_date so each TD entry's
    # source_mix flag can be computed without re-reading the sidecar
    # repeatedly. None canonical_end_date = no boundary recorded for
    # that symbol; treat as "unknown" → does not contribute to
    # source_mix=True.
    boundary_cache: dict = {}
    for sym in target_wts.columns:
        b = get_boundary(sym)
        boundary_cache[sym] = (
            b["canonical_end_date"] if b and b.get("canonical_end_date")
            else None
        )

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

        # Source-mix detection: if any held symbol on this date has a
        # canonical_end_date BEFORE d, the bar driving today's NAV
        # came from yfinance frontier (different source layer than
        # the candidate's polygon-canonical construction). Mark the
        # entry so downstream consumers don't conflate forward
        # observation NAV with construction-layer NAV.
        held_today = [
            sym for sym in target_wts.columns
            if abs(target_wts.loc[ts, sym]) > 0.0
        ] if ts in target_wts.index else []
        source_mix: Optional[bool] = None
        if held_today:
            source_mix = False
            for sym in held_today:
                ce = boundary_cache.get(sym)
                if ce is not None and d > ce:
                    source_mix = True
                    break
        # ── v2.1 input-scope hashes + observation-time evidence ─────
        sig_h, sig_in = compute_signal_input_hash(
            spec=spec, universe=v2_universe, panel=panel, as_of_date=d,
        )
        exec_h, exec_in = compute_execution_nav_hash(
            held_or_traded_symbols=held_or_traded,
            panel=panel,
            start_date=manifest.start_date,
            as_of_date=d,
        )
        bench_h, bench_in = compute_benchmark_hash(
            benchmark_symbols=bench_syms,
            panel=panel,
            start_date=manifest.start_date,
            as_of_date=d,
        )
        rollup = compute_bar_hash_rollup(sig_h, exec_h, bench_h)
        bar_inputs = BarHashInputs(
            signal_input=sig_in, execution_nav=exec_in, benchmark=bench_in,
        )

        # held_today_weights snapshot — drives revalidate's NAV-impact
        # bps via Σ weight[sym] × close_drift_pct. Captured at observation
        # time; never mutated.
        held_today_weights: dict = {}
        if ts in target_wts.index:
            for sym in target_wts.columns:
                w = float(target_wts.loc[ts, sym])
                if abs(w) > 0:
                    held_today_weights[sym] = w

        # Source-layer breakdown — both views per PRD §G3.
        as_of_co = as_of_fo = as_of_mx = 0
        for sym in held_today:
            layer = classify_as_of(sym, d)
            if layer == "canonical_only":
                as_of_co += 1
            elif layer == "frontier_only":
                as_of_fo += 1
            else:
                as_of_mx += 1
        win_co = win_fo = win_mx = 0
        win_universe = sorted(set(v2_universe) | set(held_or_traded) | set(bench_syms))
        for sym in win_universe:
            layer = classify_window(sym, manifest.start_date, d)
            if layer == "canonical_only":
                win_co += 1
            elif layer == "frontier_only":
                win_fo += 1
            else:
                win_mx += 1
        layer_breakdown = SourceLayerBreakdown(
            as_of_held_source=SourceLayerView(
                canonical_only_n_symbols=as_of_co,
                frontier_only_n_symbols=as_of_fo,
                mixed_n_symbols=as_of_mx,
            ),
            window_input_source=SourceLayerView(
                canonical_only_n_symbols=win_co,
                frontier_only_n_symbols=win_fo,
                mixed_n_symbols=win_mx,
            ),
        )

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
            source_mix=source_mix,
            # ── v2.1 fields (PRD `forward_evidence_hardening_prd.md` v2.1) ──
            legacy_unhashed_inputs=False,
            signal_input_hash=sig_h,
            execution_nav_hash=exec_h,
            benchmark_hash=bench_h,
            bar_hash=rollup,
            bar_hash_inputs=bar_inputs,
            source_layer_breakdown=layer_breakdown,
            held_today_weights=held_today_weights,
        ))

    if not appended:
        return []

    # ── PRD v2.1 §4.2 + §G6: TD001 legacy boundary ──────────────────
    # Existing entries that were written before v2.1 shipped have no
    # bar_hash and no legacy_unhashed_inputs marker. The first v2.1
    # observe() call rewrites those entries' metadata-only legacy
    # marker (numeric fields are NOT touched). v2.1 entries already
    # write legacy_unhashed_inputs=False at construction time.
    grandfathered_runs: list = []
    for entry in manifest.runs:
        if (entry.bar_hash is None
                and entry.legacy_unhashed_inputs is None):
            grandfathered_runs.append(
                entry.model_copy(update={"legacy_unhashed_inputs": True})
            )
        else:
            grandfathered_runs.append(entry)

    # Reconstruct manifest with appended entries (append-only contract).
    new_runs = grandfathered_runs + appended

    # PRD F step 3: warn-class config drift was deferred above so it
    # could anchor on the freshest TD. Attach to the latest new TD here.
    if reval.config_drift_event is not None:
        # Only reachable on warn severity (halt branch returned early).
        new_runs = _attach_drift_to_latest_td(
            new_runs, reval.config_drift_event,
        )

    new_status = _next_status_after_observe(
        current_status=manifest.current_status,
        new_runs=new_runs,
        decision_days=list(manifest.checkpoint_cadence.decision_days or []),
    )
    new_manifest = manifest.model_copy(
        update={"runs": new_runs, "current_status": new_status}
    )

    # NOTE: revalidate already ran at the top of observe() against
    # pre-existing entries. New TDs in `appended` were just hashed from
    # the same panel they'd be revalidated against, so re-running
    # revalidate here would be a no-op for them. Skipping avoids
    # redundant work + the risk of double-persisting flagged_only
    # events from the top pass.

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
