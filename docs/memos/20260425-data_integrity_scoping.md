# Data-Integrity Workstream — Scoping Memo (Round 1)

**Date**: 2026-04-25
**Status**: scoping only — no code changes, no data rebuild in this
round.
**Trigger**: M11 fix landed; user closeout direction switched the
main technical-debt line off M14/M11 stack and onto data integrity.
The M11 memo §5 left a parking-lot item on misdated 2022 Saturday
rows; the older split-adjustment memo
(`docs/20260424-data_integrity_2022_split_adjustment.md`) left
TSLA/GOOGL contamination unresolved. This memo does not fix either;
it pins down scope, contamination boundaries, hypotheses, repair
options, and downstream re-run obligations so the next round can
start with a clear surface.

**Out of scope (per user direction)**:
- Universe extension, new mining round, Candidate-3, new data tier,
  retroactive RCMv1 spec change.
- Any code edit to `BarStore`, ingest scripts, or paper engines in
  this round.
- Any rebuild of the underlying `data/intraday/1m/*.parquet` or the
  daily aggregation derived from them.
- Any drift / parity re-verification cell run.

This memo splits the workstream into **two independent sub-issues**.
Either can in principle be repaired without the other, but their
fixes have different blast radii — see §5.

---

## 1. Sub-issue I — Split-Adjustment Consistency

### 1.1 What the bug looks like

In some symbols' `daily` BarStore parquet, **adjacent days' close
prices alternate between the raw and the split-adjusted scale**.
Reproduction example, TSLA 2022-Q1 (from the older memo):

```
2022-03-29:  $366.52      ← split-adjusted (raw / 3)
2022-03-30: $1099.57      ← RAW pre-split
2022-03-31: $1093.99      ← RAW
2022-04-01: $1079.63      ← RAW
2022-04-04:  $381.82      ← split-adjusted again
2022-04-05: $1145.38      ← RAW again
```

When the panel is held into one of these alternations, daily close-
to-close return computes as ~+200% / -65% / ~+200% — spurious
single-day moves of 100s of percent. This is the +190.95% TSLA spike
that surfaced the issue originally.

### 1.2 Empirical scope (this round, read-only scan)

Adjacent-day close-ratio outliers `(ratio < 0.5 or ratio > 2.0)`
across 24 universe symbols × 2015-2026:

| Symbol | n outliers | year span | Cause hypothesis |
|--------|-----------:|-----------|------------------|
| **TSLA** | **1132** | 2016-2022 | systemic — alternating pattern, ~15× ratio (= 5×3 cumulative split factor) |
| **GOOGL** | **692** | 2018-2022 | systemic — ~20× ratio matches 2022-07 GOOGL 20:1 split |
| **TJX** | **465** | 2016-2018 | systemic — ~2.3× pattern |
| TQQQ | 9 | 2017-2025 | episodic — single-day jumps near splits |
| SOXL | 4 | 2015, 2021 | episodic — near 5:1 (2015) and 15:1 (2021) splits |
| NVDA | 2 | 2021-07 | episodic — at NVDA 4:1 split boundary |
| LRCX | 2 | 2024-10 | episodic — at LRCX 10:1 split boundary |
| META | 1 | 2022-06-10 | unexplained — no META 2022 split known |
| (others) | 0 | — | clean |

**16 / 24 universe symbols are clean** under this 0.5/2.0 ratio
heuristic. **3 are systemically contaminated** (TSLA, GOOGL, TJX).
**5 are episodically contaminated** at split boundaries.

The systemic class is much more dangerous: every cross-day position
held into one of the alternation gaps takes a 100s-of-bps spurious
P&L hit. The episodic class can be papered over with a 1-2 day
exclusion at the split boundary.

### 1.3 Known contaminated vs clean windows

From the older memo + this round's scan:

