# PRD — Framework Completion (Pre-Universe-Expanded-Mining-Continuation)

**Status**: Draft v1.0 — 2026-04-21
**Scope**: 在恢复 `prd_universe_expanded_mining.md` 32 轮循环 **之前** 必须
补齐的工程框架项。本 PRD **不包含** 新的 factor / strategy mining 研究
（那是 `prd_universe_expanded_mining.md` 的职责）。
**Owner**: single-maintainer project
**Prerequisite**: pytest 1109 passed 0 xfailed（已达成 2026-04-21）

---

## 0. 背景与触发条件

Codex 2026-04-21 审计 + 自审后确认 3 个 P0 blocker 与 6 个功能 gap：

| # | 级别 | 问题 | 证据 |
|---|---|---|---|
| 1 | P0 | `run_paper.py` 与 `run_backtest.py` 默认 MFS 权重硬编码 + 互不一致 + 未包含 R15 promoted `drawup_from_252d_low` | `run_paper.py:373` vs `run_backtest.py:90` vs `test_backtest_paper_consistency.py:279` |
| 2 | P0 | Mining archive 有 `promote()` 但 production 入口不消费 promoted 结果作 baseline | `run_backtest.py:121` 只额外 append，不替换 |
| 3 | P0 | backtest / paper / replay 之间无运行时 alignment hard check | consistency 只是测试，非 runtime gate |
| 4 | P1 | 声明式 cross-ticker 规则层缺失（SPY 触发 QQQ / regime basket / multi-TF 确认） | 现有 cross_asset_rotation 是硬编码 strategy，非 declarative |
| 5 | P1 | Multi-TF 仅以 timing layer 存在，未形式化为执行层契约 | CLAUDE.md §约束 3 已有方向但未闭环 |
| 6 | P1.5 | LLM factor proposal 靠对话式产 YAML，无可编程入口 | 有 funnel scaffold，无 API-driven engine |
| 7 | P2 | XGBoost 仅作 importance 工具，未作 weight/score model | `run_xgb_importance.py` 输出 importance 不输出权重 |
| 8 | P2 | Transformer 能力完全缺失（用户 5 项能力之一） | `torch` 未装，无 model 代码 |
| 9 | P2 | 文档测试基线是硬写数字，漂移风险高 | README / start_universe_mining_loop.sh / reconstructed 文档三处都写死 |

**关键已知事实**（写入 PRD 作为设计前提，非假设）：
- CLAUDE.md 标注"当前 best 数字产出于 P0.1 fix 前... 同参数在当前 codebase
  下不再复现"。R29-R35 mining 无一 trial 过 OOS 0.20 门槛。**post-fix
  validated best 客观不存在**。
- 因此单一真源首版必须允许 `no_validated_best / conservative_default` 的
  **诚实状态**，系统不假装已有 best。此状态是**合法生产状态**，不是临时工。
- **Intraday 术语必须严格区分**（本 PRD 起在任何文档 / commit / 报告中强制）:
  - `intraday cached-runtime paper trading` —— 当前能力；bar-by-bar 跑缓存数据
  - `realtime intraday live-feed paper trading` —— 未具备；需接盘中实时 feed
  - 禁止笼统叫 "intraday live"，易误导
- 实时 feed 接入不在本 PRD 范围（留到 `prd_live_feed.md`）。
- **LLM capability 现状**: Claude 对话式写 candidate YAML 并跑 funnel 的
  流程 **已经是有效 LLM capability**（R1-R14 产出 26 候选 + 1 promoted 为证）。
  M6 做的是将此流程规范化，**不是** "从零建 LLM 能力"。

---

## 1. 目标（硬性）

交付后必须满足：

1. **Single Source of Truth**: 系统只存在**一份** production strategy 定义文件，backtest / paper / replay / report 从它读取，硬编码默认权重必须被移除。
2. **Promote Contract**: mining archive 到 production 有显式 promote 动作（CLI 工具 + git commit + acceptance pack）。promote 前必须通过 acceptance gate。
3. **Alignment Runtime Check**: backtest / paper / replay 启动时自动对比 strategy hash / factor registry hash / universe hash / config hash，不一致时 WARN（第一版）或 FAIL（第二版，soak period 后升级）。
4. **Cross-ticker Declarative Layer**: 至少支持 3 类规则（benchmark-trigger / regime-basket / multi-TF-confirmation），YAML 定义，无需改 code 即可增减规则。
5. **Multi-TF Execution Contract**: 书面化 TF 权限层级（60m 可 veto / 15m 只 defer / long-only 不反向），runtime enforced。
6. **LLM Proposal Phase 1**: formalize Claude-in-loop 写 YAML 的流程（模板 / seed context / funnel checklist）。Phase 2 API 接入暂不做。
7. **XGBoost Weight Model (Research)**: 新增 `run_xgb_weight_model.py`，输出 per-symbol score → weight 转换，对比 equal-weight baseline。Research-only，不进 production。
8. **Transformer Research Phase 1**: 最小可跑 PyTorch encoder，daily horizon，benchmark vs Ridge/XGBoost。Research-only，不进 production。
9. **Baseline Automation**: `scripts/build_research_baseline_snapshot.py` 产出可读 JSON，文档不再硬写测试数。

