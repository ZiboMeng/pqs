# Chart-structure → ML 表征 pipeline — 研究方向 memo (v2)

**日期**: 2026-05-15
**状态**: v2 —— 已整合 codex 批注 + `dev/deep-research-report.md`；pre/post audit 已做。
下一步转正式 PRD。
**作者**: resident quant operator
**触发**: 用户观察 —— PQS 现有因子全是「标量 → 横截面排名 → top-N」，缺少把
K 线 / 蜡烛图 / 形态结构（如艾略特波浪）转成 ML 可处理表征的 pipeline。
**v2 修订依据**:
- codex 对 v1 的 6 段独立批注（已逐条吸收，见 §10 操作员回应）
- `dev/deep-research-report.md`（用户委托的 ML quant 系统深度调研）
- pre-audit 代码核查（§2 的本地 ML 现状全部 grep / Read 验证过）

---

## 0. v2 最重要的一句话（先说结论）

v1 把问题定义成「PQS 缺一个把图变成数字喂 ML 的 pipeline」。pre-audit 之后
要诚实修正：

> **PQS 不缺 ML 基建，也不缺把图变数字的能力。真正缺的、也是真正卡住
> alpha 的，是两件相互独立的事：(a) 比标量因子更有信息量的结构化输入
> 表征；(b) 一个能让候选 NAV 跳出 sibling-by-construction 簇的构造 /
> universe 改动。本 memo 主攻 (a)，但必须把 (b) 写清楚 —— 因为光做 (a)
> 不会产出新的 fleet 候选。**

这个修正不是否定方向，而是把方向锚到本地真实证据上（§2 + §5）。

---

## 1. 背景与动机

PQS 当前所有 *因子* 都遵循同一套路：

```
原始 OHLCV → 算一个标量 → 横截面 rank / zscore → 加权合成 → 选 top-N
```

图的**结构信息**在进 ML 之前就被塌缩成单个数。即使 2026-05-15 新增的
Family R 图形因子（`donchian_break_252d`、`golden_cross_score` 等），也只是
把图形压成一个标量 —— 形状、多指标联合状态、序列结构全部丢失。

用户点名的具体例子 = **艾略特波浪结构判断**（5 浪上升 / 3 浪调整 / 主升浪
定位）—— 这种判断本质是「当前价格处在某个多段结构的哪个位置」，是序列 +
结构信息，标量排名因子完全无法表达。

**但要分清两个层面（codex 批注 §1 + pre-audit 修正）**：

| 层面 | PQS 现状 | 缺不缺 |
|---|---|---|
| ML *模型* 基建 | `core/ml/` 已有 4 个模块（见 §2.1）+ 一份 ML Mining Pipeline PRD | **不缺** |
| 把因子喂进 ML | `feature_panel_builder` 已做 162-factor 面板 + 横截面 rank 变换 | **不缺** |
| 比标量因子更**有信息量的结构化输入** | 因子仍是标量；无 swing 段序列 / embedding / 图像表征 | **缺 —— 本 memo 主攻** |
| 能跳出 sibling 簇的**构造 / universe** | 79-stock × cap_aware × monthly × top-N 固定 | **缺 —— §5 专门讲** |

所以本 memo 的价值**不是**「再上一个 ML 模型」，而是「如何把 chart
structure 提炼成比 `golden_cross_score` 更丰富、但仍可被 IC / Track A /
sealed 漏斗检验的特征」。

---

## 2. 本地 ML 现状 —— pre-audit 真实盘点

v1 对本地 ML 状态描述含糊。pre-audit 逐个 grep / Read 之后的事实如下。

### 2.1 已有的 ML 基建（`core/ml/`，全部已验证存在）

| 模块 | 内容 | 验证等级 |
|---|---|---|
| `feature_panel_builder.py` | 多路径 162-factor 面板 + 横截面 rank∈[0,1] 变换；NaN 原生保留不 zero-impute | code_verified |
| `xgb_alpha.py` | Phase 1 XGBoost return-prediction | code_verified |
| `xgb_ranking.py` | Phase 1.6 排序目标：`rank:pairwise` / `rank:ndcg` / 自定义 LambdaRankIC / quintile 分类 | code_verified |
| `transformer_encoder.py` | `SmallEncoder` —— 1-layer time-series transformer scaffold（research-only，PRD M8） | code_verified |