| Window | Contaminated symbols | Status | Where used |
|--------|---------------------|--------|------------|
| 2020-01-02 → 2020-04-22 (COVID bear) | TSLA + GOOGL | ❌ | Not used |
| 2022-01-03 → 2022-04-22 (Q1 bear)    | TSLA          | ❌ | Not used (rejected before paper run) |
| **2022-08-26 → 2022-12-15 (Q4 bear)** | **none from systemic class — TSLA's 3:1 split is 2022-08-25, after which systematic alternation stops** | ✅ | Currently the canonical 2022 cell |
| 2024-01-02 → 2024-04-19 (up-tape)    | none | ✅ | Currently the canonical 2024 cell |
| 2024-10-?? (any window crossing LRCX 10:1) | LRCX | ⚠️ episodic | Not currently used |

Important caveat: "clean" here means **no large adjacent-day ratio
outliers** in the heuristic. It does NOT certify the prices are
correct in absolute level. A consistently-RAW-throughout window and
a consistently-adjusted-throughout window both pass this heuristic
but live on different scales — IC / NAV / cost-bps math degrade
equally if the level is wrong.

### 1.4 Root-cause hypotheses

These are conjectures, not confirmed. Verification belongs to a
later round.

1. **H-1a: yfinance auto_adjust toggling across ingest runs.**
   yfinance default is `auto_adjust=False` (raw close + separate
   `Adj Close` column); newer codepaths use `auto_adjust=True`. If
   the daily ingest pipeline ran some date ranges with
   `auto_adjust=True` and others with `auto_adjust=False`, the
   resulting parquet rows would be on mixed scales. Provenance
   table shows TSLA / GOOGL / NVDA / META / SOXL / TQQQ all flow
   from `yfinance_daily`; TJX flows from `polygon_gz` 2015-2023 +
   `stocks_csv` 2024+, so this hypothesis cannot explain TJX.

2. **H-1b: Manual top-up runs that re-fetched a symbol mid-history
   without applying the same adjustment factor.** Each top-up run
   would re-pull yfinance with the fresh-as-of-then split table
   already cascaded back; rows pulled before a later major split
   would not have the new split's factor applied. The
   2018-2022 TSLA + 2018-2022 GOOGL pattern (alternating across
   YEARS) fits this — a top-up after the 2020 TSLA 5:1 would mix
   pre-2020 raw with post-2020 adjusted; a later top-up after the
   2022-07 GOOGL 20:1 would do the same to GOOGL.

3. **H-1c: `BarStore.load(adjusted=True)` cascade applies the same
   split factor twice for some rows and zero times for others.**
   The store is documented as RAW-stored + read-time-cascade. If
   the splits.parquet recorded a duplicate or missing entry, the
   read-time multiplication would produce mixed scales even though
   the on-disk parquet is consistent. Cheapest to verify (read-only
   diff against splits.parquet).

4. **H-1d: TJX-specific source mismatch.** TJX shows ~2.3× ratios
   in 2016-2018 only (the polygon_gz era), then clean after the
   stocks_csv switch in 2024. Plausible that polygon_gz gave already-
   split-adjusted prices but `splits.parquet` then applied a
   2017-04 TJX 5:4 split's factor again at read time, double-
   adjusting some rows and not others. Cheap to verify against
   splits.parquet.

The truth may be a mix of H-1a / H-1b / H-1c / H-1d for different
symbols. Confirming requires (read-only) comparison of:
- on-disk RAW parquet rows for a contaminated symbol vs yfinance
  re-pull at known auto_adjust setting
- splits.parquet entries for that symbol
- the cascade output from `BarStore.load(adjusted=True)`

That is the next round's first technical task; this round merely
parks the hypothesis list.

### 1.5 Repair-path options (no decision in this memo)

Each option below has different cost / risk / scope. Listing them
so the next round picks one.

