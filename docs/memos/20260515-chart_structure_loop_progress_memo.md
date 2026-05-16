# Chart-structure 输入表征层 ralph-loop —— 进度 memo(说人话版)

**日期**: 2026-05-15
**作者**: resident quant operator
**Lineage**: `chart-structure-input-repr-2026-05-15`
**给谁看**: 用户 —— 这是 chart-structure 方向自动化执行到目前为止的完整、
诚实交代。

---

## 0. 一句话总结

把 K 线/形态结构转成 ML 特征这个方向,**Phase 1 把第一版特征(swing 段
结构)造出来并接进系统了;Phase 2A 用真实数据严格检验了它 —— 结论是:
这 12 个特征对模型预测力没有统计显著的增量贡献**。这不是「方向死了」,
但是一个**必须正视的负信号**,它直接影响后面 Phase 3(深度 CNN,要花
大量 GPU 算力)值不值得现在就上。

---

## 1. 这个 loop 在干什么(背景)

你之前的观察:PQS 所有因子都是「图 → 压成一个数 → 排名 → 选 top-N」,
丢掉了图的结构。我们立了一份 PRD(`docs/prd/20260515-chart_structure_
input_representation_prd.md`)+ 一份把它拆成 17 个小步的执行 PRD,然后
按 ralph-loop 一步步跑。

4 个 Phase:Phase 1 swing 段结构特征 → Phase 2 检验「结构输入有没有用」
→ Phase 3 chart-native 模型(CNN 等)→ Phase 4 universe 扩张。

---

## 2. 已完成的部分(都是真跑、真测、已 commit)

### Phase 1 —— swing 段结构 family T(3 轮,全部完成)

把价格序列压成「swing 段序列」(一串交替的高低点),从段与段的关系派生
12 个结构特征(段长比、斜率比、斐波那契回撤贴合度、推动 vs 调整打分、
趋势成熟度…),进 PQS 的因子注册表。

| commit | 内容 |
|---|---|
| `adb0c98` | P1·R1 因果 swing 核心 |
| `893ad98` | P1·R2 12 个特征 |
| `1ea1ad8` | P1·R3 接进 registry(RESEARCH_FACTORS 175→187,family T)|

**Phase 1 期间抓到并修掉 3 个真问题**(都不是走过场):
1. **因果 bug**:swing 检测的「合并」步骤如果在「按日期过滤」之前做,
   会用未来的 swing 决定丢弃哪个过去的 swing —— 等于偷看未来。改成
   先过滤再合并。
2. **指标退化**:我第一版写的特征公式里,有 3 个(impulse/corrective/
   trend_maturity)在「严格交替的 swing 序列」里是退化的(恒为 0 或恒
   为 1,等于没用)。发现后上报你、你批准,改成「隔 2 段比较」的正确
   定义。
3. **性能**:接进主因子生成函数后全套测试从 11 分钟涨到 24 分钟。用
   「增量合并」优化(数学上等价)修回。

### Phase 2A —— 检验 family T 有没有用(2 轮,完成)—— **关键结果**

做了一个严格的配对实验,在**真实的 79 只股票 × 4276 天**面板上:
- 对照组:101 个现有因子。
- 实验组:101 个 + 12 个 swing 特征 = 113 个。
- 同一个 ML 模型(rank:ndcg XGBoost)、同样的时间切分、同样随机种子 ——
  唯一区别就是那 12 列。
- 看 17 年里每年的预测力(Rank IC),做配对 t 检验。
- swing 窗口长度 K 扫了 6 / 8 / 12。

**结果(`b07a246`)**:

| K | 平均增量 IC | p 值 | 显著? |
|---|---|---|---|
| 6 | +0.0075 | 0.078 | 否(最接近)|
| 8 | +0.0029 | 0.54 | 否 |
| 12 | +0.0030 | 0.38 | 否 |

**三个 K 全部不显著**。也就是说 —— 这 12 个 swing 结构特征,加进去之后
**没有让模型多预测对**(三个 K 的增量都是微弱正数,没变差,但统计上分
不出来)。

**为什么?**(我的分析)对照组那 101 个因子里**已经有** Family R(图形
形态:突破、均线交叉、连涨)+ Family D(趋势质量)+ 一堆动量因子。swing
段结构本质上和「趋势 / 形态」是同一类信息。模型从那 101 个因子里早就把
趋势结构信号学走了 —— 再加 12 个 swing 特征,**能贡献的「新」信息所剩
无几**。说白了:**新特征和老特征高度冗余**。