外加 `docs/prd/20260512-ml_mining_pipeline_prd.md` —— 一份完整 ML PRD，
Phase 1（XGBoost）→ Phase 2（multi-horizon）→ Phase 3（**cross-sectional
Transformer**）→ Phase 4（RL）。**§5 的 cross-sectional Transformer phase
已经规划在案** —— 本 memo 不重复它，只补它上游缺的「输入表征层」。

### 2.2 ML Phase 1 / 1.5 / 1.6 的真实结论（codex 批注 §1 的关键修正）

codex 批注引用了 `docs/memos/20260513-ml_phase_1_5_closeout.md`，说
「现成 XGBoost 方案 Track A 能过最低门槛，但 alpha 强度明显弱于 linear
baseline」。**这个引用 stale —— Phase 1.6 已把 Phase 1.5 的结论推翻。**

| 阶段 | 设置 | best avg per-yr vs SPY | 占 linear baseline (+15.31%) | 裁决 |
|---|---|---|---|---|
| Phase 1.5 | `reg:squarederror`，27-config grid | **+6.36%** | **42%** | §3.9 abort 触发 |
| Phase 1.6 | `rank:ndcg`（LambdaMART）| **+14.45%** | **94%** | §3.9 技术仍触发，但仅差 0.86pp |

Phase 1.5 的 "+6.36% = 42%" 不是 ML 弱，是**目标函数选错**（用回归 MSE
做横截面排序任务）。Phase 1.6 换成 `rank:ndcg` 后，ML 跟 linear baseline
**几乎打平**（94%）。所以正确表述是：

> **在 PQS 79-stock long-only top-N 上，properly-tuned ML（rank:ndcg）
> 与 linear baseline 大致 competitive，不是 "structurally inferior"。**

### 2.3 但真正卡住的不是 alpha 强度，是 G3 orthogonality

Phase 1.6 的 rank:ndcg config 虽然 alpha 接近 baseline，**G3 anti-sibling
仍 0/3 PASS**：raw NAV 相关 0.829–0.845 vs RCMv1 / Cand-2 / Trial9_v2 —— 跟
cycle09b Trial 1 同一个 sibling 簇。

这就引出 §5 的诊断。

---

## 3. 方法论 landscape

### 3.1 chart → ML 的 5 大类（websearch 2026-05-15 + deep-research-report）

| 类别 | 术语 | 大白话 | 代表文献 |
|---|---|---|---|
| **1. 图像-CNN** | image-based CNN | 把 OHLC 直接画成黑白像素图，CNN 学"哪种形状之后涨" | Jiang-Kelly-Xiu 2023《(Re-)Imag(in)ing Price Trends》(JF) |
| **2. 时序转图** | GAF / MTF / recurrence plot | 用三角变换把 1D 序列转 2D 图，再喂 CNN | Wang-Oates 2015 |
| **3. 表征学习** | representation learning / embedding | 自监督学每个窗口的特征向量（embedding），产出向量不是标量 | TS2Vec / Series2vec |
| **4. 形态分类** | candlestick / harmonic pattern CNN | 识别教科书形态（吞没、头肩、谐波）—— "认已知形态"不是"学新形态" | YOLO candlestick, harmonic-pattern CNN |
| **5. 富特征 + 树/序列模型** | multi-indicator state → GBDT / seq model | 不去图像，但**不把因子塌缩成单标量** —— 把完整多指标状态向量喂 XGBoost / 序列模型找交互 | PQS Phase 1.6 已部分在做 |

### 3.2 deep-research-report 给的模型分层纪律（必须遵守）

`dev/deep-research-report.md` 的核心工程结论之一：**模型上线顺序几乎总是
线性/树 → 序列深度 → Transformer → LLM**，而且 —— 关键 —— **Transformer
应该被当成「比 GBDT 更强的候选 ensemble 成员」，不是默认主模型**。

