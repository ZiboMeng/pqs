# Chart-structure 输入表征层 PRD —— ML Mining Pipeline 的上游补全

**日期**: 2026-05-15
**状态**: v2 —— 用户决策 D1-D6 已拍板;已做 codebase audit + 6 轮 websearch;
implementation-ready + audit-ready。
**作者**: resident quant operator
**上游 memo**: `docs/memos/20260515-chart_structure_ml_pipeline_memo.md` (v2)
**相邻 PRD**: `docs/prd/20260512-ml_mining_pipeline_prd.md`(ML 模型层 ——
本 PRD 是它的上游输入表征层,衔接不重复,见 §2.4)
**Lineage tag**: `chart-structure-input-repr-2026-05-15`

> **本 PRD 的使用方式**:每个 Phase 含「Spec(可据此 implement)」+
> 「Acceptance(可据此审计/验收)」两套。Acceptance 编号即审计 checklist。
> §A 附录给出已核实的本地代码 API,implement 时直接引用。

---

## §1 TL;DR

### §1.1 解决什么

PQS 现在所有因子都是「图 → 压成一个标量 → 横截面排名 → top-N」。图的
**结构信息**(形状、多段序列、多指标联合状态)在进 ML 之前就丢了。本 PRD
建一条 pipeline,把 K 线 / 形态结构(含艾略特波浪指向的 swing 段结构)转成
**比单标量更有信息量、仍可被 IC / Track A / sealed 漏斗检验**的表征,逐级
喂给 ML 模型。

### §1.2 为什么不是「换个 ML 模型就行」(pre-audit 结论)

- PQS 不缺 ML 基建(`core/ml/` 已 4 个模块,见 §A.2)。
- PQS 不缺把因子喂 ML 的能力(Phase 1.6 `rank:ndcg` XGBoost 已做到
  linear baseline 的 94%,不是 Phase 1.5 误报的 42%)。
- 真正卡住的是**两件独立的事**:(a) 比标量更有信息量的结构化输入(本
  PRD 主攻);(b) 能让候选 NAV 跳出 **sibling-by-construction 簇**的构造 /
  universe 改动。sibling 簇是 construction-bound —— 换因子、换 seed、换
  目标函数都跳不出(3 个独立证据,memo v2 §5.2)。**光做 (a) 不产 fleet
  候选**;本 PRD 把 (a)(Phase 1-3)和 (b)(Phase 4 + §7.2)一起做。

### §1.3 用户拍板的 6 个决策(2026-05-15,无 explicit-go 不得推翻)

| # | 决策 | 内容 |
|---|---|---|
| **D1** | PRD 范围 | **全 staged roadmap 一次 commit**。便宜先做 = 执行顺序,不是 scope-limiting。Phase 1-4 全 committed,各有 fire trigger。 |
| **D2** | 深度 CNN | **确定要走**。每次 attempt 记录确切架构+config+panel;失败只写「这个 attempt 失败」+ root-cause;**禁止 blanket verdict「CNN 不行」**。 |
| **D3** | 优先级 | 与 forward fleet soak **并行**,不互相冻结。 |
| **D4** | 波浪特征范围 | **先 12 个**(§3.3),`swing_structure.py` 留 `FEATURE_REGISTRY` 扩展开口。 |
| **D5** | fleet 资格 | 结构特征过 incremental-IC gate **不自动**成 fleet 候选 —— 必须叠加构造/universe 自由度 + 过 G3 anti-sibling(§7.2)。 |
| **D6** | universe 隔离 | universe expansion **不得影响任何之前的结论/方法**;必须显式 flag 指定 universe;cycle04-12 + 所有 forward candidate 的 79-universe 结论保持有效,不被追溯失效(§6)。 |

### §1.4 4 个 Phase 一句话 + 依赖图

```
Phase 1  swing 段结构 family T (12 特征)        ~2-3 天   立即 fire
   │
   ├──> Phase 2A incremental-IC 检验            ~1 周     dep: P1
   │       (复用 Phase 1.6 rank:ndcg)
   ├──> Phase 2B bridge + 自监督表示层           ~1-3 周   dep: P1
   │       (MiniROCKET/shapelet/dictionary + TS2Vec/GAF/patch)
   │
   ├──> Phase 3  chart-native 模型               ~3-5 周   dep: P2(3A 还需 P4)
   │       3A image-CNN / 3B structure-seq / 3C fusion
   │
   └──> Phase 4  universe expansion              ~2-3 周   与 P2/P3 交错
           (显式 --universe flag, 79→200-500+)
```

---

## §2 Background

### §2.1 本地真实状态(codebase audit 已核实,§A 给签名)

| 资产 | 路径 | 状态 |
|---|---|---|
| ZigZag swing 检测器 | `core/intraday/sr_swing.py` | 已实现 + 有测试,**但 NON-CAUSAL**(§2.2)|
| swing 距离因子 | `factor_generator._sr_swing_factors` | 已上线,只用距离没用段序列 |
| 多路径因子面板 | `core/ml/feature_panel_builder.py` | 已实现,接受任意因子 dict(§A.2)|
| XGBoost 排序模型 | `core/ml/xgb_ranking.py::XGBRankingModel` | 已实现 + 测试,`rank:ndcg` 可用 |
| transformer scaffold | `core/ml/transformer_encoder.py::SmallEncoder` | 1-layer scaffold,未接线 |
| ML 模型层 PRD | `docs/prd/20260512-ml_mining_pipeline_prd.md` | Phase 1-4 已规划 |
| 图像 / GAF / CNN 代码 | —— | **不存在**,Phase 3 从零起 |
| `--universe` flag | —— | **不存在**,Phase 4 新增 plumbing |

