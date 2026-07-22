"""Canonical costless SPY total-return hurdle for Mining V5."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from core.research.qualification_v2 import canonical_sha256, sha256_file
from core.research.qualification_v4 import _max_drawdown


class CanonicalBenchmarkError(RuntimeError):
    """Raised when SPY source data cannot prove the required return basis."""


def _annualized_return(values: np.ndarray) -> float:
    return float(np.prod(1.0 + values) ** (252.0 / len(values)) - 1.0)


def build_canonical_spy_payload(
    source_path: str | Path,
    *,
    evaluation_start: date,
    evaluation_end: date,
) -> dict[str, Any]:
    """Build a self-contained, independently checkable benchmark artifact.

    The hard path is ``total_return_close.pct_change()``.  It must equal the
    independent exact-cash recurrence ``(close_t + D_t) / close_(t-1) - 1``.
    A one-share portfolio that leaves distributions in cash is retained only
    as a negative control and must differ when distributions exist.
    """

    path = Path(source_path).resolve()
    try:
        frame = pd.read_parquet(path)
    except Exception as exc:
        raise CanonicalBenchmarkError(f"cannot read SPY source: {path}") from exc
    required = {"close", "cash_distribution", "total_return_close"}
    if required - set(frame):
        raise CanonicalBenchmarkError("SPY source lacks exact-cash columns")
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise CanonicalBenchmarkError("SPY source requires DatetimeIndex")
    if (
        frame.empty
        or not frame.index.is_monotonic_increasing
        or frame.index.has_duplicates
    ):
        raise CanonicalBenchmarkError("SPY source index is not sorted and unique")
    numeric = frame[list(required)].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any() or not np.isfinite(numeric.to_numpy()).all():
        raise CanonicalBenchmarkError("SPY source contains non-finite values")
    if bool((numeric[["close", "total_return_close"]] <= 0.0).any().any()):
        raise CanonicalBenchmarkError("SPY price levels must be positive")
    if bool((numeric["cash_distribution"] < 0.0).any()):
        raise CanonicalBenchmarkError("SPY cash distributions must be non-negative")

    direct = numeric["total_return_close"].pct_change()
    recurrence = numeric["close"].add(numeric["cash_distribution"]).div(
        numeric["close"].shift(1)
    ).sub(1.0)
    mask = (frame.index.date >= evaluation_start) & (
        frame.index.date <= evaluation_end
    )
    if not bool(mask.any()):
        raise CanonicalBenchmarkError("evaluation interval is absent from source")
    selected = frame.index[mask]
    if selected[0].date() != evaluation_start or selected[-1].date() != evaluation_end:
        raise CanonicalBenchmarkError("evaluation endpoints must be source sessions")
    direct_eval = direct.loc[selected]
    recurrence_eval = recurrence.loc[selected]
    if direct_eval.isna().any() or recurrence_eval.isna().any():
        raise CanonicalBenchmarkError("evaluation start lacks a prior source session")
    parity_error = float(np.max(np.abs(
        direct_eval.to_numpy(dtype=float) - recurrence_eval.to_numpy(dtype=float)
    )))
    if parity_error > 1e-12:
        raise CanonicalBenchmarkError("total-return series fails exact-cash recurrence")

    prior_position = frame.index.get_loc(selected[0]) - 1
    if prior_position < 0:
        raise CanonicalBenchmarkError("cash-ledger negative control lacks opening NAV")
    opening_close = float(numeric["close"].iloc[prior_position])
    cash_held = numeric.loc[selected, "cash_distribution"].cumsum()
    cash_ledger_nav = numeric.loc[selected, "close"] + cash_held
    prior_nav = pd.concat([
        pd.Series([opening_close], index=[frame.index[prior_position]]),
        cash_ledger_nav,
    ])
    cash_ledger_returns = prior_nav.pct_change().iloc[1:]
    distributions = int((numeric.loc[selected, "cash_distribution"] > 0.0).sum())
    negative_control_equal = bool(np.allclose(
        cash_ledger_returns.to_numpy(dtype=float),
        direct_eval.to_numpy(dtype=float),
        rtol=0.0,
        atol=1e-12,
    ))
    if distributions and negative_control_equal:
        raise CanonicalBenchmarkError("dividend-cash negative control did not diverge")

    dates = [item.date().isoformat() for item in selected]
    values = direct_eval.to_numpy(dtype=float)
    years: dict[str, Any] = {}
    selected_years = np.asarray([item.year for item in selected], dtype=int)
    for year in sorted(set(selected_years.tolist())):
        year_values = values[selected_years == year]
        years[str(year)] = {
            "sessions": int(len(year_values)),
            "max_drawdown": _max_drawdown(year_values),
            "total_return": float(np.prod(1.0 + year_values) - 1.0),
        }
    return {
        "schema_version": 1,
        "artifact_type": "canonical_costless_total_return_benchmark",
        "symbol": "SPY",
        "return_basis": "split_and_distribution_adjusted_total_return",
        "cost_policy": "costless_total_return_hurdle",
        "distributions": "reinvested",
        "evaluation_start": evaluation_start.isoformat(),
        "evaluation_end": evaluation_end.isoformat(),
        "source": {
            "path_at_build": str(path),
            "sha256": sha256_file(path),
            "rows": int(len(frame)),
            "first_session": frame.index[0].date().isoformat(),
            "last_session": frame.index[-1].date().isoformat(),
        },
        "parity": {
            "direct_total_return_vs_exact_cash_recurrence_max_abs_error": parity_error,
            "tolerance": 1e-12,
            "passed": True,
            "dividend_cash_negative_control_equal": negative_control_equal,
            "dividend_cash_negative_control_passed": not negative_control_equal,
            "distribution_events": distributions,
        },
        "dates": dates,
        "total_returns": values.tolist(),
        "date_index_sha256": canonical_sha256(dates),
        "returns_sha256": canonical_sha256(values.tolist()),
        "metrics": {
            "sessions": int(len(values)),
            "cagr": _annualized_return(values),
            "max_drawdown": _max_drawdown(values),
            "calendar_years": years,
        },
    }


__all__ = [
    "CanonicalBenchmarkError",
    "build_canonical_spy_payload",
]
