# 第二阶段范围审计

审计基线：`9ffc1ce564ca18a04554db20a442749e65f24672`

回退标签：`codex-pre-strategy-research-20260717`

工作分支：`codex/strategy-research-and-paper-v2`

审计日期：2026-07-17（America/Los_Angeles）

结论：**回测认证和策略晋升暂时 FAIL-CLOSED；先关闭 P0/P1，再开始新研究。**

## 1. 范围与方法

本轮不是重新泛化审计整个仓库，而是沿第二阶段的真实调用链重新核查：

`raw/sidecar data -> adjusted price access -> signals/regime -> portfolio weights ->`
`T close decision -> T+1 open fill -> account ledger -> metrics/walk-forward/holdout ->`
`candidate registry -> PAPER pre-trade -> fill/state/checkpoint/restart`

第一阶段已经验证的 LIVE 双闸门、订单状态机、期权隔离和运维基础不无理由重写；但凡与
回测认证、策略晋升或 PAPER 接缝相交的部分均重新验证。方法包括完整阅读任务书和第一轮
十份核心文档、静态引用/入口追踪、真实 parquet/sidecar 抽查、最小反例、602 项 focused
regression，以及对历史 sealed ledger 和失败 artifact 的谱系核查。

## 2. 现有系统与第二阶段关键路径

| 层 | 当前实现 | 第二阶段判定 |
|---|---|---|
| 原始行情 | `MarketDataStore` 保存 raw parquet；`BarStore` 在读取时按 split/dividend sidecar 调整 | 架构可保留，但价格消费者必须走唯一受控入口 |
| 价格访问 | `core/data/price_access.py` 封装 `BarStore.load(adjusted=True)` | 挖矿/PAPER 多数已接入；主回测未接入 |
| 策略与组合 | 策略输出权重；`PortfolioConstructor` 做波动率、regime、单标的 cap、归一化 | long-only 骨架可复用；需要认证信号纯度和组合聚合约束 |
| 日线执行 | `BacktestEngine`: T 收盘决策，下一可用行 open 成交，统一成本模型 | 存在价格、卖出数量、成交日期三类认证阻断 |
| 稳健性 | `WindowAnalyzer`、temporal split、CPCV/DSR/PBO 等已有组件 | 组件丰富，但默认 runner 的 walk-forward 执行语义不一致 |
| 研究隔离 | train/validation/sealed 配置、单次 sealed ledger、acceptance pack | 旧 2026 sealed 已被消费；不能重新命名为“未见最终留出集” |
| PAPER | 日线/60m 共用执行组件，SQLite state/history/order events/checkpoint | 批量风控使用旧快照；成交与账户状态不在同一原子提交 |
| Regime | 六状态分类、当前时点 confidence/UNKNOWN、改善平滑 | 可选增强；历史 confidence、冷却期和切换成本尚不完整 |
| LIVE/期权 | LIVE 默认禁用；期权独立安全边界但缺真实历史 chain | 不属于本轮强行晋升对象，代码和证据必须保留 |

## 3. 阻断项

### P0-01：主回测读取 raw 未调整价格

- 证据：`scripts/run_backtest.py:139` 和 `:154` 直接调用 raw store；规范入口是
  `core/data/price_access.py`。
- 真实数据反例：TQQQ raw/adjusted 最大倍率差 47，NVDA 为 39；SPY/QQQ 没有该反例
  只说明这两个 ticker 在样本内无 split，不能证明 loader 正确。
- 影响：含股票、杠杆 ETF、行业 ETF 的历史信号、成交和 NAV 可被拆股跳变污染；此前
  主 runner 输出和基于它的阶段一诊断数字不能作为认证证据。
- 必需修复：回测、PAPER、研究统一到可声明的 price-basis contract；添加 split 反例和
  loader parity 回归，禁止悄悄回退 raw。

### P0-02：跳空卖出可超卖并制造现金

