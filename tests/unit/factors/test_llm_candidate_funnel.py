"""Round 10 Topic J (2026-04-20): LLM candidate funnel tests.

Scaffold for the auto-launch LLM factor mining phase (see
`docs/20260420-prd_llm_factor_mining.md`). Tests validate:

  1. YAML schema round-trip + required-field enforcement
  2. Namespace hygiene: candidates can't shadow PRODUCTION_FACTORS or
     RESEARCH_FACTORS names
  3. Leakage heuristic catches lookahead keywords + missing lag
  4. Dedup flags high rank-correlation with existing factors
  5. Funnel never auto-KEEPs (always routes strong candidates to
     NEEDS_HUMAN_REVIEW per PRD §2.2 "LLM is not the final judge")
  6. Funnel rejects compute_fn crashes and empty outputs
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from core.factors.llm_candidate import (
    CandidateValidationError,
    CandidateVerdict,
    FactorCandidate,
    dedup_check,
    leakage_heuristic_check,
    load_candidate_from_dict,
    load_candidate_from_yaml,
    run_funnel,
)


def _minimal_valid_dict():
    return {
        "factor_name": "llm_novel_vol_regime_v1",
        "hypothesis": "High realized vol in mean-reverting regime predicts "
                       "21d outperformance",
        "formula": "daily_ret.rolling(21).std() * sign(spy_trend.shift(1))",
        "required_fields": ["close"],
        "suitable_horizon": ["21d"],
        "suitable_universe": "SPY + Mag7",
        "suitable_regime": ["NEUTRAL"],
        "expected_edge": "IC ~0.05",
        "expected_risk": "Cost-sensitive on intraday noise",
        "possible_failure_modes": ["high_turnover"],
        "novelty_vs_existing_factors": "Combines vol with sign(trend)",
    }


class TestSchemaValidation:

    def test_valid_dict_loads(self):
        cand = load_candidate_from_dict(_minimal_valid_dict())
        assert cand.factor_name == "llm_novel_vol_regime_v1"
        assert cand.compute_fn_path is None

    def test_missing_required_raises(self):
        bad = _minimal_valid_dict()
        del bad["hypothesis"]
        with pytest.raises(CandidateValidationError, match="hypothesis"):
            load_candidate_from_dict(bad)

    def test_empty_required_raises(self):
        bad = _minimal_valid_dict()
        bad["formula"] = ""
        with pytest.raises(CandidateValidationError, match="formula"):
            load_candidate_from_dict(bad)

    def test_production_namespace_collision_rejected(self):
        bad = _minimal_valid_dict()
        bad["factor_name"] = "low_vol"  # already in PRODUCTION_FACTORS
        with pytest.raises(CandidateValidationError,
                           match="PRODUCTION_FACTORS"):
            load_candidate_from_dict(bad)

    def test_research_namespace_collision_rejected(self):
        bad = _minimal_valid_dict()
        bad["factor_name"] = "vol_63d"  # in RESEARCH_FACTORS
        with pytest.raises(CandidateValidationError,
                           match="RESEARCH_FACTORS"):
            load_candidate_from_dict(bad)


class TestYAMLRoundtrip:

    def test_yaml_file_load(self, tmp_path):
        path = tmp_path / "cand.yaml"
        path.write_text(yaml.safe_dump(_minimal_valid_dict()))
        cand = load_candidate_from_yaml(path)
        assert cand.factor_name == "llm_novel_vol_regime_v1"

    def test_to_yaml_roundtrip(self, tmp_path):
        cand1 = load_candidate_from_dict(_minimal_valid_dict())
        path = tmp_path / "out.yaml"
        path.write_text(cand1.to_yaml())
        cand2 = load_candidate_from_yaml(path)
        assert cand1.factor_name == cand2.factor_name
        assert cand1.hypothesis == cand2.hypothesis
        assert cand1.formula == cand2.formula


class TestLeakageHeuristic:

    def test_lookahead_keyword_flagged(self):
        cand = load_candidate_from_dict(_minimal_valid_dict())
        cand.formula = "uses future close to predict return"
        issues = leakage_heuristic_check(cand)
        assert any("future" in msg for msg in issues)

    def test_missing_lag_keyword_flagged(self):
        cand = load_candidate_from_dict({
            "factor_name": "no_lag_factor",
            "hypothesis": "raw price magnitude predicts",
            "formula": "price_df / 100.0",  # no shift/lag/rolling
        })
        issues = leakage_heuristic_check(cand)
        assert any("lag" in msg or "shift" in msg for msg in issues)

    def test_clean_candidate_no_issues(self):
        cand = load_candidate_from_dict(_minimal_valid_dict())
        issues = leakage_heuristic_check(cand)
        assert issues == []


class TestDedupCheck:

    def _mkdf(self, seed=0):
        np.random.seed(seed)
        idx = pd.date_range("2024-01-01", periods=100)
        syms = ["A", "B", "C", "D"]
        return pd.DataFrame(
            np.random.randn(100, 4), index=idx, columns=syms,
        )

    def test_identical_values_flagged(self):
        cand = self._mkdf(seed=7)
        # Existing factor is the SAME df
        flagged = dedup_check(cand, {"shadow": cand}, corr_threshold=0.7)
        assert len(flagged) == 1
        name, rho = flagged[0]
        assert name == "shadow"
        assert abs(rho - 1.0) < 0.01

    def test_uncorrelated_not_flagged(self):
        cand = self._mkdf(seed=1)
        other = self._mkdf(seed=99)
        flagged = dedup_check(cand, {"other": other}, corr_threshold=0.7)
        assert flagged == []  # uncorrelated random

    def test_empty_existing_factor_skipped(self):
        cand = self._mkdf(seed=3)
        flagged = dedup_check(cand, {"empty": pd.DataFrame()})
        assert flagged == []


class TestRunFunnel:

    def _cand(self):
        return load_candidate_from_dict(_minimal_valid_dict())

    def test_leakage_triggers_reject(self):
        c = self._cand()
        c.formula = "use future close tomorrow"
        v = run_funnel(c)
        assert v.verdict == "REJECT"
        assert "leakage" in v.reason.lower()

    def test_no_compute_fn_returns_needs_human_review(self):
        c = self._cand()
        v = run_funnel(c)
        assert v.verdict == "NEEDS_HUMAN_REVIEW"
        assert "compute_fn" in v.reason.lower() or "implement" in v.reason.lower()

    def test_compute_fn_crash_returns_reject(self):
        c = self._cand()
        def _boom(price_df):
            raise RuntimeError("compute broken")
        price_df = pd.DataFrame(
            100 + np.cumsum(np.random.randn(200, 4) * 0.5, axis=0),
            index=pd.bdate_range("2024-01-02", periods=200),
            columns=["A", "B", "C", "D"],
        )
        v = run_funnel(c, compute_fn=_boom, price_df=price_df)
        assert v.verdict == "REJECT"
        assert "compute_fn raised" in v.reason

    def test_empty_output_rejected(self):
        c = self._cand()
        def _empty(price_df):
            return pd.DataFrame()
        price_df = pd.DataFrame(
            100.0, index=pd.bdate_range("2024-01-02", periods=100),
            columns=["A", "B"],
        )
        v = run_funnel(c, compute_fn=_empty, price_df=price_df)
        assert v.verdict == "REJECT"

    def test_strong_candidate_goes_to_review_not_keep(self):
        """Per PRD §2.2, even strong IC must route to human review.
        Funnel must never output 'KEEP'."""
        c = self._cand()
        np.random.seed(42)

        # Synthesize a factor that truly predicts fwd return
        price_df = pd.DataFrame(
            100.0, index=pd.bdate_range("2024-01-02", periods=300),
            columns=["A", "B", "C", "D", "E", "F"],
        )
        # Add some random walk
        rets = np.random.randn(300, 6) * 0.01
        for i in range(1, 300):
            price_df.iloc[i] = price_df.iloc[i-1] * (1 + rets[i])

        def _pseudo_factor(price_df):
            # Factor = shifted fwd return (proxy for "works on train")
            return price_df.pct_change(21).shift(-21) * 0.5 + \
                   np.random.randn(*price_df.shape) * 0.01

        v = run_funnel(c, compute_fn=_pseudo_factor, price_df=price_df)
        # Even if IC is huge, verdict is NEVER "KEEP"
        assert v.verdict != "KEEP"
        assert v.verdict in ("NEEDS_HUMAN_REVIEW", "ARCHIVE", "REJECT")

    def test_weak_candidate_goes_to_archive(self):
        c = self._cand()
        np.random.seed(42)
        price_df = pd.DataFrame(
            100.0, index=pd.bdate_range("2024-01-02", periods=300),
            columns=["A", "B", "C", "D", "E", "F"],
        )
        rets = np.random.randn(300, 6) * 0.01
        for i in range(1, 300):
            price_df.iloc[i] = price_df.iloc[i-1] * (1 + rets[i])

        def _noise(price_df):
            # Pure noise — no predictive relationship
            return pd.DataFrame(
                np.random.randn(*price_df.shape),
                index=price_df.index, columns=price_df.columns,
            )

        v = run_funnel(c, compute_fn=_noise, price_df=price_df)
        # Noise → low IC → ARCHIVE
        assert v.verdict == "ARCHIVE"
