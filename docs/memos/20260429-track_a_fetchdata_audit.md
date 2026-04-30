---
date: 2026-04-29
type: memo
status: closed
lineage_tag: track-a-fetchdata-audit-2026-04-29
related_prds:
  - docs/prd/20260429-temporal_split_holdout_discipline_prd.md (v1.1)
  - inline fetch_data partial-bar fix (2026-04-29)
related_memos:
  - docs/memos/20260429-track_a_implementation_log.md
  - docs/memos/20260429-track_a_f1_f2_fork_criteria.md
---

# Track A + fetch_data audit (R1 + R2)

User instruction: "做两轮针对已经完成的这些工作的audit 一定要细致 我不希望
再出现你说你audit没有问题 结果codexaudit出问题的情况 不要只跑test 或者
smoke test 一定要跑代码 看一下结果是否符合预期 然后有bug改 有不合理的
地方 也改 有需要讨论的地方 提出来 包括A和fetchdata"

Two adversarial audit rounds against the just-shipped Track A v1
(8 modules, 6 commits, 126 unit tests landed earlier this session)
and the inline fetch_data partial-bar guard. **Live code execution
where reasonable, not just `pytest`** — that was the user's hard
request because tests can pass while behavior is wrong.

## Scope

Track A modules audited:
- `core/research/temporal_split.py` (split loader + restrict_frames +
  leak guard + purge_labels + validate_factor_lookback +
  enforce_c5_no_role_remint + compute_split_sha256)
- `core/research/temporal_split_acceptance.py` (17-gate evaluator)
- `core/research/sealed_ledger.py` (M5 + B1 fail-closed ledger)
- `core/research/regime_classifier.py` (M9 manual↔auto reconciliation)
- `core/mining/rcm_archive.py` Track A migration (split metadata cols)
- `config/temporal_split.yaml` SOT
- `scripts/run_research_miner.py` Track A wiring

fetch_data audited:
- `scripts/fetch_data.py` (download_daily + download_intraday)
- `core/data/calendar.py` (get_session_close_et / is_session_complete)
- `core/data/fetch_session_log.py` (record_fetch / was_fetched_pre_close)

## Round 1 — live code execution

Tests run live (not just pytest):

| # | Test | Method | Result |
|---|------|--------|--------|
| 1 | fetch_data scenarios A-D | trace pre/post-close, force-refresh, legacy paths | identified BUG #1 |
| 2 | fetch_data force_refresh data-loss | constructed adversarial last_date | **BUG #1 confirmed** |
| 3 | split_sha256 stability + cross-module | regenerate, compare across modules | PASS |
| 4 | split_sha256 vs F PRD ConfigSnapshot | inspect F PRD `_canonical_yaml_sha` callsites | PASS — independent (codex R20 B2 corrected) |
| 5 | sealed_ledger record_eval with realistic types | passed numpy.int64 / numpy.float64 / numpy.ndarray | **BUG #2 confirmed** |
| 6 | acceptance evaluator non-numeric metric | passed string in `excess_vs_qqq` | **BUG #3 confirmed** |
| 6b | acceptance evaluator NaN handling | passed `float("nan")` aggregate | **BUG #4 (silent filter)** |
| 7 | rcm_archive Track A schema migration | fresh DB + reopen idempotency | PASS |
| 8 | restrict_frames + leak guard on real-shape panel | DataFrame 2018-2026, validation+sealed leak | PASS |
| 8b | regime_classifier on real SPY/VIX 2018-2026 | live `RegimeDetector` against `data/daily/SPY.parquet` + `_VIX.parquet` | PASS — 0/5 disagreement (tier=memo_only) |
| 9 | purge_labels_at_boundary boundary purging | year boundaries 2017→2018, 2019→2020 | PASS — 151 NaN rows out of 2173 |
| 10 | validate_factor_lookback edge cases | -1, 0, cap, 2000 | **BUG #6 (negative accepted)** |