| Option | Description | Cost | Blast radius |
|--------|-------------|-----:|-------------:|
| A. Rebuild `splits.parquet` from a trusted source + re-run the read-time cascade | Surgical if H-1c is the cause; no parquet writes needed | low | small |
| B. Re-fetch contaminated symbols from yfinance with explicit `auto_adjust=False` and rewrite the daily parquet | Direct; touches the parquet | medium | medium (changes `data/intraday/1m/*.parquet` for those symbols, plus all aggregations downstream) |
| C. Skip-list: refuse to load contaminated (symbol, year-window) pairs at BarStore boundary; force the rest of the system to work with reduced coverage until the data is rebuilt | Buys time without writes; degrades research surface | low | low |
| D. Forward-only: stop using contaminated history; only run paper / mining over the post-2022-08-26 + 2024+ clean windows we've already verified | Effectively the current ad-hoc state | none | none, but research coverage is permanently reduced |
| E. Rebuild from the existing 1m bar pipeline (which is RAW per-symbol parquet, see CLAUDE.md "1m Bar Pipeline") and re-derive daily via aggregation | Most thorough; sidesteps yfinance-source ambiguity | high | high (touches the daily parquet rebuild, all factor / signal / paper artifacts derived from it) |

A, B, and E are the only ones that actually clean the data. C and D
are coping mechanisms.

### 1.6 Repair risks

- **B and E both touch the on-disk parquet store.** Once rewritten,
  every previously-saved test fixture, regression baseline,
  factor-IR snapshot, walk-forward fold result, and paper-run
  artifact loses its bit-equality with the new store. We have to
  decide which baselines to refresh and which to retire.
- **A has the smallest footprint but the highest "doesn't actually
  fix it" risk.** If the underlying parquet is already mixed-scale
  on disk (H-1a / H-1b), re-cascading a corrected splits.parquet
  cannot repair it — the inconsistency is in the bars themselves,
  not the cascade.
- **C creates a coverage cliff.** TSLA and GOOGL dropping out of
  the universe for 2018-2022 noticeably reduces the research
  surface and may break factor screens that depend on them being
  in-universe. RCMv1 spec doesn't ride on TSLA/GOOGL in the 2022-H2
  / 2024 windows; need to verify before adopting C.
- **D's silent risk** is that any researcher who later picks a
  pre-2022-08-26 window (e.g. for cross-regime expansion to
  2008-2009 GFC, or 2018-Q4 selloff) will run into the contamination
  and may not know it. Documentation alone isn't a control surface.

### 1.7 Downstream re-run obligations

If sub-issue I is fixed (any of A / B / E), the following need to
be re-run / refreshed before any "post-fix" claim is defensible:

- `data/baseline/latest.json` — rebuild via
  `dev/scripts/baseline/build_research_baseline_snapshot.py
  --run-tests`. Test counts may shift if any test
  fixture references contaminated symbols × dates.
- 4 paper drift cells (2024 + 2022-H2 × RCMv1 + Cand-2) — re-run
  via `scripts/run_paper_candidate.py` and `paper_drift_report.py`;
  expect zero drift to hold, but final NAVs may shift if any held
  symbol's prices change post-fix.
- TD75 cross-regime memo §0b numbers — refresh the post-M11
  baselines table in `docs/20260424-parallel_paper_2022h2_checkpoint_75d.md`.
- Mining lineage snapshots (`data/mining/*.db`) — leave alone (they
  are historical record); do NOT re-run. Document in the data-fix
  memo that those snapshots were taken on the pre-fix data.
- `factor_evaluator` IC / IR baselines — re-run if the cleaned
  symbols have non-trivial in-universe weight in any production
  factor (RCMv1 spec uses momentum / quality / value families;
  TSLA / GOOGL are in those baskets cross-sectionally → IR shift
  is likely).

---

## 2. Sub-issue II — Date-Label Integrity (Saturday-row systemic shift)

### 2.1 What the bug looks like

In every universe symbol's `daily` BarStore data, **a row exists at
a Saturday date label that should have been the following Monday**
(or, when that Monday is a US market holiday, the next trading day).
The Saturday row carries full real OHLCV; the corresponding real
Monday is **missing**. Ratio is roughly 1:1 across all weeks.

