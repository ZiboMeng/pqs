"""Fleet correlation: options NAV vs stock candidate NAV vs SPY.

Path D of post-Phase-1.5 plan. Question: do options sleeves materially
diversify the stock candidate fleet (RCMv1 / Cand-2 / Trial 9 once
forward starts)?

Two scopes:
  (1) ROBUST 33-year scope: options NAV vs SPY (all 4 cells × 8350 days).
      Stock candidates not directly available but correlated with SPY
      ~0.6+ per `docs/memos/20260430-rcmv1_cand2_realized_correlation.md`,
      so options-vs-SPY upper-bounds options-vs-stock-candidate.
  (2) SHORT-WINDOW direct scope: options NAV vs RCMv1+Cand-2 paper NAV
      on overlapping ~154 days (2022-08-26→2022-12-15 + 2024-01-02→
      2024-04-19). Sample noisy but DIRECT.

Trial 9 forward observation just started (TD001 = 2026-05-04 EOD); no
NAV history yet. Trial 9 spec known but recreating its backtest NAV
violates branch isolation (requires stock workstream code). Trial 9
analysis deferred to post-TD20 (2026-06-03 ~1 month in).

Outputs:
  data/options/analysis/fleet_correlation_summary.json
  stdout: markdown digest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJ = Path(__file__).resolve().parents[3]
SNAP_DIR = PROJ / "data" / "options" / "snapshots"
BT_DIR = PROJ / "data" / "options" / "backtest"
ANAL_DIR = PROJ / "data" / "options" / "analysis"

# Stock candidate paper run cells (longest available per cell window)
STOCK_PAPER_CELLS = {
    "rcm_v1": {
        "2022_h2": "data/paper_runs/rcm_v1_defensive_composite_01/20260425T041403Z/pnl_daily.csv",
        "2024_h1": "data/paper_runs/rcm_v1_defensive_composite_01/20260425T041358Z/pnl_daily.csv",
    },
    "cand_2": {
        "2022_h2": "data/paper_runs/candidate_2_orthogonal_01/20260425T041405Z/pnl_daily.csv",
        "2024_h1": "data/paper_runs/candidate_2_orthogonal_01/20260425T041400Z/pnl_daily.csv",
    },
}

OPTIONS_CELLS = ["bull_put", "bear_call", "iron_condor", "signal_driven"]


def _load_options_returns() -> pd.DataFrame:
    out = {}
    for c in OPTIONS_CELLS:
        df = pd.read_parquet(BT_DIR / f"spread_baseline_{c}_nav.parquet"
                             if c != "signal_driven"
                             else BT_DIR / "spread_signal_driven_nav.parquet")
        out[c] = df["nav"].pct_change().dropna()
    return pd.DataFrame(out).dropna()


def _load_spy_returns() -> pd.Series:
    spy = pd.read_parquet(SNAP_DIR / "spy_history.parquet")["close"]
    return spy.pct_change().dropna().rename("spy")


def _load_stock_paper_returns() -> dict[str, pd.DataFrame]:
    """Per-candidate dict of {cell_label: returns Series}."""
    out: dict[str, dict[str, pd.Series]] = {}
    for cand, cells in STOCK_PAPER_CELLS.items():
        out[cand] = {}
        for cell_label, p in cells.items():
            df = pd.read_csv(PROJ / p)
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
            ret = df["ret"] if "ret" in df.columns else df["equity_curve"].pct_change()
            out[cand][cell_label] = ret.dropna().rename(f"{cand}_{cell_label}")
    return out


def _ann_sharpe(ret: pd.Series) -> float:
    if ret.std() == 0 or ret.empty:
        return 0.0
    return float(ret.mean() / ret.std() * np.sqrt(252))


def _max_dd(ret: pd.Series) -> float:
    nav = (1 + ret).cumprod()
    rmax = nav.cummax()
    return float(((nav - rmax) / rmax).min())


def scope_1_options_vs_spy(opt_ret: pd.DataFrame, spy: pd.Series) -> dict:
    """33-year robust scope."""
    df = pd.concat([opt_ret, spy], axis=1, join="inner").dropna()
    corr = df.corr()
    return {
        "n_overlap_days": int(len(df)),
        "window": [str(df.index.min().date()), str(df.index.max().date())],
        "correlation_with_spy": {c: float(corr.loc[c, "spy"]) for c in OPTIONS_CELLS},
        "options_pairwise_corr": corr.loc[OPTIONS_CELLS, OPTIONS_CELLS].round(3).to_dict(),
        "options_individual_sharpe": {c: _ann_sharpe(df[c]) for c in OPTIONS_CELLS},
        "spy_individual_sharpe": _ann_sharpe(df["spy"]),
    }


def _combine_fleet(returns_df: pd.DataFrame, weights: dict) -> dict:
    """Equal/custom weight combo on aligned returns; report Sharpe + DD."""
    cols = [c for c in weights if c in returns_df.columns]
    w = np.array([weights[c] for c in cols])
    w = w / w.sum()
    combo = (returns_df[cols] * w).sum(axis=1)
    return {"weights": dict(zip(cols, w.tolist())),
            "n_days": int(len(combo)),
            "annual_return": float(combo.mean() * 252),
            "annual_vol": float(combo.std() * np.sqrt(252)),
            "sharpe": _ann_sharpe(combo),
            "max_dd": _max_dd(combo)}


def scope_2_short_direct(
    opt_ret: pd.DataFrame, spy: pd.Series,
    stock_ret: dict[str, dict[str, pd.Series]],
) -> dict:
    """Cell-by-cell: pull options + stock cell + SPY for overlapping window;
    pairwise correlation + combined fleet Sharpe."""
    out = {}
    for cell_label in ["2022_h2", "2024_h1"]:
        rcm = stock_ret["rcm_v1"][cell_label]
        cd2 = stock_ret["cand_2"][cell_label]
        # Use overlap
        overlap_idx = rcm.index.intersection(cd2.index).intersection(opt_ret.index)
        if len(overlap_idx) < 20:
            out[cell_label] = {"n": int(len(overlap_idx)), "skipped_too_short": True}
            continue
        r = pd.concat([
            opt_ret.loc[overlap_idx],
            spy.loc[overlap_idx].rename("spy"),
            rcm.loc[overlap_idx].rename("rcm_v1"),
            cd2.loc[overlap_idx].rename("cand_2"),
        ], axis=1).dropna()

        corr_mat = r.corr().round(3)
        cell_out = {
            "window": [str(r.index.min().date()), str(r.index.max().date())],
            "n_days": int(len(r)),
            "individual_sharpe": {c: _ann_sharpe(r[c]) for c in r.columns},
            "individual_max_dd": {c: _max_dd(r[c]) for c in r.columns},
            "stock_vs_options_corr": {
                c: {"rcm_v1": float(corr_mat.loc[c, "rcm_v1"]),
                    "cand_2": float(corr_mat.loc[c, "cand_2"])}
                for c in OPTIONS_CELLS
            },
            "stock_vs_spy_corr": {
                "rcm_v1": float(corr_mat.loc["rcm_v1", "spy"]),
                "cand_2": float(corr_mat.loc["cand_2", "spy"]),
            },
            "rcm_vs_cand2_corr": float(corr_mat.loc["rcm_v1", "cand_2"]),
            "fleet_combos": {},
        }

        # Fleet combos to evaluate
        combos = {
            "stock_only_eq": {"rcm_v1": 1, "cand_2": 1},
            "stock_plus_iron_condor_3way":  {"rcm_v1": 1, "cand_2": 1, "iron_condor": 1},
            "stock_plus_signal_driven_3way":{"rcm_v1": 1, "cand_2": 1, "signal_driven": 1},
            "stock_plus_iron_condor_50_50": {"rcm_v1": 0.25, "cand_2": 0.25, "iron_condor": 0.50},
            "stock_70_options_30":           {"rcm_v1": 0.35, "cand_2": 0.35, "iron_condor": 0.30},
        }
        for combo_name, weights in combos.items():
            cell_out["fleet_combos"][combo_name] = _combine_fleet(r, weights)
        out[cell_label] = cell_out

    return out


def render_md(scope1: dict, scope2: dict) -> str:
    lines = [
        "# Fleet correlation analysis — options sleeves vs stock candidates",
        "",
        "## Scope 1: 33-year robust (options NAV vs SPY)",
        "",
        f"Overlap window: {scope1['window'][0]} → {scope1['window'][1]} "
        f"({scope1['n_overlap_days']} trading days)",
        "",
        "Options-vs-SPY daily-return correlation:",
    ]
    for c, v in scope1["correlation_with_spy"].items():
        lines.append(f"- {c}: **{v:+.3f}**")
    lines.append("")
    lines.append(f"SPY individual Sharpe: {scope1['spy_individual_sharpe']:.2f}")
    lines.append("Options individual Sharpe (33y):")
    for c, v in scope1["options_individual_sharpe"].items():
        lines.append(f"- {c}: {v:.2f}")
    lines.append("")
    lines.append("## Scope 2: Direct overlap with stock candidate paper cells")
    for cell, blk in scope2.items():
        if blk.get("skipped_too_short"):
            lines.append(f"\n### {cell} — SKIPPED (only {blk['n']} overlap days)")
            continue
        lines.append("")
        lines.append(f"### Cell: {cell} ({blk['window'][0]} → {blk['window'][1]}, "
                     f"n={blk['n_days']} days)")
        lines.append("")
        lines.append("Individual Sharpe (annualized, this cell):")
        for c, v in blk["individual_sharpe"].items():
            lines.append(f"- {c}: {v:+.2f}")
        lines.append("")
        lines.append("Stock candidates correlation:")
        lines.append(f"- rcm_v1 vs cand_2: **{blk['rcm_vs_cand2_corr']:+.3f}**")
        lines.append(f"- rcm_v1 vs SPY: {blk['stock_vs_spy_corr']['rcm_v1']:+.3f}")
        lines.append(f"- cand_2 vs SPY: {blk['stock_vs_spy_corr']['cand_2']:+.3f}")
        lines.append("")
        lines.append("Options-vs-stock-candidate correlation:")
        lines.append("")
        lines.append("| Options cell | vs RCMv1 | vs Cand-2 |")
        lines.append("|---|---|---|")
        for c, v in blk["stock_vs_options_corr"].items():
            lines.append(f"| {c} | {v['rcm_v1']:+.3f} | {v['cand_2']:+.3f} |")
        lines.append("")
        lines.append("Fleet combo Sharpes (annualized, this cell):")
        lines.append("")
        lines.append("| Combo | Annual Ret | Annual Vol | Sharpe | Max DD |")
        lines.append("|---|---|---|---|---|")
        for combo_name, m in blk["fleet_combos"].items():
            lines.append(
                f"| {combo_name} | {m['annual_return']*100:+.1f}% | "
                f"{m['annual_vol']*100:.1f}% | {m['sharpe']:+.2f} | "
                f"{m['max_dd']*100:+.1f}% |"
            )
    return "\n".join(lines)


def main() -> int:
    ANAL_DIR.mkdir(parents=True, exist_ok=True)

    print("[fleet] loading options NAV ...")
    opt_ret = _load_options_returns()
    spy_ret = _load_spy_returns()
    print("[fleet] loading stock candidate paper NAV ...")
    stock_ret = _load_stock_paper_returns()

    print("[fleet] scope 1 (33-yr options vs SPY) ...")
    s1 = scope_1_options_vs_spy(opt_ret, spy_ret)

    print("[fleet] scope 2 (cell-by-cell direct overlap) ...")
    s2 = scope_2_short_direct(opt_ret, spy_ret, stock_ret)

    summary = {"scope_1_options_vs_spy_33yr": s1, "scope_2_direct_overlap_cells": s2}
    out = ANAL_DIR / "fleet_correlation_summary.json"
    out.write_text(json.dumps(summary, indent=2, default=str))
    print(f"[fleet] wrote {out}")
    print()
    print(render_md(s1, s2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
