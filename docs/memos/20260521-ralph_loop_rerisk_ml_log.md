# Ralph-Loop 运行日志 — Re-Risk + ML Training Framework Hardening

每一轮 ralph-loop 迭代结束时,将本轮完整的中文 11 部分报告**追加**到本
文件末尾。不要覆盖既有条目。

参考:
- `docs/prd/20260521-rerisk-and-ml-training-audit-prd.md` — 阶段 PRD
- `docs/memos/20260521-ralph_loop_rerisk_ml_prompt.md` — 每轮协议
- `CLAUDE.md` — 系统不变约束

执行顺序:R0 → P0 → P1 → P2 → P3 → P4 → P5 → P6。
完成 promise:`RERISK-ML-PRD-DONE`。

---

## Round 1 — R0 第一步:re-risk pack 驱动 + baseline train-only 行

**时间**: 2026-05-21 · **主 commit**: `393b570` · **测试基线**: 3864
passed(未动 module 代码,不变)

① **当前阶段** — Round 1 / Workstream R0 / 第一步。

② **本轮目标** — 建 re-risk pack 驱动,产出 production baseline 的
train-only re-risk 行。

③ **为什么先做它** — PRD §12.4:R0 是 P0-P6 硬前置;§6.1 candidate #1
= production baseline;§6.4 要求行可复现自 checked-in 路径。

④ **做了什么** — 轮前审计发现 2 个 stray audit 工件(r32 重复重跑 =
已提交 215758Z 逐字副本;p7 = 环境漂移、verdict 不变),非 WIP/非
directional → housekeeping 清理留痕,不 halt loop。新建
`dev/scripts/audit/rerisk_pack.py`(subprocess run_backtest → 解析
master_report → verdict + JSON upsert)。跑 baseline train-only
2009-2017,写 `rerisk_pack_20260521.json` + `20260521-rerisk-pack.md`。

⑤ **改了哪些文件** — `dev/scripts/audit/rerisk_pack.py`(新)/
`data/audit/rerisk_pack_20260521.json`(新)/
`docs/memos/20260521-rerisk-pack.md`(新)。

⑥ **跑了哪些测试 + 结果** — driver exit 0;R3 复现:CAGR 12.59% /
MaxDD -20.21% / vol 13.16% 与 commit `8073c88` audit memo §6 逐字
一致;新独立 driver 未动 module 代码,不重跑全量回归。

⑦ **当前结果** — baseline train-only 2009-2017:总收益 +190.35% /
CAGR +12.59% / Sharpe 0.67 / MaxDD -20.21% / vol 13.16% / Beta 0.28
/ 1629 trades。verdict YELLOW(provisional,MaxDD 越 20% 硬线 0.2pp)。

⑧ **剩余风险** — verdict provisional(stress-slice + per-year MaxDD
未出);近期高波动窗口 -64% 未在 pack 复现;cycle06/08/PEAD 三行未做。

⑨ **下一轮建议** — Round 2 = R0 第二步:baseline stress slices
(covid_flash / rate_hike)+ 近期窗口 `partition: diagnostic` 复现
§2.1 -63.95% 画像;扩 driver 支持 per-year MaxDD。

⑩ **TODO** — [x] R0 driver [x] R0 baseline train-only ·
[ ] R0 baseline stress+diagnostic [ ] cycle06 [ ] cycle08 [ ] PEAD
[ ] R0 收口 · [ ] P0-P6。

⑪ **commit** — `393b570`(主)。

## Round 2 — R0 第二步:baseline 近期窗口 diagnostic 行 + regime 解析

**时间**: 2026-05-21 · **主 commit**: `de7eb38` · **测试基线**: 3864
passed(未动 module 代码,不变)

① **当前阶段** — Round 2 / Workstream R0 / 第二步。

② **本轮目标** — 扩驱动解析 regime 分层表;产出 baseline 近期窗口
diagnostic 行,复现 PRD §2.1 -64% 画像。

③ **为什么先做它** — §2.1 caveat 要求把 -63.95% 落成 checked-in、
explicit-window、标注 diagnostic 的可复现行;用户决策〇.4 已预授权。

④ **做了什么** — 轮前 bar-integrity smoke(SPY/QQQ 2022-2025 各 1003
行 0 周末行 CLEAN)。扩 `rerisk_pack.py`:`parse_regime_breakdown` +
diagnostic-partition verdict 分支。跑 baseline 2022-01-03..2025-12-31
(partition=diagnostic),更新 pack(2 行)+ memo §1.2/§1.3。

