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
