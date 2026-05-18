# PQS 大清盘 Audit —— 2026-05-18

**Lineage**: `grand-stocktaking-audit-2026-05-18`
**Scope**: 全项目代码级 bug(真跑)+ 逻辑 + 跨模块配合 + 文献 SOTA-vs-naive
**Method**: 4 维(A1 真跑 / A2 operator 逻辑驱动 / A3 集成 / A4 SOTA),
3 并行 agent + operator 亲自 R3 验证最高 stakes 项 + 全量 pytest 真跑。
**纪律**: `feedback_audit_surfaces_not_thorough`、`feedback_no_blanket_
failure_verdict`、`feedback_self_audit_methodology`(R3 不可跳)、
`feedback_websearch_sealed_data_discipline`(A4 只查方法不查市场)。

---

## §0 一句话(大白话)

测试面干净(3367 passed/0 failed)、没有会崩的生产 bug。**但挖出 1 个
真 P0 root-cause + 1 个并列 P0 级文献 gap**,两者合起来解释了"为什么
mining 数值一直不可靠、被逐候选打补丁":
- **P0-A(数据)**:Track-C 生产挖矿 loader(`run_research_miner.py`)
  + paper loader 用 `MarketDataStore.read()` 读 **raw 未复权价**,
  **绕过文档强制的 `BarStore.load(adjusted=True)` split cascade**。
- **P0-B(验证)**:DSR/PBO/CPCV/MinBTL 这套 SOTA 过拟合防御**没接进
  生产 Track-A 验收 gate**(只在 ML-redo dev 脚本用);binding gate
  仍是 naive 按日历年 contiguous fold + 未做自相关修正的 t-test。
诚实定性:CLAUDE.md **已有** standing caveat(cycle02 ARCHIVED、
cycle04-10 numerics DEPRECATED)——所以这不是"没人知道的灾难",而是
**症状被打补丁、root cause 从未被命名根治**。这正是本 audit 的价值。

---

## §1 P0 findings(必须处理)

### P0-A 挖矿/paper loader 绕过 split cascade(operator 亲自 R3 实证)

**契约**:CLAUDE.md Pricing Semantics —— "Splits applied at **read
time** via `BarStore.load(..., adjusted=True)` using
`data/ref/splits.parquet` cascade";`data/daily/*.parquet` 按设计是
raw。

**违反点(file:line)**:
- `scripts/run_research_miner.py:33,103,692`(Track-C 真路径,产出
  cycle04-12 / RCMv1 / Cand-2 / trial9 的入口)→ `MarketDataStore`
  + `store.read(sym,"1d")`。
- `core/data/market_data_store.py:149-174` `read()` = 只读 parquet +
  日期过滤,**零 split 调整,不 delegate BarStore**(实读源码确认)。
- `scripts/run_research_miner.py:65-128` `_load_price_volume` → 直接
  `df["close"]`,**全程无补调整**(实读确认)。
- `scripts/run_paper.py:332,392` `create_default_store` → MarketDataStore
  → `store.read`;`scripts/run_mining.py:53,57`(legacy 路径)同。

**实测发散(operator 真跑)**:2015-01-02 close —— NVDA
MarketDataStore.read=**20.125** vs BarStore.load(adjusted)=**0.503**
(~40×);AAPL **109.3** vs **27.325**(~4×)。data/daily 确为 raw。

**影响(精确 scope,不夸大)**:
- 因子/IC/NAV 在 raw 价上算 → 任何 lookback 跨 split 日的窗口被污染
  (4:1 split = 单日 −75% 假收益)。**直接解释** CLAUDE.md 已记的
  cycle02 ARCHIVED(LRCX $72/$7 alternating)、cycle04-10 "numerical
  claims DEPRECATED"、"heterogeneous split-adjustment fix"——这些是
  **同一 root cause 的症状**,之前被逐个打补丁未根治。
- **不影响**:在跑的 forward 观察**估值**(cycle06/08/pead)——
  A3 实证 `attention_report.py:456-459` 用 `BarStore.load(adjusted=
  True, adjusted_total_return=True)`,估值价基正确。但这些候选当初
  是被 raw 价挖矿**选出来**的 → 选择可疑、观察估值无误(内部不一致,
  honest scope)。
- **不是 blanket "全坏"**:测试面绿、forward 估值对、qualitative
  findings(sibling geometry / TC ceiling)是理论/构造性的不依赖此
  数值,CLAUDE.md 已 preserve。

