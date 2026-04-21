#!/usr/bin/env python3
"""
scripts/llm_factor_propose.py — Round 10 Topic J (2026-04-20):
scaffold CLI for LLM-proposed factor candidates.

Takes a YAML candidate (per `docs/prd_llm_factor_mining.md` §4 schema)
and runs it through the candidate funnel:

  load YAML → shape validation → leakage heuristic → (optional)
  dedup vs existing factors → (optional) IC screen → verdict

This script does NOT call any LLM. It's the validation layer for
candidates produced by an LLM (or a human emulating one). The actual
LLM proposal flow happens in the auto-launch phase (see
`docs/prd_llm_factor_mining.md`).

Usage
-----
    # Validate a candidate YAML file (no compute_fn → NEEDS_HUMAN_REVIEW)
    python scripts/llm_factor_propose.py --input my_candidate.yaml

    # Read from stdin
    cat my_candidate.yaml | python scripts/llm_factor_propose.py --input -

    # With compute_fn for dedup + IC (compute_fn_path = "module:func")
    python scripts/llm_factor_propose.py --input my_candidate.yaml \\
        --config-dir config

YAML schema (per PRD §4)
------------------------
    factor_name: "my_novel_factor"
    hypothesis: "Stocks with high X tend to outperform due to Y"
    formula: "daily_ret.rolling(21).std() * sign(pct_change(63))"
    required_fields: [close]
    suitable_horizon: [21d]
    suitable_universe: "SPY + Mag7"
    suitable_regime: [NEUTRAL, BULL]
    expected_edge: "IC ~0.05 on 21d horizon"
    expected_risk: "Drawdown-sensitive; fails in trend reversals"
    possible_failure_modes: [high_turnover, cost_sensitive]
    novelty_vs_existing_factors: "Combines low-vol with sign(momentum)"
    compute_fn_path: "my_module:compute_factor"  # optional
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dataclasses import asdict

import pandas as pd

from core.config.loader import load_config
from core.data.market_data_store import MarketDataStore
from core.factors.factor_generator import generate_all_factors
from core.factors.llm_candidate import (
    CandidateValidationError,
    FactorCandidate,
    load_candidate_from_yaml,
    run_funnel,
)
from core.logging_setup import setup_logging, get_logger

setup_logging()
logger = get_logger("llm_factor_propose")


def _resolve_compute_fn(path: str):
    """Parse 'module:function' spec and import."""
    if ":" not in path:
        raise ValueError(
            f"compute_fn_path must be 'module:function', got '{path}'"
        )
    module_name, func_name = path.split(":", 1)
    mod = importlib.import_module(module_name)
    return getattr(mod, func_name)


def _load_price_and_factors(cfg):
    """Minimal universe + factor snapshot for dedup + IC."""
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))
    uni = cfg.universe
    all_syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs) +
        list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    symbols = [s for s in all_syms
               if s not in uni.blacklist and s not in uni.macro_reference]
    # Just load the top-15 for a reasonable dedup reference. The LLM
    # auto-launch phase can expand this; scaffold keeps it fast.
    pf = {}
    for s in symbols[:15]:
        df = store.read(s, "1d")
        if df is not None and not df.empty and "close" in df.columns:
            pf[s] = df["close"]
    price_df = pd.DataFrame(pf).sort_index()
    price_df = price_df.loc[price_df.index >= "2022-01-01"]
    factors = generate_all_factors(price_df)
    return price_df, factors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True,
                        help="Path to candidate YAML (or '-' for stdin)")
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--skip-data", action="store_true",
                        help="Skip price_df + existing_factors loading "
                             "(shape + leakage check only; no dedup/IC)")
    parser.add_argument("--out-dir", default="data/ml/llm_candidates",
                        help="Where to write verdict JSON")
    args = parser.parse_args()

    # Load candidate
    try:
        if args.input == "-":
            import tempfile
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".yaml", delete=False
            ) as fh:
                fh.write(sys.stdin.read())
                tmp_path = fh.name
            cand = load_candidate_from_yaml(tmp_path)
        else:
            cand = load_candidate_from_yaml(args.input)
    except CandidateValidationError as exc:
        logger.error("Candidate validation FAILED: %s", exc)
        sys.exit(2)
    except Exception as exc:
        logger.error("Failed to load candidate: %s", exc)
        sys.exit(2)

    logger.info("Candidate loaded: %s", cand.factor_name)

    compute_fn = None
    if cand.compute_fn_path:
        try:
            compute_fn = _resolve_compute_fn(cand.compute_fn_path)
        except Exception as exc:
            logger.error("compute_fn_path resolution FAILED: %s", exc)
            sys.exit(2)

    price_df, existing = None, None
    if compute_fn is not None and not args.skip_data:
        cfg = load_config(Path(args.config_dir))
        price_df, existing = _load_price_and_factors(cfg)
        logger.info("Data loaded: price_df %s, %d existing factors",
                    price_df.shape, len(existing))

    verdict = run_funnel(
        cand,
        compute_fn=compute_fn,
        price_df=price_df,
        existing_factors=existing,
    )

    # Write verdict to disk
    out_dir = Path(args.out_dir) / cand.factor_name
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "candidate.yaml").write_text(cand.to_yaml())
    verdict_doc = {
        "verdict":         verdict.verdict,
        "reason":          verdict.reason,
        "leakage_issues":  verdict.leakage_issues,
        "dedup_matches":   [(n, round(r, 4)) for n, r in verdict.dedup_matches],
        "ic_stats":        verdict.ic_stats,
        "candidate":       asdict(cand),
    }
    (out_dir / "verdict.json").write_text(
        json.dumps(verdict_doc, indent=2, ensure_ascii=False)
    )

    # Pretty-print summary
    print()
    print("=" * 70)
    print(f"Factor candidate: {cand.factor_name}")
    print(f"Verdict:          {verdict.verdict}")
    print(f"Reason:           {verdict.reason}")
    if verdict.leakage_issues:
        print(f"Leakage issues:   {verdict.leakage_issues}")
    if verdict.dedup_matches:
        print("Dedup matches:")
        for name, rho in verdict.dedup_matches:
            print(f"  {name:<30} rho={rho:+.3f}")
    if verdict.ic_stats:
        print(f"IC stats:         {verdict.ic_stats}")
    print("=" * 70)
    print(f"Artifacts: {out_dir}")

    # Exit code reflects verdict (for CI / batch pipelines):
    #   0 = ARCHIVE or NEEDS_HUMAN_REVIEW (non-blocking outcome)
    #   3 = REJECT (the candidate should not be kept)
    if verdict.verdict == "REJECT":
        sys.exit(3)
    sys.exit(0)


if __name__ == "__main__":
    main()
