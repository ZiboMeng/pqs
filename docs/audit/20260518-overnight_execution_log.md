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
