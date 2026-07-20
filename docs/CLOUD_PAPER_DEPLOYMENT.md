# PQS Phase 3 云端 PAPER 部署准备报告

日期：2026-07-20

状态：`PREPARED_AND_LOCAL_SMOKE_TESTED`，不是 `DEPLOYED`

适用模式：`FORWARD_PAPER`，`live_enabled=false`

## 1. 结论

仓库已经具备可移植到云主机或 Kubernetes 的最小安全部署单元：固定 Python 版本和直接依赖、非 root
进程、只读根文件系统、显式持久卷、singleton、health/readiness 分离、优雅退出、SQLite 在线备份与
非覆盖恢复、默认拒绝网络以及 provider-free IaC 安全契约。

本机没有 Docker/Podman、kubectl、Terraform/OpenTofu，也没有获批云账户、镜像仓库、broker 凭据或
付费数据源。因此本阶段完成的是静态验证和本地进程/持久化 smoke，不是容器 build、编排器启动或云部署。

## 2. 部署资产

| 资产 | 作用 | 安全边界 |
|---|---|---|
| `Dockerfile` | Python 3.13.12、运行依赖锁、Phase 3 entrypoint/liveness | UID/GID 10001；build 时复验策略 artifact |
| `deployment/compose.yaml` | 单实例本地容器与四个持久卷 | read-only root、cap-drop、no-new-privileges、tmpfs |
| `deployment/kubernetes/phase3-paper.yaml` | singleton StatefulSet/PVC/PDB/NetworkPolicy 模板 | non-root、seccomp、禁 service-account token、默认 deny egress |
| `deployment/terraform/` | provider-free 部署输入契约 | 只校验 immutable digest、singleton、加密卷、PAPER；创建资源数为 0 |
| `monitoring/phase3-monitoring.yaml` | supervisor cadence、heartbeat、status/alert 命令 | monitor-only，不生成 market event |
| `scripts/phase3_backup.py` | SQLite-aware backup/verify/restore | 拒绝 symlink；恢复只到新目录且要求 manifest hash 确认 |
| `scripts/validate_phase3_deployment.py` | 静态 fail-closed validator | 检查 Docker/Compose/Kubernetes/IaC/lock 和工具可用性 |

默认 supervisor 只做 heartbeat、只读状态和告警评估。它不会伪造 `CLOSE_DECISION`、
`OPEN_EXECUTION` 或 `EOD_FINALIZE`，所以基础设施 uptime 不会被误计为真实 Forward PAPER 证据。

## 3. 已实际验证

- 静态部署 validator：PASS；Docker、Compose、Kubernetes、Terraform 契约全部满足检查项。
- 本地 supervisor：启动、heartbeat、liveness、重启后 missed-schedule 告警和 SIGTERM 优雅退出通过。
- 持久化：3 个 SQLite/状态文件在线备份、manifest hash 验证和恢复到全新路径后 liveness 通过。
- runtime lock：24 个直接依赖与冻结策略环境一致；`pip check` 和 `pip-audit` 通过。
- 策略 artifact：根哈希
  `7d1c2d96ea06f051f298331a6a9a8a5bc6e0b85af72fd158e8524cc56b0a553c` 复验通过。
- Phase 3 runtime certification：根哈希
  `438d366637d146be189617eaefd678f8127a634222eeb6ad2428ee4bacc93cb0` 复验通过。

由于本机没有容器或 IaC 工具，下列结果明确为未验证：镜像 build/sign/push、容器内 health、Kubernetes
调度和卷重挂载、真实加密存储、云日志/告警、远端对象锁、云端灾难恢复、真实 provider 连通性。

## 4. 获得外部授权后的部署门

部署前必须全部满足：

1. 构建并签名镜像，以真实不可变 digest 替换 Kubernetes 中全零占位 digest；
2. 选择加密、可备份、单写者语义明确的 RWO 存储，并演练恢复到新卷；
3. 只通过 secret mount 或平台 secret 注入只读 provider 凭据，禁止写入仓库或普通环境快照；
4. 如确需数据源 egress，按最小目的地址修改默认 deny NetworkPolicy，并保留 DNS/TLS 审计；
5. 保持副本数为 1，同时保留数据库 lease/fencing；不得仅依赖编排器副本数防 split-brain；
6. 启动后先运行 artifact、config、registry、数据库和 broker snapshot readiness；
7. readiness 必须仍显示 `ready_for_live=false`。Phase 3 不存在 LIVE 开关；
8. 用显式、不可变的真实市场事件调用 forward CLI。supervisor heartbeat 不计入 forward session；
9. 首个 session 前验证告警值班、备份周期、时钟、NYSE calendar 和 operator runbook；
10. 在真实 broker 写权限仍为 false 的条件下累计 PAPER 证据。

推荐部署顺序是：镜像静态扫描与签名 → 临时隔离环境 smoke → 空状态启动 → 备份/恢复演练 →
只读 provider 连通性 → 单个真实 Forward PAPER session → 对账审核 → 才进入长期调度。

## 5. 回滚与灾难恢复

- 代码回滚基点：tag `codex-pre-forward-paper-phase3-20260720`，指向 Phase 2 基线。
- 镜像回滚：只允许切换到已签名 digest；不能使用 mutable tag。
- 状态回滚：不覆盖现有目录。先 global pause，完成在线备份和 manifest verify，再恢复到新路径并以只读
  status/reconcile 检查，最后由显式 `YES:<request-id>` 操作决定是否恢复 PAPER。
- artifact、registry、hash-chain 或 broker snapshot 不一致时保持暂停；不得通过删库或改 manifest 消除证据。
- 本地 dangling Git objects 是可恢复历史对象，不是损坏；本阶段没有执行 prune。

## 6. 当前阻塞项

| 项目 | 当前状态 | 解锁条件 |
|---|---|---|
| 容器 build/start | 未执行 | 安装 Docker/Podman并完成镜像审查 |
| Kubernetes 部署 | 未执行 | 真实签名 digest、集群、加密 RWO 存储和网络审批 |
| Terraform/OpenTofu plan/apply | 未执行 | 工具、获批 provider 模块和云账户授权 |
| broker snapshot | 未初始化 | 获批 sandbox/read-only 凭据；本阶段仍禁止写单 |
| 外部告警通知 | 未配置 | 独立批准的通知 adapter/secret；本地 durable sink 已可用 |
| 远端 sealed object lock | 未配置 | 独立 UID/账户和不可变存储治理 |

这些阻塞不影响代码层 Phase 3 验收，但阻止任何“已云部署”“已生产就绪”或“可 LIVE”的声明。
