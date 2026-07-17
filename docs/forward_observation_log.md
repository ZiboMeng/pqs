# Forward OOS Observation Log

Per-day record of the forward observation ritual triggered by user
signal "new daily data has arrived". Append-only, one entry per
day per ritual run. The manifest files
(`data/research_candidates/<id>_forward_manifest.json`) are the
canonical record of TD entries; this log is the human-readable
heartbeat showing **when** observations were attempted, what state
the data was in, and what got appended.

Workflow: `docs/prd/20260426-forward_oos_runner_prd.md` + memory
`feedback_forward_observation_ritual.md`.

Entry format:

```
## YYYY-MM-DD (UTC)
- data_state: <SPY latest date / how many syms behind>
- RCMv1: <can_append? appended N TDs (latest TD<NNN> @ date) or no-op>
- Cand-2: <same>
- notes: <source_mix changes / readiness flags / anomalies>
```

---

## 2026-04-26 (UTC) — initial state pre-ritual

State at end of R-fwd-1 setup + post-MVP audit fixes (commit
`3aa3866` and prior). NOT a ritual run — recorded here as the
baseline before daily observation begins:

- data_state: SPY latest 2026-04-24; all 78 universe syms at 2026-04-24
- RCMv1: TD001 @ 2026-04-24 / cum_ret=0.00% / source_mix=True
  (start_date=2026-04-24, n_runs=1, status=in_progress)
- Cand-2: TD001 @ 2026-04-24 / cum_ret=0.00% / source_mix=True
  (start_date=2026-04-24, n_runs=1, status=in_progress)
- notes: both candidates entered observation mode after timestamp-aware
  start_date fix (commit `04e89b5`); next ritual triggers on user
  signaling new data (expected next trading day = Mon 2026-04-27 close)

---

## 2026-05-15 (UTC) — daily ritual (post-close)

First ritual since the 2026-04-26 baseline. RCMv1 + Cand-2 aborted
2026-04-30; current forward set is the 4 candidates below.

- data_state: SPY latest 2026-05-15 (close $739.17, −1.2% day); 84
  syms fetched post-close via `fetch_data.py --daily-only`
