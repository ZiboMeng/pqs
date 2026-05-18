# 审计员 claim-discipline review —— operator 独立评估 + 纠正(SoT)

**日期**: 2026-05-18
**触发**: 审计员对 ML-redo claim 口径的 review(baseline 表述 /
expanded_v2 scope / MiniROCKET 退化 / foundation-model 定位)。
**性质**: claim-layer 诚实纠正(operator 独立判断,接受审计实质)。
**纪律**: `feedback_audit_surfaces_not_thorough`(纠己 overclaim,fold
进文档非口头)、`feedback_no_blanket_failure_verdict`、
`feedback_self_audit_methodology`(R3 实查再判)。

---

## §1 operator 独立判断(实查后,不附和不护短)

R3 实查两条 load-bearing,**审计员两条都对,其中一条比他说的更重**:

1. **baseline 口径**:`run_c3c4` 的 `vs_tabular` 实际 = `pred_IC −
   单动量IC`(脚本 "C3: ... vs momentum"),但 verdict token 命名
   **`beats_tabular_baseline`**(closeout §3 L80 引用同名)。**不只是
   文档措辞松——代码 verdict token 本身在 over-claim**:"tabular
   baseline" 暗示强 tabular 模型,实际比的是一个动量因子。`gaf_tree`
   是 GAF 图上的树、且 D3 clean 里 −0.057 输掉;唯一"赢"= mae_probe
   vs 单动量。**接受,不辩护。**
2. **MiniROCKET 退化标量**:`rolling_minirocket_ppv_mean` 文档原文
   "MEAN PPV across all kernels — a single scalar bridge feature"。
   MiniROCKET 价值=上万维确定性特征库,压成 1 数 = 当复杂单因子,
   **非文献(Dempster 2012.08791)高维表征** → 可能 false-negative
   低估 bridge 线。完整 `minirocket_transform` 存在(能力在、未释放)。

**operator 比审计员更进一步(用我们自己证据继续纠己)**:landmark④
审计员只说"别拿 JKX 强度类比小票池"。但**我们自己 D3 clean 重跑已证
landmark④ 惊艳 beat 是脏数据虚高**(gaf IC 脏 +0.128 → 干净 +0.045)+
F3 证因子库 raw-vs-adj 实证 immaterial。**∴ landmark④ 降更狠:从
"landmark" → "弱方向性信号、规模受限"**(我们 clean 证据 + JKX 规模论
双重支持)。

**文献核(均方法论,非市场数据)**:TS2Vec / MiniROCKET / PatchTST /
MOMENT / TimesFM / JKX / candlestick-CNN —— 审计员 characterization
**准确无误用**,epistemic 立场(方向可信、claim 要管紧)正确;JKX
"规模关键"是最 load-bearing 且读得最准,反而强化 operator 对
landmark④ 的更狠降级。

**自评(不防御)**:no-overclaim/no-blanket 纪律我们有、也做过部分
纠正(DSR 边界 memo / F3 de-escalation / cycle13b W7c/d 诚实拒)。
审计员精准点中的缺口 = 纪律没一致应用到 ML-redo headline + 代码误导
token + 缺强 tabular 锚。**这一记对,接住。**

**一处对审计员的细化**:其建议 4(主线=强 tabular + family T +
bridge + 诚实 ensemble,别加码 CNN/foundation)—— operator 同意,
**且已被硬证据 de-risk**:cycle13b 证接好的 W7c/d/PBO 会自动拦过拟合
chart 类 composite。主线转向不只是建议,是已接线 pipeline 本就强制
的方向(operator 比审计员更乐观一点:机制已就位)。

## §2 一个根 + 处置

审计 finding 1+3+4 收敛同一根:**比较里没"强 tabular 锚",比的是单
动量,MiniROCKET bridge 是退化标量** → "打过 baseline"在建锚前**无法
回答**(不只是没软化)。

### §2.1 现在做(claim-layer 卫生,fold 进文档)

