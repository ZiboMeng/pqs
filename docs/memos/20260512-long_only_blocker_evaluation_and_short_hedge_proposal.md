# Long-only Constraint — Profitability Blocker Evaluation + Short Hedge Proposal

**Date**: 2026-05-12
**Status**: DRAFT proposal — NOT authorization to violate long-only invariant
**Trigger**: User question 2026-05-12: "如果 long only 是 profitable 的障碍 写好 memo 之后看怎么加入 short hedge 但要控制风险 防止 short squeeze 之类的"
**Authority**: This memo evaluates the question + proposes a structured framework. Implementation requires **separate explicit-go** because it changes a core CLAUDE.md invariant.

---

## §1 TL;DR — 大白话版

**问题**: long-only 是不是 PQS 跑不出 alpha 的根本障碍？

**回答 (resident-quant 视角)**: **部分是**。

- ✅ Long-only **绝对限制了 Sharpe 上限** — 你拿不到 down-side alpha (做空赚钱的部分)。AQR/Fama-French 文献长期显示 long-short factor portfolio Sharpe 比 long-only 高 0.3-0.6。
- ⚠️ 但**不是唯一障碍** — cycle04-08 sibling-by-construction 也来自 78-股 universe + monthly cap_aware top-N 这两个 binding，short 不直接解决这个。
- ❌ **个人 $10K-$100K scale 加 short 是 risk 灾难** — short squeeze / margin call / broker recall 在小账户上等同于一次性爆仓。

**Recommendation**:
- 不要直接放开 long-only invariant
- 但可以加 **"defensive overlay" 通过 inverse ETF**（SH, PSQ）作为受控对冲, 上限 20% 仓位
- 这不算 short（持有 inverse ETF 是 long position）, 但能拿一部分 down-side alpha
- Risk control: VIX-gated, no leveraged inverse, position cap 20%, time-cap 30 days
- 期望 Sharpe 提升: 0.1-0.2 (modest)，主要是 BEAR 防御和 max DD 改善
- 期望成本: inverse ETF tracking error ~30-50bp/yr drag

**核心论点**:
- "完全放开 long-only" 风险 >> 收益（个人账户 scale）
- "受控 defensive overlay via inverse ETF" 是 risk-controlled 中间路径
- 真正的 alpha 突破更可能来自 **universe expansion** + **strategy-type diversification**, 不是 short side

---

## §2 evidence: long-only 是不是 binding?

### 2.1 Cycle04-09 + alt-A 证据

| 周期 / 候选 | Long-only? | Track A 通过？| 关键 fail mode |
|---|---|---|---|
| cycle04 | ✅ long-only | 0 nominee | sibling-by-NAV |
| cycle05 | ✅ | 0 nominee | sibling-by-NAV |
| cycle06 | ✅ | 0 nominee | sibling-by-NAV |
| cycle07a | ✅ | Trial 3 PASS | RED anti-sibling NAV |
| cycle08 | ✅ | 0 nominee | sibling-by-NAV |
| cycle #09b (just smoke PASS) | ✅ | TBD | TBD |
| alt-A intraday | ✅ | FAIL vs SPY aggregate | 84% cash drag in BULL years |
| Trial 9 v2 (forward) | ✅ | candidate | low beta 0.07 |

**Pattern**: 所有 fail mode 都跟 long-only 有关吗？
- **NO** — cycle04-08 sibling 跟 long-short 都会 sibling (同因子, 同 universe, 同 construction → 同 alpha 来源)
- **YES partially** — alt-A 84% cash drag 在 BULL 年是 long-only invariant 直接结果（不能 short 拖累带的"被动 cash"）

### 2.2 学术 + 业界文献证据

| 来源 | 结论 |
|---|---|
| Fama-French (1993, 2015) | long-short HML/SMB factor Sharpe ~0.6; long-only 等价 ~0.3 |
| AQR Style Premia (2014+) | long-short Style 多因子 Sharpe 1.2; long-only equivalent ~0.6 |
| Asness et al "Value & Momentum Everywhere" | 全 asset class long-short Sharpe ~1.0; long-only Sharpe ~0.4 |
| BlackRock factor ETFs | long-only smart-beta Sharpe ~0.5-0.7 (DGRO/MTUM); long-short equivalent ~0.8-1.1 |
| Quantopian / Numerai community | universal observation: long-short 比 long-only Sharpe +0.3-0.6 |

**总结**: long-short 的 Sharpe 提升是 robust 学术事实，幅度 ~0.3-0.6 annualized Sharpe.

### 2.3 但 long-only 不是唯一 binding

