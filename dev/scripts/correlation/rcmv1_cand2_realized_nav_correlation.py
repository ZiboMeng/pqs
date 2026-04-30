"""
RCMv1 vs Cand-2 — historical NAV correlation diagnostic.

External-reviewer-prompted experiment (2026-04-30): Cand-2 was nominated
under a "factor-IC orthogonal" claim that has never been verified at the
NAV / portfolio-return level. With Step 5 C2 correlation budget now
shipped (warn 0.70 / reject 0.85; pairwise on realized candidate daily
returns), we can finally close that loop.

Inputs:
  data/paper_runs/rcm_v1_defensive_composite_01/20260425T041403Z/   (2022-08-26 -> 2022-12-15)
  data/paper_runs/rcm_v1_defensive_composite_01/20260425T041358Z/   (2024-01-02 -> 2024-04-19)
  data/paper_runs/candidate_2_orthogonal_01/20260425T041405Z/        (2022-08-26 -> 2022-12-15)
  data/paper_runs/candidate_2_orthogonal_01/20260425T041400Z/        (2024-01-02 -> 2024-04-19)

These are the latest post-step3b ("honest" data round-3) re-runs of the
two paper cells the candidates were nominated on.

Outputs:
  - prints to stdout
  - dumps machine-readable JSON next to the memo for re-use
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import numpy as np


REPO = Path(__file__).resolve().parents[3]

CELLS = {
    "2022_h2": {
        "rcm_v1": REPO / "data/paper_runs/rcm_v1_defensive_composite_01/20260425T041403Z",
        "cand_2": REPO / "data/paper_runs/candidate_2_orthogonal_01/20260425T041405Z",
    },
    "2024_q1": {
        "rcm_v1": REPO / "data/paper_runs/rcm_v1_defensive_composite_01/20260425T041358Z",
        "cand_2": REPO / "data/paper_runs/candidate_2_orthogonal_01/20260425T041400Z",
    },
}


def load_pnl(run_dir: Path) -> pd.DataFrame:
    p = run_dir / "pnl_daily.csv"
    df = pd.read_csv(p, parse_dates=["date"]).set_index("date").sort_index()
    return df[["ret"]].rename(columns={"ret": "ret"})


def load_benchmark(run_dir: Path) -> pd.DataFrame:
    p = run_dir / "benchmark_relative_paper.csv"
    df = pd.read_csv(p, parse_dates=["date"]).set_index("date").sort_index()
    spy_d = df["SPY_cum_ret"].diff().fillna(df["SPY_cum_ret"]).rename("spy_ret_d")
    qqq_d = df["QQQ_cum_ret"].diff().fillna(df["QQQ_cum_ret"]).rename("qqq_ret_d")
    return pd.concat([spy_d, qqq_d], axis=1)


def load_positions(run_dir: Path) -> pd.DataFrame | None:
    p = run_dir / "target_portfolio_daily.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p, parse_dates=["date"])
    return df


def _empty_diagnostic(cell: str, n: int, reason: str) -> dict:
    """Return a structured diagnostic indicating insufficient data.

    Used when the joined frame has zero or one row, or when pearson is
    non-finite (zero variance). Downstream JSON consumers should not
    receive silent NaN.
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
        "max_dd": {"rcm_v1": None, "cand_2": None},
        "pct_days_both_in_dd": None,
        "holdings_overlap_jaccard_avg": None,
        "holdings_top10_overlap_last": None,
        "beta_to_qqq": {"rcm_v1": None, "cand_2": None},
        "beta_to_spy": {"rcm_v1": None, "cand_2": None},
    }


