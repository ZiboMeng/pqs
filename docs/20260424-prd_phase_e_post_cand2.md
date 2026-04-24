# PRD: Phase E-post 收尾 + 第二个 Orthogonal Candidate 并行 Paper 验证

## 1. Executive Summary

本 PRD 是当前阶段的**统一执行主文档**，目的只有两个：

1. **完成 Phase E 的最小收尾**，把已经搭好的治理链路、paper 过渡层和关键工程债收干净。
2. **在不扩 universe、不新开大规模 mining 的前提下**，基于现有
   `RESEARCH_FACTORS` 构造一个与 `RCMv1` 明显正交的第二个 candidate，
   并让两个 candidate 进入并行 paper 验证，建立真正的对照参考系。

这份 PRD 明确：

- **现在不做 universe extension**
- **现在不做新一轮大规模 factor mining**
- **现在不做 Production Layer**
- **现在不做 heavy model 研究**

这不是"停滞"，而是为了避免在治理与验证层尚未完全闭环时继续扩大研究
空间，导致后续结论混乱。

本 PRD 的逻辑是：

> 先把治理和 paper 过渡层真正收尾，
> 再用第二个正交 candidate 让 paper 层从"单样本验证"升级为"可比较
> 验证"，最后基于 paper feedback 再决定 universe extension / new
> mining / new data tier 是否值得做。

---

## 2. 为什么现在不优先做 Universe Extension / New Mining

### 2.1 当前系统的主瓶颈不再是 universe size

当前可交易 universe 已经达到约 79 symbols 规模。对当前阶段来说，这
已经足以支撑：

- research composite miner
- orthogonal feature experimentation
- benchmark-relative candidate construction
- paper-layer 对比验证

继续做 Stage 3 universe 扩张，最大的可能不是立刻带来更清晰的 alpha，
而是：

- 加大 beta / 风格噪声
- 恶化归因
- 让 paper drift 和 candidate-specific 行为更难解释

### 2.2 当前最缺的是"第二参考系"

目前 governance + paper pipeline 已主要被 `RCMv1` 一个 candidate 验证
过。这样会带来两个问题：

1. **治理链路样本量不足**：一个 candidate 跑通，不代表 candidate
   lifecycle 设计已经足够可靠。
2. **paper 层没有比较基准**：如果只有 `RCMv1` 在跑 paper，就无法清楚
   区分：
   - drift 是 candidate-specific 的
   - drift 是 paper implementation 的
   - drift 是 replay / data / execution 假设的系统性问题

### 2.3 继续新 mining 的边际信息增益不如第二个 candidate

当前系统并不缺"还可以继续搜索"的空间。当前更缺的是：

- 一个与 `RCMv1` 正交的第二候选
- 一组真实的并行 paper feedback
- 一套可比较的 drift / turnover / concentration / benchmark-relative
  观察

因此，当前继续开一轮大规模 mining，在信息增益上不如：

> 用现有 `RESEARCH_FACTORS` 构造第二个正交 candidate，并让它进入
> paper 对照验证。

---

## 3. 当前阶段的明确范围（Scope Freeze）

### 3.1 本 PRD 要做的事

本 PRD 只做两条主线：

**主线 A：Phase E-post 收尾** —— 只收真实剩余 gap：

1. paper path 再解耦 `MarketDataStore`
2. research mask 阈值统一
3. 依赖声明补齐
4. revoke 在真实 candidate 上演练
5. migration / paper CLI 的 hermetic / clean-failure 收尾

**主线 B：第二个正交 candidate**:

1. 从现有 `RESEARCH_FACTORS` 中构造第二个与 `RCMv1` 明显正交的
   candidate
2. 让它走完整的 `S0 -> S1 -> S2`
3. 与 `RCMv1` 并行 paper 跑
4. 建立 10/20/40/60 trading-day checkpoints

### 3.2 本 PRD 明确不做的事

