# Drawdown Gate 外部审计意见独立处置

日期：2026-07-22

状态：`FINAL_DISPOSITION / PRD_REVISED / GOVERNANCE_NOT_CHANGED`

关联文件：

- `docs/audit/20260722-drawdown-gate-authoritative-web-research.md`
- `docs/prd/20260722-annual-spy-relative-dd-strategy-mining-v5-prd.md`（v1.1）
- `config/research_governance.yaml`（当前 schema v2）

## 1. 总结

外部审计意见的核心经济反例成立：相对 SPY 回撤更小，不等于个人账户的绝对亏损一定可接受；因此不能
用 Balanced relative gate 代替账户层 risk budget。

但其流程指控不成立。当前 `CLAUDE.md` 和 governance config 并不是“未经批准地关闭绝对门”：commit
`1e9cf3ccd010e1fb41f48b60eb5e1930f28685aa` 已依据 2026-07-22 用户显式决定，将原 20%/25% promotion
caps prospectively 替换为逐年 SPY-relative gate。当前文件的 System Identity、Invariant Constraints 和
Drawdown comparison policy 三处均明确写了 absolute/stress-slice MaxDD 只报告、不作晋升硬 cap；config
中的两个 `false` 与当时决定一致。

正确处置不是简单选择审计员的 A 或拒绝其意见，而是：

1. 废除 annual-all-years strict dominance，采用 Qualification V4 Balanced Drawdown；
2. 不把旧 absolute cap 偷渡回 raw strategy qualification；
3. 在 account/PAPER deployment 层建立独立绝对风险合同；
4. deployment 层未真实实现和验证前，candidate 最多进入无资本权限的 shadow observation；
5. 新定义尚未获用户明确批准，因此不修改 schema v2、Qualification V3 或历史 artifact。

## 2. 逐项处置

| 审计意见 | 处置 | 理由/动作 |
|---|---|---|
| annual-all-years gate 低功效且日历边界任意 | 接受 | V5 v1.1 改为 D1-D5 Balanced Drawdown |
| D3 SPY-defined episode 与 D4 downside capture | 接受 | 写入 Qualification V4 hard gate |
| 防 cash dilution 必须保留 return gate | 接受并加强 | 30bps CAGR>SPY；60bps CAGR>=SPY；90bps 报告 |
| 相对门无法执行绝对账户容忍度 | 接受 | 新增独立 account-risk contract 和状态分层 |
| 立即恢复 raw strategy stress cap<=25% | 不接受为默认架构 | 与用户已批准的 no-absolute-strategy-cap 决定冲突，也混淆 strategy quality 与 deployment sizing |
| 采用组合层/vol-target 层方案 B | 接受 | 未验证前 fail closed 到 shadow，不授予 capital eligibility |
| 当前 config 的 false 未经明确批准 | 不接受 | commit、决策 memo、CLAUDE 三处均记录了用户显式决定 |
| 当前 CLAUDE 仍有 15%-20%/25% 硬不变量 | 不接受为当前事实 | 相关 current policy 已在 2026-07-22 替换；仍残留的旧说明属于历史 rationale |
| SPY MDD 口径需要统一 | 接受且提升为 P0 | 发现旧 bound SPY path 的分红未持续再投资问题，V4 禁止沿用 |
| D5 从 5pp 收紧到 3pp | 接受 | 平静年 5pp 对约 $10K 账户过松；3pp 仍允许小幅 active-risk excursion |
| 36-month 重叠导致有效样本少 | 接受 | 保留 60% consistency gate，同时强制 effective-count 报告并禁止显著性过度表述 |
| 15%/60%/5pp 有 in-sample 味道 | 接受 | D5 改 3pp；所有常数均标 project governance choice，prospective-only 复核 |

## 3. 当前 authority 的事实核验

### 3.1 当前 CLAUDE.md

当前有效文本包括：

- System Identity：absolute 与 stress-slice MaxDD 必须报告，但不再作为晋升硬阈值；
- Invariant Constraints：逐年 SPY-relative 是 2026-07-22 用户显式决定，absolute caps 是 diagnostics；
- Drawdown comparison policy：former 20%/25% promotion caps 被 prospective relative rule supersede。

`CLAUDE.md` 中“beat QQQ 会违反 15%-20% invariant”来自 2026-05-02 的历史 QQQ-deprecation rationale，
没有随 2026-07-22 policy revision 改写。它容易误导，但不能推翻后写、专门且带 revision date 的当前
policy。该句应改成明确的历史语境；这只是文档去歧义，不改变治理。

### 3.2 当前 config

`config/research_governance.yaml` schema v2：

- `require_every_year_strictly_better: true`；
- `absolute_max_drawdown_gate_enabled: false`；
- `stress_slice_absolute_drawdown_gate_enabled: false`；
- `authority: user_explicit_direction`。

