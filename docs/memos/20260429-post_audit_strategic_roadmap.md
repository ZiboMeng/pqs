---
title: 后审计阶段战略路线图 — 4 track 串行/并行执行计划
date: 2026-04-29
type: strategic_roadmap
status: draft_for_user_review
authors:
  - claude (synthesis)
  - external_auditor_1 (engineering / research-rigor lens)
  - external_auditor_2 (regime-stratified split proposal)
supersedes: none
parent_context:
  - docs/audit/20260428-ralph_audit_cycle_summary_for_codex_review.md
  - docs/prd/20260428-candidate_fleet_allocator_prd.md
  - docs/prd/20260427-forward_evidence_hardening_prd.md
related_open_decisions:
  - gate_recalibration_vs_new_factor_family (Track C 入口决策, 未决)
  - 2025_validation_year_hard_gate (本路线图建议, 待用户确认)
  - bear_regime_validation_strategy (本路线图建议: 2018 移 validation + stress slices, 待用户确认)
---

# 后审计阶段战略路线图

## 0. 这份文档是什么 / 不是什么

**是**：综合两份外部审核员意见 + Claude 自己作为美股量化的判断后，**项目下一阶段工作的排序与依赖图**。它取代"再做一轮 audit / 再加一个 PRD" 的工程惯性，明确从此刻起到第一个 active 生产策略落地之间，必须按什么顺序做什么。

**不是**：
- 任何 track 的具体 PRD（每个 track 单独写 PRD，本文档只给骨架与 acceptance 要点）
- Track C 第一个 fork 的最终决策（gate 重新校准 vs 新因子家族 — 留给 Track A + B 落地后再回答）
- 不可推翻的命令——任一 track 完成时，依据当时事实重新评估下一 track 是否仍然合理

---

## 1. 当前事实（2026-04-29 verified）

| 维度 | 状态 | 来源 |
|---|---|---|
| `config/production_strategy.yaml` | `status: conservative_default`，4 个 validation flag 全 false | 仓库 head 读取 |
| 最新 mining archive (`post-2026-04-23-feat-v1-expanded`) | 65 trials，**0 OOS pass**，best OOS IR = **-0.119**（负值），0 promoted | `data/baseline/latest.json` |
| 最近 research-cycle (`2026-04-26-01`) | 200-trial TPE → top trial **G2.A 集中度 39.5% > 30% 上限失败 → 0 nominee** | `docs/memos/20260426-research-cycle-2026-04-26-01_close.md` |
| Forward observation | RCMv1 + Cand-2 各 **TD003**（首次决策包在 TD010） | `data/research_candidates/*_forward_manifest.json` |
| RCMv1 thin-data weighted | **14.97%**（extreme tier，仍 frozen） | `docs/memos/20260425-m12_review_decision.md` |
| Dividends adjustment | **未实现**，仅 splits 通过 `splits.parquet` apply | `core/data/bar_store.py` + `CLAUDE.md` |
| 2026 数据覆盖 | 81 个交易日 (`2026-01-02` → `2026-04-29`) | `data/daily/*.parquet` |
| 2007-2025 数据覆盖 | 完整 19 年 | 同上 |

---

## 2. 诊断: 真问题不是基础设施，是 alpha 不收敛

工程框架成熟度 70-80%，研究治理框架 60-70%，**但 post-fix codebase 在真实 gate 下没有产出过任何 promoted candidate**。

这不是"再挖一轮就有"——是 65 trial / 0 OOS pass + 200 trial 真 G2.A 失败 已经组成的证据：

- **可能 1**: 当前 7 production + 64 research factor 的因子库在 post-fix 真实数据下已触顶，需要新因子家族（intraday microstructure / event-driven / cross-asset）
- **可能 2**: Gate 阈值（OOS IR ≥ 0.20、G2.A 30% 上限）相对当前 alpha 强度过严，需要诚实降级 + 写入 PRD 的版本化 recalibration

这两条是 Track C 入口的 **fork 决策**——但 **Track A 必须先做完**，否则在污染的 split 上做这个决策本身就不可信。

第二个独立诊断：**RCMv1 + Cand-2 是旧 gate 框架下的提名，新框架（M12 weighted thin-data + G2.A 30% ceiling）下大概率不会再通过**。它们 forward observe 到 TD60 仍有意义（验证 decay），但**不能成为新 gate 标定的样本**。

---