- Stage 3 universe extension
- 新一轮大规模 factor mining
- 新数据 vendor / earnings / options / alt data 接入
- Production deploy / broker / execution / kill switch
- scheduler / daemon / airflow / paper automation
- 大规模历史 artifact 回溯 bundling
- 大规模 repo docs 重组
- heavy model research（Transformer / decoder-only / encoder-decoder）

### 3.3 为什么现在不做这些

因为这些动作会同时引入：

- 新 research 变量
- 新系统复杂度
- 新归因难题

而当前最需要的是：

- 把现有治理链路彻底坐实
- 让 paper 层从"单样本验证"升级为"对照验证"

---

## 4. Phase E-post：只收 5 个真实 gap

### 4.1 E-post-1：继续解耦 paper path 与 `MarketDataStore`

**目标**: 让 paper runner 的核心逻辑不再直接依赖具体 parquet-backed
store 实现。

**当前问题**: 虽然 `MarketDataStore` 中的 `pyarrow` 已改为 lazy
import，但：

- `scripts/run_paper.py` 仍直接 import `MarketDataStore`
- `scripts/run_paper_candidate.py` 也仍直接 import `MarketDataStore`

这意味着 import 级别的耦合缓解了，但 paper runner 级别的数据访问
耦合仍然存在。

**本阶段要做的事**:

1. 让 `run_paper.py` 不再把 `MarketDataStore` 作为默认直接入口
2. 让 `run_paper_candidate.py` 依赖数据访问接口 / loader / factory，
   而不是具体 store
3. 让 paper 层逻辑依赖"数据访问边界"，而不是具体 parquet store 类
4. 不要求整个 data layer 全量重构，只要求把 paper path 解耦出来

**验收标准**:

- `from core.paper_trading.paper_trading_engine import PaperTradingEngine`
  不触发 `pyarrow`
- paper 层关键单测在不初始化 parquet stack 的情况下可运行
- `run_paper_candidate.py` 不因直接 store 依赖而强绑数据后端

**常见坑**: 误以为 lazy import 已经完全解决问题；趁机重构整个 data
layer，导致 scope 爆炸；把 dependency injection 做得过重，反而增加
复杂度。

### 4.2 E-post-2：统一 research mask 阈值

**目标**: 把 research 样本定义从"脚本里散落的参数"升级为"统一、
可审计、可比较的配置"。

**当前问题**: 多个脚本仍然各自写自己的 `min_price` / `min_usd` /
`window` / 其他 eligibility / tradability 相关阈值。这会导致 research
结果 silently 漂移、acceptance / paper / miner 的样本口径不一致、
后续比较失真。

**本阶段要做的事**:

1. 建立统一的 research mask config
2. 梳理以下脚本的参数来源：research miner、research acceptance、
   `run_paper_candidate.py`、关键模型 / diagnostics / sensitivity 脚本
3. 区分：样本定义参数、特征工程参数、实验参数
4. 至少让 research acceptance、paper candidate runner、candidate
   validation 共用同一套核心 eligibility 规则

**验收标准**:

- 关键脚本不再散落硬编码主阈值
- 任一结果能回答"它用的是哪套 research mask 口径"
- paper 与 research 的核心 eligibility 口径一致

**硬 invariant（见 §10.2）**: Unified mask 在
`post-2026-04-24-rcm-v1-lag1` lineage 窗口上产出的 eligibility set
必须与 RCMv1 现有口径 bit-for-bit identical。

**常见坑**: 一次性把所有参数全收进一个大 config，反而更乱；只改主
脚本，不改周边 diagnostics；混淆 sample definition 和 feature 参数。

### 4.3 E-post-3：补齐依赖声明

**目标**: 让 fresh environment 更接近真实可复现，不再依赖"当前机器
上正好装过"。

**当前问题**: 代码里真实 import 了 `requests` / `scipy` / `tqdm` /
`pyzipper` 等，但依赖声明并未完整覆盖。

**本阶段要做的事**:

1. 对最新仓库做一遍真实 import 核对
2. 区分：核心依赖 / 研究可选依赖 / 开发运维依赖
3. 更新依赖声明
4. 同步更新 README 中的安装说明（如果当前说明已经过时）

**验收标准**:

- fresh env 能完成当前阶段主链路所需安装
- 不会因缺隐含依赖导致 freeze/promote/paper 流程中断

### 4.4 E-post-4：在真实 candidate 上演练 revoke

**目标**: 证明 revoke 不是"存在脚本"，而是"在真实候选上可以安全演练
的治理动作"。

**当前问题**: 虽然 `revoke_candidate.py` 已存在、单测已存在、多种
revoke reason 已定义，但还没有在真实 `RCMv1` candidate 上做过一次
负路径演练。

**本阶段要做的事**:

1. 选择演练方式：dry-run revoke 或 clone 一份真实 candidate 再演练
2. 演练以下内容：状态变更、revoke reason 记录、memo / supporting
   artifact 引用、对 paper 状态的影响
3. 明确：真正唯一的 S2 样本不得被无保护打废

**验收标准**:

- revoke 在真实 candidate 衍生路径上完成一次演练
- registry / state / memo / artifact 链路一致
- 结果可审计

**常见坑**: 直接拿唯一真实 S2 candidate 做 destructive test；只改
状态不留审计痕迹；把 revoke 仍然当成 paper 层专属动作。

### 4.5 E-post-5：修 migration / paper CLI 的 hermetic / clean-failure 问题

**目标**: 让当前治理链路在"最小环境 / 非本地遗留状态"下也更可验证。

**当前问题 A（migration dry-run 依赖 runtime data contract）**:
`migrate_rcm_v1_memo_to_registry.py --dry-run` 仍会隐式依赖
`data/mining/rcm_archive.db::rcm_trials` 的存在（见脚本 line 63-78
的 spot-check）。

**当前问题 B（paper CLI clean-failure contract 需要收窄与写实）**:
此前对 `run_paper_candidate.py` 的问题表述过宽。当前代码已经对
**empty close panel** 做了 clean failure（`frames["close"].empty` →
`logger.error(...)` + `return 1`）。因此"空 panel 直接抛异常"不应
继续作为笼统表述。本阶段真正要处理的是：

- migration / test 的 hermetic 性
- paper CLI 在非 happy-path 条件下的**可预测失败合同**是否足够清晰
- 若存在**非 empty panel 的 dtype / tz / index mismatch** 路径，则
  必须先提供可复现 repro 再纳入修复范围

**本阶段要做的事**:

A. migration/test hermetic 化
  - 让 migration 测试使用最小 fixture 或可注入 archive path
  - 避免测试依赖本地运行遗留状态

B. `run_paper_candidate.py` clean-failure contract 收口
  - 保留并验证现有 empty-panel clean failure 行为
  - 若存在其他非 happy-path（例如 dtype / tz / index mismatch）导致
    异常退出的路径，必须先写 repro，再修复
  - 明确 paper CLI 的错误码 / logger 语义，使失败可预测而不是依赖
    底层异常文本

**验收标准**:

- migration dry-run / 相关测试在最小环境下可预测
- `run_paper_candidate.py` 对 empty-panel 情况保持 clean failure
- 若新增收口其他失败路径，必须有明确 repro 与对应测试

---

## 5. 第二个 Orthogonal Candidate：构造原则

### 5.1 目标

构造一个与 `RCMv1` 明显正交的第二个 candidate，用于：

- 让 governance pipeline 被第二个真实样本再验证一次
- 为 paper 层建立第二参考系
- 对比 drift / turnover / concentration / benchmark-relative 行为
- 为后续决定 universe extension / new mining 提供更强依据

### 5.2 不是"找第二个高分 spec"

第二个 candidate 的目的不是再找一个"分数最好"的 spec。它的目的应该是：

> **构造一个经济逻辑清晰、与 `RCMv1` 明显正交、适合做 paper 对照组
> 的 candidate。**

### 5.3 正交性要求

