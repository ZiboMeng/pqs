# /loop script — PRD #3 trigger-first canonical promotion

Use this prompt verbatim with `/loop` to drive PRD #3 implementation.
Operator follows existing PRD-X loop protocol; phases P3.1-P3.7
sequenced per PRD.

```
/loop 不间断推进 PRD #3 trigger-first canonical promotion implementation
per docs/prd/20260520-prd_trigger_first_canonical_promotion.md。每轮按此协议:

【定位】先读 docs/memos/20260519-prdx_execution_ledger.md(跨轮 SoT)+
docs/prd/20260520-prd_trigger_first_canonical_promotion.md(主 PRD,7 phases)+
docs/memos/20260520-task3_status_flip_directional_block.md(prerequisite list)+
docs/memos/20260520-passed_qqq_gate_schema_decision.md(F6 schema decision,需用户explicit-go)+
git log 最近若干。据 PRD 进度找"下一个最小可验证步"。

锁定 PRD #3 phase 顺序:
  P3.1 canonical config selection(R16 Path A 推荐;user explicit-go gate)
  P3.2 OOS walk-forward for trigger-first(WindowAnalyzer 扩展 + 跑)
  P3.3 paper-backtest M3 alignment test for trigger-first
  P3.4 QQQ diagnostic(folded into P3.2)
  P3.5 fingerprints(universe_hash/factor_registry_hash/config_hash)
  P3.6 M2 promote_strategy.py extension for trigger-first
  P3.7 status flip + post-flip verification(含 P3.7.x yaml-driven default)

【执行】小步:一轮一个主目标。可行则 TDD —— RED 后 GREEN 后跑。
复用现有模块不重造(per PRD §F.1 inventory + PRD-X v2 已 ship 8 modules)。
任何动 canonical chart_native L3 / core acceptance / backtest_engine.run /
M11 主路径的改动须 bit-identical 回归验证。
长跑用后台(Bash run_in_background)。commit 一律 git commit -F <msgfile>。

【纪律】R1-R4 自审每轮(R3 真跑对比期望永不跳);bug 必 ROOT CAUSE 不 hand-wave;
禁 blanket "X 不行"(只写"这个 attempt 失败+用了什么+root cause");
sealed 2026 永不读、守 temporal_split partition;
§6.4 不变量守护硬绑不放松(long-only / no-margin / SQQQ / MaxDD / 真 short 永禁);
§9.0 post-fix:ML 输出严格 sign-vote;
M11 parity 保留(wrapper pattern,不动 backtest_engine.run 主路径);
PRD #3 scope boundary:thin overlay canonical NOT full state-machine engine。

【收尾每轮】commit+push(-F 文件;具体文件不用 git add -A)→ 更新 ledger
进度表 + 本轮追加行 → 输出 11-part 式简报。

【停止-等用户(directional)】遇到这些不自决,停下写清选项+建议然后结束本轮:
- canonical config selection(operator 推 R16 Path A;若用户想换别的)
- passed_qqq_gate schema decision(per 20260520-passed_qqq_gate_schema_decision.md
  3 options A/B/C,需用户选)
- 任何动 §6.4/§9.0 invariant 项
- CLAUDE.md invariant 进一步修订
- 真 short execution
- live broker 接入

【DONE】PRD #3 P3.1-P3.7 全 phase per-phase AC 达成 + status flipped 到 active
经 pydantic validator 接受 + 187+/187+ origin-GREEN + §6.4/§9.0 invariants 守 +
sealed-2026 全程未读 + M11 parity preserved + final honest summary memo →
终止 loop。

【硬禁】不自启嵌套 loop / 不静默改不变量 / 不 git add -A / 不假装完成 /
不读 sealed 2026 / 不绕过 §6.4 / 不对 backtest_engine.run 主路径做改动。
```
