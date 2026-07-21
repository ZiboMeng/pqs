# Mining v4 精确现金复审、结论重跑与下一轮实验

日期：2026-07-21（America/Los_Angeles）

分支：`codex/governance-and-semantic-strategy-v4`

结论：上一轮 `v5` 的价格语义审计不充分，相关研究结论已正式作废；精确现金 `v6`、四条研究线重跑和一个预注册低换手实验已完成。没有策略获得自动晋升、sealed forward 或 paper 资格。

## 1. 对上一轮和独立判断的复审

上一轮正确的判断：

- 不放宽“含成本跑赢 SPY + 滚动窗口 + 相对回撤”三重门；
- 不因失败自动删除 candidate，也不把 exceptional near-miss 自动当作 PASS；
- 当前公司池有 survivorship bias，开发结果不是历史 OOS；
- 数值 XGB 没有稳定胜过简单基线，不应因“更智能”而默认升级；
- SEC 高频事件组合必须经过真实成本，frictionless 只能解释机制；
- LLM 不得直接定权，sealed feedback 不得反哺同期开发。

上一轮错误或证据不足的判断：

- 把 `v5` 称为可用总回报价基是错误的。它使用 `1 - D/P_prev` 回填 OHLC，只是供应商式近似，不是精确现金账户；
- numeric 特征和 21 日 label 仍用不含分派的 split-adjusted close；SEC 5 日 event label 也漏掉持有期内应得现金；
- 因此上一轮 numeric near-miss、structured IC、lexical incremental gate 和 event portfolio 数值都不能继续作为有效选择证据；
- `v5` 下“文本不足以升级表示层”的结论过早。`v6` 同 cohort 负对照显示真实 lexical 有可复核增量，但仍不足以让生成式 LLM 直接进入决策层。

机器可读作废记录：

- `research/results/governance/price_basis_v5_invalidation.json`；
- 原 `price_basis_v3_invalidation.json` 已增加后续 supersession 指针；
- `v3`、`v5` 报告和 ledger trial 全部保留，不能删除或借作废重置 multiplicity。

## 2. 根因与精确现金修复

对 296 个当时可用标的、11,581 个可比现金事件独立复算发现，`v5` 的中位累计误差虽仅约 `0.023%`，但特殊分派存在材料性错误。最显著案例：

- KDP，2018-07-10，现金分派 `$103.75`，前收盘约 `$123.66`；
- `v5` 当日收益与精确账户的绝对误差约 `9.61` 个百分点；
- WULF、BKR、MO、OXY 等也有显著单日偏差。

修复后的契约：

1. OHLC 保持拆股已调整、分派未回填的真实执行价格；
2. 每个 symbol/session 单列 `cash_distribution`；
3. 特征和 close-to-close label 使用精确总回报递推：
   `TR_t / TR_(t-1) = (close_t + D_t) / close_(t-1)`；
4. 回测组合只给除息日前一收盘已持仓的份额记入 `qty * D_t`，并在除息日 open 成交前到账；
5. 除息日 open 新买入不领当日现金，open 卖出仍领取；
6. 组合永远使用 raw split-adjusted OHLC + cash ledger，禁止再把 synthetic total-return OHLC 与现金同时使用，避免双算。

实现提交：`f0c3b50`。定向测试覆盖特殊分派、首日不可观察事件、缺失事件日期、隔夜持仓、除息日新买入、现金感知 numeric 特征和 SEC event entitlement。

## 3. 不可变 `v6` 数据证据

快照：`yahoo_exact_cash_ledger_2007_2024_v6`

- manifest SHA-256：`c8382dfbddfe2522c37558bb2f3c573fefedb3893c803d80abe1db9b93e80c46`；
- builder commit：`f0c3b50f96f40efe84e36c15c73e438ac69b424a`；
- 301/301 source parquet、raw response 和 output parquet hash 链验证通过；
- 11,799 个现金事件，4 个历史起点前事件显式跳过；
- 精确递推最大绝对误差 `4.44e-16`，门限 `1e-12`；
- 296 个 eligible symbols（295 公司 + SPY）；
- `ASML/DHR/JCI/TMUS/TSM` 因同日 distribution + split 组合歧义 fail-closed；
- 最大事件为 KDP `$103.75`，占前收盘 `83.90%`，在 manifest 中显式记录；
- Yahoo 仍是非官方源，分派事件按现金或现金等价价值处理，不能称 production-grade vendor certification。

35 个 corporate-action cross-query mismatch 经追踪均属于较粗旁证查询漏事件，日线原始响应包含事件；没有观察到同一日期金额互相冲突。该差异继续保留在 manifest，不被静默删除。

## 4. `v6` 重跑结果

### 4.1 Numeric

有效报告：`governed_numeric_rank_exact_cash_v6.json`。

信号层 10 折平均 Rank IC：

| 模型 | Mean IC | 正 IC fold 比例 | 独立判断 |
|---|---:|---:|---|
| Rule rank | `+0.00160` | `5/10` | 很弱但可解释 |
| Linear rank | `-0.00232` | `5/10` | 全截面平均无稳定增量 |
| XGB rank:ndcg | `-0.01510` | `4/10` | 复杂度没有价值 |

30 bps 下值得注意的组合：

