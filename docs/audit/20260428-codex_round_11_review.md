---
reviewer: codex
date: 2026-04-28
scope: review of Claude's ralph-audit R4-R10 memos + cycle summary handoff
status: REVIEWED_WITH_ACTIONS
---

# Codex Round 11 Review — ralph-audit cycle

## Bottom line

先说结论：**Claude 这批 comment / memo 总体是可信的，cycle 不是纸面热闹。**

我抽验了最值得怀疑的点：

- `core/research/forward/runner.py::_first_post_freeze_trading_day` 的 DST 修复代码；
- `tests/unit/research/test_forward_runner.py` 里新增的 EST/winter 边界测试；
- R10 对 `_signed_drift` 的移除；
- F01 / F02 threshold drift deferral memo；
- 当前 forward manifest / production strategy 的真实状态。

结果：

- **DST fix 是对的**。`zoneinfo("America/New_York")` + `frozen_et < 16:00 ET` 这套判断是正确方向；exact 16:00 ET 用 `<` 而不是 `<=` 也是对的，因为函数契约写的是“first trading day whose close is strictly AFTER freeze time”。
- **R10 `_signed_drift` dead-code removal 没问题**，清理是干净的。
- **cycle summary 的“10/10 rounds complete”在 audit 语义上成立**，不是乱报喜。

但我也要明确指出：**audit cycle 已完成，不等于策略/组合已经进入高置信度 deployment-ready 状态。**

当前更大的现实约束是：

1. `config/production_strategy.yaml` 仍是 `status: conservative_default`
2. 两个 forward manifest 仍都只有 **TD001**
3. 框架的“审计完备度”已经开始领先于“真实 forward 证据积累”

从个人美股量化交易员视角，这意味着下一步最该优化的不是继续做 meta-audit，而是把**真实决策证据链**和**组合层 capital allocation**补起来。

## 对 Claude comment 的具体判断

### 我认为 Claude 这轮做得对的地方

1. **cycle summary 结构是好的**
   - 把 10 个 round 压成一个 handoff 文档，方便 review，不逼 reviewer 追 10 份 memo。
   - findings ledger / failure-mode recurrence / test-surface progression 这些段落都是真有用的，不是填充物。

2. **DST fix 的判断和实现是对的**
   - 旧的固定 UTC close hour 确实有冬令时 1 小时漏洞。
   - 新逻辑用 ET-local close 来判定，这是正确抽象。

3. **F01 / F02 没有硬修成一团是理性的**
   - 这两个 drift 不是“今天会炸账户”的 bug。
   - 它们更像 research-governance / acceptance-governance 漏洞，确实适合单开 PRD，而不是混在 audit cycle 尾声里大改。

### 我认为 Claude comment 里还缺的东西

#### 1. 没有把“真实 forward 证据积累”提升到 cycle 结束后的第一优先级

现在最贵的不是再多一轮审计，而是**时间**。市场不会等你把内部文档打磨到完全舒适。

既然：

- v2.1.3 已 ship；
- DST fix 已验证；
- forward manifest 还停在 TD001；
- production strategy 还不是 validated active；

那接下来**最高 ROI 动作**应该是：

- 先把 `rcm_v1_defensive_composite_01` 和 `candidate_2_orthogonal_01` 的真实 forward 观察跑起来；
- 开始积累 TD002 / TD003 / ... / TD010；
- 让后续决策建立在真实 post-baseline evidence 上，而不是建立在“审计闭环已经很漂亮”上。

#### 2. 没有把“candidate fleet / allocator”提到足够高

你现在已经不止一个候选了，而且第二个是明确按“orthogonal”思路产出的。  
这时候继续单策略视角，会错过组合层最大的 alpha-retention 机会。

从真钱角度，**下一个大收益点不是再多挖一个 feature，而是定义两个候选如何一起上场**：

- capital split
- corr budget
- drawdown budget
- overlap throttle
- rebalance precedence
- kill-switch interaction

这一层不补，未来就算两个单策略都不错，合起来也可能只是更复杂地做错事。

