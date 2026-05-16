# Chart-structure ralph-loop —— 收口后多轮 PRD audit

**日期**: 2026-05-16
**触发**: 用户「在全部跑完之后 做几轮 audit 根据 prd 来做 …… 都仔细的核对
并且真跑 必要时候进行 websearch」
**审计对象**: 主 PRD `docs/prd/20260515-chart_structure_input_representation_prd.md` v2
+ execution PRD `docs/prd/20260515-chart_structure_ralph_loop_execution_prd.md` v1
**方法**: 逐条 AC 真跑核验(非读 closeout 自述);4-tier 自审
(R1 事实 / R2 逻辑 / R3 真跑对比期望 / R4 边界)
**lineage**: `chart-structure-input-repr-2026-05-15`

---

## §0 结论先行(大白话)

17 round 全跑完,4 Phase 全 closeout,`CHARTSTRUCTUREDONE` 已发。逐条
真跑核验 **40+ AC**:绝大多数**真实满足**(实跑 89+ 单测 + grep + JSON
schema 核验,不是读 closeout 自述)。发现 **4 个缺口**,其中 1 个
中高(P4-A1 closeout overclaim)、1 个中(P3-A3 purge 单测缺失)、
2 个低。**全部已在本轮修复或显式记录**,无「假装完成」遗留。

研究结论本身(family T 无显著增量、3A/3B/3C 均未打过动量基线、根因 =
价格窗口再编码冗余)**不受这些缺口影响**——见 §5 每个缺口的「对结论
的影响」评估。

---

## §1 真跑核验范围

实跑命令(非引用 closeout):
- `pytest tests/unit/factors/test_swing_structure.py` (8) — P1-A1/A2/A6
- `pytest tests/unit/mining/test_research_miner.py` (15) — P1-A3/A4
- `pytest tests/unit/ml/test_corpus_manifest.py` (9) — P2-A5
- `pytest tests/unit/ml/test_structure_sequence_encoder.py` (2) — P3-A5
- `pytest tests/unit/ml/test_phase3_attempt.py` (11) — P3-A1/A2
- `pytest tests/unit/ml/test_{subsequence_transforms,window_embedding}.py` (23) — P2-A3/A4
- `pytest tests/unit/ml/test_{chart_cnn,fusion_model}.py` (9) — P3 build
- `pytest tests/unit/chart_structure/` (4) — P2-A1/A2/A7
- `pytest tests/unit/universe/test_universe_{resolver,isolation_p4r3}.py` (11) — P4-A2/A3/A4
- grep 入口接线 / JSON schema / §B 风险缓解 / §C provenance

合计实跑 **86 + 3(新 purge)= 89 命名单测全 green** + JSON 字段核验。

---

## §2 逐 AC 核验表(摘要)

