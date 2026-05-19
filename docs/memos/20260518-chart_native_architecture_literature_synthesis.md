# chart_native 架构方向 —— 4 路并行文献深挖综合

**日期**: 2026-05-18
**性质**: 文献综合 + 研究方向判定(directional 待用户拍板;本 memo = 决策输入,非晋升结论)
**方法**: 4 个并行 agent,各专攻一架构族,每个走 ≥2 轮 websearch(fuzzy→提炼→强制第二轮精确→primary 挖透),全程仅方法/论文、未触 2026 市场数据(sealed 纪律)。
**纪律**: `feedback_websearch_fuzzy_to_primary_depth`、`feedback_no_blanket_failure_verdict`、`feedback_promotion_only_falsification_evidence_gated`、`feedback_audit_surfaces_not_thorough`、`feedback_temporal_split_discipline`。

---

## §0 现状锚点

`chart_native_s1` = 63 日 ADJUSTED CLOSE(仅收盘)→ GAF 2ch 图 → frozen ImageNet ResNet18 → train-only ridge probe → 分数。config-scoped,NOT deployable。下游 long-only 月度 cap_aware top-N(construction-bound)。21d 远期、~1000 股截面、低 SNR、4GB VRAM。

---

## §1 四路独立深挖的**收敛结论**(最高价值 = 各自 primary 互相印证)

### 收敛①: 本问题是 canonical 低 SNR regime —— 浅/正则 > 深;我们的 frozen-pretrain→probe 是文献认可的最稳健姿态

- **Gu-Kelly-Xiu 2020 (RFS 33(5), NBER w25398) 原文逐字**: *"Shallow learning outperforms deeper learning"* —— NN 性能在 **3 层达峰**、更深退化;树平均 <6 leaves;明确归因 **小有效样本 + 极小 SNR**(与 CV/NLP 的天文数据相反)。这是金融收益预测"浅胜深"的 canonical primary,**直接外部印证我方房内发现"from-scratch 深网输给 pretrain→probe"**。
- **Raghu Transfusion 2019 (NeurIPS, arxiv 1902.07208)**: ImageNet→非自然图迁移增益主要来自**低层滤波器 + weight-scaling 统计量,不是语义迁移**;frozen-backbone + linear probe 是最稳健用法;from-scratch 仅对 oversized 模型在小数据吃亏。→ 我们能 work **很可能不是 ImageNet 学到图表语义,而是通用边缘滤波 + GAF implicit scaling**。脆弱但可接受,**必须证伪钉死**。
- **PatchTST / TS2Vec / TS-TCC**: 自监督 pretrain→probe 在 noisy/few-label 时序上一致 > from-scratch。与我方哲学同向。

### 收敛②: 图像的真实增量 = 隐式 per-name 截面归一化,**不是视觉形状魔法**

- **JKX 2023 (JF 78(6)) 自陈**: 传统信号仅解释 CNN 截面变异 **≤12%**(故 ≠ momentum 换皮),但**最大单一驱动 = implicit data scaling**(把每股 high-low 拉满图高);"做完该变换后一个线性模型即可逼近 CNN"。
- A、D 两 agent 独立收敛: 我们 close-only GAF 的 `[-1,1]` rescale = JKX implicit scaling 同构 → **解释了为何 momentum IC 在 ~1k universe 崩塌它仍保 ~0.10 IC: 它本质是自动 per-name 归一化器**。
- 含义: 把归一化几何**显式做成表格特征**(`close_pos_in_range` 等),树就能吃到 → 这是"图像到底必不必要"的硬 ablation。

### 收敛③: 图像**非必要**(是带损失再编码);下一 arm 最高 ROI = 工程化平稳特征 + XGBoost + stack frozen-probe 表征

- **ROCKET (Dempster 2020, DMKD 34)**: 随机 1D 卷积核 + 线性分类器 = TSC SOTA,快 2-3 数量级;深度非线性对多数 TSC 非必须。
- **Grinsztajn 2022 (NeurIPS D&B, arxiv 2207.08815)**: 低 SNR 金融工程表格**正落在"树赢"regime**,3 机制全中(target 不规则 / 无信息特征鲁棒 / 非旋转不变)。边界严格在 ≤10K medium i.i.d.,金融面板更脏 → 方向更强但**幅度需实测**;TabPFN 系反驳 scope 在 i.i.d. 干净小表格,**不构成否定 GBDT 的理由**。
- **Krauss-Do-Huck 2017 (EJOR 259(2))**: 同一金融特征上 RAF 0.43% > GBT 0.37% > DNN 0.33%,**异构等权 ensemble 0.45% > 任何单模型**。
- **Grinsztajn §5.4**: frozen embedding 当 tree 输入列正是 deep 表征对 tabular 有用之处 → **把 frozen-probe embedding(PCA 16-32 维)当 XGBoost 额外列 stack** 是 primary 支撑的最佳融合。