Reproduction (AAPL 2022, ad-hoc scan):

```
真实 bdate 应有 260 天, BarStore 实际 252 行
缺失 weekday 数: 60 (含 holidays), real_missing = 53
出现 weekend 行数: 52   ← essentially 1:1 with real_missing

抽样:
  缺 2022-01-03 (Mon) | 出现 2022-01-01 (Sat)  delta = 2d
  缺 2022-01-10 (Mon) | 出现 2022-01-08 (Sat)  delta = 2d
  缺 2022-01-18 (Tue) | 出现 2022-01-15 (Sat)  delta = 3d  [Mon 1/17 = MLK]
  缺 2022-01-31 (Mon) | 出现 2022-01-29 (Sat)  delta = 2d
  ...
```

The pattern is: each week, the first actual trading day's data lands
on the preceding Saturday's label instead of on its real date. When
the would-be Monday is a federal holiday, the data lands two days
earlier (i.e. the Tuesday is shifted to the Saturday at delta=3
days instead of delta=2).

There are zero Sunday-labeled rows (verified). The shift is
exclusively to Saturday.

### 2.2 Empirical scope (this round, read-only scan)

| Symbol | Saturday rows 2015-2026 | Per-year average |
|--------|------------------------:|-----------------:|
| every universe symbol | 530-570 | ~50-52 / year (≈ 1 / week) |

**24 / 24 universe symbols are affected.** META starts in 2021
(matches its provenance — it has fewer years in the store), VICI
starts in 2018 (matches its public listing). Otherwise every symbol
has continuous weekly Saturday rows from its first store date
through 2026-04.

This is a **systemic ingest-pipeline bug**, not a per-symbol /
per-window issue. It affects the entire daily store across the
entire historical span.

### 2.3 Known contaminated vs clean windows

There is no clean daily window. Every paper / backtest / factor /
mining run that uses daily bars over a > 7-day span has hit at
least one shifted row. The 4 canonical paper cells (2024-Q1 +
2022-H2 × RCMv1 + Cand-2) all contain ~13-16 shifted rows each.

What HAS been demonstrated:
- ✅ M11 fix made paper-vs-replay drift = 0 across all 4 cells.
- ✅ This implies paper and replay are consistent **with each other**
  on the same shifted panel.

What has NOT been demonstrated:
- ❌ That the in-universe NAV trajectory matches what would obtain
  on a calendar-aligned panel. The 4-cell NAV numbers in the post-
  M11 TD75 §0b are internally consistent but external-calendar-mis-
  aligned. The "+74.57% Cand-2 in 2022-H2" is roughly right by
  construction (real prices were used) but it's the integral of a
  panel with one-week-delayed Mondays, not the integral of the real
  exchange calendar. Whether the discrepancy is material at the NAV
  level is open.

### 2.4 Root-cause hypotheses

1. **H-2a: TZ-floor bug at ingest.** yfinance returns daily bars
   with a timestamp that's `00:00 UTC` for the trading-day date.
   If the ingest converts that to `tz_localize(US/Eastern).floor('D')`
   incorrectly (e.g. `tz_convert` instead of `tz_localize`), the
   Monday `2022-01-03 00:00 UTC` becomes `2022-01-02 19:00 EST`
   which floors to `2022-01-02` — Saturday. **Most likely cause** —
   matches the 1:1 Mon→prev-Sat structure exactly.

2. **H-2b: Polygon flat-files trading-day vs settlement-day.**
   Polygon's flat files for some products record the trading day
   under the settlement date convention, which can land on the
   weekend for some early-week trades. Less likely to produce the
   universal pattern we see (every symbol from `yfinance_daily`
   exhibits it too).

3. **H-2c: stocks_csv producer's date convention.** The 2024+
   `stocks_csv` source might store dates as "previous Saturday" by
   convention. Less likely (the issue exists pre-2024 in every
   yfinance-only symbol too).

