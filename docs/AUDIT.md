# PQS 全面审计

审计基线：`a68694ba3ea751c137c56885d87a5d375d178762`
审计日期：2026-07-17
回退标签：`codex-pre-takeover-20260717`

## 1. 结论

PQS 是一个规模较大、研究治理较强的本地量化研究与内部模拟系统，不是可连接
真实资金的生产交易系统。它已经具备较成熟的股票/ETF 数据处理、因子研究、
T+1 open 回测、时序切分、候选治理、forward observation、成本模型和内部 paper
记账；但用户本次要求的“安全 live-ready 系统”所需的统一风险否决、订单状态机、
持久幂等、异常报价/数据新鲜度门、真实 Broker 语义、完整期权数据与执行、运维和
云部署边界尚不存在或没有贯通。

当前不能启用真实资金，原因不是单一 bug，而是生产控制面尚未形成：

- README 和 CLI 把内部 paper 的当日回放称为 `live`，但系统没有真实 Broker；
- 股票/ETF 执行对象只有 `symbol/side/qty/signal_date`，没有订单 ID、决策 ID、
  幂等键、版本和生命周期；
- Broker 适配层是同步立即成交的内存镜像，paper engine 仍以本地 simulator 为
  真源，Broker 拒单和对账失败只记 warning；
- 风险约束主要在策略/组合构建阶段，缺少所有订单入口共享的最终 pre-trade veto；
- paper 当日路径没有可靠的行情新鲜度门，可以把缓存中很旧的最后一天当成
  “live day”；
- 期权模块只有合成 Black-Scholes spread 研究和 CSV/JSON paper 观察，不具备
  合约链、真实 bid/ask、组合单、assignment/exercise、OCC 调整和恢复语义；
- 期权 paper NAV 已复现 credit 重复计入问题；
- 无 CI、容器、迁移框架、健康端点、metrics/alerts、依赖锁文件或部署骨架；
- lint 与类型检查当前不是绿色基线。

## 2. 审计方法与范围

本轮没有根据目录名推断完成度，实际检查了：

- `README.md`、`CLAUDE.md`、完整用户任务说明和 Git 历史；
- 1,702 个 Git 跟踪文件（约 82 MiB）与 326 个 `core/`/顶层 `scripts/`
  Python 模块的 AST import 图；
- 主要入口 `scripts/run_backtest.py`、`scripts/run_paper.py`、
  `scripts/run_mining.py`、forward runner 和 options paper runner；
- 数据、配置、regime、signal、portfolio、risk、execution、paper、options、
  persistence、reporting、notification 和研究治理调用路径；
- 当前配置校验、CLI 启动、pytest、ruff、mypy、依赖一致性与 secret 模式扫描；
- 2026-07-08 旧审计及其后续修复，并重新核对旧结论是否仍成立；
- 一个独立的期权 paper 会计复现实验。

本地 workspace 约 140 GiB，主要由 Git 忽略的数据、缓存、虚拟环境和研究产物
构成；审计将这些与 Git 跟踪源码分开处理。

## 3. 当前系统地图

### 3.1 主要入口

| 入口 | 实际用途 | 状态 |
|---|---|---|
| `scripts/run_backtest.py` | 股票/ETF 主回测、报告、walk-forward | PARTIAL |
| `scripts/run_paper.py` | 本地 paper status/replay/当日缓存 bar 执行 | PARTIAL |
| `scripts/run_mining.py` | 旧策略空间 Optuna 挖掘 | PARTIAL |
| `scripts/run_research_miner.py` | 新研究因子/组合挖掘 | PARTIAL |
| `dev/scripts/oos_mvp/run_forward_observe.py` | 冻结候选的追加式 forward 观察 | COMPLETE（研究用途） |
| `dev/scripts/options/*` | 合成期权研究与 options paper ritual | PARTIAL |
| `scripts/run_all.sh` | 本地组合脚本 | PARTIAL |

