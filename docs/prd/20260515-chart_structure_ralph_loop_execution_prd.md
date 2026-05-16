# Chart-structure 输入表征层 —— ralph-loop execution PRD(Phase 1-4)

**日期**: 2026-05-15
**状态**: v1 —— 待用户启动 loop。
**作者**: resident quant operator
**主 PRD**: `docs/prd/20260515-chart_structure_input_representation_prd.md` v2
**Lineage tag**: `chart-structure-input-repr-2026-05-15`
**loop log**: `docs/memos/20260515-chart_structure_loop_log.md`(每 round 追加
11-part 中文报告)

> 本文档**只管 round 切分**(怎么把主 PRD 拆成小步执行)。「建什么 / 验收
> 标准」全部以主 PRD 为准 —— 本文档每个 round 的验收门都是主 PRD AC 的
> 子集,不新增、不改动 AC。主 PRD 的 D1-D6 决策、§B 实现风险、§C provenance
> 纪律,本 loop 全程遵守。

---

## §1 TL;DR

主 PRD 有 4 个 Phase。本 execution PRD 把它们拆成 **17 个 round**(Phase 3
attempt round 可能再增),每个 round 是一个**小而可验收的 patch**:1-3 个
文件 + 测试 + 一份 11-part 报告,验收门是确定性检查。

loop 结构 = **每个 Phase 一个 sub-loop**,Phase 之间用主 PRD 的 fire-trigger
当硬 checkpoint:

```
P1 loop (3 round)  →  P2A loop (2)  →  P2B loop (4)  ┐
                                                      ├─ P4 loop (3) ∥ P3-3B
                                                      └─ P3 loop (5+) ── 3A 等 P4
全 4 Phase closeout  →  CHARTSTRUCTUREDONE
```

---

## §2 Loop 纪律

### §2.1 round 的两种类型(验收标准不同)

- **build round**:确定性产物(模块 / schema / 接线)。验收 = 命名单测
  green + 映射的 AC 全过。无悬念。
- **experiment round**:跑实验(incremental-IC、CNN attempt),结果未知。
  验收 = **「实验执行了 + 产物/attempt JSON 存在 + verdict 记录了 + 若负
  则有 root-cause」**,**不是**「实验成功」。

### §2.2 negative 实验不终止 loop(D2)

experiment round 出负结果 → 该 round **仍 PASS**(它做完了该做的)。是否
继续由主 PRD 的 **config-scoped abort 逻辑**决定(§4.6 / §5.7)——
abort 只暂停某个 config / attempt,不暂停 Phase、不终止 loop。**禁** blanket
verdict。loop 不得因单个 negative 实验自我终止。

### §2.3 每 round 收尾固定动作

1. 跑该 round 验收门的全部命名单测 + 全量 `pytest`(G1)。
2. commit + push(specific files,不 `git add -A`)。
3. 向 `docs/memos/20260515-chart_structure_loop_log.md` 追加 11-part 中文
   报告(主 CLAUDE.md Phase D 格式:本轮主题 / 目标 / 为什么这轮 / 做了
   什么 / 改了哪些文件 / 跑了什么测试 / 结果 / 新问题 / 剩余风险 / 下一轮
   方向 / TODO)。
4. 4-tier 自审(R1 事实 / R2 逻辑 / R3 实跑对比 / R4 边界)。

### §2.4 Phase checkpoint + termination promise

每个 Phase 末 round = closeout round,产出 phase closeout memo,发出 phase
termination promise:`CHARTSTRUCT-P1-DONE` / `-P2A-DONE` / `-P2B-DONE` /
`-P3-DONE` / `-P4-DONE`。4 个 Phase 全 closeout → 发 `CHARTSTRUCTUREDONE`。
Phase 间 checkpoint:下一 Phase 的 fire-trigger(主 PRD §x.6/§x.7)未满足
则 loop 在此 Phase 边界暂停,等条件 / 等用户。

### §2.5 不变量