这一点直接 temper 了 v1 / codex 把「chart-CNN / chart-native model」写成
「terminal layer」的表述。更准确的说法：

> chart-native / structure-native 模型是一个**研究分支**，它必须在
> purged walk-forward + 真实成本 + 换手惩罚下**持续打败 tabular
> baseline**，才有资格进 ensemble。它不是「注定的终局」，是「要挣来的
> 席位」。

### 3.3 怀疑派证据（必须正视）

- CNN-chart 预测力随时间**衰减**，残余信号集中在小盘 / 低流动性票。
- 大量 DNN/LSTM 选股论文有 temporal-context 泄漏 → false positive。
- CNN robust 需要比典型研究**大 2-3 个数量级**的数据集。
- "少而强的信号" OOS 复现性远好于 "多而弱的信号"。
- deep-research-report 的诚实预期：小团队上线后净 Sharpe 落 **0.5–1.2**，
  税前净年化高个位数到低双位数 —— 回测里的 1.5+ Sharpe / 15-25% 年化
  「上线自然实现」基本会被滑点、拥挤、衰减、泄漏打回。

### 3.4 关键区分（codex 批注 §2，已吸收）

「chart-CNN 在文献里可行」与「PQS 当前就适合 chart-CNN」**必须分开写**：
- JKX 2023 用的是 **CRSP 全市场 1993-2019 日线**（NYSE/AMEX/NASDAQ 全体
  股票），不是几十只票的小面板。
- TS2Vec 这类自监督路线提供的是 **representation quality**，不是直接的
  financial alpha 证明 —— 它的产出 embedding 仍要交给 IC / Track A /
  sealed 漏斗裁判。

---

## 4. 结构化形态理论（艾略特波浪 / 主升浪 / 浪型）

> codex 批注 §3：「这节是整篇 memo 里最稳的一节」。v2 保留主线，只做精度修正。

### 4.1 是什么

艾略特波浪理论（Elliott Wave）：
- **推动浪（impulse）**：顺势 5 浪（1-2-3-4-5），其中 1/3/5 上升、2/4 回调。
- **调整浪（corrective）**：逆势 3 浪（A-B-C）。
- **主升浪 = 第 3 浪**：通常最长最强，是趋势的主升段。
- 经典规则：浪 2 不回撤浪 1 的 100%；浪 3 不是最短；浪 4 不与浪 1 重叠。
- 回撤 / 扩展常踩斐波那契比率（0.382 / 0.618 / 1.618）。

### 4.2 为什么对量化是个难题（必须诚实）

艾略特波浪在量化圈是**有争议的**：
- **主观性** —— 同一张图不同分析师数出不同浪，浪标不唯一。
- **不可证伪** —— 事后总能重新数浪让它"对"。这是它最被诟病的点。
- 正统波浪计数当 ground truth → 训练标签本身不可靠 → ML 学到的是分析师的
  主观偏差。

**所以：不要把"正统艾略特波浪计数"当目标。** 那是把噪声当信号。

### 4.3 务实的量化版本 —— 提取结构基元，让 ML / IC 裁判

波浪理论底层指向的**结构基元**是可提取、可 IC 检验的：

1. **Swing 检测**（ZigZag / 摆动高低点）—— 把价格序列压成一串交替的摆动
   高 / 低点。这是确定性算法，不主观。
   **pre-audit 发现**：PQS 已有 `core/intraday/sr_swing.py`，里面
   `detect_swing_extrema` / `compute_nearest_sr` / `distance_to_sr` /
   `SwingConfig` 都已实现且有测试。`factor_generator._sr_swing_factors`
   目前只用它算 `dist_to_swing_high_20d` / `dist_to_swing_low_20d` 两个
   距离因子 —— **ZigZag 检测器本身已经在，段序列特征是增量扩展，不是
   白纸起步**。
2. **段序列特征** —— 从 swing 序列派生：
   - 当前处于第几段上升 / 下降；
   - 最近一段相对前一段的长度比、斜率比（捕捉"主升浪" = 比前段更陡更长）；
   - 段长的斐波那契比率贴合度；
   - impulse-like（连续同向且递进）vs corrective-like（重叠震荡）分类。
