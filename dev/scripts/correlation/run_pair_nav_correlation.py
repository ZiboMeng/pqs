"""
Generic pair NAV correlation diagnostic.

Computes pairwise realized-NAV correlation diagnostic for any two
candidates. Replaces the pair-specific RCMv1×Cand-2 logic; that
script (`rcmv1_cand2_realized_nav_correlation.py`) is now a thin
wrapper around this module's `run_pair_correlation()`.

Output schema is stable for evidence pack §4.6 (NAV-orthogonality
tier) consumption: raw_pearson + residual_pearson_vs_spy +
residual_pearson_vs_qqq + tier classifications + root-cause label
+ adjacent diagnostics (down-market, drawdown overlap, holdings
overlap, beta).

Tier 4-classification (per audit-R2 + reviewer §3 2026-04-30):
  < 0.50           true_diversifier
  0.50 - 0.70      partial_diversifier
  0.70 - 0.85      warn_label_void
  >= 0.85          reject_step5

CLI:
    python dev/scripts/correlation/run_pair_nav_correlation.py \\
        --candidate-a-id    <id_a> \\
        --candidate-a-run-dirs <dir_a_1> [<dir_a_2> ...] \\
        --candidate-b-id    <id_b> \\
        --candidate-b-run-dirs <dir_b_1> [<dir_b_2> ...] \\
        [--cell-labels <label_1> [<label_2> ...]] \\
        [--min-overlap 60] \\
        [--output-json <path>]

Run dirs MUST be ordered consistently between candidates A and B
so cells line up. cell-labels are optional human-readable names
(default: cell_0, cell_1, ...).

Programmatic use:
    from dev.scripts.correlation.run_pair_nav_correlation import (
        run_pair_correlation, classify, classify_residual
    )
    result = run_pair_correlation(
        cand_a_id="rcm_v1_defensive_composite_01",
        cand_a_run_dirs=[Path(...), Path(...)],
        cand_b_id="candidate_2_orthogonal_01",
        cand_b_run_dirs=[Path(...), Path(...)],
        cell_labels=["2022_h2", "2024_q1"],
        min_overlap=60,
    )
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


# ── Loaders ─────────────────────────────────────────────────────────


def load_pnl(run_dir: Path) -> pd.DataFrame:
    """Load `pnl_daily.csv` returns from a paper-run directory."""
    p = run_dir / "pnl_daily.csv"
    df = pd.read_csv(p, parse_dates=["date"]).set_index("date").sort_index()
    return df[["ret"]]


def load_benchmark(run_dir: Path) -> pd.DataFrame:
    """Load `benchmark_relative_paper.csv` and convert to daily returns."""
    p = run_dir / "benchmark_relative_paper.csv"
    df = pd.read_csv(p, parse_dates=["date"]).set_index("date").sort_index()
    spy_d = df["SPY_cum_ret"].diff().fillna(df["SPY_cum_ret"]).rename("spy_ret_d")
    qqq_d = df["QQQ_cum_ret"].diff().fillna(df["QQQ_cum_ret"]).rename("qqq_ret_d")
    return pd.concat([spy_d, qqq_d], axis=1)


def load_positions(run_dir: Path) -> Optional[pd.DataFrame]:
    """Load wide-format `target_portfolio_daily.csv` if present."""
    p = run_dir / "target_portfolio_daily.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p, parse_dates=["date"])
    return df


# ── Tier classification ─────────────────────────────────────────────


def classify(corr: Optional[float]) -> str:
    """Tier classification per audit-Round-2 revision (2026-04-30) +
    external-reviewer §3 (2026-04-30).

    Mirrors Step 5 fleet correlation budget with one extra gate at
    0.50: long-only US equity has a market-beta correlation floor
    that makes flat 0.40 (factor-IC config) structurally over-strict
    at NAV level.
    """
    if corr is None:
        return "insufficient_data"
    if corr < 0.50:
        return "true_diversifier"
    if corr < 0.70:
        return "partial_diversifier"
    if corr < 0.85:
        return "warn_label_void"
    return "reject_step5"


def classify_residual(raw_corr: Optional[float], residual_corr: Optional[float]) -> str:
    """Diagnose root cause of high raw NAV correlation by residual drop.

    Returns one of:
      - "shared_market_beta_dominant": raw high (>=0.70) AND residual
        drops materially (>=0.30 absolute) AND residual < 0.50
      - "shared_alpha_dominant": raw high AND residual stays > 0.70
      - "mixed": between the two
      - "low_raw": raw is low to begin with — residual is moot
      - "insufficient_data": missing inputs
    """
    if raw_corr is None or residual_corr is None:
        return "insufficient_data"
    if raw_corr < 0.70:
        return "low_raw"
    drop = raw_corr - residual_corr
    if residual_corr < 0.50 and drop >= 0.30:
        return "shared_market_beta_dominant"
    if residual_corr >= 0.70:
        return "shared_alpha_dominant"
    return "mixed"


# ── Per-cell diagnostics ────────────────────────────────────────────


def _empty_diagnostic(
    cell: str, n: int, reason: str,
    cand_a_col: str = "cand_a", cand_b_col: str = "cand_b",
) -> dict:
    """Structured insufficient-data diagnostic; downstream JSON consumers
    should not receive silent NaN. Column name keys are parametric so the
    legacy RCMv1×Cand-2 wrapper preserves its original key names
    (rcm_v1 / cand_2) on insufficient-data path too.
    """
    return {
        "cell": cell,
        "n_days": n,
        "date_range": [None, None],
        "status": "insufficient_data",
        "status_reason": reason,
        "pearson_corr": None,
        "spearman_corr": None,
        "n_down_days": 0,
        "down_market_corr": None,
        "n_up_days": 0,
        "up_market_corr": None,
        "rolling_30d_corr": {"min": None, "max": None, "mean": None},
        "max_dd": {cand_a_col: None, cand_b_col: None},
        "pct_days_both_in_dd": None,
        "holdings_overlap_jaccard_avg": None,
        "holdings_top10_overlap_last": None,
        "beta_to_qqq": {cand_a_col: None, cand_b_col: None},
        "beta_to_spy": {cand_a_col: None, cand_b_col: None},
    }


def cell_diagnostics(
    *,
    cell: str,
    cand_a_dir: Path,
    cand_b_dir: Path,
    cand_a_col: str = "cand_a",
    cand_b_col: str = "cand_b",
) -> dict:
    """Compute per-cell pair diagnostics. Column names parametric for
    use both as the legacy RCMv1×Cand-2 wrapper (cand_a_col=rcm_v1,
    cand_b_col=cand_2) and as the generic Track C runner.

    Benchmark is loaded from `cand_a_dir` (this cell's dir) so that
    SPY/QQQ dates overlap the cell's PnL window. NEVER pass a
    cross-cell benchmark dir here — pre-refactor regression caught
    by R3 audit 2026-04-30 (cell N's benchmark loaded from cell 0's
    dir produced zero overlap → false insufficient_data).
    """
    a = load_pnl(cand_a_dir).rename(columns={"ret": cand_a_col})
    b = load_pnl(cand_b_dir).rename(columns={"ret": cand_b_col})
    bmk = load_benchmark(cand_a_dir)  # always per-cell; see docstring

    df = pd.concat([a, b, bmk], axis=1).dropna()
    n = len(df)

    if n == 0:
        return _empty_diagnostic(
            cell, n=0, reason="zero overlap rows after dropna",
            cand_a_col=cand_a_col, cand_b_col=cand_b_col,
        )
    if n < 2:
        return _empty_diagnostic(
            cell, n=n,
            reason=f"only {n} overlap row(s); pearson undefined for n<2",
            cand_a_col=cand_a_col, cand_b_col=cand_b_col,
        )

    # 1. unconditional correlation
    with np.errstate(invalid="ignore", divide="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        try:
            from scipy.stats import ConstantInputWarning  # type: ignore[import-not-found]
            warnings.simplefilter("ignore", category=ConstantInputWarning)
        except ImportError:
            pass
        pearson = float(df[cand_a_col].corr(df[cand_b_col]))
        spearman = float(df[cand_a_col].corr(df[cand_b_col], method="spearman"))
    if not np.isfinite(pearson):
        return _empty_diagnostic(
            cell, n=n,
            reason=f"pearson non-finite ({pearson}) — zero variance in at least one series",
        )

    # 2. down-market conditional correlation
    down_mask = df["spy_ret_d"] < -0.005
    n_down = int(down_mask.sum())
    down_corr = None
    if n_down >= 5:
        with np.errstate(invalid="ignore", divide="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                from scipy.stats import ConstantInputWarning  # type: ignore[import-not-found]
                warnings.simplefilter("ignore", category=ConstantInputWarning)
            except ImportError:
                pass
            c = float(df.loc[down_mask, cand_a_col].corr(df.loc[down_mask, cand_b_col]))
        if np.isfinite(c):
            down_corr = c

    # 3. up-market conditional
    up_mask = df["spy_ret_d"] > 0.005
    n_up = int(up_mask.sum())
    up_corr = None
    if n_up >= 5:
        with np.errstate(invalid="ignore", divide="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                from scipy.stats import ConstantInputWarning  # type: ignore[import-not-found]
                warnings.simplefilter("ignore", category=ConstantInputWarning)
            except ImportError:
                pass
            c = float(df.loc[up_mask, cand_a_col].corr(df.loc[up_mask, cand_b_col]))
        if np.isfinite(c):
            up_corr = c

    # 4. rolling 30d correlation
    roll = df[cand_a_col].rolling(30).corr(df[cand_b_col]).dropna()
    roll_min = float(roll.min()) if len(roll) else None
    roll_max = float(roll.max()) if len(roll) else None
    roll_mean = float(roll.mean()) if len(roll) else None

    # 5. drawdown overlap
    eq_a = (1 + df[cand_a_col]).cumprod()
    eq_b = (1 + df[cand_b_col]).cumprod()
    dd_a = eq_a / eq_a.cummax() - 1
    dd_b = eq_b / eq_b.cummax() - 1
    both_in_dd = ((dd_a < -0.001) & (dd_b < -0.001)).sum()
    pct_both_dd = float(both_in_dd / n)
    a_max_dd = float(dd_a.min())
    b_max_dd = float(dd_b.min())

    # 6. holdings overlap
    pos_a = load_positions(cand_a_dir)
    pos_b = load_positions(cand_b_dir)
    holdings_overlap_jaccard_avg = None
    holdings_top10_overlap_last = None
    if pos_a is not None and pos_b is not None:
        a_w = pos_a.set_index("date")
        b_w = pos_b.set_index("date")
        common_dates = a_w.index.intersection(b_w.index)
        jaccards: list[float] = []
        for d in common_dates:
            a_set = set(a_w.columns[(a_w.loc[d] > 0)])
            b_set = set(b_w.columns[(b_w.loc[d] > 0)])
            if not a_set and not b_set:
                continue
            jaccards.append(len(a_set & b_set) / max(len(a_set | b_set), 1))
        if jaccards:
            holdings_overlap_jaccard_avg = float(np.mean(jaccards))

        last_date = df.index.max()
        if last_date in a_w.index and last_date in b_w.index:
            a_last = a_w.loc[last_date]
            b_last = b_w.loc[last_date]
            a_top = set(a_last.nlargest(10).index[a_last.nlargest(10) > 0])
            b_top = set(b_last.nlargest(10).index[b_last.nlargest(10) > 0])
            holdings_top10_overlap_last = len(a_top & b_top)

    # 7. beta-to-QQQ + beta-to-SPY
    beta_a_qqq = float(df[cand_a_col].cov(df["qqq_ret_d"]) / df["qqq_ret_d"].var())
    beta_b_qqq = float(df[cand_b_col].cov(df["qqq_ret_d"]) / df["qqq_ret_d"].var())
    beta_a_spy = float(df[cand_a_col].cov(df["spy_ret_d"]) / df["spy_ret_d"].var())
    beta_b_spy = float(df[cand_b_col].cov(df["spy_ret_d"]) / df["spy_ret_d"].var())

    return {
        "cell": cell,
        "n_days": n,
        "date_range": [str(df.index.min().date()), str(df.index.max().date())],
        "status": "ok",
        "status_reason": None,
        "pearson_corr": pearson,
        "spearman_corr": spearman,
        "n_down_days": n_down,
        "down_market_corr": down_corr,
        "n_up_days": n_up,
        "up_market_corr": up_corr,
        "rolling_30d_corr": {
            "min": roll_min,
            "max": roll_max,
            "mean": roll_mean,
        },
        "max_dd": {
            cand_a_col: a_max_dd,
            cand_b_col: b_max_dd,
        },
        "pct_days_both_in_dd": pct_both_dd,
        "holdings_overlap_jaccard_avg": holdings_overlap_jaccard_avg,
        "holdings_top10_overlap_last": holdings_top10_overlap_last,
        "beta_to_qqq": {cand_a_col: beta_a_qqq, cand_b_col: beta_b_qqq},
        "beta_to_spy": {cand_a_col: beta_a_spy, cand_b_col: beta_b_spy},
    }


# ── Pooled diagnostics ──────────────────────────────────────────────


def combined_diagnostics(
    *,
    cells: dict[str, dict[str, Path]],
    cand_a_col: str = "cand_a",
    cand_b_col: str = "cand_b",
) -> dict:
    """Pool all cells (concat returns, ignoring time gaps). Gaps are
    treated as discontinuities — no synthetic returns inserted.
    """
    frames = []
    for cell, paths in cells.items():
        a = load_pnl(paths[cand_a_col]).rename(columns={"ret": cand_a_col})
        b = load_pnl(paths[cand_b_col]).rename(columns={"ret": cand_b_col})
        df = pd.concat([a, b], axis=1).dropna()
        df = df.assign(cell=cell)
        frames.append(df)
    pooled = (
        pd.concat(frames).sort_index()
        if frames
        else pd.DataFrame(columns=[cand_a_col, cand_b_col])
    )
    n = len(pooled)
    if n < 2:
        return {
            "n_days_pooled": n,
            "pearson_corr_pooled": None,
            "spearman_corr_pooled": None,
            "status": "insufficient_data",
            "status_reason": f"only {n} pooled overlap row(s); pearson undefined for n<2",
        }
    with np.errstate(invalid="ignore", divide="ignore"):
        pearson = float(pooled[cand_a_col].corr(pooled[cand_b_col]))
        spearman = float(pooled[cand_a_col].corr(pooled[cand_b_col], method="spearman"))
    if not np.isfinite(pearson):
        return {
            "n_days_pooled": n,
            "pearson_corr_pooled": None,
            "spearman_corr_pooled": None,
            "status": "insufficient_data",
            "status_reason": "pooled pearson non-finite — zero variance in at least one series",
        }
    return {
        "n_days_pooled": n,
        "pearson_corr_pooled": pearson,
        "spearman_corr_pooled": spearman,
        "status": "ok",
        "status_reason": None,
    }


# ── Residual correlation ────────────────────────────────────────────


def compute_residual_correlation(
    df: pd.DataFrame,
    *,
    benchmark_col: str,
    cand_a_col: str = "cand_a",
    cand_b_col: str = "cand_b",
) -> dict:
    """Beta-neutralize each candidate against benchmark; correlate residuals.

    Per external-reviewer 2026-04-30 §4.3: raw NAV correlation alone
    cannot distinguish "shared market beta" from "shared alpha". If
    residual correlation drops sharply (raw > 0.85 → residual < 0.40),
    NAV correlation is mostly market beta. If residual stays high
    (> 0.70), alpha sleeves themselves are similar.

    Adjacent: residual annualized Sharpe (sign + magnitude) catches
    cases where residuals correlate but one is +SR and the other
    is -SR (organic diversification value) vs both same-sign-same-
    size (genuine redundancy).
    """
    if benchmark_col not in df.columns:
        return {"benchmark": benchmark_col, "status": "missing_benchmark"}
    bm = df[benchmark_col]
    bm_var = float(bm.var())
    if not np.isfinite(bm_var) or bm_var == 0.0:
        return {"benchmark": benchmark_col, "status": "zero_variance_benchmark"}

    def _residualize(s: pd.Series) -> tuple[pd.Series, float]:
        beta = float(s.cov(bm) / bm_var)
        return s - beta * bm, beta

    a_res, beta_a = _residualize(df[cand_a_col])
    b_res, beta_b = _residualize(df[cand_b_col])

    with np.errstate(invalid="ignore", divide="ignore"):
        residual_corr = float(a_res.corr(b_res))

    def _ann_sharpe(s: pd.Series) -> Optional[float]:
        std = float(s.std(ddof=1))
        # Guard against both exact-zero AND floating-point near-zero residuals
        # (R4 audit 2026-04-30: synthetic perfect-beta candidate produced
        # std ~1e-15 → fake Sharpe 0.44 from ratio of two near-zero values).
        if not np.isfinite(std) or std < 1e-10:
            return None
        v = float(s.mean() / std * np.sqrt(252))
        return v if np.isfinite(v) else None

    return {
        "benchmark": benchmark_col,
        "status": "ok" if np.isfinite(residual_corr) else "non_finite",
        f"beta_{cand_a_col}": beta_a,
        f"beta_{cand_b_col}": beta_b,
        "residual_pearson": residual_corr if np.isfinite(residual_corr) else None,
        f"residual_ann_sharpe_{cand_a_col}": _ann_sharpe(a_res),
        f"residual_ann_sharpe_{cand_b_col}": _ann_sharpe(b_res),
    }


# ── Top-level runner ────────────────────────────────────────────────


def run_pair_correlation(
    *,
    cand_a_id: str,
    cand_a_run_dirs: list[Path],
    cand_b_id: str,
    cand_b_run_dirs: list[Path],
    cell_labels: Optional[list[str]] = None,
    min_overlap: int = 60,
    cand_a_col: str = "cand_a",
    cand_b_col: str = "cand_b",
) -> dict:
    """Run full pair NAV correlation diagnostic.

    Args:
        cand_a_id, cand_b_id: candidate identifiers (recorded in output).
        cand_a_run_dirs, cand_b_run_dirs: ordered list of paper-run dirs.
            MUST be index-aligned: cand_a_run_dirs[i] and cand_b_run_dirs[i]
            are the same cell.
        cell_labels: optional labels (default cell_0, cell_1, ...).
        min_overlap: minimum pooled overlap days; below = warn in output.
        cand_a_col, cand_b_col: column names for diagnostic shape; for
            legacy compat callers may pass `rcm_v1` / `cand_2` etc.

    Benchmark (SPY/QQQ) is always loaded per-cell from each cell's
    own paper run dir — not from a global source. This matches
    legacy behavior and avoids the cross-cell-benchmark regression
    R3-audit caught at refactor time.

    Returns: dict with raw_pooled / per_cell / pooled_residual /
        classification fields, ready for JSON dump.
    """
    if len(cand_a_run_dirs) != len(cand_b_run_dirs):
        raise ValueError(
            f"run_dirs length mismatch: cand_a has {len(cand_a_run_dirs)} dirs, "
            f"cand_b has {len(cand_b_run_dirs)} dirs; must match index-aligned"
        )
    if not cand_a_run_dirs:
        raise ValueError("at least one run_dir per candidate required")

    if cell_labels is None:
        cell_labels = [f"cell_{i}" for i in range(len(cand_a_run_dirs))]
    if len(cell_labels) != len(cand_a_run_dirs):
        raise ValueError(
            f"cell_labels length mismatch: {len(cell_labels)} labels for "
            f"{len(cand_a_run_dirs)} cells"
        )

    cells = {
        label: {cand_a_col: a_dir, cand_b_col: b_dir}
        for label, a_dir, b_dir in zip(cell_labels, cand_a_run_dirs, cand_b_run_dirs)
    }

    per_cell = [
        cell_diagnostics(
            cell=label,
            cand_a_dir=cells[label][cand_a_col],
            cand_b_dir=cells[label][cand_b_col],
            cand_a_col=cand_a_col,
            cand_b_col=cand_b_col,
        )
        for label in cell_labels
    ]
    pooled = combined_diagnostics(cells=cells, cand_a_col=cand_a_col, cand_b_col=cand_b_col)

    # Pooled residual correlation vs SPY and QQQ. Benchmark loaded
    # PER CELL (each cell's own paper run dir) so concatenated frame
    # has the correct SPY/QQQ alignment per cell window. Do NOT use
    # the global benchmark_source_dir here — see cell_diagnostics
    # docstring for the regression this avoids.
    pooled_residual: dict = {}
    pooled_frames = []
    for label in cell_labels:
        cell_a_dir = cells[label][cand_a_col]
        cell_b_dir = cells[label][cand_b_col]
        a = load_pnl(cell_a_dir).rename(columns={"ret": cand_a_col})
        b = load_pnl(cell_b_dir).rename(columns={"ret": cand_b_col})
        bmk = load_benchmark(cell_a_dir)
        df = pd.concat([a, b, bmk], axis=1).dropna()
        pooled_frames.append(df)
    pooled_df = pd.concat(pooled_frames).sort_index() if pooled_frames else pd.DataFrame()
    if len(pooled_df) >= 2:
        pooled_residual["vs_spy_ret_d"] = compute_residual_correlation(
            pooled_df, benchmark_col="spy_ret_d",
            cand_a_col=cand_a_col, cand_b_col=cand_b_col,
        )
        pooled_residual["vs_qqq_ret_d"] = compute_residual_correlation(
            pooled_df, benchmark_col="qqq_ret_d",
            cand_a_col=cand_a_col, cand_b_col=cand_b_col,
        )
    else:
        pooled_residual = {"status": "insufficient_data"}

    raw_pooled = pooled.get("pearson_corr_pooled")
    res_spy = (
        pooled_residual.get("vs_spy_ret_d", {}).get("residual_pearson")
        if isinstance(pooled_residual, dict) else None
    )
    res_qqq = (
        pooled_residual.get("vs_qqq_ret_d", {}).get("residual_pearson")
        if isinstance(pooled_residual, dict) else None
    )

    pooled_n = pooled.get("n_days_pooled", 0) or 0
    overlap_warning = None
    if pooled_n < min_overlap:
        overlap_warning = (
            f"pooled overlap {pooled_n} days < min_overlap {min_overlap}; "
            f"correlation classification may be unstable"
        )

    return {
        "experiment": f"pair_nav_correlation_{cand_a_id}_vs_{cand_b_id}",
        "candidate_a_id": cand_a_id,
        "candidate_b_id": cand_b_id,
        "min_overlap_days": min_overlap,
        "overlap_warning": overlap_warning,
        "nav_orthogonality_tiers": {
            "true_diversifier":     "< 0.50",
            "partial_diversifier":  ">= 0.50 and < 0.70",
            "warn_label_void":      ">= 0.70 and < 0.85",
            "reject_step5":         ">= 0.85",
        },
        "step5_thresholds": {
            "warn": 0.70,
            "reject": 0.85,
            "min_overlap_days": min_overlap,
        },
        "per_cell": per_cell,
        "pooled": pooled,
        "pooled_residual_correlation": pooled_residual,
        "classification_pooled": classify(pooled.get("pearson_corr_pooled")),
        "classification_per_cell": [
            {"cell": c["cell"], "label": classify(c["pearson_corr"])}
            for c in per_cell
        ],
        "residual_root_cause": {
            "vs_spy": classify_residual(raw_pooled, res_spy),
            "vs_qqq": classify_residual(raw_pooled, res_qqq),
        },
    }


# ── CLI ─────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Generic pair NAV correlation diagnostic — see module docstring.",
    )
    p.add_argument("--candidate-a-id", required=True, help="Candidate A identifier")
    p.add_argument("--candidate-a-run-dirs", required=True, nargs="+", type=Path,
                   help="Ordered list of paper-run dirs for candidate A")
    p.add_argument("--candidate-b-id", required=True, help="Candidate B identifier")
    p.add_argument("--candidate-b-run-dirs", required=True, nargs="+", type=Path,
                   help="Ordered list of paper-run dirs for candidate B (must be index-aligned with A)")
    p.add_argument("--cell-labels", nargs="+", default=None,
                   help="Optional human-readable cell labels (default cell_0, cell_1, ...)")
    p.add_argument("--min-overlap", type=int, default=60,
                   help="Minimum pooled overlap days (default: 60, mirrors Step 5)")
    p.add_argument("--output-json", type=Path, default=None,
                   help="Output JSON path (default: stdout only)")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    result = run_pair_correlation(
        cand_a_id=args.candidate_a_id,
        cand_a_run_dirs=args.candidate_a_run_dirs,
        cand_b_id=args.candidate_b_id,
        cand_b_run_dirs=args.candidate_b_run_dirs,
        cell_labels=args.cell_labels,
        min_overlap=args.min_overlap,
    )

    text = json.dumps(result, indent=2, allow_nan=False)
    print(text)
    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(text)
        print(f"\nWrote machine-readable result to: {args.output_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
