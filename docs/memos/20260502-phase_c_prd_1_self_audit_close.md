# Phase C-PRD-1 ship 全套 self-audit close — 2026-05-02

**Mandate**: 4 层方法论 (R1 事实 / R2 逻辑 / R3 真跑 / R4 边界) 回扫
Phase C-PRD-1 ship 4 个 commit，确认没有第 3 个 post-ship gap。前
两个已发现并修：
- gap #1: v2 dispatch 不生效 → commit `60e0dfe`
- gap #2: TD20/40/60 attention 自动化缺 → commit `7dbae10`

**Verdict**: **第 3 个 gap 找到了** — `R2-A`：cross-system role naming
mismatch (`core_alpha` vs `core`)。修复一并 ship in this round。

---

## Audit 范围

| Commit | 描述 | 主要文件 |
|---|---|---|
| `7dcdf50` | 主 ship: diversifier role + Trial 9 forward init | manifest_schema.py / candidate_registry.py / runner.py / config/temporal_split_v2.yaml / Trial 9 yaml + manifest |
| `60e0dfe` | P0 fix: v1↔v2 dispatch | temporal_split.py / temporal_split_acceptance.py |
| `7dbae10` | P0: attention check automation | core/research/forward/attention_report.py + dev/scripts/forward/attention_check.py |
| `dfe3b4f` | P1: C-PRD-2 spec DRAFT | docs/prd/20260501-c_prd_2_dd_throttle_role_caps_DRAFT.md |

---

## R1 事实 — 文件层面

每个 commit 列 file 数已通过 `git show --stat` 验证：
- `7dcdf50`: 13 files (CLAUDE.md + 4 core code + 2 manifest + 2 dev script + 1 PRD memo + 412-line test + 1 yaml)
- `60e0dfe`: 5 files (2 code + 3 test)
- `7dbae10`: 4 files (1 module + 1 CLI + 1 test + 1 doc)
- `dfe3b4f`: 1 file (PRD draft)

无文件意外 / 无遗漏 / commit message 与 file list 一致。✅

---

## R2 逻辑 — 4 个 finding

### R2-A (P1) — Phase C-PRD-1 ↔ Track A role naming mismatch  *[FIXED in this round]*

**Surface**:
- `core/research/candidate_registry.py:157` — `_VALID_ROLES =
  {"core_alpha", "diversifier", "legacy_decay_verification", "risk_control"}`
- `core/research/forward/manifest_schema.py:87` — `CandidateRole.core_alpha = "core_alpha"`
- `config/temporal_split.yaml` + `temporal_split_v2.yaml` — `roles: {core, diversifier}`
- `core/research/sealed_ledger.py:215` — `if role == "core":`
- `core/fleet/manifest_schema.py:42` — `_RoleLiteral = Literal["core", "satellite"]` + bridge

**Bug demonstrated** (R3 真跑):
```python
>>> from core.research.temporal_split import load_temporal_split, ensure_role_assigned
>>> ensure_role_assigned("core_alpha", load_temporal_split())
ValueError: role 'core_alpha' not declared in split 'alternating_regime_holdout_v1'; available: ['core', 'diversifier']
```

**Impact**: 当 cycle #06+ 出 core_alpha candidate 走 Track A acceptance 时
`ensure_role_assigned` 直接 raise，mining 启动失败。

**Why Trial 9 escaped**: Trial 9 role=`diversifier`，名字在 Phase C +
Track A 两个 vocabulary 里碰巧一致。

**Fix shipped this round**:
- 加 `phase_c_role_to_track_a_role()` bridge function in
  `core/research/forward/manifest_schema.py` (mirrors fleet 的
  `track_a_role_to_fleet_role` pattern)
- `core_alpha → core` / `diversifier → diversifier` (passthrough) /
  `legacy_decay_verification`+`risk_control → ValueError`
- 8 new unit tests in `test_diversifier_role_phase_c_prd_1.py`
  (32 → 40 tests)
- end-to-end integration test: bridge output 通过 `ensure_role_assigned`
  + `resolve_split_path` (v1↔v2 dispatch unaffected)

**Bridge 用法**: candidate_registry → Track A acceptance 边界 ONE
explicit translation point。**禁止** open-code dict lookup。

### R2-B (P3 doc) — `resolve_split_path` docstring listed `"core"` not `"core_alpha"`  *[FIXED]*

`core/research/temporal_split.py:556` docstring 写：
> Candidate role. One of {"core", "diversifier", "legacy_decay_verification", "risk_control"}.

但函数只 check `role == "diversifier"` 才走 v2，其他都默认 v1。如果
caller 直接传 `manifest.candidate_role.value` (`"core_alpha"`)，dispatch
正确（落 v1）但 docstring 误导维护者。

**Fix shipped**: docstring 改为说明 "Track A acceptance role string"，
显式要求 phase_c → track_a translation via bridge before passing in。

### R2-C (P3 doc) — `classify_td60_verdict` `soft_warn_cleared==False → RED`  *[NOTED, not fixed]*

`core/research/forward/attention_report.py:377` 的 RED 条件包含
`soft_warn_cleared==False`，但 PRD §7.1 GREEN/YELLOW/RED 里只把
soft_warn 列在 GREEN requirement 里，没说 RED。

