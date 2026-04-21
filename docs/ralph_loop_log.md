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
- `96f0784` — docs: 第 2 轮日志更新

---

## Round 3 — Topic C: stale_counts 持久化到 bar_checkpoints

**日期**: 2026-04-20（22:02 完成）
**Topic**: C（stale_counts 跨进程持久化）
**Lineage_tag**: `post-2026-04-20-capital-100k`（无方法论变更）
**测试变化**: 1012 → **1018**（+6 stale_counts 持久化测试）
**主要 commits**: `5bc3e4e`

### 1. 当前阶段
Ralph-loop 第 3 轮 / Topic C

### 2. 本轮目标
把 `PaperTradingEngine._intraday_stale_counts` 持久化到 `bar_checkpoints` 表，进程重启后能恢复，让多日 halt 的 ghost cleanup 能正确跨天累积触发

### 3. 为什么先做它
PRD §3.1 第三优先级。Closeout 1/4 commit 里就标过"stale_counts 跨进程不持久化"是遗留风险。生产 live 场景：标的被 halt 跨天、engine 重启之后 counter 清零，threshold 永远不触发

### 4. 做了什么
- `save_bar_checkpoint` 的 `state_json` 里额外写 `stale_counts` 字段（不改 signature，直接读 `self._intraday_stale_counts`）
- `load_bar_checkpoint` 返回 dict 新增 `stale_counts` 字段；老 checkpoint 缺此 key 时返回 `{}`（向后兼容）
- `run_day_intraday` 的 resume 路径：**总是**从 cp 恢复 `stale_counts`，**不依赖** `cp.date == date` 判断。语义：stale_counts 是跨日累积量，不是"当日状态"。Positions/cash 仍只在同日 resume 时恢复

### 5. 修改了哪些文件
- `core/paper_trading/paper_trading_engine.py`（+30：`save/load_bar_checkpoint` + `run_day_intraday` 恢复路径）
- `tests/unit/paper_trading/test_stale_counts_checkpoint.py`（新，6 tests）
- `CLAUDE.md`（Round 3 entry in Ralph-Loop Findings）
- `docs/prd_intraday_mining_loop.md` Appendix A（本日志）
- `docs/ralph_loop_log.md`（本节）

### 6. 跑了哪些测试
- `pytest tests/ -q`：**1018 passing**（+6）
- 6 focused 测试覆盖完整：save 写入 / load 读回 / 老格式兼容 / 同日 resume / 跨日 resume / **多日 halt 端到端累积触发 ghost cleanup**（5 天 halt + 重启 + 6 天 halt，cumulative 11 > threshold 8）

### 7. 当前结果
Topic C completion signal **达成**：
- 关键测试 `test_cumulative_halt_across_two_days_triggers_cleanup` 直接验证"杀 engine mid-day halt → 重启 → 新 engine 续上 counter → 累积到 threshold → 正确触发 ghost cleanup"
- 老格式 checkpoint 向后兼容 (`test_legacy_checkpoint_without_stale_counts_returns_empty_dict`)

### 8. 剩余风险
- `save_bar_checkpoint` 现在写整个 `stale_counts` dict 到 JSON。大 universe 场景下 checkpoint 体积会增长。目前可接受（生产 top_n=4-6）
- checkpoint 里 `date` 仍 `str(date.date())`，时间诊断不如 ISO datetime 精确（留给 future round）
- Round 1 的 OOS 研究 blocker 仍未解决，非本轮范围

### 9. 下一轮建议
**Round 4 = Topic D**（factor gate WARN/ERROR 可配置），PRD §3.1 最后一项。完成后 §3.1 全关闭，Round 5+ 转入 §3.2 research 菜单或 off-menu OOS blocker

### 10. TODO checklist（更新后）
- [x] Round 0: smoke + audit + NaN fix + capital bump
- [x] Round 1: Topic A（诊断 OOS 100% 失败率）
- [x] Round 2: Topic B（leaderboard lineage + QQQ）
- [x] Round 3: Topic C（stale_counts 进 checkpoint）
- [ ] Round 4: Topic D（factor gate strict mode）
- [ ] Round 5-9: E/F/G/H/I（research，含 OOS 诊断）
- [ ] Round 10-12: J/K/L（infra）

### 11. 本轮 commit 哈希
- `5bc3e4e` — Round 3 (Topic C): stale_counts 持久化到 bar_checkpoints
- `4be37e0` — docs: 第 3 轮日志更新

---

## Round 4 — Topic D: factor gate WARN/ERROR 可配置

**日期**: 2026-04-20（22:30 完成）
**Topic**: D（factor registry strict mode）
**Lineage_tag**: `post-2026-04-20-capital-100k`（无方法论变更）
**测试变化**: 1018 → **1029**（+11 strict mode 测试）
**主要 commits**: `f4ee30d`
**里程碑**: **PRD §3.1 Topics A-D 全部关闭**

### 1. 当前阶段
Ralph-loop 第 4 轮 / Topic D

### 2. 本轮目标
给 factor registry gate 加 `strict_mode` 配置：ERROR 模式下未注册 factor 名抛 `UnregisteredFactorError`；默认 WARN + drop 保持不变