cycle04-08 sibling-by-construction 的 root cause:
1. **78-股 universe**：long-only top-N 在固定 universe 上必然产生 high-correlation 选择
2. **Monthly cap_aware top-N construction**：同 universe + 同 rebalance cadence → 长得像的选择
3. **162-factor library 互相 correlated**：159 个 |r| ≥ 0.7 高相关对 (Z1 cluster report)

**这 3 个 binding 加 short side 也会重复出现** — long bottom decile, short top decile 还是同一个 factor universe driven, 结果仍 sibling.

**真正 de-sibling 的 axis 是**:
- 不同 universe (78 → 200+ stocks, OR + cross-asset)
- 不同 time scale (daily → intraday)
- 不同 strategy type (passive top-N → event-driven / reversal / volatility / pairs)

Short side 提升 Sharpe 但不解决 sibling.

---

## §3 个人账户加 short 的真实 risk

### 3.1 Short squeeze 风险

**例子**: GameStop 2021-01: short interest 140% → 单周涨 700% → short 全爆仓

**机制**: 当被做空股票被大量买入, 价格上涨 → short 卖方需要 cover → 买入推高价格 → death spiral.

**$10K 个人账户**:
- short 1 股 GME ($30 → $300) = $270 loss = 2.7% 账户
- 但 margin requirement: short 通常需要 50%-100% margin posted
- 如果价格涨 10x → margin call → 强制 cover at 顶 → 100% loss + 可能负债

**Pre-2024 数据**: 平均年化 short squeeze 事件 ~5-10 起 (S&P 500 内). 个人小账户碰到的概率不低.

### 3.2 Broker recall 风险

短借股票时 broker 可以**随时召回**:
- 通常召回原因: 股东大会 / dividend / institutional buy-back / hard-to-borrow 等
- 短期 retail brokers (IBKR, Fidelity) 召回率 ~5-15%/月 (取决于 stock)
- 召回时被迫在不利价格 cover

### 3.3 Margin call cascade

$10K 账户 short 25%:
- 初始: $10K cash + $2.5K short (margin $1.25K) → equity $10K
- Short 涨 50%: short value $3.75K, cash unchanged. Margin requirement re-priced.
- 涨 100%: short value $5K → margin call → broker liquidates at worst price
- **个人小账户的 margin 不是 graceful degradation**, 是 binary 爆仓

### 3.4 Tax + operational cost

- Short dividend payments owed to lender (substitute payments — fully taxed)
- Hard-to-borrow fees: 10-200 bp/yr depending on stock
- Wash-sale rule限制 short → cover → re-short
- IRS reporting complexity

### 3.5 心理 + 操作 risk

- Long position max loss = 100% capital
- Short position max loss = **unlimited** (in theory)
- 操作员失误成本 asymmetric — short side 一次错误等于一年盈利

---

## §4 我推荐的 risk-controlled 中间路径

### 4.1 不放开 long-only invariant — 用 inverse ETF overlay

**Inverse ETF (e.g. SH = -1× SPY, PSQ = -1× QQQ, RWM = -1× Russell 2000)**:
- 持有 inverse ETF 是 **long position** (you own the ETF, ETF manager handles the short)
- 不触发 short squeeze on your account
- No margin requirement
- No broker recall risk
- No unlimited loss (max loss = 100% of inverse ETF allocation)

**Caveats**:
- Daily-rebalance inverse ETF has **path-dependence decay** (compound erosion 1-3%/yr)
- Long-hold inverse ETF for months = guaranteed loss vs short SPY directly
- **Only useful for short-horizon defensive hedge (1-30 days), not core position**

### 4.2 Proposal: "Defensive Overlay Layer" with strict controls

**Architecture** (separate from core long strategy):

```
Core PQS long-only strategy (cycle04+, RCMv1, future ML)
   ↓ produces target portfolio with long positions
Defensive Overlay Layer (NEW)
   ↓ adds inverse-ETF allocation based on regime signal
Final portfolio = long_core × (1 - overlay_weight) + inverse_etf × overlay_weight
```

**Rules**:
- `overlay_weight` ∈ [0, 0.20] (max 20% of portfolio in inverse ETF)
- `overlay_weight > 0` only when VIX > 25 (regime gate; not always-on)
- Single inverse ETF only (SH); no leveraged (SQQQ blacklisted per CLAUDE.md)
- Max hold period: 30 trading days per allocation (force-exit timer)
- Auto-exit when VIX < 20 (regime release)
- Pre-2026 backtest must demonstrate Sharpe improvement net of decay

