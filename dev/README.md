# `dev/` — Dev Process (separate from the quant product)

This directory holds everything that is about **how the codebase is
built and maintained**, keeping it separate from the **quant
substance** (strategies, factors, backtests, candidates, paper runs).

## Split rule

| If a script's main output is ... | Home |
|---|---|
| A strategy / research / backtest / candidate / validation result | `scripts/` (quant ops) |
| Dev process / migration / notification / loop orchestration / demo | `dev/scripts/` |

Same rule for docs:

| If a doc is about ... | Home |
|---|---|
| Quant research, a candidate memo, a factor finding, a synthesis | `docs/` |
| Code architecture, ralph-loop plans, code audits, migration PRDs, LLM-handoff templates | `dev/docs/` |

## Layout

```
dev/
  docs/                    dev PRDs (architecture, loop execution plans,
                           code audits, path conventions, LLM templates)
  scripts/
    loop/                  ralph-loop launchers (start_*_loop.sh)
    migrations/            one-time data migrations
    baseline/              baseline snapshot builder
    notify/                wecom bot sender
    llm_handoff/           LLM context dump for external handoff
    demo/                  tutorials / examples
    ops/                   ops guardrails (disk_guard, etc.)
  artifacts/               gitignored (baseline snapshots, etc.)
```

## Full rule reference

`docs/20260424-path_naming_conventions_proposal.md` §2.3 ("Hard split:
quant substance vs dev process").
