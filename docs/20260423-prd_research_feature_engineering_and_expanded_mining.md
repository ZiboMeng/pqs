# PRD：Research Feature Engineering + Expanded Universe Re-Mining

**Date**: 2026-04-23
**Status**: ACCEPTED — supersedes draft v0.1 (`_feature_engineering_v1` filename)
**Connects to**: `docs/20260422-deep_mining_50round_final_synthesis.md`
**Execution mode**: ralph-loop (see §15)
**Lineage tag (all rounds)**: `post-2026-04-23-feat-v1-expanded`

---

## 1. 背景与目标

当前研究已经得到三个清晰结论：

1. 现有 52-symbol universe + 当前 factor space 基本饱和，继续在原空间里加大搜索预算，边际收益有限。
2. Expanded universe 已经显示出研究价值，但旧参数在新 universe 上没有被重新调优；因此不能用旧参数表现来否定扩容方向。
3. 现有 research panel 仍有明显 coverage 缺口，尤其是短期 returns、raw overnight gap、相对 benchmark 因子、52 周位置因子，以及部分标签模式（oc / oo）尚未补齐。

本 PRD 的目标是把后续工作收敛成一条明确主线：

**先补 research feature engineering，再基于 expanded universe 做一轮 fresh mining，然后根据结果进入 regime / acceptance / DSL 修正的下一层验证。**

本 PRD 明确不以"今晚直接生成 production 候选"为目标，而以"把研究输入空间补齐并启动新一轮高信息增益搜索"为目标。

---

## 2. 本轮决策总览

### D1. Helper 放置方式

**决策：拆分实现层，但保留稳定入口。**

不建议继续把新增逻辑全部堆进 `core/factors/base_factors.py`。本轮新增内容包含：

* 10 个新增 research factors
* forward return 模式扩展（cc / oc / oo）
* per-date tradability / admission mask 暴露
* 15+ 单测

如果继续堆到单文件，会让后续维护、命名管理、窗口定义、标签复用都变得更脆弱。

**推荐结构：**

* `base_returns.py`：ret_1d / ret_2d / reversal family / overnight gap raw
* `base_volatility.py`：hl_range / vol helpers / range-like 因子
* `base_relative.py`：rel_spy_5d / dist_52w_high / benchmark-relative 因子
* `base_factors.py`：保留为统一入口 / registry / 对外兼容层

这样做的原则是：

* **对外 API 尽量不变**
* **实现按主题拆分**
* **避免 monolith 继续膨胀**

### D2. `dollar_vol_20d` 的角色

**决策：两用，但分层。**

`dollar_vol_20d` 同时作为：

1. **ML / research feature**：供 mining / screening / ML panel 使用
2. **tradability mask 的基础输入**：生成 per-date-per-symbol tradability mask

但不能把 raw feature 与 filter 语义混成一个对象。

**实现原则：**

* `dollar_vol_20d` 作为普通 research feature 保留原始数值
* 另行生成 `tradable_mask_dollar_vol_20d`（或等价命名）作为布尔 mask
* PRODUCTION_FACTORS 与生产 admission 规则本轮不改

### D3. `vol_20d` vs `vol_21d`

**决策：不新增独立 `vol_20d` 计算逻辑；在 research 层做 alias，并在文档中明确 `vol_21d` 视为 de-facto 20d。**

原因：

* 避免为了几乎等价的窗口重新引入一套冗余实现
* 保持与现有 panel、历史试验结果的连续性
* 给 LLM / mining / screening 端一个更统一的名字解析层

**推荐做法：**

* 在 research feature registry 中登记 `vol_20d -> vol_21d`
* 在 PRD / README / docs 中写明窗口近似关系
* 不修改生产因子名

### D4. `dist_52w_high` 窗口定义

**决策：252。**

采用 252 交易日，理由是：

* 与研究语境中的 "52-week high" 习惯定义更一致
* 与风险 / position-based 因子直觉更一致
* 避免 250/252 在研究结果比对时产生无意义混淆

### D5. IC screen panel 使用哪个 universe

**决策：主 panel 用 post-expansion 79-symbol universe。**

原因：

* 本轮的核心目标就是服务 expanded universe 的后续 mining
* 如果 feature engineering 仍停留在 52-symbol panel，后面的筛选与 mining 输入会错位

但为了保持可比性，建议额外保留一份轻量的 52-symbol 对照统计（不是主 screen）。

---

## 3. 本轮范围（In Scope）