3. **趋势相位定位** —— 不数"第几浪"，而是给一个连续的"趋势成熟度"分数：
   刚突破 / 主升中 / 衰竭背离。
4. **ML / IC 裁判** —— 这些结构特征**不预设方向**，进 mining 漏斗，
   IC + Track A + sealed 来判定它们到底有没有 alpha。波浪理论只负责
   **启发特征构造**，不负责下结论 —— 完全符合 CLAUDE.md「因子走漏斗」原则。

**一句话**：把艾略特波浪当**特征构造的灵感来源**，不当**预测真理**。提取它
指向的确定性结构基元（swing 段、长度比、斜率比、重叠度），让 PQS 现有的
IC / Track A / sealed 漏斗去裁判。

### 4.4 工程纪律 —— 防 temporal leakage（codex 批注 §6，已吸收）

任何 swing / segment 特征都必须严格使用 **只在当日可见的已确认摆点**。
ZigZag 的天然陷阱：一个摆点要等后续 bar 才能"确认"，如果用未来 bar 来
确认当前结构位置，就把「形态识别」偷偷做成 temporal leakage。
- swing 检测必须 causal：第 t 日的特征只能用 ≤ t 的已确认摆点。
- deep-research-report 进一步要求：标签区间重叠时对训练集做 **purging +
  embargo**（金融 ML 标准做法，MlFinLab purged/CPCV）。
- 这条必须在 PRD 里写成 hard test，不是 best-effort。

---

## 5. 关键诊断 —— sibling-by-construction（操作员独立判断，修正 codex）

> 这是 v2 新增、也是最 load-bearing 的一节。codex 批注没有触及它，但
> pre-audit 读 Phase 1.5 + 1.6 closeout 之后，必须把它写清楚。

### 5.1 codex 的一个判断我**不全盘接受**

codex 审计结论说：「Phase 1.5 的失败误读成 'ML 终局失败'，它失败的是
**旧输入表示**」。

pre-audit 读完两份 closeout memo 后，这个说法**只对了一半，另一半误导**：
- Phase 1.5 的 "+6.36%" 不是输入表示的锅，是**目标函数**的锅
  （`reg:squarederror` vs `rank:ndcg`）。Phase 1.6 没换任何输入、只换目标
  函数，alpha 就从 42% 跳到 94%。
- 真正没解决、而且**换输入也解决不了**的是 G3 orthogonality。

### 5.2 sibling-by-construction —— 3 个独立证据

`ml_phase_1_6_closeout.md` §3.1 把这件事锤实了：cycle04-09b 的
sibling-by-NAV 现象有 **3 个相互独立的确认**：

1. **factor swap**：换因子锚 → NAV 仍 sibling。cycle07a Trial 3 只跟
   RCMv1 共享 1/4 因子（仅 drawup），raw NAV 仍 0.874；vs Cand-2 是
   0 共享因子（Cand-2 根本没有 drawup），raw 反而更高 0.892
   （source: `docs/memos/20260507-cycle07a_trial3_red_verdict_evidence_only.md`）。
2. **seed change**（cycle09b §5.3）：同 yaml + 换 Optuna seed → 0/3 因子
   重叠但 NAV raw 0.761。
3. **objective swap**（Phase 1.6）：cap_aware_cross_asset + ML 排序目标 →
   NAV raw 0.829-0.845 vs anchors，同一个 sibling 簇。

**结论**：sibling 的根因是 **construction-driven，不是 factor / objective /
输入表示 driven**。绑死它的是这套构造本身：

```
cap_aware_cross_asset + monthly rebalance + top-10 + 79-stock universe
```

### 5.3 这对本 memo 意味着什么（最关键的推论）

> **光做结构化输入表征（§4 的 swing 段特征），即使它真的提供新增 IC，
> 在同一套 79-stock × cap_aware × monthly × top-N 构造下跑出来的候选，
> 大概率仍是 sibling，不会成为新的 fleet 成员。**

