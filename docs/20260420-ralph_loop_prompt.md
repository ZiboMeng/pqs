# Ralph-Loop 协议 — Intraday Mining 阶段

每一轮 Ralph-loop 迭代，你都必须在动任何代码之前读完：

- `docs/prd_intraday_mining_loop.md` — 本阶段 PRD，含 Topics A-L 菜单 与 第 5 节 exit criteria
- 本文件 `docs/ralph_loop_prompt.md` — 完整 8 步协议
- `CLAUDE.md` — 系统不变约束

所有面向用户的文本、计划陈述、审计结论、commit 消息，一律使用**中文**。代码注释保持英文。

---

## 一、本轮协议（严格按顺序，不得跳步）

### 第 1 步 — 轮前审计（≤5 分钟）

1. `git log --oneline -15` — 读上一轮的 commit subject
2. `git status` 必须干净；不干净就停下问用户
3. 读 `docs/prd_intraday_mining_loop.md` Appendix A round log，识别下一轮编号 + 预期 topic
4. `pytest tests/ -q` 超时 3 分钟；必须绿；不绿就先修，别碰 topic
5. 扫 `data/mining/archive.db`：统计 `score=-999` 行数、不同 `lineage_tag` 的分布、有没有缺 `lineage_tag` 的行。任何异常 → 本轮 topic 变成"修这个"，而不是 §3 菜单里的项

### 第 2 步 — 主题选择

从 PRD 第 3 节菜单（A-L）挑**一个** topic。第 3.1 节的项未全关闭前优先挑那里的。用中文发布本轮计划：

- **当前阶段** — Round N / Topic X
- **本轮目标** — 一句话
- **为什么选它** — 1-2 句，绑到 PRD 第 3 节优先级，或轮前审计发现
- **计划的 lineage_tag** — 方法论改变才 bump，见 PRD 第 2.3 节

### 第 3 步 — 实施

一次只做一个主目标。小步。每个新行为都要 focused test。**严禁把两个 topic 合进一轮**。

### 第 4 步 — Pipeline run（提交前必须跑）

- `pytest tests/ -q` 必须绿
- 涉及 mining：一次 smoke run，用本轮 lineage_tag
  - 默认参数：`--trials 20 --budget 300`
  - Topic A 才允许升到：`--trials 80 --budget 1800`
  - 命令：`python scripts/run_mining.py --trials N --budget T --lineage-tag <tag> --type multi_factor`
- 涉及 timing：跑 `python scripts/validate_timing_value.py --symbols SPY QQQ AAPL NVDA MSFT --start-date 2024-01-01`，抓 verdict 行

### 第 5 步 — 轮后审计（≤5 分钟）

- 扫 smoke / validation log 里的新 warning
- 按本轮 lineage_tag 查 archive：有没有 `score=-999` 行？有没有新的 NaN 崩溃？有没有 QQQ gate 被绕过？
- 如果本轮引入了新的静默失败，本轮不算完 —— 必须同轮修掉

### 第 6 步 — 更新 CLAUDE.md

只写事实，不写计划。若本轮关闭了"约束收口"或"闭环项"清单里的某一项，更新对应的表。

### 第 7 步 — 主 commit

- `git add` 具体文件，**禁用 `-A` 与 `.`**
- Subject 格式：`Round N (Topic X): 简述`
- Body 用 **11 部分中文报告**：
  1. 当前阶段
  2. 本轮目标
  3. 为什么先做它
  4. 做了什么
  5. 修改了哪些文件
  6. 跑了哪些测试
  7. 当前结果
  8. 剩余风险
  9. 下一轮建议
  10. TODO checklist（更新后）
  11. 本轮 commit 哈希汇总
- 加 `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`

### 第 8 步 — 日志收尾（一个小 doc commit）

- 编辑 `docs/prd_intraday_mining_loop.md` Appendix A，加本轮一行：日期 / topic / lineage_tag / 一句话结果
- 编辑 `docs/ralph_loop_log.md`，**追加**（不是覆盖）本轮完整 11 部分中文报告，含时间戳、commit 哈希、测试数量变化
- commit 消息：`docs: 第 N 轮日志更新`

---

## 二、硬规则（违反任一立即停下问用户）

1. 不动 `CLAUDE.md` "Invariant Constraints" 段
2. 不在生产路径引入 `apply_extra_shift=True`
3. 不在 live 路径引入 `fillna(20)` 或常数 VIX 回退
4. 不绕过 `save_eval` / `promote` 直写 archive
5. 不绕过 `passed_qqq_gate` 做 promote
6. 不把 §3 菜单里两个 topic 合到一轮
7. 没有明确用户签核不得用 `--trials > 200`
8. `pytest tests/` 通过数跌破 **1009** 立即停下先修回来
9. 不动 `config/system.yaml::initial_capital_usd`（当前 $100,000 是 active experimental scale，改动会让 lineage 作废）

---

## 三、早退条件

下面任一情况命中就停下问用户，不要硬推：

- 即将违反上述硬规则
- 遇到需要用户设计决策的 blocker（新 schema / 新 config section / 新外部依赖）
- 本轮 topic 依赖另一个未完成的 topic → 换一个 topic

---

## 四、完成标志

满足以下任一即视为本阶段完成，输出 `<promise>RALPHDONE</promise>` 结束 loop：

- PRD 第 5 节 exit criteria 任一命中（策略 promote / 基建 J+K+L 完成 / 用户主动停）
- 全部 12 个 topics（A-L）都已在 PRD Appendix A round log 里关闭

---

## 五、当前状态（2026-04-20）

- 测试通过数：**1009**
- 最新 lineage_tag：**`post-2026-04-20-capital-100k`**（capital 从 10k 升到 100k 后 bump）
- `initial_capital_usd`：**100,000 美元**
- 已完成：Round 0（smoke + audit + NaN blocker fix + capital bump）
- 下一轮预期：**Topic A** —— 全预算 smoke，让 QQQ gate 真正在 Stage 6 触发，使用 100k 真实 scale

---

## 六、交付物（每轮都要有）

1. 至少新增一个 focused test 或者捕获一个 validation 脚本的输出
2. 一个主 commit + 一个 PRD/log doc commit
3. 若本轮关闭了某个列出的收口项，CLAUDE.md 已更新
4. 主 commit body 是 11 部分中文报告
5. `docs/ralph_loop_log.md` 末尾已追加本轮完整中文报告

---

**核心原则：** 小步。不贪功。拿不定主意先停下问用户，不要瞎猜方法论决策。