**Root cause**:挖矿/ paper 数据 loader 选了 `MarketDataStore`(raw
parquet 直读)而非 `BarStore`(split cascade)。**从未被命名为"loader
绕过 cascade",只在候选层打补丁**。

**修复方向(不在本 audit 落,P0 fix item)**:`_load_price_volume` /
run_paper / run_mining 改走 `BarStore(root=...).load(sym,"1d",
adjusted=True)`;加 split-aware 价基回归测试(price semantics
regression test —— CLAUDE.md 早有此要求但未覆盖 loader 层);重跑评估
受影响候选 / 诚实标注哪些 standing 数值是此 root cause 而非已 caveat。

### P0-B SOTA 过拟合防御未接进生产 gate(A4 + grep 实证)

`overfit_metrics.py`(DSR/PBO/MinBTL/ONC)+ `cpcv.py`(purged+embargo
CPCV)+ G1-G5 新模块 = **kernel 层 SOTA、忠实 Bailey/LdP**;但 grep
实证 **`temporal_split_acceptance.py` / `run_research_miner.py` 零
call site**——binding 晋升 gate 仍是 per-calendar-year contiguous
fold + `ttest_1samp` 未做 Newey-West/HAC 自相关修正(`factor_engine.py:
158`)+ 无跨 12+ cycle 的 FWER/FDR ledger。**非 invariant-justified,
是未接线**(项目自己的 "no dead wiring before consumer" + new-cycle-only
纪律导致;G1-G5 PRD 已诚实记 "available-not-wired")。与 P0-A 合起来 =
生产挖矿链"输入价基错 + 选择偏差不 deflate"双 root。

---

## §2 P1 / P2 findings

| # | sev | 项 | file:line | 来源 |
|---|---|---|---|---|
| P1-1 | P1 | 验收 fold 是 contiguous 年、无 purge/embargo;21d label 跨年泄漏(M4 部分缓解但 fold 本身非 CPCV) | `temporal_split_acceptance.py` | A4 |
| P1-2 | P1 | 因子 IC t-stat 未 HAC/Newey-West 修正 → 显著性高估,喂 Tier gate | `core/factors/factor_engine.py:158` | A4 |
| P1-3 | P1 | 组合构建用对角协方差近似(忽略相关性),cross-asset diversifier track 恰恰看不见它要利用的 equity-bond 相关 | `core/portfolio/constructor.py:204-206` | A4 |
| P2-1 | P2 | paper engine 缺 bar 时把持仓标 $0(write-off)vs BacktestEngine 标 last_valid_close(M14 spec)——生产 caller 已 shield,但 paper-vs-BT 估值语义分歧未测 | `core/paper_trading/paper_trading_engine.py:226,271` | A1 |
| P2-2 | P2 | `dev/scripts/cycle09/cycle09b_pit_audit_rd_intensity.py:36` 缺 sys.path bootstrap → 标准调用 ModuleNotFoundError | 同 | A1 |
| P2-3 | P2 | `dev/scripts/chart_structure/phase4_ingest_expanded.py:66` 模块级读 /tmp 文件 → `--help`/裸跑 FileNotFoundError | 同 | A1 |
| P2-4 | P2 | `cap_aware_risk_parity` 实为 1/vol 非真 risk parity;Ledoit-Wolf shrinkage CPU-trivial 未用 | `core/research/risk_parity_weighting.py` | A4 |

**A1 显式"没发现"**(诚实留痕):core 无 bare `except:`、无 mutable
default、无 `==None`、无 pricing/sizing div-by-zero;M14 BacktestEngine
修复未回归(5+4 测绿)。**A3 OK 项**:factor_registry production/
research boundary、temporal_split v1/v2/v3 dispatch、provenance/
evaluation_policy/executable_universe 三层、G1-G5 模块 wiring 纪律 ——
均实证 OK 无 dangling。

---

## §3 文献 SOTA-vs-naive 对照表(A4,methodology-only,未触市场数据)