### §2.2 关键发现:swing 检测器 NON-CAUSAL(audit + websearch 双确认)

`detect_swing_extrema(bars, n=5)` 用窗口 `[i-n, i+n]` 判定 bar i 是否
swing 极值 —— **用了未来 n 根 bar**。websearch 同样确认:标准 ZigZag
「calculation requires future price information」。

- 后果:bar i 的 swing 身份只在 i+n 日才能确认。
- 现成 `compute_nearest_sr` 已 lag-aware(只用 j-n 之前的 swing);但
  raw `detect_swing_extrema` 输出是非因果的。
- **本 PRD 硬要求(§3.4)**:Phase 1 必须实现因果包装
  `confirmed_swings_asof(...)` —— 第 t 日特征只能用确认 bar(swing_idx+n)
  ≤ t 的 swing。这是 Phase 1 的核心正确性要求,不是 best-effort。

### §2.3 sibling-by-construction —— 本 PRD 必须正视的硬约束

memo v2 §5.2:cycle04-09b 的 sibling-by-NAV 有 3 个独立确认 —— 换因子
(cycle07a Trial 3 共享 1/4 因子仍 raw 0.874)、换 seed(cycle09b §5.3
raw 0.761)、换目标函数(Phase 1.6 rank:ndcg raw 0.829-0.845)都跳不出
同一簇。根因 = 构造 `cap_aware_cross_asset × monthly × top-10 ×
79-universe`。能撬动它的自由度:改选择规则 / 改加权 / 改 universe / 改
cadence。Phase 4 + §7.2 冲这个去。

### §2.4 与 ML Mining Pipeline PRD 的边界(audit 已确认无重复)

- `20260512-ml_mining_pipeline_prd.md` §5 = **cross-stock attention**
  (TabTransformer,股票之间每日互相 attend,listwise rank loss)。
- 本 PRD Phase 3 = **chart-native**(单股 chart 图像 CNN / swing 段序列
  encoder)。**输入域不同,不重复。** 本 PRD Phase 2B/3 产出的表征可
  作为额外特征**插入** ML PRD §5 的 Transformer。

---

## §3 Phase 1 — Swing 段结构 family T

### §3.1 Hypothesis

价格序列压成 swing 段序列后,段间长度比 / 斜率比 / 重叠度 / 斐波那契
贴合度,携带标量因子塌不进去的结构信息;至少一部分对 21d forward
return 有独立 IC。
外部支持(websearch):Vantuch-Zelinka-Vasant 2018 给出确定性 Elliott
波形检测算法;「complete impulsive wave 比 incomplete 预测更好」;「用
ZigZag 结构做趋势过滤可消除约 60% 假动量信号」—— 说明结构基元有信息,
但裁判仍是 PQS 漏斗。

### §3.2 数据结构定义(implement 必须按此)

**因果 swing 序列**:对 symbol 的 adjusted close 序列,用
`detect_swing_extrema(bars, n)` 得 raw 极值,再过因果包装(§3.4)得
*confirmed swing 序列* —— 一串交替的 `(idx_i, price_i, kind_i)`,
`kind ∈ {HIGH, LOW}`。

**段(segment)**:相邻两 swing 之间的移动。段 j 从 swing_j 到
swing_{j+1}:
- 价格幅度 `len_j = |price_{j+1} − price_j|`
- 持续 bar 数 `dur_j = idx_{j+1} − idx_j`
- 方向 `dir_j = sign(price_{j+1} − price_j)`(+1 上升 / −1 下降)
- 斜率 `slope_j = (price_{j+1} − price_j) / dur_j`

**lookback 窗口**:第 t 日特征基于「截至 t 已确认的最近 `K` 个 swing」
(`K` ∈ config,默认 8 → 7 段)。不足 K 个 → 特征 NaN(XGBoost 原生
处理)。

### §3.3 12 个特征(D4 锁定起步集,exact 定义)

设截至 t 已确认最近段序列 `seg[0..m-1]`(m ≤ K−1,seg[m−1] 最新)。

| # | 特征 | 定义(formula) |
|---|---|---|
| 1 | `seg_count_up` | `#{j : dir_j = +1}` |
| 2 | `seg_count_down` | `#{j : dir_j = −1}` |
| 3 | `last_seg_len_ratio` | `len[m−1] / len[m−2]`;m<2 → NaN;分母 0 → NaN |
| 4 | `last_seg_slope_ratio` | `|slope[m−1]| / |slope[m−2]|`;同上边界 |
| 5 | `fib_retrace_fit_382` | 若 seg[m−1] 与 seg[m−2] 反向:`r = len[m−1]/len[m−2]`,`fit = max(0, 1 − |r − 0.382| / tol)`;否则 NaN。`tol` ∈ config,默认 0.15 |
| 6 | `fib_retrace_fit_618` | 同 5,对 0.618 |
| 7 | `impulse_score` | 最近 K-swing 内「连续同向且递进」段占比:`#{j : dir_j = dir_{j−1} 且 |price 创新极值|} / (m−1)` ∈ [0,1] |
| 8 | `corrective_score` | 段价格区间与前一段区间重叠的占比:`#{j : overlap(range_j, range_{j−1}) > 0} / (m−1)` ∈ [0,1] |
| 9 | `trend_maturity_0_1` | 当前同向 leg 计数归一:`min(1, consecutive_same_dir_legs / maturity_cap)`,`maturity_cap` ∈ config 默认 5 |
| 10 | `swing_high_low_overlap_pct` | 最近上升结构里,相隔一段的两段价格区间重叠幅度 / 后段幅度(浪 4 重叠代理);无上升结构 → NaN |
| 11 | `seg_len_dispersion` | 最近 K−1 段 `len` 的变异系数 `std/mean`;mean 0 → NaN |
| 12 | `since_last_swing_bars` | `t − idx[最新已确认 swing]`(整数 bar 数) |

