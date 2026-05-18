# P0-A 修复 PRD —— 价格 loader 统一走 BarStore adjusted + 价基回归测试

**日期**: 2026-05-18
**lineage**: `p0a-loader-barstore-fix-2026-05-18`
**状态**: **DRAFT — 未授权**;实现需用户 explicit-go。
**触发**: 大清盘 audit P0-A
(`docs/audit/20260518-grand_stocktaking_audit.md` §1.A + §1.A.q)。
**纪律**: `feedback_no_blanket_failure_verdict`、
`feedback_no_over_conservative_scoping`(全 roadmap 进 scope,排序≠
砍 scope)、`feedback_audit_surfaces_not_thorough`、
`feedback_self_audit_methodology`、`feedback_temporal_split_discipline`、
`feedback_pre_post_audit_must_smoke_observe`(动 live 候选前必 smoke)。

---

## §0 一句话(大白话)

挖矿**搜索**入口 + paper + 因子筛选用 `MarketDataStore.read()` 读
**raw 未复权价**,绕过文档强制的 `BarStore.load(adjusted=True)` split
cascade。修法 = **价格消费层 loader 统一走 BarStore adjusted + 加
loader 层价基回归测试**。**不重写 raw 数据存储**(data/daily 按设计
就是 raw,cascade 是 read-time 的活),**不全量回挖所有 cycle**
(backstop 量化 §1.A.q 证主轴 raw≈adjusted Spearman 0.96,主力
nominee 选择本就稳)。修它是 **根治"一类反复打补丁" + 解锁短周期
因子可信 + 因子库 IC 诚实重算**,不是"过去全错"。

---

## §1 Root cause(audit 已实证)

- `core/data/market_data_store.py:149-174` `read()` = 读 raw parquet +
  日期过滤,零 split 调整,不 delegate BarStore。
- 价格消费层误用 `MarketDataStore`(raw):
  - `scripts/run_research_miner.py:33,103,692`(Track-C 挖矿**搜索**)
  - `scripts/run_paper.py:332,392`(paper)
  - `scripts/run_mining.py:53,57`(legacy 挖矿)
  - `scripts/run_factor_screen.py:80`(143 因子 / 16 families IC)
- 正确范式(已在用):`cycle*_track_a_eval.py` / `run_sealed_2026_eval`
  / `attention_report` / ml_redo / pead 均 `BarStore.load(adjusted=
  True[, adjusted_total_return])`。
- 严重性(诚实,backstop 量化 §1.A.q):主轴(中长动量+vol+drawup)
  raw≈adjusted(Spearman 0.964,top-3 同,翻转全在噪声级短周期因
  子)→ **主力 nominee 选择稳**;**残余真风险 = 短周期因子
  (ret_1d/ret_5d/rev_5d)合成候选** raw 符号不可靠。

---

## §2 范围内(全 committed;排序见 §6,非 scope-cut)

### F1 价格消费层 loader 统一
- **F1-A1**: 新增 `core/data/price_access.py::load_adjusted_panel(
  symbols, freq, root, fallback)` 单一入口,内部
  `BarStore.load(adjusted=True)`(OHLCV+volume 经 splits cascade,
  含 NaN-vol 安全)。
- **F1-A2**: `run_research_miner._load_price_volume` /
  `run_paper.py` 价格加载 / `run_mining.py` / `run_factor_screen.py`
  改调用 F1-A1。**MarketDataStore 本身不删**(ingest/raw 存储/
  provenance accessor 合法保留);仅**价格消费 callers** 切换。
- **F1-A3**: `MarketDataStore.read` 加 docstring 警示 + 可选
  `assert_not_price_consumer` 钩子(防新代码再误用,no hard break)。

### F2 价基回归测试(CLAUDE.md 早要求、从未覆盖 loader 层)
- **F2-A1**: `tests/unit/data/test_price_semantics_regression.py` —— 已
  知 split 票(NVDA/AAPL)经 F1-A1 加载:(a) 与 `BarStore.load(
  adjusted=True)` bit 对齐;(b) split 日无 spurious 单日 |ret|>50%;
  (c) raw vs adjusted 在 split 日发散(反向断言,证测试有效)。
- **F2-A2**: loader-contract 测试:每个 F1-A2 改造点的输出 == F1-A1
  输出(防回归再绕过)。≥6 测。

### F3 因子库 IC 诚实重算(recompute,非重挖)
- **F3-A1**: F1 后重跑 `run_factor_screen` → 143 因子 / 16 families
  IC/IR adjusted 重算;产 `docs/audit/<date>-factor_ic_library_
  adjusted_restate.md` 对照(raw→adjusted),诚实重述,不假装旧值。