- trial9_diversifier_002: **no-op — status=requires_data_review**
  (halted at TD002 @ 2026-05-14; pre-existing revalidate halt, needs
  separate investigation — NOT resolved by today's ritual)
- cycle08_3f40e3f4ed1a_evidence_v1: appended **TD001 @ 2026-05-15**
  (forward day 1, cum_ret baseline; core_alpha role, evidence stance)
- cycle06_31af04cf2ff9_evidence_v1: appended **TD001 @ 2026-05-15**
  (forward day 1, cum_ret baseline; core_alpha role, evidence stance)
- pead_sue_trial1_evidence_v1: appended **TD001 @ 2026-05-15**
  (forward day 1, all metrics 0% baseline; 287 lifetime signals)
- spy_8otm_bull_put_v1 (options): **TD007** NAV $10,000.00, DD 0.00%,
  0 open positions, cum_pnl $0.00 (SPY $739.17 / VIX 18.43)
- VRP scan: NVDA +7.98±1.90 STABLE-RICH candidate; COIN noisy; AAPL/
  MSFT/GOOG/META/AMD structurally cheap
- notes: cycle06/08 evidence candidates' first observe required adding
  FactorInputContract entries for xsection_rank_63d / trend_tstat_20d /
  ret_2d to bar_hash._FACTOR_REGISTRY (pre-flight gap — should have
  smoke-tested observe before forward-init). trial9_v2 halt to be
  investigated next session.

## 2026-05-18 daily ritual(收盘后)
- fetch_data: ✅ 收盘后(2026-05-18 ~16:46 ET,pre-close 守卫通过,243 日内更新)
- **env caveat**:本会话装 torchvision 连带升 torch2.12+pandas3.0;**先 dry-run smoke 验** cycle06/08 在新环境无 drift/fail-closed(字节 no-op)→ 再真 observe(守 pre/post-smoke 纪律)
- cycle06_31af04cf2ff9_evidence_v1 / cycle08_3f40e3f4ed1a_evidence_v1:**no-new-bar no-op**,今日无新 canonical 日线 → 未写 TD(诚实:非漏,daily 聚合未跟上/idempotent;dry-run==real)
- pead_sue_trial1_evidence_v1(standalone track):✅ 推进,写 manifest 3 TDs + nav 2356 行,forward MaxDD -0.04%(60d -0.04%),lifetime 287 signals/507 trades
- spy_8otm_bull_put_v1(options):✅ **TD008**,SPY $738.65/VIX 17.82,NAV $10,000,DD 0%,0 仓,cum_pnl $0,events=[]
- cumulative_vrp_scan:已跑
- 状态:全候选 healthy;无 fail-closed/无 drift;torch2.12+pandas3.0 下 forward 路径验证正常(加固 60-测回归信心)

## 2026-05-21 daily ritual(收盘后,审计会话内并行)
- fetch_data: ✅ 243 更新(daily + 60m/30m/15m,收盘后)
- **pre-observe smoke**:cycle06/08 先 `observe --dry-run` 验 runtime canonical hash → 无 drift / 无 halt / 无 fail-closed(ralph-loop ML 工作未触 factor registry / universe,canonical hash 稳定,符合预期)
- cycle06_31af04cf2ff9_evidence_v1:✅ **TD001-003**(2026-05-19/20/21),cum_ret **+3.22%**,vs_spy **+1.99%**,vs_qqq +1.37%,max_dd 0.00%
- cycle08_3f40e3f4ed1a_evidence_v1:✅ **TD001-003**,cum_ret **-0.74%**,vs_spy -1.96%,vs_qqq -2.59%,max_dd -0.74%
- pead_sue_trial1_evidence_v1(standalone track):✅ 4 TDs,forward Sharpe +10.03(年化;tiny-NAV evidence 轨,数值放大正常),forward MaxDD -0.18%(60d -0.18%),lifetime 287 signals / 504 trades
- spy_8otm_bull_put_v1(options):✅ **TD009**,SPY $742.72 / VIX 16.76,NAV $10,000,DD 0%,0 仓,cum_pnl $0,events=[]
- simple_baseline_v1:✅ **TD002**(2026-05-21),NAV $9,917.70,regime=risk_on(MTUM $6,648 / TQQQ $2,924 / cash $346)
- chart_native_s1_evidence_v1:⚠ **observe FAILED** —— `observe_chart_native_evidence.py` import `_frozen_imagenet_features` 失败(`run_chart_native_l3_track_a` 已无该符号)。**pre-existing 断裂,非本审计/ralph-loop 造成**(ML 工作未触 chart_native 路径);该候选本就带 leakage caveat、evidence_only。observe 脚本 stale import 需单独修,记入 TODO。
- 状态:5/6 候选 healthy 推进、无 drift / 无 halt;chart_native observe 脚本 stale-import 待修。

## 2026-06-17 daily ritual(收盘后,会话内手动触发;距上次 05-21 隔 ~4 周)
- fetch_data: ✅ NYSE 17:39 EDT 收盘后,243 更新(daily + 60m/30m/15m);bar-level 完整性 smoke 通过(SPY/QQQ/MTUM/TQQQ 均到 2026-06-17,无周末行)
- ⚠ **cycle06 / cycle08 = requires_data_review HALT(data-revision invalidated)** —— observe `--dry-run` CLI 误报 "no new bars",实为 revalidate fail-closed(已实测确认:`_resolve_dates_to_observe` 返回 18 个新 TD 但被 reval halt 拦在前面)。根因:05-21→06-17 期间 yfinance 对已记录 TD(05-19/20/21)做**回溯修正**(几乎确定为除息):
  - cycle06:TD003 invalidated,E1 NAV 16.05 bps(>10bps),raw drift 0.44%;修正符号 AAPL/COST/GS/LRCX/TQQQ/TXN/VLUE
  - cycle08:TD003 invalidated,E1 NAV 26.09 bps + E5 raw drift 0.568%(>0.5%);修正符号 AMZN/BKNG/COST/MSFT/OXY/TQQQ/TXN/UNH
  - **未写盘(dry-run),manifest 仍 in_progress,未污染。** 是否 `decide()` 清 halt + 重 observe 18 TD = 留给用户决策(pause-before-commit 纪律),本轮不自动清。
  - 附带发现(记 TODO):dry-run 模式下 reval halt 被 CLI 打印成 "no new bars (idempotent no-op)",reporting 误导,应区分 halt vs 真 no-op。
- pead_sue_trial1_evidence_v1(standalone track,不经 v2.1 materiality gate):✅ **TD004**(forward day 23),cum_ret **+5.32%**,vs SPY **+5.08%**(SPY +0.24%),vs QQQ +3.40%,Sharpe +7.86(年化;tiny-NAV evidence 轨放大正常),MaxDD -0.34%(60d -0.34%),lifetime 287 signals / 514 trades
- simple_baseline_v1:✅ **TD003**(2026-06-17),NAV **$10,514.46**(+5.1%),regime=risk_on(MTUM $7,222 / TQQQ $3,102 / BIL $0 / cash $191;VIX 18.44,QQQ 722.51 > SMA200 626.87)
- spy_8otm_bull_put_v1(options):✅ **TD010**,SPY $740.96 / VIX 18.44,NAV $10,000,DD 0%,0 仓,cum_pnl $0,events=[](无 qualifying entry,与历史一致)
- cumulative_vrp_scan:✅ N=10 快照;NVDA mean +5.87±5.18(high-but-noisy→avoid),COIN/TSLA neutral,AAPL/MSFT/GOOG/META/AMD structurally cheap(don't sell);无可操作信号
- chart_native_s1_evidence_v1:⏭ 跳过(observe 脚本 stale-import 未修,见 05-21 条;evidence_only + leakage caveat)
- trial9_diversifier_002:⏭ 跳过(completed_fail / RETIRED,仅 forensic)
- 状态:pead / simple_baseline / options / VRP = 4 健康推进;**cycle06 + cycle08 = data-revision halt 待用户决策**(materiality gate 正确 fail-closed)。

### 2026-06-17 cycle06/08 halt RESOLUTION(同日,用户 go A)
- **诚实纠正**:上方"benign 除息修正"措辞**错**。逐 cell 验证(option 2)实测:只有 **05-21 最后一根 frontier bar** 变动(05-19/05-20 byte-stable,0 cell);05-21 open+close 按同一 per-symbol 因子等比缩放;无 split;幅度 -0.08%~-0.57%(GS/VLUE/BKNG/OXY/UNH)。除息会动 ex-date 前所有日 → **排除除息**。本质 = **raw frontier 最后一根 bar 的 preliminary→final 精修**(CLAUDE.md 明确 dividends 不入 adjustment,仅 split read-time cascade)。良性、非损坏。
- **机制纠正**:原拟"decide/recover 清 halt"路径不存在 —— recover() 仅在 drift 在当前 policy 下不再 invalidated 时清,但本 drift 仍 >E1(实测 recover raise);contract 无"接受良性修正后继续"按钮(有意设计)。
- **resolution = option A(用户 explicit-go 2026-06-17)**:程序化 `runner.init(overwrite=True, candidate_role=CandidateRole.core_alpha, start_date='2026-05-19')` 重锚到 final 数据 → re-observe。**metadata 全保住**:role=core_alpha、evidence_class=forward_oos、cadence[10,20,40,60]/weekly、SPY/QQQ、universe=主 yaml。旧 manifest 备份 /tmp + git-tracked 可回溯。
- **cycle06**:✅ TD001-**TD021**(2026-05-19→06-17),TD021 cum_ret **+19.86%** / vs SPY **+18.87%** / vs QQQ +16.87% / MaxDD **-9.18%**(峰值 TD019 +23% 后回落 → 高 beta 高波动,记录非 verdict)
- **cycle08**:✅ TD001-**TD021**,TD021 cum_ret **+4.98%** / vs SPY **+3.99%** / vs QQQ +1.98% / MaxDD **-11.05%**
- 重锚后验证:两候选 status=in_progress、**data_revision_events=none**、dry-run observe = 真幂等 no-op(明天不会再 halt)。
- **TD20 milestone**:n_runs=21 跨过 TD20。attention_check.py = diversifier-scoped(residual-corr vs anchors / 非股暴露 / diversifier maxdd soft-warn),对 core_alpha cycle06/08 不适用(默认 anchors 是 retired RCMv1/Cand-2,强跑产 mismatched 噪声;TD60 verdict 需 n≥60)→ **未强跑误导报告**;core_alpha TD20 读数 = 上述 forward 指标。
- 全程 sealed 2026 未读;无 silent invariant change。

### 2026-06-17 forward 构建一致性修复(cap-aware;cycle06/08 第二次 re-init)
- **发现(实测铁证)**:forward observe 一直用 naive top-N 等权(`runner.py` `_composite_to_target_weights(top_n)`),**不读候选 spec 的 `construction` 块** —— 而 cycle06/08 的 frozen spec 声明 `cap_aware_cross_asset`(equities≤70%,cycle06 weekly / cycle08 monthly),Track-A 验的也是 cap-aware(`cycle06_track_a_eval.py:121-139`)。铁证:上一次 re-init 后 cycle06 持仓 = 10 股 ×0.10 = **100% 股票**,违反 70% cap。→ **Track-A↔forward 构建不一致,违反 backtest-execution consistency 不变量**。
- **修复**:`runner.py` 新增 `_build_forward_target_weights(spec, composite)`,读 `spec.extras["construction"]`:cap_aware/cap_aware_cross_asset → 复刻 Track-A 的 `topn_signals_with_caps`(同 cluster_map / caps / cadence);无 construction 块 → naive 退回(RCMv1/Cand-2/trial9 **bit-identical**)。单测 `test_build_forward_target_weights_respects_caps_and_falls_back` + TODO-1 套件全绿。
- **cycle06/08 第二次 re-init + re-observe(cap-aware,metadata 全保住)**,对比 naive→cap-aware:

  | | naive(旧/错) | cap-aware(新/对) |
  |---|---|---|
  | cycle06 TD21 vs SPY | +18.87% | **+2.63%** |
  | cycle06 MaxDD | -9.18% | **-3.53%** |
  | cycle08 TD21 vs SPY | +3.99% | **+1.20%** |
  | cycle08 MaxDD | -11.05% | **-5.01%** |

- 验证 held weights 现尊重 cap:cycle06 TD21 = 70% 股 + 10% 债(TLT)+ 20% 现金(BIL/SHV),**无杠杆 ETF**(TQQQ/SOXL 不在 cluster_map,与 Track-A 一致);cycle08 = 70% 股 + 10% 金(GLD)+ 20% 债(TLT/SHY)。两者 in_progress。
- **诚实结论**:naive 的 +18.87% vs SPY 是杠杆 ETF 超配 artifact,非被验证策略的成色;cap-aware 后收益/回撤大降但**仍正向跑赢 SPY**(信号在受约束构建下温和有效)。这才是与 Track-A 一致的诚实主线证据。
- 旧(naive)manifest 备份 /tmp `*_pre_capfix_20260617.json.bak`;sealed 2026 未读。

### 2026-06-29 cycle06/08 第三次 re-init —— halt 循环根因修复(track_per_cell=True)+ total-return basis
- **背景**:06-25 daily ritual,cycle06/08 又 HALT(requires_data_review),recover() 清不掉。这是 06-17 re-init 后**第二次**同类 halt → 怀疑 re-init 是治标跑步机,做只读诊断。
- **根因(已量化,非数据损坏)**:halt 由 `track_signal_input_per_cell=False`(spec 默认)的 **Blocker-2 fail-closed** 驱动 —— per_cell_digest 为空 → revalidate **证不了** signal_input diff 在 execution_nav 锚定 cell 内 → 不管漂移多小都保守 invalidate。实测全部 21 run **n_revised_cells=0、最大 close 漂移 0.00158%**(亚 bp,yfinance 尾部 bar preliminary→final 末位精修)、NAV impact=null、无 sign flip。**re-init 只把 baseline hash 清零,下次 fetch yfinance 再改末位 → 必再 halt(06-17→06-25 已 empirically 验证循环)**。
- **修复(用户 explicit-go 2026-06-29)**:给 cycle06/08 spec 加 `evidence_config.track_signal_input_per_cell: true`(观察期配置,非策略定义字段;feature_set/transforms/composite_rule/construction 全不变)。开启后 observe 在 TD-write 时写 per_cell_digest → revalidate 能 per-attribute 归因,亚 bp in-ring 修订降级 flagged_only 而非 invalidated。**这是打破 halt 循环的根因修复,非放松 policy**(给引擎它需要的 per-cell 数据做精确判定;Blocker-2 对其它候选保护不动)。
- **同时**:本次 re-init 落在已提交的 `6a8448a`(forward observe/recover 改用 adjusted+total-return+drop_symbols,与 Track-A 逐位一致)basis 上 —— forward NAV 现与 Track-A 价格基准一致(此前 raw split-unadjusted 默默偏离)。
- **re-init #3 + re-observe(metadata 全保住:role=core_alpha、evidence_class=forward_oos、start=2026-05-19、SPY/QQQ、cadence[10,20,40,60]/weekly)**,窗口 TD001-**TD028**(05-19→06-29,较 06-17 多 7 TD):

  | | cap-aware(06-17, raw basis, TD21) | 本次(06-29, total-return basis, TD28) |
  |---|---|---|
  | cycle06 vs SPY | +2.63% | **+4.64%** (cum_ret +5.63%, MaxDD -3.99%, Sharpe 1.93) |
  | cycle08 vs SPY | +1.20% | **+6.15%** (cum_ret +7.14%, MaxDD -6.87%, Sharpe 2.00) |

  (差异 = +7 TD 窗口 + total-return 复权;两者仍正向跑赢 SPY,vs QQQ 诊断 +2.42%/+3.93%。)
- **验证**:两候选 status=in_progress、**per_cell_digest 已写入(79 cells/TD)**、**data_revision_events=0**(无 halt)、role=core_alpha。source_mix=True(yfinance frontier vs polygon canonical,readiness 已 flag,预期)。
- 旧(cap-aware/raw)manifest 备份 `*_forward_manifest.preReinit_2026-06-29.json`(git-tracked 可回溯);sealed 2026 未读;无 silent invariant change。
- **预期**:下次新数据来,亚 bp 尾部修订将走 flagged_only 而非 halt(track_per_cell=True 生效)。若仍有 `out-of-ring revision (no anchor)` 类触发(另一路径),再据实判读。

#### 2026-06-30 补:per-cell digest 存储 offload(sidecar parquet)—— track_per_cell 的可持续化
- **发现的阻断问题**:track_per_cell=True 开启后,signal_input 的 per_cell_digest 是 79×252 全网格(~20K cells/TD),且 revalidate 对**每个**历史 TD 重比对(不能只留最近),28-TD inline 进 JSON → cycle06 **47MB** / cycle08 **69MB**。GitHub 单文件 >100MB 硬拒绝,60-TD soak 必撞墙;每次 observe 重写整文件 → git 历史爆。**未 push,先停。**
- **根因量化**:膨胀 99.7% 来自 signal_input;exec_nav(~800 cells 总)/benchmark(~60)极小。digest 值本身已最优(8-char close-only)。
- **修复(用户 go,sidecar 方案)**:新增 `core/research/forward/digest_sidecar.py` + 改 `manifest_io.py` 序列化层 —— save 时把 signal_input per_cell_digest offload 进 zstd parquet sidecar(`*_forward_manifest.digests.parquet`)、JSON 写精简版;load 时回填。**in-memory 模型 + revalidate/runner 逻辑零改动**。exec/bench digest 保持 inline(小)→ **track_per_cell=False 的 legacy 候选(RCMv1/Cand-2/trial9/pead)与旧代码逐位一致、不产生 sidecar**。
- **效果**:cycle06 47MB→**2.6MB json + 1.2MB parquet**;cycle08 69MB→**2.0MB + 1.8MB**(~20x)。sidecar = revision 检测快照(不可由当前数据复现)故 **git-track**。
- **验证**:① round-trip full model_dump 逐位相等(569,604 cells);② legacy 新 save == 旧代码 dump 逐位一致、无 sidecar;③ `observe --dry-run` 两候选 no-op 不 halt(load 回填 → revalidate 正常);④ forward 测试套件 **83 passed**(runner 54 / recover 7 / readiness 4 / backfill 8 / v2_integration 10)。
- 转换后 cycle06/08 NAV 与上节一致(转换仅动序列化,不动数据)。

### 2026-07-08 cycle06/08 observe → settle-window 根因修复(track_per_cell 生效但暴露第二路径)+ re-init #4
- **daily ritual**:fetch(243 更新,frontier 07-08)后 observe cycle06/08 → **又 HALT**(requires_data_review)。但与 06-25 不同:`revised_symbols` 是具体 18/17 个 symbol(非空),`affected_scopes` 含 execution_nav,**E1 NAV 实际影响 cycle06 22.4 / cycle08 20.9 bps**、n_revised_cells 32/29。**track_per_cell=True 生效**——精确归因,不再是空 digest 假 halt。
- **只读诊断(决定性)**:recover 枚举的 revised cell **全部日期 = 2026-06-29**(= re-init#3 的 frontier 尾 bar)。distributions.parquet 未动(mtime 05-19)、06-29 raw==total_return → **不是分红/total-return artifact,是 yfinance 直接改了 06-29 raw bar**(单 cell max 0.368%,组合 ~22bps)。
- **根本洞察**:修订全在**上次尾 bar** = yfinance「最新几根 preliminary,几天后终化」规律 → **每次 observe 必 halt**(本次新 frontier 07-08 过几天必被修订)。re-init 是跑步机(06-17→07-08 已印证)。
- **根因修复(用户 go 1,memo `docs/memos/20260708-forward_settle_window_decision.md`)= settle-window**:最近 N 交易日的 TD 为 **provisional**,每次 observe 从 manifest **drop 掉 → 由 append loop 从当前数据重算**(NAV+hash 刷新),**不参与 revision 判定**;settled(≥N TD 老)历史仍严格 fail-closed。改 `CheckpointCadence.settle_window_trading_days`(schema 默认 0=legacy;RECOMMENDED 10)+ `_drop_provisional_tail` helper + observe() drop-before-revalidate + CLI `--settle-window`。**revalidate 内部零改动**;init 默认 0 → 现有 manifest/测试 byte-identical。11 新单测 + runner 54 + recover 7 + v2 halt 2 全绿。
- **re-init #4(settle_window=10,metadata 全保住)+ observe → 无 halt**,TD001-**TD034**(05-19→07-08),status=in_progress,revision_events=0,`observe --dry-run` exit 0 no-op。
- **历史 NAV 稳定性核实**:05-26/06-15 逐位 == re-init#3;06-29 微调 +5.63%→+5.53%(~10bps = 那次 finalized 修订被吸收,不再 halt)→ re-derivation 未污染历史。
- **⚠ 市场结果(如实记录,非 artifact)**:cycle06/08 早 7 月给回全部超额并转跑输 SPY。frontier 轨迹 cycle06:06-30 见顶 +6.42%(vs SPY +4.64%)→ 07-08 **+0.06%(vs SPY -1.54%)**,MaxDD -7.27%;cycle08:06-30 +8.65% → 07-08 **-0.18%(vs SPY -1.77%)**,MaxDD -8.13%。属 forward evidence 如实反映(防御/rotation sleeve 早 7 月跑输市场反弹),TD60 verdict 前继续观察。
- 旧 manifest 备份 `*.preReinit_2026-07-08.json`;sealed 2026 未读;无 silent invariant change。
- **预期**:settle-window 生效后,frontier 尾 bar 的 preliminary→final 修订将被 re-derive 吸收,不再 halt。若修订落在 >10 TD 的 settled 历史(罕见),仍会严格 halt(正确)。

## 2026-07-17 daily ritual(距上次 07-08 隔 ~9 天)
- **时点纪律**:触发时 NYSE 未收盘(14:58 EDT),`fetch_data.py` 按设计整体拒绝(避免今日 partial bar 落盘)。起后台任务 sleep 到 16:17 EDT 收盘后自动 fetch → 243 更新,daily/60m/30m/15m 全到 **2026-07-17**;bar-level smoke 通过(SPY/QQQ/MTUM/TQQQ/AAPL/GLD/TLT 均到 07-17,无周末尾行)。未 override,未落 partial。
- **pead_sue_trial1_evidence_v1**(独立轨):✅ **TD006**(forward day 43),cum_ret **+5.28%**,vs SPY **+4.73%**(SPY +0.56%),vs QQQ +7.20%,Sharpe +5.39,MaxDD -0.34%。lifetime 287 signals / 514 trades。健康。
- **simple_baseline_v1**:✅ **TD004**(2026-07-17),NAV **$9,538.04**(自 06-17 $10,514 回落 ~9.3%,MTUM $6,646 / TQQQ $2,836 拖累),regime=risk_on(VIX 18.80,QQQ 695.33 > SMA200 639.53)。
- **spy_8otm_bull_put_v1**(options):✅ **TD012**,SPY $743.29 / VIX 18.80,NAV $10,000,DD 0%,0 仓,cum_pnl $0,events=[](无 qualifying entry,与历史一致)。
- **cumulative_vrp_scan**:✅ N=12 快照;COIN +5.94±7.76 / NVDA +4.50±6.13 = high-but-noisy(avoid);AAPL/MSFT/GOOG/META/AMD structurally cheap(don't sell);无可操作信号。
- **chart_native_s1_evidence_v1**:⏭ 跳过(observe 脚本 stale-import 未修 + evidence_only + leakage caveat)。
- **trial9_diversifier_002**:⏭ 跳过(completed_fail / RETIRED,仅 forensic)。

### 2026-07-17 ⚠ cycle06/08 = config_drift HALT(pause-before-commit,未 auto-resolve)
- **现象**:cycle06/08 observe 均 HALT `requires_data_review`,message 带 "config drift halt-class active"。readiness 显示 7 个新 TD(07-09→07-17)可 append,但被 config-drift 拦在 append 前。
- **诊断(只读,决定性)**:
  - halt message `revised_symbols=n/a` → **无 data revision 被 invalidate**;settle_window=10 正确吸收了尾 bar preliminary→final 修订(第二根因路径已闭环,本次未触发)。
  - halt **纯由 config_drift(severity=halt)触发**。逐 source 比对冻结(2026-07-08T22:07)vs 当前 hash:**仅 `universe_hash` 漂移**(4ba86629 vs 7a02437a);factor_registry / research_mask / risk_config / system 四项 **hash 全 same**。
  - **根因 = 本人 audit 收口 commit `e287201`(P0-1 SQQQ blacklist)改了 `config/universe.yaml`**:往 blacklist 加了 inverse ETF(SPXU/SPXS/SDS/TZA)+ 注释。该 commit 自验 "executable unchanged bit-for-bit (79)" —— 这些 inverse ETF 本就不在 79 基础池,**cycle06/08 可选 universe 逐位不变**,只是 blacklist YAML 文本变 → universe_hash 变。
  - `risk.yaml` commit `21f43a2` 只加注释到 dead key → risk_config_hash **未变**(算的是解析值,注释被忽略),不构成 drift。
  - **结论**:benign config drift,fail-closed 正确触发,但对这两候选**可证明无实质影响**(executable 79 不变 + factor_registry 不变)。
- **纪律留痕**:这正是 `feedback_pre_post_audit_must_smoke_observe` 警告的场景("改 universe.yaml 立刻 check 活跃 forward 候选 drift")—— **audit 收口时漏跑 observe smoke,本次才暴露**。诚实记录,非隐瞒。
- **处置 = 未 auto-resolve**(ritual 纪律:config_drift halt = pause-before-commit,surface 给用户)。cycle06/08 manifest 留 dirty(status=requires_data_review + config_drift_event 落在最新 TD,**未 append 新 TD**,仍 31 settled runs),**未 commit**。resolution 选项待用户拍板:
  - **(A) backfill_config_snapshot.py --force + 清 halt**:re-snapshot universe_hash 到当前 + migration_note 留痕("assert unchanged-in-effect"),NAV 历史零改动。最轻、最诚实(保留 audit 信号)。
  - **(B) re-init #5(overwrite=True)**:re-anchor config + re-derive NAV;NAV 应逐位不变(同数据同 executable universe),metadata 保住。重但已验证 4 次。
  - 我倾向 **(A)**:改动可证明 benign,re-snapshot + migration_note 比 re-init 更轻且保留"config 于此日重锚"的审计痕迹。
- sealed 2026 未读;无 silent invariant change。
