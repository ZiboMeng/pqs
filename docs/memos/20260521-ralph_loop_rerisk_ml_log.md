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

## Round 9 — P0:环境 floor + ml_sources.yaml source-tier 契约

**时间**: 2026-05-21 · **主 commit**: `75032d1` · **测试基线**: 3864
(纯 config,无代码改动)

① **当前阶段** — Round 9 / Package P0 / 第一步。

② **本轮目标** — 确认 xgboost/lightgbm 可 import;建
`config/ml_sources.yaml`(6 mandatory + 1 optional source tier +
PIT 契约 + driver-contract)。

③ **为什么先做它** — R0 CLOSED;§12.4 P0 是 P1-P6 硬前置。

④ **做了什么** — 环境 floor:xgboost 3.2.0 / lightgbm 4.6.0 / numpy
2.4.4 / pandas 3.0.2 / sklearn 1.8.0 / scipy 1.17.1 全 importable
→ `data/audit/ml_env_floor_20260521.json`。建 `config/ml_sources.yaml`
(全局 PIT rules + 7 tier A-G + driver_contract)。

⑤ **改了哪些文件** — `config/ml_sources.yaml`(新)/
`data/audit/ml_env_floor_20260521.json`(新)。

⑥ **跑了哪些测试 + 结果** — ml_sources.yaml safe_load 通过(7 tier,
6 mandatory/1 optional);环境 import 检查 exit 0;纯 config 无回归。

⑦ **当前结果** — P0 三件套出两件:env_floor json(gate xgboost+
lightgbm importable ✅)+ ml_sources.yaml(6 mandatory tier 全有
declared contract ✅)。

⑧ **剩余风险** — P0 memo 未写;P0 gate "no driver source-agnostic"
是前瞻条款(P2+ driver 落实);B/C/D/E/F tier status=partial(gaps
已标注)。

⑨ **下一轮建议** — Round 10 = P0 收口:写
`docs/memos/20260521-ml-source-contracts.md`,核对 P0 §12.3 gate
三条,关闭 P0 → P1。

⑩ **TODO** — [x] R0 CLOSED [x] P0 环境 floor + ml_sources.yaml ·
[ ] P0 memo + 收口 [ ] P1 [ ] P2-P6。

⑪ **commit** — `75032d1`(主)。

## Round 10 — P0 收口:ML source-contracts memo + gate 核对

**时间**: 2026-05-21 · **主 commit**: `505798d` · **测试基线**: 3864
(收口文档轮)

① **当前阶段** — Round 10 / Package P0 / 收口。

② **本轮目标** — 写 P0 source-contracts memo,核对 §12.3 gate,关闭 P0。

③ **为什么先做它** — Round 9 出 P0 两件套;memo 是第三件产物,P0
须关闭才能进 P1。

④ **做了什么** — 写 `docs/memos/20260521-ml-source-contracts.md`
(环境 floor / 6+1 tier / PIT rules / gap 表 / driver 契约 / §12.3
gate 逐条核对)。

⑤ **改了哪些文件** — `docs/memos/20260521-ml-source-contracts.md`(新)。

⑥ **跑了哪些测试 + 结果** — 收口文档轮,无代码无测试;机读产物
Round 9 在案。

⑦ **当前结果** — **P0 CLOSED**。§12.3 gate 三条全过:① 6/6 mandatory
tier 有 declared contract;② xgboost+lightgbm importable;③ driver
source_tiers 契约已建(P2 起强制,当前无 ML 训练 driver 无违规)。

⑧ **剩余风险** — B/C/D/E/F 五 tier status=partial,gap 表已列待闭项
(随 P2-P4 闭合);tier A 是唯一 present → P2 从 tier A 起步。

⑨ **下一轮建议** — Round 11 = Package P1(canonical labels + split
discipline):扩 `config/ml_labeling.yaml`(canonical label-mode
schema);purge+embargo 默认在 ML driver override(§8.2 + 决策 ④,
不改共享 temporal_split*.yaml)。

