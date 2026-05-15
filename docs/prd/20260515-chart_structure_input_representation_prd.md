# Chart-structure 输入表征层 PRD —— ML Mining Pipeline 的上游补全

**日期**: 2026-05-15
**状态**: v1 —— 用户决策已拍板（D1-D6,见 §1.3）,待 codex 审。
**作者**: resident quant operator
**上游 memo**: `docs/memos/20260515-chart_structure_ml_pipeline_memo.md` (v2)
**相邻 PRD**: `docs/prd/20260512-ml_mining_pipeline_prd.md`(ML 模型层 ——
本 PRD 是它的**上游输入表征层**,两者衔接、不重复)
**Lineage tag**: `chart-structure-input-repr-2026-05-15`

---

## §1 TL;DR — 大白话

### §1.1 这份 PRD 解决什么

PQS 现在所有因子都是「图 → 压成一个标量 → 横截面排名 → top-N」。图的
**结构信息**(形状、多段序列、多指标联合状态)在进 ML 之前就被丢掉了。
本 PRD 建一条 pipeline,把 K 线 / 蜡烛图 / 形态结构(含艾略特波浪指向的
swing 段结构)转成**比单标量更有信息量、但仍可被 IC / Track A / sealed
漏斗检验**的表征,逐级喂给 ML 模型。

### §1.2 为什么不是「换个 ML 模型就行」

pre-audit 已确认(memo v2 §2 + §5):
- PQS **不缺 ML 基建** —— `core/ml/` 已有 feature_panel_builder /
  xgb_alpha / xgb_ranking / transformer_encoder 4 个模块。
- PQS **不缺把因子喂 ML 的能力** —— Phase 1.6 的 `rank:ndcg` XGBoost
  已经做到 linear baseline 的 94%。
- 真正卡住的是**两件相互独立的事**:
  (a) 比标量因子更有信息量的**结构化输入**(本 PRD 主攻);
  (b) 能让候选 NAV 跳出 **sibling-by-construction 簇**的构造 / universe
  改动(本 PRD §6 + §7.2 处理)。
- 光做 (a) 不会产出新 fleet 候选 —— sibling 簇是 construction-bound
  (3 个独立证据,见 memo v2 §5.2)。所以本 PRD 必须把 (a) 和 (b) 一起做。

### §1.3 用户拍板的 6 个决策(2026-05-15,不可在无 explicit-go 下推翻)

| # | 决策 | 内容 |
|---|---|---|
| **D1** | PRD 范围 | **全 staged roadmap 一次 commit**。便宜先做 = 执行顺序,不是 scope。Phase 1-4 全部 committed,各有 fire trigger。「不要把 scope 限制在小范围,永远 mine 不出 alpha core」 |
| **D2** | 深度 CNN | **确定要走**。每次 attempt 记录确切架构+config+panel;失败只写「这个 attempt 失败」+ root-cause;**禁止 blanket verdict「CNN 不行」** |
| **D3** | 优先级 | 与 forward fleet soak **并行**,不互相冻结 |
| **D4** | 波浪特征范围 | **先 12 个**(§3.2),family T 留扩展开口 |
| **D5** | fleet 资格 | 结构特征过 incremental-IC gate **不自动**成 fleet 候选 —— 必须叠加构造/universe 自由度 + 过 G3 anti-sibling(§7.2) |
| **D6** | universe 隔离 | universe expansion **不得影响任何之前的结论/方法**;必须有显式 flag 指定 universe;cycle04-12 + 所有 forward candidate 的 79-universe 结论保持有效(§6.4) |

### §1.4 4 个 Phase 一句话

- **Phase 1**(便宜,先做):swing 段结构 family T —— 12 个确定性结构特征,
  进 RESEARCH_FACTORS。~2-3 天。
- **Phase 2**:结构输入有没有新增信息 —— 复用 Phase 1.6 `rank:ndcg` 跑
  incremental-IC 检验 + TS2Vec 式自监督 embedding。~2-3 周。
