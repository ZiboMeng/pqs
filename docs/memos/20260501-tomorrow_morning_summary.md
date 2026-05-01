# 给明天的简报 — 2026-05-01 晚 PT (operator 自主推进)

写于 2026-05-01 晚（cycle #03 closeout 完成后）。今天一天我（operator）按你昨晚 + 今天上午的几个 explicit-go 自主推进了 Task #49 完成 + cycle #02 archive + cycle #03 全流程（yaml 预 register + mining + 评估 + closeout）。

---

## 1. 一句话总结

**Task #49 修完了**（canonical 1m → daily rebuild，13/78 → 78/78 universe scan-clean）；**Cycle #02 archive 了**（保留 immutability，同时标注 numerical 不可信）；**Cycle #03 (cap-aware construction) 跑完了，0 nominee**，10/10 Tier 2 sibling-by-NAV。**Headline: NAV correlation floor ≈ 0.85 是 long-only × top-N × 54-stock universe 的结构性属性，cluster_cap 打不破**。下一轮唯一仍有突破口的是 C-4 cross-asset (扩 universe 到 bonds + commodities + cash anchor)；C-2 long-short 违反 no-short invariant 排除；C-1 weekly cap_aware 是次要选项但先验弱。

---

## 2. 今天做了什么（commit 顺序，最早→最新）

| Commit | 内容 |
|---|---|
| `be387d3` | Task #49 close: canonical 1m → daily rebuild。78/78 sym scan-clean。Panel n_obs 3021→1511 (canonical N_min 强制). 4 个 paper cell drift=0 bps. Harness 在 cycle02 top-1 上 cum_ret=1957% / sharpe=1.117 / maxdd=-35.9% (post-rebuild 真值) |
| `2034563` | Archive cycle #02，同时保留 yaml sha256 不动 (external archive marker `..._ARCHIVED.md`)，标注 "ARCHIVED 2026-05-01 — NUMERICAL RESULTS NOT RELIABLE" |
| `e8ee074` | Cycle #03 path-decision memo |
| `d13f3ff` → `3423270` | P1.1-1.3a: sector_map.py + risk_cluster_map.py |
| `7a24e67` | P1.2: partition_for_role (role="miner"/"selector"/"sealed_test_runner") |
| `6ef38ce` | P1.3b: topn_signals_with_caps 在 composite_evaluator 里 + HarnessConfig 扩 cap_aware 模式 + 71 unit tests pass |
| `dab40f2` | Cycle #03 yaml 预 register (sha256 `5df2c305...`) — **后来发现有 typo** |
| `1edc42b` | Cycle #03 yaml typo fix → -02 (sha256 `9fa478f0...`)。Typo: `mining_config.trials` 而不是 canonical `n_trials` → miner CLI silently 用 default 50 trials, 只 archive 了 3 个。-01 lineage **invalid**, 用 -02 重跑全 200 trials |
| `105b923` | Cycle #03-02 closeout (这次 commit) |

总 10 个 commit。

---

## 3. Cycle #03-02 关键数字

- 200 TPE trials → 58 archived
- Top-1: `rs_vs_spy_126d × drawup_from_252d_low × market_vol_ratio`，IC_IR=**1.187**
- **不是 cycle #01/#02 的 sibling factor**（sibling 因子 `beta_spy_60d` / `mom_12_1` 在 top-10 里各只出现 1 次，13 个独立因子在 30 个 top-10 slot 里）
- 但 cap-aware harness 算 NAV：与 RCMv1 / Cand-2 reference NAV 的 pooled raw Pearson **20/20 全 ≥ 0.85**（中位数 0.902，范围 0.852-0.947）
- 去掉 SPY+QQQ 共同 beta 后 residual Pearson 中位数掉到 0.64，只有 1/20 还在 0.70 warn 之上
- Cluster 多样性: avg 12.5 个独立 cluster per rebalance（17 个 cluster 池），max concentration 0.30 (= 月度 rebalance 之间的价格 drift；cap_aware 在 selection 时严格执行 0.20)
- Implicit cash 平均 3% (top_n=10 的 cap-aware 几乎总能填满 10 个名次)
- All 10 trials Tier 2（10/10）

**Headline 推导**:
- 0.902 raw correlation - 0.64 residual ≈ 0.26 来自共同 SPY+QQQ market beta
- 也就是 **~85% 的 NAV correlation 是结构性 long-only top-N market beta share，不是单名/单 cluster 集中度**
- Cap_aware = cluster_cap 0.20 + max_single 0.10 在 SELECTION 层做了正确的事，但 universe 本身（54 只 cap-eligible 股票）是 binding constraint
- Mining 找到了因子多样性（13 unique factors），但 cap-aware 把它们映射回相似的 NAV 邻域

---

## 4. 三轮 Track C 的累积 verdict (cycle #01 + #02 + #03)

| Cycle | Axis | Top-1 spec | Outcome |
|---|---|---|---|
| #01 (2026-04-30-01) | 21d global top-N | β + 12-1 mom + volume | Tier 2 sibling-by-construction-and-factor-overlap |
| #02 (2026-04-30-02) | 5d weekly + global top-N | β + 12-1 mom + volume (IDENTICAL) | Tier 2 sibling, C-1 horizon refuted; **archived** (data corruption) |
| #03 (2026-05-01-02) | 21d monthly + cap-aware (cluster_cap 0.20, max_single 0.10) | rs_vs_spy_126d + drawup + market_vol_ratio | Tier 2 sibling-by-NAV (universe-bound) |

**收敛中的认识**：
- Long-only × top-N × 78-stock universe 的 NAV correlation floor ≈ 0.85
- 因子层面、construction 层面（cap_aware）、horizon 层面（5d/21d）、cadence 层面（weekly/monthly）都试过了，都不能突破这个 floor
- 不是因子选错，不是 mining 不行，不是 sibling 因子的偏好 —— 是 **universe 本身**

