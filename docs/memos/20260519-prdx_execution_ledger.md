# PRD-X v2 Execution Ledger (cross-round SoT)

**用途**: PRD-X v2 implementation /loop 的跨轮 single-source-of-truth。每轮 loop:(1) 读本 ledger 找进度 (2) 做事 (3) 收尾时追加一行 + 更新进度表 + commit。

**关联**:
- 主 PRD: `docs/prd/20260519-trigger_threshold_first_rebalance_architecture.md` (v2 post-audit)
- /loop 协议: `docs/memos/20260519-prdx_execution_loop_protocol.md`
- 历史 audit: `docs/memos/20260518-prd123_execution_ledger.md`(PRD-1/2/3+Track-A DONE)
- post-fix 约束: `docs/memos/20260519-strategic_close_out_REVISION_post_audit_fix.md`

---

## 进度表

锁定 implementation 顺序(per PRD §0 修订史 #16 logical ordering,与 §11 numerical 顺序不一致点已知 → 待 v2.1 patch):

| Phase | 名称 | 顺序 | 性质 | 状态 |
|---|---|---|---|---|
| X0 | Dividend extension + atr flip | 1 | data work | ⬜ |
| X1 | Protocol schema + GenerateStrategyAdapter | 2 | TDD build | ⬜ |
| X2 | Rule-based trigger + exit policy + vol-conditional no-trade band | 3 | TDD build + experiment | ⬜ |
| **X4** | **Deferred execution integration + M11 parity matrix** | **4** | **integrate existing** | ⬜ |
| **X3** | **Partial rebalance / delta-to-trade policy** | **5** | **true new build + experiment** | ⬜ |
| X5 | ML sidecar (sign-vote only, post-fix constrained) | 6 | build + experiment | ⬜ |
| Post-audit | per-phase AC reconciliation + cycle06 baseline regression + final honest summary | 7 | audit | ⬜ |

注:X4 比 X3 先做(integrate-existing 优先于 true-new)per PRD §0 修订史 #16,§11 numerical 写法相反,**v2 内部一致性待 v2.1 patch**(loop round-1 须 fold 此 ledger 留痕)。

### Per-phase 通用 AC(每 phase 必过,per /loop 协议 + PRD §12.4)

- bit-identical default mode(默认 mode="off" 既有路径不变,同 cascade_overlay R12 / construction_tier T0 / sample_weight=None pattern)
- sealed 2026 永不读 + strict-chronological walk-forward
- bar-integrity smoke(weekend rows=0 / monotone / sealed-year guard)before heavy ML/backtest
- §6.4 不变量守护硬绑(long-only / no-margin / SQQQ / MaxDD / 2008-≤25% / 真 short 永禁)
- M11 parity 不退化(for phases touching execution)
- §9.0 post-fix 约束:ML 输出严格 sign-vote / include-veto,禁 continuous magnitude as size weight

### Directional 停等点(7 项,per /loop 协议)

1. production_strategy.yaml status flip "active"
2. P2.4 真 short execution
3. CLAUDE.md invariant 进一步修订
4. repo-level fork
5. §13 live gate flip
6. cycle06 baseline 显著 FAIL 后主线归零方向
7. CLAUDE.md §1.4 Invariant Constraints 任意项改动

---

## 轮次日志(每轮 commit 时追加 1 行)

### Round 0(2026-05-19 initialization)

- Ledger + /loop 协议 doc 落地。PRD-X v2 已 post-audit revision(18 issue + 3 conflict fold)。X1-X5 phase 锁定顺序记本表头。**v2 §0 vs §11 内部不一致**(§11 numerical X1-X5 vs §0 修订史 logical X0/X1/X2/X4/X3/X5)留痕,loop round-1 必修 → 写 v2.1 patch 修正 §11 phase header 标号或在 §11 加 "execution order per §0 修订史 #16" 注。下一步=用户 /loop 启动 round 1。

---

## DONE 条件(loop 终止)

- X0-X5 全 phase per-phase AC 满足(build TDD GREEN + experiment ran+recorded+verdict+root-cause)
- §12.0 cycle06 baseline regression PASS(trigger-first ≥ cycle06 Sharpe/MaxDD/turnover 容差内)
- Post-audit memo 写完(逐 phase ✅/部分/未做 + 端到端链路 + 依赖 + §6.4 全守 + sealed 全程未读 + M11 parity matrix 7 strategy 全过)
- 最终 honest summary commit + push
- **不**包含 §13 live gate(broker / paper soak / production_strategy.yaml flip)—— 那是后续独立 directional scope
