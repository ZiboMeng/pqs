"""PRD-X v2 Phase X2 sub-step 5a — NoTradeBandCalculator (TDD).

build round. AC (PRD §5.3.1 + §11 X2):
  - 4 bands per symbol (enter / add / trim / exit)
  - vol-conditional: high vol → wider band (Leland 1999)
  - regime-conditional: RISK_OFF/CAUTIOUS → wider band
  - bands > 0 always (degenerate guard)
  - deterministic given same inputs
  - sealed 2026 永不读 (calculator reads ctx only, no panel access)
"""
import inspect

import pytest

from core.regime.regime_detector import RegimeState
from core.research.decision.no_trade_band import (
    Bands,
    NoTradeBandCalculator,
)


# ── shape + deterministic ────────────────────────────────────────────
class TestBandsShape:
    def test_four_bands(self):
        b = Bands(enter=0.02, add=0.01, trim=0.01, exit=0.02)
        assert b.enter == 0.02 and b.add == 0.01
        assert b.trim == 0.01 and b.exit == 0.02

    def test_negative_band_rejected(self):
        # PRD §5.3 bands are widths (>0); negative is meaningless
        with pytest.raises(ValueError, match=r"non-negative|width"):
            Bands(enter=-0.01, add=0.01, trim=0.01, exit=0.02)


class TestNoTradeBandDeterministic:
    def test_same_inputs_same_output(self):
        c = NoTradeBandCalculator(base_band=0.02)
        ctx = {"realized_vol": 0.15, "regime": RegimeState.NEUTRAL}
        a = c.compute("SPY", ctx)
        b = c.compute("SPY", ctx)
        assert a == b


# ── vol-conditional (Leland 1999 mechanic) ───────────────────────────
class TestVolConditional:
    def test_high_vol_wider_than_low_vol(self):
        c = NoTradeBandCalculator(base_band=0.02)
        lo = c.compute("X", {"realized_vol": 0.10,
                             "regime": RegimeState.NEUTRAL})
        hi = c.compute("X", {"realized_vol": 0.40,
                             "regime": RegimeState.NEUTRAL})
        # PRD §5.3.1 + Leland 1999: high vol → wider no-trade band
        # (reduces churn under noise).
        assert hi.enter > lo.enter
        assert hi.exit > lo.exit
        assert hi.trim > lo.trim
        assert hi.add > lo.add

    def test_vol_multiplier_monotone(self):
        c = NoTradeBandCalculator(base_band=0.02)
        b1 = c.compute("X", {"realized_vol": 0.10,
                             "regime": RegimeState.NEUTRAL})
        b2 = c.compute("X", {"realized_vol": 0.20,
                             "regime": RegimeState.NEUTRAL})
        b3 = c.compute("X", {"realized_vol": 0.40,
                             "regime": RegimeState.NEUTRAL})
        assert b1.enter < b2.enter < b3.enter

    def test_missing_vol_defaults_to_one(self):
        # graceful: if realized_vol absent from ctx, treat as 1x
        # base (no widening, no narrowing). NOT a crash.
        c = NoTradeBandCalculator(base_band=0.02)
        b = c.compute("X", {"regime": RegimeState.NEUTRAL})
        assert b.enter > 0


# ── regime-conditional ───────────────────────────────────────────────
class TestRegimeConditional:
    def test_risk_off_wider_than_risk_on(self):
        c = NoTradeBandCalculator(base_band=0.02)
        on = c.compute("X", {"realized_vol": 0.15,
                             "regime": RegimeState.RISK_ON})
        off = c.compute("X", {"realized_vol": 0.15,
                              "regime": RegimeState.RISK_OFF})
        # PRD §5.3.1: risk-off → wider band (avoid unnecessary turnover)
        assert off.enter > on.enter
        assert off.exit > on.exit

    def test_cautious_between_neutral_and_risk_off(self):
        c = NoTradeBandCalculator(base_band=0.02)
        ctx = lambda r: {"realized_vol": 0.15, "regime": r}
        neu = c.compute("X", ctx(RegimeState.NEUTRAL))
        cau = c.compute("X", ctx(RegimeState.CAUTIOUS))
        off = c.compute("X", ctx(RegimeState.RISK_OFF))
        assert neu.enter <= cau.enter <= off.enter

    def test_bull_and_risk_on_no_widening(self):
        c = NoTradeBandCalculator(base_band=0.02)
        ctx = lambda r: {"realized_vol": 0.15, "regime": r}
        neu = c.compute("X", ctx(RegimeState.NEUTRAL))
        on = c.compute("X", ctx(RegimeState.RISK_ON))
        bull = c.compute("X", ctx(RegimeState.BULL))
        # neutral/risk-on/bull should be ~ same (no penalty multiplier)
        assert abs(on.enter - neu.enter) < 1e-9
        assert abs(bull.enter - neu.enter) < 1e-9

    def test_missing_regime_defaults_to_neutral(self):
        c = NoTradeBandCalculator(base_band=0.02)
        b = c.compute("X", {"realized_vol": 0.15})
        b_neu = c.compute("X", {"realized_vol": 0.15,
                                "regime": RegimeState.NEUTRAL})
        assert b == b_neu