**三层 claim 分类(对外一律分开写,禁混成一层)**:
- L1 `representation works`(表征有结构信息)
- L2 `beats single momentum factor under current config`(≠ 打过
  production-grade / 强 tabular baseline)
- L3 `production-eligible candidate`(**未达**:未走 Track A / sealed
  / forward 漏斗;survivorship 未解;config-scoped)

**token 误名更正**:代码 `vs_tabular` / `beats_tabular_baseline` 的
真实语义 = `vs_single_momentum` / `beats_single_momentum_factor`。
**不 retro-edit frozen ml_redo 脚本**——与 DSR placeholder-N 处理
**完全相同的先例**:脚本是已 commit forensic,改了会篡改已提交审计
陈述。更正用本 memo + closeout/plain-summary caveat 指针 + 管
go-forward(任何新脚本用诚实 token)。**自洽 = 不走过场。**

**landmark④ 降级**:措辞首句即写"此票池/stride 动量基线为负 + D3
clean 重跑 gaf +0.128→+0.045 = 惊艳 beat 系脏数据虚高",定性从
"landmark" 降为"弱方向性信号、规模受限(JKX 规模论)"。

**expanded_v2 钉死**:一律标 `research-only, survivorship-bounded`,
直到有 as-of universe 或更强替代证据。

### §2.2 下个高杠杆研究项(记录,非现在 tail-rush;S2 GPU 在跑)

**建缺失的锚**:MiniROCKET **完整特征向量** + 线性/树头 + 一个强
tabular baseline(工程特征 GBDT)作为正式比较锚。**~~在这之前 L2 的
"打过 baseline" 不可严格回答~~ → 见 §2.3,已建已答。**

### §2.3 task#21 ANCHOR 结果(2026-05-18,真跑,fold-in,L2 闭环)

强对照锚已建并跑(同 S1/S2 协议:executable-79 / 除权价 / train-only
+ sealed-guard / 15 CPCV / honest-N DSR)。CPCV IC:

| 臂 | IC |
|---|---|
| 单动量(旧弱对照) | 0.032 |
| 完整 MiniROCKET 1008维→ridge | **0.023** |
| **强 tabular GBDT(184 因子库 XGB)= 真锚** | **0.058** |
| S1 frozen-ImageNet probe | 0.122 |
| S2 放大 MAE d128/d64 | 0.087 / 0.090 |

**L2 现可回答(审计 finding 1 闭环)**:S1/S2 **均 > 强 tabular 锚
0.058**(不只 > 弱动量)→ chart-native claim 从"打过弱对照"**升级为
"train-only CPCV 上打过强 tabular 锚"**,扛过审计核心批评。完整
MiniROCKET(0.023)**两个 baseline 都没打过**(no-blanket:此 config
弱,非"MiniROCKET 无用";empirically 证伪审计 finding 3"低估"假设)。

**钉死 caveat(不 over-claim)**:仍严格 **L2**,非 L3——vs-SPY 硬门/
成本/压力/forward 一关没走;cycle13b 已证 IC_IR 1.1 也被 vs-SPY/covid
拦掉,**"打过强 tabular IC 锚 ≠ 跑赢 SPY ≠ 可部署"**。可信的是
**排序**(S1>S2>强tabular>动量>MiniROCKET),非绝对数(pooled
8.5-11.7 万行 IC 有膨胀可能);DSR-N=2 非锚;JKX 规模论(exec-79
train-only 不可外推强度)仍在。artifact
`data/audit/task21_strong_anchor.json`。

## §3 关联
[[project-backtest-robustness-ml-redo-2026-05]]
[[project-grand-audit-2026-05-18-two-p0]]
[[feedback_audit_surfaces_not_thorough]]
[[feedback_no_blanket_failure_verdict]]
DSR-placeholder-N 先例:`docs/memos/20260517-dsr_placeholder_n_boundary_memo.md`
(本 memo 沿用其"不 retro-edit frozen forensic 脚本"自洽处理)。
