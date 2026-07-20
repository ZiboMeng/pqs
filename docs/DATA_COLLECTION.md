# Phase 3 数据采集契约

日期：2026-07-20
状态：本地 collect-only 实现完成；真实持续 provider 为 0，真实采集批次为 0

## 1. 能力与边界

本模块建立独立于旧 `data/daily`、`data/intraday` 和策略 reader 的原始采集边界。它只负责取得、校验、
留存和追踪 provider 批次，不向策略暴露读取接口，不触发参数修改或晋升。配置
`config/data_collection.yaml` 同时锁定：

- `mode: COLLECT_ONLY`；
- `strategy_consumption_enabled: false`；
- `live_enabled: false`；
- 当前只允许 `file` 和 `mock` adapter。

因此，日内和期权实现表示“采集基础设施可运行”，不表示已取得真实历史数据、已完成回测、或策略可晋升。

## 2. 统一 envelope

每个批次必须提供：`batch_id`、`feed`、`source`、固定 `data_schema`、batch 级
`event_time/available_time/received_time`、原始 `rows`、`provider_cursor/next_cursor`、quality flags 和可选
`revision_of`。三类时间均须带时区并归一到 UTC：

- `event_time`：市场事件实际发生时间；
- `available_time`：provider 声称调用方最早可取得该值的时间；
- `received_time`：PQS 实际收到该值的时间。

行内必须满足 `event <= available <= received`。批次 event 是所有通过结构解析行的最早 event；批次
available/received 分别是最大值。修订批次必须使用新的 batch ID、保留新的实际 available/received，并以
`revision_of` 指向先前可信批次；不能把后来修订伪装成历史时点已经可用。

## 3. 三种固定 schema

`daily_total_return_v1` 保存股票/ETF 的 session、OHLCV、adjusted close、total-return factor、dividend、
split factor、corporate action、XNYS calendar、三类时间、source 和 quality。校验包括字段全集、唯一
`symbol/session`、价格几何、正价格/调整因子/拆分因子、非负整数成交量和来源一致性。

`intraday_quote_bar_v1` 只接受 1m/5m，保存 bar start/end、OHLCV、bid/ask、PRE/REGULAR/POST、
latency、三类时间、source 和 quality。event 必须等于 bar end，latency 必须和 receive-event 一致；重复、
乱序、同 session 的缺 bar、crossed/负报价均隔离。它当前不被任何策略消费。

`options_chain_v1` 保存 chain/contract/OCC identity、underlying、quote time、expiration、strike、CALL/PUT、
bid/ask/last 和 size、volume/OI、IV、Greeks、multiplier、三类时间、source 和 quality。同一批次只能是一份
underlying/chain/time snapshot；过期合约、不可能报价、越界 delta、负 gamma/IV 或无效 multiplier 均隔离。

## 4. 追加、隔离与恢复

默认 operational root 是 `data/collection/`，不会进入 Git。完整原始记录只创建一次，权限为 `0400`，并
按最终状态落在：

```text
data/collection/
  trusted/{daily,intraday,options}/<sequence>_<record_sha256>.json
  quarantined/{daily,intraday,options}/<sequence>_<record_sha256>.json
```

所有分区共享严格递增 sequence 和 previous-record SHA-256。每次读/写前都会验证文件名、目录、原始 rows
content hash 和全局链；符号链接、未知文件、链断或原始内容变化会 fail closed。同一 batch ID 与完全相同
内容会幂等复用；同 ID 不同内容失败，不能覆盖。

语义校验失败也会追加保存，但进入 `quarantined`，error 只含稳定代码、不回显原始值。只有 `trusted` 批次
能推进 `next_cursor`。重启后 `resume_cursor(feed, source)` 从最后可信批次恢复，所以隔离批次不会令采集器
跳过待修复范围。revision 父批次不存在、不是可信状态或 feed/source/schema 不一致时，子批次同样隔离。

这是单主机 `flock + fsync + hard-link create` 边界；它不能抵抗同 UID 恶意进程或 root。远端 object lock、
多主机 consensus 和商业 provider SLA 未实现，也未声称实现。

## 5. Provider 与调度接入

`CollectionProvider` 是注入协议：provider 必须返回与请求 feed/source/cursor 一致、且 received time 不晚于
`requested_at` 的 envelope。`FileCollectionProvider` 拒绝 path escape、任意层级 symlink、重复 JSON key、
读取竞争和超大输入；`MockCollectionProvider` 按 feed/cursor 确定性返回一批。

`config/data_collection.yaml` 提供 America/New_York 的建议 cron。CLI 是可由 cron/systemd/Kubernetes 调用的
幂等 one-shot job；调度器应在每次调用时省略 `--cursor`，让它从最后可信记录恢复。PQS 当前没有真实
provider credential，因而没有启动持续 job；R7 只会准备部署模板，不会声称已经部署。

查看空的正式 store：

```bash
.venv/bin/python scripts/collect_phase3_data.py status
```

用隔离临时 store 运行三类合成 fixture（每个命令使用不同临时 store 或按返回 cursor 继续）：

```bash
.venv/bin/python scripts/collect_phase3_data.py ingest-file \
  --feed daily --source synthetic_fixture \
  --provider-root examples/data_collection --input daily.json \
  --store-root /tmp/pqs-collection-smoke

.venv/bin/python scripts/collect_phase3_data.py ingest-mock \
  --feed options --source synthetic_fixture \
  --input examples/data_collection/options.json \
  --store-root /tmp/pqs-options-smoke
```

示例 rows 带 `SYNTHETIC` quality flag，绝不能作为市场证据。日频、日内和期权完整示例分别位于
`examples/data_collection/`。

## 6. 已验证反例与诚实状态

专项测试覆盖三类 mock E2E、file E2E、坏 OHLC、intraday missing bar、坏 Greeks、revision 血缘、未知父、
隔离不推进 cursor、重复幂等、同 ID 冲突、provider source/cursor/time 错误、path escape、symlink、重复 key
和链篡改。当前结论只限于代码和本地 fixture：

- 真实日频持续采集：未配置；
- 真实 1m/5m 持续采集：未配置；
- 真实 point-in-time options chain：未配置；
- 正式 `data/collection` 真实批次：0；
- 日内/期权策略晋升：禁止。
