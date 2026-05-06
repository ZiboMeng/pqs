"""PRD-E v1.1 §4.4 ASSET_CLASS_BY_CLUSTER → equal-weight target_wts builder.

Given a regime label series + rule set + universe metadata, builds the
daily target_wts panel (date × symbol) the TAA harness feeds into the
BacktestEngine. Within each asset class, weights are equal-weight across
the symbols mapped to that class via ``risk_cluster_map``.

PRD references:
  * §4.3 ASSET_CLASS_BY_CLUSTER mapping (equities / bonds / commodities /
    cash_anchor)
  * §4.4 within-class equal-weight (no factor-driven differentiation
    inside an asset class — TAA is top-down by design)
  * §4.6 OOS discipline: target_wts uses ONLY the regime label
    observable at the rebalance day, no future windows
"""

from __future__ import annotations

from typing import Dict, Mapping, Sequence

import pandas as pd

from core.regime.regime_detector import RegimeState
from core.research.risk_cluster_map import (
    ASSET_CLASS_BY_CLUSTER,
    get_asset_class,
)
from core.research.taa.regime_rules import (
    RegimeAllocation,
    VALID_ASSET_CLASSES,
    validate_rule_set,
)


def build_class_to_symbols(
    universe: Sequence[str],
    *,
    asset_class_lookup=None,
) -> Dict[str, list]:
    """Group universe symbols by asset class.

    Parameters
    ----------
    universe : Sequence[str]
        Tradable universe (excludes SPY/QQQ benchmarks; the TAA harness
        uses universe symbols for execution and benchmarks for diagnostics).
    asset_class_lookup : callable[str, str], optional
        Symbol → asset_class mapper. None uses the default
        ``risk_cluster_map.get_asset_class`` (unified stocks +
        cross-asset map). Pass an explicit callable for custom universes.

    Returns
    -------
    Dict[str, list]
        ``{asset_class_str: [sym, sym, ...]}``. Asset classes with no
        mapped symbols in the universe are present with an empty list.
    """
    out: Dict[str, list] = {ac: [] for ac in VALID_ASSET_CLASSES}
    if asset_class_lookup is None:
        def lookup(sym: str) -> str:
            try:
                return get_asset_class(sym)
            except KeyError:
                # Unmapped symbol — silently fall back to equities
                # (consistent with classify_cross_asset_spec convention)
                return "equities"
        asset_class_lookup = lookup
    for sym in universe:
        ac = asset_class_lookup(sym)
        if ac in out:
            out[ac].append(sym)
        # else: skip unrecognized asset class (defensive; should not
        # happen with the default lookup)
    return out


def build_target_weights_for_regime(
    allocation: RegimeAllocation,
    class_to_symbols: Mapping[str, Sequence[str]],
) -> Dict[str, float]:
    """Convert a single ``RegimeAllocation`` to per-symbol target weights
    via within-class equal-weighting.

    Returns
    -------
    Dict[str, float]
        ``{symbol: weight}`` summing to 1.0 (within float tolerance).
        Asset classes with 0% allocation contribute 0 symbols. Asset
        classes with > 0% allocation but EMPTY symbol list raise — the
        portfolio cannot allocate to a class with no symbols (caller
        should pre-validate the universe covers all non-zero classes).
    """
    weights: Dict[str, float] = {}
    for ac, pct in allocation.to_dict().items():
        syms = list(class_to_symbols.get(ac, []))
        if pct <= 0.0:
            continue
        if not syms:
            raise ValueError(
                f"regime={allocation.regime.value} allocation has "
                f"{ac}_pct={pct} but universe has no {ac!r} symbols; "
                f"either expand universe or use a rule set with "
                f"{ac}_pct=0.0"
            )
        per_sym = pct / len(syms)
        for sym in syms:
            weights[sym] = weights.get(sym, 0.0) + per_sym
    return weights


def build_target_wts_panel(
    regime_labels: pd.Series,
    rule_set: Mapping[RegimeState, RegimeAllocation],
    universe: Sequence[str],
    *,
    asset_class_lookup=None,
) -> pd.DataFrame:
    """Build the full date × symbol target_wts panel for the TAA backtest.

    Parameters
    ----------
    regime_labels : pd.Series
        Output of ``monthly_regime_labels`` (or daily variant). Index =
        rebalance dates; values = RegimeState string values. Each row
        becomes a target_wts row.
    rule_set : Mapping[RegimeState, RegimeAllocation]
        Active rule set (DEFAULT_TAA_RULES_V1 / V0_MINIMAL / etc.).
        Validated via ``validate_rule_set`` before iteration.
    universe : Sequence[str]
        All tradable symbols in scope. Symbols not represented in any
        regime's allocation contribute zero throughout (still appear as
        a column for harness alignment).
    asset_class_lookup : callable, optional
        Symbol → asset class mapper (passed to ``build_class_to_symbols``).

    Returns
    -------
    pd.DataFrame
        Indexed by ``regime_labels.index``, columns = sorted ``universe``,
        values = target weights in [0, 1]. Each row sums to 1.0 within
        float tolerance.
    """
    validate_rule_set(rule_set)
    class_to_symbols = build_class_to_symbols(
        universe, asset_class_lookup=asset_class_lookup,
    )
    cols = sorted(universe)
    rows = []
    for date, label in regime_labels.items():
        # Look up enum from string value
        try:
            regime = RegimeState(label)
        except ValueError:
            raise ValueError(
                f"regime label at {date} = {label!r} not a valid "
                f"RegimeState enum value"
            )
        if regime not in rule_set:
            raise KeyError(
                f"rule_set missing regime {regime.value!r} required at {date}"
            )
        weights = build_target_weights_for_regime(
            rule_set[regime], class_to_symbols,
        )
        # Pad to full universe + sort columns
        row = {sym: weights.get(sym, 0.0) for sym in cols}
        rows.append(row)
    return pd.DataFrame(rows, index=regime_labels.index, columns=cols)