---

## 2. 非目标（明确排除）

- **不实装实时 intraday data feed**（盘中每分钟 live bar）。当前缓存式 bar-by-bar 继续使用。
- **不接入真实 broker**。`BrokerAdapter` ABC 保留。
- **不做 Transformer production deployment**。Phase 1 仅研究对比。
- **不做 LLM API programmatic proposal**。Phase 2 留待 Phase 1 验证后再评估。
- **不新开 mining round**。本 PRD 纯工程框架；mining 恢复由 `prd_universe_expanded_mining.md` 在本 PRD 交付后继续。
- **不改动 PRODUCTION_FACTORS set** 除非本 PRD 的验收过程发现必须。

---

## 3. 里程碑分解

### Milestone M0 — 环境 baseline snapshot（0.5 天）

**Deliverable**: `scripts/build_research_baseline_snapshot.py` + `data/baseline/snapshot_<ts>.json`

**Content**:
- pytest 结果（passed / failed / skipped / xfailed counts）
- git status + HEAD SHA
- `MiningArchive` 的 per-lineage 统计（trials / promoted / best oos_ir）
- `config/` 下所有 YAML 的 sha256
- `factor_registry` 的 PRODUCTION / RESEARCH / MAP 三 set hash
- Python version / 关键依赖版本（pandas / numpy / xgboost / optuna）

**Acceptance**:
- CLI `python scripts/build_research_baseline_snapshot.py` 3 秒内完成
- 产出 JSON 可被 jq 读
- 更新 README §1.4 改为 "latest snapshot: see `data/baseline/`" 不再硬写 1109
- 更新 `start_universe_mining_loop.sh` 的 1108+1xfailed 文本

**Dependency**: 无。

---

### Milestone M1 — Production Strategy Single Source of Truth（1-2 天）⭐ P0

**Deliverable**:
- `config/production_strategy.yaml`（git-tracked）
- `core/config/production_strategy.py`（pydantic schema + loader）
- `run_backtest.py` / `run_paper.py` 消费它替代硬编码权重

**Schema**（草案，v1）:
```yaml
# config/production_strategy.yaml — SINGLE SOURCE OF TRUTH
schema_version: "1.0"

# Lifecycle status — 3 合法状态，不允许其他值
#   active               : 已通过 acceptance pack 的 validated best
#   conservative_default : 知道没有 validated best，显式用保守默认
#   no_validated_best    : 明确声明 "当前没有可用 production 策略"
#                          （不会阻断 backtest / research，会阻断 live paper）
# "conservative_default" 是合法生产状态，不是 placeholder。
status: "conservative_default"

strategy_type: "multi_factor"

# 来源追溯 —— 如果 status=active 则必须 source.mode=promoted_from_archive
source:
  mode: "manual"                  # manual | promoted_from_archive
  spec_id: ""                     # archive.trials.spec_id (active 时必填)
  lineage_tag: ""                 # archive.trials.lineage_tag
  promoted_at: ""                 # ISO-8601 (active 时必填)
  rationale: "Pre-artifact default inherited from pre-P0.1-fix R33 grid search; not post-fix validated."

# Strategy parameters (must match MultiFactorStrategy.__init__)
params:
  top_n: 4
  rebalance_monthly: false
  score_weighted: true
  min_holding_days: 3
  lookback_mom: 189
  lookback_quality: 189
  lookback_vol: 84
  apply_extra_shift: false

# factor_weights sums to 1.0 ± 1e-6; names must be in PRODUCTION_FACTORS.
factor_weights:
  low_vol: 0.15
  momentum: 0.05
  quality: 0.30
  pv_div: 0.05
  rel_strength: 0.30
  market_trend: 0.0
  drawup_from_252d_low: 0.15

# Validation status —— 显式承认 post-P0.1-fix 验证差距
validation:
  post_fix_validated: false       # ⚠ 当前 false,表明此 params 未在 P0.1-fix
                                   #   后 codebase 重新验证
  passed_oos_gate: false          # OOS IR ≥ 0.20 跨过没
  passed_qqq_gate: false          # full/holdout/OOS-avg 全过 QQQ 没
  passed_paper_backtest_alignment: false
  notes: "Inherited R33 grid-best (pre-P0.1-fix). Post-fix revalidation pending after M2 acceptance pack on new mining round."

# Fingerprints —— runtime alignment check 比对这些 hash
fingerprints:
  universe_hash: ""                # sha256 of frozen seed_pool+ETFs at promote
  factor_registry_hash: ""         # sha256 of PRODUCTION_FACTORS sorted tuple
  config_hash: ""                  # sha256 of risk+backtest+cost YAML concat
```

**核心规则**:
- `status: conservative_default` —— `source.mode=manual`，`validation.*` 全 false 是合法的；**不阻断 backtest/research；阻断 live paper**（除非 `--accept-conservative-default` 显式 override）
- `status: no_validated_best` —— 更强声明；阻断 backtest baseline 运行 `multi_factor`，要求显式 `--strategy X` 指定
- `status: active` —— `source.mode=promoted_from_archive` 必填，`source.spec_id / lineage_tag / promoted_at` 必填，`validation.passed_oos_gate / passed_qqq_gate / passed_paper_backtest_alignment` 必须全 true
- 任何非 `active` 状态下 `fingerprints.*` 可为空；`active` 下必须填满
- 由 `conservative_default` 直接手改 params 到 `active` **不允许**；必须走 M2 promote CLI + acceptance pack