“PARTIAL”并不表示这些入口不能运行，而是表示它们没有满足本任务定义的生产交易
契约。例如回测是可用的，但 corporate-action PIT、退市证券、完整容量模型和统一
event-time/available-time 数据契约仍不完整。

### 3.2 真实股票/ETF 决策和执行流

```text
YAML config + production_strategy.yaml
        |
MarketDataStore / BarStore / price_access
        |
RegimeDetector (SPY + VIX, optional TNX)
        |
Strategy.generate() -> date x symbol raw signals
        |
PortfolioConstructor -> capped target weights
        |
optional cross-ticker / decision-stack / kill-switch scaling
        |
BacktestEngine or PaperTradingEngine
        |
Order(symbol, side, qty, signal_date)
        |
ExecutionSimulator -> Fill
        |
in-memory cash/positions + SQLite paper snapshots / report artifacts
```

股票/ETF回测在 `BacktestEngine.run()` 中以 T 日 close 形成目标，并使用下一行
open 成交；缺 open 时跳单。paper daily 路径重用 `_generate_orders()` 和 simulator；
intraday 路径重用 `IntradayBacktestEngine`。这是现有架构最扎实的共享逻辑。

### 3.3 Options 实际流

```text
frozen StrategySpec
  + supplied SPY spot / VIX / SPY close history
        |
synthetic IV skew + European Black-Scholes
        |
bull put / iron condor synthetic strikes and metrics
        |
JSON manifest + daily_nav.csv + trade_log.csv
```

该路径没有 options chain provider、OCC symbol、quote time、bid/ask、volume/OI、
真实 IV/Greeks surface、broker combo order 或 assignment/exercise engine，因此只能
称为合成研究观察器。

## 4. 模块完成度

| 逻辑边界 | 代码证据 | 状态 | 主要缺口 |
|---|---|---|---|
| configuration | `core/config/loader.py`, pydantic schemas | PARTIAL | 多数 schema 未 `extra=forbid`；paper/live 分层缺失 |
| market_data | provider/MarketDataStore/BarStore/price_access | PARTIAL | 单供应商脆弱；默认绝对路径；时间/provenance 契约不统一 |
| reference_data | splits/distributions/sector map | PARTIAL | 无统一 security master/OCC/corporate-action PIT 服务 |
| corporate_actions | BarStore split/dividend cascade | PARTIAL | sidecar 漂移仅 warning；退市/并购/OCC 调整不完整 |
| feature_engine | `core/features`, `core/factors` | COMPLETE（研究范围） | 规模大但静态检查不绿，研究/运行时边界复杂 |
| regime_engine | `core/regime/regime_detector.py` | PARTIAL | 6 状态、无 confidence/UNKNOWN、输入不足返回 NEUTRAL |
| signal_engine | `core/signals`, decision stack | PARTIAL | 多套入口编排；失败有 non-fatal fallback |
| strategy_registry | production config + mining space | PARTIAL | 仅 multi-factor 可作为 production artifact build |
| portfolio_allocator | `PortfolioConstructor`, fleet | PARTIAL | fleet DD throttle/observe 明确 `NotImplementedError` |
| risk_engine | kill switch/stress/stops | BROKEN（生产目标） | 无独立统一订单否决；配置风险项未全消费 |
| order_manager | 无 | MISSING | 无状态机、ID、幂等、版本、UNKNOWN 隔离 |
| execution_engine | simulator + intraday engine | PARTIAL | 仅模拟；报价、限价、超时、部分成交恢复不完整 |
| broker_adapters | ABC + `SimulatedBrokerAdapter` | STUB | 内存即时成交；不持久；不是 paper 主真源 |
| position_reconciliation | adapter compare + EOD warnings | PARTIAL | mismatch/异常只 warning，不 fail closed |
| backtest_engine | daily/intraday/window/deferred | PARTIAL | 主路径成熟；无完整退市/PIT/capacity/option lifecycle |
| paper_trading | SQLite stock paper engine | PARTIAL | bar 幂等不是 order 幂等；事务边界和并发锁不足 |
| options_data | 空 `core/options/data/__init__.py` | MISSING | 无链/报价/历史/质量模型 |
| options_engine | BS + spreads + synthetic paper | BROKEN/PARTIAL | NAV bug；无 American/assignment/OCC/真实成交 |
| options_execution | 空包 | MISSING | 无 combo/legging/partial fill/cancel recovery |
| event_store | 无 | MISSING | 没有 append-only runtime order/risk/audit event store |
| state_store | 多个 SQLite/JSON/CSV 专用实现 | PARTIAL | 无统一事务/迁移/并发/恢复契约 |
| scheduler | `apscheduler` 依赖但无主调度服务 | MISSING | 依赖 shell/manual ritual |
| observability | logging/report/notify | PARTIAL | 无 metrics、health/readiness/liveness/alerts |
| reporting | master/intraday/forward reports | PARTIAL | 研究报告丰富；生产订单/风险 blotter 不完整 |
| secrets | `.env.example`, `.env` ignored | PARTIAL | 无 secret manager adapter/轮换；未发现已提交私钥模式 |
| llm_advisor | candidate research helpers | PARTIAL（研究） | 无统一 strict decision schema/runtime audit adapter |
| control_plane | 无 | MISSING | 无 live gate、人工审批状态和 kill-switch API |
| deployment | 无 Docker/CI/IaC | MISSING | 仅本地脚本 |
| news | `core/news/__init__.py` 空 | STUB | 无新闻/事件运行模块 |

