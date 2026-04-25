# Post-Data-Integrity OOS Validation Framework — PRD v3

**Author**: Codex  
**Date**: 2026-04-25  
**Version**: v3, final pre-MVP review  
**Status**: approved for user review; implementation not started

---

## 背景

Data-integrity round-3 已完成：

- `data/daily/*.parquet` 已由 polygon 1m 单一源重建
- 4 个 canonical paper cells 在新数据上 drift = 0.00 bps
- M11/M14 的 paper/replay 一致性修复在新数据上仍成立
- 旧 NAV 叙事被重估，尤其 2022 Cand-2 从 +74.57% 变成 +3.47%

这说明旧历史收益叙事曾被数据问题显著放大。现在最危险的动作不是
"找不到 alpha"，而是在更干净的数据上重新做一轮更精致的
in-sample 叙事。

本 PRD 的目标是建立一个 **honest OOS framework**，先区分：

- 历史上看起来不错
- 经过严格复核后仍值得真钱继续押

在这个框架落地前，universe extension / new mining / Candidate-3 /
new PRODUCTION_FACTORS / frozen spec changes 继续冻结。

---

## 1. 问题定义

### 1.1 当前历史结果不是 deployable OOS

当前 `rcm_v1_defensive_composite_01` 和
`candidate_2_orthogonal_01` 已在 2026-04-24 冻结。它们的构建过程
已经看过大量 2007-2026 历史信息：

- RCMv1 通过 2007-2026 walk-forward / acceptance 路径筛选
- Cand-2 通过 2015+ IC / orthogonality / paper replay 画像筛选

因此，事后再从历史中切一段 "holdout" 不能把当前 pair 变成真正
OOS。对当前 pair，历史 segment 只能叫：

**pseudo-OOS / narrative robustness segment**。

它可以验证历史叙事是否稳健，但不能作为 deployable alpha estimate。

真正可部署 OOS 只有两类：

- 当前 pair 的 frozen-date 之后 forward observation
- 未来候选在构建前预登记、构建流程未看过的 historical holdout

### 1.2 命名本身是风险控制

当前 pair 和任何 post-hoc 从已看过历史中切出来的窗口，必须使用
`robustness_*` artifact 名称。只有未来候选在构建前预登记、且构建流程
未看过的窗口，才允许使用 `holdout_*` 名称。

同一 runner 可以支持 robustness / future-holdout 两类历史窗口，但
文件名由 `evidence_class` + window registration rule 共同决定。
MVP 的 `evidence_class` enum 固定为三值，不能静默新增默认值：

| evidence_class | window registration | artifact naming |
|---|---|---|
| `historical_replay` | ordinary historical replay | replay-specific artifacts |
| `pseudo_oos_robustness` | post-hoc / already-seen historical window | `robustness_*.yaml/json/md` |
| `forward_oos` | frozen-date之后真实 forward | `forward_*.json/md` |
| `historical_replay` + pre-registered holdout flag | future candidate only, pre-construction and never seen by selection | `holdout_*.yaml/json/md` |

这个命名规则不是 cosmetic。它是防止 pseudo-OOS 被读成 OOS 的第一道
结构性防线。

### 1.3 候选治理缺少 OOS annotation

当前 registry 状态机能表达 S0/S1/S2/S5，但不能表达：

- 有没有 pseudo-OOS robustness eval
- 有没有 forward OOS eval
- concentration / watch-list / thin-data 暴露是否可接受
- negative result 后 narrative permission 是否被冻结

MVP 不改 registry。先用 candidate 目录下的 sidecar artifacts 表达这些
结论，等格式稳定后再讨论 registry annotation。

### 1.4 数据干净后不能解冻研究面

在 OOS framework 落地前，不解冻：

- universe extension
- new mining round
- Candidate-3
- new data tier
- frozen-spec retroactive changes
- new PRODUCTION_FACTORS

---

## 2. 目标

本 PRD 的目标不是提高回测收益，而是建立一个能阻止叙事幻觉的验证
系统。

**G1**: candidate-level pseudo-OOS / future-OOS artifact contract  
**G2**: forward OOS / forward paper schema，MVP 只定义契约不自动化  
**G3**: M12 concentration report + extreme manual-review tier  
**G4**: watch-list / thin-data / quarantine exposure 进入报告  
**G5**: negative-result protocol，把差结果制度化而不是叙事化

---

## 3. 非目标

本 PRD 不做：

- 修改当前两个 candidate 的 frozen spec
- 改 production strategy
- 新挖矿 / 新候选 / 新因子
- registry state-machine migration
- registry annotations beyond `oos_status.yaml`
- 真实 broker / live trading
- 用 factor-level IC fold 替代 candidate-level NAV OOS

