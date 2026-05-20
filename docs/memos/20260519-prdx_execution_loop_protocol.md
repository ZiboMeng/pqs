# PRD-X v2 implementation /loop 协议

**用途**: 把以下整段 `【定位】 ... 【硬禁】` 文本作为 `/loop` 的输入,启动 PRD-X 实施。每次 /loop 调用都用**同一段**协议文本(确保跨轮纪律一致)。

**SoT 引用**:
- 主 PRD: `docs/prd/20260519-trigger_threshold_first_rebalance_architecture.md`(v2 post-audit)
- 跨轮 ledger: `docs/memos/20260519-prdx_execution_ledger.md`(本轮新建,SoT)
- 历史背景: `docs/memos/20260518-prd123_execution_ledger.md`(PRD-1/2/3 + Track-A audit cycle DONE)+ `docs/memos/20260519-strategic_close_out_REVISION_post_audit_fix.md`(post-fix data-driven 约束)

---

## /loop 协议(下方整段是要传给 `/loop` 的 input)

```
不间断推进 PRD-X v2 (Trigger/Threshold-First 决策架构) implementation。每轮按此协议:

【定位】先读 docs/memos/20260519-prdx_execution_ledger.md(跨轮 SoT)+ docs/prd/20260519-trigger_threshold_first_rebalance_architecture.md(v2 post-audit 主 PRD,18-issue+3-conflict 全 fold)+ docs/memos/20260519-strategic_close_out_REVISION_post_audit_fix.md(post-fix data-driven 约束:ML 输出走 sign-vote/include-veto,不走 continuous magnitude)+ docs/memos/20260518-prd123_execution_ledger.md(PRD-1/2/3+Track-A 历史)+ git log 最近若干。据账本进度表找"下一个最小可验证步"。锁定顺序(per PRD §0 修订史 #16 logical ordering):**X0(dividend extension)→X1(Protocol schema)→X2(rule trigger + vol-conditional no-trade band)→X4(integrate existing deferred kernel + M11 parity matrix)→X3(true-new partial rebalance / delta-to-trade)→X5(ML sidecar sign-vote only)**。注:§11 numerical 顺序写为 X1-X5 但 §0 logical order 把 X4(integrate-existing,lower risk)放 X3(true-new)前——按 logical order 执行,在 round-1 ledger 留痕此 §11/§0 v2 内部不一致(待 v2.1 patch)。每 phase 含 build round(TDD GREEN)+ acceptance experiment(ran+recorded+verdict+root-cause)。

【执行】小步:一轮一个主目标。可行则 TDD —— 先写测试(RED)再写实现(GREEN)再跑。**复用现有 pattern 不重造**(per PRD §F.1 inventory):signal_driven_runner pattern → decision_driven_runner 扩展(C1)/ 6+1 Strategy + Protocol+GenerateStrategyAdapter(C2)/ bar_store.adjusted_total_return + distributions.parquet + build_distributions_parquet.py(C3)/ SignalStateMachine + DeferredExecutionSchedule + cascade_overlay + tier_overlay + RegimeDetector + KillSwitch + FailureDetector + sr_stops + StressTester + BaseDetector + signal_confirmation_factors + sue_calculator + price_jump_signal。新增模块只写 PRD §F.2 列表中的(`core/research/decision/` + exit-trigger detectors + RiskExitTrigger + event_window detector + regime affinity table + NoTradeBandCalculator + DeltaToTradePolicy + ReviewScheduler + decision_driven_runner)。改 leakage 相关默认走 core/research/label_leakage canonical helper。任何动 canonical chart_native L3 / core acceptance / backtest_engine.run 的改动须 bit-identical 回归验证(后台 run,Bash run_in_background,串行单 GPU)。重 ML/mining/backtest 前先跑 bar-level data-integrity smoke(weekend rows / monotone / sealed-year guard)。长跑用后台,不 strawman-wait。**bg 启动:run_in_background 直接跑目标进程,禁加 nohup/&(R16 root-cause)**。**commit 一律 git commit -F <msgfile>(R11 root-cause)**。模块历史/契约细节进对应 core/*/CONTEXT.md。CLAUDE.md 仅项目级。

【纪律】R1-R4 自审每轮(R3 真跑对比期望永不跳);bug 必 ROOT CAUSE 不 hand-wave;**禁 blanket "X 不行"**(只写"这个 attempt 失败+用了什么+root cause");**禁 over-conservative 砍 scope**(cheap-first 是 sequencing 不是 scope-limiting);**sealed 2026 永不读、守 temporal_split partition**;**strict-chronological walk-forward**(Track-A R1 temporal-leakage 教训,interleaved selector partition + ML 训练 = looking-forward leakage);websearch 仅方法/论文禁市场数据;promotion 只在证伪-evidence-gated,**non-blanket failure verdict**(只 record this attempt failed + 用了什么 + root cause,非"X doesn't work");**§6.4 不变量守护硬绑不放松**:long-only / no-margin / SQQQ blacklist / MaxDD 15-20% / 2008-≤25% / 真 short execution 永禁(P2.4 R14 stub guard 已在);**bit-identical default mode**(cascade_overlay R12 / construction_tier T0 / sample_weight=None 等 precedent pattern);**§9.0 post-audit-fix 约束**:ML 输出严格 sign-vote / include-veto / classifier,**禁 continuous magnitude as size weight**(post-fix A/B FORCED 跨 3 model class 一致 magnitude IC 普世毒)。

【收尾每轮】commit+push(-F 文件;具体文件不用 git add -A)→ 更新 prdx ledger 进度表 + 本轮追加行 → 输出本轮 11-part 式简报(目标 / 做了 / 改了哪些文件 / 跑了什么测试 / 结果 / 新问题 / 剩余风险 / 下一步)。

【停止-等用户(directional)】遇到这些不自决,停下写清选项+我的建议然后结束本轮等用户:
- production_strategy.yaml status 从 "conservative_default" → "active" 是 PRD-X DONE 之后的独立 directional;
- 真 short(P2.4)execution——永不实现除非用户 explicit-go;
- CLAUDE.md invariant 进一步修订(超出 PRD §6.4 已 enumerate 的);
- repo-level 结构 fork / 新 PRD 主轴;
- §13 live gate 任意 hard gate flip(broker / paper soak 标 done);
- 若 X3 / X5 experiment 出现"trigger-first 不劣 cycle06" 显著 FAIL 时,主线归零 vs 重设 trigger params 的方向选择;
- 任何动 CLAUDE.md 1.4 Invariant Constraints 项的提案。

其余 tactical 自决连续推进(参 memory `feedback_autonomous_execution_within_correct_path`)。

【DONE】PRD-X X0-X5 全 phase per-phase AC 达成(build round TDD GREEN + experiment round ran+recorded+verdict+root-cause;若 experiment FAIL 必 scoped non-blanket)+ §12.0 cycle06 baseline regression 通过(trigger-first ≥ cycle06 Sharpe/MaxDD/turnover 容差内)+ post-audit(逐 phase 对照 PRD AC ✅/部分/未做 + 端到端链路跑通 + 依赖 OK + §6.4 不变量全守 + sealed-2026 全程未读 + M11 parity matrix 7 strategy 全过)通过 → 写最终 honest summary memo + 终止 loop(不再续)。注意:**PRD §13 live gate(production_strategy.yaml flip / dividend done / broker seam / paper soak)不是 loop DONE 条件,是 live-readiness 后续独立 directional**。

【硬禁】不自启嵌套 loop / 不 ScheduleWakeup 给自己加戏(loop 机制自管节奏);不 git add -A;不静默改不变量(§6.4 列表外的不变量改动是 directional 停等);不假装完成(做出来≠做透,做出来不验=没做);不读 sealed 2026 任何 query 路径;不用 continuous magnitude as size weight(§9.0 post-audit-fix 约束);不绕过 §6.4 不变量守护任意一条;不对 backtest_engine.run() 主路径做改动(M11 parity 由 signal_driven_runner / decision_driven_runner wrapper pattern 保留)。
```

