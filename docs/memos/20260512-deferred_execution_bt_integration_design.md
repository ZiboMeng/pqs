# Design Memo — alt-A Phase 2 deferred-execution × BacktestEngine integration

**Date**: 2026-05-12
**Status**: DESIGN (ready for implementation Step 4+)
**Lineage**: `alt-archetype-intraday-reversal-2026-05-12`
**Authority**: PRD `docs/prd/20260512-alt_archetype_intraday_reversal_prd.md` §11 LOCKED 2026-05-12

---

## §1 TL;DR — 人话版

**人话**: 我读 BT 主循环之后发现 Phase 2 的工程量比之前估的 1 周小很多。BacktestEngine 已经支持 "信号 T → 成交 T+1 open" 这种最常见的延迟执行，不需要从底层重写。需要的是**一个 bridge module**：把 IntradayReversalStrategy 内部的 SignalStateMachine 状态机 + DeferredExecutionSchedule 输出，翻译成 BT 能消费的 daily signals_df。

修订后 Phase 2 工程量：**~2 天**（不是 1 周）。

---

## §2 BT 主循环架构（R3 实际读完）

`BacktestEngine.run(signals_df, price_df, open_df, ...)` 主循环：

```
for date in dates:
    1. portfolio_value = mark-to-market at price_row (NaN-safe per M14)
    2. cur_weights = market-weight snapshot
    3. tgt_weights = signals_df.loc[date] (T 日信号)
    4. if i < len(dates) - 1:
         orders = self._generate_orders(cur_weights, tgt_weights, ..., signal_date=date)
         fills = self._sim.simulate_fills(orders, open_prices=opens[T+1], ...)
         shares ← apply fills
    5. record snapshot
```

执行约定：
- signals_df[T] = 目标权重 at T-close
- fills 在 dates[T+1] open 成交（T+1 first-day-open simulation）
- 这正好对应 "deferred-execution kernel 的 execution_delay_bars=1" 在日颗粒度的语义。

**关键 insight**: BT 现有 signals_df + open_df 架构 = 隐式 deferred-execution（T→T+1）。我们不需要重写。

---

## §3 关键 mismatch — daily vs 60m grain

PRD §11 Q3 LOCKED: "T+1 first-60m-bar-close (10:30 ET)"

- 60m grain semantically: signal at T (60m bar close 10:30 ET) → fill at T+1 (next 60m bar close 11:30 ET)
- daily grain approximation: signal at T (daily close) → fill at T+1 day open

**两个 grain 的差异（人话）**:
- 60m grain 真实想要的："今天上午 10:30 看到反弹信号 → 11:30 之前成交"（1 个 60m bar 内）
- daily grain 模拟："T 日收盘后看信号 → T+1 日开盘成交"（1 天延迟，比 60m 慢 ~6 小时）

**Phase 2 决定**: 用 **daily-grain BT 模拟** 作为 alt-A first-fire。理由：
1. PQS 数据基础设施 60m bars 不完整（per PRD §4.1，部分 ETF 2024+ 数据缺）
2. Daily-grain BT 已 production-tested（cycle04-08 + RCMv1 + Cand-2 都用它）
3. 60m grain 是更高精度但工程量大（需要 IntradayBacktestEngine 重写）
4. Cost model 用 2.5bp slip（vs 2bp daily 标准）已经预留 ~25% market-impact 上调，捕捉了 6h-delay 偏差的近似

**未来**（Phase 3 后，如果 alt-A 实战 Sharpe > 0.7）：
- 升级到 60m-grain `IntradayBacktestEngine` 提高精度
- 但 Phase 2 仅做 daily-grain — 不阻塞 first-fire

---

## §4 Integration plan — 3 个新 artifact + 0 BT 内部 breaking change

### Artifact 1: `core/backtest/intraday_reversal_bridge.py` (NEW)

Bridge module that runs `IntradayReversalStrategy.step_day()` across a date range and emits a daily signals_df:

```python
def build_intraday_reversal_signals(
    strategy: IntradayReversalStrategy,
    weekly_reversal_signal_5d: pd.DataFrame,
    vol_21d: pd.DataFrame,
    intraday_volume_60m_zscore: pd.DataFrame,
    early_session_return_pct: pd.DataFrame,
    dates: pd.DatetimeIndex,
) -> pd.DataFrame:
    """For each date T in dates:
      1. Call strategy.step_day(T) → confirmed weights (already deferred-
         execution scheduled internally).
      2. Apply position-aging: if a confirmed signal at T is on its
         holding_period_max_days=5 day, force exit (weight = 0).
      3. Emit signals_df row at T+1 with confirmed weights.

    Returns daily signals_df consumable by BacktestEngine.run().
    """
```

This module is the **only new strategy↔BT plumbing**.

### Artifact 2: `core/backtest/cost_model.py` — intraday slip override (extend existing)

PRD §11 Q4 LOCKED: 2.5bp slip per leg. Current CostModel uses 2bp default. Add `intraday_slip_override_bps` parameter that callers (alt-A bridge) can pass to override slip for the duration of alt-A backtest.

### Artifact 3: `tests/integration/intraday_reversal_e2e_test.py` (NEW)

