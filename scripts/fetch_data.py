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
    python scripts/fetch_data.py --allow-pre-close-today  # 紧急覆写（不推荐）

下载范围
--------
  日线  : 2013-01-01 至今（自动增量）
  日内  : 60m / 30m / 15m，回看 700 天（yfinance 60m 免费上限约 730 天）
  宏观  : ^VIX / ^TNX / DX-Y.NYB（仅日线，用于 regime 计算）

收盘前/后纪律 (2026-04-29 fix)
-------------------------------
  - 收盘前运行 (NYSE 16:00 ET / 半天 13:00 ET 之前，加 15 分钟缓冲)
    脚本拒绝写入今日数据；只 fetch 到昨天为止；提示用户收盘后再跑。
  - 误用 --allow-pre-close-today 写了 partial bar：下次收盘后再跑会自动
    检测 fetch_session_log 里的 is_pre_close=true 标记，强制重新拉取
    今日数据覆盖。
  - 半天交易日 (Black Friday / Christmas Eve / July 3 当 7-4 是工作日)
    通过 pandas_market_calendars 自动识别 13:00 ET 收盘；脚本逻辑无需
    特例。
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from core.config.loader import load_config
from core.data.calendar import (
    get_session_close_et,
    is_session_complete,
    is_trading_day,
)
from core.data.fetch_session_log import (
    record_fetch as _record_fetch_event,
    was_fetched_pre_close,
)
from core.data.market_data_store import MarketDataStore
from core.data.yfinance_provider import YFinanceProvider
from core.data.validator import DataValidator
from core.logging_setup import get_logger, setup_logging

setup_logging()
logger = get_logger("fetch_data")

_DEFAULT_START_DATE  = "2007-01-01"
_INTRADAY_FREQS      = ["60m", "30m", "15m"]
# yfinance per-freq lookback limits:
#   60m  → ~730 days
#   30m  → 60 days
#   15m  → 60 days
#   5m   → 60 days
#   1m   → 30 days
# Requesting beyond the limit causes yfinance to return empty data with
# a "requested range must be within the last N days" error. Size each
# request to stay inside the safe window.
_INTRADAY_LOOKBACK_DAYS = {
    "60m": 700,
    "30m": 55,
    "15m": 55,
    "5m":  55,
    "1m":  25,
}
_INTRADAY_LOOKBACK_FALLBACK = 55    # unknown freq → conservative 55d


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


def _today_et() -> pd.Timestamp:
    """ET-naive today (matches store date semantics)."""
    return pd.Timestamp.now(tz="America/New_York").normalize().tz_localize(None)


def _today_session_status():
    """Return (today_et, session_close_utc, session_complete) for today.

    today_et             — pd.Timestamp (tz-naive ET date)
    session_close_utc    — pd.Timestamp tz=UTC, OR None if today is a non-trading day
    session_complete     — bool: True iff NYSE has closed (incl. early-close days)
                           and the post-close buffer (15 min default) elapsed
    """
    today_et = _today_et()
    close_et = get_session_close_et(today_et)
    if close_et is None:
        return today_et, None, True  # non-trading day → "complete" by definition
    session_close_utc = close_et.tz_convert("UTC")
    complete = is_session_complete(today_et)
    return today_et, session_close_utc, complete