H-2a is the most likely; verification is read-only (one-line
yfinance pull + compare timestamps against the parquet).

### 2.5 Repair-path options (no decision in this memo)

> ⚠️ Amended by §2.8 round-1.1 update: α validation rejected the
> simple "Sat = next trading day" hypothesis. The table below now
> applies per the II-a / II-b split, not as a uniform menu.

| Option | Description | Cost | Blast radius | Applies to |
|--------|-------------|-----:|-------------:|------------|
| α. **Read-time relabel** of Saturday rows to the next trading day. Conditional on II-a's "right data, wrong label" sub-hypothesis being confirmed against a vendor-stable oracle. | low | small (only `BarStore` reads) | **II-a only**; cannot fix II-b |
| β. **Rebuild on-disk daily from the 1m pipeline.** | medium-high | high (every daily-derived artifact recomputes) | II-a; II-b only if 1m pipeline data for polygon-sourced symbols is itself reliable, which is now in doubt |
| γ. **Re-fetch from yfinance with explicit `tz_localize('America/New_York')`.** | medium | medium (replaces yfinance-sourced daily) | II-a only; abandons polygon-sourced symbols' history or forces them to switch source |
| δ. **Skip-list Saturday rows at write-time.** Drops real data — **NOT recommended.** | low | low but lossy | n/a |
| ε. **Source-specific II-b investigation + remediation.** Polygon-gz daily appears structurally unreliable for at least DG 2022-08 (post-α-validation finding). Requires a separate scoping pass to determine whether the 8-year polygon-gz window is salvageable, partially salvageable per-symbol, or must be replaced wholesale (yfinance / 1m re-aggregate). | unknown | unknown — could be very large (9 of 24 universe symbols × 8 years) | II-b only |

α / γ are no longer "the cheapest universal patches" — they're
candidates for II-a only, with α further conditional on oracle
validation. β remains the only option that could in principle cover
both classes, but its applicability to II-b depends on whether the
underlying 1m polygon data is consistent with the daily polygon
data (a question that cannot be answered without ε first).

### 2.6 Repair risks

- **α has a hidden assumption**: every Saturday row maps to "the
  next valid trading day". The MSFT 2024-09-07 (Sat) → 2024-09-09
  (Mon) sample matches; but if any Saturday row actually represents
  Friday or Tuesday data due to upstream nuances we haven't seen,
  α relabels them wrong. Low-probability based on the AAPL 2022
  scan, but the assumption needs a broader audit before α ships.
- **β changes the daily parquet bit-identity for every symbol.**
  Every regression baseline that pins specific close prices needs
  refreshing. The 1m → 1d aggregation also has its own assumptions
  (which trades count as in-day vs after-hours, etc.); a poorly
  done aggregation may introduce a different inconsistency.
- **β touches every paper artifact's reproducibility.** Post-β,
  `tests/unit/paper_trading/test_run_paper_candidate_immediate_rerun.py`
  produces a different deterministic byte-string than pre-β; the
  old paper-runs in `data/paper_runs/` are no longer reproducible
  byte-for-byte. The hash-determinism property still holds within
  any single state of the data, but the underlying data identity
  changed.
- **γ leaves the polygon-sourced symbols (DG, ED, GILD, GIS, LRCX,
  MU, TJX, TSN, VICI) un-fixed.** Either we apply γ universally
  (also re-fetching those from yfinance, abandoning polygon) or we
  combine γ with β only for the polygon segments.
- **All options change every existing memo's claim about specific
  dates.** Phrases like "2022-10-17 NaN day" or "2022-10-03 NVDA
  missing" reference BarStore-label dates; post-fix those labels
  shift. The label/date references in the M14 memo §1, the
  cand2_drift_attribution memo §2, the TD75 memo §0/§1, and the
  M11 memo §5 will all need a one-line caveat or refresh.

### 2.7 Downstream re-run obligations

If sub-issue II is fixed (α / β / γ):