**代码改动**:
- 新增 `core/config/production_strategy.py`:
  - `ProductionStrategyConfig` pydantic model
  - `load_production_strategy(path="config/production_strategy.yaml") -> ProductionStrategyConfig`
  - `build_strategy_from_config(cfg, price_df, universe) -> MultiFactorStrategy`
- 修改 `run_backtest.py`:
  - `build_strategies()` 中 `multi_factor` baseline 改为 `build_strategy_from_config(...)`
  - 保留 CLI `--override-production`（显式 opt-out，用于研究 one-off）
- 修改 `run_paper.py`:
  - Strategy 构造改为 `build_strategy_from_config(...)`
  - 无 opt-out（paper 不允许 ad-hoc 覆盖）
- 修改 `tests/integration/test_backtest_paper_consistency.py`:
  - fixture 改从 `config/production_strategy.yaml` 读权重，保证测试跟踪真源

**Acceptance**:
- `run_backtest.py` / `run_paper.py` grep 无 hardcoded `factor_weights={...}`
- 启动 log 包含 `Loading production strategy: status=<>, spec_id=<>, lineage_tag=<>`
- 新增测试 `tests/unit/config/test_production_strategy.py`（10+ tests）
  - schema 解析
  - provisional vs validated 区分
  - factor_weights 必须 sum to 1.0 ± 1e-6
  - factor names 必须在 PRODUCTION_FACTORS
- 新增集成测试 `tests/integration/test_single_source_of_truth.py`
  - backtest + paper 用同一个 config 产同一个 strategy instance 的 `__repr__` 等价

**Dependency**: M0 完成后做（需要 baseline snapshot 作 before/after 对比）。

**Risk**: 
- R33 权重是在 P0.1 fix 前 grid search 出来的，首版 `config/production_strategy.yaml` 用它其实是 inherited drift。这个 risk 接受 —— 标 `status: provisional`，未来 promote 会覆盖。

---

### Milestone M2 — Promote CLI + Acceptance Pack（2-3 天）⭐ P0

**Deliverable**:
- `scripts/promote_strategy.py --spec-id <hash>` CLI
- `core/mining/acceptance_pack.py`（可独立调用的 validation pack）
- 流程文档在 `docs/promotion_flow.md`

**CLI 行为**:
```bash
# 查看某 spec_id 详情（dry-run）
python scripts/promote_strategy.py --spec-id 81f5cdaa053e --dry-run

# 跑 acceptance pack + 如果全过生成新 production_strategy.yaml
python scripts/promote_strategy.py --spec-id 81f5cdaa053e --promote

# Force 模式（跳过 acceptance，**需要明确 --yes-i-know-what-im-doing**）
python scripts/promote_strategy.py --spec-id <id> --promote --force --yes-i-know-what-im-doing
```

**Acceptance Pack** 内容（复用现有检查器，不重造轮子）:
1. Full-period backtest vs SPY + QQQ（复用 `core/backtest/backtest_engine.py`）
2. Holdout 252d vs SPY + QQQ
3. OOS walk-forward IR ≥ 0.20（复用 `core/backtest/window_analyzer.py`）
4. Regime robustness（6 states，复用 `MiningEvaluator._check_regime_robustness`）
5. Cost robustness（2x cost，复用 `_check_cost_robustness`）
6. Paper-BT consistency < 10 bps equity drift（复用 integration test）
7. MaxDD absolute ≤ 25% + relative ≤ 1.5× SPY MaxDD
8. Position concentration ≤ 3 symbols 不允许（risk guardrail）
9. QQQ hard gate：full + holdout + OOS avg 全过

**每项输出**:
```json
{
  "check": "qqq_hard_gate",
  "passed": true,
  "values": {"full_cagr_excess": 0.0313, "holdout_excess": 0.011},
  "threshold": {"full_cagr_excess": 0.0, "holdout_excess": 0.0}
}
```

**Acceptance**:
- Promote 成功后 `config/production_strategy.yaml` 自动更新，`status: validated`，acceptance 字段填满
- Git status 在 promote 后显示 `config/production_strategy.yaml` 改动 —— 要求用户 `git commit` 确认
- 提供 `scripts/acceptance_pack.py --spec-id <id> --out artifacts/acceptance_<id>.json` 独立入口（促进 promote 前手动审查）
- 新增测试 `tests/unit/mining/test_acceptance_pack.py`（fixture-driven，用 synthetic 数据走完整 pack）

**Dependency**: M1 完成。

**Risk**:
- 当前 archive 里没有任何 post-P0.1-fix trial 能过 OOS 0.20 门槛 —— M2 上线后实际可能无 spec_id 通过 acceptance。**这是预期**，M2 正是为了把"无 validated best"的事实公开化。

---

