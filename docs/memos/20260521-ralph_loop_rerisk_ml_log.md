# Ralph-Loop 运行日志 — Re-Risk + ML Training Framework Hardening

每一轮 ralph-loop 迭代结束时,将本轮完整的中文 11 部分报告**追加**到本
文件末尾。不要覆盖既有条目。

参考:
- `docs/prd/20260521-rerisk-and-ml-training-audit-prd.md` — 阶段 PRD
- `docs/memos/20260521-ralph_loop_rerisk_ml_prompt.md` — 每轮协议
- `CLAUDE.md` — 系统不变约束

执行顺序:R0 → P0 → P1 → P2 → P3 → P4 → P5 → P6。
完成 promise:`RERISK-ML-PRD-DONE`。

---

## Round 1 — R0 第一步:re-risk pack 驱动 + baseline train-only 行

**时间**: 2026-05-21 · **主 commit**: `393b570` · **测试基线**: 3864
passed(未动 module 代码,不变)

① **当前阶段** — Round 1 / Workstream R0 / 第一步。

② **本轮目标** — 建 re-risk pack 驱动,产出 production baseline 的
train-only re-risk 行。

③ **为什么先做它** — PRD §12.4:R0 是 P0-P6 硬前置;§6.1 candidate #1
= production baseline;§6.4 要求行可复现自 checked-in 路径。

④ **做了什么** — 轮前审计发现 2 个 stray audit 工件(r32 重复重跑 =
已提交 215758Z 逐字副本;p7 = 环境漂移、verdict 不变),非 WIP/非
directional → housekeeping 清理留痕,不 halt loop。新建
`dev/scripts/audit/rerisk_pack.py`(subprocess run_backtest → 解析
master_report → verdict + JSON upsert)。跑 baseline train-only
2009-2017,写 `rerisk_pack_20260521.json` + `20260521-rerisk-pack.md`。

⑤ **改了哪些文件** — `dev/scripts/audit/rerisk_pack.py`(新)/
`data/audit/rerisk_pack_20260521.json`(新)/
`docs/memos/20260521-rerisk-pack.md`(新)。

⑥ **跑了哪些测试 + 结果** — driver exit 0;R3 复现:CAGR 12.59% /
MaxDD -20.21% / vol 13.16% 与 commit `8073c88` audit memo §6 逐字
一致;新独立 driver 未动 module 代码,不重跑全量回归。

⑦ **当前结果** — baseline train-only 2009-2017:总收益 +190.35% /
CAGR +12.59% / Sharpe 0.67 / MaxDD -20.21% / vol 13.16% / Beta 0.28
/ 1629 trades。verdict YELLOW(provisional,MaxDD 越 20% 硬线 0.2pp)。

⑧ **剩余风险** — verdict provisional(stress-slice + per-year MaxDD
未出);近期高波动窗口 -64% 未在 pack 复现;cycle06/08/PEAD 三行未做。

⑨ **下一轮建议** — Round 2 = R0 第二步:baseline stress slices
(covid_flash / rate_hike)+ 近期窗口 `partition: diagnostic` 复现
§2.1 -63.95% 画像;扩 driver 支持 per-year MaxDD。

⑩ **TODO** — [x] R0 driver [x] R0 baseline train-only ·
[ ] R0 baseline stress+diagnostic [ ] cycle06 [ ] cycle08 [ ] PEAD
[ ] R0 收口 · [ ] P0-P6。

⑪ **commit** — `393b570`(主)。

<!-- Round 2 起在此行下方追加 -->