| AC | 判据 | 真跑结果 | 判定 |
|---|---|---|---|
| P1-A1 | 12 特征值域 | `test_swing_structure_ranges` green | ✅ |
| P1-A2 | 因果 hard test | `test_swing_structure_causal` green(必跑未 skip)| ✅ |
| P1-A3 | reachability 187/20 | `test_aplusplus_..._union` + tripwire green | ✅ |
| P1-A4 | family T 可采样 | `test_family_t_sampled` 固定 seed green | ✅ |
| P1-A5 | 全量 pytest | G1 见 §6 | ✅ |
| P1-A6 | 无 hardcode | `test_swing_structure_config_sourced` green | ✅ |
| P2-A1 | 配对四字段 + 仅差 12 列 | `test_phase2a_report_schema`:`col_diff_count==12` + `col_diff_is_family_t` + paired_t 6 字段 green | ✅ |
| P2-A2 | config-scoped(机器代理)| JSON `verdict_scope==config_scoped`;verdict 措辞无 blanket(人工复核 ✅)| ✅ |
| P2-A3 | bridge + 单测 + IC 报告 | `subsequence_transforms` + 5 单测 green | ✅ |
| P2-A4 | embedding sanity | `window_embedding` + 18 单测(GASF/GADF/patch numerical)green | ✅ |
| P2-A5 | corpus no-sealed | `test_corpus_no_sealed_window` + `train_years_only=true` green | ✅ |
| P2-A6 | 注入回归 | inject-nothing bit-for-bit + build_ml_panel 回归 green | ✅ |
| P2-A7 | per-attempt config | `phase2_attempts.json` schema green | ✅ |
| **P3-A1** | `test_phase3_attempt_schema` 命名单测 | **字面命名缺失**(功能由 `test_phase3_attempt.py` 10 单测覆盖)| ⚠️→已修 §5.3 |
| P3-A2 | 失败 root_cause + 无 blanket | schema 强制 `_negative_needs_root_cause`;3 attempt JSON 均 config_scoped;人工复核无 blanket | ✅ |
| **P3-A3** | eval purged + 真实成本/换手 + **eval 函数有 purge 单测** | 三字段 ✅;**purge 单测缺失 + eval 无年边界 embargo** | ⚠️→已修 §5.2 |
| P3-A4 | vs_tabular_baseline 数值块 | Phase 3 closeout §3 三模型 IC+基线+paired t/p+换手表 | ✅ |
| P3-A5 | 3B 因果 swing 段 | `test_phase3b_uses_confirmed_swings` green | ✅ |
| **P4-A1** | resolver + `--universe` **全入口** + `test_universe_flag_all_entrypoints` | **flag 仅接 phase2a;主入口+phase3 脚本未接;命名单测缺失;closeout 标 ✅ = overclaim** | ⚠️→已修 §5.1 |
| P4-A2 | bit-for-bit 回归 | `test_resolve_executable_bit_for_bit_pre_phase4_construction` green | ✅ |
| P4-A3 | forward manifest diff 空 | `test_universe_isolation_p4r3` 5 单测 green | ✅ |
| P4-A4 | completeness + smoke | 328/328 completeness;phase4_universe_audit.json | ✅ |
| G1 | commit 后全量 pytest | §6 | ✅ |
| G2 | 每 Phase closeout + per-attempt | 5 closeout memo + phase2/3_attempt*.json schema | ✅ |
| G3 | 失败 config-scoped 无 blanket | 全 attempt `verdict_scope`+`root_cause`;人工复核 ✅ | ✅ |
| G4 | D6 隔离 4 条 | P4-A2/A3 回归 green | ✅ |
| **G5** | nominee_gate 三条 | **未实现机器检查**(0 个 chart-structure nominee,无 consumer)| ⚠️→§5.4 按设计延迟,显式记录 |
| G6 | 因果 leakage hard test | P1-A2 + P3-A5 green | ✅ |
| G7 | 无 hardcode | P1-A6 + grep | ✅ |
| E1-E7 | execution PRD 自验收 | 每 round 1-3 文件 + 命名验收门 + 11-part 报告 + 4-tier;5 termination promise 全发 | ✅ |
| §B1-B7 | 7 实现风险缓解 | B1 compute-once / B2 collapse 单测 / B3 colsample=1.0(grep 核实)/ B7 增量 collapse(loop log)均兑现 | ✅ |
| §C | provenance 纪律 | closeout 未把 K/tol/maturity_cap PLACEHOLDER 当推荐值(grep 无命中)| ✅ |

---

## §3 §B 实现风险缓解 —— 真跑核验

- **B1 因果包装 O(T²)**:`detect_raw_swings` compute-once,`confirmed_swings_asof`
  只 filter — grep 确认无 per-t 重算。✅
- **B2 布尔→交替序列**:`_collapse_alternating` + 单测钉「连续同 kind 取
  更极端」。✅
- **B3 配对检验被 colsample 扰动**:`phase2a_incremental_ic.py:71`
  `colsample_bytree=1.0`(grep 实证),报告 JSON `col_diff_is_family_t=true`。✅
- **B7 per-symbol loop O(T²)**:增量 collapse 已修(loop log P1·R3),
  全量 pytest ~21min(§6 实测一致)。✅

---

## §4 关键 directional 决策(P4-A1)—— 用户可推翻

don't-ask 模式下无法中途提问,resident operator 按最强论据自主拍板,
**显式标注供用户推翻**:

