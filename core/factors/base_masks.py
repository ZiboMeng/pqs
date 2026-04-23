"""Per-date-per-symbol research masks (PRD 20260423 Step 1 Round 5, §6.4).

Existing admission screen (`scripts/universe_admission_screen.py`) makes
binary per-symbol decisions at universe-refresh time. These masks
expose the SAME criteria as **per-date-per-symbol** boolean panels so
research scripts (IC screen, ML panel builder, label alignment) can
check "was symbol X tradable at date T?" without re-running admission.

Scope (PRD §3.3):
  - admission-style mask: price floor
  - tradability mask: rolling dollar volume threshold
  - combined research mask: admission AND tradable

Output: `pd.DataFrame` of bool, same shape/index/columns as input
`price_df`. NaN-safe: bars with NaN data produce False, not NaN.

No side effects on generator output. Masks are distinct objects from
factors; they don't go into `RESEARCH_FACTORS`.
"""

from __future__ import annotations

import pandas as pd

from core.factors.base_volatility import dollar_volume_ma


def price_floor_mask(
    price_df: pd.DataFrame, min_price: float = 5.0,
) -> pd.DataFrame:
    """Boolean panel: True where close >= min_price.

    Mirrors `scripts/universe_admission_screen._check_price_floor`
    semantics but applied per-date rather than once against a recent
    window. NaN close → False (non-tradable).

    Parameters
    ----------
    price_df  : close prices, index=date, columns=symbols
    min_price : USD floor (default 5.0, matches the admission extended
                tier; core tier uses 10.0)
    """
    if min_price < 0:
        raise ValueError(f"min_price must be >= 0, got {min_price}")
    return (price_df >= min_price).fillna(False)


def tradable_mask_dollar_vol(
    price_df: pd.DataFrame,
    volume_df: pd.DataFrame,
    min_usd: float = 20_000_000.0,
    window: int = 20,
) -> pd.DataFrame:
    """Boolean panel: True where 20d rolling dollar volume >= min_usd.

    Reuses the existing `dollar_volume_ma` helper (base_volatility.py);
    PRD §D2 dual-role: the same computation feeds both the feature
    (`dollar_vol_20d`) and this mask.

    Default threshold $20M matches admission extended tier. Core tier
    ($50M) can be obtained by passing `min_usd=50e6`.

    Parameters
    ----------
    price_df  : close prices
    volume_df : share volume
    min_usd   : rolling dollar volume threshold (default 20e6)
    window    : rolling window (default 20 trading days)

    Returns
    -------
    Boolean DataFrame aligned to price_df. NaN rolling values → False
    (warmup bars not yet tradable).
    """
    if min_usd < 0:
        raise ValueError(f"min_usd must be >= 0, got {min_usd}")
    rolling_dv = dollar_volume_ma(price_df, volume_df, window=window)
    return (rolling_dv >= min_usd).fillna(False)


def research_mask(
    price_df: pd.DataFrame,
    volume_df: pd.DataFrame,
    min_price: float = 5.0,
    min_usd: float = 20_000_000.0,
    window: int = 20,
) -> pd.DataFrame:
    """Combined research mask: `price_floor AND tradable_dollar_vol`.

    Per PRD §3.3 "optional combined research mask". Use for research
    scripts that want a single truth-value panel for "is this bar
    usable?". Individual masks remain available for ablation.
    """
    pf = price_floor_mask(price_df, min_price=min_price)
    tr = tradable_mask_dollar_vol(
        price_df, volume_df, min_usd=min_usd, window=window,
    )
    # Align shapes (tradable mask's columns come from volume_df reindex)
    tr = tr.reindex_like(pf).fillna(False)
    return pf & tr
