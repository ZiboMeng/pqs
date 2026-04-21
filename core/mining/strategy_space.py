"""
StrategySpec + ParameterSpace: 策略搜索空间定义。

每种策略类型对应一个 ParameterSpace 子类：
  - suggest(trial)   : Optuna trial → params dict
  - instantiate(...) : params dict + universe → 可调用的策略对象

新增策略类型时，只需继承 ParameterSpace 并注册到 ALL_SPACES。
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

try:
    import optuna
    _OPTUNA_AVAILABLE = True
except ImportError:
    _OPTUNA_AVAILABLE = False

from core.factors.factor_registry import PRODUCTION_FACTORS
from core.signals.strategies.dual_momentum import DualMomentumStrategy
from core.signals.strategies.trend_following import TrendFollowingStrategy
from core.signals.strategies.cross_asset_rotation import CrossAssetRotationStrategy
from core.signals.strategies.multi_factor import MultiFactorStrategy


# ── StrategySpec ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StrategySpec:
    """
    策略实例的不可变描述。

    Attributes
    ----------
    strategy_type : 策略类型标识符
    params        : 参数 k-v 元组（frozenset，确保可哈希）
    """
    strategy_type: str
    params:        Tuple[Tuple[str, Any], ...]   # sorted tuple of (k, v) pairs

    @classmethod
    def from_dict(cls, strategy_type: str, params: dict) -> "StrategySpec":
        return cls(
            strategy_type=strategy_type,
            params=tuple(sorted(params.items())),
        )

    @property
    def params_dict(self) -> Dict[str, Any]:
        return dict(self.params)

    @property
    def spec_id(self) -> str:
        """12-char SHA256 前缀，用于去重和存档键。"""
        raw = f"{self.strategy_type}:{sorted(self.params)}"
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    def __repr__(self) -> str:
        pd = self.params_dict
        return f"StrategySpec({self.strategy_type}, id={self.spec_id}, params={pd})"


# ── ParameterSpace base ───────────────────────────────────────────────────────

class ParameterSpace(ABC):
    """策略参数搜索空间基类。"""

    strategy_type: str = ""

    @abstractmethod
    def suggest(self, trial: Any) -> Dict[str, Any]:
        """从 Optuna trial 中采样参数（返回 params dict）。"""

    @abstractmethod
    def instantiate(
        self,
        params:        Dict[str, Any],
        risk_universe: Optional[List[str]] = None,
        def_universe:  Optional[List[str]] = None,
    ) -> Any:
        """从参数 dict 实例化策略对象。"""

    def make_spec(self, params: Dict[str, Any]) -> StrategySpec:
        return StrategySpec.from_dict(self.strategy_type, params)

    def random_params(self, seed: Optional[int] = None) -> Dict[str, Any]:
        """用 Optuna RandomSampler 采样一组参数（用于 baseline 测试）。"""
        if not _OPTUNA_AVAILABLE:
            raise ImportError("optuna is required")
        import optuna
        sampler = optuna.samplers.RandomSampler(seed=seed)
        study   = optuna.create_study(sampler=sampler)
        trial   = study.ask()
        params  = self.suggest(trial)
        study.tell(trial, 0.0)
        return params


# ── DualMomentum ─────────────────────────────────────────────────────────────

class DualMomentumSpace(ParameterSpace):
    """双重动量策略搜索空间。"""

    strategy_type = "dual_momentum"

    def suggest(self, trial: Any) -> Dict[str, Any]:
        return {
            "lookback_months":    trial.suggest_int("lookback_months", 3, 12),
            "top_n":              trial.suggest_int("top_n", 1, 5),
            "abs_momentum_rate":  trial.suggest_float("abs_momentum_rate", 0.0, 0.06, step=0.01),
            "rebalance_monthly":  trial.suggest_categorical("rebalance_monthly", [True, False]),
            "momentum_weighted":  trial.suggest_categorical("momentum_weighted", [True, False]),
        }

    def instantiate(
        self,
        params:        Dict[str, Any],
        risk_universe: Optional[List[str]] = None,
        def_universe:  Optional[List[str]] = None,
    ) -> DualMomentumStrategy:
        return DualMomentumStrategy(
            universe          = risk_universe,
            lookback_months   = params["lookback_months"],
            top_n             = params["top_n"],
            abs_momentum_rate = params["abs_momentum_rate"],
            rebalance_monthly = params["rebalance_monthly"],
            momentum_weighted = params["momentum_weighted"],
        )


# ── TrendFollowing ────────────────────────────────────────────────────────────

class TrendFollowingSpace(ParameterSpace):
    """趋势跟踪策略搜索空间。"""

    strategy_type = "trend_following"

    def suggest(self, trial: Any) -> Dict[str, Any]:
        slow_ema = trial.suggest_int("slow_ema", 100, 250, step=25)
        # fast_ema must be < slow_ema
        fast_ema = trial.suggest_int("fast_ema", 20, min(slow_ema - 10, 100), step=10)
        return {
            "slow_ema":             slow_ema,
            "fast_ema":             fast_ema,
            "use_fast_confirm":     trial.suggest_categorical("use_fast_confirm", [True, False]),
            "use_trend_direction":  trial.suggest_categorical("use_trend_direction", [True, False]),
        }

    def instantiate(
        self,
        params:        Dict[str, Any],
        risk_universe: Optional[List[str]] = None,
        def_universe:  Optional[List[str]] = None,
    ) -> TrendFollowingStrategy:
        return TrendFollowingStrategy(
            symbols             = risk_universe,
            fast_ema            = params["fast_ema"],
            slow_ema            = params["slow_ema"],
            use_fast_confirm    = params["use_fast_confirm"],
            use_trend_direction = params["use_trend_direction"],
        )


# ── CrossAssetRotation ────────────────────────────────────────────────────────

class CrossAssetRotationSpace(ParameterSpace):
    """跨资产轮动策略搜索空间。"""

    strategy_type = "cross_asset_rotation"

    def suggest(self, trial: Any) -> Dict[str, Any]:
        return {
            "lookback_months":   trial.suggest_int("lookback_months", 3, 12),
            "skip_months":       trial.suggest_int("skip_months", 0, 2),
            "top_n":             trial.suggest_int("top_n", 1, 4),
            "defensive_top_n":   trial.suggest_int("defensive_top_n", 1, 2),
            "rebalance_monthly": trial.suggest_categorical("rebalance_monthly", [True, False]),
            "momentum_weighted": trial.suggest_categorical("momentum_weighted", [True, False]),
        }

    def instantiate(
        self,
        params:        Dict[str, Any],
        risk_universe: Optional[List[str]] = None,
        def_universe:  Optional[List[str]] = None,
    ) -> CrossAssetRotationStrategy:
        return CrossAssetRotationStrategy(
            risk_assets       = risk_universe,
            defensive_assets  = def_universe or ["TLT", "GLD", "IEF"],
            lookback_months   = params["lookback_months"],
            skip_months       = params["skip_months"],
            top_n             = params["top_n"],
            defensive_top_n   = params["defensive_top_n"],
            rebalance_monthly = params["rebalance_monthly"],
            momentum_weighted = params["momentum_weighted"],
        )


# ── MultiFactorSpace ─────────────────────────────────────────────────────────

class MultiFactorSpace(ParameterSpace):
    """Multi-factor composite strategy search space.

    Invariant: every factor weight tuned here MUST be a name in
    PRODUCTION_FACTORS (core/factors/factor_registry.py). Trials with
    weights for unknown factors would be silently dropped by
    MultiFactorStrategy and produce misleading OOS stats. The assertion
    below catches drift — if PRODUCTION_FACTORS changes but this space
    doesn't, tests fail fast.
    """

    strategy_type = "multi_factor"
    # Factor weight slots this space tunes. Must equal PRODUCTION_FACTORS.
    _TUNED_FACTORS = {
        "low_vol", "momentum", "quality",
        "pv_div", "rel_strength", "market_trend",
    }

    def __init__(self) -> None:
        assert self._TUNED_FACTORS == PRODUCTION_FACTORS, (
            f"MultiFactorSpace tuned factors {self._TUNED_FACTORS} do not "
            f"match PRODUCTION_FACTORS {PRODUCTION_FACTORS}. Update "
            f"_TUNED_FACTORS and suggest() to match the registry."
        )

    def suggest(self, trial: Any) -> Dict[str, Any]:
        w_vol = trial.suggest_float("w_low_vol", 0.0, 0.15, step=0.05)
        w_mom = trial.suggest_float("w_momentum", 0.10, 0.30, step=0.05)
        w_qual = trial.suggest_float("w_quality", 0.15, 0.35, step=0.05)
        w_rs = trial.suggest_float("w_rel_strength", 0.10, 0.30, step=0.05)
        w_mt = trial.suggest_float("w_market_trend", 0.0, 0.15, step=0.05)
        w_pv = max(0.0, round(1.0 - w_vol - w_mom - w_qual - w_rs - w_mt, 2))
        return {
            "top_n":             trial.suggest_int("top_n", 4, 6),
            "w_low_vol":         w_vol,
            "w_momentum":        w_mom,
            "w_quality":         w_qual,
            "w_pv_div":          round(w_pv, 2),
            "w_rel_strength":    w_rs,
            "w_market_trend":    w_mt,
            "rebalance_monthly": trial.suggest_categorical("rebalance_monthly", [False]),
            "score_weighted":    trial.suggest_categorical("score_weighted", [True, False]),
            "lookback_vol":      trial.suggest_int("lookback_vol", 42, 126, step=21),
            "lookback_mom":      trial.suggest_int("lookback_mom", 126, 252, step=63),
            "lookback_quality":  trial.suggest_int("lookback_quality", 63, 252, step=63),
            "min_holding_days":  trial.suggest_int("min_holding_days", 3, 21, step=3),
        }

    def instantiate(
        self,
        params:        Dict[str, Any],
        risk_universe: Optional[List[str]] = None,
        def_universe:  Optional[List[str]] = None,
    ) -> MultiFactorStrategy:
        return MultiFactorStrategy(
            symbols           = risk_universe,
            top_n             = params["top_n"],
            factor_weights    = {
                "low_vol":       params["w_low_vol"],
                "momentum":      params["w_momentum"],
                "quality":       params["w_quality"],
                "pv_div":        params["w_pv_div"],
                "rel_strength":  params.get("w_rel_strength", 0.0),
                "market_trend":  params.get("w_market_trend", 0.0),
            },
            rebalance_monthly = params["rebalance_monthly"],
            score_weighted    = params["score_weighted"],
            lookback_vol      = params["lookback_vol"],
            lookback_mom      = params["lookback_mom"],
            lookback_quality  = params["lookback_quality"],
            min_holding_days  = params.get("min_holding_days", 5),
            apply_extra_shift = False,  # T+1-open execution already provides
                                        # the 1-bar lag; extra shift only
                                        # produces stale T-2 signals.
        )


# ── Registry ──────────────────────────────────────────────────────────────────

ALL_SPACES: List[ParameterSpace] = [
    DualMomentumSpace(),
    TrendFollowingSpace(),
    CrossAssetRotationSpace(),
    MultiFactorSpace(),
]


def instantiate_strategy(
    spec:          StrategySpec,
    risk_universe: Optional[List[str]] = None,
    def_universe:  Optional[List[str]] = None,
) -> Any:
    """从 StrategySpec 实例化策略对象（工厂函数）。"""
    space_map = {s.strategy_type: s for s in ALL_SPACES}
    space = space_map.get(spec.strategy_type)
    if space is None:
        raise ValueError(f"Unknown strategy type: {spec.strategy_type}")
    return space.instantiate(spec.params_dict, risk_universe, def_universe)
