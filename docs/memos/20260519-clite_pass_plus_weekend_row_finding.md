# C-lite PASS（P1.3 闭）+ bulk expanded_v2 weekend-row 数据质量 finding

**日期**: 2026-05-19 (loop R6) · **纪律**: `feedback_bar_level_data_integrity_smoke`、`feedback_audit_surfaces_not_thorough`（smoke 报异常不因 C-lite PASS 而埋）、`feedback_no_blanket_failure_verdict`、`feedback_self_audit_methodology`(R3 grounded blast-radius)。

---

## §1 C-lite empirical 背书 = PASS（P1.3 正式闭）

`bdwoxptnv`：cycle06（--lineage track-c-cycle-2026-05-06-01 --top-n 3）+ cycle08（track-c-cycle-2026-05-08-01）在当前 HEAD（含 P1.1 label_leakage + P1.2b acceptance.yaml leakage_correct default-on）重评 → diff vs `cycle0{6,8}_track_a_eval_postP0maxdd.json`：

> **cycle06 / cycle08 均 VERDICT BIT-IDENTICAL — NONE differ**（n_passed + per-trial verdict/failed_gates/metrics_full_period 全等）。

→ grounded §1（factor-composite 无 probe-fit leakage 作用面）**经验证实**。**A = grounded + empirical 双确认**：run4 probe-fit leakage 仅 chart_native_s1（已 Option A caveat）;cycle06/08 主线 Track-A PASS 站得住,不重评不 retire,主线不归零。**PRD-1 P1.3 正式闭。**

## §2 NEW finding：bulk expanded_v2 ~1000 parquet weekend-row 污染 + 陈旧

C-lite STEP0 bar-integrity smoke 报 90 个 daily 中 81 个有 weekend 行。R3 grounded blast-radius 实查：

| 集合 | weekend 行 | span | 判定 |
|---|---|---|---|
| **CURATED/active**（SPY/QQQ/AAPL/MSFT/NVDA/MU/TXN/BIL/SHV）| **全 0** | SPY 2007+ 4874 行;curated 2015+ | **干净**（SPY off-by-one tz fix 守住） |
| **BULK expanded_v2**（AAA/AAAA/AAAU/AAAP/AAAC...）| 重污染（AAAU 386 / AAA 231 ...）| 多止于 **2026-04-17**(陈旧) | **污染 + stale**;AAA 不在 core universe yaml |

**Root cause（不 hand-wave）**：SPY/BIL/SHV off-by-one tz_localize fix（2026-05-13）当初**窄修了 active 3 名,未覆盖 ~1000 bulk expanded_v2**（yfinance bulk-fetch 名,同 tz artifact 未修 + 未续 fetch 故 stale 于 04-17）。

## §3 影响范围（诚实，scoped 非 blanket）

- **不受影响**：curated / PRD-1/2/3 critical path / cycle06/08 / 所有活跃 forward 候选 / chart_native executable-79 forward 候选 —— 全 grounded 干净。C-lite PASS 与此自洽。
- **受影响**：chart_native **1k 实验**(S1 scale falsification expanded_v2 / L3-A expanded_v2 FAIL / de-confound 三点曲线的 1k 点)—— 用的正是这批污染 bulk parquet。
  - 这些结论**已 config-scoped / research-signal / 非可部署 / 已 caveat**,且 L3-A 1k 已 FAIL、chart_native_s1 forward 候选用的是 curated-79(不受影响)。
  - **新增诚实 confound（必须标，不埋）**：de-confound 的 "IC-on-59 随 59→79→1k 单调退化(+0.022→+0.015→−0.012)" 里,**1k 那一点的退化部分可能是 weekend 垃圾 bar 污染,而非纯 train/trade dilution**。不推翻主结论(仅 chart_native_s1 受 run4 leakage / cycle06/08 干净 —— 那是 curated-clean 独立证据),但 **de-confound 1k 点的"纯 dilution"解释要降一档置信:dilution 方向仍在(79 vs 59 对比是 curated-clean),1k 绝对数混了数据污染**。

## §4 处置（tactical,非 directional stop）

- 不在 loop 内自动重 fetch 1000 bulk 名（重活、off-critical-path、那批 1k 实验已闭/已 caveat）。
- **PRD-3 依赖标注**：若 PRD-3 组件 A4 / B 或任何未来实验要用 expanded_v2(>79 universe),**前置必须先修 bulk parquet weekend-row + 续 fetch**（同 SPY off-by-one fix 推广到 1000 名）。已记入 ledger 作 PRD-3 expanded-universe 硬前置。
- 非协议 directional stop（不动不变量/评估准则/repo 结构;loop PRD-1/2/3 走 curated-clean,继续）。但作为**显著 finding 上报用户**(并与用户进行中的 CLAUDE.md→`core/data/CONTEXT.md` reorg 相关:此 finding 应入 data CONTEXT.md)。

## §5 P1.4 协调点（诚实标）

PRD-1 P1.4 = "结论 fold 进 manifest/CLAUDE.md"。**用户正在决策 CLAUDE.md reorg（3 确认点未答）→ P1.4 的 CLAUDE.md-fold 暂缓**，本轮只 fold 进 ledger + 本 memo + scope-correction memo;CLAUDE.md 部分待 reorg 决策后一并落（避免与 reorg 冲突 / 二次返工）。PRD-1 实质完成,仅 CLAUDE.md-fold 这一尾巴 entangled 于 reorg,显式留痕非遗漏。

关联 [[feedback_bar_level_data_integrity_smoke]] [[project-grand-audit-2026-05-18-two-p0]];源 `data/audit/ml_redo/clite_verify.log`、`docs/memos/20260518-prd1_p13_scope_correction_factor_composite_unaffected.md`、`docs/memos/20260518-l3_deconfound_correctness_verdict.md`。
