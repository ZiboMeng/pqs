# Ralph-Loop 运行日志 — Supplement PRD(audit 整改 + ranking-baseline OOS 验证)

每一轮 ralph-loop 迭代结束时,将本轮完整的中文 11 部分报告**追加**到本
文件末尾。不要覆盖既有条目。

参考:
- `docs/prd/20260522-rerisk-ml-audit-remediation-supplement-prd.md` — supplement PRD
- `docs/prd/20260521-rerisk-and-ml-training-audit-prd.md` — master PRD
- `docs/memos/20260522-ralph_loop_supplement_prompt.md` — 每轮协议
- `CLAUDE.md` — 系统不变约束

执行顺序:S1 → S2 → S4 → S5 → S3 → S7 → S6。
完成 promise:`RERISK-ML-SUPPLEMENT-DONE`。

---

## Round 1 — S1:embargo 改 trading-bar purge(iter_folds 修复)

**时间**: 2026-05-22 · **主 commit**: `167c55b` · **测试基线**: 3923
→ 3929(+6 新)

① **当前阶段** — Round 1 / S1 / embargo 泄漏修。

② **本轮目标** — `iter_folds` purge 从 calendar-day 改 trading-bar +
horizon∈{5,10,21} 零泄漏回归测试。

③ **为什么先做它** — S1 是执行顺序第一;C1 CRITICAL 泄漏污染下游。

④ **做了什么** — `pipeline.py` 新增 `_embargo_train_end`(给
trading_index 时按交易日精确 purge,无则保守 `ceil(×1.6)` calendar
fallback + warn);`iter_folds` 加 `trading_index` 参数。

⑤ **改了哪些文件** — `core/research/ml/pipeline.py` /
`tests/unit/research/ml/test_pipeline.py`(+6 测试)。

⑥ **跑了哪些测试 + 结果** — test_pipeline 31 passed:
zero-overlap[5/10/21] 三 horizon 零泄漏、钉旧 bug、legacy warn、
embargo=0 不变;既有 25 无回归。

⑦ **当前结果** — `iter_folds` trading-bar purge 完成;S1 gate 第一条
(回归证零泄漏)✅。

⑧ **剩余风险** — 4 个 driver 未传 trading_index(走 legacy 保守
fallback);S1 gate 第二条待 driver 接线。

⑨ **下一轮建议** — Round 2 = 4 driver 传 trading_index +
embargo_leak_quant re-run 确认 delta 归零 → 关 S1。

⑩ **TODO** — [x] S1 iter_folds 修+测试 · [ ] S1 driver 接线+收口 ·
[ ] S2/S4/S5/S3/S7/S6。

⑪ **commit** — `167c55b`(主)。

## Round 2 — S1 收口:driver 接线 trading_index(S1 CLOSED)

**时间**: 2026-05-22 · **主 commit**: `0bb581b` · **测试基线**: 3929
（research/ml 162 passed）

① **当前阶段** — Round 2 / S1 / 收口。

② **本轮目标** — 4 driver 接 trading_index,re-run P4 确认 C1 修复
进生产路径。

③ **为什么先做它** — Round 1 修核心;gate 第二条要生产路径实际用上。

④ **做了什么** — `run_walk_forward` 从 `labels.index` 自动派生
trading_index(零 driver 改动覆盖 walk_forward_rank_sign);
portfolio_acceptance + 2 sign driver 显式传 trading_index。

⑤ **改了哪些文件** — `pipeline.py` / `portfolio_acceptance.py` /
`walk_forward_sign_classifier.py` / `hyperparam_search_sign_classifier.py`
/ 新 acceptance json。

⑥ **跑了哪些测试 + 结果** — test_pipeline+xgb 43 passed;research/ml
162 passed 无回归。R3 生产复跑 `portfolio_acceptance.py`:path-D
Sharpe **1.176**(buggy 1.29 消失,= leak-quant correct 值),MaxDD
-19.85%,DSR 0.893,PBO 0.135,verdict PASS。

⑦ **当前结果** — **S1 CLOSED**。gate ①回归证零泄漏 ②生产路径实跑
用 trading-bar purge。

⑧ **剩余风险** — leak-free 真实数:path-D Sharpe 1.18 / MaxDD
**-19.85%**(贴 20% 线)/ DSR 0.89 / PBO 0.135 —— S6 真 OOS 须用
此 leak-free 基线判读。

⑨ **下一轮建议** — Round 3 = S2(R4 §10.2 artifact schema 16 字段
+ fail-closed validator)。

⑩ **TODO** — [x] S1 CLOSED · [ ] S2/S4/S5/S3/S7/S6。

⑪ **commit** — `0bb581b`(主)。

<!-- Round 3 起在此行下方追加 -->
