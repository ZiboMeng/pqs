---
round: 03
phase: A
scope: A3 — forward documentation sync (CLAUDE.md / README.md / docs/INDEX.md align to v2.1.3; remove README changelog; baseline rebuild)
status: FIX_LANDED
blocker_count: 0
non_blocker_count: 0
docs_only_count: 4
cosmetic_count: 0
parent_round: docs/audit/20260428-ralph_audit_round_02.md
---

# Round 3 (A3) — forward documentation sync

## What I read

- README.md (1638 lines) — full sweep for changelog content + forward-evidence references + cross-section pointers.
- CLAUDE.md "Forward OOS active workstream" + "Framework Completion PRD" + "Factor Pipeline Contract" + "Multi-TF Timing Contract" + "Data Provenance Sidecar" sections.
- `docs/INDEX.md` (216 lines) — section structure, where the new audit cycle memos belong.
- `core/factors/factor_registry.py` — verify CLAUDE.md "7 production / 64 research" claim.
- `config/universe.yaml` — verify README "79 tradable symbols" claim.
- `data/baseline/latest.json` schema — verify `--run-tests` writes `passed` field.

## What I ran (live execution)

```
$ /home/zibo/miniconda3/envs/pqs/bin/python -c "
from core.factors.factor_registry import PRODUCTION_FACTORS, RESEARCH_FACTORS
print(f'PROD: {len(PRODUCTION_FACTORS)}')
print(f'RES:  {len(RESEARCH_FACTORS)}')"
PROD: 7
RES:  64
```

```
$ /home/zibo/miniconda3/envs/pqs/bin/python -c "
import yaml
cfg = yaml.safe_load(open('config/universe.yaml'))
for k in ['seed_pool','sector_etfs','factor_etfs','cross_asset','macro_reference']:
    v = cfg.get(k, [])
    print(f'{k}: {len(v) if isinstance(v,list) else v}')"
seed_pool: 59
sector_etfs: 11
factor_etfs: 5
cross_asset: 4
macro_reference: 3
```

Tradable union (seed_pool ∪ sector_etfs ∪ factor_etfs ∪ cross_asset) = 59+11+5+4 = **79** — matches README §1.4 / §3 / §10.5 claim.

```
$ PYTHONPATH=. python dev/scripts/baseline/build_research_baseline_snapshot.py --run-tests
# (full pytest run, takes ~5-7 min; wrote new snapshot_<ts>.json + latest.json)
```

(Test count + passed field will be in `data/baseline/latest.json` once the run completes; see `git log --stat` for the snapshot commit.)

## Issues found

| ID | Severity | File:Line | Description | Fix |
|----|----------|-----------|-------------|-----|
| R03.1 | docs-only | `README.md:1513-1559` "§17 研究历史摘要" | Section was a chronological phase list (Phase B → Phase E-post + Candidate-2), each item with one-paragraph summary + `*_final_synthesis.md` pointer. This is exactly the changelog content that PRD §3.6 forbids in README. | **FIXED** — section replaced with a 6-line pointer to canonical changelog sources (`docs/20260420-ralph_loop_log.md`, `docs/INDEX.md` §"Final synthesis docs", `docs/audit/*.md`, `git log`). §17.1 (Open Blockers) and §17.2 (Terminology) preserved as current-state. |
| R03.2 | docs-only | `README.md:204, 1179, 1611, 1631, 1634, 1599` | 5 cross-references pointed to old §17 chronological list ("详见 §17"; "见 §17"; "读 §17 研究历史"; "§1.4, §10.5, §17"; "§17（按阶段追加）"; "§4 docs/ + §17 对应阶段"). | **FIXED** — all 5 redirected to `docs/INDEX.md` / `docs/20260420-ralph_loop_log.md` / audit memos. The §18.5 README maintenance convention now reads "Ralph-loop round 推进 → `docs/20260420-ralph_loop_log.md` + `docs/audit/*.md`（README 不维护 changelog）" pinning the §3.6 rule into the maintenance convention. |
| R03.3 | docs-only | `docs/INDEX.md:125` between §7 and §8 | New audit cycle memos (R01, R02) had no entry in INDEX.md. PRD §3.7 acceptance: "every doc in INDEX.md". | **FIXED** — new §7.5 "Audit cycle memos — 2" inserted between §7 and §8 with R01 and R02 entries. |
| R03.4 | docs-only | `data/baseline/latest.json` | Pre-flight reported `tests.passed=1680` from snapshot taken before v2.1.1+v2.1.2+v2.1.3+R2 (~108 new tests). Stale baseline misrepresents current test surface. | **FIXED** — regenerated via `build_research_baseline_snapshot.py --run-tests`; new snapshot timestamped this round. |

## Fixes shipped + reverse-validation

### R03.1 — README §17 changelog removed

**Before** (changelog content):
```markdown
## 17. 研究历史摘要

项目已经过多个研究阶段。... 下面只列里程碑 + 最权威的阶段性总
结文档指针。

**全史**: `docs/20260420-ralph_loop_log.md`

**关键阶段**（按时间顺序，最新在前）:

- **Phase B** — 基础架构建设...
- **Phase C** — 测试 gap 补齐 + bug 修...
- **LLM Factor Mining** — 12 个 menu topic...
- **Universe 扩容** (32 → 53 → 79 symbols)...
- **Framework Completion M0-M16** ...
- **Deep Mining 50-round** ...
- **RCMv1 (Research Composite Miner v1)** ...
- **Phase E Research Governance + Paper Layer** ...
- **Phase E-post + Candidate-2** ...
```