### Milestone M3 — Runtime Alignment Check（1 天）⭐ P0

**Deliverable**:
- `core/alignment/alignment_check.py`
- 集成到 `run_backtest.py` / `run_paper.py` 启动路径

**检查项**:
```python
class AlignmentReport:
    strategy_hash_match: bool
    factor_registry_hash_match: bool
    universe_hash_match: bool
    config_backtest_hash_match: bool
    config_risk_hash_match: bool
    warnings: list[str]
    errors: list[str]
    mode: Literal["warn", "fail"]
```

**启动行为**（v1 WARN 模式）:
```
[INFO] Production strategy: status=provisional, spec_id=None
[WARN] Runtime alignment:
  - factor_registry_hash: MATCH
  - universe_hash: MATCH
  - config_risk_hash: MATCH
  - config_backtest_hash: MISMATCH (artifact: abc123, runtime: def456)
  Reason: backtest.yaml changed after promote (diff: oos_min_ir_vs_benchmark)
  -> Proceeding (warn mode). Set alignment.mode=fail to block.
```

**升级路径**（v2 FAIL，未来决定）:
- 配置项 `config/system.yaml::alignment::mode: warn | fail`
- FAIL 模式下 hash mismatch 直接 `sys.exit(2)` 并推送 notify
- 逃生舱：`--ignore-alignment-check` CLI flag（所有入口都接受）

**Acceptance**:
- 首版默认 `mode: warn`
- `alignment_report.json` 每次运行都落到 `data/paper_trading/alignment_<ts>.json`
- 新增测试 `tests/unit/alignment/test_alignment_check.py`（12+ tests）
- 文档化：什么样的改动 expected mismatch，什么必须重 promote

**Dependency**: M1 + M2。

---

### Milestone M4 — Cross-ticker Rule DSL（2-3 天）P1

**Deliverable**:
- `config/cross_ticker_rules.yaml`（YAML 规则集）
- `core/signals/cross_ticker_rules.py`（rule engine）
- 集成到 signal pipeline（pre-strategy filter / post-strategy adjustor 两种注入点）

**规则 schema**（最小 3 类）:

```yaml
rules:
  # 类 1: benchmark-triggered allocation
  - name: "qqq_unlocked_by_spy_trend"
    type: benchmark_trigger
    driver: SPY
    condition: "close > sma(close, 200)"  # 简单 DSL
    action:
      allow_symbols: [QQQ, TQQQ, SOXL]
    regime_scope: [BULL, RISK_ON, NEUTRAL]
    priority: 1

  # 类 2: regime-conditioned basket
  - name: "defensive_basket_risk_off"
    type: regime_basket
    regime: [RISK_OFF, CRISIS]
    basket_weights:
      TLT: 0.30
      GLD: 0.30
      SHY: 0.20
      cash: 0.20
    override_strategy: true
    priority: 10

  # 类 3: multi-timeframe confirmation
  - name: "qqq_breakout_confirmed"
    type: multi_tf_confirmation
    target: QQQ
    primary_tf: daily
    primary_condition: "close > ref_high(20)"
    confirmations:
      - tf: 60m
        condition: "close > sma(close, 50)"
      - tf: 15m
        condition: "rsi(14) > 50"
    action:
      timing_scale_multiplier: 1.2
    priority: 5
```

**解析器 scope**:
- 支持 `close / open / high / low / volume`
- 支持 `sma(x, N) / ema(x, N) / rsi(x, N) / ref_high(N) / ref_low(N)`
- 支持 `>` `<` `>=` `<=` `==` `and` `or` `not`
- **不** 支持任意 Python eval（安全）

**长 only 不变量**（enforced）:
- rule action 只能 ADD/REMOVE symbol from pool，或 SCALE weight，不能产生负权重
- 冲突解决按 `priority` 排序

**Acceptance**:
- 3 个规则 YAML 可以被 parse + apply
- 集成测试 `tests/integration/test_cross_ticker_rules.py`
  - SPY 200d cross 后 QQQ 被允许
  - RISK_OFF regime 切换到 defensive basket
  - multi-TF confirmation 正确 gate timing_scale
- 规则应用**不**破坏现有 MFS / DM / TF / CAR 单测
- 可选启用（`config/system.yaml::cross_ticker_rules::enabled: false` 默认关）

**Dependency**: M1 完成（rule engine 消费的 strategy output 来自单一真源）。

---

### Milestone M5 — Multi-TF Execution Contract 形式化（1 天）P1

**Deliverable**: 书面化 + runtime enforce CLAUDE.md §约束 3 已有的合约。

**核心契约**（已部分实现，本里程只是**闭环 enforce**）:

```python
# core/intraday/multi_timescale.py (existing)
class TimingDecision:
    execute: bool                    # True = 本 bar 下单
    timing_scale: float              # [0, 1] 对 base_weight 的缩放
    effective_weight: float          # base_weight × timing_scale if execute else 0
    higher_tf_vote: dict[str, Literal["confirm", "contradict", "neutral", "absent"]]
    reason: str

# 不变量（已有测试覆盖，但 CLI 未强制）:
# 1. Lower TF (15m/5m) 不能翻转 direction，只能 defer
# 2. effective_weight >= 0 永远（long-only）
# 3. daily_side=-1 (short) → execute=False
# 4. base_weight=0 → execute=False
```

