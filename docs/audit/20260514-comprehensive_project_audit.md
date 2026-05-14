# PQS 全面 Audit — 2026-05-14

**Lineage**: `comprehensive-audit-2026-05-14`
**Scope**: scripts bugs + bottlenecks + logic errors + README drift + actual script runs + corner cases + data integrity + mining flow summary
**Method**: 6 rounds (R1-R6), 3 parallel Explore agents + manual verification (per `[[feedback_self_audit_methodology]]` R3 真跑代码 discipline)
**Companion doc**: `docs/audit/20260514-mining_pipeline_plain_chinese_summary.md` (R1 mining flow + cycle results 通俗汇总，用户最优先 deliverable)

---

## §1 P0 findings — 必须立刻处理

### 1.1 `daily_freshness_check.py` CANDIDATES list 全过时

**File**: `dev/scripts/daily_freshness_check.py:25-29`
**Issue**: hardcoded CANDIDATES tuple 包含 3 个 terminal 候选：
```python
CANDIDATES = (
    "rcm_v1_defensive_composite_01",   # aborted 2026-04-30
    "candidate_2_orthogonal_01",        # aborted 2026-04-30
    "trial9_diversifier_001",            # completed_fail 2026-05-12
)
```

**Impact**: `_check_forward()` line 104 跳过 terminal 状态 → 全部 skip → **不出任何 nag**。**Trial 9 v2 (start 2026-05-13) 至今 2 个交易日没 observe（status=not_started, n_runs=0）**，因为 daily ritual 没指向它。

**Fix shipped this audit**:
- `trial9_diversifier_002` (main forward runner)
- `pead_sue_trial1_evidence_v1` (standalone PEAD track — separate observe path)

**Verdict**: P0 闭环 in this commit.

### 1.2 Trial 9 v2 forward observe gap

**Manifest state**:
- `current_status`: `not_started`
- `n_runs`: 0
- `start_date`: 2026-05-13 (Wed)
- Today: 2026-05-14 (Thu)

**Should have**: TD001 (2026-05-13 EOD) recorded.

**Cause**: 1.1 (freshness check failed to nag). Plus PEAD/options soak 启动消耗的 attention budget.

**Action**: 用户今晚 NYSE 16:30 ET close 后跑 `fetchdata` + observe trial9_v2 + observe PEAD + observe options paper（3-candidate daily ritual）。

---

## §2 P1 findings — 文档 + 代码 drift

### 2.1 README.md 多处过时

| 字段 | README 说 | CLAUDE.md 说 | 实际 (verified) |
|---|---|---|---|
| RESEARCH_FACTORS 计数 | **64** | 143 | **162** ✓ |
| PRODUCTION_FACTORS | 7 | 7 | 7 ✓ |
| QQQ gate | **"硬约束: 策略 CAGR 必须 > QQQ CAGR"** | **diagnostic only (2026-05-02 deprecated)** | CLAUDE.md 对，README 错 |
| Active forward candidates | RCMv1 + Cand-2 列为 active | 3 个 (trial9_v2 + pead_evidence + options) | CLAUDE.md 对，README 完全过时 (RCMv1+Cand-2 aborted 2026-04-30) |
| Test count | "见 `data/baseline/latest.json`" | live 1300+ | **3109** (verified by pytest run today) |
| Universe count | "~80 个美股标的" / "79 交易标的" | 78-股 mining / 54-股 PEAD | seed_pool=59, total tradeable ~85 |

**Action (this commit)**: fix factor count + QQQ gate + active candidates in README §0.3 / §1.4 / §3.

### 2.2 `docs/INDEX.md` 缺 55+ 个 2026-05-12+ 文档

INDEX 文件最近一次更新没有 catch up 这两天 deluge of work：
- 13 个新 PRDs (包括 PEAD bundle / cycle10 closeout / ML Phase 2 architecture)
- 34 个新 memos (包括 cost gate revision / cycle11 audit / SPY off-by-one postmortem / PEAD closeout)
- 8 个新 audit docs

INDEX 的 "Convention for new docs"（2026-04-24）说新文档放 per-category subdir，但 INDEX 自己没列。

