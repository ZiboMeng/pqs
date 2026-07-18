# 回测与 PAPER 认证

认证日期：2026-07-17（America/Los_Angeles）

代码基线：`81c6ea0` 加本认证修复集（最终提交号见 `CODEX_PROGRESS.md`）

结论：**核心日线回测/PAPER 会计与时间语义通过本轮认证；现有策略均未通过晋升。**

## 1. 认证边界

本文件认证的是执行引擎、价格口径、账户守恒、成本接入、窗口输入和 PAPER 恢复语义。
它不证明任何策略有 alpha，也不把历史 replay 伪装成真实 forward track record。LIVE 仍禁用，
options 仍因缺真实 point-in-time chain 而不具备晋升证据。

## 2. 冻结的价格与时间契约

1. 原始 parquet 是存储层；所有研究、回测和日线 PAPER 价格消费都必须经
   `BarStore(adjusted=True, adjusted_total_return=True, fallback="local")`。
2. split 和 distribution 调整同时作用于 OHLC，保证 T close 信号与 T+1 open 成交在同一
   synthetic total-return basis；volume 只按 split 调整，分红不改 volume。
3. 每个 symbol 必须在 `distribution_coverage.parquet` 有 `OK` 查询记录且覆盖到实验终点；
   零分红只有在显式查询成功后才合法。coverage 和 distribution 的 split hash 必须与
   `splits.parquet` 一致，否则 fail closed。
4. 信号只使用 T 及以前的信息；订单在 panel 的真实下一根可成交 bar 的 open 成交。
   `Fill.fill_date` 取该 bar 的时间戳，不从日历猜测。缺 open 就不下单，不用 close 替代。
5. SELL 数量由实际持股与目标股数之差产生并以实际持股封顶。任何价格跳空都不得产生
   负持仓或凭空现金。
6. 卖单先于买单；滑点进入成交价，佣金进入 cash delta。PAPER pre-trade 对成本做现金预留。
7. 当前现金利息假设为明确的 0%，不是遗漏字段；所有策略与 benchmark 使用相同假设。
   将来启用非零现金收益必须作为新数据/模型版本重跑全部证据。

## 3. 公司行动与数据证据

2026-07-17 对 executable universe 81 个 ticker 全量查询成功：

- `splits.parquet`: SHA-256
  `624165282c1142b43f1445b2ac737f6c8f509b66a57126af8277b371e14c1b1b`；
- `distributions.parquet`: 3,802 rows，SHA-256
  `73001d19c8befda06f3fc127f982b2eb42b6ef4fd498c9392b70e9b83cdff8a3`；
- `distribution_coverage.parquet`: 81 `OK` rows，覆盖到 2026-07-17，SHA-256
  `9b0bb1aa368820c3b6697bed9fde73c6c48208b006bc98019b251766f8873b33`；
- SPY 最后事件 2026-06-18，QQQ 2026-06-22，TLT/IEF/SHY/BIL/SHV 2026-07-01；
- GLD、AMZN、TSLA、BRK-B、CMG、ISRG、SLV 为成功查询后的零分红，不是缺失值；
- corrected close/open panel: 4,915 × 81，2007-01-03 至 2026-07-17，索引和列完全对齐；
- mixed-source boundary sidecar SHA-256：
  `9a679f496d985f88018519fd43da8f6dcd3723c676da27a4c11ccb62456ae453`。

数据 sidecar 因仓库数据政策不进 Git；上述 hash、builder、coverage schema 和运行 manifest
共同构成复算证据。供应商后续修订导致 hash 变化时，旧结果自动成为 data-revision 前版本，
不能混入同一 track record。

## 4. 负面对照与不变量

| 场景 | 旧行为 | 认证行为 |
|---|---|---|
| NVDA/TQQQ split | raw 路径出现 4×/40×/47× 级跳变 | canonical loader 消除虚假 split return |
| 100 -> 50 跳空清仓 | 可卖约 2× 持股并把 NAV 留在约 10k | 卖出不超过持股，NAV 正确降到约 5k |
| 100 -> 200 跳空清仓 | 可能只卖一半并残留仓位 | 精确按实际持股清仓 |
| panel 缺一个 NYSE session | 价格来自后一个 bar，日期却标在前一个 session | fill date 等于真实执行 bar |
| Good Friday/周末 | `BDay` 可能把 signal/fill 标错 | 使用 NYSE calendar 或显式 source bar |
| walk-forward | full run 用 open，fold 未传 open 而用 close proxy | 每 fold 接收相同 open slice |
| 两张各 50% BUY | 每张都看 100% cash，可合计穿透 min cash | 第二张看到第一张后的虚拟现金并被 veto |
| FILLED 后写账户时崩溃 | 可能留下 FILLED + 旧 cash/positions/checkpoint | 同一事务全回滚为 VALIDATED，可幂等重试 |