## 5. Findings

### P0-1：paper 当日模式可在陈旧数据上产生新订单

证据：

- `scripts/run_paper.py:597-611` 从所有缓存日中取 `<= today` 的最大日期，未要求
  等于最新已完成 NYSE session；数周前的缓存也可成为 `live_date`。
- `core/data/vix_loader.py:91-105` 只将 VIX reindex 到价格 panel 的最后日期。
  如果价格 panel 本身陈旧，旧 VIX 仍非 NaN，`strict` 通过。
- `MarketDataStore.is_stale()` 和 `data_completeness_gate` 没有接入该订单入口。

影响：系统会把历史缓存当成当前交易日执行，破坏 paper 证据，未来若替换真实
Broker 则可能提交基于陈旧信息的订单。必须在生成任何新增敞口前 fail closed。

### P0-2：没有统一、独立、最终否决的 pre-trade risk engine

证据：

- `Order` 只有 symbol/side/qty/signal_date/comment。
- `PortfolioConstructor` 做权重 cap，`run_paper.py` 在 CLI 层做 kill-switch scaling，
  但 `ExecutionSimulator`/BrokerAdapter 前没有共享 `OrderValidator`。
- 没有 max order notional、strategy exposure、daily loss、gross/net/delta-adjusted、
  option risk、quote spread/liquidity 等聚合订单检查。
- 其他调用者可以直接调用 simulator 或 adapter 绕过 CLI helper。

影响：风险规则不是执行不可绕过的边界；策略错误或新入口可越过安全限制。

### P0-3：订单和 Broker 生命周期不足以安全处理未知结果

证据：

- 无 client order ID、idempotency key、decision ID、signal ID、parent/child、version。
- `SimulatedBrokerAdapter.submit_order()` 同步创建随机 ID 并立即成交；重试会再成交。
- paper 的幂等检查是 `(run_id, bar_ts) 是否已有 fill`，无 fill 的拒单/超时/崩溃
  窗口可重试生成重复提交。
- broker mirror submit/reconcile 异常在 `paper_trading_engine.py:497-548` 只 warning；
  engine 继续把本地 simulator 状态当真源。

影响：无法证明“UNKNOWN 不盲目重试”“重启不重复下单”“拒单不更新本地持仓”。

### P0-4：真实资金与内部 paper 没有明确的运行模式安全门

证据：

- 当前没有真实 Broker，因此尚不会误下真实单；但 CLI 使用 `--mode live`，README
  还称其“真正跑一天”。
