"""PRD-3 RB1 — component-B prerequisite gate (TDD).

build / 🛑 gated. AC: refuse/raise when prerequisites not met
(gated-off evidence); explicit STATUS report; naive intraday
archetypes refused upstream of any B impl.
"""
import pytest

from core.research.component_b_gate import (
    DIFFERENTIATED_ARCHETYPES,
    NAIVE_ARCHETYPES,
    GateStatus,
    assert_archetype_differentiated,
    assert_component_b_prerequisites,
    b_gate_status,
)


class TestPrerequisiteGate:
    def test_status_all_four_keys_present(self):
        s = b_gate_status()
        assert isinstance(s, GateStatus)
        for k in ("prd1_leakage_correct", "prd2_p2_3_executed",
                  "r11_intraday_cost_hardened", "ra7_r6_expanded_guard"):
            assert hasattr(s, k)

    def test_all_prereqs_currently_met(self):
        # Per ledger R42: PRD-1 ✅, PRD-2 R1-R14 ✅ (P2.3 EXECUTED),
        # R11 ✅ (sensitivity_multiplier), RA7 ✅ (R6 guard).
        s = b_gate_status()
        assert s.all_met, f"prereqs missing: {s.missing}"
        assert s.prd1_leakage_correct
        assert s.prd2_p2_3_executed
        assert s.r11_intraday_cost_hardened
        assert s.ra7_r6_expanded_guard

    def test_assert_passes_when_all_met(self):
        st = assert_component_b_prerequisites()
        assert isinstance(st, GateStatus) and st.all_met

    def test_assert_raises_specific_runtimeerror_when_missing(
        self, monkeypatch
    ):
        # simulate a prereq breaking: patch _probe_imports so one
        # prereq returns False → assert_component_b_prerequisites
        # raises a SPECIFIC RuntimeError listing the missing item.
        import core.research.component_b_gate as cbg

        def _broken():
            return {"prd1_leakage_correct": False,
                    "prd2_p2_3_executed": True,
                    "r11_intraday_cost_hardened": True,
                    "ra7_r6_expanded_guard": True}

        monkeypatch.setattr(cbg, "_probe_imports", _broken)
        with pytest.raises(RuntimeError, match=r"missing.*prd1"):
            assert_component_b_prerequisites()


class TestNaiveArchetypeRefuser:
    @pytest.mark.parametrize("a", sorted(NAIVE_ARCHETYPES))
    def test_naive_archetypes_refused(self, a):
        with pytest.raises(ValueError, match=r"NAIVE|老路子|naive"):
            assert_archetype_differentiated(a)

    @pytest.mark.parametrize("a", sorted(DIFFERENTIATED_ARCHETYPES))
    def test_differentiated_archetypes_accepted(self, a):
        assert_archetype_differentiated(a)            # no raise

    def test_case_insensitive_naive_match(self):
        with pytest.raises(ValueError, match=r"NAIVE|老路子|naive"):
            assert_archetype_differentiated("Bar_Direction_Voting")

    def test_unknown_archetype_raises(self):
        with pytest.raises(ValueError, match=r"unknown"):
            assert_archetype_differentiated("magic_alpha")