**Action**: defer to user — INDEX 不在 critical path（用户都通过 git log / grep find docs）。建议下个 idle round 集中 batch update。

### 2.3 `data/baseline/latest.json` stale

- `timestamp`: 2026-05-12T21:19:31Z
- `tests`: `passed: null` (snapshot 那次 build_research_baseline_snapshot.py 没 run pytest)
- Live count today: 3109 passed

**Action**: defer to user — refresh 是 `python dev/scripts/baseline/build_research_baseline_snapshot.py` 一行命令。

---

## §3 R3 + R4 agent reports — verified findings + false positives

### 3.1 Verified false-positives (我手动 verify 这 4 个 P0 claim 全 FP)

| Agent | Claim | 实际 verify 结果 |
|---|---|---|
| R3 | `observe_pead_evidence.py:138,142` hardcode ttl_bars=0/exec_delay=1 → divergence from spec | FALSE — spec yaml 写的就是 0 和 1 (我创建时就一致)。但 P2 code smell 改成 parametrize 更好 |
| R4 | `acceptance_pack.py:290-299` 空 equity 时年份计算 misaligned | FALSE — line 304 NaN-safe fail-closed branch 已 catch |
| R4 | forward runner `runner.py:1032` skip 1-bar TD entries → undercount | FALSE — code is `if len < 1: continue` (skip 0-bar only)，1-bar 正常记录 cum_ret=0.0 |
| R4 | `backtest_engine.py:184-193` open_df fallback before date alignment | NOT NEW — `prices` 已经是 daily indexed close panel, fallback `opens=prices.copy()` 是 same-index。已在 cycle11 audit memo 文档化 |

**Lesson**: 不能盲信 Explore agent severity rating — agents 在边界条件上经常 over-rate。**R3 永远不能跳过** 是黄金规则。

### 3.2 Verified latent bugs (active path 不 trigger 但 worth flagging)

**P1 — `core/backtest/signal_driven_runner.py:206`** symbol superset:
```python
symbols = sorted(set(self.entry_signals.columns) | set(self.price_df.columns))
```
如果 entry_signals 跟 price_df columns 不一致 → weight_panel 有 column 但没 price 数据 → silent NaN propagation. 现在所有 caller (cycle11 smoke, PEAD smoke, init) 都用 same universe build → union==intersection，不 trigger.

**P1 — `fundamentals_store.py:167-168`** groupby/last 依赖 sort 顺序：
> "groupby('end').last() takes LATEST-FILED row by iteration order"
现 code 是 sort_values 后 groupby last → 工作正常。但 future refactor 若 remove sort 静默 corrupt PIT。建议加 docstring assert.

**P2 — bottlenecks**:
- `price_jump_signal.py:66` iterrows + `.at[]` 4× per row → O(n²) on n=1700 events. 当前 ~5s acceptable. Phase 2 paid data 上量后再优化.
- 类似 `sue_calculator.py:169`.

---

## §4 R5 live runs — 实测结果

### 4.1 Full pytest unit suite

```
3109 passed, 1 skipped, 0 failed in 577.80s (9:37)
```

- vs 2026-05-12 baseline snapshot 的 2760 collected → **+349 tests post 5/12** (PEAD 53 + 其它 296)
- 0 regression
- 75 warnings 全 deprecation / runtime divide (test fixture, 不 critical)

### 4.2 3-candidate dry-run observes

| Candidate | State | Verdict |
|---|---|---|
| `trial9_diversifier_002` | `not_started`, n_runs=0 | **2 trading days behind** (start 5/13, 0 TDs at 5/14 EOD) |
| `pead_sue_trial1_evidence_v1` | `in_progress`, TD000 baseline | ✅ idempotent no-op on init day (correct) |
| `spy_8otm_bull_put_v1` | n_observe_days=5 | ✅ 跟踪正常 |

---

## §5 Mining flow + cycle results 总结（关键 deliverable）

详见 `docs/audit/20260514-mining_pipeline_plain_chinese_summary.md`。要点：

