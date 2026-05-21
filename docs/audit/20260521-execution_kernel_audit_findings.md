# 执行内核审计 — 发现与处置（2026-05-21）

**触发**：外部独立 review（用户粘贴）对 backtest/paper parity、研究治理、
执行内核提出若干 claim。operator 以独立 quant 身份逐条 grep 代码核验、
literature 经 websearch 核对，并把"需要做的"全部修掉。

**关联**：`feedback_audit_surfaces_not_thorough`（audit 必须暴露"做出来
没做透"+ 纠 overclaim + fold 进文档）、`feedback_quant_operator_role`、
`feedback_no_blanket_failure_verdict`。

---

## 1. 逐条核验结果

| # | review claim | 裁决 | commit |
|---|---|---|---|
| 1 | backtest_engine 时序错位 | ✅ 真（review over-claim "浓度统计") | `d5f4ca9` |
| 2 | partial fill 强制整数股 | ✅ 真 | `75752e7` |
| 3 | run_paper exec_open 用 T+1 close 顶替 | ✅ 真 | `842f813` |
| 4 | strict_match 测试容差过松（500bps） | ✅ 真，且 root cause 比 review 说的更具体 | `14a1c0c` |
| 5 | 未验证策略进默认生产路径 | 🟡 事实真，"做成注释而非制度"错（见 §3） | — |
| 6 | baseline n_oos_pass=0 | ✅ 真（项目自报状态，非隐藏） | — |
| 7 | cost_model 静态 bps | ✅ 真（前瞻性，无 live 执行） | — |
| 8/9 | multi_factor -67% MaxDD / BULL 差 | 🟠 真，且 review **低估**：是 invariant 违反，root cause = §2 | `d056652` |

---

## 2. P0：conservative_default -67% MaxDD 的 root cause

**`PortfolioConstructor._apply_vol_target` 用对角（零相关）协方差估计组合
波动率** —— `sqrt(sum((w·σ)^2))`。对集中、高相关的 long-only 股票组合，
这系统性低估真实波动率约 1.5-2x，于是 `scale = min(1, target_vol/port_vol)`
长期 = 1.0、敞口从不被缩减，实际波动率跑到 target 的 ~2x，多年回撤复利
成 -67% MaxDD，直接违反「MaxDD 15-20%」硬不变量。

**R3 实证**（4 个同涨同跌标的等权）：
- 对角(旧) port_vol = 0.166
- realized port_vol = 0.329 ← 旧估计低估 **1.99x**
- 协方差(新) port_vol = 0.329 ← 精确吻合

**修复**（`d056652`）：新 `_portfolio_vol()` 计算 `sqrt(wᵀ Σ w)`，
Σ = D·R·D（D=各标的年化 vol，R=滚动窗口相关性矩阵，严格 pre-date
无 lookahead）；缺失 pair 相关性回退到已观测 off-diagonal 均值。

**连起来的旧发现**：2026-05-18 大清盘 audit 曾把"组合用对角协方差"
列为 diversifier-track 的 P1 —— 但没认出它就是**主生产策略 MaxDD
invariant 违反的 root cause**。这是 audit discipline 要的"没做透 +
没连起来"。

**剩余 directional（未自决，留给用户）**：`_DEFAULT_TARGET_VOL = 0.25`
本身（docstring 却写 0.15）—— 修复后实际波动率 ≈ 25%，仍高于
15-20% MaxDD invariant 的隐含预算。把 target 调低是 risk-budget
决策，须用户拍板。

---

## 3. operator 对 review 的 3 处纠偏（独立判断）

1. **claim #1 over-claim "浓度统计被污染"**：`equity_curve` 与
   `weights_df` 都是 pre-fill 自洽 → CAGR/Sharpe/MaxDD/M12 浓度**不
   受影响**；真实 off-by-one 只在 `positions_df` + `cash_curve`。该
   off-by-one **是已知的**：`test_cash_carry_armed_not_yet_filled`
   显式注释"cycle04-08 existing BT semantics"把它钉成 canonical 而非
   修 —— 又一个"做出来没做透"。

2. **claim #5 "governance 是注释不是制度"说反了**：
   `core/config/production_strategy.py` 有 `StatusLiteral` 三态 enum
   + pydantic validator（`status=active` 硬校验）+ 对
   `no_validated_best` 直接 `raise`（fail-closed 已实现）。准确的
   窄问题 = `conservative_default` 是故意设计的"允许未验证策略跑
   paper、只 WARN"的第三态；未来上 live 是否放行它 = 设计选择。

3. **PBO/DSR 不是新建议**：`core/research/` 已有 `cpcv.py` /
   `mining_pbo.py` / `dsr_trial_accounting.py` / `overfit_metrics.py`
   等（G1-G5 PRD，2026-05-17 ship）。真实 open item = wiring 完整性。

literature 核对（websearch）：FINRA 5310「regular & rigorous review」
（至少季度、security×order-type）+ SEC Rule 605 2024 修订（纳入
fractional/odd-lot，notional 分桶，合规日 2026-08-01）—— review 描述
均准确，属前瞻性（项目无 live 执行）。

---

## 4. 五个修复（全部 commit + push + 回归绿）

| commit | 内容 | 测试 |
|---|---|---|
| `d056652` | P0-1 相关性感知 vol-target | +3 constructor 回归测试 |
| `75752e7` | P2-1 partial-fill 尊重 fractional 配置 | +2 simulator 回归测试 |
| `d5f4ca9` | P1-1 cash_curve/positions 对齐 equity（off-by-one） | +1 reconciliation 测试，修正 1 个钉 bug 的旧测试 |
| `842f813` | P2-2 去掉 run_paper exec_open→T+1-close 静默顶替 | NaN-guard 既有覆盖 |
| `14a1c0c` | P0-2 修 parity 测试 helper（丢了 integer_shares） | strict_match 500bps→10bps，divergence 实测 10.58→0.00 |

**P0-2 root cause 比 review 更具体**：divergence 不是"path-dependent
execution"（注释错，backtest 也是 day-by-day），而是 `_run_paper`
helper 接了 `integer_shares` 参数**从不转发**给 `PaperTradingEngine`
→ paper 静默跑整数股、backtest 跑小数股。helper 修好后 fractional
+ zero-cost + deterministic 两引擎**精确匹配 0.00 bps**。

---

## 5. 未决（directional，待用户）

- **target_vol=0.25**：vol-target 现在准确了，但 0.25 target 本身与
  15-20% MaxDD invariant 有张力。调低 target 或 docstring/常量对齐
  （0.15 vs 0.25）= risk-budget 决策。
- **conservative_default 在未来 live 路径是否放行** = 设计选择。
- **cost_model TCA 升级 / robustness 模块 wiring 完整性** = 前瞻性，
  按既有 backlog 排期。
- **multi_factor 修复后 MaxDD 端到端重测**：建议在 train-only 窗口
  （2010-2017，避免消耗 validation）实测新 MaxDD，确认从 -67% 下降。
