# Chart-structure → ML 表征 pipeline — 研究方向 memo

**日期**: 2026-05-15
**状态**: 讨论用 memo（用户将批注 → 后续转 PRD）
**作者**: resident quant operator
**触发**: 用户观察 — PQS 现有因子全是「标量 → 横截面排名 → top-N」，缺少把
K 线 / 蜡烛图 / 形态结构（如艾略特波浪）转成 ML 可处理表征的 pipeline。

---

## 1. 背景与动机

PQS 当前所有因子（含 2026-05-15 新增的 Family R 图形因子）都遵循同一套路：

```
原始 OHLCV → 算一个标量 → 横截面 rank / zscore → 加权合成 → 选 top-N
```

问题：图的**结构信息**在进 ML 之前就被塌缩成单个数。Family R 的
`donchian_break_252d`、`golden_cross_score` 也只是把图形压成一个标量。
形状、多指标联合状态、序列结构全部丢失。

用户点名的具体例子 = **艾略特波浪结构判断**（5 浪上升 / 3 浪调整 / 主升浪
定位）—— 这种判断本质是「当前价格处在某个多段结构的哪个位置」，
是序列 + 结构信息，标量排名因子完全无法表达。

---

## 2. 方法论 landscape（websearch 2026-05-15，5 大类）

| 类别 | 术语 | 大白话 | 代表文献 |
|---|---|---|---|
| **1. 图像-CNN** | image-based CNN | 把 OHLC 直接画成黑白像素图，CNN 学"哪种形状之后涨" | Jiang-Kelly-Xiu 2023《(Re-)Imag(in)ing Price Trends》(JF 顶刊) |
| **2. 时序转图** | GAF / MTF / recurrence plot | 用三角变换把 1D 序列转 2D 图（Gramian Angular Field = 时间点两两角度关系矩阵），再喂 CNN | Wang-Oates 2015 |
| **3. 表征学习** | representation learning / embedding | 自监督学每个窗口的特征向量（embedding），产出向量不是标量 | TS2Vec / Series2vec |
| **4. 形态分类** | candlestick / harmonic pattern CNN | 识别教科书形态（吞没、头肩、谐波）— "认已知形态"不是"学新形态" | YOLO candlestick, harmonic-pattern CNN |
| **5. 富特征 + 树模型** | multi-indicator state → GBDT | 不去图像，但**不把因子塌缩成单标量** — 把完整多指标状态向量喂 XGBoost 找交互 | （PQS 部分在做，但因子仍是标量） |

**怀疑派证据（必须正视）**：
- CNN-chart 预测力随时间**衰减**，残余信号集中在小盘/低流动性票
- 大量 DNN/LSTM 选股论文有 temporal-context 错误 → false positive
- CNN robust 需要比典型研究**大 2-3 个数量级**的数据集
- "少而强的信号" OOS 复现性远好于 "多而弱的信号"

---

## 3. 结构化形态理论（艾略特波浪 / 主升浪 / 浪型）

### 3.1 是什么

艾略特波浪理论（Elliott Wave）：
- **推动浪（impulse）**：顺势 5 浪（1-2-3-4-5），其中 1/3/5 上升、2/4 回调
- **调整浪（corrective）**：逆势 3 浪（A-B-C）
- **主升浪 = 第 3 浪**：通常最长最强，是趋势的主升段
- 经典规则：浪 2 不回撤浪 1 的 100%；浪 3 不是最短；浪 4 不与浪 1 重叠
- 回撤/扩展常踩斐波那契比率（0.382 / 0.618 / 1.618）

### 3.2 为什么对量化是个难题（必须诚实）

艾略特波浪在量化圈是**有争议的**：
- **主观性** — 同一张图不同分析师数出不同浪。浪标不唯一。
- **不可证伪** — 事后总能重新数浪让它"对"。这是它最被诟病的点。
- 正统波浪计数当 ground truth → 训练标签本身不可靠 → ML 学到的是分析师的主观偏差。

**所以：不要把"正统艾略特波浪计数"当目标。** 那是把噪声当信号。

### 3.3 务实的量化版本 —— 提取结构基元，让 ML/IC 裁判

波浪理论底层指向的**结构基元**是可提取、可 IC 检验的：

1. **Swing 检测**（ZigZag / 摆动高低点）—— 把价格序列压成一串交替的
   摆动高/低点。这是确定性算法，不主观。PQS 已有
   `core/factors/factor_generator._sr_swing_factors` 部分在做。
2. **段序列特征** —— 从 swing 序列派生：
   - 当前处于第几段上升/下降
   - 最近一段相对前一段的长度比、斜率比（捕捉"主升浪"= 比前段更陡更长）
   - 段长的斐波那契比率贴合度
   - impulse-like（连续同向且递进）vs corrective-like（重叠震荡）分类
3. **趋势相位定位** —— 不数"第几浪"，而是给一个连续的"趋势成熟度"
   分数：刚突破 / 主升中 / 衰竭背离。
4. **ML/IC 裁判** —— 这些结构特征**不预设方向**，进 mining 漏斗，
   IC + Track A + sealed 来判定它们到底有没有 alpha。波浪理论只负责
   **启发特征构造**，不负责下结论 —— 完全符合 CLAUDE.md「因子走漏斗」
   原则（启发可以来自任何理论，裁判永远是数据）。