所有阈值(`K` / `tol` / `maturity_cap` / `SwingConfig.n`)进
`config/swing_structure.yaml`,**不得 hardcode**(CLAUDE.md 不变量)。

### §3.4 因果包装(§2.2 的修复,Phase 1 核心正确性要求)

`swing_structure.py` 必须实现并使用:

```
confirmed_swings_asof(bars, swing_cfg, t_idx) -> List[SwingPoint]
  # 只返回 confirmation_idx = swing_idx + swing_cfg.n <= t_idx 的 swing
```

第 t 日的所有 12 特征只能用 `confirmed_swings_asof(..., t)` 的输出。
严禁用未确认 swing。

### §3.5 模块 API spec(implement 直接照此)

新文件 `core/factors/swing_structure.py`:

```python
SWING_STRUCTURE_FEATURES: tuple[str, ...]   # 12 个特征名,顺序固定
FEATURE_REGISTRY: dict[str, Callable]        # D4 扩展开口:名 -> 单特征算子

def confirmed_swings_asof(bars, swing_cfg, t_idx) -> list[SwingPoint]
def compute_swing_structure_factors(
    price_df: pd.DataFrame,         # adjusted close, index=date, col=symbol
    high_df: pd.DataFrame | None,
    low_df: pd.DataFrame | None,
    cfg: SwingStructureConfig,
) -> dict[str, pd.DataFrame]          # 12 个 factor,index/col 同 price_df
```

`compute_swing_structure_factors` 由 `factor_generator.generate_all_factors`
经 `factors.update(...)` 调用(模式同 `_family_r_chart_patterns`,§A.4)。

### §3.6 Deliverables

| # | 产物 |
|---|---|
| P1-d1 | `core/factors/swing_structure.py`(12 特征 + `confirmed_swings_asof` + `FEATURE_REGISTRY`) |
| P1-d2 | `config/swing_structure.yaml`(`K` / `tol` / `maturity_cap` / `SwingConfig.n`) |
| P1-d3 | `factor_registry.py`:RESEARCH_FACTORS 175 → **187**(+12 family T) |
| P1-d4 | `research_miner.py`:`FAMILY_T_SWING_STRUCTURE` FamilyConfig 进 `FAMILIES_V2_EXTENDED`,FAMILIES_V2 19 → **20** |
| P1-d5 | `factor_generator.generate_all_factors` 接线 |
| P1-d6 | 单测 ≥ 22(明细见 §3.7) |

### §3.7 Acceptance(audit checklist)

| AC | 判据 | 验收方法 |
|---|---|---|
| P1-A1 | 12 特征全部产出,数值在定义域内(ratio>0、score∈[0,1]、count≥0) | 单测 `test_swing_structure_ranges` |
| P1-A2 | **因果 hard test**:对截断到 t 的面板算 t 日特征 vs 完整面板算 t 日特征,**逐位 ==** | 单测 `test_swing_structure_causal`(必跑,不可 skip)|
| P1-A3 | reachability contract:`union(FAMILIES_V2) == RESEARCH_FACTORS`,计数 187 / 家族 20 同步 | `test_aplusplus_families_v2_union_equals_research_factors` + 计数 tripwire |
| P1-A4 | family T 在 miner `family_first` 采样下可被采到 | 3-trial smoke |
| P1-A5 | 全量 `pytest` green | CI |
| P1-A6 | 阈值全部来自 `config/swing_structure.yaml`,无 hardcode | grep 审计 |

### §3.8 Engineering estimate / Fire trigger / Abort

- 估时 ~2-3 天。
- Fire:**立即**(用户 explicit-go D1)。
- Abort:无 —— Phase 1 只造特征不下 alpha 结论;弱特征留 RESEARCH_FACTORS
  由漏斗淘汰,不删模块。

---

## §4 Phase 2 — 结构输入有没有新增信息

### §4.1 Hypothesis

- **H2a**:family T 12 特征加进 ML 输入,使 `rank:ndcg` 的 OOS Rank IC
  **配对显著**高于不含结构特征版本(incremental IC > 0)。
- **H2b**:bridge 表示层(MiniROCKET / shapelet / dictionary)能在当前
  79-universe / 低算力约束下,提供比单个结构特征更丰富、但比深度 CNN 更
  sample-efficient 的局部形态表示。
- **H2c**:OHLCV 窗口自监督 embedding(TS2Vec 式 / patch 式)下游 IC ≥
  Phase 1.6 富特征基线。外部支持:TS2Vec 证明 hierarchical contrastive
  表示有效;PatchTST 说明 patch token + 自监督预训练可同时保留局部语义并
  延长有效 lookback。
- **H2d**:若长期要做 structure-native encoder,则**预训练语料**本身必须
  被当成一等资产(versioned corpus),不能只写模型不写 corpus。外部支持:
  MOMENT / TimesFM 的关键价值之一就是把 pretraining corpus 变成显式
  engineering object。

### §4.2 Phase 2A spec — incremental-IC 配对检验(复用现成基建)