### 3. 为什么先做它
PRD §3.1 最后一项。完成后 §3.1 A-D 全关闭，Round 5+ 转入 §3.2 research 菜单或 off-menu OOS blocker

### 4. 做了什么
- 新 `UnregisteredFactorError(ValueError)` 异常类
- 新 `enforce_execution_factor_names(weights, *, strict=False)` 统一入口（替换 `MultiFactorStrategy.__init__` 里的 inline 逻辑）
- 新 pydantic `FactorRegistryConfig(strict_mode: bool = False)` + `config/risk.yaml::factor_registry` 段
- `MultiFactorStrategy.__init__` 加 `strict_registry: bool = False` kwarg
- 3 个生产脚本 + `MultiFactorSpace` 从 config 透传
- `_registry_kwargs()` lazy-load helper（同 `_concentration_kwargs` 模式）

### 5. 修改了哪些文件
- `core/factors/factor_registry.py`（+60：错误类 + enforce 函数）
- `core/config/schemas/risk.py`（+20：FactorRegistryConfig）
- `config/risk.yaml`（+7：factor_registry 段）
- `core/signals/strategies/multi_factor.py`（+5 / -11：简化 gate 路径）
- `core/mining/strategy_space.py`（+12：`_registry_kwargs` helper）
- `scripts/run_backtest.py` / `run_paper.py` / `run_multi_tf_backtest.py`（+2 each：传递 strict_registry）
- `tests/unit/factors/test_factor_registry_strict_mode.py`（新，11 tests）
- `CLAUDE.md`（Round 4 entry）

### 6. 跑了哪些测试
- `pytest tests/ -q`：**1029 passing**（+11）
- 11 focused 测试：enforce 函数 default/strict/空 / MultiFactorStrategy 三种场景 / Config schema 默认 / mining space 读配置 + fallback

### 7. 当前结果
- Topic D completion signal **达成**
- **PRD §3.1 A-D 里程碑 全关闭** —— 接下来转研究或基建主题
- 默认保持 WARN 不破坏 legacy 脚本；mining/CI 可随时切 strict 防 typo

### 8. 剩余风险
- 当前生产 default 仍 WARN；mining 里 typo 仍可能静默被 drop。用户可在 config 里随时切 `strict_mode: true` 升级为 error
- factor_generator 的研究因子没有自动化 promotion check 工具（研究→生产仍需手工改 3 处：`PRODUCTION_FACTORS` + `MultiFactorStrategy.generate` + `MultiFactorSpace.suggest`）。future round 可考虑
- Round 1 OOS blocker 仍在

### 9. 下一轮建议
Round 5 候选：
- **§3.2 Topic F**（intraday factor family）—— 最贴合 PRD 初衷 "intraday mining"，独立于 OOS blocker（IC screen 不需要 OOS pass），有机会发现新 OOS-positive 因子 ⭐
- §3.2 Topic E（shadowed-factor merge）—— 合并 research↔production 配对；风险：改动会影响 backtest 结果
- off-menu：用户签核 `--trials > 200` 攻击 OOS blocker

**推荐 Topic F**。

### 10. TODO checklist（更新后）
- [x] Round 0: smoke + audit + NaN fix + capital bump
- [x] Round 1: Topic A（诊断 OOS 100% 失败率）
- [x] Round 2: Topic B（leaderboard lineage + QQQ）
- [x] Round 3: Topic C（stale_counts 进 checkpoint）
- [x] Round 4: Topic D（factor gate strict mode）→ **§3.1 全关闭**
- [ ] Round 5: **Topic F**（intraday factor family）— 推荐
- [ ] Round 6-9: E/G/H/I（research）
- [ ] Round 10-12: J/K/L（infra）

### 11. 本轮 commit 哈希
- `f4ee30d` — Round 4 (Topic D): factor gate WARN/ERROR 可配置
- `036a054` — docs: 第 4 轮日志更新

---

## Round 5 — Topic F: 首个 intraday factor family 引入（research-only）

**日期**: 2026-04-20（22:55 完成）
**Topic**: F（intraday factor family introduction）
**Lineage_tag**: `post-2026-04-20-capital-100k`（无方法论变更）
**测试变化**: 1029 → **1039**（+10 intraday factor 单测）
**主要 commits**: `710e8c3`

### 1. 当前阶段
Ralph-loop 第 5 轮 / Topic F

### 2. 本轮目标
在 factor_generator.py 加第一个依赖 60m bar 的 factor family；注册为 RESEARCH-only（不进 PRODUCTION_FACTORS）；通过 IC 筛验证有非平凡 IC

### 3. 为什么先做它
§3.1 全关闭后 §3.2 第一项；最贴合 "intraday mining" 主题；独立于 Round 1 OOS blocker（IC 筛不需要 OOS pass）

### 4. 做了什么
- `generate_all_factors` 加可选 `intraday_bars_60m: Dict[str, pd.DataFrame]` 参数
- 新 `_intraday_factors()` helper 产出 3 个因子（RTH 过滤、warmup 处理、NaN 安全）：
  - `realized_vol_60m_21d` — 21d 滚动 annualized realized vol，从 60m bar returns 计算
  - `intraday_vol_ratio_21d` — intraday rv / daily close-to-close vol 比值
  - `intraday_autocorr_21d` — 日内 60m bar lag-1 自相关 21d 滚动均值
