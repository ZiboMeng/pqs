"""Settle-window (memo 20260708) — the most-recent N trading days of forward
observation are provisional (yfinance frontier bars revise preliminary→final),
so they are dropped + re-derived each observe instead of halting on benign
trailing-bar revisions. Settled history keeps strict revision detection.

These are fast unit tests (schema + the pure partition helper + init wiring);
the end-to-end observe path is exercised by the real cycle06/08 re-init and
the existing test_forward_runner_v2_integration suite.
"""
from pathlib import Path

import pandas as pd
import pytest

from core.research.forward.manifest_schema import CheckpointCadence
from core.research.forward.runner import (
    RECOMMENDED_SETTLE_WINDOW_TRADING_DAYS,
    _drop_provisional_tail,
    init,
    manifest_path,
)


# ── schema ──────────────────────────────────────────────────────────────
def test_cadence_settle_window_default_zero():
    """Legacy default = 0 (disabled) so existing manifests deserialize to the
    pre-2026-07-08 strict contract, byte-unchanged."""
    assert CheckpointCadence().settle_window_trading_days == 0


def test_cadence_settle_window_round_trip():
    c = CheckpointCadence(settle_window_trading_days=10)
    assert CheckpointCadence.model_validate(
        c.model_dump()).settle_window_trading_days == 10


def test_cadence_settle_window_rejects_negative():
    with pytest.raises(Exception):
        CheckpointCadence(settle_window_trading_days=-1)


# ── partition helper ────────────────────────────────────────────────────
class _R:
    def __init__(self, label, as_of):
        self.checkpoint_label = label
        self.as_of_date = pd.Timestamp(as_of).date()


def _mk_runs(idx):
    return [_R(f"TD{i + 1:03d}", idx[i].date()) for i in range(len(idx))]


def test_drop_disabled_when_zero_keeps_all():
    idx = pd.bdate_range("2026-05-19", "2026-07-08")
    runs = _mk_runs(idx)
    kept, dropped = _drop_provisional_tail(runs, idx, 0)
    assert dropped == 0 and len(kept) == len(runs)


def test_drop_unsettled_tail_exact_count():
    """N=k drops exactly the last k TDs (those with < k trading days after)."""
    idx = pd.bdate_range("2026-05-19", "2026-07-08")
    runs = _mk_runs(idx)
    for k in (1, 5, 10):
        kept, dropped = _drop_provisional_tail(runs, idx, k)
        assert dropped == k, f"N={k}"
        assert len(kept) == len(runs) - k
        # the kept entries are the OLDEST ones (settled)
        assert kept[-1].as_of_date == idx[len(idx) - k - 1].date()


def test_drop_keeps_non_td_entries():
    idx = pd.bdate_range("2026-05-19", "2026-07-08")
    runs = _mk_runs(idx)
    runs.append(_R("DECIDE-user", idx[-1].date()))  # non-TD at the frontier
    kept, dropped = _drop_provisional_tail(runs, idx, 10)
    assert any(r.checkpoint_label == "DECIDE-user" for r in kept)
    assert dropped == 10  # only TD entries counted


def test_drop_boundary_entry_exactly_n_is_settled():
    """An entry with EXACTLY N trading days after it is settled (kept); N-1 is
    provisional (dropped)."""
    idx = pd.bdate_range("2026-05-19", "2026-07-08")
    runs = _mk_runs(idx)
    N = 6
    kept, dropped = _drop_provisional_tail(runs, idx, N)
    # entry at position len-1-N has exactly N TDs after → kept (settled)
    settled_boundary = idx[len(idx) - 1 - N].date()
    assert any(r.as_of_date == settled_boundary for r in kept)
    # entry at position len-N has N-1 TDs after → dropped (provisional)
    provisional_boundary = idx[len(idx) - N].date()
    assert all(r.as_of_date != provisional_boundary for r in kept)


def test_drop_empty_or_none_index_safe():
    assert _drop_provisional_tail([], pd.DatetimeIndex([]), 10) == ([], 0)
    idx = pd.bdate_range("2026-05-19", "2026-05-22")
    runs = _mk_runs(idx)
    kept, dropped = _drop_provisional_tail(runs, None, 10)
    assert dropped == 0 and len(kept) == len(runs)


# ── init() wiring ───────────────────────────────────────────────────────
def _minimal_spec_yaml(cid: str) -> str:
    return f"""
candidate_id: {cid}
strategy_version: test-v1-2026-07-08
source_trial_id: test_trial_001
feature_set:
  - name: ret_5d
    weight: 1.0
    family: B
    source: core/factors/factor_generator.py
benchmark_relative_summary: 'test'
oos_holdout_summary: 'test'
robustness_summary: 'test'
decision_memo: 'test'
"""


def _setup(tmp_path: Path):
    out_dir = tmp_path / "candidates"
    out_dir.mkdir()
    (out_dir / "fake_cand.yaml").write_text(_minimal_spec_yaml("fake_cand"))
    cost = tmp_path / "cost_model.yaml"
    cost.write_text("commission_per_trade: 0.005\nslippage_bps: 5\n")
    return out_dir, cost


def test_init_default_is_zero_opt_in(tmp_path: Path):
    """init()'s OWN default is 0 (legacy strict contract) so existing manifests
    + tests are byte-unchanged; the settle-window is opt-in per candidate."""
    out_dir, cost = _setup(tmp_path)
    m = init(candidate_id="fake_cand", start_date="2026-04-25",
             output_dir=out_dir, cost_model_path=cost)
    assert m.checkpoint_cadence.settle_window_trading_days == 0
    assert RECOMMENDED_SETTLE_WINDOW_TRADING_DAYS == 10  # documented recommendation


def test_init_settle_window_override(tmp_path: Path):
    out_dir, cost = _setup(tmp_path)
    m = init(candidate_id="fake_cand", start_date="2026-04-25",
             output_dir=out_dir, cost_model_path=cost,
             settle_window_trading_days=3)
    assert m.checkpoint_cadence.settle_window_trading_days == 3
    # persisted through save/load
    from core.research.forward.manifest_io import load_manifest
    reloaded = load_manifest(manifest_path("fake_cand", out_dir))
    assert reloaded.checkpoint_cadence.settle_window_trading_days == 3


def test_init_settle_window_zero_is_legacy(tmp_path: Path):
    out_dir, cost = _setup(tmp_path)
    m = init(candidate_id="fake_cand", start_date="2026-04-25",
             output_dir=out_dir, cost_model_path=cost,
             settle_window_trading_days=0)
    assert m.checkpoint_cadence.settle_window_trading_days == 0