**Risk caps**:
- Position cap 20% (prevents over-hedging)
- Time cap 30 days (prevents long-hold decay accumulation)
- VIX gating (not always-on, ~10-20% of time only)
- Decay budget: max 50bp/yr drag if regime gating is wrong

### 4.3 Expected outcome (back-of-envelope)

**Without overlay (long-only)**:
- 2008-equivalent year: max DD -34% (SPY drawdown)
- 2018 BEAR: alt-A +3.17% vs SPY (defensive value real but limited)
- Sharpe baseline ~1.08 (Trial 3 reference)

**With overlay (20% cap, VIX-gated)**:
- 2008-equivalent: max DD -25% to -28% (5-9 pp improvement; PRD §1.4 target)
- BULL years: -50bp/yr drag from inverse ETF holding cost
- BEAR years: +100-300bp/yr defensive alpha
- Net annualized Sharpe lift: estimated +0.1-0.2

**Long-only purist alternative** (NO overlay):
- Live with -34% in 2008-equivalent stress (Sharpe ~1.0-1.2 ceiling)
- Rely on cash-anchor 30% + bonds/commodities in cross-asset universe

**Trade-off**: overlay buys 5-9 pp max DD reduction at 50bp/yr BULL cost.

### 4.4 Implementation phasing

If user explicit-go on overlay:

**Phase A (1 week eng)**: Standalone inverse ETF overlay backtest module
- `core/strategies/defensive_overlay.py`
- Take core_long_nav + VIX series → output overlay-adjusted NAV
- Backtest 2009-2025 with VIX gating + 30-day time cap
- Compare overlay-adjusted Sharpe / max DD vs core_long_only

**Phase B (1 week eng)**: Wire into BacktestEngine
- New `BacktestEngine.run(..., overlay_strategy=...)` kwarg
- Default None (cycle04-08 bit-for-bit preserved)
- Track A acceptance still evaluates final overlay-adjusted NAV

**Phase C (post Phase 1 ML)**: Test overlay with ML phase candidates
- Does overlay help ML-phase Sharpe pass Track A? Verdict drives next.

**Phase D (gated on Phase A-C success)**: Optional limited real-short integration
- Only after 6+ months overlay paper-trade healthy
- Then PRD a "directly-short small-portion" proposal with separate risk framework
- This is SEPARATE PRD and requires major user explicit-go

---

## §5 What about FULL long-short PQS?

User asked "how to add short hedge with risk controls". Above is the
**conservative middle path** (inverse ETF overlay). 

**Full long-short (Phase D+)** is in principle possible but requires:
- Capital scale upgrade (~$50-100K min to absorb margin requirements)
- New broker setup with margin account
- Risk monitoring infrastructure (real-time margin / loan availability)
- Operational protocols (recall handling, dividend substitute tax)
- Multi-page risk PRD with regulatory considerations

**Not recommended at $10K-$100K personal scale**. Recommend wait until $100K+
account size before opening this discussion.

---

## §6 What if PQS doesn't need short side?

Alternative paths that don't need long-only relaxation:

### 6.1 Universe expansion
- 78 stocks → 200-500 stocks (Russell 1000 universe)
- More universe = more selection diversity = potentially less sibling-by-construction
- Engineering: 2-3 weeks data pipeline + factor recomputation

### 6.2 Cross-asset expansion
- Add bonds (TLT/IEF/SHY), commodities (GLD), real estate (VNQ), international (EFA/EEM)
- Asset class diversification provides defensive alpha **without short side**
- Engineering: 1-2 weeks (mostly data + universe.yaml extension)

### 6.3 Multi-strategy fleet
- Cycle04-08 sibling because all are same-construction strategies
- Run 3-5 structurally different strategies in parallel
  - Daily-monthly cap_aware (current)
  - Intraday reversal (alt-A pivot, deferred)
  - Event-driven (FOMC/CPI calendar; new alt PRD)
  - Volatility-targeting overlay
  - Pairs trading (long both legs but spread-driven)

### 6.4 ML mining (the deferred ML PRD)
- Non-linear factor combination may find alpha linear couldn't
- Less universe/construction binding
- See `docs/prd/20260512-ml_mining_pipeline_prd.md`

---

## §7 Recommendation Tree (decision-flow)

```
Is alpha gap from long-only specifically?
  ├── Evidence YES (defensive BEAR alpha, max DD reduction)
  │   ├── Recommendation: §4 inverse ETF overlay (1-2 weeks eng)
  │   └── If overlay improves Sharpe + max DD by ≥ 10% → keep it
  │       Else revert to long-only
  │
  └── Evidence MIXED (alpha gap also from universe/construction)
      ├── Recommendation: parallel
      │   ├── §6.1 universe expansion (3 weeks)
      │   ├── §6.2 cross-asset (1-2 weeks)
      │   └── §4 overlay (1-2 weeks)
      └── Compare incremental Sharpe contribution to choose which 
          to push forward
```