⑩ **TODO** — [x] R0 CLOSED [x] P0 CLOSED · [ ] P1 [ ] P2-P6。

⑪ **commit** — `505798d`(主)。

## Round 11 — P1:expand ml_labeling.yaml canonical label-mode schema

**时间**: 2026-05-21 · **主 commit**: `1043d5c` · **测试基线**: 3864
(纯 config 扩展)

① **当前阶段** — Round 11 / Package P1 / 第一步。

② **本轮目标** — 把 `config/ml_labeling.yaml` 扩成 canonical task +
label-mode 契约(PRD §7.2)。

③ **为什么先做它** — P0 CLOSED;P1 label 契约 schema 须先定,后续
实现/测试/wiring 依赖它。

④ **做了什么** — 扩 `ml_labeling.yaml`:保留 4 legacy key verbatim
(不破 reader),additive 加 `default_task` + `label_modes`(5 模式:
residual_rank/_quantile = PRIMARY,binary/binary_after_cost/
triple_barrier = SECONDARY,各带 source_tiers 对接 P0)+
`default_label_mode` + §7.4 产品规则。

⑤ **改了哪些文件** — `config/ml_labeling.yaml`(schema_version 1→2)。

⑥ **跑了哪些测试 + 结果** — yaml safe_load 通过;R3 核对 4 legacy
key 字节级完好 → 现有 reader 无回归;纯 config 无 module 改动。

⑦ **当前结果** — P1 canonical label-mode 契约 schema 就位(5 模式 +
产品规则:residual-rank 默认,binary 降级 sidecar-only)。

⑧ **剩余风险** — label 模式的**实现**(residualized-rank 计算、
cost-aware binary helper)未做;purge/embargo driver-override 未做;
P1 §12.3 gate + smoke json + 单测待后续轮。

⑨ **下一轮建议** — Round 12 = 实现 residualized-rank/quantile label
(canonical 主模式,复用既有 labeling 原语)+ deterministic smoke +
单测。

⑩ **TODO** — [x] R0/P0 CLOSED [x] P1 label-mode schema ·
[ ] P1 label 实现+单测 [ ] P1 cost-aware binary + purge/embargo
override [ ] P1 收口 · [ ] P2-P6。

⑪ **commit** — `1043d5c`(主)。

## Round 12 — P1:residualized cross-sectional rank/quantile label 实现

**时间**: 2026-05-21 · **主 commit**: `8392b67` · **测试基线**: 3864
+ 8 新(labels.py additive,research/ml 131 passed)

① **当前阶段** — Round 12 / Package P1 / label 实现。

② **本轮目标** — 实现 canonical 主 label 模式 cross_sectional_
residual_rank / _quantile(PRD §7.2)。

③ **为什么先做它** — Round 11 定了 schema;§7.4 指定 residual-rank
为默认目标 → 先实现主模式。

④ **做了什么** — `core/research/ml/labels.py` 加(additive)
`_rolling_market_beta` + `make_residualized_rank_labels`(residual =
fwd_ret − beta·fwd_mkt,per-bar 截面 rank)+
`make_residualized_quantile_labels`(分桶)。test_labels.py +8 单测。

⑤ **改了哪些文件** — `core/research/ml/labels.py`(+3 函数)/
`tests/unit/research/ml/test_labels.py`(+8 测试)。

⑥ **跑了哪些测试 + 结果** — test_labels.py 32 passed;research/ml
全目录 131 passed(labels.py additive 无 sibling 回归);R3 核对:
「纯market/+idio/-idio」三票断言 residual rank +idio>纯market>-idio
逐 bar 成立 → 残差化语义正确。

⑦ **当前结果** — P1 canonical 主 label 模式(residual_rank/_quantile,
market 残差化)已实现 + 测试。

⑧ **剩余风险** — 残差化目前仅 vs market(sector 残差化未实现);
cost-aware binary label 未做;purge+embargo driver-override 未做;
P1 §12.3 gate + smoke json 未做。

⑨ **下一轮建议** — Round 13 = cost-aware binary label
(binary_forward_return_after_cost)+ 单测;后 sector 残差化、
purge/embargo override、P1 收口。

