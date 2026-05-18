# Scaled / External Pretrained Checkpoint —— ML 架构研究 PRD

**日期**: 2026-05-17
**lineage**: `scaled-pretrain-checkpoint-2026-05-17`
**状态**: **DRAFT — 未授权**;实现需用户 explicit-go **+ 算力现实
(GPU)前置门**。
**触发**: 用户 2026-05-17 问"CNN/transformer 训练有没有用 pretrained
model?大模型从一个 reasonable checkpoint 开始会更好",并要求同步
准备 PRD。
**关系**: 独立于回测稳健性 PRD(G1-G5)与已 **CLOSED** 的 ML
supplementary PRD(D1-D4 完结)。这是**新一轮研究方向**,不阻塞也不
被 G2-G5 阻塞。
**纪律**: `feedback_no_over_conservative_scoping`(全 roadmap 进 scope,
排序≠砍 scope)、`feedback_no_blanket_failure_verdict`、
`feedback_temporal_split_discipline`、`feedback_self_audit_methodology`、
`feedback_websearch_sealed_data_discipline`(只查方法/模型,不查市场)。

---

## §0 一句话(大白话)

用户的直觉**已被项目自己的数据证实**:从一个合理预训练 checkpoint
出发(`mae_probe`)IC 0.045-0.048,**远胜从零训**(0.002-0.010,
landmark②/④ + D4)。但目前的 checkpoint 是**我们自己的小型 in-domain
MAE(d_model=64)**;**两处真实未测的 lever**:(1) GAF/CNN 那条路
**从未吃过任何 checkpoint**;(2) MAE 是小模型,**没试过更大 / 外部
checkpoint**。本 PRD 把"放大/外部 checkpoint"作为完整研究 roadmap
committed,但**算力(GPU)是硬前置**——不是不做,是先确认能不能跑。

---

## §1 现状(实查,2026-05-17)

| 模型 | 预训练? | 实查依据 |
|---|---|---|
| MAE encoder(Linear+GELU 小编码器,d_model=64/seq_len=63) | **是**,in-domain SSL(R3,461716 train-only 窗口/5000 步,`pretrain_mae.pt`) | `core/ml/ssl_pretrain.py`;`run_r4` load_state_dict fail-closed |
| ChartCNN(3 层 Conv2d 32→64→64) | **否**(C4/D4 故意 from-scratch 对照组) | `core/ml/chart_cnn.py` 无 load_state / 无 pretrain |
| gaf_tree | 不适用(GAF→梯度树) | —— |

**经验事实**:pretrain→probe >> from-scratch(IC 4-5×),D4 严格
per-fold 已确认不反转。**未测**:CNN/GAF 吃 checkpoint;放大 MAE;
外部基础模型 checkpoint。

---

## §2 目标

检验"放大 / 外部预训练 checkpoint 能否把 chart-native **研究信号**
(probe/CPCV IC,配 G1 honest-N DSR + G2 PBO)推到现有小 MAE
(~0.045-0.048)之上",并诚实记录受阻/负结果(禁 blanket verdict)。

**非目标**:不产可部署候选(Track A/sealed/forward 漏斗本 PRD 不走);
不引云/不破 macOS-local 不变量;不读 sealed 2026;不动 G1-G5。

---

## §3 算力现实(硬前置门 P0,先回答再谈别的)

- 现状:这些跑的是 **CPU torch**(D4 一个 3 层小 CNN per-fold 跑了
  6 小时)。任何"大模型 / 外部 backbone"在 CPU 上不可行。
- **P0 门 = GPU 可用性评估**:本机/本环境有无可用 GPU、显存多大、
  是否满足 macOS-local 不变量(无云)。**P0 不通过 → 整 PRD 挂起**
  (诚实记录,不假装能跑);P0 通过 → 按 §4 排序展开。
- P0 产出:`docs/memos/<date>-scaled_pretrain_compute_feasibility.md`
  (GPU 清单 + 各 S 项 wall-clock 估算 + 不可行项显式标注)。

---

## §4 Roadmap(全 committed;排序非 scope-cut;每项 machine-checkable AC)

### S1 — GAF/CNN 路径接视觉预训练 backbone
- **S1-A1**: GAF 图喂 ImageNet-预训练 CNN backbone(如 ResNet/
  EfficientNet)两种模式:frozen+probe / fine-tune;vs 现 from-scratch
  ChartCNN + vs mae_probe,同 CPCV/temporal-split/票池。
