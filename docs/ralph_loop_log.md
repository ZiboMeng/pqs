# Ralph-Loop 运行日志 — Intraday Mining Phase

每一轮 ralph-loop 迭代结束时，将本轮的完整中文 11 部分报告**追加**到本文件末尾。
不要覆盖既有条目。

参考：
- `docs/prd_intraday_mining_loop.md` — 阶段 PRD
- `docs/ralph_loop_prompt.md` — 每轮协议
- `CLAUDE.md` — 系统不变约束

---

## Round 0 — Smoke + 审计 + NaN blocker 修复 + 资本金调整

**日期**: 2026-04-20
**Topic**: 前置准备（不属于 §3 A-L 主菜单）
**Lineage_tag**: `post-2026-04-20-closeout` → `post-2026-04-20-capital-100k`（capital bump 后）
**Commits**: `d562934`（NaN 护栏）· `ff2eeea`（PRD）· `e65285d`（ralph-loop prompt v1）· `b2ee519`（capital 10k→100k + prompt v2）
**测试**: 1005 → 1009 passing

### 1. 当前阶段
Mining 前最后收口 + smoke run + 全项目审计 + 生成下一阶段 PRD + 初始化 ralph-loop

### 2. 本轮目标
验证收口成果在真实 mining 环境下稳定；审计确认无新 blocker；产出可执行的 ralph-loop PRD；把资本金调到 $100k 让后续 mining 暴露真问题

### 3. 为什么先做它
"静态审计 10 问全绿"和"smoke 跑起来 13/20 崩溃"是两回事。先 smoke 再进入正式 mining 是 PRD §2.2 的硬规则

### 4. 做了什么
- Smoke v1（`--trials 20 --budget 300`）暴露 `int(NaN)` blocker
- 静态审计 10 问（Explore subagent）→ 全绿 + 1 doc minor
- 修复 `_generate_orders` NaN 护栏（`d562934`）+ 4 回归测试
- Smoke v2（fresh archive 同参数）：19/20 通过 quick，0 NaN 崩溃
- 写 PRD `docs/prd_intraday_mining_loop.md`（`ff2eeea`）
- 写 ralph-loop prompt `docs/ralph_loop_prompt.md`
- **Capital 10k → 100k**（`b2ee519`）：$700 SPY + integer_shares 下 10k 预算每次只能买 14 股，舍入噪声压过真实信号

### 5. 修改了哪些文件
- `core/backtest/backtest_engine.py`（NaN 护栏）
- `tests/unit/backtest/test_generate_orders_nan_guard.py`（新，4 tests）
- `docs/prd_intraday_mining_loop.md`（新）
- `docs/ralph_loop_prompt.md`（新 + rewrite）
- `config/system.yaml`（10k → 100k）
- `reports/ralph_loop_log.md`（本文件，新）

### 6. 跑了哪些测试 / 验证
- 2 次 smoke mining
- 4 个 NaN 护栏 focused 测试
- 全套 pytest 2 次：1005 → 1009 passing
- Archive 读取验证：20 行 lineage_tag 正确

### 7. 当前结果
Mining 基座稳定。QQQ gate plumbing 验证通过但未在 smoke 中实战触发（因无 trial 过 OOS）

### 8. 剩余风险
- QQQ gate 未实战触发 —— Round 1 (Topic A) 处理
- `_intraday_stale_counts` 跨进程不持久 —— Round 3 (Topic C) 处理
- Mining evaluator 不传 `open_df`（研究路径 warning storm）—— NON-BLOCKER

### 9. 下一轮建议
Round 1 执行 Topic A：`--trials 80 --budget 1800 --lineage-tag post-2026-04-20-capital-100k`，让 ≥1 trial 抵达 Stage 6

### 10. TODO checklist
- [x] Round 0 (smoke + audit + NaN fix + capital bump)
- [ ] Round 1 — Topic A: 全预算 smoke，QQQ gate 真正触发
- [ ] Round 2 — Topic B: leaderboard 显示 lineage + QQQ
- [ ] Round 3 — Topic C: stale_counts 进 checkpoint
- [ ] Round 4 — Topic D: factor gate strict mode
- [ ] Round 5-9 — E/F/G/H/I（research）
- [ ] Round 10-12 — J/K/L（infra）

---

## Round 1 — Topic A: 全预算 smoke + 研究 blocker 诊断

**日期**: 2026-04-20（21:11 完成）
**Topic**: A（full-budget smoke，QQQ gate 触发）
**Lineage_tag**: `post-2026-04-20-capital-100k`
**测试变化**: 1009 → 1009（未新增单测；本轮交付物是真实 mining 数据 + 研究信号）
**主要 commits**: `6f2a437`（清理 ralph-loop 状态 track）· `07d51e5`（研究发现写入 CLAUDE.md）

### 1. 当前阶段
Ralph-loop 第 1 轮 / Topic A