⚠️ 这个结论是 **config-scoped** 的 —— 说的是「这一版 12 特征 + 这个
模型 + 21 天 horizon 无显著增量」,**不是**「结构信息完全没用」。K=6
(短窗口)最接近显著,说明结构信号 faint 地存在、偏短周期。family T
没有被废弃,留在因子库里由长期漏斗裁判。

### P2B·R1 —— MiniROCKET bridge 表示层(完成)

`a4f1d1a`:`core/ml/subsequence_transforms.py` —— 一个 numpy 自实现的
MiniROCKET 式变换(84 个固定卷积核 + PPV 池化),作为「手工特征」和
「深度 CNN」之间的中间层。模块 + 5 个单测已 ship。

---

## 3. 还没跑的部分 —— 诚实交代为什么在这里 checkpoint

剩下的:Phase 2B 的 R2-R4(TS2Vec 自监督 embedding 训练、GAF 转图、
语料 manifest、注入)、Phase 3(5 轮,chart-native CNN —— 要训练神经网络)、
Phase 4(3 轮,universe 扩到 200-500 只 —— 要 ingest 几百只新股票的数据)。

**为什么现在停下来写这份 memo,而不是硬跑完**:

1. **算力现实**:剩下的几乎每一轮都是小时级算力 —— TS2Vec 要训练、CNN
   要训练(多次 attempt)、universe 扩张要 ingest 几百只股票数据。一个
   自动化连续会话里硬压这 10 轮,要么很多个小时,要么质量打折。你这一
   整个 session 反复强调的就是「不要幻想、要真跑真验证、质量优先于走
   过场」—— 我不能为了「跑完」而糊弄。

2. **更重要的:Phase 2A 是个战略岔路口**。Phase 2A 已经用真实数据告诉
   我们:**最便宜、最先做的那版结构特征,没有增量**。在这个负信号之后,
   不跟你打招呼就直接砸下 Phase 3 的 GPU 算力去训 CNN,是**拿证据不当
   回事的走过场**。一个称职的操作员该在这里把结果摆出来,让你决定。

---

## 4. 操作员的战略判断(我的独立意见)

**Phase 2A 的负结果,本质上是说:在 PQS 现有的 79-stock × 已有 101 因子
的设定下,「把同一批价格信息换一种结构化表示」很难再挤出增量 alpha ——
因为老因子已经把趋势/形态信息吃得差不多了。**

这跟 memo v2 §5 早就写下的诊断是一致的:真正卡住的不是「输入表示不够
好」,是 **sibling-by-construction**(候选被 79-universe × 同构造绑死)。
Phase 2A 等于又给这个诊断添了一个实证。

我的建议(供你决策,不是我替你定):

- **选项 A —— 先做 Phase 4(universe 扩张),再回头做 Phase 2B/3**。
  Phase 2A 的负结果根因是「老因子已经够多 + universe 太小」。先扩
  universe(79→200-500),既是 Phase 3 CNN 的数据前提,也直接攻
  sibling 根因。在大 universe 上重做 incremental-IC,结论可能不同。
  **这是我最推荐的次序调整**。

- **选项 B —— 继续按原顺序 Phase 2B → 3 → 4 硬跑完**。可以,但 Phase 3
  CNN 在 79-universe 上是 PRD §6 早就写明的「过拟合陷阱」,在 Phase 4
  之前跑 3A image-CNN 价值存疑。

- **选项 C —— 把 Phase 2A 当成方向性结果,暂缓重算力投入**,先消化
  「结构表示在小 universe 上增量有限」这个结论,把资源放回别的 alpha
  方向。

我个人倾向 **A** —— 它符合 PRD 自己的依赖图(Phase 3-3A 本来就 gated
on Phase 4),也直接回应 Phase 2A 暴露的根因。

---

## 5. 全部 commit 清单(本 loop 至今)

| commit | round | 内容 |
|---|---|---|
| `adb0c98` | P1·R1 | 因果 swing 核心 |
| `893ad98` | P1·R2 | 12 个 swing 特征 |
| `1ea1ad8` | P1·R3 | registry 接线 + Phase 1 closeout |
| `ec535dd` | P2A·R1 | incremental-IC harness |
| `b07a246` | P2A·R2 | incremental-IC 实验(负结果)|
| `a4f1d1a` | P2B·R1 | MiniROCKET bridge 层 |

文档:执行日志 `docs/memos/20260515-chart_structure_loop_log.md`(每轮
11-part 报告);Phase closeout `..._phase1_closeout.md` / `..._phase2a_
closeout.md`。

---

## 6. 你需要拍板的

剩下 Phase 2B(R2-4)/ 3 / 4 怎么走 —— 选项 A / B / C 见 §4。你定方向,
我接着按 ralph-loop 跑。我倾向 A(先 Phase 4 扩 universe)。