- `data/baseline/latest.json` — refresh.
- 4 paper drift cells — re-run; verify drift remains zero on the
  relabeled / rebuilt panel. Fill counts and final NAVs WILL change
  (different rebalance dates).
- TD75 §0b numbers — refresh.
- M14 memo §1 NaN-equity day pattern (Mondays vs Saturdays) — the
  pattern reading depends on which days were "missing"; post-fix
  the missing days move (or disappear, if α's relabel + the M14
  fallback together cover the prior Mondays). Re-document.
- Cand2 drift attribution memo §2.2 "next-day-after-NaN" date list
  — if the underlying NaN days move, the date list moves with them.
  Re-document.
- M11 memo §5 — retract again if α / β / γ removes the
  "misdated Monday-as-Saturday" finding. The §5 caveat that 2022
  date references are BarStore labels becomes obsolete.
- All hand-coded date references in PRDs, decision memos, and
  readmes need a sweep against the post-fix calendar; non-trivial.

### 2.8 Round-1.1 update — α simple-relabel rejected; II must split

**Date appended**: 2026-04-25 (same day as round-1; addendum
reflects α validation results that postdate §2.5's framing.)

α validation was run as the first step under the §3 recommended
order. 170 samples × 10 symbols × 3 provenance sources × 9 years
were drawn from BarStore Saturday rows; for each, the predicted
"next valid trading day" (after `CustomBusinessDay` with
`USFederalHolidayCalendar`) was pulled fresh from yfinance and
compared on volume (split-neutral fingerprint) + close (raw +
adjusted).

**Result: α simple-relabel hypothesis is rejected.**

| Metric | Result |
|--------|-------:|
| Volume match (1% tolerance) | **3 / 170** |
| Volume mismatch | 167 / 170 |
| Close match (raw, 1% tolerance) | 113 / 170 |
| Close match (adjusted, 1% tolerance) | 29 / 170 |

Close-raw matches at ~66% but volume mismatches dominate, and the
two never co-occur cleanly. This is incompatible with "Saturday row
holds a single calendar day's complete OHLCV under a wrong label".

A drill-down on individual rows surfaced a structural finding that
forces a sub-issue II split:

#### II-a (yfinance_daily symbols) — Mon → Sat replacement

For mega-cap stocks + ETFs sourced from yfinance_daily (AAPL, MSFT,
NVDA, TSLA, AMZN, META, GOOGL, SPY, QQQ, SOXL, TQQQ, MTUM, QUAL,
SLV, XLRE, ED-via-yfinance ones), the panel's Mondays are missing
and the preceding Saturdays carry data. Per-row OHLCV is consistent
in shape with a real trading day, but volume drift vs current
yfinance pulls suggests the data is from an older pull whose volume
has since been revised (split-volume cascade or vendor revision).
The Mon → Sat replacement structure is consistent with
the original §2.4 H-2a (TZ-floor) hypothesis.

α-style read-time relabel **could** in principle work for this
class IF we accept "BarStore has the right OHLCV but the wrong date
label" — the relabel just shifts the index and leaves OHLCV alone.
The 30-65% volume mismatch vs current yfinance is then explained by
yfinance revising volumes over time, NOT by the BarStore data being
wrong-day. This is plausible but unverified; needs a vendor-stable
oracle (e.g. polygon flat files) to confirm.

#### II-b (polygon_gz symbols) — extra Saturday "ghost" rows

For mid-cap stocks sourced from polygon_gz (DG, ED, GILD, GIS,
LRCX, MU, TJX, TSN, VICI 2018-2023), **every Monday is present in
BarStore**, AND a Saturday row also exists each week. Saturday
close, open, high, low, volume are all distinct from the adjacent
Friday and Monday — independent values, not duplicates. Adjacent-
day close ratios within these symbols also show ~7% intra-week
swings during 2022-08 (e.g. DG Mon 8-15 close=235.76 → Tue 8-16
close=252.92 → Wed 8-17 close=238.19), which is implausible for a
non-split symbol on calm trading days.

Two distinct problems are entangled here:
- A "ghost Saturday row" of unknown origin (could be intra-week
  trade aggregation, after-hours block, vendor-feed artifact, or
  pure ingest bug)
- An apparent **polygon_gz daily quality issue** that is unrelated
  to date labels — closes themselves bounce in ways the underlying
  symbol's real prices did not (cross-checked vs yfinance for DG
  2022-08: yfinance shows smooth ~$235 to ~$245 trajectory, no 7%
  intra-week swings).

