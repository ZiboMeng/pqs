# Forward OOS Observation Log

Per-day record of the forward observation ritual triggered by user
signal "new daily data has arrived". Append-only, one entry per
day per ritual run. The manifest files
(`data/research_candidates/<id>_forward_manifest.json`) are the
canonical record of TD entries; this log is the human-readable
heartbeat showing **when** observations were attempted, what state
the data was in, and what got appended.

Workflow: `docs/prd/20260426-forward_oos_runner_prd.md` + memory
`feedback_forward_observation_ritual.md`.

Entry format:

```
## YYYY-MM-DD (UTC)
- data_state: <SPY latest date / how many syms behind>
- RCMv1: <can_append? appended N TDs (latest TD<NNN> @ date) or no-op>
- Cand-2: <same>
- notes: <source_mix changes / readiness flags / anomalies>
```

---

## 2026-04-26 (UTC) — initial state pre-ritual

State at end of R-fwd-1 setup + post-MVP audit fixes (commit
`3aa3866` and prior). NOT a ritual run — recorded here as the
baseline before daily observation begins:

- data_state: SPY latest 2026-04-24; all 78 universe syms at 2026-04-24
- RCMv1: TD001 @ 2026-04-24 / cum_ret=0.00% / source_mix=True
  (start_date=2026-04-24, n_runs=1, status=in_progress)
- Cand-2: TD001 @ 2026-04-24 / cum_ret=0.00% / source_mix=True
  (start_date=2026-04-24, n_runs=1, status=in_progress)
- notes: both candidates entered observation mode after timestamp-aware
  start_date fix (commit `04e89b5`); next ritual triggers on user
  signaling new data (expected next trading day = Mon 2026-04-27 close)

---

## 2026-05-15 (UTC) — daily ritual (post-close)

First ritual since the 2026-04-26 baseline. RCMv1 + Cand-2 aborted
2026-04-30; current forward set is the 4 candidates below.

- data_state: SPY latest 2026-05-15 (close $739.17, −1.2% day); 84
  syms fetched post-close via `fetch_data.py --daily-only`
- trial9_diversifier_002: **no-op — status=requires_data_review**
  (halted at TD002 @ 2026-05-14; pre-existing revalidate halt, needs
  separate investigation — NOT resolved by today's ritual)
- cycle08_3f40e3f4ed1a_evidence_v1: appended **TD001 @ 2026-05-15**
  (forward day 1, cum_ret baseline; core_alpha role, evidence stance)
- cycle06_31af04cf2ff9_evidence_v1: appended **TD001 @ 2026-05-15**
  (forward day 1, cum_ret baseline; core_alpha role, evidence stance)
- pead_sue_trial1_evidence_v1: appended **TD001 @ 2026-05-15**
  (forward day 1, all metrics 0% baseline; 287 lifetime signals)
- spy_8otm_bull_put_v1 (options): **TD007** NAV $10,000.00, DD 0.00%,
  0 open positions, cum_pnl $0.00 (SPY $739.17 / VIX 18.43)
- VRP scan: NVDA +7.98±1.90 STABLE-RICH candidate; COIN noisy; AAPL/
  MSFT/GOOG/META/AMD structurally cheap
- notes: cycle06/08 evidence candidates' first observe required adding
  FactorInputContract entries for xsection_rank_63d / trend_tstat_20d /
  ret_2d to bar_hash._FACTOR_REGISTRY (pre-flight gap — should have
  smoke-tested observe before forward-init). trial9_v2 halt to be
  investigated next session.

## 2026-05-18 daily ritual(收盘后)
- fetch_data: ✅ 收盘后(2026-05-18 ~16:46 ET,pre-close 守卫通过,243 日内更新)
- **env caveat**:本会话装 torchvision 连带升 torch2.12+pandas3.0;**先 dry-run smoke 验** cycle06/08 在新环境无 drift/fail-closed(字节 no-op)→ 再真 observe(守 pre/post-smoke 纪律)
- cycle06_31af04cf2ff9_evidence_v1 / cycle08_3f40e3f4ed1a_evidence_v1:**no-new-bar no-op**,今日无新 canonical 日线 → 未写 TD(诚实:非漏,daily 聚合未跟上/idempotent;dry-run==real)
- pead_sue_trial1_evidence_v1(standalone track):✅ 推进,写 manifest 3 TDs + nav 2356 行,forward MaxDD -0.04%(60d -0.04%),lifetime 287 signals/507 trades
- spy_8otm_bull_put_v1(options):✅ **TD008**,SPY $738.65/VIX 17.82,NAV $10,000,DD 0%,0 仓,cum_pnl $0,events=[]
- cumulative_vrp_scan:已跑
- 状态:全候选 healthy;无 fail-closed/无 drift;torch2.12+pandas3.0 下 forward 路径验证正常(加固 60-测回归信心)