⑤ **改了哪些文件** — `dev/scripts/audit/rerisk_pack.py` /
`data/audit/rerisk_pack_20260521.json` /
`docs/memos/20260521-rerisk-pack.md`。

⑥ **跑了哪些测试 + 结果** — driver exit 0;R3 复现:diagnostic 行
CAGR -4.49% / MaxDD -63.95% / vol 27.72% 与 PRD §2.1 /tmp 数字逐字
一致 → §2.1 caveat 闭合;regime parser 解析 5 个 regime;仅扩 driver
未动 module 代码。

⑦ **当前结果** — baseline 2022-2025 diagnostic:CAGR -4.49% / MaxDD
-63.95% / vol 27.72%,verdict RED(informational)。对照 §1.1
train-only(+12.59% / -20.21% / 13.16%)→ 印证 baseline regime-
fragile、高波动期风控翻译失效(diagnostic 窗口 realized vol 27.72%
越 constructor 25% target)。

⑧ **剩余风险** — stress slices 未做(需先核查既有 stress harness,
避免重造/误触 holdout);per-year MaxDD 字段未出;cycle06/08/PEAD
未做;Round-1 train-only 行 regime_breakdown 空(非 load-bearing)。

⑨ **下一轮建议** — Round 3 = R0 第三步:先核查项目既有 stress-slice
MaxDD 机制(`stress_tester` / cycle06_track_a_eval),确认 sanctioned
实现后产出 covid_flash / rate_hike stress 行;若需遍历 validation
且无 sanctioned 封装则按协议四停下问用户。

⑩ **TODO** — [x] driver [x] baseline train-only [x] baseline 近期
diagnostic · [ ] baseline stress slices [ ] per-year MaxDD
[ ] cycle06 [ ] cycle08 [ ] PEAD [ ] R0 收口 · [ ] P0-P6。

⑪ **commit** — `de7eb38`(主)。

## Round 3 — R0 第三步:stress-slice 机制核查 — STOPPED, NEEDS USER DECISION

**时间**: 2026-05-21 · **主 commit**: `a23bcf0` · **测试基线**: 3864
passed(无代码改动,不变)

① **当前阶段** — Round 3 / Workstream R0 / 第三步(机制核查)。

② **本轮目标** — 核查既有 stress-slice MaxDD 机制,确认 sanctioned
实现后产出 baseline covid_flash / rate_hike stress 行。

③ **为什么先做它** — Round 2 §⑨ 已定:stress-slice 实现前先核查。

④ **做了什么** — 核查 `stress_tester.py`(静态 shock 模型,不适用)、
`cycle06_track_a_eval.py`(Track-A 用 selector 面板算
metrics_per_stress_slice)、`temporal_split.py`(slice source 自
train 年)、`temporal_split_acceptance`(stress_check_only gate)。
结论写入 `rerisk-pack.md` §1.3。

⑤ **改了哪些文件** — `docs/memos/20260521-rerisk-pack.md`(§1.3)。

⑥ **跑了哪些测试 + 结果** — 机制核查 + 文档轮,无代码改动无测试。

⑦ **当前结果** — 确认:算 baseline 穿越 covid/rate_hike 的 MaxDD,
189d 动量 warmup 必然吃危机前 ~9 个月(2019/2021 = validation 年)。
Track-A 用 selector 面板这样做合规;R0 不是 selector 阶段。

⑧ **剩余风险 / 为什么停** — 真实 temporal_split 方法论问题:用户
决策 ⑤ 授权 "designated stress slice" 但未明确 "warmup 穿 validation"
子问题。按 `feedback_temporal_split_discipline`(不确定就停)+ 协议
四 #3 停下问用户 —— PRD 审计 §5 已预标的 directional 点。

⑨ **下一轮建议** — 用户在 §1.3 选项 A/B/C 拍板(operator 推荐 A:
warmup+slice 标 informational,同 diagnostic 行纪律);拍板后重启
ralph-loop。

⑩ **TODO** — [x] driver [x] baseline train-only [x] baseline 近期
diagnostic [x] stress 机制核查 · [ ] baseline stress slices
(BLOCKED 等用户 A/B/C)[ ] per-year MaxDD [ ] cycle06/08/PEAD
[ ] R0 收口 · [ ] P0-P6。

⑪ **commit** — `a23bcf0`(主)。