### 收敛④: 多变量 OHLCV+S/R 的正确喂法(三条,按 ROI)

1. **JKX-style bar image**(OHLC 顶 78% + volume 底 17% + MA 线,单通道二值,保 implicit per-name scaling)—— canonical、被多次复现;**优于继续堆 GAF channel**(2501.12239 证多通道 GAF 不比单 bar 图好)。
2. **iTransformer (Liu 2024, ICLR Spotlight) variate-as-token** 或 **PatchTST (Nie 2023, ICLR) channel-independent** + **masked-patch 自监督预训练 → 冻结探针**: token 数=变量数 → 4GB 友好;CI 是低 SNR 抗噪默认,cross-variable mixing 仅作受控增量。
3. **工程化平稳表格特征 + XGBoost**(见 §3)。
- **支撑/阻力**: 文献无显式画 S/R 标准做法(定义不唯一+拟合自由度);用**距滚动极值的归一化距离**作 proxy,绝不喂裸价位,严格无 look-ahead。

### 收敛⑤: 我方 chart_native 链路的**"做出来没做透"缺口**(audit 纪律,诚实暴露)

- **López de Prado (Advances in Financial ML 2018, Ch.3-4,7)**: 21d 远期标签**严重重叠** → **必须 average-uniqueness 样本加权 + purged/embargo CPCV**。**当前 chart_native ridge probe 没有 sample-uniqueness 加权 → 这是明确缺口,很可能使 IC 虚高**(就是房内反复出现的"too good"陷阱机制根因)。
- **Zeng et al. DLinear (AAAI 2023) 的真正教训**: 任何 transformer/深度实验**必须同时跑 DLinear/NLinear 线性基线**,否则结果不可信 —— 进实验协议。
- **construction-bound caveat(4 agent 独立都标)**: 信号变好**不自动解决 sibling-by-construction**;必须在 NAV / Track-A 17 门验证,不能停在 IC 层宣布胜利。**禁 over-claim 任何架构"破 sibling"**。

---

## §2 直接回答用户的原始问题

| 问题 | 判定(scoped,非 blanket) |
|---|---|
| **CNN/图像是否真适合我们的信号** | **非必要,是带损失再编码**;主要价值(implicit 归一化)可显式复现。保留现状作 cheap 正交特征源,**不当 alpha**。若保留图像→升级 close-only GAF 为 JKX-style OHLC+vol+MA bar 图(canonical 加 OHLC/量方式) |
| **怎么处理 OHLC/成交量/支撑阻力** | OHLC/量 → JKX-style bar 图 **或** iTransformer/PatchTST variate/patch token;S/R → 距滚动极值归一化距离 proxy(无 look-ahead),**不显式画 S/R 线** |
| **Transformer/self-attention(1D 或多维)** | 值得开 research arm,**仅** iTransformer variate-token / PatchTST CI + masked-patch SSL pretrain→冻结探针(4GB 友好、低 SNR 抗噪);**不要** vanilla 深时间维 full-attention(DLinear 批判 + 低 SNR 过拟合);**必带 DLinear 基线** |
| **LSTM 怎么做** | 独立 from-scratch LSTM arm **本 regime 不值得**(GKX 浅胜深;Fischer-Krauss 2018: LSTM edge=高波动短反转、2010 后衰减、与下游 construction 冗余;"LSTM 默认"=开发便利偏差)。要序列表征 arm 用 **TCN(Bai 2018)冻结→probe 进 ensemble**,非 LSTM;LSTM 仅作科学对照基线。**非 blanket 否定**:单资产/高频/高 SNR/波动率任务 LSTM/TCN 合法 |
| **XGBoost 怎么做** | **最高 ROI 的下一 arm**: 工程化平稳特征(JKX 归一化几何 + 距极值 S/R proxy + K 线 body/wick/gap + 成交量 z + 分数差分价 + swing-structure,全逐月截面 rank)+ 浅 XGBoost(depth 2-4 + 早停)+ **stack frozen-probe embedding(PCA 16-32 维)当额外列**;**强制** sample-uniqueness 加权 + purged/embargo |

---

