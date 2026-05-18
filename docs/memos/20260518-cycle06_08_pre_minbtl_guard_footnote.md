# 边界注脚 —— cycle06/08 在 G3 MinBTL 守卫之前被接受

**日期**: 2026-05-18
**lineage**: `backtest-robustness-completion-2026-05-17`(G3-A2)
**性质**: **只读文档注脚**(read-only)。**不撤 forward 观察、不动
manifest/spec_hash、不重跑回测**。PRD §9.1 桶 B 交付物。
**纪律**: `feedback_no_blanket_failure_verdict`、
`feedback_audit_surfaces_not_thorough`、不编数(未 grep 实证的不填)。

---

## §1 事实(不带评判)

`cycle06_31af04cf2ff9_evidence_v1` 与 `cycle08_3f40e3f4ed1a_evidence_v1`
于 2026-05-15 通过 `temporal_split_acceptance`(per-validation-year +
stress-slice + role-gate + post-MaxDD-fix)被接受、forward-init 为
evidence 角色。**当时不存在 Minimum Backtest Length(Bailey MinBTL)
守卫**——G3 于 2026-05-18 才实现。本注脚仅记录这一时序事实。

## §2 G3 守卫是什么

`check_min_backtest_length(SR_annual, n_trials, actual_years)`:当回测
历史年数 < `MinBTL ≈ (2 ln N)/SR_annual²`(Bailey/Borwein/LdP/Zhu
2014)时 fail-closed。诊断性,调用方决定 enforcement。

## §3 cycle06/08 套用(illustrative,只读,数未全实证则不假装)

- `n_trials`:cycle06/cycle08 mining 各 **200 trials**(CLAUDE.md 记录)。
- `actual_years`:Track A 窗口 = `temporal_split` train+validation
  (alternating 2009-2017+2020/22/24 训 + 2018/19/21/23/25 验),
  有效跨度 **~14-17 年**。
- `SR_annual`:**未 grep 实证 cycle06/08 的 Track A 验收 annualized
  Sharpe**(evidence-init memo 里的 Sharpe~4.0 是 4.5 月 sealed 短窗,
  原文已标"noisy/optimistic、非稳态"——**不能当 MinBTL 输入**)。故
  此处给区间 illustrative,不落单一伪值:

  | 假设 SR_annual | MinBTL=2ln(200)/SR² | 14-17y 窗口是否够 |
  |---|---|---|
  | 1.0 | ~10.6 y | **够**(留余量) |
  | 1.5 | ~4.7 y | 够 |
  | 0.5 | ~42.4 y | **不够** |

**只读结论(不 over/under-claim)**:若 cycle06/08 的 Track A 稳态
annualized Sharpe ≥ ~1.0,其 ~14-17y 窗口**通过** MinBTL;若 < ~0.6
则不通过。**确切判定需 Track A eval artifact 的 annualized Sharpe**
(本注脚不为此重跑——只读纪律);在该数被实证前,**不下"通过/不通过"
的硬结论**,只记录"取决于稳态 Sharpe,门槛如上表"。

## §4 处置

- **不撤** cycle06/08 forward 观察;**不动** manifest/spec_hash;**不重跑**。
- G3 守卫 **new-cycle-only 生效**(未来 Track A 验收强制套用)。
- 若日后需对 cycle06/08 出硬判定:opt-in 读其 Track A eval artifact 的
  annualized Sharpe 套 §2 公式即可(只读,无重跑),非本注脚范围。
- 与边界 memo(DSR placeholder-N)同属"已跑工作的诚实证据质量注脚",
  互不重叠(那个管 DSR,这个管 MinBTL)。
