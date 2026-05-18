# chart_native_s1_evidence_v1 — post-promote 深度 audit(证伪动机驱动)

**日期**: 2026-05-18
**对象**: 已 forward-init 的 `chart_native_s1_evidence_v1`(spec_hash
`d035c184…`,beta_sha `439ee31e…`)
**触发**: 用户 —— "针对已 promote 的 cnn strategy 再做一遍 audit:
数据 / 标签 / 数据处理 / 数据准备代码 / 模型训练代码与模型 / 验证
有没有问题,其他需要 audit 的你来看"。
**性质**: harness 规则下的**证伪尝试**——
[[feedback_promotion_only_falsification_evidence_gated]]:promote 后
怀疑 → 做更多证伪;**唯一合法 halt = 找到 strategy 自身缺陷的证据**。
**纪律**: [[feedback_self_audit_methodology]] R3 真读真跑 + R4 边界
+ [[feedback_no_blanket_failure_verdict]] + [[feedback_audit_surfaces_not_thorough]]
(纠正/caveat 必须 fold 进文档,不是列出来就完)。

---

## §1 strategy pipeline(被审对象,R3 实读)

GAF(63 窗,adjusted close)→ 冻结 ResNet18 IMAGENET1K_V1 512d →
ridge probe(λ=10,**仅 train-year 行拟合后冻结**)→ score=E@β →
逐日横截面 zscore → cap_aware_cross_asset / monthly / top-10 →
BacktestEngine T+1 开盘执行。

## §2 六维 audit 结论(全部 R3 实查实跑,无 hand-wave)

| # | 维度 | 实查内容 | 结论 |
|---|---|---|---|
| 1 | 数据 | 79 票 BarStore adjusted+split cascade(P0-A 已修);bar 完整性 smoke | **干净**:0 周末行 / 0 重复日 / 0 中段 NaN-close。数据覆盖断崖(90% 票 ~2015 起,vendor 覆盖非 IPO)= 已诚实记录的 C5 边界,**非 bug** |
| 2 | 标签 | `fwd=px.pct_change(_H).shift(-_H)`,_H=21,手算验证方向 | **干净**:= 前向 21d 收益(i=0→(s[3]-s[0])/s[0] 实证);特征窗结束 bar i、标签 [i,i+21],**无反向 lookahead**;no-overlap 证伪已加额外 21d gap 仍存活 |
| 3 | 数据处理 | GAF `rescale_to_unit` 缩放源;composite `zscore_cs` 轴向 | **干净**:rescale 只用**窗自身** np.nanmin/max;zscore_cs `axis=1` **逐日横截面**(实测 row0 独立于 row1/2)——无全局/未来/全样本时序归一化泄漏 |
| 4 | 数据准备代码 | 非有限窗过滤、keys/imgs 锁步、特征顺序保序、ImageNet 预处理 | **干净**:`isfinite(w).all() and w[0]>0` 跳过坏窗;keys 与 imgs 同循环 append;`_frozen_imagenet_features` 顺序 batch+concatenate 保序 → score_all↔keys 对齐 by construction;mean/std ImageNet 归一化、2ch→3ch、no_grad、eval、requires_grad False 均正确 |
| 5 | 模型训练 代码+模型 | ridge 拟合掩码、train/val 年份隔离、backbone 来源、冻结契约 | **干净**:`is_train = d.year in train_year_set`;`train_year_set ∩ validation_years = ∅`(**实证空**:train=[2009-17,20,22,24] vs val=[18,19,21,23,25]);backbone=ImageNet 预训练**从不在我们数据/标签上训练→结构上不能泄漏我们的标签**;β sha256 钉死,observe 加载即校验、**永不重训**(smoke 实证 "frozen beta … sha256 OK") |
| 6 | 验证 | per-validation-year OOS 性质、执行时序 | **干净**:per-validation-year = 冻结 probe 在 held-out 年打分(probe 层真 OOS);执行=BacktestEngine T+1 开盘(M11a/b bit-for-bit parity 共用 kernel),signal@d(≤d 收盘)→ d+1 开盘成交,**无同日 fill** |

