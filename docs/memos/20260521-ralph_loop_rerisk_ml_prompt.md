# Ralph-Loop 协议 — Re-Risk + ML Training Framework Hardening

每一轮 Ralph-loop 迭代,在动任何代码之前必须读完:

- `docs/prd/20260521-rerisk-and-ml-training-audit-prd.md` — 本阶段
  PRD(已经过 2026-05-21 dev-lead 审计修订;`AUDIT-2026-05-21` 标记
  的块是硬约束,必须遵守)
- 本文件 — 完整每轮协议
- `docs/memos/20260521-ralph_loop_rerisk_ml_log.md` — 跨轮日志(round 0
  创建;每轮追加,不覆盖)
- `CLAUDE.md` — 系统不变约束
- memory:`feedback_temporal_split_discipline` /
  `feedback_promotion_only_falsification_evidence_gated` /
  `feedback_no_blanket_failure_verdict` / `feedback_self_audit_methodology`
  / `feedback_audit_per_round_methodology`

所有面向用户的文本、计划、审计结论、commit message 一律用**中文**;
代码与代码注释用英文。

---

## 一、执行顺序(PRD §4.2 + §12.4)

```
R0 (re-risk pack, §6)  →  P0 → P1 → P2 → P3 → P4 → P5 → P6  (§12.3)
```

- 一轮只推进**一个** package 的**一个最小可验证步**。package 未到其
  §12.3 gate 全绿不算关闭。
- 任一 earlier package 的 hard gate 还红,后面的 package 不得开工
  (PRD §12.4)。
- R0 是 P0-P6 的前置:R0 未交付 `docs/memos/20260521-rerisk-pack.md`
  + `data/audit/rerisk_pack_20260521.json` 之前不进 P0。

## 二、每轮协议(严格按顺序)

### 第 1 步 — 轮前审计(≤5 分钟)

1. `git log --oneline -15` 读上一轮 commit;`git status` 必须干净,
   不干净停下问用户。
2. 读 `docs/memos/20260521-ralph_loop_rerisk_ml_log.md` 末尾,确定
   下一轮编号 + 当前 package + 上一轮"下一步建议"。
3. `pytest tests/unit -q`(超时 5 分钟)必须绿;不绿先修回来,别碰
   新 package。基线通过数见下方"五、当前状态"。
4. bar-integrity smoke:重 ML 训练 / 回测前先 weekend-row scan +
   cross-symbol date intersection(memory
   `feedback_bar_level_data_integrity_smoke`)。

### 第 2 步 — 选本轮步骤 + 发布计划

按"一、执行顺序"挑当前 package 的下一个最小步。用中文发布:

- **当前阶段** — Round N / Workstream R0 或 Package Px / 第几小步
- **本轮目标** — 一句话
- **为什么是它** — 绑到 PRD §12.4 顺序或轮前审计发现
- **预期产物** — 文件 / 测试 / artifact

### 第 3 步 — 实施