## 5. 测试证据

- 第二阶段认证集：653 passed，1 xfailed，0 failed，123.42 秒；覆盖 backtest、execution、
  PAPER、order/risk、BarStore、price basis、regime、temporal split 和 integration parity。
- 原子恢复 failure injection：intraday 与 daily 两个崩溃点均验证 rollback；重试后只有一个
  canonical order、一个 fill、一个 checkpoint/account snapshot。
- focused static：Fatal Ruff/F821 通过；配置 schema 验证通过。
- backtest/PAPER gap-open equity parity 保持在既定 1 bps/日、5 bps 累计容差内。
- 现有一个 xfail 是既有 integration 预期失败项，不是本修复新增失败。

## 6. 修复后全期诊断基准

命令：

```text
python scripts/run_backtest.py --no-walk-forward --no-cross-ticker-rules \
  --output-dir research/results/certification_baseline
```

区间为 2007-01-03 至 2026-07-17，81 symbols，含当前成本，SPY 为硬基准、QQQ 仅诊断：

| 策略 | CAGR | Sharpe | MaxDD | IR | 交易数 | 晋升 |
|---|---:|---:|---:|---:|---:|---|
| dual momentum | 5.7% | 0.22 | -22.0% | -0.33 | 913 | 否 |
| trend following | -1.5% | -1.18 | -30.2% | -0.71 | 7,084 | 否 |
| cross-asset rotation | 4.2% | 0.05 | -11.1% | -0.43 | 781 | 否 |
| multi-factor | 8.0% | 0.47 | -15.0% | -0.23 | 2,999 | 否 |
| SPY total-return benchmark | 10.9% | 0.42 | -55.2% | — | — | benchmark |

该 run 是 corrected diagnostic baseline，不是 OOS。四个策略 IR 全为负，trend following 还突破
25% halt drawdown；因此全部保持未晋升。artifact 位于
`research/results/certification_baseline/backtest/runs/20260717_173221_backtest/`。

## 7. Walk-forward/OOS 资格

`WindowAnalyzer.walk_forward` 现在保证窗口和 open 输入一致，但它仍只负责时间切片，不能从
一个预计算 signal matrix 证明 fold-local fitting。固定、事先登记且不拟合的规则可直接做
walk-forward；任何训练、阈值选择、特征选择或 universe 选择必须在每个 train fold 内完成，
并把 train/validation/holdout 访问写进 manifest。旧 2026 sealed 已消费，禁止称为 pristine。

## 8. PAPER 认证

- 风控按 execution 顺序维护虚拟 positions/cash/turnover，并接入配置化 daily loss/turnover；
- session turnover 写入 SQLite，重启恢复；
- local simulator 的 VALIDATED -> SUBMITTED -> ACKNOWLEDGED -> FILLED、intraday orders/fills、
  `pt_state` 和 bar checkpoint 在同一 `BEGIN IMMEDIATE` 事务；
- 事务失败后的 VALIDATED 本地订单可以同幂等键重试；SUBMITTED/UNKNOWN 的外部 broker 风险
  仍 fail closed，不能把本地安全重试外推到真实 broker；
- LIVE 依然需要真实 broker-authoritative reconciliation 和显式授权，本认证不改变该闸门。

## 9. 已知限制

1. executable stock universe 不是 point-in-time 成分股集合，仍有 survivorship/selection bias；
2. corporate-action 数据来自 yfinance 免费源，不等价于商业级主数据；
3. mixed canonical/yfinance frontier 已记录但仍可能有 vendor revision；
4. total-return OHLC 是分红再投资代理，不是逐账户税务/withholding/cash-dividend 模拟；
5. cash interest 固定为 0%，借券、融资和 short 不存在（long-only/no-margin）；
6. 本认证不触碰已消费的 sealed 数据，也不证明任何候选具备 forward 稳定性。

上述限制会降低结论强度，但不允许通过放宽门槛来补偿。若最终找不到两个合格策略，正确结论
是“不晋升”，不是把诊断基准升级为 PAPER。