### 5.1 PQS 已 mining 总数
- **cycle04 → cycle08**: 5 cycles，全 **0 nominee**。共同特征 = sibling-by-NAV，factor swap 不破 long-only top-N geometry
- **cycle09**: INVALID (sampler architecture bug at 17-family expansion; fixed with `family_first` mode)
- **cycle10**: 0 nominee, R7 fail-SPY stop rule 触发
- **cycle11 signal-driven mini-smoke**: 3/20 marginally 过 SPY (informative null after close-fallback bug fixed)
- **PEAD bundle Phase 1**: **Path 1 SUE 8/9 trial 过 SPY**, Sharpe 1.063 / MaxDD -7.6% (第一个事件驱动真信号)

### 5.2 当前最强候选状态
- **PEAD trial 1** (today, evidence-only forward soak): Sharpe 1.055 / MaxDD -7.6% / Track A 14/17 fail on CAGR-vs-SPY
- **T1b ConfirmationPattern**: Sharpe 1.18 / CAGR 20.3% but year-inconsistent
- **Trial 9 v2** (active forward, diversifier role): Sharpe ~0.78 / CAGR ~10%, TD60 ~2026-08-06

### 5.3 战略瓶颈 = TC Ceiling
**5 cycles + cycle11 + Track C 集体证明**：
- 78-股 universe + monthly + top-N + long-only + 30bp 框架下，alpha 上限 = Clarke-de Silva-Thorley 2002 transfer coefficient 0.45-0.55
- 不是 implementation bug，是结构性约束
- Unlock 方向：horizon (intraday) / cadence (event-driven) / universe (200+ stocks) / strategy type (options) / relax long-only

### 5.4 PEAD 是 PQS 历史上第一个事件驱动 + 非参数化触发的真 alpha 信号
但 alpha shape = defensive low-vol → 单独 deploy 跑不赢 SPY → 真正 unlock 在 fleet 合成 (Phase C-PRD-2, deferred until Trial 9 v2 TD60)

---

## §6 Files this commit changes

- `dev/scripts/daily_freshness_check.py` — P0 CANDIDATES list 更新
- `README.md` — 因子计数 + QQQ rule + active candidates 状态
- `docs/audit/20260514-mining_pipeline_plain_chinese_summary.md` — R1 deliverable
- `docs/audit/20260514-comprehensive_project_audit.md` — 本 memo

## §7 Deferred to user explicit-go (NOT shipped this commit)

| Item | Reason | ETA |
|---|---|---|
| `docs/INDEX.md` 全面 update (55+ docs) | 工程量大，不在 critical path | 1-2 hours batch update |
| `data/baseline/latest.json` refresh | 一行命令 (`build_research_baseline_snapshot.py`) | 5 mins |
| `core/backtest/signal_driven_runner.py:206` column-equality assert | P2 防御性 hardening, 不 active | 30 mins |
| `observe_pead_evidence.py` parametrize ttl_bars/exec_delay from spec | P2 code smell, 当前 values match | 15 mins |
| iterrows() 优化 in `price_jump_signal.py / sue_calculator.py` | P2 bottleneck, 不 block PEAD soak | 1-2 hours when Phase 2 unlocks |

---

## §8 用户 directional decisions waiting

1. **今晚 NYSE 16:30 ET close 后跑 daily ritual?**（fetchdata + trial9_v2 observe + PEAD observe + options observe）— operator 推荐 YES（trial9_v2 需要补 2 个 missed TDs）
2. **INDEX.md batch update 何时做?** — defer 到周末或下个 idle round
3. **baseline snapshot refresh?** — 一行命令，可顺手
4. **P2 hardening items（superset assert + parametrize observe + iterrows）批准下一个 PEAD Phase 2 启动时一起做?** — operator 默认 defer 到 PEAD TD60 GREEN 触发 Phase 2 时

---

## §9 Honest audit verdict in 1 sentence

PQS 项目质量整体稳健（3109 tests pass / 0 regression / 关键 forward observation 基础设施 + cycle 04-11 完整闭环 + PEAD 今日 ship），主要 drift 集中在文档层（README 因子计数 + QQQ gate 过时；INDEX.md 缺 55+ docs；daily_freshness_check.py 候选列表全 terminal）而非代码层，3 agent 报告里 4 个 P0 全 false positive 验证了 R3 真跑代码原则的重要性。
