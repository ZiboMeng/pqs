# Master report per-ticker provenance display — deferred until consumer arrives

**Status**: DEFERRED (resident-quant decision 2026-05-02). Builder
infrastructure (`BarStore.attrs["provenance"]` + sidecar
`data/ref/bar_provenance.parquet`) is SHIPPED and operational. Display
layer in `core/reporting/master_report.py` is NOT shipped.

**Authority**: priority realign memo `docs/memos/20260430-priority_realign_alpha_first.md`
("pre-emptive guard work is over until evidence justifies"). Operator
判断 per `feedback_autonomous_execution_within_correct_path.md`.

---

## Why deferred (not "todo eventually")

1. **0 immediate consumer**:
   - Trial 9 forward = 100% yfinance frontier (only post-canonical
     symbols; provenance row per ticker = single `yfinance_daily`
     entry). Display value = 78 identical rows. Zero information.
   - RCMv1 + Cand-2 = aborted; not regenerating master reports.
   - Cycle #06+ candidate (when it arrives) MAY mix polygon canonical
     + trades_backfill + yfinance_fallback if universe expands beyond
     post-canonical-cutoff symbols. THAT is when provenance display
     gains audit value.

2. **Risk of changing master_report shape now**:
   - 8 existing setters (backtest / rolling_windows / factors /
     universe / paper_trading / regime / attribution / reconciliation)
     are consumed by downstream notebooks + scripts that may not be
     covered by `tests/`. Adding `set_bar_provenance(...)` + new section
     is non-breaking ADDITIVE but still a schema change to MasterReport
     output JSON / markdown.
   - Forward soak window (~90 days) = NOT the time to change reporting
     surfaces that touch the candidates being observed.

3. **Resident-quant principle**: "Don't add features beyond what the
   task requires" (CLAUDE.md system prompt §Doing tasks). Wiring with
   no consumer = dead code that decays before consumer arrives, then
   needs re-validation anyway.

---

## Activation triggers (clear path to un-defer)

Implement when ANY of:

- **Trigger A**: a Track C cycle (#06+) produces a candidate that
  passes Track A acceptance AND its universe contains ≥ 1 symbol with
  multi-source provenance (e.g. polygon_gz + yfinance_fallback for ETF
  gap fill, or trades_backfill for pre-2024 ETF history). Provenance
  display becomes audit-relevant for evidence pack.

- **Trigger B**: external auditor / reviewer (codex round, user
  request) explicitly asks for per-ticker data-epoch attribution in
  master report or evidence pack output.

- **Trigger C**: forward observation surfaces a data-epoch-correlated
  performance anomaly (e.g. trial 9 forward NAV diverges sharply on
  yfinance-only symbols vs polygon-canonical symbols), and the
  diagnostic needs a per-ticker provenance breakdown.

Until ANY of A/B/C, the feature stays deferred.

---

## Implementation sketch (when triggered)

~ 2 hours total work:

1. **Builder side** (~30 min):
   ```python
   # core/reporting/master_report_builder.py
   def set_bar_provenance(
       self,
       provenance_table: pd.DataFrame,
       *,
       universe: list[str] | None = None,
   ) -> "MasterReportBuilder":
       """Attach per-ticker bar provenance contribution.

       provenance_table columns:
         symbol, source, first_date, last_date, n_bars, share_pct
       (one row per (symbol, source) pair; share_pct sums to 100% per
       symbol over its sources).

       Built from BarStore.attrs["provenance"] aggregated across the
       backtest universe, OR from data/ref/bar_provenance.parquet
       directly via core.data.bar_store.read_provenance_sidecar().
       """
       self._bar_provenance_table = provenance_table
       self._bar_provenance_universe = universe
       return self
   ```

2. **MasterReport schema** (~15 min):
   - Add `bar_provenance: Optional[BarProvenanceSection]` field to
     `MasterReport`
   - `BarProvenanceSection` = pydantic model with
     `per_ticker_table: list[ProvenanceRow]` + `universe: list[str]` +
     `mixed_source_symbols: list[str]` (symbols with > 1 source)

3. **Renderer** (~30 min):
   - Add markdown section to `master_report.py.render_markdown()`:
     ```
     ## Bar provenance contribution
     | symbol | source           | first_date | last_date | n_bars | share |
     |--------|------------------|------------|-----------|--------|-------|
     | AAPL   | polygon_gz       | 2015-01-02 | 2024-12-31 | 2515 |  82%  |
     | AAPL   | yfinance_daily   | 2025-01-02 | 2026-04-30 |  338 |  11%  |
     | ...    | ...              | ...        | ...       | ...    | ...   |
     ```
   - Highlight mixed-source symbols (≥ 2 sources) in a separate
     callout for audit attention.

4. **Tests** (~30 min):
   - `test_bar_provenance_section_single_source_per_ticker_table`
   - `test_bar_provenance_section_mixed_source_symbols_callout`
   - `test_bar_provenance_section_empty_provenance_graceful`
   - `test_bar_provenance_renderer_markdown_section_format`

5. **Caller wiring** (~15 min):
   - `scripts/generate_report.py` (or wherever master report is built
     from real data) calls `builder.set_bar_provenance(prov_table)`
     after `set_universe(...)`.

Total: ~2 hours. Not currently authorized — wait for trigger.

---

## Closeout

- BarStore.provenance sidecar API: SHIPPED (verified 2026-05-02 via
  `core/data/bar_store.py:201,245,278,298,314` grep)
- Display layer: NOT shipped, NOT implementing this round
- Memo authored 2026-05-02 to preserve trigger criteria + impl sketch
- CLAUDE.md older TODO entry updated from "[ ]" → deferred-with-memo-link
