"""Production-side wrapper for applying cross-ticker DSL rules to a
strategy's date × symbol weight matrix.

PRD: docs/20260421-prd_framework_completion.md §11 M10

Design principle (per PRD §1.4 M4 acceptance):
  - Rules are OFF by default at the production wrapper level; only apply
    if config/cross_ticker_rules.yaml::enabled is true AND rules are non-empty
  - Long-only invariant enforced by rule engine; wrapper just verifies
    after-application sum is non-negative
  - Missing ohlcv for a symbol → rule fail-safe skips that rule
  - Wrapper is NO-OP when rules empty or disabled (backward compat)

Called from run_backtest.py and run_paper.py after PortfolioConstructor.build().
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from core.logging_setup import get_logger
from core.signals.cross_ticker_rules import (
    RuleContext,
    apply_rules,
    load_rules,
)

logger = get_logger(__name__)


def apply_rules_to_weight_matrix(
    weights: pd.DataFrame,
    regime: pd.Series,
    ohlcv_frames: Dict[str, pd.DataFrame],
    rules_path: str | Path = "config/cross_ticker_rules.yaml",
    ohlcv_tail: int = 252,
) -> tuple[pd.DataFrame, Dict[str, Any]]:
    """Apply cross-ticker DSL rules to a production weight matrix.

    Args:
        weights: date × symbol weight matrix from PortfolioConstructor
        regime: date → regime_label Series
        ohlcv_frames: dict of symbol → OHLCV DataFrame (used for DSL
                      condition evaluation; symbols not present in frames
                      won't have rules applied to them)
        rules_path: path to cross_ticker_rules.yaml
        ohlcv_tail: number of bars to slice per context (for speed)

    Returns:
        (adjusted_weights, stats_dict)

    Behavior:
        - If rules file missing / enabled=false / no rules → returns
          (weights, {"applied": False, "reason": ...}) unchanged
        - Otherwise iterates each date, builds RuleContext, applies rules,
          writes adjusted weights back. Logs INFO summary at end.
    """
    try:
        enabled, rules = load_rules(rules_path)
    except Exception as exc:
        logger.warning("Failed to load cross_ticker_rules: %s. NO-OP.", exc)
        return weights, {"applied": False, "error": str(exc)}

    if not enabled or not rules:
        return weights, {
            "applied": False,
            "reason": ("disabled in config" if not enabled
                       else "no rules defined"),
        }

    logger.info("Applying %d cross-ticker rule(s) to weight matrix (%d dates)...",
                len(rules), len(weights))

    adjusted = weights.copy()
    n_changed_rows = 0
    n_symbol_changes = 0

    for date in weights.index:
        if not isinstance(date, pd.Timestamp):
            continue
        # Build ohlcv context per date (tail-sliced for speed)
        ctx_ohlcv = {}
        for sym, df in ohlcv_frames.items():
            if df is None or df.empty:
                continue
            mask = df.index <= date
            if mask.any():
                ctx_ohlcv[sym] = df[mask].tail(ohlcv_tail)
        ctx = RuleContext(
            bar_timestamp=date,
            regime=str(regime.get(date, "NEUTRAL")) if regime is not None else "NEUTRAL",
            ohlcv=ctx_ohlcv,
        )
        # Filter to non-zero weights only (rule engine operates on dict)
        before = {s: float(weights.loc[date, s]) for s in weights.columns
                  if float(weights.loc[date, s]) != 0}
        after = apply_rules(before, ctx, rules)

        # Apply changes back
        row_changed = False
        for sym, new_w in after.items():
            if sym not in adjusted.columns:
                adjusted[sym] = 0.0
            old_w = float(adjusted.loc[date, sym]) if sym in adjusted.columns else 0.0
            if abs(new_w - old_w) > 1e-9:
                adjusted.loc[date, sym] = new_w
                row_changed = True
                n_symbol_changes += 1
        # Symbols dropped by override_strategy rules
        for sym in before:
            if sym not in after:
                adjusted.loc[date, sym] = 0.0
                row_changed = True
                n_symbol_changes += 1
        if row_changed:
            n_changed_rows += 1

    # Long-only invariant check after all rules applied
    neg_count = int((adjusted < 0).sum().sum())
    if neg_count > 0:
        logger.warning(
            "Cross-ticker wrapper: %d negative weight entries after rules; "
            "clipping to 0 (long-only invariant).",
            neg_count,
        )
        adjusted = adjusted.clip(lower=0.0)

    stats = {
        "applied": True,
        "n_rules": len(rules),
        "n_dates": len(weights),
        "n_dates_changed": n_changed_rows,
        "pct_dates_changed": n_changed_rows / max(1, len(weights)),
        "n_symbol_changes": n_symbol_changes,
    }
    logger.info(
        "Cross-ticker rules applied: %d/%d dates changed (%.1f%%), "
        "%d total symbol-weight changes",
        stats["n_dates_changed"], stats["n_dates"],
        stats["pct_dates_changed"] * 100, stats["n_symbol_changes"],
    )
    return adjusted, stats