⑩ **TODO** — [x] R0/P0 CLOSED [x] P1 schema [x] P1 residual-rank/
quantile label · [ ] cost-aware binary [ ] sector 残差化 +
purge/embargo override [ ] P1 收口 · [ ] P2-P6。

⑪ **commit** — `8392b67`(主)。

## Round 13 — P1:cost-aware binary label

**时间**: 2026-05-21 · **主 commit**: `6511748` · **测试基线**: 3864
+ 13 新(P1 additive,test_sign_classifier 24 passed)

① **当前阶段** — Round 13 / Package P1 / cost-aware binary label。

② **本轮目标** — 实现 binary_forward_return_after_cost(§3.5/§7.2)。

③ **为什么先做它** — §3.5 明确点名:bare-0.0 threshold 把"略正但低于
交易成本"误算 winner。

④ **做了什么** — `sign_classifier.py` 加 `compute_cost_aware_binary_
labels`(threshold=(cost_hurdle+min_edge)/10000,薄封装复用
compute_binary_sign_labels)。+5 单测。

⑤ **改了哪些文件** — `core/research/ml/sign_classifier.py`(+1 函数)/
`tests/unit/research/ml/test_sign_classifier.py`(+5 测试)。

⑥ **跑了哪些测试 + 结果** — test_sign_classifier 24 passed;R3 核对:
X +20bps→0 / Y +60bps→1(40bps hurdle),对照 bare-0.0 X 会是 1 →
§3.5 gap 闭合;additive 无回归。

⑦ **当前结果** — P1 的 5 个 canonical label 模式全部有实现支撑:
residual_rank/_quantile(R12)+ binary(既有)+ binary_after_cost
(本轮)+ triple_barrier(既有 labeling.py)。

⑧ **剩余风险** — sector 残差化未实现;purge+embargo driver-override
未做;P1 §12.3 gate + smoke json 未做。

⑨ **下一轮建议** — Round 14 = purge+embargo driver-override(§8.2 +
决策 ④,不改共享 temporal_split)+ label smoke json;后 P1 §12.3
gate 核对 + P1 收口。

⑩ **TODO** — [x] R0/P0 CLOSED [x] P1 schema/residual-rank/cost-aware
binary · [ ] purge/embargo override + smoke json [ ] P1 收口 ·
[ ] P2-P6。

⑪ **commit** — `6511748`(主)。

## Round 14 — P1:purge+embargo in the ML walk-forward path

**时间**: 2026-05-21 · **主 commit**: `94701cb` · **测试基线**: 3864
+ 17 新(research/ml 140 passed)

① **当前阶段** — Round 14 / Package P1 / purge+embargo override。

② **本轮目标** — ML walk-forward 路径加 purge+embargo gap(§8.2 +
决策 ④:pipeline 内做,不改共享 temporal_split*.yaml)。

③ **为什么先做它** — iter_folds 现无 embargo gap → train 末尾 21d
label 伸进 val 年 = overlapping-label 泄漏。

④ **做了什么** — `pipeline.py`:`WalkForwardConfig` 加 `embargo_days`
(默认 0 = bit-identical);`iter_folds` 把 train_end 回拉
embargo_days 日历日。接两个 sign-classifier walk-forward driver 传
`embargo_days=horizon_days`。test_pipeline +4 单测。

⑤ **改了哪些文件** — `core/research/ml/pipeline.py` /
`dev/scripts/ml/walk_forward_sign_classifier.py` /
`dev/scripts/ml/hyperparam_search_sign_classifier.py` /
`tests/unit/research/ml/test_pipeline.py`。

⑥ **跑了哪些测试 + 结果** — test_pipeline 25 passed;R3:embargo=0
→ train_end 仍 Dec-31(bit-identical),embargo=30 → 回拉、gap≥30d、
strict-chrono 成立、fold 数不变;research/ml 全目录 140 passed 无回归。

