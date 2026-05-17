# ML 方法论 literature review —— chart-native redo 前的文献基线

**日期**: 2026-05-16
**触发**: 用户质疑 Phase 3 是否按 literature 已证明路径做(不是最 naive 尝试);
要求 websearch → supplementary PRD → 重做。
**方法**: fuzzy→具体分级 websearch + canonical 源深读;**全程仅查方法/
论文/理论,零当前年市场表现数据**(memory `feedback_websearch_sealed_data_discipline`,
sealed 2026 未触碰)。
**定位**: 本 memo = Step5 综合,是 supplementary PRD(Step6)的 SoT。

---

## §0 两个问题的直接回答

**Q1:之前的因子适合 ML 吗?**
**适合 tree/NN,已是 literature 共识。** Gu-Kelly-Xiu《Empirical Asset
Pricing via Machine Learning》(RFS 2020)= 该领域 canonical:trees +
神经网络表现最好,预测增益来自"非线性 + 预测变量交互",**所有方法都
指向同一组主导信号 = 动量/流动性/波动率**,ML 相对回归型策略收益可翻倍。
→ PQS 175+ 表格因子喂 tree/NN 是 literature-backed;Phase 1.6
`rank:ndcg` 已验证(94% linear baseline)。**"因子不适合 ML"不成立。**

**Q2:Phase 3 按 literature 路径了吗?**
**Phase 2A 部分(比 naive 好但非 literature-grade);Phase 3 否。**
P2A 用了 rank + LOTYO + 边界 purge,但缺 sample-uniqueness 加权 /
sector-neutral / winsorize / vol-scale / CPCV / DSR-PBO——"family T
无增量"是地基结论,**必须 R2.5 复检**(初稿曾误称 P2A"严谨不重做",
已纠正,见 §2 修正块 + supplementary PRD §13)。Phase 3 的 3A/3B/3C
= **从零监督训练的小模型**,literature 明确预测这种 regime 会失败。
**结论:Phase 3 负结果不是"chart-native 不行"的干净检验,必须 redo;
P2 地基同步复检。**

---

## §1 Literature-proven 路径(分 7 轴,每条带来源)

### A. 数据准备 / 清洗工程(用户强调"非常重要")
- **横截面 rank 归一化**:每个 rebalance 月内对全 universe 按因子值
  排名 → 映射 [0,1] 百分位。**动态、逐切片做以防 look-ahead**。是
  stock-prediction 的标准预处理(LASSO/LightGBM/FFN 通用)。[S12]
- **Winsorize**:极值 hard-cap 在 1/99 百分位,去掉新闻/异常事件尾部。[S12]
- **Sector / industry neutralization**:回归掉行业效应,避免无意 sector
  bet;**vol-scaling**(按历史波动缩放)。[S12]
- **Fractional differentiation**(López de Prado):整数差分抹掉价格序列
  "记忆";找**最小 d 使序列平稳**,在平稳性与记忆间取平衡——比直接
  log-return 保留更多信息。[S5][S9]
- 非平稳是金融时序第一难题:DL 论文标准做法 = z-score 归一化(均值0
  方差1)+ **定期 retrain**(不 retrain 模型质量随时间衰减)。[S3]

### B. Label 构造(Phase 3 用裸 21d fwd return = 偏 naive)
- **Triple-barrier labeling**(LdP):每个样本设上障(止盈)/下障(止损)
  /竖障(到期);先碰哪个决定 label ∈ {+1,0,−1}。比固定 horizon return
  更贴近真实交易。[S5][S8]
- **Meta-labeling**:主模型出"方向",二级 ML 学"下注大小"——把
  precision/recall 解耦。[S5][S8]
- **Sample uniqueness / concurrency 加权**:重叠 label 的样本不独立;
  算每个样本生命周期内的平均唯一度(并发标签倒数均值),**bagging 时
  max_samples=平均唯一度**,或样本加权。重叠样本权重→0,独立样本→1。[S5][S8]

### C. 验证纪律(Phase 3 年块切分 = 粗糙近似;literature 金标准更严)
- **Purged k-fold + embargo**(LdP 2017):purge = 删掉 label 形成期与
  test 时间重叠的训练样本(test 前后都删);embargo = test 之后再删一
  小段(默认 ~1% 观测;吸收市场反应滞后),**只能在 test 之后**。
  标准 k-fold 对金融时序"根本无效"(IID 假设崩)。[S6][S10][S11]
- **CPCV(Combinatorial Purged CV)**:N 个连续不重叠组,取所有 C(N,k)
  种 k-组合做 test,产出 **OOS 表现分布**(不是单点),φ[N,k]=(k/N)·C(N,k)
  条独立回测路径。统计推断更稳。[S6][S10]
- **过拟合度量**:**Deflated Sharpe Ratio**(Bailey-LdP)——按"你试了
  多少个没给我看的策略"+ 偏度峰度,把 Sharpe 打折;False Strategy
  Theorem:即便所有策略真 Sharpe=0,试得够多最高的也会显著为正。
  **PBO(Probability of Backtest Overfitting)**配套。[S13][S14]

