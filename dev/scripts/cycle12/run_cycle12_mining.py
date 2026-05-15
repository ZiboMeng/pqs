"""Cycle12 200-trial mining — Priority 6 (2026-05-14).

Single-axis diff vs cycle08: factor pool expansion (Family R chart
patterns + Family S regime ML, 162 → 175 factors). Same partition,
construction, sampler, weights.

Yaml: data/research_candidates/track-c-cycle-2026-05-14-12_promotion_criteria.yaml
Yaml sha256 (committed at ship): 4b39b5b3b3ad1b14b35d0d8e47d3d491b0b09296a2041f3db45e303a88ad575f

Pattern follows dev/scripts/cycle08/run_cycle08_mining.py with:
  - lineage_tag override
  - sampling_mode=family_first (cycle10 A++ ship; required for 19 family count)
  - objective_version=v2_nav_based (cycle10 default; not v3 — simpler)

Wall-clock estimate: ~50-90 min for 200 trials on 19-family pool
+ extended sampling (Family R chart-pattern + Family S regime).
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

import pandas as pd

from core.config.loader import load_config
from core.data.bar_store import BarStore
from core.factors.base_masks import research_mask_default
from core.factors.factor_generator import (
    compute_forward_returns, generate_all_factors,
)
from core.mining.rcm_archive import RCMArchive
from core.mining.research_miner import (
    FAMILY_A_V2, FAMILY_B_V2, FAMILY_C_V2, FAMILY_D_V2,
    FAMILY_E, FAMILY_F,
    FAMILY_R_CHART_PATTERNS, FAMILY_S_REGIME_ML,
    FAMILY_G_VOLUME_MICROSTRUCTURE, FAMILY_H_CONSOLIDATION,
    FAMILY_I_HIGHER_MOMENTS_AND_ANCHOR, FAMILY_J_CALENDAR,
    ObjectiveWeights, ResearchMiner,
)

# OHLCV-only families (factor_generator.generate_all_factors produces all).
# Excludes Family K/L/M/N (EDGAR fundamental), O (sector_map), P (FRED macro),
# Q (signal-confirmation multi-bar) — these need separate compute_* functions
# called via scripts/run_research_miner.py::_build_factor_panel_map and are
# not exercised in this direct-instantiation cycle12 first run.
FAMILIES_OHLCV_ONLY = [
    FAMILY_A_V2, FAMILY_B_V2, FAMILY_C_V2, FAMILY_D_V2,
    FAMILY_E, FAMILY_F,
    FAMILY_G_VOLUME_MICROSTRUCTURE, FAMILY_H_CONSOLIDATION,
    FAMILY_I_HIGHER_MOMENTS_AND_ANCHOR, FAMILY_J_CALENDAR,
    FAMILY_R_CHART_PATTERNS, FAMILY_S_REGIME_ML,
]
from core.research.harness import HarnessConfig
from core.research.risk_cluster_map import (
    ASSET_CLASS_BY_CLUSTER, CROSS_ASSET_RISK_CLUSTER_MAP,
    make_unified_cluster_map,
)
from core.research.temporal_split import load_temporal_split, partition_for_role

LINEAGE = "track-c-cycle-2026-05-14-12"
YAML_SHA = "4b39b5b3b3ad1b14b35d0d8e47d3d491b0b09296a2041f3db45e303a88ad575f"


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    log = logging.getLogger(__name__)
    log.info("=== Cycle12 mining (lineage=%s, yaml=%s) ===", LINEAGE, YAML_SHA[:16])
    t0 = time.time()

    cfg = load_config(PROJ / "config")
    store = BarStore(root=Path(cfg.system.paths.data_dir))
    uni = cfg.universe
    syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs)
        + list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    drop = {"BRK-B", "USO", "SLV"}
    syms = [s for s in syms if s not in uni.blacklist
            and s not in uni.macro_reference and s not in drop]
    for b in ("SPY", "QQQ"):
        if b not in syms:
            syms.append(b)

    log.info("Loading %d symbols...", len(syms))
    cross_asset_set = set(CROSS_ASSET_RISK_CLUSTER_MAP.keys())
    frames = {k: {} for k in ("close", "open", "high", "low", "volume")}
    for sym in syms:
        atr = sym in cross_asset_set
        df = store.load(sym, freq="1d", adjusted=True,
                        adjusted_total_return=atr, fallback="local")
        if df is None or df.empty or "close" not in df.columns:
            continue
        frames["close"][sym] = df["close"]
        for col in ("open", "high", "low", "volume"):
            if col in df.columns:
                frames[col][sym] = df[col]
    panel = {"close": pd.DataFrame(frames["close"]).sort_index()}
    panel["open"] = pd.DataFrame(frames["open"]).reindex_like(panel["close"])
    panel["high"] = pd.DataFrame(frames["high"]).reindex_like(panel["close"])
    panel["low"] = pd.DataFrame(frames["low"]).reindex_like(panel["close"])
    panel["volume"] = pd.DataFrame(frames["volume"]).reindex_like(panel["close"])

    split_cfg = load_temporal_split(PROJ / "config" / "temporal_split.yaml")
    panel = partition_for_role(panel, split_cfg, role="miner")
    log.info("Miner panel: %s (max date %s)",
             panel["close"].shape, panel["close"].index.max().date())

    bench = {b: panel["close"][b] for b in ("SPY", "QQQ") if b in panel["close"].columns}
    factors = generate_all_factors(
        panel["close"], volume_df=panel["volume"],
        open_df=panel["open"], high_df=panel["high"], low_df=panel["low"],
        benchmark_map=bench,
    )
    log.info("Generated %d factors", len(factors))
    mask = research_mask_default(panel["close"], panel["volume"])

    cluster_map = make_unified_cluster_map(include_cross_asset=True)
    asset_class_map = {
        sym: ASSET_CLASS_BY_CLUSTER[cluster_map[sym]]
        for sym in panel["close"].columns if sym in cluster_map
    }

    fwd_returns = compute_forward_returns(panel["close"], horizons=[21], mode="cc")

    spy = panel["close"].get("SPY")
    qqq = panel["close"].get("QQQ")

    hc = HarnessConfig(
        rebalance_cadence="monthly",
        construction_mode="cap_aware_cross_asset",
        top_n=10, cluster_cap=0.20, max_single_weight=0.10,
        cluster_map=cluster_map, asset_class_map=asset_class_map,
        asset_class_caps={
            "equities": 0.70, "bonds": 0.40,
            "commodities": 0.20, "cash_anchor": 0.30,
        },
    )

    archive = RCMArchive(PROJ / "data/mining/rcm_archive.db")

    # ObjectiveWeights v1_legacy default (cycle04-08 sibling-compatible).
    # cycle12 single-axis diff is factor pool, NOT objective change.
    weights = ObjectiveWeights()

    # fwd_returns is Dict[int, pd.DataFrame] keyed by horizon; pick 21d.
    fwd_21 = fwd_returns[21] if isinstance(fwd_returns, dict) else fwd_returns

    miner = ResearchMiner(
        factor_panel_map=factors,
        fwd_returns=fwd_21,
        mask=mask,
        families=FAMILIES_OHLCV_ONLY,
        objective_weights=weights,
        min_families=3,
        max_features_per_family=2,
        composite_weighting="equal_weight",
        target_n_features=3,
        horizon=21, lag=1,
        archive=archive,
        lineage_tag=LINEAGE,
        study_id="cycle12-2026-05-14",
        # factor_registry_pool=None: bypass pool reachability assert.
        # FAMILIES_OHLCV_ONLY is a strict SUBSET of RESEARCH_FACTORS; the
        # A++ reachability contract would fail closed if we declared pool
        # = RESEARCH_FACTORS but only sample OHLCV families.
        explicit_exclusions=(
            "intraday_autocorr_21d",
            "intraday_vol_ratio_21d",
            "realized_vol_60m_21d",
            # Family J FRED-event calendar factors (need macro data not loaded)
            "pre_fomc_window_flag", "post_fomc_window_flag",
            "pre_cpi_window_flag", "pre_nfp_window_flag",
        ),
        price_df=panel["close"], open_df=panel["open"],
        spy_series=spy, qqq_series=qqq,
        harness_config=hc,
        sampling_mode="family_first",  # cycle10 A++ ship; required for 19-family pool
    )

    log.info("Starting 200-trial TPE mining...")
    miner.mine(n_trials=200, seed=42, sampler="tpe")

    elapsed = time.time() - t0
    log.info("=== Cycle12 mining DONE (%.1f min, lineage=%s) ===",
             elapsed / 60, LINEAGE)
    log.info("Track A eval next: python dev/scripts/cycle06/cycle06_track_a_eval.py "
             "--lineage %s --top-n 3", LINEAGE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