---

## 4. 设计原则

- **先验证，再研究**：OOS framework 先于下一轮 alpha research。
- **以 candidate 为单位**：最终看 NAV / turnover / drawdown /
  concentration / implementation quality，不以单因子 IC 代替。
- **真钱优先**：任何收益结论都要同步检查集中度、成本、流动性、
  thin-data 暴露和 regime 依赖。
- **artifact-first**：所有判断必须落成文件，能追到 spec / data /
  window / benchmark / threshold。
- **历史 robustness 不等于未来 alpha**：当前 pair 的 historical
  segment 输出必须显式标注 pseudo-OOS。
- **无默认 evidence class**：schema 缺 `evidence_class` 时必须失败，
  不能自动把旧 artifact 归类。

---

## 5. 模块范围

### 模块 A：Candidate-Level Robustness / True Holdout

目标：为每个 frozen candidate 生成标准化 historical robustness 或
true holdout artifact。

对当前 RCMv1 + Cand-2：

- 窗口名称必须是 `pseudo_oos_robustness_window`
- artifact 文件名必须使用 `robustness_*`
- 结果不得写成 deployable OOS evidence
- 结果只能回答："当前历史叙事是否在未重点叙述的片段里仍站得住"

对未来候选：

- 如果 holdout 在构建前预登记，且构建流程未看过该 segment，才允许
  使用 `holdout_*` 文件名和 true holdout 语义。
- 如果未来候选也只是 post-hoc 从已看过历史里切片，仍使用
  `robustness_*`。

窗口规则：

- 默认目标 = 252 trading days
- 不允许手选 "clean segment" 或最好看的 regime
- 如果数据覆盖、candidate history 或 valid-window constraints 使
  252 TD 不可行，允许缩短，但必须在 spec 中写 `shrink_reason`
- 禁止为了凑满 252 TD 做 unnatural splicing

`candidate_robustness_window.yaml` schema draft：

```yaml
candidate_id: <id>
schema_version: "1.0"
evidence_class: pseudo_oos_robustness
window:
  start_date: "YYYY-MM-DD"
  end_date: "YYYY-MM-DD"
  target_trading_days: 252
  actual_trading_days: 240
  selection_rule: "last_valid_trading_days_before_frozen_date"
  shrink_reason:
    code: data_coverage_short
    note: "free text only when actual_trading_days < target_trading_days"
benchmark: SPY
secondary_benchmark: QQQ
data_integrity_snapshot:
  daily_store_rebuild_commit: <sha>
  baseline_snapshot_path: data/baseline/latest.json
  generated_at_utc: "YYYY-MM-DDTHH:MM:SSZ"
```

`shrink_reason` is optional when `actual_trading_days >= 252`, and required
when `actual_trading_days < 252`.

Controlled vocabulary for `shrink_reason.code`:

- `data_coverage_short`
- `regime_boundary`
- `candidate_history_short`
- `other`

交付物：

- `candidate_robustness_window.yaml` for current pair / post-hoc windows
- `robustness_eval.json`
- `robustness_eval.md`
- `negative_result_memo.md` when triggered
- future true holdout path may emit `candidate_holdout_spec.yaml`,
  `holdout_eval.json`, and `holdout_eval.md`

### 模块 B：Forward OOS / Forward Paper

目标：定义 frozen-date 之后的真实 forward 验证。

约束：

- candidate spec / benchmark / cost / turnover assumptions / checkpoint
  cadence 必须在 forward 开始前冻结
- forward 结果不得被 hindsight 调参污染
- forward 不因 10TD 或 20TD 结果好看而提前宣称 deployable

节奏：

- weekly operational checkpoint
- 10 TD operational sanity
- 20 TD early behavior
- 40 TD role stability
- 60 TD first decision checkpoint

加速器：

- 可在 pseudo-OOS NAV 上做 block-bootstrap CI
- CI 只能提示 "likely fail / fragile"，不能替代 forward OOS

MVP only defines `forward_run_manifest.json` schema. It does **not**
wire a forward runner or automation.

`forward_run_manifest.json` schema draft：

