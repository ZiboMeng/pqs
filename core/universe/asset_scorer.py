"""
AssetScorer: 对候选 symbol 按多维度打分，输出排名供选股使用。

打分维度（均归一化到 [0, 1]，越高越好）
--------------------------------------
  momentum    — 多周期动量加权均值（ret_20d × 0.3 + ret_60d × 0.5 + ret_120d × 0.2）
  stability   — 低波动性得分（1 - rank(hv20)，波动越小得分越高）
  liquidity   — 相对成交量活跃度（rank(volume_surge20)）
  composite   — 三维加权综合得分（默认权重 0.5 / 0.3 / 0.2）

使用方式
--------
    scorer = AssetScorer()
    # features: Dict[symbol → feature DataFrame（compute_daily_features 输出）]
    scores = scorer.score(features)
    top5   = scorer.top_n(scores, n=5)
"""

from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from core.logging_setup import get_logger

logger = get_logger(__name__)

# 动量权重：短 / 中 / 长周期
_MOMENTUM_WINDOWS = [
    ("ret_20d",  0.30),
    ("ret_60d",  0.50),
    ("ret_120d", 0.20),
]

# 综合得分权重
_DEFAULT_WEIGHTS = {
    "momentum":  0.50,
    "stability": 0.30,
    "liquidity": 0.20,
}


class AssetScorer:
    """
    对候选 symbol 集合进行横截面打分。

    Parameters
    ----------
    weights : dict, optional
        三个维度的自定义权重 {'momentum': x, 'stability': y, 'liquidity': z}，
        不需要加总为 1（内部会归一化）。
    min_symbols : int
        打分所需最少 symbol 数量，不足时返回 None 并记录警告。
    """

    def __init__(
        self,
        weights:     Optional[Dict[str, float]] = None,
        min_symbols: int = 2,
    ):
        w = weights or _DEFAULT_WEIGHTS
        total = sum(w.values())
        self.weights     = {k: v / total for k, v in w.items()}   # 归一化
        self.min_symbols = min_symbols

    # ── 公开 API ──────────────────────────────────────────────────────────────

    def score(
        self,
        features: Dict[str, pd.DataFrame],
    ) -> Optional[pd.DataFrame]:
        """
        对所有 symbol 打分。

        Parameters
        ----------
        features : dict[symbol → feature DataFrame]
            每个 DataFrame 是 compute_daily_features() 的输出，
            至少包含最近一行有效数据。

        Returns
        -------
        pd.DataFrame  index=symbols, columns=['momentum','stability','liquidity','composite']
        返回 None 如果有效 symbol 数量不足 min_symbols。
        """
        if len(features) < self.min_symbols:
            logger.warning(
                "AssetScorer: only %d symbols, need >= %d — skipping scoring",
                len(features), self.min_symbols,
            )
            return None

        raw = self._extract_latest(features)
        if raw.empty:
            return None

        result             = pd.DataFrame(index=raw.index)
        result["momentum"] = self._momentum_score(raw)
        result["stability"] = self._stability_score(raw)
        result["liquidity"] = self._liquidity_score(raw)
        result["composite"] = (
            result["momentum"]  * self.weights["momentum"]
            + result["stability"] * self.weights["stability"]
            + result["liquidity"] * self.weights["liquidity"]
        )

        return result.sort_values("composite", ascending=False)

    def top_n(
        self,
        scores: pd.DataFrame,
        n:      int,
        exclude: Optional[List[str]] = None,
    ) -> List[str]:
        """
        从评分 DataFrame 中取前 N 个 symbol。

        Parameters
        ----------
        scores  : score() 返回的 DataFrame
        n       : 取前 N 名
        exclude : 需要排除的 symbol 列表（如高风险品种限制时使用）
        """
        df = scores.copy()
        if exclude:
            df = df[~df.index.isin(exclude)]
        return df.head(n).index.tolist()

    def rank(
        self,
        scores: pd.DataFrame,
        by:     str = "composite",
    ) -> pd.Series:
        """返回按指定维度排名的 Series（1 = 最好）。"""
        if by not in scores.columns:
            raise ValueError(f"Column '{by}' not in scores DataFrame")
        return scores[by].rank(ascending=False).astype(int)

    # ── 内部打分逻辑 ──────────────────────────────────────────────────────────

    @staticmethod
    def _extract_latest(features: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        """
        从每个 symbol 的 feature DataFrame 中提取最后一行有效数据。
        返回 DataFrame，index = symbol，columns = 特征名。
        """
        rows = {}
        for sym, df in features.items():
            if df is None or df.empty:
                continue
            # 取最后一行非全 NaN 的行
            valid = df.dropna(how="all")
            if valid.empty:
                continue
            rows[sym] = valid.iloc[-1]

        if not rows:
            return pd.DataFrame()

        return pd.DataFrame(rows).T   # shape: (n_symbols, n_features)

    @staticmethod
    def _momentum_score(raw: pd.DataFrame) -> pd.Series:
        """
        多周期动量加权打分，归一化到 [0, 1]。

        若某窗口列缺失则跳过，只用存在的列加权平均后再做横截面百分位排名。
        """
        available  = [(col, w) for col, w in _MOMENTUM_WINDOWS if col in raw.columns]
        if not available:
            return pd.Series(0.5, index=raw.index)

        total_w = sum(w for _, w in available)
        mom = sum(
            raw[col].fillna(0.0) * (w / total_w)
            for col, w in available
        )
        return _percentile_rank(mom)

    @staticmethod
    def _stability_score(raw: pd.DataFrame) -> pd.Series:
        """
        稳定性 = 低波动优先。
        先取 hv20（20日年化波动率），横截面百分位排名后取反（低波动 → 高得分）。
        若无 hv20 则 fallback 到 atr_pct14。
        """
        if "hv20" in raw.columns:
            vol = raw["hv20"].fillna(raw["hv20"].median())
        elif "atr_pct14" in raw.columns:
            vol = raw["atr_pct14"].fillna(raw["atr_pct14"].median())
        else:
            return pd.Series(0.5, index=raw.index)

        return 1.0 - _percentile_rank(vol)   # 波动越低，得分越高

    @staticmethod
    def _liquidity_score(raw: pd.DataFrame) -> pd.Series:
        """
        流动性 = 成交量活跃度。
        用 volume_surge20（成交量相对20日均值的倍数）横截面百分位排名。
        """
        if "volume_surge20" in raw.columns:
            surge = raw["volume_surge20"].fillna(1.0)
        else:
            return pd.Series(0.5, index=raw.index)

        return _percentile_rank(surge)


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _percentile_rank(series: pd.Series) -> pd.Series:
    """
    横截面百分位排名，归一化到 [0, 1]。
    最大值 → 1.0，最小值 → 0.0；只有一个值时返回 0.5。
    """
    n = series.notna().sum()
    if n <= 1:
        return pd.Series(0.5, index=series.index)
    ranked = series.rank(method="average", na_option="keep")
    return (ranked - 1) / (n - 1)
