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

Phase E-post R5 (E-post-2): `research_mask_default()` loads the
canonical `{min_price, min_usd, window}` triple from
`config/research_mask.yaml`, replacing 9 call-sites' inline
`{5.0, 20e6, 20}` literals. The values in the yaml MUST match the
historical hardcoded defaults for bit-for-bit eligibility stability
across the `post-2026-04-24-rcm-v1-lag1` lineage.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd
import yaml

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


# ── PRD 20260424 §7 — Research-mask sample-definition hardening ──────────────


_DEFAULT_CONFIG_PATH = Path("config/research_mask.yaml")

# Frozen fallback: if the yaml is missing (CI / fresh clone before git
# pull), callers still get the bit-identical historical behavior. If the
# yaml IS present but has a different value, the yaml wins — this keeps
# the config file authoritative for any intentional future change.
_HISTORICAL_DEFAULTS = {
    "min_price": 5.0,
    "min_usd": 20_000_000.0,
    "window": 20,
}


def load_research_mask_params(
    config_path: Optional[Path | str] = None,
) -> dict:
    """Load the `{min_price, min_usd, window}` triple from config.

    Parameters
    ----------
    config_path : optional path to the research_mask.yaml file.
                  Defaults to `config/research_mask.yaml` (relative to
                  cwd). If the file does not exist, returns the frozen
                  historical defaults — so callers degrade gracefully
                  on fresh clones / CI.

    Returns
    -------
    dict with exactly the keys `{"min_price", "min_usd", "window"}`.
    """
    path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH
    if not path.exists():
        return dict(_HISTORICAL_DEFAULTS)
    with path.open() as f:
        doc = yaml.safe_load(f) or {}
    section = doc.get("research_mask", {}) if isinstance(doc, dict) else {}
    out = {
        "min_price": float(section.get("min_price",
                                       _HISTORICAL_DEFAULTS["min_price"])),
        "min_usd": float(section.get("min_usd",
                                     _HISTORICAL_DEFAULTS["min_usd"])),
        "window": int(section.get("window",
                                  _HISTORICAL_DEFAULTS["window"])),
    }
    return out


def research_mask_default(
    price_df: pd.DataFrame,
    volume_df: pd.DataFrame,
    config_path: Optional[Path | str] = None,
) -> pd.DataFrame:
    """Compute the unified research mask using config-driven params.

    Equivalent to `research_mask(price_df, volume_df, **params)` where
    `params` comes from `config/research_mask.yaml`. This is the
    canonical entry point for research / acceptance / paper callers.

    Use this instead of `research_mask(..., min_price=5.0, min_usd=20e6,
    window=20)` so that a single config change propagates without
    hunting 9+ scripts.

    Bit-identical to the historical inline call today (PRD §10.2
    invariant) because yaml values equal the historical defaults.
    """
    p = load_research_mask_params(config_path)
    return research_mask(
        price_df, volume_df,
        min_price=p["min_price"],
        min_usd=p["min_usd"],
        window=p["window"],
    )


def apply_research_mask(
    factor_panel: pd.DataFrame,
    mask: pd.DataFrame,
    fill: float = float("nan"),
) -> pd.DataFrame:
    """Apply a boolean research mask to a factor panel.

    Cells where `mask == False` are set to `fill` (default NaN). This is
    the anti-pattern replacement for `factor_panel.fillna(0)` which
    silently conflates four different states into a single value:
      1. 真正中性值 (factor legitimately equals 0 on this date)
      2. warmup 缺失 (factor not yet computable — leading-NaN)
      3. 不可交易样本 (mask says illiquid / below price floor)
      4. 数据缺失样本 (OHLCV genuinely missing)

    After this function:
      - non-NaN cells = valid observation AND passes mask
      - NaN cells    = either warmup / data-missing (pre-existing NaN in
                       factor_panel) OR excluded by mask

    Downstream callers (IC screen, ML trainer, miner metric) should
    then `.dropna()` on rows/columns as appropriate for their objective,
    rather than `.fillna(0)` which hides the distinction.

    Parameters
    ----------
    factor_panel : DataFrame of factor values
    mask         : Boolean DataFrame (same semantic shape as panel); cells
                   that are True stay, cells that are False are masked.
                   Missing entries in mask (after reindex_like) become
                   False (conservative: mask out unknown cells).
    fill         : value for False-mask cells; default NaN preserves the
                   "skip this sample" distinction. Callers wanting strict
                   zero-neutralization can pass fill=0.0 explicitly, which
                   is then intentional and auditable (unlike implicit
                   .fillna(0)).

    Returns
    -------
    DataFrame aligned to factor_panel.
    """
    aligned_mask = mask.reindex_like(factor_panel).fillna(False)
    return factor_panel.where(aligned_mask, other=fill)
