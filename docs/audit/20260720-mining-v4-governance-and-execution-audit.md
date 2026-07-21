# Mining v4 治理、数据修复与首轮执行审计

日期：2026-07-20（America/Los_Angeles）

分支：`codex/governance-and-semantic-strategy-v4`

状态：numeric、SEC structured baseline 与 8-K lexical ablation 已完成；无候选获准进入组合回测或 paper。

## 1. 独立结论

本轮没有因为“用了 XGBoost”或看到单个正指标就产生候选。价量 numeric 轨的复杂模型没有增量；
完整 SEC metadata 的 structured 轨存在弱的、非稳定的预测关系，足以支付 lexical 实验成本，但尚不足以
支付 total-return 组合评估或 forward 槽位。

所有收益/组合结论继续被 corporate-action coverage fail-closed。本文的 IC 都是 split-adjusted
price-return 上的 `DEVELOPMENT_ONLY` 信号诊断，不是可投资收益。

## 2. numeric 开跑前发现并修复的问题

### 2.1 canonical daily 面板不是同一日历/价基

冻结 300 公司池第一次真实运行只得到 3,306 个 eligible cells；2015 年后 eligibility 全为 0，所有
validation observation 为 0，却被旧 harness 记成 IC=0 的“成功 fold”。根因不是弱 alpha：

- 当前池中 60 家 canonical daily 含 weekend-row 日期偏移，总计 20,360 个周末行；
- 其中纯污染序列是全部日期标签 `+1 calendar day`；部分 sidecar 在 2018 年后还混入第二条日期流，不能
  用整体平移修复；
- 156 家曾由 Phase-4 `yfinance auto_adjust=True` 替换，若再走 `BarStore(adjusted=True)` 会有重复拆股
  调整风险；
- 多标的 union 把“63 行”变成混合日历而非 63 个 SPY session，95% density 门错误清空全体股票。

### 2.2 隔离 raw snapshot

没有覆盖 `data/daily`。新 builder 从 canonical raw 或 `.preP4Expand_*` raw sidecar 建立隔离 snapshot：

- 85 家原样使用；
- 182 家只有在“平移后全部落入 SPY session”的严格证明成立时统一 `-1 calendar day`；
- 34 家混合污染序列从本地 1-minute regular session 重新聚合；
- 301/301（含 SPY）通过 weekday、SPY-session containment、OHLCV finite/bounds、unique/monotonic；
- 1m 重聚合显式 quarantine 3,192 个不完整 symbol-days；
- 每个输入、输出、splits 表、builder 和 repair module 均有 SHA-256；模型启动时逐文件重算核对。

实际采用的实例是外部 artifact `raw_daily_snapshot_v3`。v1/v2 是未采用的诊断实例，不参与最终结果。

### 2.3 ticker reuse 与 fold 假成功

NU 的本地序列同时含 2015 年旧发行人 32 天与 2021 年当前发行人。旧 eligibility 的 lifetime
`cumsum()` 会把旧公司的历史借给新公司。现在 `min_history_sessions` 改为最近 252 个 benchmark sessions
内的覆盖门，跨多年缺口不再累计。

OOF harness 现在要求每个 validation fold 至少有一个 `>=3` 个 prediction/label pairs 的横截面；空 fold
必须记为失败，不能用 `IC=0` 冒充成功。

## 3. numeric v3 有效结果

有效报告：`research/results/governed_numeric_rank_raw_snapshot_v3.json`

- 300/300 公司加载；180 个 month-end；29,548 eligible cells；
- 75,135 条非空 OOF prediction；
- Rule：mean IC `+0.01008`，10 个年度 fold 中 5 个为正；
- Linear：mean IC `-0.01166`，4/10 为正；
- XGB rank:ndcg：mean IC `-0.01257`，5/10 为正，2021–2024 连续为负；
- portfolio preflight：因 distribution/split per-symbol coverage 不完整而 `BLOCKED_FAIL_CLOSED`。

判断：numeric v1 feature set 不产生候选；不继续以同一组特征做广义超参数搜索。

## 4. SEC corpus 逆向审计

### 4.1 recent-only 结果被推翻

第一次 corpus 仅抓 submissions `filings.recent`：23,792 条目标 filing，开发期 19,158 条。该数据上的
structured XGB mean IC 一度为 `+0.02475`（4/5 fold 为正），但逆向覆盖审计发现：

- 255/300 家存在 historical shard；
- 215 家的 shard 与 2015+ 重叠；
- 82 家 recent 起点晚于 2020-01-01；
- 大型金融机构的 recent 起点甚至在 2025，2020–2024 filing 大量位于 shard。

因此 recent-only v1 不是有效历史 corpus。其结果已撤销，不在 `research/results` 保留正式 JSON。

### 4.2 complete-shard v2

构建器随后下载 300 个 main response 和 374 个与 2015–2024 相交的 historical shards：

- 674/674 HTTP 200；raw response 全量缓存并哈希；
- 49,634 条目标 filing；截至 2024 年 44,991 条；
- 开发期覆盖 281 家；外国发行人的 20-F/6-K 不被伪装成 8-K/10-Q/10-K 的零值；
- `(CIK, accession)` 为 filing 主键；跨 CIK co-filing 合法保留，未来按 document hash 去重；
- 972 条历史 metadata 缺 primary document：structured 可用，正文层明确 missing。

