# Trial 9 历史 walk-forward TD60 先验闭环 — 2026-05-01

**Lineage**: Phase C-PRD-1 / Option A (historical walk-forward prior estimation)
**Author**: operator (claude)
**PRD**: `docs/prd/20260501-two_stage_allocation_architecture_prd.md` §7.1
**Decision memo**: `docs/memos/20260501-diversifier_role_decision.md`
**Companion**: Trial 9 forward init shipped, start_date `2026-05-04`

---

## 1. 目的

Trial 9 (`trial9_diversifier_001`) 已经进入 forward 观察，PRD §7.1 规定
TD60 GREEN/YELLOW/RED triage 在 **2026 年 7 月底**触发。在等待真正的 60
trading days 之前，Option A 用历史 panel 跑一遍 walk-forward，估计**如果
forward 行为延续 2009-2025 历史样本特征，TD60 verdict 大致会落在哪个
分布**。这是先验，不是真 OOS。

## 2. 重要 caveat（不读这条不要看后面数字）

**Trial 9 的 spec 是在 2009-2025 panel 上 mining 出来的（cycle 05 trial 9，
`6c745c601a47`）。本 walk-forward 只是验证它在历史期内的稳定性，不能等
同于真正的样本外验证。所有数字应该被理解为 in-sample upper bound：真实
forward 表现大概率比历史 prior **更差**。**

为什么仍然有意义：
1. 验证 mining 出来的 spec 不是单点过拟合（如果在 130 个滚动窗口里都崩
   就是空头警报，应该 kill candidate before forward）
2. 验证 combo（trial9 + RCMv1 + Cand-2）是否真的改善 portfolio 风险特征
3. 给 TD60 verdict 决策提供 base rate（避免在 forward TD60 RED 时被 panic
   误导成"完全失败"，实际可能历史也只有 30% GREEN）

## 3. 实验设置

| 参数 | 值 | 说明 |
|---|---|---|
| Panel | 2009-01-02 → 2025-12-31 | 不读 2026 sealed window（M5 fail-closed enforced） |
| Window length | 60 trading days | 对应 PRD §7.1 TD60 触发点 |
| Sampling cadence | Monthly start (`MS`) | 每月第一个交易日开窗，避免重叠过密 |
| Candidate spec | trial9_diversifier_001 frozen yaml | spec_hash `8f58d40d...acec5a6` |
| Construction | `cap_aware_cross_asset` | cluster_cap=0.20 / max_single=0.10 / asset_class_caps |
| Universe | 53 stocks + 6 cross-asset ETFs | 与 cycle #04 一致 |
| Anchors | RCMv1 + Cand-2 | 现有 forward observation candidate |
| Total windows attempted | 130 | sampled monthly starts 2009-2025 |
| **Fully valid windows** | **96** | benchmarks + residual corr 都计算成功 |

34 个窗口被丢弃的原因：
- 早期窗口（2009-2014）lookback 不够（trial 9 用 252d momentum 因子）
- 部分窗口 BarStore 因子值缺失导致 NaN 传播

## 4. 核心结果（96 valid windows）

### 4.1 TD60 verdict 分布

| Verdict | Count | Pct |
|---|---|---|
| **GREEN** | 29 | **30.2%** |
| YELLOW | 31 | 32.3% |
| **RED** | 36 | **37.5%** |

**Headline**：30% GREEN / 38% RED。如果 forward TD60 行为完全延续历史
分布，**Trial 9 比 RCMv1/Cand-2 更可能输出 RED 而非 GREEN**。这与
Trial 9 在 2025 年实际有 17.21% MaxDD（D10c soft-warn 触发原因）一致。

### 4.2 Per-regime（post-hoc 分类）

按窗口起始日 SPY 的 200d trend / 252d drawdown / 60d annualized vol 重新
分类（脚本里 manual_regime_labels 函数有 bug 全部输出 UNKNOWN，post-hoc
重做）：

| Regime | n | GREEN | YELLOW | RED |
|---|---|---|---|---|
| BULL | 70 | 34.3% | 35.7% | **30.0%** |
| BEAR | 8 | 12.5% | 12.5% | **75.0%** |
| RISK_ON | 8 | 12.5% | 25.0% | **62.5%** |
| SIDEWAYS | 8 | 25.0% | 37.5% | 37.5% |
| CRISIS | 2 | 50.0% | 0.0% | 50.0% |

**洞察**：
- **BULL 窗口（73% of sample）**：GREEN 34% > RED 30% — Trial 9 在常态
  bull 市场表现最佳，与 cycle 05 的 mining context 一致。