- 证据：`core/backtest/backtest_engine.py:398` 用“目标权重差 × 前收 NAV / 次日 open”
  同时计算 BUY 和 SELL，未以实际持股数封顶。
- 最小反例：10,000 美元在 100 买入约 99.955 股；清仓日 open 跳到 50 时生成约
  199.910 股 SELL。成交现金按超卖数量增加，而持仓更新又把负值 clamp 到 0，权益错误地
  保持约 9,991，而真实跳空后应约 4,995。
- 影响：Backtest 和 daily PAPER 都复用该订单生成器。无独立风控时制造现金；有 long-only
  风控时整张清仓单被拒，导致应卖未卖。两种行为都不正确。
- 必需修复：订单生成显式接收实际 positions；SELL 永不超过持股，部分减仓按目标持股量
  算数量；对上/下跳空、整数/碎股和 backtest/PAPER 一致性加测试。

### P0-03：公司行动/分红回报口径尚未闭环

- split-adjusted 本身不足以进行长期总回报比较。当前 `load_adjusted` 默认不是 total-return；
  2007 至今 SPY total-return 与 split-only 路径终值相差约 36.37%，TLT 约 66%。
- `data/ref/distributions.parquet` 存在且哈希与当前 split sidecar 对齐，但覆盖不完整：SPY/QQQ
  最后分红为 2025-12，TLT/IEF/SHY 为 2026-04，XLP/XLU/XLB 无记录，而价格已到
  2026-07-17。
- 影响：策略和 SPY benchmark 若使用不同或不完整的回报口径，超额收益、IR、波动、回撤
  和筛选结果都不公平。
- 必需修复：定义并机器校验同一研究/回测/PAPER价格口径；刷新并验证 sidecar，或把认证
  终点显式截到完整覆盖日。禁止把不完整数据默认为“无分红”。

## 4. 高优先级缺陷

### P1-01：成交日期是推断日，不是实际使用的下一根 bar

`core/execution/execution_simulator.py:197` 用交易日历从 signal date 推断 fill date；runner
实际按 panel 下一可用行取 open。全市场缺失某一 session 时，价格来自后一个 bar，fill label
却落在更早日期。PAPER 的 `exec_date - BDay(1)` 也不等于真实上一交易 session。应把实际
signal bar 和 fill bar 明确传入执行器并持久化。

### P1-02：默认 walk-forward 与全期回测的成交价格不一致

`scripts/run_backtest.py:473` 调 `WindowAnalyzer.walk_forward` 时没有传 `open_df`：全期回测用
T+1 open，fold 退化为 next-close proxy。该 analyzer 还接收预先计算的全历史 signals；它只
是窗口切片器，不会替调用者训练/选参，因此不能泛称“真正 OOS”。固定、预注册规则可以用
它做时间验证；任何拟合或选择必须在每 fold 内完成并留 lineage。

### P1-03：旧 mining “holdout”不是最终一次性留出集

`MiningEvaluator` 对每个到 Stage 5 的候选反复读取最后 252 bars，Stage 3b 又允许在完整
`price_df` 上跑 stress period。它可作为筛选数据，不可作为最终 sealed evidence。新的 Phase 2
funnel 必须把 development、validation 和 finalist-only holdout 物理/接口隔离。

### P1-04：2026 sealed 已经消费，不能恢复成未见数据

`data/research_candidates/sealed_eval_ledger.parquet` 记录
`alternating_regime_holdout_v1 / cycle08` 于 2026-05-15 的单次评估；
`data/audit/sealed_2026_eval.json` 还保存 cycle06/cycle08 的 2026-01-01 至 2026-05-14
结果。删除 ledger、改 split 名或换文件夹都不能“un-see”这些数据。

本阶段将诚实采用：新假设先预注册；development 内嵌 walk-forward/CPCV；只让极少 finalists
进入新定义且预先冻结的 validation/holdout 段；报告明确它不是全仓库历史意义上的 pristine
2026 sealed。若证据不足，结果就是“不晋升”，而不是降低阈值。

