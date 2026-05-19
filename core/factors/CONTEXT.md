<!-- PQS module CONTEXT.md — 由 CLAUDE.md 2026-05-19 reorg 拆出。
CLAUDE.md = context 入口,仅留项目级(不变量/纪律/架构/概括)。
本文件 = 本模块的历史/契约细节(content-preserving 搬迁,无删改)。
回指: ../../CLAUDE.md ; 索引见 CLAUDE.md 末「Module CONTEXT.md 索引」。 -->

# core/factors/CONTEXT.md — module history / contract detail


## [Factor Pipeline Contract]

### Factor Pipeline Contract

Single source of truth: `core/factors/factor_registry.py`. Two
registries with strict **directional** separation (production drives
execution; research is read-only at the execution boundary):
- `PRODUCTION_FACTORS` (7): only these drive execution; changes
  require user authorization
- `RESEARCH_FACTORS` (143 as of PRD 20260512 Bucket A/B/C/Macro
  expansion; up from 64 baseline): available for IC / OOS / regime
  research; may share a NAME with a production factor (e.g.
  `drawup_from_252d_low`) so long as the two implementations are
  numerically identical — see `factor_registry.py:213-220`.
  **Source-path split**: OHLCV factors come from
  `core/factors/factor_generator.generate_all_factors`; fundamental
  / sector / macro factors come from separate `compute_*` functions
  (different input signatures — EDGAR cache / sector_map / FRED).
  `scripts/run_research_miner.py::_build_factor_panel_map` merges
  all four paths.

`MultiFactorStrategy` gate: unknown names in `factor_weights` are
logged at WARNING and DROPPED — prevents research names silently
reaching execution. `MultiFactorSpace._TUNED_FACTORS` asserts
consistency at miner startup.

Promotion flow (manual, one-way): RESEARCH → PRODUCTION requires
registry addition + `MultiFactorStrategy.generate()` inline impl +
`_TUNED_FACTORS` update + passing full acceptance. Full promotion
steps + shadowed-research map archived in
`docs/20260424-claude_md_phase_e_history.md` §Factor Pipeline Contract.
