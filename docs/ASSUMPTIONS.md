# 假设

- 当前真实业务模式为 PAPER；任何名为 `live` 的旧 CLI 都只表示 paper 的当日 bar
  执行，不表示真实 Broker。
- 继续遵守 long-only、no-margin、no-short；不自动启用裸期权或 0DTE。
- SPY 是 stable-core/rotation 的 primary benchmark；growth-engine 使用 QQQ 作为冻结的
  相对 Calmar、beta 和风险增量 hard-gate benchmark。
- 本地开发可使用 SQLite；接口必须允许未来替换 PostgreSQL。
- 无 Broker/商业 options 数据时继续实现标准接口、fixtures、Mock/PaperBroker，不阻塞
  其他工程工作。
- 金额内部逐步迁移到 Decimal/明确货币精度；研究向量计算保留 float，但执行和记账
  边界必须做有限值、舍入和容差校验。
- 历史现存 options synthetic artifacts 在会计修复后视为需要重算，不能静默沿用。
- 配置中的风险数值仅是 paper 默认值；live example 不提供可直接启用的最终参数。
- 当前 workspace 大数据属于用户资产，不移动、不删除、不提交。
- 2024-01-02 至 2026-07-17 的 phase-two holdout 已被三个 finalist 合法访问；它不能通过
  改名、换参数或换目录重新成为未见数据。
