"""cycle09b §5.3 — second-seed replication (seed=42 → seed=123).

Re-runs cycle09b 200-trial mining identically EXCEPT the Optuna
sampler seed. If the top trial's spec and NAV trajectory reproduce
within tolerance, mining is robust to seed; if not, the verdict
becomes "seed-sensitive" which weakens the forward-init case.

Lineage / study suffix `-seed123` to keep original cycle09b archive
intact. Yaml sha256 lock is the SAME yaml file → verified identical
to the seed=42 run (immutability).

Output:
- archive lineage: track-c-cycle-2026-05-12-09b-seed123
- log: data/audit/cycle09b_seed123_mining.log (passed to file via
  redirect in caller)
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import yaml

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

# Reuse exactly the same helpers as the original frozen launcher.
from dev.scripts.cycle09.run_cycle09b_mining import (  # noqa: E402
    YAML_PATH,
    YAML_SHA256_LOCKED,
    _load_panel_miner,
    _build_extended_panel_map,
    _verify_yaml_sha256,
)
from core.factors.factor_generator import compute_forward_returns  # noqa: E402
from core.factors.base_masks import research_mask_default  # noqa: E402
from core.research.risk_cluster_map import (  # noqa: E402
    ASSET_CLASS_BY_CLUSTER,
    make_unified_cluster_map,
)
from core.research.harness import HarnessConfig  # noqa: E402
from core.mining.rcm_archive import RCMArchive  # noqa: E402
from core.mining.research_miner import (  # noqa: E402
    FAMILIES_V2,
    ObjectiveWeights,
    ResearchMiner,
)
from core.research.temporal_split import compute_split_sha256  # noqa: E402


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


LINEAGE = "track-c-cycle-2026-05-12-09b-seed123"
STUDY = "cycle09b-2026-05-12-seed123"
N_TRIALS = 200
SEED = 123


def main() -> int:
    log.info("=" * 70)
    log.info("cycle09b SEED=123 replication (audit §5.3)")
    log.info("=" * 70)

    log.info("Step 1: verify yaml sha256 lock (same yaml as cycle09b)")
    _verify_yaml_sha256()

    log.info("Step 2: parse yaml")
    d = yaml.safe_load(YAML_PATH.read_text())
    mc = d["mining_config"]
    log.info("  factor_registry_pool: %s", mc["factor_registry_pool"])
    log.info("  n_trials: %d", N_TRIALS)
    log.info("  sampling_mode: %s", mc.get("sampling_mode"))

    log.info("Step 3: load miner panel (partition_for_role role='miner')...")
    t0 = time.time()
    panel, split_cfg, store = _load_panel_miner()
    log.info(
        "  panel: %d dates × %d symbols (%.1fs)",
        panel["close"].shape[0], panel["close"].shape[1], time.time() - t0,
    )

    spy = panel["close"].get("SPY")
    qqq = panel["close"].get("QQQ")

    log.info("Step 4: build extended panel_map (6 compute paths)...")
    factors = _build_extended_panel_map(panel, store, list(panel["close"].columns))

    log.info("Step 5: compute forward returns (horizon=21d)...")
    fwd_dict = compute_forward_returns(panel["close"], horizons=[21], mode="cc")
    fwd_returns = fwd_dict[21]

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

    ow = ObjectiveWeights(**mc["objective_weights"])
    assert ow.is_nav_based()

    archive_db = PROJ / "data/mining/rcm_archive.db"
    archive = RCMArchive(str(archive_db))
    split_sha = compute_split_sha256(PROJ / "config/temporal_split.yaml")

    universe_close = panel["close"].drop(
        columns=["SPY", "QQQ"], errors="ignore",
    )
    universe_open = (
        panel["open"].drop(columns=["SPY", "QQQ"], errors="ignore")
        if panel["open"] is not None else None
    )

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
        study_id=STUDY,
        split_name=split_cfg.split_name,
        split_sha256=split_sha,
        role="core",
        max_factor_lookback_days=split_cfg.access_rules.factor_warmup_max_lookback_days,
        factor_registry_pool="RESEARCH_FACTORS",
        explicit_exclusions=tuple(mc["explicit_exclusions"]),
        price_df=universe_close,
        open_df=universe_open,
        spy_series=spy,
        qqq_series=qqq,
        harness_config=hc,
        holding_freq_choices=tuple(mc.get("holding_freq_choices") or ()),
        enable_sr_defer_choices=tuple(mc.get("enable_sr_defer_choices") or (False,)),
        auto_dedup_masked_factors=False,
        sampling_mode=mc.get("sampling_mode", "independent"),
    )

    log.info("Step 9: fire mining (seed=%d lineage=%s study=%s)",
             SEED, LINEAGE, STUDY)
    optuna_storage = f"sqlite:///{PROJ}/data/mining/rcm_optuna.db"
    t0 = time.time()
    results = miner.mine(
        n_trials=N_TRIALS,
        seed=SEED,
        sampler="tpe",
        optuna_storage=optuna_storage,
        study_name=STUDY,
        load_if_exists=False,
    )
    elapsed = time.time() - t0
    log.info(
        "Mining done: %d trials finite (of %d attempted) in %.1f min",
        len(results), N_TRIALS, elapsed / 60.0,
    )
    log.info("Top-5 trials:")
    for i, r in enumerate(results[:5], start=1):
        log.info(
            "  #%d obj=%+.4f IR=%+.3f n_feat=%d feats=%s",
            i, r.objective, r.metrics.ic_ir,
            r.spec.n_features, ",".join(r.spec.features),
        )

    log.info("=" * 70)
    log.info("seed=123 replication complete; lineage=%s", LINEAGE)
    log.info("Next: compare top-N specs vs seed=42 archive")
    log.info("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