第二个 candidate 至少应满足以下要求：

**A. 经济逻辑与 `RCMv1` 不同**: 若 `RCMv1` 偏防御型 / downside /
regime-aware / risk-overlay 友好，那么第二 candidate 应偏
benchmark-relative / residual strength / risk-adjusted continuation /
medium-horizon trend quality / 或 stock-selection oriented 的横截面
逻辑。

**B. 持有期 / turnover 轮廓不同**: 第二 candidate 不应与 `RCMv1` 在
交易节奏上高度同构，否则 paper 对照信息不够新。

**C. 结构比 `RCMv1` 更简单**: 第二 candidate 应优先追求可解释、
可冻结、可对照，而不是比 `RCMv1` 更复杂。见 §5.6 的硬约束。

### 5.4 候选因子来源

**只允许使用现有 `RESEARCH_FACTORS`。**

本 PRD 明确：不做新 feature engineering；不做新的 factor mining；
不做新数据层接入。

### 5.5 候选构造原则（硬约束）

**因子数量**:

- **固定 3 个 factor**
- **equally-weighted（每个权重 = 1/3）**
- 明确禁止：TPE / Optuna 调权；grid search 调权；任何形式的隐式
  小 mining

**选入门槛（硬）**: 每个 factor 必须在 `post-2026-04-24-rcm-v1-lag1`
窗口上同时满足：

- Spearman IC `p < 0.05`
- 在 6 个 regimes 中至少 **3 个**为正 IC

**与 RCMv1 的正交性约束（硬）**: 在 shared paper window 或等价共享
观察窗口上：

- Candidate-2 composite 与 `RCMv1` composite 的相关性 `< 0.5`
- Turnover profile 与 `RCMv1` 至少差异 **20%**

**因子维度**: 建议分别来自不同子维度，例如 benchmark-relative /
residual、risk-adjusted return、trend quality、downside / state
filter。

**允许的起始方向（示例，不是强制）**:

- `residual_mom_spy_20d`
- `return_per_risk_21d`
- `trend_tstat_20d`
- `rolling_sharpe_126d`（可作为备选，但要警惕与已有 trend-quality
  家族同源性）

最终组合不应凭"好看直觉"拍板，而应以：与 `RCMv1` 的风格差异、
可解释性、可冻结性、turnover / concentration 初筛来确定。

### 5.6 额外设计原则

**simpler than RCMv1 必须是可验证约束**: "更简单"不能只是一句描述，
必须体现在：

- 因子数固定为 3
- 权重固定等权
- 不做调权搜索
- 有明确的正交性与 turnover 差异门槛

**不是第二次 mining**: Candidate-2 的构造本质上是假设驱动、约束
驱动、对照组驱动，而不是在现有 `RESEARCH_FACTORS` 上偷偷做一轮
小型优化器搜索。

---

## 6. 第二个 Candidate 的执行链路

### 6.1 从现有 RESEARCH_FACTORS 中人工 / 半规则选择候选组合

禁止为它单独开一轮大型 mining。选择过程必须满足 §5.5 的所有硬
约束，并在 decision memo 中记录每一条约束的具体数值。

### 6.2 走完整的治理路径

必须完整走：

- `S0`: Research Prototype
- `freeze_research_candidate.py`
- `research_promote.py`
- `S1`: Research Candidate
- `paper_enter.py`
- `S2`: Paper Candidate

### 6.3 产出完整 artifact

至少包括：

- frozen spec YAML
- decision memo
- acceptance / validation summary
- registry record
- paper run outputs
- drift report outputs

### 6.4 与 `RCMv1` 并行 paper

第二个 candidate 进入 S2 后，应与 `RCMv1` 并行 paper 运行，而不是
串行排队。原因：

- 当前最缺的是对照参考系
- 并行 paper 的价值大于再做一个孤立候选

---

## 7. 并行 Paper 观察框架

### 7.1 为什么不用"等 60 天后再看"

