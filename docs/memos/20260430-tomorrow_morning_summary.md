# 给明天的简报 — 2026-04-30 晚 PT (operator 自主推进)

写于 19:30 PT。我下班前是 18:00 PT 左右；之后我（operator）按照你昨晚的指令"按照你的建议走 不需要收工 就一直往下走就可以"自主继续工作。

---

## 1. 一句话总结

Cycle #02 收 0-nominee（**Tier-2 sibling-by-construction**）；**C-1 短视野假设被完全证伪**；发现 production 数据有 16.7% 的股票（13/78）有 heterogeneous split-adjustment 数据腐败问题，harness realized-NAV 在生产数据上不可用；写完了你要求的额外审计 + 一个 P1 修复 + 后续问题 scope memo。

---

## 2. 今晚做了什么（commit 顺序）

| Commit | 内容 | 说明 |
|---|---|---|
| `f24104b` | Cycle #02 closeout memo | Tier-2 sibling-by-construction，C-1 视野被否决；2026 sealed 未消耗；harness 因数据问题不可用 |
| `504274d` | Cycle #02 数据隔离审计 memo | **你重点要求的审计**。12-项审计，0 个 FAIL，2 个 WARN |
| `9ff1ab7` | A1 修复：`purge_labels_at_boundary` wire 入 miner | 审计 WARN #1 修复，2 个新 unit test |
| `747eabf` | Task #49 stage-1 scope: heterogeneous split audit | 13/78 sym 受影响，4 fix options |

---

## 3. Cycle #02 关键数字

- 200 trials → 146 finite → 60 archived
- Top-1: `beta_spy_60d, mom_12_1, volume_ratio_20d`，IC_IR=**1.0592**
- **与 cycle #01 的 top-1 完全相同**（cycle #01 = 0.6562 at 21d 视野）
- Family E/F (intraday/microstructure + short-reversal): **0/60 trial 进 archive**（C-1 假设证伪）
- 与 RCMv1 因子重叠：1/4（共 `beta_spy_60d`）
- 与 Cand-2 因子重叠：0/3
- 与 cycle #01 top-1 因子重叠：3/3 (IDENTICAL)
- Composite 截面 Pearson: vs RCMv1 0.357 / vs Cand-2 0.286 / RCMv1 vs Cand-2 0.387 (基线参考)

**结论**：5d 短视野只是放大了同一组 momentum + beta + volume 信号；构造塌缩 (construction collapse) 在 21d 和 5d 两个视野 + 月度和周度两个 cadence 上都成立。下一个 cycle 应该改 **构造维度**（sector-relative top-N），而不是继续找因子。

---

## 4. 数据隔离审计（你点名要的）

12 项检查，结果：

- ✅ **8 PASS**: train-only filter, validate_no_holdout_leakage, panel_max_date 2024-12-31, split_sha256 stamped, role=core stamped, end_date cap, 因子 lookback cap, eval-script 同样限制 train-only
- ⚠️ **2 WARN**:
  - **WARN #1**: `purge_labels_at_boundary` 在 yaml 配为 true 但 miner 脚本从未调用 → 已修（commit `9ff1ab7`，2 new tests）
  - **WARN #2**: Step 3 eval script 也限制 train-only，所以 per-validation-year 指标永远是空。这对 cycle #02 不成问题（没到 Track A 阶段），但下个有候选的 cycle 之前需要重构
- ❌ **0 FAIL**: 没有数据泄露

完整 memo: `docs/memos/20260430-cycle02_data_isolation_audit.md`

---

## 5. 严重发现：harness realized-NAV 在生产数据上完全不能用

Step 3a 调试 NAV 爆炸（cum_ret = 10^100 量级）时发现 `data/daily/LRCX.parquet` 在 2015-04-15..30 之间相邻日交替出现 $72/$7 价格 —— heterogeneous split-adjustment。BarStore.load(adjusted=True) 修不了，因为 splits.parquet 只能向前级联，不能把混合源拆开。

随后我跑了 universal scan：

