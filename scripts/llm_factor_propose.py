#!/usr/bin/env python3
"""
scripts/llm_factor_propose.py — Round 10 Topic J (2026-04-20):
scaffold CLI for LLM-proposed factor candidates.

Takes a YAML candidate (per `docs/20260420-prd_llm_factor_mining.md` §4 schema)
and runs it through the candidate funnel:

  load YAML → shape validation → leakage heuristic → (optional)
  dedup vs existing factors → (optional) IC screen → verdict

This script does NOT call any LLM. It's the validation layer for
candidates produced by an LLM (or a human emulating one). The actual
LLM proposal flow happens in the auto-launch phase (see
`docs/20260420-prd_llm_factor_mining.md`).

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


def _load_price_and_factors(cfg, n_symbols: int = 15):
    """Minimal universe + factor snapshot for dedup + IC.

    PRD 20260423 R16: now loads OHLCV (not just close) and passes
    open_df / high_df / low_df / volume_df to generate_all_factors so
    candidates requiring these inputs (hl_range, overnight_ret_1d,
    intraday_ret_1d, dollar_vol_20d, and LLM candidates that reference
    OHLC like close_to_high_proximity_21d / intraday_support_21d /
    range_compression_5_63 / xsec_volume_surge_5d) can be properly
    funneled. Discovered R15 4 candidates archived due to this gap.

    PRD 20260423 R25: `n_symbols` parameter lets callers widen the
    universe beyond the default top-15. R24 discovered that cross-
    sectional signals (e.g. quality-gated reversal) under-perform on
    a 15-symbol panel compared to the 79-symbol expanded universe.
    Use `--universe-size full` to load the whole expanded set.
    """
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))
    uni = cfg.universe
    all_syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs) +
        list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    symbols = [s for s in all_syms
               if s not in uni.blacklist and s not in uni.macro_reference]
    # Use up to n_symbols. For wide cross-sectional signals set n_symbols
    # = len(symbols) via --universe-size full.
    closes, opens, highs, lows, volumes = {}, {}, {}, {}, {}
    for s in symbols[:n_symbols]:
        df = store.read(s, "1d")
        if df is None or df.empty or "close" not in df.columns:
            continue
        closes[s] = df["close"]
        if "open" in df.columns:
            opens[s] = df["open"]
        if "high" in df.columns:
            highs[s] = df["high"]
        if "low" in df.columns:
            lows[s] = df["low"]
        if "volume" in df.columns:
            volumes[s] = df["volume"]
    price_df = pd.DataFrame(closes).sort_index()
    price_df = price_df.loc[price_df.index >= "2022-01-01"]
    open_df = pd.DataFrame(opens).reindex_like(price_df) if opens else None
    high_df = pd.DataFrame(highs).reindex_like(price_df) if highs else None
    low_df = pd.DataFrame(lows).reindex_like(price_df) if lows else None
    volume_df = pd.DataFrame(volumes).reindex_like(price_df) if volumes else None
    factors = generate_all_factors(
        price_df,
        volume_df=volume_df,
        open_df=open_df,
        high_df=high_df,
        low_df=low_df,
    )
    return price_df, factors, {
        "open_df": open_df, "high_df": high_df,
        "low_df": low_df, "volume_df": volume_df,
    }


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
    parser.add_argument("--universe-size", default="15",
                        help="Number of symbols to load for IC screen "
                             "(int, or 'full' for the complete expanded "
                             "universe). Default 15 for fast dedup. "
                             "Use 'full' for cross-sectional candidates "
                             "per PRD R25 finding.")
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

    price_df, existing, extra_panels = None, None, {}
    if compute_fn is not None and not args.skip_data:
        cfg = load_config(Path(args.config_dir))
        if args.universe_size == "full":
            n_syms = 10_000  # effectively the whole universe
        else:
            try:
                n_syms = int(args.universe_size)
            except ValueError:
                raise SystemExit(
                    f"--universe-size must be int or 'full', got {args.universe_size!r}"
                )
        price_df, existing, extra_panels = _load_price_and_factors(cfg, n_symbols=n_syms)
        n_extra = sum(1 for v in extra_panels.values() if v is not None)
        logger.info(
            "Data loaded: price_df %s, %d existing factors, %d extra panels",
            price_df.shape, len(existing), n_extra,
        )

    # Inspect compute_fn signature to see if it accepts OHLCV kwargs. The
    # older LLM-candidate convention was compute_fn(price_df, vol_df=None,
    # regime=None, **kwargs). New candidates that need OHLC read them out
    # of **kwargs (e.g. kwargs.get("open_df")). Pass all extra panels as
    # kwargs so both conventions work.
    fn_kwargs = {k: v for k, v in extra_panels.items() if v is not None}
    if fn_kwargs and compute_fn is not None:
        # Wrap compute_fn so run_funnel's simple signature still works
        _orig_fn = compute_fn
        def _wrapped(*args, **kwargs):
            merged = {**fn_kwargs, **kwargs}
            return _orig_fn(*args, **merged)
        compute_fn_wrapped = _wrapped
    else:
        compute_fn_wrapped = compute_fn

    verdict = run_funnel(
        cand,
        compute_fn=compute_fn_wrapped,
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
