# Cycle #03 路径决定 — sector-relative construction

**Date**: 2026-05-01
**Decision authority**: operator under user delegation ("根据你的经验选最优路径 然后开工")
**One-liner**: Cycle #03 = sector-relative top-1-per-sector construction, 21d horizon, same factor pool / same temporal split / same long-only invariant. Single-variable diff vs cycle #01 (which was 21d global top-N). Goal: test whether sector-stratified selection breaks the "{β + 12-1 mom + volume}" winner-collapse template.

---

## 0. 前序状态（fact-checked 2026-05-01）

| 项 | 状态 | 证据 |
|---|---|---|
| Task #49 数据质量修复 | ✅ DONE | commit `be387d3`，78/78 universe sym 重 scan 全 clean |
| Step 1 harness 在 production data 上可用 | ✅ DONE | 验证 cycle02 top-1 cum_ret=1957% / sharpe 1.117 / maxdd -35.9% |
| Cycle #02 archived | ✅ DONE | commit `2034563`，reliability markers 加好 |
| Sealed 2026 window | ✅ INTACT | 仅 cycle #01+#02 的 train+validation 消耗 |
| `MultiFactorStrategy.rebalance_monthly` 仍是 bool | ⚠️ KNOWN, NOT BLOCKER | cycle #03 走 harness 路径不依赖 MFS；MFS cleanup 留 promote 阶段 |
| `partition_for_role` 助手 | ❌ 不存在 | 数据隔离审计 WARN #2 — cycle #03 P1 必修 |
| sector classification 源 | ❌ 不存在 | cycle #03 P1 必建 |
| sector-relative selector | ❌ 不存在 | cycle #03 P1 必建 |

---

## 1. 三个 tactical 决定（operator 裁定）

### 1.1 Sector 分类源 = 静态 map @ `core/research/sector_map.py`

- 从 `config/universe.yaml` 注释提取 + 手补 gap
- 11 GICS sectors: Communication Services / Consumer Discretionary / Consumer Staples / Energy / Financials / Health Care / Industrials / Materials / Real Estate / Technology / Utilities
- 在仓内、可 grep / git diff、零外部依赖
- 不用 yfinance.Ticker.info → 避免外部依赖 + 数据 staleness 风险

### 1.2 选股池 = 56 single-name stocks（排除所有 ETF）

排除以下 22 sym 不参与 sector ranking：

| 类别 | 数量 | 例 |
|---|---|---|
| Sector ETFs | 11 | XLK XLF XLE XLV XLI XLY XLP XLU XLB XLRE XLC |
| Factor ETFs | 5 | MTUM QUAL VLUE USMV SCHD |
| Broad-market | 2 | SPY QQQ |
| Cross-asset | 4 | TLT IEF SHY GLD SLV (5, 但 SLV 不在 78-sym 中, GLD 在 seed_pool 不在 cross_asset block) |

理由：sector-relative 要求"sector member 在 sector 内排名"；ETFs 是 sector/factor 聚合体，不是 single-name，纳入会让"sector winner = sector ETF 自身"，结构退化。

剩余 56 sym 跨 11 sectors → 平均 5 stocks/sector → 内部排名有意义。

### 1.3 Top-K-per-sector = 1, Horizon = 21d

