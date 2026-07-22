# 30 轮多样化策略挖掘执行前独立审计

日期：2026-07-21

结论：在以下边界内可执行 `diverse-mining-20260721-v1`；它是 development campaign，不是重开 holdout，
formal 的含义仅为通过 canonical qualification 后冻结、等待同一未来 session 的 PAPER 候选。

## 1. 数据审计

本轮唯一价格源为 exact-cash v6：

- snapshot：`yahoo_exact_cash_ledger_2007_2024_v6`；
- manifest SHA-256：`c8382dfbddfe2522c37558bb2f3c573fefedb3893c803d80abe1db9b93e80c46`；
- 301 个输出文件，296 个 eligible symbols（295 公司 + SPY），5 个同日 split/distribution 歧义标的排除；
- 历史截止固定 `2024-12-31`，不会读取已消耗的 2024–2026 sealed/holdout 结果作为新 OOS；
- OHLC 为 split-adjusted execution price，现金分派通过独立 ledger 进入持仓账户，总回报不再用 synthetic OHLC
  近似或双算现金。

公司池文件 SHA-256 为
`9ed1e370c8bb7d2827c65085d7117757a7058c7d046319c1d02c2d9301a2cef8`。它是 2026 current-company
snapshot，历史回测有 survivorship bias；所有输出必须保留 `DEVELOPMENT_ONLY`、
`historical_oos_claim_allowed=false` 和 `PROSPECTIVE_CURRENT_COMPANY_POOL_USED_FOR_DEVELOPMENT`。

复用的 numeric OOF prediction SHA-256 为
`ee10574f14510954242ded85e2720e4827343664ab6a05e20bb971d72093a313`；semantic OOF prediction
SHA-256 为 `03d4f4eb67951780a8a4ccdc4a9e9c8440e47721c5f723eb8165767c3f68e1a7`。它们是已观察的
development artifact，只能让 ML/semantic 参与横向诊断；未完成候选特定 feature/model prefix replay 时不能
成为 formal candidate。

## 2. Holdout 与反馈隔离

- `research_boundary.observed_through=2026-07-17` 不变；
- campaign 的历史价格实际止于 2024-12-31；
- 不读取 `research/results/phase2/holdout` 或旧 sealed summary 来选本轮参数；
- 30 个 round 在运行前一次性写入 preregistration；结果不触发第 31 个兄弟参数；
- 达到 5 个 canonical formal candidates 可以停止，否则跑满 30；失败、blocked、synthetic short 全计 raw N；
- forward/PAPER 结果不得反馈本 campaign。

## 3. Trial accounting 与统计语义

权威台账为本 campaign 独立 append-only hash-chain ledger：每个 round 先 intent/fsync，再 started，最后只能
append outcome/failed 和 artifact binding。重命名相同内容不增加独立 N；失败的 LLM feasibility 与缺 PIT
borrow 的 short 尝试不会消失。

Qualification V2 重新审计后作了一项关键修正：

- candidate absolute Sharpe 只作诊断；
- binding DSR、PBO、MinBTL、CPCV 和 effective-N 全部基于 after-cost
  `candidate − SPY` active returns；
- 否则高 beta SPY clone 会因市场绝对收益而错误通过“策略发现”统计门。

PBO performance matrix 只包含有实际、同日期净收益的成功 round，但 DSR/MinBTL 的 raw N 来自完整 ledger，
包括失败、RESEARCH_INCOMPLETE 和被阻断的第 30 轮。PBO 与 CPCV 分开记录 `S/n_combinations` 和
`n_groups/k_test/n_splits/n_paths`。

## 4. 机制多样性与自由度

30 轮包括：

- 多期限/12-1/residual/volume-confirmed/liquidity-adjusted momentum；
- low-vol、downside-vol、defensive momentum、5 日 reversal；
- active、SPY35 hybrid、buffer-15、dual-momentum 和 volatility overlay；
- 已冻结 OOF rule、linear、shallow XGB 和 rule+linear ensemble；
- structured + lexical SEC event overlay；
- 两个 sector/beta-neutral 之前的 market-neutral short diagnostic；
- 一个 schema-constrained LLM feasibility round。

这里的“多样”不是 30 个隐藏超参。每个 rule 的权重、模型 artifact、construction 和成本压力已固定。active 与
hybrid 是同一 family 的 sibling，最终每 family 最多冻结一个；候选收益相关性绝对值 `>=0.70` 时只保留
active excess 更强且先排序者。

## 5. Short 与 LLM 可行性判断

Short：历史 exact-cash 数据没有 PIT borrow availability/quantity/fee/recall/NBBO。两轮 short 仍可用固定 3%
borrow assumption 做 market-neutral 机制诊断，但输出必须为 `RESEARCH_INCOMPLETE`，不进入 qualification matrix
或 5 个 formal candidate 计数。真正 PAPER 从未来 broker source batch 开始，契约见
`docs/prd/20260721-short-paper-research-lane-prd.md`。

LLM：当前没有与本 campaign 预先冻结的 provider/model/prompt/schema response corpus。临时联网生成会引入未登记
模型版本、不可复现响应和额外自由度。因此第 30 轮按预注册 blocker fail/count，不用词袋结果冒充 LLM，也不让
LLM 直接生成权重。

## 6. 算力与执行可行性

执行前主机状态：24 GiB RAM 中约 17 GiB available、约 12 GiB swap、项目盘约 791 GiB free；GTX 1650 Ti
4 GiB 可用但本轮不依赖 GPU。exact-cash snapshot 仅约 55 MiB，301 files。主要开销是 29 个实际 round 的
30/60/90 bps BacktestEngine replay，内存和磁盘均足够；模型不重新训练，避免把算力转成额外搜索自由度。

## 7. 出口

执行后必须同时满足：

- ledger raw independent N 等于实际 round 数且无 incomplete；
- 每个成功 round 有 immutable result hash；
- qualification 从 raw returns + ledger head 独立复算；
- formal candidate 有单独 freeze manifest，但 `source_batch_bridge_ready=false` 时 PAPER readiness 仍 NOT_READY；
- 无论 formal count 是 0、1–4 或 5，都发布全 30/提前停止事实，不放宽 gate 或追加兄弟搜索。