CLAUDE.md 全部不变量 + 主 PRD §7 全部 cross-cutting 纪律 + §B 7 条实现风险
缓解 + §C provenance 纪律,loop 全程适用。任何新数字进产物前先按 §C 登记
来源。

---

## §3 锁定的 open questions(loop 跑前定死,免得中途卡)

主 PRD §10 的 open questions,loop 执行需要的部分在此锁定(operator 判断;
用户可改):

| 主 PRD §10 | 锁定值 | 理由 |
|---|---|---|
| q1 Phase 2A 显著阈值 | paired t-test `p < 0.05` + 同时报 ICIR 提升幅度 | 双报,标准统计 |
| q2 expanded universe 成分 | **不锁** —— P4·R2 内含一个 polygon 覆盖度 audit 子步,audit 后定成分 | 需数据依据,不能拍脑袋(§C 纪律)|
| q3 Phase 3 图像编码先做哪个 | **GAF(GASF+GADF)先做** | 确定性变换、无绘图歧义 |
| q4 embedding 维度 / 窗口 | window_len=63、embedding_dim=64 起步 | = `SmallEncoder` 的 `seq_len=63`/`d_model=64`(FACT 默认,非幻想)|
| q5 `K`(swing lookback)| Phase 2A 内 sweep `K ∈ {6, 8, 12}` | 主 PRD §10 q5 已列;K 是 PLACEHOLDER |
| q6 MiniROCKET 依赖 | **~200 行 numpy 自实现**,不引 `sktime`/`pyts` | 不给 PQS 加重依赖(§B-B... 依赖风险)|
| q7 corpus 粒度 | 先 daily-only freeze;manifest schema 预留 multi-timeframe 字段 | 避免 schema 返工 |

`tol` / `maturity_cap` 是 PLACEHOLDER —— **不在 §3 锁定**,由 Phase 2A 的
incremental-IC 标定(它们影响特征值,属实验范畴,不是 loop 配置)。

---

## §4 Phase 1 loop —— swing 段结构 family T(`CHARTSTRUCT-P1`)

主 PRD §3。3 个 build round。fire:立即(D1)。

| Round | 类型 | 目标 / 交付 | 验收门(machine-checkable)| 量化产出 | 估时 |
|---|---|---|---|---|---|
| **P1·R1** | build | causal swing 核心:`core/factors/swing_structure.py` 骨架 + `confirmed_swings_asof` + 布尔→交替序列(§B-B2 规则:连续同 kind 取更极端者)+ `SwingPoint` / `SwingStructureConfig` dataclass | 主 PRD **P1-A2** 因果 hard test(`test_swing_structure_causal`)green;B2 交替序列单测 green | 2 个命名单测 green | 0.5-1 天 |
| **P1·R2** | build | 12 个特征:`compute_swing_structure_factors` + 12 feature 算子 + `FEATURE_REGISTRY` + `SWING_STRUCTURE_FEATURES` + `config/swing_structure.yaml`(P1-d1 / P1-d2)| **P1-A1** `test_swing_structure_ranges` green;**P1-A6** `test_swing_structure_config_sourced` green | 12 特征产出;ranges 测试 green | 1-1.5 天 |
| **P1·R3** | build | registry 接线 + closeout:RESEARCH_FACTORS 175→187(P1-d3)、`FAMILY_T_SWING_STRUCTURE`→FAMILIES_V2 19→20(P1-d4)、`factor_generator` 接线(P1-d5)、计数 tripwire 更新(P1-d6)+ Phase 1 closeout memo | **P1-A3** reachability `union==RESEARCH_FACTORS` + 计数 187/20;**P1-A4** `test_family_t_sampled`(固定 seed,T∈采样集);**P1-A5** 全量 `pytest` green | 187 / 20;全量套件 green | 0.5-1 天 |

**P1 checkpoint**:P1-A1..A6 全过 → 发 `CHARTSTRUCT-P1-DONE`。Phase 2 fire
条件 = P1-A1..A6 全过(主 PRD §4.6)。

---

## §5 Phase 2A loop —— incremental-IC 配对检验(`CHARTSTRUCT-P2A`)

