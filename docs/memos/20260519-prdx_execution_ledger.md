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
| X0 | Dividend extension + atr flip | 1 | data work | 🟡 R1 done (data+flip+smoke);R2 re-run baselines |
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

### Round 1(2026-05-19) — v2.1 patch + X0 sub-step-1 (data+flip+R3 smoke)

- **v2.1 PRD patch**: PRD §11 头部 + R1 留痕注:execution order per §0 #16 logical(X0→X1→X2→X4→X3→X5),§11 phase numbering vs execution order 内部不一致正式 documented,future v2.2 可选重命名 phase IDs。提交于本 round commit。
- **X0 sub-step 1 builder**:`dev/scripts/data_integrity/build_distributions_parquet.py --symbols SPY QQQ XLK XLF XLE XLV XLI XLY AAPL MSFT --start 2009-01-01 --append`。distributions.parquet:**876 → 1342 rows**(+466 = 10 new equity symbols)。Dry-run 先于 real-run。SPY 68 events($80.28 17yr 合理),sector ETFs/AAPL/MSFT 44-45 events 各(2015 start due yfinance coverage)。
- **X0 sub-step 2 atr flip**:`dev/scripts/cycle06/cycle06_track_a_eval.py:64` `atr = sym in cross_asset_set` → `atr = True`(注释完整,引用 bar_store no-op guarantee for non-distributions symbols)。Track-A `a1_b1_nav_track_a.py` 通过 importlib `_c6_panel()` reuse cycle06 automatic propagate。
- **R3 smoke**:cycle06 panel SPY 现 TR cum_ret **9.0037 vs pre-X0 split-only 6.3356**(+267pp,17yr ~1.5%/yr dividend yield 一致)。QQQ "NaN" 初见误判 ROOT-CAUSE = my math bug(iloc[0] 取了 SPY-start 2007 NaN-aligned 位置,QQQ raw 数据自 2015 起);per-symbol first-valid 重算:QQQ 5.48 / XLK 6.95 / XLF 1.70 / AAPL 10.22 / MSFT 11.14 全 reasonable TR-adjusted cum_ret。
- **诚实留痕**:Track-A v1 vs-SPY -353pp(split-only baseline)在 X0 后会变 **A1 -619pp**(strategy 比正确 TR baseline 显著更差)。**A1/B1 FAIL Track-A 真相在 TR baseline 下更 decisive,非翻盘**——与 v2 §11 X0 deliverable 预期(post-X0 vs-SPY 可能更负)完全 align。
- **下一步**:Round 2 = re-run cycle06 + Track-A 用 TR baseline(bg,heavy);记录 post-X0 verdict 数;X0 phase 完结。

### Round 0(2026-05-19 initialization)

- Ledger + /loop 协议 doc 落地。PRD-X v2 已 post-audit revision(18 issue + 3 conflict fold)。X1-X5 phase 锁定顺序记本表头。**v2 §0 vs §11 内部不一致**(§11 numerical X1-X5 vs §0 修订史 logical X0/X1/X2/X4/X3/X5)留痕,loop round-1 必修 → 写 v2.1 patch 修正 §11 phase header 标号或在 §11 加 "execution order per §0 修订史 #16" 注。下一步=用户 /loop 启动 round 1。

---

## DONE 条件(loop 终止)

- X0-X5 全 phase per-phase AC 满足(build TDD GREEN + experiment ran+recorded+verdict+root-cause)
- §12.0 cycle06 baseline regression PASS(trigger-first ≥ cycle06 Sharpe/MaxDD/turnover 容差内)
- Post-audit memo 写完(逐 phase ✅/部分/未做 + 端到端链路 + 依赖 + §6.4 全守 + sealed 全程未读 + M11 parity matrix 7 strategy 全过)
- 最终 honest summary commit + push
- **不**包含 §13 live gate(broker / paper soak / production_strategy.yaml flip)—— 那是后续独立 directional scope