- **F3-A2**: 重算用 train-only(temporal_split 纪律),sealed 不读。

### F4 parity + live 候选边界(最敏感,smoke 硬前置)
- **F4-A1**: F1 改 `run_paper` 价基 → **M11a/M11b paper-vs-backtest
  parity 必须重验仍 bit-for-bit**(两侧同步 adjusted);回归测试。
- **F4-A2**: **live forward/paper 候选(cycle06/08 evidence、
  spy_8otm options paper)价基变更 = 当 data-revision-event 处理**,
  不静默改 live soak 序列;走 v2.1 revalidate fail-closed / 显式
  new-run boundary。**改动落地前对全部活跃候选跑 `observe
  --dry-run` smoke**(pre/post 对比,无 drift 才合入)。
- **F4-A3**: pead 独立 track / simple_baseline(yfinance)/ ml_redo /
  G1-G5 不受 F1 影响(已 adjusted/独立,实证)——回归断言其不变。

### F5 standing 结论诚实重述(留痕,不重挖)
- **F5-A1**: 更新 audit memo + CLAUDE.md 相关行:哪些 caveat **CLEAR**
  (主轴 nominee 选择 per §1.A.q 稳)、哪些**保留**(短周期因子合成
  候选 selection 仍 suspect;过 adjusted gate 的业绩仍真)。
- **F5-A2**: **不全量回挖 cycle04-12**(backstop 量化证主轴稳 + 已
  DEPRECATED + 重挖巨贵)。仅当某 live 候选 edge 被实证短周期主导
  且影响决策时,opt-in 单候选 adjusted 重挖(非默认)。

---

## §3 非目标 / 明确不做

- **不重写 `data/daily/*.parquet`**(按设计 raw,cascade 是 read-time;
  重写会破坏文档化架构 + 与 BarStore 双调整)。
- **不删 MarketDataStore**(raw 存储/ingest/provenance 合法消费者)。
- **不全量回挖所有历史 cycle**(§F5-A2)。
- 不改 long-only/no-margin/QQQ rule/temporal_split partition。
- 不读 sealed 2026。

---

## §4 对在跑工作的影响矩阵(预答"会影响什么")

| 对象 | 影响 |
|---|---|
| cycle06/08 Track A PASS + sealed 2/2 | **不变**(本就 adjusted 算的) |
| cycle06/08 / pead / options live forward 观察 | F4-A2:价基变更当 data-revision 处理 + smoke 门;**不静默改 live 序列** |
| cycle04-12 mining 数值 | 已 DEPRECATED;F5 重述不重挖 |
| 143 因子库 IC | F3 recompute(分钟级,非重挖)+ 诚实重述 |
| ML-redo / PEAD / G1-G5 / simple_baseline | 不受影响(实证 adjusted/独立),F4-A3 回归断言 |
| M11a/M11b parity | F4-A1 重验必须仍 bit-for-bit |

---

## §5 验收口径

- F1-F5 各 machine-checkable AC + F2 价基回归测试通过 + F4-A1 parity
  bit-for-bit + F4-A2 smoke-observe 全活跃候选无 drift = PRD 完成门。
- 4-tier 自审(R1 事实/R2 逻辑/R3 真跑对比期望/R4 边界)+ 禁 blanket
  verdict + 诚实重述不假装旧值。
- 实现需用户 explicit-go;遵重活串行;F4 smoke 为硬前置。

---

## §6 实现排序(sequencing,非 scope-cut;F1-F5 全进 scope)

1. **F1**(loader 统一,纯结构,无 live 风险)
2. **F2**(价基回归测试,锁住不再绕过)
3. **F3**(因子库 IC recompute + 重述)
4. **F4**(parity 重验 + live 候选 data-revision 边界 + smoke 门)——
   最敏感,放后面,smoke 硬前置
5. **F5**(standing 结论诚实重述留痕)

每项独立 commit + 单测 + 报告 + 自审。

---

## §7 大白话总结

挖矿搜索/paper/因子筛选读的是没除权的原始价。修法就一句:**算因子/
收益的地方,把数据加载从 MarketDataStore 换成 BarStore(带除权),
再加一个测试卡死它别再绕过去**。不重写原始数据库(那是设计如此)、
不把所有历史 cycle 重挖一遍(量化已证主力候选其实稳)。修它的价值
是**根治一类反复打补丁 + 让短周期因子可信 + 把 143 因子库 IC 诚实
重算**;最需要小心的是 paper 那块——cycle06/08 还在跑,改它价基要当
"数据修订事件"走 fail-closed + 先 smoke,不能静默改活的序列。DRAFT,
等你 explicit-go 再实现。
