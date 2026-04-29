---
title: 后审计阶段战略路线图 — 4 track 串行/并行执行计划
date: 2026-04-29
version: v3
type: strategic_roadmap
status: track_a_prd_codex_round_20_APPROVED — implementation begins
authors:
  - claude (synthesis)
  - external_auditor_1 (engineering / research-rigor lens)
  - external_auditor_2 (regime-stratified split proposal)
  - codex_round_19 (review and additions)
supersedes: none
parent_context:
  - docs/audit/20260428-ralph_audit_cycle_summary_for_codex_review.md
  - docs/audit/20260429-codex_round_19_strategic_redirection_review.md
  - docs/prd/20260428-candidate_fleet_allocator_prd.md
  - docs/prd/20260427-forward_evidence_hardening_prd.md
related_open_decisions:
  - gate_recalibration_vs_new_factor_family (Track C 入口决策, F1/F2 fork criteria 一页写进 Track A PRD)
  - role_specific_gate_yaml_lock_design (本路线图建议, 见 §4.2 M6)
v1_to_v2_changelog: |
  v2 (2026-04-29 同日) 在 v1 基础上吸收 codex round 19 review +
  外部审核员 follow-up + Claude 三处加约束 + 两处新增, 共 12 项
  Track A PRD 必须项, 落 §4.2 + §11. v2 用户已 explicit-go (1+2+3
  并行启动: 路线图更新 / 写 round 19 reply / 开写 Track A PRD 草稿)
v2_to_v3_changelog: |
  v3 (2026-04-29 同日) 标记 Track A PRD codex round 20 APPROVED;
  PRD v1.0 → v1.1 吸收 codex 4 项必须修正 (B1-B4) + 3 项答复驱动
  schema 改动 (Q1 F1 floor / Q3 role-lock C5 / Q4 regime tiered).
  R20 没有 reject 任何项. 实施 authorized; Track A Step A.1 开始.
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

### 4.2 修订列表 v2 — 9 个 PRD 必须项

v1 提了 M1/M2/M3。v2 吸收 codex round 19 + 审核员 follow-up + Claude 加约束/新增，**共 9 个修订项 (M1-M9)**，全部进 Track A PRD：

#### v1 原始 3 个 split-structure 修订（保留）

| 修订 | 问题 | 解决 |
|---|---|---|
| **M1: bear/stress validation** | 审核员 2 原 split 把 2018 + 2020 + 2022 全放 train，**4 个 validation 年（2019/2021/2023/2025）全是 long bull**，没有 bear 验证 | (a) 2018 移到 validation；(b) 从 train 里"借"COVID flash (2020-02-15 → 2020-04-30) + rate-hike (2022-08-15 → 2022-10-15) 作 stress slice，**仅评估 MaxDD sanity check，不参与 alpha selection、不算独立 validation 年** |
| **M2: 2025 单年硬 gate（仅 first active/core role）** | 审核员 2 原方案 "2025 权重最高"是软处理。2025 是唯一反映"当前 mega-cap + AI + algo + 期权流"市场结构的 validation 年；通过 2019/2021/2023 但 2025 失败 = 学到过时市场结构 | 2025 excess vs QQQ < 0 或 MaxDD > 上限 → **直接 kill candidate**，不进入加权平均。**仅适用 first active/core role**；diversifier role 见 M6 |
| **M3: factor warmup 跨边界明文规则** | 审核员 2 原 PRD 写 `miner_may_access: ["train"]` 太硬。实际 momentum_252d 在 2019-01-15 评估时必须读 2018 数据——这是因子滚动语义不是 leak | 加 `factor_warmup_may_cross_boundary: true` + `factor_warmup_max_lookback_days: 504` + `validation_signal_dates_must_be_in: ["validation"]` |

#### v2 新增 6 个 discipline 修订（codex R19 + 审核员 + Claude）

