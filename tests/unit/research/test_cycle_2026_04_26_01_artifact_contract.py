"""Pin the on-disk artifact contract for cycle 2026-04-26-01.

Codex Round 2 audit (`docs/claude_review_loop.md`) set an explicit
acceptance bar that the canonical YAML / closeout JSON / closeout memo
must not retain `S1_nominee`, `S1_RESEARCH_CANDIDATE`, or
`pending_closeout_eval` semantics anywhere in their text — historical
references included. These tests pin that contract so a future edit
that re-introduces those tokens (e.g. someone naively pasting back
the original header) fails CI.
"""
from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
CYCLE = "research-cycle-2026-04-26-01"

CANONICAL_YAML = (
    ROOT / "data" / "research_candidates" / f"{CYCLE}_top_trial_rejected_at_g2a.yaml"
)
CLOSEOUT_JSON = (
    ROOT / "data" / "research_candidates" / f"{CYCLE}_closeout_eval.json"
)
CLOSEOUT_MEMO = (
    ROOT / "docs" / "memos" / "20260426-research-cycle-2026-04-26-01_close.md"
)

FORBIDDEN_TOKENS = ("S1_nominee", "S1_RESEARCH_CANDIDATE", "pending_closeout_eval")


@pytest.mark.parametrize(
    "path",
    [CANONICAL_YAML, CLOSEOUT_JSON, CLOSEOUT_MEMO],
    ids=["canonical_yaml", "closeout_json", "closeout_memo"],
)
def test_cycle_artifact_has_no_forbidden_tokens(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    hits = [tok for tok in FORBIDDEN_TOKENS if tok in text]
    assert not hits, (
        f"{path.name} contains forbidden tokens {hits} — Codex Round 2 "
        f"acceptance bar requires no remaining S1/pending semantics, "
        f"including in historical-explanation prose."
    )


def test_canonical_yaml_candidate_id_is_rejected_form() -> None:
    import yaml as yaml_module

    spec = yaml_module.safe_load(CANONICAL_YAML.read_text(encoding="utf-8"))
    assert spec["candidate_id"] == f"{CYCLE}_top_trial_rejected_at_g2a"


def test_closeout_json_candidate_id_is_rejected_form() -> None:
    import json

    payload = json.loads(CLOSEOUT_JSON.read_text(encoding="utf-8"))
    assert payload["candidate_id"] == f"{CYCLE}_top_trial_rejected_at_g2a"


def test_canonical_yaml_acceptance_decision_is_rejected_at_g2a() -> None:
    import yaml as yaml_module

    spec = yaml_module.safe_load(CANONICAL_YAML.read_text(encoding="utf-8"))
    assert spec["acceptance_decision"] == "rejected_at_g2a_watchlist_total_share"


def test_canonical_yaml_summaries_are_finalized_not_placeholders() -> None:
    """The four closeout summaries must hold real values, not placeholder strings."""
    import yaml as yaml_module

    spec = yaml_module.safe_load(CANONICAL_YAML.read_text(encoding="utf-8"))
    for key in (
        "benchmark_relative_summary",
        "oos_holdout_summary",
        "robustness_summary",
    ):
        value = spec[key]
        assert isinstance(value, dict), f"{key} must be a finalized dict, got {type(value).__name__}"
        # Defensive: no nested string with the placeholder marker either.
        flat = repr(value)
        assert "pending_closeout_eval" not in flat, (
            f"{key} contains a residual `pending_closeout_eval` placeholder."
        )
