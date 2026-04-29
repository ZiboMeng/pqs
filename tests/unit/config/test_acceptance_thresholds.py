"""Unit tests for AcceptanceThresholds (Step 1 of threshold unification PRD).

Per PRD §6.1 of `docs/prd/20260428-acceptance_threshold_unification_prd.md`:
- (a) full-nested-yaml override loads correctly
- (b) partial-yaml override keeps other submodels at default
- (c) missing yaml falls back to schema defaults

After Step 1 these thresholds exist in config but no consumer reads them yet
(WindowAnalyzer / factor_evaluator wiring lands in Step 2 / Step 3).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from core.config.loader import load_config
from core.config.schemas import (
    AcceptanceThresholds,
    FactorTierThresholds,
    TierDThresholds,
    WalkForwardThresholds,
)


PROJECT_CONFIG_DIR = Path(__file__).parents[3] / "config"


# ── Schema-level defaults ─────────────────────────────────────────────────────


class TestAcceptanceThresholdsSchema:
    def test_defaults_match_documented_pre_relocation_values(self):
        thresholds = AcceptanceThresholds()
        assert thresholds.tier_d.min_excess_return_vs_spy == 0.05
        assert thresholds.tier_d.min_ir_vs_spy == 0.30
        assert thresholds.tier_d.max_dd_vs_spy_multiplier == 1.50
        assert thresholds.walk_forward.min_oos_vs_is_return_ratio == 0.50
        assert thresholds.walk_forward.min_windows_positive_excess_pct == 0.60
        assert thresholds.walk_forward.auto_fail_single_period_contribution == 0.50
        assert thresholds.walk_forward.auto_fail_single_asset_contribution == 0.40
        assert thresholds.walk_forward.auto_fail_crisis_vs_benchmark_multiplier == 2.0
        assert thresholds.walk_forward.max_crisis_drawdown_abs == 0.25
        assert thresholds.factor_tiers.s_min_ir == 0.80
        assert thresholds.factor_tiers.a_min_ir == 0.50
        assert thresholds.factor_tiers.b_min_ir == 0.30
        assert thresholds.factor_tiers.c_min_ir == 0.10

    def test_nested_construction_from_kwargs(self):
        thresholds = AcceptanceThresholds(
            tier_d=TierDThresholds(min_ir_vs_spy=0.55),
            factor_tiers=FactorTierThresholds(s_min_ir=0.95),
        )
        assert thresholds.tier_d.min_ir_vs_spy == 0.55
        assert thresholds.factor_tiers.s_min_ir == 0.95
        # Untouched submodel keeps defaults.
        assert thresholds.walk_forward.min_oos_vs_is_return_ratio == 0.50

    def test_extra_fields_rejected(self):
        # Codex round-13 §"Decision 1": one policy surface, no flat 12-field bag,
        # and no silent extra keys.
        import pydantic
        try:
            AcceptanceThresholds.model_validate({"tier_d": {"unknown_field": 1.0}})
        except pydantic.ValidationError:
            return
        raise AssertionError("Expected ValidationError on unknown field")


# ── Loader integration ───────────────────────────────────────────────────────


def _write_config_dir(tmp_path: Path, acceptance_yaml: str | None) -> Path:
    """Mirror the project's config/ into tmp_path, optionally overwriting acceptance.yaml.

    Passing ``acceptance_yaml=None`` removes the file entirely (test (c) case).
    """
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    for f in PROJECT_CONFIG_DIR.iterdir():
        if f.is_file() and f.suffix in {".yaml", ".yml"}:
            (cfg_dir / f.name).write_bytes(f.read_bytes())
    if acceptance_yaml is None:
        (cfg_dir / "acceptance.yaml").unlink()
    else:
        (cfg_dir / "acceptance.yaml").write_text(acceptance_yaml)
    return cfg_dir


class TestAcceptanceThresholdsLoader:
    def test_acceptance_thresholds_loads_from_yaml(self, tmp_path):
        """(a) Full nested override: every field replaced via yaml."""
        full_override = {
            "tier_d": {
                "min_excess_return_vs_spy": 0.07,
                "min_ir_vs_spy": 0.55,
                "max_dd_vs_spy_multiplier": 1.20,
            },
            "walk_forward": {
                "min_oos_vs_is_return_ratio": 0.65,
                "min_windows_positive_excess_pct": 0.75,
                "auto_fail_single_period_contribution": 0.40,
                "auto_fail_single_asset_contribution": 0.30,
                "auto_fail_crisis_vs_benchmark_multiplier": 2.5,
                "max_crisis_drawdown_abs": 0.20,
            },
            "factor_tiers": {
                "s_min_ir": 0.95,
                "a_min_ir": 0.70,
                "b_min_ir": 0.40,
                "c_min_ir": 0.15,
            },
        }
        cfg_dir = _write_config_dir(tmp_path, yaml.safe_dump(full_override))
        cfg = load_config(config_dir=cfg_dir)

        assert isinstance(cfg.acceptance, AcceptanceThresholds)
        assert cfg.acceptance.tier_d.min_ir_vs_spy == 0.55
        assert cfg.acceptance.tier_d.max_dd_vs_spy_multiplier == 1.20
        assert cfg.acceptance.walk_forward.min_windows_positive_excess_pct == 0.75
        assert cfg.acceptance.walk_forward.max_crisis_drawdown_abs == 0.20
        assert cfg.acceptance.factor_tiers.s_min_ir == 0.95
        assert cfg.acceptance.factor_tiers.c_min_ir == 0.15

    def test_acceptance_thresholds_partial_yaml(self, tmp_path):
        """(b) Partial override: only one submodel field changed; others stay default."""
        partial = {"tier_d": {"min_ir_vs_spy": 0.55}}
        cfg_dir = _write_config_dir(tmp_path, yaml.safe_dump(partial))
        cfg = load_config(config_dir=cfg_dir)

        # Overridden field reflects the yaml.
        assert cfg.acceptance.tier_d.min_ir_vs_spy == 0.55
        # Sibling fields in same submodel keep defaults.
        assert cfg.acceptance.tier_d.min_excess_return_vs_spy == 0.05
        assert cfg.acceptance.tier_d.max_dd_vs_spy_multiplier == 1.50
        # Other submodels untouched.
        assert isinstance(cfg.acceptance.walk_forward, WalkForwardThresholds)
        assert cfg.acceptance.walk_forward.min_oos_vs_is_return_ratio == 0.50
        assert isinstance(cfg.acceptance.factor_tiers, FactorTierThresholds)
        assert cfg.acceptance.factor_tiers.s_min_ir == 0.80

    def test_acceptance_thresholds_missing_yaml_falls_back_to_defaults(self, tmp_path):
        """(c) Absent yaml file: schema default_factory wins; no error."""
        cfg_dir = _write_config_dir(tmp_path, acceptance_yaml=None)
        cfg = load_config(config_dir=cfg_dir)

        assert isinstance(cfg.acceptance, AcceptanceThresholds)
        # Every nested default reproduced.
        assert cfg.acceptance.tier_d.min_ir_vs_spy == 0.30
        assert cfg.acceptance.walk_forward.max_crisis_drawdown_abs == 0.25
        assert cfg.acceptance.factor_tiers.s_min_ir == 0.80

    def test_project_config_acceptance_yaml_matches_schema_defaults(self):
        """Step-1 invariant: shipped config/acceptance.yaml MUST equal schema defaults.

        PRD §3.1 hard constraint: 'no numeric value changes' during the relocation.
        Reverse-validation cue: if anyone edits the yaml in this commit, this
        regression catches it.
        """
        cfg = load_config(config_dir=PROJECT_CONFIG_DIR)
        defaults = AcceptanceThresholds()
        assert cfg.acceptance.model_dump() == defaults.model_dump()