```json
{
  "schema_version": "1.0",
  "candidate_id": "<id>",
  "evidence_class": "forward_oos",
  "spec_hash": "<frozen-spec-hash>",
  "start_date": "YYYY-MM-DD",
  "benchmark": "SPY",
  "secondary_benchmark": "QQQ",
  "cost_assumptions": {
    "source": "config/cost_model.yaml",
    "config_hash": "<sha256>"
  },
  "checkpoint_cadence": {
    "weekly": true,
    "decision_days": [10, 20, 40, 60]
  },
  "current_status": "not_started",
  "data_integrity_snapshot": {
    "daily_store_rebuild_commit": "<sha>",
    "baseline_snapshot_path": "data/baseline/latest.json",
    "generated_at_utc": "YYYY-MM-DDTHH:MM:SSZ"
  },
  "runs": []
}
```

交付物（future, not MVP automation）：

- `forward_run_manifest.json`
- `forward_checkpoint_{10,20,40,60}d.md`
- weekly checkpoint snippets

### 模块 C：M12 Concentration Report + Extreme Review Tier

MVP 阶段默认是 report-first，不自动 block。但极端集中度不能静默通过。

Soft warning thresholds：

- top-1 weight > 40%：warning
- top-3 weight > 70%：warning
- thin-data exposure > 5%：warning
- watch-list single-name weight-day share >= 8%：warning
- single-sector weight-days > 50%：block-for-review label

Extreme manual-review thresholds（OR 条件，任一触发即可）：

- top-1 weight > 50%
- top-3 weight > 80%
- thin-data exposure > 10%
- watch-list single-name weight-day share > 15%

当 extreme tier 触发：

- `concentration_gate_status: manual_review_required`
- `narrative_permission: frozen`
- 报告和 memo 必须展示该字段
- 不自动 revoke
- 不自动 block execution
- 用户 resolve 前，候选不能被写成 "robustness eval strengthened"

覆盖维度：

- top-1 / top-3 / top-5 concentration
- name-days concentration
- sector concentration
- benchmark beta concentration
- watch-list names concentration
- thin-data exposure concentration

交付物：

- `concentration_report.json`
- `concentration_gate_result.md`

### 模块 D：Watch-List / Thin-Data Exposure Integration

目标：把 round-3 sidecars 真正接入报告口径。

必须展示：

- thin-data weight-days
- quarantined / dropped-name exposure
- data_quality_watch symbols contribution
- watch-list symbols 对 PnL / turnover / drawdown 的贡献

交付物：

- `watch_exposure_summary.json`
- master report section
- drift report section
- checkpoint summary section

### 模块 E：OOS Sidecar Annotation

MVP 不改 registry 状态机，不新增 S2_holdout_candidate。

候选目录下新增 sidecar：

- `oos_status.yaml`

Required fields:

```yaml
candidate_id: <id>
schema_version: "1.0"
evidence_class: pseudo_oos_robustness
has_pseudo_oos_eval: true
pseudo_oos_eval_passed: true|false|null
has_forward_eval: false
forward_checkpoint_count: 0
concentration_gate_status: pass|warning|manual_review_required|manual_review|null
watch_exposure_status: pass|warning|manual_review|null
narrative_permission: allowed|frozen|manual_review
data_integrity_snapshot:
  daily_store_rebuild_commit: <sha>
  baseline_snapshot_path: data/baseline/latest.json
  generated_at_utc: "YYYY-MM-DDTHH:MM:SSZ"
```

`evidence_class` is required. There is no default. Schema validation must
reject artifacts without it.

`data_integrity_snapshot` is a struct, not a string, to avoid inconsistent
future references after another data rebuild.

Registry boolean/status fields deferred to a post-MVP implementation round
after artifacts prove stable.

---

## 6. Negative-Result Protocol

这是本 PRD 的硬要求。差结果必须变成 artifact，不能回到临时叙事。

### 6.1 Pseudo-OOS robustness failure

适用于当前 pair 的 historical robustness window。

触发：

- robustness PnL < 0
- 或 annualized return 落后 benchmark >= 200 bps
- 或 M12 extreme manual-review tier 触发

动作：

- `pseudo_oos_eval_passed=False` if performance trigger fires
- `concentration_gate_status=manual_review_required` if concentration
  trigger fires
- `narrative_permission=frozen`
- 自动生成 `negative_result_memo.md` or manual-review memo
- escalate to user
- 不自动 revoke
- candidate 原 S2_paper_candidate 状态不变

含义：它否定的是历史叙事权限，不是自动否定候选存在价值。

### 6.2 Real forward OOS failure

触发：

- forward 60TD cumulative return 落后 benchmark >= 500 bps

动作：

- 标记为 revoke-candidate
- 自动生成 negative-result memo
- escalate to user
- 真实 revoke 仍必须由 user 确认

### 6.3 Sign flip

触发：

- pseudo-OOS robustness positive
- forward 60TD negative

