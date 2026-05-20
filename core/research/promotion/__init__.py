"""Promotion-side utilities for trigger-first canonical + MFS promote paths.

PRD: docs/prd/20260520-prd_trigger_first_canonical_promotion.md §P3.5
"""

from core.research.promotion.fingerprints import (
    compute_config_hash,
    compute_factor_registry_hash,
    compute_fingerprints,
    compute_universe_hash,
)

__all__ = [
    "compute_universe_hash",
    "compute_factor_registry_hash",
    "compute_config_hash",
    "compute_fingerprints",
]
