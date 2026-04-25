# OOS MVP Execution PRD (ralph-loop driven)

**Author**: Claude (derived from codex's PRD v3)
**Date**: 2026-04-25
**Version**: v1
**Status**: ready for ralph-loop execution
**Source**: `docs/prd/20260425-oos_validation_framework_codex_v3.md`
**Lineage tag**: `oos-mvp-2026-04-25`

---

## 1. 目标

把 PRD v3 §12 的 MVP（4 项）通过 ralph-loop 跑成可审计的 artifact-first
实现。**只做 MVP 范围**：

- candidate-level robustness window spec + runner
- M12 concentration **report** (no hard block)
- Watch-list / thin-data exposure section in master + drift report
- forward manifest **schema-only** (no runner)

artifacts 落候选目录，registry 不动。

不解冻 universe / mining / Candidate-3 / new data tier / spec changes /
new PRODUCTION_FACTORS / registry state machine。

完成 = 所有 7 rounds 落地 + pytest 无 regression + 完成 promise
`OOSMVPDONE` emit。

---

## 2. 全局 HARD 约束（每 round 必须遵守，违反即 halt loop）

- 不修改 `config/*.yaml` 任何字段（含 `production_strategy.yaml`）
- 不修改 `core/factors/factor_registry.py::PRODUCTION_FACTORS`
- 不增加新依赖（`requirements*.txt` / `pyproject.toml` 不动）
- 不重命名 public function
- 不迁移 SQLite schema（`data/research_candidates/registry.db` 不动）
- 不删除 tests
- 不动 `core/research/candidate_registry.py` 的 state-machine enum
  (S0_research_prototype / S1_research_candidate / S2_paper_candidate /
  S5_deprecated 仍保持 4 状态)
- 不动 `core/research/frozen_spec.py`
- 不修改任一 frozen candidate spec
  (`data/research_candidates/*.yaml`)
- 不重建 `data/daily/*.parquet`（round-3 已稳定）
- 不修改 `data/ref/splits.parquet`
- 不开始任何不在 §3 R1-R7 的 round 范围内的 work
- 每 round 开始 + 结束都 record pytest tuple `(passed, skipped, xfailed)`；
  任何非本 round 加入的 regression test 解释的 drift → halt loop

---

## 3. Round split

7 rounds + closeout 第 8 round。每 round 的"acceptance gate"必须 pass
才能进入下一 round；不 pass 就 halt 升级给用户。

### R1 — schema + draft runner skeleton

**目标**：定义 `candidate_robustness_window.yaml` schema 和
`robustness_eval` runner 骨架。不真跑 eval，只把 schema +
schema-validation tests 落地。

**Artifacts**:
- `core/research/robustness/__init__.py`
- `core/research/robustness/window_spec.py` — pydantic schema for
  `candidate_robustness_window.yaml`. 必含字段:
  `candidate_id / evidence_class (enum: pseudo_oos_robustness |
  forward_oos | historical_replay) / start_date / end_date /
  actual_trading_days / target_trading_days (default 252) /
  shrink_reason (Optional, but REQUIRED when actual<target) /
  data_integrity_snapshot (struct: daily_store_rebuild_commit /
  baseline_snapshot_path / generated_at_utc)`
- `core/research/robustness/runner.py` — runner with `evaluate(spec)`
  signature; emits `NotImplementedError` for now
- `tests/unit/research/test_robustness_schema.py` — schema validation
  tests:
  - missing `evidence_class` → reject
  - default `evidence_class` value impossible (no default)
  - `actual<target` without `shrink_reason` → reject
  - `shrink_reason.code` 必须 ∈ {data_coverage_short, regime_boundary,
    candidate_history_short, other}
  - `data_integrity_snapshot` 必须三字段都存在

**Acceptance gate**:
- 全 pytest 不 regression
- schema test 至少 5 个 case 全 pass
- runner.py import 通过

### R2 — robustness eval real run for RCMv1 + Cand-2

**目标**：把 R1 的 runner 实现真正的 robustness eval 逻辑，对当前两个
candidate 跑一遍，产出 artifacts。

**Artifacts**:
- `core/research/robustness/runner.py` — full implementation:
  - load candidate frozen spec
  - load 252 TD before frozen-date as default robustness window
  - replay candidate composite signal + paper run on that window
    (reuse existing `BacktestEngine.run` via candidate spec)
  - compute: cum_ret / sharpe / max_dd / vs_spy / vs_qqq /
    turnover / fill_count
  - emit `robustness_eval.json` (structured) + `robustness_eval.md`
    (human-readable)
- `data/research_candidates/<id>_robustness_window.yaml` for both
  candidates with `evidence_class: pseudo_oos_robustness`
- `data/research_candidates/<id>_robustness_eval.{json,md}` for both
- `tests/unit/research/test_robustness_runner.py` — mock runner test
  + real-data smoke test (skip if data missing)

**Acceptance gate**:
- 全 pytest 不 regression
- 两个 candidate 都产出 robustness_eval artifacts
- artifacts 中 `evidence_class == pseudo_oos_robustness` 显式 set
- 252 TD window before frozen-date `2026-04-24` 实际能 carve 出（pre-2024-04-24 至少 252 TD）；如果 short则 `shrink_reason` 必填

### R3 — M12 concentration report (no hard block)

**目标**：实现 PRD v3 §C concentration report，warning + extreme tier，
**只产报告，不 block candidate**。

**Artifacts**:
- `core/research/concentration/__init__.py`
- `core/research/concentration/report.py` — `compute(candidate_id,
  weights_df) -> ConcentrationReport`
  - 6 dimensions: top-1 / top-3 / top-5 / name-days / sector / watch-list
  - warning thresholds (per v3 §C lines 283-287):
    - top-1 > 40% / top-3 > 70% / thin-data > 5% /
      watch-single >= 8% weight-day-share /
      sector > 50% (block-for-review label)
  - extreme thresholds (per v3 §C lines 291-294):
    - top-1 > 50% OR top-3 > 80% OR thin-data > 10% OR
      watch-single > 15%
    → `concentration_gate_status: manual_review_required`
    → `narrative_permission: frozen`
- `tests/unit/research/test_concentration.py` — unit tests for each
  dimension + warning/extreme tier classification
- 集成到 R2 的 runner: 调 robustness eval 时同时产出
  `concentration_report.{json,md}` 在候选目录

**Acceptance gate**:
- 全 pytest 不 regression
- concentration test 至少 8 case (per dimension warning + extreme +
  pass)
- 两个 candidate 都产出 concentration_report
- **不 hard block**: candidate 即使 manual_review_required 也仍然
  emit artifact，只是带状态字段

### R4 — Watch exposure section integration

**目标**：把 `data/ref/data_quality_watch.parquet`（round-3 step-3b
落地）的 sidecar 集成到 master report + drift report 输出，让用户看到
"这个候选实际暴露多少 thin_data / quarantine / watch-list names"。

**Artifacts**:
- 修改 `core/reporting/master_report.py` 增加
  `_render_watch_exposure_section(candidate_id, paper_run_dir)`，
  output 一个 markdown section:
  - top-of-section table: per-symbol, weight-day-share, watch_reason,
    thin_data_days, quarantine_days
  - prose: "candidate has X% weight-day-share on watch-list names;
    Y days had thin_data flagged; Z days quarantined"
- 修改 `scripts/paper_drift_report.py` 同样集成（drift report 是 candidate
  paper run 的核心 review 工具，必须显示 watch exposure）
- `tests/unit/reporting/test_watch_exposure_section.py` — 验证 section
  在 mock paper run dir + watch sidecar 下正常产出

**Acceptance gate**:
- 全 pytest 不 regression
- 两个 candidate 的 master report + drift report 都含 watch exposure
  section
- section 至少包含 top-table + 1 段 prose
- watch sidecar 缺失时 graceful degrade（输出 "no watch sidecar; data
  quality unknown" 而不是 crash）

### R5 — forward manifest schema-only

**目标**：定义 `forward_run_manifest.json` schema validator。**不实现
runner**。PRD v3 §B 明文说 schema only no runner — 严格遵守。

**Artifacts**:
- `core/research/forward/__init__.py`
- `core/research/forward/manifest_schema.py` — pydantic schema:
  - `candidate_id / spec_hash / start_date / benchmark /
    cost_assumptions / checkpoint_cadence / current_status /
    data_integrity_snapshot / runs (List, initially [])`
  - `current_status` enum: `pre_start | running | paused | closed`
- `tests/unit/research/test_forward_manifest_schema.py` — schema
  validation tests
- **明确不允许**：不写 forward_runner.py / 不写任何 forward
  execution 代码 / 不在 R5 内开始 forward eval

**Acceptance gate**:
- 全 pytest 不 regression
- schema validator pass
- `core/research/forward/` 目录下没有 runner 实现文件
- R5 commit 内不包含任何 forward execution 代码

### R6 — integration smoke + cross-artifact consistency

**目标**：写一个 end-to-end smoke 把 R1-R5 串起来跑两个 candidate，
验证 `evidence_class` propagate 正确，artifact 之间无冲突。

**Artifacts**:
- `dev/scripts/oos_mvp/smoke.py` — 串联调用：
  1. load candidate
  2. compute robustness window
  3. run robustness_eval (R2)
  4. compute concentration_report (R3)
  5. emit watch exposure section (R4) — invoke master report
  6. validate forward manifest schema (R5) on a fake manifest
- 在 RCMv1 + Cand-2 上跑，输出
  `dev/scripts/oos_mvp/smoke_<candidate>.log`
- **negative-result simulation**: smoke 内含一个 case 故意把
  `evidence_class` 设成 `historical_replay` 然后调 R3 concentration
  report 的 narrative_permission 检查 — 验证 schema validator 拒绝
  错误 evidence_class
- `tests/integration/test_oos_mvp_smoke.py` — 把 smoke 跑成 pytest
  test (skip if real candidate data unavailable)

**Acceptance gate**:
- 全 pytest 不 regression
- smoke 跑两 candidate 都成功
- negative-result simulation 正确 reject

### R7 — docs sync + closeout + emit OOSMVPDONE

**目标**：刷新 docs，rebuild baseline，emit completion promise。

**Artifacts**:
- `docs/memos/20260425-oos_mvp_close.md` — 关闭 memo:
  - R1-R6 commit hashes
  - artifact 清单（每个 candidate）
  - 关键发现：两 candidate 的 robustness eval 数字 + concentration
    report 状态 + watch exposure 数字
  - **不 framing 为"OOS validated"** — framing 必须是"pseudo-OOS
    robustness eval done; deployable OOS still requires forward
    observation"（per v3 §1.1）
- 更新 `CLAUDE.md` "Current TODO" 加 OOS MVP done entry
- 更新 `docs/INDEX.md` 加新 PRD + memo entries
- `data/baseline/latest.json` rebuild via `--run-tests`
- pytest tuple 必须 match expected (1617 baseline + R1-R6 累积新增 N tests)

**Acceptance gate**:
- 全 pytest 不 regression（drift 必须由 R1-R6 加入的 regression test
  解释，否则 halt）
- baseline rebuilt
- 关闭 memo 存在且 framing 正确（pseudo-OOS, not OOS）
- CLAUDE.md + INDEX.md 更新
- assistant-turn reply emit `<promise>OOSMVPDONE</promise>` 在 top
  level（per ralph-loop contract）

---

## 4. Ralph-loop contract

- **lineage_tag**: `oos-mvp-2026-04-25` (用于 artifact / commit /
  log entry tagging)
- **completion promise**: `OOSMVPDONE`
- **max_iterations**: 8 (7 rounds + 1 buffer for any single-round
  retry)
- **每 round commit message 格式**:
  ```
  oos-mvp R<N>: <scope>: <summary>
  ```
  例: `oos-mvp R1: robustness window schema + runner skeleton`
- **每 round 11-part Chinese report**: append to
  `docs/20260420-ralph_loop_log.md` as
  `R-oos-mvp-2026-04-25-round-NN`. 11 parts 按现有 convention:
  本轮目标 / 做了什么 / 修改文件 / 跑了什么测试 / 当前结果 / 剩余
  风险 / 下一步 / 修改 commit hash / 等等

### 4.1 Authorized 自动操作

- 在 `core/research/{robustness,concentration,forward}/` 下新增 modules
- 在 `tests/unit/research/` + `tests/unit/reporting/` +
  `tests/integration/` 下新增 tests
- 在 `data/research_candidates/<id>_*` 下新增 artifacts
- 在 `dev/scripts/oos_mvp/` 下新增 dev scripts
- 修改 `core/reporting/master_report.py` 增加 watch exposure section
- 修改 `scripts/paper_drift_report.py` 增加 watch exposure section
- 更新 `docs/memos/`、`docs/INDEX.md`、`CLAUDE.md`、
  `data/baseline/latest.json`

### 4.2 Must Pause 升级用户

- 任何要修改 §2 HARD 约束 list 中条目的需求
- 任何 round 连续两次 retry 仍 fail（说明有真 blocker）
- pytest 出现非本 round 加入 regression test 解释的 drift
- 任何 round 跑超过 30 分钟（cost guardrail）
- 任何 round 内 artifact 体积异常（单文件 > 10 MB；累积 > 100 MB）

### 4.3 Halt 条件

- §2 HARD 约束被违反
- §4.2 Must Pause 触发但用户未授权继续
- 完成 promise `OOSMVPDONE` emit 之后

---

## 5. 整体 acceptance（R7 emit `OOSMVPDONE` 之前必须满足全部）

- 7 rounds 全部 commit
- 全 pytest pass + drift 都由本 batch 加入的 regression test 解释
- baseline `data/baseline/latest.json` rebuilt with `--run-tests`
- 两个 candidate 都有完整的 OOS MVP artifact set:
  - `robustness_window.yaml`
  - `robustness_eval.{json,md}`
  - `concentration_report.{json,md}`
  - master report + drift report 都 render watch exposure section
- forward manifest schema validator 工作但 no runner code
- `docs/memos/20260425-oos_mvp_close.md` 写成正确 framing（pseudo-OOS,
  not deployable OOS）
- CLAUDE.md / INDEX.md 反映 OOS MVP done

---

## 6. 一句话总结

ralph-loop 在 7 round 内把 PRD v3 §12 MVP 的 4 项艺术化落地为可审计
artifacts，整轮内不动 spec / registry / production / data layer，
不把 pseudo-OOS 包装成 OOS，emit `OOSMVPDONE` 后等用户决定是否进入
forward observation 阶段。