## 3. 4 个 track 排序总览

```
Track A (P0)   ─────►  Track C (P0)  ─────►  Track D (P0)
Temporal       │       真挖 + 2026                Forward TD60 + 第一个 promotion
Split &        │       sealed test
Holdout        │
Discipline     │
PRD + 实现     │
~3-5 天        │
               │
Track B (P1) ──┘ (并行可做，不阻塞 C)
Fleet Allocator step 1-4 (synthetic input)
~3-5 天
```

依赖关系：
- **A 阻塞 C**：没有 alternating-split + holdout 纪律，C 跑出来的 candidate 仍是 pseudo-OOS
- **B 不阻塞任何**：用合成输入开发，C 出 candidate 时即可接入
- **C 阻塞 D**：没有 candidate 通过新 split 就没有 D
- **D 出第一个 active candidate**：项目从研究框架进入"有生产策略"阶段

总工时估算 **2-3 周** 到第一个 active candidate 落地，**前提是 Track C 第一次跑就出 candidate**。如果 C 第一次跑 0 nominee，需要回到 Track C fork 决策（重新校准 gate vs 新因子家族），再加 1-2 周。

---

## 4. Track A — Temporal Split & Holdout Discipline

### 4.1 核心思路（采纳外部审核员 2 提案 + Claude 修订）

外部审核员 2 提议的 alternating-year regime-stratified split **比单 cutoff 严格更好**：每个近年 regime 旁边都有未见 validation 年，强迫策略跨多 regime 鲁棒。基础 split：

| 年份 | 用途 | regime 标签 |
|---|---|---|
| 2007-2008 | crisis stress reference（不参与 alpha 评估） | financial_crisis |
| 2009-2017 | train | 多 regime mix |
| 2018 | **validation**（Claude 修订: 移自 train） | rate_hike_bear |
| 2019 | validation | normal_bull |
| 2020 | train（含 COVID flash slice 借出） | covid_v_recovery |
| 2021 | validation | liquidity_mania |
| 2022 | train（含 rate-hike Q3-Q4 stress slice 借出） | rate_hike_bear_full |
| 2023 | validation | ai_narrow |
| 2024 | train | ai_continuation |
| 2025 | validation（**hard gate**） | current_market |
| 2026 | sealed final test（一次性） | unseen |

### 4.2 Claude 在审核员 2 基础上加的 3 个修订（必须都做）

| 修订 | 问题 | 解决 |
|---|---|---|
| **M1: bear/stress validation** | 审核员 2 原 split 把 2018 + 2020 + 2022 全放 train，**4 个 validation 年（2019/2021/2023/2025）全是 long bull**，没有 bear 验证 | (a) 2018 移到 validation；(b) 从 train 里"借"COVID flash (2020-02-15 → 2020-04-30) + rate-hike (2022-08-15 → 2022-10-15) 作 stress slice，仅评估 MaxDD |
| **M2: 2025 单年硬 gate** | 审核员 2 原方案 "2025 权重最高"是软处理。但 2025 是唯一反映"当前 mega-cap + AI + algo + 期权流"市场结构的 validation 年；通过 2019/2021/2023 但 2025 失败 = 学到过时市场结构 | 2025 excess vs QQQ < 0 或 MaxDD > 上限 → **直接 kill candidate**，不进入加权平均 |
| **M3: factor warmup 跨边界明文规则** | 审核员 2 原 PRD 写 `miner_may_access: ["train"]` 太硬。实际 momentum_252d 在 2019-01-15 评估时必须读 2018 数据——这是因子滚动语义不是 leak | 加 `factor_warmup_may_cross_boundary: true` + `factor_warmup_max_lookback_days: 504` + `validation_signal_dates_must_be_in: ["validation"]` |

### 4.3 YAML schema（**完全配置驱动，不在代码里写任何年份/阈值**）

