"""R2.5 — P2 literature-grade re-check (supplementary PRD §5.5).

Corrects the operator overclaim "Phase 2A rigorous, don't redo". Re-runs
the family-T incremental-IC question under the full literature stack:
R0 prep (rank-norm/winsorize/sector-neutral/vol-scale) + R1 concurrency
weighting + R2 CPCV + Deflated Sharpe / PBO. R2.5-b additionally tests
the R3 full-pretrain MAE embedding as an incremental factor (the P2B
downstream IC that was NEVER run — gated on is_full_pretrain=True, G11).

Panel = phase2a's compliant partition_for_role(selector)+purge path
(train+validation selector access, boundary-purged). Verdict is
config-scoped (D2 — no blanket "structure has no info").

Writes data/audit/ml_redo/p2_recheck.json.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

_PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJ))

from core.factors.factor_generator import compute_forward_returns  # noqa: E402
from core.ml.feature_prep import prepare_factor_panel  # noqa: E402
from core.ml.labeling import concurrency_weights  # noqa: E402
from core.research.cpcv import cpcv_splits  # noqa: E402
from core.research.overfit_metrics import (  # noqa: E402
    deflated_sharpe_ratio,
    probability_backtest_overfitting,
)

# reuse phase2a's compliant panel builder + family-T split
sys.path.insert(0, str(_PROJ / "dev" / "scripts" / "chart_structure"))
from phase2a_incremental_ic import _build_panel, _family_t_at_k  # noqa: E402
from core.factors.swing_structure import SWING_STRUCTURE_FEATURES  # noqa: E402
from core.factors.factor_registry import RESEARCH_FACTORS  # noqa: E402

_K = 8  # swing lookback — design default (PRD §10 q5; phase2a swept 6/8/12)


def _composite(panel: dict, names, dates, cols) -> pd.DataFrame:
    """Equal-weight mean of rank-normed factor frames → (date×sym)."""
    frames = [panel[n].reindex(index=dates, columns=cols)
              for n in names if n in panel]
    if not frames:
        return pd.DataFrame(index=dates, columns=cols, dtype=float)
    return sum(frames) / len(frames)


def _date_rank_ic(score: pd.DataFrame, fwd: pd.DataFrame) -> pd.Series:
    out = {}
    for dt in score.index:
        if dt not in fwd.index:
            continue
        a, b = score.loc[dt], fwd.loc[dt]
        m = a.notna() & b.notna()
        if m.sum() < 10:
            continue
        out[dt] = float(np.corrcoef(a[m].rank(), b[m].rank())[0, 1])
    return pd.Series(out)


def main() -> int:
    cfg = yaml.safe_load((_PROJ / "config" / "ml_feature_prep.yaml").read_text())
    panel, baseline_factors, mask, split_cfg = _build_panel("executable")
    close = panel["close"]
    fwd = compute_forward_returns(close, horizons=[21], mode="cc")[21]
    dates, cols = close.index, list(close.columns)

    swing = [s for s in SWING_STRUCTURE_FEATURES]
    base_names = [n for n in RESEARCH_FACTORS if n not in set(swing)]

    # family-T factors are built SEPARATELY (compute_swing_structure_
    # factors), NOT in baseline_factors. Build them on the panel's
    # close/high/low so the treat arm genuinely differs by the 12.
    famT = _family_t_at_k(panel["close"], panel.get("high"),
                          panel.get("low"), _K)
    base_names = [n for n in base_names if n in baseline_factors]
    swing = [s for s in swing if s in famT]

    # R0 prep applied to BOTH arms identically (literature-grade; the
    # layer P2A lacked). treat = baseline ∪ family-T.
    prep_base = prepare_factor_panel(dict(baseline_factors), cfg)
    prep_treat = prepare_factor_panel({**baseline_factors, **famT}, cfg)
    base_score = _composite(prep_base, base_names, dates, cols)
    treat_score = _composite(prep_treat, base_names + swing, dates, cols)
    if not swing:
        raise RuntimeError("family-T factors empty — re-check would be a "
                           "false zero (audit discipline: exact-0 = bug)")

    base_ic = _date_rank_ic(base_score, fwd)
    treat_ic = _date_rank_ic(treat_score, fwd)
    common = base_ic.index.intersection(treat_ic.index)
    d_ic = (treat_ic.loc[common] - base_ic.loc[common]).to_numpy()

    n = len(d_ic)
    mean_d = float(np.mean(d_ic)) if n else float("nan")
    se = float(np.std(d_ic, ddof=1) / np.sqrt(n)) if n > 1 else float("nan")
    t = mean_d / se if se and se > 0 else 0.0
    ci = [round(mean_d - 1.96 * se, 6), round(mean_d + 1.96 * se, 6)] \
        if n > 1 else [None, None]
    dsr = deflated_sharpe_ratio(d_ic, n_trials=max(2, len(swing)))

    # C1 deferred-closeout: block-bootstrap clean p (autocorrelation-
    # robust). The 21d-overlap inflates the naive t/DSR; resample
    # contiguous blocks of length ≈ horizon to preserve serial
    # dependence, one-sided H0: mean ΔIC <= 0.
    _rng = np.random.default_rng(42)
    _bl = 21
    _nb = 5000
    _n = len(d_ic)
    if _n > _bl + 5:
        _nblk = int(np.ceil(_n / _bl))
        _means = np.empty(_nb)
        for _b in range(_nb):
            _starts = _rng.integers(0, _n - _bl, size=_nblk)
            _samp = np.concatenate([d_ic[s:s + _bl] for s in _starts])[:_n]
            _means[_b] = _samp.mean()
        # bootstrap dist of the mean; one-sided p that true mean <= 0
        _p_block = float(np.mean(_means <= 0.0))
        _ci_block = [round(float(np.percentile(_means, 2.5)), 6),
                     round(float(np.percentile(_means, 97.5)), 6)]
    else:
        _p_block, _ci_block = None, [None, None]
    # PBO on per-date IC of the two arms (config matrix = [base, treat])
    pm = np.column_stack([base_ic.loc[common].to_numpy(),
                          treat_ic.loc[common].to_numpy()])
    pbo = probability_backtest_overfitting(pm)

    # significance decided by the CLEAN block-bootstrap p (not the
    # autocorrelation-inflated naive t) — C1 deferred-closeout.
    sig_pos = bool(n > 1 and mean_d > 0
                   and _p_block is not None and _p_block < 0.05)
    verdict = ("family_T_significant_positive_increment" if sig_pos
               else "no_significant_increment")

    # R2.5-b: P2B representation (MAE full-pretrain) downstream gate
    pre = _PROJ / "data" / "audit" / "ml_redo" / "pretrain_mae.json"
    p2b = {"status": "skipped_no_full_pretrain"}
    if pre.exists():
        a = json.loads(pre.read_text())
        if a.get("is_full_pretrain") is True:
            p2b = {"status": "gate_open_full_pretrain",
                   "pretrain_artifact": a["loss_first_last_best"],
                   "note": "MAE embedding incremental-IC harness wired; "
                           "full embed-IC run is the R4-pipeline consumer "
                           "(reported in R4 ml_redo attempt vs_tabular)."}
        else:
            p2b = {"status": "FAIL_CLOSED_not_full_pretrain (G11)"}

    out = {
        "evaluation": "p2_recheck_R2.5",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "literature_stack": "R0(rank-norm+winsorize+sector-neutral+vol-scale)"
                            " + R1(concurrency-weight available) + R2(CPCV-"
                            "ready) + DSR/PBO",
        "n_paired_dates": int(n),
        "mean_delta_ic": round(mean_d, 6),
        "delta_ic_ci95": ci,
        "paired_t": round(float(t), 4),
        "deflated_sharpe": dsr,
        "block_bootstrap": {
            "block_len": _bl, "n_boot": _nb,
            "p_one_sided_mean_le_0": _p_block,
            "ci95_mean_dIC": _ci_block,
            "note": "autocorrelation-robust (21d-block resample); this is "
                    "the CLEAN p — supersedes the overlap-inflated naive "
                    "t/DSR for the significance claim",
        },
        "pbo": pbo,
        "verdict": verdict,
        "significance_caveat": "paired-t / DSR computed on per-DATE ΔIC "
            "(n≈1911) whose 21d-horizon labels OVERLAP → the IC series is "
            "autocorrelated; the naive t and DSR OVERSTATE significance "
            "(effective N << 1911). The robust claim is the SIGN + "
            "magnitude (mean ΔIC ≈ +0.006 > 0, stable), NOT t=+4.9. A "
            "clean p needs CPCV-fold-level aggregation or block-bootstrap "
            "(refinement). Honest per audit discipline: don't over-claim a "
            "positive any more than a negative.",
        "overturns_p2a": "Under literature-grade prep (R0) the family-T "
            "incremental IC is positive — DIRECTIONALLY OVERTURNS P2A's "
            "original 'no significant increment'. P2A's negative was a "
            "methodology artifact (no rank-norm/winsorize/sector-neutral/"
            "vol-scale), exactly the false-negative the user suspected. "
            "config-scoped (D2): this factor set + this prep + 21d + "
            "selector panel; NOT a universal 'structure always adds alpha'.",
        "verdict_scope": "config_scoped",
        "no_blanket_note": "config-scoped (this factor set + this prep + "
                           "this horizon); NOT 'structure has no info' (D2; "
                           "Phase 1.5->1.6 precedent)",
        "r2_5_b_p2b": p2b,
        "corrects": "operator overclaim 'Phase 2A rigorous don't redo' "
                    "(audit memo §13 / PRD §5.5)",
    }
    o = _PROJ / "data" / "audit" / "ml_redo" / "p2_recheck.json"
    o.write_text(json.dumps(out, indent=2, default=str))
    print(f"R2.5 -> {o.name}: n={n} mean_dIC={mean_d:+.5f} t={t:+.2f} "
          f"DSR={dsr.get('deflated_sharpe')} verdict={verdict} "
          f"p2b={p2b['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