### 3.1 新增 research features

基于当前审计，目标是补齐下列净新增：

#### A. 必做新增（当前缺失）

* `ret_1d`
* `ret_2d`
* `hl_range`
* `dist_52w_high`
* `rel_spy_5d`

#### B. 部分已有但需要补 raw sibling / 规范化定义

* `reversal_5d`：补 raw sibling，并显式定义 sign convention
* `overnight_gap_5d` / `overnight_gap_21d`：当前只有 rolling mean，需补 raw 1-bar gap
* `mean_rev_sma20`：补充 sign-flipped / raw 关系说明

#### C. alias / 兼容层

* `vol_20d` → alias 到现有 `vol_21d`
* `volume_surge_20d` → alias 到现有 `volume_ratio_20d`

### 3.2 labels 扩展

扩展 `compute_forward_returns` 的 mode：

* `cc`
* `oc`
* `oo`

现状是 `y_cc_*` 已有，但 `y_oc_1d` / `y_oo_1d` 缺失。目标是把标签模式补成一个统一接口，而不是散落的特例。

### 3.3 filters / masks 暴露

现有 admission/filter 逻辑只在 universe refresh 层运行，未显式暴露为 per-date-per-symbol mask。

本轮目标：

* 将 admission / tradability 相关逻辑暴露为 research 可消费的面板级 mask
* 用于 IC screen、label alignment、panel filtering
* 不改变生产 refresh 逻辑，只新增 research-side observability

### 3.4 单测

目标 15+，覆盖：

* factor 数值正确性
* alias 正确性
* label 模式正确性（cc / oc / oo）
* lookahead 安全性
* mask 暴露语义
* sign convention
* 窗口边界 / NaN 行为

---

## 4. 不在本轮范围（Out of Scope）

以下内容本轮明确不作为主线：

1. 修改 `PRODUCTION_FACTORS`
2. 立即自动 promote 新 spec 到 `production_strategy.yaml`
3. 重构全部 factor infra 或一次性重写全部 panel builder
4. 重型 Transformer / decoder-only / encoder-decoder 新实验主线
5. 大规模全库 re-score / 全历史重算
6. Stage 3 universe 同步接入第一轮 baseline

---

## 5. 为什么顺序必须是"先 feature engineering，再 expanded mining"

本轮不是简单地"加 27 个 symbol 再多跑几轮"。

如果不先补齐 research feature coverage，会出现三个问题：

1. **expanded universe 的新增信息进不来**

   * 新 symbol 加进来，但 panel 仍缺 benchmark-relative / short-horizon / path-shape 类输入
   * 相当于只扩了票池，没有扩研究可见性

2. **第一轮 fresh mining 的信息增益被浪费**

   * 新的 universe 已经需要新搜索；如果 panel 还不完整，跑出来的 spec 只能基于旧 coverage 做局部优化

3. **后续很难归因**

   * 如果先跑 expanded mining，再补 features，等于把"universe 改变"和"feature space 改变"拆成两轮低质量实验
   * 更合理的是：先把 panel 补齐，再让 expanded universe 得到一轮干净搜索

结论：

**本轮最佳顺序是：先补 panel，再做 expanded universe baseline mining。**

---

## 6. Feature Engineering 详细实施方案

### 6.1 设计原则

1. **研究层增强，不动生产层默认行为**
2. **所有新增 feature 均必须 lookahead-safe**
3. **命名清晰区分 raw / transformed / alias**
4. **标签与 mask 统一走同一套对齐逻辑**
5. **新增结构要服务后续 mining，不只是补"看起来缺了"的名词**

### 6.2 因子族拆解

#### Returns family

* `ret_1d`
* `ret_2d`
* raw `overnight_gap_1d`
* rolling `overnight_gap_5d`
* rolling `overnight_gap_21d`
* `reversal_5d`
* `mean_rev_sma20`

关键要求：

* 明确每个因子是 raw direction 还是 signal-ready direction
* 所有 sign-flipped 因子必须保留对应 raw sibling 或文档说明

#### Volatility / Range family

* `hl_range`
* alias: `vol_20d -> vol_21d`
* `dollar_vol_20d`

关键要求：

* `hl_range` 明确定义是否归一化（建议相对 close 归一化）
* `dollar_vol_20d` 同时支持 feature 与 mask 派生

#### Relative / Position family

* `dist_52w_high`
* `rel_spy_5d`

关键要求：

* `rel_spy_5d` 必须保证 benchmark 对齐
* `dist_52w_high` 明确为 rolling max reference，不允许未来污染

