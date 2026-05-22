"""Capital allocation layer (PRD 20260521 §4.8, Package P3).

Score-to-weight mapping, portfolio-constraint enforcement, and exit
policy — a layer SEPARATE from forecasting. A rank model produces a
cross-sectional score; this package governs how that score becomes
long-only target weights.
"""