α relabel cannot fix II-b: there's no "wrong label" to correct,
and the Monday data is already there. Whatever II-b actually is,
it needs source-specific investigation — either polygon_gz daily
is an unreliable source (in which case the entire 2015-2023 polygon
segment is suspect, not just the Saturday ghosts), or there's a
per-symbol ingest mode-switch we haven't identified.

#### Implications for §2.5 / §3 / §5

- §2.5 option α: **NOT a universal fix.** At best a partial fix
  for II-a only; needs a vendor-stable oracle to verify II-a's
  "right data, wrong label" assumption first. § 2.5 wording below
  amended; original options β / γ / δ remain on the table.
- §3 recommended order: II validation can no longer be "0.5d ship
  or reject" — it's now "audit II-a vs II-b separately, decide on
  per-source remedies". §3 wording below amended.
- §5 question 1: was "pick α / β / γ"; now "decide II-a remediation
  strategy AND scope II-b as a separate workstream item". §5 wording
  below amended.
- New round-1.5 deliverable required before any II fix execution:
  a separate II-b root-cause memo. polygon_gz is the source for 9
  of 24 universe symbols across 2015-2023 (an 8-year span), and if
  the daily aggregation is structurally unreliable there, the
  decision space for sub-issue I narrows materially (option E
  "rebuild from 1m" is then inapplicable to those years for those
  symbols).
- "24 / 24 universe symbols affected" headline in §2.2 still
  holds, but now reads as a UNION of two distinct mechanisms, not
  a single uniform shift.

#### What's NOT changed

- Sub-issue I scope, hypotheses, options, risks, and re-run
  obligations (§1.x) are unaffected by this addendum.
- Frozen list (§4) is unchanged.
- Mining-lineage quarantine decision (§5 q4) is unchanged.

---

## 3. Independence and order between sub-issues

Sub-issues I (split adjustment) and II (date label) are independent
in cause and in repair path. But repair order matters:

- **If we fix II first (date labels)**, the post-fix universe still
  contains the split-adjustment alternation in TSLA / GOOGL / TJX.
  Paper runs over windows where those symbols carry weight will
  still hit spurious 100s-of-bps moves. The 2022-H2 + 2024 cells
  remain clean (sub-issue I scan said so) so the 4 canonical drift
  cells are not affected, but any expansion to 2018-2022 windows
  is blocked.
- **If we fix I first (split adjustment)**, the post-fix daily
  parquet still has Saturday rows for every Monday. Paper-vs-
  replay parity remains (M11 already proved that). External-
  calendar references remain ambiguous.
- **Fixing I before II is preferred** because the split-adjustment
  hazard produces *NAV-level* spurious returns (factor IR moves,
  paper NAV moves, mining ranking moves). The date-label hazard is
  primarily an *external-calendar* concern — internal comparisons
  (M11-style parity, drift, replay determinism) are unaffected.
- ~~However, II's option α is the cheapest patch by far~~
  **Superseded by §2.8: α failed validation. There is no longer a
  single cheap universal patch for II.** II now bifurcates into
  II-a (yfinance Mon→Sat replacement) and II-b (polygon-gz extra
  ghost rows + apparent daily-aggregation quality issue), each
  requiring its own remedy.

Recommended **per-issue priority** for next round
(amended after §2.8):

