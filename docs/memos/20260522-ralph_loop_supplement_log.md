# Ralph-Loop 运行日志 — Supplement PRD(audit 整改 + ranking-baseline OOS 验证)

每一轮 ralph-loop 迭代结束时,将本轮完整的中文 11 部分报告**追加**到本
文件末尾。不要覆盖既有条目。

参考:
- `docs/prd/20260522-rerisk-ml-audit-remediation-supplement-prd.md` — supplement PRD
- `docs/prd/20260521-rerisk-and-ml-training-audit-prd.md` — master PRD
- `docs/memos/20260522-ralph_loop_supplement_prompt.md` — 每轮协议
- `CLAUDE.md` — 系统不变约束

执行顺序:S1 → S2 → S4 → S5 → S3 → S7 → S6。
完成 promise:`RERISK-ML-SUPPLEMENT-DONE`。

---

## Round 1 — S1:embargo 改 trading-bar purge(iter_folds 修复)

**时间**: 2026-05-22 · **主 commit**: `167c55b` · **测试基线**: 3923
→ 3929(+6 新)

① **当前阶段** — Round 1 / S1 / embargo 泄漏修。

② **本轮目标** — `iter_folds` purge 从 calendar-day 改 trading-bar +
horizon∈{5,10,21} 零泄漏回归测试。

③ **为什么先做它** — S1 是执行顺序第一;C1 CRITICAL 泄漏污染下游。

④ **做了什么** — `pipeline.py` 新增 `_embargo_train_end`(给
trading_index 时按交易日精确 purge,无则保守 `ceil(×1.6)` calendar
fallback + warn);`iter_folds` 加 `trading_index` 参数。

⑤ **改了哪些文件** — `core/research/ml/pipeline.py` /
`tests/unit/research/ml/test_pipeline.py`(+6 测试)。

⑥ **跑了哪些测试 + 结果** — test_pipeline 31 passed:
zero-overlap[5/10/21] 三 horizon 零泄漏、钉旧 bug、legacy warn、
embargo=0 不变;既有 25 无回归。

⑦ **当前结果** — `iter_folds` trading-bar purge 完成;S1 gate 第一条
(回归证零泄漏)✅。

⑧ **剩余风险** — 4 个 driver 未传 trading_index(走 legacy 保守
fallback);S1 gate 第二条待 driver 接线。

⑨ **下一轮建议** — Round 2 = 4 driver 传 trading_index +
embargo_leak_quant re-run 确认 delta 归零 → 关 S1。

⑩ **TODO** — [x] S1 iter_folds 修+测试 · [ ] S1 driver 接线+收口 ·
[ ] S2/S4/S5/S3/S7/S6。

⑪ **commit** — `167c55b`(主)。

## Round 2 — S1 收口:driver 接线 trading_index(S1 CLOSED)

**时间**: 2026-05-22 · **主 commit**: `0bb581b` · **测试基线**: 3929
（research/ml 162 passed）

① **当前阶段** — Round 2 / S1 / 收口。

② **本轮目标** — 4 driver 接 trading_index,re-run P4 确认 C1 修复
进生产路径。

③ **为什么先做它** — Round 1 修核心;gate 第二条要生产路径实际用上。

④ **做了什么** — `run_walk_forward` 从 `labels.index` 自动派生
trading_index(零 driver 改动覆盖 walk_forward_rank_sign);
portfolio_acceptance + 2 sign driver 显式传 trading_index。

⑤ **改了哪些文件** — `pipeline.py` / `portfolio_acceptance.py` /
`walk_forward_sign_classifier.py` / `hyperparam_search_sign_classifier.py`
/ 新 acceptance json。

⑥ **跑了哪些测试 + 结果** — test_pipeline+xgb 43 passed;research/ml
162 passed 无回归。R3 生产复跑 `portfolio_acceptance.py`:path-D
Sharpe **1.176**(buggy 1.29 消失,= leak-quant correct 值),MaxDD
-19.85%,DSR 0.893,PBO 0.135,verdict PASS。

⑦ **当前结果** — **S1 CLOSED**。gate ①回归证零泄漏 ②生产路径实跑
用 trading-bar purge。

⑧ **剩余风险** — leak-free 真实数:path-D Sharpe 1.18 / MaxDD
**-19.85%**(贴 20% 线)/ DSR 0.89 / PBO 0.135 —— S6 真 OOS 须用
此 leak-free 基线判读。

⑨ **下一轮建议** — Round 3 = S2(R4 §10.2 artifact schema 16 字段
+ fail-closed validator)。

⑩ **TODO** — [x] S1 CLOSED · [ ] S2/S4/S5/S3/S7/S6。

⑪ **commit** — `0bb581b`(主)。

## Round 3 — S2:§10.2 ArtifactGovernance schema + fail-closed validator

**时间**: 2026-05-22 · **主 commit**: `e4e68fd` · **测试基线**: 3929
→ 3938(+9;research/ml 171 passed)

① **当前阶段** — Round 3 / S2 / §10.2 artifact schema。

② **本轮目标** — artifact schema 扩到 §10.2 全字段 + fail-closed
validator。

③ **为什么先做它** — S1 CLOSED;S2 第二顺位;R4 §10.2 缺字段是
audit CRITICAL。

④ **做了什么** — `artifact.py` 新增 `ArtifactGovernance` dataclass
(§10.2 always-required 11 + §9.6 dsr/pbo + conditional + portfolio-tier
5,required 无 default 强制构造)+ `ArtifactMetadata.governance` 可选
字段(默认 None 非破坏)+ `validate_artifact_governance` fail-closed
+ `_metadata_from_json` 重建。

⑤ **改了哪些文件** — `core/research/ml/artifact.py` /
`tests/unit/research/ml/test_artifact.py`(+9 测试)。

⑥ **跑了哪些测试 + 结果** — test_artifact 31 passed(+9);research/ml
171 passed 无回归。

⑦ **当前结果** — §10.2 schema + validator 就位;spec_id 不含
governance(非破坏)。

