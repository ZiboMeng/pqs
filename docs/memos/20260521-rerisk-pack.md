# R0 Re-Risk Pack — 2026-05-21

**PRD**: `docs/prd/20260521-rerisk-and-ml-training-audit-prd.md` §6
**驱动**: `dev/scripts/audit/rerisk_pack.py`(可复现,§6.4)
**机读产物**: `data/audit/rerisk_pack_20260521.json`
**Lineage**: `rerisk-and-ml-training-audit-2026-05-21`

执行内核 5 修复(2026-05-21,commits `d056652`..`14a1c0c`)之后,对
production baseline 与活跃 evidence 候选重算可信风险画像。每行声明
回测窗口 + temporal_split partition(§6.5);所有数字由 checked-in 的
`run_backtest.py` 路径产出,无手工计算。

本 memo 随 ralph-loop 逐轮增补,不覆盖既有行。

---

## 进度

| 候选 | 状态 |
|---|---|
| production baseline | 🟡 Round 1:train-only 行已出;stress slice + 近期窗口 diagnostic 待 Round 2 |
| cycle06_31af04cf2ff9_evidence_v1 | ⬜ 待后续轮(exact frozen spec replay) |
| cycle08_3f40e3f4ed1a_evidence_v1 | ⬜ 待后续轮 |
| pead_sue_trial1_evidence_v1 | ⬜ 待后续轮 |

---

## 1. Production baseline(multi_factor conservative_default)

来源:`config/production_strategy.yaml`(status=conservative_default)。

### 1.1 train-only 窗口 2009-01-02 .. 2017-12-31(partition: train_only)

| 指标 | 值 |
|---|---|
| 总收益 | +190.35% |
| CAGR | +12.59% |
| Sharpe | 0.67 |
| 最大回撤 | **-20.21%** |
| 年化波动率 | 13.16% |
| Beta vs SPY | 0.28 |
| IR | -0.02 |
| 交易笔数 | 1629 |

**verdict: YELLOW(provisional)** —— full-period MaxDD 20.2% 略越
15-20% 硬上限(超 0.2pp);stress-slice + per-validation-year MaxDD
待 Round 2 补齐后升级为正式 verdict。

复现:`python scripts/run_backtest.py --strategy multi_factor
--start 2009-01-02 --end 2017-12-31 --no-walk-forward`。

**解读**:在纯 train 低波动期,baseline 实际波动率仅 ~13%(远低于
constructor 的 25% target_vol),correlation-aware vol-target(P0-1
修复)在此窗口 inert,MaxDD ~20% 基本贴线。这与 PRD §2.1 修订
后的判断一致 —— baseline 非全局损坏,而是 regime-fragile:灾难性的
-64% MaxDD 出现在近期高波动窗口(Round 2 将以显式标注的 diagnostic
窗口复现该对比)。

### 1.2 stress slices + 近期窗口 diagnostic

⬜ 待 Round 2。covid_flash 2020-Q1 / rate_hike 2022-Q3 作 MaxDD
sanity;近期 ~4 年窗口作 `partition: diagnostic` 复现 §2.1 的
-63.95% / 27.7%-vol 画像。

---

## 2-4. cycle06 / cycle08 / PEAD

⬜ 待后续 ralph-loop 轮。cycle06/cycle08 必须按 **exact frozen
spec** replay(PRD §2.2:不用 lineage top-1 lookup);sealed 2026
不在 R0 范围内单发。