End-to-end smoke: 5-sym 1-month panel → bridge → BacktestEngine.run() → assert intraday-reversal fills are present + cash-carry NAV correct (armed-not-filled = 0 contribution to portfolio_value).

---

## §5 What does NOT change

**Zero BT internal changes**:
- `_generate_orders` unchanged (M11a sorted iteration preserved)
- `simulate_fills` unchanged (T+1 open execution unchanged)
- Main loop unchanged
- `cycle04-08` paper-vs-replay regression UNAFFECTED (no shared code path)

**Zero deferred_execution.py / signal_state.py changes**:
- Phase 1 kernel already complete + tested
- Bridge module CONSUMES these without modifying them

---

## §6 Day-by-day Phase 2 plan

| Day | Work | Tests | Deliverable |
|---|---|---|---|
| **D1** (today) | Step 1 PRD lock ✅; Step 4 (param-less, simplified scope) — Bridge module skeleton + unit tests | Bridge module: setup → confirm → signals_df row mapping | `intraday_reversal_bridge.py` + 8-10 unit tests |
| **D2** | Step 5-6 — Cost model intraday override + integration smoke | 5-sym 1-month e2e | E2E smoke PASS |
| **D3** | Step 7 — M11a/M11b parity check + cost sensitivity test | cycle04-08 spec re-run unchanged | parity report |
| **D4** | Step 8 — alt-A walking 2018/2019/2021/2023/2025 (Track A acceptance) | Track A 17 gates | Track A verdict |
| **D5** | If Track A PASS → anti-sibling NAV correlation vs RCMv1/Cand-2/Trial9 + closeout | anti-sibling matrix | first-fire authorization OR not |

**Day 1 today's commit scope**: PRD §11 LOCKED + Bridge module skeleton + 8-10 unit tests + 0 BT change.

---

## §7 Cost sensitivity (PRD §11 Q4 derived)

Daily-grain BT with 2.5bp slip per leg + holding 5d:
- Annual turnover ≈ 252 / 5 × 2 (entry+exit) = 100x (vs cycle04-08 monthly = 12x)
- Slip cost annual ≈ 100 × 2.5bp = 250bp = 2.5%/yr
- Vs cycle04-08 ≈ 12 × 2bp = 24bp = 0.24%/yr

**Implication**: alt-A needs Sharpe-after-cost > 0.7 (PRD §9 threshold) which requires gross-of-cost Sharpe > ~1.0. Lehmann (1990) reversal alpha ~30bps/day pre-cost on 1d-5d horizon, ~75bps/week. Post 2.5bp/leg × 2 legs/5d = 1bp/day cost. Net ~29bps/day at 1d. Sharpe of ~30bps/day daily series with sample stddev ~50bps/day = Sharpe ≈ 0.6 daily → annualized ≈ 0.6 × √252 ≈ 9.5 ... that doesn't sound right.

Actually let me redo:
- 30bps/day mean × 250 trading days = 75% annualized return
- 50bps/day std × √252 = 7.9% annualized vol (this is symbol-level; portfolio-level lower due to diversification)
- Sharpe = 75 / 7.9 ≈ 9.5 (annualized)

That's WAY too high. Lehmann 1990 reversal alpha is realistic ~10-20% annualized return at 1d horizon (NOT 75%/yr). My back-of-envelope above conflates symbol-vs-portfolio. Let me re-estimate:

Realistic alt-A pre-cost:
- ~12-18%/yr return (Lehmann post-2010 with cost adjustment)
- ~12%/yr vol (long-only top-5 portfolio at 1-5d holding)
- Sharpe ≈ 1.0-1.5 pre-cost

Post 2.5%/yr cost: ~10-15%/yr return → Sharpe ≈ 0.8-1.2.

**Threshold check**: PRD §9 requires Sharpe-validation-aggregate ≥ 0.70. Plausible if reversal alpha real + persists 2018-2025. Backtest will tell.

**Cost sensitivity 2× test** (PRD §9 hard blocker): if 2.5bp × 2 = 5bp/leg breaks profitability → reject. Reversal alpha + Lehmann literature suggests should survive 2× cost; let's measure.

---

## §8 Forward-looking risks called out at design time

1. **60m bar quality on 53-stock universe**: PRD §4.1 requires ≥95% bar coverage per sym×year. We haven't run the coverage report yet. Will run as part of D1 work.
2. **weekly_reversal_signal_5d factor — train-only sanity**: this factor MUST come from PQS Bucket A factor library (per PRD §2 "exists"). Will verify it's in RESEARCH_FACTORS.
3. **Universe attrition in validation**: 2018/19/21/23/25 — some 53 symbols may not exist in early years. PIT membership rebuild required.

---

## §9 Open directional questions for Phase 3 (NOT today)

- Sealed 2026 panel one-shot — when? (after TD60 forward soak? or upfront?)
- If Track A PASS + forward soak healthy → fleet integration with Trial 9 v2 + cycle #09 nominee (if exists)?

These are Phase 3 decisions; not blocking Phase 2.

---

*End of design memo. Phase 2 D1 work begins below.*