主 PRD §4.2。1 build + 1 experiment round。fire:`CHARTSTRUCT-P1-DONE`。

| Round | 类型 | 目标 / 交付 | 验收门 | 量化产出 | 估时 |
|---|---|---|---|---|---|
| **P2A·R1** | build | incremental-IC harness:`dev/scripts/chart_structure/phase2a_incremental_ic.py`(P2-d1)—— baseline = Phase 1.6 canonical(`rank:ndcg`/n=200/lr=0.05);**配对 run 设 `colsample_bytree=1.0`**(§B-B3 修复);12-fold LOTYO | harness 单测:col-diff 断言 `set(cols_treat)−set(cols_baseline)=={12 family T 名}`;smoke panel 上跑通 | harness 在 smoke panel 跑通 | 2-3 天 |
| **P2A·R2** | **experiment** | 跑 incremental-IC(`K ∈ {6,8,12}` sweep)+ Phase 2A closeout memo | **P2-A1** 报告 JSON 含 `mean(ΔIC)`/`std`/paired-t `p`/95% CI;**P2-A2** closeout 有 `verdict_scope` 字段(机器代理)+ 措辞人工复核 | ΔIC mean / p-value(每个 K);verdict 记录 | 2-3 天 |

**experiment round 说明**:P2A·R2 验收 = 实验跑了 + 报告存在 + verdict
记录(config-scoped)。ΔIC 为正 → Phase 3-3B fire 条件之一满足。ΔIC ≤ 0
且 CI 含 0 → 按主 PRD §4.6 config-scoped abort:root-cause(特征构造 /
`tol`·`maturity_cap` 标定 / horizon)→ 迭代 family T 或换 horizon,**不**
终止 loop;Phase 2B 仍照常(embedding 是独立表示轴)。

**P2A checkpoint**:发 `CHARTSTRUCT-P2A-DONE`。

---

## §6 Phase 2B loop —— bridge + 自监督表示层(`CHARTSTRUCT-P2B`)

主 PRD §4.3。4 round。fire:`CHARTSTRUCT-P1-DONE`(2B 与 2A 都只 dep P1;
排在 2A 后执行)。

| Round | 类型 | 目标 / 交付 | 验收门 | 量化产出 | 估时 |
|---|---|---|---|---|---|
| **P2B·R1** | build | bridge baseline:`core/ml/subsequence_transforms.py` —— MiniROCKET-style random convolution transform,**~200 行 numpy 自实现**(§3 q6)(P2-d2)| **P2-A3** 模块 + 命名单测 + 下游 IC 报告 JSON 存在 | bridge 特征维度;下游 IC | 3-4 天 |
| **P2B·R2** | build | 自监督表示:`core/ml/window_embedding.py` —— TS2Vec 式 hierarchical contrastive encoder + GASF/GADF 变换 + patch 视图(`representation_view ∈ {raw_window, GASF_GADF, patch_tokens}`)(P2-d3)| **P2-A4** 命名单测;GASF/GADF/patch 对已知输入 numerical sanity test | embedding_dim(起步 64);sanity 测试 green | 4-6 天 |
| **P2B·R3** | build | 预训练语料 manifest:`data/manifests/chart_structure_pretrain_corpus_v1.json`(P2-d4)—— daily-only freeze + `train_years_only=true` + universe 字段 + multi-timeframe schema 预留 | **P2-A5** schema 校验 + `train_years_only=true` + `test_corpus_no_sealed_window` green | manifest 字段数;样本数;no-sealed 测试 green | 1-2 天 |
| **P2B·R4** | build | 注入路径 + closeout:bridge/embedding → `feature_panel_builder` 注入(P2-d5)+ Phase 2B closeout(P2-d6)+ 结构化 `phase2_attempts.json`。(P2-d7 prototype library = 可选,默认不在本 round,evidence-gated)| **P2-A6** 注入后 `build_ml_panel` 回归 green;**P2-A7** `phase2_attempts.json` schema 校验 | 注入回归 green;closeout 存在 | 2-3 天 |