换句话说：本 memo 的 (a)「更好的输入」和 (b)「能跳出 sibling 簇的构造 /
universe」是**两个独立的锁**，得分别开。已知能撬动 sibling 簇的自由度
（`ml_phase_1_6_closeout.md` §3.1）：
- (a) 改选择规则（top-N → 别的 N / 加 min_holding）；
- (b) 改加权方式（equal → risk-parity / inverse-vol / score-weighted）；
- (c) 改 universe（79 → 200+ 股 或 永久加 bond/commodity）；
- (d) 改 cadence（monthly → weekly；cycle08 试过，同样失败）。

**universe expansion 之所以要被提升为主线**（codex 批注 §4 的方向对，但
理由要换）：codex 给的理由是「CNN 需要大样本」—— 那是 §3 远期才用得上的
理由。**更近、更硬的理由是：universe expansion 是少数几个能撬动
sibling-by-construction 簇的自由度之一**，这是本地 5 个 cycle + Phase 1.6
反复验证出来的。

---

## 6. PQS 硬约束 —— universe 太小

PQS executable universe = **79 只股票**（`config/executable_universe.yaml`）。

- 类别 1（图像-CNN，JKX 式）在 CRSP 全市场（几千只 × 几十年）上训练。79 只
  对 CNN 小 **2-3 个数量级** → 深度 CNN-on-charts 在当前 universe 基本只会
  过拟合。
- PQS 的强项（Track A temporal split + sealed holdout + forward
  observation）能抓过拟合，但**抓不了"样本量根本不够"**。
- universe expansion 因此有**两个独立动机**：
  1. **近期、硬**：撬动 sibling-by-construction 簇（§5）—— 不需要 CNN 也成立。
  2. **远期**：给图像 / 表征模型足够训练样本（§3 类别 1-3）。
- PRD 应明确：`chart-native terminal architecture = structure pipeline +
  ML representation + larger universe`，且 universe expansion 默认实现
  方式 = **新增独立 universe yaml**，不动主 universe / 不动 forward
  candidates 的 panel（per memory `feedback_multi_universe_research_default`）。

---

## 7. 推荐路径（staged，每阶段都有 evidence gate）

| 阶段 | 内容 | 成本 | universe | 角色 | 通过门槛 |
|---|---|---|---|---|---|
| **Stage A** | swing 段结构特征 family + 富特征喂 XGBoost rank:ndcg（Phase 1.6 已有的 canonical config）| 低（无 GPU、用 79）| 79 够 | 结构原型层 | 结构特征独立 IC > 现有 Family R；rank:ndcg + 结构特征 vs rank:ndcg without 有 **incremental** OOS IC |
| **Stage B** | TS2Vec 式自监督 embedding / GAF-recurrence 表示 | 中 | 79 勉强（自监督复用所有窗口）| 表征过渡层 | embedding 下游 IC ≥ Stage A 富特征 |
| **Stage C** | 图像-CNN / structure-sequence transformer（复用 `transformer_encoder.py`）/ hybrid encoder | 高（GPU + universe）| 需先扩 universe | 长期模型分支 | purged walk-forward + 真实成本 + 换手惩罚下持续打败 tabular baseline |

**三条纪律**：
1. **Stage A/B/C 不是互斥路线，也不是一条硬顺序**（codex 批注 §5）。这是
   长期 roadmap：上游提供表示层和证据层，下游可展开多个 chart-native 分支。
2. **每个阶段的裁判固定是 IC / Track A / sealed / NAV correlation** —— 没有
   任何波浪计数被当成 ground truth。
3. **Stage A 即使通过 incremental-IC gate，也不自动产出 fleet 候选** —— 因为
   §5 的 sibling 锁还在。要产出 fleet 候选，必须 Stage A 结构特征 **叠加**
   §5.3 的构造 / universe 自由度。这点 PRD 必须写死，否则会重蹈 cycle04-09b
   「IC 好看但 0 nominee」的覆辙。

**波浪结构特征落在 Stage A** —— swing 检测 + 段序列特征是确定性算法产出的
数值特征，先作为 structure abstraction layer；它们不是终局的替代品，而是
通往 chart-native / structure-native 模型族的第一层可解释表示。

---

## 8. 落地草图（PRD 雏形）