- top-K=1: 11 sectors × 1 = 11 picks (matches cycle #02 global top-N=10 量级)
- Cap parameters in yaml: `max_sector_weight: 0.20` (单 sector 不超过 20% 组合，与 11×0.0909 等权天然吻合 + 5% buffer)
- Horizon=21d: 与 cycle #01 同 horizon → 单变量对比 "+sector-relative"
- Cycle #02 已经测过 5d，cycle #03 不重测 5d (那会双变量混淆)

---

## 2. 实施路径（task #51 P1 + #52 P2）

### Phase 1 (P1): Harness 扩展 — 4 组件

| 组件 | 文件 | 测试 |
|---|---|---|
| `core/research/sector_map.py` | 新文件，static 78-sym → GICS-11 map + ETF exclusion list | `tests/unit/research/test_sector_map.py`: 完整覆盖 + ETF 排除 + 78 sym 全在 map 内 |
| `partition_for_role(role, split_cfg)` | 加在 `core/research/temporal_split.py` | `tests/unit/research/test_partition_for_role.py`: train/validation 角色访问；未授权角色 raise |
| `topn_signals_per_sector(...)` | 加在 `core/research/harness/composite_evaluator.py` | `tests/unit/research/test_harness_composite_evaluator.py` 加 5+ tests: ETF 排除、sector 内排名、跨 sector 等权聚合 |
| 跨 cycle NAV correlation 诊断 | 加在 eval 脚本 (refactor `evaluate_cycle02_top_n.py` → 通用 `evaluate_research_cycle.py`) | 单元测试覆盖 corr 函数；端到端在 P2 cycle #03 eval 时验证 |

**P1 audit gates** (R3 真跑)：
- 全 universe 5 个 sector 抽样 spot-check map 正确
- harness eval 在 cycle02 top-1 composite + sector-relative selector 上跑通 (sane NAV)
- partition_for_role 取 validation-only 时确实只看到 5 个 validation years
- 4 组件单元测试全 pass
- 现有 26 harness tests 全 regression pass

### Phase 2 (P2): Cycle #03 mining + eval + closeout

| 步 | 内容 | ETA |
|---|---|---|
| 2a | Cycle #03 yaml 预登记 + sha256 lock + commit | 15 min |
| 2b | Mining 200 trials seed=42 (background) | ~12-15 min |
| 2c | Top-10 trials 通过 sector-relative harness eval | 5-10 min |
| 2d | R41 5-tier 分类 + closeout memo | 20 min |
| 2e | Tomorrow morning summary update | 5 min |

**P2 audit gates**：
- Mining preflight: 78-sym universe panel restrict to train (post-rebuild canonical data) — 应得 1511+ 行
- Mining log: factor pool reachability PASS (A++ patch already shipped)
- Sealed 2026 unconsumed (panel_max_date=2024-12-31)
- top-1 trial harness eval: cum_ret / sharpe / maxdd / vs SPY / vs QQQ all sane
- NAV correlation vs RCMv1 + Cand-2: pooled Pearson reported; if < 0.50 raw → "true_diversifier"; 0.50-0.85 → label_or_warn; ≥ 0.85 → reject_step5

### Phase 3 (P3, 仅当 Phase 2 出非-sibling 候选)

- Forward init candidate
- Track A acceptance NAV gates (现在 unblocked since data fixed)
- A.MV / B.MV / Fleet Step 6+ reactivate

如果 Phase 2 仍 sibling: closeout 直接走 Tier-2 + 升级到 P4 (C-3 binding cap sanity, cap ≤ 0.10) 或 P5 (C-4 cross-asset)

---

## 3. 与 user 提案的对齐 + 偏离点

### 对齐
- C-1 跳过：✅
- 不再纠结 C-3 vs C-1，主线是 sector-relative：✅
- β=-0.2 不行（违反 long-only/no-short 约束）：✅
- harness 必须可信于 production data：✅ (Task #49 修了)
- 完整 harness 7 组件清单：✅

### 偏离 (operator 裁定理由)
- **P0 不再是数据修复（已完成）**。User 当时基于 cycle #02 closeout 19:00 PT 状态读，未注意 4 个后续 commit 修了。
- **MFS rebalance_monthly cleanup 排到 promote 阶段**，不阻塞 cycle #03（cycle 走 harness 路径）。
- **C-3 binding cap 测试用 ≤0.10 而非 0.25**，因为 RCMv1 natural β=0.143-0.314，0.25 cap 在 2/3 cell 仍不 bind，不 meaningful。

---

## 4. 时间线 + commit ritual

每个 P1 组件单独 commit + push（4 commits）。
P2 yaml 单独 commit。Mining 跑完后 archive + eval + closeout 3 个 commit。
全程 self-audit R1-R4（feedback memory 强制要求）。

预计总时长 2.5-3 小时。

— operator, 2026-05-01