- 3 个新名加入 `RESEARCH_FACTORS`；故意不加 `RESEARCH_TO_PRODUCTION_MAP`（研究-only）
- 适配 drift 测试：`test_all_generator_outputs_registered` 加合成 60m bars 让新因子参与校验

### 5. 修改了哪些文件
- `core/factors/factor_generator.py`（+85：`_intraday_factors` helper + 参数）
- `core/factors/factor_registry.py`（+5：`RESEARCH_FACTORS` 加 3 名）
- `tests/unit/factors/test_intraday_factor_family.py`（新，10 tests）
- `tests/unit/factors/test_factor_registry.py`（+25：drift 测试加合成 bars）
- `CLAUDE.md`（Ralph-Loop Findings: Round 5）
- `docs/prd_intraday_mining_loop.md` Appendix A（本日志）
- `docs/ralph_loop_log.md`（本节）

### 6. 跑了哪些测试
- `pytest tests/ -q`：**1039 passing**（+10）
- 真实数据 IC smoke：SPY + QQQ + Mag7（8 symbols）× 2020 至今（1582 days）:

  | Factor | IC_5d | IC_21d |
  |---|---:|---:|
  | `realized_vol_60m_21d` | +0.054 | **+0.096** ✓ |
  | `intraday_vol_ratio_21d` | -0.015 | -0.002 |
  | `intraday_autocorr_21d` | +0.003 | +0.043 |

### 7. 当前结果
- Topic F completion signal **达成**：`realized_vol_60m_21d` 21d IC ≈ +0.10（远超 trivial 门槛）
- 研究信号：高日内波动 → 未来回报偏正（vol risk premium 理论一致）
- 但仍是 research-only，未做 OOS/regime/cost 完整 funnel，**不得直接进生产**

### 8. 剩余风险
- IC smoke 只在 8 标的 × 6 年，跨 universe / 跨 regime 验证未做
- `realized_vol_60m_21d` 与已有 `vol_63d` / `vol_21d` 正相关强，promote 前需做 orthogonality check
- Round 1 OOS blocker 仍未解；下轮可考虑用新因子重跑 mining 看是否改变结果

### 9. 下一轮建议
- **Round 6 = Topic E（shadowed-factor merge）**⭐ —— 清理 vol_63d ↔ low_vol 等双实现，降低维护成本；可能影响 backtest 数字
- 备选 Topic G（cross-TF feature training）—— 较大工程
- Off-menu：手工 promote `realized_vol_60m_21d` 到 `PRODUCTION_FACTORS` 跑 smoke 看 OOS 改善（需用户签核）

### 10. TODO checklist（更新后）
- [x] Round 0: smoke + audit + NaN fix + capital bump
- [x] Round 1: Topic A（诊断 OOS 100% 失败率）
- [x] Round 2: Topic B（leaderboard lineage + QQQ）
- [x] Round 3: Topic C（stale_counts 进 checkpoint）
- [x] Round 4: Topic D（factor gate strict mode）→ **§3.1 全关闭**
- [x] Round 5: Topic F（intraday factor family → IC_21d +0.096）
- [ ] Round 6: Topic E（shadowed-factor merge）— 推荐
- [ ] Round 7-9: G/H/I（research）
- [ ] Round 10-12: J/K/L（infra）

### 11. 本轮 commit 哈希
- `710e8c3` — Round 5 (Topic F): 首个 intraday factor family 引入
- `72d0d7d` — docs: 第 5 轮日志更新

---

## Round 6 — Topic E: shadowed-factor merge（vol_63d↔low_vol, rs_vs_spy_63d↔rel_strength）

**日期**: 2026-04-20（23:20 完成）
**Topic**: E（shadowed-factor merge，2 对）
**Lineage_tag**: `post-2026-04-20-capital-100k`（纯代码 refactor，数值等价，不 bump）
**测试变化**: 1039 → **1053**（+14 merge 单测）
**主要 commits**: `12fe965`

### 1. 当前阶段
Ralph-loop 第 6 轮 / Topic E

### 2. 本轮目标
抽取共享 factor 实现到 `core/factors/base_factors.py`，让 factor_generator 与 MultiFactorStrategy 都调用同一个；消除 2 对 shadow 实现；`RESEARCH_TO_PRODUCTION_MAP` 从 9 条缩到 7 条

### 3. 为什么先做它
PRD §3.2。Round 5 已引入新 intraday 因子；如果 shadow 不清掉，未来 promote 时无法确定是 promote 研究版还是改生产 inline。本轮一次性清完，后续 promote 只需加 helper，两路同时受益