- 配置无 `BACKTEST/PAPER/LIVE` 强类型 runtime mode、`live_enabled=false`、人工
  approval token 和启动风险摘要。

影响：为未来添加真实 adapter 时埋下命名/配置误启风险。必须先建立 live gate，
再允许任何真实 adapter 被构造。

### P1-1：期权 paper NAV 重复计算开仓 credit

证据：

- 开仓时 `runner.py:411-413` 扣 collateral 并把 credit 加入 cash。
- 持仓日 `runner.py:389-395` 又以 `(credit - mtm)` 作为 unrealized，加到
  `cash + collateral`，因此 credit 被计算两次。
- 独立复现：初始 $10,000、SPY 600、VIX 18、1 张 spread；次日报告
  `$10,103.4144`。cash `$8,982.7183`、collateral `$1,108.6409`、
  unrealized `$12.0553`；开仓 credit 为 `$91.3591`。正确 NAV 约
  `$10,012.0553`，报告恰好多一个 credit。
- 现有测试只断言开仓/到期存在，不验证 daily cash-collateral-liability 会计不变量。

影响：options forward 回撤、收益、止损与最终 go/no-go 证据失真。

### P1-2：options paper 的持久化不是原子、并发安全或可恢复状态机

`trade_log.csv`、`daily_nav.csv` 和 `manifest.json` 分步写；manifest 直接覆盖，CSV
直接 append，无 file lock、临时文件 rename、事务或 event ID。进程在任一步崩溃或
两个 observe 并发会造成重复交易/日志与状态不一致。

### P1-3：期权实现远低于真实美股/ETF期权要求

当前是 European Black-Scholes 合成价格；源码明确无 bid-ask、slippage 和
American early-exercise premium。没有真实 expiration calendar、dividend/borrow、
pin/assignment/exercise、multiplier/reference-data adjustment、quote quality、volume/OI、
surface、combo fill、partial fill、legging risk 或 margin/capital engine。历史“options
paper”不能作为可成交性或真实 P&L 证据。

### P1-4：regime 不满足所需状态、置信度和数据不足语义

现有六态为 `BULL/RISK_ON/NEUTRAL/CAUTIOUS/RISK_OFF/CRISIS`。无 required
`UNKNOWN/DEFENSIVE/SIDEWAYS_LOW_VOL/SIDEWAYS_HIGH_VOL/STRONG_BULL_TREND/
STRESSED_OR_DISLOCATED`，无 probability/confidence、switch cost、最短持有期；数据
不足时明确返回 `NEUTRAL` 而非低风险 `UNKNOWN`。输入主要是 VIX、SPY EMA/drawdown
和 optional TNX，缺 breadth、volume participation、credit、liquidity、skew/term
structure 与 data-quality confidence。

### P1-5：数据/时间契约不统一

- DataProvider 文档规定 daily 和 intraday 都返回 tz-naive；用户目标要求内部 UTC。
- 核心 bar 没有统一 `event_time/available_time/received_time/source/quality/is_stale`。
- `BarStore.DEFAULT_ROOT` 是用户主目录绝对路径，不利于新环境/容器。
- yfinance auto tail merge 与本地 corporate-action cascade 的基准可能不同；旧审计已
  识别 seam 风险。
- corporate-action sidecar hash 不一致只 warning，而不是需要一致价基的路径全部 halt。

### P1-6：回测仍存在需要明确披露的现实偏差

主股票路径的 T/T+1 时序和成本共享经过较多测试，未发现新的直接 look-ahead；但：

- universe 主要是当前/人工维护证券列表，无法证明历史成分 PIT 或退市完整性；
- yfinance 和本地数据修订、缺失 corporate actions、混合来源构成 revision risk；
- `open_df=None` 时使用下一行 close 作为成交代理，虽然不把该 close 用于 T 日信号，
  但成交时点和滑点模型与真实 open 不同；
- ghost position 用 last close 强平是保守恢复规则，不是退市/停牌真实成交模型；
- 没有现金利息、borrow/margin（当前 no-margin）、税务、market impact/order-book
  容量的完整模型；