- **Phase 3**:chart-native 模型 —— 图像-CNN + structure-sequence
  transformer + image/tabular fusion。~3-5 周。
- **Phase 4**:universe expansion —— 新增独立 universe(显式 flag),
  79 → 200-500+,给图像/表征模型样本 + 撬动 sibling 簇。~2-3 周。

---

## §2 Background

### §2.1 本地真实状态(pre-audit 已验证)

| 资产 | 路径 | 状态 |
|---|---|---|
| ZigZag swing 检测器 | `core/intraday/sr_swing.py`(`detect_swing_extrema` / `compute_nearest_sr` / `distance_to_sr` / `SwingConfig`) | 已实现 + 有测试 |
| swing 距离因子 | `factor_generator._sr_swing_factors`(`dist_to_swing_high/low_20d`) | 已上线,只用了距离,没用段序列 |
| 多路径因子面板 | `core/ml/feature_panel_builder.py`(162-factor + 横截面 rank) | 已实现 |
| XGBoost 排序模型 | `core/ml/xgb_ranking.py`(`rank:ndcg` = Phase 1.6 canonical) | 已实现 + 测试 |
| transformer scaffold | `core/ml/transformer_encoder.py`(`SmallEncoder` 1-layer) | research scaffold |
| ML 模型层 PRD | `docs/prd/20260512-ml_mining_pipeline_prd.md` | Phase 1-4 已规划 |

**结论**:Phase 1 的 swing 段结构特征是**增量扩展**(复用现成 ZigZag
检测器),不是白纸起步。

### §2.2 sibling-by-construction —— 本 PRD 必须正视的硬约束

memo v2 §5.2:cycle04-09b 的 sibling-by-NAV 有 3 个独立确认 —— 换因子
(cycle07a Trial 3 只共享 1/4 因子仍 raw 0.874)、换 seed(cycle09b §5.3
raw 0.761)、换目标函数(Phase 1.6 rank:ndcg raw 0.829-0.845)都跳不出
同一簇。根因是构造:`cap_aware_cross_asset × monthly × top-10 ×
79-universe`。

已知能撬动它的自由度:改选择规则 / 改加权 / 改 universe / 改 cadence。
**本 PRD 的 Phase 4(universe)+ §7.2(构造自由度)就是冲这个去的。**

### §2.3 本 PRD 与 ML Mining Pipeline PRD 的边界

- `20260512-ml_mining_pipeline_prd.md` 管**模型**:XGBoost → multi-horizon
  → cross-sectional Transformer → RL。
- 本 PRD 管**喂给模型的输入表征**:swing 段结构 → embedding → 图像/
  序列表示。
- 衔接点:本 PRD Phase 2/3 产出的表征,通过 `feature_panel_builder` 进入
  ML PRD 的模型 phase。**不重复模型实现。**

---

## §3 Phase 1 — Swing 段结构 family T(便宜,先做)

### §3.1 Hypothesis

价格序列压成 swing 段序列之后,段与段之间的长度比 / 斜率比 / 重叠度 /
斐波那契贴合度,携带**标量因子塌不进去的结构信息**;其中至少一部分对
21d forward return 有独立 IC。

### §3.2 Architecture — 12 个特征(D4 锁定起步集)

新文件 `core/factors/swing_structure.py`,复用
`core/intraday/sr_swing.detect_swing_extrema`:

