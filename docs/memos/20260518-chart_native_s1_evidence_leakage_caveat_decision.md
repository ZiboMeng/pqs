# chart_native_s1_evidence_v1 — leakage caveat + KEEP decision (Option A)

**日期**: 2026-05-18
**决策**: 用户 explicit-go 2026-05-18 = **A(保留 + 文档化 caveat)**(非 retire)。
**纪律**: `feedback_promotion_only_falsification_evidence_gated`、`feedback_no_blanket_failure_verdict`、`feedback_audit_surfaces_not_thorough`(主动暴露、留痕、不掩埋)、`feedback_decision_authority_operator_audit_split`(directional 用户拍)。

---

## §1 CAVEAT(必须随该候选所有判读一起读)

`chart_native_s1_evidence_v1`(role=evidence_only_observation,GAF63 →
frozen ResNet18 IMAGENET1K_V1 → train-only ridge β,FROZEN;
spec_hash `d035c184…`,beta_sha `439ee31e…`)当初 forward-init 依据
= 原 Track-A **17/17 全过**。

**2026-05-18 leakage-correct 复评(run4: 79-train + López de Prado
average-uniqueness 加权 + purge/embargo)证明该 PASS 部分是
方法学产物**:
- 重叠 21d 标签未降权(无 sample-uniqueness)+ train 行 21d 标签跨进
  validation 年未 purge → IC 与 Track-A 指标 leakage-inflated。
- 修正后:IC-on-59 **0.0146 → 0.0110(−25%)**;Track-A
  **PASS → FAIL**(新增 fail `validation_aggregate_excess_vs_spy`
  + `role_core__validation__2025__excess_vs_spy`);cum_ret 20.42→18.19,
  vs_spy +14.09→+11.85。
- 证据:`docs/memos/20260518-l3_deconfound_correctness_verdict.md` §5、
  `data/audit/chart_native_l3_track_a_suniq_purge.json`。

**honest 定性(scoped,非 blanket)**:不是"信号为零"——honest
frozen-OOS IC 仍小正(~0.011)、full-period cum_ret 仍大幅 > SPY;
是**它过不了 leakage-correct 的生产纪律 gate**(per-year-vs-SPY +
2025-vs-SPY)。这是关于**该候选自身**的证伪证据(其 acceptance
是 leakage-inflated)。

## §2 为什么 KEEP 而非 retire(Option A 理由)

- 该候选 **role=evidence_only_observation,不入 fleet、不投资金**;
  forward soak 的全部意义就是用真实时间体检"回测看着过、是否真"。
  现在已知"回测的过是 leakage-inflated"——**这恰恰使 forward 观察
  更有信息量**(它直接回答:一个 leakage-correct 后 FAIL 的弱信号,
  真实样本外会怎样)。retire 会丢掉这个信息;留 + caveat 保留它。
- 符合 `feedback_promotion_only_falsification_evidence_gated`:证伪
  证据是**不晋升**的依据,不是**强制 retire** evidence-only 观察轨
  的依据;继续观察 + 诚实 caveat 是证据导向的正确处置。

## §3 不做什么(边界,防 A 与 B 冲突)

- **不 refit 该候选的 frozen β**。β 是 sha256-pin 冻结契约
  (`init_chart_native_evidence.py` line 26:NEVER refit during
  forward observation)。用 leakage-correct 重拟合 β = 改 beta_sha
  = 变成**新候选**,与 A(保留**现有**候选)矛盾。leakage-correct
  修复作用于**研究评估链(future L3 runs)**,**不追溯改活的 forward
  候选 β**。现候选带 caveat 原样续观察。
- 不改其 spec_hash / manifest 的 spec 部分;仅加 caveat 记录通路
  (本 memo + marker + CLAUDE.md bullet)。

## §4 落地动作

1. 本 memo(caveat + KEEP 决策留痕)。
2. marker:`data/research_candidates/chart_native_s1_evidence_v1_CAVEAT.md`
   (项目 marker 约定;运营可见,observe 数据须带此 caveat 读)。
3. CLAUDE.md "Forward OOS workstream" 的 chart_native_s1_evidence_v1
   bullet 加 caveat 一行(每会话读的 operational SoT)。
4. `docs/INDEX.md` 新增条目。
5. observe 继续(daily ritual 不变);**所有 chart_native_s1 forward
   判读必须引用本 caveat**。TD60 verdict(~2026-08-13)解读时把
   "回测 PASS 是 leakage-inflated、leakage-correct 后 FAIL" 作为
   先验,不得用原 17/17 PASS 作为健康基线。

## §5 关联 / 升级 finding

core acceptance 机制 **sample-uniqueness 加权全项目缺失**(`cpcv.py`
有 purge/embargo,但重叠标签降权 grep 零命中)→ 可能同样影响
cycle06/08/trial9 的 acceptance metric。**这是 evaluation-criteria 级
问题,需独立 PRD + 用户 explicit-go,不在此静默改 core**(本次仅修
chart_native L3 研究评估链 default)。记为高优先 finding。

关联 [[project-backtest-robustness-ml-redo-2026-05]] [[project-grand-audit-2026-05-18-two-p0]] [[feedback_promotion_only_falsification_evidence_gated]];源 `docs/memos/20260518-l3_deconfound_correctness_verdict.md`。