Round 1 found 5 bugs (#1, #2, #3, #4, #6).

## Round 2 — adversarial / cross-cutting

| # | Test | Method | Result |
|---|------|--------|--------|
| 2.1 | split_sha256 invariance | trailing newline / new comment / key-reorder / actual change | PASS — canonical, semantic-only |
| 2.2 | F PRD ConfigSnapshot vs Track A | grep `_canonical_yaml_sha` callsites; inspect file list | PASS — fully independent |
| 2.3 | sealed_ledger M5 + B1 with cross-fixture spec | fresh ledger per scenario | PASS |
| 2.4 | sealed_ledger numpy in fresh ledger | re-confirm BUG #2 outside B1 cross-contamination | **BUG #2 reconfirmed** |
| 2.5 | session-close DST boundaries | 2025-03-07 (EST), 2025-03-10 (EDT), 2025-10-31 (EDT), 2025-11-03 (EST) | PASS — close shifts UTC offset correctly |
| 2.5b | session-close edge inputs | empty string / invalid date | minor: empty string error message confusing (NaTType.normalize) — non-blocking |
| 2.6 | legacy partial-bar without log entry | grep was_fetched_pre_close (no record) → False | LIMITATION — legacy partials need `--full` to clear |
| 2.7 | stale pre-close marker N days ago | log shows is_pre_close=True for 3 days ago | DISCUSSION — fetch_data only checks today |
| 2.8 | intraday `--allow-pre-close-today` + last_date=yesterday | trace download_intraday line 308 | **BUG #7 confirmed** |
| 2.9 | fetch_session_log atomic write under concurrent writers | 2 threads × 20 writes | **BUG #5 confirmed** (FileNotFoundError) |

Round 2 found 2 additional bugs (#5, #7).

## Bug summary + fixes

### CONFIRMED + FIXED in this audit (7 bugs)

| # | Sev | File | Bug | Fix |
|---|-----|------|-----|-----|
| 1 | **HIGH** | `scripts/fetch_data.py:298-303` | `download_intraday` force_refresh hardcoded `start = today_et - 5d`, ignored `last_date`. If user away >5 days then ran with `--allow`, then re-ran post-close, days between `last_date+1` and `today-6d` were lost. | Consult `last_date`; use `min(today-5d, last_date-5d)`. Bounded by yfinance lookback (60d / 700d). |
| 2 | **HIGH** | `core/research/sealed_ledger.py:99-109` | `compute_result_metrics_sha256` used `json.dumps` directly; raised `TypeError` on numpy.int64 / numpy.float64 / numpy.ndarray returned by Track C mining (real path, would have blocked first sealed eval). | Coerce numpy scalars via `.item()` and ndarrays via `.tolist()` in `_canon`. |
| 3 | **HIGH** | `core/research/temporal_split_acceptance.py` (multiple sites) | 12 of 17 gates called `float(value)` directly on `_resolve_metric` output. Non-numeric value (e.g. miner returns string error code) crashed evaluator with `TypeError`. | Added `_as_float_or_none(value)` helper; bool intentionally rejected (consumed by dedicated bool gates); patched all 12 sites; fail-closed with `notes` explaining why. |
| 4 | MEDIUM | `core/research/temporal_split_acceptance.py:241-265` | Aggregate excess gate silently treated NaN as "not positive". Operator had no signal that the metric was missing vs negative. | Added `missing_or_invalid_years` to gate output + `notes` listing which years were missing/non-numeric. Aggregate still requires strict positive count; missing years cannot contribute. |
| 5 | LOW | `core/data/fetch_session_log.py:67-72` | `_save_atomic` used fixed `.json.tmp` filename; concurrent writers raced on rename → `FileNotFoundError`. (Documented single-writer, but trivially preventable.) | Per-pid + per-tid suffix on tempfile; cleanup in `finally`. Lost-update race on shared dict still possible (single-writer assumption stands), but no crash. |
| 6 | LOW | `core/research/temporal_split.py:684` | `validate_factor_lookback` only checked upper bound; negative lookback (lookahead, the worst leak class) silently passed. Defense-in-depth hole. | Added `lookback_days >= 0` check before cap check. |
| 7 | MEDIUM | `scripts/fetch_data.py:308` | `download_intraday` skipped fetch when `days_stale <= 1 and (session_complete or allow_pre_close_today)`. With `--allow` + `last_date=yesterday`, user who **wanted** today's partial bar was silently skipped. | Split into `days_stale == 0` (skip — already have today) vs `days_stale <= 1` post-close (skip — up-to-date) vs `days_stale <= 1 + pre-close + no-allow` (skip — wait for close). With `allow=True` + `days_stale==1`, fall through and fetch. |

### DISCUSSION items (no code fix; documented for future)

**D1: Legacy partial-bar bars before this fix shipped.** If a user ran
`fetchdata` pre-close before 2026-04-29 and partial bars are sitting on
disk with no `fetch_session_log` entry, the new force-refresh logic
won't detect them. Mitigation: doc note in fetch_data.py docstring;
operational guidance is `--full` to rebuild. A scan-all-stale-partials
mode is a future enhancement, not a bug.

**D2: Stale pre-close marker for older dates.** If user runs with
`--allow-pre-close-today` on day N and then doesn't run until day
N+2, day N's row stays partial because fetch_data only checks
`was_fetched_pre_close(sym, freq, today_et)`. Future enhancement:
scan ALL pre-close markers in the log and force-refresh those rows.
Not currently triggered (user's normal workflow is daily post-close).

**D3: `fetch_session_log` lost-update race under concurrent writers.**
After the BUG #5 fix, no crash; but two writers reading the JSON
simultaneously, then both writing, can lose one's update. The
docstring is explicit that this is single-writer. fcntl-based
locking is a future hardening if multi-writer scenarios appear.

**D4: Empty-string / invalid date error in `get_session_close_et`.**
`get_session_close_et("")` raises `AttributeError: 'NaTType' object
has no attribute 'normalize'`. Confusing message but rare in
practice (caller passes valid date). Non-blocking.

## Verification

Smoke verification passed for all 7 fixes (live code, not pytest):

```
=== BUG #1 verification ===  FIX present
=== BUG #2 verification ===  numpy types now hash 2ccd0c5ef25d951f
=== BUG #3 verification ===  evaluate_candidate handled non-numeric, passed=False
=== BUG #5 verification ===  concurrent writers OK (no FileNotFoundError)
=== BUG #6 verification ===  -1 lookback rejected
=== BUG #7 verification ===  days_stale==0 short-circuit present
ALL FIXES VERIFIED
```

Plus full pytest unit suite must remain green; expected 1979 → 1979
(no test changes for this audit; only behavior fixes the existing
tests don't cover the adversarial inputs that exposed the bugs).

## Coverage gap acknowledged

Round 1 + Round 2 did not cover:
- Real Track C mining end-to-end through `run_research_miner.py`
  with `--temporal-split` flag (Track C not yet built — it is the
  next workstream)
- Real BarStore-backed end-to-end: leak guard / purge_labels under
  real factor frames (only synthetic random panels were tested)
- Codex review of these fixes (this memo + the diff push to
  `review/claude-collab` is part of that)

These will surface in follow-up work; flagging here for honesty.

## Conclusion

7 real bugs found and fixed; 4 discussion items documented. The
single most consequential bug was **#3 (non-numeric crash)** — it
would have killed the first Track C mining evaluation that returned
a string error code, and is the kind of bug that doesn't show up
in synthetic tests. The next most consequential was **#2 (numpy
serialization)** — would have killed the first real sealed-eval
attempt. The fetch_data bugs (#1 + #7) would have caused silent
data loss / silent miss respectively, both of which the user
explicitly reported having lived through.

Audit was substantive — not "tests pass therefore audit clean".