**baseline config**(= Phase 1.6 canonical,§A.3 给 dataclass 默认值):
`XGBRankingModel(objective="rank:ndcg", n_estimators=200, learning_rate=0.05,
max_depth=5, seed=固定)`;88 OHLCV 因子;inner-val = 2016+2017 两年。

**流程**:
```
factors = build_multi_path_factors(panel)           # §A.2
baseline_panel, cols_b = build_ml_panel(factors_without_T, fwd_ret)
treat_panel,    cols_t = build_ml_panel(factors_with_T,    fwd_ret)
# 12-fold LOTYO,每 fold 同 seed、同 inner-val:
for fold: fit XGBRankingModel on baseline vs treat → predict → Rank IC
```

**配对检验(关键)**:baseline 与 treatment **同 fold 同 seed,只差
family T 这 12 列**。度量 = 每 fold 的 `IC_treat − IC_baseline`,对 12
个差值做 paired t-test + 报 ICIR 提升。不是两次独立跑比 headline。

### §4.3 Phase 2B spec — bridge + 自监督表示层

- **2B-0 bridge baseline(新增,长期 scope 必含)**:
  `core/ml/subsequence_transforms.py` 实现至少一条 transform-based bridge
  路线,优先级:
  1. MiniROCKET / ROCKET-style random convolution transform
  2. shapelet-distance bank
  3. dictionary / bag-of-patterns
  目的不是替代 Phase 3,而是在当前样本规模下建立一个**介于 family T 与
  deep chart-native 之间**的高表达、低算力中间层。
- **2B-1 自监督 encoder**:`window_embedding.py` 实现 TS2Vec 式 encoder
  —— hierarchical contrastive(random cropping + timestamp masking,见
  §13 参考),OHLCV 窗口 → embedding 向量。
- **2B-2 多尺度表示**:除原始 OHLCV window 外,显式支持
  `representation_view ∈ {raw_window, GASF_GADF, patch_tokens}`。
  `patch_tokens` 用于把长 lookback 切成 patch/subsequence token,给
  self-supervised encoder 或后续 Phase 3B 复用。
- **2B-3 预训练语料 manifest(新增,长期 scope 必含)**:
  `data/manifests/chart_structure_pretrain_corpus_v1.json` 记录:
  universe、timeframe(daily/weekly/60m 如有)、window_len、step、
  point-in-time freeze、样本数、symbol coverage、缺失率、标签是否存在。
  该 manifest 是后续所有 embedding / chart-native attempt 的共同语料账本。
  **sealed 纪律(operator 补,codex 漏)**:自监督预训练复用**所有**窗口
  (含无标签窗口)—— 若 corpus 含 validation / sealed 窗口,encoder 会
  从 holdout 数据学习,任何下游候选的 sealed 评估即被污染。因此 corpus
  manifest **默认只纳入 train_years 窗口**;纳入 validation/sealed 窗口
  须走与有标签数据**同一套** split 纪律(§7.3)+ 显式 split_name。
  manifest 必须有 `train_years_only: bool` 字段并默认 `true`;corpus 也
  是 universe-scoped(`--universe` flag,D6)—— manifest 记录用的哪个
  universe,不同 universe 的 corpus 是不同账本。
- **2B-4 prototype / retrieval library(可选诊断层,memo §3.5 分支 4)**:
  把历史窗口 embed 后做 nearest-neighbor / cluster / motif library,作为
  (a) structure embedding 的 linear-probe sanity check;(b) 可解释层 ——
  判断模型在学什么局部结构。即使不直接产 alpha,也是 Stage B/C 的诊断
  基础设施。**不在 Phase 2B 关键路径上**,作为 evidence-gated 可选附加
  项,无 blocking AC。
- bridge feature / embedding 列经 `build_multi_path_factors` 输出 dict 注入
  ( §A.2 确认 panel builder 接受任意因子),下游仍走 `XGBRankingModel`。

### §4.4 Deliverables

| # | 产物 |
|---|---|
| P2-d1 | `dev/scripts/chart_structure/phase2a_incremental_ic.py` + 配对检验报告 JSON |
| P2-d2 | `core/ml/subsequence_transforms.py`(MiniROCKET/shapelet/dictionary 至少一条 bridge baseline)|
| P2-d3 | `core/ml/window_embedding.py`(TS2Vec 式 encoder + GASF/GADF + patch 视图)|
| P2-d4 | `data/manifests/chart_structure_pretrain_corpus_v1.json`(预训练语料 manifest,含 `train_years_only` + universe 字段)|
| P2-d5 | bridge/embedding → `feature_panel_builder` 注入路径 + 单测 |
| P2-d6 | Phase 2 closeout memo(每个 attempt 的确切 config 记录,per D2)|
| P2-d7 | (可选)prototype/retrieval library —— embedding nearest-neighbor / motif 诊断层(2B-4,无 blocking AC)|

### §4.5 Acceptance(audit checklist)

| AC | 判据 |
|---|---|
| P2-A1 | Phase 2A 配对检验报 `mean(ΔIC)` + `std` + paired-t `p` + 95% CI;baseline 与 treatment 仅差 12 列(代码 diff 可验)|
| P2-A2 | incremental-IC 结论 config-scoped(写「这组 12 特征 + 这个 config」,不写「结构信息不存在」)|
| P2-A3 | 至少一条 bridge baseline(MiniROCKET / shapelet / dictionary)有实现、有单测、有下游 IC 报告 |
| P2-A4 | `window_embedding.py` 有单测;GASF/GADF / patch 视图对已知输入有 numerical sanity test |
| P2-A5 | `chart_structure_pretrain_corpus_v1.json` 存在且字段完整(含 `train_years_only` + universe);默认 `train_years_only=true`;后续 attempt 可追溯到同一 corpus manifest;corpus 不含 sealed 窗口(单测验证)|
| P2-A6 | bridge / embedding 注入后 `build_ml_panel` 仍正常产 panel(回归测试)|
| P2-A7 | Phase 2 closeout 含 per-attempt config 表 + representation_view + corpus manifest id |