**STOPPED — NEEDS USER DECISION**:rerisk-pack.md §1.3,stress-slice
warmup 穿越 validation 的方法论选择 A/B/C。

## Round 4 — R0:cycle06 re-risk 行(exact frozen-spec replay)

**时间**: 2026-05-21 · **主 commit**: `d3cf26d` · **测试基线**: 3864
passed(未动 module 代码)

① **当前阶段** — Round 4 / Workstream R0 / cycle06 行。

② **本轮目标** — 按 exact frozen spec 重评 cycle06_31af04cf2ff9,产出
R0 cycle06 re-risk 行。

③ **为什么先做它** — baseline stress 行 block 于 Round 3 的 A/B/C
决策;cycle06 不被它 block。用户沉默多轮 → 推进不依赖该决策的工作而
非空转。(用户本轮中途回「走 A」,已落账 §1.3。)

④ **做了什么** — 新建 `rerisk_cycle06.py`(载 frozen yaml 3-feature
composite verbatim,复用 cycle06 Track-A `_eval_trial`,selector
面板对 research 候选 Track-A 阶段合规)+ `--reuse-eval` 缓存。跑重评,
写 cycle06 行 + eval artifact。memo §2 + §1.3 决策落账。

⑤ **改了哪些文件** — `dev/scripts/audit/rerisk_cycle06.py`(新)/
`data/audit/rerisk_pack_20260521.json` / `rerisk_cycle06_eval.json`
(新)/ `docs/memos/20260521-rerisk-pack.md`。

⑥ **跑了哪些测试 + 结果** — driver exit 0;R3 核对:covid -15.99%
(frozen -15.32%)/ rate_hike -9.48%(frozen -9.48%)/ 2018 -19.94%
(frozen -19.60%)—— 风险面 ≈ frozen ±<0.7pp,复现可信;未动 module
代码不重跑回归。

⑦ **当前结果** — cycle06 exact-frozen-spec verdict **RED**,
non-blanket:① 风险面稳定(per-year ≤20% / stress ≤25%,与 frozen
一致);② Track-A 总判 **PASS→FAIL**(`validation_aggregate_excess_
vs_spy`)。frozen yaml 的 `track_a_acceptance: PASS` 当前不复现 ——
alpha-gate 失败,非风控回归。

⑧ **剩余风险** — cycle06 Track-A PASS→FAIL 是 R0 实质发现(留收口
+ 用户讨论);cycle08/PEAD 行未做;baseline stress 行 + per-year
字段待 Round 5。

⑨ **下一轮建议** — Round 5 = baseline stress slices via Option A
(用户已批);后 cycle08 / PEAD / R0 收口。

⑩ **TODO** — [x] driver [x] baseline train-only [x] baseline 近期
diagnostic [x] stress 机制核查+裁定 A [x] cycle06 行 ·
[ ] baseline stress(Option A)[ ] cycle08 [ ] PEAD [ ] per-year
MaxDD [ ] R0 收口 · [ ] P0-P6。

⑪ **commit** — `d3cf26d`(主)。

## Round 5 — R0:baseline stress slices via Option A

**时间**: 2026-05-21 · **主 commit**: `4c3708b` · **测试基线**: 3864
(run_backtest 改动纯附加,不受影响)

① **当前阶段** — Round 5 / Workstream R0 / baseline stress 行。

② **本轮目标** — 按用户裁定 Option A 产出 baseline 在 covid_flash /
rate_hike_2022 designated stress slice 上的 MaxDD 行。

③ **为什么先做它** — Round 3 决策用户已回「走 A」;Round 4 排定。

④ **做了什么** — 轮前 bar-integrity smoke(CLEAN)。`run_backtest.py`
加附加 equity_curve.csv dump(try/except,不改回测行为)。
`rerisk_pack.py` 加 `_maxdd` + `run_baseline_stress`(warmup+slice
回测→读 equity csv→按 designated slice 日期算 MaxDD)+ `_verdict`
stress 分支 + `--candidate baseline-stress`。跑 covid + rate_hike。

⑤ **改了哪些文件** — `scripts/run_backtest.py` /
`dev/scripts/audit/rerisk_pack.py` /
`data/audit/rerisk_pack_20260521.json` /
`docs/memos/20260521-rerisk-pack.md`。