- **BEAR (n=8) 75% RED**：Trial 9 在熊市 60d 滚动窗口里有 75% 概率触发
  RED，主要由 maxdd>10% 触发（详见 §4.4）。这是 D10c soft-warn 18-20%
  MaxDD 接受范围背后的核心担忧。
- **RISK_ON (n=8) 62.5% RED**：高 vol 期 trial 9 的 residual 与 RCMv1/
  Cand-2 飙升，被 residual>0.6 触发 RED（详见 §4.4）。

### 4.3 Combo 证据 (Trial 9 + RCMv1 + Cand-2 vs RCMv1 + Cand-2)

| 改善维度 | Pct of windows |
|---|---|
| Combo 改善 Sharpe | 59.4% |
| **Combo 改善 MaxDD** | **90.6%** |
| Combo 改善 Sharpe **或** MaxDD | **91.7%** |

**当 combo 改善 MaxDD 时，median 改善 = +1.22 pp**（baseline combo
MaxDD 比 trial9-augmented combo MaxDD 深 1.22 pp on median）。

**这是 Option A 最强的证据**：即使 Trial 9 单独 30% RED，加入 portfolio
后在 92% 的窗口里改善了风险特征，证明 D10c 接受 18-20% MaxDD 的判断在
**portfolio 层面**是合理的——单候选承担稍多 DD 换取整体 portfolio 改善。

### 4.4 RED 窗口归因（n=36）

| 触发原因 | Count | Pct of RED |
|---|---|---|
| Trial 9 单独 max_dd > 10% | 14 | 38.9% |
| Residual corr (vs RCMv1 或 Cand-2) > 0.6 | 18 | 50.0% |
| Combo Sharpe AND MaxDD 都不如 baseline | 8 | 22.2% |

**关键发现**：50% 的 RED 不是因为 Trial 9 自己亏，而是因为 Trial 9 与
RCMv1/Cand-2 的 **residual correlation 上升**——也就是 diversifier role
的核心承诺（NAV 不相关）在某些时段失效。这正是 PRD §7.1 RED 触发条件
里 residual > 0.6 的设计意图。

### 4.5 GREEN 窗口特征（n=29）

| 指标 | Median |
|---|---|
| Trial 9 60d Sharpe | 1.78 |
| Trial 9 60d MaxDD | -3.37% |
| Trial 9 60d vs QQQ | **-2.31%** |
| Residual corr vs RCMv1 | 0.171 |
| Residual corr vs Cand-2 | 0.231 |

**值得注意**：即使在 GREEN 窗口里，trial 9 vs QQQ median 是 **-2.31%**
（落后 QQQ）。这与 diversifier role 的 PRD §6.2 acceptance 一致——
diversifier 仅在 OOS walk-forward 平均 vs QQQ 维度被豁免，TD60 verdict
**不要求** vs QQQ 跑赢。如果对 trial 9 设 vs QQQ > 0 硬门槛会把绝大
多数 GREEN 改判 RED。

## 5. 数据质量问题

1. **manual_regime_labels 函数有 bug**：脚本里 `regimes` 字段所有窗口
   全部输出 `UNKNOWN`。已通过 post-hoc Python（SPY 200d trend + 252d
   drawdown + 60d vol）重新分类。**没有影响 verdict 计算（regime 不
   进 verdict 公式）**，但脚本本身的 per-regime 字段不可信。

2. **34/130 窗口被弃用**（NaN benchmark / 缺失 baseline）。这部分主
   要在 2009-2014 早期，trial 9 用了 252d momentum 因子，lookback 不
   够。前期弃用不影响后期窗口，但减小了 sample 总量。

3. **BEAR/RISK_ON/SIDEWAYS/CRISIS sample 都很小（n=2-8）**。BULL 是
   90 多个窗口里的 70 个，其他 regime 推论统计 power 弱。

4. **JSON 中 `trial9_vs_qqq_60d` 字段在 median 计算时出现 +nan%**
   （早期遗留，详 §3 已定位是 NaN window 在 valid 集里被排除后正常）。

## 6. 操作员判断

### 6.1 Trial 9 forward 应该继续观察吗？YES

理由：
1. **Combo 证据非常强（92%）**。Trial 9 单独看 30% GREEN 不够亮眼，
   但在 portfolio 层面几乎在所有窗口都改善 MaxDD。这是 fleet allocator
   关心的根本问题，不是 trial 9 单独 alpha 强度。
2. **30% GREEN base rate 是 in-sample upper bound**。Forward 大概率
   会比这低（mining 偏差），但即使 20% GREEN 仍然意味着 1/5 的 path
   会发出绝佳信号（清除 D10c soft-warn + 过 PRD §6.2 hard gates）。