- **S1-A2**: 报告 per-fold IC + vs 动量 + **G1 honest-N DSR** + **G2
  PBO**;`verdict_scope=config_scoped`;诚实 caveat(ImageNet→GAF
  迁移文献 mixed,GAF 非自然图像)。
- **S1-A3**: ≥4 单测(管线 + 形状 + frozen/fine-tune 分支 + 退化)。

### S2 — 放大 in-domain MAE
- **S2-A1**: MAE encoder d_model/depth 放大(网格记录)+ 预训练语料
  扩大(train-only,manifest 预留多 timeframe),vs 现 d_model=64。
- **S2-A2**: scaling 曲线(模型尺寸/语料 → 下游 probe IC);honest-N
  DSR + PBO;sealed 全程未读断言。
- **S2-A3**: ≥4 单测。

### S3 — 外部时序基础模型 checkpoint
- **S3-A1**: **先做诚实 survey**(websearch,仅方法/模型,非市场)
  =是否存在"对原始价格形状/窗口、迁移到日频截面 IC 已被证明"的
  公开基础模型 checkpoint。**survey 负 → S3 显式标
  `no_credible_checkpoint_honest_caveat` 并停**(不硬塞一个未证迁移
  的 backbone 充数,禁 blanket"外部没用"——记 attempt+root-cause)。
- **S3-A2**: survey 正 → frozen-probe 接入,同 §4 评测口径。
- **S3-A3**: survey memo + (若做)≥3 单测。

### S4 — scaled-pretrain ensemble vs 现小 MAE
- **S4-A1**: S1/S2/(S3) 最优 arm 做 stacking OOF,vs 现 mae_probe
  单挑 + vs 现 C2 ensemble;边际贡献分解。
- **S4-A2**: honest-N DSR + PBO + `verdict_scope`;结论"放大是否真
  把 IC 推过现有 0.045-0.048"如实记(正负都不 over-claim)。
- **S4-A3**: ≥3 单测。

---

## §5 与其它工作的协同(诚实正向)

- **本 PRD 的所有 DSR 用 G1 honest-N + G2 PBO**——回测稳健性 PRD 让
  本 PRD 未来数字一开始就可信(不重蹈 placeholder-N overclaim)。
- 复用 supplementary PRD 的 R0 数据准备 / R2 CPCV-embargo /
  temporal-split partition(已 CLOSED,可直接当输入,不重造)。
- 与 G2-G5 互不阻塞:G 系列是回测验收/失效检测;本 PRD 是上游表征
  模型——可并行,但**算力串行**(重训不与 G 系列重活同时跑,见
  `feedback_heavy_training_serial_wsl`)。

---

## §6 限制与诚实记录(前置,不藏)

- 无"对原始价格形状/GAF 已证明迁移有效"的成熟基础模型;金融时序
  基础模型很新、迁移未证;ImageNet→GAF 文献 mixed。
- CPU 不可行 → GPU 为硬前置(§3 P0);P0 不通过整 PRD 挂起。
- 全 config-scoped、research 信号、**非可部署**;sealed 2026 不读。
- 负结果只写"这个 attempt 失败 + 用了什么 + root-cause",禁 blanket
  "放大/外部没用"(Phase 1.5→1.6 先例)。

---

## §7 验收口径

- P0 算力门产出 memo(不可行项显式标)= 展开 S1-S4 的前置。
- S1-S4 各 machine-checkable AC + honest-N DSR + PBO + verdict_scope
  + sealed-unread 断言 + 4-tier 自审 + 禁 blanket verdict = 各 S 完成门。
- 全 PRD DRAFT;实现需用户 explicit-go **且** P0 GPU 门通过。

---

## §8 参考(均方法/模型,非市场数据)

- López de Prado, *Advances in Financial ML*(SSL / CPCV / DSR/PBO)
- 待 S3-A1 survey 补:时序基础模型迁移性文献(websearch,方法类)
- 项目内:`docs/memos/20260516-ml_methodology_redo_closeout.md`(D1-D4
  现状)、`docs/memos/20260517-dsr_placeholder_n_boundary_memo.md`
  (DSR honest-N)、`docs/prd/20260517-backtest_robustness_completion_prd.md`
  (G1-G5)