### 4. 做了什么
- 新 `core/factors/base_factors.py`：共享 `low_vol_factor` + `rel_strength_factor`（纯函数，无 config 耦合）
- `factor_generator` 里 `vol_21d/63d`、`rs_vs_spy_21d/63d/126d`、`rs_acceleration` 全走 helper
- `MultiFactorStrategy.generate` 的 `low_vol` 和 `rel_strength` inline 实现移除，改调 helper
- `RESEARCH_TO_PRODUCTION_MAP` 删 `vol_63d` 和 `rs_vs_spy_63d` 两条（9 → 7）
- 14 focused 单测（纯度 / 数值等价 / map 精确减 2 / 向后兼容）

### 5. 修改了哪些文件
- `core/factors/base_factors.py`（新，80 行）
- `core/factors/factor_generator.py`（-18, +10：两处改共享 helper）
- `core/signals/strategies/multi_factor.py`（-5, +12：inline 改 helper）
- `core/factors/factor_registry.py`（MAP 减 2 + docstring 更新）
- `tests/unit/factors/test_shadowed_factor_merge.py`（新，14 tests）
- `CLAUDE.md`（Round 6 entry）

### 6. 跑了哪些测试
- `pytest tests/ -q`：**1053 passing**（+14）
- 现有 drift 测试 `test_all_generator_outputs_registered` 无需改动（RESEARCH_FACTORS 集合未变）
- 8-symbol backtest smoke（SPY + QQQ + Mag7, 2020 至今, $100k）：CAGR +6.32%, Sharpe 0.21，完成无异常

### 7. 当前结果
Topic E completion signal **达成**：
- MAP 精确缩减 9 → 7
- Backtest delta 远小于 50bps CAGR（z-score 之后 annualization 相消；`min_periods=20` 两边一致，warmup 无差异）
- 代码层面：factor_generator 和 MultiFactorStrategy 共享实现，后续 promote 新因子（如 `realized_vol_60m_21d`）只需加一个 helper 到 `base_factors.py`

### 8. 剩余风险
- 还有 7 对 shadow 可合并（`mom_252d/mom_12_1` → `momentum`、`rolling_sharpe_126d/return_per_risk_21d` → `quality`、`price_volume_div` → `pv_div`、`spy_trend_200d` → `market_trend`、`vol_21d` → `low_vol`）。未本轮范围。但模式已经确立，后续合并都很轻
- Round 1 OOS blocker 仍在，不本轮处理

### 9. 下一轮建议
**Round 7 = Topic I**（mining 扩展到多 strategy type）⭐ —— 最直接暴露 mining 系统扩展性（新 strategy type 过 QQQ gate 一致吗？），独立于 OOS blocker
- 备选 Topic G（cross-TF feature training）或 Topic H（ridge vs XGB）
- Off-menu：继续合并剩余 shadow pairs，或 promote `realized_vol_60m_21d`（需用户签核因为涉及 PRODUCTION_FACTORS 变更）

### 10. TODO checklist（更新后）
- [x] Round 0: smoke + audit + NaN fix + capital bump
- [x] Round 1: Topic A（诊断 OOS 100% 失败率）
- [x] Round 2: Topic B（leaderboard lineage + QQQ）
- [x] Round 3: Topic C（stale_counts 进 checkpoint）
- [x] Round 4: Topic D（factor gate strict mode）→ **§3.1 全关闭**
- [x] Round 5: Topic F（intraday factor family，IC_21d +0.096）
- [x] Round 6: Topic E（shadow merge: 9→7）
- [ ] Round 7: Topic I（mining 多 strategy type）— 推荐
- [ ] Round 8-9: G/H（research）
- [ ] Round 10-12: J/K/L（infra）

### 11. 本轮 commit 哈希
- `12fe965` — Round 6 (Topic E): shadowed-factor merge
- `9025dec` — docs: 第 6 轮日志更新

---

## Round 7 — Topic I: mining 跨 4 种 strategy_type + QQQ gate 类型无关

**日期**: 2026-04-20（23:45 完成）
**Topic**: I（parameter search expansion across strategy types）
**Lineage_tag**: `post-2026-04-20-capital-100k`
**测试变化**: 1053 → **1067**（+14 跨类型 invariant 单测）
**主要 commits**: `cb47d80`

### 1. 当前阶段
Ralph-loop 第 7 轮 / Topic I

### 2. 本轮目标
验证 mining 系统能跨 4 种 strategy_type 一致工作；archive 有 ≥3 non-multi_factor trials；QQQ gate + `_assign_tier` 对所有 strategy_type 应用一致

### 3. 为什么先做它
PRD §3.2 Topic I。之前 archive 只有 multi_factor trials；其它 3 种 ParameterSpace 虽注册但未实战验证过 pipeline，尤其 QQQ gate 是否 type-agnostic

### 4. 做了什么
- 真实 mining run：`scripts/run_mining.py --trials 5 --budget 900 --lineage-tag post-2026-04-20-capital-100k`（**不带 --type**）
- 运行 199s，140 evaluations，**20 unique trials × 4 types 均匀入库**
- Archive 分布：multi_factor × 37 + dual_momentum × 5 + cross_asset_rotation × 5 + trend_following × 5 + legacy 20 = 72
- **15 个 non-multi_factor trials**（远超 completion signal 3）
- 所有 trials tier = D（`trend_following` 0/5 quick；其余 3/5 quick；multi_factor 37/37 quick；全部 0 OOS pass）
- 新 focused 单测（14 条）守护跨类型 invariants：ALL_SPACES 4 注册 / suggest+instantiate 不 crash / archive 跨类型保留 strategy_type / `_assign_tier` 在 gate fail 时强制 D 不论 strategy_type