⑥ **跑了哪些测试 + 结果** — driver exit 0;2 次 run_backtest 子进程
成功产 master_report + 新 equity_curve.csv 并被解析 → run_backtest
附加改动端到端验证(R3);改动纯附加不触 engine.run。

⑦ **当前结果** — covid_flash slice(2020-02-15..04-30)MaxDD
**-13.66%** GREEN;rate_hike_2022 slice(2022-08-15..10-15)MaxDD
**-3.51%** GREEN;均 ≤25% Black-Swan 上限。

⑧ **剩余风险 / 诚实 caveat** — **stress GREEN ≠ baseline 抗危机**:
designated slice 是窄窗,rate_hike slice 只覆盖 2022 熊市最后一段,
故 -3.51% 很小 —— baseline 整个 2022 真实创伤是 §1.2 diagnostic 行
的 -63.95%。不可误读。cycle08/PEAD 行未做;baseline per-year MaxDD
未补。

⑨ **下一轮建议** — Round 6 = cycle08 re-risk 行(exact frozen spec,
与 cycle06 同路);后 PEAD、baseline per-year MaxDD、R0 收口。

⑩ **TODO** — [x] driver [x] baseline train-only [x] 近期 diagnostic
[x] stress 机制核查+裁定 A [x] cycle06 行 [x] baseline stress slices ·
[ ] cycle08 [ ] PEAD [ ] baseline per-year MaxDD [ ] R0 收口 ·
[ ] P0-P6。

⑪ **commit** — `4c3708b`(主)。

## Round 6 — R0:cycle08 re-risk 行(exact frozen-spec replay)

**时间**: 2026-05-21 · **主 commit**: `6d54a31` · **测试基线**: 3864
(未动 module 代码)

① **当前阶段** — Round 6 / Workstream R0 / cycle08 行。

② **本轮目标** — 按 exact frozen spec 重评 cycle08_3f40e3f4ed1a,产出
R0 cycle08 re-risk 行。

③ **为什么先做它** — Round 5 排定;cycle08 与 cycle06 同路、不依赖待
决项。

④ **做了什么** — `rerisk_cycle06.py` git mv → `rerisk_composite_
candidate.py` 并泛化(`--candidate {cycle06,cycle08}`)。核查 cycle08
frozen construction 与 `_eval_trial` HarnessConfig 一致。跑
`--candidate cycle08`(heavy)+ `--candidate cycle06 --reuse-eval`
(instant,刷新 cycle06 行 reproduce_cmd)。

⑤ **改了哪些文件** — `rerisk_composite_candidate.py`(git mv+泛化)/
`rerisk_pack_20260521.json` / `rerisk_cycle08_eval.json`(新)/
`docs/memos/20260521-rerisk-pack.md`。

⑥ **跑了哪些测试 + 结果** — driver exit 0;R3 核对:cycle08
covid -19.73%(frozen -19.72%)/ rate_hike -11.90%(frozen -11.90%)
/ 2018 -16.79%(frozen -18.10%)—— frozen evidence 完整复现;
未动 module 代码。

⑦ **当前结果** — cycle08 exact-frozen-spec verdict **GREEN**:
Track-A 总判 **PASS 保持**,per-year ≤20% / stress ≤25%,与 frozen
几乎逐字一致。**对比 cycle06**:cycle06 重评 PASS→FAIL(vs-SPY);
cycle08 PASS 稳住 —— cycle08 是两个 evidence 候选里更稳健的。

⑧ **剩余风险** — PEAD 行未做;baseline per-year MaxDD 字段未补;
R0 收口未做。

⑨ **下一轮建议** — Round 7 = PEAD re-risk 行;后 baseline per-year
MaxDD、R0 收口 → P0-P6。

⑩ **TODO** — [x] driver [x] baseline train-only [x] 近期 diagnostic
[x] stress 机制核查+裁定 A [x] baseline stress slices [x] cycle06 行
[x] cycle08 行 · [ ] PEAD 行 [ ] baseline per-year MaxDD [ ] R0 收口
· [ ] P0-P6。

⑪ **commit** — `6d54a31`(主)。

## Round 7 — R0:PEAD re-risk 行(post-fix Track-A acceptance)

**时间**: 2026-05-21 · **主 commit**: `de2a55e` · **测试基线**: 3864
(未动 module 代码)

① **当前阶段** — Round 7 / Workstream R0 / PEAD 行。

② **本轮目标** — post-fix 重评 PEAD 候选 pead_sue_trial1_evidence_v1,
产出 R0 PEAD 行。