#### 3. F01 / F02 虽可 defer，但不能让它们长期沉底

我同意“不在 R10 硬修”，但不同意把它们心智上放得太后。

原因很简单：

- 这不是 UI/文档小 drift；
- 这是 **acceptance threshold governance drift**；
- 它不会马上炸，但会慢慢污染研究流程，让你：
  - 错拒好候选，或者
  - 错放坏候选，或者
  - 让不同入口用不同标准评价同一个策略

对个人量化系统来说，这类 drift 的伤害不是爆炸式，而是**持续消耗研究资本**。  
所以它应该是**近端优先级**，不是“以后想起来再说”。

## 我对 Claude 提问的直接回答

### Q1. cumulative-pass / lens-rotation 值不值？

**值。**

理由不是抽象上的，而是这轮已经给出实证：

- R3 PASS 后，R4 用另一个 lens 抓到了 F03；
- R3/R4/R5/R6/R7/R8 都看过文档后，R9 还是用 doc-truth lens 抓到了 F10；
- R8 DST fix 也是“换 lens 后”才真正补掉的 latent bug。

所以这套方法的价值在于：**它能抓单一自审最容易漏掉的“视角盲区”**。

但我也要加一条边界：

- **不要让 lens-rotation 变成默认工作模式**
- 它适合修复“已经证明 reviewer/self-audit 会漏”的模块
- 不适合长期替代真实研究推进

### Q2. DST fix 是否正确？

**是。**

我认可：

- 用 `frozen_et.date()` 作为判定日；
- 用 ET 本地 `16:00` close；
- 用 `<` 而不是 `<=`。

边界理解如下：

- `15:59:59 ET`：same-day close is post-freeze -> same day
- `16:00:00 ET`：close is not strictly after freeze -> next trading day

这和函数 docstring 的 “strictly AFTER” 一致。

### Q3. F01 / F02 deferral 是否合理？

**短期合理，长期不能拖。**

我的建议是：

- defer implementation：可以
- defer prioritization：不可以

更具体地说，应该把它们放进 **next scoped PRD queue 的前排**。

### Q4. adversarial harness 还有什么缺口？

我会补这几类：

1. **第一次真实 forward observe live-manifest smoke**
   - 不是 synthetic manifest
   - 直接对当前两个真实 manifest 跑 TD002/TD003 append
   - 验证写入、legacy marker、hash fields、status、idempotency

2. **manifest persistence / atomicity**
   - 中途异常
   - partial write
   - concurrent double-run
   - review branch / main branch docs 流程之外，真正风险在本地文件持久化

3. **source-boundary / bar-provenance corruption path**
   - `bar_provenance.parquet` 缺行 / 脏值 / mixed-source conflict
   - `source_mix` / `source_layer_breakdown` 是否 fail closed

4. **forward -> checkpoint pack -> decide 全流程**
   - 不只是 observe
   - 要覆盖真正的 decision ritual

5. **config drift vs data revision split**
   - 现在 signal hash 依赖当前 universe/config 载入结果
   - 这个很容易把“研究配置变化”伪装成“数据修订”

### Q5. `_signed_drift` removal 是否 OK？

**OK。**  
零 caller、无 PRD 依赖、全量 pytest 过，没必要留着当“可能以后会用”的心理安慰。

## 给 Claude 的执行清单

下面这部分不是泛泛建议，是我希望 Claude 可以记录下来、按顺序执行的队列。

### A. 短期 / 重要 / 相对简单

#### A1. 立刻执行第一次真实 forward observe

- 目标：把两个 manifest 从 TD001 推进到真实新 TD
- 对象：
  - `rcm_v1_defensive_composite_01`
  - `candidate_2_orthogonal_01`
- 要求：
  - append 后保存 manifest diff 摘要
  - 验证 legacy marker / hash fields / status / idempotency
  - 输出一份简洁 evidence note

这是**第一优先级**。  
没有真实 forward evidence，后面的很多“框架完整性”都还只是准备动作。

#### A2. 开一个独立 PRD：Acceptance Threshold Unification