```
阶段 1 — 结构抽象层（新 factor family，~2-3 天）
  core/factors/swing_structure.py  (新文件，复用 core/intraday/sr_swing.detect_swing_extrema)
    - 段序列派生特征（≥12 个，全部 causal、防 leakage）：
        seg_count_up / seg_count_down       (当前结构第几段)
        last_seg_len_ratio / _slope_ratio   (主升浪强度代理)
        fib_retrace_fit_382 / _618          (斐波那契贴合度)
        impulse_score / corrective_score    (推动 vs 调整分类)
        trend_maturity_0_1                  (趋势相位连续分)
        swing_high_low_overlap_pct          (浪 4 重叠度代理)
  → 进 RESEARCH_FACTORS 新 family（family T）
  → leakage hard test：第 t 日特征只用 ≤ t 已确认摆点

阶段 2 — 结构输入有没有新增信息（~1 周）
  - 2A: 结构特征 + Phase 1.6 rank:ndcg config，对比 without 结构特征的
        incremental OOS IC（这一步直接复用现有 core/ml/ 基建，无新模型）
  - 2B: OHLCV window / GAF / recurrence 表示 → TS2Vec / self-supervised embedding
  evidence gate：incremental IC 显著为正才进阶段 3

阶段 3 — chart-native 模型分支（~2-4 周，依赖更大 universe）
  - 3A: OHLC / candlestick / GAF 图像 → CNN
  - 3B: structure-sequence encoder（段序列 → transformer_encoder.py 扩展）
  - 3C: image + tabular fusion
  evaluation：IC / Track A / sealed / NAV correlation
  必须搭配 §5.3 构造 / universe 自由度，否则只产出 sibling

阶段 4 — universe expansion（与阶段 2-3 交错）
  - 新增独立 universe yaml（不动主 yaml、不动 forward candidates）
  - 79 → 200-500+ 股，给图像 / 表征模型足够样本 + 撬动 sibling 簇
  - 保留 Track A / sealed / forward governance
```

**关键纪律**：阶段 1 特征构造**可以**受波浪理论启发；阶段 3 的裁判
**必须**是 IC / Track A / sealed。本 memo 描述的是 ML Mining Pipeline PRD
（`docs/prd/20260512-ml_mining_pipeline_prd.md`）的**上游输入表征层** ——
两者衔接，不重复：那份 PRD 管模型（XGBoost→Transformer→RL），本 memo 管
喂给模型的**结构化表征**。

---

## 9. 决策点（2026-05-15 用户已拍板 → 已转 PRD）

PRD: `docs/prd/20260515-chart_structure_input_representation_prd.md`。

1. **D1 — PRD 范围**：**全 staged roadmap 一次 commit**。用户明确推翻
   操作员「只做 Stage A」建议 ——「便宜的先做，但便宜之后一定要接着
   expensive 的，新模型 / 数据处理 / universe expansion 肯定都要做，不要
   把 scope 限制在小范围，永远 mine 不出 alpha core」。便宜先做 = 执行
   顺序，不是 scope。Stage A/B/C + universe expansion 全部进 committed
   scope，各有 fire trigger。

2. **D2 — 深度 CNN**：**确定要走**。用户：不能随便下结论「CNN 不行」，
   只能说「尝试的那个 CNN config 可能不行」，必须 root-cause 找原因再
   迭代。PRD 写入方法论纪律：每次 attempt 记录确切架构 + config + panel；
   失败只写「这个 attempt 失败」+ root-cause，禁止 blanket verdict。

3. **D3 — 优先级**：**并行研究**（forward verdict 只决定 fleet 组合，
   不冻结 alpha mining）。

4. **D4 — 波浪结构特征范围**：**先按 12 个走**，但 family T 留扩展开口，
   后续 research 看还有什么方向。

5. **D5 — Stage A 候选 fleet 资格**：**确认写死**。结构特征即使过
   incremental-IC gate 也不自动成 fleet 候选 —— 必须叠加构造 / universe
   自由度并通过 G3 anti-sibling。

6. **D6（用户追加强调）— universe expansion 隔离**：universe expansion
   **不得影响任何之前的结论和方法**；必须有显式 flag 指定用哪个 universe。
   cycle04-12 + 所有 forward candidate 的 79-universe 结论保持有效、不被
   追溯失效。