**P2B checkpoint**:P2-A3..A7 全过 → 发 `CHARTSTRUCT-P2B-DONE`。

---

## §7 Phase 3 loop —— chart-native 模型(`CHARTSTRUCT-P3`)

主 PRD §5。**build round + attempt round 混合**。attempt round 数**不预设
魔数** —— 按 attempt 结果迭代(§C 不幻想:不假装知道要几次)。fire:见各
round。

| Round | 类型 | 目标 / 交付 | 验收门 | 量化产出 | 估时 |
|---|---|---|---|---|---|
| **P3·R1** | build | 3B structure-sequence encoder:扩展 `transformer_encoder.SmallEncoder` 吃 family T 段序列(每段 len/dur/slope/dir)(P3-d2)| **P3-A5** `test_phase3b_uses_confirmed_swings`(断言走因果 swing 段序列);encoder 在 smoke panel 训练通 | encoder smoke 训练 loss 曲线 | 4-6 天 |
| **P3·R2** | **experiment** | 3B attempt(s) + eval:每 attempt 一份 `data/audit/chart_structure/phase3_attempt_<id>.json` | **P3-A1** attempt JSON schema 校验;**P3-A3** eval 输出含 `eval_method`/`cost_model`/`turnover_penalty` 字段 | 每 attempt 的 IC / vs baseline | 3-5 天 |
| **P3·R3** | build | 3A image-CNN:`core/ml/chart_cnn.py` —— GAF(GASF+GADF)→ CNN(§3 q3 先 GAF)(P3-d1)。**fire 额外 gated on `CHARTSTRUCT-P4-DONE`**(universe 扩大)+ GPU 环境(§B-B4)| `chart_cnn` 在 smoke 数据 build + 训练通;attempt JSON schema | CNN smoke 训练通 | 5-7 天 |
| **P3·R4** | **experiment** | 3A attempt(s) + eval | P3-A1 / P3-A3 同上 | 每 attempt IC / vs baseline | 3-5 天 |
| **P3·R5** | build | 3C fusion(`core/ml/fusion_model.py`,P3-d3)+ Phase 3 closeout(P3-d5)| **P3-A2** 失败 attempt 有 `root_cause` 字段(机器)+ 无 blanket verdict(人工);**P3-A4** closeout 有 `vs_tabular_baseline` 数值块 | fusion vs baseline;closeout | 4-6 天 |

**attempt round 可重复**:P3·R2 / P3·R4 若需多次 attempt,记为 R2a/R2b…,
每次一份 attempt JSON。**experiment 纪律同 §2.2**:负结果 round 仍 PASS,
abort config-scoped(§5.7),不终止 loop、不下「CNN 不行」(D2)。

**P3 checkpoint**:P3-A1..A5 全过 + Phase 3 closeout → 发 `CHARTSTRUCT-P3-DONE`。

---

## §8 Phase 4 loop —— universe expansion(`CHARTSTRUCT-P4`)

主 PRD §6。3 round。fire:`CHARTSTRUCT-P2A-DONE`(与 P2B/P3-3B 交错)。D6
隔离硬约束全程适用。

| Round | 类型 | 目标 / 交付 | 验收门 | 量化产出 | 估时 |
|---|---|---|---|---|---|
| **P4·R1** | build | universe resolver + flag plumbing:`core/universe/universe_resolver.py`(P4-d2)+ `--universe {executable\|expanded_v1}` flag。**先完整 grep 枚举所有 universe 加载点**(§B-B6),不留「等」| **P4-A1** `resolve_universe` 单测 + `test_universe_flag_all_entrypoints`(遍历完整入口清单);**P4-A2** `--universe executable` 下 bit-for-bit 回归对照 baseline snapshot | 入口数;bit-for-bit 回归 PASS | 4-6 天 |
| **P4·R2** | build | expanded universe:polygon 覆盖度 audit(§3 q2)→ 定 `config/universe_expanded_v1.yaml` 成分 → ingest(走 BarStore + `bar_provenance.parquet`)(P4-d1)+ integrity smoke(P4-d3)| **P4-A4** 过 `data_completeness_gate` + weekend-row / cross-symbol date smoke | universe N 只;completeness PASS | 5-8 天 |
| **P4·R3** | build | 隔离回归 + closeout:universe 隔离回归测试(P4-d4)+ Phase 4 closeout | **P4-A3** forward manifest diff == 空;P4-A2 复跑确认;§6.4 五条全过 | 隔离回归 PASS;closeout | 2-3 天 |