### D. 自监督表征(Phase 3 完全跳过 = 核心偏离)
- SSL-for-TS taxonomy [S2]:三大类 = generative(自回归预测 / **masked
  autoencoder** / diffusion)、contrastive(sampling/prediction/
  augmentation/prototype/expert-knowledge)、adversarial。
- **低标签/回归 regime 的 proven 配方**:**MAE(segment-wise masking)
  在无标签数据上预训练 → 5-10% 标签 fine-tune** 是推荐 baseline;
  **TS2Vec**(hierarchical contrastive,random crop + timestamp mask,
  temporal+instance 双层——Phase 2B 已造!)强泛化;**TS-TCC**(弱增广
  Jitter-Scale + 强增广 Permutation-Jitter)适合多变量;**CoST**
  (seasonal-trend 解耦)直接对付非平稳。[S2]
- **关键**:"少量标签 + 预训练/fine-tune 即可高性能"——Phase 3
  从零监督正是跳过这条。[S2]
- **不要直接搬 CV/NLP 增广**(rotation/crop 破坏时序依赖),要 TS 专属。[S2]
- 金融专属 SSL 先例:《Contrastive Learning of Asset Embeddings》
  (ICAIF 2024)——正负对用**共现 top-k 相关性的比例假设检验**(z→p,
  α+=0.05 正 / α−=0.30 负)抗金融噪声;w=22/stride=5/topk=5,L2 单位
  超球,Adam 1e-3 bs128 30ep,emb=16;下游 sector 分类 + 对冲均超
  Pearson 基线。[S4](注:它是关系型 embedding,非 return 预测;可借
  "噪声鲁棒正负对构造"思想)。
- TS2Vec-Ensemble(arXiv 2511.22395):encoder + 工程特征融合。[S4]

### E. chart-image(3A 路径)
- GAF(Wang-Oates 2015)把 1D 序列编码成 2D 图给 CNN;GAF-CNN 在
  20 个标准集赢 9 个,GADF+GASF ResNet ~90%。[S7]
- **已证限制**:GAF/MTF **对噪声敏感、过度强调局部而牺牲全局结构**;
  多通道堆叠计算/显存代价高。[S7] → 解释为何 naive 小 CNN 在低信噪
  金融数据上弱;literature 路径是 **GAF + 树模型常反超 GAF + 从零CNN**
  (PRD §5.2 已引,本轮二次确认方向)。

### F. Ensemble(后续必走,literature 有 proven 配方)
- **Stacking + out-of-fold**:base 模型 5-fold OOF 预测当 meta-feature,
  **meta-model 用简单 Linear/Ridge**(复杂 meta 极易过拟合 base 预测);
  Ridge 比 Linear 好(正则处理 base 间相关)。[S15a][S15b]
- 关键价值:**stacking 能把"弱但正交、可加"的信号融进去而不被强信号
  淹没**;OOS 增益在极端下行市尤其明显。[S15a] → 直接对应:chart-native
  即便单挑输动量,作为弱正交信号 stack 进去仍可能有边际价值(主 PRD
  §5.2 ensemble 候选定位的 literature 支撑)。
- **Autoencoder / FactorVAE** 解 factor-zoo(降维抽潜在定价因子)优于
  单纯 LASSO。[S1b]

### G. 失败模式(Step4,提前知死路)
- **可复现性危机**:多数 DL 论文不给代码/超参,"**多数 DL 方法打不过
  naive baseline**,只有少数勉强超过";不 retrain 就衰减。[S3]
- **结构性断裂过拟合 + 非 IID**:复杂模型 train 好 test 崩(regime
  shift + 无套利侵蚀);MoE/路由网络部分缓解。[S1b]
- **多重检验/选择偏差**:试 millions 策略必出假阳性 → 必须 Deflated
  Sharpe / PBO 把关。[S13][S14]
- 黑箱不可解释(监管/可信度);金融数据稀缺昂贵限制复现。[S1b]

---

## §2 Phase 3 偏离 literature 的精确清单(redo 必修)

| 维度 | Phase 3 naive 做的 | Literature proven | redo 必做 |
|---|---|---|---|
| 预训练 | 从零监督 | SSL 预训练→fine-tune(MAE/TS2Vec)[S2] | 用 Phase2B TS2Vec/MAE 预训练 |
| Label | 裸 21d fwd return | triple-barrier / sample-uniqueness 加权 [S5] | 至少加并发加权;评估 triple-barrier |
| 数据预处理 | 仅横截面 z-score 目标 | rank-norm + winsorize + sector-neutral + vol-scale + 评估 fractional-diff [S12][S5] | 全套上 |
| 验证 | 年块 fit/OOS(已修边界 purge)| CPCV + embargo + Deflated Sharpe/PBO [S6][S13] | 升级 CPCV + 加 DSR/PBO 报告 |
| 训练 | 固定 lr 80ep 无 early-stop 无 HPO | 验证集 early-stop + LR schedule + HPO + 定期 retrain [S3] | 全套上 |
| 增广 | 无 | TS 专属增广(jitter/permutation/mask),禁 CV/NLP 搬运 [S2] | 加 TS 专属增广 |
| 模型角色 | 单挑动量 | 弱正交信号 → stacking ensemble [S15a] | redo 含 ensemble 评估 |

