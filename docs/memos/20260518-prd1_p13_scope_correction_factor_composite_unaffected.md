# PRD-1 P1.3 scope correction — factor-composite cycle06/08 are NOT leakage-affected by the probe-fit mechanism (grounded)

**日期**: 2026-05-18 (loop R3) · **性质**: 诚实 scope 纠正 + directional 停等点（评估准则定义 + 改变"之前结论真实性" + 主线去留）。
**纪律**: `feedback_audit_surfaces_not_thorough`（纠我自己 PRD-1 的 overclaim,grounded 非 hand-wave）、`feedback_no_blanket_failure_verdict`、`feedback_decision_authority_operator_audit_split`（directional 停等用户）、`feedback_promotion_only_falsification_evidence_gated`。

---

## §1 Grounded finding（R3 实读代码,非推测）

`dev/scripts/cycle06/cycle06_track_a_eval.py` 实读：
- 用 `ResearchCompositeSpec`(line 105)+ `evaluate_composite_spec`(line 132)。
- **无 ridge probe / 无 `np.linalg.solve` / 无 β 拟合**（composite = 确定性 zscore_cs 加权和,零学习参数）。
- grep `cpcv_inputs|overfit_inputs|stack|fwd21|pct_change|pred` = **零命中** —— 该 eval 脚本**不构造重叠 21d 标签的 pred/fwd IC 向量**（与 chart_native L3 的 `al = concat(sc.stack, fwd21.stack)` 不同）。
- cycle06/08 binding gate 历史是 NAV-based `validation_aggregate_excess_vs_spy`（cap_aware 月度组合收益）。

→ **run4 实测的 leakage 机制 =（probe-fit average-uniqueness 缺失 + probe-fit purge 缺失 → 学习 β 虚高 → IC/Track-A 虚高）。该机制对 cycle06/08 无机械作用面**：没有 probe 可拟合,eval 不产重叠标签 IC,uniqueness/purge 是标签/probe-fit 层权重——碰不到确定性 composite 的 NAV gate。

## §2 我上一轮 PRD-1 的 overclaim（诚实纠正）

PRD-1 §1/§2/P1.3 + ledger 把 cycle06/08 列为"factor-composite Track-A 通病、须 leakage-correct 重评、全 retire 可接受"。**这个 premise 对 factor-composite 是错的**：run4 leakage 是 **learned-probe-specific**（chart_native_s1）。cycle06/08 确定性 composite **无此 leakage 向量** → 其 Track-A PASS **不因该机制虚高** → 不需 leakage 重评、不会 leakage-FAIL → **"主线归零 → fire 新 mining" 的前提不成立**。这是 grounded 结论（读代码得出),不是护着在任候选——证据在 §1。

## §3 残留真问题（不 blanket "cycle06/08 全清白"）

唯一对 factor-composite 仍可争的 leakage 向量 = **重叠 21d 标签对 cpcv IC 的 sample-uniqueness 加权**（López de Prado Ch.4 适用于任何重叠标签 IC,不止 probe）。但：
- cycle06/08 eval 脚本**根本没喂 cpcv_inputs** → 它们的 cpcv 门要么 skip 要么 fail-closed,IC 不是其 binding gate（NAV-aggregate 才是）→ 即便加 uniqueness 也不动 verdict。
- 若要对"未来 factor-composite cpcv IC"普遍加 uniqueness：**与 `cpcv_acceptance` §3 冻结契约（仅 sample-SIZE fold 加权,禁额外加权）相撞 → 评估准则修订 = directional,需独立 mini-PRD + 用户 explicit-go**。

## §4 PRD-1 P1.3 正确 re-scope（待用户 ratify）

- chart_native_s1（learned-probe）= leakage-affected → 已 Option A caveat（done）。
- **cycle06/08（factor-composite）= probe-fit leakage 机制无作用面 → Track-A PASS 站得住,不重评、不 retire；主线不归零、不触发新 mining directional。**（grounded §1）
- pead_sue_trial1 = 事件驱动 SUE,有重叠 hold-period 标签 + 独立 eval 轨 → **需单独小检查**（是否有 learned 参数 / 重叠标签 IC 向量;evidence-only 非主线,优先级低）。
- options/simple_baseline = 独立轨,非 composite-Track-A,无此机制。

## §5 STOP-for-user：directional 选项 + 我的建议

**选项**：
- **A（我建议）**：ratify §4 re-scope —— P1.3 收窄为「chart_native 已 caveat（done）+ pead 单独小检查」;**cycle06/08 不重评(grounded 无作用面),主线不归零,不触发新 mining**。PRD-1 §1/§2/P1.3 + ledger 按 §2 诚实改。这是读代码得出的事实,不是护盘。
- **B**：你要把 sample-uniqueness 普遍加到 factor-composite 的 cpcv IC（即便 cycle06/08 当前没喂 cpcv_inputs,为未来 cycle 普适）→ 这是 **§3 冻结契约修订 = 评估准则 directional**,我起独立 mini-PRD 待你 explicit-go,**不在此静默改 §3**。
- **C**：你仍要对 cycle06/08 跑一次 leakage-correct 重评做实证背书（即便分析说无作用面,要 empirical 确认）→ 我后台串行重跑,预期 verdict 不变（grounded 预测;若变则 §1 分析有误,必 root-cause）。

**我的建议 = A + C-lite**：ratify A（事实如此），同时为消除"分析 vs 实测"残疑,后台对 cycle06/08 各跑一次 leakage-correct flag-on 重评做**实证背书**（预期 bit-不变 verdict;偏差则证 §1 错,root-cause）。B 仅在你要普适未来 cycle 时单独起。

**不自决理由**：改变"之前结论真实性"判断 + 评估准则 scope + 主线候选去留 —— 全在协议 directional 停等清单。

关联 [[project-grand-audit-2026-05-18-two-p0]] [[feedback_audit_surfaces_not_thorough]];源 `docs/memos/20260518-l3_deconfound_correctness_verdict.md`、`prd/20260518-prd1_leakage_correct_foundation.md`。