**一句话**：把艾略特波浪当**特征构造的灵感来源**，不当**预测真理**。
提取它指向的确定性结构基元（swing 段、长度比、斜率比、重叠度），
让 PQS 现有的 IC / Track A / sealed 漏斗去裁判。

---

## 4. PQS 硬约束 —— universe 太小

PQS universe = **79 只股票**。

- 类别 1（图像-CNN，JKX 式）在 CRSP 全市场（几千只 × 几十年）上训练。
  79 只对 CNN 小 **2-3 个数量级** → 深度 CNN-on-charts 在当前 universe
  基本只会过拟合。
- PQS 的强项（Track A temporal split + sealed holdout + forward
  observation）能抓过拟合，但**抓不了"样本量根本不够"**。
- 推论：**若要走类别 1，universe expansion（扩到 500-2000 只）是前提，
  不是可选项**。这跟之前因 TC-ceiling 理由 drop 的 D1 重新挂钩。

---

## 5. 推荐路径（按 PQS 现实约束排序）

| 路径 | 内容 | 成本 | universe 要求 | 推荐度 |
|---|---|---|---|---|
| **A** | 富特征 + GBDT：停止标量塌缩，把完整多指标状态向量（含 swing 段结构特征）喂 XGBoost 找非线性交互 | 低（无 GPU、用现有 79）| 79 够 | ⭐ 先做 |
| **B** | TS2Vec 式自监督 embedding：在现有 OHLCV 上学窗口 embedding 向量再喂下游 | 中 | 79 勉强（自监督复用所有窗口，样本要求低于 CNN）| 次做 |
| **C** | 图像-CNN / GAF 转图 | 高（GPU + universe）| 需先扩到几百+只 | 缓做，gated on universe expansion |

**波浪结构特征落在路径 A 里** —— swing 检测 + 段序列特征是确定性算法
产出的数值特征，直接进 XGBoost 富特征集，不需要图像也不需要扩 universe。

---

## 6. 落地草图（路径 A + 波浪结构，PQS-feasible）

```
阶段 1 — Swing/结构特征模块（新 factor family，~2-3 天）
  core/factors/swing_structure.py
    - ZigZag swing 检测（阈值可配，threshold ∈ config）
    - 段序列派生特征（≥15 个）：
        seg_count_up / seg_count_down (当前结构第几段)
        last_seg_len_ratio / last_seg_slope_ratio (主升浪强度代理)
        fib_retrace_fit_382 / _618 (斐波那契贴合度)
        impulse_score / corrective_score (推动 vs 调整分类)
        trend_maturity_0_1 (趋势相位连续分)
        swing_high_low_overlap_pct (浪 4 重叠度代理)
  → 全部进 RESEARCH_FACTORS 新 family（family T?）

阶段 2 — 富特征 mining mode（~3-4 天）
  ResearchMiner 增加 "rich_feature" 模式：
    不做单因子合成 → 把完整特征向量喂 XGBoost
    输出 = XGB 预测分 → 横截面 rank → top-N
  Track A / sealed 漏斗不变（XGB 输出当作 composite score 处理）

阶段 3 — IC + Track A 检验
  swing 结构特征独立 IC 检验 → 哪些有 alpha
  rich-feature XGBoost vs 现有线性合成的 Track A 对比
```

**关键纪律**：阶段 1 的特征构造**可以**受波浪理论启发；阶段 3 的裁判
**必须**是 IC / Track A / sealed。没有任何波浪计数被当成 ground truth。

---

## 7. 决策点（用户批注）

1. **D1 — 走不走深度 CNN（类别 1/C）？**
   若走 → universe expansion 必须先做（重新激活之前 drop 的 D1）。
   若不走 → 接受 79-universe 现实，专注路径 A/B。
   *operator 倾向*：先不走 C。79 universe 做 CNN 是过拟合陷阱。

2. **D2 — 先做路径 A 还是直接上 B（embedding）？**
   *operator 倾向*：先 A。富特征 + 树模型便宜、立刻能做、直接回应
   "全是 ranking" 的抱怨，且 swing 结构特征天然落在 A 里。

3. **D3 — 波浪结构特征的范围**
   阶段 1 草图列了 ~9 类特征。用户可增删 / 调方向（如更重斐波那契、
   或更重 impulse/corrective 分类）。

4. **D4 — 这个方向 vs 现有 forward fleet 的优先级**
   当前 forward fleet（cycle06/08 + PEAD + options）在 60 天 soak 中。
   chart-structure 方向是并行研究还是等 soak 出结果？

---

## 8. 后续

用户批注本 memo → operator 据批注转正式 PRD（路径 A 优先，含 swing
结构特征 family 的完整 spec）→ 按 PQS 标准流程（小步 patch + 测试 +
Track A 漏斗）开展。

websearch 来源见会话记录 2026-05-15（JKX / TS2Vec / GAF / candlestick
CNN / 怀疑派复现文献）。所有 query 为方法论性质，未触碰 2026 sealed
window 市场数据。