### 6.3 Label 扩展

统一 forward-return 计算接口：

* `cc`: close-to-close
* `oc`: open-to-close
* `oo`: open-to-open

目标不是简单再加两个函数，而是让：

* label mode 成为统一参数
* 屏蔽 mode-specific 调用分叉
* 确保后续 ML / IC / screening 都能用相同接口选择标签

### 6.4 Mask 暴露

需要把目前只在 universe refresh 中内部使用的条件，显式暴露为：

* admission mask
* tradability mask
* optional combined research mask

用途：

* IC screen 使用统一样本定义
* 排查 label / feature 是否落在不可交易样本上
* 后续 mining 或 ML panel 可以选择是否严格使用 tradable universe

---

## 7. Expanded Universe Mining 详细实施方案

### 7.1 Universe 范围

本轮只使用：

* 现有 52 symbols
* 新增 Stage 1 + Stage 2 共 27 symbols

总计：

* 79-symbol expanded universe

**明确不把 Stage 3 直接并入第一轮 baseline。**

原因：

* Stage 3 更偏高 beta / 更高相关扩张
* 本轮首先要验证 expanded universe 是否能带来更干净的 alpha 扩展
* 过早引入 Stage 3，会让归因再次变差

### 7.2 研究顺序

#### Phase A：panel ready

完成 feature engineering 后，先确认：

* 79-symbol panel 可稳定生成
* 所有新增 feature / label / mask 可以被下游消费
* alias 与 raw sibling 行为清晰

#### Phase B：fresh baseline mining（R39）

用 expanded universe + 补齐后的 panel 跑一轮 fresh baseline mining。

这一轮的核心目标不是"立即找到 production strategy"，而是回答：

* unique spec 数量是否显著上升
* top specs 是否不再完全局限于旧因子簇
* full-period 表现是否较旧 universe / conservative baseline 改善
* holdout / OOS 是否保持基本生命力

#### Phase C：top-K 结构分析

对 R39 结果不只看一行分数，而要读：

* 因子族分布
* 是否出现 benchmark-relative / position / short-horizon 因子进入 top specs
* 新增 27 个 symbols 是否在 alpha 贡献中有存在感
* improved spec 是否靠单一高 beta 风格"伪改善"

#### Phase D：R40 regime validation

如果 R39 出现方向性改善，再进入 regime-stratified validation，重点看：

* bull / bear / crash / recovery 各段表现
* 是否只是 risk-on 放大带来的表面改善
* defensive / recovery behavior 是否合理

#### Phase E：R41 acceptance pack v2

只有在 top specs 通过前述筛查后，再进入 acceptance pack。其目的是：

* 排除 cost fragile 的候选
* 排除 stress 不稳的候选
* 过滤"holdout 强但全周期太薄"的候选

---

## 8. DSL 线怎么接

已知信息显示 DSL layer 在 expanded universe 上仍然贡献正向 alpha，因此：

* DSL 不应被移除
* 但 DSL 修正不应与 expanded-universe baseline 第一轮混在一起

推荐顺序：

1. 先做 expanded universe baseline mining
2. 读 R39 top specs
3. 再做 DSL fast-exit ablation
4. 单独判断 DSL 修正是否改善 recovery / V-shape 退出问题

这样可以避免把 universe 变化与 DSL 变化混成一个结论。

---

## 9. LLM Factor Mining / Transformer 的位置

### 9.1 LLM factor mining

**建议做，但只做 sidecar，不做主线。**

原因：

* 现阶段最重要的是 expanded universe 的 fresh search
* LLM 更适合作为新 factor 候选的持续供给器
* 不适合抢占今晚主线

建议方式：

* 只产出 3-6 个高质量候选
* 限定在 expanded-universe-aware 的方向，例如：

  * benchmark-relative breadth
  * defensive-vs-cyclical spread
  * sector leadership rotation
  * path-shape / distance-from-extrema
* 候选与本轮 panel 补齐后的 feature family 保持一致

**参考素材**：已有 97 个 funnel-visible LLM candidates（commit `74dbfec`），
含 20 Gemini_round_02 + 20 codex_round_04。Step 7 先从中按方向挑 3-6
个重跑 funnel，再决定是否新造。

### 9.2 Transformer

**本轮不建议作为主线。**

理由：

* 历史结果已经表明当前主要瓶颈不在 model class
* 1650 GPU 只适合 very small validation，不适合大 sweep
* decoder-only / encoder-decoder 与当前任务形状不匹配