**已合规、不重做**:temporal_split 纪律(本会话已修
partition_for_role(miner)+purge);D6 隔离 + `--universe` 全链路
(GAP1-4);基础设施**模块代码**(因果 swing / GAF / TS2Vec encoder /
fusion / universe resolver)。

**修正(2026-05-16,supplementary PRD §13 audit)**:本 memo 初稿曾把
**Phase 2A 列入"已合规不重做"——overclaim**。P2A 比 naive 好(rank +
边界 purge)但缺 sample-uniqueness 加权 / sector-neutral / winsorize /
vol-scale / CPCV / DSR-PBO,**非 literature-grade**;"family T 无增量"
是地基结论,须经 R2.5 复检(supplementary PRD §5.5)。Phase 2B 的
MiniROCKET/TS2Vec **下游 IC 从未跑、TS2Vec 仅 40 步 smoke 从未全量
预训练**——"造好≠做透",补做于 R3(full-pretrain)+ R2.5-b。Phase 4
expanded_v1=328 规模是主 PRD §C 自承 PLACEHOLDER,literature 需更大
cross-section → R-P4ext(~1k + survivorship 审计)。详 supplementary
PRD `docs/prd/20260516-ml_methodology_supplementary_prd.md` §13。

---

## §3 来源表(全部方法/论文性质,未触 sealed)

| ID | 来源 | URL |
|---|---|---|
| S1a | Gu-Kelly-Xiu, Empirical Asset Pricing via ML, RFS 2020 | https://www.nber.org/system/files/working_papers/w25398/w25398.pdf |
| S1b | From Factor Models to Deep Learning (asset pricing ML 综述) | https://arxiv.org/html/2403.06779v1 |
| S2 | Self-Supervised Learning for Time Series: Taxonomy (arXiv 2306.10125) | https://arxiv.org/html/2306.10125v1 |
| S3 | Financial Time Series DL — Practical Recommendations (MDPI) | https://www.mdpi.com/2673-4591/39/1/79 |
| S4 | Contrastive Learning of Asset Embeddings (ICAIF 2024) | https://arxiv.org/html/2407.18645v1 |
| S5 | López de Prado, Advances in Financial ML (notes) | https://reasonabledeviations.com/notes/adv_fin_ml/ |
| S6 | Purged cross-validation (mechanics) | https://en.wikipedia.org/wiki/Purged_cross-validation |
| S7 | Imaging Time-Series (GAF, Wang-Oates 2015) | https://arxiv.org/pdf/1506.00327 |
| S8 | Triple-barrier / meta-labeling (Hudson&Thames / mlfinpy) | https://hudsonthames.org/does-meta-labeling-add-to-signal-efficacy-triple-barrier-method/ |
| S9 | Fractional differentiation (AFML ch.5) | https://reasonabledeviations.com/notes/adv_fin_ml/ |
| S10 | CPCV with code | https://www.quantbeckman.com/p/with-code-combinatorial-purged-cross |
| S11 | Pitfalls of standard CV in financial ML | https://bhakta-works.medium.com/the-pitfalls-of-standard-cross-validation-in-financial-machine-learning-aec03f672179 |
| S12 | Cross-sectional rank-norm / winsorize / neutralization (UCLouvain thesis) | https://thesis.dial.uclouvain.be/server/api/core/bitstreams/23918243-8c05-47b6-bada-855c77d38214/content |
| S13 | Deflated Sharpe Ratio (Bailey-LdP) | https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf |
| S14 | Min backtest length & deflated SR (Jansen ML4T) | https://stefan-jansen.github.io/machine-learning-for-trading/08_ml4t_workflow/01_multiple_testing/ |
| S15a | Stock return prediction: Stacking a variety of models (ScienceDirect) | https://www.sciencedirect.com/science/article/abs/pii/S0927539822000342 |
| S15b | Ensemble Learning in Investment (CFA Institute 2025) | https://rpc.cfainstitute.org/research/foundation/2025/chapter-4-ensemble-learning-investment |

---

## §4 4-tier 自审

- **R1 事实**:每条 proven 路径有 ≥1 来源(§3 表);Q1/Q2 结论锚定
  Gu-Kelly-Xiu + SSL taxonomy 原文,非臆测。
- **R2 逻辑**:§2 偏离清单逐条对应 §1 proven 项 + Phase3 实际代码
  (本会话 grep 实证);"Phase2A 合规 / Phase3 不合规"裂判与证据一致。
- **R3 真跑对比**:websearch/fetch 实际执行(非假设);MDPI 403 +
  LdP PDF >10MB 已记录,改用可达源补全(Wikipedia/notes/arXiv)——
  无 hand-wave。
- **R4 边界**:sealed 纪律每 query 自查(零市场表现数据);来源含
  "失败模式"轴(不只挑正面);明确标注 S4 是关系型 embedding 非 return
  预测(不夸大可迁移性)。

**下一步**:Step6 supplementary PRD —— 把 §1 proven 路径 + §2 必修项
落成可执行规格 + 验收门 + sealed/temporal_split 纪律。
