# PRD-3 — 信号层 ML arms（日线-close + intraday，喂 PRD-2 新构建）

**日期**: 2026-05-18 · **lineage**: `signal-ml-arms-2026-05-18`
**性质**: 信号层研究 arm。**信号非 binding constraint（L3 已证）→ PRD-3 单独做不是进步；价值仅在(a)差异化非 sibling +(b)走 PRD-2 改过的构建**。全 config-scoped、NOT deployable、走 funnel。
**纪律**: `feedback_no_blanket_failure_verdict`、`feedback_no_over_conservative_scoping`、`feedback_promotion_only_falsification_evidence_gated`、`feedback_websearch_fuzzy_to_primary_depth`（架构结论已 4-agent primary-grounded）。
**源**: `docs/memos/20260518-chart_native_architecture_literature_synthesis.md`（5 收敛结论）+ 4 agent 交付。

---

## §1 架构结论（4-agent primary 综合，直接落地）

- 低 SNR：浅/正则>深；frozen-pretrain→probe 是文献认可姿态（GKX/Raghu）。
- 图像非必要，真实增量=隐式 per-name 归一化（JKX 自陈）。
- **最高 ROI=工程化平稳特征+浅 XGBoost+stack frozen-probe embedding**（Grinsztajn/Krauss/ROCKET）。
- 多变量 OHLCV/多 TF：iTransformer variate-token / PatchTST channel-independent + masked-patch SSL→冻结探针；S/R=距滚动极值归一化距离（无 look-ahead，非裸价）。
- 每个深度实验**必带 DLinear 基线**（Zeng et al. 真正教训）。LSTM 独立 from-scratch 本 regime 不值得（Fischer-Krauss；非 blanket，TCN 进 ensemble 可）。

## §2 Scope — 两组件，cheapest-safest-first

### 组件 A：日线-close 信号 arm
- **A1（最高 ROI，先做）**：工程化平稳特征（JKX 归一化几何 `close_pos_in_range` 多窗 + 距滚动极值 S/R proxy + K线 body/wick/gap + 量 z + 分数差分价 + Family T swing-structure，全月度截面 rank）+ 浅 XGBoost（depth 2-4+早停）+ **stack frozen-probe embedding（PCA 16-32 维当额外列）**。
- **A2（决定性 ablation）**：1D/ROCKET + 显式 per-name 归一化 vs 图像 → 回答"图像必不必要"（IC-on-tradeable 单调性，沿用三点曲线法）。
- **A3（后）**：JKX-style OHLC+vol bar 图（canonical 加 OHLC/量，保 implicit scaling）+ frozen vs from-scratch JKX-CNN 对照。
- **A4（后）**：iTransformer/PatchTST + 域内 masked-patch SSL→冻结探针（域内预训练 vs ImageNet 域外，增量实测、禁 vision 量级 overclaim）。

### 组件 B：intraday 信号 arm（用户 2026-05-18:intraday 也上 ML）
**B 是信号层，与 PRD-2 P2.3 intraday 构建是两个 distinct DOF（用户已厘清:intraday 信号+构建都有）。** archetype 限 differentiated 非 naive（日内反转/微观结构/event；`IntradayReversalStrategy` skeleton 已在）——**禁 "15m 上重开动量因子挖矿"**（= 老路子换更快 TF，naive bar-方向投票负结论已证死，scoped 非 blanket）。
- **B1（先，最便宜、最不易过拟合）**：intraday 工程特征（日内反转/开盘区间/VWAP 偏离/已实现波动/量分布）+ 浅 XGBoost。
- **B2（后，gate 最硬）**：intraday 深度（TCN(Bai 2018) / iTransformer / PatchTST，15m/30m/60m 当 channel/variate + masked SSL→冻结探针）。

## §3 跨 PRD 依赖 + 硬 gate

- 全 PRD-3 评估走 **PRD-1 leakage-correct**（否则重蹈 IC 虚高，run4 先例）。
- **组件 B gated 于 PRD-2 P2.3**（无日内构建能力，日内信号无法诚实评）+ 日线 ML arm（A）先跑通方法论 + intraday 专属 cost+leakage gate 硬化 + **强制 A/B 去混淆**（信息 vs timing 分离）。
- intraday-ML = **全 program 自欺风险最高支**（SNR 更差、multiple-testing 爆炸、1m provenance 脆、cost 最毒）→ 排 PRD-3 最后、gate 最硬；非 blanket 负面（有文献+codebase skeleton），走 funnel 不预判生死。
- 信号产出喂 PRD-2 新构建评判（NAV/Track-A），**不在 IC 层宣布胜利**；单独喂老 cap_aware top-N = 老路子（弃）。

## §4 验收

每 arm：leakage-correct frozen-OOS IC（pooled + on-tradeable）+ 对 momentum/reversal/Amihud 残差正交性（JKX ≤12% 测，判是否 sibling）+ DLinear/动量基线对照 + 走 PRD-2 构建的 NAV Track-A + Path-1 forward。config-scoped 留痕，sealed 未读，DSR 真 N（禁 placeholder overclaim）。

## §5 Out / Deferred

不晋升/不入 fleet（除非走完 PRD-1+PRD-2 funnel + 证伪 evidence-gated）；ROCKET 若未装用 sklearn 随机卷积代；intraday-ML 在 §3 gate 全满足前不启动 B2。

## §6 R1-R4 自审

- R1：架构结论 4-agent primary-grounded（作者/venue/假设已在源 memo）；preflight 实证 XGBoost 3.2.0/Family T/drawup 已在。
- R2：信号非 binding（L3 证）→ PRD-3 单独非进步、必配 PRD-2；intraday 信号(B)与构建(P2.3)distinct 且耦合+去混淆，逻辑自洽。
- R3：run4 已实证 leakage-naive 使 IC 虚高 → §3 强制 PRD-1 footing 非空话。
- R4：边界——intraday-ML 自欺风险最高 → 排最后 gate 最硬；naive-intraday/sibling 用 scoped 纪律挡非 blanket；不晋升不入 fleet 守 funnel。
