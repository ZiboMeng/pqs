"""cycle #09 mining launcher: diversified-anchor search via 95-factor
expansion (RESEARCH_FACTORS = 162 post Bucket A/B/C/Macro).

Lineage: track-c-cycle-2026-05-12-09
Yaml: data/research_candidates/track-c-cycle-2026-05-12-09_promotion_criteria.yaml
Yaml sha256: 26c4176bc1beb87a4d80a970785e6fc2ef017a6d1db4365bb2f03816125b89ca

Single-axis differential vs cycle08:
  - factor_registry_pool: RESEARCH_FACTORS (162, up from 67 baseline)
  - explicit_exclusions: 12 (3 intraday + 2 cycle-anchor + 7 masked-dup)
  - objective_version: v2_nav_based (revert from v3_regime_conditional)
  - holding_freq_choices: [monthly] only (cycle08 had 3 choices)
  - enable_sr_defer_choices: [false] only (cycle08 had both)

cycle #09 is INDEPENDENT of Trial 9 verdict per
[[feedback_parallel_alpha_mining_default]]. Trial 9 v2 forward
observation begins 2026-05-13 EOD; cycle #09 produces standalone
candidate regardless of v2's TD60 verdict.

Wall-clock estimate: ~60-90 min for 200 trials with v2_nav_based +
cap_aware_cross_asset + FAMILIES_V2 (16 families, 150 reachable
post-exclusions). Cycle06 was ~80 min for similar config.

Compute paths (4-way panel_map):
  (1) OHLCV from generate_all_factors (families A-J)
  (2) Fundamental (EDGAR) from compute_fundamental_factors (families K-N)
  (3) Sector (yfinance + sector_map) from compute_sector_factors (family O)
  (4) Macro (FRED) from compute_macro_factors (family P)
  (5) Signal-conf multi-bar from compute_signal_confirmation_factors (family Q)
  (6) Event window from compute_event_window_factors (family J)

Usage:
    python dev/scripts/cycle09/run_cycle09_mining.py
    # or:
    python dev/scripts/cycle09/run_cycle09_mining.py --n-trials 16  # smoke
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
import yaml

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
    ObjectiveWeights,
    ResearchMiner,
)
from core.research.harness import HarnessConfig
from core.research.risk_cluster_map import (
    ASSET_CLASS_BY_CLUSTER,
    CROSS_ASSET_RISK_CLUSTER_MAP,
    make_unified_cluster_map,
)
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


LINEAGE = "track-c-cycle-2026-05-12-09"
STUDY = "cycle09-2026-05-12"
N_TRIALS = 200
SEED = 42
YAML_PATH = (
    PROJ / "data/research_candidates/"
    "track-c-cycle-2026-05-12-09_promotion_criteria.yaml"
)
YAML_SHA256_LOCKED = (
    "351e6e2ce004ef5a96a92ebe85f394ee193467dab78b60e4deb94c14ec0c424f"
)


def _verify_yaml_sha256():
    import hashlib
    data = YAML_PATH.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != YAML_SHA256_LOCKED:
        raise SystemExit(
            f"yaml sha256 mismatch:\n  expected: {YAML_SHA256_LOCKED}\n"
            f"  actual:   {actual}\n"
            f"yaml has been modified since lock — immutability violated"
        )
    log.info("  yaml sha256 verified: %s", actual)


def _load_panel_miner():
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


def _build_extended_panel_map(panel, store, sym_list):
    """Build cycle #09 panel_map merging 6 compute paths.

    Mirrors `scripts/run_research_miner.py::_build_factor_panel_map`
    (canonical impl) to ensure signature parity. Returns
    dict[factor_name → DataFrame] covering RESEARCH_FACTORS.
    """
    from core.factors.factor_registry import RESEARCH_FACTORS

    close = panel["close"]
    volume = panel["volume"]
    tickers = list(close.columns)
    daily_idx = close.index
    bench = {b: close[b] for b in ("SPY", "QQQ") if b in close.columns}

    # (1) OHLCV factors via generate_all_factors
    log.info("  Path (1) OHLCV factors via generate_all_factors...")
    t0 = time.time()
    factors = generate_all_factors(
        close, volume_df=volume,
        open_df=panel["open"], high_df=panel["high"], low_df=panel["low"],
        benchmark_map=bench,
    )
    panel_map = {n: f for n, f in factors.items() if n in RESEARCH_FACTORS}
    log.info("    %d OHLCV panels (%.1fs)", len(panel_map), time.time() - t0)

    # (2) Fundamental factors (families K-N) from EDGAR cache
    log.info("  Path (2) Fundamental factors via compute_fundamental_factors_full...")
    t0 = time.time()
    try:
        from core.factors.fundamental_factors import (
            compute_fundamental_factors_full,
        )
        from core.data.fundamentals_store import FundamentalsStore
        fstore = FundamentalsStore()
        fund = compute_fundamental_factors_full(
            daily_idx, tickers, store=fstore, price_df=close,
        )
        added = 0
        for n, f in fund.items():
            if n in RESEARCH_FACTORS:
                panel_map[n] = f
                added += 1
        log.info("    %d fundamental panels (%.1fs)", added, time.time() - t0)
    except Exception as e:
        log.warning("    fundamental compute SKIPPED: %s", e)

    # (3) Sector factors (family O)
    log.info("  Path (3) Sector factors via compute_sector_factors...")
    t0 = time.time()
    try:
        from core.factors.sector_factors import compute_sector_factors
        sect = compute_sector_factors(close)
        added = 0
        for n, f in sect.items():
            if n in RESEARCH_FACTORS:
                panel_map[n] = f
                added += 1
        log.info("    %d sector panels (%.1fs)", added, time.time() - t0)
    except Exception as e:
        log.warning("    sector compute SKIPPED: %s", e)

    # (4) Macro factors (family P)
    log.info("  Path (4) Macro factors via compute_macro_factors...")
    t0 = time.time()
    try:
        from core.factors.macro_factors import compute_macro_factors
        macro = compute_macro_factors(daily_idx, tickers)
        added = 0
        for n, f in macro.items():
            if n in RESEARCH_FACTORS:
                panel_map[n] = f
                added += 1
        log.info("    %d macro panels (%.1fs)", added, time.time() - t0)
    except Exception as e:
        log.warning("    macro compute SKIPPED: %s", e)

    # (5) Event window factors (family J extension; FOMC/CPI/NFP)
    log.info("  Path (5) Event window factors via compute_event_window_factors...")
    t0 = time.time()
    try:
        from core.factors.event_window_factors import (
            compute_event_window_factors,
        )
        events = compute_event_window_factors(daily_idx, tickers)
        added = 0
        for n, f in events.items():
            if n in RESEARCH_FACTORS:
                panel_map[n] = f
                added += 1
        log.info("    %d event window panels (%.1fs)", added, time.time() - t0)
    except Exception as e:
        log.warning("    event window compute SKIPPED: %s", e)

    # (6) Signal-conf factors (family Q)
    log.info("  Path (6) Signal-conf factors via compute_signal_confirmation_factors...")
    t0 = time.time()
    try:
        from core.factors.signal_confirmation_factors import (
            compute_signal_confirmation_factors,
        )
        sigconf = compute_signal_confirmation_factors(close, volume)
        added = 0
        for n, f in sigconf.items():
            if n in RESEARCH_FACTORS:
                panel_map[n] = f
                added += 1
        log.info("    %d signal-conf panels (%.1fs)", added, time.time() - t0)
    except Exception as e:
        log.warning("    signal-conf compute SKIPPED: %s", e)

    log.info(
        "  Total panel_map: %d factors (target = 162 RESEARCH_FACTORS)",
        len(panel_map),
    )
    return panel_map


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--n-trials", type=int, default=N_TRIALS)
    ap.add_argument("--smoke", action="store_true",
                    help="Run 16-trial smoke instead of full 200")
    args = ap.parse_args()
    if args.smoke:
        args.n_trials = 16

    # Study name: full fire uses canonical (cycle09-2026-05-12); smoke
    # uses timestamped variant to avoid optuna UNIQUE constraint collision
    # across multiple smoke runs.
    if args.smoke:
        import datetime
        ts = datetime.datetime.now().strftime("%H%M%S")
        study_name = f"{STUDY}-smoke-{ts}"
    else:
        study_name = STUDY

    log.info("=" * 70)
    log.info("cycle #09 mining: %s", LINEAGE)
    log.info("=" * 70)
    log.info("Step 1: verify yaml sha256 lock")
    _verify_yaml_sha256()

    log.info("Step 2: parse yaml")
    d = yaml.safe_load(YAML_PATH.read_text())
    mc = d["mining_config"]
    log.info("  factor_registry_pool: %s", mc["factor_registry_pool"])
    log.info("  n_trials: %d (--n-trials override = %d)", mc["n_trials"], args.n_trials)
    log.info("  explicit_exclusions: %d", len(mc["explicit_exclusions"]))
    log.info("  objective_version: %s", mc["objective_version"])

    log.info("Step 3: load miner panel (partition_for_role role='miner')...")
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

    log.info("Step 4: build extended panel_map (6 compute paths)...")
    factors = _build_extended_panel_map(panel, store, list(panel["close"].columns))

    log.info("Step 5: compute forward returns (horizon=21d)...")
    fwd_dict = compute_forward_returns(panel["close"], horizons=[21], mode="cc")
    fwd_returns = fwd_dict[21]
    log.info("  fwd_returns: %s", fwd_returns.shape)

    mask = (
        research_mask_default(panel["close"], panel["volume"])
        if panel["volume"] is not None else None
    )

    log.info("Step 6: cluster_map + asset_class_map (cap_aware_cross_asset)...")
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

    log.info("Step 7: build ObjectiveWeights from yaml v2_nav_based...")
    ow = ObjectiveWeights(**mc["objective_weights"])
    log.info(
        "  ObjectiveWeights: w_ir=%.2f w_nav_sharpe=%.2f w_nav_orth=%.2f w_vs_qqq=%.2f",
        ow.w_ir, ow.w_nav_sharpe, ow.w_nav_orthogonality, ow.w_vs_qqq_excess,
    )
    assert ow.is_nav_based(), "v2_nav_based requires is_nav_based()=True"

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

    log.info("Step 8: build ResearchMiner...")
    miner = ResearchMiner(
        factor_panel_map=factors,
        fwd_returns=fwd_returns,
        mask=mask,
        families=FAMILIES_V2,
        objective_weights=ow,
        min_families=mc["min_families"],
        max_features_per_family=mc["max_features_per_family"],
        composite_weighting=mc["composite_weighting"],
        target_n_features=mc["composite_cardinality"],
        horizon=21,
        lag=1,
        archive=archive,
        lineage_tag=LINEAGE,
        study_id=study_name,
        split_name=split_cfg.split_name,
        split_sha256=split_sha,
        role="core",
        max_factor_lookback_days=split_cfg.access_rules.factor_warmup_max_lookback_days,
        factor_registry_pool="RESEARCH_FACTORS",
        explicit_exclusions=tuple(mc["explicit_exclusions"]),
        # v2_nav_based requires panel inputs:
        price_df=universe_close,
        open_df=universe_open,
        spy_series=spy,
        qqq_series=qqq,
        harness_config=hc,
        holding_freq_choices=tuple(mc.get("holding_freq_choices") or ()),
        enable_sr_defer_choices=tuple(mc.get("enable_sr_defer_choices") or (False,)),
        # cycle #09 does NOT auto-dedup (yaml-static explicit_exclusions handle it)
        auto_dedup_masked_factors=False,
    )

    log.info(
        "Step 9: fire mining (lineage=%s study=%s n_trials=%d)",
        LINEAGE, study_name, args.n_trials,
    )
    optuna_storage = f"sqlite:///{PROJ}/data/mining/rcm_optuna.db"
    t0 = time.time()
    results = miner.mine(
        n_trials=args.n_trials,
        seed=SEED,
        sampler="tpe",
        optuna_storage=optuna_storage,
        study_name=study_name,
        load_if_exists=False,
    )
    elapsed = time.time() - t0
    log.info(
        "Mining done: %d trials with finite objective (of %d attempted) in %.1f min",
        len(results), args.n_trials, elapsed / 60.0,
    )
    log.info("Top-5 trials by objective:")
    for i, r in enumerate(results[:5], start=1):
        log.info(
            "  #%d obj=%+.4f IR=%+.3f corr=%.3f n_feat=%d feats=%s",
            i, r.objective, r.metrics.ic_ir, r.metrics.corr_concentration,
            r.spec.n_features, ",".join(r.spec.features),
        )

    log.info("=" * 70)
    log.info("cycle #09 mining complete. Next: cycle09_closeout_analysis.py")
    log.info("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