如果必须做：

* 只做 very small encoder-only confirmation
* 且放在 expanded universe baseline 之后
* 目标仅限于验证"新输入空间是否让 sequence encoder 更接近可用"

---

## 10. 成功标准

### 10.1 Feature Engineering 成功标准

* 10 个 research features 补齐并可被下游调用
* `compute_forward_returns` 支持 `cc / oc / oo`
* 研究层可拿到 per-date-per-symbol mask
* 15+ 单测全部通过
* 不改动 `PRODUCTION_FACTORS`

### 10.2 Mining 成功标准

* fresh R39 产生比旧状态更丰富的 unique specs
* top-K 不再完全围绕旧因子簇
* 至少出现 1-3 个比旧 baseline 更有希望的候选
* 结果足以决定是否进入 R40/R41

### 10.3 研究价值成功标准

即便暂未产生可 promote spec，只要出现以下信号，也视为成功：

* expanded universe 重新打开搜索空间
* 新 feature families 开始进入 top specs
* DSL 在 expanded universe 上仍显示正向贡献
* 后续 should-do 的方向比之前更清晰

---

## 11. 风险与对策

### 风险 1：功能补得太多，影响现有 factor infra 稳定性

**对策：**

* 实现拆分，入口兼容
* 单测覆盖 alias / labels / masks / sign convention

### 风险 2：panel 补齐后，结果改善仍不显著

**对策：**

* 先分析 top-K 结构，而不是立刻跳 Transformer
* 如果仍不动，再考虑补新的 factor families 或 Stage 3

### 风险 3：expanded universe 改善只来自更高 beta

**对策：**

* regime validation 中重点审 recovery / drawdown / risk-on dependency
* 不以单一 CAGR 决策

### 风险 4：LLM sidecar 产出大量冗余候选

**对策：**

* 严格限制候选数量
* 只围绕 expanded-universe-aware 的方向提案

---

## 12. 推荐执行顺序

### Step 1

完成 feature engineering：

* 新 research factors
* label mode 扩展
* per-date mask 暴露
* 单测

### Step 2

生成 / 校验 expanded-universe 79-symbol research panel

### Step 3

在 fresh study / fresh cache 条件下跑 expanded universe baseline mining（R39）

### Step 4

对 R39 做 top-K 结构阅读与初步 regime 观察

### Step 5

只有在 R39 显示方向性改善后，进入 R40 / R41

### Step 6

把 DSL fast-exit 作为单独 ablation 接入，不与 baseline 第一轮混跑

### Step 7

最后再布置一轮轻量 LLM factor candidate generation，作为后续续航线

---

## 13. 最终建议（一句话）

**先把 research panel 补齐，再让 expanded universe 进入一轮 fresh mining；LLM factor mining 只做 sidecar，Transformer 不做主线。**

---

## 14. 连接当前状态（Pre-PRD 已完成）

* R38 Stage 1+2 universe 扩容（27 符号，commit `786e267`）— 79-symbol universe 已在 `config/universe.yaml`
* 旧 R39 结果作为参考：`post-2026-04-22-deep-R38-stage12` lineage, 70 trials, 1 OOS pass
* 候选 `4b5f36ed9ab5` 被 reject（9/10 gates，cost_robust + stress 双 fail）— 保留作 research lead
* NaN/inf metric bug fixes 已落盘：M14 `compute_metrics` (commit `ee3effb`) +
  `_check_qqq_gate` 同类修复 (commit `1f7e08e`) + D4 fail-soft WARN (commit `2f9fbe9`)
* DSL Rule 2 suppress_if + Rule 5 `&` fix + PG→GIS 一致性（commit `786e267`）
* LLM candidate inventory 97/97 funnel-visible（commit `74dbfec`）
* Backups on disk: `data/mining/optuna.db.bak.20260422_210343` + `archive.db.bak.20260422_210343`

---

## 15. Ralph-Loop 执行方案

本 PRD 的 7 个 Step 用 ralph-loop autonomous 执行。

### 15.1 推荐 loop number: **15 rounds**（上限，可提前 halt）

**推导**：