### §4.6 Engineering estimate / Fire trigger / Abort

- 估时:2A ~1 周;2B ~1-3 周。
- Fire:Phase 1 family T ship + P1-A1..A6 全过。
- Abort(config-scoped,per D2):2A 若配对检验 `mean(ΔIC) ≤ 0 且 CI 含
  0` → 记录「这组 12 特征 + rank:ndcg config 未显新增信息」,root-cause
  (特征构造?ZigZag 阈值?21d horizon 噪声?)→ 据 root-cause 迭代
  family T(§3.5 `FEATURE_REGISTRY` 开口)或换 horizon。**禁** blanket
  「结构信息不存在」。

---

## §5 Phase 3 — chart-native 模型(D2:确定要走)

### §5.1 Hypothesis

把图的结构以 2D 图像 / 段序列直接喂视觉/序列模型,在 purged
walk-forward + 真实成本 + 换手惩罚下,能在某个 universe / horizon 子域
持续打败 tabular baseline。

### §5.2 必须正视的 conflicting evidence(websearch,写进 PRD)

candlestick-CNN 文献结论**冲突**:有研究报 91% 分类准确率,也有研究报
candlestick pattern 不优于纯图像、且 **XGBoost 在 GAF 图像上反超 CNN**;
图像转换会丢精确数值 / 成交量信息。JKX 2023 OOS 方向准确率仅 57.13%。
**共识:视觉分析是 multi-factor 方法的一环,不是 standalone oracle。**
→ Phase 3 的 chart-native 模型是 **ensemble 候选**,必须在裁判下打败
tabular baseline 才有资格,不是默认主模型。

同时,时间序列文献里还有一条对 PQS 很重要的补充证据:高质量 time-series
pipeline 往往不是「只押一种表示」,而是组合 shapelet / dictionary /
interval / convolution 等**异质表示域**。这意味着长期 scope 不应只写
「family T → TS2Vec/GAF → CNN」一条线,还应保留 Phase 2B 的 bridge
表示层作为长期稳定分支。

### §5.3 spec — 3 个并行分支

- **3A image-CNN**:OHLC bar 图 / candlestick / GAF(GASF+GADF)→ CNN。
  图像规格(分辨率、通道、窗口长度)写进 `phase3_attempt_*.json`。
- **3B structure-sequence encoder**:family T 段序列 → 扩展
  `transformer_encoder.SmallEncoder`(§A.5,`forward: (batch, seq_len,
  n_features) → (batch,)`,seq = 段序列,n_features = 每段的
  len/dur/slope/dir)。
- **3C image + tabular fusion**:CNN feature + tabular MLP / CNN + tree-stack。
- training target:next-horizon return rank bucket / 横截面 score。

### §5.4 CNN 方法论纪律(D2 硬要求,implement 与 audit 都按此)

1. **每 attempt 必记录** `data/audit/chart_structure/phase3_attempt_<id>.json`:
   确切架构(层/通道/kernel)、超参、训练 panel、universe flag、图像编码
   方式、随机种子、训练曲线。
2. **失败措辞**只能是「architecture X + config Y 在 universe Z 上 attempt
   失败」;**禁** blanket「CNN 不行」「图像方法不行」。
3. **失败必 root-cause**:样本量?过拟合?图像编码丢信息?标签噪声?
   leakage?—— 写进 attempt JSON + closeout。
4. **abort 只暂停 config,不暂停技术类别**。先例:Phase 1.5「ML 不行」被
   Phase 1.6 推翻(只是目标函数选错)。

### §5.5 Deliverables

| # | 产物 |
|---|---|
| P3-d1 | `core/ml/chart_cnn.py`(3A)|
| P3-d2 | `transformer_encoder.py` 段序列扩展(3B)|
| P3-d3 | `core/ml/fusion_model.py`(3C)|
| P3-d4 | `data/audit/chart_structure/phase3_attempt_*.json`(每 attempt 一份)|
| P3-d5 | Phase 3 closeout(per-attempt config 表 + root-cause + IC/Track A)|

### §5.6 Acceptance(audit checklist)

| AC | 判据 |
|---|---|
| P3-A1 | 每个 attempt 都有 `phase3_attempt_<id>.json`,字段完整(§5.4-1)|
| P3-A2 | closeout 无 blanket failure verdict;所有失败 attempt 有 root-cause |
| P3-A3 | 模型评估走 purged walk-forward + 真实成本 + 换手惩罚(不是裸 IC)|
| P3-A4 | chart-native 候选 vs tabular baseline 的对比明确报出(谁赢)|
| P3-A5 | 3B 训练数据用因果 swing 段序列(继承 §3.4)|

### §5.7 Engineering estimate / Fire trigger / Abort

- 估时 ~3-5 周(3B/3C 原型可在 79-universe 先做;3A image-CNN 等 Phase 4
  universe ≥ 200)。
- Fire:Phase 2A 显 family T 正 incremental IC,**或** Phase 2B embedding
  下游 IC 不弱于富特征基线 —— 二者任一即可 fire 3B;3A 额外 gated on
  Phase 4 universe ≥ 200。