```yaml
# config/temporal_split.yaml
schema_version: "1.0"
split_name: "alternating_regime_holdout_v1"
created_at: "2026-04-29"
locked_after_first_use: true                    # 一旦用过就 frozen，改 split 必须改 split_name

partition:
  train_years:
    - {range: [2009, 2017]}
    - {year: 2020}
    - {year: 2022}
    - {year: 2024}
  validation_years:
    - {year: 2018, regime: "rate_hike_bear",       weight: 1.0, hard_gate: false}
    - {year: 2019, regime: "normal_bull",          weight: 1.0, hard_gate: false}
    - {year: 2021, regime: "liquidity_mania",      weight: 1.0, hard_gate: false}
    - {year: 2023, regime: "ai_narrow",            weight: 1.0, hard_gate: false}
    - {year: 2025, regime: "current_market",       weight: 2.0, hard_gate: true}
  stress_slices:
    - {name: "covid_flash",   start: "2020-02-15", end: "2020-04-30", source_year: 2020, mode: "stress_check_only"}
    - {name: "rate_hike_2022", start: "2022-08-15", end: "2022-10-15", source_year: 2022, mode: "stress_check_only"}
  reference_years:
    - {range: [2007, 2008], purpose: "crisis_reference_only", excluded_from_alpha: true}
  sealed_test_years:
    - {year: 2026, mode: "single_shot_evaluation", access_after_seen: "candidate_frozen_no_reselection"}

access_rules:
  miner_may_access: ["train"]
  selector_may_access: ["train", "validation"]
  factor_warmup_may_cross_boundary: true
  factor_warmup_max_lookback_days: 504
  validation_signal_dates_must_be_in: ["validation"]
  sealed_test_access: "final_only_single_shot"

acceptance:
  validation_year_pass:
    excess_vs_spy_positive_min: 4               # 5 年 validation 至少 4 年 SPY 正
    excess_vs_qqq_positive_min: 3               # 至少 3 年 QQQ 正
    maxdd_per_year_max: 0.20                    # 每年 MaxDD 上限
  hard_gates:
    - {field: "validation.2025.excess_vs_qqq", op: ">",  value: 0.0,   action: "kill_candidate"}
    - {field: "validation.2025.maxdd",         op: "<=", value: 0.20,  action: "kill_candidate"}
  stress_slice_pass:
    maxdd_per_slice_max: 0.25                   # stress 段稍宽（这些是真危机）
  cost_robustness:
    multiplier_2x_must_remain_positive: true
  concentration:
    top1_max: 0.40
    top3_max: 0.70
    no_leveraged_etf_dependency: true           # 砍掉 TQQQ/SOXL 后策略不能直接死
  beta:
    beta_to_qqq_max: 0.85                       # 不允许变相 QQQ proxy

audit:
  config_sha256_recorded_in_archive: true       # 每个 trial 的 fingerprint 必须含 split yaml hash
  panel_max_date_recorded_per_run: true         # 每次 run 强制记录实际 panel max date
  fail_closed_if_2026_row_in_train_panel: true  # mining 时若发现 2026 row 在 train 直接 abort
  fail_closed_if_validation_year_in_train_panel: true  # 同上，validation 年 leak 直接 abort
```

### 4.4 实现拆解

| Step | 内容 | 估时 |
|---|---|---|
| A.1 | `config/temporal_split.yaml` schema + `core/research/temporal_split.py` loader/validator (pydantic) | 0.5 天 |
| A.2 | Mining panel 构造改造：`core/mining/*` 接受 `split_config` 参数，按 yaml 决定 train year set | 1 天 |
| A.3 | Acceptance pack 改造：按 yaml 评估 5 validation 年 + stress slices + 2025 hard gate；输出 per-year + per-slice 表格 | 1 天 |
| A.4 | Archive metadata 加 `split_sha256` + `panel_max_date` 字段；evaluator 启动时 fail-closed 检查 | 0.5 天 |
| A.5 | Leak detection 测试：尝试在 train panel 注入 2026/validation row → 必须 abort；尝试在 validation 评估时不应包含 train 信号日 → 必须 abort | 1 天 |
| A.6 | PRD `docs/prd/20260429-temporal_split_holdout_discipline_prd.md`：写明上述 schema + 算法 + 一次性使用纪律 + lock_after_first_use 的 commit 留痕规则 | 0.5 天 |
| A.7 | README + CLAUDE.md 同步：标注 RCMv1 + Cand-2 是 "pre-alternating-split candidates" | 0.5 天 |

总计 ~5 天。

### 4.5 验收标准

