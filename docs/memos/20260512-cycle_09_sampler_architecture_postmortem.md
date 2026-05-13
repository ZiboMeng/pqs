# cycle #09 Postmortem — sampler architecture mismatch with 17-family expansion

**Date**: 2026-05-12
**Status**: INVALID MINING RUN (not 0-nominee verdict)
**Lineage**: `track-c-cycle-2026-05-12-09`
**Yaml sha256**: `351e6e2ce004ef5a96a92ebe85f394ee193467dab78b60e4deb94c14ec0c424f`
**Mining wall-clock**: 2.1 min (200 TPE trials, ALL PRUNED at sampler stage)

---

## §1 TL;DR — 人话版

**cycle #09 不是 0 nominee verdict —— 是 mining 跑了但是因为 sampler 架构跟今天扩的 17 个 family 不匹配，200 个 trial 全部在采样阶段就被剪枝了。NO trial 真的进入 backtest evaluation。**

**人话**：今天我把因子库从 64 个扩到 162 个，对应 mining family 从 6 个扩到 17 个。但是 mining 的 TPE 采样器一直按"4-6 family"的假设设计，独立地让每个 family 抽 0-2 个因子。17 个 family × 平均 1 个因子 = 期望 17 个因子被采样，但 yaml 要求 composite_cardinality=3。命中率从 cycle04-08 的 2.74% 降到 0.0005%（4个数量级下降）。200 trials 全没命中。

**这是 sampler-architecture limitation，不是 alpha 不存在的证据**。所以不应该按 yaml.stop_rule_post_cycle.if_zero_nominee 触发 pivot —— 那个 stop rule 假设 "0 nominee = 没找到 alpha"，跟我们这里 "0 nominee = sampler 没真的跑" 完全不是一回事。

---

## §2 数值证据

### 2.1 实际跑出来的 trial state 分布

```
Total trials: 200
States: {'PRUNED': 200, 'COMPLETE': 0}
```

200/200 = 100% PRUNED. ZERO trials reached backtest evaluation.

### 2.2 PRUNED 原因（per `suggest_composite_spec`）

剪枝条件：
- `n_active_families < min_families (=3)` → PRUNE
- `len(unique_selected) != target_n_features (=3)` → PRUNE

实际 TPE 第一批随机采样（前 5 trial）：
- Trial #0: total=14 features across 9 active families (cardinality fail)
- Trial #1: total=12 features across 9 active families
- Trial #2: total=17 features across 11 active families
- Trial #3: total=23 features across 16 active families
- Trial #4: total=11 features across 7 active families

期望分布：17 families × suggest_int(0, 2) → 期望 total ≈ 17。目标 cardinality = 3。

### 2.3 命中率简谱

| Config | Families | max_per_family | P(valid spec) | Expected in 200 trials |
|---|---|---|---|---|
| cycle04-08 | 6 | 2 | **2.7435%** | ~5.5 archived ✓ |
| cycle #09 (current yaml) | 17 | 2 | **0.0005%** | ~0.001 archived ✗ |
| cycle #09 if max=1 (hypothetical) | 17 | 1 | 0.546% | ~1.1 archived (still poor) |
| cycle #09 if 10 families × max=1 | 10 | 1 | 11.7% | ~23 archived (workable) |

Confirmed via 100k-trial Monte Carlo simulation.

---

## §3 R4 audit failure analysis

**这个 bug 怎么没在 preflight audit R1+R2 抓到？**

- R1 factual: yaml 字段值都对、合法。
- R2 logical: explicit_exclusions ⊂ RESEARCH_FACTORS、qualifying_families 都存在、trial9_v2 manifest 存在。
- **R3 实际跑**: 我只跑了 smoke 16 trials — 16 trials × 0.0005% hit rate = expected 0.00008 archived. 期望 0 archived，所以 smoke 0 archived 看起来正常（合理化为"smoke 太少"，没追究是 sampler bug）。
- **R4 boundary**: 应该问 "为什么 cycle08 在 same yaml params 下 work？" — 没问。

**Lesson learned**: 当一个 cycle 跟历史 cycle 在 family 数量上发生数量级跳跃（6 → 17），preflight 必须包含 **combinatorics sanity check**（hit rate at random sampling）。如果 hit rate < 1%，sampler-architecture 需要重设计而不是只跑 mining。

[[feedback_audit_per_round_methodology.md]] 加一条：cycle-config 变化跨越数量级时（family count、cardinality、universe size），必须 numerical combinatorics check。

---

## §4 三种 path forward（需要 user directional decision）

### Option A: Sampler refactor（推荐为长期解）
重设计 `suggest_composite_spec` 为 family-first sampling：
1. 先 `trial.suggest_int("n_active_families", 3, 5)`
2. 再 `trial.suggest_categorical("families_subset", combinations(all_families, k))`
3. 每个 active family 内 `trial.suggest_categorical("factor", factors)`

**Pros**:
- P(valid spec) ≈ 100% — 每个 trial 都是 valid by construction
- 所有 future cycle 都受益
- 不需要 yaml 改动 — 现有 cycle #09 yaml 可以直接用新 sampler 重跑

