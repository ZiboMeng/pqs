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

<!-- Round 13 起在此行下方追加 -->