def download_daily(
    symbols:    list,
    store:      MarketDataStore,
    provider:   YFinanceProvider,
    full:       bool = False,
    start_date: str  = _DEFAULT_START_DATE,
    allow_pre_close_today: bool = False,
) -> None:
    """下载/增量更新日线数据。

    Pre-close discipline (codex R20 operational note + 2026-04-29 fix):

    1. If today is a trading day AND the session has NOT yet closed
       (with 15 min post-close buffer): we REFUSE to write today's
       partial bar. Fetch up through yesterday only.
    2. If today's bar already exists in the store AND was previously
       written by a pre-close fetch (recorded in fetch_session_log):
       on the next post-close run, force re-fetch to overwrite the
       partial.
    3. If today's bar already exists AND was written post-close (or
       no log entry exists predating today's close): skip.

    Half-day handling: get_session_close_et() returns 13:00 ET on
    NYSE early-close days (Black Friday / Christmas Eve / July 3 when
    July 4 is a regular weekday). The 15-min buffer applies the same
    way; e.g. on Black Friday, session-complete = 13:15 ET.

    The ``allow_pre_close_today`` flag is an emergency override. It
    bypasses guard #1 only and still respects #2 (post-close refresh).
    """
    validator = DataValidator()
    success, failed = 0, []
    today_et, session_close_utc, session_complete = _today_session_status()

    if not session_complete and not allow_pre_close_today:
        logger.warning(
            "Pre-close fetch refused: today=%s, NYSE close=%s ET (with 15min buffer). "
            "Will fetch through %s (yesterday) only. Re-run after close to capture today.",
            today_et.date(),
            (get_session_close_et(today_et) or "(no session)"),
            (today_et - pd.Timedelta(days=1)).date(),
        )
    if not session_complete and allow_pre_close_today:
        logger.warning(
            "Pre-close fetch ALLOWED via override: today=%s. Today's bar will be "
            "marked is_pre_close=true; next post-close run will force-refresh.",
            today_et.date(),
        )

    for sym in symbols:
        try:
            last_date = None if full else store.get_last_date(sym, "1d")

            # Guard 2: post-close refresh of any prior pre-close write
            force_refresh_today = False
            if (
                last_date is not None
                and last_date.normalize() == today_et
                and session_complete
                and was_fetched_pre_close(sym, "1d", today_et)
            ):
                force_refresh_today = True
                logger.info(
                    "[%s] 检测到今日已有 pre-close 记录 → 强制刷新今日日线",
                    sym,
                )

            # Decide start date
            if force_refresh_today:
                # Re-fetch from 2 days ago so today's row is overwritten
                start = str((today_et - pd.Timedelta(days=2)).date())
            elif last_date is not None:
                start = str(last_date.date())
                # Skip-up-to-date check, modulated by guard 1
                if last_date.normalize() >= today_et and not (
                    not session_complete and not allow_pre_close_today
                ):
                    # Already have today's row AND we're allowed to consider
                    # it final → skip
                    logger.info("[%s] 日线已是最新，跳过", sym)
                    success += 1
                    continue
                if last_date.normalize() >= (today_et - pd.Timedelta(days=1)) \
                        and not session_complete and not allow_pre_close_today:
                    # Pre-close: we have yesterday's row already → nothing more to do today
                    logger.info("[%s] 日线已到昨日；今日尚未收盘，跳过", sym)
                    success += 1
                    continue
            else:
                start = start_date

            # Guard 1: cap end at yesterday when pre-close
            end_arg = None
            if not session_complete and not allow_pre_close_today:
                end_arg = str(today_et.date())  # yfinance end is exclusive

            logger.info(
                "[%s] 下载日线 from %s%s ...",
                sym, start,
                "" if end_arg is None else f" to {end_arg} (exclusive; pre-close cap)",
            )
            if end_arg is not None:
                result = provider.fetch_daily([sym], start=start, end=end_arg)
            else:
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

            # Record fetch metadata for any rows in df whose date is
            # today: lets the next run detect pre-close → force refresh.
            if today_et in df.index.normalize():
                _record_fetch_event(
                    sym, "1d", today_et,
                    fetched_at_utc=pd.Timestamp.now(tz="UTC"),
                    session_close_utc=session_close_utc,
                    post_close_buffer_min=15,
                )

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
    full:     bool = False,
    allow_pre_close_today: bool = False,
) -> None:
    """下载/增量更新日内数据（60m / 30m / 15m）。

    Same pre-close discipline as ``download_daily``:
      1. Pre-close: refuse to write today's intraday bars (yfinance
         intraday data prior to close is partial and will be revised);
         end-cap to yesterday.
      2. Post-close + prior pre-close write detected → force refresh
         the most recent ~5 days to overwrite partials.

    Half-day handling matches ``download_daily`` via
    ``get_session_close_et``: bars beyond 13:00 ET on early-close days
    don't exist; vendor returns the truncated session.
    """
    freqs     = freqs or _INTRADAY_FREQS
    validator = DataValidator()
    success, skipped = 0, 0
    today_et, session_close_utc, session_complete = _today_session_status()

    for sym in symbols:
        for freq in freqs:
            try:
                end = pd.Timestamp.today()
                max_lookback_days = _INTRADAY_LOOKBACK_DAYS.get(
                    freq, _INTRADAY_LOOKBACK_FALLBACK,
                )
                earliest_start = end - pd.Timedelta(days=max_lookback_days)

                # Force-refresh detection: if last fetched intraday for
                # today was pre-close, force refresh
                force_refresh = (
                    session_complete
                    and was_fetched_pre_close(sym, freq, today_et)
                )

                if force_refresh:
                    start = today_et - pd.Timedelta(days=5)
                    logger.info(
                        "[%s/%s] 检测到今日 pre-close 记录 → 强制刷新近 5 天",
                        sym, freq,
                    )
                elif not full:
                    last_date = store.get_last_date(sym, freq)
                    if last_date is not None:
                        days_stale = (end - last_date).days
                        if days_stale <= 1 and (
                            session_complete or allow_pre_close_today
                        ):
                            # Already up-to-date AND session has closed (or override).
                            skipped += 1
                            continue
                        if days_stale <= 1 and not session_complete \
                                and not allow_pre_close_today:
                            # Pre-close + already have yesterday → nothing to fetch yet
                            skipped += 1
                            continue
                        start = last_date - pd.Timedelta(days=5)
                    else:
                        start = earliest_start
                else:
                    start = earliest_start

                if start < earliest_start:
                    logger.debug(
                        "[%s/%s] start %s predates yfinance %dd window; "
                        "clamping to %s",
                        sym, freq, start.date(), max_lookback_days,
                        earliest_start.date(),
                    )
                    start = earliest_start

                # Pre-close cap end at yesterday
                end_arg = None
                if not session_complete and not allow_pre_close_today:
                    end_arg = str(today_et.date())

                logger.info(
                    "[%s] 下载 %s (from %s%s)...",
                    sym, freq, start.date(),
                    "" if end_arg is None else f", end={end_arg} excl. pre-close cap",
                )
                if end_arg is not None:
                    result = provider.fetch_intraday(
                        [sym], freq=freq, start=str(start.date()), end=end_arg,
                    )
                else:
                    result = provider.fetch_intraday(
                        [sym], freq=freq, start=str(start.date()),
                    )
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
                success += 1
                logger.info("[%s] %s 保存完成 (%d 行)", sym, freq, len(df))

                # Record event if any bar landed in today's date
                normalized = pd.DatetimeIndex(df.index).normalize()
                if today_et in normalized:
                    _record_fetch_event(
                        sym, freq, today_et,
                        fetched_at_utc=pd.Timestamp.now(tz="UTC"),
                        session_close_utc=session_close_utc,
                        post_close_buffer_min=15,
                    )

                time.sleep(0.2)

            except Exception as exc:
                logger.error("[%s/%s] 下载失败: %s", sym, freq, exc)

    logger.info("日内下载完成: %d 更新, %d 跳过 (已是最新)", success, skipped)


