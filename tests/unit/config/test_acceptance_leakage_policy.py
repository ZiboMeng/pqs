"""PRD-1 P1.2b — acceptance.yaml leakage_correct contract switch (TDD).

This is the CONTRACT SURFACE only (default-on + legacy escape hatch).
Per PRD-1 §2 / cross-audit §C it governs the probe-fit/sample layer;
it does NOT touch cpcv_acceptance §3 fold-aggregation size-weighting.
"""
from pathlib import Path

import pytest

from core.config.schemas.acceptance import (
    AcceptanceThresholds,
    LeakageCorrectPolicy,
)


class TestLeakageCorrectPolicyDefaults:
    def test_default_is_leakage_correct_on(self):
        p = LeakageCorrectPolicy()
        assert p.enabled is True
        assert p.sample_uniqueness is True
        assert p.purge_embargo is True
        assert p.embargo == 5
        assert p.legacy_no_leakage_corr is False

    def test_effective_default(self):
        eff = LeakageCorrectPolicy().effective()
        assert eff == {"sample_uniqueness": True, "purge_embargo": True,
                       "embargo": 5}

    def test_legacy_escape_hatch_forces_both_off(self):
        eff = LeakageCorrectPolicy(legacy_no_leakage_corr=True).effective()
        assert eff["sample_uniqueness"] is False
        assert eff["purge_embargo"] is False

    def test_enabled_false_gates_both_off(self):
        eff = LeakageCorrectPolicy(enabled=False).effective()
        assert eff["sample_uniqueness"] is False
        assert eff["purge_embargo"] is False

    def test_granular_single_leg_off(self):
        eff = LeakageCorrectPolicy(purge_embargo=False).effective()
        assert eff == {"sample_uniqueness": True, "purge_embargo": False,
                       "embargo": 5}

    def test_extra_key_forbidden(self):
        with pytest.raises(Exception):
            LeakageCorrectPolicy(bogus=1)

    def test_embargo_non_negative(self):
        with pytest.raises(Exception):
            LeakageCorrectPolicy(embargo=-1)


class TestWiredIntoAcceptanceThresholds:
    def test_acceptance_has_leakage_correct_default(self):
        a = AcceptanceThresholds()
        assert isinstance(a.leakage_correct, LeakageCorrectPolicy)
        assert a.leakage_correct.effective()["sample_uniqueness"] is True

    def test_loads_from_config_yaml(self):
        from core.config.loader import load_config
        cfg = load_config(Path("config"))
        lc = cfg.acceptance.leakage_correct
        assert lc.enabled is True
        assert lc.effective() == {"sample_uniqueness": True,
                                  "purge_embargo": True, "embargo": 5}