| Step | 任务 | 预估 rounds |
|---|---|---:|
| Step 1 | Feature engineering（10 factors + labels + masks + 15+ 单测） | 3-4 |
| Step 2 | Panel build + sanity check | 1 |
| Step 3 | R39 fresh baseline mining (80 trials × 3600s) | 1-2 |
| Step 4 | Top-K 结构分析 + 因子族统计 | 1 |
| Step 5 | R40 regime validation + R41 acceptance pack | 2-3 |
| Step 6 | DSL fast-exit ablation（A/B backtest）| 1 |
| Step 7 | LLM sidecar（从 97 candidates 挑 3-6 跑 funnel）| 1-2 |
| Buffer | 未预期诊断、bug fix、重跑 | 2-3 |
| **合计** | | **12-16** |

**15 作为"上限不浪费"折中值**：

* 低于 12 大概率不够（Step 1 单测覆盖面 + Step 5 条件分支）
* 20+ 容易漫无目的；50-round deep-mining 已证明 autonomous 模式下超过一定轮数后边际产出快速下降
* 15 允许正常预算 + 2-3 round buffer，**§15.3 halt 条件触发时自动提前退出**

### 15.2 Launch script

`scripts/start_feature_and_mining_loop.sh`（本 commit 新建）

关键参数：

* Rounds: 15
* Lineage tag: `post-2026-04-23-feat-v1-expanded`
* Reference PRD path: 本文件
* Log path: `docs/20260420-ralph_loop_log.md`（appendable，沿用现有 log）
* Per-round 11-part 中文报告写入 log

### 15.3 Halt 条件（§11.8 style，优先级从高到低）

Loop 必须在以下情况**立刻停止**：

1. `pytest` 断路（> 5 tests regress）
2. `core/` 模块 import 失败
3. 磁盘可用 < 10GB
4. 非授权 config 改动（`config/production_strategy.yaml` / `config/universe.yaml` / `PRODUCTION_FACTORS`）
5. Archive 数据库损坏（SQLite integrity check fail）
6. 同一 loop 内 `--force` promote 尝试出现 3 次
7. **新增**：Step 3 R39 fresh mining 跑完后，若 `n_oos_pass == 0` AND
   所有 trial 的 OOS IR 均 < 0（严格劣于 pre-PRD 旧结果），halt 并写入
   blocker 文档，等用户确认是否进 Step 5 或重新设计

### 15.4 Autonomous 决策边界

本 PRD 授权 loop 内部**自主**执行：

* 新建 `base_returns.py` / `base_volatility.py` / `base_relative.py` + 测试
* 扩展 `compute_forward_returns(mode=...)` + 兼容旧签名
* 将 10 新 factors 添加到 `RESEARCH_FACTORS`
* 新建 mask helper + 单测
* 跑 R39 mining / acceptance pack / DSL ablation
* 从现有 97 LLM candidates 挑选 3-6 跑 funnel
* 每轮 commit + 11-part 中文报告

本 PRD **禁止** loop 自主执行（触发 halt + 用户确认）：

* 修改 `PRODUCTION_FACTORS`
* 修改 `config/production_strategy.yaml`
* 修改 `config/universe.yaml`（Stage 3 追加、删除现有符号）
* Auto-promote via `scripts/promote_strategy.py`
* 新增 data source / pipeline
* Transformer 主线 sweep（只允许 very small confirmation 放到 Step 5 末尾）

### 15.5 Per-round 交付

每轮结束时产出：

1. Git commit（改动 + 可验证 artifact）
2. `docs/20260420-ralph_loop_log.md` 追加"R-feat-v1-round-NN"章节，11-part 中文格式：
   1. 本轮主题 / Step
   2. 本轮目标
   3. 为什么这轮优先做它
   4. 做了什么
   5. 修改了哪些文件
   6. 跑了哪些测试/实验
   7. 结果如何
   8. 当前发现的新问题/新机会
   9. 剩余风险
   10. 下一轮建议方向
   11. Halt 条件检查（§15.3）
3. 可选：`scripts/send_round_summary.py` 微信通知（若配好 webhook）

### 15.6 最终产出（15 round 结束或提前 halt 时）

* Final summary 文档：`docs/YYYYMMDD-feat_v1_expanded_final_report.md`
* 所有新 features + labels + masks 落盘 `RESEARCH_FACTORS`
* 至少一次 R39 fresh mining 结果入 archive (`post-2026-04-23-feat-v1-expanded` lineage)
* 若产出可 promote candidate：**不自动 promote**，在 final report 里列举等用户决策
* 若无 promote candidate：按 §10.3 判断研究价值是否达成

---

*PRD v1.0 final. 等用户运行 `bash scripts/start_feature_and_mining_loop.sh` 启动 loop。*