1. **First**: I hypothesis verification (read-only diffs against
   yfinance + splits.parquet). 1-2 days. Picks among A / B / C / D / E.
   Promoted to first because II's quick-α path is gone, AND I's
   NAV-level hazard is the bigger semantic risk.
2. **Second**: II-a oracle validation. Confirm or reject "right
   data, wrong label" by cross-checking BarStore Saturday rows
   against polygon flat files (vendor-stable, contemporaneous to
   the original ingest) for 5-10 symbols × 5 years. Half-day to
   one day. If confirmed, α becomes a viable II-a-only fix.
3. **Third**: II-b scoping. Separate memo. Determine whether
   polygon-gz daily 2015-2023 is structurally unreliable for the
   9 mid-cap universe symbols, and what the path forward looks
   like (re-aggregate from 1m / switch source / accept reduced
   coverage). 1 day for the scoping; remediation cost downstream
   depends on the finding.
4. **Fourth**: chosen sub-issue I fix execution. Cost per §1.5.
5. **Fifth**: chosen II-a + II-b fix execution.
6. **Sixth**: re-run obligations from §1.7 + §2.7 batch.

---

## 4. What stays frozen during this workstream

Per existing direction (continuing through this workstream):

- No universe extension.
- No new mining round.
- No new data tier.
- No Candidate-3 work.
- No retroactive RCMv1 / Cand-2 frozen-spec change.
- No new factor in PRODUCTION_FACTORS.

Plus a new freeze specific to this workstream:

- No paper artifacts archived as "post-data-fix canonical" until at
  least one of {I, II} is shipped AND the §1.7 / §2.7 re-runs
  completed.

---

## 5. Open questions for next-round sign-off

Listing the decisions that this scoping memo deliberately does not
take:

1. **Decide II-a remediation strategy** (among α-conditional / β /
   γ; α is conditional on oracle validation per §2.8, was previously
   the leading low-cost option but is no longer "the universal cheap
   fix"). **Separately, scope II-b** as its own source-specific
   data-quality investigation (option ε in §2.5) — this is now a
   prerequisite to any II-b remediation, not a remediation choice
   itself.
2. Pick I's repair path among A / B / C / D / E.
3. Decide whether to attempt sub-issue I's full clean-up
   (B or E) or to live with C/D for now and revisit later.
4. Decide whether mining-lineage snapshots in `data/mining/*.db`
   are quarantined or refreshed (current default: quarantined as
   historical record, not refreshed).
5. Decide whether the post-data-fix re-runs blanket-refresh all
   memos (heavy) or only the headline ones (TD75 §0b, M11 §5,
   M14 §1, Cand2 attribution §2.2).
6. Whether to add any test that actively guards against either
   sub-issue regressing in the future:
   - A "no Saturday rows in BarStore.load(symbol, '1d')" assertion
     (cheap, tight, but locks α / β / γ into having shipped).
   - A "no adjacent-day ratio > 2.0 outside known split dates"
     assertion (more nuanced, requires a known-splits whitelist).

---

## 6. Status & artifacts

- This memo is the round-1 deliverable.
- No code changes in this round.
- No new tests in this round.
- No commit yet (this commit will be scoping-memo-only, gated on
  user sign-off on §5).
- pytest baseline unchanged: 1577 passed / 0 failed / 1 skipped /
  1 xfailed (from M11 close).

Cross-references:
- `docs/20260424-data_integrity_2022_split_adjustment.md` (older
  pre-M11 finding on TSLA/GOOGL/2020/2022-Q1 split contamination)
- `docs/memos/20260424-m11_paper_engine_parity_fix.md` §5 (Saturday-
  row finding parking lot)
- `docs/memos/20260424-m14_nan_equity_fix.md` §5 (NaN-day pattern
  documented in BarStore-label terms; supersedes the §5.1
  "Saturday is pad" claim per M11 §5.1 retraction)
- `docs/20260424-parallel_paper_2022h2_checkpoint_75d.md` §0b
  (post-M11 canonical baselines; survives this workstream pending
  re-runs)
