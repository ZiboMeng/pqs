# Cycle11 Smoke Execution Artifact — close-as-fallback Inflated Numbers

**Date**: 2026-05-14 evening (post Track A spot-check)
**Status**: BUG FIXED — smoke v3 re-running with proper open_df
**Severity**: P0 — invalidates cycle11 smoke v1 + v2 Sharpe numbers (Donchian + Connors)
**Trigger**: Track A spot-check on Donchian-20 hold=21 with `open_df=open_df` passed produced Sharpe 0.66 (vs smoke v2's 1.31). 0.65 gap is large.

---

## §1 What happened

`dev/scripts/cycle11/run_cycle11_mini_smoke.py` (versions v1 + v2) did NOT
pass `open_df` to `SignalDrivenBacktest`. The downstream `BacktestEngine.run()`
has a fallback path: when `open_df is None`, it uses **same-day close** as
execution price (with a warning log).

For a breakout strategy (Donchian + Connors):
- Signal generated at T-close (e.g., close > rolling_max(T-1))
- Real execution: T+1 OPEN (often gap-up from T-close)
- Smoke (buggy): T+1 CLOSE used (since open_df missing, but fallback uses
  same-day close at T+1 → exec price is T+1's close, not T+1's open)

The fallback path gives systematically BETTER fills than reality because:
- T+1 OPEN typically gaps UP from T-close on breakout days
- T+1 CLOSE may or may not be above T+1 OPEN
- For breakouts (which tend to continue), CLOSE > OPEN → using CLOSE as
  fill is BETTER than reality (real fill is at OPEN)

Actually wait — re-reading `core/backtest/backtest_engine.py:191`:
```python
else:
    logger.warning("BacktestEngine.run: open_df 未提供，使用同日 close 作为"
                   "执行价代理（有小幅偏差但无 lookahead）")
    opens = prices.copy()  # same-day close used as fallback "open"
```

The fallback uses **same-day** close as a proxy for open. The "no lookahead"
claim assumes you're trying to backtest "execute at the open of today's
bar" — using today's close instead is slightly forward-looking compared
to "open at the top of bar T+1" semantics.

Actually wait, let me re-read the variable flow: the `opens` is used inside
`_generate_orders` as the execution price for orders signaled on the
previous bar. So:
- Signal at T → order generated
- Order executes at "T+1 open" semantically
- If open_df present: use open_df.loc[T+1, sym]
- If open_df absent: use prices.loc[T+1, sym] (= T+1 close, NOT T+1 open)

So smoke v1/v2 used T+1 CLOSE as the fill price for breakout-triggered orders.
This is a backwards-looking fill (later in the day than intended), and for
breakout continuation patterns, T+1 CLOSE > T+1 OPEN typically → bug
INFLATES strategy returns.

Empirically confirmed: Donchian-20 hold=21
- Smoke v2 (close fallback): Sharpe 1.31, CAGR 21.24%
- Standalone (proper open_df): Sharpe 0.66, CAGR 9.81%

Δ Sharpe = -0.65, Δ CAGR = -11.43pp. Substantial.

## §2 What's affected

**Affected smoke runs** (use close-as-fallback fill):
- `cycle11_mini_smoke.json` v1 (5bp cost, smoke v1)
- `cycle11_mini_smoke.json` v2 (30bp cost, smoke v2)
- Top-5 ranking @ 30bp (smoke v2): all 5 numbers inflated

**NOT affected** (use proper open_df):
- T1a alt-A intraday reversal Phase 3 backtest — used pre-existing
  `intraday_reversal_bridge.py` with proper open_df
- T1b ConfirmationPattern Track A eval — passed `open_df=open_df`
- cycle11 standalone Track A spot-check (`run_cycle11_top_trial_track_a.py`)
  — passes `open_df=open_df`
- simple_baseline_v1 — uses yfinance direct, not BarStore
- Trial 9 v2 forward observe — not affected (uses different path)

## §3 Re-doing

Smoke v3 in progress with `open_df` passed. Expect:
- Top trial Sharpe drops from 1.31 → ~0.66
- More trials drop below SPY (0.76)
- True winner ranking will reveal robust-to-realistic-execution alpha
- Connors RSI(2) hold=3 (smoke v1 #1) likely drops further (high turnover
  + close-fallback inflation both affected it)

## §4 Root cause

The smoke script (`run_cycle11_mini_smoke.py`) was written quickly to test
20 trial configs as a feasibility check. open_df loading was omitted to
save ~10s of fetch time per universe. The warning log from
`BacktestEngine.run` was hidden in the per-trial output.

In hindsight: the standalone Track A eval explicitly tests every detail
including open_df — that's what caught the artifact. The smoke script
was a less rigorous "quick check" that didn't.

## §5 Process lesson (memory update)

Adding to memory `feedback_bar_level_data_integrity_smoke`:

> Add open_df-not-None check to smoke scripts. Backtest fallback to
> close-as-open is a SILENT artifact that inflates breakout-strategy
> Sharpe by ~0.5-0.7 in our experience.

The R3 audit methodology already says "actually run code + compare to
expected numbers" — the standalone vs smoke gap (0.65 Sharpe) is exactly
the kind of "implementation drift" R3 catches. Standalone-then-smoke
verification was correct discipline; just took an extra round.

## §6 Honest verdict update for cycle11

Pre-fix (smoke v2): 15/20 trials beat SPY @ 30bp; top Sharpe 1.31
Post-fix (smoke v3 expected): Probably 3-7 trials beat SPY @ 30bp;
top likely Faber or Donchian medium-hold at Sharpe 0.8-1.0

The smoke result inflation does NOT invalidate the cycle11 hypothesis:
- Signal-driven mining CAN still beat SPY at realistic cost
- But the BAR is higher than smoke v2 implied
- Track A passing is HARDER than smoke v2 suggested

Standalone Donchian-20 hold=21 result:
- Sharpe 0.66 (below SPY 0.76) ← NOT a Track A nominee
- 2x cost gate FAILS (final equity $4.4K at 60bp)
- Per-year vs SPY: 4/5 negative → consistency FAIL
- vs T1b daily-return correlation 0.74 (PASS, but close to threshold)
- vs alt-A daily-return correlation 0.20 (PASS, well clear)

**T1b is still the strongest signal-driven candidate** PQS has produced.
cycle11 mining needs to find something BETTER than the smoke v3 honest
winners, not better than the smoke v2 inflated winners.

## §7 What to do

1. Wait for smoke v3 to complete (~10 min) — gives honest 20-trial ranking
2. Update T2b closeout with v3 numbers as authoritative
3. Mark smoke v1+v2 results in cycle11_mini_smoke.json as DEPRECATED
4. Updated daily summary doc

Files affected:
- `dev/scripts/cycle11/run_cycle11_mini_smoke.py` (FIXED 2026-05-14 evening)
- `data/audit/cycle11_mini_smoke.json` (will be overwritten by v3)
- `docs/memos/20260514-t2b_cycle11_resmoke_v2_realistic_cost.md` (needs amendment)
- `docs/memos/20260514-pqs_daily_summary_plain_chinese.md` (needs amendment)