### 2. 本轮目标
让 archive 至少 1 行有非 NULL `qqq_full_period_excess`，证明 Stage 6 QQQ gate 在真实 mining 中被调用

### 3. 为什么先做它
PRD §3.1 第一优先级。Smoke v2 时 0 OOS 通过导致 gate 从未触发，这是收口结束后最大的未验证缺口

### 4. 做了什么
- 真实 mining run：`scripts/run_mining.py --trials 80 --budget 1800 --lineage-tag post-2026-04-20-capital-100k --type multi_factor`
- 运行 677 秒，120 evaluations，37 唯一 trials 写入 archive
- 审计 archive:
  - Lineage 分布 `post-2026-04-20-capital-100k` × 37 + `post-2026-04-20-closeout` × 20
  - `score=-999` 行数：**0**
  - 缺 `lineage_tag` 行数：0
  - `qqq_full_period_excess` 非 NULL：**0**
- OOS 分布诊断：`oos_ir` 区间 **-0.709 到 -0.113**（全部负值），quick_sharpe 0.424 到 0.774
- 在 CLAUDE.md 加新 section "Ralph-Loop Findings"，正式记录 Round 1 研究信号
- 在 "Current Best Strategy" 段加 ⚠️ 警告，明确那些数字来自 P0.1-fix 之前

### 5. 修改了哪些文件
- `CLAUDE.md`（⚠️ 标注 + 新 Ralph-Loop Findings 节）
- `.gitignore`（untrack `.claude/ralph-loop.local.md`）
- `docs/prd_intraday_mining_loop.md`（Appendix A Round 1 行）
- `docs/ralph_loop_log.md`（本节新增）

### 6. 跑了哪些测试
- `pytest tests/ -q`：**1009 passing**（轮前审计）
- `scripts/run_mining.py` 80 × 1800s 真实 smoke（677 秒）
- Archive 审计查询：lineage 分布、-999 行、缺 lineage 行、qqq 非 NULL 行、OOS IR 区间

### 7. 当前结果
- **Topic A 字面 completion signal（archive ≥1 非 NULL qqq_full_period_excess）未达成**
  - 根因：0 个 trial 通过 OOS → gate 从未被调用
- **但多项非目标验证通过**：
  - NaN 护栏在 80 trials 规模下稳定（0 crash）
  - Lineage tagging 跨 run 一致（37 new + 20 legacy 独立）
  - Archive schema 所有 QQQ 列正确写入（只是值是 NULL）
  - `_assign_tier` 正确把 100% trials 降级到 D
- QQQ gate 的 plumbing 在单测层已被 3 个文件充分覆盖

### 8. 剩余风险
- **研究 blocker**（新发现，本轮最重要产出）：post-P0.1-fix 口径下，当前策略参数空间在 80 trials / 1800s 预算内无法产生 OOS 正值。Phase B 文档记录的"current best"参数产自旧 shift=True 口径，本质是历史局部最优
- Ralph-loop 硬规则 7（`--trials > 200` 需用户签核）限制了 Round 2 通过加 trials 快速解决
- Legacy 20 行 `post-2026-04-20-closeout` lineage 在 $10k capital 下产生，与新 37 行已经隔离；Topic B 的 leaderboard 改动需要明确显示这个分层

### 9. 下一轮建议
**推荐 Round 2 = Topic B**（leaderboard 显示 lineage + QQQ），理由：
- 按 PRD §3.1 顺序
- 当前 archive 有 57 rows 跨 2 个 lineage，恰好是 Topic B 的测试用例
- 独立于 OOS 研究 blocker
- 完成后能更好地可视化 Round 1 发现的"历史 vs 当前"对比

**备选（off-menu，需用户签核）**：先解决 OOS 失败率 100% 的研究 blocker，选项：
- 扩搜索空间（加 `rebalance_monthly=True`、放宽 lookback）
- 调低 `oos_min_ir`（0.20 → 0.10）观察是否门槛问题
- 增加 trial 预算（需用户签核超 200）

默认按 PRD 顺序走 Topic B。

### 10. TODO checklist（更新后）
- [x] Round 0: smoke + audit + NaN fix + capital bump
- [x] Round 1: Topic A 真实 smoke → 诊断研究 blocker（post-P0.1 口径下 OOS 失败率 100%）
- [ ] Round 2: 推荐 Topic B（leaderboard 显示 lineage + QQQ）
- [ ] Round 3: Topic C（stale_counts 进 checkpoint）
- [ ] Round 4: Topic D（factor gate strict mode）
- [ ] Round 5-9: E/F/G/H/I（research，含新增的 OOS 诊断）
- [ ] Round 10-12: J/K/L（infra）

