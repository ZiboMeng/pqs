# Ralph-Loop 协议 — Supplement PRD(audit 整改 + ranking-baseline OOS 验证)

每一轮严格按本协议推进 `docs/prd/20260522-rerisk-ml-audit-remediation-supplement-prd.md`
的 S1-S7。SoT 文档:
- 该 supplement PRD(整改 package 定义 + gate)。
- master PRD `docs/prd/20260521-rerisk-and-ml-training-audit-prd.md`
  (硬约束 + §10.2 / §9.6 / temporal-split;supplement 继承不可 override)。
- 本协议(含〇用户决策记录)。
- 跨轮日志 `docs/memos/20260522-ralph_loop_supplement_log.md`。
- `CLAUDE.md` 不变量 + 相关 memory(尤其 feedback 类纪律)。

## 〇、用户决策记录(2026-05-22 锁定 — loop 不得自行推翻)

为支持"一口气跑",用户预先裁定:

1. **S4 sector/beta-neutral** — 不强求实现。min-edge-to-trade + turnover
   cap + exit_policy 是 load-bearing → 实现;sector-neutral / beta-neutral
   对当前 long-only cycle06 book 非 load-bearing → config 标
   `enabled: false` + roadmap note 即可(不阻塞,不是停点)。
2. **S7 §〇#5 遗留项** — P4 acceptance gate 措辞 = 「path D net Sharpe
   beats baseline AND MaxDD ≤ 20% 不变量带」(用户 2026-05-22 已定),
   fold 进 master PRD §9.3/§12.3;promoted path-D 配置选择 **defer 到
   S6 OOS 结果**后定(不是停点)。
3. **temporal_split** — S6 用 validation_years(2018/19/21/23/25,holdout,
   validation 用途合法);sealed 2026 永不碰。
4. **machine-checkable gate** — 能 import / 端到端跑通 / artifact 字段齐
   等 machine-checkable gate,loop 自证即继续,无需逐个签核。

## 一、执行顺序(supplement §4)

```
S1 → S2 → S4 → S5 → S3 → S7 → S6
```
S6 最后(消费 S1/S2/S3/S5 的正确性,且 S6 = §12.6 解锁 gate)。
earlier package gate 还红不得跳下一个 —— 但顺序错乱不是停点,loop
自己回到正确 package。

## 二、每轮协议(严格按顺序)

1. **轮前审计**(≤5 min):`git log -1` + `git status` 干净;读
   supplement PRD 当前 package + 本协议 + 日志末轮 + 相关 memory;
   涉及 mining/forward/temporal_split 时 pull 对应 memory 文件。
2. **选本轮一个最小可验证步** + 在报告里发布计划。
3. **实施**:小步、TDD、复用既有模块不重造(§9.6 复用
   dsr/pbo/cpcv;不另写)。
4. **测试 + pipeline**:跑 focused test 或 R3 实跑 artifact;基线
   `pytest tests/unit` 不得跌破 **3923**(跌破立即停下先修)。
5. **轮后自审 4 维**(memory `feedback_audit_per_round_methodology`):
   实跑对比期望数字 + edge case + 跨模块 logic;bug 要 ROOT CAUSE。
6. **主 commit**(11 部分中文报告)+ push。
7. **日志收尾**:追加本轮 11-part 报告到 supplement log,单独小
   doc commit。

## 三、硬规则(违反立即停下问用户)

1. 继承 master PRD 全部硬约束 + CLAUDE.md 不变量(long-only /
   no-margin / no-short / SQQQ blacklist / benchmark 规则 /
   temporal-split / §9.0 rank-or-sign-vote 非 magnitude / §9.6
   DSR-PBO-CPCV 复用不重造 / §4.11 stacking leakage)。
2. **诚实收口**:一个 package 只有其 literal gate criterion 真满足
   才算 CLOSED;红的子项就报红,**禁止重标为 "forward-looking" /
   "follow-up"**(这正是本 supplement 在纠的 audit 病根 —
   supplement §5)。
3. 不假装完成;不发假 promise;非实测的 PLACEHOLDER 值不算做透。
4. websearch 只查方法 / 论文 / 监管,禁查当年市场行情。
5. 每个 ML artifact 必带 master §10.2 全字段(S2 完成后);缺字段
   fail-closed。

## 四、早退 / 停下问用户(命中即停)

写清问题 + 选项 + 建议 → 报告头标 **"STOPPED — NEEDS USER
DECISION"** → 输出 `<promise>RERISK-ML-SUPPLEMENT-DONE</promise>`
停 loop,等用户拍板后重启。只有两类停点:

1. **S6 ranking-baseline 真 OOS 验证结局为 FAIL** —— 即 path-D 在
   validation 分区上**没赢 baseline / MaxDD 破 20% / DSR-PBO 没过**。
   按 `feedback_no_blanket_failure_verdict`:写"这个 attempt 失败 +
   root cause",停下让用户定方向(§12.6 保持锁定)。不自行宣判、
   不反应式 promote。
2. **未预见的 hard blocker**:即将违反"三、硬规则";需要改
   CLAUDE.md 不变量 / master PRD `AUDIT-2026-05-21` 块;`git status`
   不干净修不回;测试基线跌破 3923 修不回。

## 五、完成标志

满足即输出 `<promise>RERISK-ML-SUPPLEMENT-DONE</promise>`:
- S1-S7 全部 supplement §2 hard gate 绿(literal criterion 真满足,
  非重标),且 master §13 auditability 五条满足;或
- 命中"四、早退"(报告头标 STOPPED,非真完成)。

S6 PASS 时,在最终报告里明确:**§12.6 deferred model families 解锁
条件已满足**(供用户决定是否启动 §12.6)。

## 六、每轮交付物

1. ≥1 focused test 或 R3 实跑 artifact。
2. 主 commit(11 部分中文报告)+ 日志 doc commit。
3. 本轮报告已追加到 `20260522-ralph_loop_supplement_log.md`。
4. 本轮 package 进度在报告 ⑩ TODO 可见。

## 七、当前状态(round 0 前)

- supplement PRD 已 link 进 master PRD 顶部 + docs/INDEX。
- 测试基线:`pytest tests/unit` = 3923 passed(跌破立即停修)。
- audit 证据:`data/audit/embargo_leak_quant_20260522T030257Z.json`。
- 下一轮预期:**Round 1 = S1**(embargo 泄漏修)第一步:按交易日
  position 重写 `iter_folds` 的 purge,加 horizon∈{5,10,21} 回归测试。