小步。可行就 TDD(RED → GREEN → 跑)。复用现有模块,不重造
(尤其见硬规则 #2 关于三套 rank-model)。新模块只放 PRD §12.1 指定
路径。**严禁一轮塞两个 package。**

### 第 4 步 — 测试 + pipeline(提交前必须)

- 改了模块代码:`pytest` 跑受影响目录 + 一次广回归;load-bearing
  改动(constructor / backtest_engine / 训练管线)跑全量
  `pytest tests/unit`。
- 重 ML 训练 / walk-forward 用后台跑(`Bash run_in_background`)。
- 每个 package 的 §12.3 gate 项逐条 R3 实跑核对,不靠"看起来对"。

### 第 5 步 — 轮后自审(4 维,memory `feedback_audit_per_round_methodology`)

- R1 事实 / R2 逻辑 / R3 真跑对比预期 / R4 边界。
- temporal_split 合规是固定核查项(见硬规则 #4)。
- 本轮若引入新静默失败,同轮修掉才算完。

### 第 6 步 — 主 commit

- `git add` 具体文件,**禁 `-A` 与 `.`**。
- Subject:`Round N (R0|Px): 简述`。
- Body = 11 部分中文报告:① 当前阶段 ② 本轮目标 ③ 为什么先做它
  ④ 做了什么 ⑤ 改了哪些文件 ⑥ 跑了哪些测试+结果 ⑦ 当前结果
  ⑧ 剩余风险 ⑨ 下一轮建议 ⑩ TODO checklist ⑪ commit 哈希汇总。
- 加 `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`。

### 第 7 步 — 日志收尾(一个小 doc commit)

- 向 `docs/memos/20260521-ralph_loop_rerisk_ml_log.md` **追加**本轮
  完整 11 部分中文报告(含时间戳 + commit 哈希 + 测试数变化)。
- commit message:`docs: rerisk-ml ralph-loop 第 N 轮日志`。

## 三、硬规则(违反任一立即停下问用户)

1. 不动 `CLAUDE.md` "Invariant Constraints" 段;long-only / no-margin
   / no-short / SQQQ 黑名单 / MaxDD 15-20% 一概不破。
2. **不造第四套 rank-model**。PRD §1.5:`core/ml/xgb_ranking.py` /
   `core/research/ml/rank_model.py` / `core/ml/xgb_alpha` 已有三套,
   P2 从中选一套 canonical 迁移。
3. **rank-IR 0.30 阈值是 open question,不许自决**(PRD §1.5 + §9.5,
   用户 2026-05-21 决定)。不把 0.30 当硬 gate 卡开发,也不预先改写
   它;只报告实测 IR,阈值留给用户。
4. **temporal_split 纪律硬绑**(PRD §6.5 + `feedback_temporal_split_
   discipline`):任何 backtest / 训练默认只用 train 年
   (2009-2017+2020+2022+2024);validation(2018/19/21/23/25)与
   sealed(2026)是 holdout;跨边界要 explicit 标 diagnostic;
   crisis MaxDD 用 designated stress slice。
5. **§9.6 过拟合控制**:任何跨 fold / 跨 config 的模型选择必须过
   DSR / PBO / CPCV(复用 `core/research/dsr_trial_accounting.py` /
   `mining_pbo.py` / `cpcv.py`,不重造)。
6. **§4.11 stacking leakage 规则**:meta-model 只能用 OOS base 预测
   训练,禁 in-sample。
7. **§9.0 post-fix**:ML 输出严格 sign-vote / rank,禁 continuous
   magnitude as size weight。
8. 每个 ML artifact 必带 PRD §10.2 全字段(含 trial count / DSR /
   PBO);缺字段 fail-closed。
9. bit-identical default mode:接 ML 到既有 backtest / paper 主路径,
   默认 mode 必须 bit-identical(R12/T0 precedent)。
10. websearch 只查方法 / 论文 / 监管,禁查当年市场行情数据。

## 四、早退 / 停下问用户(命中即停,不硬推)

ralph-loop 自身只认 `<promise>` 与 `--max-iterations`。命中下列任一
**directional** 情形:写清问题 + 选项 + 建议 → 在日志与本轮报告里
标 **"STOPPED — NEEDS USER DECISION"** → 输出
`<promise>RERISK-ML-PRD-DONE</promise>` 把 loop 停掉,等用户拍板后
重新 `/ralph-loop` 启动。

- rank-IR 0.30 阈值到了"该不该改 / 改成多少"的取舍点(硬规则 #3)。
- 某 package 的 §12.3 gate 需要用户签核才能宣布关闭。
- 需要新 schema / 新 config section / 新外部依赖 / 新 model family
  超出 PRD §1.3 roadmap。
- R5 fresh mining 启动(PRD §11)—— 永远等用户 explicit-go。
- 即将违反"三、硬规则"任一条。
- 本轮 package 依赖另一个未完成 package → 不换 package,停下报告。
- 出现需要改 CLAUDE.md invariant / PRD `AUDIT-2026-05-21` 块的情况。

## 五、完成标志

满足即输出 `<promise>RERISK-ML-PRD-DONE</promise>` 结束 loop:

- R0 交付完成,且 P0-P6 全部 §12.3 hard gate 绿(PRD §12.4),且
  PRD §13 auditability 五条全满足;或
- 命中"四、早退"任一(此时报告头标 STOPPED,非真完成)。

## 六、每轮交付物

1. 至少一个 focused test 或一个 R3 实跑 artifact。
2. 一个主 commit(11 部分中文报告)+ 一个日志 doc commit。
3. `docs/memos/20260521-ralph_loop_rerisk_ml_log.md` 末尾已追加本轮
   完整中文报告。
4. 本轮 package 进度在报告 ⑩ TODO 里可见。

## 七、当前状态(2026-05-21,round 0 前)

- PRD:`docs/prd/20260521-rerisk-and-ml-training-audit-prd.md`
  (2026-05-21 已审计 + 两轮修订;`AUDIT-2026-05-21` 块为硬约束)。
- 测试基线:`pytest tests/unit` = 3864 passed / 2 skipped(2026-05-21
  执行内核 5 修复后)。通过数跌破 3864 立即停下先修。
- 已 ship 的相关基础:correlation-aware vol-target、parity 测试修复、
  PRD #4 P4.1-P4.5、`core/research/` 下 cpcv/pbo/dsr 模块、
  `core/ml/labeling.py`(uniqueness/triple-barrier 原语)。
- 下一轮预期:**Round 1 = Workstream R0** 第一步(re-risk pack:
  baseline 行,按 §6.5 用 explicit train-only 窗口复现 §2.1 数字)。

---

**核心原则:** 小步,不贪功,不假装完成(做出来 ≠ 做透)。directional
决策一律停下问用户,不瞎猜。