1. ✅ 任何 mining run 在 train_years 之外的年份的数据 row 出现在 panel 中 → 立刻 abort 并报错
2. ✅ 任何 acceptance pack 评估时，validation 年 signal date 落在 train 或 sealed test 年 → 立刻 abort
3. ✅ Archive metadata 每条 trial fingerprint 都含 `split_sha256` + `panel_max_date` 两个字段
4. ✅ 2025 单年硬 gate 在合成测试中能正确 kill 失败 candidate（即使 2019/2021/2023 全 pass）
5. ✅ Stress slices 在 train 内但能独立计算 MaxDD（借出语义正确）
6. ✅ YAML 改 `split_name` 从 v1 到 v2 时，旧 archive trial 仍可读、但 evaluator 拒绝混用两个 split 的结果
7. ✅ 无任何年份 / 阈值在 Python 代码中硬编码——全部读自 yaml

---

## 5. Track B — Fleet Allocator step 1-4 (synthetic input)

### 5.1 范围

PRD `docs/prd/20260428-candidate_fleet_allocator_prd.md` v1.1 已 codex round-14 PRD-level 批准，但实现未授权。**Track B 实现前 4 步**（不依赖真 candidate）：

| Step | 内容 | 依赖真 candidate |
|---|---|---|
| 1. Fleet manifest schema (sleeve / role / 配置) | pydantic model + yaml loader | ❌ |
| 2. 组合数学 (weight aggregate / correlation budget / overlap) | 用合成双 candidate 测 | ❌ |
| 3. Capital routing + DD throttle | 同上 | ❌ |
| 4. Shadow mode 基础设施 | 10-TD soak 等真 candidate 来再跑 | ❌ |
| 5. Live wiring + 真实 promoted candidate | **不在 Track B 范围**，归 Track D | ✅ |

估时 ~5 天。

### 5.2 明确不做

- 不调 correlation 阈值、overlap 上限、DD throttle 触发点 —— 用 PRD 默认值，等第一次 shadow run 才有数据校准
- 不做 v2/v3 regime-conditional / dynamic risk parity —— 留给后续 PRD
- Step 5（live wiring）不做 —— 在 Track D 出第一个 active candidate 后再做

### 5.3 验收标准

PRD `docs/prd/20260428-candidate_fleet_allocator_prd.md` §6 acceptance #1-#13（除了 #14 / #14b shadow soak 因依赖真 candidate 推迟到 Track D）。

---

## 6. Track C — 真挖（Track A 完成后）

### 6.1 入口决策（fork）

Track A 完成后，必须先回答这个问题再开始挖：

**Q: post-fix codebase 在 alternating-split 真实 gate 下，因子库是否还有 alpha？**

只有两条路：

| Fork | 触发条件 | 动作 |
|---|---|---|
| **F1: gate 重新校准 PRD** | Track A 实现后用现有 64 research factor 跑 100-trial smoke test，证明 OOS IR 阈值 0.20 在当前数据下永远过不了 | 写 PRD 降级 gate（如 OOS IR ≥ 0.10），版本化校准记录 + 必须明文写"这是因为当前因子库 alpha 不足"，**不能伪装成原版** |
| **F2: 新因子家族 PRD** | F1 不成立或 smoke test 显示 IR 0.10 也过不了 | 写 PRD 引入新因子家族（intraday microstructure / event-driven / cross-asset），过 LLM 漏斗 |

**Track A.5 leak detection 测试通过后立即跑 100-trial smoke test 决定走 F1 还是 F2**——这是 Track C 真正开始之前的 gate。

### 6.2 主挖流程（fork 决定后）

| Step | 内容 |
|---|---|
| C.1 | 在 alternating-split 下跑 200-500 trial mining（用 F1 校准后的 gate 或 F2 新因子库） |
| C.2 | Top-N 走 acceptance pack：5 validation years + 2 stress slices + 2025 hard gate + concentration + beta + cost robustness |
| C.3 | 通过 acceptance 的 candidate 走 2026 sealed test **一次性** 评估 |
| C.4 | 2026 通过 → 进入 Track D；2026 失败 → kill，不准回头调 gate 再 retest（这一刻 holdout 被消耗） |

### 6.3 一次性使用纪律（hard rule）

**2026 sealed test 只能跑一次**。如果失败，下一轮必须：
1. 改 `split_name` 从 `alternating_regime_holdout_v1` → v2（例如把 sealed 改成 2027 或调整 validation 年）
2. 旧 archive 全部废弃
3. 重新走完 Track A.4 的 schema validation

**这条纪律不靠代码强制，靠 PRD + commit 留痕 + git review**。任何回头 retest 2026 都视为污染。

---

## 7. Track D — Forward + 第一个 promotion