60 trading days 作为一轮观察窗口是合理的，但不应机械等待到第 60 天
才分析。如果第 10 天就出现严重 drift、第 20 天就出现异常
concentration、replay vs paper 差异明显不可解释，那么应尽早识别，
而不是等满 60 天。

### 7.2 Checkpoints

**Checkpoint 1: 10 trading days** —— 这是一个 **operational sanity
checkpoint**，不是 research-signal checkpoint。关注：signal 是否
稳定生成、paper artifacts 是否完整、drift 是否异常、target portfolio
/ turnover 是否合理、两个 candidate 的初期 live-like 行为是否明显
不同。

明确说明：10 天 drift 样本太小；任何 bps 级数字都**不应**直接驱动
revoke / reject / research 结论；这一 checkpoint 主要用于发现
pipeline / artifact / portfolio construction 层的问题。

**Checkpoint 2: 20 trading days** —— 关注：turnover / concentration
是否开始分化、paper vs replay 差异是否可解释、是否出现
candidate-specific 的问题。

**Checkpoint 3: 40 trading days** —— 关注：风格轮廓是否稳定、
benchmark-relative 表现路径是否开始分化、drift 是系统性还是
candidate-specific 更清晰。

**Checkpoint 4: 60 trading days** —— 关注：完整对比 `RCMv1` 与
Candidate-2、做下一轮 research 路线决策。

### 7.3 每个 checkpoint 至少要看什么

- benchmark-relative path
- replay vs paper drift
- turnover
- concentration
- paper artifacts completeness
- 是否触发 manual review（例如 drift > 50 bps）

---

## 8. 做完这个 PRD 之后再决定什么

本 PRD 完成后，再回答以下问题：

### 8.1 是否值得 extend universe

只有在以下任一结论出现时才值得讨论：

- 两个 candidate 在 current universe 上都表现出结构性饱和
- paper feedback 表明现有 feature family 已无法提供足够差异
- benchmark-relative 结果表明 universe coverage 明显不足

### 8.2 是否值得开新一轮 factor mining

只有在以下条件满足后才值得：

- E-post 收尾完成
- 第二个 candidate 已进入并行 paper
- 至少一个 checkpoint 给出明确反馈
- 有新的正交信息增量，而不是只想"继续推进节奏"

### 8.3 是否值得接新数据层

只有在以下情况下才值得：

- 两个 candidate 都显示 current OHLCV / benchmark-derived feature
  space 已接近饱和
- paper feedback 不能用治理/执行层问题解释

---

## 9. 明确写死的非目标（Non-goals）

本 PRD 明确不承担：

- Universe Stage 3 扩张
- 新一轮大型 factor mining
- 新 feature engineering
- New vendor / alt data / earnings / options 接入
- Production execution / broker / kill-switch
- Automated paper orchestration
- 大规模 repo 重组

---

## 10. 执行细节 (execution contract)

### 10.1 E-post 子项执行顺序（硬）

为降低风险，E-post 按以下顺序执行（ralph-loop R1-R5 一一对应）：

1. **R1 = E-post-3**（依赖补齐）—— 预计 0.5 天，改动最小，最快
   获得 green light
2. **R2 = E-post-5A**（migration hermetic）—— 预计 0.5 天，小 bug，
   容易单独验证
3. **R3 = E-post-4**（在 rcm_v1 clone / dry-run 上演练 revoke）——
   预计 0.5 天，纯治理路径 exercise
4. **R4 = E-post-1**（paper path 继续解耦 `MarketDataStore`）——
   预计 1-1.5 天，中等 refactor
5. **R5 = E-post-2**（research mask 统一 + invariant diff 验证）——
   预计 1.5-2 天，风险最高，且最可能改变研究口径，因此放最后

### 10.2 Unified mask invariant

统一 research mask 之后，必须满足以下 invariant：

> **在 `post-2026-04-24-rcm-v1-lag1` lineage 窗口上，Unified mask
> 产出的 eligibility set 必须与 RCMv1 现有口径 bit-for-bit
> identical。**