| 修订 | 来源 | 内容 |
|---|---|---|
| **M4: Purged label / forward-return 边界**（codex + 审核员共识） | codex R19 #1, 审核员 #1 | Feature warmup 可向后 cross（M3）；但 **label / forward return / holding PnL / acceptance 评估窗口** 不可跨 train→validation 或 validation→sealed 边界。例：validation 第一天的 21d forward return 如果落进 train 或 sealed 区间，必须 purge 或 drop。这是 financial ML 标准 purging+embargo |
| **M5: Sealed-test machine-auditable ledger**（codex + 审核员共识） | codex R19 #2, 审核员 #2 | 2026 sealed test 单次使用纪律不能只靠 PRD + commit trail。必须有 **machine-auditable ledger** 记录每次 sealed evaluation: `split_name` / `split_sha256` / `candidate_spec_sha256` / `git_sha` / `panel_max_date` / `evaluation_timestamp_utc` / `result_metrics_sha256`。Fail-closed 防止同一 candidate/spec 反复评 2026 调参 |
| **M6: Role-specific gate 必须 yaml 锁 + 补偿约束**（Claude 加约束于 codex/审核员） | codex R19 #3 + 审核员 #3, **Claude 加约束** | Codex/审核员说 "first core hard gate; future diversifier role-specific" 方向对，但裸写进 PRD 是后路。Claude 加 4 条约束: (a) Role 必须在 mining 启动**前**在 yaml 里声明，pre-mining 锁定；(b) Role 不能 candidate 出来后再分配；(c) Role-specific 弱化 gate 必须有**补偿约束**（diversifier 必须满足 vs core orthogonality / overlap 阈值才能享受弱 2025 gate）；(d) 修改 role gate 必须改 `split_name` |
| **M7: F1/F2 fork criteria 用百分位阈值，不用"default bias"**（Claude 修正 codex） | codex R19 F1/F2 答复, **Claude 修正** | Codex 说 "default bias should be F2 unless...". Claude 反对裸 default bias——F2 (新因子家族) 成本远高于 F1 (gate 校准)，F1 风险是"为通过而降 gate"。**正确做法**: PRD 一页 fork criteria 用 100-trial smoke 后的 IR 分布百分位定 fork: `if IR_p90 > 0.15 AND ≥20% trials > 0.10 → F1`; `elif IR_p90 < 0.05 AND IR_p50 < -0.05 → F2`; else 升级 user 决定。Pre-smoke 写死，避免 anchoring |
| **M8: Dividend pass margin 量化**（Claude 量化 codex） | codex R19 #6, **Claude 量化** | Codex 说 Track D promotion 需要"dividend-aware evidence OR pass margin large enough"。"large enough" 太软。**Claude 量化**: SPY div yield ~1.3% / QQQ ~0.6% / 差额 ~0.7%/yr → 5y 累积差异 ~3.5-4%。**rule**: 5-year 累积 excess vs QQQ > 4% 才能不做 dividend 校正即声明通过；< 4% 必须先加 dividend 再 re-evaluate。Track A 不阻塞，Track D 强制 |
| **M9: Regime tag 双标 (manual + auto-classifier)**（Claude 新增） | **Claude 新增** | M1/M2 都依赖 regime tag (2018=rate_hike_bear, 2025=current_market 等)，但这些是主观 tag。项目已有 `core/diagnostics/regime_detector.py`。Track A PRD 写 manual tag 同时，必须**运行 regime_detector 对每年分类**，把 `manual_tag` + `auto_classifier_tag` 都写进 yaml；不一致时 PRD 必须说明为什么用 manual。这条让"alternating split 强迫多 regime"论点经得起未来质询 |

### 4.3 YAML schema（**完全配置驱动，不在代码里写任何年份/阈值**）

**v2 schema 新增字段**（合并 M4-M9）:
- `partition.validation_years[].manual_regime_tag` + `auto_classifier_tag` (M9)
- `partition.validation_years[].label_horizon_days_max` 强制 purged 边界 (M4)
- `roles[]` 顶层节点定义 core / diversifier / hedge gate (M6)
- `roles[].eligibility_constraint[]` 补偿约束 (M6)
- `acceptance.purge_rules` (M4)
- `acceptance.dividend_safety` (M8 — Track A 收 schema, Track D 强制)
- `audit.sealed_eval_ledger.*` (M5)
- `acceptance.fork_criteria.*` 百分位阈值 (M7)

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
  # M5: machine-auditable sealed-eval ledger
  sealed_eval_ledger:
    enabled: true
    path: "data/research_candidates/sealed_eval_ledger.parquet"
    fields:
      - split_name
      - split_sha256
      - candidate_spec_sha256
      - git_sha
      - panel_max_date
      - evaluation_timestamp_utc
      - result_metrics_sha256
    fail_closed_on_repeat:
      key: ["split_name", "candidate_spec_sha256"]   # 同 split + 同 spec 复评 → abort
      action: "abort_with_message"
  # M6: role 在 mining 启动前必须锁
  fail_closed_if_role_unspecified_at_mining_start: true
  # M9: regime tag 双标必须填齐
  fail_closed_if_regime_tag_missing_either_source: true