### 7.1 触发条件

Track C 产出至少 1 个通过 2026 sealed test 的 candidate。

### 7.2 内容

| Step | 内容 |
|---|---|
| D.1 | 新 candidate 用现有 forward runner 启动 forward observation（v2.1.3 + F PRD 已就绪） |
| D.2 | 同时启动 Fleet Allocator step 5：live wiring 第一个 active candidate（10-TD shadow soak） |
| D.3 | Forward TD10 决策包：是否升级到 paper live 资金 |
| D.4 | Forward TD60 决策包：是否升级到 active production status |
| D.5 | `config/production_strategy.yaml` 通过 `scripts/promote_strategy.py` 改 status 到 active |

### 7.3 RCMv1 + Cand-2 同期处理

- **不参与新 split 评估**（旧 gate 框架，污染 2026 holdout）
- **继续 forward observe 到 TD60** 当 "legacy framework decay 验证"
- README + CLAUDE.md 标注 "pre-alternating-split candidates"
- TD60 完成后归档，不进入 fleet

---

## 8. 明确不做的事（避免诱惑清单）

| 诱惑 | 为什么不做 |
|---|---|
| 第 11 轮 audit / 第 N 轮自查 | ralph-audit 10-round + codex 18-round 已经覆盖；继续刷 audit 是工程惯性，不是 alpha 来源 |
| 在 Track A 完成前再跑一轮 mining | 当前 split 是 pseudo-OOS，再多 trial 都不可信 |
| 在第一个 candidate 通过 2026 sealed test 前做 fleet step 5 | 没有 active 输入；在 0 candidate 上调 fleet 参数全是猜 |
| 在 Track C 跑出 0 nominee 后回头降 gate 再跑同一份数据 | 等于消耗 holdout；要降 gate 必须改 `split_name` 走新版本 |
| 实现 dividend total-return 改造（虽然审核员提到） | Track A-D 全部完成后再做；此刻 SPY/QQQ 都不含分红，比较虽然偏低 1.5-2pt 但**对策略选择影响是系统性的、可校准的**，不是项目 P0 卡点 |
| 加 regime-conditional fleet allocator (v2/v3) | PRD 明确 v1 不做；先让 v1 跑稳 |
| 新增 broker / paper / 真实交易约束建模 | 需要先有 active 策略；当前是 0 active，建模没意义 |

---

## 9. 决策检查点

每个 track 完成时回答 3 个问题再决定下一 track：

1. **本 track 的 acceptance criteria 是否全部达成？** （不是"差不多了"）
2. **本 track 揭示了什么之前不知道的事实？** （e.g., Track A 的 100-trial smoke test 是否暗示 F1 还是 F2？）
3. **下一 track 的依赖是否仍成立？** （e.g., Track C 跑出 0 nominee 时，是否还该走 Track D，还是回头 fork F1 vs F2？）

---

## 10. 用户决策点（在 Track A PRD 落地前需要确认）

请在 Track A PRD 草稿写出来之前明确以下选项：

| # | 决策 | Claude 推荐 | 备选 |
|---|---|---|---|
| **D1** | 2018 是否移到 validation？ | **是**（M1 修订） | 否：但需要其他方式补 bear validation gap |
| **D2** | 2025 单年是否硬 gate？ | **是**（M2 修订） | 否：用加权平均，但要明文承认会洗掉 2025 失败 |
| **D3** | Stress slices 借出方案 | **采纳**（COVID flash + rate-hike 2022 Q3-Q4） | 不借出：但 stress 验证缺失 |
| **D4** | Track A 与 Track B 是否并行？ | **并行**（B 不阻塞 C，且独立可测） | 串行：但拖慢首个 active 落地 |
| **D5** | Track A.5 之后必须跑 100-trial smoke test 决定 F1/F2 ? | **是**（避免 Track C 走错路） | 直接进 Track C：但风险高 |
| **D6** | 2026 sealed test 是否真的一次性？ | **是**（hard rule） | 软规则：但 holdout 价值大幅降低 |

---

## 附录: 文档 lineage

- 外部审核员 1（engineering / research-rigor lens）的原始审计意见：用户消息粘贴
- 外部审核员 2（regime-stratified split proposal）的原始提案：用户消息粘贴
- Claude 的核对事实清单 + 量化判断 + M1/M2/M3 修订：本会话历史
- 本路线图整合上述 3 视角
