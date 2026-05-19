# cycle06/08 forward re-init + PRD-F registry-hash over-halt finding

**日期**: 2026-05-18
**性质**: 处置记录(tactical,operator 执行)+ 治理设计 finding(仅记录,
未 action,用户 2026-05-18 explicit "B, just record the PRD-F issue as a
finding")。
**纪律**: `feedback_self_audit_methodology`(R1-R4)、
`feedback_audit_surfaces_not_thorough`(暴露没做透 + fold 进文档)、
`feedback_decision_authority_operator_audit_split`(directional 由用户定)、
`feedback_no_blanket_failure_verdict`。

---

## §1 背景

`cycle06_31af04cf2ff9_evidence_v1` + `cycle08_3f40e3f4ed1a_evidence_v1`:
2026-05-15 过 Track-A acceptance(post-MaxDD-fix)+ sealed 2026 单发
2/2 PASS,forward-init 为 core_alpha evidence cohort,start 2026-05-15。
2026-05-18 daily-ritual observe 后两者 `current_status=requires_data_review`
(halt),从未积累真实 forward 证据(仅 init baseline TD001,
cum_ret=0.0,n_observed=1)。

## §2 根因(R3 实证,非 hand-wave)

两个 halt **不是数据修订引起**:

| 信号 | cycle06 | cycle08 |
|---|---|---|
| `data_revision_event.policy_decision` | flagged_only | flagged_only |
| materiality / NAV 影响 | in_ring / 1.05 bps | in_ring / 2.16 bps |
| raw drift | 0.00049% | 0.00185% |
| sign_flip | false | false |
| `config_drift_event.drifted_sources` | **factor_registry_hash** | **factor_registry_hash** |
| severity | **halt** | **halt** |

`factor_registry_hash`: init(05-15)`7cafec1b…` → now `13d42101…`。
驱动变化的 commit = **`1ea1ad8`(2026-05-15 22:37,Family T
swing-structure registry wiring)**。`git show 1ea1ad8 --
core/factors/factor_generator.py` 证明**纯加性**:仅 `+1` import +
`+1` 行 `factors.update(compute_swing_structure_factors(...))` 塞进
`generate_all_factors`(`factors.update()` 只新增 `swing_*` 列);
**不碰** cycle06 的 `drawup_from_252d_low / trend_tstat_20d / ret_2d`、
cycle08 的 `max_dd_126d / xsection_rank_63d / ret_5d`,不改
`build_composite_series`。commit message 自声明
`test_compute_factors_matches_reference guards bit-identical output`。

**判定**:cycle06/08 的 halt = 加性 registry 扩张触发 PRD-F
`factor_registry_hash` 全契约哈希变 → fail-closed 一律判
`severity=halt`。候选自身 composite 因子数值**可证不变**,evidence
零损伤。**与 trial9_001/002 本质不同**(那是 signal_input scope
`bound_only` + 空 per_cell_digest + 无重建路径 = 真不可逆失效)。

## §3 处置(用户 2026-05-18 选 B)

**B = 全新 re-init**(候选仅 baseline TD001,零真实 forward 证据,
re-init 零证据损失;绕开 recover 对 config_drift 的路径不确定性)。

- forensic 留痕:halt 态 manifest 复制为
  `data/research_candidates/{cid}_forward_manifest.preReinit_2026-05-18.json`。
- `dev/scripts/forward/init_cycle06_cycle08_evidence.py
  --start-date 2026-05-19 --overwrite`(dry-run 先验)。
- 结果:两者 `current_status=not_started`,`start_date=2026-05-19`,
  `runs=0`,spec_hash 不变(d2e7311e… / 8e26ad3a…,frozen spec 未动,
  仅 config_snapshot 刷新)。
- R3 验证:新 `config_snapshot.factor_registry_hash =
  13d42101fa50838a0581f8af0d9199e7833bdcb776d0ed9e638f95bc3dfd05f8`
  == 当前 registry hash → 下次 observe 不再触发 config_drift。
- TD60 决策点 ~2026-08-18(05-19 + ~60 交易日)。

**未选**:A(保 05-15 lineage recover)/ C(abort——明确排除,
非 trial9 失效模式,abort 会因一次良性加性扩张白扔主线仅有的两个
Track-A+sealed 过 core_alpha)。

## §4 治理设计 FINDING(仅记录,未 action)

PRD-F `_factor_registry_contract_sha` hash 的是**整个 RESEARCH_FACTORS
契约**,不是候选 spec 实际引用的因子子集。后果:**任何 registry
加性扩张都会 halt 所有在跑的 forward 候选**——本次拦 cycle06/08,
后续 registry 再长(Bucket/Family 扩张是 PQS 常态)也会同样误拦正在
soak 的 `chart_native_s1_evidence_v1` / `pead_sue_trial1_evidence_v1`。
这是会反复咬人的保守误拦模式(false-halt on additive expansion)。

**更精确设计(记录,未实现)**:按候选 frozen spec 实际引用的因子
子集 hash(per-candidate factor-subset registry hash),而非全契约
hash;加性扩张不影响未引用新因子的候选。属 PRD 级改动,用户
2026-05-18 explicit "just record as a finding" → **不起 PRD、不改
severity 策略**,仅作为已知 finding 留档,未来 registry 扩张期间
operator 需预期此误拦并按本 memo §3 同法 re-init / recover 处置。

关联 [[project-grand-audit-2026-05-18-two-p0]]
[[feedback_audit_surfaces_not_thorough]]
[[feedback_no_blanket_failure_verdict]]。
