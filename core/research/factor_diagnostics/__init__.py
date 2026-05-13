"""Factor diagnostic tools for independent cross-validation.

PRD-driven 2026-05-12 (Round Z1).

These run on `train_years` slice (no sealed-panel consumption) and
produce evidence that informs:
- cycle #09 archetype selection (which 162 factors actually have alpha)
- Sibling-by-NAV detection (which new factors are disguised duplicates
  of RCMv1 / Cand-2 / Trial 9 candidate)
- Cluster decomposition (factors that look distinct by name but ARE
  correlated)
"""

from core.research.factor_diagnostics.cross_ic_table import (
    compute_factor_ic_table,
)
from core.research.factor_diagnostics.cluster_decomposition import (
    compute_factor_clusters,
)
from core.research.factor_diagnostics.anchor_correlation import (
    compute_anchor_nav_correlation,
)

__all__ = [
    "compute_factor_ic_table",
    "compute_factor_clusters",
    "compute_anchor_nav_correlation",
]