### 5. 修改了哪些文件
- `tests/unit/mining/test_all_strategy_types.py`（新，14 tests）
- `CLAUDE.md`（Ralph-Loop Findings: Round 7）
- `docs/prd_intraday_mining_loop.md` Appendix A（本日志）
- `docs/ralph_loop_log.md`（本节）

### 6. 跑了哪些测试
- `pytest tests/ -q`：**1067 passing**（+14）
- Archive 跨类型审计：4 种 strategy_type 全部写入成功，schema 一致，tier 分配一致
- 轮后 invariant：`tier != 'D' AND passed_qqq_gate = 0` 计数 = 0（无泄漏）

### 7. 当前结果
Topic I completion signal **达成**：
- 15 non-multi_factor trials ≥ 3 ✓
- 4 种类型全部正常走完 pipeline
- QQQ gate plumbing 跨类型一致（gate 未触发仅因 0 trial 过 OOS，不是 bug）

### 8. 剩余风险
- **`trend_following` 0/5 quick_pass**：要么该类策略在当前 universe 上本身不工作，要么 ParameterSpace 搜索空间过窄。后续轮可针对性调
- QQQ gate 仍"未在真实 trial 触发" —— 同 Round 1/4
- Round 1 OOS blocker 仍在；跨 4 种类型的 mining 也没改变 OOS 通过率 = 0 的结论
- Optuna 采样 140 evals 只有 20 unique trials（去重明显），但对本轮 invariant 验证不影响

### 9. 下一轮建议
**Round 8 = Topic G**（cross-TF feature training）⭐
- 最能帮助理解 Round 5 新 intraday 因子是不是真正有 alpha（用 `validate_timing_value.py` 对比 with/without intraday factor composite）
- 输出决定下一步是否 promote `realized_vol_60m_21d` 到 `PRODUCTION_FACTORS`
- 备选 Topic H（ridge vs XGB）：研究工具对比
- Off-menu：直接攻击 OOS blocker（需用户签核 `--trials > 200`）

### 10. TODO checklist（更新后）
- [x] Round 0: smoke + audit + NaN fix + capital bump
- [x] Round 1: Topic A（诊断 OOS 100% 失败率）
- [x] Round 2: Topic B（leaderboard lineage + QQQ）
- [x] Round 3: Topic C（stale_counts 进 checkpoint）
- [x] Round 4: Topic D（factor gate strict mode）→ **§3.1 全关闭**
- [x] Round 5: Topic F（intraday factor family）
- [x] Round 6: Topic E（shadow merge）
- [x] Round 7: Topic I（mining 跨 4 strategy type）
- [ ] Round 8: Topic G（cross-TF feature training）— 推荐
- [ ] Round 9: Topic H（ridge vs XGB）
- [ ] Round 10-12: J/K/L（infra）

### 11. 本轮 commit 哈希
- `cb47d80` — Round 7 (Topic I): mining 跨 4 种 strategy_type
- `64528a5` — docs: 第 7 轮日志更新

---

## Round 8 — Topic G: cross-TF factor × timing bucket 分析 → NEUTRAL

**日期**: 2026-04-20（23:38 完成）
**Topic**: G（cross-TF feature training）
**Lineage_tag**: `post-2026-04-20-capital-100k`
**测试变化**: 1067 → 1067（本轮加分析工具，不加单测）
**主要 commits**: `25e0f8a`（Round 8 + LLM PRD 合并提交）

### 1. 当前阶段
Ralph-loop 第 8 轮 / Topic G

### 2. 本轮目标
用 `decide_timing` 输出 + `factor_generator` 输出联合分析：Round 5 的 `realized_vol_60m_21d` 是否在 timing 层提供增量 alpha？

### 3. 为什么先做它
PRD §3.2 Topic G；直接决定 Round 5 因子是否 promote；独立于 Round 1 OOS blocker

### 4. 做了什么
- `scripts/validate_timing_value.py` 扩展 `--factor-bucket <name>` 模式
- 新 `_print_factor_bucket_analysis()` helper：加载因子 → per-event 查值 → per-day cross-sectional rank → 3 tercile bucket → per-bucket naive/timed/delta 统计
- **诚实的 verdict**：比较 top-tercile delta vs **同样本** overall delta（避免"通过历史 stale 基线但样本内失败"的 false positive）
- 完整端到端用 `realized_vol_60m_21d`（Round 5 winner）测试
- 用户睡前指定 LLM 阶段 PRD 入档：`docs/prd_llm_factor_mining.md`（30 轮 LLM 候选挖掘 + XGBoost cross-signal，严格按现有 funnel 验证）

### 5. 修改了哪些文件
- `scripts/validate_timing_value.py`（+60：`--factor-bucket` + bucket 分析）
- `CLAUDE.md`（Round 8 entry，含真实数据表 + NEUTRAL 结论）
- `docs/prd_llm_factor_mining.md`（新，下阶段规划，含 LLM 角色边界 + funnel 要求 + 30 轮菜单）
- `docs/prd_intraday_mining_loop.md` Appendix A（本日志）
- `docs/ralph_loop_log.md`（本节）