- Abort:per §5.4-4,只暂停 attempt 不暂停类别,abort 必附 root-cause。

---

## §6 Phase 4 — universe expansion(D6:严格隔离)

### §6.1 Hypothesis

universe 79 → 200-500+:(a) 给图像/表征模型足够训练样本;(b) 撬动
sibling-by-construction 簇,让 chart-structure 候选有机会过 G3。

### §6.2 spec — `--universe` flag plumbing(audit 确认:此 flag 不存在)

**新增**:
- `config/universe_expanded_v1.yaml`(Russell-1000 large+mid 子集,目标
  200-500;成分选取见 §10 open question 2)。**不动**
  `config/universe.yaml` / `config/executable_universe.yaml`。
- 统一解析器 `core/universe/universe_resolver.py`:
  `resolve_universe(name: str) -> list[str]`,`name ∈ {executable,
  expanded_v1}`,默认 `executable`。
- CLI flag `--universe {executable|expanded_v1}` 加到所有入口:
  `scripts/run_research_miner.py`、`scripts/run_factor_screen.py`、
  `scripts/run_xgb_*`、`dev/scripts/chart_structure/*`、
  factor panel / 评估脚本。audit 已确认当前 universe 加载分散,无单一
  resolver —— 本 Phase 把它收口。
- universe 标识写进每个产物的 metadata。

### §6.3 Deliverables

| # | 产物 |
|---|---|
| P4-d1 | `config/universe_expanded_v1.yaml` + ingest 脚本(走 BarStore,写 `bar_provenance.parquet`)|
| P4-d2 | `core/universe/universe_resolver.py` + `--universe` flag 贯穿所有入口 |
| P4-d3 | bar-level data integrity smoke(weekend-row scan + cross-symbol date intersection,per memory `feedback_bar_level_data_integrity_smoke`)|
| P4-d4 | universe 隔离回归测试(§6.4)|

### §6.4 D6 隔离硬约束(不可妥协,既是 spec 也是 audit 项)

1. universe expansion **不得修改或重算** cycle04-12 / 所有 forward
   candidate / Phase 1.5-1.6 的任何已发布数字。
2. 默认 universe = `executable`(79);expanded 只在显式
   `--universe expanded_v1` 下生效。
3. **bit-for-bit 回归测试**:同一 mining/eval 脚本在 `--universe
   executable` 下产出与本 Phase 之前对照 baseline snapshot **逐位一致**。
4. forward candidates(cycle06/08 evidence / PEAD / options / trial9 线)
   的 manifest / panel 完全不被 Phase 4 touch。
5. universe flag 写进每个产物 metadata,任何引用可追溯。

### §6.5 Acceptance / estimate / Fire / Abort

| AC | 判据 |
|---|---|
| P4-A1 | `resolve_universe` 单测;`--universe` flag 在所有列出的入口可用 |
| P4-A2 | §6.4-3 bit-for-bit 回归通过 |
| P4-A3 | §6.4-4 forward manifest 未受影响(diff = 空)|
| P4-A4 | expanded universe 过 `data_completeness_gate` + integrity smoke |

- 估时 ~2-3 周(数据 ingest + 完整性校验是主要工作量)。
- Fire:Phase 2A/2B 出结果后(与 Phase 3 交错);3A image-CNN 不晚于它。
- Abort:数据完整性 gate 不过 → 修数据不 abort Phase;扩 universe 后 IC
  无改善 → 记录「这个 universe 子集 + 这个 attempt」结果 + root-cause,
  **禁** blanket「universe expansion 无用」。

---

## §7 Cross-cutting 纪律

### §7.1 因子走漏斗(CLAUDE.md 不变量)

任何阶段产出的特征 / embedding / 模型分数,裁判永远是 IC / Track A /
sealed / NAV correlation。波浪理论、CNN 架构、embedding 方法只负责
**启发**,不下结论。无任何波浪计数被当 ground truth。

### §7.2 anti-sibling gate(D5 写死)

chart-structure 衍生候选成为 **fleet nominee** 的充要条件:
1. 结构特征 / 模型有正的 incremental OOS IC(Phase 2 配对证据);**且**
2. 过 Track A acceptance(17/18 gate,含修好的 MaxDD sign 检查);**且**
3. 过 G3 anti-sibling:raw NAV Pearson < 0.85 **且** residual < 0.50 vs
   所有现役 anchor(RCMv1 / Cand-2 / cycle06 / cycle08 / Trial9 线)。

第 3 条大概率要求候选叠加构造 / universe 自由度 —— **Phase 1-3 单独
不产 nominee;nominee 必须是 (输入表征 × 构造/universe 自由度) 的组合**。

### §7.3 sealed / temporal split / leakage 纪律

- 2026 sealed window 对 split `alternating_regime_holdout_v1` **已
  consumed**(本会话 cycle06/08)。本 PRD 任何候选要过 sealed 需
  split_name bump。
- 默认只读 train_years;validation / sealed 是 holdout(memory
  `feedback_temporal_split_discipline`)。
- 标签区间重叠时下游 IC 走 purged + embargo(对齐
  `temporal_split.purge_labels_at_boundary`)。
- **自监督预训练语料同样受 split 纪律约束**:`chart_structure_pretrain_corpus_v1`
  默认只纳 train_years 窗口(`train_years_only=true`)—— 预训练复用所有
  窗口,corpus 含 holdout 数据会污染 sealed 评估。详 §4.3 2B-3。
