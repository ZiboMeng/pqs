# /loop script — PRD #4 rank-first ML pipeline

Use this prompt verbatim with `/loop` to drive PRD #4 implementation.

```
/loop 不间断推进 PRD #4 rank-first ML pipeline implementation per
docs/prd/20260520-prd_rank_first_ml_pipeline.md。每轮按此协议:

【定位】先读 docs/memos/20260519-prdx_execution_ledger.md(跨轮 SoT)+
docs/prd/20260520-prd_rank_first_ml_pipeline.md(主 PRD,5 phases)+
docs/memos/20260519-strategic_close_out_REVISION_post_audit_fix.md(§9.0 post-fix
hard禁 continuous magnitude as size)+ core/research/decision/ml_voters.py(已 ship
voter wiring)+ git log 最近若干。据 PRD 进度找"下一个最小可验证步"。

锁定 PRD #4 phase 顺序:
  P4.1 cross-sectional rank model(Stage 1 RANK;XGBRanker / LightGBM / linear baseline;
       AC: rank-IC > 0.02 + rank-IR > 0.30 BOTH 在 executable + expanded_v2)
  P4.2 sign-vote binary classifier(Stage 2 SIGN;{VETO, NO_VOTE};F1 > baseline)
  P4.3 multi-TF context features(higher-TF context + lower-TF execution;无 fixed
       cadence)
  P4.4 training pipeline + artifact persistence(walk-forward,sealed-2026 守)
  P4.5 acceptance experiments + production integration(4 paths: A baseline /
       B Stage 2 only / C Stage 1+2 / D cap_aware + ML overlay)

【执行】小步:一轮一个主目标。可行则 TDD。
复用现有 113-factor research panel(core.factors.factor_generator.generate_all_factors)
+ temporal_split discipline + sealed-2026 partition + MLSidecarPolicy §9.0 runtime
enforcement + ml_voters.py 4 voter factories。
新模块只放 core/research/ml/(P4.1-P4.4 全 ship 在这里)+ dev/scripts/ml/(training driver)+
data/ml/(artifact)。
重 ML 训练前必 bar-integrity smoke(weekend rows / monotone / sealed-year guard)。
长跑用后台(Bash run_in_background)。commit 一律 git commit -F <msgfile>。

【纪律】R1-R4 自审每轮(R3 真跑对比期望永不跳);bug 必 ROOT CAUSE;
禁 blanket "ML 不行"(per `feedback_no_blanket_failure_verdict`,只写"this attempt 失败
+用了什么+root cause");
sealed 2026 永不读;
strict-chronological walk-forward(interleaved selector + ML 训练 = looking-forward leakage,
Track-A R1 教训);
**§9.0 post-audit-fix HARD**:vote_fn 输出严格 SignVote enum(VETO/NO_VOTE/CONFIRM),
禁 continuous magnitude as size weight(post-fix A/B FORCED 跨 3 model class 一致
magnitude IC 普世毒);MLSidecarPolicy.vote runtime TypeError 是 safety net 不是
代码意图;
§6.4 不变量(long-only/no-margin/MaxDD)守(ML 是 sidecar 不是 sizer);
特征严格 per-bar cross-sectional standardization(避 magnitude leakage);
universe + horizon + pool 三 binding constraint per PRD §P4.1 AC:executable AND
expanded_v2 双过,horizon match PRD-2 candidate,on-tradeable + pooled 双验证。

【收尾每轮】commit+push(-F 文件;具体文件不用 git add -A)→ 更新 ledger
进度表 + 本轮追加行 → 输出 11-part 式简报(含 fold-level rank-IC / rank-IR 数字)。

【停止-等用户(directional)】遇到这些不自决:
- 选 XGBRanker vs LightGBM vs linear baseline 之外的 model class
- horizon 改成不在 PRD-2 candidate set 的值
- pool/universe 扩到 expanded_v2 之外
- §9.0 invariant 修订
- 任何动 backtest_engine.run 主路径

【DONE】P4.1-P4.5 全 phase per-phase AC 达成 + R-ML-A/B/C/D 至少 1 path 在 Sharpe AND
MaxDD 两 metric 都 beat heuristic baseline + §9.0 invariant verified end-to-end +
artifact lineage 可重 + voter wired into config schema(classifier_voter loadable)→
final honest summary + 终止 loop。注:promote 进 production 走 PRD #3 M2 path,
not 本 PRD。

【硬禁】不静默用 continuous magnitude as size(§9.0);不读 sealed 2026;
不绕过 §6.4;不 git add -A;不假装训练成功(rank-IC 数字必从 R3 实跑出来);
不破 temporal-split discipline。
```