验证方式：对 unified mask 与当前 RCMv1 路径的 eligibility 输出做
diff；只有在 diff 为零的情况下，才允许将 Candidate-2 的 paper drift
与 RCMv1 的 paper drift 做直接比较。

原因：如果 unified mask 改变了样本集合，那么 Candidate-2 vs RCMv1
的差异会混入 sample-definition 差异，失去对照价值。

### 10.3 Loop execution constants

若本 PRD 通过 ralph-loop 推进，写死以下常量：

- `lineage_tag = phase-e-post-2026-04-24`
- `completion_promise = EPOST_CAND2_DONE`
- `target_rounds = 8`
- `max_iterations = 10`（8 + 2 buffer）

**Round map**:

| Round | Scope | Output |
|-------|-------|--------|
| R1 | E-post-3 deps 补齐 | requirements.txt diff + README 安装章节同步 |
| R2 | E-post-5A migration hermetic | migration 脚本 + 测试可注入 archive path |
| R3 | E-post-4 revoke 在 rcm_v1 clone 上演练 | revoke audit trail + rejection memo 样本 |
| R4 | E-post-1 paper path 解耦 MarketDataStore | PaperTradingEngine import 无 pyarrow |
| R5 | E-post-2 research mask 统一 + invariant diff | unified mask config + diff=0 验证 |
| R6 | Candidate-2 构造 + S0→S1→S2 全链路 | 2nd candidate 在 registry 中 @ S2，paper run 启动 |
| R7 | **Exhaustive 代码审计**（详见 §10.5） | R1-R6 改动面全量 AST/smoke/test sweep |
| R8 | **Docs 瘦身 + 同步**（详见 §10.5） | README.md + CLAUDE.md slim + final synthesis |

### 10.4 Candidate-2 被拒绝也算 PRD 成功

本 PRD 不应因为 Candidate-2 质量不够而"永远无法完成"。若 Candidate-2
在以下任一阶段被拒绝：

- `research_promote.py`
- `paper_enter.py`

则仍然视为 PRD 成功的一种。必须产出一份
`docs/YYYYMMDD-candidate_2_rejection_memo.md`，记录：

- 被哪一条 gate 拒绝
- 原因是什么
- 未来 re-try 前需要修什么

理由：gate 真实地拒绝一个候选，本身就是 governance pipeline 有效
的正向验证。

### 10.5 最后两轮 (R7 + R8) 的强制扫尾

**R7 — Exhaustive 代码审计**（参考 audit-v2 R1+R2 合并版口径）：

1. 对 R1-R6 所有 touched files 做 AST 级 scan：
   - Unused imports (exclude `__future__`)
   - Silent `except: pass` 是否 legitimate
   - Shadowed builtins
2. 对 `core/research/` + `core/paper_trading/` + `core/data/` 做
   一次 full import + static-check sweep（因为 R4 paper path 解耦可能
   牵动 core/data 的 public-API 边界）
3. `pytest tests/ -q`（unit + integration 全量）—— 必须与 R6 结束
   时的 baseline 相等（无 > 10 tests regression）
4. `--help` sweep 所有 touched scripts + 新增 Candidate-2 相关脚本
5. Round report：R7 报告要像 audit-v2 R1+R2 那样给出具体 bug list +
   具体 fix list + 具体 delta

**R8 — Docs 瘦身 + 同步**:

1. **README.md 同步**:
   - §1.4 Current state 补 Phase E-post 条 + Candidate-2 状态
   - §4 tree 和 §6 quick-start 若涉及 paper path / mask config 改动
     要同步
   - §14.1 test count 和 §8 Script list 刷新
   - Footer 加 v1.4 条目（按 v1.3 模板）
