# /loop script — unified PRD #3 + PRD #4 implementation (interleaved)

**Supersedes**: separate prd3/prd4 scripts(`loop_script_prd3_*.md` +
`loop_script_prd4_*.md`)— keep those for audit-trail / 留痕,but use
this unified script going forward.

**Operator interleaving discipline**: per round, pick highest-ROI
NEXT step from EITHER PRD #3 OR PRD #4 based on:
1. Dependency: PRD #3 P3.2+ blocked on user explicit-go (P3.1
   canonical config selection); PRD #4 P4.1-P4.4 independent
2. ROI: prefer steps that unlock more downstream work
3. Cycle-window: each round is small (1-2 commits)

Default sequencing while user-asleep / waiting for explicit-go on P3.1:
- **PRD #4 P4.1 → P4.2 → P4.3 → P4.4** (can advance without user gate)
- **PRD #3 P3.5 fingerprints** (can advance — doesn't need canonical
  selection)
- PRD #3 P3.1 canonical config memo recommendation written (operator-side
  done in `20260520-canonical_trigger_first_config_R16PathA.md`)
- PRD #3 P3.2-P3.7 ALL wait for user explicit-go on canonical

---

```
/loop unified PRD #3 trigger-first canonical promotion + PRD #4 rank-first ML
pipeline implementation,interleaved。每轮按此协议:

【定位】先读:
- docs/memos/20260519-prdx_execution_ledger.md (跨轮 SoT)
- docs/prd/20260520-prd_trigger_first_canonical_promotion.md (PRD #3)
- docs/prd/20260520-prd_rank_first_ml_pipeline.md (PRD #4)
- docs/memos/20260520-canonical_trigger_first_config_R16PathA.md (operator P3.1 推荐)
- docs/memos/20260520-passed_qqq_gate_schema_decision.md (F6 directional)
- docs/memos/20260519-strategic_close_out_REVISION_post_audit_fix.md (§9.0 hard禁)
- git log 最近若干

根据进度找"下一个最小可验证步",interleave PRD #3 / #4 per dependency + ROI:

PRD #3 锁定 phase 顺序:
  P3.1 canonical config selection(operator 已写推荐 R16 Path A;**等用户 explicit-go**)
  P3.2 OOS walk-forward for trigger-first(**blocked on P3.1**)
  P3.3 paper-backtest M3 alignment(**blocked on P3.1**)
  P3.4 QQQ diagnostic(folded into P3.2)
  P3.5 fingerprints(**可独立做**;universe_hash + factor_registry_hash + config_hash)
  P3.6 M2 promote_strategy.py extension(**blocked on P3.1 + P3.2 + P3.5**)
  P3.7 status flip + verification(**blocked on P3.6**)

PRD #4 锁定 phase 顺序(**全部不依赖 user gate,可独立推进**):
  P4.1 cross-sectional rank model(Stage 1 RANK;XGBRanker/LightGBM/linear baseline)
  P4.2 sign-vote binary classifier(Stage 2 SIGN;{VETO, NO_VOTE})
  P4.3 multi-TF context features
  P4.4 training pipeline + artifact persistence
  P4.5 acceptance experiments + voter integration

Operator 默认优先顺序(user 不在线时):
  1. PRD #4 P4.1 build (rank model scaffold + linear baseline 1-fold smoke)
  2. PRD #4 P4.1 XGBRanker / LightGBM model class
  3. PRD #3 P3.5 fingerprint computation utility
  4. PRD #4 P4.4 training pipeline + walk-forward driver
  5. PRD #4 P4.2 sign classifier scaffold + 1-fold smoke
  6. PRD #4 P4.3 multi-TF features extension
  7. PRD #4 P4.5 acceptance experiments(需 P4.1/P4.2 都 PASS 才有意义跑)

User 醒后 explicit-go on P3.1 → 立即切到 PRD #3 P3.2 OOS walk-forward。

【执行】小步:一轮一个主目标。可行则 TDD —— RED 后 GREEN 后跑。
复用现有 patterns(per PRD-X v2 §F.1 inventory + 已 ship 9 modules)。
新模块只放:
  core/research/ml/(P4 ML pipeline)
  core/research/promotion/(P3.5 fingerprints + P3.6 M2 extension)
  dev/scripts/ml/(P4 training drivers)
  dev/scripts/promotion/(P3 driver)
  data/ml/(artifacts)
重 ML 训练前必 bar-integrity smoke(weekend rows / monotone / sealed-year guard)。
长跑用后台(Bash run_in_background)。
commit 一律 git commit -F <msgfile>。
任何动 canonical chart_native L3 / core acceptance / backtest_engine.run / M11
主路径的改动须 bit-identical 回归验证。

【纪律】
- R1-R4 自审每轮;R3 真跑对比期望永不跳
- bug 必 ROOT CAUSE 不 hand-wave
- 禁 blanket "X 不行"(只写"这个 attempt 失败+用了什么+root cause"
  per `feedback_no_blanket_failure_verdict`)
- sealed 2026 永不读;守 temporal_split partition
- **strict-chronological walk-forward**(Track-A R1 leakage 教训;
  interleaved selector + ML 训练 = looking-forward leakage)
- websearch 仅方法/论文禁市场数据
- §6.4 不变量守护硬绑(long-only / no-margin / SQQQ / MaxDD / 真 short 永禁)
- bit-identical default mode(R12/T0/sample_weight=None precedent)
- **§9.0 post-audit-fix HARD**(PRD #4 核心):
  - vote_fn 输出严格 SignVote enum(VETO/NO_VOTE/CONFIRM)
  - 禁 continuous magnitude as size weight(post-fix A/B FORCED 跨 3 model class
    一致 magnitude IC 普世毒;详 strategic_close_out_REVISION memo)
  - MLSidecarPolicy.vote runtime TypeError 是 safety net
- 每 ML 模型必 per-bar cross-sectional standardization(避 magnitude leakage)
- PRD #4 P4.1 AC 3 binding constraint:executable + expanded_v2 universe BOTH;
  horizon match PRD-2 candidate;on-tradeable AND pooled BOTH 验证
- PRD #3 scope boundary:thin overlay canonical NOT full state-machine engine
- commit hygiene:每轮 commit 前 `git status` 查 untracked 关键 module(P4-1 防 R5a-bug
  复现)

【收尾每轮】
1. commit+push(-F 文件;具体文件不用 git add -A)
2. 更新 docs/memos/20260519-prdx_execution_ledger.md 进度表 + 本轮追加行
3. 输出 11-part 式简报:
   - 本轮主题 / 选 PRD#3 还是 #4 + 哪个 phase
   - 本轮目标
   - 为什么这轮优先
   - 做了什么 + 改了哪些文件
   - 跑了什么测试 + 结果
   - 新发现 / 新机会
   - 剩余风险
   - 下一轮建议方向(下一步会做 PRD #3 哪 phase 或 PRD #4 哪 phase)
   - TODO checklist 更新

【停止-等用户(directional)】遇到这些不自决,停下写清选项+建议然后结束本轮:
- PRD #3 P3.1 canonical config selection:operator 已推 R16 Path A,需用户 explicit-go
  on this 或 override 选其他(R14 / R12 Path A / etc)
- F6 passed_qqq_gate schema decision per 20260520-passed_qqq_gate_schema_decision.md
  (3 options A/B/C)
- 任何动 §6.4 / §9.0 invariant 项
- CLAUDE.md invariant 进一步修订
- 真 short execution
- live broker 接入 / production_strategy.yaml status flip 实操(P3.7 等用户最终签字)
- 选 XGBRanker / LightGBM / linear baseline 之外的 model class
- horizon 改成不在 PRD-2 candidate set 的值
- pool/universe 扩到 expanded_v2 之外

【DONE】PRD #3 P3.1-P3.7 全 AC PASS + PRD #4 P4.1-P4.5 全 AC PASS + 整合 acceptance
(PRD #4 trained voter 接进 PRD #3 canonical config 的 ml_sidecar section + 实跑
beat heuristic baseline)+ §6.4/§9.0/sealed-2026 全程守 + M11 parity preserved +
final honest summary memo → 终止 loop。

注意:实际 status="active" flip 是 PRD #3 P3.7 的最后一步,**保持 directional 必由
用户 explicit-go 签字**(operator 不替决)。

【硬禁】
- 不自启嵌套 loop / 不静默改不变量(§6.4/§9.0)
- 不 git add -A
- 不假装完成(做出来 ≠ 做透;rank-IC 数字必从 R3 实跑出来)
- 不读 sealed 2026 任何 query 路径
- 不用 continuous magnitude as size weight(§9.0 post-fix HARD)
- 不绕过 §6.4 不变量守护任意一条
- 不对 backtest_engine.run() 主路径做改动(M11 parity wrapper pattern 保留)
- 不破 temporal-split discipline(per `feedback_temporal_split_discipline`)
```