动作：

- mandatory user escalation
- no auto-demote
- no auto-revoke
- 要求重新解释 strategy role，而不是直接补叙事

---

## 7. 推荐执行顺序

1. 定义 artifact schemas：
   `candidate_robustness_window.yaml` / `oos_status.yaml` /
   `concentration_report.json` / `watch_exposure_summary.json` /
   `forward_run_manifest.json`
2. 实现 robustness runner，仅生成 pseudo-OOS robustness artifacts
3. 实现 M12 concentration report + extreme manual-review tier
4. 实现 watch exposure report sections
5. 跑 RCMv1 + Cand-2，生成 artifacts 和 negative/manual-review memo
   （若触发）
6. 评估 artifact 格式是否稳定，再决定是否做 registry annotations
7. forward runner / automation 放到下一版

---

## 8. 第一批接入对象

只接入：

- `rcm_v1_defensive_composite_01`
- `candidate_2_orthogonal_01`

这两个候选的输出必须标注：

```text
Evidence type: pseudo-OOS robustness only, not deployable alpha estimate.
```

---

## 9. 验收标准

### 9.1 框架级

- 两个候选都能生成标准化 robustness artifacts
- 所有 artifacts 记录 candidate id / frozen spec / window / benchmark /
  threshold / data snapshot
- `evidence_class` required and consumed by reports
- `data_integrity_snapshot` struct present in status / eval artifacts
- concentration report 可执行
- extreme tier can set `manual_review_required`
- watch exposure section 可生成
- registry 不变，工作区不引入 lifecycle migration

### 9.2 治理级

- historical replay 自动标注为 non-OOS 或 pseudo-OOS robustness
- 报告里禁止把 current pair 的 historical robustness 写成 deployable OOS
- negative-result protocol 有 artifact 输出
- manual-review tier freezes narrative permission
- 用户能据此决定是否继续 forward，而不是被历史收益牵着走

### 9.3 操作级

- 不破坏 round-3 data baseline
- 不重新解冻 mining / universe / Candidate-3
- 不修改当前 frozen specs
- 不修改 production strategy
- forward manifest schema exists, but no forward automation is implied

---

## 10. 风险

- **风险 1**：做 OOS framework 时顺手改 candidate spec。本 PRD 禁止。
- **风险 2**：把 pseudo-OOS 写成真钱 evidence。本 PRD 明确禁止。
- **风险 3**：过早 hard-block concentration。MVP 不自动 revoke/block，
  但 extreme values freeze narrative permission until user review.
- **风险 4**：结果显示当前候选很弱。这不是失败，是框架的价值。
- **风险 5**：forward 太慢。允许 weekly checkpoint 和 bootstrap CI，
  但不允许它们替代 forward。
- **风险 6**：未来数据重建后旧 artifact 解释漂移。`data_integrity_snapshot`
  必须绑定每次 eval 的数据状态。

---

## 11. 解冻规则

本 PRD 只建议解冻 OOS-framework MVP。其余继续冻结。

下一步研究面解冻条件：

- 至少一个 candidate 完成 pseudo-OOS robustness + concentration +
  watch exposure
- manual-review items resolved or explicitly accepted by user
- first forward checkpoint 已开始产生真实数据
- 报告口径已经从 replay narrative 升级为 OOS narrative
- 用户明确批准解冻具体工作流

---

## 12. MVP

### MVP 范围

1. `candidate_robustness_window.yaml` schema + robustness runner
2. `oos_status.yaml` with required `evidence_class` and structured
   `data_integrity_snapshot`
3. `forward_run_manifest.json` schema only, no runner
4. M12 concentration report + `manual_review_required` extreme tier
5. watch exposure sections in master / drift / checkpoint reports
6. candidate-dir artifacts only，registry untouched

### MVP 外

- registry boolean/status fields
- registry state-machine migration
- M12 auto-revoke / auto-demote
- forward pipeline automation
- new mining / Candidate-3 / production factor changes

---

## 拍板建议

从真钱投资角度，round-3 之后最值得做的不是继续找新 alpha，而是先
建立这个 OOS 纪律层。

如果当前两个候选在 pseudo-OOS robustness / concentration / watch
exposure 下显得弱，这不是坏消息。这是在亏真钱之前发现系统边界。

如果某个候选触发 extreme concentration，它不一定是坏策略，但它不能
被轻易写成 "稳健性增强"。对个人账户而言，集中度和数据质量暴露就是
收益数字的一部分。

只有能经受住 forward observation 的候选，才值得进入下一轮更重的
研究和配置讨论。
