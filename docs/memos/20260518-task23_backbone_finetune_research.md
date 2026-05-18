# task#23 — 现代 backbone / 微调策略研究结论(websearch,fuzzy→primary)

**日期**: 2026-05-18
**触发**: 用户 2026-05-18 "S2 结束快,试更大模型?resnet18 怎么
fine-tune,放开最后一层吗?…你肯定要去做 search 的"。
**纪律**: `[[feedback_websearch_fuzzy_to_primary_depth]]`(fuzzy seed
→真关键词→primary 原文→挖透;不泛搜定论)+
`[[feedback_websearch_sealed_data_discipline]]`(只查模型/方法论,
非市场数据 —— 本研究全程合规)+ `[[feedback_no_blanket_failure_verdict]]`
+ 诚实优先级(不 over-claim、不当 yes-man)。

---

## §1 答用户的直接问题(resnet18 在 S1 怎么用的 / 放开微调更好吗)

- **S1 实情**:resnet18 **完全冻结**(`fc=Identity`,全参 `requires_
  grad_(False)`,`eval()`),**零 fine-tune,连末层都没放开**;只有
  网络外的 ridge probe 在拟合。是最保守用法。
> ⚠️ **RETRACTION(2026-05-18,用户批评 + operator 自纠)**:下面
> 单凭 **一篇** Kumar(LP-FT)就近-blanket 判"微调对 GAF 很可能更糟"
> **是过急的**——违反我自己刚立的 `[[feedback_websearch_fuzzy_to_
> primary_depth]]`"挖透"纪律 + `[[feedback_no_blanket_failure_verdict]]`。
> 真实现状 = **没定论、强 condition-dependent**:反方有 Surgical-FT
> (Lee ICLR2023,该调哪层取决于迁移类型)、远域迁移常规经验(目标
> 域远时 frozen ImageNet 特征常本就弱、需微调/域内 SSL,医学/卫星
> 等非自然图主流微调)、且 Kumar 否定的是 naive full-FT **不是**
> 微调本身。**正确口径 = literature mixed;一篇定论已撤;裁决靠
> 多源 lit review(排 L3 之后正经做)+ 我们 pipeline 内实测 A/B。**
> 下文保留作 forensic,不作判决依据。

- **"放开微调会更好吗" —— ~~primary 文献给出诚实 pushback:对 GAF
  这种大分布迁移,很可能更糟**:
  - **canonical primary**:Kumar, Raghunathan, Jones, Ma, Liang,
    *"Fine-Tuning can Distort Pretrained Features and Underperform
    Out-of-Distribution"*, **ICLR 2022, arXiv 2202.10054**。
  - 核心结论:当(a)预训练特征好 +(b)分布迁移大,**full
    fine-tune 会扭曲(distort)预训练特征,OOD 反而比 linear-probe
    差**(10 个 shift 数据集:full-FT in-dist +2% 但 **OOD −7%** vs
    linear-probe)。
  - **GAF 金融图 ≈ 相对 ImageNet 的极大分布迁移**(GAF 非自然图,
    审计员 finding 正是此点)→ 直接落在"特征好+迁移大"区间 →
    naive full/last-block fine-tune **预期扭曲、OOD 退化**。
  - **正解 = LP-FT**(先只训 linear head,再 full fine-tune):同
    论文证 beats both(in-dist +1% / **OOD +10%** vs full-FT)。

## §2 现代小强 backbone 推荐(替代 ImageNet-resnet18)

- **DINOv2 ViT-S/14**(Meta 自监督,~21M 参,4GB 冻结可行):
  primary 定位 = **专为"单一冻结 backbone、无需任务微调"设计**,
  迁移性强于 ImageNet-监督 CNN。fuzzy seed 反复指向 DINO 家族为
  当前 frozen-feature-extraction SOTA(DINOv3 2025 同向但更大)。
  来源:DINOv2 (Oquab et al. 2023, arXiv 2304.07193) / DINOv3
  (arXiv 2508.10104)。
- 用户的 "YOLO 系列" 是**类比**(小+强);但 YOLO 是目标检测非
  通用特征器 —— 真正对口的现代小强 frozen 特征器 = **DINOv2
  ViT-S**(次选 ConvNeXt-tiny / timm 监督 backbone)。
- 4GB 约束下参数高效适配:**LoRA**(注入低秩矩阵、backbone 冻结,
  显存 −~35%)是可行的 partial-adaptation 选项。

## §3 推荐的 S1-线 lever(IF 继续做 chart-native;按 primary 排序)

1. **冻结 backbone 升级**:frozen resnet18-ImageNet → **frozen
   DINOv2 ViT-S** + ridge/linear probe(零微调,最 OOD-robust,
   4GB 可行)—— 最低风险、最有文献依据的第一步。
2. **若要微调**:**LP-FT**(Kumar 2022),**绝不** naive full /
   last-block FT(GAF 大迁移下预期扭曲 OOD)。
3. LoRA 作 4GB 友好的 partial-FT 备选。

## §4 诚实优先级(不 over-claim,接 task#21 现实)

**这些 lever 有依据、但优先级 LOW,除非 chart-native 线被决定推向
L3**:task#21 刚证 S1(frozen ImageNet)在 train-only CPCV 上**已
> 强 tabular 锚 0.058**(L2 已达)。**binding 问题是 L3**(vs-SPY
硬门/成本/压力/forward)——cycle13b 已证 IC 高也被 vs-SPY/covid
拦掉。**换更好 backbone 只提升 L2 的 IC,不解决 L3**;JKX 规模论
(exec-79 train-only 不可外推)亦不被 backbone 升级消除。

∴ #23 deliverable = **研究结论 + 有依据的 lever 清单(本 memo)**;
**实验本身 deferred**(4GB-bounded + 须排在"是否推 chart-native 到
L3"的 directional 决策之后,非 operator 单方启动)。**不写"换
DINOv2 会更好"——只说"若继续此线,这是有 primary 依据的正确做法,
且 full-FT 那条直觉被文献证伪"。**

## §5 来源(均模型/方法论,非市场数据)
- Kumar et al., LP-FT, ICLR 2022 — https://arxiv.org/abs/2202.10054
- DINOv2, Oquab et al. 2023 — https://arxiv.org/abs/2304.07193
- DINOv3 2025 — https://arxiv.org/html/2508.10104v1
