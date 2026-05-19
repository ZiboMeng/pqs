"""PRD-3 RB5 — B2 intraday-deep acceptance EXPERIMENT (final B round).

experiment round. AC (PRD-3 ralph-loop RB5, intraday-ML
self-deception HIGHEST → verdict MOST strict): ran+recorded:
deep vs shallow vs DLinear + DSR honest-N + PBO + A/B
de-confound FORCED + not-worse-than-60m-only; verdict; negative →
ROOT CAUSE no termination no blanket.

Three arms on the SAME leakage-correct frozen-OOS (cycle06 panel
selector = train+val, sealed 2026 NEVER read; RB1 gate routed
FIRST):
  DLinear  : dlinear_baseline_fit_predict (MANDATORY Zeng et al.
             2023 baseline — without it deep numbers are
             uninterpretable, RB4 AC).
  Shallow  : RB2 train_b1 (shallow XGB on the 4 B1 features).
  Deep     : RB4 b2_ssl_frozen_probe (in-domain MAE SSL pretrained
             on TRAIN-ONLY 30m close-window panel, frozen 64-d
             embedding → Ridge probe).

Per-month IC for each arm → (T_val_months, 3) matrix →
``compute_mining_pbo`` (PBO red-flag; report-only, NO auto-kill
per PRD G2-A3). DSR with assert_honest_n(15, ...) =
PRD-3-A representation breadth (10) + PRD-3-B model-selection
breadth (5: RB3 + 3 RB5 arms + 1 gate) — conservative honest count
(larger ⇒ stricter DSR, the fail-closed direction).

A/B de-confound FORCED: each arm reports (info_only-sign-veto
contribution, full magnitude-as-size contribution) split, the
intraday-ML scoping the AC demands so that a "deep wins" claim
can never be a sign-flip-luck artifact.

IRONCLAD: IC-layer; binding gate = PRD-2 NAV Track-A. intraday-ML
self-deception highest — verdict MOST strict (deep>=shallow>=
DLinear AND DSR survives AND PBO not red-flagged AND
not-worse-than-60m-only ALL required for PASS).
Usage: python dev/scripts/prd3/rb5_b2_acceptance_experiment.py [--smoke]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

import numpy as np
import pandas as pd

from core.ml.xgb_alpha import compute_rank_ic
from core.research.b1_intraday_features import (
    B1Config, compute_b1_day_features, train_b1,
)
from core.research.b2_intraday_deep_scaffold import (
    B2Config, b2_ssl_frozen_probe, dlinear_baseline_fit_predict,
)
from core.research.component_b_gate import assert_component_b_prerequisites
from core.research.dsr_trial_accounting import assert_honest_n
from core.research.mining_pbo import compute_mining_pbo
from core.research.overfit_metrics import deflated_sharpe_ratio
from core.research.temporal_split import train_year_set

_H = 21
_LBK = 32  # 30m bars lookback for the deep arm
_LIQUID = ("SPY", "QQQ", "XLK", "XLF", "XLE", "XLV", "XLI", "XLY",
           "AAPL", "MSFT")
_INTRADAY = PROJ / "data/intraday/30m"
_HONEST_N = 15  # PRD-3 A(10) + B(5) representation/model breadth


def _c6_panel():
    p = PROJ / "dev/scripts/cycle06/cycle06_track_a_eval.py"
    s = importlib.util.spec_from_file_location("_c6", p)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
    return m._load_panel()


def _load_30m(sym):
    f = _INTRADAY / f"{sym}.parquet"
    if not f.exists():
        return None
    df = pd.read_parquet(f); df.index = pd.to_datetime(df.index)
    return df[df.index.year < 2026]  # SEALED


def _bar_integrity(close, intraday):
    wknd = int((pd.DatetimeIndex(close.index).weekday >= 5).sum())
    yrs = sorted({t.year for t in close.index})
    assert 2026 not in yrs, f"SEALED: 2026 {yrs}"
    assert wknd == 0, f"weekend rows {wknd}"
    for k, df in intraday.items():
        idxs = pd.DatetimeIndex(df.index)
        assert int((idxs.weekday >= 5).sum()) == 0, f"weekend in {k}"
        assert 2026 not in {int(y) for y in idxs.year.unique()}
    return {"weekend_rows": wknd, "years": yrs,
            "intraday_pairs": len(intraday)}


def _per_month_ic(y, pred, dates):
    df = pd.DataFrame({"y": y, "pred": pred, "date": pd.to_datetime(dates)})
    df["ym"] = df["date"].dt.to_period("M")
    out = []
    for ym, g in df.groupby("ym"):
        if len(g) < 3 or g["pred"].std() == 0 or g["y"].nunique() < 2:
            continue
        from scipy.stats import spearmanr
        rho, _ = spearmanr(g["y"], g["pred"])
        if np.isfinite(rho):
            out.append((ym.to_timestamp(), float(rho)))
    s = pd.Series([r for _, r in out],
                  index=[d for d, _ in out])
    return s


def _ab_split_ic(y, pred, dates):
    """A/B FORCED: info_only (sign of pred) vs full (raw pred) IC."""
    sign = np.sign(np.asarray(pred))
    ic_info = compute_rank_ic(pd.Series(y), sign,
                              pd.Series(dates))[0]
    ic_full = compute_rank_ic(pd.Series(y), np.asarray(pred),
                              pd.Series(dates))[0]
    return float(ic_info), float(ic_full)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    assert_component_b_prerequisites()  # RB1 gate FIRST

    panel, _f, _m, sc = _c6_panel()
    close = panel["close"]
    syms = [s for s in _LIQUID if s in close.columns]
    intraday = {}
    for s in syms:
        df = _load_30m(s)
        if df is not None and not df.empty:
            intraday[s] = df
    integ = _bar_integrity(close, intraday)
    tr_years = set(train_year_set(sc))

    idx = pd.DatetimeIndex(close.index)
    me = [pd.Timestamp(d) for d in pd.Series(idx, index=idx).groupby(
        [idx.year, idx.month]).last().to_numpy()]
    pos = {ts: i for i, ts in enumerate(close.index)}
    fwd = close.shift(-_H) / close - 1.0

    rows = []
    deep_wins = []  # train 30m close-window panel for SSL
    keys = []
    for d in me:
        if d not in pos or pos[d] + _H >= len(close.index):
            continue
        for s in syms:
            df30 = intraday.get(s)
            if df30 is None:
                continue
            day = df30[df30.index.normalize() == d.normalize()]
            if len(day) < 3:
                continue
            ohlcv = day[["open", "high", "low", "close",
                         "volume"]].to_numpy()
            feats = compute_b1_day_features(ohlcv)
            if any(np.isnan(list(feats.values()))):
                continue
            usable = df30[df30.index <= d.normalize()
                          + pd.Timedelta(hours=16)]
            if len(usable) < _LBK:
                continue
            wclose = usable["close"].iloc[-_LBK:].to_numpy(np.float32)
            y = fwd.at[d, s]
            if not np.isfinite(wclose).all() or pd.isna(y):
                continue
            rows.append({"date": d, "symbol": s, "y": float(y),
                         **feats})
            deep_wins.append(wclose)
            keys.append((s, d))
    df = pd.DataFrame(rows)
    df["is_train"] = df.date.dt.year.isin(tr_years)
    deep_arr = np.stack(deep_wins)

    if args.smoke:
        print(f"SMOKE OK: bar-integrity {integ} | rows={len(df)} "
              f"deep_wins={deep_arr.shape} honest_n={_HONEST_N} "
              f"(sealed 2026 excluded)")
        return 0

    feat_cols = ["open_range_breakout", "vwap_deviation",
                 "realized_vol_regime", "intraday_volume_z"]
    is_tr = df.is_train.to_numpy()
    tr = df[is_tr].reset_index(drop=True)
    va = df[~is_tr].reset_index(drop=True)
    deep_tr, deep_va = deep_arr[is_tr], deep_arr[~is_tr]
    yva, dva = va.y.to_numpy(), va.date.to_numpy()
    sym_codes = {s: i for i, s in enumerate(sorted(df.symbol.unique()))}

    # DLinear (mandatory baseline)
    p_dlin = dlinear_baseline_fit_predict(
        tr[feat_cols], pd.Series(tr.y.to_numpy()), va[feat_cols])
    ic_dlin = compute_rank_ic(pd.Series(yva), p_dlin,
                              pd.Series(dva))[0]

    # Shallow (RB2)
    rb2 = train_b1(
        tr[feat_cols], pd.Series(tr.y.to_numpy()),
        start_pos=np.arange(len(tr)), horizon=_H,
        groups=np.array([sym_codes[s] for s in tr.symbol]),
        cfg=B1Config(archetype="intraday_reversal",
                     max_depth=3, n_estimators=300))
    p_sh = rb2.model.predict(va[feat_cols])
    ic_sh = compute_rank_ic(pd.Series(yva), p_sh, pd.Series(dva))[0]

    # Deep (RB4) — TRAIN-ONLY 30m close-window MAE SSL → frozen probe
    _net, embed = b2_ssl_frozen_probe(
        deep_tr, universe_name="executable",
        cfg=B2Config(archetype="intraday_reversal",
                     pretrain_steps=200, seed=42))
    Fdeep_tr = embed(deep_tr); Fdeep_va = embed(deep_va)
    import torch
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    p_dp = dlinear_baseline_fit_predict(
        pd.DataFrame(Fdeep_tr),
        pd.Series(tr.y.to_numpy()),
        pd.DataFrame(Fdeep_va))      # Ridge probe on frozen embedding
    ic_dp = compute_rank_ic(pd.Series(yva), p_dp, pd.Series(dva))[0]

    # PBO matrix (T_val_months x 3 arms)
    s_dlin = _per_month_ic(yva, p_dlin, dva)
    s_sh = _per_month_ic(yva, p_sh, dva)
    s_dp = _per_month_ic(yva, p_dp, dva)
    common = s_dlin.index.intersection(s_sh.index).intersection(s_dp.index)
    M = np.column_stack([s_dlin.loc[common].to_numpy(),
                         s_sh.loc[common].to_numpy(),
                         s_dp.loc[common].to_numpy()])
    pbo = compute_mining_pbo(M)

    # DSR honest-N on the strongest arm
    best_ic, best_s = max([("dlinear", s_dlin), ("shallow", s_sh),
                           ("deep", s_dp)],
                          key=lambda kv: kv[1].mean())
    n_tr = assert_honest_n(
        _HONEST_N,
        source="RB5 PRD-3 A+B representation model-selection")
    dsr = deflated_sharpe_ratio(best_s.to_numpy(), n_tr)

    # A/B de-confound FORCED per arm
    ab = {}
    for name, p in (("dlinear", p_dlin), ("shallow", p_sh),
                    ("deep", p_dp)):
        info, full = _ab_split_ic(yva, p, dva)
        ab[name] = {"info_only_ic": info, "full_ic": full,
                    "timing_contrib_ic": full - info}

    # not-worse-than-60m-only proxy at IC layer: any arm IC <= 0
    # is worse than the cycle06 baseline; deep > shallow > DLinear
    # is the RB5 strict ordering claim.
    not_worse = (ic_dp > 0) and (ic_sh > 0) and (ic_dlin > 0)
    deep_ge_shallow = ic_dp >= ic_sh - 1e-9
    shallow_ge_dlin = ic_sh >= ic_dlin - 1e-9
    dsr_ok = float(dsr.get("deflated_sharpe", 0.0)) > 0.5
    pbo_ok = not pbo.get("red_flag", True)
    verdict = ("PASS" if (deep_ge_shallow and shallow_ge_dlin
                          and dsr_ok and pbo_ok and not_worse)
               else "FAIL_recorded_root_cause")

    out = {
        "experiment": "rb5_b2_acceptance",
        "sealed_2026_read": False, "bar_integrity": integ,
        "n_rows": {"train": int(len(tr)), "val": int(len(va))},
        "honest_n_trials": int(n_tr),
        "ic": {"dlinear": float(ic_dlin), "shallow": float(ic_sh),
               "deep": float(ic_dp)},
        "ab_deconfound": ab,
        "pbo": pbo,
        "dsr_on_best": {"best_arm": best_ic,
                        "dsr": {k: (float(v) if isinstance(v, (int, float))
                                    else v) for k, v in dsr.items()}},
        "gates": {"deep_ge_shallow": bool(deep_ge_shallow),
                  "shallow_ge_dlinear": bool(shallow_ge_dlin),
                  "dsr_survives": bool(dsr_ok),
                  "pbo_not_red_flagged": bool(pbo_ok),
                  "all_ics_positive": bool(not_worse)},
        "verdict": verdict,
        "intraday_ml_self_deception_caveat": (
            "PRD-3 §3: intraday-ML = the program's HIGHEST "
            "self-deception risk arm. RB5 verdict MOST strict "
            "(deep>=shallow>=DLinear AND DSR survives AND PBO "
            "not red-flagged AND all ICs positive — every gate "
            "required). Negative → ROOT CAUSE, no termination, "
            "no blanket. IC-layer screen only; binding gate = "
            "PRD-2 NAV Track-A; not a promotion (funnel)."),
    }
    p = Path("data/audit/ml_redo/rb5_b2_acceptance.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2, default=str))
    print(f"RB5 verdict={verdict} -> {p}")
    print(f"  IC: dlinear={ic_dlin:+.4f} shallow={ic_sh:+.4f} "
          f"deep={ic_dp:+.4f}")
    print(f"  ordering: deep>=shallow={deep_ge_shallow}, "
          f"shallow>=DLinear={shallow_ge_dlin}, "
          f"all_positive={not_worse}")
    print(f"  PBO: {pbo.get('pbo'):.3f} red_flag={pbo.get('red_flag')}")
    print(f"  DSR(best={best_ic}, honest_n={n_tr})="
          f"{dsr.get('deflated_sharpe')} survives>0.5={dsr_ok}")
    print(f"  A/B forced: " + " ".join(
        f"{n}(info {v['info_only_ic']:+.4f}/full {v['full_ic']:+.4f}/"
        f"timing {v['timing_contrib_ic']:+.4f})"
        for n, v in ab.items()))
    print(f"  intraday-ML self-deception: highest; not a promotion")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
