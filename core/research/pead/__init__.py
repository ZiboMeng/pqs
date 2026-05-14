"""PEAD (Post-Earnings Announcement Drift) signal modules.

PRD: docs/prd/20260514-pead_bundle_phase1_prd.md
Lineage: pead-bundle-2026-05-14
"""

from core.research.pead.earnings_dates import (
    extract_earnings_dates,
    extract_earnings_dates_panel,
)

__all__ = [
    "extract_earnings_dates",
    "extract_earnings_dates_panel",
]
