"""PRD-2 ralph-loop P2.1 R1 — construction_tier T0 bit-identical guard (TDD).

R1 = scaffold only: add `construction_tier` to HarnessConfig with
default "T0". T0 MUST be a pure no-op (zero behaviour change, bit-
identical to the pre-tier path); T1 (1x inverse-hedge) is R2 (not yet
wired -> NotImplementedError); T2 (true short) is permanently gated
(PRD-2 §6 / P2.4 — needs user explicit-go, never auto). Machine-
checkable AC: default == T0, explicit-T0 config == default config,
construction_tier is NOT consumed by any construction code yet
(structural bit-identical guarantee), T1/T2/bogus rejected.
"""
import inspect
import re

import pytest

from core.research.harness.composite_evaluator import HarnessConfig
import core.research.harness.composite_evaluator as ce


def _cfg(**kw):
    # cap_aware needs cluster_map etc.; use global_top_n for a minimal
    # valid config (R1 only touches the tier field/validation).
    base = dict(construction_mode="global_top_n", top_n=10)
    base.update(kw)
    return HarnessConfig(**base)


class TestConstructionTierT0:
    def test_default_is_T0(self):
        assert _cfg().construction_tier == "T0"

    def test_explicit_T0_equals_default(self):
        # frozen dataclass: same field values -> __eq__ True. Proves
        # specifying T0 changes nothing vs the default path.
        assert _cfg() == _cfg(construction_tier="T0")

    def test_T1_not_yet_wired(self):
        # R2 wires 1x inverse-hedge; until then T1 must refuse loudly,
        # not silently behave like T0.
        with pytest.raises(NotImplementedError):
            _cfg(construction_tier="T1")

    def test_T2_permanently_gated(self):
        # true short = invariant break; PRD-2 §6 — never auto, needs
        # explicit-go. Must raise regardless.
        with pytest.raises((NotImplementedError, ValueError)):
            _cfg(construction_tier="T2")

    def test_bogus_tier_rejected(self):
        with pytest.raises(ValueError):
            _cfg(construction_tier="T9")

    def test_tier_not_consumed_by_construction_code(self):
        # Structural bit-identical guarantee for T0: in R1 the field is
        # a scaffold only — it must NOT be referenced anywhere in the
        # construction functions (only in the class def + __post_init__).
        src = inspect.getsource(ce)
        # strip the HarnessConfig class block (def + docstring + __post_init__)
        # everything else = construction code; it must not mention the field.
        hits = [m.start() for m in re.finditer(r"construction_tier", src)]
        # allowed region = the HarnessConfig dataclass through its
        # __post_init__ end; conservatively: every hit must be within the
        # first occurrence's class. Simplest robust check: the only
        # functions referencing it are NONE of the _global_top_n_/
        # _cap_aware* construction helpers.
        for fn_name in ("_global_top_n_signals", "_cap_aware_signals",
                        "_cap_aware_cross_asset_signals"):
            fn = getattr(ce, fn_name, None)
            if fn is not None:
                assert "construction_tier" not in inspect.getsource(fn), (
                    f"{fn_name} references construction_tier — R1 must be "
                    f"a pure no-op scaffold (T1 wiring is R2)")
