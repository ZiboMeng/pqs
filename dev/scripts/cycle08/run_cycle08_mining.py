"""Master PRD §4.3 Phase C.2 cycle08 200-trial mining (v3_regime_conditional).

Direct ResearchMiner construction (bypasses run_research_miner.py CLI which
doesn't yet wire v3 yaml parsing). Loads:
  - partition_for_role(role="miner") panel via cycle06/07a pattern
  - VIX from data/daily/_VIX.parquet
  - Daily regime labels via core.research.taa.regime_label_generator
  - 60m bars via BarStore for SR defer (R4 ship)
  - ObjectiveWeightsV3 from cycle08 yaml objective_weights_v3 block

Uses lineage_tag = track-c-cycle-2026-05-08-01 (yaml sha256
27e8a3e16e3a467f...).

Wall-clock estimate: ~95-130 min per master PRD §4.3 C.2 (200 trials
with regime-conditional IC + SR defer enabled).

Usage
-----
    python dev/scripts/cycle08/run_cycle08_mining.py
"""

from __future__ import annotations

import argparse
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
    compute_forward_returns,
    generate_all_factors,
)
from core.mining.rcm_archive import RCMArchive
from core.mining.research_miner import (
    FAMILIES_V2,
    ObjectiveWeightsV3,
    ResearchMiner,
)
from core.regime.regime_detector import RegimeDetector
from core.research.harness import HarnessConfig
from core.research.risk_cluster_map import (
    ASSET_CLASS_BY_CLUSTER,
    CROSS_ASSET_RISK_CLUSTER_MAP,
    make_unified_cluster_map,
)
from core.research.taa.regime_label_generator import daily_regime_labels
from core.research.temporal_split import (
    compute_split_sha256,
    load_temporal_split,
    partition_for_role,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


LINEAGE = "track-c-cycle-2026-05-08-01"
STUDY = "cycle08-2026-05-08"
N_TRIALS = 200
SEED = 42


def _load_panel_miner():
    """Load full universe + restrict to role='miner' (mirrors cycle06/07a)."""
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
    return panel, split_cfg, store


def _load_vix(path: Path = PROJ / "data/daily/_VIX.parquet") -> pd.Series:
    df = pd.read_parquet(path)
    return df["close"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--n-trials", type=int, default=N_TRIALS)
    args = ap.parse_args()

    log.info("Loading miner panel (partition_for_role role='miner')...")
    t0 = time.time()
    panel, split_cfg, store = _load_panel_miner()
    log.info(
        "  panel: %d dates × %d symbols (%.1fs)",
        panel["close"].shape[0], panel["close"].shape[1], time.time() - t0,
    )

    spy = panel["close"].get("SPY")
    qqq = panel["close"].get("QQQ")
    if spy is None:
        raise SystemExit("SPY missing from panel")

    log.info("Loading VIX + classifying daily regimes...")
    t0 = time.time()
    vix = _load_vix()
    vix = vix.reindex(panel["close"].index, method="ffill").dropna()
    cfg = load_config(PROJ / "config")
    detector = RegimeDetector(config=cfg.regime)
    common = spy.index.intersection(vix.index)
    regime_labels = daily_regime_labels(
        spy=spy.loc[common], vix=vix.loc[common], detector=detector,
    )
    log.info(
        "  daily_regime_labels: %d rows (%.1fs); distribution:",
        len(regime_labels), time.time() - t0,
    )
    for state, count in regime_labels.value_counts().items():
        pct = 100 * count / len(regime_labels)
        log.info("    %s: %d (%.1f%%)", state, count, pct)

    log.info("Generating factors (RESEARCH_FACTORS pool)...")
    t0 = time.time()
    bench = {b: panel["close"][b] for b in ("SPY", "QQQ")
             if b in panel["close"].columns}
    factors = generate_all_factors(
        panel["close"], volume_df=panel["volume"],
        open_df=panel["open"], high_df=panel["high"], low_df=panel["low"],
        benchmark_map=bench,
    )
    log.info("  %d factor panels (%.1fs)", len(factors), time.time() - t0)

    log.info("Loading 60m bars for SR defer (R4)...")
    t0 = time.time()
    intraday_bars: dict = {}
    for sym in panel["close"].columns:
        try:
            df = store.load(sym, freq="60m")
        except Exception:
            df = None
        if df is None or len(df) == 0:
            continue
        intraday_bars[sym] = df
    log.info(
        "  60m bars loaded for %d/%d symbols (%.1fs)",
        len(intraday_bars), panel["close"].shape[1], time.time() - t0,
    )

    log.info("Computing forward returns (horizon=21d)...")
    fwd_dict = compute_forward_returns(panel["close"], horizons=[21], mode="cc")
    fwd_returns = fwd_dict[21]
    log.info("  fwd_returns: %s", fwd_returns.shape)

    mask = (
        research_mask_default(panel["close"], panel["volume"])
        if panel["volume"] is not None else None
    )

    cluster_map = make_unified_cluster_map(include_cross_asset=True)
    asset_class_map = {
        sym: ASSET_CLASS_BY_CLUSTER[cluster_map[sym]]
        for sym in panel["close"].columns if sym in cluster_map
    }
    hc = HarnessConfig(
        rebalance_cadence="monthly",
        construction_mode="cap_aware_cross_asset",
        top_n=10, cluster_cap=0.20, max_single_weight=0.10,
        cluster_map=cluster_map,
        asset_class_map=asset_class_map,
        asset_class_caps={
            "equities": 0.70, "bonds": 0.40,
            "commodities": 0.20, "cash_anchor": 0.30,
        },
    )

    weights_v3 = ObjectiveWeightsV3(
        # Per-regime IR (per yaml objective_weights_v3)
        w_ir_BULL=0.5, w_ir_RISK_ON=0.5, w_ir_NEUTRAL=0.5,
        w_ir_CAUTIOUS=1.0, w_ir_RISK_OFF=1.5, w_ir_CRISIS=2.0,
        # Per-regime NAV-Sharpe
        w_nav_sharpe_BULL=0.10, w_nav_sharpe_BEAR=0.30,
        # Full-period
        w_nav_orthogonality=2.0, w_vs_qqq_excess=0.20,
    )

    archive_db = PROJ / "data/mining/rcm_archive.db"
    archive = RCMArchive(str(archive_db))

    split_sha = compute_split_sha256(PROJ / "config/temporal_split.yaml")

    # Universe panel for ResearchMiner: drop SPY/QQQ (benchmarks)
    universe_close = panel["close"].drop(
        columns=["SPY", "QQQ"], errors="ignore",
    )
    universe_open = (
        panel["open"].drop(columns=["SPY", "QQQ"], errors="ignore")
        if panel["open"] is not None else None
    )

    log.info("Building ResearchMiner with v3_regime_conditional...")
    miner = ResearchMiner(
        factor_panel_map=factors,
        fwd_returns=fwd_returns,
        mask=mask,
        families=FAMILIES_V2,
        objective_weights=weights_v3,
        min_families=3,
        max_features_per_family=2,
        composite_weighting="equal_weight",
        target_n_features=3,  # PRD-AC composite_cardinality=3
        horizon=21,
        lag=1,
        archive=archive,
        lineage_tag=LINEAGE,
        study_id=STUDY,
        split_name=split_cfg.split_name,
        split_sha256=split_sha,
        role="core",
        max_factor_lookback_days=split_cfg.access_rules.factor_warmup_max_lookback_days,
        factor_registry_pool="RESEARCH_FACTORS",
        explicit_exclusions=(
            "intraday_autocorr_21d", "intraday_vol_ratio_21d",
            "realized_vol_60m_21d",
        ),
        # Required for v3 + nav_active
        price_df=universe_close,
        open_df=universe_open,
        spy_series=spy,
        qqq_series=qqq,
        harness_config=hc,
        holding_freq_choices=("monthly", "weekly", "daily"),
        enable_sr_defer_choices=(False, True),  # R4 ship
        intraday_bars_60m=intraday_bars,
        daily_regime_labels=regime_labels,  # R6 wire
    )

    log.info(
        "Starting cycle08 mining (lineage=%s study=%s n_trials=%d)...",
        LINEAGE, STUDY, args.n_trials,
    )
    optuna_storage = f"sqlite:///{PROJ}/data/mining/rcm_optuna.db"
    t0 = time.time()
    results = miner.mine(
        n_trials=args.n_trials,
        seed=SEED,
        sampler="tpe",
        optuna_storage=optuna_storage,
        study_name=STUDY,
        load_if_exists=False,
    )
    elapsed = time.time() - t0
    log.info(
        "Mining done: %d trials with finite objective (of %d attempted) in %.1f min",
        len(results), args.n_trials, elapsed / 60.0,
    )
    for i, r in enumerate(results[:5], start=1):
        log.info(
            "  #%d obj=%+.4f IR=%+.3f corr=%.3f n_feat=%d feats=%s",
            i, r.objective, r.metrics.ic_ir, r.metrics.corr_concentration,
            r.spec.n_features, ",".join(r.spec.features),
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