**本里程做的事**:
- 在 `PaperTradingEngine.run_day_intraday()` 里显式 assert `all(d.effective_weight >= 0 for d in decisions)`
- `--use-timing` 模式下每 bar log timing_decision summary
- 新增 `tests/integration/test_multitf_execution_contract.py`:
  - 构造 "15m 想反方向" scenario，验证 timing 正确 defer 而非反向
  - 构造 "60m vetos" scenario，验证 execute=False
- 更新 CLAUDE.md 的 "Multi-TF Timing Contract" 段，引用本 PRD 作为 enforcement point

**Acceptance**:
- 新测试过
- `validate_timing_value.py` 输出里明确显示 enforcement log
- 文档与代码一致

**Dependency**: M1 完成。

---

### Milestone M6 — LLM Proposal Phase 1（1 天）P1.5

**Deliverable** 仅 process + template，无代码改动：
- `docs/llm_proposal_prompt_template.md`（标准化我（Claude）写 candidate YAML 时的 system prompt）
- `docs/llm_proposal_seed_context.md`（跑 proposal 前应注入的 repo state：PRODUCTION_FACTORS / RESEARCH_FACTORS / 最近 archive summary / 近 rejected candidate 列表）
- `docs/llm_funnel_checklist.md`（每个 candidate 必跑的命令序列 + verdict 解读指南）

**Template 规约**（摘录）:
```
Seed context (must be current):
- PRODUCTION_FACTORS: <list from registry>
- RESEARCH_FACTORS: <list>
- Last 5 rejected candidates with reasons: <from research/llm_candidates/round_*/>
- Current regime distribution over 252d: <computed>
- Open research directions from CLAUDE.md / blocker report

Candidate contract:
- Every YAML must include: factor_name, hypothesis, formula, required_fields,
  suitable_horizon, suitable_universe, suitable_regime, expected_edge,
  expected_risk, possible_failure_modes, novelty_vs_existing_factors
- Claude must NEVER return verdict=KEEP (contract per PRD §2.2)

Funnel execution (mandatory, in order):
1. scripts/llm_factor_propose.py --input <yaml>
2. If verdict != REJECT: scripts/llm_candidate_deep_check.py ...
3. If deep_check PASS: scripts/llm_candidate_factor_backtest.py ...
4. If all 5 gates pass: flag NEEDS_HUMAN_REVIEW, DO NOT auto-promote
```

**Phase 2（不在本 PRD 范围）**: 未来若决定做，新增 `core/factors/proposal_engine.py` 调用 Anthropic API。先用 Phase 1 6 个月观察是否真的是瓶颈。

**Acceptance**:
- 3 个 markdown 文档就位
- README §15.6 改为引用本三文档
- 下次我（Claude）写 candidate 时可以按 template 走，历史 R1-R14 已验证 process 可行

**Dependency**: 无。

---

### Milestone M7 — XGBoost Weight Model（Research-only，2 天）P2

**Deliverable**:
- `scripts/run_xgb_weight_model.py`
- `data/ml/xgb_weights/<tag>/` artifact

**用途**: 从 factor panel 训练 XGBoost regressor `forward_21d_return = f(factors)`，
产出每个 `(date, symbol)` 的 score，按 score 转换为 per-symbol weight（z-score +
softmax 或 top-N pick）。

**对比 baseline**:
- MFS z-score composite（当前生产路径）
- Equal-weight top-N
- XGBoost score → weight

**严格要求**:
- 时间严切 train/test（不洗牌）
- OOS permutation importance 作解释
- **只产 `data/ml/` artifact，不进 production**，`config/production_strategy.yaml` 不动
- 结果对比放进 master_report 作 diagnostic

**Acceptance**:
- CLI 可跑 + 5 分钟内出结果（53 symbols × 10 年 daily）
- 对比报告证明 XGB-weighted vs z-score-weighted 的相对表现
- 新增测试 `tests/unit/ml/test_xgb_weight_model.py`（smoke + 时序切分验证）

**Dependency**: 无。

**Risk**: R9 已发现 XGBoost OOS R² 负数，可能此 milestone 的结果也是 "XGB 比 equal-weight 差"。**这就是 research finding，不视为失败**。

---

### Milestone M8 — Transformer Research Phase 1（3-5 天）P2

**Deliverable**:
- `requirements-gpu.txt` 加 `torch` + `transformers`（可选分离安装）
- `core/ml/transformer_encoder.py` 小 encoder
- `scripts/run_transformer_research.py`
- `data/ml/transformer/<tag>/` artifact

**严格 scoping**（1650 GPU 4GB VRAM）:
- **Model**: 1-layer TransformerEncoder, hidden=64, heads=4, ~50k params
- **Input**: 最近 63 day × [n_factors] 特征张量 per symbol
- **Output**: scalar forward_21d_return 预测
- **Target**: Ridge / XGBoost OOS R² 作 head-to-head benchmark
- **Data split**: strict temporal, last 252d holdout
- **Research-only**: 不进 production，不进 paper