2. **CLAUDE.md 瘦身**:
   - "Current TODO Checklist" 所有 COMPLETE 项（Deep Mining 50R /
     RCMv1 20R / audit v1 / audit v2 / Phase E 14R / Phase E-post
     8R）统一压缩为**单行摘要 + 历史 doc 引用**
   - 历史详情移到新 `docs/20260424-claude_md_phase_e_history.md`
     （参照 `docs/20260422-claude_md_phase_bc_history.md` 的模式）
   - Current TODO 只留**真正 active 的 TODO**（Older TODO 里 data /
     intraday / research 未闭环项 + Phase E-post 余留 8.1-8.3
     决策问题）
   - 目标：CLAUDE.md 瘦到 < 800 行（当前 ~1100+ 行）
3. **Final synthesis doc**:
   `docs/20260424-phase_e_post_cand2_final_synthesis.md`，格式参照
   `docs/20260424-phase_e_final_synthesis.md`。包含：
   - 8 rounds summary
   - E-post 5 gap 交付清单
   - Candidate-2 final spec + registry state + orthogonality metrics
   - parallel paper status (两个 candidate checkpoint-1 初始观察)
   - Decision readiness 评估：§8.1/8.2/8.3 的 4 个问题现在能否回答

**R8 最后必须包含的动作**:

1. 在 final synthesis doc 中重新复述 §10.6 列出的 3 条"与 audit-v2
   launcher 的关键差异"（让审计员事后翻阅时不必再回查 launcher 源码）
2. emit `<promise>EPOST_CAND2_DONE</promise>`

### 10.6 与 audit-v2 launcher 的关键差异

本次 `dev/scripts/loop/start_phase_e_post_loop.sh` 相较
`dev/scripts/loop/start_codebase_audit_loop.sh`（audit-v2 使用的
launcher）有 3 处有意的偏离。R8 final synthesis doc 必须显式重复
这 3 条以便审计员事后审阅。

**D1. 不 auto-generate PRD**

audit-v2 launcher 会在 `docs/20260424-prd_codebase_audit_3round.md`
缺失时 auto-generate 一份 heredoc 内嵌的 PRD。本 launcher 不做。
原因：

- 本 PRD 714 行（audit-v2 PRD ~140 行），嵌 heredoc 后 launcher
  超过 800 行，可读性塌陷
- 本 PRD 已经作为正式 committed artifact 入 git，不再需要
  launcher 作为 fallback 备份

行为差异：launcher 检测不到 PRD 时**直接 exit 1**并输出 `git log
-- <path>` + `git checkout <sha> -- <path>` 恢复指令。

**D2. PAUSE 规则更严 —— `--force revoke` 真实 RCMv1 被硬拦**

audit-v2 的 Pause-for-user 只覆盖 config schema change / public API
删除 / dependency 增加 / schema migration。本 PRD §12.2 额外加：

- 任何 `--force` revoke 真实 `rcm_v1_defensive_composite_01` 必须
  PAUSE 并走用户确认

原因：rcm_v1 是当前**唯一**的真实 S2_paper_candidate 样本，如果
R3（revoke drill）的 loop 自动化不小心把真实样本打废，整个 paper
对照参考系会被摧毁。clone 路径演练是强制的。

**D3. R7 halt 条件 —— 审计发现 >5 真 bug 不强推**

audit-v2 的 halt 条件只有 5 条（轮数上限 / test 回归 / core import
断 / disk 不够 / 触发新 PRD）。本 PRD §12.3 追加第 6 条：

- R7 exhaustive audit 若发现 > 5 个真 functional bug（不是 unused
  import 级的 bit rot，是会改行为的 bug），loop 必须 halt 并 surface
  给用户；**不得**把 R7 变成"把 R1-R6 的坑顺便补了"的 catch-all
  垃圾桶

原因：R7 的角色是**验证** R1-R6 没破东西，不是**修复** R1-R6 的遗漏。
如果 R7 发现 >5 真 bug，意味着 R1-R6 某一轮或多轮质量不过关，应该
回到那一轮重做而不是在 R7 里一把梭。

---

## 11. 成功标准

### 11.1 E-post 收尾成功标准

- `run_paper.py` / `run_paper_candidate.py` 与 `MarketDataStore` 的
  直接耦合进一步降低