它准确实现了当时用户决定。问题不是“false 已被偷偷写入”，而是新的权威研究显示 annual-all-years
本身不适合继续使用。修改它仍需用户对 schema v3 显式批准。

### 3.3 legacy evaluator

`temporal_split_v1/v2/v3`、TAA acceptance 和若干旧 PRD 仍包含 20%/25% hard gates。这些属于锁定的历史
protocol，不应回写；但 V4 loader 必须通过 protocol/schema identity 将其隔离，不能让它们成为第二机器
权威，也不能让旧测试名称误导新 promotion。

## 4. SPY benchmark 新发现

外部审计用 raw close 复算得到：

- 2020 MaxDD 34.10%；
- 2022 MaxDD 25.36%。

raw close 忽略分红，因此不适合作为本项目 total-return benchmark。可是它成功暴露了旧 bound path 的
异常。对同一 frozen exact-cash snapshot 复算：

| 口径 | 2015-2024 CAGR | 2020 MaxDD | 2022 MaxDD |
|---|---:|---:|---:|
| 旧 Qualification-bound SPY backtest | 12.35% | 31.43% | 22.71% |
| direct `total_return_close` | 13.04% | 33.70% | 24.50% |
| raw close | 不作为正式口径 | 34.10% | 25.36% |

复算输入绑定：

- SPY parquet SHA-256：`1990e0b88a726c250d6b01998793e864f85cf5daa240d66770699f21b76c91d8`；
- snapshot manifest SHA-256：`c8382dfbddfe2522c37558bb2f3c573fefedb3893c803d80abe1db9b93e80c46`；
- 旧 Qualification input SHA-256：`4374fcf0c884066e2a614c9710d70120aac1c96b968dff5563d58abbbfec4b06`。

旧 runner 只在首次 decision 建立 100% SPY target；后续现金分红留在 cash，未持续再投资。这会同时：

- 压低 SPY CAGR，使 candidate 更容易通过 return hurdle；
- 用累积现金垫压低后续年度 MaxDD，使 candidate 更难通过 relative-DD gate；
- 令同一 artifact 在收益和风险两侧产生方向不同的偏差。

因此不能把“偏保守”作为保留旧 benchmark 的理由。V4 必须使用 costless、持续分红再投资的 canonical SPY
total-return series，并把 implementable SPY entry cost 另作诊断。

## 5. 绝对风险的分层设计

### 5.1 为什么不恢复 raw strategy cap

固定 raw-strategy MaxDD cap 会把策略质量、部署规模和账户容忍度混成一个统计量，并可能通过现金稀释、
降低 beta 或针对已知 stress path 调参被 gaming。用户也已明确取消该晋升 cap。

### 5.2 为什么仍需 absolute account contract

审计员给出的 GFC 反例是决定性的：candidate -50%、SPY -55% 仍可能通过相对 gate，但不适合目标账户。
因此 absolute risk 不能被删除，只能放到正确层级：candidate signal + position sizing + risk overlay + cash +
execution 组成的 deployed account composite。

### 5.3 Fail-closed 状态机

```text
Balanced D1-D5 + return/stat/data gates PASS
                    |
                    v
       FORMAL_V5_RESEARCH_CANDIDATE
                    |
          frozen raw shadow PAPER
                    |
        account overlay + real path stress
             /                  \
          PASS                  INCOMPLETE/FAIL
           |                          |
RISK_GOVERNED_PAPER_ELIGIBLE   SHADOW_PAPER_OBSERVATION
           |
     CAPITAL_ELIGIBLE = false（本阶段）
```

建议的 deployment contract 是 15%-20% operating target、真实可重放危机路径 MaxDD<=25%、15/20/25%
alert/de-risk/halt。它必须明确是模型与响应控制，不是防止隔夜 gap overshoot 的保证。

## 6. D5 与 36-month 的独立判断

### D5

5pp 在 SPY MaxDD 2.5% 的平静年允许 candidate 7.5%，相对差约三倍。固定 3pp 更符合当前小账户风险偏好，
也比“每年差 0.01pp 就失败”稳定。动态比例规则看似精细，但会增加新的自由度和阈值 gaming，v1.1 不采用。

### 36-month

month-end 36-month windows 高度重叠，不能把几十个窗口当几十份独立证据。V4 保留 60% 为一致性 gate，
但必须输出 overlap-adjusted effective count；它不能替代 full-period、episode、downside capture、DSR/PBO 或
future forward。PAPER 只有 252 sessions 时也不能宣称完成 36-month forward 验证。

## 7. 决策边界

本处置与 V5 v1.1 是完整提案，不是已生效 policy：

- 当前 schema v2/Qualification V3 不变；
- 旧候选不按 V4 回签；
- 旧 benchmark artifact 不重写；
- 用户批准前不运行 V5 direction trial；
- 批准后必须以 governance schema v3、evaluation contract v2、Qualification V4 新实现生效。