def cell_diagnostics(cell: str, rcm_dir: Path, cand_dir: Path) -> dict:
    rcm = load_pnl(rcm_dir).rename(columns={"ret": "rcm_v1"})
    cnd = load_pnl(cand_dir).rename(columns={"ret": "cand_2"})
    bmk = load_benchmark(rcm_dir)

    df = pd.concat([rcm, cnd, bmk], axis=1).dropna()
    n = len(df)

    # Boundary guards: pearson requires n >= 2 with non-zero variance;
    # downstream date-range / drawdown / holdings computations require
    # n >= 1. Zero-variance series (constant returns) yield NaN pearson
    # — surface as insufficient_data, not silent NaN.
    if n == 0:
        return _empty_diagnostic(cell, n=0, reason="zero overlap rows after dropna")
    if n < 2:
        return _empty_diagnostic(cell, n=n, reason=f"only {n} overlap row(s); pearson undefined for n<2")

    # 1. unconditional correlation. Guard against constant-series
    # warnings from scipy (spearman) and numpy (pearson divide).
    import warnings
    with np.errstate(invalid="ignore", divide="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        try:
            from scipy.stats import ConstantInputWarning  # type: ignore[import-not-found]
            warnings.simplefilter("ignore", category=ConstantInputWarning)
        except ImportError:  # scipy not available or older version
            pass
        pearson = float(df["rcm_v1"].corr(df["cand_2"]))
        spearman = float(df["rcm_v1"].corr(df["cand_2"], method="spearman"))
    if not np.isfinite(pearson):
        return _empty_diagnostic(
            cell, n=n,
            reason=f"pearson non-finite ({pearson}) — zero variance in at least one series",
        )

    # 2. down-market conditional correlation (SPY day < -0.5%)
    down_mask = df["spy_ret_d"] < -0.005
    n_down = int(down_mask.sum())
    if n_down >= 5:
        down_corr = float(df.loc[down_mask, "rcm_v1"].corr(df.loc[down_mask, "cand_2"]))
    else:
        down_corr = None

    # 3. up-market conditional
    up_mask = df["spy_ret_d"] > 0.005
    n_up = int(up_mask.sum())
    if n_up >= 5:
        up_corr = float(df.loc[up_mask, "rcm_v1"].corr(df.loc[up_mask, "cand_2"]))
    else:
        up_corr = None

    # 4. rolling 30d correlation (corr of one series against the other)
    roll = df["rcm_v1"].rolling(30).corr(df["cand_2"]).dropna()
    roll_min = float(roll.min()) if len(roll) else None
    roll_max = float(roll.max()) if len(roll) else None
    roll_mean = float(roll.mean()) if len(roll) else None

    # 5. drawdown overlap — days both candidates in DD from cell-start peak
    eq_rcm = (1 + df["rcm_v1"]).cumprod()
    eq_cnd = (1 + df["cand_2"]).cumprod()
    dd_rcm = eq_rcm / eq_rcm.cummax() - 1
    dd_cnd = eq_cnd / eq_cnd.cummax() - 1
    both_in_dd = ((dd_rcm < -0.001) & (dd_cnd < -0.001)).sum()
    pct_both_dd = float(both_in_dd / n)
    rcm_max_dd = float(dd_rcm.min())
    cnd_max_dd = float(dd_cnd.min())

    # 6. holdings overlap — average across all days where both candidates
    # are invested. target_portfolio_daily.csv is wide (symbol-per-column).
    pos_rcm = load_positions(rcm_dir)
    pos_cnd = load_positions(cand_dir)
    holdings_overlap_jaccard_avg = None
    holdings_top10_overlap_last = None
    if pos_rcm is not None and pos_cnd is not None:
        rcm_w = pos_rcm.set_index("date")
        cnd_w = pos_cnd.set_index("date")
        common_dates = rcm_w.index.intersection(cnd_w.index)
        jaccards: list[float] = []
        for d in common_dates:
            rcm_set = set(rcm_w.columns[(rcm_w.loc[d] > 0)])
            cnd_set = set(cnd_w.columns[(cnd_w.loc[d] > 0)])
            if not rcm_set and not cnd_set:
                continue
            jaccards.append(len(rcm_set & cnd_set) / max(len(rcm_set | cnd_set), 1))
        if jaccards:
            holdings_overlap_jaccard_avg = float(np.mean(jaccards))

        last_date = df.index.max()
        if last_date in rcm_w.index and last_date in cnd_w.index:
            rcm_last = rcm_w.loc[last_date]
            cnd_last = cnd_w.loc[last_date]
            rcm_top = set(rcm_last.nlargest(10).index[rcm_last.nlargest(10) > 0])
            cnd_top = set(cnd_last.nlargest(10).index[cnd_last.nlargest(10) > 0])
            holdings_top10_overlap_last = len(rcm_top & cnd_top)

    # 7. beta-to-QQQ for each
    beta_rcm_qqq = float(df["rcm_v1"].cov(df["qqq_ret_d"]) / df["qqq_ret_d"].var())
    beta_cnd_qqq = float(df["cand_2"].cov(df["qqq_ret_d"]) / df["qqq_ret_d"].var())
    beta_rcm_spy = float(df["rcm_v1"].cov(df["spy_ret_d"]) / df["spy_ret_d"].var())
    beta_cnd_spy = float(df["cand_2"].cov(df["spy_ret_d"]) / df["spy_ret_d"].var())

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
            "rcm_v1": rcm_max_dd,
            "cand_2": cnd_max_dd,
        },
        "pct_days_both_in_dd": pct_both_dd,
        "holdings_overlap_jaccard_avg": holdings_overlap_jaccard_avg,
        "holdings_top10_overlap_last": holdings_top10_overlap_last,
        "beta_to_qqq": {"rcm_v1": beta_rcm_qqq, "cand_2": beta_cnd_qqq},
        "beta_to_spy": {"rcm_v1": beta_rcm_spy, "cand_2": beta_cnd_spy},
    }


