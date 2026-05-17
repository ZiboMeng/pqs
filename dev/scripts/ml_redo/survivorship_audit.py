"""R0-d4 — survivorship-rigor audit (supplementary PRD §3, R0-A5).

Quantifies the universe's survivorship bias. PQS has a PIT first-trade-
date mechanism (prevents look-ahead INCLUSION) but NO as-of-date
membership reconstruction (the universe is current-constituents with
manual delisting removal e.g. K/Kellanova) → residual survivorship.

This audit measures what is measurable from the data: per-year symbol
data coverage + symbols whose daily data ends well before the panel
end (a delisting/stale proxy), and sets `as_of_rebuild_required`
(structurally true: the yaml is current-constituents). Honest: it does
NOT claim a true delisting DB exists; it reports the proxy + the
structural fact so R-P4ext can decide v2 composition.

Writes data/audit/ml_redo/survivorship_audit.json.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

_PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJ))

from core.config.loader import load_config  # noqa: E402
from core.data.bar_store import BarStore  # noqa: E402
from core.universe.universe_resolver import resolve_universe  # noqa: E402


def main() -> int:
    cfg = load_config(_PROJ / "config")
    store = BarStore(root=Path(cfg.system.paths.data_dir))
    syms = list(resolve_universe("executable"))

    spans = {}
    panel_end = None
    for s in syms:
        df = store.load(s, freq="1d", adjusted=True, fallback="local")
        if df is None or df.empty:
            spans[s] = None
            continue
        lo, hi = df.index.min(), df.index.max()
        spans[s] = (lo, hi)
        panel_end = hi if panel_end is None else max(panel_end, hi)

    # per-year alive count
    years = list(range(2009, (panel_end.year if panel_end else 2024) + 1))
    per_year = {}
    for y in years:
        alive = sum(
            1 for v in spans.values()
            if v is not None and v[0].year <= y <= v[1].year)
        per_year[y] = alive

    # delisting/stale proxy: data ends > 250 trading days before panel end
    stale = []
    if panel_end is not None:
        cutoff = panel_end - pd.Timedelta(days=400)
        for s, v in spans.items():
            if v is not None and v[1] < cutoff:
                stale.append({"symbol": s, "last_bar": str(v[1].date())})

    n_total = len([v for v in spans.values() if v is not None])
    bias_est = len(stale) / n_total if n_total else 0.0

    audit = {
        "audit": "survivorship_rigor",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "universe": "executable",
        "n_symbols_with_data": n_total,
        "panel_end": str(panel_end.date()) if panel_end is not None else None,
        "per_year_alive": per_year,
        "delisting_stale_proxy": stale,
        "n_stale": len(stale),
        "bias_estimate_frac": round(bias_est, 4),
        "pit_first_trade_date_exists": True,   # config/universe.yaml:204
        "as_of_membership_rebuild_exists": False,  # current-constituents only
        "as_of_rebuild_required": True,        # structural: yaml = survivors
        "note": "PIT first-trade-date prevents look-ahead inclusion; NO "
                "as-of-date membership reconstruction (current-constituents "
                "+ manual delisting removal e.g. K). Residual survivorship "
                "bias. R-P4ext expanded_v2 should include historical "
                "delisted names with alive-windows OR record an explicit "
                "evidence caveat.",
        "c5_as_of_rebuild_resolution": {
            "status": "structurally_infeasible_honest_caveat",
            "why": "a true as-of-date membership rebuild needs a "
                   "delisting / historical-index-constituent database "
                   "(survivors + dead names + each name's alive window). "
                   "PQS has NO such DB — data/daily is current/surviving "
                   "tickers only. Fabricating dead-name membership would "
                   "be inventing data (audit discipline: do NOT fake).",
            "what_was_measured": "data-span delisting proxy (n_stale) + "
                                 "the structural fact (current-constituents "
                                 "+ manual removal). expanded_v2 also "
                                 "membership-by-data (no external index).",
            "what_proper_resolution_needs": "ingest a delisting/CRSP-style "
                                            "historical-constituent feed → "
                                            "rebuild as-of universe per "
                                            "date. Paid-data / new ingest "
                                            "scope; user explicit-go gated.",
            "decision": "ALL chart-native results are explicitly caveated "
                        "as survivorship-biased (surviving-name universe); "
                        "this is a known, recorded limitation NOT a hidden "
                        "one — honest closure, not a pretended fix.",
        },
    }
    out = _PROJ / "data" / "audit" / "ml_redo" / "survivorship_audit.json"
    out.write_text(json.dumps(audit, indent=2, default=str))
    print(f"survivorship audit -> {out.name}: n={n_total} stale={len(stale)} "
          f"bias~{bias_est:.2%} as_of_rebuild_required=True")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
