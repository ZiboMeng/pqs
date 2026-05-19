# scaled-checkpoint PRD §3 —— P0 算力可行性评估

**日期**: 2026-05-18
**lineage**: `scaled-pretrain-checkpoint-2026-05-17`(P0 gate 交付物)
**PRD**: `docs/prd/20260517-scaled_pretrained_checkpoint_ml_prd.md` §3
**纪律**: `feedback_no_blanket_failure_verdict`、诚实记录不可行项、
`feedback_heavy_training_serial_wsl`(重训串行)。

---

## §1 实测环境(真跑 `torch.cuda` + `nvidia-smi`)

| 项 | 值 |
|---|---|
| CUDA available | **True** |
| GPU | NVIDIA GeForce GTX 1650 Ti,1 device |
| **VRAM** | **~4 GB**(GTX 1650 Ti 规格) |
| torch | 2.11.0+cu130 |
| host | WSL2,10 核,23 GB RAM |

---

## §2 P0 gate 判定(诚实,不假装)

**GPU 存在 → PRD 不挂起**;但 **4GB VRAM 是硬约束**,决定 S1-S4
scope 必须 VRAM-bounded:

| PRD 项 | 4GB VRAM 下可行? | 说明 |
|---|---|---|
| **S1 GAF/CNN 接 ImageNet backbone** | **可行(frozen + probe)** / 谨慎(轻 fine-tune) | ResNet18/EfficientNet-B0 frozen 前向 + 轻探针,batch 调小可入 4GB;全 backbone fine-tune VRAM 紧 |
| **S2 放大 in-domain MAE** | **适度可行** | d_model 64→128/256 + 深度小增可入 4GB;大幅放大不行 |
| **S3 外部时序基础模型 checkpoint** | **多半不可行 / 需 survey** | MOMENT/Chronos 等基础模型参数量大,4GB 多半放不下全量;先按 PRD S3-A1 做 survey,若仅大模型 → 诚实标 `vram_bounded_infeasible`,不硬塞 |
| **S4 scaled ensemble** | 可行(组合 S1/S2 产物) | OOF stacking 是 CPU 级,不吃 VRAM |

**结论**:P0 gate = **conditional pass —— GPU 可用,scope 收窄为
"frozen-backbone probe + 适度 in-domain 放大 + ensemble";大型外部
foundation model 全量 fine-tune 列为 4GB-bounded 不可行(S3 survey
后诚实定)**。非 blanket"不行",是 VRAM-scoped 可行。

---

## §3 排期约束

- 重训 GPU 任务**串行**(不与 P0-A/P0-B 重活或彼此并行;单 GPU +
  `feedback_heavy_training_serial_wsl`)。
- S1-S4 实现排在 **P0-A(数据价基修复)+ P0-B(验证接生产 gate)
  之后**——理由:S1-S4 的 IC/probe 评估必须在已修正(adjusted)价
  + 已接 DSR/PBO 的 gate 上跑才有意义,否则又是 raw 输入 + naive
  gate 上的数(P0-A/B 未修前跑 = 白跑)。
- 每个 S 项 GPU wall-clock 估算待 S 启动时实测首 epoch 外推。

---

## §4 处置

- P0 gate 判定 = **conditional pass(VRAM-bounded)**,记入 PRD §3
  执行前提:S1-S4 scope 按 §2 表收窄,S3 先 survey。
- 实现仍需用户 explicit-go(本会话"全部 go"已含),但**排在
  P0-A + P0-B 之后**(§3 理由);GPU 串行。
- 关联 [[project-backtest-robustness-ml-redo-2026-05]]
  [[project-grand-audit-2026-05-18-two-p0]]。
