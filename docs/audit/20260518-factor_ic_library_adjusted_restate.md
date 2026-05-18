# P0-A F3 —— 因子库 IC raw→adjusted 诚实重述

**日期**: 2026-05-18(隔夜自主执行)
**lineage**: `p0a-loader-barstore-fix-2026-05-18`(F3 交付物)
**脚本**: `dev/scripts/audit/f3_factor_ic_library_adjusted_restate.py`
**数据**: `data/audit/f3_factor_ic_library_restate.json`
**纪律**: train-only(sealed 红线严守)、不走过场(真跑真比对真根因)、
`feedback_no_blanket_failure_verdict`、不夸大 scope。

---

## §1 范围(诚实,不谎称"全 143")

`generate_all_factors` 实产 **97 个 OHLCV 族因子,86 个有定义 IC**
(11 个 constant/degenerate → IC undefined,诚实排除,非 error;
0 failed)。**这不是全 143**:fundamental/sector/macro 族(K/L/M/N/O/P)
来自独立 compute path(EDGAR/sector_map/FRED),**不经价格 loader →
不在 P0-A scope**。P0-A 的 split 价格污染**正命中价格窗口类 = 这
86 个**,所以本 restate 覆盖的恰是 P0-A 真正能影响的子集。

train-only(2009-2024 train years,`sealed_2026_read=False`,
SEALED-GUARD fail-closed 未触发),81 syms。

## §2 结果(真跑)

| 指标 | 值 |
|---|---|
| (factor,h) 对(raw∩adj) | 86 |
| **Spearman(raw_ir, adj_ir)** | **0.9992** |
| top-20 \|IR\| 重叠 | 0.95(19/20) |
| 符号翻转 | **0** |
| material 翻转(\|IR\|>0.3) | **0** |
| 最大 \|adj_ir\|−\|raw_ir\| | ~0.023(golden_cross_score 0.232→0.255) |

## §3 诚实结论(de-escalation,非 blanket)

因子库 OHLCV 族 IC/IR **原则上 P0-A in-scope(raw 价算的,scope 续追
时正确点名),但实证 raw vs adjusted 差异可忽略**:Spearman 0.9992、
零符号翻转、最大 IR 差 0.023。**因子库 IC 数字在 adjusted 下不发生
实质改变**。

机制与 §1.A.q backstop 量化一致:库内多数因子是 cross-sectional /
归一化 / 长窗口,split 假跳被摊薄;raw 的污染主要伤短窗口绝对收益
(ret_1d/ret_5d——§1.A.q 已点名),而这些在因子库里 IC_IR 本就近零、
不进 top。

**这把"因子库 IC raw-suspect"从"数值需推翻"降为"in-scope 但实证
immaterial"**——与 cycle-mining 主轴结论同型(in-scope、已 root-cause、
但主力数稳)。**不是"因子库全错",也不是"没问题":是 in-scope、
已实证 immaterial、honest scope = 86 OHLCV 因子非全 143。**

## §4 不变 / 仍须

- F1 修复仍必要(根治 loader 绕过 + 短窗口因子可信 + 防未来污染);
  本 restate 只是说"已跑出来的因子库 IC 数实证没被显著污染"。
- fundamental/sector/macro 族不在此 scope(非价格 path)——若日后
  质疑其价基,另立项,**本 restate 不替它背书**(诚实边界)。
- F5 standing 重述会引本结论:因子库 caveat = in-scope/immaterial。