```

#### v2 新增 schema 节: `roles` + `purge_rules` + `dividend_safety` + `fork_criteria`

```yaml
# M6: Role 必须 mining 启动前定义；不准 candidate 出来后再分配
roles:
  core:
    description: "First active/leading allocator; full gate"
    eligibility_constraint: []                     # 任何 candidate 都可申请 core role
    validation_gates:
      - {field: "validation.2025.excess_vs_qqq", op: ">", value: 0.0,  action: "kill_candidate"}
      - {field: "validation.2025.maxdd",         op: "<=", value: 0.20, action: "kill_candidate"}
  diversifier:
    description: "Role-locked at mining start; not a fallback for failed core"
    eligibility_constraint:
      - {field: "vs_existing_core_correlation",   op: "<",  value: 0.40}
      - {field: "vs_existing_core_overlap",       op: "<",  value: 0.30}
    validation_gates:
      # 弱化 2025 gate 但 MaxDD 反而更严
      - {field: "validation.2025.excess_vs_qqq", op: ">", value: -0.05, action: "kill_candidate"}
      - {field: "validation.2025.maxdd",         op: "<=", value: 0.18, action: "kill_candidate"}

# M4: Purged label / forward-return 边界规则
acceptance:
  purge_rules:
    label_horizon_days_max: 21                     # 任何 forward-return label 最长 21d
    purge_at_split_boundary: true                  # 跨边界 label 必须 drop
    embargo_days: 0                                # v1 不加 embargo；记录此选项以便后续加
  # M8: Dividend pass margin (Track A 仅 schema, Track D 强制)
  dividend_safety:
    enforce_at: "track_d_promotion"                # Track A 不阻塞
    required_excess_margin_5yr: 0.04               # 5y 累积 excess vs QQQ > 4% 才能豁免分红校正
    fallback: "must_add_dividend_correction_before_promotion"
  # M7: F1/F2 fork criteria (百分位阈值, pre-smoke 写死)
  fork_criteria:
    smoke_trial_count: 100
    rules:
      - if:
          all:
            - {metric: "smoke.IR_p90", op: ">", value: 0.15}
            - {metric: "smoke.fraction_above_0.10", op: ">=", value: 0.20}
        then: "F1_gate_recalibration"
        new_threshold: "smoke.IR_p75"              # 新 OOS IR 阈值 = smoke 75 分位
        explicit_rationale_required: true
      - if:
          all:
            - {metric: "smoke.IR_p90", op: "<", value: 0.05}
            - {metric: "smoke.IR_p50", op: "<", value: -0.05}
        then: "F2_new_factor_family"
      - else: "escalate_to_user_explicit_decision"
```

#### v2 新增 schema 节: `validation_years` 双 regime tag (M9)

```yaml
# 替换 v1 partition.validation_years 节, 每个年份必须双 tag:
partition:
  validation_years:
    - year: 2018
      manual_regime_tag: "rate_hike_bear"
      auto_classifier_tag: null                    # PRD 实现时跑 regime_detector 填
      weight: 1.0
      hard_gate: false                             # M6 lookup: only core 享受 hard_gate
    # ... 其他 validation 年同样双 tag