def main():
    parser = argparse.ArgumentParser(description="PQS 市场数据下载器")
    parser.add_argument("--symbols",       nargs="*", help="指定 symbol 列表")
    parser.add_argument("--full",          action="store_true", help="强制全量重新下载")
    parser.add_argument("--daily-only",    action="store_true", help="仅下载日线")
    parser.add_argument("--intraday-only", action="store_true", help="仅下载日内")
    parser.add_argument("--no-macro",      action="store_true", help="跳过宏观指标下载")
    parser.add_argument("--config-dir",    default="config", help="配置目录")
    parser.add_argument(
        "--allow-pre-close-today", action="store_true",
        help="紧急覆写: 允许在 NYSE 未收盘时写入今日数据 (不推荐). 写入会被 "
             "fetch_session_log 标记为 is_pre_close, 下次收盘后运行会自动 "
             "强制重拉. 默认行为是收盘前拒绝写入今日数据.",
    )
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
        download_daily(
            tradeable + macro, store, provider,
            full=args.full, start_date=start_date,
            allow_pre_close_today=args.allow_pre_close_today,
        )

    if not args.daily_only:
        logger.info("=== 下载日内数据 ===")
        download_intraday(
            tradeable, store, provider,
            full=args.full,
            allow_pre_close_today=args.allow_pre_close_today,
        )

    logger.info("全部下载完成。")


if __name__ == "__main__":
    main()