| 区域 | 项目实现 | 文献 SOTA | verdict | invariant-justified? |
|---|---|---|---|---|
| 回测成本/冲击 | 固定 bps + VIX×2.5 binary | Almgren-Chriss √-impact | NAIVE | **是**(scale-gated;$10K-100K 参与率≈0,但 `capacity_model` 是 dead config 隐患) |
| 因子挖矿/选择 | TPE + full-panel IC_IR;naive 年-fold gate | CPCV+embargo / DSR-deflation / Harvey-Liu-Zhu t>3 / ONC | **NAIVE-GAP** | **否,未接线**(P0-B) |
| 组合/仓位 | 1/vol + 对角协方差 | Ledoit-Wolf / HRP | NAIVE | 部分(cross-asset track **不** justified) |
| Regime | rule-based VIX 阈值 | HMM / Bayesian CP | ADEQUATE | **是**(仅 defensive cap,HMM 加 overfit DOF;低优先) |
| ML 表征 | in-domain MAE d=64 | TS2Vec/PatchTST/foundation | ADEQUATE(方法对,仅 scale) | 已被 scaled-checkpoint PRD owned,不重导 |
| 验证/过拟合 | kernel SOTA 但 gate 不用 | Bailey/LdP 全栈 | **SOTA kernel + NAIVE wiring** | 否(P0-B) |
| 信号组合 | 固定线性权重 | stacking(项目自有 `stacking.py` 未接生产) | NAIVE-GAP | 部分(roadmap gap,非 invariant) |

**A4 选出 5 个 invariant 不阻塞的最高杠杆升级**:①DSR+PBO 接进生产
gate ②年-fold→purged CPCV ③Ledoit-Wolf shrinkage(尤其 cross-asset)
④因子 IC t-stat 加 HAC ⑤`stacking.py` 接进 alpha 组合(opt-in)。

---

## §4 优先级 / 下一步(operator 建议,directional 待用户)

- **P0-A(数据价基)= 最高优先**:loader 改走 BarStore adjusted +
  价基回归测试 + 受影响 standing 数值诚实重标。这是 root-cause 级,
  修了消除一类反复打补丁。
- **P0-B / P1-1 / P1-2**:与刚做完的 backtest-robustness PRD G1-G5
  **天然衔接**——G1-G5 已建好 kernel,P0-B 就是"把它们接进生产
  gate"(G4 PRD 写的 new-cycle-only 正是这个);可并成"G6 生产
  acceptance 接线 + HAC + purged-fold" 一个 PRD round。
- **P1-3 / P2-4**:Ledoit-Wolf shrinkage(~20 行,CPU-trivial,
  invariant 中性),cross-asset diversifier track 收益最大。
- **P2-1/2/3**:低风险小修(paper 估值语义对齐 M14 spec、2 个 dev
  脚本 sys.path/argparse)。
- **operator overclaim 自查**:本 audit 未发现新的我方 overclaim;
  P0-A 不是我引入(早于本会话),但**之前我没主动审到 loader 层**
  是 audit 覆盖盲点,诚实记录。

**不下 blanket verdict**:项目骨架/测试/forward 估值/G1-G5 kernel 是
扎实的;P0 是"生产链两处 root cause 没根治",不是"全坏"。qualitative
findings + 理论结论不受影响。

---

## §5 大白话总结

整个项目体检:**代码没有会崩的 bug,3367 个测试全过**。但挖出两个
要命的根子问题,而且它俩合起来解释了"为什么挖矿数字总不靠谱、一直
在打补丁":
1. **数据价基错**:真正在用的挖矿入口读的是**没除权的原始价**
   (英伟达 2015 年价能差 40 倍),而规矩明明要求用除权价。之前
   cycle02 作废、cycle04-10 数字弃用,都是这个根子的症状,被一个个
   单独打补丁,但**没人指出"挖矿数据加载器整个绕过了除权这一步"**。
2. **防过拟合的高级武器没装上枪**:DSR/PBO/CPCV 这套学术界最强的
   "防自欺"工具,代码写好了、测试过了,但**真正决定候选能不能晋升
   的那道关卡根本没调用它们**,还在用最朴素的"按年切+没修正的
   t 检验"。
好消息:第 2 点正好接得上我们刚做完的 G1-G5(武器已造好,差"接进
生产关卡"这一步);第 1 点是明确的修复方向(加载器改走带除权的
BarStore + 加价基回归测试)。其余是 7 个中小问题(组合用了忽略
相关性的简化协方差、因子显著性没做自相关修正、2 个 dev 脚本路径
小毛病等)。**没有"全盘崩了"——骨架、测试、在跑的 forward 估值、
新做的 G1-G5 kernel 都是扎实的**;问题集中在"生产挖矿链的两处
根子没根治",而且修复路径清楚。