---

## 10. 操作员对 codex 批注的逐条回应

> 用户要求独立判断，不全盘接受。以下是 6 段批注 + 审计结论的处理。

| codex 批注 | 操作员裁决 | 处理 |
|---|---|---|
| §1 PQS 不缺 ML 基建，缺有信息量的结构化输入 | **接受**（grep 验证 4 个 `core/ml/` 模块存在）| §0 + §1 表 + §2.1 |
| §1 引用 Phase 1.5「alpha 弱于 linear」 | **修正** —— stale。Phase 1.6 已推翻：rank:ndcg = 94% baseline | §2.2 专门一节 |
| §2 chart-CNN 可行 ≠ PQS 适合；JKX 用 CRSP 全市场 | **接受** | §3.4 |
| §2 区分长期目标 vs 中间层 | **接受，但 temper** —— deep-research-report 说 Transformer 都该是 ensemble 候选不是默认主模型；chart-native 是「要挣来的席位」不是「注定终局」 | §3.2 |
| §3 Elliott-wave 降级成启发式结构基元 + IC 裁判 | **接受**（最稳的一节）| §4 保留 |
| §4 universe expansion 提升为主线 | **接受方向，换理由** —— codex 给的「CNN 需要大样本」是远期理由；更硬的近期理由是「撬动 sibling-by-construction」 | §5.3 + §6 |
| §6 swing/segment 必须用当日可见摆点防 leakage | **接受** | §4.4 hard test |
| 审计结论「Phase 1.5 失败的是旧输入表示」 | **部分不接受** —— Phase 1.5 失败的是目标函数（Phase 1.6 换 rank:ndcg 即解决，没换输入）；真正未解、且换输入也解不了的是 sibling-by-construction | §5.1 |

**整合 `dev/deep-research-report.md` 的额外约束**（已写进 v2）：
- 模型分层纪律：线性/树 → 序列 → Transformer → LLM；Transformer 是
  ensemble 候选不是默认主模型（§3.2）。
- 诚实预期：上线净 Sharpe 0.5-1.2，不是回测 1.5+（§3.3）。
- 泄漏防控：purged / embargo CV、triple-barrier label、point-in-time
  （§4.4）。
- 小团队应做中低频横截面 + 事件驱动，避开 HFT —— 与 PQS 现有定位一致，
  支持 universe expansion 到 200-500+（§6）。

---

## 11. 后续

本 v2 memo → 转正式 PRD：

> **PRD 标题（建议）**：Chart-structure 输入表征层 PRD —— ML Mining
> Pipeline 的上游补全。
> **范围**：阶段 1（swing 段结构 family T）+ 阶段 2A（incremental-IC
> 检验，复用 Phase 1.6 基建）为 PRD v1 的硬范围；阶段 2B / 3 / 4 为
> evidence-gated 后续 phase。
> **不做的事**：不重复 `docs/prd/20260512-ml_mining_pipeline_prd.md` 的
> 模型层；不在 79-universe 上做深度 CNN；不把任何波浪计数当 ground truth。

PRD 将按 PQS 标准流程开展（小步 patch + 测试 + Track A 漏斗）。

---

## 参考资料

- JF / SSRN: `(Re-)Imag(in)ing Price Trends`
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3756587
- arXiv: `TS2Vec: Towards Universal Representation of Time Series`
  https://arxiv.org/abs/2106.10466
- ScienceDirect: `Exploring the Elliott Wave Principle to interpret metal
  commodity price cycles`
  https://www.sciencedirect.com/science/article/pii/S0301420718301843
- 本地: `dev/deep-research-report.md`（ML quant 系统深度调研，2026-05-15）
- 本地: `docs/memos/20260513-ml_phase_1_5_closeout.md` /
  `20260513-ml_phase_1_6_closeout.md`（ML Phase 1.5/1.6 真实结论）
- 本地: `docs/prd/20260512-ml_mining_pipeline_prd.md`（ML 模型层 PRD）

所有 query 为方法论 / 论文性质，未触碰 2026 sealed window 市场数据。