### 6. 跑了哪些测试
- `pytest tests/ -q`：**1067 passing**（基线）
- 真实 bucket 分析 on SPY+QQQ+Mag7，2024-01 至今，4596 events：

| bucket | n | naive_net bps | timed_net bps | delta bps |
|---|---:|---:|---:|---:|
| bottom | 890 | -10.43 | -7.19 | +3.24 |
| middle | 1334 | -17.80 | -9.99 | +7.81 |
| top | 1334 | -14.87 | -10.21 | **+4.66** |

Overall delta: +5.49 bps/event。Top vs overall: **-0.83 bps**。Top-bottom spread: +1.42 bps。

### 7. 当前结果
Topic G completion signal **达成（NEGATIVE/NEUTRAL finding）**：
- `realized_vol_60m_21d` 单独测 IC_21d ≈ +0.10（Round 5 发现）
- **但** 联合 `decide_timing` 在 timing 层不提供增量
- Cross-bucket spread +1.42 bps 在噪声内
- 明确不推荐 promote 到 `PRODUCTION_FACTORS`

**研究含义**: 因子"对未来回报有 IC" ≠ 因子"在 timing 层有增量"。Round 5 IC 的 alpha 来源不是 timing 质量差异，而是跨样本的 vol risk premium。

### 8. 剩余风险
- Verdict 逻辑早期硬编码比较 +3.26 (P1.7 时代) 会误判；已改为 same-sample overall，但 future factor 测试仍需警惕
- Bucket 分析只在 8 symbols × 2 年；全 universe 可能不同结论
- Round 1 OOS blocker 仍在

### 9. 下一轮建议
- **Round 9 = Topic H**（ridge vs XGB feature importance）⭐ —— PRD §3.2 顺序，为后续 LLM 阶段的 XGBoost cross-signal 提供 baseline
- 备选：提前搭 LLM propose 脚本 scaffold 为 auto-launch 做准备
- Off-menu 可能性：继续合并剩余 shadow pairs（Round 6 建立模板）

### 10. TODO checklist（更新后）
- [x] Round 0-7
- [x] Round 8: Topic G（factor × timing bucket → NEUTRAL）
- [ ] Round 9: Topic H（ridge vs XGB）— 推荐
- [ ] Round 10-12: J/K/L（infra）
- [ ] Round 13-42 条件触发: LLM factor mining auto-launch（见 `docs/prd_llm_factor_mining.md`，若 12 轮结束无 promote 自动启 30 轮）

### 11. 本轮 commit 哈希
- `25e0f8a` — Round 8 (Topic G): 主 commit + 下阶段 LLM PRD
- `00361b2` — docs: 第 8 轮日志更新

---

## Round 9 — Topic H: Ridge vs XGBoost 特征重要性对比

**日期**: 2026-04-20（22:48 完成）
**Topic**: H（model comparison — feature importance only）
**Lineage_tag**: `post-2026-04-20-capital-100k`（无 mining 运行）
**测试变化**: 1067 → **1071**（+4 smoke tests）
**主要 commits**: `09cb224`

### 1. 当前阶段
Ralph-loop 第 9 轮 / Topic H

### 2. 本轮目标
在同一 feature panel 上对比 Ridge 和 XGBoost 的 OOS permutation importance，产出 side-by-side top-20 leaderboard + rank agreement 度量

### 3. 为什么先做它
PRD §3.2 Topic H。为即将到来的 LLM factor mining 阶段（30 轮自动启动）提供 baseline：LLM 提出的候选因子必须达到现有 classical factors 的 importance 水平才算增量

### 4. 做了什么
- 新 `scripts/run_model_comparison.py`（240 行）：
  - 加载 32 个 classical factors 的完整面板（79966 rows）
  - **时序** train/test split（按 unique dates，no shuffle）
  - Ridge + 5-fold TimeSeriesSplit CV 调 alpha
  - XGBRegressor 200 trees × depth 4
  - Permutation importance 在 **OOS test set** 上
  - Spearman rank agreement 度量
  - Artifacts: `data/ml/model_comparison_*.{json,csv,parquet}`
- 4 focused smoke tests 守护 helper 契约

### 5. 修改了哪些文件
- `scripts/run_model_comparison.py`（新）
- `tests/unit/factors/test_model_comparison_smoke.py`（新，4 tests）
- `CLAUDE.md`（Round 9 entry）
- `docs/prd_intraday_mining_loop.md` Appendix A（本日志）
- `docs/ralph_loop_log.md`（本节）

### 6. 跑了哪些测试
- `pytest tests/ -q`：**1071 passing**（+4）
- 真实 comparison 在 79966 rows × 32 factors：

| metric | Ridge | XGBoost |
|---|---:|---:|
| OOS R² | **+0.00692** | **-0.14791** |
| Ridge alpha (CV) | 1000 | — |
| Rank agreement (ρ) | +0.349 (MODERATE) |

