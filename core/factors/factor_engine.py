"""
FactorEngine: 单因子统计计算。

提供的计算
----------
  compute_ic          — 截面 IC（Pearson）时间序列
  compute_rank_ic     — 截面 Rank IC（Spearman）时间序列
  compute_ir          — IC 信息比率 = mean(IC) / std(IC)
  compute_ic_decay    — IC 衰减曲线（不同预测期 lag=1..max_lag）
  compute_factor_stats — 汇总统计：mean_ic / ic_std / ir / t_stat / ic_positive_ratio

命名约定
--------
  factor_df  : pd.DataFrame，index=日期，columns=symbol，值=因子暴露（截面）
  returns_df : pd.DataFrame，index=日期，columns=symbol，值=前向收益率（同截面）
  ic_series  : pd.Series，index=日期，值=该日 IC
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from core.logging_setup import get_logger

logger = get_logger(__name__)


def _hac_ttest_mean0(x: np.ndarray, lag: int) -> tuple[float, float]:
    """Newey-West (Bartlett) HAC t-test of H0: mean(x)=0.

    P0-B / audit P1-2. Serially-autocorrelated IC (overlapping
    horizon-day labels) → iid t overstates significance. Bartlett-
    weighted long-run variance of the sample mean:
        S = γ0 + 2 Σ_{k=1}^{L} (1 - k/(L+1)) γk ,  γk = autocov at lag k
        Var(mean) = S / n ;  t = mean / sqrt(Var(mean))
    statsmodels intentionally NOT used (no heavy dep — project stance).
    Degenerate S≤0 (strong negative autocorr) → fall back to iid var.
    Two-sided p from the t-distribution with n-1 df.
    """
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = x.size
    if n < 2:
        return float("nan"), float("nan")
    mu = x.mean()
    e = x - mu
    g0 = float(e @ e) / n
    L = max(1, min(int(lag), n // 4))
    s = g0
    for k in range(1, L + 1):
        gk = float(e[k:] @ e[:-k]) / n
        s += 2.0 * (1.0 - k / (L + 1.0)) * gk
    if not np.isfinite(s) or s <= 0.0:          # degenerate → iid
        s = float(x.var(ddof=1))
    var_mean = s / n
    if var_mean <= 0.0:
        return float("nan"), float("nan")
    t = mu / np.sqrt(var_mean)
    p = 2.0 * scipy_stats.t.sf(abs(t), df=n - 1)
    return float(t), float(p)


# ── 汇总统计结果 ──────────────────────────────────────────────────────────────

@dataclass
class FactorStats:
    """单因子的汇总统计指标。"""
    factor_name:       str
    horizon:           int              # 预测期（天数）
    n_periods:         int              # 有效 IC 观测数
    mean_ic:           float
    ic_std:            float
    ir:                float            # mean_ic / ic_std
    t_stat:            float            # t 检验统计量
    p_value:           float            # 双尾 p 值
    ic_positive_ratio: float            # IC > 0 的比例
    ic_gt_02_ratio:    float            # |IC| > 0.02 的比例（绝对方向）

    @property
    def is_significant(self) -> bool:
        """IR > 0.3 且 p_value < 0.05 时认为显著。"""
        return abs(self.ir) > 0.3 and self.p_value < 0.05

    def __str__(self) -> str:
        sig = "★" if self.is_significant else " "
        return (
            f"{sig} [{self.factor_name} H{self.horizon}]  "
            f"IC={self.mean_ic:.4f}  IR={self.ir:.3f}  "
            f"t={self.t_stat:.2f}  p={self.p_value:.3f}  "
            f"n={self.n_periods}  IC+%={self.ic_positive_ratio:.1%}"
        )


# ── FactorEngine ──────────────────────────────────────────────────────────────

class FactorEngine:
    """
    单因子统计引擎。无状态，所有方法均为纯函数风格。

    典型用法
    --------
        engine = FactorEngine()
        ic     = engine.compute_rank_ic(factor_df, fwd_returns)
        stats  = engine.compute_factor_stats(ic, factor_name="momentum_60d", horizon=5)
    """

    # ── IC 计算 ───────────────────────────────────────────────────────────────

    @staticmethod
    def compute_ic(
        factor_df:   pd.DataFrame,
        returns_df:  pd.DataFrame,
    ) -> pd.Series:
        """
        每日截面 IC（Pearson 相关系数）。

        对 factor_df 和 returns_df 按日期对齐后，逐日计算截面相关。
        至少需要 3 个共同 symbol 才计算该日；否则该日 IC = NaN。

        Returns
        -------
        pd.Series  index=日期，值=该日 Pearson IC
        """
        f, r = factor_df.align(returns_df, join="inner")
        return _rolling_crosssection_corr(f, r, method="pearson")

    @staticmethod
    def compute_rank_ic(
        factor_df:  pd.DataFrame,
        returns_df: pd.DataFrame,
    ) -> pd.Series:
        """
        每日截面 Rank IC（Spearman 秩相关）。

        Rank IC 对异常值更稳健，通常是因子研究的首选指标。
        """
        f, r = factor_df.align(returns_df, join="inner")
        return _rolling_crosssection_corr(f, r, method="spearman")

    # ── 汇总统计 ──────────────────────────────────────────────────────────────

    @staticmethod
    def compute_ir(ic_series: pd.Series) -> float:
        """
        IR = mean(IC) / std(IC)。

        std 使用样本标准差（ddof=1）。若 std==0 或样本不足则返回 NaN。
        """
        valid = ic_series.dropna()
        if len(valid) < 2:
            return np.nan
        std = valid.std(ddof=1)
        if std < 1e-10:
            return np.nan
        return float(valid.mean() / std)

    @staticmethod
    def compute_factor_stats(
        ic_series:   pd.Series,
        factor_name: str = "factor",
        horizon:     int = 1,
    ) -> FactorStats:
        """
        从 IC 时序计算完整的汇总统计。

        Parameters
        ----------
        ic_series  : compute_ic / compute_rank_ic 的输出
        factor_name: 因子标识字符串（用于报告展示）
        horizon    : 预测期天数。**P0-B 后影响计算**：HAC t 检验的
                     Bartlett lag = max(1, horizon-1)（重叠 label 的
                     自相关长度），其余统计不依赖 horizon。
        """
        valid = ic_series.dropna()
        n     = len(valid)

        if n < 2:
            return FactorStats(
                factor_name=factor_name, horizon=horizon, n_periods=n,
                mean_ic=np.nan, ic_std=np.nan, ir=np.nan,
                t_stat=np.nan, p_value=np.nan,
                ic_positive_ratio=np.nan, ic_gt_02_ratio=np.nan,
            )

        mean_ic = float(valid.mean())
        ic_std  = float(valid.std(ddof=1))
        ir      = mean_ic / ic_std if ic_std > 0 else np.nan

        # P0-B / audit P1-2: HAC (Newey-West, Bartlett) t-test, NOT
        # plain ttest_1samp. Overlapping ``horizon``-day forward-return
        # labels make the per-date IC series serially autocorrelated →
        # iid t overstates significance (Harvey-Liu-Zhu). Bartlett lag
        # tied to label overlap = max(1, horizon-1), capped n//4 for NW
        # stability; degenerate NW var (≤0) falls back to iid variance.
        t_stat, p_value = _hac_ttest_mean0(valid.values,
                                           max(1, int(horizon) - 1))

        ic_positive_ratio = float((valid > 0).mean())
        ic_gt_02_ratio    = float((valid.abs() > 0.02).mean())

        return FactorStats(
            factor_name       = factor_name,
            horizon           = horizon,
            n_periods         = n,
            mean_ic           = mean_ic,
            ic_std            = ic_std,
            ir                = float(ir) if not np.isnan(ir) else np.nan,
            t_stat            = float(t_stat),
            p_value           = float(p_value),
            ic_positive_ratio = ic_positive_ratio,
            ic_gt_02_ratio    = ic_gt_02_ratio,
        )

    # ── IC 衰减 ───────────────────────────────────────────────────────────────

    @staticmethod
    def compute_ic_decay(
        factor_df:   pd.DataFrame,
        price_df:    pd.DataFrame,
        max_lag:     int = 20,
        method:      str = "spearman",
    ) -> pd.DataFrame:
        """
        计算 IC 衰减曲线。

        对同一截面因子暴露，分别计算 lag=1,2,...,max_lag 日后的前向收益 IC。
        返回 DataFrame，index=lag，columns=['mean_ic','ir','n']。

        Parameters
        ----------
        factor_df : 因子暴露矩阵，index=日期，columns=symbol
        price_df  : close 价格矩阵，index=日期，columns=symbol
        max_lag   : 最大预测期
        method    : 'pearson' 或 'spearman'
        """
        rows = []
        for lag in range(1, max_lag + 1):
            fwd_ret = price_df.pct_change(lag).shift(-lag)
            fwd_ret, fac = fwd_ret.align(factor_df, join="inner")
            ic = _rolling_crosssection_corr(fac, fwd_ret, method=method)
            valid = ic.dropna()
            if len(valid) < 2:
                rows.append({"lag": lag, "mean_ic": np.nan, "ir": np.nan, "n": len(valid)})
            else:
                mean_ic = valid.mean()
                ir      = mean_ic / valid.std(ddof=1) if valid.std(ddof=1) > 0 else np.nan
                rows.append({"lag": lag, "mean_ic": float(mean_ic), "ir": float(ir), "n": len(valid)})

        df = pd.DataFrame(rows).set_index("lag")
        return df

    # ── 前向收益构造（研究专用） ───────────────────────────────────────────────

    @staticmethod
    def make_forward_returns(
        price_df: pd.DataFrame,
        horizon:  int = 5,
        mode:     str = "cc",
        open_df:  Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """
        [研究专用] 构造 horizon 日前向收益率（使用未来价格）。

        ⚠️  此函数通过 shift(-horizon) 引用未来数据，仅供离线因子研究使用。
            严禁在以下场景中调用：
            - 实盘 / 模拟盘信号生成路径
            - BacktestEngine.run() 之前的信号预处理
            - 任何以"当前时点"为基准的计算

        如需滞后收益率（历史数据，无未来泄漏），请使用
        make_lagged_returns(price_df, horizon) 代替。

        PRD 20260423 R04/R13 label-mode extension (symmetric with
        `compute_forward_returns`):
          - mode="cc" (default, backward-compat):
                close[t+h] / close[t] - 1
          - mode="oc":
                close[t+h] / open[t+h] - 1  (requires open_df)
          - mode="oo":
                open[t+h] / open[t] - 1     (requires open_df)

        Returns
        -------
        pd.DataFrame  与 price_df 形状相同；末尾 horizon 行为 NaN（真实未来不可得）
        """
        if mode not in {"cc", "oc", "oo"}:
            raise ValueError(f"mode must be one of cc/oc/oo, got {mode!r}")
        if mode in {"oc", "oo"} and open_df is None:
            raise ValueError(f"mode={mode!r} requires open_df")
        if mode == "cc":
            return price_df.pct_change(horizon).shift(-horizon)
        elif mode == "oc":
            oc = price_df / open_df.reindex_like(price_df) - 1.0
            return oc.shift(-horizon)
        else:  # "oo"
            oo = open_df.pct_change(horizon)
            return oo.reindex_like(price_df).shift(-horizon)

    @staticmethod
    def make_lagged_returns(
        price_df: pd.DataFrame,
        horizon:  int = 5,
    ) -> pd.DataFrame:
        """
        构造 horizon 日滞后收益率（仅使用过去数据，无未来泄漏）。

        用于实盘/模拟盘路径的特征工程。
        值 = price_df.pct_change(horizon)，前 horizon 行为 NaN。

        Returns
        -------
        pd.DataFrame  与 price_df 形状相同；前 horizon 行为 NaN
        """
        return price_df.pct_change(horizon)


# ── 内部工具 ──────────────────────────────────────────────────────────────────

def _rolling_crosssection_corr(
    factor_df:  pd.DataFrame,
    returns_df: pd.DataFrame,
    method:     str = "spearman",
    min_symbols: int = 3,
) -> pd.Series:
    """
    逐日计算截面相关系数。

    factor_df 和 returns_df 必须已按 join='inner' 对齐。
    """
    results = {}
    for date in factor_df.index:
        f = factor_df.loc[date].dropna()
        r = returns_df.loc[date].dropna() if date in returns_df.index else pd.Series(dtype=float)

        common = f.index.intersection(r.index)
        if len(common) < min_symbols:
            results[date] = np.nan
            continue

        f_vals = f[common].values
        r_vals = r[common].values

        if method == "pearson":
            corr, _ = scipy_stats.pearsonr(f_vals, r_vals)
        else:
            corr, _ = scipy_stats.spearmanr(f_vals, r_vals)

        results[date] = float(corr)

    return pd.Series(results, name=f"ic_{method}")
