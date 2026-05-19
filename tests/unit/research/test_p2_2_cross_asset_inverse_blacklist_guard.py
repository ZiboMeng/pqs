"""PRD-2 P2.2 R6 — cross-asset universe SQQQ / leveraged-inverse
blacklist regression guard (TDD).

Grounded re-scope (honest, same pattern as R4): cap_aware_cross_asset
is ALREADY fully wired (composite_evaluator construction_mode +
asset_class_caps incl. inverse_equities; cycle06/08 use it) and the
SQQQ/leveraged-inverse reject is enforced at the T1 call-site
(construction_tiers._check_hedge_etf, tested). The genuinely-new R6
gap is a UNIVERSE/config-LAYER guard: a future edit to the
cross-asset universe must NOT be able to admit SQQQ or any leveraged
(-2x/-3x) inverse, and the T1-allowed 1x set must stay consistent
with the universe-declared 1x inverse (single SoT). This locks the
CLAUDE.md invariant at the config layer (the call-site guard alone
does not protect a universe yaml edit).
"""
from pathlib import Path

import pytest
import yaml

from core.research.construction_tiers import _VALID_1X_INVERSE

_PROJ = Path(__file__).resolve().parents[3]
# Representative leveraged-inverse tickers that must NEVER be tradeable.
_LEVERAGED_INVERSE = {
    "SQQQ", "SPXU", "SPXS", "SDS", "SOXS", "TZA", "SARK", "QID",
    "DXD", "SDOW", "TECS", "FAZ", "LABD", "DRV", "SRTY",
}


def _load(p):
    return yaml.safe_load((_PROJ / p).read_text())


class TestCrossAssetInverseBlacklistGuard:
    def test_priority5_inverse_all_1x_only(self):
        u5 = _load("config/universe_priority5.yaml")
        inv = u5["extensions"]["inverse_etfs_added"]
        assert len(inv) >= 3
        for e in inv:
            assert e["leverage"] == -1.0, (
                f"{e['sym']} leverage {e['leverage']} — only 1x inverse "
                f"allowed (CLAUDE.md invariant; no -2x/-3x)")
            assert e["sym"] not in _LEVERAGED_INVERSE

    def test_priority5_blacklists_sqqq(self):
        u5 = _load("config/universe_priority5.yaml")
        bl = {e["sym"] for e in u5["extensions"]["blacklist_preserved"]}
        assert "SQQQ" in bl

    def test_main_universe_blacklists_sqqq(self):
        u = _load("config/universe.yaml")
        assert "SQQQ" in set(u.get("blacklist", []))

    def test_no_leveraged_inverse_in_priority5_tradeable(self):
        u5 = _load("config/universe_priority5.yaml")
        ex = u5["extensions"]
        tradeable = {e["sym"] for e in ex["blue_chips_added"]} | {
            e["sym"] for e in ex["inverse_etfs_added"]}
        leaked = tradeable & _LEVERAGED_INVERSE
        assert not leaked, f"leveraged-inverse leaked into tradeable: {leaked}"

    def test_t1_allowed_set_consistent_with_universe_declared_1x(self):
        # single SoT: construction_tiers._VALID_1X_INVERSE must equal
        # the universe-declared 1x inverse set, so a universe edit and
        # the T1 guard can't silently diverge.
        u5 = _load("config/universe_priority5.yaml")
        uni_1x = {e["sym"] for e in u5["extensions"]["inverse_etfs_added"]}
        assert set(_VALID_1X_INVERSE) == uni_1x, (
            f"T1 allowed {set(_VALID_1X_INVERSE)} != universe-declared "
            f"1x {uni_1x} — keep them a single source of truth")

    def test_no_leveraged_inverse_can_pass_t1_guard(self):
        from core.research.construction_tiers import _check_hedge_etf
        for bad in sorted(_LEVERAGED_INVERSE):
            with pytest.raises(ValueError):
                _check_hedge_etf(bad)