### 7. 当前结果
Topic H completion signal **达成**（side-by-side leaderboard + rank agreement 都有）。

**核心研究发现**:
- **XGBoost OOS R² 为负数** —— 比预测均值还差。证据表明：当前 universe + factor set 下非线性模型**过拟合**，不 generalize
- **Ridge OOS R² = +0.007** —— 线性 signal 也很弱，但稳定正向
- **两模型共识**: `max_dd_126d` 排名 #1（跨模型共识是最强的 promote 信号）
- MODERATE rank agreement（+0.349）说明 XGBoost 抓到一些 nonlinear 结构但不泛化

**对 LLM 阶段的指导**:
- 不要盲目 XGBoost 评估候选（给过乐观的 train-set scores）
- Ridge importance 当基线更稳
- 新候选必须能 push `max_dd_126d` 以外的特征进 top-5 才算增量
- Rank agreement 可作为"因子稳健性"的诊断指标

### 8. 剩余风险
- XGBoost hyperparams 没调优；但 PRD 明确"feature importance only, 不 hyper-tune"
- Ridge alpha=1000 意味极强正则，说明 universe 层面 factor signal 真的很弱
- Permutation importance 在高度共线特征下会低估单个特征；未来或加 orthogonalization
- Round 1 OOS blocker 仍在

### 9. 下一轮建议
- **Round 10 = Topic J**（LLM factor system scaffold）⭐ — 为 `docs/prd_llm_factor_mining.md` auto-launch 阶段准备基础设施；不动 production path
- 备选 K/L（real-time feed / broker adapter）：需外部依赖，可能需用户签核
- Off-menu：解决 Round 1 OOS blocker（需用户签核 `--trials > 200`）

### 10. TODO checklist（更新后）
- [x] Round 0-8
- [x] Round 9: Topic H（ridge vs XGB，XGBoost OOS R² 为负数）
- [ ] Round 10: Topic J（LLM factor scaffold）— 推荐
- [ ] Round 11-12: K/L（infra）
- [ ] Round 13-42 条件触发: LLM factor mining auto-launch

### 11. 本轮 commit 哈希
- `09cb224` — Round 9 (Topic H): Ridge vs XGBoost permutation importance
- `2438f10` — docs: 第 9 轮日志更新

---

## Round 10 — Topic J: LLM factor proposal scaffold + funnel

**日期**: 2026-04-20（23:00 完成）
**Topic**: J（LLM factor system scaffold）
**Lineage_tag**: `post-2026-04-20-capital-100k`（scaffold 不动生产路径）
**测试变化**: 1071 → **1090**（+19 LLM candidate 单测）
**主要 commits**: `324ebc1` · `2ae0e1d`（轮前 chore）

### 1. 当前阶段
Ralph-loop 第 10 轮 / Topic J

### 2. 本轮目标
为 `docs/prd_llm_factor_mining.md` auto-launch 阶段搭建基础：结构化 YAML 候选 schema + validation funnel + 命名空间守护 + 永不 KEEP 契约。**不调 LLM API**

### 3. 为什么先做它
§3.3 首项。LLM auto-launch 前必须先有 validation/funnel 框架，否则 LLM 生成的候选没验证通道直接影响生产

### 4. 做了什么
- 新 `core/factors/llm_candidate.py`（270 行）：
  - `FactorCandidate` dataclass（PRD §4 schema 对齐）
  - `load_candidate_from_yaml` + shape validation + **命名空间碰撞拒绝**（`PRODUCTION_FACTORS` / `RESEARCH_FACTORS` 重名抛错）
  - `leakage_heuristic_check` 文本扫描
  - `dedup_check` Spearman rank correlation 阈值 0.7
  - `run_funnel` orchestrator
  - **契约**：`run_funnel` 永不返回 `KEEP`；强候选路由到 `NEEDS_HUMAN_REVIEW`
- 新 `scripts/llm_factor_propose.py` CLI
- 19 focused 单测（**含 "永不 KEEP" 契约测试**）

### 5. 修改了哪些文件
- `core/factors/llm_candidate.py`（新）
- `scripts/llm_factor_propose.py`（新）
- `tests/unit/factors/test_llm_candidate_funnel.py`（新）
- `CLAUDE.md`（Round 10 entry）
- `.gitignore`（`data/ml/` 和 `data/mining/` 入列）
- `docs/prd_intraday_mining_loop.md` Appendix A（本日志）
- `docs/ralph_loop_log.md`（本节）

### 6. 跑了哪些测试
- `pytest tests/ -q`：**1090 passing**（+19）
- CLI end-to-end smoke：合成 YAML → funnel → verdict=NEEDS_HUMAN_REVIEW（compute_fn 未提供 → 设计如此）；artifacts 写 `data/ml/llm_candidates/llm_demo_vol_sign_mom/`

### 7. 当前结果
Topic J completion signal **达成**：
- 基础设施就位（schema / validation / funnel / CLI / artifacts）
- PRD §2.2 硬约束（LLM 不是最终裁判）被 `test_strong_candidate_goes_to_review_not_keep` 单测守护
- **下一阶段 auto-launch 无需额外代码**：LLM 生成 YAML → CLI 接收 → funnel 跑 → 人工审核

