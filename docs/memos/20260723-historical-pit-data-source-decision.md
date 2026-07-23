# V6 历史 PIT 数据源决策备忘录

日期：2026-07-23

状态：`USER DECISION REQUIRED BEFORE PROCUREMENT OR FORMAL INGESTION`

适用契约：`config/pit_data_v1.yaml` / `pqs-pit-data-v1`

## 结论

当前不能用仓库已有 bars、current ticker 列表或 Yahoo/Polygon 下载结果解锁
`FORMAL_HISTORICAL_PIT`。本地数据量很大，但缺少可证明的永久证券身份、完整历史上市/退市状态、逐证券
退市处置和公司行动 coverage；其中 `split_coverage.parquet` 在实际 source root 中不存在。

推荐顺序如下：

1. **若用户已经拥有学校、机构或雇主许可的 CRSP/WRDS 访问，优先接入 CRSP US Stock daily。** 其
   PERMNO/PERMCO、name history、distribution 与 delisting 数据最直接匹配 V6 G1-G4；但必须先核对许可是否
   允许本项目用途和本地派生数据保存。
2. **若没有机构访问，先做 Norgate Platinum 的接口可行性验证，不直接购买。** 它对个人用户更现实，
   官方列出的 Platinum 包含 1990 年以来的当前及退市证券、历史 major-exchange 状态和 capital-event
   指标；但官方同时说明，退市证券按最后已知 ticker 保存，且名称/ticker 会复用。这不能自动满足 V6 的
   完整历史 alias interval 和永久身份契约。其官方 Python 支持仅列为 Windows，和当前 Linux 环境也有
   运维摩擦。免费试用只提供最近两年，足以验证 API/字段，不足以完成 2012-2024 正式面板。
3. **若不批准任何外部数据访问或费用，继续 `FREE_PROSPECTIVE_PIT`。** 该路径能从 2026-07-23 起形成
   真实可 replay 的 universe，但不能倒推出历史 PIT，也不能开放 Phase B historical mining。

不建议为了 V6 另购 historical fundamentals：SEC accession-bound filings/XBRL 应由项目自行构建；本轮
真正不可替代的采购对象是历史 security master、价格、公司行动与 delisting lifecycle。

## 独立依据

CRSP 官方说明 PERMNO/PERMCO 是跨名称变化、重组和公司行动的永久标识；其正式数据指南包含 name
history、分配/拆股、delisting reason、delisting return/amount/next price 等字段。这与 V6 的身份和退市
契约高度一致。另一方面，CRSP 的订阅页明确提示其数据库主要面向学术机构、政府和投资专业许可方，
个人投资者应考虑其他服务，且页面没有公开固定报价。因此，CRSP 是**字段首选**，不是可以假设个人可
直接购买的默认方案。

Norgate 官方 US package 页面当前列出：Platinum 历史回到 1990、含 delisted securities，6 个月
USD 346.50、12 个月 USD 630；Diamond 回到 1950，6 个月 USD 433.13、12 个月 USD 787.50。V6 目标从
2012 开始，因此如果字段验收通过，Platinum 的历史长度已经足够，不应为更长但本轮不用的历史默认购买
Diamond。

但“包含退市证券”不等于“满足正式 PIT”。Norgate 官方 FAQ 说明，一个退市证券以最后已知公司名与
ticker 存在，而不是保留所有旧名称/ticker；同一 ticker 还可能被不同证券复用。Accessibility 页面也
提示第三方插件未必暴露数据库全部内容，并将受支持的 Python 接入标为 Windows。基于这些公开信息，
Norgate 只能作为**条件式候选源**，必须先通过下面的字段验收。

官方资料：

- [CRSP subscription information](https://www.crsp.org/subscription-information/)
- [CRSP PERMNO/PERMCO](https://www.crsp.org/research/permno/)
- [CRSP US Stock database guide](https://www.crsp.org/wp-content/uploads/guides/CRSP_US_Stock_%26_Indexes_Database_Guide_Flat_File_Format_2.0.pdf)
- [Norgate US stock packages](https://norgatedata.com/stockmarketpackages.php)
- [Norgate data content](https://norgatedata.com/data-content-tables.php)
- [Norgate data-package FAQ](https://norgatedata.com/data-package-faq.php)
- [Norgate accessibility](https://norgatedata.com/accessibility.php)
- [Norgate general FAQ](https://norgatedata.com/faq.php)

## 采购前字段验收

任何候选 vendor 必须提供一个不含收益分析的 sample/export，并逐项通过：

| 验收项 | 最低要求 | 对应 Gate |
|---|---|---|
| 永久身份 | security-level stable ID；ticker 不能作为主键 | G1 |
| 身份时段 | ticker/name/exchange/share-class 的有效起止日，可识别 ticker reuse | G1/G2 |
| 上市生命周期 | 当日 active/inactive、list/delist date、security type | G2/G9 |
| 日频交易数据 | raw open/close/volume，明确 auction/venue 定义和缺失规则 | G2/G4 |
| 公司行动 | cash/special distributions、split/reverse split、reorganization 与生效日 | G4 |
| 退市处置 | delist reason，以及 return、consideration 或 source-bound missing code | G3/G4 |
| 版本与修订 | release/cut date、revision policy、可冻结 edition/hash | G12 |
| 接入与许可 | 当前 Linux/Python 可重复导出；许可允许研究、派生结果与必要本地留存 | G12 |

任何一项只有营销描述、没有 sample 字段或许可证明，都保持 `BLOCKED`。尤其禁止把“有 delisted ticker”
推断成“有可执行的 delisting return”。

## 建议的最小决策

下一步只需要用户选择一条，不涉及策略参数：

- 提供现有 CRSP/WRDS 或其他机构数据访问方式；或
- 允许创建 Norgate 免费试用账户并在 Windows 环境做字段/API 验收，验收后再单独决定是否购买
  Platinum；或
- 明确本阶段保持零采购，仅积累 prospective PIT。

在该决定前，Phase B 继续由机器门禁阻断，binding raw independent trial N 保持 60。
