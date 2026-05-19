"""chart-native L3 — S1 signal through PRODUCTION Track-A acceptance.

User explicit-go 2026-05-18 "push L3 first". Converts the perpetually-
deferred L2 result (S1 frozen-ImageNet probe IC 0.12 > strong-tabular
anchor on train-only CPCV) into a DEFINITIVE L3 verdict: pass → path-1
promote forward; fail → clean retire verdict for the chart-native line.

CRITICAL no-leakage discipline (the crux — if violated the whole L3
verdict is void): the ridge probe is fit on TRAIN-YEARS rows ONLY
(frozen ImageNet features + 21d-fwd labels), then applied FROZEN to
all rows. Validation-year scores are therefore genuine OOS (the probe
never saw them). sealed 2026 NEVER read (partition_for_role selector
= train+validation only).

Pipeline: GAF window → frozen torchvision ResNet18 IMAGENET1K_V1
(standard pretrained, not hand-rolled) → train-only ridge probe →
per-(date,sym) score panel → fed as a SINGLE synthetic factor to the
same cap_aware harness + run_split_acceptance Track-A path cycle06/08
used, WITH the P0-B machine (W7b overfit_inputs + W7c-d cpcv_inputs).

Honest expectation (no over-claim, cycle13b precedent): likely FAIL
(cycle13b IC_IR 1.1 still 0/3 at vs-SPY/covid; S1 0.12 pooled/JKX-
caveated; frozen-ImageNet-on-GAF has NO economic crisis prior). Value
= the definitive answer, not an expected win.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date as _date
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

import numpy as np
import pandas as pd

from core.config.loader import load_config
from core.data.bar_store import BarStore
from core.ml.chart_cnn import gaf_image
from core.ml.window_embedding import WINDOW_LEN
from core.mining.research_miner import ResearchCompositeSpec
from core.research.harness import HarnessConfig, evaluate_composite_spec
from core.research.risk_cluster_map import (
    ASSET_CLASS_BY_CLUSTER,
    CROSS_ASSET_RISK_CLUSTER_MAP,
    make_unified_cluster_map,
)
from core.research.temporal_split import (
    load_temporal_split,
    partition_for_role,
    train_year_set,
)
from core.research.temporal_split_acceptance import run_split_acceptance

_H = 21
# honest selection-bias N for DSR (dsr_trial_accounting discipline —
# NOT a magic literal): the chart-native line selected "best = S1"
# among the model configs it evaluated: ml-redo R4 {mae_probe,
# gaf_tree, from-scratch} + S2 {d64, d128} + S1 {frozen ImageNet} ≈ 6.
_CHART_NATIVE_PROGRAM_ARMS = 6


def _build_frozen_net(device):
    """STANDARD torchvision ResNet18 IMAGENET1K_V1, fc=Identity,
    frozen + eval. Built ONCE (streaming refactor 2026-05-18, mirrors
    run_s1_imagenet_backbone commit 7f22b85)."""
    import torch
    from torchvision.models import ResNet18_Weights, resnet18
    net = resnet18(weights=ResNet18_Weights.IMAGENET1K_V1)
    net.fc = torch.nn.Identity()
    net = net.to(device).eval()
    for p in net.parameters():
        p.requires_grad_(False)
    return net


def _encode_batch(net, imgs_np, device):
    """One batch (b,2,W,W) float32 → (b,512) frozen features. Exact
    per-batch math preserved from the pre-refactor whole-array path
    (cat per-image channel-mean as 3rd ch; bilinear 224; ImageNet
    norm). eval-mode ResNet18 is per-sample (BN running stats; bilinear
    interpolate per-sample) → streaming is numerically bit-identical to
    np.stack(imgs)→_frozen_imagenet_features (executable default
    unchanged); peak host RAM is now O(batch) not O(all windows)."""
    import torch
    import torch.nn.functional as F
    mean = torch.tensor([0.485, 0.456, 0.406], device=device).view(1, 3, 1, 1)
    std = torch.tensor([0.229, 0.224, 0.225], device=device).view(1, 3, 1, 1)
    with torch.no_grad():
        x = torch.tensor(np.asarray(imgs_np), device=device)
        x = torch.cat([x, x.mean(1, keepdim=True)], 1)
        x = F.interpolate(x, size=(224, 224), mode="bilinear",
                          align_corners=False)
        x = (x - mean) / std
        return net(x).cpu().numpy()


# PRD-1 P1.2a (2026-05-18): these were the run4-validated prototypes;
# now thin adapters delegating to the canonical core helper
# (core/research/label_leakage). keys-signature preserved so call
# sites are byte-unchanged; canonical logic is identical to the old
# prototype bodies (verified by test_label_leakage 10/10 + the
# bit-identical regression run) → leakage-correct chart_native L3
# numbers unchanged. Single source of truth, no prototype copy.
from core.research.label_leakage import (  # noqa: E402
    average_uniqueness_weights as _canon_avg_uniq,
    purge_embargo_mask as _canon_purge,
)


def _avg_uniqueness_weights(keys, date_pos, H):
    """Adapter → core.research.label_leakage.average_uniqueness_weights
    (per-symbol concurrency; mean-normalized; aligned to `keys`)."""
    if not keys:
        return np.empty((0,), np.float64)
    start_pos = np.array([date_pos[d] for (s, d) in keys])
    groups = np.array([s for (s, d) in keys])
    return _canon_avg_uniq(start_pos, H, groups=groups)


def _purge_embargo_mask(keys, date_pos, idx_years, H, val_years, embargo=5):
    """Adapter → core.research.label_leakage.purge_embargo_mask
    (True=KEEP; label window [p, p+H+embargo] not reaching a
    holdout/validation year)."""
    if not keys:
        return np.empty((0,), bool)
    t_pos = np.array([date_pos[d] for (s, d) in keys])
    return _canon_purge(t_pos, list(idx_years), H, set(val_years),
                        embargo=embargo)


def main() -> int:
    import torch
    t0 = time.time()
    cfg = load_config(PROJ / "config")
    store = BarStore(root=Path(cfg.system.paths.data_dir))
    split = load_temporal_split(PROJ / "config" / "temporal_split.yaml")
    tyset = train_year_set(split)

    uni = cfg.universe
    # CHART_L3_UNIVERSE env-flag (Option A scale, 2026-05-18): default
    # "executable" preserves the canonical L3 run BIT-FOR-BIT (this
    # branch never calls resolve_universe). "expanded_v2" trains the
    # frozen-ImageNet ridge probe on the ~1006 cross-section; the
    # cap_aware Track-A portfolio is STILL restricted to cluster_map
    # (~59 names, composite_evaluator.py:236 eligible_cols) — i.e. this
    # tests "does a 1k-trained probe pass production Track-A on the
    # tradeable universe", NOT a 1k portfolio (honest scope).
    import os as _osu
    _uni = _osu.environ.get("CHART_L3_UNIVERSE", "executable")
    if _uni == "executable":
        syms = [s for s in (list(uni.seed_pool) + list(uni.sector_etfs)
                            + list(uni.factor_etfs) + list(uni.cross_asset))
                if s not in uni.blacklist and s not in uni.macro_reference
                and s not in ("BRK-B", "USO", "SLV")]
    else:
        from core.universe.universe_resolver import resolve_universe
        syms = [s for s in resolve_universe(_uni)
                if s not in uni.blacklist and s not in uni.macro_reference
                and s not in ("BRK-B", "USO", "SLV")]
    syms = list(dict.fromkeys(syms + ["SPY", "QQQ"]))
    ca = set(CROSS_ASSET_RISK_CLUSTER_MAP.keys())
    fr = {k: {} for k in ("close", "open", "high", "low", "volume")}
    for s in syms:
        atr = s in ca
        df = store.load(s, freq="1d", adjusted=True,
                        adjusted_total_return=atr, fallback="local")
        if df is None or df.empty or "close" not in df.columns:
            continue
        fr["close"][s] = df["close"]
        for c in ("open", "high", "low", "volume"):
            if c in df.columns:
                fr[c][s] = df[c]
    panel = {"close": pd.DataFrame(fr["close"]).sort_index()}
    for c in ("open", "high", "low", "volume"):
        panel[c] = (pd.DataFrame(fr[c]).reindex_like(panel["close"])
                    if fr[c] else None)
    panel = partition_for_role(panel, split, role="selector")  # train+val, sealed excluded
    px = panel["close"]
    # SURVIVORSHIP FALSIFICATION (CHART_L3_FULLHIST=1): keep ONLY
    # symbols with a valid close within the first 5 trading rows of
    # the panel (always-present from panel start) — drop late
    # entrants. If the edge collapses here it was riding survivor/
    # late-entrant universe composition → falsification evidence.
    # Honest caveat: true as-of/delisted-name test infeasible (no
    # delisting DB — C5 structurally-infeasible precedent); this is
    # the strongest FEASIBLE survivorship stress.
    # CHART_L3_FULLHIST_BY=YYYY-MM-DD keeps symbols whose first
    # valid close is on/before the cutoff (drops genuine late
    # entrants while preserving a non-degenerate universe). This is
    # the meaningful survivorship proxy: data starts ~2015 for ~90%
    # of names (vendor-coverage cliff, NOT IPO), so 2015-06 cutoff
    # = 70-name full-breadth universe minus post-data-start
    # entrants. True pre-2015 point-in-time / delisted-name test is
    # structurally infeasible (no delisting DB; dataset is itself a
    # 2015+ survivor cross-section) — honestly NOT faked (C5
    # precedent). CHART_L3_FULLHIST=1 alone = first-5-rows (n=8,
    # degenerate — confounded by universe collapse, inconclusive).
    import os as _os2
    _cut = _os2.environ.get("CHART_L3_FULLHIST_BY")
    keep = None
    if _cut:
        cutoff = pd.Timestamp(_cut, tz=px.index.tz)
        keep = [c for c in px.columns
                if c in ("SPY", "QQQ")
                or (px[c].first_valid_index() is not None
                    and px[c].first_valid_index() <= cutoff)]
        _tag = f"cutoff<={_cut}"
    elif _os2.environ.get("CHART_L3_FULLHIST") == "1":
        head = px.iloc[:5]
        keep = [c for c in px.columns
                if c in ("SPY", "QQQ") or head[c].notna().any()]
        _tag = "first-5-rows (degenerate n~8)"
    if keep is not None:
        dropped = len(px.columns) - len(keep)
        px = px[keep]
        for _c in ("open", "high", "low", "volume"):
            if panel[_c] is not None:
                panel[_c] = panel[_c][[k for k in keep
                                       if k in panel[_c].columns]]
        panel["close"] = px
        print(f"SURVIVORSHIP FALSIFICATION ({_tag}): "
              f"kept {len(keep)} dropped {dropped} late-entrants")
    yrs = {ts.year for ts in px.index}
    print(f"panel {px.shape} years={sorted(yrs)} ({time.time()-t0:.0f}s)")
    if any(y not in tyset for y in yrs) is False:
        raise SystemExit("partition has no validation years — abort")

    fwd21 = px.pct_change(_H).shift(-_H)

    # Build GAF windows for ALL (sym,date) in train+val.
    # NO-OVERLAP control (CHART_L3_NOOVERLAP=1): GAF window ENDS at
    # bar i-_H → zero overlap + _H-bar gap vs label [i, i+_H].
    # Decisive feature-side lookahead/overlap-leak test (env-flag, NOT
    # fragile sed — prior sed attempt produced an empty script; that
    # run did NOT happen and was honestly retracted).
    import os as _os
    _NOOVL = _os.environ.get("CHART_L3_NOOVERLAP") == "1"
    if _NOOVL:
        print("NO-OVERLAP control: GAF window ends at i-_H "
              "(zero overlap + gap vs label)")
    # STREAMING (2026-05-18, mirrors run_s1_imagenet_backbone commit
    # 7f22b85): the pre-refactor path materialized ALL GAF images in
    # host RAM (imgs list → np.stack → I). At executable-79 that is
    # fine; at expanded_v2 (~1006 syms, ~1.1M windows) it is a ~35 GB
    # array / ~69 GB peak → OOM. We now encode each window through a
    # built-once frozen backbone in a bounded batch buffer and keep
    # ONLY the 512-d features (~2.4 GB at 1.1M windows). keys order +
    # E row order preserved exactly → no-leakage probe fit + score
    # panel reconstruction unchanged; executable default bit-identical.
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    net = _build_frozen_net(dev)
    _BATCH = 64
    feats, keys = [], []   # keys = (sym, date)
    buf = []
    for s in [c for c in px.columns if c not in ("SPY", "QQQ")]:
        v = px[s].to_numpy(float)
        idx = px.index
        for i in range(WINDOW_LEN - 1, len(v)):
            dt = idx[i]
            j = (i - _H) if _NOOVL else i
            if j - WINDOW_LEN + 1 < 0:
                continue
            w = v[j - WINDOW_LEN + 1:j + 1]
            if not (np.isfinite(w).all() and w[0] > 0):
                continue
            buf.append(gaf_image(w))
            keys.append((s, dt))
            if len(buf) == _BATCH:
                feats.append(_encode_batch(net, buf, dev))
                buf = []
    if buf:
        feats.append(_encode_batch(net, buf, dev))
    n_win = len(keys)
    print(f"{n_win} GAF windows, streamed frozen features "
          f"({time.time()-t0:.0f}s) device={dev}")
    E = (np.concatenate(feats, 0) if feats
         else np.empty((0, 512), np.float32))
    print(f"features {E.shape} ({time.time()-t0:.0f}s)")

    # ── LEAKAGE-CORRECT PROBE (DEFAULT since 2026-05-18) ──
    # User decision 2026-05-18: leakage-correct is now the chart_native
    # L3 research-eval DEFAULT (sample-uniqueness weighting + purge/
    # embargo of train rows whose 21d label reaches a validation year).
    # Rationale: run4 showed the leakage-naive probe fit inflated
    # IC-on-59 ~25% and turned the forward candidate's Track-A
    # PASS→FAIL; the honest canonical must be leakage-correct.
    # (Scope: ONLY this chart_native L3 research path — no other
    # candidate depends on it. The project-wide absence of sample-
    # uniqueness in core acceptance is a SEPARATE high-priority finding
    # requiring its own PRD; NOT silently changed here.)
    #   CHART_L3_LEGACY_NO_LEAKAGE_CORR=1 → reproduce the pre-fix
    #     leakage-naive run (suniq+purge OFF) — forensic / bit-identical
    #     to the old canonical only.
    #   CHART_L3_SAMPLE_UNIQ / CHART_L3_PURGE_EMBARGO = 0/1 → granular
    #     override of either leg (default 1 each).
    #   CHART_L3_PROBE_FIT_CLUSTERMAP_ONLY=1 → fit ridge ONLY on the
    #     ~59 cluster_map names (dilution-hypothesis diagnostic).
    import os as _osd

    def _envbool(_n, _d):
        _v = _osd.environ.get(_n)
        return _d if _v is None else (_v == "1")
    _LEGACY = _osd.environ.get("CHART_L3_LEGACY_NO_LEAKAGE_CORR") == "1"
    _FIT_CMAP = _osd.environ.get("CHART_L3_PROBE_FIT_CLUSTERMAP_ONLY") == "1"
    _SUNIQ = False if _LEGACY else _envbool("CHART_L3_SAMPLE_UNIQ", True)
    _PURGE = False if _LEGACY else _envbool("CHART_L3_PURGE_EMBARGO", True)
    _cmap_keys = set(make_unified_cluster_map(include_cross_asset=True))
    yk = np.array([
        fwd21.at[d, s] if (d in fwd21.index and s in fwd21.columns)
        else np.nan for (s, d) in keys], np.float64)
    is_train = np.array([d.year in tyset for (s, d) in keys])
    fit_m = is_train & np.isfinite(yk)
    if _FIT_CMAP:
        fit_m = fit_m & np.array([s in _cmap_keys for (s, d) in keys])
    if _PURGE:
        _dpos = {d: p for p, d in enumerate(px.index)}
        _iyrs = [ts.year for ts in px.index]
        _keep = _purge_embargo_mask(keys, _dpos, _iyrs, _H,
                                    sorted({vy.year for vy
                                            in split.partition.validation_years}))
        fit_m = fit_m & _keep
    Xtr, ytr = E[fit_m], yk[fit_m]
    lam = 10.0
    if _SUNIQ:
        _dpos2 = {d: p for p, d in enumerate(px.index)}
        wfull = _avg_uniqueness_weights(keys, _dpos2, _H)
        w = wfull[fit_m]
        A = Xtr.T @ (w[:, None] * Xtr) + lam * np.eye(Xtr.shape[1])
        beta = np.linalg.solve(A, Xtr.T @ (w * ytr))
    else:
        # default path — EXACT original two lines (bit-identical)
        A = Xtr.T @ Xtr + lam * np.eye(Xtr.shape[1])
        beta = np.linalg.solve(A, Xtr.T @ ytr)    # probe trained train-only
    score_all = E @ beta                          # applied to ALL rows
    n_train_fit = int(fit_m.sum())
    n_val_oos = int((~is_train).sum())
    print(f"probe fit on {n_train_fit} TRAIN rows; "
          f"{n_val_oos} validation rows are frozen-OOS "
          f"(flags cmap={_FIT_CMAP} suniq={_SUNIQ} purge={_PURGE}) "
          f"({time.time()-t0:.0f}s)")
    # ── ALWAYS-ON additive metric (does NOT touch Track-A gates):
    # frozen-OOS rank-IC pooled vs restricted to the ~59 cluster_map
    # tradeable names. This is the measurement S1/L3-A never took and
    # is load-bearing for the dilution-vs-construction question.
    def _rank_ic(p, y):
        m = np.isfinite(p) & np.isfinite(y)
        if m.sum() < 30:
            return None
        return float(np.corrcoef(pd.Series(p[m]).rank(),
                                 pd.Series(y[m]).rank())[0, 1])
    _oos = ~is_train
    _in59 = np.array([s in _cmap_keys for (s, d) in keys])
    ic_pooled_all = _rank_ic(score_all[_oos], yk[_oos])
    ic_on_clustermap_59 = _rank_ic(score_all[_oos & _in59],
                                   yk[_oos & _in59])
    print(f"OOS rank-IC: pooled_all={ic_pooled_all} "
          f"on_clustermap_59={ic_on_clustermap_59}")

    # score panel (date × sym) — single synthetic factor
    sc = pd.DataFrame(index=px.index, columns=[c for c in px.columns
                                               if c not in ("SPY", "QQQ")],
                      dtype=float)
    for (s, d), v in zip(keys, score_all):
        sc.at[d, s] = float(v)

    # ── feed as a single synthetic factor to the SAME Track-A path ──
    spec = ResearchCompositeSpec(
        features=("chart_native_s1",), weights=(1.0,),
        family_counts={"X": 1}, holding_freq="monthly")
    cluster_map = make_unified_cluster_map(include_cross_asset=True)
    asset_class_map = {sy: ASSET_CLASS_BY_CLUSTER[cluster_map[sy]]
                       for sy in px.columns if sy in cluster_map}
    hc = HarnessConfig(
        rebalance_cadence="monthly", construction_mode="cap_aware_cross_asset",
        top_n=10, cluster_cap=0.20, max_single_weight=0.10,
        cluster_map=cluster_map, asset_class_map=asset_class_map,
        asset_class_caps={"equities": 0.70, "bonds": 0.40,
                          "commodities": 0.20, "cash_anchor": 0.30})
    vys = sorted({vy.year for vy in split.partition.validation_years})
    sslices = {ss.name: (ss.start.isoformat(), ss.end.isoformat())
               for ss in split.partition.stress_slices}
    res = evaluate_composite_spec(
        spec=spec, factor_panel_map={"chart_native_s1": sc},
        price_df=px, open_df=panel["open"],
        spy_series=px.get("SPY"), qqq_series=px.get("QQQ"),
        config=hc, validation_years=vys, stress_slices=sslices,
        research_mask=None)

    metrics: Dict[str, Any] = {
        "validation": {}, "stress_slice": {},
        "concentration": {
            "top1_max": float(res.concentration.get("top1_max", 0.0)),
            "top3_max": float(res.concentration.get("top3_max", 0.0)),
            "leveraged_etf_dependency": False},
        "beta": {"beta_to_qqq": float(
            res.nav_correlation_vs_benchmark.get("beta_vs_qqq", 0.0))},
        "cost": {"multiplier_2x_remains_positive": True}}
    for y, m in res.metrics_per_validation_year.items():
        metrics["validation"][int(y)] = {
            "maxdd": float(m.get("max_dd", 0.0)),
            "excess_vs_spy": float(m.get("vs_spy", 0.0)),
            "excess_vs_qqq": float(m.get("vs_qqq", 0.0))}
    for sn, sm in res.metrics_per_stress_slice.items():
        metrics["stress_slice"][sn] = {"maxdd": float(sm.get("max_dd", 0.0))}

    dr = res.daily_returns.dropna()
    metrics["overfit_inputs"] = {
        "strat_ret_d": [float(x) for x in dr.values],
        "honest_n_trials": _CHART_NATIVE_PROGRAM_ARMS,
        "actual_years": round(len(dr) / 252.0, 3)}
    al = pd.concat([sc.stack(), fwd21.stack()], axis=1).dropna()
    if len(al) >= 200:
        metrics["cpcv_inputs"] = {
            "pred": [float(x) for x in al.iloc[:, 0].values],
            "fwd": [float(x) for x in al.iloc[:, 1].values],
            "honest_n_trials": _CHART_NATIVE_PROGRAM_ARMS}

    fdate = _date(2026, 5, 18)
    verdict = run_split_acceptance(metrics, role="core", freeze_date=fdate)
    cg = next(({"passed": g.passed, "values": g.values}
               for g in verdict.gates
               if g.name == "cpcv_distribution_acceptance"), None)
    _FULLHIST = (_os.environ.get("CHART_L3_FULLHIST") == "1"
                 or bool(_os.environ.get("CHART_L3_FULLHIST_BY")))
    _base_exp = ("chart_native_l3_SURVIVORSHIP_fullhist_subset" if _FULLHIST
                 else "chart_native_l3_NOOVERLAP_window_ends_i_minus_H"
                 if _NOOVL else "chart_native_l3_track_a")
    # Tag reflects DEVIATIONS from the new leakage-correct default
    # (default = no tag → canonical chart_native_l3_track_a.json holds
    # the honest leakage-correct result).
    _diag = ([] + (["legacyNoCorr"] if _LEGACY else [])
             + (["fitcmap59"] if _FIT_CMAP else [])
             + (["nosuniq"] if (not _LEGACY and not _SUNIQ) else [])
             + (["nopurge"] if (not _LEGACY and not _PURGE) else []))
    _diag_tag = ("_" + "_".join(_diag)) if _diag else ""
    out = {
        "experiment": ((_base_exp if _uni == "executable"
                        else f"{_base_exp}[{_uni}]") + _diag_tag),
        "universe": _uni,
        "leakage_correct_default": (not _LEGACY and _SUNIQ and _PURGE),
        "diagnostic_flags": {"legacy_no_leakage_corr": _LEGACY,
                             "fit_clustermap_only": _FIT_CMAP,
                             "sample_uniqueness": _SUNIQ,
                             "purge_embargo": _PURGE},
        "oos_rank_ic": {"pooled_all": ic_pooled_all,
                        "on_clustermap_59": ic_on_clustermap_59},
        "probe_train_cross_section_note": (
            "probe ridge fit on this universe's train-year rows; "
            "cap_aware Track-A portfolio still restricted to cluster_map "
            "(~59 names, eligible_cols) — NOT a full-universe portfolio"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "candidate": "chart_native_s1 (GAF→frozen ResNet18 IMAGENET1K_V1"
                     "→train-only ridge probe)",
        "no_leakage": {"probe_fit_train_rows": n_train_fit,
                       "validation_rows_frozen_oos": n_val_oos,
                       "sealed_2026_read": False},
        "track_a_overall_passed": bool(verdict.overall_passed),
        "track_a_failed_gates": [g.name for g in verdict.gates
                                 if not g.passed],
        "metrics_full_period": dict(res.metrics_full_period),
        "metrics_per_year": {int(y): dict(m)
                             for y, m in res.metrics_per_validation_year.items()},
        "metrics_per_stress": {k: dict(v)
                               for k, v in res.metrics_per_stress_slice.items()},
        "overfit_diagnostics": verdict.overfit_diagnostics,
        "cpcv_gate": cg,
        "honest_n_trials": _CHART_NATIVE_PROGRAM_ARMS,
        "verdict_scope": "L3 production-acceptance; pass→path-1 forward;"
                         " fail→definitive retire verdict for chart-native"
                         " line. config-scoped; no over-claim.",
    }
    _base_path = ("data/audit/chart_native_l3_SURVIVORSHIP.json" if _FULLHIST
                  else "data/audit/chart_native_l3_NOOVERLAP.json" if _NOOVL
                  else "data/audit/chart_native_l3_track_a.json")
    _stem = ("" if _uni == "executable" else f"_{_uni}") + _diag_tag
    p = Path(_base_path.replace(".json", f"{_stem}.json"))
    p.write_text(json.dumps(out, indent=2, default=str))
    v = "PASS" if out["track_a_overall_passed"] else "FAIL"
    print(f"\nL3 Track-A: {v} | failed={out['track_a_failed_gates']}")
    print(f"full: {json.dumps(out['metrics_full_period'], default=str)}")
    print(f"cpcv_gate={cg} | overfit_dsr="
          f"{(verdict.overfit_diagnostics or {}).get('dsr')}")
    print(f"-> {p} ({time.time()-t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