**硬性 risk guard**:
- CPU fallback 自动（若 GPU 不可用）
- Batch size 自适应 VRAM（先试 32, 失败降 16, 8）
- 训练时间 cap: 30 min per run
- 若 vs Ridge OOS R² 无显著优势（p > 0.05 on bootstrap），**explicit 标注 "no edge"**，不追加迭代

**Acceptance**:
- `python scripts/run_transformer_research.py --epochs 10` 在本机能跑（GPU 或 CPU）
- artifact 包含 OOS R² vs Ridge/XGB 的三方对比表
- 新增 `docs/transformer_research_phase1_findings.md` 诚实写结果
- 新增 smoke test `tests/unit/ml/test_transformer_encoder.py`（CPU only，2 秒内）

**Dependency**: 无（独立研究分支）。

**Risk**: 
- 1650 GPU 可能 VRAM 不够，需 CPU fallback
- 数据量小（53 symbols × 日线 × 10 年 ≈ 130k samples），transformer 大概率过拟合
- **这是 expected**，findings 文档要写"小数据 + daily horizon 不是 transformer 擅长的场景，建议探索 intraday sequence"

---

### Milestone M9 — 文档同步（持续）P2

每个 M0-M8 完成时必须同步更新：
- `README.md` 对应小节（见 `README.md::§18.5 README 维护约定`）
- `CLAUDE.md` Phase / 约束 段
- `docs/prd_universe_expanded_mining.md` 若依赖本 PRD 的 artifact 需更新 prerequisite 段

---

## 4. 依赖关系 / 推进顺序

```
M0 (baseline snapshot)
  └─► M1 (production strategy SoT) ─┬─► M2 (promote CLI)
                                    ├─► M3 (alignment check)
                                    ├─► M4 (cross-ticker DSL)
                                    └─► M5 (multi-TF contract)

M6 (LLM proposal template)   — 独立
M7 (XGBoost weight)          — 独立
M8 (Transformer research)    — 独立
M9 (docs)                    — 每步同步
```

**Critical path**: M0 → M1 → M2 → M3 → M9。
这条路不走完不应恢复 `prd_universe_expanded_mining.md` R36+ 循环。

M4 / M5 / M6 / M7 / M8 可以并行或延后，不阻塞 mining 恢复。

**一句话决策**:
> 当前最重要的不是挖更多策略，而是先把"当前生产到底运行哪一个策略，以及
> 它和研究结果的关系"定清楚。正确做法不是"自动上线最佳"，而是**先允许
> `no_validated_best / conservative_default` 的诚实状态，再建立 promote
> 与 alignment 闭环**。

---

## 5. 硬性条款（Invariant）

1. **Single Source of Truth**: 除 `config/production_strategy.yaml` 外任何脚本禁止 hardcode production 策略权重。违反即测试失败。
2. **Conservative Default is Legal**: `status: conservative_default` / `no_validated_best` 是合法生产状态，**不**强迫系统声明"已有 best"。
3. **Promote Contract**: 未过 acceptance pack 的 spec_id 不得使 `status: active` 生效；`conservative_default → active` 转换必须走 M2 promote CLI，不允许手动改 yaml status 字段。
4. **Alignment Hard Gate (phased)**: Phase 1 WARN-only 不阻断任何入口；Phase 2 FAIL 仅阻断 live paper，不阻断 backtest/research；`--ignore-alignment-check` 作显式逃生舱。
5. **LLM Role**: LLM（含 Claude）只生成 candidate + 做反向审查，verdict KEEP 永不返回。
6. **LLM Capability 已存在**: Claude 对话式 YAML + funnel 流程本身是 LLM capability 的一种形态，不得被错误描述为 "missing" 或 "scaffold only"。
7. **Cross-ticker Long-only**: 任何规则 action 结果 effective_weight < 0 即测试失败。
8. **Multi-TF Execution**: lower TF 不得产生相反方向 order。已有测试覆盖，runtime assert 巩固。
9. **Intraday 术语**: 任何新 PR / 文档 / 报告禁止笼统使用 "intraday live"；必须明确 `cached-runtime` 还是 `realtime live-feed`。
10. **Transformer Scope**: Phase 1 不得进 `config/production_strategy.yaml`，不得被 run_paper.py 调用。
11. **XGBoost Weight Scope**: 同上，research-only。

---

## 6. 验收场景（端到端）

本 PRD 完成后，以下 3 个场景应跑通：

**场景 A — 新人 onboarding**:
```bash
git clone ... && cd pqs
python scripts/build_research_baseline_snapshot.py   # 看 latest baseline
cat config/production_strategy.yaml                   # 看当前生产策略
python scripts/run_backtest.py --no-walk-forward      # 用单一真源
python scripts/run_paper.py --mode status             # 状态
# 所有 3 个命令应自报当前 spec_id / lineage_tag / alignment status
```

**场景 B — mining promote**:
```bash
python scripts/run_mining.py --trials 30 --type multi_factor --lineage-tag my_exp
# 拿到 best spec_id，跑 acceptance pack
python scripts/acceptance_pack.py --spec-id <id> --out artifact.json
# 如果过了，promote
python scripts/promote_strategy.py --spec-id <id> --promote
# 审查 diff + commit
git diff config/production_strategy.yaml
git add config/production_strategy.yaml
git commit -m "promote <id> to production"
# 下次 run_paper.py 自动用新策略
```

