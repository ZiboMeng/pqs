# V6 Phase A 地基实现与 Data Readiness 独立审计

日期：2026-07-23

实现提交：`0bc7347c` (`feat: establish PIT phase A data contracts`)

审计结论：**软件地基 PASS；正式历史数据 readiness BLOCKED；Phase B BLOCKED。**

这不是矛盾状态。代码、schema 和验证器已经能够表达并阻断不合格数据，但当前仓库没有通过 G1-G12 的
历史数据。把“类和测试已经存在”误写成“数据已经 ready”会制造比缺代码更危险的虚假确定性，因此本轮
readiness artifact 有意将 12 个 gate 全部保持 fail-closed。

## 1. 执行边界

用户于 2026-07-23 以 `go` 批准 V6 Phase A。实际执行遵守：

- 证据范围仅为 `DATA_ENGINEERING_NO_DIRECTIONAL_RETURN`；
- 没有计算 candidate return、SPY excess、Sharpe、MaxDD、IC、label 或模型结果；
- 没有运行 Phase B trial，binding raw independent N 仍为 60；
- 没有订阅、购买、创建云资源或开启 short/LIVE；
- 原始 prospective snapshots 与 append-only ledger 存在本地 `data/pit/`，不进入 Git；Git 只保存 compact
  hash-bound evidence。

## 2. 已实施的控制面

### 2.1 契约与禁止边界

`config/pit_data_v1.yaml` 固定了 universe、availability、G1-G12 和 Phase B 条件。`PitDataContract` 对允许
操作采用显式 allowlist，并递归拒绝 returns、labels、IC、Sharpe、drawdown、signals、models 和 trials 等
方向性 artifact key。Phase B 默认 disabled，raw N 低于 60 也会被验证器拒绝。

### 2.2 永久身份、动态 universe 与统一 as-of API

`pit_security_master.py` 以 `asset_id`/vendor permanent ID 为核心，检查同一资产身份时段重叠以及同一 ticker
被不同资产在同一 session 重叠使用；ticker 历史复用本身被允许但必须时段化。动态 universe 只读取 decision
session 当时已知的 listing、trailing density、价格与流动性。

`pit_asof.py` 强制每次查询显式给出 session，没有 `latest` 捷径，并统一返回 security state、当日 eligible
assets、raw price、fundamental、filing documents 与 industry。Phase A 下不暴露派生收益接口。

### 2.3 基本面、文档、行业与市场 lifecycle

- `pit_fundamentals.py` 保存 accession/context/unit 级 fact；amendment/restatement 追加 vintage，不覆盖旧值；
  availability 严格映射到 SEC acceptance 后下一 NYSE session；
- `pit_filings.py` 规定 10-K/10-Q 及 amendments 的 hash、parser status 和 coverage/failure 契约；
- `pit_industry.py` 使用有效时段，拒绝把未来 reclassification 回填到过去；
- `pit_market_data.py` 分离 raw OHLCV、公司行动和 delisting disposition；正式退市资产若没有 source-bound
  disposition 就失败，明确禁止按最后 stale close 无损清仓。

### 2.4 Prospective 官方源 collector

collector 已真实抓取并冻结 SEC `company_tickers_exchange.json`、Nasdaq Listed 与 Other Listed 三个官方
current feed。每批保存 immutable raw response、normalized records、diff 和带前序 hash 的 append-only
ledger，写入使用文件锁与 fsync。

首批 `20260723T175930807077Z` 的 compact 结果：

- SEC 10,414 rows；Nasdaq Listed 5,556 rows；Other Listed 7,466 rows；
- normalized source records 23,436；
- ledger events 1，hash-chain integrity PASS；
- 该证据精确标为 `FREE_PROSPECTIVE_PIT`，不会冒充 2026-07-23 以前的历史 PIT。

## 3. 真实本地数据盘点

只读 inventory 指向现有主项目数据目录，得到：

| 资产 | 实测状态 |
|---|---|
| daily parquet | 25,344 files，994,312,938 bytes |
| bar provenance | 3,797,742 rows |
| splits | 4,960 rows |
| distributions | 5,376 rows |
| distribution coverage | 81 rows |
| split coverage | **不存在** |
| SEC Company Facts cache | 56 files，219,573,584 bytes |
| complete submissions | 674 raw responses，49,634 selected filings，1994-2026 |
| 已有正文 corpus | 16,180 份 **8-K** primary documents，不是 V6 所需 10-K/10-Q corpus |
| 历史研究级 vendor access | 没有发现 WRDS/CRSP/Norgate/Databento access file 或环境变量名 |

上述 bars/事件对开发很有价值，但数据量不能替代 lifecycle 证明。尤其没有 permanent identity、完整 delist
disposition 和公司行动 coverage 时，不能判断缺失证券究竟是未上市、停牌、ticker 变更、退市还是抓取失败。

## 4. G1-G12 结论

机器可读结论位于 `research/data_readiness/pit_v1/readiness.json`，并绑定 contract、inventory 与 prospective
manifest 的 SHA-256。独立 verifier 重算结果为：

```text
integrity_pass=true
all_gates_pass=false
phase_b_eligible=false
phase_b_status=BLOCKED
```

主要阻塞链路是：

1. G1-G4/G9/G12：无批准的历史永久身份/security lifecycle 数据源，因此不能构造正式动态 universe、
   delisting execution 或冻结历史 edition；
2. G5-G7：accession-level schema、availability 和 vintage 测试已实现，但尚未把完整 filing XBRL 实例转换成
   formal fact panel；
3. G8：现有正文 corpus 是 8-K，缺 historical issuer set 的 10-K/10-Q 正文与 parser coverage；
4. G10-G11：只有单元级因果性证明，没有全量 source coverage 与 prefix replay。

因此，当前正确状态不是 `Phase A complete`，而是 **Phase A foundation checkpoint complete / historical
population awaiting an approved source**。

## 5. 验证证据

最终提交前复核：

- 101 个新实现及相关回归测试：PASS；
- Ruff（全部新增 source/scripts/tests）：PASS；
- Mypy（10 个新增核心模块，`--follow-imports=skip`）：PASS；
- readiness artifact 独立完整性验证：PASS，且正确保持 Phase B BLOCKED；
- `git diff --check`：PASS。

正常递归运行 mypy 仍会触及两个与本轮无关的既有类型问题：
`core/data/source_boundaries.py:188` 的 `date | None` 排序，以及 `core/logging_setup.py:91` 的 handler 类型。
本轮没有修改或掩盖它们；新增十个核心模块自身通过检查。

## 6. 独立判断与下一步

当前最重要的下一步不是开始 ML/LLM，也不是在已有 ETF 策略周围继续微调，而是完成历史数据源验收。
具体选择与字段检查见 `docs/memos/20260723-historical-pit-data-source-decision.md`。

一旦用户提供或批准候选访问，后续固定顺序为：

1. 在无收益模式运行 vendor sample inventory 与字段/许可验收；
2. 实现 vendor adapter，生成 security master、raw market/action/delist tables；
3. 从 historical issuer set 构建 accession-bound 10-K/10-Q 与 as-filed facts；
4. 生成 coverage、missingness、prefix invariance 与人工抽样证据；
5. 冻结正式 data snapshot，重新构建并独立验证 G1-G12；
6. 仅在 `all_gates_pass=true` 后另行开放 Phase B 的最多 20 个方向性 trials。

任何一步失败都保留 prospective collector 和工程成果，但不得通过改状态文字绕过机器门禁。