**Cons**:
- 工程量约 1-2 天（含 cycle04-08 regression test 确保历史 archive 可重现）
- 引入新的 sampler dimension（families_subset 是 C(17,3..5) categorical = 数千 choices）— TPE 需要更多 trial 学习

### Option B: cycle #09b yaml with corrected combinatorics（推荐为短期解）
新 yaml `track-c-cycle-2026-05-12-09b`，调整：
- `factor_registry_pool`: 改为只覆盖 family G-P（10 个 new families，跳过 legacy A-F）
- `max_features_per_family: 1`（forces 1+1+1）
- `min_families: 3`

期望 archive rate ≈ 11.7% × 200 = ~23 trials。

**Pros**:
- 不需要 code change
- 立即可 fire
- 聚焦 cycle #09 真正的"new family anchor"目的（legacy A-F 本来就该被新 family 取代）

**Cons**:
- 新 yaml = 新 lineage = cycle #09 original yaml 标记 INVALID
- 仍然有 88% 的 trial 被 pruned（命中率仍偏低）— TPE 学习效率打折

### Option C: Halt cycle #09 + pivot to alt-archetype A intraday reversal（推荐为战略路径）
- cycle #09 = sampler-architecture mismatch, 视为 INVALID
- 不 trigger yaml.stop_rule_post_cycle (因为 stop rule 假设 alpha 不存在；这里 sampler 没真跑)
- alt-archetype A PRD 今天已扩充到 315 行 13 章；intraday reversal 是真正未开采方向
- 在 alt-A 实施过程中，可以并行做 Option A sampler refactor，让 cycle #10 reset 后可用

**Pros**:
- 战略 ROI 最高（intraday 是 PQS 真正未利用的 alpha 时间尺度）
- alt-A 已经 80% prep complete（PRD 13 章已写）
- sampler refactor 可以在 alt-A 实施期间并行做（不阻塞）

**Cons**:
- alt-A 需要 deferred-execution × BacktestEngine integration（约 1 周工程量）
- 不是"快速重试 cycle #09"路径

---

## §5 资深 quant 推荐

按 [[feedback_quant_operator_role.md]] 我应该独立给战略判断（不当 yes-man）：

**短期最佳**: **Option C**（pivot to alt-A）
理由：
1. cycle04-08 already proves daily monthly cap_aware top-N is sibling-locked. cycle #09 的设计是想突破这个 sibling，但即使 fix sampler 重跑，95% 概率仍然是 sibling（cycle03/04/05 的 78-stock universe 是 binding constraint，不是 factor source）
2. 真正破 sibling 的方向是 **time scale** 改变（daily → intraday）OR **strategy type** 改变（passive top-N → event-driven），不是 factor zoo 扩张
3. alt-A intraday reversal 是已经 prep 好的真正不同维度
4. Trial 9 v2 forward observation 已经活跃；cycle #09 暂时不出 nominee 不阻塞 fleet

**工程并行**: **Option A**（sampler refactor）
理由：
1. 17-family sampler architecture limitation 是 PQS 长期债务，cycle #10+ 都会撞到
2. 在 alt-A 实施的 1-2 周内并行做 sampler refactor 是合理时间分配
3. 重跑 cycle #09 在 sampler refactor 之后随时可以做（yaml 已 locked）

**不推荐 Option B 短期路径**: 命中率从 0.0005% 升到 11.7% 看起来够，但 88% trial 还是被剪枝，TPE 在 sparse space 学习效率差，最终结果仍可能 0 nominee — 然后还要再做 Option A 修 sampler。Option C+A 是更干净的路径。

---

## §6 Pending decisions

**Need user directional decide**:
1. Confirm Option C as primary path（halt cycle #09 + pivot to alt-A），是否同意？
2. Sampler refactor (Option A) 何时启动？立即 OR 等 alt-A 完成？
3. cycle #09 original yaml 标记 INVALID — 是否同意？markdown 标记 + 不删除 evidence trail。

**Tactical (我会做)**:
- 写 cycle #09 INVALID 标记 markdown
- Update CLAUDE.md cycle #09 entry to reflect sampler-architecture INVALID
- 在 cycle #10 yaml 起草前 ensure sampler refactor 完成

---

## §7 Lineage continuity

cycle #09 yaml + commits + closeout script 全部保留为 forensic evidence（NOT 删除）:
- yaml: `data/research_candidates/track-c-cycle-2026-05-12-09_promotion_criteria.yaml` (sha256 locked)
- launcher: `dev/scripts/cycle09/run_cycle09_mining.py`
- closeout: `dev/scripts/cycle09/cycle09_closeout_analysis.py`
- mining log: `data/ml/research_miner/track-c-cycle-2026-05-12-09/mining_stdout.log`
- this memo

未来 sampler refactor 完成后可以同 yaml 重新 fire 这个 cycle 验证 sampler fix。

---

*End of postmortem. Awaiting user directional decision on Options A/B/C.*
