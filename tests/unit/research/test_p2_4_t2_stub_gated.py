"""PRD-2 P2.4 / R14 — T2 true-short STUB permanent-gate guard.

stub round (NOT execution). AC (PRD-2 ralph-loop R14): T2 =
schema + gate + cost-model DESIGN only; execution wiring is a
PERMANENT TODO. Guard asserts the T2 execution path
refuses/raises (gated-off evidence); there is NO execution
wiring; trigger conditions are documented. **The loop NEVER
auto-fires P2.4 execution** — this test is the safety mechanism
that ENFORCES that, it is the opposite of implementing true-short.

Grounded scope (honest, R4/R6/R7): the T2 schema
(``core.research.long_short_config.LongShortConfig``) and the
per-site raises (HarnessConfig __post_init__ on
``construction_tier='T2'``; ``construction_tiers`` on negative
weights) ALREADY exist. This file is the CONSOLIDATED named
permanent-gate contract in ONE place + the structural assertion
that no execution path consumes the schema for real short orders +
the documented trigger conditions for any future P2.4.
"""
import inspect

import pytest

from core.research.harness.composite_evaluator import HarnessConfig
from core.research import construction_tiers as ct
from core.research import long_short_config as lsc


class TestT2ConfigGate:
    def test_harnessconfig_T2_raises_permanently_gated(self):
        with pytest.raises(ValueError, match="PERMANENTLY GATED"):
            HarnessConfig(construction_tier="T2")

    def test_no_explicit_go_param_exists_to_enable_T2(self):
        # there is NO --explicit-go-true-short / enable flag on the
        # config: T2 cannot be turned on through any normal path.
        sig = inspect.signature(HarnessConfig.__init__)
        for p in sig.parameters:
            assert "explicit_go" not in p and "true_short" not in p, (
                f"HarnessConfig exposes {p!r} — T2 must have NO "
                f"enable param (permanent gate, user-memo only)")

    def test_apply_tier_overlay_T2_raises(self):
        import pandas as pd
        sig = pd.DataFrame({"AAA": [0.6], "BBB": [0.4]})
        # full positional contract (signals, tier, hedge_etf,
        # hedge_frac); T2 must raise regardless of hedge args.
        with pytest.raises((ValueError, NotImplementedError)):
            ct.apply_tier_overlay(sig, construction_tier="T2",
                                  hedge_etf="SH", hedge_frac=0.0)


class TestNoNegativeWeightExecution:
    def test_t1_hedge_rejects_negative_weights_T2_territory(self):
        import pandas as pd
        # negative long weights = T2/true-short territory → must raise
        with pytest.raises(ValueError, match="T2|true-short|negative"):
            ct.apply_t1_inverse_hedge(
                pd.Series({"AAA": -0.2, "BBB": 0.5}),
                hedge_etf="SH", hedge_frac=0.1)


class TestSchemaIsDesignOnlyNoExecutionWiring:
    def test_long_short_config_schema_exists_but_no_execution(self):
        # schema/design object exists (R14 "schema 已在")…
        cfg = lsc.long_only_default()
        assert cfg is not None
        # …but it must NOT be wired into any execution/backtest path.
        # Structural: no order-routing / fill / paper module imports
        # long_short_config to place real short orders.
        import core.backtest.backtest_engine as be
        import core.backtest.intraday_engine as ie
        for mod in (be, ie):
            src = inspect.getsource(mod)
            assert "long_short_config" not in src, (
                f"{mod.__name__} imports long_short_config — true-short "
                f"execution wiring is a PERMANENT TODO, must not exist")

    def test_conservative_130_30_is_schema_not_executed(self):
        # the 130/30 factory is a DESIGN artifact; constructing it must
        # not enable any short execution (it is config-only).
        c = lsc.conservative_130_30()
        assert c is not None  # schema constructs…
        # …and is not consumed by HarnessConfig as an executable tier
        # (T2 still raises regardless of any LongShortConfig object).
        with pytest.raises(ValueError, match="PERMANENTLY GATED"):
            HarnessConfig(construction_tier="T2")


class TestTriggerConditionsDocumented:
    def test_permanent_gate_message_documents_triggers(self):
        # the gate message must spell out the (future, user-only)
        # trigger conditions — explicit-go memo + borrow/margin/
        # squeeze/SSR model + risk-invariant regression.
        try:
            HarnessConfig(construction_tier="T2")
        except ValueError as e:
            msg = str(e)
        for token in ("explicit-go", "borrow", "squeeze", "SSR",
                      "risk-invariant"):
            assert token in msg, (
                f"trigger condition {token!r} not documented in the "
                f"T2 permanent-gate message")