| # | 特征 | 含义 |
|---|---|---|
| 1 | `seg_count_up` | 当前结构里上升段计数 |
| 2 | `seg_count_down` | 下降段计数 |
| 3 | `last_seg_len_ratio` | 最近一段长度 / 前一段长度(主升浪强度代理) |
| 4 | `last_seg_slope_ratio` | 最近一段斜率 / 前一段斜率 |
| 5 | `fib_retrace_fit_382` | 最近回撤对 0.382 的贴合度 |
| 6 | `fib_retrace_fit_618` | 最近回撤对 0.618 的贴合度 |
| 7 | `impulse_score` | 连续同向且递进的程度(推动浪代理) |
| 8 | `corrective_score` | 重叠震荡的程度(调整浪代理) |
| 9 | `trend_maturity_0_1` | 趋势相位连续分(刚突破→主升→衰竭) |
| 10 | `swing_high_low_overlap_pct` | 摆动高低点重叠度(浪 4 重叠代理) |
| 11 | `seg_len_dispersion` | 段长离散度(规则 vs 不规则结构) |
| 12 | `since_last_swing_bars` | 距最近确认摆点的 bar 数 |

**扩展开口(D4)**:`swing_structure.py` 暴露一个 `FEATURE_REGISTRY` dict,
新特征加一个 entry 即可;不改 family 注册逻辑。后续 research 方向(谐波
形态、多 TF swing、成交量加权 swing)按 IC 证据增补。

### §3.3 Leakage 纪律(hard test,非 best-effort)

- swing 检测必须 **causal**:第 t 日特征只能用 ≤ t 的**已确认**摆点。
  ZigZag 的摆点要等后续 bar 确认 —— 严禁用未来 bar 确认当前摆点。
- 单测必须含:给定截断到 t 的面板 vs 完整面板,t 日特征值**逐位相等**。
- 标签区间重叠时,下游 IC 评估走 purged + embargo(对齐
  `core/research/temporal_split.purge_labels_at_boundary`)。

### §3.4 Deliverables

- `core/factors/swing_structure.py`(12 特征 + `FEATURE_REGISTRY`)
- `factor_registry.py`:RESEARCH_FACTORS +12 → family T;FAMILIES_V2 +1
- `research_miner.py`:`FAMILY_T_SWING_STRUCTURE` 进 FAMILIES_V2_EXTENDED
- 单测:≥ 20(含 §3.3 causal/leakage hard test + 各特征数值 sanity)
- 更新 reachability-contract 计数测试(参照本会话 Family R/S 先例)

### §3.5 Engineering estimate

~2-3 天。

### §3.6 Fire trigger

**立即** —— 用户已 explicit-go(D1)。

### §3.7 Abort condition(config-scoped,per D2)

不存在「Phase 1 abort」—— Phase 1 只是造特征,不下 alpha 结论。特征 IC
弱由 Phase 2 裁判;弱特征留在 RESEARCH_FACTORS 由漏斗淘汰,不删模块。

---

## §4 Phase 2 — 结构输入有没有新增信息

### §4.1 Hypothesis

H2a:family T 结构特征加进 ML 输入,会让 `rank:ndcg` 的 OOS Rank IC
**显著**高于不含结构特征的版本(incremental IC > 0)。
H2b:OHLCV 窗口的自监督 embedding(TS2Vec 式)下游 IC ≥ Phase 1.6
富特征基线。

### §4.2 Architecture

**Phase 2A — incremental-IC 检验(复用现成基建,无新模型)**:
- baseline = Phase 1.6 canonical config(`rank:ndcg`,lr=0.05,n=200,
  `multi_2016_2017` inner-val,88 OHLCV 因子)。
- treatment = baseline + family T 12 特征。
- 度量 = OOS Rank IC / ICIR 差值,12-fold LOTYO,报 mean + std。
- **incremental IC 必须用配对检验**(同 fold 同 seed,只差结构特征),
  不是两次独立跑比 headline。

**Phase 2B — 自监督 embedding**:
- 子路 2B-1:OHLCV window → TS2Vec / 对比学习 → 窗口 embedding 向量。
- 子路 2B-2:OHLCV → GAF / recurrence plot 2D 表示(为 Phase 3 图像
  分支铺路)。
- embedding 进 `feature_panel_builder` 当额外特征列,下游仍走 `rank:ndcg`。