- options 历史为合成数据，不能当成真实期权链回测。

### P1-7：已有防过拟合能力没有形成所有生产候选的统一强制门

CPCV/DSR/PBO/MinBTL、temporal split、sealed ledger 均有真实实现；旧审计已确认新
harness 可使用它们。但在任候选中存在旧流程遗留，且多套 mining/evaluation 入口
并存。production artifact validator 只检查布尔结果，不验证统一 evidence bundle
版本/哈希/方法。需要一个不可绕过的 promotion contract。

### P2-1：静态质量基线失败

- `ruff check core scripts tests`：1,236 个问题，674 个可自动修复；包含未定义名、
  unused import/变量、格式和命名问题。
- `mypy core --no-error-summary`：127 个 error；包含 options Optional strike、fleet
  type、forward annotation、feature pipeline 未定义名等。
- `pyproject.toml` 宣称 ruff/mypy，但没有 CI 执行。

大量命名/导入问题本身不是资金风险；F821 和关键路径类型错误必须先修，然后再逐步
收紧基线，避免一次机械格式化制造不可审查的大 diff。

### P2-2：构建不可复现且运维边界缺失

依赖只有下限，无 lock/constraints 和 hash；本地环境实际为 Python 3.13，而 README
推荐 3.14，`run_all.sh` 默认调用 PATH 中的 3.14。没有 CI、Docker、DB migration、
health/readiness/liveness、Prometheus metrics、alert rules、backup/restore drill 或 IaC。

### P2-3：异常处理过度降级

多个 runtime 路径广泛 `except Exception: pass/warning`：价格加载会无声漏 symbol，
decision-stack/cross-ticker 失败会退回另一套权重逻辑，Broker submit/reconcile 失败继续
运行。研究型可选增强可以降级，但影响订单、风险、价基和策略一致性的路径必须
fail closed 并产生人工处理事件。

### P2-4：配置与文档存在漂移

README 仍把 QQQ 描述成 6-stage hard gate，尽管代码和较新决策已将其降为 diagnostic；
README 将内部 paper live 描述为“真正跑一天”；旧文档同时使用 production/live/paper
指代不同概念。必须把运行模式、安全能力和研究证据级别写清楚。

### P3

- 顶层无 Makefile/任务入口，用户要求的一键命令未实现；
- 历史文档和 artifacts 很多，索引与当前执行真源之间认知成本高；
- 大模块（research_miner 2,344 行、forward runner 1,699 行、factor_generator
  1,593 行）维护成本较高，应在功能修复后按边界渐进拆分。

## 6. 已验证的正面能力

- Git 状态干净且主分支/远端一致后才创建接管基线；
- 配置 loader 本轮真实校验通过；
- backtest/paper CLI `--help` 本轮真实启动通过；
- `pip check` 通过，未发现已提交私钥/常见 token 模式；
- 股票/ETF backtest 和 paper 共享 CostModel/ExecutionSimulator 的重要部分；
- T+1 open、missing-open skip、holiday-aware fill label、split-adjustment、symbol cap、
  inverse ETF blacklist 等旧问题已有实现与测试；
- temporal split、forward manifest hash/drift、sealed ledger、research candidate lifecycle
  是有价值且真实存在的研究治理资产；
- 测试规模大，覆盖许多财务/时间不变量，而非只验证“不抛异常”。

## 7. 验收判定（审计时点）

| 验收面 | 当前判定 |
|---|---|
| 本地研究/股票回测 | 可用但需披露偏差 |
| 内部股票 paper | 可运行，尚非 production-safe |
| 真实 live | 禁止；架构与授权门缺失 |
| options research | 合成研究可用，NAV 证据待修复重算 |
| options paper/live | 不满足 |
| P0/P1 全处理 | 未完成，进入实施阶段 |
| CI/静态检查 | 不满足 |
| 云部署 | 不满足 |

本文件会随修复更新 finding 状态；已修复不等于删除历史 finding，而是在条目中记录
修复 commit、测试与残余风险。