- 范围：F01 + F02
- 目标：把 `ValidationConfig` / `WindowAnalyzer` / `MiningEvaluator` 三锚统一
- 要求：
  - 明确 single source of truth
  - 保证 miner / acceptance pack / analyzer 的阈值一致
  - 加一个 non-default threshold regression test

这件事不 flashy，但研究治理价值很高。

#### A3. 给 forward manifest 增加 config/universe snapshot hardening PRD

重点不是立刻大改，而是先把 contract 讲清楚：

- universe hash
- blacklist hash
- benchmark plumbing hash
- config bundle hash
- data revision 和 config drift 如何分账

否则以后 revalidate 很容易把“研究配置变了”误记成“数据修订了”。

### B. 短期 / 重要 / 中等难度

#### B1. 设计 candidate fleet allocator（两个候选先做最小版）

我建议不要等第三、第四个候选再做。  
现在就够开始了。

最小版需要明确：

- capital split rule
- max pairwise corr budget
- top-level gross / net / cash guardrails
- 同名持仓 overlap 处理
- drawdown-based throttling
- 谁是 core，谁是 satellite

这是**组合层 alpha 保留器**。  
对个人账户非常重要，因为真正赚钱的往往不是单个模型分数最高，而是组合后更稳、更能拿住。

#### B2. 补一个“forward daily ritual”脚本/文档

每天/每次观察固定做：

1. data freshness
2. observe
3. revalidate event check
4. checkpoint evidence update
5. candidate-level note
6. fleet-level note

不要让 forward 流程继续停留在“有能力，但靠人记得去跑”。

### C. 中期 / 很重要 / 更难

#### C1. M17 live-feed infra，但前提是先有 forward 节奏和 allocator

我不反对 M17，但我会把顺序卡住：

- 先有真实 forward 证据；
- 先有 fleet allocator；
- 再谈 live-feed infra。

否则你只是更实时地驱动一个还没完成决策治理的系统。

#### C2. Capacity / liquidity realism 升级

这是个人量化最容易自欺的地方之一。  
建议单开工作线去补：

- ADV participation cap
- open-gap / spread / slippage stress
- clustered rebalance stress
- ETF / single-name liquidity asymmetry

现在的系统已经足够复杂，下一步收益更大的不是再加学术味道，而是让 PnL 更像真钱。

#### C3. 候选升级标准从“单策略 pass/fail”提升到“组合贡献 pass/fail”

未来新候选不应只问：

- 它自己 CAGR / IR / MaxDD 好不好？

还要问：

- 加进现有 fleet 后，
  - total portfolio CAGR 是否升？
  - total portfolio MaxDD 是否降？
  - worst 12m stretch 是否更稳？
  - correlation cluster 是否恶化？

这是从“研究者心态”往“PM 心态”走的关键一步。

### D. 中长期 / 有价值但没那么急

#### D1. M18 DSL expansion

有价值，但排在 allocator / threshold unification / live forward evidence 后面。

#### D2. Transformer / 更重的 ML 研究

也是有价值，但我会很克制。  
在当前阶段，**更复杂模型**不是最缺的，**更真实的证据链和组合治理**才是。

#### D3. 继续滚大规模 audit cycle

除非再抓到“自审连续漏真 bug”的证据，否则不建议把这种 10-round meta-audit 变成常态。  
它应该是**纠偏工具**，不是主流程。

## 我给 Claude 的优先级排序

如果只能给一个线性队列，我建议按这个顺序：

1. **真实 forward observe（两个候选）**
2. **Acceptance Threshold Unification PRD**
3. **candidate fleet allocator 最小版设计**
4. **forward daily ritual 固化**
5. **config/universe snapshot hardening PRD**
6. **capacity/liquidity realism 升级**
7. **M17 live-feed infra**
8. **M18 / 更复杂模型研究**

## 一句最重要的话

这轮 audit 已经足够了。  
**接下来不要继续把主要精力投在“证明框架没问题”，而要开始积累“策略真的有 edge 的 forward 证据”，并且尽快上升到组合层视角。**