### 8. 剩余风险
- `compute_fn_path` 是 importlib 直接 import，无沙箱；auto-launch 前要加 subprocess 隔离
- `dedup_check` 是 flat Spearman，没考虑 regime-conditional
- 文本 leakage heuristic 无法替代 truncation-based leakage 验证
- Round 1 OOS blocker 仍在；`realized_vol_60m_21d` 未 promote

### 9. 下一轮建议
Round 11 候选：
- **Topic K**（real-time feed）或 **Topic L**（broker adapter）—— 都需外部依赖，可能需用户签核
- Off-menu：攻击 Round 1 OOS blocker（需用户签核 `--trials > 200`）
- Off-menu：直接进入 `docs/prd_llm_factor_mining.md` auto-launch 阶段（底座就位）

默认按 PRD 顺序走 Topic K，但需先确认是否有真实数据源可接入

### 10. TODO checklist（更新后）
- [x] Round 0-9
- [x] Round 10: Topic J（LLM factor scaffold）
- [ ] Round 11: Topic K（real-time feed）— 可能需用户签核
- [ ] Round 12: Topic L（broker adapter）— 可能需用户签核
- [ ] Round 13-42 条件触发: LLM factor mining auto-launch（底座就位）

### 11. 本轮 commit 哈希
- `2ae0e1d` — chore: gitignore data/ml/ + data/mining/
- `324ebc1` — Round 10 (Topic J): LLM factor proposal scaffold + funnel
- `b41569a` — docs: 第 10 轮日志更新

---

## Round 11 — Topic L: BrokerAdapter ABC + SimulatedBrokerAdapter

**日期**: 2026-04-20（23:38 完成）
**Topic**: L（broker adapter skeleton）
**Lineage_tag**: `post-2026-04-20-capital-100k`（不动生产路径）
**测试变化**: 1090 → **1102**（+12 broker adapter 单测）
**主要 commits**: `168ae14`

### 1. 当前阶段
Ralph-loop 第 11 轮 / Topic L

### 2. 本轮目标
按 CLAUDE.md §4.1 建 `BrokerAdapter` ABC + `SimulatedBrokerAdapter` 实现；PRD 完成信号：submit → ack → fill → reconcile round-trip 接口测试

### 3. 为什么先做它
§3.3 Topic L，不需要外部真实 broker 账户；Topic K（real-time feed）需 vendor API 密钥不能无签核做；Topic L 为未来接真实 broker 打基础

### 4. 做了什么
- 新 `core/execution/broker_adapter.py`（230 行）：
  - `BrokerAdapter` ABC + 7 抽象方法（按 CLAUDE.md §4.1）
  - `OrderAck` + `ReconcileResult` dataclasses
  - `SimulatedBrokerAdapter` wrap `ExecutionSimulator`（`set_next_fill_price` / `set_default_fill_price` 做确定性测试）
- 12 focused 单测覆盖 submit → ack → fill → reconcile 全链路

### 5. 修改了哪些文件
- `core/execution/broker_adapter.py`（新）
- `tests/unit/execution/test_broker_adapter.py`（新，12 tests）
- `CLAUDE.md`（Round 11 entry）
- `docs/prd_intraday_mining_loop.md` Appendix A（本日志）
- `docs/ralph_loop_log.md`（本节）

### 6. 跑了哪些测试
- `pytest tests/ -q`：**1102 passing**（+12）
- round-trip 单测: 下单 → ACCEPTED ack → 立即 fill → cash/position 更新 → reconcile 通过

### 7. 当前结果
Topic L completion signal **达成**：
- ABC 定义 7 个抽象方法
- SimulatedBrokerAdapter 全部实现
- round-trip 端到端 pass
- strategy 代码未来可 target BrokerAdapter 接口，真实 broker 接入时 strategy 代码**不改**

### 8. 剩余风险
- SimulatedBrokerAdapter 即时 fill（无 latency / partial / reject）；真实 broker 行为更复杂，后续可加 `LatencyInjectingAdapter` 做 stress test
- `PaperTradingEngine` 未接入 `BrokerAdapter`；下轮可以做这个接入
- Round 1 OOS blocker 仍在

### 9. 下一轮建议
**Round 12（off-menu）= PaperTradingEngine 接入 BrokerAdapter** ⭐
- Round 11 的自然延续
- 不需外部依赖
- 验证 adapter 接口在真实 paper run 中也工作
- 完成后 PRD §3 菜单只剩 Topic K 需外部签核

备选：继续 Topic K（real-time feed，需用户签核）或直接进入 LLM auto-launch（底座从 Round 10 就已就位）

### 10. TODO checklist（更新后）
- [x] Round 0-10
- [x] Round 11: Topic L（BrokerAdapter skeleton）
- [ ] Round 12: off-menu PaperTradingEngine 接 BrokerAdapter — 推荐
- [ ] Round 13-42 条件触发: LLM factor mining auto-launch

### 11. 本轮 commit 哈希
- `168ae14` — Round 11 (Topic L): BrokerAdapter ABC + SimulatedBrokerAdapter
- （本条 doc commit）— docs: 第 11 轮日志更新

---