- WebSearch 只查方法/论文,禁查当前年 market behavior 数据(memory
  `feedback_websearch_sealed_data_discipline`)。

### §7.4 与 forward fleet 并行(D3)

全程与 cycle06/08 + PEAD + options 的 60 天 soak 并行;forward verdict
只决定 fleet 组合,不冻结本 PRD 任何 phase。

---

## §8 PRD 级验收(总 checklist)

逐 Phase 的 AC 见各 §x.y;PRD 级:

| # | 项 | 判据 |
|---|---|---|
| G1 | 每个 commit 后全量 `pytest` green | CI |
| G2 | 每个 Phase 有 closeout memo,含 per-attempt config 记录 | docs |
| G3 | 所有失败结论 config-scoped + 有 root-cause,无 blanket verdict(D2)| 审 closeout |
| G4 | D6 universe 隔离 4 条全过(P4-A2/A3)| 回归测试 |
| G5 | 任何 fleet nominee 提名前过 §7.2 三条;Phase 1-3 单独不提名(D5)| 审 |
| G6 | 因果 leakage hard test 存在且过(P1-A2 / P3-A5)| 单测 |
| G7 | 所有阈值在 `config/*.yaml`,无 hardcode | grep |

---

## §9 Engineering estimate 汇总

| Phase | 内容 | 估时 | 依赖 |
|---|---|---|---|
| 1 | swing 段结构 family T | 2-3 天 | 无(立即 fire)|
| 2A | incremental-IC 配对检验 | ~1 周 | P1 |
| 2B | bridge + 自监督表示层 + corpus manifest | ~1-3 周 | P1 |
| 3 | chart-native 模型(3A/3B/3C)| ~3-5 周 | P2(3A 需 P4)|
| 4 | universe expansion | ~2-3 周 | P2(与 P3 交错)|

总计 ~9-14 周,Phase 间可重叠;Phase 1 立即开工。

---

## §10 Open questions(implement 前可议)

1. Phase 2A「显著」阈值 —— paired t-test p<0.05 + ICIR 提升幅度双报?
   (operator 倾向双报。)
2. Phase 4 expanded universe 成分 —— Russell-1000 子集如何取?数据源
   (polygon 覆盖度)需先 audit。
3. Phase 3 图像编码先做哪个 —— OHLC bar 图 vs candlestick vs GAF?
   (operator 倾向先 GAF GASF+GADF,确定性变换、无绘图歧义。)
4. embedding 维度 / 窗口长度 —— 待 Phase 2B 设计 memo 细化。
5. `K`(lookback swing 数)默认 8 是否合适 —— Phase 1 可先扫 6/8/12。
6. bridge baseline 优先级 + 依赖 —— MiniROCKET 先做,还是 shapelet/
   dictionary 先做?(operator 倾向 MiniROCKET first,因为快、强基线、对
   当前样本规模更友好。)依赖决策:MiniROCKET 走新依赖(`sktime`/`pyts`)
   还是 ~200 行 numpy 自实现?(operator 倾向自实现,避免给 PQS 引入重
   依赖;implement 前确认。)
7. 预训练语料粒度 —— 只做 daily,还是把 weekly / 60m 一起纳入
   `chart_structure_pretrain_corpus_v1`?(operator 倾向先 daily freeze schema,
   预留 multi-timeframe 字段,避免 schema 返工。)

---

## §11 本 PRD 的 audit trail(operator 自审 + codex v2 复审)

- **codex v2 复审**(2026-05-15):codex 直接改了 PRD 三处 —— (1) Phase 2B
  补 bridge 表示层(MiniROCKET/shapelet/dictionary);(2) 加预训练语料
  manifest 层;(3) 修 2B 估时不自洽(统一 ~1-3 周)。operator 独立复核:
  三处均成立、有文献支撑,**接受**。operator 另补三处 codex 漏掉的:
  (a) corpus manifest 必须受 sealed split 纪律约束(§4.3 2B-3 + §7.3) ——
  预训练复用所有窗口,corpus 含 holdout 会污染 sealed,这是真实污染风险;
  (b) memo §3.5 分支 4(prototype/retrieval library)codex 没进 PRD,
  补为可选诊断层 2B-4;(c) §11 本节标题更新。
- **codebase audit**(Explore agent,2026-05-15):核实 9 个 PRD 假设。
  关键发现:`detect_swing_extrema` non-causal(→ §3.4 因果包装硬要求);
  `--universe` flag 不存在(→ §6.2 plumbing spec);无图像/CNN/GAF 代码
  (→ Phase 3 从零);ML PRD §5 不重复(→ §2.4)。9 个签名已核实,见 §A。
- **websearch ×6**(2026-05-15,均方法论/论文性质,未触 sealed window):
  ZigZag 非因果性确认;GAF = GASF+GADF;Elliott「edge 来自 objective
  rules 不是 wave count」「ZigZag 趋势过滤消 ~60% 假信号」+ Vantuch
  2018 算法;TS2Vec hierarchical contrastive + TS2Vec-Ensemble 融合;
  JKX OOS 57.13%;candlestick-CNN 证据冲突 + XGBoost 在 GAF 反超 CNN
  (→ §5.2 写进 PRD)。
- **4-tier 自审**(per memory `feedback_self_audit_methodology`):
  - R1 事实:§A 所有签名 grep/Read 核实;RESEARCH_FACTORS=175(本会话
    Family R/S 后)→ Phase 1 +12 → 187。
  - R2 逻辑:Phase 依赖图无环;D1-D6 逐条落地;§7.2 与 D5 一致。
  - R3 执行:Phase 1 计数 187/20 与本会话刚改的 reachability 测试机制
    一致(test 机制见 §A.6)。
  - R4 边界:非因果 swing(§3.4)、universe 隔离回归(§6.4)、sealed
    已 consumed(§7.3)均已覆盖。