⑦ **当前结果** — ML walk-forward 支持 purge+embargo gap;两 driver
默认 embargo=horizon;共享 temporal_split*.yaml 未动(决策 ④)。

⑧ **剩余风险** — embargo 按日历日回拉(传 horizon_days 作日历日偏
保守,不偏泄漏);label smoke json + P1 §12.3 gate + P1 收口未做;
sector 残差化未做。

⑨ **下一轮建议** — Round 15 = label deterministic smoke json + P1
§12.3 gate 核对 + P1 收口。

⑩ **TODO** — [x] R0/P0 CLOSED [x] P1 schema/labels/purge-embargo ·
[ ] P1 smoke json + 收口 · [ ] P2-P6。

⑪ **commit** — `94701cb`(主)。

## Round 15 — P1 收口:label-contract smoke + §12.3 gate(P1 CLOSED)

**时间**: 2026-05-21 · **主 commit**: `f0884aa` · **测试基线**: 3864
+ 17 新(P1 累计)

① **当前阶段** — Round 15 / Package P1 / 收口。

② **本轮目标** — 出 label deterministic smoke,核对 P1 §12.3 gate,
关闭 P1。

③ **为什么先做它** — P1 schema/实现/purge-embargo 已就位;smoke 是
§12.3 第二件产物,P1 须关闭才进 P2。

④ **做了什么** — 新建 `label_contract_smoke.py`(5 canonical 模式各
跑两次验 deterministic → `ml_label_contract_smoke_*.json`);两个
walk-forward driver artifact 显式记 `embargo_days`。

⑤ **改了哪些文件** — `dev/scripts/ml/label_contract_smoke.py`(新)/
`data/audit/ml_label_contract_smoke_20260521T233959Z.json`(新)/
`walk_forward_sign_classifier.py` / `hyperparam_search_sign_classifier.py`。

⑥ **跑了哪些测试 + 结果** — smoke exit 0:5/5 模式
deterministic=True;driver 编辑是 1-line additive 无行为改动。

⑦ **当前结果** — **P1 CLOSED**。§12.3 gate:① label 模式
deterministic ✅(5/5);② walk-forward driver 记 purge/embargo ✅
(artifact 含 embargo_days);③ 禁用 purge 需显式代码改动 ✅,
weighting 半项诚实标注 carry-forward(sample-weight 属后续 package)。

⑧ **剩余风险** — gate 3 weighting 半项延后;sector 残差化未实现
(P1 外 follow-up)。

⑨ **下一轮建议** — Round 16 = Package P2:先核查三套既有 rank-model,
选一套 canonical(不造第四套,§1.5)。

⑩ **TODO** — [x] R0/P0/P1 CLOSED · [ ] P2 ranker baseline
[ ] P3-P6。

⑪ **commit** — `f0884aa`(主)。

## Round 16 — P2:canonical rank-model 决策(不造第四套)

**时间**: 2026-05-21 · **主 commit**: `4b277ce` · **测试基线**: 3864
(核查 + 决策文档)

① **当前阶段** — Round 16 / Package P2 / 第一步。

② **本轮目标** — 核查 §1.5 列的三套 rank-model,选一套 canonical。

③ **为什么先做它** — §1.5 把"选 canonical"列为 P2 §12.3 gate;后续
driver 须建在 canonical 上。