⑧ **剩余风险** — `make_artifact_metadata` 未接 governance 参数;
driver 未 populate;validator 未接 freeze gate。

⑨ **下一轮建议** — Round 4 = `make_artifact_metadata` 加 governance
参数 + 4 driver populate §10.2 真值。

⑩ **TODO** — [x] S1 CLOSED · [x] S2 schema+validator · [ ] S2
driver populate + freeze 接线 + 收口 · [ ] S4/S5/S3/S7/S6。

⑪ **commit** — `e4e68fd`(主)。

## Round 4 — S2:make_artifact_metadata 接 governance 参数

**时间**: 2026-05-22 · **主 commit**: `bde105e` · **测试基线**: 3938
→ 3940(+2;test_artifact 33 passed)

① **当前阶段** — Round 4 / S2 / governance 透传。

② **本轮目标** — `make_artifact_metadata` 加 governance 参数透传。

③ **为什么先做它** — Round 3 建好 schema+validator;工厂须能接收
governance。

④ **做了什么** — `make_artifact_metadata` 加 `governance` 可选参数,
透传进 `ArtifactMetadata`。保持最小步,driver 真值组装留 Round 5。

⑤ **改了哪些文件** — `core/research/ml/artifact.py` /
`tests/unit/research/ml/test_artifact.py`(+2 测试)。

⑥ **跑了哪些测试 + 结果** — test_artifact 33 passed(+2:透传 +
legacy 默认 None);纯 additive 无回归。

⑦ **当前结果** — artifact 工厂可接收并透传 governance。

⑧ **剩余风险** — `walk_forward_rank_sign.py` 未组装 ArtifactGovernance
(产出仍 governance=None);validator 未接 freeze gate。

⑨ **下一轮建议** — Round 5 = `walk_forward_rank_sign.py` 组装
`ArtifactGovernance` 真值 + 传 make_artifact_metadata。

⑩ **TODO** — [x] S1 CLOSED · S2 schema/validator/工厂参数 · [ ] S2
driver populate + freeze 接线 + 收口 · [ ] S4/S5/S3/S7/S6。

⑪ **commit** — `bde105e`(主)。

## Round 5 — S2:walk_forward_rank_sign 组装 §10.2 ArtifactGovernance

**时间**: 2026-05-22 · **主 commit**: `0d51854` · **测试基线**: 3940
（仅改 driver；R3 实跑验证)

① **当前阶段** — Round 5 / S2 / driver populate。

② **本轮目标** — rank driver 组装 + 传 ArtifactGovernance。

③ **为什么先做它** — schema/validator/工厂参数就位,让真 driver
populate 真值。

④ **做了什么** — 新增 `_rank_artifact_governance` helper 组装 §10.2
真值(source_tiers=A_market_data 诚实只记实际消费的、label_mode=
forward_return、sample_weight_mode=uniform 诚实标 S3 前、purge_embargo
trading_bars、config_hash、objective per-model、trial_count);
make_artifact_metadata 调用传 governance。

⑤ **改了哪些文件** — `dev/scripts/ml/walk_forward_rank_sign.py`。

⑥ **跑了哪些测试 + 结果** — R3 实跑:`--model xgb --save` 跑
2010-2016 → `load_artifact` 重载 governance present=True、11 字段
全真值、`validate_artifact_governance` PASS。

⑦ **当前结果** — rank driver artifact 带全 §10.2 governance 且过
validator。

⑧ **剩余风险 / S2 未尽** — sign driver + portfolio_acceptance harness
未 populate §10.2;freeze gate 未在 promote 时调 validator(与 S7
freeze-model-hash 耦合)。

⑨ **下一轮建议** — Round 6 = portfolio_acceptance harness 嵌 §10.2
governance(含 portfolio-tier 字段)。

⑩ **TODO** — [x] S1 CLOSED · S2 schema/validator/工厂/rank-driver ·
[ ] S2 portfolio_acceptance+sign-driver+收口 · [ ] S4/S5/S3/S7/S6。

⑪ **commit** — `0d51854`(主)。

## Round 6 — S2:portfolio_acceptance harness 嵌 §10.2 governance

**时间**: 2026-05-22 · **主 commit**: `b652e7a` · **测试基线**: 3940
（test_artifact 33;R3 实跑)

① **当前阶段** — Round 6 / S2 / acceptance harness governance。

② **本轮目标** — `portfolio_acceptance.py` 输出嵌 §10.2 governance
(portfolio-tier)+ 写前 fail-closed 校验。

③ **为什么先做它** — S2 required-work 含 acceptance harness;它是
promote-decision artifact。

④ **做了什么** — `validate_artifact_governance` 改 polymorphic(也接
bare ArtifactGovernance);`portfolio_acceptance.py` 加
`_acceptance_governance`(always 11 + portfolio-tier 7,dsr/pbo 取
真值)+ 写前 `validate(is_portfolio=True)` fail-closed +
`out["governance"]`。

⑤ **改了哪些文件** — `core/research/ml/artifact.py` /
`dev/scripts/ml/portfolio_acceptance.py` / 新 acceptance json。

⑥ **跑了哪些测试 + 结果** — test_artifact 33 passed;R3 实跑
portfolio_acceptance exit 0、verdict PASS、输出带 governance(
portfolio-tier 全填、dsr 0.893/pbo 0.135)、写前 fail-closed 通过。

⑦ **当前结果** — acceptance harness 产出带全 §10.2 portfolio-tier
governance。

⑧ **剩余风险 / S2 未尽** — sign driver 未 populate §10.2;freeze gate
未调 validator(S7 耦合)。

⑨ **下一轮建议** — Round 7 = sign driver §10.2 + S2 §12.3 gate 核对
+ S2 收口。

⑩ **TODO** — [x] S1 CLOSED · S2 schema/validator/工厂/rank/acceptance
· [ ] S2 sign-driver+收口 · [ ] S4/S5/S3/S7/S6。