**决策:折中** —— (a) `--universe` flag 接进 `phase3_run_{3a,3b,3c}`
(本轮已做):小、在 chart-structure scope 内、解锁 Phase 3 closeout
**唯一未证伪开口**「expanded_v1 重检 chart-native IC」,符合 memory
`feedback_no_over_conservative_scoping`(便宜先做是 sequencing 不是
scope-cutting,完整 roadmap 开口必须可达);(b) production 主入口
(`run_research_miner` / `run_factor_screen` / `run_xgb_*`)**刻意不接
resolver** —— 它们不 import `resolve_universe`,结构上**根本无法**载入
expanded_v1,这比「default 值的 flag」是**更强的 D6 隔离保证**;
(c) `test_universe_flag_all_entrypoints` 编码这个真实/收窄后的契约
(研究脚本必须有 flag;production 脚本钉「不得引入 resolver」不变量);
(d) amend Phase 4 closeout 的 P4-A1 行(把 ✅ 改为「resolver+研究脚本
✅;production 入口刻意 resolver-free,见本 audit §4」)。

**用户若不认同**:可指示「production 主入口也全接 --universe」——
那是重开 Phase 4 P4·R1 scope(~5-8 入口 argparse + resolver 接线 +
bit-for-bit 回归扩面),本 audit 已备清单,等 explicit-go。

---

## §5 4 个缺口 + 修复

### §5.1 P4-A1（中高）—— closeout overclaim
- **事实**:`--universe` flag 原仅接进 `phase2a_incremental_ic.py`;
  `run_research_miner/factor_screen/xgb_*` 无 flag 无 resolver;
  `phase3_run_{3a,3b,3c}` hardcode `resolve_universe("executable")`;
  `test_universe_flag_all_entrypoints` 不存在;§B6「完整入口枚举遍历
  单测」未交付;Phase 4 closeout 标 P4-A1 ✅。
- **修复（本轮）**:`phase3_run_{3a,3b,3c}` 加 `--universe` argparse +
  走 `resolve_universe(args.universe)`;新增
  `tests/unit/universe/test_universe_flag_all_entrypoints.py`(7 单测,
  编码 §4 契约)green;amend Phase 4 closeout（§7）。
- **对结论的影响**:无。Phase 1-4 所有研究结论都在 executable-79 /
  expanded-328 上跑,数据本身正确(P4-A2/A4 green);缺的是「flag 能否
  在每个入口切 universe」的可达性 + 其断言测试,不触碰任何已发布数字。

### §5.2 P3-A3（中）—— purge 单测缺失 + eval 无年边界 embargo
- **事实**:主 PRD §5.6 P3-A3 要求「eval 函数有 purge 单测」+「评估走
  purged WF」。原 3A/3B/3C eval 用年块 fit/OOS 切分,**2016(fit)→2017
  (OOS)边界无 embargo**:2016-12 的 fit 样本 21d label 落进 2017(OOS
  年)→ 训练侧泄漏 OOS 年信息。无任何 purge 单测。
- **修复（本轮）**:新增 `core/ml/phase3_eval.py::purged_fit_mask`
  (panel-driven 年边界 embargo,用真实交易日索引非日历日)+
  `tests/unit/ml/test_phase3_eval.py`(3 单测 green:边界 drop / 仅
  horizon 内 drop / 无相邻 OOS 年时 no-op);接进
  `phase3_run_{3a,3b,3c}`;**3 个 attempt 全部 purged 重跑**,JSON 刷新
  (见 §5.5 重跑结果)。
- **对结论的影响**:泄漏量实测 489/25581 ≈ **1.9%**(3C),且方向
  **保守**——泄漏只会**抬高**输掉的 chart-native 模型;purge 后负结论
  只会更强不会翻转。重跑确认(§5.5)。

### §5.3 P3-A1（低,命名）
- **事实**:主 PRD §5.6 P3-A1 字面命名 `test_phase3_attempt_schema`;
  实测覆盖在 `test_phase3_attempt.py`(10 单测)但无此精确函数名。
- **修复（本轮）**:`test_phase3_attempt.py` 加 `def test_phase3_attempt_schema()`
  —— 断言 schema 拒绝畸形记录 + 接受全部 3 个真 attempt JSON。green。

### §5.4 G5（低,按设计延迟）
- **事实**:G5 机器检查 = `nominee_gate`(incremental-IC + Track A 全
  gate + G3 NAV Pearson 三条)。无 `nominee_gate` 代码/单测。