---

## 配套 ledger 初始化

新建 `docs/memos/20260519-prdx_execution_ledger.md` 作为 cross-round SoT(下方独立文件,见 git commit)。

## 启动方式

复制上方 `【定位】...【硬禁】` 整段(在 ``` ``` 之间),粘贴到 Claude Code 的 prompt 框作为 `/loop <prompt>` 的 input。

或者直接:`/loop <复制上面整段>`

第一轮(Round 1):loop 会按【定位】读 PRDX ledger(空 / 初始化) + PRD-X v2 + history,选 Phase X0 first sub-step 启动(extend `data/ref/distributions.parquet` 覆盖 SPY/QQQ + main equity universe via existing `build_distributions_parquet.py` builder)。

## R3 自审本协议是否完备

- **R1 事实**: 协议引用的 5 个 SoT 文件全部 R3 grep-existence-verified;§F.1 列出的现有模块全部 R3 grep-existence-verified(PRD v2 编写时已 ground)。
- **R2 逻辑**: 锁定顺序按 §0 修订史 #16 logical ordering(integrate-existing 先 / true-new 后);bit-identical default + M11 parity 由 signal_driven_runner wrapper pattern 保留(C1 solution);ML 用 sign-vote 严格约束(§9.0 post-fix 数据)。
- **R3 真跑对比期望**: 每 phase build round TDD + 每 phase experiment ran+recorded+verdict+root-cause(沿用 PRD-1/2/3 ralph-loop 已验证的 round 协议)。
- **R4 边界/cross-module**: directional 停等清单(7 项)+ 硬禁(8 项)+ §6.4 不变量守护硬绑;sealed-2026 + strict-chronological 双重纪律全程;§9.0 magnitude-as-size 反模式硬禁;backtest_engine.run() 不动 by design。

无 v1-v2 不一致遗漏(§0 修订史/#16 phase order vs §11 numerical 已显式留痕 in 协议 + ledger round-1 须记)。