**Verdict**: 这是 *defensive stricter-than-spec* 实现，与 PRD §6.2 D10c
"TD60 self-clearing" contract 一致。code 比 PRD §7.1 严格但 *consistent
with §6.2*。无需 code 修改；标记给未来 PRD reviewer 确认。

### R2-D (无) — `dfe3b4f` C-PRD-2 spec DRAFT 内部一致性

- ✅ Status `DRAFT_PENDING_FORWARD_EVIDENCE` 显式
- ✅ §8 / §9 显式 DEFERRED 等 forward evidence
- ✅ 所有 numeric threshold 标 `<TBD_FROM_FORWARD>`
- ✅ Implementation NOT authorized until TD60 GREEN 明示
- 无 R2 issue

---

## R3 真跑 — pytest + manual

### R3.1 单测套件 (audit baseline before fix)

| Suite | Tests | Result |
|---|---|---|
| `test_diversifier_role_phase_c_prd_1.py` | 32 | ✅ pass |
| `test_temporal_split_v1_v2_dispatch.py` | 20 | ✅ pass |
| `test_forward_runner.py` | 24 | ✅ pass |
| `test_candidate_registry.py` | varies | ✅ pass (in subset) |
| `forward/test_attention_report.py` | 31 | ✅ pass |
| `test_temporal_split_acceptance.py` | varies | ✅ pass |
| **Total relevant** | **202** | **✅ 0 fail** |

### R3.2 单测套件 (audit baseline after fix)

| Suite | Tests | Result |
|---|---|---|
| `test_diversifier_role_phase_c_prd_1.py` | 32→**40** | ✅ pass |
| Full `tests/unit/research/` + `tests/unit/fleet/` | (broad regression) | ✅ pass (timing TBD-from-monitor) |

### R3.3 Manual exercise

- `forward status / readiness / dry-run observe` on Trial 9 — done in
  Task #1 pre-flight, no regression
- `attention_check.py --candidate trial9_diversifier_001 --no-json` —
  TD000 graceful degrade, no exception, soft_warn=`pending_insufficient_data`
- Bridge function direct call all 4 enum values + 1 unknown + None / int
  TypeErrors — covered by 8 new pytest cases

---

## R4 边界 — 5 个 boundary check

| Boundary | Result |
|---|---|
| TD60 verdict `residual_corr_max == 0.4` exact | YELLOW (matches PRD `[0.4, 0.6]` inclusive) ✅ |
| TD60 verdict `residual_corr_max == 0.6` exact | YELLOW (matches PRD `> 0.6` strict for RED) ✅ |
| TD60 verdict `bull_vs_qqq_60d == -0.03` exact | YELLOW (matches PRD `[-10%, -3%]` inclusive) ✅ |
| TD60 verdict `bull_vs_qqq_60d == -0.10` exact | YELLOW (matches PRD `< -10%` strict for RED) ✅ |
| `freeze_date == 2026-05-01` exactly (Trial 9) | v2 (matches `>= cutoff`); ✅ Trial 9 dispatch confirmed v2 in ad-hoc test |
| `phase_c_role_to_track_a_role(None)` | TypeError (post-fix) ✅ |
| `phase_c_role_to_track_a_role(42)` | TypeError (post-fix) ✅ |
| `phase_c_role_to_track_a_role("orphan_role")` | ValueError "unknown Phase C role" (post-fix) ✅ |

无新边界 bug。

---

## Open follow-ups (NOT shipped this round)

1. **R2-C 文档化**: PRD §7.1 reviewer 确认 `soft_warn_cleared==False
   → RED` 是否应该明示在 §7.1 而不是只在 §6.2 D10c。Low priority。
2. **`candidate_registry → Track A acceptance` 实际 promotion path
   wiring**: bridge 函数已 ship + 测试覆盖，但还没人调用。当 Track A
   acceptance promotion 真跑时（cycle #06+ 出 core_alpha），调用方
   需改为 `phase_c_role_to_track_a_role(record.role)` 后再 pass 给
   `ensure_role_assigned`。Tracked in CLAUDE.md TODO; activates at
   first core_alpha promotion.
3. **CandidateRecord.to_track_a_role() helper** (可选): 如果将来调用
   方很多，可以在 CandidateRecord 上加 `to_track_a_role()` method
   forward 到 bridge function。当前直接调 bridge 也够清晰。

---

## 收尾

- `7dcdf50` + `60e0dfe` + `7dbae10` + `dfe3b4f` audit done
- 1 个真 P1 bug 找到 + 修复 + 测试覆盖
- 1 个 P3 doc smell 修
- 1 个 P3 stricter-than-spec 标记
- 0 第 4 个 post-ship gap suspect
- baseline tests 202 → 210 in this round (+8 bridge regression tests)

**Self-audit verdict**: Phase C-PRD-1 ship + 3 post-ship fix (gap #1
v2 dispatch / gap #2 attention check / gap #3 role bridge — this
round) **complete**。下一个 risk surface = TD20 attention check 真跑
（~2026-06-01），届时验证 attention_check.py 在 n_runs=20 状态下
端到端工作。