---

## §A 附录 —— 已核实的本地代码 API(implement 直接引用)

### §A.1 `core/intraday/sr_swing.py`

```python
detect_swing_extrema(bars: pd.DataFrame, n: int = 5) -> pd.DataFrame
  # 返回同 index 的 DataFrame[is_swing_high, is_swing_low](bool)
  # 窗口 [i-n, i+n] —— NON-CAUSAL,需 §3.4 因果包装
compute_nearest_sr(bars, n=5, lookback=20, min_separation_pct=0.0) -> DataFrame
distance_to_sr(bars, n=5, lookback=20, min_separation_pct=0.0) -> DataFrame
@dataclass(frozen=True) SwingConfig(n_window, lookback, min_swing_separation_pct)
```

### §A.2 `core/ml/feature_panel_builder.py`

```python
build_multi_path_factors(panel: dict[str, pd.DataFrame],
    restrict_to_research_factors: bool = True) -> dict[str, pd.DataFrame]
  # 6 个 compute_* 路径,接受任意因子;无 hardcoded 因子数上限
build_ml_panel(factors: dict, fwd_returns: pd.DataFrame, ...
    ) -> tuple[pd.DataFrame, list[str]]   # (panel_df, feature_cols)
```

### §A.3 `core/ml/xgb_ranking.py::XGBRankingModel`(dataclass 默认值)

```python
objective="rank:pairwise"  # Phase 2A 须显式设 "rank:ndcg"
n_estimators=200  max_depth=5  learning_rate=0.05  subsample=0.8
colsample_bytree=0.7  reg_alpha=0.1  reg_lambda=0.1
early_stopping_rounds=20  seed=42  n_jobs=-1
fit(train_panel, y_train, val_panel=None, y_val=None, feature_cols=None)
predict(panel) -> np.ndarray
# inner-val "multi_2016_2017" 是 caller 约定,模型只收 val_panel
```

### §A.4 `core/factors/factor_generator.py` 家族函数模式

```python
def _family_X(price_df, high_df=None, low_df=None) -> dict[str, pd.DataFrame]
# 返回 dict,index/col 同 price_df;high/low 缺失则优雅降级
# 接线:generate_all_factors 内 factors.update(_family_X(...))
```

### §A.5 `core/ml/transformer_encoder.py::SmallEncoder`

```python
SmallEncoder(n_features, seq_len=63, d_model=64, nhead=4,
             dim_feedforward=128, dropout=0.1)
forward(x: Tensor[batch, seq_len, n_features]) -> Tensor[batch]
# 1-layer,~50k params,torch-optional,纯 scaffold,未接线
```

### §A.6 家族注册 5 步(R/S 本会话先例)

1. `research_miner.py` 定义 `FAMILY_T_SWING_STRUCTURE = FamilyConfig(
   name="T", title=..., factors=frozenset({12 名}))`。
2. 加进 `FAMILIES_V2_EXTENDED` list。
3. `factor_registry.py` RESEARCH_FACTORS 加 12 名(175→187)。
4. `factor_generator.generate_all_factors` 接线 compute 函数。
5. 更新 `test_aplusplus_families_v2_union_equals_research_factors`(双向
   `union(FAMILIES_V2)==RESEARCH_FACTORS`)+ 计数 tripwire(187 / 20)。

---

## §12 后续

本 PRD v2 → Phase 1 开工(用户已 explicit-go D1)。实施日志按 phase
closeout 记于 `docs/memos/`,lineage `chart-structure-input-repr-2026-05-15`。

## §13 参考资料

- JF/SSRN `(Re-)Imag(in)ing Price Trends`(JKX 2023,OOS 57.13%)
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3756587
- arXiv `TS2Vec: Towards Universal Representation of Time Series`
  https://arxiv.org/abs/2106.10466
- arXiv `MINIROCKET: A Very Fast (Almost) Deterministic Transform for Time Series Classification`
  https://arxiv.org/abs/2012.08791
- arXiv `HIVE-COTE 2.0: a new meta ensemble for time series classification`
  https://arxiv.org/abs/2104.07551
- OpenReview `A Time Series is Worth 64 Words: Long-term Forecasting with Transformers`
  https://openreview.net/forum?id=Jbdc0vTOcol
- arXiv `MOMENT: A Family of Open Time-series Foundation Models`
  https://arxiv.org/abs/2402.03885
- Google Research `A decoder-only foundation model for time-series forecasting`
  https://research.google/blog/a-decoder-only-foundation-model-for-time-series-forecasting/
- arXiv `TS2Vec-Ensemble`(2511.22395,encoder + 工程特征融合)
- Vantuch-Zelinka-Vasant 2018 `An algorithm for Elliott Waves pattern
  detection`(IDT,确定性波形检测)
- `Encoding candlesticks as images for pattern classification using CNN`
  (Financial Innovation 2020)
- 本地 `dev/deep-research-report.md`(ML quant 系统深度调研)
- 本地 `docs/memos/20260513-ml_phase_1_{5,6}_closeout.md`
- 本地 `docs/prd/20260512-ml_mining_pipeline_prd.md`(ML 模型层 PRD)

所有 query 为方法论/论文性质,未触碰 2026 sealed window 市场数据。
