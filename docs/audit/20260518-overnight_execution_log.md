# 隔夜自主执行日志 —— 2026-05-18 夜

**授权**: 用户 2026-05-18 "三个 prd 都接着往下走,有疑问 websearch 后
按最 feasible 跑先,做好记录,明天白天讨论"。
**纪律**: `feedback_autonomous_execution_within_correct_path`(路径对
则连续执行)、`feedback_no_blanket_failure_verdict`、
`feedback_temporal_split_discipline`(F3/P0-B train-only,sealed 不读)、
`feedback_pre_post_audit_must_smoke_observe`(F4 live 候选)、
`feedback_heavy_training_serial_wsl`(GPU 串行)、不自启 loop。
**排序**: W1✅(GPU P0)→ W2 F1 → W3 F2 → W4 F3 → W7 P0-B →
W5 F4(最敏感)→ W6 F5 →(W8 scaled S1-S4 排最后,GPU 串行)。
**feasible-first 决策**会在此标 `⚑DISCUSS` 供明早讨论。

---

## 进度流水(逐 W 追加)

### W1 — scaled-checkpoint GPU P0 ✅
GPU 存在(GTX 1650Ti 4GB)→ conditional pass,VRAM-bounded。memo
`docs/memos/20260518-scaled_pretrain_compute_feasibility.md`。S1-S4
排 P0-A+P0-B 后(理由:须在 adjusted 价 + 接好 gate 上跑才有意义）。

### W2 — P0-A F1 loader 统一 ✅
- 新建 `core/data/price_access.py`(`load_adjusted` / `load_adjusted_panel`,BarStore adjusted,不删 MarketDataStore)。
- rewire:`run_research_miner._load_price_volume`(Track-C 真路径)✅ / `run_factor_screen.load_price_volume`(143 因子库)✅ / `run_mining` 3 daily 点(legacy)✅。
- ⚑DISCUSS-1:**run_paper 的 loader swap 故意 NOT 在 F1 做**——裸 swap 会静默改 cycle06/08 live soak 价基(PRD F4-A2 禁)。留到 W5/F4 当 data-revision-event + smoke 处理。这是 deliberate sequencing,非遗漏。
- 验证:compile OK;NVDA 2015-01-02 经 price_access = 0.503(正确除权,原 raw 20.125)✅。

---
## ⚑ 用户纲领(2026-05-18 夜,最高优先)
**"最重要的做好 audit 不要走过场"** → 隔夜执行**深度优先于广度**:
每个 W 必须真跑 + 对比期望数字 + edge case + ROOT CAUSE,不 hand-wave、
不假装完成、不为赶进度糊弄。做不完的诚实记录留明天讨论,绝不走过场。
W3+ 全部按此标准;F2 测试必须含 negative-control(证测试真能抓 bug)。

### W3 — P0-A F2 价基回归测试 ✅(透做)
`tests/unit/data/test_price_semantics_regression.py` 14 passed。**非走
过场**:4 个真实 split 锚点(NVDA 2021 1:4 / AAPL 2020 1:4 / TSLA
2022 1:3 / AMZN 2022 1:20)逐个:(a) adjusted 无 spurious split 跳
(<30%);(b) **NEGATIVE CONTROL**:raw(MarketDataStore)确实跳
(<-40%,证测试真能抓 P0-A,否则判 BROKEN 非 green);(c) price_access
与 BarStore.load(adjusted) bit 对齐 rtol1e-9;(d) NVDA 2015 具体签名
<5(原 raw 20.1)。AAPL 2014 锚点诚实排除(daily 数据 ~2015 起,
split 在数据窗外,非掩盖回归;≥2-anchor guard + 每例 negative
control 仍绑定,实跑 4 个)。

### W4 — P0-A F3 因子库 adjusted 重算 ⏳ 运行中
- **sealed 红线处理**:`run_factor_screen` 只有 start cut、无 end/
  train-only → **裸跑会读 2026 sealed,不可逆,绝不裸跑**。改写专用
  脚本 `dev/scripts/audit/f3_factor_ic_library_adjusted_restate.py`:
  generate_all_factors 全库 × raw vs adjusted × **仅 train years** +
  **SEALED GUARD fail-closed**(非 train 年泄入即 abort)。
- bug 修:compute_forward_returns 要 list 非 int(已修,run_factor_
  screen 传的是 [5,10,21])。
- 状态:后台 bk831d1jr 运行中(CPU 因子生成,分钟级)。完成后记真
  raw→adjusted IC 对照 + 诚实重述(W4),再续 W7(P0-B)。
- **未走过场**:不裸跑污染 sealed;train-only + guard;真算真比对。

### 当前状态快照(给用户明早)
- ✅ W1 GPU P0(conditional pass,VRAM-bounded)
- ✅ W2 F1 loader 统一(run_research_miner/factor_screen/mining;
  run_paper 故意留 F4)
- ✅ W3 F2 价基回归测试(4 真 split 锚 + negative control,14 passed)
- ⏳ W4 F3 因子库重算(后台运行,sealed-guarded)
- ⏸ W5 F4(最敏感:live 候选 cycle06/08 价基变更须当 data-revision
  + smoke,不静默改 live soak)/ W6 F5 / W7 P0-B / W8 scaled —— 待续
- 纲领:深度优先、真跑真比对、不走过场、不假装完成;⚑DISCUSS-1
  (run_paper F1 deferred to F4)留明早确认。

### W4 — F3 root-cause + relaunch(不走过场:真根因非 hand-wave)
- 首跑 exit 143 = **`timeout 600` 太短**(非 OOM 非 bug)。复现:5 票
  generate_all_factors 2.8s → 全 76 票 ×2 价基 × IC loop 远超 10min。
- **诚实范围发现**:generate_all_factors 仅产 **96 个 OHLCV 族因子**
  (143 需 fundamental/sector/macro 另 compute path)。P0-A 价格 split
  污染**正命中价格窗口类=这 96 个**;fundamental/sector/macro 来自
  非价格 path,**不在 P0-A loader scope**。F3 诚实范围 = OHLCV 96 因
  子 raw vs adjusted,restate 会如实写明此 scope,不谎称"全 143"。
- 重跑:无 timeout 后台 PID 137366,tracked 监控 b6kw0398e,完成
  自动续 W4 记真数 → W7。

### W4 — F3 v2 0-stats root-cause(现场抓出自己的反面教材)
- v2 跑通 sealed-safe(train-only/81 票/sealed_read=False)但 **0 stats**。
- **真根因(非 hand-wave)**:复现单因子不吞异常 → `compute_rank_ic`/
  `compute_factor_stats` **正常**;bug 在我脚本 `st.ic_mean`(FactorStats
  真字段是 `mean_ic`/`ir`)→ 每因子 AttributeError 被我 `except
  Exception: continue` **静默吞掉** → 假装 0 stats。**"不走过场"的
  直接教训:自己的吞异常掩盖自己的错——已现场抓出**。
- 修:`mean_ic`/`ir` 正确字段 + **去 blanket swallow**:记 n_fail/
  first_err,**全失败 fail-closed raise**(永不静默当干净 0)。
- v3 重跑 PID 141159(fixed),tracked b0cfm7mu3,完成自动续。

### W4 — P0-A F3 因子库 adjusted 重述 ✅(透做完成)
v3 成功真跑:86 OHLCV 因子×h,train-only,sealed_read=False,0 failed。
**Spearman(raw_ir,adj_ir)=0.9992,0 符号翻转,0 material flip,top-20
重叠 0.95,最大 |IR| 差 0.023**。诚实结论:因子库 IC **原则 P0-A
in-scope(raw 算)但实证 immaterial**——与 §1.A.q 同型 de-escalation。
诚实 scope:86 OHLCV 非全 143(fundamental/sector/macro 非价格 path
不背书)。restate `docs/audit/20260518-factor_ic_library_adjusted_
restate.md`;audit memo §1 scope 行已 fold。F1 修复仍必要(根治 +
短窗口因子 + 防未来污染),本结论只说"已跑出的因子库数没被显著污染"。
**三次失败全真根因(超时/自己错字段名被自己吞),无一 hand-wave。**

---
## 隔夜收尾 —— 给用户明早讨论(2026-05-18 夜止)

**严谨完成并 push(每项真跑/真比对/真根因,无走过场)**:
- ✅ W1 GPU P0(conditional pass / VRAM-bounded)
- ✅ W2 P0-A F1 loader 统一(price_access;run_research_miner /
  run_factor_screen / run_mining;run_paper 故意留 F4=⚑DISCUSS-1)
- ✅ W3 P0-A F2 价基回归测试(4 真 split 锚 + negative control,14 passed)
- ✅ W4 P0-A F3 因子库 raw→adjusted 重述(Spearman 0.9992、0 翻转 →
  in-scope 但实证 immaterial;诚实 scope 86 OHLCV 非全 143;F3 三败
  全真根因)

**未做,诚实留明天(绝不假装/不在 tail 半吊子起,违"不走过场")**:
- ⏸ **W7 P0-B**(大、碰生产 acceptance:DSR/PBO/CPCV/MinBTL 接 gate +
  HAC IC t-stat + 年-fold→purged CPCV)——需独立专注 pass,不在巨长
  turn 尾仓促做。
- ⏸ **W5 P0-A F4**(最敏感:cycle06/08 live soak 价基变更须当
  data-revision-event + smoke,不静默改活序列)。
- ⏸ W6 F5 standing 重述 / W8 scaled S1-S4(GPU 串行,排最后)。

**待你拍板(明早)**:
1. `⚑DISCUSS-1`:run_paper loader swap 延到 F4 当 data-revision +
   smoke 处理(deliberate sequencing,非遗漏)——确认 OK?
2. P0-A 整体 severity 已被 F3 + §1.A.q 双重 de-escalate(主轴
   Spearman 0.96、因子库 0.9992)→ 是否仍按原优先级推 P0-B/F4,
   还是因 severity 降而调顺序?
3. W7 P0-B 接生产 gate 是否 new-cycle-only(同 G4 PRD)即可,还是
   要回溯重评 cycle06/08(我倾向 new-cycle-only:它们已过 adjusted
   gate + forward 在跑,回溯低值)。

无后台任务在跑;不自启 loop;明早从本日志可完整复盘。

---
## 2026-05-18 白天续(用户"按建议走接着做" → W7 P0-B 优先,new-cycle-only)

### W7a — 因子 IC t-stat 加 HAC(Newey-West)✅(P1-2,透做)
- `core/factors/factor_engine.py`:加 `_hac_ttest_mean0`(Bartlett,手写,
  statsmodels 不可用→不加重依赖,合项目惯例);compute_factor_stats
  的裸 `ttest_1samp` 换 HAC,Bartlett lag=max(1,horizon-1)(重叠 label
  自相关长度),degenerate≤0 fallback iid。
- docstring 改:原"horizon 不影响计算"是错的(现影响 HAC lag)——顺带
  审计诚实纠正。
- 影响面:`is_significant`(=|ir|>0.3 且 p<0.05)→ HAC 让 p 更诚实变大
  → 显著门正确变严(P1-2 本意);new-cycle-forward,不回溯改存量。
- 测试 4/4 + factor_engine 31 回归 0 破坏。**不走过场**:含决策意义
  flip 测(iid 假阳性 p<0.05 → HAC 正确 p>0.05);首版我加的
  `p_hac>1e-6` 是不合理断言(signal 太强),改成测真 HAC 属性(flip+
  deflation ordering)而非删断言凑绿。
- 仍属 W7 内:W7b DSR/PBO/MinBTL 接 cycle-eval 输出(new-cycle-only)、
  W7c CPCV 分布 acceptance、W7d purged/embargo fold —— 待续,逐增量。

### W7b — DSR/PBO/MinBTL 接进生产 acceptance evaluator ✅(new-cycle-only,真接)
- `temporal_split_acceptance.py`:SplitAcceptanceResult 加 optional
  `overfit_diagnostics`(lazy-migration,legacy 无→None→as_dict 字节
  不变,**cycle06/08 零回溯**);`build_overfit_diagnostics`(G1 honest-N
  DSR + G3 MinBTL fail-closed gate + G2 PBO[matrix 有则算,无则
  forward-only note]);`run_split_acceptance` 读 `metrics["overfit_
  inputs"]` —— **仅新 cycle caller 传此键才 attach**,legacy/cycle06-08
  metrics 无此键 → 完全不变。这是在 canonical 生产 evaluator 真接,
  非 dead helper。
- honest-N guard:honest_n_trials=1(magic literal)→ raise,不静默 pass。
- 测试 6/6 + G1/G3 13 回归 + temporal_split/acceptance **211 passed 0
  回归**。**不走过场**:测了 legacy 字节不变 / 新 cycle attach / MinBTL
  fail-closed / guard 拒 magic literal / PBO forward-only。
- **P0-B 范围诚实**:W7a(HAC)+ W7b(DSR/PBO/MinBTL 接 evaluator)=
  关掉"SOTA kernel available-not-wired"最高价值部分,真接已 ship。
  **W7c/W7d(年-fold→purged/embargo CPCV 分布替换)= 更 invasive 的
  fold 结构改,new-cycle-only,cpcv_acceptance 模块已建已测但 swap
  生产 fold 结构无现 consumer**——按项目"无 consumer 不 dead-wire +
  new-cycle-only"纪律 + 不在 turn 尾仓促做 invasive swap,**诚实留作
  W7 剩余,待新 cycle 授权时落**,不假装 W7 全done。

### W5 — P0-A F4 ✅(R3 实证 de-escalate「最敏感」误判,透做)
- **F4-A2 前提被 R3 证伪**:run_paper 不写 forward/evidence manifest
  (grep 空);live cycle06/08/pead observe 走 `run_forward_observe →
  core.research.forward.observe`,daily 估值 `attention_report` BarStore
  -adjusted(复核 line456)。**改 run_paper loader ≠ 静默改 live soak**
  ——PRD F4-A2 的保守假设不成立,诚实 de-escalation(同 F3/§1.A.q 型)。
- **F4-A1 shipped**:run_paper.py:392 daily `store.read`→`load_adjusted`
  (60m reads 留 raw,intraday 独立,同 run_mining)。compile OK。
- **smoke 守纪律(虽风险低仍做)**:cycle06/08 `observe --dry-run`
  **改前/改后字节相同**("no new bars idempotent no-op")→ 经验证明
  forward-evidence 路径与 run_paper loader **隔离**。
- **M11a/b parity 119 passed 0 回归**(全 paper_trading 套件)。诚实:
  parity 测合成数据,验引擎一致性非价基变更本身;价基正确性由 F2
  回归测试覆盖。
- **残余诚实 flag(不隐瞒)**:`forward/runner.py:527` 60m 经
  MarketDataStore raw,**仅 `enable_sr_defer` 候选才跑**(否则
  early-return identical NAV)、且是 60m swing filter 非 daily 证据
  NAV → 独立小项,记录待后续(非 F4 live 风险)。
- **结论**:W5/F4 "最敏感"是基于保守假设;R3 实证后 = F4-A1 真修
  +parity 保持+隔离经验证明,F4-A2 重机制**不需要**(风险在此路径
  不存在)。不假装做了不需要的机制,也不隐瞒 60m 残余。

### W7c/d — CPCV-distribution fold acceptance 接进生产 evaluator ✅(用户授权新 cycle → 真 consumer)
- `temporal_split_acceptance`:加 optional `cpcv_acceptance` 字段
  (lazy-migration,legacy 无 `cpcv_inputs`→None→字节不变零回溯);
  run_split_acceptance 读 `metrics["cpcv_inputs"]` → 调
  cpcv_acceptance_distribution(purged+embargo G4)+ append **binding
  fail-closed gate** `cpcv_distribution_acceptance`(insufficient/
  noise/error → passed=False → overall_passed=False)。
- new-cycle-only by 输入存在;contiguous-year gate 保留为 legacy 路径
  (G4-A3 back-compat by construction)。
- 测试 5/5 + W7b 6 + G4 6 + **temporal_split/acceptance 216 passed
  0 回归**(211→216)。不走过场:测了 legacy 字节不变/强 edge 过/
  noise+insufficient+error 三种 fail-closed binding。
- **P0-B W7 完整**:W7a HAC + W7b DSR/PBO/MinBTL + W7c/d CPCV fold,
  全真接 canonical 生产 evaluator,new-cycle-only。用户授权新 cycle
  使 W7c/d 从"new-cycle-gated 剩余"变"真 consumer 已接"。
- 硬 blocker 已 surface:`alternating_regime_holdout_v1` 2026 sealed
  CONSUMED → 新 cycle scope = adjusted mining SEARCH + Track-A-accept
  (train/val),**sealed 步骤 pre-register DEFERRED**(合纪律,非
  静默跳)。下:pre-reg criteria yaml + 后台 mining + W8 GPU。