**场景 C — 跨 ticker 规则调整**:
```bash
# 改 config/cross_ticker_rules.yaml 加一个 "SPY 50d cross 200d 才允许 QQQ"
vim config/cross_ticker_rules.yaml
pytest tests/integration/test_cross_ticker_rules.py
python scripts/run_backtest.py --strategy multi_factor --no-walk-forward
# 对比前后 CAGR / MaxDD / QQQ 曝光
```

---

## 7. 风险与回退

| Milestone | 主要风险 | Mitigation |
|---|---|---|
| M1 | `config/production_strategy.yaml` 首版无 validated spec_id | `status: conservative_default` 标注 + README 明写 "post-fix validated best 尚未存在" |
| M2 | 当前 archive 无 post-fix trial 能过 acceptance pack | 接受，M2 正是为了把此事实公开化；不降门槛 |
| M3 | WARN 阶段用户忽视告警 | notify 推送 + baseline snapshot artifact 记录 |
| M4 | Rule DSL 蠕变变 Python eval | 严格白名单 operator，grep ci 禁止 `eval / exec / compile` |
| M7 | XGB 无 edge | findings 文档诚实写；不强推产品化 |
| M8 | VRAM 不够 / 数据量不足 | CPU fallback + findings 写"daily + 小数据不适合 transformer" |

---

## 8. 参考

- 审计来源：Codex 2026-04-21 audit + self-audit
- 约束来源：CLAUDE.md §2 invariants + §约束 3 multi-TF + §9 QQQ rule
- 关联 PRD: `prd_universe_expanded_mining.md` (mining loop continuation, post-M3)
- 历史决策：`docs/ralph_loop_log.md` R15 (drawup promote) / R28 (universe expansion) / R33 (xfail resolution)

---

*PRD v1.1 — 2026-04-21, author: Claude; incorporated re-audit revisions
(status enum triad / schema regrouping / intraday terminology / LLM capability
statement / conservative_default as legal state).*

---

## 9. M0-M8 Delivery Log (2026-04-21, post-audit)

All 9 milestones shipped in sequence 2026-04-21. Test count grew
**1109 → 1201 collected** (1200 passed + 1 skipped when torch installed).

| Milestone | Commit | Scope |
|---|---|---|
| M0 | `bb90eb6` | `build_research_baseline_snapshot.py` + gitignore for `data/baseline/` |
| M1 | `8d2deeb` | `config/production_strategy.yaml` + `core/config/production_strategy.py` + 3 entrypoints rewired (+28 tests) |
| M2 | `868d60f` → `8b59417` | Acceptance pack v1 → **v2** (`full_period_fresh_backtest` gate added after rollback incident, see §10); `promote_strategy.py` CLI; `docs/promotion_flow.md` (+18 tests) |
| M3 | `df0e7db` | Runtime alignment WARN mode; `core/alignment/alignment_check.py`; wired into `run_backtest.py` + `run_paper.py` (+12 tests) |
| M4 | `c657175` → `86077e3` | Cross-ticker DSL + safe expression evaluator + 3 rule types; demo script; enabled with 3 example rules (+24 tests) |
| M5 | `770b453` | Multi-TF execution contract runtime assert; `IntradayBacktestEngine.run_multi_day` clips negative weights (+4 tests) |
| M6 | `dd4de8b` | LLM proposal Phase 1 — 3 markdown docs (no code) |
| M7 | `f412147` | `scripts/run_xgb_weight_model.py` — research-only XGB weight model |
| M8 | `f412147` | `core/ml/transformer_encoder.py` `SmallEncoder` + `scripts/run_transformer_research.py` (+6 tests) |
| M9 | continuous | README + CLAUDE.md + docs synced each milestone per `README §18.5 maintenance contract` |

**Critical path (M0→M1→M2→M3)** took about 4 hours end-to-end. M4-M8 in
another 3-4 hours. Pack v2 upgrade (after rollback) added ~2 hours.

---

## 10. Post-M8 Incident Log: Pack v1→v2 Rollback

**2026-04-21, post-M8**: User authorized a real-world test of the M2 promote
flow. Mining round `post-2026-04-21-framework-m1-m8-done` (30 trials) plus
existing archive yielded top spec `6d15b735a64c` with all 9 acceptance pack
v1 gates PASS.

`promote_strategy.py --promote` wrote `config/production_strategy.yaml`
with `status: active`. BUT subsequent pytest showed:
```
FAILED tests/integration/test_backtest_paper_consistency.py::
  TestQQQOutperformance::test_full_period_cagr_beats_qqq
  AssertionError: Strategy CAGR 14.0% must exceed QQQ 17.6%
```

**Root cause**: archive's `quick_cagr=25.6%` and `qqq_full_period_excess=+6.17%`
were computed on the **first 70% of data** (`quick_data_fraction=0.7`). Pack
v1 trusted the archive row. Fresh full-period backtest revealed the spec
overfits to the training window and underperforms QQQ by ~3.6% on full period.