### §4.3 Deliverables

- `dev/scripts/chart_structure/phase2a_incremental_ic.py` + 配对检验报告
- `core/ml/window_embedding.py`(TS2Vec 式 encoder + GAF/recurrence 变换)
- embedding → `feature_panel_builder` 接入 + 单测
- Phase 2 closeout memo(含每个 attempt 的确切 config 记录,per D2)

### §4.4 Engineering estimate

Phase 2A ~1 周;Phase 2B ~1-2 周。

### §4.5 Fire trigger

Phase 1 family T 已 ship + 因子注册 + 单测过。

### §4.6 Abort condition(config-scoped)

- Phase 2A:若 family T incremental IC 配对检验 **mean ≤ 0 且 95% CI 含 0**
  → 记录「这一组 12 特征 + rank:ndcg config 未显示新增信息」,root-cause
  (是特征构造问题?ZigZag 阈值问题?还是 21d horizon 噪声?)→ 据
  root-cause 迭代 family T(D4 扩展开口)或换 horizon。**不下「结构信息
  不存在」的 blanket verdict**(per D2)。
- Phase 2B:embedding 下游 IC < Phase 2A 富特征 → 记录该 encoder
  架构+超参,root-cause,迭代;不结论「embedding 不行」。

---

## §5 Phase 3 — chart-native 模型(D2:确定要走)

### §5.1 Hypothesis

把图的结构以 2D 图像 / 段序列直接喂给视觉/序列模型,在
purged walk-forward + 真实成本 + 换手惩罚下,能持续打败 tabular baseline
—— 至少在某个 universe / horizon 子域上。

### §5.2 Architecture(3 个并行分支)

- **3A 图像-CNN**:OHLC / candlestick / GAF 图像 → CNN(JKX 2023 式)。
- **3B structure-sequence encoder**:family T 段序列 → 扩展
  `core/ml/transformer_encoder.py` 的 `SmallEncoder`。
- **3C image + tabular fusion**:CNN + MLP / CNN + tree-stack。
- training target:next-horizon return rank bucket / 横截面 score。
- 三分支不预设谁赢,deep-research-report 纪律:chart-native 模型是
  **ensemble 候选**,不是默认主模型 —— 要在裁判下挣席位。

### §5.3 CNN 方法论纪律(D2 硬要求,写入 PRD 不可省)

1. **每次 attempt 必须记录**:确切架构(层数/通道/kernel)、超参、训练
   panel、universe flag、图像编码方式、随机种子。落地为
   `data/audit/chart_structure/phase3_attempt_<id>.json`。
2. **失败结论的措辞**:只能是「architecture X + config Y 在 universe Z
   上 attempt 失败」,**禁止**「CNN 不行」「图像方法不行」这类 blanket
   verdict。
3. **失败必须 root-cause**:是样本量不够?过拟合?图像编码丢信息?
   标签噪声?leakage?—— root-cause 写进 attempt JSON + closeout,
   再决定迭代方向。
4. **abort 只暂停 config,不暂停技术类别**:Phase 3 abort memo 必须
   明确「暂停的是这个 attempt,chart-CNN 类别保持 open」。
   (先例:Phase 1.5「ML 不行」被 Phase 1.6 推翻,因为只是目标函数选错。)

### §5.4 Deliverables

- `core/ml/chart_cnn.py`(3A)+ `transformer_encoder.py` 扩展(3B)+
  `core/ml/fusion_model.py`(3C)
- `data/audit/chart_structure/phase3_attempt_*.json`(每 attempt 一份)
- Phase 3 closeout(per-attempt config 表 + root-cause + IC/Track A 结果)

### §5.5 Engineering estimate

~3-5 周(依赖 Phase 4 universe 是否就位;79-universe 上先做 3B/3C 原型,
3A 图像-CNN 等 Phase 4)。

### §5.6 Fire trigger

