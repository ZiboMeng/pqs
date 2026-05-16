"""P4-A1 — `--universe` flag complete-entrypoint enumeration (PRD §6.2 / §B6).

PRD-audit 2026-05-16 finding: the main PRD §6.5 P4-A1 names this exact
test and §B6 requires a *complete* entrypoint enumeration; the Phase 4
closeout marked P4-A1 ✅ without it. This test encodes the audited,
honest contract (see docs/memos/20260516-chart_structure_prd_audit.md):

  * In-scope chart-structure research entrypoints MUST expose
    `--universe {executable|expanded_v1}` so the one un-falsified
    Phase-3-closeout opening ("re-check chart-native IC on expanded_v1")
    is reachable by flag.
  * Production mining/screen/xgb entrypoints INTENTIONALLY do NOT wire
    `resolve_universe` — they cannot load expanded_v1 at all, which is a
    *stronger* D6 isolation guarantee than a default-valued flag. This
    is a recorded, deliberate scope (operator decision, audit memo §4),
    not an omission, and is pinned here so the contract can't silently
    drift.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_PROJ = Path(__file__).resolve().parents[3]

# §6.2 entrypoints that MUST carry the --universe flag (chart-structure
# research scripts — where expanded_v1 is actually exercised).
_FLAGGED = [
    "dev/scripts/chart_structure/phase2a_incremental_ic.py",
    "dev/scripts/chart_structure/phase3_run_3a_attempt.py",
    "dev/scripts/chart_structure/phase3_run_3b_attempt.py",
    "dev/scripts/chart_structure/phase3_run_3c_attempt.py",
]

# §6.2-listed production entrypoints that, per audit-memo §4 operator
# decision, INTENTIONALLY stay resolver-free (conservative D6 isolation).
_INTENTIONALLY_RESOLVER_FREE = [
    "scripts/run_research_miner.py",
    "scripts/run_factor_screen.py",
    "scripts/run_xgb_importance.py",
]


@pytest.mark.parametrize("rel", _FLAGGED)
def test_research_entrypoint_exposes_universe_flag(rel):
    src = (_PROJ / rel).read_text()
    assert 'add_argument("--universe"' in src, f"{rel}: missing --universe flag"
    assert 'choices=["executable", "expanded_v1"]' in src, \
        f"{rel}: --universe must restrict to executable|expanded_v1"
    assert "from core.universe.universe_resolver import resolve_universe" in src, \
        f"{rel}: must import the canonical resolver"
    # the flag value must actually flow to the resolver (directly or via
    # a helper) — not a hardcoded resolve_universe(\"executable\").
    assert "args.universe" in src, \
        f"{rel}: --universe value must flow to resolution (found no args.universe use)"
    assert 'resolve_universe("executable")' not in src and \
           "resolve_universe('executable')" not in src, \
        f"{rel}: must not hardcode resolve_universe(\"executable\") — use the flag"


@pytest.mark.parametrize("rel", _INTENTIONALLY_RESOLVER_FREE)
def test_production_entrypoint_is_resolver_free_by_design(rel):
    p = _PROJ / rel
    if not p.exists():
        pytest.skip(f"{rel} not present")
    src = p.read_text()
    # Pinned invariant: these never import the resolver, so they
    # structurally cannot mine on expanded_v1 (stronger than a flag).
    assert "resolve_universe" not in src, (
        f"{rel} now references resolve_universe — the audit-memo §4 "
        f"conservative-isolation contract changed; update the audit memo "
        f"+ Phase 4 closeout P4-A1 before allowing this.")
