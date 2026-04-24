# PQS — Personal Quantitative System

> **个人量化研究与模拟交易系统**，目标是长期可持续跑赢 SPY 和 QQQ，同时
> 保持低回撤（15-20%），具备黑天鹅韧性。

本文档面向**从未接触过本工程的读者**，帮你在一小时内建立完整的心智模型，
能够独立执行回测 / 挖矿 / 模拟盘 / 报告生成，并在遇到问题时通过本文档
定位答案。

---

## 目录

- [1. 项目是什么](#1-项目是什么)
- [2. 核心约束（不得违反）](#2-核心约束不得违反)
- [3. 架构总览](#3-架构总览)
- [4. 目录结构速查](#4-目录结构速查)
- [5. 环境准备](#5-环境准备)
- [6. 五分钟快速开始](#6-五分钟快速开始)
- [7. 核心工作流](#7-核心工作流)
- [8. 脚本详细手册](#8-脚本详细手册)
- [9. 配置文件说明](#9-配置文件说明)
- [10. 关键概念](#10-关键概念)
- [11. 报告与输出解读](#11-报告与输出解读)
- [12. 常见任务 Recipes](#12-常见任务-recipes)
- [14. 测试套件](#14-测试套件)
- [15. 研究方法论](#15-研究方法论)
- [16. 故障排查](#16-故障排查)
- [17. 研究历史摘要](#17-研究历史摘要)

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

### 1.4 当前状态（2026-04-24, post Phase E-post + Candidate-2 8-round）

- **生产策略**: `config/production_strategy.yaml` (M1 单一真源，当前 `status: conservative_default`；post-fix validated best **尚未存在** — pack v2 在 50-round R49 仍拒绝唯一候选 `6d15b735a64c`)
- **Universe**: **79 交易标的** = `seed_pool` 59（含 Mag7 + SPY/QQQ/GLD + leveraged + R28 扩容 common stocks + R38 扩容；`SQQQ` + `SOXS` 在 blacklist）+ 11 sector ETFs + 5 factor ETFs + 4 cross-asset。另有 3 个 macro_reference（^VIX/^TNX/DX-Y.NYB）只作 features
- **Factor registry**: **7 PRODUCTION + 64 RESEARCH**（RCMv1 在 RESEARCH 里加 12 个 orthogonal features，deep-mining R7/R10 各加一个），通过 `test_factor_registry.py` 强一致
- **Alignment**: runtime WARN 模式（M3）；fingerprints hash 对 yaml 匹配
- **Cross-ticker DSL**: `config/cross_ticker_rules.yaml` **enabled: true**，**5 条规则**（R24 加 Rule 4 `leveraged_etfs_dual_confirmation` + Rule 5 `xlu_outperformance_signals_defensive_rotation`）；M10 完成 production 集成（`core/signals/cross_ticker_wrapper.py`），`run_backtest.py` + `run_paper.py` 启动时默认应用；`--no-cross-ticker-rules` 可关闭；R23 A/B 测试证明 +2.3pt CAGR alpha，R25 stress 揭示 Rule 2/5 在 COVID V-recovery 下有非对称伤害
- **数据**: 日线 2007-2026 / 60m intraday 2015-2026 / 1m 2015-2026（部分）/ S&P 500 pool 513 symbols (R34 sync)
- **Mining archive**: Production `data/mining/archive.db` = 65 trials / 1 lineage (post-2026-04-23-feat-v1-expanded; prior history trimmed after feat-v1 expansion). Research `data/mining/rcm_archive.db` = 216 trials / 3 lineages (RCMv1 R13 pre-fix `post-2026-04-24-rcm-v1` + R16/R17 post-fix `post-2026-04-24-rcm-v1-lag1` + R19 random baseline `post-2026-04-24-rcm-v1-random`)
- **Candidate registry** (Phase E + E-post): `data/research_candidates/registry.db` = **2 records, both S2_paper_candidate**. `rcm_v1_defensive_composite_01` (Phase E R11) + `candidate_2_orthogonal_01` (Phase E-post R6, features `{ret_5d, rs_vs_spy_126d, hl_range}` equally-weighted 1/3 each; composite correlation with RCMv1 = 0.404 < 0.5; turnover relative diff = 79.2% ≥ 20%). Parallel paper 参考系建立。Registry DB 是 gitignore 的；git-committed 快照见 `docs/20260424-phase_state_snapshot.md`（用 `dev/scripts/export/dump_phase_state_snapshot.py` 刷新）
- **研究 mask**: `config/research_mask.yaml` 为 **single source of truth** (Phase E-post R5)；9 个脚本的 `{min_price=5.0, min_usd=20e6, window=20}` 硬编码已统一 config-driven，bit-identical invariant 在真 universe 上验证通过
- **Paper data boundary**: `core/data/factory.py::PriceStore` Protocol + `create_default_store(cfg)` (Phase E-post R4)。Paper 脚本依赖 Protocol 而不是具体 `MarketDataStore` 类
- **测试**: 计数见 `data/baseline/latest.json`（跑 `dev/scripts/baseline/build_research_baseline_snapshot.py --run-tests` 刷新快照）
- **Framework**: M0-M8 + M10 + M13 + M15 + M16 已交付。开放项 M11/M12/M14/M17/M18。详 `docs/20260421-prd_framework_completion.md`
- **Deep-mining (complete)**: 50 rounds autonomous search across 7 tracks (daily+ML / intraday / DSL / universe / XGB / transformer / synthesis). 详 **`docs/20260422-deep_mining_50round_final_synthesis.md`**
- **RCMv1 (complete)**: Research Composite Miner v1 — leakage fix (`evaluate_composite(lag=1)` default) + TPE-converged 4-feature defensive composite + acceptance passed. 详 **`docs/20260424-rcm_v1_final_synthesis.md`**
- **Phase E governance + paper layer (complete)**: `candidate_registry` state machine + `FrozenStrategySpec` + freeze / promote / paper_enter / revoke pipeline. 详 **`docs/20260424-phase_e_final_synthesis.md`**
- **Phase E-post + Candidate-2 (complete)**: 5 E-post 收尾 gap + Candidate-2 orthogonal candidate 走通 S0→S1→S2。详 **`docs/20260424-phase_e_post_cand2_final_synthesis.md`**

---

## 2. 核心约束（不得违反）

这些是**硬约束**，任何代码 / 策略 / 配置改动都不得破坏：

| # | 约束 | 原因 |
|---|---|---|
| 1 | **Long-only, no-margin, no-short** | 个人账户风险 |
| 2 | **SQQQ 黑名单; TQQQ/SOXL 严审** | 杠杆反向 ETF 极端风险 |
| 3 | **No real broker API this phase** | 模拟盘 = internal simulation |
| 4 | **macOS / Linux 本地运行** | 不上 AWS / cloud 优先 |
| 5 | **Benchmark: SPY 主 / QQQ 次** | 策略必须跑赢两者 (see §15.2) |
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
│  ├─ data/daily/*.parquet        (37+ symbols)        │
│  ├─ data/intraday/{1m,5m,...,60m}/*.parquet          │
│  └─ data/ref/splits.parquet, bar_provenance.parquet  │
└──────────────────────┬───────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────┐
│              Factors Layer                           │
│  RESEARCH_FACTORS (41, generate_all_factors)         │
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
│   └── cross_ticker_rules.yaml  - 跨标的声明式规则 DSL (PRD M4, enabled:true, 5 rules)
├── core/                        ← 核心业务代码
│   ├── backtest/                - BacktestEngine / WindowAnalyzer
│   ├── config/                  - pydantic schemas + loader
│   ├── data/                    - MarketDataStore / BarStore / panel_loader / vix_loader
│   ├── factors/                 - factor_generator / factor_registry / base_factors
│   ├── features/                - feature engineering helpers
│   ├── signals/                 - strategies (MFS, dual_momentum, etc.) + left_side
│   ├── mining/                  - MiningEvaluator / StrategyMiner / Archive / strategy_space
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
├── tests/                       ← pytest 套件（计数见 `data/baseline/latest.json`）
│   ├── unit/
│   └── integration/
├── data/                        ← 数据目录（gitignored）
│   ├── daily/                   - 日线 parquet
│   ├── intraday/{1m,5m,...,60m}/ - intraday parquet
│   ├── ref/                     - splits, bar_provenance
│   ├── mining/                  - archive.db, optuna.db
│   ├── paper_trading/           - paper_trading.db
│   └── ml/                      - 研究产出（llm candidates, grid results 等）
├── research/                    ← 研究源码（tracked）
│   └── llm_candidates/          - LLM 生成的 factor 候选 (R1-R14 各 round)
├── docs/                        ← 研究文档 + PRD + 阶段性 synthesis（详见 §17）
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

## 6. 五分钟快速开始

假设数据已就绪，跑一次完整"研究 → 挖掘 → 回测 → 报告"流程：

```bash
# 1. 检查 universe 和 config（可跳过，默认就行）
cat config/universe.yaml | head -40

# 2. 做一次回测（快速版，~3 分钟）
python scripts/run_backtest.py --no-walk-forward

# 3. 看报告（回测产出落在 reports/backtests/ 下带时间戳的目录）
ls reports/backtests/backtest/runs/                   # 列出所有 run
cat reports/backtests/backtest/runs/*/master_report.md | head -80  # 看最近一个

# 4. 跑挖掘循环（寻找最佳参数；15-30 分钟）
python scripts/run_mining.py --trials 30 --budget 900 --type multi_factor

# 5. 看 mining 排行榜
python scripts/run_mining.py --leaderboard

# 6. 跑一次模拟盘（当日 live 模式，需当日 60m 已更新）
python scripts/run_paper.py --mode live

# 7. 综合全流程
bash scripts/run_all.sh research      # 一键跑研究全套
```

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
- **作用**: 对 archive 中某 spec_id 跑 9-gate acceptance pack，产 JSON artifact
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

validation:                  # promote 门槛（非 mining）
  min_ir_vs_spy: 0.30
  max_drawdown_vs_spy_multiplier: 1.5
  max_crisis_drawdown_abs: 0.25

mining:                      # Mining 5-stage funnel 阈值
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
分 tier 的滑点 + 佣金（单位 bps）：
```yaml
mode: bps_based
vix_stress_threshold: 30.0        # VIX ≥ 30 时启用 stress multiplier
stress_slippage_multiplier: 2.5

tiers:
  liquid_etf:                     # SPY/QQQ/GLD/XL* 宽 ETF
    symbols: [SPY, QQQ, GLD, XLK, ...]
    commission_bps: 0.5
    slippage_interday_bps: 4
    slippage_intraday_bps: 7
  large_cap_equity:               # Mag7 + 大 cap common stock
    commission_bps: 0.5
    slippage_interday_bps: 6
    slippage_intraday_bps: 10
  leveraged_etf:                  # TQQQ/SOXL 等 3x
    commission_bps: 1.0
    slippage_interday_bps: 12
  # 等等
```

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

---

## 10. 关键概念

### 10.1 Factor

**Factor** = 对每 (date, symbol) 打分的 DataFrame。
- **RESEARCH_FACTORS** (41): 由 `core/factors/factor_generator.py::generate_all_factors` 输出，研究用
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

| Tier | 标准 | 含义 |
|---|---|---|
| S | 全部 stage 过 + top-decile IR | 推荐主力 |
| A | 全部 stage 过 | 推荐 |
| B | 过 quick + OOS + QQQ | 候选 |
| C | 过 quick + OOS | Watch |
| D | 未过 OOS | 不 promote |

### 10.5 Universe 两层概念

详 `docs/20260421-universe_expansion_spec_v2_2.md`:
- **Tradable Universe** (execution) — 本 config/universe.yaml，含 ETFs
- **Admission Whitelist** (expansion screening) — v2.2 spec Layer 1，common stock only

### 10.6 Lineage Tag

Archive 里每个 trial 打 `lineage_tag`，用于实验隔离：
- `post-2026-04-20-capital-100k` — LLM phase R1 baseline
- `post-2026-04-21-universe-mining-round-N` — 当前扩容阶段
- 同 lineage_tag 的 trials 才直接可比

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

每个完成阶段的权威总结（`docs/*_final_synthesis.md`）见 §17。

从 2026-04-20 开始累计 ~35 轮工作记录，是了解项目进展的**必读文档**。

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
- `test_evaluator.py` — mining 5-stage funnel
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

### 15.2 QQQ Outperformance Rule ⭐ 新近强化

**硬目标**: 策略 CAGR 必须跑赢 QQQ，不接受"接近"或"落后 ≤ 2%"。

| 维度 | 要求 | 类型 |
|---|---|---|
| Full-period | CAGR > QQQ | Hard |
| Holdout 252d | Return > QQQ | Hard |
| OOS walk-forward avg | Mean excess > 0 | Hard |
| Per-window | Reported | Diagnostic |
| Per-regime | Reported | Diagnostic |

**Risk guardrail**: 不许通过"集中 ≤3 symbols" / 违反 position limit /
恶化 MaxDD 来硬换 QQQ 超额。

### 15.3 Pricing Semantics

- **Raw vs adjusted**: yfinance `auto_adjust=True`，全流程用 adjusted
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

---

## 16. 故障排查

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

## 17. 研究历史摘要

项目已经过多个研究阶段。每个阶段的详细记录（每轮报告、决策过程、
实验结果）都汇集在研究日志中。下面只列里程碑 + 最权威的阶段性总
结文档指针。

**全史**: `docs/20260420-ralph_loop_log.md`

**关键阶段**（按时间顺序，最新在前）:

- **Phase B** — 基础架构建设（kill switch / cost model / walk-forward
  OOS / regime detection）。奠定当前的 backtest / paper consistency
  契约与 MultiFactorStrategy 骨架。
- **Phase C** — 测试 gap 补齐 + bug 修、Intraday 5 表 persistence、
  真 XGBoost / permutation importance 上线。
- **LLM Factor Mining** — 12 个 menu topic 覆盖、26 个 LLM 结构化候选
  走完 funnel、1 factor (`drawup_from_252d_low`) 进入 PRODUCTION。
  详 `docs/20260420-prd_llm_factor_mining.md` +
  `docs/20260421-llm_phase_blocker_report.md`。
- **Universe 扩容** (32 → 53 → 79 symbols) — 从 Mag7-heavy 扩到
  4-layer sector / factor / cross-asset 结构。详
  `docs/20260421-prd_universe_expanded_mining.md`。
- **Framework Completion M0-M16** — 单一真源
  `config/production_strategy.yaml`、promote 闭环、runtime alignment
  hard gate 等 P0 工程 blocker 收口。详
  `docs/20260421-prd_framework_completion.md`。
- **Deep Mining 50-round** — 7 tracks autonomous 搜索。0/302 trials
  通过 pack v2 全 10 gates（硬目标未达）；带出 R38 universe 扩容 v3
  proposal + R46 XGB rigor park 等 5 个决策。详
  **`docs/20260422-deep_mining_50round_final_synthesis.md`**。
- **RCMv1 (Research Composite Miner v1)** — 12 orthogonal features +
  TPE 收敛到 4-feature defensive composite
  `{beta_spy_60d, drawup_from_252d_low, days_since_52w_high, amihud_20d}`
  IC_IR +0.50；关键里程碑是 leakage fix
  (`evaluate_composite(lag=1)` default)。详
  **`docs/20260424-rcm_v1_final_synthesis.md`**。
- **Phase E Research Governance + Paper Layer** — `candidate_registry`
  状态机（S0/S1/S2/S5）+ `FrozenStrategySpec` + freeze / promote /
  paper_enter / revoke pipeline；RCMv1 从 memo 迁移到
  S2_paper_candidate。详
  **`docs/20260424-phase_e_final_synthesis.md`**。
- **Phase E-post + Candidate-2** — 5 E-post 收尾 gap +
  `candidate_2_orthogonal_01`
  (`{ret_5d, rs_vs_spy_126d, hl_range}` 等权) 走完 S0 → S1 → S2。
  Registry 现有 2 个 S2_paper_candidate，建立了 parallel paper 对照
  参考系。详
  **`docs/20260424-phase_e_post_cand2_final_synthesis.md`**。

### 17.1 未解 blockers 摘要

- **OOS IR ≥ 0.20 promote threshold 仍未跨过**（Deep Mining 唯一
  candidate `6d15b735a64c` OOS IR +0.292，但 full-period fresh
  backtest 揭示 -10.33pt CAGR vs QQQ 挡下）
- **factor → forward-return 在 2021+ 系统性负**（XGBoost / Transformer
  跨 model class 一致 OOS R² ≤ 0）
- **universe 仍 tech-concentrated**：79 symbols 中约 10-12 个 alpha
  generators
- 突破方向候选：universe 再扩容 / 新数据源（microstructure /
  order flow / sentiment）/ structurally new factor family

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
4. 读 §17 研究历史 + 最新阶段的 `*_final_synthesis.md` 了解当前状态
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
| universe 扩 / 缩容 | §1.4, §10.5, §17 |
| mining funnel 阈值 / gate 逻辑 | §10.3, §10.4, §9.3 |
| 测试数变化 | §1.4 "测试"行 + §14 |
| Ralph-loop round 推进 | §17（按阶段追加） |
| 新 docs/*.md PRD | §4 docs/ + §17 对应阶段 |

小改动（typo / 排版）可直接编辑；结构性或语义性改动先和用户确认。