③ **为什么先做它** — Round 6 排定;PEAD 现有 verdict 是 May-14 stale,
需 post-fix 重跑。

④ **做了什么** — 重跑 sanctioned 的 `run_pead_track_a_acceptance.py`
(刷新 verdict json + NAV)。新建 `rerisk_pead.py`(读 verdict json
trial1_short_hold,折进 pack)。memo §4 + 进度表。

⑤ **改了哪些文件** — `dev/scripts/audit/rerisk_pead.py`(新)/
`pead_path1_track_a_verdict.json`(重跑覆写)/ 2 NAV parquet /
`rerisk_pack_20260521.json` / `docs/memos/20260521-rerisk-pack.md`。

⑥ **跑了哪些测试 + 结果** — 两 driver exit 0;R3 对比 pre-fix:
Sharpe 1.055→0.986 / CAGR 5.48%→5.43% / MaxDD -7.64%→-7.92% /
Track-A 14/17→16/17 —— 风险面稳健,Track-A 改善;未动 module 代码。

⑦ **当前结果** — PEAD post-fix verdict **GREEN**:MaxDD -7.92%(远在
风险上限内),2x-cost robust,Track-A 16/17(pre-fix 14/17,修复后
改善 +2 gate)。overall 仍 FAIL 但 PEAD 本就 evidence-only、frozen
即 14/17;失败 gate 是 aggregate excess vs SPY/QQQ(alpha 非风控)。

⑧ **剩余风险** — baseline per-validation-year MaxDD 字段未补;R0 收口
(verdict 汇总 + §6.4 核对)未做。

⑨ **下一轮建议** — Round 8 = R0 收口:补 baseline per-year MaxDD,
写 R0 收口节(4 候选 verdict 汇总 + §6.4 acceptance),关闭 R0 → P0。

⑩ **TODO** — [x] driver [x] baseline train-only/diagnostic/stress
[x] cycle06 [x] cycle08 [x] PEAD · [ ] baseline per-year MaxDD
[ ] R0 收口 · [ ] P0-P6。

⑪ **commit** — `de2a55e`(主)。

## Round 8 — R0 收口:re-risk pack 4 候选交付 + acceptance

**时间**: 2026-05-21 · **主 commit**: `62ace66` · **测试基线**: 3864
(收口文档轮,无代码改动)

① **当前阶段** — Round 8 / Workstream R0 / 收口。

② **本轮目标** — 关闭 R0:写收口节(verdict 汇总 + §6.4 acceptance
+ R0-level 发现)。

③ **为什么先做它** — R0 四候选 Round 1-7 已全交付;§12.4 R0 是
P0-P6 硬前置,须正式关闭。

④ **做了什么** — 写 `rerisk-pack.md` §5(5.1 七行 verdict 汇总 / 5.2
§6.4 acceptance 8 条全 ✅ / 5.3 R0-level 4 发现 / 5.4 baseline per-year
不单列的决定 / 5.5 R0 CLOSED)+ 更新进度表。

⑤ **改了哪些文件** — `docs/memos/20260521-rerisk-pack.md`。

⑥ **跑了哪些测试 + 结果** — 收口文档轮,无代码无测试;机读 pack
已含全 7 行(Round 1-7 driver 产出)。

⑦ **当前结果** — **R0 CLOSED**。R0-level 发现:① baseline regime-
fragile 非全局损坏;② 风险面 post-fix 稳定无新回归;③ 所有 RED/FAIL
落在 alpha gate(vs-SPY)非风控 → binding bottleneck = alpha/
construction;④ cycle08 最稳健、cycle06 frozen PASS 不复现。

⑧ **剩余风险** — cycle06 Track-A PASS→FAIL 的 forward 候选地位含义
留 R0 外用户复核;baseline per-year MaxDD 未单列(§5.4 决定)。

⑨ **下一轮建议** — Round 9 = Package P0(source contracts + 环境
floor):confirm xgboost/lightgbm import、建 `config/ml_sources.yaml`
+ PIT 契约、写 ml-source-contracts memo + ml_env_floor json。

⑩ **TODO** — [x] R0 全 7 行 [x] R0 收口 → **R0 CLOSED** ·
[ ] P0 [ ] P1 [ ] P2 [ ] P3 [ ] P4 [ ] P5 [ ] P6。

⑪ **commit** — `62ace66`(主)。

<!-- Round 9 起在此行下方追加 -->