**Resident-quant top recommendation**:

1. **First**: complete cycle #09b verdict + Phase 1 ML to see if existing
   approach can produce alpha at scale (need empirical evidence before
   adding more lever)

2. **Second**: §6.2 cross-asset expansion (highest expected ROI + lowest
   risk) — diversification benefit without short side complications

3. **Third (if #1+#2 not enough)**: §4 inverse ETF overlay (moderate ROI,
   moderate risk)

4. **Defer**: direct short positions (high risk, $10K account inappropriate)

---

## §8 Pre-commitment to risk controls if overlay implemented

If user explicit-go on inverse ETF overlay implementation, mandatory:

1. **Position cap**: `overlay_weight ∈ [0, 0.20]` hard
2. **VIX gate**: `overlay_weight > 0` requires `VIX > 25`
3. **Time cap**: max 30 trading days per overlay allocation
4. **Auto-exit**: `VIX < 20` triggers immediate overlay → 0
5. **Single inverse ETF**: only SH (no SQQQ, no leveraged inverse)
6. **Pre-fire Track A**: 2009-2025 backtest must demonstrate Sharpe net improvement
7. **Forward soak 60 days**: paper-trade overlay live before any real-money push
8. **CLAUDE.md edit**: requires explicit update to invariant section (add "inverse ETF overlay ≤ 20%, VIX-gated, time-capped" carve-out)
9. **Reversibility**: any 3 consecutive months overlay underperforms long-only baseline → auto-disable

---

## §9 Open Questions

1. **Is user comfortable with inverse-ETF overlay as middle path** (not full short)?
2. **VIX threshold 25 / 20 — calibrate?** Pre-2020: VIX > 25 ~10-15% of time. Tighter (e.g. > 30) reduces overlay activation; looser (e.g. > 22) increases drag.
3. **Single SH vs basket (SH + PSQ + RWM)?** Single is simpler but less diversified inverse exposure. Basket more nuanced but more decay sources.
4. **When to first overlay backtest?**
   - (a) After cycle #09b verdict (recommended — see if long-only path can still produce alpha)
   - (b) Now in parallel with cycle #09b
   - (c) Defer until ML Phase 1 verdict (need empirical "long-only is binding" evidence first)

5. **CLAUDE.md invariant**: add "inverse ETF overlay carve-out"? My recommendation:
   - First demonstrate value in 6+ month paper trade
   - Then propose invariant relaxation with documented rules
   - NOT change invariant prophylactically

---

## §10 Connection to existing PQS work

- **cycle04-08 sibling root cause**: NOT primarily long-only — overlay won't fix sibling-by-construction
- **alt-A 2018 +3% vs SPY**: overlay could push this to +5-8% in BEAR
- **alt-A 84% cash drag in BULL**: overlay won't fix (overlay is also "non-position") but is **different drag mechanism** (you pay inverse ETF decay instead of zero-return cash)
- **Trial 9 v2 low-beta defensive**: overlay synergizes here — Trial 9 is naturally defensive + overlay amplifies the down-protection
- **Phase 1 ML**: overlay can wrap ML output similarly to wrapping linear composite output. Architecturally compatible.

---

## §11 Bottom line (resident-quant view)

按 [[feedback_quant_operator_role.md]] 不当 yes-man：

**Long-only is a constraint** that reduces Sharpe ceiling by 0.3-0.6 (literature),
但是:
- **不是 PQS 当前 cycle04-08 / alt-A 失败的主因** — universe + construction 才是
- **个人 $10K-$100K scale 直接放开 short = 高风险低 expected value**
- **Inverse ETF overlay 是合理中间路径** — modest 收益, 受控风险, 不破 invariant 精神
- **真正 alpha 突破更可能来自 universe / strategy-type 多样化** (§6) + ML 非线性 mapping

**Recommendation**:
- 先看 cycle #09b + Phase 1 ML 结果
- 如果 alpha 还差 → §6.2 cross-asset 扩展（最低风险路径）
- 如果还差 → §4 inverse ETF overlay (1-2 周 eng, 受控 risk)
- 真正 short 至少等到 $100K+ 账户 scale 再讨论

**NOT recommended right now**: 直接放开 long-only invariant for short trades.

---

*End of memo. Awaiting user directional decision per §9.*
