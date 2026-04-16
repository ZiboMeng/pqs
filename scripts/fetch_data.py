#!/usr/bin/env python3
"""
scripts/fetch_data.py — 批量下载/增量更新市场数据。

用法
----
    python scripts/fetch_data.py                   # 更新所有配置中的 symbol
    python scripts/fetch_data.py --symbols SPY QQQ # 只更新指定 symbol
    python scripts/fetch_data.py --full            # 强制全量重新下载（覆盖现有数据）
    python scripts/fetch_data.py --daily-only      # 只下载日线，跳过日内
    python scripts/fetch_data.py --intraday-only   # 只下载日内

下载范围
--------
  日线  : 2013-01-01 至今（自动增量）
  日内  : 60m / 30m / 15m，回看 700 天（yfinance 60m 免费上限约 730 天）
  宏观  : ^VIX / ^TNX / DX-Y.NYB（仅日线，用于 regime 计算）
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from core.config.loader import load_config
from core.data.market_data_store import MarketDataStore
from core.data.yfinance_provider import YFinanceProvider
from core.data.validator import DataValidator
from core.logging_setup import get_logger, setup_logging

setup_logging()
logger = get_logger("fetch_data")

_DEFAULT_START_DATE  = "2007-01-01"
_INTRADAY_FREQS      = ["60m", "30m", "15m"]
_INTRADAY_LOOKBACK_DAYS = 700   # yfinance 60m 免费限制约 730 天


def get_all_symbols(cfg) -> dict:
    """从 universe.yaml 收集所有需要下载的 symbol。"""
    uni = cfg.universe
    tradeable = (
        list(uni.seed_pool)
        + list(uni.sector_etfs)
        + list(uni.factor_etfs)
        + list(uni.cross_asset)
    )
    macro = list(uni.macro_reference)
    return {"tradeable": list(dict.fromkeys(tradeable)), "macro": list(dict.fromkeys(macro))}


def download_daily(
    symbols:    list,
    store:      MarketDataStore,
    provider:   YFinanceProvider,
    full:       bool = False,
    start_date: str  = _DEFAULT_START_DATE,
) -> None:
    """下载/增量更新日线数据。"""
    validator = DataValidator()
    success, failed = 0, []

    for sym in symbols:
        try:
            last_date = None if full else store.get_last_date(sym, "1d")
            if last_date is not None:
                start = str(last_date.date())
                if start >= str(pd.Timestamp.today().date()):
                    logger.info("[%s] 日线已是最新，跳过", sym)
                    success += 1
                    continue
            else:
                start = start_date

            logger.info("[%s] 下载日线 from %s ...", sym, start)
            result = provider.fetch_daily([sym], start=start)
            ohlcv  = result.get(sym)

            if ohlcv is None or ohlcv.df.empty:
                logger.warning("[%s] 日线返回空数据", sym)
                failed.append(sym)
                continue

            df = ohlcv.df
            vr = validator.validate(df, symbol=sym, freq="1d")
            if not vr.passed:
                for issue in vr.issues:
                    logger.error("[%s] 数据质量问题: %s", sym, issue)

            store.append(sym, "1d", df)
            logger.info("[%s] 日线保存完成 (%d 行)", sym, len(df))
            success += 1
            time.sleep(0.3)

        except Exception as exc:
            logger.error("[%s] 下载失败: %s", sym, exc)
            failed.append(sym)

    logger.info("日线下载完成: %d 成功, %d 失败 %s", success, len(failed), failed or "")


def download_intraday(
    symbols:  list,
    store:    MarketDataStore,
    provider: YFinanceProvider,
    freqs:    list = None,
) -> None:
    """下载/增量更新日内数据（60m / 30m / 15m）。"""
    freqs     = freqs or _INTRADAY_FREQS
    validator = DataValidator()

    for sym in symbols:
        for freq in freqs:
            try:
                end   = pd.Timestamp.today()
                start = end - pd.Timedelta(days=_INTRADAY_LOOKBACK_DAYS)

                logger.info("[%s] 下载 %s ...", sym, freq)
                result = provider.fetch_intraday([sym], freq=freq, start=str(start.date()))
                ohlcv  = result.get(sym)

                if ohlcv is None or ohlcv.df.empty:
                    logger.warning("[%s] %s 返回空数据", sym, freq)
                    continue

                df = ohlcv.df
                vr = validator.validate(df, symbol=sym, freq=freq)
                if not vr.passed:
                    for issue in vr.issues:
                        logger.error("[%s/%s] 数据质量问题: %s", sym, freq, issue)

                store.append(sym, freq, df)
                logger.info("[%s] %s 保存完成 (%d 行)", sym, freq, len(df))
                time.sleep(0.2)

            except Exception as exc:
                logger.error("[%s/%s] 下载失败: %s", sym, freq, exc)


def main():
    parser = argparse.ArgumentParser(description="PQS 市场数据下载器")
    parser.add_argument("--symbols",       nargs="*", help="指定 symbol 列表")
    parser.add_argument("--full",          action="store_true", help="强制全量重新下载")
    parser.add_argument("--daily-only",    action="store_true", help="仅下载日线")
    parser.add_argument("--intraday-only", action="store_true", help="仅下载日内")
    parser.add_argument("--no-macro",      action="store_true", help="跳过宏观指标下载")
    parser.add_argument("--config-dir",    default="config", help="配置目录")
    args = parser.parse_args()

    cfg      = load_config(Path(args.config_dir))
    store    = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))
    provider = YFinanceProvider()

    sym_groups = get_all_symbols(cfg)

    if args.symbols:
        tradeable = args.symbols
        macro     = []
    else:
        tradeable = sym_groups["tradeable"]
        macro     = [] if args.no_macro else sym_groups["macro"]

    logger.info("准备下载 %d 个可交易标的 + %d 个宏观指标", len(tradeable), len(macro))

    start_date = cfg.backtest.start_date or _DEFAULT_START_DATE
    logger.info("日线起始日期: %s (来自 backtest.yaml)", start_date)

    if not args.intraday_only:
        logger.info("=== 下载日线数据 ===")
        download_daily(tradeable + macro, store, provider, full=args.full, start_date=start_date)

    if not args.daily_only:
        logger.info("=== 下载日内数据 ===")
        download_intraday(tradeable, store, provider)

    logger.info("全部下载完成。")


if __name__ == "__main__":
    main()