⑪ **commit** — `b652e7a`(主)。

## Round 7 — S2 收口:sign driver §10.2 governance(S2 CLOSED)

**时间**: 2026-05-22 · **主 commit**: `cbd6d18` · **测试基线**: 3940
(test_artifact+pipeline 64 passed)

① **当前阶段** — Round 7 / S2 / 收口。

② **本轮目标** — sign driver §10.2 + rank-driver fail-closed validate
补 + S2 收口。

③ **为什么先做它** — S2 required-work 含 sign driver。

④ **做了什么** — `walk_forward_sign_classifier.py` 加
`_sign_artifact_governance`(§10.2 真值)+ summary 写前 fail-closed
validate + `summary["governance"]`;`walk_forward_rank_sign.py` 补
`validate_artifact_governance` 在 save 前(三 driver 一致 fail-closed)。

⑤ **改了哪些文件** — `walk_forward_sign_classifier.py` /
`walk_forward_rank_sign.py`。

⑥ **跑了哪些测试 + 结果** — test_artifact+pipeline 64 passed;R3:
`_sign_artifact_governance` 对 xgb/logreg 产出 governance 均过
validator。

⑦ **当前结果** — **S2 CLOSED**。§12.3 gate:① 三 model-artifact
driver(rank/acceptance/sign)写文件前 fail-closed validate、带全
§10.2 字段 ② 缺字段 validator raise 测试(R3)。

⑧ **剩余风险 / 诚实标注** — hyperparam_search 出 search log 非单个
可晋升 artifact(§10.2 适用于 model artifact,已覆盖 3 个);freeze
gate validator 接线交 S7(与 M9 freeze-model-hash 耦合);spec_id
不含 governance(非破坏,留痕)。

