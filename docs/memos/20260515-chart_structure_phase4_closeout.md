# Chart-structure 输入表征层 —— Phase 4 closeout

**日期**: 2026-05-16
**Lineage**: `chart-structure-input-repr-2026-05-15`
**execution PRD**: `docs/prd/20260515-chart_structure_ralph_loop_execution_prd.md` §8
**loop log**: `docs/memos/20260515-chart_structure_loop_log.md`(P4·R1/R2/R3)
**termination promise**: `CHARTSTRUCT-P4-DONE`

---

## §1 Phase 4 做了什么(大白话)

Phase 4 把 chart-structure 研究能用的股票池从 **79 只扩到 328 只**,
并且做到一件关键的事:**扩张完全不影响之前任何一个结论**。

为什么要扩:Phase 2A 的负结果(12 个 swing 特征无显著增量 IC)根因之一
是「79 只票太小 + 101 个老因子已经把趋势/形态信息吃饱了」。在更大的票池
上重做检验,结论可能不同 —— 这是用户选 option A(先 Phase 4)的理由。

3 个 round:
- **P4·R1** —— 建 universe 解析器(单一入口 + flag 隔离)。
- **P4·R2** —— 建 expanded universe + ingest 数据 + 多轮数据 audit。
- **P4·R3** —— universe 隔离回归测 + 本 closeout。

## §2 D6 隔离契约 —— 扩张不碰旧结论

这是 Phase 4 的硬约束(用户反复强调)。落实方式:

- `resolve_universe(name)` 是唯一入口。`name` 默认 `"executable"`。
- `resolve_universe("executable")` **逐符号、顺序一致**地复现 Phase-4
  之前的 79-symbol 构造 —— 单测 `test_executable_resolution_bit_for_bit`
  逐一比对 `union(seed+sector+factor+cross_asset)` 减
  blacklist/macro/cycle-drop 再补 SPY/QQQ 的结果。
- `expanded_v1` 是**单独的 yaml**(`config/universe_expanded_v1.yaml`),
  只有显式传 `--universe expanded_v1` 才会用到。`config/universe.yaml`
  **一个字节都没动**。
- forward manifest 不会漂移:forward 的 `ConfigSnapshot.universe_hash`
  按文件名 hash `config/universe.yaml`,新增 `universe_expanded_v1.yaml`
  在它的 hash 输入集之外 —— **P4-A3「forward manifest diff == empty」
  由此结构性成立**,单测 `test_forward_universe_hash_excludes_expanded_yaml`
  证明。
- 解析器在 `core/research/forward/` 下零引用 —— 单测
  `test_resolver_has_zero_forward_path_coupling`。

结论:cycle04-12、所有 forward 候选、Phase 1.5/1.6、chart-structure
Phase 1/2A 的结果都**不会**被这次 universe 扩张回溯影响。

## §3 expanded_v1 票池怎么选的

- 扫了 `data/daily/` 全部 25344 个 parquet。
- 筛选(确定性、可复现):ticker 形如 `^[A-Z]{1,5}$`;首 bar ≤
  2015-02-01;末 bar ≥ 2026-04-01;≥ 2500 行;重新 ingest 后 0 weekend
  行。按「最近 252 bar 的中位美元成交额」降序,取非-79 的 top 流动性
  符号。选入的流动性下限 ~2.3 亿美元/日。
- 最终:**79 base + 249 added = 328**。

## §4 数据 audit —— 抓到并修掉的真问题(诚实交代)

用户明确要求「数据一定要干净、多做几轮 audit」。`phase4_data_audit.py`
跑了 4 轮:

| 轮 | 检查 | 结果 |
|---|---|---|
| R1 | 索引卫生(单调/无重复/无 weekend/无 tz/无 intraday) | PASS 328/328 |
| R2 | OHLC 有效性(high≥low、high≥max(o,c)、正价、无 NaN) | PASS 0 fail / 1 benign warn |
| R3 | 动态(完整度 gate + 跳变结构) | PASS,完整度 gate 328/328 |
| R4 | 边界(跨源字节稳定 + D6 隔离) | PASS |

**audit 抓到 2 个真问题(不是走过场)**:

1. **store 规模化 off-by-one bug**:覆盖度 audit 发现 `data/daily/` 里
   3357 个长覆盖 ticker 带 weekend-row(SPY off-by-one 日期标签 bug 的
   规模化遗留),只有 82 个干净。→ 选入 expanded_v1 的 240 个 corrupt
   符号经 **fixed `YFinanceProvider(auto_adjust=True)`** 重新 ingest;
   重 fetch 后 0 weekend 行。executable-79 不受此影响(早已修复)。

