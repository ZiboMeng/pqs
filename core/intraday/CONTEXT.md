<!-- PQS module CONTEXT.md — 由 CLAUDE.md 2026-05-19 reorg 拆出。
CLAUDE.md = context 入口,仅留项目级(不变量/纪律/架构/概括)。
本文件 = 本模块的历史/契约细节(content-preserving 搬迁,无删改)。
回指: ../../CLAUDE.md ; 索引见 CLAUDE.md 末「Module CONTEXT.md 索引」。 -->

# core/intraday/CONTEXT.md — module history / contract detail


## [Multi-TF Timing Contract (实现细节;框架本身留 CLAUDE.md Phase D)]

### Multi-TF Timing Contract

Multi-timescale framework is a **timing / execution / risk layer** on
top of daily MFS, NOT a standalone alpha system (naive bar-direction
voting strictly underperformed 60m-only baseline).

Role by TF: 60m = primary context (can VETO to scale=0); 30m =
confirmation / confidence penalty; 15m / 5m = defer trigger only,
never flip direction (long-only).

Canonical API: `core.intraday.multi_timescale.decide_timing(ctx,
symbol, base_weight, daily_side) -> TimingDecision` with fields
`{execute, timing_scale, effective_weight, higher_tf_vote, reason}`.
Invariants enforced by `tests/unit/intraday/test_timing_decision.py`.

Legacy `evaluate_cross_tf_signal` / `CrossTFSignal` shim kept for
back-compat. Full role table + validation evidence +
`validate_timing_value.py` results archived in
`docs/20260424-claude_md_phase_e_history.md` §Multi-TF Timing Contract.