### P1-05：PAPER 批量风控可被聚合订单穿透

`PaperTradingEngine._apply_pretrade_boundary`（`:543`）逐单检查，却为每张订单复用相同
positions/cash/equity/daily_turnover 快照。前一张已接受订单不更新虚拟账户，因此多张 BUY
可分别通过、合计后突破 min cash、gross exposure、max positions 或 daily turnover。
`run_paper.py` 也未从配置/状态接入 daily loss 和 turnover。需要顺序虚拟结算或真正的原子
batch risk decision，并持久化 session turnover/P&L。

### P1-06：订单成交与 PAPER 账户状态不是同一恢复事务

`_record_order_outcomes` 先在 OrderStore 的独立事务把 canonical order 标为 FILLED；随后
`save_intraday_bar`、`save_bar_checkpoint`、`_save_state` 又各开独立连接/事务。崩溃点可留下
“订单已成交，但现金/持仓/checkpoint 仍旧”。重启后 idempotency key 抑制重放，不能自动修复。
日线和 intraday 都受影响；逐 bar 表也没有 `(run_id, bar_ts, symbol, intent)` 唯一约束。
必须引入同一 SQLite 原子 commit 或可重放、幂等的 fill application ledger，并用 failure
injection 验证所有关键崩溃点。

### P1-07：Regime 历史标签缺 confidence/cooldown 完整语义

当前 live `assess_current` 有低置信 veto；历史 `classify_series` 在数据不足时直接 NEUTRAL，
没有逐日 confidence/UNKNOWN。恶化立即切换、改善连续 N 日确认，但没有独立 min duration、
cooldown 或 switching cost。Regime 不是强制创新点：只有在 OOS 中提供增量价值才进入策略；
否则策略保持 regime-free。若使用，先补历史 assessment contract 与边界测试。

### P1-08：价格源混合边界需要进入 artifact lineage

`daily_source_boundaries.parquet` 显示 canonical 数据约到 2026-04，之后由 yfinance frontier
延展。混合源不必然错误，但每次实验必须记录每 symbol 的数据端点、来源边界、sidecar hash、
价格口径和缺失率；否则同一候选无法确定性复算，也无法解释 forward 数据修订。

## 5. 清理审计

文件只有同时满足以下证据才可删除：

1. 静态 import、CLI、配置、测试、CI 和文档均无有效引用；
2. 动态加载、包发现、文件名约定和 artifact lineage 不依赖该文件；
3. Git 历史或审计证据不要求保留它来解释当前结果；
4. 删除后 focused regression 和相关端到端路径通过。

| 候选 | 依赖追踪结果 | 决定 |
|---|---|---|
| 约 319 个历史文档/PRD/memo | 很多无字面反向引用，但它们记录阈值变更、失败结论、sealed 消费和数据修订；absence of grep reference 不是无依赖 | **保留**，用 INDEX 导航，不批量删除 |
| temporal split v1/v2/v3 | 旧 artifact 和 dispatcher 仍按版本路由；不可变历史是复算条件 | **保留** |
| research candidates/results/ledger | 是失败归因、试验次数、holdout 消费和防重复研究证据 | **保留** |
| 空 `__init__.py` | Python package/discovery 边界；删除可能改变 import 和工具行为 | **保留** |
| `core/news/__init__.py` 空 stub | 无有效调用，但保留 namespace 的成本近零，删除收益不足以抵消动态发现风险 | **保留** |
| options 目录 | 第二阶段不晋升 options，但第一轮安全边界、测试和未来真实 chain 接口依赖 | **保留** |
| raw `MarketDataStore` | 它是合法存储层；问题是消费者绕开受控访问，不是 store 本身无用 | **保留并收窄调用** |
| 多个 price loader | 均有活跃入口；应迁移到 canonical loader 后再删除重复实现 | **现在不删，后续重构** |
| 根目录 `.codex` 0-byte 占位文件 | 未跟踪、被 ignore、0 字节、无引用，且直接阻塞任务要求的 `.codex/strategy_phase_state.json` | **已精确删除并替换为状态目录** |