## §3 推荐排期(4 agent 收敛的优先级;cheap-first 是 sequencing 不砍 scope)

**L3 方案 A(后台 `bvsybf5et` 跑中)= 第一道 gate**。其结果出来后:

1. **(最高 ROI)工程化特征 + XGBoost + frozen-probe stack** —— primary 最强(GKX/Grinsztajn/Krauss)、最便宜、4GB 无压力。配套**必做** sample-uniqueness 加权 + purged/embargo + DSR 真 N。
2. 保留 frozen-probe(现状,房内已验)。
3. **JKX-style bar-image 升级**(加 OHLC/量 canonical 方式)+ **1D/ROCKET/GBDT ablation = "图像是否必要"的决定性硬对照**(若显式归一化的 1D/树追平图像 → 图像降级冗余;若图像仍显著高 → 形状有真增量,保留为正交源)。
4. **iTransformer/PatchTST + masked-patch 域内自监督预训练 → 冻结探针** arm(域内预训练应优于 ImageNet 域外迁移,但增量待实测、禁 vision 量级 overclaim)。
5. TCN 冻结→probe 进 ensemble(唯一值得的"序列"方向)。
6. **不做**独立 from-scratch LSTM(本 regime 错误选择,理由全 primary)。

**横切必做(correctness 缺口,非新功能)**: 给 chart_native 评估链补 **average-uniqueness 样本加权 + purged/embargo** —— 很可能影响所有现有 chart_native IC 数字,须诚实重算。

---

## §4 Scope / 不 over-claim

- 全部 = 研究 signal-quality 假设,**config-scoped、NOT deployable**;须走 Track-A/sealed/forward 漏斗才谈晋升(`feedback_promotion_only_falsification_evidence_gated`)。
- "树赢"primary 边界严格 ≤10K medium i.i.d.;金融面板更脏 → 方向更强幅度需实测,不照搬 GKX 0.40% R² 绝对数。
- **不下 blanket "deep 不行"**: deep 表征作 stack 输入列仍 additive(Krauss + Grinsztajn §5.4);是"加树 + 保留 deep 表征",非"弃 deep"。LSTM 判定是"本 regime 错误选择",非"LSTM 不行"。
- sibling-by-construction 是 binding constraint;以上改善的是信号源非线性/交互利用率,**不自动破 sibling**,后者需 construction-DOF(cadence/cross-asset/universe)另行攻击。

## §5 Primary 清单(canonical + 作者 + venue + 关键假设/局限)

Gu-Kelly-Xiu 2020 (RFS 33(5)/NBER w25398; 浅胜深、小样本极小 SNR);Jiang-Kelly-Xiu 2023 (JF 78(6); 增量主因 implicit scaling、传统因子仅释 ≤12%);Raghu Transfusion 2019 (NeurIPS, arxiv 1902.07208; 非自然图迁移=低层+尺度非语义);Dempster ROCKET 2020 (DMKD 34, arxiv 1910.13051; 随机 1D 核+线性=SOTA);Grinsztajn-Oyallon-Varoquaux 2022 (NeurIPS D&B, arxiv 2207.08815; 树赢 3 机制,scope ≤10K i.i.d.);Krauss-Do-Huck 2017 (EJOR 259(2); 同特征 tree≥deep,异构 ensemble 最优);Zeng et al. DLinear 2023 (AAAI, arxiv 2205.13504; 时间点-token attention permutation-invariant 丢序);Nie et al. PatchTST 2023 (ICLR, arxiv 2211.14730; patching+CI+masked SSL>监督);Liu et al. iTransformer 2024 (ICLR Spotlight, arxiv 2310.06625; variate-as-token);Lim et al. TFT 2021 (IJF 37(4); VSN 变量选择);Bai-Kolter-Koltun 2018 (arxiv 1803.01271; TCN≥LSTM 普遍、并行/梯度稳/记忆更长,domain-shift 退化);Fischer-Krauss 2018 (EJOR 270(2); LSTM edge=高波动短反转、2010 后衰减);López de Prado 2018 (Advances in Financial ML; 分数差分/triple-barrier/sample-uniqueness/purged-CPCV);Kakushadze 2016 (101 Formulaic Alphas, arxiv 1601.00991; OHLCV→截面算子词典);Wolpert 1992 (Stacked Generalization)。

关联 [[project-backtest-robustness-ml-redo-2026-05]] [[project-grand-audit-2026-05-18-two-p0]] [[feedback_websearch_fuzzy_to_primary_depth]]。
