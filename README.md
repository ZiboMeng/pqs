# PQS — Personal Quantitative System

> **个人量化研究与模拟交易系统**，目标是长期可持续跑赢 SPY 和 QQQ，同时
> 保持低回撤（15-20%），具备黑天鹅韧性。

本文档面向**从未接触过本工程的读者**，帮你在一小时内建立完整的心智模型，
能够独立执行回测 / 挖矿 / 模拟盘 / 报告生成，并在遇到问题时通过本文档
定位答案。

> **新读者推荐顺序**：§0 术语 → §1 项目是什么 → §2 核心约束 → §3 架构 →
> §5 环境准备 → §6 首跑 → §7 工作流 → §10 关键概念深入 → §16 故障排查。
> 如果只是想"立刻跑起来看一眼"：§5 → §6 即可，遇到没听过的词回 §0 查。
> 卡住时先看 §19。

---

## 目录

- [0. 术语速查表（先看这个）](#0-术语速查表先看这个)
- [1. 项目是什么](#1-项目是什么)
- [2. 核心约束（不得违反）](#2-核心约束不得违反)
- [3. 架构总览](#3-架构总览)
- [4. 目录结构速查](#4-目录结构速查)
- [5. 环境准备](#5-环境准备)
- [6. 三十分钟首跑](#6-三十分钟首跑)
- [7. 核心工作流](#7-核心工作流)
- [8. 脚本详细手册](#8-脚本详细手册)
- [9. 配置文件说明](#9-配置文件说明)
- [10. 关键概念](#10-关键概念)
- [11. 报告与输出解读](#11-报告与输出解读)
- [12. 常见任务 Recipes](#12-常见任务-recipes)
- [14. 测试套件](#14-测试套件)
- [15. 研究方法论](#15-研究方法论)
- [16. 故障排查](#16-故障排查)
- [17. 项目当前状态](#17-项目当前状态)
- [18. 附录](#18-附录)
- [19. 卡住时怎么办（按场景反查）](#19-卡住时怎么办按场景反查)

---

## 0. 术语速查表（先看这个）

下文反复出现的缩写 / 内部代号 / 专有名词。**第一次读 README 不需要全记，
看到不懂的回这里查就行**。

### 0.0 30 秒决策树：你是谁? 先看哪些章节?

```
你是谁?
├── 我刚 clone 这个 repo, 想跑通看一眼
│       → §5 环境准备 → §6 三十分钟首跑 (其余以后再看)
│
├── 我想加 / 改一个 factor
│       → §0 术语 → §10.1 Factor → §12.1 加 factor recipe
│
├── 我想改风险阈值 / kill switch / position cap
│       → §9.4 risk.yaml → §12.2
│
├── 我想找研究方向, 看现有 candidate 表现
│       → §1.4 当前状态 → §17 未解 blocker → docs/INDEX.md §"Final synthesis"
│
├── 我跑 mining, 想 promote 一个候选到生产
│       → §10.3 mining funnel → §10.4 Tier → §8.9 promote_strategy.py → docs/20260421-promotion_flow.md
│
├── 我想跑 forward observation (锁候选看未来 N 天)
│       → §0.4 forward 概念图 → dev/scripts/oos_mvp/run_forward_observe.py --help
│
├── 我想跑 Track C controlled mining (新框架的真实挖矿)
│       → §10.9 Track 框架 → docs/memos/20260430-track_c_dry_run_plan.md
│       → docs/templates/track_c_evidence_pack_template.md
│
├── 我想看 fleet 怎么组合多个 candidate
│       → §10.8 Fleet Allocator → §9.13 fleet.yaml
│       → core/fleet/allocator.py
│
├── 我维护代码 / 准备 PR
│       → §2 核心约束 → §14 测试套件 → CLAUDE.md (claude code 自用约束)
│       → 重要改动按 docs/checkpoints/20260430-self_audit_methodology.md 4 轮自审
│
└── 我撞墙了
        → §16 故障排查 → §19 卡住路标
```

### 0.1 量化通用术语

| 缩写 / 词 | 含义 | 直观解释 |
|---|---|---|
| **CAGR** | Compound Annual Growth Rate | 年化复利收益率。"我这条策略平均每年涨多少" |
| **Sharpe** | Sharpe Ratio | 单位风险下的超额收益。> 1.0 算不错，> 2.0 出色 |
| **IR** | Information Ratio | 相对 benchmark 的"超额收益 / 跟踪误差"。本项目 OOS IR ≥ 0.20 是 promote 门槛 |
| **MaxDD** | Maximum Drawdown | 历史最大回撤（从前高跌幅）。本项目硬约束 ≤ 20% |
| **OOS** | Out-of-Sample | 样本外。模型从未见过的时段；唯一可信的"未来表现代理" |
| **IS** | In-Sample | 样本内。训练 / 拟合时见过的数据 |
| **walk-forward** | walk-forward validation | 滚动训练 → 测试。比固定 train/test split 更接近真实使用 |
| **holdout** | holdout window | 一段从未参与任何调参的数据，最后一刀验证用。本项目用最后 252 trading day |
| **IC** | Information Coefficient | factor 值跟 forward return 的 cross-sectional 相关系数 |
| **factor** | factor / 因子 | 给每个 (date, symbol) 打一个分（如 momentum, volatility）。多 factor 加权 → 仓位信号 |
| **regime** | market regime | 市场状态分类（本项目分 6 类: BULL/RISK_ON/NEUTRAL/CAUTIOUS/RISK_OFF/CRISIS） |
| **kill switch** | risk kill switch | 触发风控 → 自动减仓 / 全现金 / 停摆。本项目 4 阶: WARNING/REDUCE/DEFENSIVE/HALT |
| **PIT** | Point-In-Time | 那一天能拿到的数据，不能用未来数据 reconstruct（防止 lookahead bias） |
| **lookahead bias** | lookahead bias | 用了未来才知道的信息。回测最常见的 silent killer |
| **slippage** | slippage | 实际成交价跟决策时观察价的差。本项目用 bps 模型 |

### 0.2 标的术语

| 词 | 含义 |
|---|---|
| **SPY** | S&P 500 ETF。本项目主 benchmark |
| **QQQ** | NASDAQ-100 ETF。Diagnostic reference only post-2026-05-02 ([memo](docs/memos/20260502-qqq_benchmark_deprecation.md)) |
| **TQQQ** | 3x leveraged QQQ。本项目允许但严审 |
| **SOXL** | 3x leveraged 半导体（SOXX 底层）。允许但严审 |
| **SQQQ** | 3x **inverse** QQQ。**本项目黑名单** |
| **SOXS** | 3x **inverse** 半导体。**本项目黑名单** |
| **Mag7** | "Magnificent 7" — AAPL / MSFT / GOOGL / AMZN / META / NVDA / TSLA |
| **^VIX / ^TNX** | 波动率指数 / 10年国债收益率 — 不交易，只作 features 用 |
| **macro_reference** | universe 里"只读 features 不下单"的 ticker 类（含 ^VIX/^TNX/DX-Y.NYB） |

### 0.3 项目专有术语

| 词 | 含义 | 详见 |
|---|---|---|
| **PRD** | Product Requirements Document — 一个明确写下需求 + 接受标准的内部规格文档。本项目 `docs/prd/*.md` 是当前主线，按字母编号（M1, M2... 或字母 F, G...） | `docs/INDEX.md` §1 |
| **mining funnel / 6-stage funnel** | 一个候选策略要过 6 道门: Quick → OOS → Robustness → Diversity → Holdout → QQQ gate（每道一个 `passed_*` flag） | §10.3 |
| **QQQ gate** | 硬约束: 策略 CAGR 必须 > QQQ CAGR (full-period + holdout + OOS avg 都要过) | §15.2 |
| **Tier** | 策略评级 S/A/B/C/D。S/A 推荐, B 候选, C watch, D 不 promote | §10.4 |
| **promote** | 把 mining 出来的候选写进 `config/production_strategy.yaml` 让 paper trading 真正用它。流程: `acceptance_pack.py` → `promote_strategy.py` | §8.9 |
| **acceptance pack** | promote 前的 10-gate 验收 artifact (`docs/20260421-promotion_flow.md`) | §8.9 |
| **lineage tag** | mining archive 里的实验隔离标签（如 `post-2026-04-26-cycle-01`）。同 lineage 的 trial 才直接可比 | §10.6 |
| **spec_id** | 一个具体参数组合的唯一 hash (12 char prefix)。在 `data/mining/archive.db::trials` 表里查 | — |
| **forward observe** | "锁定一个 candidate, 从今天起每天观察它真实表现 N 个 trading day, 满 10/20/40/60 TD 后做决策"。模拟"假装上线"但不真实下单 | §0.4 |
| **TD** / **TD001** | Trading Day。`TD001` = forward observation 的第一个交易日；checkpoint 在 TD10/20/40/60 | §0.4 |
| **paper trading** | 模拟盘。从 `config/production_strategy.yaml` 读策略，用真实价格模拟下单 + 跟踪 P&L。**不是** forward observe (paper 是"假装在交易"，forward 是"假装提前锁了候选看它过未来 N 天") | §7.3 |
| **RCMv1** / **Cand-2** | 当前两个 forward-observation 中的候选。RCMv1 = "Research Candidate Memo v1 defensive composite"; Cand-2 = "candidate 2 orthogonal" 由 `{ret_5d, rs_vs_spy_126d, hl_range}` 等权组成 | `CLAUDE.md` |
| **Phase B / C / D / E** | 项目历史阶段。当前活跃在 Phase D + E-post (forward observation)；前期阶段总结在 `docs/INDEX.md` §"Final synthesis docs" | `CLAUDE.md` |
| **Ralph loop** | 多轮 audit 流程的内部代号。每轮一个 round number 一个 lineage tag。详见 `docs/20260420-ralph_loop_log.md` | — |
| **ConfigSnapshot / ConfigDriftEvent** | PRD F 引入: forward manifest 在 init 时锁定 5 个 config hash, observe 时检查漂移。Halt-class drift (universe / factor_registry / risk) → manifest 状态翻 `requires_data_review` | §0.4 + `docs/prd/20260428-config_universe_snapshot_hardening_prd.md` |
| **legacy_unhashed_inputs** | forward TD 入口标记: 用 PRD-F 之前老格式写的 entry, revalidate 时跳过 | — |
| **strict_match** | backtest ↔ paper trading 一致性: 一致的 fill 序列 / 同 hash 输出 | `CLAUDE.md` |

### 0.4 Forward observation 概念图（PRD F + v2.1.3）

```
   freeze a candidate              every trading day after
   (lock spec + cost + config) ──> observe(): append one TD entry
            │                              │
            │                              ├─ revalidate v2.1: bar hash
            │                              │  drift detection (data
            │                              │  revision events)
            │                              │
            │                              └─ revalidate F: config hash
            │                                 drift detection (config
            │                                 events)
            ▼                              ▼
       TD001 (entry day)              TD002, TD003, ..., TD010, ...
                                       │
                                       ├─ TD10/20/40/60 = decision
                                       │   checkpoints
                                       │
                                       └─ at decision day: user runs
                                          decide() → completed_success /
                                          completed_fail / aborted
```

**关键约束**:
- Forward 是"事先锁、事后看"，**不能事后调参**
- Halt-class config drift（改 universe / factor_registry / risk）会让 manifest 翻 `requires_data_review`，必须 `decide()` 才能继续
- TD 计数只算真实交易日（不含周末/假期）

---

## 1. 项目是什么

### 1.1 一句话

**PQS 是一个本地运行的量化研究框架**，帮助个人交易者基于 yfinance / 内部
数据源，在 ~80 个美股标的上研究因子 / 组合策略 / 回测 / 模拟盘，
最终跑出可以真实落地的仓位建议。

### 1.2 定位边界

| 是 | 不是 |
|---|---|
| 研究 + 模拟盘框架 | 自动下单系统（无真实 broker 对接） |
| 本地 macOS / Linux 运行 | 云端 SaaS |
| 中等规模（~80 标的）股票策略 | HFT / 毫秒级 |
| 长周期（天-月）持仓 | 日内短线 |
| 长仓 + 现金 | 做空 / 杠杆（SQQQ 已黑名单） |
| 初始 $10k 规划 / 当前 $100k 研究 → $1M 可扩展 | 大资金（百万美金以上） |

### 1.3 目标量化指标

- **CAGR 跑赢 SPY 和 QQQ**（full period + holdout 都要过）
- **最大回撤 15-20%**，黑天鹅中不差于 SPY
- **OOS walk-forward IR ≥ 0.20**（promote 到生产的门槛）

### 1.4 当前状态

> 本节只列**用户可见 / 公共契约**层面的当前状态。轮次细节 / 内部
> archive 计数 / candidate registry 记录细节 / round-by-round 工作
> 状态都在 `CLAUDE.md` 和 `docs/INDEX.md`（指向 final synthesis
> 文档）。
>
> 看不懂下面的 RCMv1 / Cand-2 / TD / ConfigSnapshot 等? → §0 术语表。

- **生产策略**: `config/production_strategy.yaml` 为单一真源（PRD M1）。当前 `status: conservative_default` — post-fix validated best 尚未存在
- **Universe**: **79 交易标的** = 59 seed_pool + 11 sector ETFs + 5 factor ETFs + 4 cross-asset；另 3 个 macro_reference（^VIX / ^TNX / DX-Y.NYB）只作 features 不交易；`SQQQ` + `SOXS` 在 blacklist
- **Factor registry**: **7 PRODUCTION + 64 RESEARCH**，单一真源 `core/factors/factor_registry.py`，通过 `test_factor_registry.py` 强一致
- **数据**: 日线 2007-2026 / 60m intraday 2015-2026 / 1m 2015-2026（部分覆盖）
- **Cross-ticker DSL**: `config/cross_ticker_rules.yaml` 5 条规则，`enabled: true`，启动时默认应用；`--no-cross-ticker-rules` 可关闭
- **Pricing semantics**: 详见 `CLAUDE.md` §"Pricing and Valuation Semantics"（raw bars + splits.parquet 读时 cascade；T+1 open-fill 执行）
- **测试**: 当前计数 / git head 见 `data/baseline/latest.json`；刷新用 `dev/scripts/baseline/build_research_baseline_snapshot.py --run-tests`
- **Framework**: M0-M8 + M10-M16 已交付（M11a / M11b / M12 / M14 在 2026-04-24 → 2026-04-27 ship；详见 `CLAUDE.md` §"Framework Completion PRD"）。开放项 M17（live-feed infra）+ M18（DSL func expansion）
- **Forward OOS evidence guard**: forward 运行的 manifest 现在在 `init` 时锁定一份 `ConfigSnapshot`（universe / factor_registry / research_mask / risk / system 5 个 hash），`observe` 每次跑 revalidate 时检查 config 漂移。Halt-class（universe / factor_registry / risk）会把 `current_status` 翻成 `requires_data_review`；warn-class（research_mask / system）只记录。Pre-PRD-F manifest 走 lazy-migration（不强制 halt），可用 `dev/scripts/forward/backfill_config_snapshot.py --dry-run` opt-in 接管。详细契约：`docs/prd/20260428-config_universe_snapshot_hardening_prd.md`
- **Track 三件套**（2026-04-29+ 主线）:
  - **Track A** ✅ — 时序切分纪律 (`config/temporal_split.yaml` `alternating_regime_holdout_v1` split + 17-gate acceptance evaluator + sealed_eval ledger + C5 role-remint guard)。详 `docs/prd/20260429-temporal_split_holdout_discipline_prd.md` v1.1
  - **Track B** ✅ — Fleet allocator Step 1-5 已 land (`config/fleet.yaml` + `core/fleet/`)。Step 5 = C2 correlation budget (warn 0.70 / reject 0.85, pairwise on realized candidate daily returns)。Steps 6-9 (DD throttle / role caps / fleet observe / shadow-to-live) codex-frozen 等 explicit-go
  - **Track C** ⏸️ — Real controlled mining 等 `docs/templates/track_c_evidence_pack_template.md` codex 签 + 三个 concern guards (A 2026 sealed double-dip / B forward TD60 early-attention / E economic-invariant tests)。Plan 在 `docs/memos/20260430-track_c_dry_run_plan.md`
- **Forward observation 现状（legacy decay verification）**: `RCMv1` + `Cand-2` 两个 candidate 在 forward observe，但 2026-04-30 NAV-correlation 实验显示 pooled Pearson **0.898** > Step 5 reject 阈值 0.85 — Cand-2 "orthogonal" 标签**作废**，fleet-of-two 等权组合不产生 risk diversification。两 candidate 已 reclassified 为 legacy decay verification（不进 fleet promotion）。证据 + 撤回详见 `docs/memos/20260430-rcmv1_cand2_realized_correlation.md`
- **Options research track**（独立 sleeve，不进 production candidate registry / fleet allocator，详 `CLAUDE.md` §"Options Research Track"）:
  - **Phase 1** ✅ — free-path D→A→C→B→E sweep done (`pqs-options-v1-2026-05-02` branch, merged 2026-05-03)。honest winner = SPY 8% OTM bull put 在 realistic asymmetric skew (put 1.30 / call 0.75 × VIX) 下 Sharpe **0.62** / CAGR **+0.99%/yr** / MaxDD -2.96%（synthetic 33yr backtest，需 paper-observe 验证）；wheel **REJECTED**（MaxDD -32.72% > 25% ceiling，long-only no-margin 结构性原因）
  - **Path 2** ▶️ — paper-trading layer active (`spy_8otm_bull_put_v1`, first observe 2026-05-04 EOD)；51 unit tests 含 isolation contract HARD merge gate；$10K 起始 NAV 是 mechanism validation 不是 Sharpe estimation（生产 sizing 需 $50-100K+）
  - **下一决策窗口 ~2026-07-30** — Trial 9 TD60 + options paper TD60 同期对齐时判 paid chain data 是否上 (ORATS / Polygon options ~$50-200/mo) + 单股扩展（Path B 标 NVDA/AMD 为 Tier 1）。Phase 1.4 viability memo 明确建议在此之前 DEFER 付费决定
- **自审方法论**（forward-only 2026-04-30+）: 重要改动须经 4-round audit (R1 事实 / R2 逻辑 / R3 真正执行 / R4 边界故障)。详 `docs/checkpoints/20260430-self_audit_methodology.md`
- **历史阶段总结**: 入口在 `docs/INDEX.md` §"Final synthesis docs"；ralph-loop 工作日志在 `docs/20260420-ralph_loop_log.md`

---

## 2. 核心约束（不得违反）

这些是**硬约束**，任何代码 / 策略 / 配置改动都不得破坏：

| # | 约束 | 原因 |
|---|---|---|
| 1 | **Long-only, no-margin, no-short** | 个人账户风险 |
| 2 | **SQQQ 黑名单; TQQQ/SOXL 严审** | 杠杆反向 ETF 极端风险 |
| 3 | **No real broker API this phase** | 模拟盘 = internal simulation |
| 4 | **macOS / Linux 本地运行** | 不上 AWS / cloud 优先 |
| 5 | **Benchmark: SPY 主 (HARD outperform); QQQ diagnostic only** | post-2026-05-02 QQQ deprecation; see §15.2 |
| 6 | **Left-side trading = enhancement only** | 永不作默认 engine |
| 7 | **Intraday: 60m/30m 主; 15m research-only** | 数据可得性约束 |
| 8 | **所有阈值必须 config/*.yaml 可调** | 不硬编码 |
| 9 | **Backtest - Execution 一致性** | strict_match 机制保证 |
| 10 | **中文报告, 英文代码** | 本项目惯例 |
| 11 | **设计目标 $10k → $1M+**（研究阶段当前用 $100k，见 §9.1） | 设计目标 |
| 12 | **MaxDD 目标 15-20%**, 不差于 SPY in crisis | 风险铁则 |

**"不降标准" 原则 (R17)**: 遇到研究瓶颈时，**不降阈值**（OOS IR ≥ 0.20 /
QQQ gate / MaxDD 硬顶），用扩 universe / 加数据源 / 找新 alpha 源解决。

---

## 3. 架构总览

```
┌──────────────────────────────────────────────────────┐
│            Config (config/*.yaml)                    │
│     universe / risk / cost_model / regime / etc.     │
└──────────────────────┬───────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────┐
│                 Data Layer                           │
│  MarketDataStore / BarStore / yfinance fallback      │
│  ├─ data/daily/*.parquet        (79 tradable + macro)│
│  ├─ data/intraday/{1m,5m,...,60m}/*.parquet          │
│  └─ data/ref/splits.parquet, bar_provenance.parquet  │
└──────────────────────┬───────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────┐
│              Factors Layer                           │
│  RESEARCH_FACTORS (64, generate_all_factors)         │
│  PRODUCTION_FACTORS (7, used by MFS inline)          │
└──────────────────────┬───────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────┐
│           Signals / Strategies                       │
│  MultiFactorStrategy / dual_momentum /               │
│  trend_following / cross_asset_rotation /            │
│  left_side                                           │
└──────────────────────┬───────────────────────────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
      Backtest     Mining       Paper Trading
     (validate)  (optimize)    (live simulation)
          │            │            │
          ▼            ▼            ▼
┌──────────────────────────────────────────────────────┐
│            Reports & Risk                            │
│  master_report / intraday_report / diagnostics /     │
│  kill_switch / stress_tester                         │
└──────────────────────────────────────────────────────┘
```

**数据流**: config → data → factors → signals → (backtest | mining | paper) → reports

### 3.1 决策流程图（一个 idea 怎么变成生产仓位）

上面是模块**依赖**视图。下面是一个 idea 从研究到生产的**决策**视图。

```
                    ┌──────────────┐
                    │   IDEA       │  "low_vol 可能 work"
                    │  (人 / LLM)  │  "这个 alpha 在 RISK_OFF regime 可能不一样"
                    └──────┬───────┘
                           │
                           ▼
        ┌─────────────────────────────────────────┐
        │  RESEARCH 通道 (idea ↔ factor 探索)     │
        │                                         │
        │  写 YAML 候选 → llm_factor_propose.py   │  →  REJECT / ARCHIVE
        │       ↓ (如果有 IC)                     │      / NEEDS_HUMAN_REVIEW
        │  llm_candidate_deep_check.py            │
        │       ↓ (如果 OOS+regime+quartile 过)   │
        │  llm_candidate_factor_backtest.py       │
        │       ↓ (5 gate 过)                     │
        │  user 审核 → 加入 RESEARCH_FACTORS      │  ← 见 §12.1 recipe
        └────────────────┬────────────────────────┘
                         │
                         ▼ (如果想进生产组合)
        ┌─────────────────────────────────────────┐
        │  STRATEGY 通道 (factor → strategy)      │
        │                                         │
        │  在 MultiFactorStrategy 里 inline impl  │
        │  + 加入 PRODUCTION_FACTORS (强约束:     │
        │  跟 RESEARCH 同名时必须数值一致)        │
        └────────────────┬────────────────────────┘
                         │
                         ▼
        ┌─────────────────────────────────────────┐
        │  MINING 通道 (优化 strategy 参数)       │
        │                                         │
        │  scripts/run_mining.py                  │
        │       ↓ Optuna trial                    │
        │  MiningEvaluator 跑 6-stage funnel:     │
        │   1. Quick   2. OOS   3. Robustness     │  ← 见 §10.3
        │   4. Diversity  5. Holdout  6. QQQ gate │
        │       ↓                                 │
        │  archive.db (含 tier S/A/B/C/D)         │  ← 见 §10.4
        └────────────────┬────────────────────────┘
                         │
                         ▼ (找到 tier ≥ B 的 candidate)
        ┌─────────────────────────────────────────┐
        │  ACCEPTANCE 通道 (promote 前的 10-gate) │
        │                                         │
        │  scripts/acceptance_pack.py             │  ← 见 §8.9
        │  --spec-id <id>                         │
        │       ↓ (10 gate 全过)                   │
        │  scripts/promote_strategy.py            │
        │  --spec-id <id> --promote               │
        │       ↓ (rewrites)                      │
        │  config/production_strategy.yaml         │  ← 现 paper 真的会用它
        │  status: active                         │
        └────────────────┬────────────────────────┘
                         │
            ┌────────────┼────────────┐
            ▼                         ▼
    ┌──────────────────┐    ┌──────────────────┐
    │ PAPER TRADING    │    │ FORWARD OBSERVE  │
    │ (假装在交易)      │    │ (假装锁了候选,   │
    │                  │    │  看未来 N 天)    │
    │ scripts/run_     │    │                  │
    │   paper.py       │    │ dev/scripts/oos_ │
    │ --mode live      │    │   mvp/run_       │
    │                  │    │   forward_       │
    │ 每日 EOD 跑一次  │    │   observe.py     │
    │ 持仓 / cash /    │    │ init → observe → │
    │ kill switch /    │    │ TD001..TD060 →   │
    │ 跟踪 P&L         │    │ decide()         │
    │                  │    │                  │
    │ 见 §7.3          │    │ 见 §0.4 + §10.7  │
    └──────────────────┘    └──────────────────┘
```

**两条道路并行**:
- **Paper trading** = 把生产策略当真用（每日跑、tracking P&L）
- **Forward observe** = 把候选**事先锁**（spec hash + cost hash + config hash），然后**事后观察** N 个交易日。**不能事后改参数**（这是 OOS 的灵魂）。两者**互不替代**。

---

## 4. 目录结构速查

```
pqs/
├── README.md                    ← 本文件
├── CLAUDE.md                    ← Claude Code 专用 instructions + 历史
├── config/                      ← 所有 YAML 配置
│   ├── system.yaml              - 资本 / 路径 / 日志
│   ├── universe.yaml            - 交易 universe 定义（79 symbols）
│   ├── production_strategy.yaml ⭐ - **生产策略单一真源** (PRD M1)
│   ├── backtest.yaml            - 回测 + mining 阈值
│   ├── risk.yaml                - 风险约束（position limits, kill switch 等）
│   ├── cost_model.yaml          - 交易成本参数
│   ├── regime.yaml              - 市场状态分类阈值
│   ├── reporting.yaml           - 报告风格
│   ├── events.yaml              - 事件日历
│   ├── notify.yaml              - 消息推送 (微信 / Server 酱)
│   ├── cross_ticker_rules.yaml  - 跨标的声明式规则 DSL (PRD M4, enabled:true, 5 rules)
│   ├── temporal_split.yaml      - Track A alternating_regime_holdout_v1 (train/validation/sealed splits + role gates + stress slices)
│   ├── fleet.yaml               - Track B FleetAllocator config (Steps 1-5: capital split + C2 corr budget + C3 overlap throttle)
│   ├── research_mask.yaml       - 因子研究面板的 min_price / min_usd_volume / window mask
│   └── acceptance.yaml          - Tier-D + walk-forward + factor-tier 阈值单一真源 (PRD threshold unification)
├── core/                        ← 核心业务代码
│   ├── backtest/                - BacktestEngine / WindowAnalyzer / concentration_metrics
│   ├── config/                  - pydantic schemas + loader
│   ├── data/                    - MarketDataStore / BarStore / panel_loader / vix_loader
│   ├── factors/                 - factor_generator / factor_registry / base_factors
│   ├── features/                - feature engineering helpers
│   ├── signals/                 - strategies (MFS, dual_momentum, etc.) + left_side
│   ├── mining/                  - MiningEvaluator / StrategyMiner / Archive / acceptance_pack / rcm_archive / research_miner
│   ├── fleet/                   - FleetAllocator (Track B Step 1-5; correlation budget / overlap throttle / capital split / manifest_io / evidence)
│   ├── research/
│   │   ├── concentration/       - M12 concentration gate (top1 / top3 / watchlist exposure / weighted thin-data)
│   │   ├── forward/             - forward OOS runner / manifest_schema / revalidate (PRD F + v2.1.3 hardening)
│   │   ├── robustness/          - window_spec / EvidenceClass enum
│   │   ├── temporal_split.py    - Track A alternating_regime_holdout_v1 split loader (+ partition_for_role miner/selector/sealed_test_runner)
│   │   ├── temporal_split_acceptance.py - Track A 17-gate acceptance evaluator
│   │   ├── sealed_ledger.py     - 2026 sealed-eval ledger (M5 fail_closed_on_repeat + R20 split-failure guard)
│   │   ├── regime_classifier.py - M9 manual + auto regime tag (tiered disagreement policy)
│   │   ├── frozen_spec.py       - FrozenStrategySpec loader (research_candidates yaml)
│   │   ├── risk_cluster_map.py  - 17 trade-level risk clusters (54 stocks; cycle #03+ cap_aware construction)
│   │   ├── sector_map.py        - GICS-11 stock→sector map (54 stocks; concentration reporting)
│   │   ├── harness/             - per-trial composite-spec → paper-NAV evaluator (HarnessConfig: global_top_n / cap_aware modes)
│   │   └── ...
│   ├── portfolio/               - PortfolioConstructor
│   ├── execution/               - CostModel / ExecutionSimulator / BrokerAdapter
│   ├── paper_trading/           - PaperTradingEngine
│   ├── risk/                    - FailureDetector / KillSwitch / StressTester
│   ├── regime/                  - RegimeDetector
│   ├── intraday/                - IntradayBacktestEngine / multi_timescale
│   ├── reporting/               - master_report / intraday_report
│   ├── diagnostics/             - 4 detectors (CostDrift / FactorDecay / PaperBacktestDivergence / StrategyAlpha)
│   ├── news/                    - 事件日历 / 新闻源
│   ├── storage/                 - 底层 parquet / sqlite 封装
│   ├── universe/                - UniverseManager / AssetScorer
│   ├── notify/                  - 消息推送
│   └── logging_setup.py         - 全局 logging 初始化
├── scripts/                     ← 全部 CLI 入口（详见 §8）
├── dev/                         ← 开发 / 研究脚本（不属于 production CLI）
│   └── scripts/
│       ├── baseline/            - build_research_baseline_snapshot.py (PRD M0)
│       ├── correlation/         - rcmv1_cand2_realized_nav_correlation.py (Track B Step 5 prep)
│       ├── forward/             - backfill_config_snapshot.py (PRD F lazy-migration opt-in)
│       ├── oos_mvp/             - run_forward_observe.py / run_robustness_eval.py / smoke.py
│       ├── llm_handoff/         - dump_llm_handoff_context.py (PRD M15)
│       ├── data_integrity/      - rebuild_daily.py
│       ├── research_cycle/      - run_close_eval.py
│       └── (其他 ops / migrations / demos)
├── tests/                       ← pytest 套件（计数见 `data/baseline/latest.json`）
│   ├── unit/
│   └── integration/
├── data/                        ← 数据目录（gitignored）
│   ├── daily/                   - 日线 parquet
│   ├── intraday/{1m,5m,...,60m}/ - intraday parquet
│   ├── ref/                     - splits, bar_provenance
│   ├── mining/                  - archive.db, optuna.db, rcm_archive.db (Track A C5 lookup)
│   ├── paper_trading/           - paper_trading.db
│   ├── paper_runs/              - per-candidate per-cell paper artifacts (pnl_daily / fills / target_portfolio / drift_*)
│   ├── ml/                      - 研究产出（llm candidates, grid results 等）
│   ├── baseline/                - latest.json snapshot（git SHA / pytest count / archive 计数）
│   ├── memos/                   - 机器可读 memo artifacts (e.g. NAV correlation JSON)
│   └── research_candidates/     - frozen spec yaml + forward_run_manifest.json + sealed_eval_ledger.parquet
├── research/                    ← 研究源码（tracked）
│   └── llm_candidates/          - LLM 生成的 factor 候选 (R1-R14 各 round)
├── docs/                        ← 研究文档 + PRD + 阶段性 synthesis（详见 docs/INDEX.md）
│   ├── *_final_synthesis.md     - 每个完成阶段的权威总结（Deep Mining / RCMv1 / Phase E / ...）
│   ├── prd_*.md                 - PRD 文档（framework / deep_mining / phase_e / llm_factor_mining / ...）
│   ├── promotion_flow.md        - Mining → production 正式流程 (M2)
│   ├── llm_external_llm_handoff.md  - 外部 LLM 协作流程 (M15)
│   └── (其他历史 audit / proposal / 报告)
└── reports/                     ← 报告产出（部分 gitignored）
    ├── backtests/               - 回测 run artifacts (`backtest/runs/<ts>_backtest/`)
    ├── consolidate_sanity/      - 数据合并 sanity check 报告
    ├── known_data_issues/       - 已知数据问题记录（如 ZTST sentinel）
    ├── post_processing/         - trades_backfill 后处理报告
    └── trades_backfill_qa/      - trades_scanner QA 产出
```

---

## 5. 环境准备

### 5.0 从 0 开始

**先决条件**: macOS 或 Linux（含 WSL2 / Windows）+ Python 3.14 + git。
后续所有命令都假定**当前工作目录是 repo 根目录**。

```bash
# 1. clone
git clone https://github.com/ZiboMeng/pqs.git
cd pqs                                # ⬅️ 之后所有命令在这里跑

# 2. 看一眼是不是真的进了项目根
ls README.md config/ core/ scripts/   # 应该都看得到
```

WSL2 用户特别提醒:
- 强烈建议把 repo 放到 WSL 文件系统（如 `~/Documents/projects/pqs`），**不要**放到 `/mnt/c/...` —— 后者磁盘 I/O 慢 10x，pytest 会卡。
- conda env 也装在 WSL 里。本仓库 CLAUDE.md 假设 Python 在 `/home/<user>/miniconda3/envs/pqs/bin/python`；自定义请在 §16 troubleshooting 找替换路径的提示。

### 5.1 Python 环境

```bash
# 推荐: conda env
conda create -n pqs python=3.14
conda activate pqs

# 核心依赖（canonical source）
pip install -r requirements.txt

# 可选：研究 / 开发依赖
pip install -e ".[dev,research]"       # pytest + ruff + mypy + sklearn + lightgbm + jupyter

# 可选：GPU / Transformer 研究（M8 research-only，默认不装）
pip install -r requirements-gpu.txt    # torch

conda install -c conda-forge libomp    # XGBoost 需要
```

### 5.2 数据准备

首次启动需拉 yfinance 数据:

```bash
# 1. Universe 日线（config/universe.yaml 里的 79 个 tradable symbols）
python scripts/fetch_data.py --daily-only

# 2. Mining pool（S&P 500 级别）—— PRD deep mining R34 用
#    注：data/daily/ 已预有 25340 parquets（全美股 polygon batch）；
#    此命令只做 S&P 500 511 个的增量 freshness sync
python scripts/fetch_sp500_pool.py   # 5-10 min 增量

# 3. Intraday（可选；若要跑 track B intraday mining）
python scripts/fetch_data.py --intraday-only
```

**已有本地 1m 数据的可选升级**（见 CLAUDE.md `1m Bar Pipeline` 段）：

```bash
python scripts/build_splits_parquet.py         # 构建 splits.parquet
python scripts/build_bars_parquet.py --phase all --workers 6
python scripts/aggregate_bars.py               # 1m → 5m/15m/30m/60m/daily
python scripts/build_catalog.py                # coverage 目录
```

### 5.3 验证环境

```bash
# 若项目 Python 不在 PATH，用 env 绝对路径（WSL/conda 常见）
PY=/home/zibo/miniconda3/envs/pqs/bin/python

$PY -m pytest -q                        # 期望计数见 `data/baseline/latest.json`
$PY scripts/run_backtest.py --help      # 验证 CLI 能进
bash scripts/run_all.sh check           # 环境自检
```

---

## 6. 三十分钟首跑

> 注：早期文档叫"五分钟快速开始"，但实际 step 4 mining 一项就 15-30
> 分钟，全套首跑约 30-45 分钟。诚实标 30 分钟。

跑一次完整"数据 → 回测 → 挖掘 → 报告"流程：

```bash
# Step 0 — 数据是否就绪？（首次运行必做）
ls data/daily/SPY.parquet 2>/dev/null && echo "数据存在" || echo "需要先跑 fetch"
# 如果显示"需要先跑 fetch":
python scripts/fetch_data.py --daily-only   # ~3-5 分钟拉 79 个 symbol 的日线

# Step 1 — 看一眼 universe（可跳过；只是确认默认就行）
head -40 config/universe.yaml

# Step 2 — 快速回测（跳过 walk-forward，~3 分钟）
python scripts/run_backtest.py --no-walk-forward

# Step 3 — 看报告（回测产出落在 reports/backtests/ 下带时间戳的目录）
ls reports/backtests/backtest/runs/                   # 列出所有 run
LATEST=$(ls -td reports/backtests/backtest/runs/*/ | head -1)
head -80 "$LATEST/master_report.md"                   # 看最近一个的开头
# ⬆ 看不懂中文报告字段含义? 见 §11 报告解读

# Step 4 — 跑挖掘循环（寻找最佳参数；15-30 分钟）
python scripts/run_mining.py --trials 30 --budget 900 --type multi_factor \
    --lineage-tag my_first_run

# Step 5 — 看 mining 排行榜
python scripts/run_mining.py --leaderboard --lineage-filter my_first_run
# ⬆ 看不懂 tier / oos_ir / passed_qqq_gate? 见 §0 + §10.3

# Step 6 — 跑一次模拟盘（当日 EOD 后跑；需当日 60m bars 已更新）
python scripts/run_paper.py --mode status      # 先看当前状态
python scripts/run_paper.py --mode live        # 真正跑一天

# Step 7 — 一键跑研究全套（包含上面所有 + universe + factor screen + xgb）
bash scripts/run_all.sh research
```

**第一次跑遇到问题?** → 先查 §16 故障排查 → 没找到去 §19 反查路标。

---

## 7. 核心工作流

五种典型工作流：

### 7.1 回测 (Backtest)

**目的**: 验证某个策略配置在历史上的表现。

```bash
# 完整回测（包含 walk-forward OOS 验证，~15-30 分钟）
python scripts/run_backtest.py

# 快速回测（跳过 walk-forward，~3 分钟）
python scripts/run_backtest.py --no-walk-forward

# 自定义时段
python scripts/run_backtest.py --start 2020-01-01 --end 2025-12-31

# 只跑某个策略
python scripts/run_backtest.py --strategy multi_factor
```

**产出**: `reports/backtests/backtest/runs/<timestamp>_backtest/` 下
- `equity_curve.csv` - 权益曲线
- `trades.csv` - 逐笔成交
- `metrics.json` - 关键指标
- `master_report.md` - 综合报告（中文）

### 7.2 挖掘 (Mining)

**目的**: Optuna 搜索最佳 strategy 参数（factor 权重、top_n、lookback 等）。

```bash
# 单类型挖掘（推荐, 30 trials ~ 15 min）
python scripts/run_mining.py --trials 30 --budget 900 --type multi_factor \
  --lineage-tag my_experiment

# 全 4 类型（~ 40 min）
python scripts/run_mining.py --trials 25 --budget 2400

# 看排行榜
python scripts/run_mining.py --leaderboard

# 按 lineage filter
python scripts/run_mining.py --leaderboard --lineage-filter 'post-2026-04%'
```

**产出**: 写入 `data/mining/archive.db`（SQLite），包含每个 trial 的：
- quick_sharpe, quick_cagr, quick_max_dd
- oos_ir, oos_sharpe, oos_pass_rate
- regime_robust, cost_robust, param_robust
- qqq_full_period_excess, qqq_holdout_excess, qqq_oos_avg_excess, passed_qqq_gate
- tier (S/A/B/C/D), composite_score, lineage_tag

### 7.3 模拟盘 (Paper Trading)

**目的**: 每日/实时模拟下单，跟踪 P&L，触发 kill switch。

**CLI mode 只有三个**：`live` / `replay` / `status`。Engine 内部会按当日
是否有 intraday bars 自动选择 `run_day_intraday`（bar-by-bar，idempotent
断点续传）或 `run_day_daily`（日线 fallback）。

```bash
# Live 模式（当日 EOD 后跑，需当日 60m bars 已更新）
python scripts/run_paper.py --mode live

# Replay 模式（历史回放，带 bias 警告；仅 diagnostic 用）
python scripts/run_paper.py --mode replay --from-date 2024-01-02

# Replay 指定窗口
python scripts/run_paper.py --mode replay --from-date 2024-01-02 --to-date 2024-06-30

# 查看当前状态（持仓 / cash / equity）
python scripts/run_paper.py --mode status

# 开启 multi-TF timing layer（实验性，默认关）
python scripts/run_paper.py --mode live --use-timing
```

**产出**: `data/paper_trading/paper_trading.db` 里
- pt_state (当前持仓 + 现金)
- pt_history (每日 equity / P&L / 交易笔数)
- intraday_{orders,fills,positions,equity} (intraday 模式)
- bar_checkpoints (断点续传)

### 7.4 因子研究 (Factor Research)

**目的**: 筛选新因子；XGBoost 特征重要性；LLM 候选 funnel。

```bash
# IC 筛选（全 41 个 RESEARCH_FACTORS × 多 horizon）
python scripts/run_factor_screen.py --top 15 --horizon 5 10 21

# XGBoost 特征重要性（permutation + OOS）
python scripts/run_xgb_importance.py

# Ridge vs XGBoost 对比
python scripts/run_model_comparison.py --horizon 21 --top-k 20

# LLM 候选 funnel（给 YAML 候选）
python scripts/llm_factor_propose.py --input research/llm_candidates/round_01/my.yaml

# 候选深度检查（OOS walk-forward + regime + quartile）
python scripts/llm_candidate_deep_check.py \
    --candidate research/llm_candidates/round_01/my.yaml \
    --universe-size 30

# 候选 5-gate 回测
python scripts/llm_candidate_factor_backtest.py \
    --candidate research/llm_candidates/round_01/my.yaml
```

**产出**: `data/ml/` 下各工具对应的 CSV / JSON artifacts。

### 7.5 Universe 管理

**目的**: 扩容 / 审计 / bucket 分配。

```bash
# 检查每个 symbol 的 alpha/beta
python scripts/universe_alpha_diagnostic.py --start 2018-01-01

# 自定义 symbol list 审计
python scripts/universe_alpha_diagnostic.py \
    --symbols "LLY,COST,JNJ,PG,CAT" \
    --out-name my_audit

# v2.2 Layer 1 admission screening
python scripts/universe_admission_screen.py \
    --input-symbols my_candidates.txt --out-tag v3

# v2.2 Layer 2 risk labels
python scripts/universe_risk_labels.py \
    --admission-csv data/ml/universe_admission_v3.csv

# v2.2 Layer 3 bucket assignment
python scripts/universe_bucket_assign.py \
    --labels-csv data/ml/universe_risk_labels_v3.csv

# 手工 universe rebalance (PIT)
python scripts/run_universe_rebalance.py
```

---

## 8. 脚本详细手册

本节是每个主要脚本的 **cheatsheet**。CLI 参数均可用 `--help` 查。

### 8.1 数据管理

#### `fetch_data.py`
- **作用**: 从 yfinance 拉 universe 所有 symbols 的日线 / 日内 OHLCV + 宏观指标
- **何时用**: 首次部署 / 数据久未更新 / 新加 symbol 后
- **关键参数**:
  - `--symbols AAPL MSFT ...`: 只下指定 symbols（否则读 config/universe.yaml）
  - `--full`: 强制全量重下（覆盖现有 parquet）
  - `--daily-only` / `--intraday-only`: 只下某一类
  - `--no-macro`: 跳过 ^VIX/^TNX/DX-Y.NYB 宏观指标
  - `--config-dir`: 指定非默认 config
- **产出**: `data/daily/<SYMBOL>.parquet` + `data/intraday/60m/<SYMBOL>.parquet`

#### `fetch_sp500_pool.py` ⭐ (PRD deep mining R34)
- **作用**: 拉 S&P 500 全体（511 个 active 成分，2 个 delisted 忽略）日线作为 mining candidate pool
- **何时用**: PRD `prd_deep_mining_50round.md` R34；universe 扩容 sourcing
- **注意**: `data/daily/` 已预有 25340 parquets（polygon batch）；此脚本是 S&P 500 specifically 的增量 freshness sync
- **关键参数**:
  - `--incremental` (默认): 只增量 append 新 bars（5-10 min）
  - `--full`: 全量从 2015-01-01 重下
  - `--skip-existing`: 跳过已有 parquet
  - `--limit N`: 测试用，只跑前 N 个
  - `--ticker-list FILE`: 自定义 list（否则从 Wikipedia 拉 S&P 500）
  - `--save-list FILE`: 保存 wiki 拉到的 ticker list 作 reproducibility

#### `build_splits_parquet.py` / `build_bars_parquet.py` / `aggregate_bars.py`
- **作用**: 从本地 polygon 源数据构建 intraday bars
- **何时用**: 已有本地 1m tick/bar 数据，要升级到完整多频率
- **参数**: `--phase all/split/bars/aggregate`, `--workers N`, `--month-only YYYYMM`

### 8.2 回测

#### `run_backtest.py`
- **作用**: 全期回测主脚本
- **关键参数**:
  - `--no-walk-forward`: 跳过 OOS 验证（快 5-10x）
  - `--start YYYY-MM-DD` / `--end YYYY-MM-DD`: 自定义时段
  - `--strategy <name>`: 只跑指定策略（默认跑全部 registered）
  - `--config-dir`: 指定非默认 config 目录
  - `--output-dir`: 覆盖默认 `reports/backtests`
  - `--production-strategy PATH`: 覆盖 M1 单一真源路径（研究用；不要指向 uncommitted 文件）
  - `--ignore-alignment-check`: 跳过 M3 runtime alignment 检查（仅研究；live paper 勿用）
- **产出**: `reports/backtests/backtest/runs/<ts>_backtest/` 下 master_report.md + equity_curve.csv + trades.csv + metrics.json
- **怎么看结果**: master_report 中文报告包含 CAGR / Sharpe / MaxDD / vs SPY / vs QQQ / regime stratification
- **baseline strategy**: `multi_factor` 默认来自 `config/production_strategy.yaml`（PRD M1）；硬编码 weights 已移除
- **启动 log**: 打印 alignment summary + production strategy summary（M3）

#### `run_multi_tf_backtest.py`
- **作用**: 多时间尺度（60m + 30m + 15m）timing layer 回测
- **何时用**: 研究 multi-TF timing 是否改善 entry 质量
- **参数**: `--use-timing`, `--factor-bucket`, `--validate-timing-value`

### 8.3 挖掘

#### `run_mining.py` ⭐ 最常用
- **作用**: Optuna + StrategyMiner + MiningEvaluator 找最佳参数
- **关键参数**:
  - `--type multi_factor/dual_momentum/trend_following/cross_asset_rotation`
  - `--trials N`（Optuna trials per type; 30 快, 80+ 大搜）
  - `--budget SECONDS`（时间预算）
  - `--lineage-tag TAG`（archive 里打标签）
  - `--leaderboard` / `--lineage-filter TAG`
  - `--reset-archive`（清空重来，**小心**）
  - `--extra-symbols FILE`（在 config universe 基础上加 symbols，不改 config）
- **产出**: `data/mining/archive.db` 逐 trial 全指标
- **读结果**:
  ```bash
  python scripts/run_mining.py --leaderboard --lineage-filter 'my_tag'
  # 重点看: tier (S/A/B/C/D), oos_ir (需 ≥ 0.20), passed_qqq_gate
  ```

### 8.4 因子研究

#### `run_factor_screen.py`
- **作用**: 所有 factor_generator 输出的因子 × 多 horizon 的 IC + t_stat + p_value
- **参数**: `--top N`, `--horizon D` (5/10/21)
- **产出**: 排行榜 stdout；可 pipe 到 CSV

#### `run_xgb_importance.py`
- **作用**: 真正 XGBoost + permutation importance（OOS）
- **产出**: `data/ml/xgb_importance.parquet` + run_summary.md

#### `run_model_comparison.py`
- **作用**: Ridge vs XGBoost 对比，揭示线性 vs 非线性信号量
- **产出**: `data/ml/ridge_perm_importance.parquet`, `xgb_perm_importance.parquet`

#### `run_llm_cross_signal_mining.py`
- **作用**: 所有 LLM 候选 + classical factors 一起喂 Ridge/XGBoost，看 LLM 候选是否进 top-20
- **CLI**: `--horizon 21 --top-k 20 [--no-llm | --llm-only]`

#### `run_factor_interaction_mine.py`
- **作用**: Top-K 因子的 pairwise 交互，按 incremental IC 排
- **参数**: `--top-k 8 --out-top 10 --horizon 21`

### 8.5 LLM 候选 funnel

#### `llm_factor_propose.py`
- **作用**: LLM 候选（YAML）通过 shape → leakage → dedup → IC 漏斗
- **Input**: `research/llm_candidates/round_XX/<name>.yaml`
- **产出**: `data/ml/llm_candidates/<name>/verdict.json`
- **可能 verdict**: REJECT / ARCHIVE / NEEDS_HUMAN_REVIEW

#### `llm_candidate_deep_check.py`
- **作用**: PRD §5.4 reverse review 自动化：OOS walk-forward + regime 6-class + time quartile
- **过则标记**: PASS（ARCHIVE → NEEDS_HUMAN_REVIEW 升级候选）

#### `llm_candidate_factor_backtest.py`
- **作用**: 单因子简化 backtest + 5-gate verdict (cost, QQQ full, QQQ holdout, MaxDD abs, MaxDD rel)

#### `llm_composite_backtest.py`
- **作用**: 多因子 composite 自定义权重的 backtest
- **CLI**: `--components "drawup:0.3,vol_63d:-0.3,spy_trend_200d:0.4"`

#### `llm_candidate_orthogonalization.py`
- **作用**: 候选 vs 既有因子正交化；判断 incremental IC（LOW/MEDIUM/HIGH）

### 8.6 Universe 扩容

#### `universe_alpha_diagnostic.py`
- **作用**: 每 symbol 的 CAPM β / α / 分类（ALPHA_GENERATOR / BETA_PLUS_ALPHA / MARKET_LIKE / DIVERSIFIER / PURE_BETA）
- **参数**: `--symbols "ABBV,UNH,..."` 自定义 list; `--start`, `--out-name`

#### `universe_admission_screen.py`
- **作用**: v2.2 Layer 1 objective-only 准入（security type / liquidity / mcap / history）
- **参数**: `--input-symbols FILE` / `--all-local` / `--out-tag TAG`

#### `universe_risk_labels.py`
- **作用**: v2.2 Layer 2 metadata（beta_spy/qqq 252d/504d, alpha_positive_rate_rolling, subperiod consistency, tail_correlation_to_spy, 等）
- **参数**: `--admission-csv FILE` 消费 Layer 1 输出

#### `universe_bucket_assign.py`
- **作用**: v2.2 Layer 3 bucket 分配（Alpha Core / Diversifier / Tactical / Proxy / Unscored）
- **注意**: 当前是 **provisional intrinsic-only** 版本（见 spec §4.6）

#### `universe_risk_profile.py` ⭐ (deep-mining R37 新增)
- **作用**: 简化 pipeline — 直接合并 alpha diagnostic + admission screen 一步产出 priority_bucket（CORE_ALPHA / SATELLITE_ALPHA / DIVERSIFIER_PREMIUM / DIVERSIFIER_BASIC / REVIEW / EXCLUDE）
- **与 `universe_risk_labels.py` 差异**: risk_labels 产 Layer 2 完整 metadata（betas/alphas/tail_corr/subperiod consistency）；risk_profile 只做 Layer 2+3 的最简合并 + bucket 分配
- **CLI**: `--alpha-csv <path> --admission-csv <path> --out-tag <tag>`
- **产出**: `data/ml/universe_risk_profile_<tag>.csv` + `_summary.json`

#### `run_universe_rebalance.py`
- **作用**: PIT universe rebalance（跑完整 UniverseManager + AssetScorer，产出建议调整）
- **何时用**: 季度 / 半年度 universe 复审；`bash scripts/run_all.sh universe` 的 entry

#### `r33_weight_grid_search.py`
- **作用**: 手工 grid 搜 MultiFactorStrategy 权重，找 CAGR > QQQ 组合（R33 解 xfail 时建立）

### 8.7 模拟盘 / Live

#### `run_paper.py`
- **作用**: PaperTradingEngine 入口
- **CLI modes**: `live` / `replay` / `status`（默认 `status`）
- **Live**: 当日 EOD 后跑一次；engine 内部按数据可得性自动走 intraday bar-by-bar 或 daily fallback；idempotent 断点续传
- **Replay**: `--from-date` / `--to-date` 历史回放，结果**带 bias 警告**仅作 diagnostic
- **Status**: 只打印当前 DB 里的持仓 / cash / equity
- **可选**: `--use-timing` 启用 multi-TF timing layer（实验性，默认关）
- **Strategy source**: 从 `config/production_strategy.yaml`（PRD M1）读；**不接受** `--production-strategy` override — paper trading fail loud on missing / invalid artifact
- **Alignment check (M3)**: 启动时比对 yaml fingerprints 与当前 universe/factor_registry/config hashes，WARN 模式（非 status mode 都会跑）；`--ignore-alignment-check` 跳过

### 8.8 报告

#### `generate_report.py`
- **作用**: 综合 master_report 生成
- **默认读**: 最新回测 + archive leaderboard

### 8.9 工具

#### `acceptance_pack.py` ⭐ (PRD M2)
- **作用**: 对 archive 中某 spec_id 跑 10-gate acceptance pack，产 JSON artifact
- **CLI**: `--spec-id <id|prefix> --out-dir <dir> --verbose`
- **产出**: `artifacts/acceptance_packs/acceptance_<id>_<ts>.json`
- **Exit code**: 0 if all pass, 1 if any fail
- **不改** `config/production_strategy.yaml`，只读；见 `promote_strategy.py` 做 promote

#### `promote_strategy.py` ⭐ (PRD M2)
- **作用**: mining archive 到 production 的显式 promote 入口
- **CLI**:
  - `--spec-id <id|prefix>` 指定 candidate
  - `--dry-run`: 显示 proposed yaml + diff，不写入
  - `--promote`: 实际写入（acceptance pack 必须 PASS，否则拒绝）
  - `--force --yes-i-know-what-im-doing`: emergency override（不推荐）
  - `--rationale "..."`: 记录 promote 原因
- **产出**: 重写 `config/production_strategy.yaml` 为 `status: active`（需后续 `git commit` 生效）
- **完整流程**: 见 `docs/20260421-promotion_flow.md`

#### `send_round_summary.py`
- **作用**: 每轮研究总结发微信 / Server 酱
- **依赖**: `PQS_WECOM_WEBHOOK_URL` 或 `PQS_SCT_SEND_KEY` 环境变量
- **CLI**: `--title "..." --file path/to/log.md --last-section`

#### `dump_llm_handoff_context.py` ⭐ (PRD M15 reframed)
- **作用**: 产出"喂给外部 LLM（Gemini/Codex/任意）的 context pack"markdown 文件
- **内容**: PRODUCTION_FACTORS + RESEARCH_FACTORS + 最近 candidates + universe + regime 分布 + YAML schema + 使用指南
- **CLI**: `--out path.md --lookback-days 252 --n-recent-candidates 10`
- **产出**: `docs/llm_handoff_seed_<ts>.md`（gitignored，每次 fresh dump）
- **用法**:
  1. 跑此脚本
  2. 打开产出 .md，复制 `--- PASTE TO LLM BELOW ---` 到 `ABOVE` 之间的内容
  3. 粘到 Gemini / Codex 对话，要求 "生成 N 个 candidates YAMLs"
  4. 手动落盘到 `research/llm_candidates/round_NN/<name>.yaml`（见 `docs/20260421-llm_external_llm_handoff.md` 规则）
  5. `git commit` —— Claude 下次 session 会自动 funnel 这些 candidates

#### `build_research_baseline_snapshot.py` ⭐ (PRD M0, 新增)
- **作用**: 生成 `data/baseline/snapshot_<ts>.json` + `latest.json`，含 git SHA / pytest count / archive lineage 统计 / config hash / factor registry hash / universe hash / production strategy status
- **何时用**: 每次研究前/后对比；PR 前跑；替代文档里硬写的测试数
- **CLI**:
  - `--run-tests`: 也跑完整 `pytest -q` (~90s)；默认只 collect count (~1.5s)
  - `--out-dir`: 默认 `data/baseline/`
  - `--stdout`: 额外打印到 stdout
- **读结果**: `jq '.tests, .git, .archive' data/baseline/latest.json`

#### `demo_cross_ticker_rules.py` (PRD M4 demo)
- **作用**: 把 `config/cross_ticker_rules.yaml` 的规则应用到当前生产策略产出的权重上，展示 before/after 差异
- **CLI**: `--start 2024-01-02 --end 2024-12-31 --rules-file <path>`
- **Demo 观测**: 2022 年窗口 66/251 dates 被规则触发（26%），2024 年全 BULL 触发率低
- **不修改生产**；研究演示 tool

### 8.10 ML / Research (PRD M7 / M8)

#### `run_xgb_weight_model.py` (PRD M7, research-only)
- **作用**: 用 XGBoost 从 factor panel 产生 per-(date,symbol) score，转 top-K 等权 weight，对比 equal-weight baseline
- **CLI**: `--horizon 21 --top-k 5 --split-frac 0.8 --out-tag mytest`
- **产出**: `data/ml/xgb_weights/<tag>/` 含 `summary.json` + `xgb_weights.parquet` + `xgb_equity.parquet` + `baseline_equity.parquet`
- **不进 production**；仅研究 artifact

#### `run_transformer_research.py` (PRD M8 Phase 1, research-only)
- **作用**: 小 transformer encoder（1-layer, ~50k 参数）vs Ridge vs XGBoost 的 OOS R² head-to-head benchmark
- **硬限制**: daily horizon only, seq_len ≤ 63, 训练时间 cap 30min，GPU→CPU fallback
- **依赖**: `pip install -r requirements-gpu.txt`（torch 可选；torch 未装时只跑 Ridge+XGB）
- **CLI**: `--horizon 21 --seq-len 63 --epochs 5 --cpu`（`--cpu` 强制 CPU）
- **产出**: `data/ml/transformer/<tag>/summary.json`

### 8.11 Multi-TF timing / validation

#### `validate_timing_value.py`
- **作用**: 量化 multi-TF timing layer 的入场质量 vs naive baseline（entry bps vs day mean, defer rate, scale distribution）
- **参数**: `--factor-bucket <name>` 按因子值 tercile 做 cross-sectional 对比

#### `validate_combo_tfs.py` / `validate_combo_costs.py` / `validate_single_tf.py`
- **作用**: multi-TF 组合 / 成本敏感性 / 单 TF IC 研究工具

#### `compare_multi_factor_shift.py`
- **作用**: 诊断 `apply_extra_shift` 对 MFS 信号的 T-1 vs T-2 差异（P0.1 fix 后工具）

### 8.12 数据 provenance / QA

#### `trades_scanner.py` + `consolidate_trades.py` + `consolidate_sanity_check.py`
- **作用**: 从 zip'd polygon trades 源数据解密 + tick → 1m bar
- **Heavy tool**: 用于历史深度数据补全，常规不碰
- **产出**: data/intraday/1m/*.parquet + data/ref/bar_provenance.parquet

#### `scanner_sequential_2026_2025.py` / `scanner_chain_2024_to_2025.py` / `scanner_terminator.py`
- **作用**: 多年度 scanner 链路编排 + 年末完结 gate；配合 trades_scanner 跑长期数据回补

#### `disk_guard.py`
- **作用**: 监控 `/mnt/c` 空间，低于阈值时结束 Baidu Netdisk 防止爆盘

#### `post_processing_pipeline.py`
- **作用**: trades_backfill 完成后的 consolidation + sanity check 端到端编排

#### `migrate_provenance.py`
- **作用**: bar provenance sidecar schema 迁移

### 8.12 批量任务

#### `run_all.sh`
```bash
bash scripts/run_all.sh full           # 数据 + 回测 + 报告
bash scripts/run_all.sh research       # 全研究流程（fetch + universe + factors + backtest + xgb）
bash scripts/run_all.sh daily          # 增量行情 + live paper + 日报
bash scripts/run_all.sh mine           # Optuna 挖掘 (1h, 80 trials)
bash scripts/run_all.sh mine-long      # Optuna 挖掘 (4h, 200 trials)
bash scripts/run_all.sh fetch-only     # 只下数据
bash scripts/run_all.sh backtest-only  # 只回测（不下数据）
bash scripts/run_all.sh backtest-quick # 只回测 + 跳 walk-forward
bash scripts/run_all.sh replay [DATE]  # 历史回放（默认 2024-01-02 起）
bash scripts/run_all.sh universe       # universe rebalance
bash scripts/run_all.sh factors        # IC screening
bash scripts/run_all.sh xgb            # feature importance
bash scripts/run_all.sh leaderboard    # mining 排名
bash scripts/run_all.sh status         # paper trading 当前状态
bash scripts/run_all.sh check          # 环境自检
```

---

## 9. 配置文件说明

所有配置均为 pydantic-验证 YAML。改了后跑 pytest 先保证无回归。

### 9.1 `system.yaml`
```yaml
env: local
project_name: pqs
version: "0.1.0"

paths:
  data_dir: data
  reports_dir: reports
  config_dir: config
  db_path: data/trading.db

logging:
  level: INFO
  log_to_file: true
  log_file_name: pqs.log

account:
  initial_capital_usd: 100000.0   # 2026-04-20 从 $10k 升到 $100k，避免
                                   # integer_shares 下 $10k + SPY $700
                                   # 导致单 symbol 过度集中
  currency: USD
  timezone: America/New_York

alignment:                         # PRD M3 runtime alignment check
  mode: warn                       # warn | strict — 不一致时如何处理
  live_only_fail: true             # paper live 下不一致直接 abort
```
⚠️ 注：`initial_capital_usd` 已调整为 `$100k`（与 §2 约束 11 "初始 $10k"
的文档 drift；实际跑 mining / backtest 都用 $100k 以避免 integer-shares
rounding 噪声主导指标）。

### 9.2 `universe.yaml` ⭐ 重要
- `seed_pool`: 主交易 universe（common stocks + leveraged + benchmarks）
- `sector_etfs`: 11 SPDR 板块 ETFs (XLK/XLF/...)
- `factor_etfs`: 5 因子 ETFs (MTUM/QUAL/VLUE/USMV/SCHD)
- `cross_asset`: 4 跨资产 (TLT/IEF/SHY/SLV)
- `macro_reference`: 不交易，只做 features 用 (^VIX/^TNX/DX-Y.NYB)
- `blacklist`: 黑名单 (SQQQ/SOXS)
- `data_sensitivity`: volume-sensitive factors（trades_backfill 源头 volume 语义不同）
- `first_trade_dates`: PIT 样本起始日

**two-layer 概念**:
- Execution universe (本 yaml) — 含 ETF/leveraged
- Admission whitelist (v2.2 spec) — common stock only，仅 expansion 筛选用

### 9.3 `backtest.yaml`
```yaml
benchmarks: [SPY, QQQ]
primary_benchmark: SPY
start_date: "2007-01-02"     # 覆盖 2008-09 危机用于 stress
end_date: null               # null → 用最新数据

window_analysis:
  enabled: true
  walk_forward_train_bars: 756     # 3 年训练
  walk_forward_test_bars: 126      # 6 月测试
  forward_block_holdout_bars: 252  # 最后 1 年 holdout

# 注：原 `validation:` 块（Tier D promote 门槛）已迁出 backtest.yaml；
# 现位于独立的 `config/acceptance.yaml`（threshold unification 2026-04-28，
# **完整说明在本文档 §9.11**, schema 在 `core.config.schemas.acceptance.AcceptanceThresholds`）。

mining:                      # Mining 6-stage funnel 阈值
  quick_min_sharpe: 0.30
  quick_max_drawdown: 0.40
  quick_min_cagr: 0.02
  oos_min_pass_rate: 0.55
  oos_min_ir_vs_benchmark: 0.20    # R17 "不降标准" 门槛
  oos_min_excess_return: 0.02
  regime_robust_min_regimes: 2
  cost_robust_multiplier: 2.0
```
💡 注：`initial_capital_usd` 在 **system.yaml** 而不是 backtest.yaml。

### 9.4 `risk.yaml`
```yaml
# Hard constraints
long_only: true
allow_margin: false
allow_short: false
max_gross_exposure: 1.0

drawdown_limits:                  # 不是 kill_switch，字段扁平
  warning_pct: 0.10               # → WARNING
  reduce_pct: 0.15                # → REDUCE (50% cash)
  defensive_pct: 0.20             # → DEFENSIVE (SPY + cash only)
  halt_pct: 0.25                  # → HALT (human review)
  max_drawdown_vs_benchmark_multiplier: 1.5
  single_crisis_drawdown_cap: 0.25

position_limits:
  max_single_position: 0.35       # **非 0.10**; 部分 symbol 如 SPY 可到 0.35
  max_positions: 10
  min_position_size_usd: 500.0
  allow_fractional_shares: false
  symbol_caps:
    SPY: 0.35
    QQQ: 0.30
    GLD: 0.20
    # ... (per-symbol 覆盖 max_single_position)

budget:                           # 按 bucket 分配
  core:     0.58                  # SPY, QQQ, GLD
  tactical: 0.27                  # Mag7
  enhancer: 0.10                  # TQQQ, SOXL (仅 RISK_ON/BULL)

left_side_trading:
  enabled: false
  allowed_regimes: [RISK_OFF]
  # ...

strategy_concentration:
  soft_cap_max_single: 0.15
  concentration_warn_threshold: 0.30

factor_registry:
  strict_mode: false              # WARN+drop vs raise on unknown names

intraday_timing:
  min_timing_scale: 0.0
  execute_threshold: 0.15
  # ... (60m/30m/15m thresholds)
```

### 9.5 `cost_model.yaml`

分 tier 的滑点 + 佣金（单位 bps; 1 bps = 0.01%）。本节列**全部字段**便于 ctrl-F；
研究 / 调阈值时直接参考当前文件即可（值会随研究迭代）。

```yaml
mode: bps_based                   # 当前唯一 mode
vix_stress_threshold: 30.0        # VIX ≥ 30 时启用 stress multiplier
stress_slippage_multiplier: 2.5   # slippage × 2.5 当 VIX 越线

tiers:
  liquid_etf:                     # 宽 ETF（最低成本档）
    symbols: [SPY, QQQ, GLD, IWM, XLK, XLF, XLE, XLV, XLI, XLY, XLP, XLU, XLB]
    commission_bps: 0.5
    slippage_interday_bps: 4
    slippage_intraday_bps: 7

  large_cap_equity:               # Mag7 + 其它大 cap common stock
    symbols: [AAPL, MSFT, GOOGL, GOOG, AMZN, META, NVDA, TSLA, BRK-B, JPM, V, MA]
    commission_bps: 0.5
    slippage_interday_bps: 6
    slippage_intraday_bps: 10

  leveraged_etf:                  # 3x 杠杆 ETF（最高成本档）
    symbols: [TQQQ, SOXL, UPRO, SPXL, TECL]
    commission_bps: 1.0
    slippage_interday_bps: 12
    slippage_intraday_bps: 20

  default:                        # fallback：未匹配上面三档的 ticker
    symbols: []
    commission_bps: 1.0
    slippage_interday_bps: 8
    slippage_intraday_bps: 12

capacity_model:                   # 资金体量影响（v1 disabled，预留 hook）
  enabled: false
  threshold_usd: 500000           # 单笔超过此 USD 触发 impact 加成
  impact_bps_per_100k: 1.0        # 每 100k 加 1 bp slippage
```

**字段索引**:
- `mode` (str): 当前唯一值 `bps_based`
- `vix_stress_threshold` (float): VIX 阈值，跨过启用 stress
- `stress_slippage_multiplier` (float): stress 模式下 slippage 放大倍数
- `tiers` (dict): 4 个 tier — `liquid_etf` / `large_cap_equity` / `leveraged_etf` / `default`
  - 每个 tier 有 `symbols` (list) + `commission_bps` + `slippage_interday_bps` + `slippage_intraday_bps`
- `capacity_model.enabled` (bool): v1 默认 false；启用后超过 `threshold_usd` 的下单按 `impact_bps_per_100k` 累加 slippage

### 9.6 `regime.yaml`
6 状态分类：BULL / RISK_ON / NEUTRAL / CAUTIOUS / RISK_OFF / CRISIS

```yaml
spy_ema_fast: 50
spy_ema_slow: 200
vix_symbol: "^VIX"
tnx_symbol: "^TNX"
tnx_spike_threshold: 0.15        # 10Y yield 单日升 ≥ 15bp → 最低 CAUTIOUS
smoothing_window: 3              # 连续 N bar 才确认，防跳

vix_thresholds:                   # 嵌套 dict，**不是**顶层 bull_thr
  bull:     15.0
  risk_on:  20.0
  neutral:  25.0
  cautious: 30.0
  risk_off: 35.0
  crisis:   45.0

drawdown_thresholds:              # SPY 52w drawdown 触发
  cautious: -0.05
  risk_off: -0.10
  crisis:   -0.20

position_constraints:             # 每 regime 单独覆盖
  BULL:
    target_cash_pct_min: 0.00
    target_cash_pct_max: 0.10
  # ...
```

### 9.7 `notify.yaml`
```yaml
notify:
  enabled: true
  backend: wecom_bot       # wecom_bot | server_chan | stdout | null
  wecom_bot:
    webhook_url: "${PQS_WECOM_WEBHOOK_URL}"
  server_chan:
    send_key: "${PQS_SCT_SEND_KEY}"
```

### 9.8 `reporting.yaml`, `events.yaml`
风格 / 事件日历，通常不碰。

### 9.9 `cross_ticker_rules.yaml` (PRD M4, M10 production-integrated)

跨标的声明式 DSL。`enabled: true` 时 `run_backtest.py` + `run_paper.py` 启动默认应用（M10）。R24 加入 2 条新规则后共 **5 rules**。R23 A/B 测试证明 +2.3pt CAGR alpha；R25 stress 揭示 Rule 2/5 在 2020 COVID V-recovery 下有非对称伤害（user decision pending）。

```yaml
enabled: true
rules:
  # Rule 1 — SPY trend gates Mag7 放大 1.20x
  - name: spy_golden_cross_enables_tech_overweight
    type: benchmark_trigger
    driver: SPY
    condition: "sma(close, 50) > sma(close, 200)"
    targets: [QQQ, TQQQ, SOXL, NVDA, AAPL, MSFT, META, GOOGL, AMZN, TSLA]
    action: allow_overweight
    weight_multiplier: 1.20
    regime_scope: [BULL, RISK_ON, NEUTRAL]
    priority: 10

  # Rule 2 — RISK_OFF/CRISIS → 50/50 defensive basket (⚠ R25 asymmetric caveat)
  - name: defensive_blend_risk_off
    type: regime_basket
    regime: [RISK_OFF, CRISIS]
    basket_weights: {TLT: 0.25, IEF: 0.15, GLD: 0.25, SHY: 0.15, JNJ: 0.10, PG: 0.10}
    override_strategy: false
    priority: 20

  # Rule 3 — QQQ breakout confirmed by XLK → 1.15x timing scale
  - name: qqq_breakout_confirmed_by_xlk
    type: multi_tf_confirmation
    target: QQQ
    primary_condition: "close > ref_high(20)"
    confirmations:
      - {symbol: XLK, timeframe: daily, condition: "sma(close, 5) > sma(close, 20)"}
    action: {timing_scale_multiplier: 1.15}
    priority: 30

  # Rule 4 (R24) — TQQQ 严审：dual benchmark (SPY + XLK) 才允许
  - name: leveraged_etfs_dual_confirmation
    type: multi_tf_confirmation
    target: TQQQ
    primary_condition: "sma(close, 50) > sma(close, 200)"
    confirmations:
      - {symbol: SPY, timeframe: daily, condition: "sma(close, 50) > sma(close, 200)"}
      - {symbol: XLK, timeframe: daily, condition: "sma(close, 20) > sma(close, 50)"}
    action: {timing_scale_multiplier: 1.10}
    regime_scope: [BULL, RISK_ON]
    priority: 40

  # Rule 5 (R24) — XLU outperformance → defensive rotation (⚠ R25 asymmetric)
  - name: xlu_outperformance_signals_defensive_rotation
    type: benchmark_trigger
    driver: XLU
    condition: "close > sma(close, 5) and sma(close, 21) > sma(close, 50)"
    action: allow_overweight
    targets: [XLU, XLP, TLT, GLD, JNJ]
    weight_multiplier: 1.10
    regime_scope: [CAUTIOUS, RISK_OFF, NEUTRAL]
    priority: 25
```

**Expression DSL 安全约束**（`core/signals/cross_ticker_rules.py` 白名单）:
- 函数白名单: `sma / ema / ref_high / ref_low / rsi` — 其他函数 REJECT
- 字段白名单: `open / high / low / close / volume`
- 逻辑: `and / or / not`
- **禁止任何 Python eval 构造**（import / exec / attribute access 直接 REJECT）

### 9.10 `production_strategy.yaml` ⭐ (PRD M1 单一真源)

这是**唯一** 的生产策略定义文件。`run_backtest.py` / `run_paper.py` /
`run_multi_tf_backtest.py` / 集成测试都从这里读，**禁止硬编码
factor_weights**（CI 会测试拒绝）。

**Lifecycle 三态**:
- `active` —— 通过 M2 promote CLI 产出，`source.spec_id` 必填，`validation.*`
  全 true，`fingerprints.*` 全填
- `conservative_default` —— 当前状态。没有 post-fix validated best，用最好
  已知手工 calibration（R33 grid-best 权重）。backtest / research 可跑，
  paper live 跑但 M3 alignment 会 WARN
- `no_validated_best` —— 更强声明；backtest baseline 直接拒绝运行 `multi_factor`
  （需 `--strategy X` / `--production-strategy PATH` override）

**关键字段**:
```yaml
status: "conservative_default"
strategy_type: "multi_factor"
source:
  mode: "manual"                  # manual | promoted_from_archive
  spec_id: ""                     # archive.trials.spec_id (active 时必填)
  lineage_tag: ""
  promoted_at: ""
  rationale: "R33 grid-best ..."
params:                           # MultiFactorStrategy.__init__ 参数
  top_n: 4
  rebalance_monthly: false
  ...
factor_weights:                   # 必 sum==1.0，名字必在 PRODUCTION_FACTORS
  low_vol: 0.15
  ...
validation:                       # M2 promote 后才会全 true
  post_fix_validated: false
  passed_oos_gate: false
  passed_qqq_gate: false
  passed_paper_backtest_alignment: false
fingerprints:                     # M3 runtime alignment check 用
  universe_hash: ""
  factor_registry_hash: ""
  config_hash: ""
```

**怎么改**:
- 改权重 / params → 直接编辑 yaml + pytest 验证 schema
- `conservative_default → active` 必须走 M2 `scripts/promote_strategy.py`，
  **禁止**手工改 status
- CI `test_single_source_of_truth.py` 守护不可回退到硬编码

### 9.11 `acceptance.yaml` (PRD threshold unification, 2026-04-28)

```yaml
# 单一真源：Tier D / walk-forward / factor-tier 阈值。
# Loader: cfg.acceptance.{tier_d, walk_forward, factor_tiers}.
# Schema: core/config/schemas/acceptance.py::AcceptanceThresholds（嵌套 3 个
# submodel + extra=forbid，typo 立即 fail）。
tier_d:                       # WindowAnalyzer.acceptance_check 消费（live）
  min_excess_return_vs_spy: 0.05
  min_ir_vs_spy: 0.30
  max_dd_vs_spy_multiplier: 1.50

walk_forward:                 # OOS / walk-forward 验收（截至 2026-04-29 仅 1 字段 live）
  min_oos_vs_is_return_ratio: 0.50           # placeholder（未接 consumer）
  min_windows_positive_excess_pct: 0.60      # LIVE：WindowAnalyzer.oos_consistency_check
  auto_fail_single_period_contribution: 0.50 # placeholder
  auto_fail_single_asset_contribution: 0.40  # placeholder
  auto_fail_crisis_vs_benchmark_multiplier: 2.0  # placeholder
  max_crisis_drawdown_abs: 0.25              # placeholder

factor_tiers:                 # factor_evaluator._auto_tier 消费（live）
  s_min_ir: 0.80
  a_min_ir: 0.50
  b_min_ir: 0.30
  c_min_ir: 0.10
```

**消费路径**:
- `scripts/run_backtest.py` → `WindowAnalyzer(thresholds=cfg.acceptance)` 和 `WindowAnalyzer.oos_consistency_check(thresholds=cfg.acceptance)`
- `scripts/run_mining.py` → `MiningEvaluator(acceptance_thresholds=cfg.acceptance)` → 内部 `WindowAnalyzer`
- 任何外部调用方：`FactorEvaluator(thresholds=cfg.acceptance)` → 自动覆盖 `FactorReport.tier`

**Placeholder 字段**: `walk_forward.*` 中除 `min_windows_positive_excess_pct` 外的 5 个字段是 codex round-13 §"Decision 1" 留下的 future-PRD 占位 — schema 已就位，未来 wire 它们的 PRD 直接 consume `cfg.acceptance.walk_forward.*` 即可，不需要再迁 schema。

**不在范围**:
- `acceptance_pack._THRESHOLDS`（`core/mining/acceptance_pack.py`）— 已 promote artifact 的稳定 contract，**不**自动同步 `AcceptanceThresholds`。修改需走 versioned recalibration PRD（codex round-13 §"Decision 3"）。
- mining 6-stage funnel 阈值（`config/backtest.yaml::mining`）— 不在 acceptance 层。
- 6 regime 阈值（`config/regime.yaml`）、Kill switch 阈值（`config/risk.yaml::drawdown_limits`）。

### 9.12 `temporal_split.yaml` ⭐ (Track A, PRD `20260429-temporal_split_holdout_discipline_prd.md` v1.1)

Track A 的核心 config: 训练/验证/sealed 三段切分 + 角色门 + stress slices。

```yaml
split_name: alternating_regime_holdout_v1   # immutable until new PRD bumps name
description: "alternating-regime holdout split (R1.1)"

train_years:        [2009, 2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2020, 2022, 2024]
validation_years:   [2018, 2019, 2021, 2023, 2025]   # 2025 是 hard gate (core role)
sealed_years:       [2026]                            # single-shot, do NOT touch

stress_slices:                                       # borrowed for MaxDD sanity only
  covid_flash:      {start: "2020-02-19", end: "2020-04-07", maxdd_threshold: 0.25}
  rate_hike_2022:   {start: "2022-01-03", end: "2022-10-14", maxdd_threshold: 0.25}

roles:
  core:        validation_gates: [excess_vs_qqq > 0, maxdd <= 0.20]   # 2025 HARD
  diversifier: validation_gates: [excess_vs_qqq > -0.05, maxdd <= 0.18]
               eligibility:     [vs_existing_core_correlation < 0.40]

acceptance:
  validation_year_pass.maxdd_per_year_max: 0.20
  stress_slice_pass.maxdd_per_slice_max:    0.25
  cost_robustness.multiplier_2x_must_remain_positive: true
```

**关键约束**:
- `split_name` 一旦发版**不可改**；改 split 要 bump 名字开新 PRD
- C5 role-remint guard: 同一 `(spec_sha, split_name)` 不能在不同 role 复审；
  same-role 决定性 rerun 允许但需在 evidence pack §4.2 披露
- 2025 是 holdout hard gate；2026 sealed eval 是 single-shot 最后审

**消费路径**: `core/research/temporal_split.py::load_temporal_split()` →
`scripts/run_research_miner.py --temporal-split --role=core`

### 9.13 `fleet.yaml` ⭐ (Track B Steps 1-5)

Track B FleetAllocator 当前 config:

```yaml
candidates:                                    # current legacy candidates (NAV-correlated, see §1.4)
  - {candidate_id: rcm_v1_defensive_composite_01, role: core, base_weight: 0.5}
  - {candidate_id: candidate_2_orthogonal_01,    role: core, base_weight: 0.5}

split_policy: equal_weight                     # equal_weight | manual_overrides

# Step 5 — C2 correlation budget (codex R30 accepted)
max_pairwise_corr_warn:    0.70                # pairwise on realized daily returns
max_pairwise_corr_reject:  0.85                # blocks composition
corr_lookback_days:        252
corr_min_overlap_days:     60                  # below this → status=insufficient_data

# Step 4 — C3 overlap throttle
max_fleet_symbol_weight:   0.20

# Step 6+ schema only (codex-frozen until explicit-go)
core_min_capital_pct:        0.60
satellite_max_capital_pct:   0.40
dd_throttle:    {warning_pct: 0.10, defensive_pct: 0.15, halt_pct: 0.20, ...}
removal_rules:  {forward_decision_fail: true, pairwise_corr_above: 0.95, ...}
parking_rules:  {m12_thin_data_extreme: 0.10}
```

**当前实际效用**: equal_weight 组合 RCMv1 + Cand-2 — 2026-04-30 NAV-correlation
0.898 已表明**不产生 diversification**（详 §1.4 + `docs/memos/20260430-rcmv1_cand2_realized_correlation.md`）。
两 candidate 保留为 legacy decay verification observation；fleet 真正 wiring 等
Track C 出 NAV-orthogonal candidate。

**消费路径**: `core/fleet/allocator.py::FleetAllocator` →
`alloc.check_correlation_budget(returns_df)` 返回 `CorrelationBudgetStatus(level=warn|reject|ok|insufficient_data, pairs=[...])`。

### 9.14 `research_mask.yaml` (factor research panel)

```yaml
min_price:           5.0      # exclude penny stocks from research panel
min_usd_volume:      20_000_000
rolling_window_days: 20
implementation:      core/factors/base_masks.py::research_mask_default
```

**何时影响什么**:
- factor IC / OOS / regime research 跑前 mask 一次
- backtest 不用此 mask（backtest 直接读 universe.yaml）
- 改这里不改 universe；只影响 factor research 的 effective panel

---

## 10. 关键概念

### 10.1 Factor

**Factor** = 对每 (date, symbol) 打分的 DataFrame。
- **RESEARCH_FACTORS** (64): 由 `core/factors/factor_generator.py::generate_all_factors` 输出，研究用
- **PRODUCTION_FACTORS** (7): 由 `MultiFactorStrategy.generate()` inline 计算，生产用
- 二者通过 `core/factors/factor_registry.py` 强一致（测试 `test_factor_registry.py` 把关）

当前 PRODUCTION 7 个:
1. low_vol (负滚动标准差)
2. momentum (长/短期收益差)
3. quality (年化 Sharpe 代理)
4. pv_div (price-volume divergence)
5. rel_strength (63d 超额 SPY)
6. market_trend (SPY vs 200d MA)
7. **drawup_from_252d_low** (R15 user-auth promoted, LLM-generated; R42/R43 5-fold CV 下 rank #27/35 作 counter-evidence 记入 R50 user decision list)

近期新增 RESEARCH factors (2026-04-22 deep-mining):
- `spy_trend_gated_mom_63d` (R7 Claude, XGB rank #12)
- `weak_market_relative_strength_63d` (R10 Gemini/Codex, XGB rank #8 / 负系数)

### 10.2 Strategy

4 种 registered strategies:
1. **MultiFactorStrategy** (MFS) — 主力，composite from PRODUCTION_FACTORS
2. **DualMomentumStrategy** (DM) — 相对强度 + 绝对动量
3. **TrendFollowingStrategy** — 趋势追随
4. **CrossAssetRotationStrategy** — 股债轮动

### 10.3 Mining 6-stage funnel

每个 trial 在 `core/mining/evaluator.py::evaluate()` 经过 6 个 gate，对应
6 个 `passed_*` flags：
1. **Quick** (`passed_quick`) — full-period backtest, 过 Sharpe ≥ 0.30 / CAGR ≥ 0.02 / MaxDD ≤ 0.40
2. **OOS walk-forward** (`passed_oos`) — rolling windows, IR ≥ 0.20, pass_rate ≥ 0.55, excess ≥ 0.02
3. **Robustness** (`passed_robustness`) — regime (6 states) + cost (2x) + stress + subperiod 全过
4. **Diversity** (`passed_diversity`) — 与 promoted 策略相关 ≤ 0.70
5. **Holdout** (`passed_holdout`) — 最后 252d forward-block
6. **QQQ hard gate** (`passed_qqq_gate`, R15+) — CAGR > QQQ (full + holdout + OOS avg)

全过 → promote 到 tier ≠ D；未过 OOS 自动 tier D，后续 gate 不检测。

### 10.4 Tier 分级

| Tier | 严格定义 | 含义 | 决策建议 |
|---|---|---|---|
| **S** | 全部 6 stage 过 + OOS IR top-decile（archive 里前 10%） | 推荐主力 | 走 acceptance pack → promote |
| **A** | 全部 6 stage 过 | 推荐 | 走 acceptance pack（10 gate 跑了再决定） |
| **B** | 过 quick + OOS + QQQ；其它 stage 部分过 | 候选 | 看 robustness / diversity 哪里弱; 可能改进后跳 A |
| **C** | 过 quick + OOS；未过 QQQ 或 robustness | Watch | 不 promote, 可作 ensemble 候选 / 等扩 universe 后回看 |
| **D** | 未过 OOS（IR < 0.20 或 pass_rate < 0.55） | 不 promote | 直接 archive；除非有 narrative 解释 OOS 弱（如 regime mismatch） |

**实际指标怎么读**（来自 archive.db 真实字段）:

```text
# 一个典型的 S tier
quick_sharpe=1.82  oos_ir=0.68  oos_pass_rate=0.78  passed_robustness=True
passed_qqq_gate=True  composite_score=0.82  tier=S

# 一个典型的 B tier (robustness 边缘 + QQQ 过)
quick_sharpe=1.21  oos_ir=0.34  oos_pass_rate=0.62  passed_robustness=True
passed_diversity=False  passed_qqq_gate=True  tier=B
# ← diversity False = 跟已 promote 策略相关 > 0.70; 不想加重曝光

# 一个典型的 D tier (OOS 失败)
quick_sharpe=1.45  oos_ir=0.12  oos_pass_rate=0.41
passed_oos=False  tier=D
# ← OOS IR 0.12 < 0.20 门槛, 后续 stage 不再检测
```

**Tier 跟 promote 不是一回事**:
- Tier 是 **mining 内部排序**（archive 里的标签）
- Promote 还要过 acceptance pack 的 9 个 gate（Tier S 也可能在 acceptance 上栽）
- Tier 是必要不充分: tier ≥ B 才能进 acceptance；acceptance 10-gate 才决定能否真上生产

**为什么 OOS IR ≥ 0.20**: 见 §15.5 "不降标准"原则; 短打就是经验上 < 0.20 的 IR 在小调整 / cost shock 后大概率塌掉。

### 10.5 Universe 两层概念

详 `docs/20260421-universe_expansion_spec_v2_2.md`:
- **Tradable Universe** (execution) — 本 config/universe.yaml，含 ETFs
- **Admission Whitelist** (expansion screening) — v2.2 spec Layer 1，common stock only

### 10.6 Lineage Tag

Archive 里每个 trial 打 `lineage_tag`，用于实验隔离：
- `post-2026-04-20-capital-100k` — LLM phase R1 baseline
- `post-2026-04-21-universe-mining-round-N` — 当前扩容阶段
- 同 lineage_tag 的 trials 才直接可比

### 10.7 Forward Observation

**目的**: "事先锁定一个 candidate, 假装从今天起它已经在生产, 看真实未来 N 个交易日表现"。是 OOS 验证的最高标准 — 因为没有任何机会回头改参数。

**关键约束**（PRD `20260427-forward_evidence_hardening_prd.md` v2.1.3 + `20260428-config_universe_snapshot_hardening_prd.md`）:

1. **freeze 必须先于第一个 TD**: `init` 时锁 `spec_hash` (frozen yaml) + `cost_assumptions.config_hash` (`config/cost_model.yaml`) + `ConfigSnapshot` (universe / factor_registry / research_mask / risk / system 5 个 hash).
2. **observe 是 append-only**: 每天跑一次, 加一个 `TD<NNN>` entry. 不能改老的.
3. **revalidate 自动跑两层 hash 检查**:
   - **v2.1**: 3 input-scope hash (signal_input / execution_nav / benchmark) + bar_hash rollup. 数据修订（如 yfinance 后修 close）→ `DataRevisionEvent`. 影响 NAV ≥ 10 bps 或 raw drift ≥ 0.5% → policy=invalidated → manifest 翻 `requires_data_review`.
   - **PRD F**: 5 个 config hash. universe / factor_registry / risk_config 漂移 → halt drift（同样翻 `requires_data_review`）；research_mask / system 漂移 → warn 不阻塞.
4. **decide 是 terminal**: `completed_success` / `completed_fail` / `aborted` 三选一. 一旦 decide, observe 不再允许跑（防止状态被 silently 覆盖, audit fix #3 加的 halt）.

**checkpoint**: TD10 / TD20 / TD40 / TD60 是默认决策点. 当观察到的 TD 数 ≥ 最大 decision_day, manifest 自动翻 `decision_pending` 等用户 `decide`.

**典型操作**:

```bash
# 锁一个 candidate
python dev/scripts/oos_mvp/run_forward_observe.py init \
    --candidate-id rcm_v1_defensive_composite_01

# 每日 EOD 后跑（fetchdata 必须在 NYSE 16:00 ET 收盘后做）
python dev/scripts/oos_mvp/run_forward_observe.py observe \
    --candidate-id rcm_v1_defensive_composite_01

# 看进度
python dev/scripts/oos_mvp/run_forward_observe.py status \
    --candidate-id rcm_v1_defensive_composite_01

# 60 TD 到了 / 用户决定 abort
python dev/scripts/oos_mvp/run_forward_observe.py decide \
    --candidate-id rcm_v1_defensive_composite_01 \
    --status completed_fail --notes "OOS 跌破 -10%"
```

**Pre-PRD-F manifest 兼容**: 在 PRD F 之前 init 的 manifest 没有 `config_snapshot` 字段, revalidate 走 lazy-migration（跳过 config drift 检查 + INFO log 提示）. 想 opt-in: `dev/scripts/forward/backfill_config_snapshot.py --dry-run`.

**Forward observe vs paper trading**:
- paper = 把当前生产策略每日跑一次, 跟踪 P&L
- forward = 把候选策略**事先锁住**, 看 N 天后表现
- 两者**不能互替**; 一个是"上线运行", 一个是"上线前最后一道 OOS"

### 10.8 Fleet Allocator（Track B）

**目的**: 多个 candidate 组成一个 portfolio sleeve（"舰队"）。每个
candidate 自己已经过 acceptance；fleet 层负责"它们组合在一起"是否依然合理。

**Track B 已 land Step 1-5**（`config/fleet.yaml` + `core/fleet/`）：

| Step | 已 land | 内容 |
|---|---|---|
| 1 | ✅ | Schema (`FleetConfig` / `FleetCandidate` / `FleetManifest`) + manifest I/O |
| 2 | ✅ | C1 capital split (equal_weight / manual_overrides) |
| 3 | ✅ | `compose_weight_matrix` (unconstrained fleet weights) |
| 4 | ✅ | C3 overlap throttle (per-symbol weight cap，目前 0.20) |
| 5 | ✅ | C2 pairwise correlation budget (warn 0.70 / reject 0.85，realized daily returns) |
| 6+ | ⏸️ codex-frozen | DD throttle / role caps / removal / fleet observe / shadow→live |

**关键检查**:

```python
from core.fleet.allocator import FleetAllocator
from core.fleet.manifest_schema import FleetConfig
import yaml
cfg = FleetConfig(**yaml.safe_load(open("config/fleet.yaml")))
alloc = FleetAllocator(cfg)
status = alloc.check_correlation_budget(returns_df)
# status.level ∈ {ok, warn, reject, insufficient_data}
# status.pairs = [CorrelationPair(a, b, correlation, level), ...]
```

**Factor-IC orthogonal ≠ NAV orthogonal**: 因子 IC 维度低相关，
组合层 NAV 仍可能高度相关（共享 market beta / Mag7 / risk-on 暴露）。
真正的 fleet 分散化必须看 NAV-level 相关。这个教训出自 RCMv1 + Cand-2
2026-04-30 NAV-correlation 实验（pooled Pearson 0.898 → reject）。
详 `docs/memos/20260430-rcmv1_cand2_realized_correlation.md`。

### 10.9 Track A / B / C 框架（2026-04-29+ 主线）

项目从 Phase D 迭代优化进入"三件套"研究框架：

```
Track A — 时序切分纪律
  ├─ alternating_regime_holdout_v1 split (config/temporal_split.yaml)
  ├─ 17-gate acceptance evaluator (validation 5 年 + stress + concentration + cost + role)
  ├─ sealed_eval ledger (M5 fail_closed_on_repeat + R20 split-failure guard)
  ├─ C5 role-remint guard (no spec_sha cross-role mining within same split_name)
  └─ regime classifier with tiered disagreement policy
       ✅ 已 ship 2026-04-29 (`docs/prd/20260429-temporal_split_holdout_discipline_prd.md`)

Track B — Fleet Allocator
  ├─ Step 1-5 已 land (capital split + compose + C3 overlap + C2 corr budget)
  └─ Step 6-9 codex-frozen (DD throttle / role caps / fleet observe / shadow-to-live)
       ✅ partial — 详 §10.8

Track C — Real Controlled Mining
  ├─ Evidence-pack template (docs/templates/track_c_evidence_pack_template.md)
  ├─ Pre-registered criteria YAML (immutable from first trial)
  ├─ Reverse-validation sentinel (designed-to-fail criteria)
  └─ NAV-orthogonality gate vs every active candidate
       ⏸️ 等 codex 签 + 三个 concern guards 落地（A 2026 sealed double-dip / B
          forward TD60 early-attention / E economic-invariant tests，详
          `docs/memos/20260430-pre_track_c_strategic_concerns.md` +
          `docs/memos/20260430-concerns_abE_proposed_solutions.md`）
```

**Track 之间的依赖**:
- Track A 必须先 ship → 提供新 split / acceptance / sealed_ledger
- Track B 可与 A 并行 → 提供 fleet-level orthogonality 工具
- Track C 依赖 A + B → 真实挖矿用 A 的 split + 用 B 的 NAV-orth 检查

**Track 边界规则**（hard line）:

| 工作流 | 允许 | 阻塞 on |
|---|---|---|
| Track C dry run | ✅ | template signoff |
| Track C 出 nominee 走 acceptance evaluation | ✅ | — |
| 写 evidence pack | ✅ | — |
| Forward init for Track C nominee | ❌ | Concern B Tier 1 |
| 2026 sealed eval | ❌ | Concern A 2026 double-dip guard |
| Fleet wiring expansion | ❌ | Step 6+ + economic-invariant flags |
| 真钱部署 | ❌ | 全部 + go-live PRD |

---

## 11. 报告与输出解读

### 11.1 Master Report (`reports/backtests/backtest/runs/<ts>_backtest/master_report.md`)

主报告分 5 段：
1. **策略概览** — CAGR / Sharpe / MaxDD / vs SPY / vs QQQ（含 holdout 对比）
2. **每年收益表** — 按年份 + regime stratification
3. **Regime 表现** — 6 regime 下分别统计（含 vs QQQ column）
4. **Drawdown 历史** — 历次深度 DD 的事件 context
5. **诊断** — factor contribution / turnover / cost attribution

**关键数字**:
- CAGR > QQQ CAGR: 硬约束，必过
- MaxDD ≤ -20%: 硬约束
- Sharpe > 0.80: 期望

### 11.2 Mining Leaderboard (`archive.db`)

```bash
python scripts/run_mining.py --leaderboard --lineage-filter 'my_tag'
```

显示 top-N trials by composite_score:
- **spec_id** — 参数组合唯一 hash
- **strategy_type** — multi_factor / dual_momentum / ...
- **tier** — S/A/B/C/D
- **composite_score** — 综合分（内部公式）
- **quick_sharpe** — quick-stage Sharpe
- **oos_ir** — OOS walk-forward IR vs benchmark（**核心**）
- **oos_pass_rate** — fraction of windows passed individually

### 11.3 Intraday Report

`core/reporting/intraday_report.py` 产出:
- Fills summary (count, avg slippage)
- Equity path per bar
- Drawdown trajectory
- Diagnostics flags

### 11.4 各工具 artifacts（`data/ml/`）

大部分研究脚本产出 `data/ml/<tool_name>/<out_tag>/` 格式：
- `llm_candidates/<name>/verdict.json`
- `llm_deep_checks/<name>/deep_check.json`
- `llm_factor_backtests/<name>/factor_backtest.json`
- `llm_composite_backtests/<config>/composite_backtest.json`
- `llm_orthog/<name>/orthog_report.json`
- `factor_interactions/interactions.parquet` + summary.json
- `universe_admission_<tag>.csv` + summary.json
- `universe_risk_labels_<tag>.csv`
- `universe_buckets_<tag>.csv`
- `xgb_importance.parquet` + `xgb_run_summary.md`

### 11.5 研究日志

每个完成阶段的权威总结（`docs/*_final_synthesis.md`）入口：`docs/INDEX.md` §"Final synthesis docs"。

`docs/20260420-ralph_loop_log.md` 累计每轮 ralph-loop 工作记录，是了解项目进展的**必读文档**。

---

## 12. 常见任务 Recipes

### 12.1 "我想加一个新 factor"

**流程**（按 `docs/20260420-prd_llm_factor_mining.md` 正式流程）：

```bash
# 1. 写 YAML 候选（按 PRD §4 schema）
mkdir -p research/llm_candidates/round_NN
cat > research/llm_candidates/round_NN/my_factor.yaml <<'EOF'
factor_name: "my_factor"
hypothesis: "..."
formula: "..."
compute_fn_path: "research.llm_candidates.round_NN.compute_fns:my_factor"
...
EOF

# 2. 写 compute_fn (接 price_df, 返回 factor values DataFrame)
# 编辑 research/llm_candidates/round_NN/compute_fns.py

# 3. 跑 funnel
python scripts/llm_factor_propose.py \
    --input research/llm_candidates/round_NN/my_factor.yaml

# 4. 如果 NEEDS_HUMAN_REVIEW 或 IC 可观，跑 deep_check
python scripts/llm_candidate_deep_check.py \
    --candidate research/llm_candidates/round_NN/my_factor.yaml \
    --universe-size 30

# 5. 如果 PASS §5.4 reverse review，跑 factor_backtest
python scripts/llm_candidate_factor_backtest.py ...

# 6. 过所有 gate 且有增量 → propose user authorize promotion to RESEARCH_FACTORS
#    具体修改 core/factors/factor_generator.py + factor_registry.py::RESEARCH_FACTORS
#    (需用户明确批准)

# 7. 进 PRODUCTION 需再审，改 core/signals/strategies/multi_factor.py + PRODUCTION_FACTORS
```

### 12.2 "我想调整一个风险阈值"

```bash
# 改 config/risk.yaml 或 config/backtest.yaml
# 如 "严 kill switch"
# 修改 risk.yaml::drawdown_limits::warning_pct / reduce_pct / defensive_pct / halt_pct

# 验证回归
pytest -q
pytest tests/unit/risk/test_kill_switch.py -v

# 回测验证
python scripts/run_backtest.py --no-walk-forward
```

### 12.3 "我想扩 universe"

按 `docs/20260421-universe_expansion_spec_v2_2.md` + `docs/20260421-prd_universe_expanded_mining.md`:

```bash
# 1. 准备候选 list (newline-separated)
cat > my_candidates.txt <<EOF
ABBV
UNH
LLY
...
EOF

# 2. Layer 1 admission screening
python scripts/universe_admission_screen.py \
    --input-symbols my_candidates.txt --out-tag v3

# 3. Layer 2 risk labels
python scripts/universe_risk_labels.py \
    --admission-csv data/ml/universe_admission_v3.csv \
    --out-tag v3

# 4. Layer 3 bucket assign
python scripts/universe_bucket_assign.py \
    --labels-csv data/ml/universe_risk_labels_v3.csv \
    --out-tag v3

# 5. 看 buckets/CORE 结果给 user 确认
cat data/ml/universe_buckets_v3_summary.json

# 6. User 确认后改 config/universe.yaml::seed_pool 加入

# 7. 回归 pytest
pytest -q
```

### 12.4 "我想调试一个失败的测试"

```bash
# 1. 看具体错误
pytest tests/integration/test_backtest_paper_consistency.py::TestX::test_Y -v

# 2. 常见原因:
#    - 数据缺失 → 先跑 fetch_data.py 或 pytest.skip 加 guard (见 §16.1)
#    - Universe 改动 → weights 需 recalibrate
#    - Factor 注册 drift → 看 test_factor_registry.py

# 3. 运行单独 subset
pytest -k "not integration" -q  # 只 unit tests
pytest -k "test_qqq" -v         # 只 QQQ 相关
```

### 12.5 "我想看某个 spec_id 的详细数据"

```bash
python -c "
import sqlite3, json
c = sqlite3.connect('data/mining/archive.db')
row = c.execute('SELECT * FROM trials WHERE spec_id LIKE \"6d15b735%\"').fetchone()
for col, val in zip([d[0] for d in c.execute('PRAGMA table_info(trials)').fetchall()], row):
    print(f'{col}: {val}')
"
```

### 12.6 "我想对比两个 lineage"

```bash
python -c "
import sqlite3
c = sqlite3.connect('data/mining/archive.db')
rows = c.execute('''
    SELECT lineage_tag, COUNT(*), MAX(oos_ir), AVG(oos_ir)
    FROM trials WHERE lineage_tag IN ('tag1', 'tag2')
    GROUP BY lineage_tag
''').fetchall()
for r in rows: print(r)
"
```

## 14. 测试套件

### 14.1 结构

- `tests/unit/<module>/test_*.py` — 单元
- `tests/integration/test_*.py` — 集成（I/O 密集）
- 合计计数（pass / skipped / xfailed）以 `data/baseline/latest.json` 为准 —
  跑 `dev/scripts/baseline/build_research_baseline_snapshot.py --run-tests`
  可刷新快照

### 14.2 运行

```bash
pytest -q                          # 全套 (~100s)
pytest --co                        # 只看 collection
pytest -k "factor" -v              # 按关键字过滤
pytest tests/unit/mining/ -q       # 单模块

# Coverage
pytest --cov=core tests/ --cov-report=html

# 快速 baseline snapshot（1-2s，不跑全套）
python dev/scripts/baseline/build_research_baseline_snapshot.py
```

**不再硬写测试数**：刷新 `data/baseline/latest.json` 来获取当前 collected/passed
统计，文档引用该文件，不在 md 里 pin 数字（防 drift）。

### 14.3 关键测试类

- `test_factor_registry.py` — registry drift 守护
- `test_backtest_paper_consistency.py` — 回测/模拟盘一致性 + QQQ outperformance
- `test_kill_switch.py` — 3-tier kill switch
- `test_evaluator.py` — mining 6-stage funnel
- `test_broker_adapter*` — broker 接入抽象层

### 14.4 xfail 策略

测试标 `@pytest.mark.xfail(strict=False)` 时表示"目前不过但是预期"。
常见原因:
- Universe 扩容导致 weights 需 recalibrate（R28-R33 曾有此情况，R33 已解决）
- 等实现中的功能

xfail 解除条件必须文档化在 reason 参数里。

---

## 15. 研究方法论

### 15.1 Invariants（不可违反，见 §2）

12 条硬约束。任何 PR 都要自检不破坏这些。

### 15.2 Benchmark Outperformance Rule [REVISED 2026-05-02 — QQQ deprecated]

**硬目标**: 策略长期跑赢 SPY (full period + 2025 holdout, both HARD)。
**QQQ 作为 diagnostic reference**, 不再是 hard outperformance gate。

| 维度 | vs SPY | vs QQQ |
|---|---|---|
| Full-period | **CAGR > SPY — HARD** | CAGR vs QQQ — diagnostic |
| 2025 holdout | **return > SPY — HARD** | return vs QQQ — diagnostic |
| OOS walk-forward avg | Mean excess > 0 — diagnostic (preferred) | Mean excess vs QQQ — diagnostic |
| Per-window | Reported | Reported |
| Per-regime | Reported | Reported |

**Why QQQ deprecated** (8-angle analysis at
[memo](docs/memos/20260502-qqq_benchmark_deprecation.md)):
- QQQ = sector-tilt ETF (60% tech), NOT market-broad benchmark
- 1999-2025 long-term: QQQ +8.3% vs SPY +7.8% (+0.5% only; 2009-2021
  outperformance was zero-rate cherry-pick)
- Long-only beat-QQQ requires beta>1 → MaxDD>QQQ → DIRECTLY violates
  15-20% MaxDD invariant
- Industry/academic norm: long-only US large-cap → S&P 500/Russell 1000

**Risk guardrail**: 不许通过"集中 ≤3 symbols" / 违反 position limit /
恶化 MaxDD 来硬换 SPY 超额。Black swan resilience quantified to
2008-style scenario MaxDD ≤ 25%.

**Authority**: branch `invariant-revision-2026-05-02` merged 2026-05-02
(checkpoint at `docs/checkpoints/20260502-invariant_revision.md`).

### 15.3 Pricing Semantics

- **Raw vs adjusted**: 数据 raw 落盘（polygon 1m → daily 聚合），
  splits 在读取时通过 `data/ref/splits.parquet` cascade 应用；
  dividends 当前不调整（deferred）。yfinance 仅作 ETF 2024+ 缺口
  fallback。详见 CLAUDE.md "Pricing and Valuation Semantics"
- **Signal timing**: T-day close (shift by 1 → no lookahead)
- **Execution**: T+1 adjusted **open**（实测用真实 open_df）
- **Valuation**: T+1 adjusted close
- **Stale/halted**: 按 last valid price 估值，不从 NAV 移除

### 15.4 Halted Data

- 持仓标的无 bar: 不下新单，按 last valid price 估值 + flag stale
- Stale > N bars (config): 从 order generation 排除，continue valuation
- 退市: 按 last price 清仓，从 universe 移除

### 15.5 "不降标准" 原则 (R17)

遇到 OOS IR 不过 0.20 门槛时，**不降门槛**。出路：
1. 扩 universe（R28 验证）
2. 加数据源（fundamentals / options / alt data）
3. 非线性 ensemble
4. 找新 alpha 源（pairs / arb 等）

而不是把 0.20 降到 0.10。

### 15.6 LLM 作为候选生成器，永不最终裁判 (PRD §2.2)

所有 funnel verdicts 只会是 `REJECT` / `ARCHIVE` / `NEEDS_HUMAN_REVIEW`，
**永不 auto-KEEP**。最终 promote 决策必须人审核 OOS + regime + cost + QQQ。

**Phase 1 — Claude 对话式（默认）**:
- `docs/20260421-llm_proposal_prompt_template.md` —— Claude 自用 system prompt + YAML schema
- `docs/20260421-llm_proposal_seed_context.md` —— 每轮开始前要注入的 5 段 repo state
- `docs/20260421-llm_funnel_checklist.md` —— 6 步 mandatory funnel

**Phase 1.5 — Multi-LLM Handoff (PRD M15 reframed)** — 通过 Gemini / Codex / 任意 LLM 参与，无需 API:
- `docs/20260421-llm_external_llm_handoff.md` —— 完整 workflow 说明
- `dev/scripts/llm_handoff/dump_llm_handoff_context.py` —— 自动 dump 当前 repo state 为 markdown context pack（copy-paste 即喂任意 LLM）
- 用户手动落盘 LLM 产出到 `research/llm_candidates/round_NN/*.yaml`；Claude funnel 自动拾取
- 无 API 依赖 / 无成本 / 无可重复性风险

**Phase 2 (未来，不推荐)**: 程序化 Anthropic API 调用。Phase 1/1.5 当前
未成瓶颈，无计划启动。

### 15.7 4-round Self-audit Methodology（forward-only 2026-04-30+）

**目的**: 单测过 + smoke test 通过 ≠ 改动审过；尤其涉及 schema / 阈值 /
新 pipeline / numerical 声明的改动，必须经 4 轮自审。

| Round | 焦点 | 必须做的 |
|---|---|---|
| **R1** 事实 | 文件 / 字段 / 数字 / yaml 语法 | 每个声明配 verification 命令；不能凭记忆引用 |
| **R2** 逻辑 | 阈值 domain-correctness / critical path / 假设 / effort 真实估算 | 每个 borrowed threshold 想清楚是不是从相邻 domain 抄过来的 |
| **R3** 真正执行 | **跑代码 + 对比期望**，不只 grep / smoke test | pydantic loader 实际加载；synthetic input 验证 corner; 数字 4dp 一致 |
| **R4** 边界故障 | ≥ 5 个 corner case，每个写明期望行为分类 (raise / safe-default / transparent) | 真正构造异常输入跑脚本 |

**反模式**（不算 R3）:
- 重读你刚写的文件
- 只看 yaml.safe_load passes（那是 R1）
- "tests pass" 不挖测试覆盖了什么
- "看起来合理"

**完整契约**: `docs/checkpoints/20260430-self_audit_methodology.md`。

**适用范围**:

| 改动类型 | 必须做 |
|---|---|
| Schema 改动 (pydantic / yaml / parquet) | R1 + R2 + R3 + R4 |
| 阈值改动 (acceptance / risk / fleet) | R1 + R2 + R3 + R4 |
| 新 script / 新 pipeline 阶段 | R1 + R2 + R3 + R4 |
| 含具体数字 / 代码状态声明的 memo | R1 + R2 + R3 |
| 一行注释 / typo / 纯文字 | R1 |

R3 是经验上**最容易跳过**也**收益最高**的一轮 — README 自审就抓出 3 个
runtime bug，靠的就是真正用边界 fixture 跑代码。

---

## 16. 故障排查

> 按错误现象 / 卡住场景反查见 §19。本节按"具体错误消息"排序，可 ⌘F / Ctrl+F 直接搜。

### 16.0 高频首跑错误（先看这个）

#### `ModuleNotFoundError: No module named 'core'` / `... 'pqs'`
**原因**: 没在 repo 根目录跑命令；或 conda env 没激活。
**解决**:
```bash
pwd                                  # 确认在 pqs/ 根
conda activate pqs                   # 激活
which python                         # 应该是 conda env 里的
```
`dev/scripts/...` 子目录下脚本通常会自己 `sys.path.insert` 加 root；`scripts/` 直接子目录脚本一般在 repo 根跑就行。

#### `FileNotFoundError: data/daily/SPY.parquet`
**原因**: 数据没准备。**解决**: 跑 §6 step 0 的 `fetch_data.py --daily-only`。

#### `yfinance` 报 rate limit / 429
**原因**: yfinance 限流（同 IP 短时间过多请求）。
**解决**: 等 5-10 分钟再 `--symbols SPY QQQ ...` 分批拉；或减少并发。

#### `pydantic.ValidationError` on `cfg = load_config()`
**原因**: 改了 `config/*.yaml` 但字段不匹配 schema。
**解决**: 看 error 里的 missing / extra field name → 检查 `core/config/schemas/*.py` 对应模型。yaml 多 typo'd 字段会报错（`extra="forbid"`）。

#### `pytest` 全部 skip 或 collection 失败
**原因**: 没装 dev 依赖。**解决**: `pip install -e ".[dev,research]"`。

#### Mining 跑了几小时显存 / 内存爆
**原因**: `--trials` 设过大或 universe × lookback × symbols 过密。
**解决**: 减 `--trials` 到 30 + `--budget 900`（15 分钟封顶）；或 `pkill -f run_mining` 然后 `--reset-archive` 慎用。

#### `OOS IR < 0.20`，整体 promote 不了
**原因**: 不是 bug，是研究标准。详见 §15.5 "不降标准"原则。
**思路**: 扩 universe / 加新数据源 / 找新 alpha 源；**不要**降阈值。

---

### 16.1 "Empty data / RangeIndex" 错误

**症状**: `TypeError: Invalid comparison between dtype=int64 and str`

**原因**: 真实数据缺失，构造出空 DataFrame，直接做 `df.index >= "YYYY-MM-DD"` 在 RangeIndex 上报错。

**解决**:
- 用 `core/data/panel_loader.py::load_close_panel_or_exit/skip` helper
- 或手工加 guard:
  ```python
  if df.empty or not isinstance(df.index, pd.DatetimeIndex):
      sys.exit(2)  # or pytest.skip(...)
  ```

### 16.2 "KeyError: 'close'" on benchmark

**原因**: `MarketDataStore.read` 返回空 DF 而不是 None，不能直接 `df["close"]`.

**解决**: 用 `load_benchmark_close_or_exit` helper。

### 16.3 Mining 产出很少 unique trials

**症状**: `run_mining.py --trials 50` 只跑出 4-5 unique。

**原因**: Optuna 持久化 study 跨多轮运行累积，sampler 重复采样近 top params，archive dedup 吞掉 duplicates.

**解决**: Reset Optuna study（保留 archive）:
```bash
mv data/mining/optuna.db data/mining/optuna_backup_$(date +%s).db
python scripts/run_mining.py ...   # 下次 run 会创建新 optuna.db
```

### 16.4 `test_full_period_cagr_beats_qqq` 失败

**原因**: Universe 改后 MFS weights 需 recalibrate.

**解决**:
1. 跑 `scripts/r33_weight_grid_search.py` 或类似工具找新 weights
2. 更新测试里的 `factor_weights={...}` 为新值
3. 保留 `@pytest.mark.xfail` + 注 reason 如果暂不能解

### 16.5 微信推送不工作

**排查**:
```bash
# 1. 看 config
cat config/notify.yaml
# 确认 enabled: true, backend: wecom_bot

# 2. env var 设了吗
echo $PQS_WECOM_WEBHOOK_URL

# 3. 测试
python dev/scripts/notify/send_round_summary.py --title "test" --stdout <<< "hello"
```

**获取 webhook URL**: 企业微信群 → 群机器人 → 新建 → 复制 URL (含 `?key=xxx`)
```bash
export PQS_WECOM_WEBHOOK_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=XXXX"
```

### 16.6 Intraday bar 数据不全

- 2015-2023: polygon flat files（全市场）
- 2024-2025/11: 每 ticker CSV (**仅 stocks，无 ETF**)
- 2025-12+: C 盘 CSV (同样仅 stocks)
- 2026+: trades_backfill (tick-level 转 1m)

**ETF 2024+ intraday 靠 yfinance 补尾**（BarStore 自动 fallback）:
```python
from core.data.bar_store import BarStore
store = BarStore()
df = store.load("SPY", freq="1m", fallback="auto")  # 自动尾部补全
```

---

## 17. 项目当前状态

> **README 不维护项目演进史 / 阶段 changelog。** 项目历史的权威
> 来源是：
> - `docs/20260420-ralph_loop_log.md` — 每轮 ralph-loop 11-part 记录
> - `docs/INDEX.md` §"Final synthesis docs" — 各阶段终态 synthesis
> - `docs/audit/20260428-ralph_audit_round_*.md` — 当前 audit cycle
>   memo
> - `git log --oneline` — 完整 commit 演进
>
> 本节只描述系统**今天**的状态：未解 blocker + 术语约定。

### 17.1 未解 blockers 摘要

> **过期检查**: 本节内容会随项目演进过期。当前活跃工作 / 决策记录在
> `CLAUDE.md` "Current TODO Checklist" + `docs/memos/`，本节只快照
> "宏观 blocker 类别"。具体客观数据日期标在每条末尾。

- **OOS IR ≥ 0.20 promote threshold 仍未跨过**（Deep Mining 唯一
  candidate `6d15b735a64c` OOS IR +0.292，但 full-period fresh
  backtest 揭示 -10.33pt CAGR vs QQQ 挡下）

- **factor → forward-return 在 2021+ 系统性负** —
  最新 XGBoost CV (R43, `data/ml/xgb_cv/R43_expanded_shap/summary.json`,
  21d horizon, 35 features, 110,969 panel rows，2026-04-22 跑):

  | Fold | Test 期 | OOS R² |
  |---|---|---|
  | 1 | 2017-10-27 → 2019-07-25 | **+0.343** ✓ |
  | 2 | 2019-07-25 → 2021-03-30 | **+0.390** ✓ |
  | 3 | 2021-03-30 → 2022-11-26 | **−0.809** ✗ |
  | 4 | 2022-11-26 → 2024-07-26 | **−0.200** ✗ |
  | 5 | 2024-07-26 → 2026-03-27 | **−0.076** ✗ |

  Mean OOS R² = **−0.070** across 5 folds; 2/5 folds positive，inflection
  point 在 2021-03-30。这是跨 model class 一致信号（早期 R3 baseline 也
  在该 cutoff 后转负），不是 single-fold 噪声。

- **Universe 仍 tech-concentrated** — 最新 alpha diagnostic
  (`data/ml/readme_audit_2026_04_29_summary.json`, SPY benchmark, 2018-01-01 起)
  79 symbols 分类:

  | Category | n | 含义 |
  |---|---|---|
  | ALPHA_GENERATOR | **11** | β 低 + 正 α 显著（独立信号源） |
  | BETA_PLUS_ALPHA | **9** | 高 β 但 α-compensated |
  | DIVERSIFIER | 24 | β < 0.5（regime hedge 用） |
  | MARKET_LIKE | 33 | β ≈ 1, α 接近 0（被动 SPY 追随） |
  | PURE_BETA | 2 | β 高但 α 负（DROP 候选: TQQQ, AXP） |

  独立 alpha 来源数 11 — 离 "20+ 多元 alpha" 的研究目标还差不少；
  SPY CAGR 12.43% / Sharpe 0.703 / MaxDD -34.23%（2018-2026 8 年期）
  作为 benchmark 基线参考。

- **突破方向候选**：universe 再扩容（参考 R37 `data/ml/R37_sp500_alpha.csv`
  511-symbol pool）/ 新数据源（microstructure / order flow / sentiment）
  / structurally new factor family

- **Track A/B/C 三件套未闭环**（截至 2026-04-30）— Track A + B Step 1-5
  已 land；Track C real mining 等 codex 签 evidence-pack template + 三个
  concern guards (A 2026 sealed double-dip ledger / B forward TD60
  early-attention flag / E economic-invariant matrix in evidence pack)。
  详 `docs/memos/20260430-pre_track_c_strategic_concerns.md` +
  `docs/memos/20260430-concerns_abE_proposed_solutions.md`

- **Fleet-of-two 假设破裂**（2026-04-30）— 当前 forward-observe 中的
  RCMv1 + Cand-2 NAV-correlation pooled Pearson **0.898**（Step 5 reject
  阈值 0.85），β-SPY 1.3-1.6（都不是 defensive），76% 天数同时 drawdown，
  top-10 持仓重叠 4/10。Cand-2 "orthogonal" 标签作废；fleet 真正 wiring
  等 Track C 出 NAV-orthogonal candidate。详
  `docs/memos/20260430-rcmv1_cand2_realized_correlation.md`

### 17.2 术语约定

- `intraday cached-runtime paper trading` — 当前能力（bar-by-bar
  缓存数据）
- `realtime intraday live-feed paper trading` — 未具备（独立 PRD
  `prd_live_feed.md` 待开）
- 禁止笼统叫 "intraday live"

## 18. 附录

### 18.1 关键常量位置

| 常量 | 位置 |
|---|---|
| **Production strategy (single source of truth)** | `config/production_strategy.yaml` |
| PRODUCTION_FACTORS set | `core/factors/factor_registry.py` |
| RESEARCH_FACTORS set | 同上 |
| MFS default weights (fallback only) | `core/signals/strategies/multi_factor.py::_DEFAULT_WEIGHTS` |
| Production strategy loader / builder | `core/config/production_strategy.py` |
| Mining Optuna space | `core/mining/strategy_space.py::MultiFactorSpace` |
| QQQ gate thresholds | `config/backtest.yaml::mining::min_*_excess_vs_qqq` |
| OOS threshold | `config/backtest.yaml::mining::oos_min_ir_vs_benchmark` |
| Kill switch (drawdown stage) thresholds | `config/risk.yaml::drawdown_limits` |
| 6 regime thresholds | `config/regime.yaml` |
| Acceptance thresholds (Tier D / walk-forward / factor tiers) | `config/acceptance.yaml` (loaded as `cfg.acceptance.{tier_d,walk_forward,factor_tiers}`) |

### 18.2 Git 安全规则

- **永不用** `git add -A` 或 `git add .`（会误加 .env, 大 binary 等）
- 永远 `git add <specific_file>` 显式列
- **不 amend** 已 push commit
- **不 force-push** 到 main
- Hook 失败时 fix 问题，不 `--no-verify`

### 18.3 学习路径（新人顺序）

1. 读本 README 全文 (~1h)
2. 运行 `pytest -q` 验证环境
3. 运行 `scripts/run_backtest.py --no-walk-forward` 看一次完整流程
4. 读 `docs/INDEX.md` §"Final synthesis docs" + 最新阶段的 `*_final_synthesis.md` 了解项目演进；§17 看当前未解 blocker
5. 读 `CLAUDE.md` 了解约束细节
6. 跑自己的第一次 mining: `scripts/run_mining.py --trials 10 --budget 300`

### 18.4 提问 / 贡献

- Issues: GitHub issues (claude.com/code 同步)

---

### 18.5 README 维护约定

**本文档是活文档**。任何改动到以下任意一项，必须同步更新 README 对应小节：

| 改动 | 更新 README |
|---|---|
| 新脚本 / 现有脚本 CLI 改动 | §8 脚本手册 |
| 新 config YAML / 字段改动 | §9 配置文件说明 |
| 新 factor 进 PRODUCTION/RESEARCH | §1.4, §10.1, §3 架构图 |
| 新 strategy 注册 | §10.2, §8.3 `--type` 列表 |
| universe 扩 / 缩容 | §1.4, §10.5 |
| mining funnel 阈值 / gate 逻辑 | §10.3, §10.4, §9.3 |
| 测试数变化 | §1.4 "测试"行 + §14 |
| Ralph-loop round 推进 | `docs/20260420-ralph_loop_log.md` + `docs/audit/*.md`（README 不维护 changelog） |
| 新 docs/*.md PRD | §4 docs/ + `docs/INDEX.md` |

小改动（typo / 排版）可直接编辑；结构性或语义性改动先和用户确认。

---

## 19. 卡住时怎么办（按场景反查）

> 这是 README 的"反向索引"。先看错误现象 / 你想做的事，再跳到对应章节。
> 如果场景找不到 → §16 故障排查 → 还找不到 → `git log --oneline` /
> `docs/INDEX.md` / 直接问 Claude。

### 我看到错误消息 ……

| 错误消息片段 | 跳转 |
|---|---|
| `ModuleNotFoundError: No module named 'core'` | §16.0 |
| `FileNotFoundError: data/daily/...parquet` | §16.0 + §6 step 0 |
| `pydantic.ValidationError` (load_config) | §16.0 |
| yfinance 429 / rate limit | §16.0 |
| `TypeError: Invalid comparison ... RangeIndex` | §16.1 |
| `KeyError: 'close'` on benchmark | §16.2 |
| Mining 一直跑出重复 trial | §16.3 |
| `test_full_period_cagr_beats_qqq` 失败 | §16.4 |
| 微信不推送 | §16.5 |
| `--config-dir` / `forward observe` 报 config drift | §0.4 + `docs/prd/20260428-config_universe_snapshot_hardening_prd.md` |
| `requires_data_review` halt | §0.4（forward 部分）|

### 我想做 ……

| 我想做的事 | 跳转 |
|---|---|
| 第一次跑通整套 | §6 三十分钟首跑 |
| 验证环境装好了 | §5.3 |
| 加一个新 factor | §12.1 |
| 改一个风险阈值（kill switch / position cap） | §12.2 + §9.4 |
| 扩 universe（加新 ticker） | §12.3 + §10.5 |
| 把 mining 找到的候选 promote 到生产 | §8.9 promote_strategy.py + `docs/20260421-promotion_flow.md` |
| 跑 forward observation（事先锁 candidate 看未来 N 天） | §0.4 + `dev/scripts/oos_mvp/run_forward_observe.py --help` |
| 给 forward manifest 补 ConfigSnapshot（lazy migration） | `dev/scripts/forward/backfill_config_snapshot.py --dry-run` |
| 看某个 spec_id 的详细数据 | §12.5 |
| 对比两个 lineage_tag | §12.6 |
| 调试某个失败的 pytest | §12.4 + §16 |
| 给 LLM 一份"喂给它的完整 context" | §8.9 dump_llm_handoff_context.py |

### 我想找一个常量 / 阈值 / 某个 yaml 字段在哪定义 ……

→ §18.1 关键常量位置表

### 我想了解项目当前状态 / 历史 ……

| 想知道的事 | 在哪看 |
|---|---|
| 系统**今天**运行状态 + 未解 blocker | §17 |
| 各阶段的"权威总结" | `docs/INDEX.md` §"Final synthesis docs" |
| 每轮 ralph-loop 工作记录 | `docs/20260420-ralph_loop_log.md` |
| 当前 audit 周期 memos | `docs/audit/20260428-ralph_audit_round_*.md` |
| commit 演进 | `git log --oneline` |
| Codex / Claude 协作记录 | `docs/claude_review_loop.md` (review/claude-collab branch) |

### 我看不懂某个术语 / 缩写 ……

→ §0 术语速查表