结论：本轮没有其他文档或代码达到“再三确认可删”的标准。大规模清理会破坏研究谱系，
收益也小于风险；先修调用链，只有迁移完成且测试证明零消费者后再删除重复函数。

## 6. 数据与证据边界

- SPY 日线 4,915 行，2007-01-03 至 2026-07-17；QQQ 2,901 行，2015 至 2026。
- `splits.parquet` 4,960 行；拆股反例证实 sidecar 和 `BarStore` 调整机制实际有效。
- `distributions.parquet` 1,342 行但尾部覆盖不完整，当前不满足全期 total-return 认证。
- benchmark：SPY 是硬基准；QQQ 仅诊断。二者都必须与策略使用同一可复算口径。
- 现金利息、分红再投资时间、退市/成分股 survivorship、源切换边界必须在最终
  `BACKTEST_CERTIFICATION.md` 中逐项声明；没有数据就写限制，不用隐含默认。

## 7. 测试与反例结果

- 快速安全基线：195 passed，2 skipped；配置校验、Fatal Ruff、F821、24 个安全模块 mypy
  全通过。
- 第二阶段 focused baseline：601 passed，1 xfailed，0 failed（165.64 秒），覆盖 backtest、
  execution、paper trading、trading order/risk、price semantics、regime、temporal split 和
  backtest/PAPER integration。
- 这些 green tests 证明现有行为稳定，不证明行为正确；P0-02 的跳空超卖反例正说明测试
  缺少关键不变量。修复时先把反例转成失败测试，再改实现。

## 8. 审计门与实施顺序

在以下全部完成前，不运行新策略搜索、不写“通过认证”、不晋升 PAPER：

1. P0-01/02/03 关闭：统一价格口径、卖出数量守恒、公司行动覆盖可验证；
2. P1-01/02 关闭：实际 bar 日期和 T+1 open 在 full/fold/PAPER 一致；
3. P1-05/06 关闭：批量风控和崩溃恢复具备账户级原子/幂等语义；
4. `BACKTEST_CERTIFICATION.md`、最小反例、benchmark 对照、重跑 manifest 全部落盘；
5. 失败归因与新假设预注册完成，之后才可触碰各自 validation/holdout。

本审计不预先承诺一定能找到两个合格策略。第二阶段的可交付成功标准是流程诚实、证据可复算、
不合格就明确淘汰；只有真实通过既定门槛的、经济逻辑不同的候选才进入 PAPER。

## 9. 修复状态（2026-07-17）

- P0-01/02/03：**CLOSED**。回测/研究/PAPER 统一 total-return adjusted loader；81-symbol
  coverage 和 split hash fail-closed；上下跳空 share conservation 回归已落地。
- P1-01/02：**CLOSED**。fill 使用实际 bar 日期；runner 的 walk-forward 传入 open slice，
  文档不再把预计算 signals 自动称为真正 OOS。
- P1-05/06：**CLOSED**。顺序虚拟账户聚合风控、daily turnover 配置/持久化，以及订单-
  fill-account-checkpoint 同事务已通过 daily/intraday failure injection。
- P1-08：**CLOSED FOR PHASE-TWO PIPELINE**。认证 manifest 固定 sidecar/source-boundary hash；
  后续每个实验仍必须生成自己的 manifest。
- P1-03/04：**GOVERNANCE-OPEN**。旧 rolling holdout 和已消费 2026 sealed 不可修复成 pristine；
  新 funnel 必须 finalist-only 访问并诚实标注。
- P1-07：**OPTIONAL FEATURE OPEN**。新候选默认不得依赖历史 regime confidence；若研究假设
  使用 regime，必须先预注册并补齐 historical confidence/cooldown 证据。

完整认证和修复后诊断结果见 `BACKTEST_CERTIFICATION.md`。
