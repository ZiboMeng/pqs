"""Initialize chart-native S1 evidence-only forward observation track.

Evidence-grounded forward-init (NOT reactive promote) per
`feedback_promotion_only_falsification_evidence_gated` harness:
the ORIGINAL causally-clean strategy PASSED Track-A all 17 gates;
4 falsification attempts (neg-control / no-overlap / survivorship
n=8 confound / survivorship 70-name meaningful) produced ZERO
strategy-self flaw evidence; the strongest FEASIBLE survivorship
proxy (70-name, drops 9 genuine late-entrants) survives cleanly
(cum_ret +2163% / Sharpe 1.62 ≈ original). The only residual
unknown — pre-2015 true point-in-time / delisted-name survivorship
— is structurally infeasible to test offline (no delisting DB;
dataset is itself a 2015+ vendor survivor cross-section; C5
precedent) AND is exactly what forward observation tests (real
out-of-sample, no survivorship in real-time data) = path-1 purpose.

Strategy = GAF(WINDOW_LEN) window of adjusted close → FROZEN
torchvision ResNet18 IMAGENET1K_V1 (fc=Identity) 512-d features →
ridge probe (lambda=10) fit on TRAIN-YEAR rows ONLY then FROZEN →
cross-sectional score → cap_aware_cross_asset monthly top-10.

This is a standalone observation track (does NOT use core/research/
forward main runner — that is built for factor-composite specs;
this is a learned probe). Precedent: pead_sue_trial1_evidence_v1 /
simple_baseline_v1. The frozen ridge `beta` is persisted as a
sha256-pinned .npy sidecar and is NEVER refit during forward
observation (frozen-probe contract).

Idempotency: re-run without --overwrite is a no-op; --overwrite
archives existing artifacts to .archived_<ts>; --dry-run prints
plan only. sealed 2026 NEVER read (partition_for_role selector).

Usage:
    python dev/scripts/chart_native_l3/init_chart_native_evidence.py
    python dev/scripts/chart_native_l3/init_chart_native_evidence.py --overwrite
    python dev/scripts/chart_native_l3/init_chart_native_evidence.py --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parents[3]
if str(PROJ) not in sys.path:
    sys.path.insert(0, str(PROJ))

import numpy as np
import pandas as pd
import yaml

from core.config.loader import load_config
from core.data.bar_store import BarStore
from core.ml.chart_cnn import gaf_image
from core.ml.window_embedding import WINDOW_LEN
from core.mining.research_miner import ResearchCompositeSpec
from core.research.harness import HarnessConfig, evaluate_composite_spec
from core.research.risk_cluster_map import (
    ASSET_CLASS_BY_CLUSTER,
    make_unified_cluster_map,
)
from core.research.temporal_split import (
    load_temporal_split,
    partition_for_role,
    train_year_set,
)
# Reuse the EXACT frozen-backbone feature path (zero divergence risk)
from dev.scripts.chart_native_l3.run_chart_native_l3_track_a import (
    _frozen_imagenet_features,
    _H,
)

CANDIDATE_ID = "chart_native_s1_evidence_v1"
RC = PROJ / "data" / "research_candidates"
SPEC_PATH = RC / f"{CANDIDATE_ID}.yaml"
MANIFEST_PATH = RC / f"{CANDIDATE_ID}_forward_manifest.json"
NAV_PATH = RC / f"{CANDIDATE_ID}_forward_nav.parquet"
BETA_PATH = RC / f"{CANDIDATE_ID}_frozen_probe_beta.npy"

_LAMBDA = 10.0
_START_DATE = "2026-05-19"   # next trading day after 2026-05-18 freeze
_FREEZE_DATE = "2026-05-18"


def _sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _canon_hash(d: dict) -> str:
    return hashlib.sha256(
        json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()


def _max_dd(nav: pd.Series) -> float:
    if len(nav) < 2:
        return 0.0
    peak = nav.cummax()
    return float(((nav - peak) / peak.replace(0, np.nan)).min())


def _archive(p: Path):
    if p.exists():
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
        p.rename(p.with_suffix(p.suffix + f".archived_{ts}"))
        print(f"  archived {p.name}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    t0 = time.time()
    print(f"=== Init chart-native evidence track: {CANDIDATE_ID} ===")

    if MANIFEST_PATH.exists() and not args.overwrite:
        print(f"  Manifest exists at {MANIFEST_PATH}; "
              f"re-run with --overwrite to re-init. No-op.")
        return 0

    cfg = load_config(PROJ / "config")
    store = BarStore(root=Path(cfg.system.paths.data_dir))
    split = load_temporal_split(PROJ / "config" / "temporal_split.yaml")
    tyset = train_year_set(split)

    uni = cfg.universe
    syms = [s for s in (list(uni.seed_pool) + list(uni.sector_etfs)
                        + list(uni.factor_etfs) + list(uni.cross_asset))
            if s not in uni.blacklist and s not in uni.macro_reference
            and s not in ("BRK-B", "USO", "SLV")]
    syms = list(dict.fromkeys(syms + ["SPY", "QQQ"]))

    from core.research.risk_cluster_map import CROSS_ASSET_RISK_CLUSTER_MAP
    ca = set(CROSS_ASSET_RISK_CLUSTER_MAP)
    fr = {k: {} for k in ("close", "open", "high", "low", "volume")}
    for s in syms:
        df = store.load(s, freq="1d", adjusted=True,
                        adjusted_total_return=(s in ca), fallback="local")
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
    # selector = train+validation; SEALED 2026 EXCLUDED (never read)
    panel = partition_for_role(panel, split, role="selector")
    px = panel["close"]
    yrs = sorted({ts.year for ts in px.index})
    print(f"  panel {px.shape} years={yrs} ({time.time()-t0:.0f}s)")

    fwd = px.pct_change(_H).shift(-_H)

    # ORIGINAL causally-clean construction: GAF window ENDS at bar i
    # (no env handicap). This is the canonical PASS config.
    imgs, keys = [], []
    for s in [c for c in px.columns if c not in ("SPY", "QQQ")]:
        v = px[s].to_numpy(float)
        idx = px.index
        for i in range(WINDOW_LEN - 1, len(v)):
            w = v[i - WINDOW_LEN + 1:i + 1]
            if not (np.isfinite(w).all() and w[0] > 0):
                continue
            imgs.append(gaf_image(w))
            keys.append((s, idx[i]))
    I = np.stack(imgs).astype(np.float32)
    dev = "cuda" if __import__("torch").cuda.is_available() else "cpu"
    print(f"  {len(I)} GAF windows → frozen features "
          f"({time.time()-t0:.0f}s) dev={dev}")
    E = _frozen_imagenet_features(I, dev)

    # FROZEN ridge probe: fit on TRAIN-YEAR rows ONLY, then frozen
    yk = np.array([
        fwd.at[d, s] if (d in fwd.index and s in fwd.columns)
        else np.nan for (s, d) in keys], np.float64)
    is_train = np.array([d.year in tyset for (s, d) in keys])
    fit_m = is_train & np.isfinite(yk)
    Xtr, ytr = E[fit_m], yk[fit_m]
    A = Xtr.T @ Xtr + _LAMBDA * np.eye(Xtr.shape[1])
    beta = np.linalg.solve(A, Xtr.T @ ytr)        # frozen forever
    score_all = E @ beta
    n_train_fit = int(fit_m.sum())
    n_val_oos = int((~is_train).sum())
    print(f"  probe fit {n_train_fit} TRAIN rows; "
          f"{n_val_oos} validation frozen-OOS")

    sc = pd.DataFrame(index=px.index,
                      columns=[c for c in px.columns
                               if c not in ("SPY", "QQQ")], dtype=float)
    for (s, d), val in zip(keys, score_all):
        sc.at[d, s] = float(val)

    cspec = ResearchCompositeSpec(
        features=("chart_native_s1",), weights=(1.0,),
        family_counts={"X": 1}, holding_freq="monthly")
    cluster_map = make_unified_cluster_map(include_cross_asset=True)
    asset_class_map = {sy: ASSET_CLASS_BY_CLUSTER[cluster_map[sy]]
                       for sy in px.columns if sy in cluster_map}
    hc = HarnessConfig(
        rebalance_cadence="monthly",
        construction_mode="cap_aware_cross_asset",
        top_n=10, cluster_cap=0.20, max_single_weight=0.10,
        cluster_map=cluster_map, asset_class_map=asset_class_map,
        asset_class_caps={"equities": 0.70, "bonds": 0.40,
                          "commodities": 0.20, "cash_anchor": 0.30})
    vys = sorted({vy.year for vy in split.partition.validation_years})
    sslices = {ss.name: (ss.start.isoformat(), ss.end.isoformat())
               for ss in split.partition.stress_slices}
    res = evaluate_composite_spec(
        spec=cspec, factor_panel_map={"chart_native_s1": sc},
        price_df=px, open_df=panel["open"],
        spy_series=px.get("SPY"), qqq_series=px.get("QQQ"),
        config=hc, validation_years=vys, stress_slices=sslices,
        research_mask=None)
    nav = res.nav.copy()
    mf = dict(res.metrics_full_period)
    sharpe = float(mf.get("sharpe", 0.0))
    cum = float(mf.get("cum_ret", 0.0))
    mdd = float(mf.get("max_dd", _max_dd(nav)))
    print(f"  frozen baseline: cum_ret {cum:+.4f} Sharpe {sharpe:+.3f} "
          f"MaxDD {mdd:+.4f} vs_spy {mf.get('vs_spy')}")

    spec = {
        "candidate_id": CANDIDATE_ID,
        "candidate_role": "evidence_only_observation",
        "strategy_type": "chart_native_learned_probe",
        "lineage": "ml-method-redo-2026-05-16",
        "construction": {
            "gaf_window_len": int(WINDOW_LEN),
            "label_horizon_bars": int(_H),
            "backbone": "torchvision.resnet18 IMAGENET1K_V1 "
                        "(fc=Identity, all params frozen, eval())",
            "probe": "ridge", "probe_lambda": _LAMBDA,
            "probe_fit_scope": "train-year rows ONLY (frozen, never "
                               "refit forward)",
            "rebalance_cadence": "monthly",
            "construction_mode": "cap_aware_cross_asset",
            "top_n": 10, "cluster_cap": 0.20, "max_single_weight": 0.10,
            "asset_class_caps": {"equities": 0.70, "bonds": 0.40,
                                 "commodities": 0.20,
                                 "cash_anchor": 0.30},
        },
        "frozen_probe_beta_path": str(BETA_PATH.relative_to(PROJ)),
        "frozen_probe_beta_sha256": None,   # filled after write
        "panel_contract": {
            "universe_source": "config/universe.yaml (executable)",
            "adjusted": True,
            "adjusted_total_return_for_cross_asset": True,
            "partition": "alternating_regime_holdout_v1 selector "
                         "(train+validation; SEALED 2026 excluded)",
        },
        "forward_contract": {"start_date": _START_DATE,
                             "freeze_date": _FREEZE_DATE},
        "evidence": {
            "track_a": "PASS all 17 gates (original causally-clean)",
            "falsification_attempts": [
                "neg-control: shuffled labels collapse (cleared "
                "harness/pooling artifact)",
                "no-overlap: 21d-gap handicap, IC/20x preserved "
                "(cleared overlap/lookahead)",
                "survivorship n=8: confound (data-coverage cliff), "
                "INCONCLUSIVE — not evidence",
                "survivorship 70-name meaningful: PASS Track-A, edge "
                "survives (NOT falsified)",
            ],
            "structural_residual_honest": (
                "pre-2015 true point-in-time / delisted-name "
                "survivorship is structurally infeasible offline "
                "(no delisting DB; dataset itself a 2015+ vendor "
                "survivor cross-section; C5 precedent). Forward "
                "observation IS the OOS test for this residual "
                "(real-time data has no survivorship). NOT faked, "
                "NOT a rejection ground per harness."),
            "scope_caveat": (
                "config-scoped research signal; pooled-IC magnitude "
                "may be inflated (Track-A uses portfolio metrics not "
                "pooled IC); PBO red_flag is N/A for single-signal "
                "(folds-as-configs misuse, audited); DSR placeholder-"
                "N not an anchor. Evidence-only; does NOT enter fleet."),
        },
    }

    if args.dry_run:
        print("  [dry-run] no artifacts written")
        return 0

    RC.mkdir(parents=True, exist_ok=True)
    for p in (BETA_PATH, NAV_PATH, SPEC_PATH, MANIFEST_PATH):
        if args.overwrite:
            _archive(p)
    np.save(BETA_PATH, beta.astype(np.float64))
    beta_sha = _sha256_file(BETA_PATH)
    spec["frozen_probe_beta_sha256"] = beta_sha
    SPEC_PATH.write_text(yaml.safe_dump(spec, sort_keys=False))
    spec_hash = _canon_hash(spec)

    pd.DataFrame({"equity": nav,
                  "ts_phase": ["initial_baseline"] * len(nav)}
                 ).to_parquet(NAV_PATH)

    td000 = {
        "td_id": "TD000", "td_phase": "initial_baseline",
        "observation_date": str(nav.index[-1].date()),
        "freeze_date": _FREEZE_DATE,
        "strat_equity": float(nav.iloc[-1]),
        "frozen_baseline_cum_ret": cum,
        "frozen_baseline_sharpe": sharpe,
        "frozen_baseline_max_dd": mdd,
        "frozen_baseline_vs_spy": float(mf.get("vs_spy", 0.0)),
        "frozen_baseline_vs_qqq": float(mf.get("vs_qqq", 0.0)),
        "n_probe_train_rows": n_train_fit,
        "n_validation_oos_rows": n_val_oos,
        "sealed_2026_read": False,
    }
    manifest = {
        "candidate_id": CANDIDATE_ID,
        "candidate_role": "evidence_only_observation",
        "strategy_type": "chart_native_learned_probe",
        "spec_hash_sha256": spec_hash,
        "frozen_probe_beta_sha256": beta_sha,
        "spec_path": str(SPEC_PATH.relative_to(PROJ)),
        "nav_path": str(NAV_PATH.relative_to(PROJ)),
        "beta_path": str(BETA_PATH.relative_to(PROJ)),
        "start_date": _START_DATE, "freeze_date": _FREEZE_DATE,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": "chart_native_evidence_v1",
        "current_status": "in_progress",
        "lifecycle_note": (
            "Evidence-only observation, standalone track (NOT main "
            "composite runner; learned probe). Does NOT enter fleet "
            "allocation. Frozen-probe contract: beta NEVER refit "
            "forward. Decision point TD60 ~ 2026-08-13. Forward soak "
            "is the OOS test for the structurally-untestable pre-2015 "
            "survivorship residual."),
        "universe_size_at_freeze": int(px.shape[1]),
        "td_observations": [td000],
        "td_count": 1,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, default=str))

    print(f"\n=== Init complete ({time.time()-t0:.0f}s) ===")
    print(f"  candidate_id : {CANDIDATE_ID}")
    print(f"  role         : evidence_only_observation")
    print(f"  spec_hash    : {spec_hash}")
    print(f"  beta_sha256  : {beta_sha}")
    print(f"  start_date   : {_START_DATE} (freeze {_FREEZE_DATE})")
    print(f"  TD000        : cum_ret {cum:+.4f} / Sharpe {sharpe:+.3f}"
          f" / MaxDD {mdd:+.4f}")
    print(f"  Next: post-NYSE close, daily-ritual observe (follow-up "
          f"script, mirrors pead observe pattern)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
