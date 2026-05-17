"""Universe resolver — single entry point for which symbol set a run uses.

Per the chart-structure PRD §6.2 and ralph-loop execution PRD §8 round
P4·R1.

D6 isolation contract
---------------------
`resolve_universe("executable")` reproduces the existing 79-symbol
executable mining universe **bit-for-bit** — same construction, same
order as the pre-Phase-4 inline universe building (e.g.
``scripts/run_research_miner.py`` and the chart-structure scripts):
``union(seed_pool + sector_etfs + factor_etfs + cross_asset)`` minus
blacklist / macro-reference / cycle-drop symbols, then SPY/QQQ appended.

`resolve_universe("expanded_v1")` is the opt-in Phase-4 expanded universe
(``config/universe_expanded_v1.yaml``, built in P4·R2). It is ADDITIVE:
the original 79 plus new symbols.

The default everywhere is `executable`. `expanded_v1` is only ever used
when a caller explicitly passes `--universe expanded_v1`, so prior
79-universe results (cycle04-12, all forward candidates, Phase 1.5/1.6,
chart-structure Phase 2A) are never retroactively affected.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import yaml

from core.config.loader import load_config

UNIVERSE_NAMES = ("executable", "expanded_v1", "expanded_v2")

# Cycle-drop symbols (data-integrity round-3 / TC-ceiling); see
# config/executable_universe.yaml. USO is a no-op (never in the union).
_CYCLE_DROP = {"BRK-B", "USO", "SLV"}

_PROJ = Path(__file__).resolve().parents[2]


def _executable_base(config_dir: Path) -> List[str]:
    """The canonical 79-symbol construction (excludes benchmarks append)."""
    cfg = load_config(config_dir)
    uni = cfg.universe
    base = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs)
        + list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    return [s for s in base
            if s not in uni.blacklist
            and s not in uni.macro_reference
            and s not in _CYCLE_DROP]


def resolve_universe(
    name: str = "executable",
    config_dir: Optional[Path | str] = None,
    include_benchmarks: bool = True,
) -> List[str]:
    """Resolve a universe name to its ordered symbol list.

    Parameters
    ----------
    name : "executable" | "expanded_v1" | "expanded_v2"
    config_dir : config directory (defaults to repo ``config/``).
    include_benchmarks : append SPY / QQQ if absent (default True —
        matches the pre-Phase-4 inline behaviour).
    """
    if name not in UNIVERSE_NAMES:
        raise ValueError(
            f"unknown universe {name!r}; expected one of {UNIVERSE_NAMES}")
    cdir = Path(config_dir) if config_dir is not None else (_PROJ / "config")

    base = _executable_base(cdir)
    if name == "executable":
        syms = list(base)
    elif name == "expanded_v1":
        exp_path = cdir / "universe_expanded_v1.yaml"
        if not exp_path.exists():
            raise FileNotFoundError(
                f"{exp_path} not found — the expanded_v1 universe has not "
                f"been built yet (chart-structure Phase 4 / P4·R2).")
        doc = yaml.safe_load(exp_path.read_text()) or {}
        extra = list(doc.get("expanded_symbols", []))
        # additive: original executable 79 first, then new symbols, deduped
        syms = list(dict.fromkeys(base + extra))
    else:  # expanded_v2 (R-P4ext: data-driven ~1k, supplementary PRD §8.5)
        exp_path = cdir / "universe_expanded_v2.yaml"
        if not exp_path.exists():
            raise FileNotFoundError(
                f"{exp_path} not found — expanded_v2 not built yet "
                f"(supplementary PRD R-P4ext; run "
                f"dev/scripts/ml_redo/universe_v2_coverage_audit.py).")
        doc = yaml.safe_load(exp_path.read_text()) or {}
        extra = list(doc.get("symbols", []))
        # additive (same D6 semantics as v1): executable base first, then
        # the coverage-audit-selected ~1k, deduped. executable/expanded_v1
        # outputs are byte-identical (this branch never runs for them).
        syms = list(dict.fromkeys(base + extra))

    if include_benchmarks:
        for b in ("SPY", "QQQ"):
            if b not in syms:
                syms.append(b)
    return syms