④ **做了什么** — 核查三套:`core/research/ml/{rank_model,xgb_rank_
model}.py`(PRD#4 P4.1,Protocol,§9.0,20 测试,pipeline 全面 import)
/ `core/ml/xgb_ranking.py`(Phase-1.6,near-orphan,只 1 处 import)
/ `core/ml/xgb_alpha.py`(legacy)。核到 `XGBRankerRankModel` 已暴露
`objective`(支持 rank:ndcg)。写决策 memo。

⑤ **改了哪些文件** — `docs/memos/20260521-p2-canonical-rank-model-
decision.md`(新)。

⑥ **跑了哪些测试 + 结果** — 核查+决策文档轮,无代码无测试。

⑦ **当前结果** — **canonical = `core/research/ml/{rank_model,
xgb_rank_model}.py`**(零迁移);`xgb_ranking.py::LambdaRankICModel`
降为 §4.7 A/B 候选;`xgb_alpha.py` legacy 不动。P2 §12.3 gate
"canonical 选定、不造第四套" 满足。

⑧ **剩余风险** — train_ranker/walk_forward_ranker 未建;LightGBM
parity 未建;DSR/PBO 接 ranker selection 未做。

⑨ **下一轮建议** — Round 17 = 建 `train_ranker.py`(canonical
`XGBRankerRankModel(rank:ndcg)` + Linear Pareto-floor;residual-rank
label;walk-forward+embargo;§10.2 artifact 字段)+ smoke。

⑩ **TODO** — [x] R0/P0/P1 CLOSED [x] P2 canonical 决策 ·
[ ] P2 train_ranker/walk_forward_ranker [ ] P2 LightGBM/DSR-PBO/收口
· [ ] P3-P6。

⑪ **commit** — `4b277ce`(主)。

## Round 17 — P2:rank walk-forward 驱动(rank:ndcg + embargo + ndcg-gain 修)

**时间**: 2026-05-21 · **主 commit**: `29402d1` · **测试基线**: 3864
+ 21 新(research/ml 142 passed)

① **当前阶段** — Round 17 / Package P2 / ranker 驱动。

② **本轮目标** — §1.5 核查既有 walk_forward_rank_sign.py;对齐 R16
(rank:ndcg)+ P1(embargo)。

③ **为什么先做它** — R16 选定 canonical;P2 §12.3 要 ≥1 XGBoost
ranker run 端到端。

④ **做了什么** — §1.5 核查:`walk_forward_rank_sign.py` 已是 rank
walk-forward 驱动 → 不另建 `walk_forward_ranker.py`,增强它(objective
默认 rank:ndcg + `--objective` flag + `embargo_days=horizon`)。**smoke
抓出真 bug 并同轮修**:rank:ndcg 在 79-symbol 截面 fold 全 FAIL
(XGBoost 指数 NDCG gain relevance ≤31 上限,within-group rank 到 79
超限)→ 修 `xgb_rank_model.py`:rank:ndcg 时传 `ndcg_exp_gain=False`。

⑤ **改了哪些文件** — `core/research/ml/xgb_rank_model.py` /
`dev/scripts/ml/walk_forward_rank_sign.py` /
`tests/unit/research/ml/test_xgb_rank_model.py`(+2)。

⑥ **跑了哪些测试 + 结果** — test_xgb_rank_model 12 passed;research/ml
142 passed(ndcg_exp_gain 是条件分支,默认 rank:pairwise bit-identical
无回归);R3 smoke:rank walk-forward 2010-2016 → Linear + XGBRanker
both pooled+tradeable **2/2 folds OK**(修复前 0/2);embargo 生效
(train_end 2014-12-26)。

⑦ **当前结果** — canonical rank walk-forward 跑通 rank:ndcg+embargo;
P2 §12.3 "≥1 XGBoost ranker run 端到端" 满足。

⑧ **剩余风险** — LightGBM parity 未建;DSR/PBO 接 ranker selection
未做;residual-rank label 接 rank walk-forward 未做;P2 收口未做。

⑨ **下一轮建议** — Round 18 = LightGBM parity(`LGBMRankerRankModel`
实现同一 RankModelProtocol,接进驱动 model 选项)。

⑩ **TODO** — [x] R0/P0/P1 CLOSED · P2 canonical 决策 [x] P2 rank
walk-forward · [ ] LightGBM parity [ ] DSR-PBO/residual-label/P2 收口
· [ ] P3-P6。

⑪ **commit** — `29402d1`(主)。

## Round 18 — P2:LGBMRankerRankModel(LightGBM parity path)

**时间**: 2026-05-21 · **主 commit**: `8ae92c8` · **测试基线**: 3864
+ 28 新(lgbm+xgb+rank_model 29 passed)

① **当前阶段** — Round 18 / Package P2 / LightGBM parity。

② **本轮目标** — 建 `LGBMRankerRankModel`,实现与 XGBRankerRankModel
同一 `RankModelProtocol`。

③ **为什么先做它** — canonical 决策 memo §4:LightGBM = 同一 Protocol
实现非第四套;P2 §12.3 含 LightGBM parity smoke。

④ **做了什么** — 新建 `core/research/ml/lgbm_rank_model.py`(镜像
XGB 的 fit/predict_rank,`LGBMRanker(objective="lambdarank")`,§9.0
rank∈[0,1])。预解决 group-size>31:0-based 整数 rank + 线性
`label_gain=range(max_group+1)`。scoped 抑制 LightGBM feature-name
warning storm。+7 单测。

⑤ **改了哪些文件** — `core/research/ml/lgbm_rank_model.py`(新)/
`tests/unit/research/ml/test_lgbm_rank_model.py`(新)。

⑥ **跑了哪些测试 + 结果** — test_lgbm_rank_model 7 passed(含
79-symbol large-group lambdarank fit);lgbm+xgb+rank_model 29
passed 无回归;warning storm 已消。

⑦ **当前结果** — LightGBM parity 模型实现+测试就位,与 XGB 同一
Protocol。

⑧ **剩余风险** — 未接进 driver `--model` 选项;LightGBM parity
端到端 smoke 未跑;per-bar glue 与 XGB 重复 ~35 行(共享 helper
后续 refactor)。

⑨ **下一轮建议** — Round 19 = 接 LGBMRankerRankModel 进
walk_forward_rank_sign.py(`--model lgbm`)+ LightGBM parity smoke。

⑩ **TODO** — [x] R0/P0/P1 CLOSED · P2 canonical/rank-wf [x] P2
LightGBM parity 模型 · [ ] LightGBM 接驱动+smoke/DSR-PBO/P2 收口
· [ ] P3-P6。

⑪ **commit** — `8ae92c8`(主)。

## Round 19 — P2:接 LGBMRankerRankModel 进 rank walk-forward 驱动

**时间**: 2026-05-21 · **主 commit**: `418d50c` · **测试基线**: 3864
（仅改 driver）

① **当前阶段** — Round 19 / Package P2 / LightGBM 接驱动。

② **本轮目标** — `LGBMRankerRankModel` 接进 walk_forward_rank_sign.py
`--model` 选项 + LightGBM parity smoke。

③ **为什么先做它** — R18 交付了 LightGBM 模型;P2 §12.3 含 LightGBM
parity smoke。

④ **做了什么** — `--model` 加 `lgbm` + `all`（`both`=linear+xgb 向后
兼容,`all`=三者）;`_build_lgbm_factory`;factories 块加 lgbm 分支。
跑 LightGBM parity smoke。

⑤ **改了哪些文件** — `dev/scripts/ml/walk_forward_rank_sign.py`。

⑥ **跑了哪些测试 + 结果** — `--model lgbm` smoke(2010-2016)exit 0:
LGBMRankerRankModel pooled+tradeable **2/2 folds OK**,embargo 生效;
仅改 driver 不重跑回归(LGBM 模型 R18 已测 7 单测)。

⑦ **当前结果** — P2 §12.3 gate 三项满足:① canonical 选定 ② XGBoost
ranker 端到端 ③ LightGBM parity smoke 端到端。

⑧ **剩余风险** — §12.3 余下:cross-fold 选择须记 trial count + 过
DSR/PBO(§9.6);residual-rank label 接 rank walk-forward 未做;
P2 收口未做。

⑨ **下一轮建议** — Round 20 = P2 §9.6 过拟合控制:ranker 跨
fold/model-family 选择接 DSR/PBO(复用既有 dsr_trial_accounting +
mining_pbo)+ P2 收口。

⑩ **TODO** — [x] R0/P0/P1 CLOSED · P2 canonical/rank-wf/LightGBM ·
[ ] P2 §9.6 DSR/PBO + 收口 · [ ] P3-P6。

⑪ **commit** — `418d50c`(主)。

<!-- Round 20 起在此行下方追加 -->