3. **38% RED base rate 已经预设了**。如果 forward TD60 真的 RED，不要
   panic kill——历史本来就 38%。RED 的判定应该跟 PRD §7.1 RED 条款
   严格对照（不是 RED 就一定 demote，要看 root cause）。
4. **D10c soft-warn 设计是对的**。Trial 9 2025 实际 MaxDD 17.21%，
   位于 18-20% 区间内 soft-warn，TD60 self-clearing 条件 = 60d 滚动
   maxdd ≤ 15%。Option A 显示 GREEN 窗口 median MaxDD -3.37%（远好
   于 15%），所以 forward 期间清除条件 reachable。

### 6.2 Forward 观察 milestone

- TD20（2026-06-01 周左右）：早期 attention check（不做 verdict）
- TD40（2026-07-01 周左右）：中期 attention check
- **TD60（2026-07-30 周左右）**：正式 GREEN/YELLOW/RED 触发
- TD120（2026-10-30 周左右）：full forward soak 完成 → 可考虑入 fleet

### 6.3 Forward 期间需警惕的"早期 RED 信号"

历史 RED 主要来自三类。如果 forward TD20 就出现以下任一，可以早期
attention 但不是 kill：
1. Trial 9 单 60d MaxDD > 10%（历史 38.9% 的 RED 由此触发）
2. Residual corr vs RCMv1 或 Cand-2 飙到 > 0.6（50% 的 RED 由此触发）
3. Combo 在 SPY 大跌时反而 underperform（22.2% 的 RED 由此触发）

### 6.4 不应该启动 Phase C-PRD-2 / 3 / 4

按照 PRD §11 phasing，C-PRD-2（DD throttle）/ C-PRD-3（fleet observe）/
C-PRD-4（shadow→live）都需要 trial 9 TD60 GREEN 触发后才启动。Option A
的结论**不能**用来替代 forward 观察证据——in-sample prior ≠ 真 OOS。

## 7. 已交付物

| 物件 | 路径 |
|---|---|
| 脚本 | `dev/scripts/forward/trial9_historical_walkforward_prior.py` |
| 输出 JSON | `data/ml/research_cycle_eval/trial9_historical_walkforward_prior.json` |
| 闭环 memo | `docs/memos/20260501-trial9_historical_walkforward_prior_close.md`（本文档） |

## 8. 已知 follow-up（不阻塞 forward 观察）

1. 修 `manual_regime_labels` 函数 bug（当前所有窗口标 UNKNOWN）—— P3
   优先级，post-hoc 替代方案已验证。
2. 验证 NaN 窗口的 root cause（factor lookback vs 数据缺失）—— P3
   优先级，弃用窗口集中在 2009-2014 早期不影响后期分析。
3. （C-PRD-3 启动后）扩展 `dev/scripts/forward/run_pair_nav_correlation.py`
   到三体（trial9 + RCMv1 + Cand-2）配套使用。

## 9. 自审 4 层

**R1 事实层**：headline 数字（30% GREEN / 38% RED / 92% combo improvement）
来自 96 valid windows 的 verdict_distribution counter，已重新独立计算
（脚本 JSON + post-hoc Python）确认一致。

**R2 逻辑层**：30% GREEN < 38% RED 的 headline 看起来负面，但 92% combo
improvement 的对照证据正面，二者不矛盾——前者评估 trial 9 单候选的
TD60 verdict，后者评估 trial 9 在 portfolio 层面的边际贡献。Diversifier
role 的设计就是接受单候选 metric 一般、portfolio 层面贡献明显。

**R3 真正执行层**：脚本完整运行成功（130 windows attempted, 96 valid，
artifacts on disk）。已 post-hoc 重新计算所有 headline 数字（独立于
原 JSON 的 summary 字段），结果一致。

**R4 边界层**：caveat §2 已声明 in-sample 性质；§5 已列出 4 个数据
质量问题；§6.4 已明确 Option A 不能替代真 OOS 证据。Phase C-PRD-2/3/4
的启动门槛仍然是 forward TD60 GREEN，本 Option A 不变更这个 gate。

## 10. 状态 / 下一步

- ✅ Phase C-PRD-1 implementation（schema + dispatch + Trial 9 forward
  init + backfill + tests）— 已交付
- ✅ Option A historical walk-forward prior — 本文档
- ⏳ **等待 Trial 9 forward 观察 TD60（~2026-07-30）**
- ⏸️  Phase C-PRD-2/3/4 — 暂不启动，gate=Trial 9 TD60 GREEN
