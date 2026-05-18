"""Observe chart_native_s1_evidence_v1 — append next forward TD.

Daily-ritual incremental observer for the chart-native learned-probe
evidence track. Mirrors dev/scripts/pead/observe_pead_evidence.py.

FROZEN-PROBE CONTRACT (load-bearing): the ridge `beta` is LOADED
from the sha256-pinned .npy sidecar and its sha256 is verified
against the manifest. It is **NEVER refit** — forward scoring only
APPLIES the frozen probe to new bars. A sha256 mismatch is a hard
abort (the frozen contract was violated).

TEMPORAL-SPLIT NOTE: forward observation LEGITIMATELY reads
post-freeze (2026+) bars — that IS the out-of-sample test (same as
pead / trial9). This is distinct from the sealed-2026 single-shot
GATE (never read for evidence). So observe builds the full panel
start→today WITHOUT the selector partition restriction (init used
selector to compute the pre-freeze frozen baseline; observe needs
the forward window). No leakage: beta was fit train-only at init
and is frozen here.

Idempotent within a trading day: appends a TD only if the latest
bar is newer than the most recent TD observation_date.

Usage:
    python dev/scripts/chart_native_l3/observe_chart_native_evidence.py
    python dev/scripts/chart_native_l3/observe_chart_native_evidence.py --dry-run
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
    CROSS_ASSET_RISK_CLUSTER_MAP,
    make_unified_cluster_map,
)
from core.research.temporal_split import load_temporal_split
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

_TERMINAL = {"completed_pass", "completed_fail", "aborted",
             "requires_data_review"}


def _sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _max_dd(nav: pd.Series) -> float:
    if len(nav) < 2:
        return 0.0
    peak = nav.cummax()
    return float(((nav - peak) / peak.replace(0, np.nan)).min())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    t0 = time.time()
    print(f"=== Observe chart-native evidence: {CANDIDATE_ID} ===")

    if not MANIFEST_PATH.exists():
        print(f"ERROR: manifest missing. Run init first.")
        return 1
    manifest = json.loads(MANIFEST_PATH.read_text())
    spec = yaml.safe_load(SPEC_PATH.read_text())

    if manifest.get("current_status") in _TERMINAL:
        print(f"  status = {manifest['current_status']} (terminal). "
              f"Manual review required.")
        return 0

    # ── FROZEN-PROBE CONTRACT: load + verify sha256, NEVER refit ──
    if not BETA_PATH.exists():
        print(f"ERROR: frozen beta sidecar missing at {BETA_PATH}")
        return 1
    beta_sha = _sha256_file(BETA_PATH)
    expected = manifest.get("frozen_probe_beta_sha256")
    if beta_sha != expected:
        print(f"HARD ABORT: frozen beta sha256 mismatch "
              f"(got {beta_sha[:12]}…, manifest {str(expected)[:12]}…). "
              f"Frozen-probe contract violated — refusing to observe.")
        return 1
    beta = np.load(BETA_PATH)
    print(f"  frozen beta loaded ({beta.shape}), sha256 OK")

    start_date = pd.Timestamp(manifest["start_date"])
    print(f"  start_date {start_date.date()} freeze "
          f"{manifest['freeze_date']}")

    cfg = load_config(PROJ / "config")
    store = BarStore(root=Path(cfg.system.paths.data_dir))
    uni = cfg.universe
    syms = [s for s in (list(uni.seed_pool) + list(uni.sector_etfs)
                        + list(uni.factor_etfs) + list(uni.cross_asset))
            if s not in uni.blacklist and s not in uni.macro_reference
            and s not in ("BRK-B", "USO", "SLV")]
    syms = list(dict.fromkeys(syms + ["SPY", "QQQ"]))
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
    # FULL panel start→today (NO selector restriction — forward
    # window 2026+ is the OOS test, legitimate post-freeze read).
    px = pd.DataFrame(fr["close"]).sort_index()
    panel = {"close": px}
    for c in ("open", "high", "low", "volume"):
        panel[c] = (pd.DataFrame(fr[c]).reindex_like(px)
                    if fr[c] else None)
    latest_bar = px.index[-1]
    print(f"  panel {px.shape} latest_bar {latest_bar.date()} "
          f"({time.time()-t0:.0f}s)")

    last_td = manifest["td_observations"][-1]
    last_obs = pd.Timestamp(last_td["observation_date"])
    if latest_bar <= last_obs:
        print(f"  latest bar {latest_bar.date()} <= last obs "
              f"{last_obs.date()}. No new data. No-op.")
        return 0

    # GAF → frozen features → APPLY frozen beta (no fit)
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
    score_all = E @ beta                       # FROZEN probe applied

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
    split = load_temporal_split(PROJ / "config" / "temporal_split.yaml")
    vys = sorted({vy.year for vy in split.partition.validation_years})
    sslices = {ss.name: (ss.start.isoformat(), ss.end.isoformat())
               for ss in split.partition.stress_slices}
    res = evaluate_composite_spec(
        spec=cspec, factor_panel_map={"chart_native_s1": sc},
        price_df=px, open_df=panel["open"],
        spy_series=px.get("SPY"), qqq_series=px.get("QQQ"),
        config=hc, validation_years=vys, stress_slices=sslices,
        research_mask=None)
    strat_nav = res.nav.copy()

    fwd = strat_nav[strat_nav.index >= start_date]
    if len(fwd) < 2:
        print(f"  <2 bars past start_date {start_date.date()}. "
              f"Waiting (no TD yet).")
        return 0

    spy = store.load("SPY", freq="1d", adjusted=True).sort_index()
    qqq = store.load("QQQ", freq="1d", adjusted=True).sort_index()
    spy_f = spy.loc[fwd.index[0]:fwd.index[-1], "close"]
    qqq_f = qqq.loc[fwd.index[0]:fwd.index[-1], "close"]
    s_r = float(fwd.iloc[-1] / fwd.iloc[0] - 1.0)
    spy_r = float(spy_f.iloc[-1] / spy_f.iloc[0] - 1.0) if len(spy_f) >= 2 else 0.0
    qqq_r = float(qqq_f.iloc[-1] / qqq_f.iloc[0] - 1.0) if len(qqq_f) >= 2 else 0.0
    dret = fwd.pct_change().dropna()
    shp = (float(dret.mean() / dret.std() * np.sqrt(252))
           if dret.std() > 0 else 0.0)
    dd_full = _max_dd(fwd)
    dd_60d = _max_dd(fwd.tail(60))

    td_id = f"TD{len(manifest['td_observations']):03d}"
    td = {
        "td_id": td_id, "td_phase": "forward_observation",
        "observation_date": str(latest_bar.date()),
        "strat_equity": float(fwd.iloc[-1]),
        "forward_cum_ret": s_r,
        "forward_cum_ret_spy": spy_r,
        "forward_cum_ret_qqq": qqq_r,
        "forward_excess_vs_spy": s_r - spy_r,
        "forward_excess_vs_qqq": s_r - qqq_r,
        "forward_sharpe_annualized": shp,
        "forward_max_dd_full": dd_full,
        "forward_rolling_max_dd_60d": dd_60d,
        "n_forward_trading_days": int(len(fwd)),
        "frozen_beta_sha256_verified": beta_sha,
        "sealed_2026_read_for_gate": False,
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }
    print(f"\n  {td_id} (forward day {len(fwd)}):")
    print(f"    obs_date {td['observation_date']}")
    print(f"    fwd cum_ret {s_r*100:+.2f}%  vs SPY "
          f"{(s_r-spy_r)*100:+.2f}% (SPY {spy_r*100:+.2f}%)  "
          f"vs QQQ {(s_r-qqq_r)*100:+.2f}%")
    print(f"    fwd Sharpe {shp:+.3f}  MaxDD {dd_full*100:+.2f}% "
          f"(60d {dd_60d*100:+.2f}%)")

    if args.dry_run:
        print("\n  [dry-run] no write")
        return 0

    manifest["td_observations"].append(td)
    manifest["td_count"] = len(manifest["td_observations"])
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, default=str))
    n_base = len(strat_nav) - len(fwd)
    pd.DataFrame({
        "equity": strat_nav,
        "ts_phase": ["initial_baseline"] * n_base
                    + ["forward_observation"] * len(fwd),
    }).to_parquet(NAV_PATH)
    print(f"\n  wrote manifest ({manifest['td_count']} TDs) + NAV "
          f"({len(strat_nav)} rows) ({time.time()-t0:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