| 构造 | CAGR 超额/SPY | 252 日滚动胜率 | MDD/SPY |
|---|---:|---:|---:|
| Rule active Top-10 | `+5.99%` | `63.34%` | `0.984x` |
| Rule SPY35 + equal Top-10 | `+4.41%` | `64.68%` | `1.014x` |
| Rule SPY35 + rank-vol | `+1.67%` | `60.00%` | `1.022x` |
| Linear SPY35 + rank-vol | `+5.08%` | `66.59%` | `1.096x` |

多个构造通过开发 gate，但这不是晋升证据：模型/构造已在 2015–2024 OOF 组合上被观察，且 universe 是 2026 当前公司池。60 bps 时 Rule active/equal 仍有 `+0.62%/+0.92%` 年化超额，Linear rank-vol 为 `+1.11%`，但滚动胜率均低于 60%。

### 4.2 SEC structured 和文本负对照

Structured 全事件 cohort：Linear/XGB mean IC 为 `+0.01696/+0.02602`，各 `4/5` fold 为正。

相同 8-K 文本 cohort：

| 特征 | Linear mean IC | XGB mean IC |
|---|---:|---:|
| Structured only | `-0.00747` | `+0.00721` |
| Lexical only | `+0.00611` | `-0.00292` |
| Structured + real lexical | `+0.01307` | `+0.01681` |
| Structured + shuffled lexical | `-0.00929` | `-0.00754` |

真实 lexical 同时胜过 same-cohort structured 和 shuffled control，说明文本表示层值得继续研究。证据仍然很小、fold 数只有 5、没有含成本组合通过，因此下一步只允许 frozen representation / train-only clustering / schema-constrained extraction；不允许 LLM 直接生成信号或权重。

### 4.3 SEC event portfolio

精确现金重跑没有改变经济结论：

- Structured Linear frictionless CAGR 超额 `+2.31%`、滚动胜率 `84.79%`；30 bps 后为 `-21.28%`、滚动胜率 `0%`；
- Structured XGB frictionless 已为 `-1.65%`；30 bps 后为 `-24.52%`；
- 30 bps 约 16,500 fills，当前 5 日 overlay 不可交易；
- 不再调 threshold、holding period 或 sibling construction。

## 5. 预注册低换手实验

唯一实验：`spy35_active65_equal_top10_buffer15_membership_only`。

- 实现提交：`ebb3d46`；
- 预注册提交：`194ef34`；
- 预注册文件：`research/preregistrations/20260721-rule-rank-buffer15-v1.yaml`；
- 在查看结果前锁定 Top-10、exit rank 15、SPY 35%、active 65%、单股 cap 10%、只在成员变化时再平衡、成本 30/60/90 bps；
- 明确标记 `DEVELOPMENT_ONLY_POST_SELECTION`、禁止自动晋升和历史 OOS 声明。

结果：

| 成本 | CAGR 超额/SPY | 252 日滚动胜率 | MDD/SPY | 年化 gross traded notional/NAV |
|---|---:|---:|---:|---:|
| 30 bps | `+4.14%` | `62.90%` | `1.045x` | `8.63x` |
| 60 bps | `+1.17%` | `49.27%` | `1.049x` | `8.61x` |
| 90 bps | `-1.72%` | `34.21%` | `1.053x` | `8.60x` |

30 bps 开发 gate 通过，60 bps 超额比原 equal Top-10 略好。但 120 个评估月有 119 个月发生 membership change；交易笔数只减少约 6%，slippage 减少约 12%–17%。它是成本稳健性的增量改善，不是“真正低换手”的突破。按预注册约束不继续搜索 buffer=12/20 等兄弟参数。

## 6. 测试、ledger 和清理决定

- 本轮新增/相关定向测试：全部通过；组合 helper 7/7、精确现金/feature/SEC/backtest 合计 41/41；ruff 与 bytecode compile 通过；
- 全量 `tests/unit`：4,303 passed、34 skipped、25 failed。16 个失败由隔离 worktree 缺少 Git-ignored `data/daily`/`data/ref` 引起；在原数据目录重跑的前 22 个代表用例全部通过后，为避免重复长耗时中止。另 9 个失败是旧 sealed/runtime artifact 检测到 `core/data/price_access.py` 指纹漂移后正确 fail-closed；
- 不为刷绿重签 production/sealed artifact。正式策略状态未修改；
- append-only ledger 当前 258 events / 129 trials / 0 incomplete，SHA-256 `57d198b227e0b71d09556c9e1733371ea3315cf1191ef36394294ed011d75490`；
- 没有删除旧报告、失败 trial、下载 partial 或旧快照。它们有 provenance、复现实验或 multiplicity 用途；通过 invalidation 和有效路径隔离，而不是物理删除。

## 7. 下一步独立判断

1. Buffer-15 保留为未来确认候选，但停止同族参数搜索；它尚不能进入 sealed forward。
2. 数值 XGB 停止；Linear/rule 的历史组合结果只作为开发线索，等待真正未来数据。
3. 下一项最高信息价值工作是文本表示层：固定同一 8-K cohort，先做 frozen encoder 或 train-only embedding/SVD clustering，并保留 shuffled、structured-only 和 lexical-only 对照。
4. 只有表示层在预注册的 fold-level incremental gate 和含成本低换手组合层都成立，才允许 schema-constrained LLM extraction；LLM 仍不得直接定权。
5. 现有 SEC 5 日 event overlay 停止，不把正 IC 误当成可交易 alpha。