def combined_diagnostics(per_cell: list[dict], cells: dict) -> dict:
    """Pool both cells (concat returns, ignoring time gap) for an aggregate
    correlation. The gap between 2022-12 and 2024-01 is treated as a
    discontinuity (no synthetic returns inserted).

    Returns insufficient_data status if pooled pearson cannot be
    computed (n<2 or zero variance).
    """
    frames = []
    for cell, paths in cells.items():
        rcm = load_pnl(paths["rcm_v1"]).rename(columns={"ret": "rcm_v1"})
        cnd = load_pnl(paths["cand_2"]).rename(columns={"ret": "cand_2"})
        df = pd.concat([rcm, cnd], axis=1).dropna()
        df = df.assign(cell=cell)
        frames.append(df)
    pooled = pd.concat(frames).sort_index() if frames else pd.DataFrame(columns=["rcm_v1", "cand_2"])
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
        pearson = float(pooled["rcm_v1"].corr(pooled["cand_2"]))
        spearman = float(pooled["rcm_v1"].corr(pooled["cand_2"], method="spearman"))
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


def classify(corr: float | None) -> str:
    if corr is None:
        return "insufficient_data"
    if corr < 0.40:
        return "true_diversifier"
    if corr < 0.70:
        return "partial_diversifier"
    if corr < 0.85:
        return "warn_label_void"
    return "reject_step5"


def main() -> None:
    per_cell = [cell_diagnostics(c, paths["rcm_v1"], paths["cand_2"]) for c, paths in CELLS.items()]
    pooled = combined_diagnostics(per_cell, CELLS)

    out = {
        "experiment": "rcmv1_vs_cand2_historical_nav_correlation",
        "as_of": "2026-04-30",
        "step5_thresholds": {
            "warn": 0.70,
            "reject": 0.85,
            "min_overlap_days": 60,
        },
        "diversifier_threshold_temporal_split_yaml": 0.40,
        "per_cell": per_cell,
        "pooled": pooled,
        "classification_pooled": classify(pooled["pearson_corr_pooled"]),
        "classification_per_cell": [
            {"cell": c["cell"], "label": classify(c["pearson_corr"])}
            for c in per_cell
        ],
    }

    out_dir = REPO / "data" / "memos"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "20260430_rcmv1_cand2_realized_correlation.json"
    # allow_nan=False forces explicit insufficient_data handling above —
    # any silent NaN slipping into the output here is a bug (R4 audit
    # 2026-04-30).
    out_path.write_text(json.dumps(out, indent=2, allow_nan=False))

    print(json.dumps(out, indent=2, allow_nan=False))
    print()
    print(f"Wrote machine-readable result to: {out_path}")


if __name__ == "__main__":
    main()
