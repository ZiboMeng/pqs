# 边界 memo —— ML-redo line 的 DSR placeholder-N overclaim

**日期**: 2026-05-17
**lineage**: `ml-method-redo-2026-05-16`(边界修正)/ 关联
`backtest-robustness-completion-2026-05-17`(G1)
**性质**: **LIVE 错误纠正**(与是否实现 G1 无关——已 commit 文档现在
就带这个 overclaim)。
**纪律**: `feedback_audit_surfaces_not_thorough`(audit=暴露没做透+纠
自己 overclaim,列出来不算要 fold 进 memo)、`feedback_no_blanket_
failure_verdict`、`feedback_self_audit_methodology`。

---

## §1 一句话

ML-redo 线所有报出来的 DSR 数字,`deflated_sharpe_ratio` 的
`n_trials` 都是 **placeholder(非真实试验配置数)**,因此 **DSR 系统性
偏乐观**。结论的 **IC 符号+幅度不依赖 DSR(全部仍成立)**;但
"DSR≈1 = 几乎肯定不是运气" 这类**对运气排除强度的措辞站不住**,本
memo 是该 overclaim 的边界纪录;G1(回测稳健性 PRD)实现后用真实 N
重算回填,结论 IC 部分不变。

---

## §2 实查证据(call site × placeholder 方案)

| 脚本 | 调用 | N 实际是什么 | 影响的 landmark |
|---|---|---|---|
| `dev/scripts/ml_redo/run_c3c4_expanded_fromscratch.py:187` | `deflated_sharpe_ratio(pr, 3)` | 硬编码 3 | ④ C3 / D3(gaf 0.999 / mae 0.9999) |
| `dev/scripts/ml_redo/run_d4_fromscratch_perfold.py:196` | `deflated_sharpe_ratio(pr, 3)` | 硬编码 3 | D4(在跑,出数同样带此 caveat) |
| `dev/scripts/ml_redo/run_r4_chart_native_redo.py:186` | `deflated_sharpe_ratio(paired, n_trials=len(arms))` | arm 数(极小,2-3) | ② R4(mae_probe DSR 0.558) |
| `dev/scripts/ml_redo/run_p2_recheck.py:109` | `deflated_sharpe_ratio(d_ic, n_trials=max(2,len(swing)))` | swing 段数,非试验数 | ① R2.5(DSR 0.999) |

(`tests/unit/research/test_cpcv_overfit.py` 用显式 N,是单测断言,**不
是结果声明**,不在范围。)

**元诚实留痕**:operator 2026-05-17 第一次纠正时只说"N=3 在 c3c4/d4"
(仅覆盖 ③④)。本 re-audit(用户要求"再审一遍")发现 R4 + p2_recheck
**也是 placeholder**,故 ①② 同样受影响——**上一轮的纠正本身没做
透,这是连带纠正**(Phase 2A overclaim 之后的同类先例,继续诚实留痕)。

---

## §3 受影响的已 commit 文档(本 memo 是单一 SoT,各文档加指针)

| 文档 | 位置 | 原措辞 | 边界 |
|---|---|---|---|
| `docs/memos/20260516-ml_methodology_redo_closeout.md` | §2/§3/§6/§7(DSR 0.999 / 0.558 / 0.9999) | 部分已有 caveat(R2.5 "t/DSR 被 label 重叠高估"、R4 "DSR 0.558=中等")但**未点名 N-placeholder 根因** | 见 §4 |
| `docs/memos/20260517-ml_method_redo_plain_chinese_summary.md` | L49 "DSR≈1=几乎可以确定是真效果不是蒙的"、L87 "DSR≈1 不是运气" | **无 caveat** | 见 §4 |
| `CLAUDE.md` 完成清单 landmark④ 行 | "DSR≈1" | **无 caveat** | 见 §4 |

---

## §4 正确口径(replace 用)

- **DSR 数字本身**:placeholder-N 下偏乐观,**不得**作为"已排除运气/
  选择偏差"的证据引用。
- **可引用的稳健结论**(不依赖 DSR):
  - landmark① R2.5:robust anchor = **C1 block-bootstrap clean p
    =0.0004**(不是 DSR);family-T 正增量结论成立。
  - landmark② R4:robust = **IC 符号 0.050 > 动量 0.038 + vs_base
    +0.012**(per-CPCV-fold);"打过单动量"结论成立,"DSR 0.558" 仅
    描述为"中等、且该 N 偏乐观"。
  - landmark③ C2 / ④ C3-D3:robust = **vs 动量基线的 IC 差为正**
    (mae +0.058 / gaf +0.055,干净 116820 样本);"DSR≈1" 改述为
    "DSR 在 placeholder-N 下偏乐观,稳健结论看 IC 差为正"。
  - D4(在跑):出数时 DSR 同样标 placeholder-N;D4 结论(from-scratch
    输 pretrain-probe)是 IC 比较,**完全不依赖 DSR**。
- **G1 实现后**:用真实 N(保守=该实验配置数;ONC 有效独立 N 为
  forward-only)重算,回填本 memo §2 表 + 上述文档指针;预期 DSR
  **下降或持平**,IC 类结论不变。

---

## §5 不在范围(honest scoping,避免过度纠正)

- **cycle06/08/forward/Track-A 线无 DSR 声明**(grep 实证为空;
  `temporal_split_acceptance` = per-year + stress-slice + role-gate,
  不产 DSR/PBO)→ **该线无 DSR overclaim 待修**,不需边界 memo。
- G2 PBO 从未报出 → 无 overclaim,仅 forward-only(PRD §6 已记)。
- G5 检测器从未存在 → 无 overclaim,已锁 new-TD-only。
- 桶 B(G3 MinBTL pre-guard 注脚 / G4 对 cycle06-08 回溯≈0 因其走
  per-year temporal-split 非弱单路径 walk_forward)= **依赖实现**,
  记进回测稳健性 PRD §9 交付物,不在本 LIVE-修正 memo 范围。

---

## §6 处置

- 本 memo = 单一 SoT;3 文档加一行指针(不重写正文,保留审计原貌)。
- D4 收口报数时引用本 memo §4 口径。
- G1 实现时本 memo §2/§4 回填真实-N 重算值,标 `recomputed_<date>`。
