# PQS 独立复审与晋升治理加固记录（2026-07-21）

## 结论

本轮先对 `docs/audit/20260721-independent_audit_report.md` 的结论逐条沿调用链反证，再实施修复。独立结论是：审计报告指出的方向性风险成立——当前没有可投入真实资本的策略，资本开关应继续关闭；但“四条路径只有一条执行 SPY 规则”这一表述不完全准确。`MiningEvaluator` 和 temporal-split 路径已经通过 `config/evaluation_policy.yaml` 把 QQQ 降为诊断，真正仍冲突的是 Phase 2 promotion、acceptance pack、WindowAnalyzer 以及若干旧研究入口和误导性配置/报告字段。

本轮没有晋升任何策略，没有重跑或重签已消耗的 sealed/holdout 证据，也没有把历史失败改写为通过。新的自动晋升失败处置统一为 `REVIEW_HOLD`，不是自动删除策略；这保留了用户提出的“接近 SPY 但显著低回撤时可人工讨论”的空间，同时禁止把例外重新标成硬门通过。

## 已确认并修复的问题

### 1. 主基准与旁路

- 新增唯一的自动晋升基准判定：主基准必须是 SPY、比较口径必须是 `total_return_after_strategy_costs`、策略必须计入成本、CAGR 超额必须严格大于零。
- Phase 2 的 growth family 不再按 QQQ 路由；QQQ Calmar/Beta 只保留为非绑定诊断。
- WindowAnalyzer、mining tier、acceptance pack 和 LLM factor pre-qualification 均改为 SPY 主规则、QQQ 诊断。
- 保留历史 QQQ 字段和 archive 列以维持历史 artifact 可读性，没有篡改已冻结配置；只有显式回滚到旧 evaluation policy 时它们才可能重新绑定。

### 2. Acceptance pack 的价格与现金口径

- fresh check 不再读取 raw close。
- 执行使用 split-adjusted OHLC；信号/状态使用精确的 `(close_t + cash_t) / close_(t-1)` 总回报递推；组合只给除息日前已持有的份额记现金。
- SPY 基准改为同日期、同成本模型的 buy-and-hold 组合，QQQ 仅诊断。
- corporate-action coverage、split lineage、缺失 open、非有限值、集中度缺失和 fresh backtest 异常全部 fail-closed。
- 自动晋升不允许跳过 fresh backtest；诊断 pack 可以省略昂贵步骤，但缺口明确标为非绑定诊断，不再伪装成自动晋升 PASS。

### 3. 前视、过拟合与 paper/backtest 对齐证据

- 删除 Phase 2 里硬编码的 `no_known_lookahead=True` 语义，改成候选 ID、代码 commit、测试集合和 SHA-256 绑定的结构化证据。
- 自动晋升要求 DSR、PBO、minimum backtest length、CPCV 和 paper/backtest replay 全部通过；缺字段不是通过。
- 新增不可覆盖写入的 evidence builder；它要求 tracked worktree 干净、候选/commit 匹配，并运行固定 timing/leakage 回归测试。
- 证据必须绑定完整的关键源码与配置清单，包括回测引擎、价格访问、现金分红、因子实现、组合构造、成本模型、promotion/acceptance 代码及 system/risk/backtest/universe/governance 配置。只哈希无关文件不能再冒充完整证据。
- `production_strategy.yaml` 的 active 状态在每次加载时都会重新读取、校验并核对证据哈希，而不是只检查 64 字符长度。
- `promote_strategy.py` 不再接受 force/skip 绕过，真实写入改为原子替换，并要求 tracked worktree 干净。

### 4. PAPER 与运行时漂移

- alignment 的 warn-only 观察期结束；PAPER live 对 fingerprint/evidence 漂移采用 fail 模式。
- PAPER live 不允许 `--ignore-alignment-check`；研究 backtest/replay 仍可保留诊断灵活性。
- 旧 S0→S1 和 S1→S2 CLI 不再允许用 `--force`、`--skip-paper-run-check` 或 `--skip-drift-report-check` 制造状态通过。
- 历史 registry/artifact 原样保留，治理覆盖层继续把不满足新条件的对象留在观察或 review hold，而不是偷偷删除。

### 5. 宏观事件日历

- `events.yaml` 被明确标注为未接 runtime 的遗留草案，没有删除，因为仍有文档/配置引用。
- event factor 默认进入 precise 模式：正式 calendar 缺失、三类事件任一缺失、日期无效/重复、请求年份覆盖不全时直接失败。
- first-Friday NFP、second-Tuesday CPI 和固定周 FOMC 只允许调用方显式选择 `heuristic`，不再静默冒充精确历史事实。
- 提供 intentionally-invalid 示例模板；在正式日期未从权威日历整理完成前，事件类精确研究会被有意阻断。

## 未删除代码或文档的理由

本轮没有清理 `core/news`、`core/fleet`、`core/options`、temporal split 旧版本、旧 QQQ archive 字段或大量历史文档。只读依赖追踪确认其中一部分仍被测试、历史复现脚本、artifact schema 或隔离契约引用；其余即使 runtime 孤立，也承担历史证据和失败知识的可追溯职责。未建立“零 import + 零脚本入口 + 零 artifact/schema 依赖 + 有迁移方案”的完整证明前，不进行删除。

## 验证结果

- 最终受影响模块定向回归：172 通过、1 个依赖真实 registry 的测试跳过；早期分组结果均已被这次最终回归覆盖。
- Python bytecode compile：通过；接入只读认证数据后，代表性的 paper-candidate 全 artifact 集成测试 1/1 通过。
- 宽测试：收集 3045 项，初次结果为 2994 通过、28 跳过、23 失败。失败中 1 项是本轮 QQQ 规则改变后的旧断言，已修复；16 项是独立 worktree 缺少 Git-ignored `data/daily`/`data/ref` 导致 adjusted loader 返回空 panel，连接原项目只读数据后对应价格语义与跨策略测试 32/32 通过，forward 集成复跑首项通过；其余 6 项是既有 sealed artifact 对 `core/data/price_access.py` 的哈希漂移而 fail-closed。
- 未安装 ruff，因此没有声称 ruff 通过；以 `compileall`、`git diff --check` 和 pytest 作为本轮可复现验证。

## 残余风险与下一步边界

1. 当前不存在满足新证据协议的自动晋升候选，这是正确的零结果，不是流水线故障。下一轮策略搜索可以继续，但进入 PAPER/active 前必须产出候选绑定的 overfit 与 replay artifact。
2. 当前没有正式 `config/macro_event_calendar.yaml`，所以事件语义特征的 precise 路径会停止。可以先显式排除事件特征继续数值/语义挖掘，或从 Fed/BLS 等权威来源整理并版本化完整日历；不能使用启发式日期做精确结论。
3. 运行环境仍是 Python 3.14.4，而项目认证环境记录为 3.13.12。现有 sealed artifact 的 hash drift 不应通过重签掩盖；应在明确的新 protocol/commit 下重新建立未来证据，旧区间继续标记 consumed/not-pristine。
4. 独立 worktree 不自带大体量 Git-ignored market data。真实 acceptance/paper 集成应在只读挂载已认证 sidecar 的环境中运行，并保留数据 manifest/hash；本轮没有以临时数据链接产出任何策略结论。
5. `run_strategy_phase2.py` 现在会对缺少 qualification evidence 的候选 fail-closed。策略挖掘的下一项工程不是放松门槛，而是让 semantic/ML miner 正式输出 canonical DSR/PBO/MinBTL/CPCV qualification artifact，再并行筛出多个候选进入后续 PAPER 观察。