Phase 2A 显示 family T 有正的 incremental IC,**或** Phase 2B embedding
下游 IC 不弱于富特征基线 —— 二者任一成立即可 fire(structure-sequence
3B 分支)。3A 图像-CNN 分支额外 gated on Phase 4 universe ≥ 200 只。

### §5.7 Abort condition(config-scoped,per §5.3)

见 §5.3 第 4 条 —— abort 只暂停 attempt,不暂停类别;abort 必须附
root-cause。

---

## §6 Phase 4 — universe expansion(D6:严格隔离)

### §6.1 Hypothesis

把 universe 从 79 扩到 200-500+,(a) 给图像/表征模型足够训练样本,
(b) 撬动 sibling-by-construction 簇 —— 让 chart-structure 候选有机会
过 G3 anti-sibling。

### §6.2 Architecture

- 新增独立 universe 声明文件:`config/universe_expanded_v1.yaml`
  (Russell-1000 large+mid 子集,目标 200-500 只),**不动**
  `config/universe.yaml` / `config/executable_universe.yaml`。
- 数据 ingest:新 universe 的 daily bars 走现有 BarStore 管线,写
  `data/ref/bar_provenance.parquet`;不重建已有 79 只的任何 parquet。
- 所有读 universe 的代码路径加 **显式 flag**
  `--universe {executable|expanded_v1}`,默认 `executable`(= 现状 79)。

### §6.3 Deliverables

- `config/universe_expanded_v1.yaml` + ingest 脚本
- universe flag 贯穿 miner / factor panel / 评估脚本
- bar-level data integrity smoke(weekend-row scan + cross-symbol date
  intersection,per memory `feedback_bar_level_data_integrity_smoke`)
- universe 隔离回归测试(见 §6.4)

### §6.4 D6 隔离硬约束(不可妥协)

1. universe expansion **不得修改或重算** cycle04-12 / 所有 forward
   candidate / Phase 1.5-1.6 的任何已发布数字。
2. 默认 universe = `executable`(79)。expanded universe 只在显式
   `--universe expanded_v1` 下生效。
3. **回归测试**:同一 mining/eval 脚本在 `--universe executable` 下
   产出与本 PRD 之前 **bit-for-bit 一致**(对照 baseline snapshot)。
4. forward candidates(cycle06/08 evidence / PEAD / options / trial9
   线)的 panel 完全不受影响 —— Phase 4 不 touch 它们的 manifest。
5. universe flag 写进每个产物的 metadata,任何引用必须能追溯用的哪个
   universe。

### §6.5 Engineering estimate

~2-3 周(数据 ingest + 完整性校验是主要工作量)。

### §6.6 Fire trigger

Phase 2A/2B 出结果后即可 fire(universe 与 Phase 3 交错推进);
图像-CNN(3A)依赖它,所以不晚于 Phase 3 3A。

### §6.7 Abort condition

universe ingest 数据完整性 gate(`data_completeness_gate`)不过 → 修数据,
不 abort 整个 Phase;若扩 universe 后 IC/Track A 无改善,记录「这个
universe 子集 + 这个模型 attempt」结果,root-cause,不结论「universe
expansion 无用」。

---

## §7 Cross-cutting 纪律

### §7.1 因子走漏斗(CLAUDE.md 不变量)

任何阶段产出的特征 / embedding / 模型分数,裁判永远是 IC / Track A /
sealed / NAV correlation。波浪理论、CNN 架构、embedding 方法只负责
**启发**,不负责下结论。没有任何波浪计数被当 ground truth。

### §7.2 anti-sibling gate(D5 写死)

chart-structure 衍生的候选成为 **fleet nominee** 的充要条件:
1. 结构特征 / 模型有正的 incremental OOS IC(Phase 2 证据);**且**
2. 通过 Track A acceptance(17/18 gate,含修好的 MaxDD sign 检查);**且**
3. 通过 G3 anti-sibling:raw NAV Pearson < 0.85 **且** residual < 0.50
   vs 所有现役 anchor(RCMv1 / Cand-2 / cycle06 / cycle08 / Trial9 线)。

