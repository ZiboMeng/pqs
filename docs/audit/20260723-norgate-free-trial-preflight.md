# Norgate 免费字段验收预检

日期：2026-07-23

状态：`BLOCKED_PERSONAL_TRIAL_REGISTRATION_REQUIRED`

用户授权：允许免费字段验收；不允许付费订阅，不允许方向性收益计算。

## 1. 结论

免费验收的代码、字段矩阵和 fail-closed 机器 artifact 已完成。实际 vendor runtime 尚未开始，因为 Norgate
要求许可证本人提供真实姓名、手机号与长期邮箱，并亲自认证其 EULA。账号属于一个自然人，登录信息不得
向其他方披露。因此项目不会代替用户填写身份、勾选认证，也不会要求用户把凭据写进仓库或发送给 Codex。

这不是技术性推脱，而是许可边界。用户完成 NDU 登录与首次更新后，验收器无需获得账号密码即可从本机
已登录服务读取接口，并且只持久化字段名、计数、布尔值与 PASS/PARTIAL/BLOCKED；不会把 vendor rows、
symbols 或 prices 提交到 Git。

## 2. 官方试用与环境事实

- 官方免费试用为 3 周，US Stocks trial 是 Platinum 权限但历史只提供最近 2 年；
- 使用 Python 需要 Windows 10/11、Norgate Data Updater 安装并运行；官方 Python package 也说明 WSL2
  可以使用，但需 mirrored networking；
- ASCII 只允许导出历史价格，不包含其他数据 features，因此不能用于完整 PIT 字段验收；
- Norgate FAQ 明确表示没有给自有应用使用的 generic API，正式支持路径是它列出的具体插件/API；
- EULA 将 licensee 定义为单个自然人，并要求其保护账号机密；trial 条款要求真实身份、手机号和长期邮箱。

本机实测：Windows 11 + WSL2、C: 剩余约 509.9 GiB，满足磁盘要求；但 NDU 与 Windows Python 尚未安装，
`.wslconfig` 也未配置 `networkingMode=mirrored`。为避免重启 WSL 中断当前工作，实际 runtime 优先使用
Windows Python；用户完成 NDU 登录后再安装，不提前改变系统。

官方资料：

- [Norgate free trial](https://norgatedata.com/freetrial.php)
- [Trial registration and terms](https://norgatedata.com/subscribe/freetrial.php)
- [NDU installation requirements](https://norgatedata.com/ndu-installation.php)
- [Norgate Python package](https://pypi.org/project/norgatedata/)
- [Norgate FAQ](https://norgatedata.com/faq.php)
- [Norgate EULA](https://norgatedata.com/subscribe/eula.php)

## 3. 文档级字段矩阵

当前 artifact：`research/data_readiness/pit_v1/norgate_trial_validation.json`

| V6 能力 | 预检 | 依据与缺口 |
|---|---|---|
| permanent security ID | PARTIAL | 官方 `assetid` 声称唯一且不变；尚未 runtime 验证 current/delisted union |
| ticker/name history | BLOCKED | `assetid -> symbol` 返回 current symbol；未文档化带起止日的历史 aliases |
| listing/delisting history | PARTIAL | 有 major-exchange time series、first/second-last quoted date 和 delisted DB；语义待实测 |
| raw daily open/close/volume | PARTIAL | 有 `price_timeseries`、NONE adjustment、NONE padding；字段与 trial coverage 待实测 |
| distributions/splits | BLOCKED | public API 记录 binary capital-event indicator，不是完整 event type/amount ledger |
| delisting disposition | BLOCKED | 未文档化 delist reason、consideration、disposition amount/price |
| revision policy | BLOCKED | 可收到 corrections，但没有验证可冻结 edition 与 replay contract |

因此，即使 runtime 把 permanent ID 和 raw daily 提升为 PASS，Norgate 单源也大概率仍不能满足 G1-G4/G12。
它可能成为正式系统的价格/上市状态组件，但 ticker history、退市处置与 revision evidence 仍需额外来源或
vendor 明确书面/字段证明。

## 4. 已实现的验收控制

- `config/norgate_trial_validation_v1.yaml`：固定免费、无收益、零凭据、零 vendor-row persistence；
- `core/data/norgate_trial_validation.py`：optional vendor adapter、aggregate-only runtime probes、七项能力矩阵；
- `scripts/validate_norgate_trial.py`：`preflight`/`runtime` 两种模式；
- `tests/unit/data/test_norgate_trial_validation.py`：覆盖身份重复、NDU 不可达、接口存在但不得夸大 formal
  eligibility 等情形；
- `scripts/build_pit_readiness.py`：readiness 现已 hash-bind Norgate 验收 artifact。

预检机器结果：

```text
runtime_status=BLOCKED_PERSONAL_TRIAL_REGISTRATION_REQUIRED
formal_source_eligible=false
phase_b_status=BLOCKED
binding_raw_independent_n=60
```

## 5. 用户一次性动作

1. 打开 [官方免费试用页](https://norgatedata.com/freetrial.php)，注册新账号；
2. 选择 `Python (Windows)` 和 `US Stocks Data Trial / Platinum`；
3. 用真实信息完成许可证本人认证并自行接受条款；
4. 安装 Norgate Data Updater，使用默认本机路径，登录并完成首次 US 数据更新；
5. 回复“**NDU 已登录并更新完成**”。不要发送用户名、密码、手机号或邮箱。

收到该状态后，项目可继续安装隔离的 Windows Python、运行 aggregate-only probes、重建 readiness，并给出
是否值得购买 Platinum 的独立结论。购买仍需另一次明确授权。