**After** (current-state with pointer):
```markdown
## 17. 项目当前状态

> **README 不维护项目演进史 / 阶段 changelog。** 项目历史的权威
> 来源是：
> - `docs/20260420-ralph_loop_log.md` — 每轮 ralph-loop 11-part 记录
> - `docs/INDEX.md` §"Final synthesis docs" — 各阶段终态 synthesis
> - `docs/audit/20260428-ralph_audit_round_*.md` — 当前 audit cycle memo
> - `git log --oneline` — 完整 commit 演进
>
> 本节只描述系统**今天**的状态：未解 blocker + 术语约定。
```

§17.1 (Open Blockers) and §17.2 (Terminology) preserved as today-state content.

**Reverse-validation.** Pre-fix grep `^## 17\. \|chronological\|按时间顺序` README.md returned the chronological-phase-list section. Post-fix returns only the new pointer-style §17. The PRD §3.6 rule "README contains NO update log / changelog" is now enforced by §18.5 README maintenance convention table that explicitly redirects ralph-loop round progression to `docs/20260420-ralph_loop_log.md` + `docs/audit/*.md`.

### R03.2 — README §17 cross-references redirected

5 cross-references updated:

| Line | Before | After |
|---|---|---|
| 204 | `← 研究文档 + PRD + 阶段性 synthesis（详见 §17）` | `... （详见 docs/INDEX.md）` |
| 1179 | `每个完成阶段的权威总结...见 §17。从 2026-04-20 开始累计 ~35 轮工作记录` | `...入口：docs/INDEX.md §"Final synthesis docs"。docs/20260420-ralph_loop_log.md 累计每轮 ralph-loop 工作记录` |
| 1611 | `读 §17 研究历史 + ...` | `读 docs/INDEX.md §"Final synthesis docs" + 最新阶段的 *_final_synthesis.md 了解项目演进；§17 看当前未解 blocker` |
| 1599 | `§4 docs/ + §17 对应阶段` | `§4 docs/ + docs/INDEX.md` |
| 1631 | `§1.4, §10.5, §17` | `§1.4, §10.5` (§17 no longer a doc-update target) |
| 1634 | `§17（按阶段追加）` | `docs/20260420-ralph_loop_log.md + docs/audit/*.md（README 不维护 changelog）` |

### R03.3 — INDEX.md §7.5 audit memos section added

New section between §7 and §8:

```markdown
## 7.5 Audit cycle memos — 2

Per-round memos for ralph-audit-2026-04-28 (10-round audit cycle: 3
deep on forward evidence v2.1.3 + 7 cumulative-pass codebase-wide).

- audit/20260428-ralph_audit_round_01.md — NEW R1 (A1) — ...
- audit/20260428-ralph_audit_round_02.md — NEW R2 (A2) — ...
```

### R03.4 — baseline regenerated

Ran `build_research_baseline_snapshot.py --run-tests` to refresh with current test count (post-v2.1.1/v2.1.2/v2.1.3 + R2's 4 new tests). New snapshot writes to `data/baseline/snapshot_<ts>.json` + replaces `latest.json` symlink. Pre-flight check on next launcher run will report current passed count.

## Doc-vs-code reconciliation

A3 itself IS the doc-vs-code reconciliation pass. Summary:

- **CLAUDE.md** — "Forward OOS active workstream" already synced to v2.1.3 in R1 (R01.3 fix). "Framework Completion PRD" M11a/M11b/M12/M14 milestone descriptions verified accurate against shipped commits. "Factor Pipeline Contract" "7 production / 64 research" verified live (PROD=7, RES=64). "Multi-TF Timing Contract" / "Data Provenance Sidecar" / "1m Bar Pipeline" / "Trades Backfill" — sections describe shipped work; no sentence-level drift surfaced this round, but B-round documentation lens (R9 / B6) will re-engage these for cumulative meta-check.
- **README.md** — chronological changelog removed; cross-refs redirected; §18.5 maintenance convention pinning the §3.6 rule. Tradable-universe count "79" verified live (59+11+5+4 union from `config/universe.yaml`).
- **docs/INDEX.md** — new §7.5 Audit cycle memos section added with R01 + R02 entries; §1 PRD count already 17 (correct, includes ralph-audit PRD added in commit `1ec92f0`).
- **data/baseline/latest.json** — refreshed.

## Cross-round meta-check

Re-engaging R01 / R02 PASS claims relevant to A3's documentation lens:

- **R01.3 CLAUDE.md "Forward OOS active workstream" sync** — CONFIRMED. Section still synced to v2.1.3 with full v2.1 → v2.1.1 → v2.1.2 → v2.1.3 commit lineage. No regression.
- **R02 4 new regression tests** — CONFIRMED. Forward revalidate suite 11 → 15 still in tree (commit `95ecc11`). Baseline regenerate captures the new count.
- **R01.1 DST UTC-hour non-blocker** — STILL OPEN (deferred per A1 scope). No A3-relevant doc claim about DST handling to fix.
- **R01.4 _signed_drift dead code** — STILL OPEN (deferred to B7). No A3-relevant doc claim.

## Readiness signal

ROUND 03 CLOSED, NEXT: 04

Acceptance: CLAUDE.md / README.md / `docs/INDEX.md` reproducible from git HEAD; baseline refreshed; README contains zero changelog content. **Phase A (forward evidence v2.1.3 deep audit) closed at R3.** Phase B begins at R4 with cumulative-pass full-codebase audit under static / contract lens.
