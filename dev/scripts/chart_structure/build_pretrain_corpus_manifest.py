"""P2B·R3 — build the self-supervised pretrain-corpus manifest.

Per chart-structure ralph-loop execution PRD §6 round P2B·R3. Writes
``data/manifests/chart_structure_pretrain_corpus_v1.json`` — the frozen
description of which price windows the TS2Vec encoder (P2B·R2) may be
pretrained on.

Holdout discipline: a window is eligible iff its END bar falls in a
``train`` year of ``config/temporal_split.yaml``. Validation years
(2018/2019/2021/2023/2025) and the sealed 2026 window are excluded.
Windows may warm up across a year boundary (a 63-bar window ending in
Jan of a train year reaches into the prior year) — that is rolling-
window warmup, capped well under the split's 504-day factor-warmup cap.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

_PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJ))

from core.ml.corpus_manifest import PretrainCorpusManifest  # noqa: E402
from core.research.temporal_split import (  # noqa: E402
    load_temporal_split,
    sealed_year_set,
    train_year_set,
    validation_year_set,
)
from core.universe.universe_resolver import resolve_universe  # noqa: E402

_DAILY = _PROJ / "data" / "daily"
_OUT = _PROJ / "data" / "manifests" / "chart_structure_pretrain_corpus_v1.json"
_WINDOW_LEN = 63
_UNIVERSE = "expanded_v1"


def main() -> int:
    cfg = load_temporal_split()
    train = sorted(train_year_set(cfg))
    val = sorted(validation_year_set(cfg))
    sealed = sorted(sealed_year_set(cfg))
    ref = [2007, 2008]  # reference_years — excluded_from_alpha
    train_set = set(train)

    syms = resolve_universe(_UNIVERSE)
    n_windows = 0
    n_syms_with_data = 0
    eligible_dates: list[pd.Timestamp] = []
    for s in syms:
        p = _DAILY / f"{s}.parquet"
        if not p.exists():
            continue
        idx = pd.DatetimeIndex(pd.read_parquet(p, columns=["close"]).index)
        # a window ending at position i needs WINDOW_LEN-1 prior bars
        years = idx.year
        for i in range(_WINDOW_LEN - 1, len(idx)):
            if int(years[i]) in train_set:
                n_windows += 1
                eligible_dates.append(idx[i])
        if (pd.Series(years).isin(train_set)).any():
            n_syms_with_data += 1

    eligible_dates.sort()
    manifest = PretrainCorpusManifest(
        schema_version="1.0",
        corpus_id="chart_structure_pretrain_corpus_v1",
        created_at=datetime.now(timezone.utc).date().isoformat(),
        split_name=cfg.split_name,
        train_years_only=True,
        timeframe="daily",
        timeframes_reserved=["60m", "30m", "15m"],
        window_len=_WINDOW_LEN,
        universe_name=_UNIVERSE,
        universe_size=len(syms),
        eligible_years=train,
        excluded_years={"validation": val, "sealed": sealed, "reference": ref},
        date_range={
            "start": eligible_dates[0].date().isoformat(),
            "end": eligible_dates[-1].date().isoformat(),
        },
        n_symbols_with_data=n_syms_with_data,
        n_windows=n_windows,
        source="data/daily/<sym>.parquet (close), window_len=63 causal",
    )
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(json.dumps(manifest.model_dump(), indent=2))
    print(f"wrote {_OUT}")
    print(f"  universe={_UNIVERSE} ({len(syms)} symbols, "
          f"{n_syms_with_data} with train-year data)")
    print(f"  eligible train years: {train}")
    print(f"  excluded: validation={val} sealed={sealed} reference={ref}")
    print(f"  n_windows={n_windows:,}  "
          f"date_range={manifest.date_range.start}..{manifest.date_range.end}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