## 5. complete-shard structured v2 结果

有效报告：`research/results/governed_sec_structured_event_v2.json`

时间语义：`acceptanceDateTime` 转 America/New_York 日期后，严格使用下一 exchange session open；label 为
该 open 到第 5 个 session close 的 market-beta residual cross-sectional rank。

- 1,828 个 `>=3` 名事件执行日；16,186 eligible event cells；
- Linear：mean IC `+0.021999`，4/5 fold 为正；年度 IC 依次为
  `+0.0869/+0.0341/+0.0131/+0.0066/-0.0308`；
- XGB：mean IC `+0.012081`，3/5 fold 为正；年度 IC 依次为
  `-0.0169/+0.0263/+0.0404/-0.0105/+0.0212`。

判断：关系弱、衰减且模型排序不稳定。它可以进入同 cohort 的 lexical ablation，但不是组合或 forward
候选。recent-only 到 complete-shard 的 Linear 从负转正，也证明历史 corpus completeness 是结论的一部分，
不能只靠模型 OOF 名称宣称“样本外”。

## 6. trial accounting

外部 append-only ledger：`data/research/mining_v4/trial_ledger.jsonl`。

进入 lexical 前：

- numeric signal 独立尝试 12（包含被数据审计推翻的真实运行，保守计数，不抹掉）；
- structured SEC signal 独立尝试 4；
- portfolio 尝试 0；
- incomplete trial 0。

改 trial 名、重建报告或把失败称为 plumbing 不会重置试验数。

## 7. 8-K lexical ablation

冻结语料 `sec_8k_primary_docs_2015_2024_v1` 包含 16,180 份 2015–2024 8-K primary
documents，全部 HTTP 200；manifest、provenance 和逐文件 SHA-256 复核通过，正文共 665,155,833 bytes，
16,176 个唯一 document hashes。确定性 parser 得到 16,179 个 `PASS`、1 个显式 `MISSING`（PFE 的壳文件
只有 4 个 lexical tokens），通过率 99.994%，通过行无 NaN/Inf。

同一个 8-K 文本覆盖 cohort（1,518 个事件日、10,965 个 eligible cells）运行四组消融：

1. structured-only；
2. lexical-only；
3. structured + lexical；
4. structured + within-date shuffled lexical negative control。

结果（2020–2024 五个 OOF fold）：

- structured-only：Linear `+0.00167`（3/5 正），XGB `-0.00864`（2/5 正）；
- lexical-only：Linear `-0.00324`（3/5 正），XGB `+0.02900`（4/5 正）；
- structured + lexical：Linear `+0.01342`（3/5 正），XGB `+0.01057`（4/5 正）；
- structured + within-date shuffled lexical：Linear `-0.00758`（1/5 正），XGB `+0.03035`（3/5 正）。

真实 XGB 文本亮点被打乱文本完整复现并略微超过，不能解释为语义增量。组合 Linear 虽优于一次打乱对照，
但仅 3/5 fold 为正且 2024 为 `-0.0160`；lexical-only Linear 为负，也不满足稳定增量门。结论是 lexical
gate **FAIL**：不进入 TF-IDF、FinBERT/冻结 encoder 或生成式 LLM。生成式 LLM 继续只允许未来在通过低成本
门后做 schema-constrained event extraction，不直接输出权重。

## 8. 回归测试与冻结 artifact 状态

新增 SEC/lexical 定向测试 16/16 通过；numeric intent 与 shuffle bundle 测试 4/4 通过；新增/改动文件 ruff
通过。全量 `tests/unit/research` 为 1,740 passed、4 skipped、20 failed：

- 14 个 forward/paper 失败来自隔离 Git worktree 没有 Git-ignored `data/daily`；显式设置
  `PQS_DATA_DIR=/home/zibo/Documents/projects/pqs/data` 后首个原失败用例通过，但单例读取本地大面板需约
  223 秒，因此没有把这一组伪装成快速 unit test；
- 6 个 sealed 测试被旧 `observation_v1` artifact 正确 fail-close。该 artifact 相对当前治理分支有 3 个
  绑定组件漂移：`core/data/price_access.py`、`core/data/price_basis.py`、`config/risk.yaml`。正式策略已在
  `REVIEW_HOLD`，不得为了测试通过重签或覆盖旧证据；恢复前必须创建新 artifact version 并重新审批。

## 9. trial accounting 与下一优先级

lexical 后 hash-chain 验证为 48 events / 24 trials / 0 incomplete：numeric 12、structured SEC 4、lexical 8、
portfolio 0。早期 4 个 structured SEC intent 因复用 helper 将实际 5-session label 误记为
`market_residual_rank_21d`；计算和正式 JSON 的 5-session 标签正确，账本旧行保持不可篡改并在此披露；之后
8 个 lexical intent 已使用正确 label id。

当前不应继续堆模型。最优先的基础设施工作是补齐隔离 snapshot 的 distribution 与 split query coverage；
在 total-return sidecars 可验证前，任何声称可跑赢 SPY 的组合结果都必须继续 `BLOCKED_FAIL_CLOSED`。
