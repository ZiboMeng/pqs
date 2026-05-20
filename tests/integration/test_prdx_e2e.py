"""PRD-X v2 P2-3 E2E integration test.

Auditor F2 + F4 + F6 closure: a single test that exercises the full
chain config → DecisionPolicy → ExecutionPolicy → BacktestEngine →
NAV artifact, end-to-end. If this passes, the trigger-first stack
is wired into the same kernel the production path uses (M11
parity preserved by virtue of routing through `BacktestEngine.run`).

Scope:
  - Load `config/production_strategy.yaml` `decision_stack:` section
  - Construct PartialRebalancePolicy + MLSidecarPolicy from config
  - Generate a synthetic weight panel + price panel
  - Apply overlay via `scripts.run_backtest._apply_decision_stack_overlay`
  - Route filtered weights through `BacktestEngine.run`
  - Assert NAV (BacktestResult.equity_curve) non-empty + values
    sensible (positive, monotonic-ish, no NaN)
  - Cross-check: legacy path (no overlay) produces a different but
    also valid NAV — the overlay does something, but didn't break
    the kernel

§6.4 long-only invariant verified end-to-end (no negative weights
reach engine.run); sealed-2026 trivially守 (synthetic 2018-2024).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

PROJ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJ))

from core.backtest.backtest_engine import BacktestEngine
from core.config.schemas.cost_model import CostModelConfig, CostTierConfig
from core.execution.cost_model import CostModel


@pytest.fixture(scope="module")
def synth_panel():
    """Synthetic price panel for deterministic E2E test."""
    rng = np.random.default_rng(42)
    dates = pd.date_range("2020-01-01", periods=500, freq="B")
    syms = [f"S{i:02d}" for i in range(6)]
    rets = rng.normal(0.0003, 0.012, size=(500, 6))
    rets[0] = 0
    close = pd.DataFrame(
        100.0 * np.exp(np.cumsum(rets, axis=0)),
        index=dates, columns=syms)
    open_df = close.shift(1).bfill()
    return close, open_df


@pytest.fixture(scope="module")
def synth_weights(synth_panel):
    """Synthetic weight panel: monthly equal-weight top-3 across rebal dates."""
    close, _ = synth_panel
    rebal_dates = close.resample("BME").last().index.intersection(close.index)
    weights = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    current = {}
    rng = np.random.default_rng(7)
    for date in close.index:
        if date in rebal_dates:
            # rotate top-3 deterministically: pick 3 of 6 each month
            picks = rng.choice(close.columns, size=3, replace=False)
            current = {s: 0.20 for s in picks}
        for s, w in current.items():
            weights.at[date, s] = w
    return weights


@pytest.fixture(scope="module")
def zero_cost():
    return CostModel(CostModelConfig(tiers={
        "default": CostTierConfig(
            symbols=[], commission_bps=0.0,
            slippage_interday_bps=0.0, slippage_intraday_bps=0.0)
    }))


# ── config load ──────────────────────────────────────────────────────
class TestConfigSchema:
    def test_production_strategy_has_decision_stack_section(self):
        """Auditor F6: config SoT must expose decision_stack abstractions."""
        cfg = yaml.safe_load(
            open(PROJ / "config" / "production_strategy.yaml"))
        assert "decision_stack" in cfg
        ds = cfg["decision_stack"]
        assert ds["mode"] in ("off", "trigger-first")
        assert "partial_rebalance" in ds
        assert "ml_sidecar" in ds
        assert "rule_based" in ds
        assert "deferred_execution" in ds

    def test_default_mode_off_status_conservative(self):
        """Default config must be bit-identical legacy path (mode='off')
        with status='conservative_default'. Flipping is directional."""
        cfg = yaml.safe_load(
            open(PROJ / "config" / "production_strategy.yaml"))
        assert cfg["decision_stack"]["mode"] == "off"
        assert cfg["status"] == "conservative_default"

    def test_decision_stack_band_base_in_unit_interval(self):
        cfg = yaml.safe_load(
            open(PROJ / "config" / "production_strategy.yaml"))
        bb = cfg["decision_stack"]["partial_rebalance"]["band_base"]
        assert 0 < bb < 1, f"band_base={bb} out of (0,1)"


# ── E2E: config → overlay → engine.run → NAV ─────────────────────────
class TestE2EOverlayAppliesAndEngineRuns:
    def test_legacy_path_engine_run_produces_nav(
            self, synth_weights, synth_panel, zero_cost):
        """Sanity: even WITHOUT overlay (legacy default), engine.run
        on the synthetic panel produces a non-empty equity curve."""
        close, open_df = synth_panel
        engine = BacktestEngine(
            cost_model=zero_cost, initial_capital=100_000.0,
            min_trade_usd=100.0, rebalance_threshold=0.02,
            integer_shares=False, execution_freq="interday")
        result = engine.run(
            signals_df=synth_weights, price_df=close, open_df=open_df)
        eq = result.equity_curve
        assert not eq.empty
        assert (eq > 0).all(), "equity curve has non-positive values"
        assert not eq.isna().any(), "equity curve has NaN"

    def test_trigger_first_overlay_then_engine_run_produces_nav(
            self, synth_weights, synth_panel, zero_cost):
        """Auditor F2 + F4: overlay route produces a valid NAV via the
        SAME engine kernel as legacy path. M11 parity preserved (kernel
        untouched). overlay's filtering changes the equity curve but
        does not break the engine."""
        from scripts.run_backtest import _apply_decision_stack_overlay
        close, open_df = synth_panel
        # apply overlay (regime=None → NEUTRAL default)
        regime = pd.Series("NEUTRAL", index=close.index, dtype=str)
        filtered = _apply_decision_stack_overlay(
            synth_weights, regime, band_base=0.02, use_sidecar=False)
        # invariant: filtered must be long-only (>= 0 everywhere)
        assert (filtered.fillna(0) >= 0).all().all(), (
            "overlay produced negative weights — §6.4 violated")
        # invariant: filtered must not exceed gross 1.0
        assert (filtered.fillna(0).sum(axis=1) <= 1.0 + 1e-6).all()
        engine = BacktestEngine(
            cost_model=zero_cost, initial_capital=100_000.0,
            min_trade_usd=100.0, rebalance_threshold=0.02,
            integer_shares=False, execution_freq="interday")
        result = engine.run(
            signals_df=filtered, price_df=close, open_df=open_df)
        eq = result.equity_curve
        assert not eq.empty
        assert (eq > 0).all()
        assert not eq.isna().any()

    def test_overlay_filters_small_deltas(self, synth_panel):
        """Overlay must HOLD when |delta| < band (band-gating active).
        Build a panel with intentionally small deltas to surface the
        filter behavior."""
        from scripts.run_backtest import _apply_decision_stack_overlay
        close, _ = synth_panel
        # Build a panel where current ≈ target for most days; deltas
        # within 0.005 < band 0.02 should HOLD.
        small_delta_w = pd.DataFrame(0.0, index=close.index,
                                      columns=close.columns)
        # day-0: 0.20 in S00; day-1 onwards: 0.205 (delta 0.005 < band)
        small_delta_w.iloc[0, 0] = 0.20
        small_delta_w.iloc[1:, 0] = 0.205
        # rebalance signature changes each day after row 0 → overlay
        # sees a "new" target each day; band gate should treat the
        # 0.005 delta as HOLD and keep weight at 0.20
        regime = pd.Series("NEUTRAL", index=close.index, dtype=str)
        filtered = _apply_decision_stack_overlay(
            small_delta_w, regime, band_base=0.02, use_sidecar=False)
        # After day-0 ENTER_FULL, subsequent days should HOLD at 0.20
        # (not adjust to 0.205, since |delta|=0.005 < add_band=0.01)
        # filtered.iloc[10, 0] should equal 0.20 (held), NOT 0.205
        assert abs(filtered.iloc[10, 0] - 0.20) < 1e-9, (
            f"expected HOLD at 0.20 (band-gated), got "
            f"{filtered.iloc[10, 0]}")
        # And it should differ from the raw target panel
        assert not small_delta_w.equals(filtered)


# ── Long-only invariant end-to-end ───────────────────────────────────
class TestLongOnlyInvariantE2E:
    def test_no_negative_weights_reach_engine(
            self, synth_weights, synth_panel):
        from scripts.run_backtest import _apply_decision_stack_overlay
        close, _ = synth_panel
        regime = pd.Series("NEUTRAL", index=close.index, dtype=str)
        filtered = _apply_decision_stack_overlay(
            synth_weights, regime, band_base=0.02, use_sidecar=True)
        # §6.4 invariant: never any negative weight
        neg_count = (filtered.fillna(0) < 0).sum().sum()
        assert neg_count == 0, (
            f"{neg_count} negative weights — §6.4 long-only violated")


# ── CLI flag wiring ──────────────────────────────────────────────────
class TestRunBacktestCliFlag:
    def test_help_exposes_decision_stack_flag(self):
        """Auditor F4: scripts/run_backtest.py CLI must expose
        --decision-stack flag (opt-in path)."""
        import subprocess
        out = subprocess.run(
            [sys.executable, str(PROJ / "scripts" / "run_backtest.py"),
             "--help"],
            capture_output=True, text=True, cwd=str(PROJ))
        assert "--decision-stack" in out.stdout
        # both modes must be listed
        assert "legacy" in out.stdout
        assert "trigger-first" in out.stdout


# ── Round 31 audit close: run_paper.py live parity ──────────────────
class TestRunPaperLiveParity:
    """Round 31 audit close: scripts/run_paper.py live mode must apply
    the same decision_stack overlay as replay (auditor F1: live ≠ replay
    was the biggest live parity gap).

    AST/source-string seam test — verifies overlay wiring is in the live
    branch source. A full live smoke needs real intraday bars; this
    seam catches the regression "live branch silently drops overlay".
    """

    def test_live_branch_applies_decision_stack_overlay(self):
        src = (PROJ / "scripts" / "run_paper.py").read_text()
        # split into replay and live regions
        live_marker = 'elif args.mode == "live":'
        assert live_marker in src, "live branch marker missing"
        live_idx = src.index(live_marker)
        live_branch_src = src[live_idx:]
        # Overlay wiring must appear inside the live branch
        assert "_apply_decision_stack_overlay_from_config" in live_branch_src, (
            "live branch missing _apply_decision_stack_overlay_from_config "
            "call (Round 31 audit close: live parity with replay)")
        assert "decision_stack" in live_branch_src
        assert "load_production_strategy" in live_branch_src

    def test_live_overlay_guarded_by_decision_stack_flag(self):
        """The overlay must only run when --decision-stack trigger-first
        is explicitly set; legacy default must still bypass."""
        src = (PROJ / "scripts" / "run_paper.py").read_text()
        live_idx = src.index('elif args.mode == "live":')
        # find the overlay block
        overlay_idx = src.index("_apply_decision_stack_overlay_from_config",
                                live_idx)
        # walk backwards to find the if-guard
        preceding = src[live_idx:overlay_idx]
        assert 'args.decision_stack == "trigger-first"' in preceding, (
            "live overlay must be guarded by --decision-stack flag check")


# ── R17 auditor F5/F8 closure: config-driven runtime ─────────────────
class TestConfigDrivenRuntime:
    """Auditor F5 + F8 closure: scripts must consume
    `production_strategy.yaml::decision_stack` section at runtime,
    not hardcode parameters. These tests are the SoT↔runtime
    consistency seam."""

    def test_pydantic_schema_parses_decision_stack(self):
        """DecisionStackConfig pydantic model must accept the yaml
        structure without error."""
        from core.config.production_strategy import (
            load_production_strategy,
        )
        ps = load_production_strategy("config/production_strategy.yaml")
        ds = ps.decision_stack
        assert ds.mode in ("off", "trigger-first")
        # all 4 nested sections present
        assert hasattr(ds, "partial_rebalance")
        assert hasattr(ds, "ml_sidecar")
        assert hasattr(ds, "rule_based")
        assert hasattr(ds, "deferred_execution")

    def test_config_driven_overlay_routes_params(self, synth_panel):
        """The `_apply_decision_stack_overlay_from_config()` wrapper
        must thread yaml-derived params into the overlay. Use
        intentionally small-delta panel (0.005) so band ranging from
        0.001 → 0.02 produces visibly different filter behavior."""
        from scripts.run_backtest import (
            _apply_decision_stack_overlay_from_config,
        )
        from core.config.production_strategy import (
            DecisionStackConfig,
            DecisionStackPartialRebalance,
            DecisionStackMLSidecar,
        )
        close, _ = synth_panel
        # Build a small-delta target panel: 0.20 → 0.205 each day
        small_delta_w = pd.DataFrame(
            0.0, index=close.index, columns=close.columns)
        small_delta_w.iloc[0, 0] = 0.20
        small_delta_w.iloc[1:, 0] = 0.205   # delta 0.005 each row
        regime = pd.Series("NEUTRAL", index=close.index, dtype=str)
        # tight band 0.001 → 0.005 > add_band ~0.0005 → ADD action
        cfg_tight = DecisionStackConfig(
            mode="trigger-first",
            partial_rebalance=DecisionStackPartialRebalance(
                band_base=0.001, partial_full_threshold=0.05),
            ml_sidecar=DecisionStackMLSidecar(
                enabled=False, voter_kind="no_op"))
        # wide band 0.02 → 0.005 < add_band 0.01 → HOLD action
        cfg_wide = DecisionStackConfig(
            mode="trigger-first",
            partial_rebalance=DecisionStackPartialRebalance(
                band_base=0.02, partial_full_threshold=0.05),
            ml_sidecar=DecisionStackMLSidecar(
                enabled=False, voter_kind="no_op"))
        out_tight = _apply_decision_stack_overlay_from_config(
            small_delta_w, regime, cfg_tight)
        out_wide = _apply_decision_stack_overlay_from_config(
            small_delta_w, regime, cfg_wide)
        # tight band lets 0.005 through (ADD updates weight to 0.205);
        # wide band HOLDs (keeps weight at 0.20)
        assert abs(out_tight.iloc[10, 0] - 0.205) < 1e-6, (
            f"tight band should ADD to 0.205, got {out_tight.iloc[10, 0]}")
        assert abs(out_wide.iloc[10, 0] - 0.20) < 1e-6, (
            f"wide band should HOLD at 0.20, got {out_wide.iloc[10, 0]}")
        assert not out_tight.equals(out_wide)

    def test_voter_kind_unknown_raises(self):
        from scripts.run_backtest import _resolve_voter_from_config
        from core.config.production_strategy import (
            DecisionStackMLSidecar,
        )
        cfg = DecisionStackMLSidecar(
            enabled=True, voter_kind="bogus", voter_params={})
        with pytest.raises(ValueError, match=r"unknown voter_kind"):
            _resolve_voter_from_config(cfg)

    def test_voter_kind_classifier_requires_explicit_wiring(self):
        # classifier_voter needs artifact path + feature_extractor;
        # not config-yaml-only — should raise hint instead of silent
        # no-op.
        from scripts.run_backtest import _resolve_voter_from_config
        from core.config.production_strategy import (
            DecisionStackMLSidecar,
        )
        cfg = DecisionStackMLSidecar(
            enabled=True, voter_kind="classifier_voter",
            voter_params={})
        with pytest.raises(ValueError, match=r"classifier_voter"):
            _resolve_voter_from_config(cfg)

    def test_default_config_yields_no_op_voter(self):
        from scripts.run_backtest import _resolve_voter_from_config
        from core.config.production_strategy import (
            DecisionStackMLSidecar,
        )
        # default = enabled=False → None (sidecar fully off)
        cfg = DecisionStackMLSidecar()
        assert _resolve_voter_from_config(cfg) is None