第 3 条大概率要求候选叠加构造 / universe 自由度(§2.2)—— 只做更好的
输入、不动构造,过不了 G3。**PRD 写死:Phase 1-3 单独不产 nominee;
nominee 必须是 (输入表征 × 构造/universe 自由度) 的组合。**

### §7.3 sealed / temporal split 纪律

- 2026 sealed window 对 split `alternating_regime_holdout_v1` **已 consumed**
  (本会话 cycle06/08)。本 PRD 任何候选要过 sealed,需 split_name bump。
- 默认只读 train_years;validation / sealed 是 holdout(memory
  `feedback_temporal_split_discipline`)。
- WebSearch 只查方法/论文,禁查当前年 market behavior 数据(memory
  `feedback_websearch_sealed_data_discipline`)。

### §7.4 与 forward fleet 并行(D3)

本 PRD 全程与 cycle06/08 + PEAD + options 的 60 天 soak 并行。forward
verdict 只决定 fleet 组合,不冻结本 PRD 的任何 phase。

---

## §8 Acceptance — PRD 级验收

| # | 验收项 | 判据 |
|---|---|---|
| A1 | Phase 1 family T ship | 12 特征 + 注册 + ≥20 单测(含 leakage hard test)全过 |
| A2 | reachability contract | FAMILIES_V2 ∪ == RESEARCH_FACTORS,计数测试同步 |
| A3 | Phase 2A 配对检验 | incremental IC 报 mean+std+CI;结论 config-scoped |
| A4 | Phase 3 attempt 记录 | 每 attempt 一份 JSON(架构/config/panel/universe/seed) |
| A5 | D2 措辞合规 | 所有 closeout 无 blanket「X 不行」verdict;失败均有 root-cause |
| A6 | D6 universe 隔离 | `--universe executable` 下 bit-for-bit 回归通过;forward manifest 未受影响 |
| A7 | D5 anti-sibling | 任何 nominee 提名前过 §7.2 三条;Phase 1-3 单独不提名 |
| A8 | 全量测试 green | 每个 commit 后 `pytest` 全绿 |

---

## §9 Engineering estimate 汇总

| Phase | 内容 | 估时 | 依赖 |
|---|---|---|---|
| 1 | swing 段结构 family T | 2-3 天 | 无(立即 fire) |
| 2A | incremental-IC 检验 | ~1 周 | Phase 1 |
| 2B | 自监督 embedding | ~1-2 周 | Phase 1 |
| 3 | chart-native 模型(3A/3B/3C)| ~3-5 周 | Phase 2 + (3A 需 Phase 4) |
| 4 | universe expansion | ~2-3 周 | Phase 2(与 3 交错) |

总计 ~9-14 周,但 Phase 间可重叠;Phase 1 立即开工。

---

## §10 Open questions(转实施前可议)

1. Phase 2A 的 incremental-IC「显著」阈值 —— 用 paired t-test p<0.05,
   还是 ICIR 提升幅度门槛?(operator 倾向 paired t + ICIR 双报。)
2. Phase 4 expanded universe 的具体成分 —— Russell-1000 子集如何取?
   数据源(polygon 覆盖度)需先 audit。
3. Phase 3 图像编码规格 —— OHLC bar 图 vs candlestick vs GAF,哪个
   先做?(operator 倾向先 GAF,确定性变换、无绘图歧义。)
4. embedding 维度 / 窗口长度 —— 待 Phase 2B 设计 memo 细化。

---

## §11 后续

本 PRD v1 → codex 审 → 据审计意见修订 → Phase 1 开工。
实施日志将记于 `docs/memos/` 按 phase closeout,lineage tag
`chart-structure-input-repr-2026-05-15`。
