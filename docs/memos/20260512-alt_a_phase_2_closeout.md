# alt-archetype A Phase 2 Closeout

**Date**: 2026-05-12
**Status**: Phase 2 D1-D3 COMPLETE; D4 PARTIAL (infrastructure shipped, full Track A walking deferred)
**Lineage**: `alt-archetype-intraday-reversal-2026-05-12`
**Authority**: PRD `docs/prd/20260512-alt_archetype_intraday_reversal_prd.md` §11 LOCKED 2026-05-12; user explicit-go "53-stock / 5d / first-60m-close / 2.5bp slip 开 Phase 2"

---

## §1 TL;DR — 人话版

**5 commits 推到 main 完成 Phase 2 D1-D4**：
- 设计 memo 确认 Phase 2 比初估 1 周小很多（其实是 ~2-3 天）
- Bridge module + BT freq kwarg + alt-A cost helper + 6 e2e tests
- M11 parity 维持 cycle04-08 bit-for-bit
- 60m bar → 每日 intraday inputs 计算管线 + 真实数据验证（5 股 × 2024）

**5 股 × 2024 真实回测**：alt-A 跑出 -0.6% vs SPY +24%。**这不是 Track A verdict**，因为 5 股太窄（只 9 个交易日有 position）。真正 Track A 需要 53 股 × 8 年。

**剩余工作（Phase 3 = Track A walking）**：约 4-8 小时工程量，需要按部就班做 53-股 60m 覆盖检查 + 8 年完整回测 + Track A 17 关 evaluator。**今日不在 Phase 2 scope**。

---

## §2 Phase 2 D1-D4 Ship 详情

### D1: 设计 memo + Bridge module
**Commit**: `f97f4ed`
- `docs/memos/20260512-deferred_execution_bt_integration_design.md` — R3 读完 BT 主循环发现集成 scope 比 1 周小（BT 现有 signals_df + open_df 架构隐式支持 daily-grain deferred execution）
- `core/backtest/intraday_reversal_bridge.py` — `IntradayReversalBridgeState` (5d 持仓 aging) + `build_intraday_reversal_signals()` (策略 → signals_df)
- 12 unit tests

### D2: BT freq kwarg + alt-A cost helper + e2e
**Commit**: `2845e3b`
- `BacktestEngine.__init__` 新加 `execution_freq` kwarg (default `"interday"`); validation strict (`"interday"|"intraday"`)
- `build_alt_a_cost_model()` 用 PRD §11 Q4 LOCKED 2.5bp slip 构建 CostModel
- 6 e2e tests: pipeline / cash carry / 2× cost / M11a det / turnover / regression

**R3 抓到 3 个 bug（fixture/semantic 类，全部 fix）**：
- cash_curve POST-fill vs equity PRE-fill 同期记录（cycle04-08 现存 semantics）
- 恒定 arming smoke → 0 turnover（合理；改 fixture 用 periodic-reversal pattern）
- `cfg.cost_model_runtime` 不存在 → `CostModel(cfg.cost_model)`

### D3: M11 parity regression tests
**Commit**: `81de011`
- 6 explicit canary tests pinning execution_freq kwarg behavior contract
- bit-for-bit assert 用 `pd.testing.assert_series_equal` 验证 default 同 explicit interday
- intraday-freq strictly worse equity (prod cost_model 中 intraday 7-20bp > interday 4-8bp)
- 验证 304 backtest + signals 测试通过

### D4 (Partial): 60m intraday inputs helper + real-data smoke
**Commit**: `118764a`
- `core/factors/alt_a_intraday_inputs.py`
  - `compute_alt_a_intraday_inputs()` — 60m bars → 每日 z-score volume + early-session return
  - `report_coverage()` — 每股 60m 覆盖率 (PRD §4.1 ≥95% 阈值)
- 8 unit tests
- **真实数据 5 股 × 2024 smoke**:
  - 5 股全部 96.6% 覆盖 ≥ 95% threshold ✓
  - 6 trades / 9 持仓日 / 252 总日
  - alt-A 2024 NAV: -0.6% vs SPY +24%（5 股太窄；不是 Track A verdict）