- research mask 阈值统一进入可审计配置，且 invariant diff = 0
- 依赖声明补齐
- revoke 在真实 candidate 路径上演练过
- migration / paper CLI 的 hermetic / clean-failure 问题修掉

### 11.2 Candidate-2 成功标准

- Candidate-2 由现有 `RESEARCH_FACTORS` 构造完成（3 factor 等权）
- 与 `RCMv1` 具有清晰正交性（相关 < 0.5，turnover 差 ≥ 20%，或被
  §10.4 rejection memo 成立覆盖）
- 完整走通 `S0 -> S1 -> S2`（或 rejection memo 成立）
- artifact 完整
- 与 `RCMv1` 并行进入 paper（或 rejection memo 成立）

### 11.3 R7 审计成功标准

- 0 functional regression (tests 全量 pass)
- R1-R6 touched files 全量 AST scan 清洁（unused imports / silent
  excepts / shadowed builtins 按 audit-v2 口径通过）
- 所有 --help smoke rc=0

### 11.4 R8 docs 瘦身成功标准

- README.md v1.4 footer 条目完成
- CLAUDE.md < 800 行，只留 active TODO
- `docs/20260424-phase_e_post_cand2_final_synthesis.md` 存在并含
  R1-R8 11-part Chinese 汇总
- `docs/20260424-claude_md_phase_e_history.md` 承接被瘦掉的历史表

### 11.5 决策成功标准

完成本 PRD 后，团队能更有把握地回答：

- 当前 drift 是系统性的还是 candidate-specific
- 当前 universe 是否真是瓶颈
- 当前 feature family 是否已经接近饱和
- 下一轮应该做 universe、feature、数据层，还是继续 paper 观察

---

## 12. Rules of engagement

### 12.1 Authorized autonomously

- Bug fixes inside existing files (including tests)
- Docstring corrections
- Adding missing tests for discovered bugs (regression guards)
- README.md + CLAUDE.md edits (per R8 scope)
- `requirements.txt` / `pyproject.toml` additions (per R1 scope only —
  this PRD explicitly allows it, otherwise forbidden)
- `data/research_candidates/registry.db` updates via official CLIs
  (`freeze_research_candidate.py` / `research_promote.py` /
  `paper_enter.py` / `revoke_candidate.py`)
- Unified mask config file (new `config/research_mask.yaml` or
  extension of `config/universe.yaml::data_sensitivity`)

### 12.2 MUST pause for user

- Any modification to `config/production_strategy.yaml` or
  `PRODUCTION_FACTORS`
- Any change to `scripts/promote_strategy.py` semantics
- Any mutation of `core/mining/archive.db` or
  `core/mining/rcm_archive.db` schema
- Any new vendor / data layer / broker adapter
- Any `--force` revoke of the real `rcm_v1_defensive_composite_01`
  (must use clone path per §4.4)

### 12.3 Halt conditions (any one triggers halt)

1. 8 rounds completed (hard ceiling) — emit EPOST_CAND2_DONE if all
   success criteria met
2. Systemic regression: test count drops by > 10 tests
3. Core import breaks (`python -c "from core.research.candidate_registry
   import CandidateRegistry"` fails)
4. Disk free space < 10 GB
5. A finding requires a schema migration or a new PRD to resolve —
   stop and surface to user
6. R7 audit detects > 5 real functional bugs in R1-R6 changes (rollback
   signal; surface to user instead of force-finishing)

---

## 13. 一句话总结

**当前最专业、最稳妥的下一步，不是继续扩 universe 或再开一轮大
mining，而是先用一个 very small 的 E-post 收尾包把治理链路收干净，
再基于现有 `RESEARCH_FACTORS` 构造第二个与 `RCMv1` 正交的 candidate，
让两个 candidate 在 paper 层并行跑出真正可比较的反馈；最后两轮
(R7 + R8) 做 exhaustive 代码审计 + docs 瘦身收尾。**
