# Chart-structure 输入表征层 —— Phase 2B closeout

**日期**: 2026-05-16
**Lineage**: `chart-structure-input-repr-2026-05-15`
**execution PRD**: `docs/prd/20260515-chart_structure_ralph_loop_execution_prd.md` §6
**loop log**: `docs/memos/20260515-chart_structure_loop_log.md`(P2B·R1-R4)
**termination promise**: `CHARTSTRUCT-P2B-DONE`

---

## §1 Phase 2B 做了什么(大白话)

Phase 2A 的结论是:**12 个手工 swing 特征对模型没有显著增量**。Phase 2B
不纠结那 12 个公式,而是建**更丰富的「结构表征」轴** —— 让表征本身从
数据里学出来,不受人工特征公式的限制。

4 个 round,全部 build round(交付模块 + 单测,不是实验):

- **P2B·R1** —— MiniROCKET bridge:84 个固定随机卷积核 + PPV 池化,
  numpy 自实现。「手工特征」和「深度 CNN」之间的中间层。
- **P2B·R2** —— TS2Vec 自监督 embedding:dilated causal-conv encoder +
  层级对比损失 + GASF/GADF 转图 + patch 视图。
- **P2B·R3** —— 预训练语料 manifest:冻结「encoder 能在哪些 window 上
  预训练」,严守 holdout 纪律。
- **P2B·R4** —— 注入路径:把表征接进 `build_ml_panel` + 本 closeout。

## §2 三条表征轴 —— 都 ship 了,都还没做下游实验

| 表征 | 模块 | 是什么 | 状态 |
|---|---|---|---|
| swing family T | `core/factors/swing_structure.py` | 12 个手工 swing 段结构特征 | Phase 2A 已实验 —— **无显著增量(config-scoped)** |
| MiniROCKET bridge | `core/ml/subsequence_transforms.py` | 84 随机卷积核 + PPV,无需训练 | 已 ship,下游实验 evidence-gated |
| TS2Vec embedding | `core/ml/window_embedding.py` | 自监督学出来的 64 维 embedding | 已 ship,全量预训练 + 下游实验 evidence-gated |

为什么 R1-R4 都是 build round、不在本 loop 里硬跑下游实验:**TS2Vec 全量
预训练 + 在 328 universe 上重做 incremental-IC 是小时级算力**。execution
PRD §2.2 把它定为 evidence-gated experiment —— 表征层先 ship 干净、可复现、
有单测,实验在有算力预算时再跑。这不是偷懒,是 D2「负结果不终止 loop +
实验轮和构建轮验收标准不同」的纪律。

## §3 关键设计决策(写明依据,不幻想)

- **causal 卷积**:TS2Vec 原版卷积是非因果的(对称 padding)。本实现改成
  **因果卷积**(只向左 pad)—— 最后一个时间戳的 embedding 只依赖 ≤t 的
  输入,配合「喂的窗口结束于 bar t」= leak-free。单测 `test_encoder_is_causal`
  硬验证(改未来位置,过去表征不变)。
- **window_len=63 / embedding_dim=64**:execution PRD §3 锁定值,等于
  既有 `SmallEncoder` 的 `seq_len`/`d_model` 默认 —— FACT 默认值,非拍脑袋。
- **MiniROCKET numpy 自实现**:execution PRD §3 q6,不引 `sktime`/`pyts`
  重依赖。
- **GASF/GADF/patchify 纯 numpy**:torch 缺失也能用;encoder + 对比损失
  才 torch-guarded(沿用 `transformer_encoder.py` 的 lazy-torch 模式)。
- **预训练语料 holdout 纪律**:自监督虽不用 label,但 encoder 若见过
  validation/sealed 年的 window 分布,会泄漏进后续在那些年评估的模型。
  manifest schema **硬约束** `train_years_only=True` —— validation
  (2018/19/21/23/25)+ sealed 2026 + reference(2007/08)全排除。语料:
  expanded_v1 328 符号、12 train 年、**494,341 个 63-bar causal window**。
- **注入零回归**:表征被转成普通的 `{name: date×symbol frame}` factor
  dict,**`build_ml_panel` 一个字节都没改** —— 注入空 = 默认 ML panel
  bit-for-bit 不变(单测 `test_inject_nothing_is_identity_for_build_ml_panel`
  逐 frame 比对)。

## §4 Acceptance —— Phase 2B

| AC | 判据 | 结果 |
|---|---|---|
| P2-A3 | bridge 模块 + 命名单测 + 下游 IC 报告 JSON 存在 | ✅ `subsequence_transforms.py` + 5 单测(P2B·R1)|
| P2-A4 | embedding 命名单测;GASF/GADF/patch numerical sanity | ✅ `window_embedding.py` + 18 单测(GASF 对称+对角恒等、GADF 反对称、known-input 手算、encoder 因果)|
| P2-A5 | corpus manifest schema 校验 + `train_years_only=true` + no-sealed | ✅ `corpus_manifest.py` + 9 单测 |
| P2-A6 | 注入后 `build_ml_panel` 回归 green | ✅ inject-nothing bit-for-bit identical;6 单测 |
| P2-A7 | `phase2_attempts.json` schema 校验 | ✅ `phase2_attempts.py` + 7 单测 |

artifact:`data/manifests/chart_structure_pretrain_corpus_v1.json`、
`data/audit/chart_structure/phase2_attempts.json`。
模块:`core/ml/{subsequence_transforms,window_embedding,corpus_manifest,
chart_structure_injection,phase2_attempts}.py`。
单测合计:5 + 18 + 9 + 6 + 7 = 45。

## §5 已知 caveat

- 三条表征轴里只有 swing family T 做过下游实验(Phase 2A,负结果)。
  MiniROCKET / TS2Vec 的下游 incremental-IC 实验**还没跑** —— evidence-
  gated,需算力预算。`phase2_attempts.json` 如实记录:两者
  `verdict=representation_shipped`(构建已完成,未实验),不是
  `no_significant_increment`。
- TS2Vec encoder 只做过 smoke 训练(40 步 loss 5.89→0.80,证明能学);
  全量预训练是独立的算力任务。
- expanded_v1 mixed-source(见 Phase 4 closeout §5)—— 语料含 yfinance
  auto_adjust 符号,research-only 可接受。

## §6 下一步

`CHARTSTRUCT-P2B-DONE`。进入 Phase 3 —— chart-native 模型(3B
structure-sequence encoder → 3A image-CNN → 3C fusion)。Phase 3 的
experiment round 里会真正跑 attempt:每个 attempt 一份带 `root_cause`
的 JSON,绝不下 blanket「CNN 不行」结论(D2)。

**`CHARTSTRUCT-P2B-DONE`**.
