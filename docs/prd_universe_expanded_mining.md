# PRD: Universe-Expanded Mining — 30-Round Ralph-Loop

**Status**: ACTIVE — ready for ralph-loop invocation
**Date**: 2026-04-21
**Trigger**: User-directed post-R28 universe expansion sign-off
**Supersedes**: `docs/prd_llm_factor_mining.md` (30-round LLM phase) at the
factor-discovery level — this phase focuses on **strategy calibration on
the expanded universe** and further alpha selection exploration
**Prior-phase findings source**: `docs/llm_phase_blocker_report.md`

---

## 1. 背景 (Context)

### 1.1 前 28 轮 LLM phase 产出
- `drawup_from_252d_low` 升级到 `PRODUCTION_FACTORS`（R15, user-auth）
- 26 个结构化 LLM factor 候选走完 funnel；1 促 RESEARCH，25 archive
- Universe alpha/beta audit (R20 + R21) 确认 Mag7-heavy 原 universe
  只 19% 符号产生 α > 3%，全部在 tech

### 1.2 R28 universe 扩容（user-approved）
- 32 → **53 symbols**: 原 universe + 21 v2 candidates
  - 1 Alpha Core: PWR (β_spy=1.32 borderline)
  - 12 Diversifier: WMT/GILD/JNJ/K/VZ/OXY/GIS/WEC/EA/ED/DG/CLX
  - 8 Tactical: GS/MS/C/LRCX/KLAC/CAT/MU/AVGO
- Spec: `docs/universe_expansion_spec_v2_2.md`
- R17 "不降标准" 原则严格保留

### 1.3 当前 blockers（本 PRD 要解决）
- **Blocker A**: MFS default weights 在扩容 universe 下 CAGR=16.3% < QQQ 17.6%
  （xfail 于 `test_full_period_cagr_beats_qqq`）—— **需 recalibration**
- **Blocker B**: R16 OOS IR barrier —— 0/83 trials 过 0.20 threshold（pre-R28）
  —— 扩容 universe 能否打破仍未测试
- **Blocker C**: Alpha Core 仅 1 symbol (PWR, borderline) ——
  universe 扩容进 v3 small-cap branch 是否增量（独立 research branch）

---

## 2. 目标 (Success Criteria)

### 2.1 硬约束（必达）
1. 全 suite pytest 回到 **1108 passed + 1 xfailed → 1109 passed 0 xfailed**
   —— i.e. 找到新 weight set / 新 factor / 新 strategy 让 MFS CAGR > QQQ 在
   扩容 universe 上
2. ≥ 1 trial 通过 evaluator.evaluate 完整 funnel（tier ≠ D）在扩容
   universe 上
3. PRODUCTION_FACTORS 和 `config/universe.yaml` 未来改动 **必须** 用户签核

### 2.2 期望（可选）
4. OOS IR 分布整体右移：新 lineage best OOS IR > pre-R28 best (+0.008 from
   R1 dual_momentum / -0.089 from R15 multi_factor)
5. 至少找到 1 个可 promote 的 factor weight 组合，通过 QQQ hard gate
6. Intraday (60m) 路径至少 1 个 trial 产出 positive OOS IR

---

## 3. 30-Round Topic Menu

按优先级粗排，每轮 pre-audit 决定具体主题:

| # | Topic | Completion signal |
|---|---|---|
| R29-R32 | **Daily mining baseline on expanded universe** | ≥1 trial OOS IR > 0.0 in new lineage |
| R33-R35 | **MFS factor weight grid search** | Find weight set where CAGR > QQQ (un-xfail test) |
| R36-R38 | **Intraday (60m) mining baseline** | 60m strategy trials archived for expanded universe |
| R39-R42 | **Alpha selection criteria v2** | Additional selection filter（e.g., sector-neutral、regime-aware）produces ≥2 trials over OOS threshold |
| R43-R46 | **Regime-conditional factor weights** | Multi-regime weight configs beat single-weight baseline on ≥3 OOS metrics |
| R47-R50 | **Dual momentum + trend-following on expanded universe** | Non-MFS strategy types promoted or archived with clear verdict |
| R51-R54 | **Cross-asset rotation expanded** | CAR explored with expanded equity pool |
| R55-R58 | **Multi-TF timing layer (prior phase tools)** | Timing layer evaluated on expanded universe |

### 3.1 Per-round delivery standards

每轮必须:
1. 使用不同 `--lineage-tag` （按 `post-2026-04-21-universe-mining-round-N`）
2. 不修改 `config/universe.yaml` 或 `core/factors/factor_registry.py::PRODUCTION_FACTORS`
   without explicit user auth
3. 保持 pytest green (1108 + 1 xfail, 或 1109 green if xfail resolved)
4. Commit code + doc updates，最后 invoke `scripts/send_round_summary.py`
5. 输出 11-part Chinese report to chat

---

## 4. 实施约束 (Constraints)

### 4.1 Universe constraints
- `config/universe.yaml` = R28 baseline (53 symbols)
- 不得在本 loop 内扩 universe 到 v3 small-cap（独立 branch）
- 不得重新引入 ETFs 到 seed_pool（v2.2 Layer 1 security type 白名单）