2. **DOW / SE NaN-pad**:这两只在流动性排名里靠前,但实际 IPO 晚于
   2015(DOW Inc 2019-03-20、Sea 2017-10-20)。yfinance 批量下载把它们
   NaN-pad 回 2015 起点 —— `_validate` 当时只看 `idx[0]`(被 pad 的
   2015 日期)没看 `first_valid`,漏过了。R2 的 `nan_ohlc` 检查抓到。
   → parquet 裁到真实首日,**从 expanded_v1 剔除**(251 → 249)。

**audit 自身的 false-positive 也修了**:R3 第一版 gap 检测用
`pd.bdate_range`,把美股假期误算成缺口(误报 PWR/ABT/LLY)。改为 defer
到权威 `core.data.data_completeness_gate.check_panel_completeness` —— 不
重复造轮子,用项目 SoT。

**剩余的非问题(已 root-cause,不是脏数据)**:
- R2 唯一 warn:XLI(base-79)末 bar high < open 0.04% —— polygon
  aggregation 末 bar 微小取整 artifact,base-79 既有数据,非本轮引入。
- R3 跳变:21 个是 base-79 raw-store 的 split 跳变(**预期** —— raw 存储,
  splits 在 read-time cascade);7 个是 added 符号真实事件(AMD 2016
  财报暴涨、INSM/ALNY 生物科技 Phase 3 二元事件、PG&E 破产、DHR 分拆
  Fortive)—— 都是真实行情,不是数据损坏。
- **249 个 added 符号本身极干净:0 weekend、0 缺失 session、0 OHLC
  违规、0 NaN** —— 比 base-79 polygon 数据还干净。

## §5 已知 caveat(写明,不藏)

- **expanded_v1 是 mixed-source**:79 base = polygon raw bars +
  splits.parquet read-time cascade;249 added = yfinance
  `auto_adjust=True`(split+div 调整连续序列)。两种调整语义不完全一致。
  可接受,因为:(a) expanded_v1 是 research-only、D6 隔离、永不进
  execution;(b) chart-structure 特征是 scale-invariant 的比值,IC 是
  rank-based 横截面度量。已在 yaml 头 + audit artifact flag。
- `data/daily/` store 里还有 3357 个 ticker 带 off-by-one weekend-row
  —— 本轮只重建了选入 expanded_v1 的部分;广域 store 重建是独立工作,
  不在 chart-structure loop scope 内。

## §6 Acceptance —— Phase 4

| AC | 判据 | 结果 |
|---|---|---|
| P4-A1 | resolver + `--universe` flag 全入口 + `test_universe_flag_all_entrypoints` | ⚠️ **AMENDED 2026-05-16 audit**(原「✅ 6 单测」是 overclaim):`resolve_universe` + chart-structure 研究脚本(phase2a + phase3_run_{3a,3b,3c})接 flag ✅;production 主入口(run_research_miner/factor_screen/xgb)**刻意 resolver-free**(更强 D6 隔离,operator 决策);`test_universe_flag_all_entrypoints`(7)钉真实契约。详 `docs/memos/20260516-chart_structure_prd_audit.md` §4/§5.1 |
| P4-A2 | `executable` bit-for-bit 复现 Phase-4 前 79 构造 | ✅ 逐符号顺序比对单测 PASS |
| P4-A3 | forward manifest diff == empty(隔离回归) | ✅ `universe_hash` 结构性独立于 expanded yaml;5 隔离单测 PASS |
| P4-A4 | 过 `data_completeness_gate` + weekend/cross-symbol smoke | ✅ 328/328 完整度;0 weekend;4 轮数据 audit 全 PASS |

artifact:`data/audit/chart_structure/phase4_universe_audit.json`(P4-A4)、
`data/audit/chart_structure/phase4_data_audit.json`(4 轮数据 audit)。
单测:`tests/unit/universe/test_universe_resolver.py`(6)、
`test_universe_isolation_p4r3.py`(5)。
脚本:`dev/scripts/chart_structure/phase4_{universe_audit,ingest_expanded,data_audit}.py`。

## §7 下一步

`CHARTSTRUCT-P4-DONE`。回到 Phase 2B R2-R4(TS2Vec 自监督 embedding +
GAF 转图 + 语料 manifest + 注入),然后 Phase 3(chart-native CNN)。
expanded_v1 已就绪 —— 后续 chart-structure 实验可用 `--universe
expanded_v1` 在 328 票池上重做 incremental-IC,检验 Phase 2A 的负结果
在更大样本上是否改变。

**`CHARTSTRUCT-P4-DONE`**.
