# Trial9 config_snapshot backfill — factor_registry RESEARCH_FACTORS 兼容性扩展

**Date**: 2026-05-05  
**Operator**: zibomeng (Claude Opus 4.7)  
**Manifest affected**: `data/research_candidates/trial9_diversifier_001_forward_manifest.json`

## 触发事件

2026-05-05 daily ritual 跑 `forward observe trial9_diversifier_001` 真实执行（非 dry_run），
revalidate_manifest 检测到 `factor_registry_hash` 漂移：

| 字段 | 值 |
|---|---|
| snapshot_hash | `faf27ce7877939616f18fc0784c0d165c1cdf12bf6ca3f9af7518dfe5f3ff9b0` |
| current_hash  | `b844d7484d099ae508d178b5945bb6c2c8c791edb82287df983dabf70b328e88` |
| severity      | halt |
| current_status flip | `in_progress` → `requires_data_review` |

## 根因

Commit `b51d3f1` (S/R Step 2: daily-resolution swing-extrema factors → RESEARCH_FACTORS) 把
3 个 SR factors 加进了 `core/factors/factor_registry.py` 的 `RESEARCH_FACTORS` frozenset：

- `dist_to_swing_high_20d`
- `dist_to_swing_low_20d`
- `sr_range_compression_20d`

trial9 init 时间在 `b51d3f1` 之前，所以 manifest 里 pinned 的 factor_registry_hash 是
扩展前的值。PRD F drift detection（按设计）将 factor_registry_hash 任何变化视为 halt-class。

## 影响评估

trial9 的 frozen feature_set = `beta_spy_60d, max_dd_126d, ret_1d`（cycle #05 trial 9 spec），
**不引用任何新加的 SR factors**。SR factors 只是 mining pool 的扩展（RESEARCH_FACTORS 是
研究 pool；只有显式 promote 进 PRODUCTION_FACTORS 才会进 execution）。

因此：
- trial9 实际 signal computation 不变
- trial9 NAV 不变
- trial9 forward OOS 观察的 vehicle 不变

这是一个**兼容性扩展**，drift detection 是 false-positive halt（按 PRD F 保守 fail-closed
设计 — 任何 contract change 都 halt，不区分 active 引用 vs pool 扩展）。

## 决策

`backfill_config_snapshot.py --force --manifest <trial9>` 重 stamp config_snapshot 到
当前 hash。Migration note = `backfilled_2026-05-05_assumed_unchanged_since_init`
（CLI 默认 stamp；该 stamp **不准确**反映真实情况 — 详见本 memo）。

重跑 `forward observe` 验证：

| 指标 | 值 |
|---|---|
| current_status | `in_progress`（保留） |
| n_runs         | 2（不变 — TD001 + TD002） |
| revalidate     | clean（无 drift event） |
| 新 TD          | 0（idempotent — TD002 已覆盖 2026-05-05） |

## Trail-of-Evidence

CLI 默认 migration_note `assumed_unchanged_since_init` **不准确**。真实情况是：
**factor_registry RESEARCH_FACTORS pool 扩展（+3 SR factors），trial9 spec 不引用新 factors，
backfill 是兼容性确认而非"假装未变"**。

将来从 manifest migration_note 反推变更原因时，应同时 grep
`docs/memos/20260505-trial9_backfill_factor_registry_extension.md`（本文件）。

## PRD F 改进建议（不在本 commit scope）

`backfill_config_snapshot.py` 缺少 `--migration-note` / `--reason` 参数。下一个
PRD F 维护周期应补 string 参数让 operator 自定义 note；默认仍为
`assumed_unchanged_since_init`。

## 反向回滚（如需）

```bash
git checkout HEAD~1 -- data/research_candidates/trial9_diversifier_001_forward_manifest.json
```

会还原到 backfill 前的 manifest（带 b51d3f1 之前的 factor_registry_hash + clean
in_progress 状态）。下次 observe 又会 trip halt。

## 不做的事

- 不 abort trial9（user explicit instruction：abort 状态不动）
- 不修改 RCMv1 / Cand-2 manifests（已 aborted，且 SR factor 扩展同样不影响他们）
- 不 revert b51d3f1（SR factors 是 6.1-min plumbing 的研究层依赖，正在使用）

## OOS 纪律

trial9 init 在 2026-05-04，TD001 = 2026-05-04，TD002 = 2026-05-05。Backfill 不读、
不改任何 2026-05-04+ 的 forward observation 数据；TD001/TD002 NAV / cum_ret 完全保留。
本动作不违反"5.4 起严格 OOS"纪律。