```

### 4.4 实现拆解

| Step | 内容 | 估时 |
|---|---|---|
| A.1 | `config/temporal_split.yaml` schema + `core/research/temporal_split.py` loader/validator (pydantic) | 0.5 天 |
| A.2 | Mining panel 构造改造：`core/mining/*` 接受 `split_config` 参数，按 yaml 决定 train year set | 1 天 |
| A.3 | Acceptance pack 改造：按 yaml 评估 5 validation 年 + stress slices + 2025 hard gate；输出 per-year + per-slice 表格 | 1 天 |
| A.4 | Archive metadata 加 `split_sha256` + `panel_max_date` 字段；evaluator 启动时 fail-closed 检查 | 0.5 天 |
| A.5 | Leak detection 测试：尝试在 train panel 注入 2026/validation row → 必须 abort；尝试在 validation 评估时不应包含 train 信号日 → 必须 abort | 1 天 |
| A.6 | PRD `docs/prd/20260429-temporal_split_holdout_discipline_prd.md`：写明 9 修订项 schema + 算法 + 一次性使用纪律 + lock_after_first_use 的 commit 留痕规则 + M5 ledger 设计 + M7 fork criteria 一页 | 1 天 |
| A.7 | M5 sealed-eval ledger 实现: `core/research/sealed_ledger.py` + parquet 存储 + fail-closed-on-repeat 检查 | 0.5 天 |
| A.8 | M9 regime auto-classifier 集成: 调用 `core/diagnostics/regime_detector.py` 对 train + validation 每年分类，写入 yaml `auto_classifier_tag` | 0.5 天 |
| A.9 | README + CLAUDE.md 同步：标注 RCMv1 + Cand-2 是 "pre-alternating-split candidates" + Track A v2 PRD pointer | 0.5 天 |

总计 ~7 天 (v1 5 天 + v2 新增 ~2 天 for M5/M9/扩展 PRD)。

### 4.5 验收标准 (v2)

#### v1 原始 7 条（保留）
1. ✅ 任何 mining run 在 train_years 之外的年份的数据 row 出现在 panel 中 → 立刻 abort 并报错
2. ✅ 任何 acceptance pack 评估时，validation 年 signal date 落在 train 或 sealed test 年 → 立刻 abort
3. ✅ Archive metadata 每条 trial fingerprint 都含 `split_sha256` + `panel_max_date` 两个字段
4. ✅ 2025 单年硬 gate 在合成测试中能正确 kill 失败 candidate（即使 2019/2021/2023 全 pass）
5. ✅ Stress slices 在 train 内但能独立计算 MaxDD（借出语义正确）
6. ✅ YAML 改 `split_name` 从 v1 到 v2 时，旧 archive trial 仍可读、但 evaluator 拒绝混用两个 split 的结果
7. ✅ 无任何年份 / 阈值在 Python 代码中硬编码——全部读自 yaml

#### v2 新增 5 条（M4-M9 验证）
8. ✅ Forward return label 跨 train→validation 边界自动 purge: 测试用 21d label 在 2018-12-15（train 末）尝试评估 → 必须 drop（M4）
9. ✅ Sealed-eval ledger 同 split + 同 spec 复评 → fail-closed abort（M5）
10. ✅ Role 在 mining 启动时 yaml 未声明 → mining 拒绝启动（M6）
11. ✅ F1/F2 fork criteria 在合成 smoke (3 个测试分布) 下能正确分类: 高 IR 分布 → F1; 全负 → F2; 中间 → escalate（M7）
12. ✅ Regime auto-classifier 对每个 validation 年都填了 `auto_classifier_tag`（不能 null）；与 manual 不一致时 PRD 必须有 explicit rationale（M9）

#### Track D 验收（M8 dividend，记录但不在 Track A 强制）
- ✅ Track D promotion 时检查 5y excess vs QQQ ≥ 4%；< 4% 必须先加 dividend 校正

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

### 6.1 入口决策（fork）— v2 用百分位阈值，pre-smoke 锁死

Track A 完成后，必须先回答：**post-fix codebase 在 alternating-split 真实 gate 下，因子库是否还有 alpha？**

**v2 改动 (M7)**：fork 决策**不靠 default bias**，靠 100-trial smoke 的 IR 分布百分位。具体规则**写进 Track A PRD 一页 fork-criteria memo，pre-smoke 锁死**:

| Fork | 触发条件 | 动作 |
|---|---|---|
| **F1: gate 重新校准 PRD** | `IR_p90 > 0.15 AND ≥ 20% trials > 0.10` | 写 PRD 降级 gate；新阈值 = `smoke.IR_p75`；明文写 explicit rationale "降 gate 因 smoke 显示 alpha 在但 X% trial 通过" |
| **F2: 新因子家族 PRD** | `IR_p90 < 0.05 AND IR_p50 < -0.05` | 写 PRD 引入新因子家族（intraday microstructure / event-driven / cross-asset），过 LLM 漏斗 |
| **Escalate** | 中间区间（既非 F1 触发，也非 F2 触发） | 写 decision memo 解释 ambiguity + 用户 explicit decision |

**注意**：codex round 19 给的"default bias to F2 unless smoke shows broad near-threshold"是 narrative-bias；Claude 修正为 quantitative thresholds 写进 schema (见 §4.3 `acceptance.fork_criteria`)，避免 anchoring。

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
| D.5 | **M8 dividend safety check**: 5y 累积 excess vs QQQ ≥ 4% → pass; < 4% → 必须先加 dividend 校正 re-evaluate |
| D.6 | `config/production_strategy.yaml` 通过 `scripts/promote_strategy.py` 改 status 到 active |
| D.7 | **forward decay detection 子模块**（v2 新增 — 从 §10 D7 来）: forward TD60 期间 per-TD alpha-decay gate（例: 3 个月滚动 cum_ret < 0 自动 kill），不能只检查数据完整性 |

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

## 10. 用户决策点（v2 — 已 explicit-go 1+2+3 启动）

v1 的 D1-D6 用户已 explicit-go (2026-04-29 同日)。v2 新增 D7-D8：

| # | 决策 | 状态 | 备注 |
|---|---|---|---|
| ~~D1~~ | 2018 是否移到 validation？ | ✅ APPROVED (v1) | 进 Track A PRD M1 |
| ~~D2~~ | 2025 单年是否硬 gate？ | ✅ APPROVED + 加 M6 role lock | 仅对 first active/core role |
| ~~D3~~ | Stress slices 借出方案 | ✅ APPROVED + M1 加约束 (仅 MaxDD sanity) | 不参与 alpha selection |
| ~~D4~~ | Track A 与 Track B 是否并行？ | ✅ APPROVED | B 不阻塞，但不抢 A |
| ~~D5~~ | Track A.5 之后跑 100-trial smoke 决定 F1/F2？ | ✅ APPROVED + M7 量化 | Pre-smoke 写百分位阈值 |
| ~~D6~~ | 2026 sealed test 一次性？ | ✅ APPROVED + M5 ledger 强制 | 不只靠 PRD 纪律 |
| **D7 (v2 新)** | Track D 是否含 forward decay detection 子模块？ | **Claude 建议 YES**（见 Track D step D.7） | 现框架只查数据完整性，不查 alpha 是否还在 |
| **D8 (v2 新)** | Dividend pass margin 阈值是否定 5y 累积 4%？ | **Claude 建议 YES**（M8） | 基于 SPY-QQQ div yield 差额 ~0.7%/yr × 5 + 缓冲 |

D7 + D8 等 Track A PRD draft 写出来时一起过。

---

## 11. Track A PRD 必须项 — 12 项 consolidated checklist (v2)

合并 codex round 19 (7 条) + 审核员 (5 条) + Claude 加约束 (3 处) + Claude 新增 (2 项)；去重后 **12 项**：

| # | 来源 | 内容 | Track A 内位置 |
|---|---|---|---|
| 1 | codex/审核员共识 | Purged label / forward-return 边界 | M4 + §4.3 acceptance.purge_rules |
| 2 | codex/审核员共识 | Machine-auditable sealed-test ledger | M5 + §4.3 audit.sealed_eval_ledger + Step A.7 |
| 3 | codex/审核员共识 | 2018 → validation + 2018-Q4 stress report; 2020/2022 stress slices 仅 MaxDD sanity | M1 + §4.3 stress_slices + reference_years |
| 4 | codex/审核员共识 | F1/F2 一页 fork criteria 写进 PRD | M7 + §4.3 acceptance.fork_criteria + §6.1 |
| 5 | codex/审核员共识 + Claude 加约束 | 2025 hard gate 第一个 core; diversifier role-specific (yaml 锁 + 补偿约束) | M6 + §4.3 roles |
| 6 | codex 加 | 504d warmup cap + 实际 max lookback per candidate 记录 | M3 + factor_warmup_max_lookback_days + 新增 audit.record_actual_max_lookback |
| 7 | codex 加 + Claude 量化 | Dividend pass margin 5y 累积 4% (Track D 强制) | M8 + §4.3 acceptance.dividend_safety + Step D.5 |
| 8 | codex 加 | Roadmap pointer hygiene (push main 让 commit 可 fetch) | ✅ 已 fix (push c62b1d8) |
| 9 | Claude 新增 | Regime tag 双标 (manual + auto-classifier) | M9 + §4.3 validation_years.manual_regime_tag + auto_classifier_tag + Step A.8 |
| 10 | Claude 新增 | Track D 含 forward decay detection 子模块 | §7 D.7 + §10 D7 |
| 11 | Claude 加约束 | Role assignment pre-mining 强制 (不准 post-hoc 分类) | M6 + audit.fail_closed_if_role_unspecified_at_mining_start |
| 12 | Claude 加约束 | F1/F2 fork 用百分位阈值, 不用 default bias | M7 + §4.3 acceptance.fork_criteria |

每一项在 Track A PRD 都必须有：(a) 对应 yaml schema 字段; (b) 实现 step 编号; (c) 验收测试编号; (d) failure mode 说明（什么情况触发 fail-closed）。

---

## 附录: 文档 lineage

- 外部审核员 1（engineering / research-rigor lens）的原始审计意见：用户消息粘贴 (v1)
- 外部审核员 2（regime-stratified split proposal）的原始提案：用户消息粘贴 (v1)
- 外部审核员 3 (post-redirection follow-up)：用户消息粘贴 (v2 — 5 条 + F1/F2 fork criteria 写进 PRD)
- codex round 19 review: `docs/audit/20260429-codex_round_19_strategic_redirection_review.md` (origin/review/claude-collab) (v2)
- Claude 的核对事实清单 + 量化判断 + M1-M3 修订 (v1) + M4-M9 加约束/新增 (v2)：本会话历史
- 本路线图 v2 整合上述 5 视角