- 扫描了 25,344 个 daily parquet
- 在 78-symbol 投资 universe 中：**13/78 受影响 (16.7%)**：AMZN, AVGO, BKNG, CMG, GOOGL, ISRG, LRCX, META, NEE, NVDA, SOXL, TQQQ, TSLA
- 异常天数从 34 (META) 到 1118 (LRCX) 不等
- 这些都是大盘成长股（NVDA / TSLA / META / GOOGL / AMZN / AVGO）—— 不是边角料

**影响**：
- Mining IC objective: 受影响很小（rank IC 对 scale jump 鲁棒）
- Step 1 harness realized NAV: **完全不可用**（10^100 量级爆炸）
- run_paper_candidate cell artifacts: 受 1-year 窗口限制，影响有限
- forward observation: 不受影响（用 yfinance 不同源）
- Track A acceptance NAV gates: **被阻塞** —— 任何未来 Tier-1 候选都过不了 acceptance

**4 个 fix options**（`docs/memos/20260430-heterogeneous_split_audit_scope.md` §3）：

A. 从 canonical 1m → daily 重新聚合 13 个受影响的股票（推荐）
B. Quarantine list（移出 13 sym → 改变 alpha 不可投资）
C. 从外部源（yfinance/Alpaca）重下
D. 维持现状 + IC-only 天花板（项目卡死风险）

**operator 推荐**：A 优先；A 不行就 C；B 是临时；D 不接受。

**需要你的方向性决定**（这是不能 operator 自己拍板的事，因为涉及数据 invariant）。

---

## 6. 当前 task 状态

| ID | 内容 | 状态 |
|---|---|---|
| #40 Step 0 | RCMv1 retro β | ✅ 完成 |
| #41 Step 1 | 每-trial harness | ✅ 完成（unit test 全过；production data 上有 §5 问题） |
| #42 Step 2 | Cycle #02 yaml | ✅ 完成 |
| #43 Step 3 | Cycle #02 mining + 评估 | ✅ 完成 |
| #44 Step 3a | NAV 爆炸 root-cause | ✅ 完成（数据 bug 而不是 harness bug） |
| #45 Step 4 | Cycle #02 closeout | ✅ 完成 |
| #46 Step 5 | 数据隔离审计 | ✅ 完成 |
| #47 Step 6 | Plan + 执行 follow-up | ✅ 完成（A1 修复 + Task #49 scope） |
| #48 Step 7 | 这份 summary | ✅ 完成 |
| #49 | data/daily heterogeneous fix | ⏳ 等你决定 fix option |

---

## 7. 你明天要拍板的决定

**唯一一个**：Task #49 fix option（A/B/C/D）。

如果你说 **A**：我会先验证 1m 数据是否干净，然后 pilot 一个 sym 看效果，预估 2-4 小时全 13 sym 完成。
如果你说 **B**：30 分钟改完，但下次 mining 时 alpha 会变。
如果你说 **C**：1 小时下载 + 1-2 小时 QA。
如果你说 **D**：项目接受 IC-only 天花板，等出现 Tier-1 候选时再处理。

我建议 **A**，因为：
- 1m 数据是 round-3 step3b 的 canonical 源，最有把握
- 13 sym 不动 universe，alpha 可比性最好
- 即使 1m 也混了，C 是干净的退路

---

## 8. 没动的事情

- Cycle #03 设计 (sector-relative top-N): 这是方向性决定，需要你拍板才能写新 PRD + yaml。我没自动开
- A.MV / B.MV / Fleet Step 6+: 按 priority realign 还是 P2 candidate-gated，没碰
- forward observation TD004+: RCMv1 + Cand-2 已经在 4-30 当天 abort 了；今晚没新数据可观察
- M11/M12/M14 等已经收工的项: 没碰
- Codex review log: 没碰（review 流是你触发的）

---

## 9. 重启上下文

明早最快路径：

```bash
# 看今晚的 4 个 commit
git log --oneline 28c7324..HEAD

# 看 cycle #02 的 closeout（最重要）
cat docs/memos/20260430-track_c_cycle_2026-04-30-02_close.md

# 看你点名要的隔离审计
cat docs/memos/20260430-cycle02_data_isolation_audit.md

# 看数据腐败 scope
cat docs/memos/20260430-heterogeneous_split_audit_scope.md

# 看明早需要拍板的 fix option（§3）
```

下班愉快。明天见。

— operator, 2026-04-30 19:30 PT
