"""P4-A1 — `--universe` flag complete-entrypoint enumeration (PRD §6.2 / §B6).

PRD-audit 2026-05-16 finding + **user directional override 2026-05-16**:
the original folded operator decision left production entrypoints
resolver-free; the user overrode it — production mining/screen/xgb
entrypoints MUST also expose `--universe`. This test now pins the full
§6.2 enumeration: every listed entrypoint carries
`--universe {executable|expanded_v1}` and routes the flag to the
canonical resolver for the expanded branch, while the `executable`
default keeps the pre-Phase-4 derivation byte-for-byte unchanged
(D6 / P4-A2, verified separately in the audit memo §4 + §11).

See docs/memos/20260516-chart_structure_prd_audit.md §4/§11.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_PROJ = Path(__file__).resolve().parents[3]

# §6.2 complete entrypoint enumeration — ALL must carry --universe.
_ALL_ENTRYPOINTS = [
    # chart-structure research scripts
    "dev/scripts/chart_structure/phase2a_incremental_ic.py",
    "dev/scripts/chart_structure/phase3_run_3a_attempt.py",
    "dev/scripts/chart_structure/phase3_run_3b_attempt.py",
    "dev/scripts/chart_structure/phase3_run_3c_attempt.py",
    # production mining / screen / xgb entrypoints (user override 2026-05-16)
    "scripts/run_research_miner.py",
    "scripts/run_factor_screen.py",
    "scripts/run_xgb_importance.py",
]


@pytest.mark.parametrize("rel", _ALL_ENTRYPOINTS)
def test_entrypoint_exposes_universe_flag(rel):
    p = _PROJ / rel
    assert p.exists(), f"{rel} missing"
    src = p.read_text()
    assert 'add_argument("--universe"' in src, f"{rel}: missing --universe flag"
    assert ('choices=["executable", "expanded_v1", "expanded_v2"]' in src
            or 'choices=["executable", "expanded_v1"]' in src), \
        f"{rel}: --universe must restrict to executable|expanded_v1[|_v2]"
    assert "default=\"executable\"" in src or "default='executable'" in src, \
        f"{rel}: --universe must default to executable (D6/P4-A2)"
    assert "from core.universe.universe_resolver import resolve_universe" in src, \
        f"{rel}: must import the canonical resolver"
    # the flag value must actually gate resolution (research scripts pass
    # resolve_universe(args.universe); production scripts branch on
    # args.universe / universe_name and call resolve_universe('expanded_v1')).
    flows = ("args.universe" in src) or ("universe_name" in src)
    assert flows, f"{rel}: --universe value must flow to universe resolution"


def test_production_executable_default_is_byte_identical_derivation():
    """D6/P4-A2 contract: production scripts' executable branch must keep
    the original cfg.universe-derived `all_syms` derivation (the seed_pool
    + sector_etfs + factor_etfs + cross_asset dict.fromkeys union) under an
    `else:` — i.e. the default path is unchanged code, not rerouted through
    resolve_universe (which would silently change 81→79)."""
    for rel in ("scripts/run_research_miner.py",
                "scripts/run_factor_screen.py",
                "scripts/run_xgb_importance.py"):
        src = (_PROJ / rel).read_text()
        assert "list(uni.seed_pool)" in src and "list(uni.sector_etfs)" in src, \
            f"{rel}: original cfg.universe derivation must remain"
        assert 'if args.universe == "expanded_v1"' in src or \
               'if universe_name == "expanded_v1"' in src, \
            f"{rel}: expanded must be the explicit branch, executable the default else"