# ── R18 (auditor F5) per-symbol vol map precedence ──────────────────
class TestPerSymbolVolMap:
    def test_per_symbol_overrides_scalar(self):
        # ctx['realized_vol_by_symbol'][symbol] takes precedence over
        # scalar ctx['realized_vol']. R18 (auditor F5) closure.
        c = NoTradeBandCalculator(base_band=0.02)
        # SPY uses per-symbol 0.40 → wide; QQQ uses scalar 0.10 → narrow
        ctx = {
            "realized_vol": 0.10,  # scalar fallback
            "realized_vol_by_symbol": {"SPY": 0.40},
            "regime": RegimeState.NEUTRAL,
        }
        b_spy = c.compute("SPY", ctx)  # uses 0.40
        b_qqq = c.compute("QQQ", ctx)  # falls back to scalar 0.10
        assert b_spy.enter > b_qqq.enter, (
            f"SPY band {b_spy.enter} should be wider than QQQ "
            f"band {b_qqq.enter} (per-symbol vol should override "
            f"scalar fallback)")

    def test_empty_map_falls_back_to_scalar(self):
        c = NoTradeBandCalculator(base_band=0.02)
        b1 = c.compute("X", {"realized_vol_by_symbol": {},
                              "realized_vol": 0.40,
                              "regime": RegimeState.NEUTRAL})
        b2 = c.compute("X", {"realized_vol": 0.40,
                              "regime": RegimeState.NEUTRAL})
        assert b1 == b2

    def test_none_value_in_map_falls_back(self):
        # NaN/None per-symbol → fallback to scalar
        c = NoTradeBandCalculator(base_band=0.02)
        b1 = c.compute("X", {"realized_vol_by_symbol": {"X": None},
                              "realized_vol": 0.40,
                              "regime": RegimeState.NEUTRAL})
        b2 = c.compute("X", {"realized_vol": 0.40,
                              "regime": RegimeState.NEUTRAL})
        assert b1 == b2


# ── compound: vol + regime stack ─────────────────────────────────────
class TestStackedMultipliers:
    def test_high_vol_plus_risk_off_widest(self):
        c = NoTradeBandCalculator(base_band=0.02)
        b1 = c.compute("X", {"realized_vol": 0.10,
                             "regime": RegimeState.BULL})
        b2 = c.compute("X", {"realized_vol": 0.40,
                             "regime": RegimeState.RISK_OFF})
        # stacked multipliers: high vol × risk-off >> low vol × bull
        assert b2.enter > b1.enter * 1.5  # at least 1.5x wider

    def test_bands_always_positive(self):
        # bands must never collapse to 0 (no-op fallback would
        # produce arbitrary trades)
        c = NoTradeBandCalculator(base_band=0.02)
        for vol in (0.0, 0.05, 0.50, 1.0):
            for reg in RegimeState:
                b = c.compute("X", {"realized_vol": vol, "regime": reg})
                assert b.enter > 0, (vol, reg)
                assert b.exit > 0
                assert b.trim > 0
                assert b.add > 0


# ── invariant + sealed-2026 discipline ──────────────────────────────
class TestSchemaPurity:
    def test_no_panel_imports(self):
        # X1 pattern: NoTradeBandCalculator must not import panel/
        # bar_store at module level (calculator reads ctx only).
        import core.research.decision.no_trade_band as mod
        import ast
        tree = ast.parse(inspect.getsource(mod))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                for n in node.names:
                    imported.add(n.name)
        for forbidden in ("core.data", "yfinance",
                          "core.data.bar_store"):
            for name in imported:
                assert not name.startswith(forbidden), (
                    f"NoTradeBandCalculator imports {name} — must be "
                    f"pure calculator, ctx-driven only")

    def test_base_band_validation(self):
        with pytest.raises(ValueError, match=r"base_band"):
            NoTradeBandCalculator(base_band=-0.01)
        with pytest.raises(ValueError, match=r"base_band"):
            NoTradeBandCalculator(base_band=0.0)