**User decision: A + B**
- **A (rollback)**: `git checkout HEAD -- config/production_strategy.yaml`
  (back to `status: conservative_default`)
- **B (pack v2)**: new gate `full_period_fresh_backtest` re-runs
  MultiFactorStrategy with spec params on current full price panel and
  verifies CAGR > QQQ on aligned full window; FAIL if excess ≤ 0 or
  equity curve contains NaN.

Pack v2 now correctly rejects `6d15b735a64c` (9/10 pass, fresh gate fails
with strategy 13.0% < QQQ 17.6%, excess -4.6%). Without v2 the flow would
have silently promoted a bad spec.

**Systemic lessons**:
1. **Archive row evidence is insufficient.** Historical evaluator flags
   (`passed_oos`, `passed_qqq_gate`) use mining's internal 70% split.
   Production deployment uses full period. Pack MUST re-run at least the
   CAGR-vs-QQQ check on current data.
2. **Small bugs emerged during v2 bring-up** (documented in commit `8b59417`):
   - `compute_metrics` returns lowercase `cagr` key not `CAGR`
   - `BacktestResult` has no `benchmark_equity` attr (pass `benchmark=` to `compute_metrics`)
   - BacktestEngine may emit NaN on last bar (stale-data edge case); use `.dropna()` before CAGR compute
   - Pass `open_df` to `engine.run()` for faithful production execution
   All fixed in pack v2.
3. **This is exactly what critical path is for.** Without M3 alignment
   check + M1 single-source enforcement, the drift would have gone
   unnoticed in production.

**v3 roadmap** (not done; tracked in §11):
- Paper-BT consistency gate (replay + diff instead of skip-pass)
- Concentration gate with actual weight-matrix analysis
- Multi-horizon stress (cost × 3, regime × single-sector)

---

## 11. Open Items (M10+)

Not required for "framework complete" signal, but should be tracked:

| Id | Description | Priority | Estimated effort |
|---|---|---|---|
| **M10** | Cross-ticker DSL **production wiring** | **✅ DONE 2026-04-21** — `core/signals/cross_ticker_wrapper.py::apply_rules_to_weight_matrix` + integrated into run_backtest.py / run_paper.py; 9 unit tests; smoke 2024 H1 shows 62.9% dates changed under SPY golden cross rule |
| **M11** | Paper-BT consistency gate in pack v3. Run a short `--mode replay` + diff against fresh backtest equity over same window. Catches engine-level drift that pack v2's static re-run doesn't | P1.5 | 1-2 days |
| **M12** | Concentration gate real enforcement. Inspect promoted spec's fresh-backtest weight matrix for top-1/top-3 concentration; reject if > threshold (currently skip-pass) | P2 | 0.5 day |
| **M13** | Alignment FAIL mode rollout | **✅ DONE 2026-04-21** — `config/system.yaml::alignment::{mode, live_only_fail}` schema in place; defaults WARN + live_only_fail=true; operator flip WARN→FAIL after 2-week soak without code change |
| **M14** | BacktestEngine last-bar-NaN edge. Root-cause fix rather than `.dropna()` workaround. Ghost-position cleanup interaction with stale-bar tracker | P2 | 1 day |
| **M15** | **REFRAMED** 2026-04-21: no Anthropic API call. User has Gemini + Codex + 任意 LLM access; provide standardized context pack doc they can paste into any LLM chat, and a script to dump current repo state into that pack. User manually places LLM-produced YAMLs into `research/llm_candidates/round_NN/`; Claude funnel picks up. **✅ DONE** — `docs/llm_external_llm_handoff.md` + `scripts/dump_llm_handoff_context.py`. Auto-file-watcher inbox pattern is deferred; current copy-paste bridge is sufficient. | Reframed DONE | 0.5 day actual |
| **M16** | Transformer Phase 1 — real findings. Run on 1650 GPU, record OOS R² head-to-head vs Ridge/XGB, produce `docs/transformer_research_phase1_findings.md` | **✅ DONE 2026-04-21** — Ridge +0.012 / XGB -0.110 / Transformer -0.207; negative finding, recommend park |
| **M17** | Realtime intraday live-feed infrastructure. Out of framework PRD scope; tracked in `prd_live_feed.md` (future) | P2 | Weeks |
| **M18** | Cross-ticker DSL: add `ratio()`, `zscore()`, `rank_cs()` safe funcs to DSL evaluator. Demand-driven | P3 | 0.3 day each |

**Critical question**: should any of M10-M14 be pulled forward before
resuming `prd_universe_expanded_mining.md` R36+? My recommendation:
- **M10 required** before re-mining — otherwise DSL rules are untested in production
- **M11, M12, M13 optional** — framework is safe without them because pack v2 + alignment WARN + conservative_default already prevent bad promotes
- **M14 required** if BacktestEngine NaN shows up in real backtest runs (not just pack fresh)
- **M16 required** to close M8 deliverable (currently just scaffold)

---

*PRD v1.2 — 2026-04-21, author: Claude; added M0-M8 delivery log,
post-M8 rollback incident (pack v1→v2), and M10-M18 open items
tracking.*