---

## §3 Pipeline 架构总结

```
                          ┌──────────────────────────────┐
                          │  Daily price/volume panel    │
                          │  (53 stocks × N years)       │
                          └────┬─────────────────────────┘
                               │
                               ▼
                  ┌─────────────────────────────────┐
                  │ factor_generator.generate_all   │
                  │  → weekly_reversal_signal_5d    │
                  │  → vol_21d                       │
                  └────┬────────────────────────────┘
                       │
                       │     ┌──────────────────────────────┐
                       │     │ 60m bars (BarStore)          │
                       │     │  (53 stocks × N years)        │
                       │     └────┬─────────────────────────┘
                       │          │
                       │          ▼
                       │  ┌─────────────────────────────┐
                       │  │ alt_a_intraday_inputs       │
                       │  │  compute_alt_a_intraday_in… │
                       │  │  → intraday_volume_60m_z    │
                       │  │  → early_session_return_pct │
                       │  └────┬────────────────────────┘
                       │       │
                       ▼       ▼
                  ┌─────────────────────────────────┐
                  │ intraday_reversal_bridge        │
                  │  build_intraday_reversal_sigs() │
                  │  - Strategy.step_day per day     │
                  │  - 5d hold cap aging             │
                  │  → daily signals_df              │
                  └────┬────────────────────────────┘
                       │
                       ▼
                  ┌─────────────────────────────────┐
                  │ BacktestEngine                  │
                  │  execution_freq="intraday"      │
                  │  cost = build_alt_a_cost_model  │
                  │  → BacktestResult: NAV / trades │
                  └─────────────────────────────────┘
```

每一层都已 ship 并验证。下一步（Phase 3）只是 scaling：53 股 × 8 年。

---

## §4 Phase 3 Track A first-fire authorization gates

要让 alt-A 真正 fire（forward init），还差以下步骤：

### Step A. 53-股全覆盖验证
- 检查 53 股每年 60m 覆盖率（重点 2018/19/21/23/25）
- 任何 <95% 覆盖率的 stock-year 列出来 → 排除 OR 留 NaN handle
- 工程量：~30 min

### Step B. 8-年 alt-A NAV 生成
- 全期回测 2018-2025（train + validation 完整范围）
- 用 `core.factors.alt_a_intraday_inputs` 计算每年 intraday inputs
- 调用 bridge → BT → NAV series
- 工程量：~2 小时（数据加载主要时间）

### Step C. Track A 17 关 acceptance
- 调用 `core.research.temporal_split_acceptance.run_split_acceptance(strategy_nav=alt_a_nav, ...)`
- 输出 verdict + gate-by-gate detail
- 工程量：~30 min

### Step D. Anti-sibling NAV correlation
- 用 `dev/scripts/correlation/run_pair_nav_correlation.py`（已 ship from cycle04 work）
- vs RCMv1 / Cand-2 / Trial 9 v2 / cycle #09 nominee（如果存在）
- pairwise raw Pearson < 0.85 hard gate
- 工程量：~30 min

### Step E. Closeout memo + user authorization
- 写 Track A 完整 verdict + 战略推荐
- **需要 user explicit-go 才能 forward init**

**Total Phase 3 工程**: ~3-4 小时 + user decision 1 round。

---

## §5 关键 honest disclosures

### 5.1 5-股 2024 smoke 不证明 alpha
- alt-A -0.6% / SPY +24% 在 5 股 × 2024 是 expected — universe 太窄，setup_quantile_threshold=0.05 on 5 股 ≈ 期望 0.25 股/day armed
- 真正 Track A 需要 53 股 universe（更宽 setup 池）+ 8 年（更多样本）