---

## 5. 下一轮（cycle #04）授权 + 设计建议

**Operator 推荐**: C-4 cross-asset

**Universe 扩展**:
- Stocks: 54 个 cap-eligible 股票（保持）
- Bonds: TLT / IEF / SHY (long/intermediate/short duration)
- Commodities: GLD / USO
- Cash anchor: BIL 或 SHV

**Risk-cluster map 扩展** (`core/research/risk_cluster_map.py`):
- 加 `bond_long_duration` / `bond_short_duration` / `commodity_metals` / `commodity_energy` / `cash_anchor` 5 个新 cluster
- Total → 22 cluster
- 让 cap_aware 在跨资产层面分配，cluster_cap=0.20 仍然 binding

**Construction**: cap-aware 不变（cluster_cap=0.20, max_single=0.10, monthly, top_n=10）。在更宽 universe 上，cluster_cap 自动驱动 ≥ 5 个 cluster 贡献 → 必有跨资产分配 → 直接攻击 cycle #03 找到的 universe-bound NAV floor

**Mining**: 200 TPE / `n_trials=200` (canonical 字段名！双重检查)

**Anti-sibling**: 同 0.85 raw / 0.70 residual

**Pre-registration discipline 仍是 hard rule**: yaml 提交带 sha256 写到 commit message，mining 才能开。任何 yaml 改字段 → 起新 lineage tag

---

## 6. 当前 task 状态

| ID | 内容 | 状态 |
|---|---|---|
| #49 | data/daily heterogeneous fix | ✅ 完成 (Task #49 close, commit `be387d3`) |
| #50 | Cycle #03: archive #02 + cap-aware path | ✅ 完成 (commit `2034563` + `e8ee074`) |
| #51 | P1: sector_map + partition_for_role + risk_cluster_map + cap_aware selector | ✅ 完成 (commits `d13f3ff`/`7a24e67`/`3423270`/`6ef38ce`) |
| #52 | Cycle #03 yaml + mining + eval + closeout | ✅ 完成 (commits `dab40f2`/`1edc42b`/`105b923`) |

无 pending task。Research-mining workstream auto re-frozen（per `docs/memos/20260426-research_layer_partial_unfreeze.md`）。

---

## 7. 你明天要拍板的决定

**唯一一个**：Cycle #04 cross-asset axis 授权？

如果你说 **go**：我会按 §5 设计预 register cycle #04 yaml（risk_cluster_map 扩 22 cluster + universe 加 bonds/commodities/cash），sha256 写到 commit message，再开 200-trial mining。预估 mining 1.5-2h（更宽 panel） + eval 2-3 min + closeout 半小时。

如果你说 **wait** / **change axis**：lineage 不动，等你方向。

如果你说 **C-1 weekly cap_aware** 而不是 C-4：可以做，但先验弱（cycle #02 已经在 IC level 否决了 weekly cadence；和 cap_aware 配也不大可能突破 universe floor）。

如果你说 **fleet step 6** / **Track A acceptance β-stamp**：那就是 priority realign §priority 转向 P1 那条路，Track C 这条线先停。

---

## 8. 没动的事情（per priority realign 2026-04-30）

- A.MV / B.MV / Fleet Step 6+: 按 priority realign 还是 P2 candidate-gated。Cycle #03 没产生 candidate，所以这些仍然 paused
- Track A acceptance β-stamp 最小扩展: P1 待办，但今天我推 cycle #03 优先；可以下一天做
- forward observation TD004+: 没新数据信号，我没自动 observe（你的 ritual 是"数据来了"再自动跑）
- M11/M12/M14 等已收工的项: 没碰
- Codex review log: 没碰（review 流是你触发的）
- README sync: cycle #03 的 risk_cluster_map / partition_for_role / cap_aware harness 是新增基础设施，README §1 章节可能需要 sync。我没碰，等你确认 cycle #04 方向再一起 sync 不会浪费

---

## 9. 重启上下文

```bash
# 看今天的 10 个 commit
git log --since="2026-04-30 23:30" --oneline

# 看 cycle #03 closeout（最重要）
cat docs/memos/20260501-track_c_cycle_2026-05-01-02_close.md

# 看 cycle #03 path decision
cat docs/memos/20260501-cycle03_path_decision.md

# 看 yaml 是不是真的 immutable + 没读 sealed
sha256sum data/research_candidates/track-c-cycle-2026-05-01-02_promotion_criteria.yaml
# 应该 = 9fa478f0ffad33dc2d40eff8ec63b2e86799404b06695b2626390970f169ff23

# 看 eval JSON（gitignored 但本地有）
ls data/ml/cycle03_evaluation/track-c-cycle-2026-05-01-02/
```

---

## 10. R1+R2+R3+R4 self-audit (本份 summary 自身)

- **R1**: 10 个 commit 用 `git log --since="2026-04-30 23:30" --oneline` 直接验证
- **R2**: §4 verdict-累积逻辑：cycle #01 (axis: factor pool/horizon at 21d global top-N) + cycle #02 (axis: weekly cadence) + cycle #03 (axis: construction layer caps) 三个独立维度全失败 → 共同变量是 universe 本身。逻辑闭环
- **R3**: §3 数字 Re-grep 自 `data/ml/cycle03_evaluation/.../evaluation_summary.json` ground truth；不是从中间 console 输出
- **R4**: §5 cycle #04 设计建议 — 建议层面，不绕过 user-authorization 边界，仍要等 user explicit-go 才动；不假定授权

---

下班愉快。明天见。

— operator, 2026-05-01 晚 PT