**P4 checkpoint**:P4-A1..A4 + §6.4 五条全过 → 发 `CHARTSTRUCT-P4-DONE`
(解锁 P3·R3 的 3A image-CNN)。

---

## §9 全 round 汇总 + 执行顺序

| # | Round | Phase | 类型 | 估时 |
|---|---|---|---|---|
| 1 | P1·R1 | 1 | build | 0.5-1 天 |
| 2 | P1·R2 | 1 | build | 1-1.5 天 |
| 3 | P1·R3 | 1 | build + closeout | 0.5-1 天 |
| 4 | P2A·R1 | 2A | build | 2-3 天 |
| 5 | P2A·R2 | 2A | experiment + closeout | 2-3 天 |
| 6 | P2B·R1 | 2B | build | 3-4 天 |
| 7 | P2B·R2 | 2B | build | 4-6 天 |
| 8 | P2B·R3 | 2B | build | 1-2 天 |
| 9 | P2B·R4 | 2B | build + closeout | 2-3 天 |
| 10 | P4·R1 | 4 | build | 4-6 天 |
| 11 | P4·R2 | 4 | build | 5-8 天 |
| 12 | P4·R3 | 4 | build + closeout | 2-3 天 |
| 13 | P3·R1 | 3 | build | 4-6 天 |
| 14 | P3·R2 | 3 | experiment | 3-5 天 |
| 15 | P3·R3 | 3 | build | 5-7 天 |
| 16 | P3·R4 | 3 | experiment | 3-5 天 |
| 17 | P3·R5 | 3 | build + closeout | 4-6 天 |

**执行顺序**:`P1(1-3) → P2A(4-5) → P2B(6-9) ∥ P4(10-12) → P3(13-17)`。
P2B 与 P4 可并行(都只 dep P1/P2A);P3-3B(13-14)可在 P4 完成前做,
P3-3A(15-16)等 `CHARTSTRUCT-P4-DONE`。

**估时**:17 round 累计 ~47-69 工作日;Phase / round 间有并行与等待,
日历周期 ~9-14 周(与主 PRD §9 一致)。**估时是工程判断、非实测**;每
round 11-part 报告回填实际工时(§C 纪律)。

---

## §10 本 execution PRD 的验收

| # | 项 | 判据 |
|---|---|---|
| E1 | 每 round 是小 patch | 1-3 个核心文件 + 测试 + 报告;不跨 round 堆改动 |
| E2 | 每 round 有确定性验收门 | 验收门全部映射主 PRD 的 machine-checkable AC(Tier-M),见 §4-§8 表 |
| E3 | 每 round 量化产出 | §4-§8 表「量化产出」列均有数值/test-count/PASS 标的 |
| E4 | experiment round 不被误判 | 负结果 round 仍 PASS;loop 不因负实验自终止(§2.2)|
| E5 | 4 Phase 全收口 | 5 个 phase termination promise 全发 → `CHARTSTRUCTUREDONE` |
| E6 | 不新增/不改 AC | 本文档只切 round,AC 一律以主 PRD 为准 |
| E7 | 每 round 11-part 报告 + 4-tier 自审 | loop log 可查 |

---

## §11 启动

本 execution PRD v1 → 用户启动(`/loop` 或明确指示)。operator **不自启**
autonomous loop。loop 从 P1·R1 开始,逐 round 执行 §2.3 收尾动作,Phase
边界按 §2.4 checkpoint 暂停 / 推进。

lineage `chart-structure-input-repr-2026-05-15`;loop log
`docs/memos/20260515-chart_structure_loop_log.md`。