### 5.2 2.5bp slip 是 optimistic 估计
- Production `cost_model.yaml` 的 `slippage_intraday_bps`: 7-20 bps
- PRD §11 Q4 LOCKED 2.5 bps
- 2× cost sensitivity test 在 PRD §9 是 hard blocker，但 2× = 5bps 仍低于 production 7bps
- Phase 3 acceptance 报告应该明确这点：**alt-A 用了 optimistic 成本假设，如果 production cost 应用则收益减半左右**

### 5.3 Lehmann reversal 文献基础需要再验证 post-2010
- PRD §1 引用 Lehmann 1990 + Akbas-Boehmer 2022 + 2024 momentum reversal
- 这些 thesis 强度 ranges from 12-18%/yr pre-cost (PRD §7 估计)
- 但 2010 年以后多个 paper 报告 reversal alpha 衰减
- 2018/19/21/23/25 5 个 validation years 不同 regime（疫情前 / 疫情 / 加息 / 复苏 / 当前）— 如果 Track A 4/5 vs SPY 通过，可信度高

### 5.4 cycle #09 与 alt-A 关系
- cycle #09 INVALID per sampler postmortem（commit `e675510`）
- Option A 已 ship (commit `f41c7e5`) — cycle #09 可以重 fire on family_first sampling
- alt-A 是独立路径，cycle #09 状态不阻塞 alt-A

---

## §6 战略推荐 (资深 quant 视角)

按 [[feedback_quant_operator_role.md]]:

**短期 (本周内)**:
1. **Phase 3 Track A walking** — 用今天 ship 的基础设施在 53 股 × 8 年跑全 alt-A backtest + Track A 评估
2. **不要在 Phase 3 之前 forward fire alt-A** — Track A verdict 必须是 GO 才能 forward init
3. **不要扩大 alt-A 工程在 Phase 3 之前** — universe / cost model / signal definitions 都 LOCKED；先看 Track A 结果

**中期 (Phase 3 verdict 之后)**:
- 如果 Track A PASS（4/5 vs SPY + per-year DD ≤ 20% + 2x cost survives）→ forward init authorize
- 如果 Track A FAIL → 检查 fail mode：是 reversal alpha 衰减 OR cost binding OR universe-too-narrow？
  - alpha 衰减 → 不再 fire alt-A，转 alt-B (event-driven) OR alt-C (cross-asset)
  - cost binding → 重新 PRD §11 Q4 (但 user 已 LOCKED 2.5bp)
  - universe-too-narrow → 扩大 universe (53 → 100+ 股，但破 PRD §11 Q1 LOCKED)

**长期 (cycle #09 + alt-A 双重 verdict 后)**:
- 如果 cycle #09 (重 fire on Option A) + alt-A 都 nominee → 2-候选 fleet
- 如果只 alt-A nominee → 1-候选 fleet
- 如果都 fail → 转 alt-B / alt-C OR strategy-type pivot

---

## §7 Pending user decisions

1. **是否启动 Phase 3 Track A walking?** (今日 commits 已完成 Phase 2 D1-D4 必要基础设施)
2. **是否同意 alt-A 2.5bp slip 是 optimistic 而 2× = 5bp 仍合理保守的 cost assumption?** (PRD §11 Q4 LOCKED + PRD §9 cost sensitivity hard blocker)

不 directional 决定：
- Phase 3 工程顺序、cycle #09 重 fire 时机、forward fire alt-A 时机 → 都需要 user explicit-go

---

## §8 Today's commits 一览

| Commit | Phase 2 step | 内容 |
|---|---|---|
| `f97f4ed` | D1 | Design memo + bridge module + 12 tests |
| `2845e3b` | D2 | BT execution_freq kwarg + alt-A cost helper + 6 e2e tests |
| `81de011` | D3 | M11 parity explicit regression tests (6 new) |
| `118764a` | D4 (partial) | 60m intraday inputs helper + 8 unit tests + real-data 5-股 2024 smoke |
| `(this memo)` | D5 | Closeout |

Total tests added today (Phase 2): **32 new tests**, 0 regression failures, 304+ broader test surface stable.

---

*End of Phase 2 closeout. Phase 3 = Track A walking on 53-股 × 8 年; awaits user explicit-go.*
