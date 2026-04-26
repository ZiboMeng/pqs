"""M12 concentration report module (PRD v3 §C / execution PRD §3 R3)."""
from .report import (
    ConcentrationReport,
    ConcentrationGateStatus,
    NarrativePermission,
    compute,
    write_artifacts,
)
from .watch_exposure import render_watch_exposure_section

__all__ = [
    "ConcentrationReport",
    "ConcentrationGateStatus",
    "NarrativePermission",
    "compute",
    "render_watch_exposure_section",
    "write_artifacts",
]