### 4.2 Spec constraints
- v2.2 spec 的 Layer 2 阈值（alpha_positive_rate 0.60 / alpha_t_stat 1.5 / r2 0.75）
  **可 calibration**（per v2.2 header note "thresholds are default starting
  points"）但**必须**:
  - 记录校准前后 bucket population 对比
  - 保留 R17 "不降标准" 原则 —— relaxation 必须**双向证据**支持

### 4.3 R15 drawup_from_252d_low promotion 不可逆
- drawup 是 PRODUCTION_FACTORS，不可移除
- 本 loop 允许调整 weight，但不可删除 inline 计算

---

## 5. 工具链 (Tools already built, ready to use)

LLM-phase R1-R28 produced these tools — all available for this phase:

| 工具 | 用途 |
|---|---|
| `scripts/run_mining.py` | 主 mining loop (现支持 `--extra-symbols`) |
| `scripts/llm_factor_propose.py` | LLM candidate 入 funnel |
| `scripts/llm_candidate_deep_check.py` | §5.4 reverse review |
| `scripts/llm_candidate_factor_backtest.py` | 5-gate 单因子验证 |
| `scripts/llm_composite_backtest.py` | 多因子 composite 测试 |
| `scripts/llm_candidate_orthogonalization.py` | residual IC gate |
| `scripts/run_factor_interaction_mine.py` | pairwise 交互挖矿 |
| `scripts/run_llm_cross_signal_mining.py` | Ridge vs XGBoost perm importance |
| `scripts/universe_admission_screen.py` | v2.2 Layer 1 admission |
| `scripts/universe_risk_labels.py` | v2.2 Layer 2 risk labels |
| `scripts/universe_bucket_assign.py` | v2.2 Layer 3 bucket 分配 |
| `scripts/universe_alpha_diagnostic.py` | β/α audit |
| `scripts/run_model_comparison.py` | Ridge + XGBoost baseline |
| `scripts/send_round_summary.py` | 每轮微信推送 |

---

## 6. Lineage tag 策略

每轮 archive entries 用:

```
post-2026-04-21-universe-mining-round-{N}
```

其中 N=29..58 (30 轮)。

**禁止** 混用 pre-R28 lineage（避免 expanded/non-expanded universe 数据污染）。

---

## 7. Stop Conditions (§13.2 等价)

每轮必须检查、任一触发则 **停下问用户**:

1. **pytest 降至 1108 以下**（加上 1 xfail 算 1109）—— 表示 universe 扩容之外的
   回归
2. **PRODUCTION_FACTORS 需变更** —— 涉 hard change, 必须签核
3. **200 trials 累计仍无 tier ≠ D promote** —— 搜索方向错了
4. **任一 archive 行 `passed_qqq_gate=False` 但 `tier != 'D'`** —— invariant
   违反
5. **`config/universe.yaml` 需改动** —— 触发用户签核 workflow

---

## 8. 启动方式

### 8.1 Ralph-loop 调用

Use `scripts/start_universe_mining_loop.sh` (see §9).

Key settings:
- `--max-iterations 30`
- `--completion-promise RALPHDONE`
- Prompt points to this PRD's §3 topic menu

### 8.2 Monitoring

每轮 stdout + `docs/ralph_loop_log.md` "Universe-Mining-Round N" 段落 +
微信推送 (via `send_round_summary.py` when `PQS_WECOM_WEBHOOK_URL` set).

### 8.3 数据产出

所有 mining 产出 archive `data/mining/archive.db`，用
`scripts/run_mining.py --leaderboard --lineage-filter 'post-2026-04-21%'`
查看。

---

## 9. 交付物 (Deliverables)

30 轮完成后产出:

1. **Universe-Expanded Mining Final Report** (markdown at
   `docs/universe_expanded_mining_final_report.md`)
   - Blocker resolution status (A/B/C from §1.3)
   - Best strategy config（factor weights, top_n, lookbacks）
   - Archive leaderboard with lineage_tag filtering
2. **Updated test suite** —— xfail 解除（如 recalibration 成功）
3. **Optional: PRODUCTION_FACTORS 追加**（需用户签核）

---

## 10. Appendix — 前 28 轮 LLM phase blockers 回顾

为避免重复相同错误:

1. **R5 MaxDD invariant 把关** —— factor-level 工具无法替代 MFS
   full-stack (kill_switch + target_vol + regime scaling)。任何 factor
   backtest 必须走 `run_mining.py` evaluator.evaluate 完整路径
2. **R7 interaction mining selectivity** —— 18/28 pair 破坏 alpha；
   interaction candidates 需 incremental-IC filter
3. **R8 regime-gating 害强 IC factor** —— 不通用 risk 机制；
   composite diversification 才是真 risk management
4. **R9 factor-level composite 达 MaxDD 天花板** —— 需 MFS full-stack
5. **R17 不降标准** —— OOS IR threshold 0.20 合理，不为 promote 降
6. **R20 universe audit** —— 19% of original universe has α>3%，全在 tech
7. **R28 universe expansion validated** —— Alpha Core from 0→1 by
   扩容，不改 spec

---

## 11. Change log

| 日期 | 变更 |
|---|---|
| 2026-04-21 | 初稿，by LLM-phase ralph-loop after user R28 approval |