## §3 额外项:claim 卫生 caveat(**非泄漏**,按 audit 纪律 fold-in)

不是 bug、不影响因果干净,但若不写明会 over-claim,故显式留痕:

- **E1 — IS/OOS 混合 headline**:全期 cum_ret +2042% / Sharpe 1.589
  **混合了 in-sample(train 年,probe 在此拟合)+ OOS(validation 年)**。
  **不是纯 OOS**。纯 OOS 证据 = per-validation-year Track-A gates
  (冻结 probe 在 held-out 年)。报告 headline 不得当纯 OOS 读。
- **E2 — benchmark total-return 不对称**:策略持 cross-asset ETF 用
  `adjusted_total_return=True`(含息),SPY/QQQ benchmark 只
  `adjusted=True`(无息)。持债 ETF 时小幅利好 vs_spy;但 SPY 自身
  ~1.5%/yr 股息也未计入 benchmark,部分反向抵消。净效应小但非零——
  **诚实标注不藏**。系 cycle04-P0a cross-asset TR 设计 + CLAUDE.md
  "dividends not applied to equity adjustment" 已知局限的交叉效应。
- **E3 — 已有 memo 覆盖,无新发现**:PBO red_flag = single-signal
  folds-as-configs 误用(已 audit,N/A);DSR placeholder-N 非锚;
  pooled-IC 幅度可能乐观(稳健 = 排序+vs-动量+扛 4 证伪,绝对 IC 软)。

## §4 VERDICT(harness,no-blanket)

本次 audit 是一次**证伪尝试**。**六维跨数据/标签/处理/准备代码/
模型训练/验证,未发现任何 strategy 自身缺陷或泄漏 bug**;pipeline
因果干净(per-window GAF、冻结预训练 backbone、train-only 拟合后冻结
probe、train/val 年份零重叠、前向标签、T+1 开盘执行)。

按 [[feedback_promotion_only_falsification_evidence_gated]]:**无
strategy-自身缺陷证据 → 不构成 halt;forward-init 维持**。E1/E2 是
claim caveat(已 fold 进本 memo + manifest `post_promote_audit` 块),
**非泄漏**。唯一诚实残留(pre-2015 真 point-in-time / 退市
survivorship)结构性不可离线测(C5)、**正是 forward soak 要测的
东西**(harness:测不到≠拒)。

**不下 "绝对永远没问题" 的 blanket**(no-blanket 纪律):仅断言
"本次这六维 + 额外项 R3 实查实跑,无 strategy-自身缺陷证据";后续
forward 真实数据若暴露缺陷,按 harness 即时 halt(唯一合法 halt)。

## §5 自洽处理(不走过场)

- spec yaml 是 **hash-pinned 冻结契约**(DSR placeholder-N 先例:不
  retro-edit 已冻结 forensic)。审计中误改 yaml 已**立即回退**,
  实证 recomputed spec_hash == manifest spec_hash == `d035c184…`
  (冻结契约完好)。E1/E2/verdict 改 fold 进**本 memo + manifest 的
  独立 `post_promote_audit` 注记块**(manifest=可变观察账本,加 sibling
  key 不动 spec_hash)。
- observe 脚本本轮新建并 smoke 实证(冻结β加载+sha256 校验+读
  2026 forward 窗+ "<2 bars past start_date 2026-05-19. Waiting"
  graceful 退出),frozen-probe 契约可执行。

## §6 关联
[[feedback_promotion_only_falsification_evidence_gated]]
[[feedback_no_blanket_failure_verdict]]
[[feedback_audit_surfaces_not_thorough]]
forward-init closeout: `docs/memos/20260518-chart_native_s1_evidence_forward_init.md`
DSR-forensic 先例: `docs/memos/20260517-dsr_placeholder_n_boundary_memo.md`