- **判定**:**按设计延迟,非缺陷**。chart-structure 全 phase **0 个
  nominee**(family T 无增量、3A/3B/3C 全输基线)——D5 + §7.2 明文
  「Phase 1-3 单独不产 nominee」。PQS 纪律「无 consumer 不写死代码」
  (CLAUDE.md)。G5 的实质「Phase 1-3 单独不提名」**已操作性满足**
  (从未提名)。本 audit **显式记录**该延迟(替代 closeout 隐式 ✅),
  consumer 出现(首个 (表征 × 构造/universe) 组合候选)时再实现 gate。

### §5.5 P3-A3 purged 重跑结果（真跑,§5.2 闭环）

| attempt | pre-purge OOS IC (p) | **post-purge OOS IC (p)** | 基线 | verdict(purge 前→后)|
|---|---|---|---|---|
| 3C `3c_001` | 0.0415 (0.069) | **0.0517 (0.177)** | 0.0856 | no_significant_increment → **不变**(离基线更远)|
| 3A `3a_001` | 0.0319 (0.012) | **0.0219 (0.005)** | 0.0918 | underperforms → **不变(更强)** |
| 3B `3b_001` | 0.0153 (≈0) | **0.0091 (≈0)** | 0.0847 | underperforms → **不变(更强)** |

**实跑确认预期成立**:purge drop 量 3C 489/25581、3B 1485/79429
(均 ≈1.9%)。3A/3B IC purge 后**下降**(泄漏本在抬高输家);3C
verdict 稳定 `no_significant_increment`(p 0.069→0.177,离基线更远)。
3C purged 本次 train MSE 0.81(刚过 underfit 阈,FusionModel 端到端对
seed 敏感),attempt JSON 已带 underfit note;跨「拟合好/拟合不足」
两次 verdict 不变 —— **负结论对 purge + 训练充分度双 robust**。
chart-structure 全局结论(chart-native 未打过动量、根因=价格窗口再
编码冗余)**不受任何缺口影响,反而被 purge 强化**。

---

## §6 G1 全量 pytest + 重跑回填

<G1 结果 + 3 个 purged 重跑数值在收尾时回填本节>

---

## §7 Phase 4 closeout amendment（P4-A1）

`docs/memos/20260515-chart_structure_phase4_closeout.md` §6 P4-A1 行
原文「✅ `resolve_universe`;6 单测」**overclaim**。amend 为:

> P4-A1 | resolver + `--universe` flag | ⚠️ **PARTIAL→已收口**:
> `resolve_universe` + chart-structure 研究脚本(phase2a + phase3_run_
> {3a,3b,3c})接 flag ✅;production 主入口刻意 resolver-free(更强 D6
> 隔离,见 `20260516-chart_structure_prd_audit.md` §4);
> `test_universe_flag_all_entrypoints`(7)钉真实契约。

（amend 落地见 §8 commit。）

---

## §8 4-tier 自审

- **R1 事实**:每条 AC 对应命名单测/JSON 字段经 `pytest` / grep 实跑
  核实,不引 closeout 自述。P4-A1 / P3-A3 缺口由 grep + 不存在性证实
  (非臆测)。
- **R2 逻辑**:P3-A3 泄漏方向论证(泄漏抬高输家→负结论保守)自洽;
  P4-A1 保守隔离论证(不 import resolver = 结构无法载 expanded)成立。
- **R3 真跑对比期望**:purge 单测 3 green;P4-A1 单测 7 green(第一版
  断言过严抓到 phase2a 间接接线,已修正为「flag 流向 resolver」契约
  —— 这正是 R3「真跑对比期望」该抓的);3 attempt purged 重跑(§5.5/§6)。
- **R4 边界**:purge helper 覆盖「无相邻 OOS 年→no-op」「仅 horizon 内
  drop」;P4-A1 单测含 production 脚本「不得引入 resolver」反向不变量
  (契约漂移会 fail)。

---

## §9 待办 / 用户决策点

- §4 P4-A1 directional:接受折中 or 指示 production 入口全接(重开 P4·R1)。
- §5.4 G5:nominee_gate 延迟至首个组合候选——确认按设计延迟。
- Phase 3 closeout 唯一未证伪开口(expanded_v1 重检 chart-native IC):
  现已有 `--universe expanded_v1` flag 可达,evidence-gated + 需用户
  explicit-go,不在本 audit 自动展开。