⑨ **下一轮建议** — Round 8 = S4(config-vs-code drift):
ml_allocation/ml_labeling 声明的 cap/exit/residualize 要么实现要么标
enabled:false(决策〇#1)。

⑩ **TODO** — [x] S1 CLOSED · **S2 CLOSED** · [ ] S4/S5/S3/S7/S6。

⑪ **commit** — `cbd6d18`(主)。

## Round 8 — S4:config honesty(enforcement_status 登记 + cross-check)

**时间**: 2026-05-22 · **主 commit**: `ee18390` · **测试基线**: 3940
→ 3947(+7;allocation 33 passed)

① **当前阶段** — Round 8 / S4 / config honesty。

② **本轮目标** — 消除 config 撒谎:enforcement_status 登记 +
cross-check 测试。

③ **为什么先做它** — S4 首步;先让 drift 显式可见再逐个实现。

④ **做了什么** — `ml_labeling.yaml` residualize_vs_sector→false(代码
只 market 残差化);`ml_allocation.yaml` 加 `enforcement_status` 登记
(15 控制:enforced 6 / pending_S4 3 / roadmap 5 / disabled 1);
新建 `test_enforcement_status.py`(7 测试:status 合法 / 每个声明的
控制必须登记 / enforced 控制有实证代码 / pending_S4 文档化)。

⑤ **改了哪些文件** — `config/ml_labeling.yaml` /
`config/ml_allocation.yaml` / `tests/unit/research/allocation/
test_enforcement_status.py`(新)。

⑥ **跑了哪些测试 + 结果** — test_enforcement_status 7 passed(首跑
抓出 concentration_cap_top1/top3 漏登记 → 补 → 全绿);allocation
33 passed 无回归。

⑦ **当前结果** — config-vs-code 撒谎消除:每个控制状态显式,
cross-check 测试守住;drift 已修。

⑧ **剩余风险** — turnover/min_edge/exit_policy 仍 pending_S4(用户
〇#1 要实现,Round 9-11)。

⑨ **下一轮建议** — Round 9 = 实现 `turnover_cap_daily` enforcement
+ 翻 enforced + 测试。

⑩ **TODO** — [x] S1/S2 CLOSED · S4 config honesty · [ ] S4 实现
turnover/min_edge/exit + 收口 · [ ] S5/S3/S7/S6。

⑪ **commit** — `ee18390`(主)。

## Round 9 — S4:constraints.py — apply_turnover_cap 实现

**时间**: 2026-05-22 · **主 commit**: `a504d49` · **测试基线**: 3947
→ 3954(+7;test_constraints 7 passed)

① **当前阶段** — Round 9 / S4 / turnover cap。

② **本轮目标** — 实现 `turnover_cap_daily` enforcing 代码。

③ **为什么先做它** — 用户〇#1 要实现 turnover;它是三个 pending 里
最干净的(纯 weight-panel 变换)。

④ **做了什么** — 新建 `core/research/allocation/constraints.py`(填补
audit 指出的 constraints.py 缺口)+ `apply_turnover_cap`(per-bar
partial-rebalance throttle:超 cap 只走 cap/turnover 比例,余量带下
bar;bar 0 默认完整 initial entry)+7 单测。

⑤ **改了哪些文件** — `core/research/allocation/constraints.py`(新)/
`tests/unit/research/allocation/test_constraints.py`(新)。

⑥ **跑了哪些测试 + 结果** — test_constraints 7 passed(empty/
under-cap 不变/over-cap throttle/收敛/initial-entry/long-only/
determinism);新模块无回归。

⑦ **当前结果** — turnover cap enforcing 代码 + 测试就位;
constraints.py 模块建立。

⑧ **剩余风险** — 未接 harness → `turnover_cap_daily` 仍 pending_S4
(诚实);min_edge/exit_policy 仍 pending。

⑨ **下一轮建议** — Round 10 = `apply_turnover_cap` 接进
portfolio_acceptance harness + 翻 enforced + cross-check 功能验证。

⑩ **TODO** — [x] S1/S2 CLOSED · S4 config-honesty/turnover-impl ·
[ ] S4 wire+min_edge+exit+收口 · [ ] S5/S3/S7/S6。

⑪ **commit** — `a504d49`(主)。

## Round 10 — S4:turnover cap 接进 harness(turnover_cap_daily ENFORCED)

**时间**: 2026-05-22 · **主 commit**: `708fc5a` · **测试基线**: 3954
+ 1(allocation 41 passed)

① **当前阶段** — Round 10 / S4 / turnover cap 接线。

② **本轮目标** — `apply_turnover_cap` 接 harness,turnover_cap_daily
翻 enforced。

③ **为什么先做它** — Round 9 实现了函数,要在用 ml_allocation.yaml
的路径生效才算 enforced。

④ **做了什么** — `portfolio_acceptance._weights` 加 `apply_turnover_cap`
(rebalance 后);`ml_allocation.yaml` turnover_cap_daily→enforced;
cross-check 加 turnover 功能验证。

⑤ **改了哪些文件** — `portfolio_acceptance.py` / `ml_allocation.yaml`
/ `test_enforcement_status.py` / 新 acceptance json。

⑥ **跑了哪些测试 + 结果** — allocation 41 passed;**R3 harness 实跑
(turnover cap 生效)**:path A Sharpe 0.73,path D Sharpe 1.14 /
MaxDD **-20.84%** / verdict **FAIL**。

⑦ **当前结果(non-blanket)** — turnover_cap_daily ENFORCED。**但接
turnover cap 后 path D MaxDD -19.85%→-20.84% 破 20% 不变量、verdict
FAIL** —— root cause:turnover cap 限速调仓→撤出回撤名变慢→回撤加深;
真实约束暴露真实风险,非 bug。

⑧ **剩余风险 / 重要 flag** — 这是 train-only smoke 非 S6 gate(协议
四非停点);**但响亮 flag**:leak-free+全约束下 path D MaxDD 已贴/破
20% → S6 真 OOS(含 2018 bear)有实打实 FAIL 风险。

⑨ **下一轮建议** — Round 11 = 实现 min_edge_to_trade enforcement。

⑩ **TODO** — [x] S1/S2 CLOSED · S4 config-honesty/turnover-enforced ·
[ ] S4 min_edge/exit+收口 · [ ] S5/S3/S7/S6(S6 MaxDD 风险已 flag)。

⑪ **commit** — `708fc5a`(主)。

## Round 11 — S4:constraints.py — apply_min_edge_gate 实现

**时间**: 2026-05-22 · **主 commit**: `7b86d84` · **测试基线**: 3955
→ 3961(+6;test_constraints 13 passed)

① **当前阶段** — Round 11 / S4 / min-edge gate。

② **本轮目标** — 实现 `min_edge_to_trade` enforcing 代码。

③ **为什么先做它** — 用户〇#1 要实现 min_edge;turnover 已 enforced。

④ **做了什么** — `constraints.py` 加 `apply_min_edge_gate(weights,
edge_bps, hurdle_bps)`:edge_bps<hurdle 的 bar 清零(cash);NaN edge
→cash fail-closed。**§9.0 纪律**:edge_bps 必须 caller 供非-forecast
proxy(§9.0 禁 ML 出 magnitude),docstring 明写。+6 单测。

⑤ **改了哪些文件** — `core/research/allocation/constraints.py` /
`tests/unit/research/allocation/test_constraints.py`(+6)。

⑥ **跑了哪些测试 + 结果** — test_constraints 13 passed(7 turnover
+ 6 min-edge);additive 无回归。

⑦ **当前结果** — min_edge gate enforcing 代码 + 测试就位。

⑧ **剩余风险** — 未接 harness → min_edge_to_trade 仍 pending_S4;
edge_bps 来源(§9.0-clean trailing-realized proxy)接 harness 时设计;
exit_policy 仍 pending。

⑨ **下一轮建议** — Round 12 = 接 apply_min_edge_gate 进 harness
(trailing-realized book-vs-universe excess 作 edge proxy)+ 翻
enforced + cross-check。

⑩ **TODO** — [x] S1/S2 CLOSED · S4 config-honesty/turnover/min-edge-impl
· [ ] S4 wire min_edge+exit_policy+收口 · [ ] S5/S3/S7/S6。

⑪ **commit** — `7b86d84`(主)。

## Round 12 — S4:min-edge 接线 attempt 失败 — revert + min_edge→roadmap

**时间**: 2026-05-22 · **主 commit**: `acb3028` · **测试基线**: 3961
(allocation 47 passed)

① **当前阶段** — Round 12 / S4 / min-edge 接线。

② **本轮目标** — `apply_min_edge_gate` 接 harness,min_edge 翻 enforced。

③ **为什么先做它** — Round 11 实现了函数,要接路径生效。

④ **做了什么 + 失败 root-cause** — 接线 attempt:`_trailing_edge_bps`
(trailing-63d realized excess)per-bar 喂 gate。**R3 harness 实跑
严重劣化**:path A Sharpe **+0.73→-0.46**、path D 1.14→0.70。
**root cause**:trailing-realized edge 滞后;滞后 proxy + 硬 gate =
edge 上追涨杀跌 whipsaw。诚实处理:**revert** 接线、`apply_min_edge_gate`
函数保留(test_constraints 6 测试)、`min_edge_to_trade → roadmap`
(§9.0 禁 ML 出 magnitude → 无现成非-whipsaw edge proxy,是研究子
问题)、portfolio_acceptance.py 留 NOTE。

⑤ **改了哪些文件** — `portfolio_acceptance.py`(revert+NOTE)/
`ml_allocation.yaml`(min_edge→roadmap)/`test_enforcement_status.py`。

⑥ **跑了哪些测试 + 结果** — allocation 47 passed(gate 函数+6 测试
仍在;harness 无接线数值回退正常)。

⑦ **当前结果(non-blanket)** — min_edge 接线 attempt 失败已 revert+
root-caused;gate 函数保留;min_edge 诚实标 roadmap。**用户〇#1 期望
实现 min_edge —— 诚实结果:gate 函数实现了,production edge-proxy
比预期难(naive proxy whipsaw),是研究子问题。**

⑧ **剩余风险 / flag** — min_edge 未 production-enforced(roadmap);
S4 gate "no silent unenforced control" 不破(roadmap=显式声明);
exit_policy 仍 pending。

⑨ **下一轮建议** — Round 13 = exit_policy(最后一个 pending_S4)。

⑩ **TODO** — [x] S1/S2 CLOSED · S4 config-honesty/turnover · S4
min_edge(失败 root-caused→roadmap)· [ ] S4 exit_policy+收口 ·
[ ] S5/S3/S7/S6。

⑪ **commit** — `acb3028`(主)。

## Round 13 — S4:exit_policy.py — signal_decay + turnover_band 实现

**时间**: 2026-05-22 · **主 commit**: `fa57098` · **测试基线**: 3961
→ 3971(+10;test_exit_policy 10 passed)

① **当前阶段** — Round 13 / S4 / exit_policy。

② **本轮目标** — 实现 exit_policy enforcing 代码。

③ **为什么先做它** — exit_policy 是最后一个 pending_S4;§4.9 要完整
退出策略。

④ **做了什么** — 新建 `core/research/allocation/exit_policy.py`:
实现 5 class 里 contemporaneous + 非-whipsaw 的两个(吸取 R12 教训)
—— `apply_signal_decay_exit`(held name rank 跌破阈值→退出,用 model
当前 rank 非滞后统计)+ `apply_turnover_band`(no-trade band)。诚实
标另外 3 个:time_based auto-满足、risk_off drawdown-exit whipsaw-prone
→roadmap、reentry cooldown=0 no-op。+10 单测。

⑤ **改了哪些文件** — `core/research/allocation/exit_policy.py`(新)/
`test_exit_policy.py`(新);删 R12 whipsaw 中间产物 json。

⑥ **跑了哪些测试 + 结果** — test_exit_policy 10 passed;新模块无回归。

⑦ **当前结果** — exit_policy 两个安全 exit 规则代码+测试就位;
exit_policy.py 模块建立。

⑧ **剩余风险** — 未接 harness → exit_policy 仍 pending_S4;risk_off
/reentry 诚实标 roadmap(非全 5 class —— drawdown-exit whipsaw-prone)。

⑨ **下一轮建议** — Round 14 = 接 signal_decay+turnover_band 进
harness + exit_policy→enforced + S4 收口。

⑩ **TODO** — [x] S1/S2 CLOSED · S4 config-honesty/turnover/min_edge
(roadmap)/exit_policy 实现 · [ ] S4 wire exit+收口 · [ ] S5/S3/S7/S6。

⑪ **commit** — `fa57098`(主)。

## Round 14 — S4 收口:exit_policy 接进 harness(S4 CLOSED)

**时间**: 2026-05-22 · **主 commit**: `c8d2935` · **测试基线**: 3971
+ 1(allocation 58 passed)

① **当前阶段** — Round 14 / S4 / 收口。

② **本轮目标** — exit_policy 接 harness,翻 enforced,关 S4。

③ **为什么先做它** — exit_policy 是最后一个 pending_S4。

④ **做了什么** — `portfolio_acceptance._weights` 加
`apply_signal_decay_exit` + `apply_turnover_band`;`ml_allocation.yaml`
exit_policy→enforced(+子规则注释);test_enforcement_status 加
exit_policy 功能验证 + pending 集断言为空。

⑤ **改了哪些文件** — `portfolio_acceptance.py` / `ml_allocation.yaml`
/ `test_enforcement_status.py` / 新 acceptance json。

⑥ **跑了哪些测试 + 结果** — allocation 58 passed;**R3 harness 全
约束集实跑**:path D Sharpe 0.81 / MaxDD **-19.17%** / verdict PASS
—— signal_decay 把 MaxDD -20.84%→-19.17% 拉回 20% 内。

⑦ **当前结果** — **S4 CLOSED**。§12.3 gate 满足:cross-check 测试守
住、master P3「no silent unenforced control」literally true。最终
状态:enforced 8 / roadmap 6 / disabled 1 / pending 0。

⑧ **剩余风险 / 诚实标注** — min_edge_to_trade=roadmap(R12 whipsaw
root-caused);exit_policy 实现 2/5 class(time_based auto、
risk_off/reentry roadmap,显式);全约束集 path D Sharpe 1.29→0.81、
MaxDD -19.17% 贴 20% 线 → S6 真 OOS 仍有 FAIL 风险。

⑨ **下一轮建议** — Round 15 = S5(§9.6 overfit-control 修正)。

⑩ **TODO** — [x] S1/S2/**S4 CLOSED** · [ ] S5/S3/S7/S6。

⑪ **commit** — `c8d2935`(主)。

## Round 15 — S5:修 DSR-喂-rank-IC 误用(rank-IC t-stat)

**时间**: 2026-05-22 · **主 commit**: `cbdb00c` · **测试基线**: 3972
→ 3978(+6;test_rank_ic_significance 6 passed)

① **当前阶段** — Round 15 / S5 / 第一刀。

② **本轮目标** — 修 audit O1:`_overfit_control` 把 rank-IC 喂给
`deflated_sharpe_ratio`。

③ **为什么先做它** — S5 首位;DSR-喂-rank-IC 是无意义数。

④ **做了什么** — 新增 `_rank_ic_significance`(mean-IC t-stat,记
n_trials 供 Bonferroni);`_overfit_control` 把 DSR 块换成
rank_ic_significance。PBO 保留(rank-IC 作 per-period perf 喂 PBO
合法,错的只是 DSR)。+6 单测。

⑤ **改了哪些文件** — `dev/scripts/ml/walk_forward_rank_sign.py` /
`tests/unit/research/ml/test_rank_ic_significance.py`(新)。

⑥ **跑了哪些测试 + 结果** — test_rank_ic_significance 6 passed(含
"结果无 dsr key" 钉子);无回归。

⑦ **当前结果** — O1(DSR-喂-rank-IC)修复:rank 走 forward 报正确
IC t-stat。

⑧ **剩余风险 / S5 未尽** — ② n_trials 硬编码(应来自 trial ledger);
③ PBO 5-config sweep 共线偏乐观。P4 harness `_overfit_control` 用真
收益喂 DSR — 那个没问题。

⑨ **下一轮建议** — Round 16 = S5 #2:n_trials 从 persisted trial
ledger 取。

⑩ **TODO** — [x] S1/S2/S4 CLOSED · S5 O1-fix · [ ] S5 ledger+PBO+收口
· [ ] S3/S7/S6。

⑪ **commit** — `cbdb00c`(主)。

## Round 16 — S5:n_trials 从 persisted trial ledger 取

**时间**: 2026-05-22 · **主 commit**: `add8ff4` · **测试基线**: 3978
(R3 实跑;仅 driver + 新 ledger)

① **当前阶段** — Round 16 / S5 / n_trials ledger。

② **本轮目标** — 修 O1 #2:`--n-trials` 硬编码 5 → 从 trial ledger 取。

③ **为什么先做它** — DSR 反通缩靠 n_trials;硬编码 5 低估 → DSR 偏松。

④ **做了什么** — 新建 `data/audit/ml_trial_ledger.json`(诚实枚举
path-D 选择中实际 examine 的 10 个 distinct config:baseline / 3
model family / 2 objective / 3 mapping / 2 vol-target);
`portfolio_acceptance.py` `--n-trials` default None → `len(ledger)`。

⑤ **改了哪些文件** — `data/audit/ml_trial_ledger.json`(新)/
`portfolio_acceptance.py` / 新 acceptance json。

⑥ **跑了哪些测试 + 结果** — R3 harness:`n_trials=10`(原 5),
**DSR 0.893→0.806**(诚实更多反通缩);verdict 仍 PASS。

⑦ **当前结果** — DSR n_trials 来自 persisted 可审计 ledger,按真实
10-trial 广度反通缩。

⑧ **剩余风险 / S5 未尽** — O1 #3:PBO 5-config sweep 共线偏乐观;
trial-ledger memo 待写。

⑨ **下一轮建议** — Round 17 = S5 #3(PBO 独立 config)+ memo +
S5 收口。

⑩ **TODO** — [x] S1/S2/S4 CLOSED · S5 O1-fix/n_trials-ledger ·
[ ] S5 PBO+memo+收口 · [ ] S3/S7/S6。

⑪ **commit** — `add8ff4`(主)。

## Round 17 — S5:PBO sweep 改 model-diverse

**时间**: 2026-05-22 · **主 commit**: `ff80503` · **测试基线**: 3978
(R3 实跑)

① **当前阶段** — Round 17 / S5 / PBO sweep。

② **本轮目标** — 修 O1 #3:PBO sweep 4 个 XGB-mapping 换皮共线。

③ **为什么先做它** — S5 三子问题最后一个;PBO 偏乐观放过过拟合。

④ **做了什么** — harness fold loop 改训 3 个真不同 model family
(XGB/Linear/LGBM)per fold;`_overfit_control` PBO sweep 改成
{A_composite + D_xgb + D_linear + D_lgbm}(model-diverse)。

⑤ **改了哪些文件** — `portfolio_acceptance.py` / 新 acceptance json。

⑥ **跑了哪些测试 + 结果** — R3 harness:**PBO 0.135 → 0.333** ——
共线 sweep 确实给 optimistically-low 0.135,model-diverse sweep 给
诚实 0.333(仍 <0.5 无红旗);n_trials=10、DSR 0.806;verdict PASS。

⑦ **当前结果** — PBO 跑在 model-diverse sweep(3 真不同模型族),
0.333 是诚实数(原 0.135 偏乐观已证)。

⑧ **剩余风险 / S5 未尽** — trial-ledger memo 待写;S5 §9.6 gate
核对 + 收口待 Round 18。

⑨ **下一轮建议** — Round 18 = trial-ledger memo + S5 §9.6 gate 核对
+ S5 收口。

⑩ **TODO** — [x] S1/S2/S4 CLOSED · S5 O1-fix/n_trials-ledger/PBO-diverse
· [ ] S5 memo+收口 · [ ] S3/S7/S6。

⑪ **commit** — `ff80503`(主)。

## Round 18 — S5 收口:trial-ledger memo + freeze-gate overfit-validity

**时间**: 2026-05-22 · **主 commit**: `cc98537` · **测试基线**: 3978
+ 5(test_freeze_bundle 12 passed)

① **当前阶段** — Round 18 / S5 / 收口。

② **本轮目标** — trial-ledger memo + freeze gate overfit-validity 检查,
关 S5。

③ **为什么先做它** — R15-17 修了 O1 三子问题;余下 = memo +
freeze-gate validity。

④ **做了什么** — 新建 `20260522-ml-trial-ledger.md`(记录 ledger /
n_trials 喂 DSR / 维护规则 / caveat);`freeze_bundle.py` 加
`_overfit_control_valid`(n_trials≥2+finite DSR+finite PBO),
`build_freeze_bundle` degenerate 块不得过 gate;test_freeze_bundle
+5 validity 测试。

⑤ **改了哪些文件** — `20260522-ml-trial-ledger.md`(新)/
`freeze_bundle.py` / `test_freeze_bundle.py`。

⑥ **跑了哪些测试 + 结果** — test_freeze_bundle 12 passed(+5)、
test_artifact 33 passed 无回归。

⑦ **当前结果** — **S5 CLOSED**。§9.6 gate 三项:① DSR/PBO inputs
valid(DSR 喂真收益/n_trials ledger/PBO model-diverse)② memo 记录
ledger ③ freeze gate 检 overfit valid 非仅存在。

⑧ **剩余风险 / 诚实标注** — trial ledger 手工 curate(caveat 已写
memo);rank-IC t-stat 不做 n_trials 反通缩(t-stat 正确,Bonferroni
留下游)。

⑨ **下一轮建议** — Round 19 = Package S3(P2/P4 命名产物 + 4-path)。

⑩ **TODO** — [x] S1/S2/S4/**S5 CLOSED** · [ ] S3/S7/S6。

⑪ **commit** — `cc98537`(主)。

## Round 19 — S3/R2:sample_weight.py — 4-component 乘性加权实现

**时间**: 2026-05-22 · **主 commit**: `60a0777` · **测试基线**: 3983
→ 3993(+10;test_sample_weight 10 passed)

① **当前阶段** — Round 19 / S3(R2 sample-weighting)。

② **本轮目标** — 实现 master §8.2 canonical multiplicative sample
weight。

③ **为什么先做它** — S5 后是 S3;R2 是 audit HIGH 遗漏(prior 0 加权)。

④ **做了什么** — 新建 `core/research/ml/sample_weight.py`:
`uniqueness × liquidity × volatility × freshness`(uniqueness 复用
concurrency_weights;liquidity 截面归一成交量;volatility inverse-vol
winsorized §3.3;freshness 指数 recency)。`COMPONENT_FORMULAS` 供
§8.4 auditability。+10 单测。

⑤ **改了哪些文件** — `core/research/ml/sample_weight.py`(新)/
`test_sample_weight.py`(新)。

⑥ **跑了哪些测试 + 结果** — test_sample_weight 10 passed;新模块无回归。

⑦ **当前结果** — 4-component 乘性样本加权代码+测试就位。

⑧ **剩余风险** — 未接训练 driver(R20);§8.3 default-on + flag、
§8.4 artifact 记录待 R20 接线落实。

⑨ **下一轮建议** — Round 20 = sample_weight 接进 sign classifier
训练(默认开,`--no-sample-weight` flag,artifact 记 weight 统计)。

⑩ **TODO** — [x] S1/S2/S4/S5 CLOSED · S3 sample_weight 模块 ·
[ ] S3 接 driver+收口 · [ ] S7/S6。

⑪ **commit** — `60a0777`(主)。

## Round 20 — S3:sign classifier .fit 接 sample_weight

**时间**: 2026-05-22 · **主 commit**: `775f054` · **测试基线**: 3993
→ 3997(+4;test_sign_classifier 28 passed)

① **当前阶段** — Round 20 / S3 / sign classifier 接 sample_weight。

② **本轮目标** — 两个 sign 模型 `.fit` 接受 `sample_weight`。

③ **为什么先做它** — R19 实现了模块;模型 .fit 须先能接。

④ **做了什么** — `LogisticRegressionSignClassifier.fit` 加 weighted
IRLS(sample_weight 进 grad+Hessian,finite_mask 对齐,None→uniform
bit-identical);`XGBSignClassifier.fit` passthrough 给 XGBClassifier。
+4 单测。

⑤ **改了哪些文件** — `core/research/ml/sign_classifier.py` /
`test_sign_classifier.py`(+4)。

⑥ **跑了哪些测试 + 结果** — test_sign_classifier 28 passed(+4 含
sample_weight=None bit-identical 钉子);additive 可选参数无回归。

⑦ **当前结果** — 两个 sign 模型 .fit 接 sample_weight;None=uniform
非破坏。

⑧ **剩余风险** — driver 未算 weight panel 未 thread;§8.3 flag /
§8.4 artifact 待 R21。

⑨ **下一轮建议** — Round 21 = `walk_forward_sign_classifier.py` 算
weight panel + `_assemble_xy` 收权重 + thread fit + `--no-sample-weight`
flag + artifact 记 weight 统计。

⑩ **TODO** — [x] S1/S2/S4/S5 CLOSED · S3 模块/sign-fit · [ ] S3
driver 接线+收口 · [ ] S7/S6。

⑪ **commit** — `775f054`(主)。

## Round 21 — S3 收口:sample_weight 接进 sign 训练 driver(S3 CLOSED)

**时间**: 2026-05-22 · **主 commit**: `a3d5b03` · **测试基线**: 3997
(R3 双路径 smoke)

① **当前阶段** — Round 21 / S3 / 收口。

② **本轮目标** — sample_weight 接进 sign driver,default-on + flag +
artifact,关 S3。

③ **为什么先做它** — R19-20 备好模块+模型 .fit;driver 接线收口。

④ **做了什么** — `_assemble_xy` 加 weight_panel 收 per-row 权重返回
(X,y,w);driver `--no-sample-weight` flag(default ON)+ 算 sw_panel
+ fold fit threads w_train;summary 加 §8.3/§8.4 `sample_weighting`
块;governance sample_weight_mode 真值。修兄弟 driver
hyperparam_search 的 3-tuple 解包。

⑤ **改了哪些文件** — `walk_forward_sign_classifier.py` /
`hyperparam_search_sign_classifier.py`。

⑥ **跑了哪些测试 + 结果** — R3 双路径 smoke:default → 加权
(mean=1.000,summary 带全 §8.3/§8.4 块);`--no-sample-weight` →
DISABLED。两 driver syntax OK;模型层 R20 已测 28 passed。

⑦ **当前结果** — **S3 CLOSED**。§8.3 gate:① 加权 default-on ②
disable 需显式 flag ③ artifact 记 weight 统计+component 公式 —— 三项
双路径实证。

⑧ **剩余风险 / 诚实标注** — hyperparam_search 搜索 log 不加权(最终
模型走 walk_forward 加权);rank 训练(XGBRanker)未加 sample_weight
(supplement S3 "where appropriate";ranker weighted fit 是更大改动,
留 follow-up,留痕)。

⑨ **下一轮建议** — Round 22 = Package S7(P2/P4 命名产物 + 4-path)。

⑩ **TODO** — [x] S1/S2/S4/S5/**S3 CLOSED** · [ ] S7/S6。

⑪ **commit** — `a3d5b03`(主)。

## Round 22 — S7:portfolio_metrics M1 hygiene 修复

**时间**: 2026-05-22 · **主 commit**: `2212b6c` · **测试基线**: 3997
→ 4001(+4;allocation 62 passed)

① **当前阶段** — Round 22 / S7 / M1 hygiene。

② **本轮目标** — 修 audit M1 的 portfolio_metrics 三项。

③ **为什么先做它** — M1 最具体可验证;portfolio_metrics 是所有 path
verdict 共享模块。

④ **做了什么** — `portfolio_metrics` 三修:M6 加 `periods_per_year`
参数替硬编码 252;M4 turnover 成本 `.shift(1)` 对齐到新权重 earn 的
bar;M3 `port_ret.clip(lower=-0.999)` NAV-正性 fail-safe。

⑤ **改了哪些文件** — `portfolio_metrics.py` / `test_portfolio_metrics.py`
(+4);删 R21 smoke 工件 2 个。

⑥ **跑了哪些测试 + 结果** — allocation 62 passed(+4)。R3 自纠:首跑
periods_per_year 测试失败 = 断言 tolerance 太紧(round(.,4) 比值舍入);
代码对、测试严,已放宽。

⑦ **当前结果** — portfolio_metrics M1 三项修复 + 测试。

⑧ **剩余风险** — turnover-cost shift 让 cost>0 数微调(S6 重跑用修正
metric);S7 余项:evaluate_fold / freeze model-hash / 命名产物 /
4-path / §〇#5 PRD 措辞。

⑨ **下一轮建议** — Round 23 = evaluate_fold 代码-bug 区分(M6)+
freeze_bundle model hash(M9)。

⑩ **TODO** — [x] S1/S2/S4/S5/S3 CLOSED · S7 M1-hygiene · [ ] S7
余项+收口 · [ ] S6。

⑪ **commit** — `2212b6c`(主)。

## Round 23 — S7:evaluate_fold 代码-bug 区分(M6)+ freeze model hash(M9)

**时间**: 2026-05-22 · **主 commit**: `701b4d0` · **测试基线**: 4001
→ 4009(+8;research/ml 204 passed)

① **当前阶段** — Round 23 / S7 / M6+M9。

② **本轮目标** — 修 M6(evaluate_fold 静默把代码 bug 当数据-fold)+
M9(freeze 不哈希模型)。

③ **为什么先做它** — audit MED 卫生项,具体可验证。

④ **做了什么** — M6:`evaluate_fold` `except` 拆 `ValueError`→
`data_fold:` / 其他→`CODE_BUG:`+`warnings.warn`。M9:`build_freeze_bundle`
强制 `model_artifact_path`(None/不存在→FreezeBundleError);
`freeze_ml_bundle.py` 加 `--model-artifact`;model hash 不再 None。

⑤ **改了哪些文件** — `pipeline.py` / `freeze_bundle.py` /
`freeze_ml_bundle.py` / `test_pipeline.py`(+2)/ `test_freeze_bundle.py`
(_build wrapper + 4 M9 测试)。

⑥ **跑了哪些测试 + 结果** — test_pipeline 33 / test_freeze_bundle 16;
research/ml 204 passed 无回归。

⑦ **当前结果** — M6 代码 bug 显式区分(CODE_BUG+warn);M9 freeze
强制哈希模型,model drift 可检出。

⑧ **剩余风险 / S7 未尽** — P2/P4 命名产物;4-path 统一;§〇#5 PRD
措辞 fold-in。

⑨ **下一轮建议** — Round 24 = §〇#5 PRD 措辞 fold-in(master §9.3/
§12.3 放宽 MaxDD gate)+ portfolio-acceptance-pack.md memo。

⑩ **TODO** — [x] S1/S2/S4/S5/S3 CLOSED · S7 M1/M6/M9 · [ ] S7 §〇#5
+命名产物+4-path+收口 · [ ] S6。

⑪ **commit** — `701b4d0`(主)。

## Round 24 — S7:§〇#5 PRD 措辞 fold-in + portfolio-acceptance-pack memo

**时间**: 2026-05-22 · **主 commit**: `b217858` · **测试基线**: 4009
(纯 doc fold-in)

① **当前阶段** — Round 24 / S7 / §〇#5 + acceptance-pack。

② **本轮目标** — §〇#5 放宽的 MaxDD gate 措辞 fold 进 master §9.3/
§12.3;写 portfolio-acceptance-pack.md。

③ **为什么先做它** — master §9.3 仍写 strict "non-inferior MaxDD",
与用户 2026-05-22 放宽决定文字冲突。

④ **做了什么** — master §9.3 `non-inferior MaxDD` → `MaxDD within
15-20% invariant`(SUPPLEMENT-2026-05-22 标记);§12.3 P4 gate 加
SUPPLEMENT 指针;新建 `portfolio-acceptance-pack.md`(§12.3 P4 命名
产物:4-path 说明 + 诚实 scoping B/C 在 r29 + §9.6 控制 + verdict
PASS+caveat + **promoted-config 决定 DEFER 到 S6**)。

⑤ **改了哪些文件** — `20260521-...-prd.md`(§9.3+§12.3 fold-in)/
`docs/memos/20260522-portfolio-acceptance-pack.md`(新)。

⑥ **跑了哪些测试** — 纯 doc fold-in,无代码,基线不变。

⑦ **当前结果** — master PRD MaxDD gate 措辞与 shipped verdict 一致;
§12.3 P4 命名产物 acceptance-pack 就位。

⑧ **剩余风险 / S7 未尽** — 4-path 统一(B/C 仍 r29,acceptance-pack
§1 诚实 scoping 留痕);§12.3 gate 核对 + S7 收口待 Round 25。

⑨ **下一轮建议** — Round 25 = S7 §12.3 gate 核对 + S7 收口。

⑩ **TODO** — [x] S1/S2/S4/S5/S3 CLOSED · S7 M1/M6/M9/§〇#5 · [ ] S7
gate+收口 · [ ] S6。

⑪ **commit** — `b217858`(主)。

<!-- Round 25 起在此行下方追加 -->