### 11. 本轮 commit 哈希
- `6f2a437` — chore: gitignore ralph-loop runtime state（轮前清理）
- `07d51e5` — Round 1 (Topic A): 实战 smoke + post-P0.1 口径下 OOS 失败率 100% 的研究信号
- `3b5f6b4` — docs: 第 1 轮日志更新

---

## Round 2 — Topic B: leaderboard 显示 lineage + QQQ + per-lineage 汇总

**日期**: 2026-04-20（21:37 完成）
**Topic**: B（leaderboard UX 升级）
**Lineage_tag**: `post-2026-04-20-capital-100k`（无方法论变更）
**测试变化**: 1009 → **1012**（+3 lineage_summary 单测）
**主要 commits**: `add1f80`（主体改动）

### 1. 当前阶段
Ralph-loop 第 2 轮 / Topic B

### 2. 本轮目标
`run_mining.py --leaderboard` 输出必须显示 `lineage_tag` / `passed_qqq_gate` / `qqq_*_excess` 列 + 按 lineage 分组汇总块

### 3. 为什么先做它
PRD §3.1 第二优先级。Round 1 在 archive 留了跨 2 个 lineage 的 57 行数据，正好是 Topic B 的真实测试用例。独立于 OOS 研究 blocker

### 4. 做了什么
- `core/mining/archive.py` 新 `lineage_summary()` helper：返回 per-lineage 聚合 DataFrame（`n_trials / n_quick_pass / n_oos_pass / n_holdout_pass / n_qqq_gate_pass / n_gate_evaluated / avg_quick_sharpe / worst_oos_ir / best_oos_ir`）。关键区分 `n_gate_evaluated`（Stage 6 被调用过）vs `n_qqq_gate_pass`（通过 gate 判定）
- `scripts/run_mining.py --leaderboard` 从 8 列扩到 13 列：加 `qqq_ok` ✓/✗ + 3 个 qqq_*_excess + `lineage_tag`。底部追加"按 Lineage 分组汇总"表格
- 新增 CLI 参数 `--lineage-filter <tag>`：可只看单一 lineage 的排行榜
- CLAUDE.md Ralph-Loop Findings 添加 Round 2 entry

### 5. 修改了哪些文件
- `core/mining/archive.py`（+40：`lineage_summary` 方法）
- `scripts/run_mining.py`（+45：CLI 重构 + `--lineage-filter`）
- `tests/unit/mining/test_archive_lineage.py`（+73：3 个新测试）
- `CLAUDE.md`（Ralph-Loop Findings: Round 2）
- `docs/prd_intraday_mining_loop.md` Appendix A（本日志更新）
- `docs/ralph_loop_log.md`（本节新增）

### 6. 跑了哪些测试
- `pytest tests/ -q`：**1012 passing**（+3）
- `scripts/run_mining.py --leaderboard`：13 列全显示；by-lineage 汇总显示 2 个 lineage（37 + 20），`n_gate_evaluated=0` 清楚证实 QQQ gate 未触发
- `scripts/run_mining.py --leaderboard --lineage-filter post-2026-04-20-closeout`：验证过滤器工作

### 7. 当前结果
Topic B completion signal **达成**：
- 默认输出含 `lineage_tag` + 全部 QQQ 列 ✓
- By-lineage breakdown 已存在 ✓
- Round 1 发现（0 gate 触发）在 CLI 里一目了然（`n_gate_evaluated=0`）
- 新 `--lineage-filter` 为"只看新 lineage"提供便利

### 8. 剩余风险
- Round 1 的研究 blocker 仍未解决：OOS 失败率 100% 是研究侧 blocker，本轮未碰（按 PRD "严禁合并两主题"）
- CLI 输出 13 列比较宽，窄终端可能折行。建议未来加 `--brief` 选项
- `qqq_full_period_excess` 等列在当前 archive 全 NULL，意料之中（gate 未触发）；新 lineage 如能跑出 OOS 通过的 trial，这些列才会有值

### 9. 下一轮建议
**Round 3 = Topic C**（stale_counts 进 checkpoint）按 PRD §3.1 顺序。或继续考虑 off-menu 解决 OOS blocker（需用户签核才能提 `--trials > 200`）。默认走 Topic C

### 10. TODO checklist（更新后）
- [x] Round 0: smoke + audit + NaN fix + capital bump
- [x] Round 1: Topic A（诊断 OOS 100% 失败率）
- [x] Round 2: Topic B（leaderboard lineage + QQQ + per-lineage 汇总）
- [ ] Round 3: Topic C（stale_counts 进 checkpoint）
- [ ] Round 4: Topic D（factor gate strict mode）
- [ ] Round 5-9: E/F/G/H/I（research，含 OOS 诊断）
- [ ] Round 10-12: J/K/L（infra）

### 11. 本轮 commit 哈希
- `add1f80` — Round 2 (Topic B): leaderboard 显示 lineage + QQQ + per-lineage 汇总
- （本条 doc commit）— docs: 第 2 轮日志更新

---
