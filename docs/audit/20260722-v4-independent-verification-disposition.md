# v4 独立验证报告处置

日期：2026-07-22

## 结论

独立报告对 ledger/hash、30 轮计数、10 份 Qualification V2 数值复算和 0 formal 的验证予以接受。
以下意见纳入整改：legacy V2 回撤门不足、REVIEW_HOLD 缺少 development/OOS/回撤 caveat、候选级
replay 证据需要加强、外部审计未独立跑完全量测试。

以下表述不采纳为事实：

1. DSR 0.387/0.294 不是“真实主动 Sharpe 大于零的概率”；它是相对多重试验调整后 `sr0` 的 PSR statistic。
2. beta>1 是重要混淆，但现有分解不足以证明“不是 alpha、只是 beta”。
3. 十候选的 excess、beta、MaxDD 不构成单调关系；一批 30 轮结果不能证明 mandate 普遍不可行。
4. deterministic replay 并非完全未执行；旧 runner 会重复生成 targets 并在不一致时抛错，但该证明仍偏弱。

## 独立复核新增的遗漏

预注册冻结 `common_qualification_start=2020-01-01`，最终 corrective replay 却使用
`development_start=2015-01-01`。2015 窗口在研究语义上更合理，但仍属于结果出现后的评估窗口变化。
因此最终报告可复算但不是严格 preregistration-conformant；它不能支撑 near-promotion 叙事。原 2020
预注册运行和 2015 corrected analysis 都是 0 formal，所以不晋升结论不受影响。

旧 runner 还把 YAML 中的 0.60/1.25 门槛重复硬编码。Qualification V3 通过绑定 evaluation contract
和 governance 消除这类配置漂移，不会回写旧 ledger 或旧 Qualification V2。

## 最终处置

- 0 formal 不变；
- 两个候选降为 `REVIEW_HOLD_EXPLORATORY_NOT_FORMAL`，不可 PAPER、不可自动晋升；
- 新 MaxDD 硬门按用户决定改为每个对齐年度、每个成本情景严格优于 SPY；无绝对硬阈值；
- absolute/stress MaxDD 继续强制报告；
- 新自动晋升只接受 Qualification V3。

## 本轮治理实现验证

- 全量回归：`4,418 passed / 37 skipped / 21 failed`（共 4,476 项）。其中
  16 项失败来自隔离 worktree 未携带 Git-ignored 的 `data/daily`/`data/ref`；
  接入主项目同一份只读数据后，对应 32 项价格语义、forward 与 PAPER 集成测试
  全部通过。
- 剩余 5 项是预期的 fail-closed 基线：3 项检测到旧 sealed/runtime artifact
  与 `core/data/price_access.py` 指纹漂移，2 项因缺少经权威来源整理的
  `config/macro_event_calendar.yaml` 而拒绝 precise event-factor 研究。
- 没有为消除这 5 项失败而重签旧 artifact，也没有复制示例或启发式宏观日期冒充
  精确历史日历；临时只读数据链接在验证后移除，且未用于生成策略结论。
